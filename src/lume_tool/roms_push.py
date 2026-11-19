"""`lume dev roms push [DIR]`: copy a test set of games to the card of the console on the
cable (game-experience-tuning D10, spec device-testing).

DIR (default `var/roms_test/` of the main repository) is laid out like the ROMS partition:
`roms/<system>/` (games, `gamelist.xml`, `images/`) and `bios/`. Every file maps to the same
relative path under /storage on the console.

- Missing: a file whose path does not exist on the card is copied. A path that exists is
  never touched: same size counts as `kept`, another size (or not a regular file) as `kept`
  and `differ` (a conflict, reported, never overwritten). Nothing is ever deleted.
- Transfer: `rsync --ignore-existing` through the ssh of `lume push` when the console has
  `rsync` (D9) and the PC too; otherwise a tar stream made here (no archive on the PC) into
  `tar -x` on the console.
- Verify: the SHA256 of every copied file, read on the console after `sync` (and a page
  cache drop), against the PC. A file that differs is copied again once (tar, overwriting
  only that file of this run); if it still differs, the command fails.
- gamelist.xml: the card's list keeps every byte of its own entries; the PC `<game>`
  elements whose `<path>` is not in it are inserted before `</gameList>`, matched by the
  same normalized path as the on-console game index (lume-index `gamelist::normalize`).
  No list on the card: the PC's is written. The write is atomic (temp file checked by
  SHA256, then `mv` only if the card's list did not change meanwhile, then `sync`). A list
  on the card that does not parse is left as it is and fails the command.
- Output: counts per system only. No game name, file name or ROM path is ever printed,
  including in errors (exceptions are reduced to a fixed text).
"""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import xml.parsers.expat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable

CARD_ROOT = "/storage"
GAMELIST = "gamelist.xml"
BIOS_GROUP = "bios"
GAME_UID = 1000                  # owner of /storage/roms (selftest roms-owner)
FREE_MARGIN = 16 << 20           # bytes kept free on ROMS beyond what the copy needs


class RomsPushError(RuntimeError):
    """An error whose message never carries a game name or a ROM path."""


# --- remote scripts ----------------------------------------------------------------------
# Paths travel on stdin, one per line (never on the command line or in the output).

def stat_script(root: str) -> str:
    """One line per path read on stdin: its size, `other` (exists, not a file) or `-`."""
    q = shlex.quote(root)
    return (f'while IFS= read -r p; do f={q}/"$p"; '
            'if [ -f "$f" ]; then stat -c %s "$f"; '
            'elif [ -e "$f" ] || [ -L "$f" ]; then echo other; else echo -; fi; done')


def hash_script(root: str) -> str:
    """After a sync and a page-cache drop (so the card is read, not the RAM): one SHA256 per
    path read on stdin, `-` when the file is missing."""
    q = shlex.quote(root)
    return ('sync; { echo 1 > /proc/sys/vm/drop_caches; } 2>/dev/null; '
            f'while IFS= read -r p; do f={q}/"$p"; '
            'if [ -f "$f" ]; then sha256sum < "$f" | cut -c1-64; else echo -; fi; done')


def free_script(root: str) -> str:
    return f"df -Pk {shlex.quote(root)} | tail -n 1"


HAS_RSYNC = "if command -v rsync >/dev/null 2>&1; then echo yes; else echo no; fi"


def tar_extract_script(root: str) -> str:
    q = shlex.quote(root)
    return f"mkdir -p {q} && tar -xf - -C {q}"


def read_list_script(path: str) -> str:
    """`Y` + the file, or `N` when there is none."""
    q = shlex.quote(path)
    return f"if [ -f {q} ]; then printf Y; cat {q}; else printf N; fi"


def write_list_script(system_dir: str, new_sha: str, old_sha: str | None) -> str:
    """Write stdin as <system_dir>/gamelist.xml: temp file, its SHA256 checked, then `mv`
    only if the current list is still the one merged (`none`: no list); prints ok, badcopy
    or changed."""
    d = shlex.quote(system_dir)
    return (f'd={d}; f="$d/{GAMELIST}"; t="$d/.{GAMELIST}.lume-push"; '
            'mkdir -p "$d"; cat > "$t"; '
            'got=$(sha256sum < "$t" | cut -c1-64); '
            f'if [ "$got" != {new_sha} ]; then rm -f "$t"; echo badcopy; exit 0; fi; '
            'if [ -f "$f" ]; then cur=$(sha256sum < "$f" | cut -c1-64); else cur=none; fi; '
            f'if [ "$cur" != {old_sha or "none"} ]; then rm -f "$t"; echo changed; exit 0; fi; '
            'mv -f "$t" "$f"; sync; echo ok')


# --- links to the card -------------------------------------------------------------------

def stream_tar(argv: list[str], src_root: Path, rels: Iterable[str]) -> int:
    """Run `argv` (a `tar -x` on the console) with a tar of `rels` (relative to src_root)
    written to its stdin as it is made. Output is dropped: it would name files."""
    p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    try:
        with tarfile.open(fileobj=p.stdin, mode="w|", format=tarfile.GNU_FORMAT) as tar:
            for rel in rels:
                src = src_root / rel
                info = tar.gettarinfo(str(src), arcname=rel)
                info.uid = info.gid = GAME_UID
                info.uname = info.gname = ""
                info.mode = 0o644
                with src.open("rb") as f:
                    tar.addfile(info, f)
    except (BrokenPipeError, ConnectionResetError):
        pass                    # the far end stopped; the verification sees what is missing
    finally:
        try:
            p.stdin.close()
        except (BrokenPipeError, OSError):
            pass
    return p.wait()


class SshLink:
    """The card of the console on the cable, through the ssh of `lume push`."""

    def __init__(self, host: str, root: str = CARD_ROOT):
        from lume_tool.push import Remote

        self.remote = Remote(host)
        self.base = self.remote.base
        self.root = root

    def run(self, script: str, data: bytes = b"") -> tuple[int, bytes]:
        r = subprocess.run([*self.base, script], input=data, capture_output=True)
        if r.returncode == 255:
            raise RomsPushError("ssh to the console failed (is it on, with the cable on its "
                                "OTG port?)")
        return r.returncode, r.stdout

    def copy_tar(self, src_root: Path, rels: list[str]) -> int:
        rc = stream_tar([*self.base, tar_extract_script(self.root)], src_root, rels)
        if rc == 255:
            raise RomsPushError("ssh to the console failed during the copy")
        return rc

    def copy_rsync(self, src_root: Path, rels: list[str]) -> int:
        # -t keeps the times, -O not on folders (exFAT); no -p/-o/-g: the card's owner stays
        argv = ["rsync", "-t", "-O", "--ignore-existing", "--from0", "--files-from=-",
                "-e", shlex.join(self.base[:-1]), f"{src_root}/",
                f"{self.base[-1]}:{self.root}/"]
        data = b"".join(os.fsencode(r) + b"\0" for r in rels)
        return subprocess.run(argv, input=data, stdout=subprocess.DEVNULL,
                              stderr=subprocess.DEVNULL).returncode

    def refresh_index(self) -> None:
        """Ask the game index to scan again (as when the PC lets go of the card)."""
        self.run("rc-service lume-index restart >/dev/null 2>&1; true")


# --- the PC side -------------------------------------------------------------------------

@dataclass
class Source:
    root: Path
    groups: dict[str, list[str]] = field(default_factory=dict)   # group -> relative paths
    lists: dict[str, Path] = field(default_factory=dict)         # system -> gamelist.xml
    bad_names: dict[str, int] = field(default_factory=dict)      # group -> unusable names


def _walk(base: Path, rel_prefix: str, group: str, src: Source, skip_top: set[str]) -> None:
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if not d.startswith("."))
        here = Path(dirpath)
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            if here == base and name in skip_top:
                continue
            p = here / name
            if not p.is_file():
                continue
            rel = f"{rel_prefix}/{p.relative_to(base).as_posix()}"
            if "\n" in rel or "\r" in rel:
                src.bad_names[group] = src.bad_names.get(group, 0) + 1
                continue
            src.groups.setdefault(group, []).append(rel)


def scan_source(root: Path) -> Source:
    src = Source(root)
    roms = root / "roms"
    if roms.is_dir():
        for sysdir in sorted(p for p in roms.iterdir() if p.is_dir()
                             and not p.name.startswith(".")):
            if (sysdir / GAMELIST).is_file():
                src.lists[sysdir.name] = sysdir / GAMELIST
            src.groups.setdefault(sysdir.name, [])
            _walk(sysdir, f"roms/{sysdir.name}", sysdir.name, src, {GAMELIST})
    bios = root / "bios"
    if bios.is_dir():
        src.groups.setdefault(BIOS_GROUP, [])
        _walk(bios, "bios", BIOS_GROUP, src, set())
    return src


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --- gamelist.xml ------------------------------------------------------------------------

def normalize(path: str, system_dir: str) -> str:
    """The key of a game, as lume-index `gamelist::normalize`: relative to the system folder,
    without `./`, `..` resolved, `/` separators; another absolute path is kept."""
    p = path.strip()
    rel = p[len(system_dir):].lstrip("/") if system_dir and p.startswith(system_dir) else p
    parts: list[str] = []
    for part in rel.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
            continue
        parts.append(part)
    joined = "/".join(parts)
    return "/" + joined if rel.startswith("/") else joined


@dataclass
class GameList:
    data: bytes
    games: list[tuple[str, bytes]]          # (normalized path, raw <game> element)
    close: int                              # offset of </gameList> (or of <gameList/>)
    empty_root: tuple[int, int] | None      # span of <gameList/>


class ListError(ValueError):
    pass


def _tag_end(data: bytes, at: int) -> int:
    end = data.find(b">", at)
    if end < 0:
        raise ListError("unterminated tag")
    return end + 1


def parse_gamelist(data: bytes, system_dir: str) -> GameList:
    """The <game> elements of a gamelist.xml with their byte spans (nothing reformatted)."""
    parser = xml.parsers.expat.ParserCreate()
    state = {"depth": 0, "root": False, "close": None, "empty": None, "game": None,
             "in_path": False, "path": None}
    games: list[tuple[str, bytes]] = []

    starts: list[int] = []

    def start(name, attrs):
        state["depth"] += 1
        d = state["depth"]
        at = parser.CurrentByteIndex
        starts.append(at)
        if d == 1:
            if name != "gameList":
                raise ListError("root element is not gameList")
            state["root"] = True
        elif d == 2 and name == "game":
            state["game"] = at
            state["path"] = None
        elif d == 3 and state["game"] is not None and name == "path" \
                and state["path"] is None:      # the first <path>, as lume-index
            state["path"] = ""
            state["in_path"] = True

    def chars(text):
        if state["in_path"] and state["depth"] == 3:
            state["path"] += text

    def end(name):
        d = state["depth"]
        at = parser.CurrentByteIndex
        began = starts.pop()
        # an empty element `<x/>` ends at its first `>`; else the end tag `</x>` is at `at`
        first = _tag_end(data, began)
        closing = data[first - 2:first - 1] != b"/"
        stop = _tag_end(data, at) if closing else first
        if d == 3:
            state["in_path"] = False
        elif d == 2 and name == "game" and state["game"] is not None:
            key = normalize(state["path"] or "", system_dir)
            games.append((key, data[began:stop]))
            state["game"] = None
        elif d == 1:
            if closing:
                state["close"] = at
            else:
                state["empty"] = (began, stop)
                state["close"] = began
        state["depth"] -= 1

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.CharacterDataHandler = chars
    parser.buffer_text = True
    try:
        parser.Parse(data, True)
    except xml.parsers.expat.ExpatError as e:
        raise ListError(f"not valid XML (line {e.lineno})") from None
    if not state["root"] or state["close"] is None:
        raise ListError("no closed gameList element")
    return GameList(data, games, state["close"], state["empty"])


def merge_lists(card: GameList | None, pc: GameList) -> tuple[bytes | None, int]:
    """(new text of the card's list or None when nothing changes, entries added)."""
    if card is None:
        return pc.data, len(pc.games)
    have = {k for k, _ in card.games}
    new: list[bytes] = []
    for key, raw in pc.games:
        if not key or key in have:
            continue
        have.add(key)
        new.append(raw)
    if not new:
        return None, 0
    block = b"".join(b"\t" + raw + b"\n" for raw in new)
    data = card.data
    if card.empty_root:
        s, e = card.empty_root
        return data[:s] + b"<gameList>\n" + block + b"</gameList>" + data[e:], len(new)
    head = data[:card.close]
    if not head.endswith(b"\n"):
        head += b"\n"
    return head + block + data[card.close:], len(new)


# --- the push ----------------------------------------------------------------------------

@dataclass
class GroupResult:
    files: int = 0
    copied: int = 0
    verified: int = 0
    recopied: int = 0
    failed: int = 0
    kept: int = 0
    differ: int = 0
    bad_names: int = 0
    gamelist: str = "-"         # "+N", "-", or an error word
    list_error: bool = False


def _lines(out: bytes, n: int) -> list[str]:
    lines = out.decode(errors="replace").splitlines()
    if len(lines) != n:
        raise RomsPushError(f"the console answered {len(lines)} lines for {n} files")
    return [ln.strip() for ln in lines]


def _paths_stdin(rels: list[str]) -> bytes:
    return b"".join(os.fsencode(r) + b"\n" for r in rels)


def _card_hashes(link, rels: list[str]) -> list[str]:
    if not rels:
        return []
    rc, out = link.run(hash_script(link.root), _paths_stdin(rels))
    if rc != 0:
        raise RomsPushError(f"reading the SHA256 on the console failed ({rc})")
    return _lines(out, len(rels))


def _free_bytes(link) -> int | None:
    rc, out = link.run(free_script(link.root))
    fields = out.decode(errors="replace").split()
    if rc != 0 or len(fields) < 4 or not fields[3].isdigit():
        return None
    return int(fields[3]) * 1024


def choose_method(link, method: str) -> str:
    if method in ("rsync", "tar"):
        return method
    if shutil.which("rsync") is None:
        return "tar"
    rc, out = link.run(HAS_RSYNC)
    return "rsync" if rc == 0 and out.decode(errors="replace").strip() == "yes" else "tar"


def _merge_system(link, system: str, pc_path: Path, src_root: Path) -> tuple[str, bool]:
    """Merge one system's list; (gamelist column, error)."""
    try:
        pc = parse_gamelist(pc_path.read_bytes(), str(src_root / "roms" / system))
    except (ListError, OSError):
        return "pc-unreadable", True
    system_dir = f"{link.root}/roms/{system}"
    for _ in range(2):          # a second round when the card's list changed meanwhile
        rc, out = link.run(read_list_script(f"{system_dir}/{GAMELIST}"))
        if rc != 0 or out[:1] not in (b"Y", b"N"):
            raise RomsPushError(f"{system}: reading the card's list failed")
        card = None
        old_sha = None
        if out[:1] == b"Y":
            try:
                card = parse_gamelist(out[1:], system_dir)
            except ListError:
                return "unreadable", True
            old_sha = hashlib.sha256(out[1:]).hexdigest()
        text, added = merge_lists(card, pc)
        if text is None:
            return "+0", False
        answer = _write_list(link, system_dir, text, old_sha)
        if answer == "ok":
            return f"+{added}", False
        if answer != "changed":
            return "write-failed", True
    return "busy", True


def _write_list(link, system_dir: str, text: bytes, old_sha: str | None) -> str:
    """ok, changed, or the last answer after a second try of a bad copy."""
    new_sha = hashlib.sha256(text).hexdigest()
    answer = ""
    for _ in range(2):
        rc, ans = link.run(write_list_script(system_dir, new_sha, old_sha), text)
        answer = ans.decode(errors="replace").strip() if rc == 0 else f"exit {rc}"
        if answer != "badcopy":
            break
    return answer


def push_roms(src_root: Path, link, method: str = "auto", out=print,
              refresh: bool = True) -> int:
    """Copy the set at src_root to the card behind `link`; print counts per system only."""
    if not (src_root / "roms").is_dir() and not (src_root / "bios").is_dir():
        raise RomsPushError("the folder has neither roms/ nor bios/")
    src = scan_source(src_root)
    results = {g: GroupResult() for g in src.groups}
    for g, n in src.bad_names.items():
        results.setdefault(g, GroupResult()).bad_names = n
    rels = [r for g in src.groups for r in src.groups[g]]
    group_of = {r: g for g in src.groups for r in src.groups[g]}

    missing: list[str] = []
    if rels:
        rc, ans = link.run(stat_script(link.root), _paths_stdin(rels))
        if rc != 0:
            raise RomsPushError(f"listing the card failed ({rc})")
        for rel, state in zip(rels, _lines(ans, len(rels))):
            res = results[group_of[rel]]
            res.files += 1
            if state == "-":
                missing.append(rel)
            elif state.isdigit() and int(state) == (src_root / rel).stat().st_size:
                res.kept += 1
            else:
                res.kept += 1
                res.differ += 1

    method = choose_method(link, method) if missing else "none"
    if missing:
        need = sum((src_root / r).stat().st_size for r in missing)
        free = _free_bytes(link)
        if free is not None and free < need + FREE_MARGIN:
            raise RomsPushError(f"ROMS has {free >> 20} MiB free, the copy needs "
                                f"{(need + FREE_MARGIN) >> 20} MiB")
        if method == "rsync":
            link.copy_rsync(src_root, missing)
        else:
            link.copy_tar(src_root, missing)
        pc_sums = {r: sha256_file(src_root / r) for r in missing}
        bad = [r for r, h in zip(missing, _card_hashes(link, missing)) if h != pc_sums[r]]
        if bad:
            link.copy_tar(src_root, bad)            # once, overwriting only these files
            still = {r for r, h in zip(bad, _card_hashes(link, bad)) if h != pc_sums[r]}
        else:
            still = set()
        bad_set = set(bad)
        for r in missing:
            res = results[group_of[r]]
            res.copied += 1
            if r in still:
                res.failed += 1
            else:
                res.verified += 1
                if r in bad_set:
                    res.recopied += 1

    for system, path in src.lists.items():
        res = results.setdefault(system, GroupResult())
        if res.failed:
            res.gamelist = "skipped"
            continue
        res.gamelist, res.list_error = _merge_system(link, system, path, src_root)

    changed = any(r.copied for r in results.values()) or any(
        r.gamelist.startswith("+") and r.gamelist != "+0" for r in results.values())
    if changed and refresh:
        link.refresh_index()

    transfer = {"rsync": "rsync over ssh", "tar": "tar over ssh",
                "none": "nothing to copy"}[method]
    out(f"transfer: {transfer}")
    out(f"{'system':<14}{'files':>7}{'copied':>8}{'verified':>10}{'recopied':>10}"
        f"{'kept':>7}{'differ':>8}  gamelist")
    tot = GroupResult()
    for g in sorted(results):
        r = results[g]
        out(f"{g:<14}{r.files:>7}{r.copied:>8}{r.verified:>10}{r.recopied:>10}"
            f"{r.kept:>7}{r.differ:>8}  {r.gamelist}")
        for name in ("files", "copied", "verified", "recopied", "kept", "differ", "failed",
                     "bad_names"):
            setattr(tot, name, getattr(tot, name) + getattr(r, name))
    out(f"{'total':<14}{tot.files:>7}{tot.copied:>8}{tot.verified:>10}{tot.recopied:>10}"
        f"{tot.kept:>7}{tot.differ:>8}")
    errors = []
    if tot.failed:
        errors.append(f"{tot.failed} copied file(s) still differ from the PC after a second "
                      "copy")
    if tot.bad_names:
        errors.append(f"{tot.bad_names} file(s) with a line break in the name were not copied")
    lists = [g for g, r in results.items() if r.list_error]
    if lists:
        errors.append(f"game list not merged in {len(lists)} system(s): "
                      f"{', '.join(sorted(lists))} (see the gamelist column)")
    for e in errors:
        print(f"error: {e}", file=sys.stderr)
    return 1 if errors else 0


def default_dir() -> Path:
    """`var/roms_test/` of the main repository (also from a worktree)."""
    from lume_tool.paths import REPO_ROOT, _main_repo_root

    return _main_repo_root(REPO_ROOT) / "var" / "roms_test"


def cmd_roms_push(host: str, folder: Path | None, method: str = "auto",
                  link_factory: Callable[[str], object] = SshLink) -> int:
    """The CLI entry: never lets a game name or a path reach the terminal, even on a crash."""
    src = folder or default_dir()
    try:
        if not src.is_dir():
            raise RomsPushError("the test set folder does not exist (give DIR or fill "
                                "var/roms_test/)")
        return push_roms(src, link_factory(host), method)
    except RomsPushError as e:
        print(f"error: {e}", file=sys.stderr)
    except OSError as e:
        print(f"error: {e.strerror or 'input/output error'} (file name withheld)",
              file=sys.stderr)
    except Exception as e:        # noqa: BLE001 - a traceback could name a game
        print(f"error: unexpected {type(e).__name__} (details withheld: they may name a "
              "game)", file=sys.stderr)
    return 1
