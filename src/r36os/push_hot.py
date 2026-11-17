"""`r36os push --hot <fragment>`: a fragment live on the running console, in RAM only
(build-speed D11).

The console root is an overlay of read-only lower layers (the SYSTEM image on the card) and a
32 MiB tmpfs upper layer at /rw/upper: whatever is written to / lands in RAM and is gone after
a reboot, when the console is back to the card's set. Steps, all through ssh (push.Remote):

1. ask the console its arch (`uname -m`; one card moves between the GA36 and the R36S), its
   board, whether / is that overlay, and the free space of the RAM layer;
2. take the newest published version of the fragment for that arch from
   out/repo/<arch>/hashes.json (noarch fragments are in every arch repo) and refuse what
   cannot change without a reboot: kernel, modules, device trees, the `base` slot and any
   package that is not a project fragment (`lume-*`, `r36os-*`), and any fragment shipping
   files under /boot or /lib/modules;
3. turn the data part of the .apk into a plain tar on the PC (no .PKGINFO, signatures,
   .lume-content or install scripts: `apk add` is not run on the console, P-14), check it
   fits the RAM layer, send it and extract it with `tar -xf - -C /`;
4. write `push OK hot <fragment> <version>` to events.log with the console's own `event`
   (logs.sh) and flush it to the card;
5. restart the fragment's services that are running: the ones of `_lume_restart="a b"` in its
   APKBUILD when it has the variable, else the init.d scripts it ships. Restarting `frontend`
   restarts the launcher session.

Nothing on the card changes except that events.log line.
"""

from __future__ import annotations

import copy
import io
import shlex
import sys
import tarfile
import tomllib
from dataclasses import dataclass
from pathlib import Path

from r36os import fragments as frag
from r36os import manifests
from r36os.packages import arch_repo_dir, read_repo_hashes
from r36os.paths import REPO_ROOT, cache_dir, ensure_dir
from r36os.push import PushError, Remote

# the fragments that only change with a reboot (normal `r36os push`)
REFUSED = frozenset({"lume-kernel", "lume-modules", "lume-dtbs"})
PREFIXES = ("lume-", "r36os-")
# a fragment with files here belongs to the boot, not to the running system
BOOT_PATHS = ("boot/", "lib/modules/")
SLOTS_MAP = REPO_ROOT / "rootfs" / "slots.toml"     # group -> packages (build-speed D9)
UPPER = "/rw/upper"
BLOCK = 4096                    # tmpfs page: every file takes whole pages
MARGIN = 1 << 20                # left free in the RAM layer after the push
FRONTEND = "frontend"
ARCHES = {"armv7l": "armv7", "armv7": "armv7", "aarch64": "aarch64", "x86_64": "x86_64"}
LIBEXEC = "/usr/libexec/r36os"

_PROBE = f"""
uname -m
b=$(cat /etc/r36os/board 2>/dev/null); echo "${{b:--}}"
if grep -q '^overlay / overlay .*upperdir={UPPER}' /proc/mounts; then echo overlay; else echo none; fi
f=$(df -Pk {UPPER} 2>/dev/null | awk 'NR==2{{print $4}}'); echo "${{f:--}}"
"""


@dataclass
class HotConsole:
    machine: str            # uname -m
    arch: str               # repo arch (armv7, aarch64, x86_64)
    board: str
    overlay: bool           # / is the overlay with its upper layer in RAM at /rw/upper
    ram_free: int           # bytes free in the RAM layer


def read_hot_console(remote) -> HotConsole:
    lines = [ln.strip() for ln in remote.run(_PROBE).splitlines()]
    if len(lines) < 4:
        raise PushError(f"unexpected answer from the console: {lines!r}")
    machine, board, root, free = lines[:4]
    arch = ARCHES.get(machine)
    if arch is None:
        raise PushError(f"the console runs `{machine}`, an arch with no repository "
                        f"(known: {', '.join(sorted(set(ARCHES.values())))})")
    return HotConsole(machine=machine, arch=arch, board=board, overlay=root == "overlay",
                      ram_free=int(free) * 1024 if free.isdigit() else 0)


def base_slot_packages(path: Path | None = None) -> set[str]:
    """The packages of the `base` slot in rootfs/slots.toml (none while the map does not
    exist). Accepts `base = [..]` or `[base] packages = [..]`."""
    path = path or SLOTS_MAP
    if not path.exists():
        return set()
    try:
        doc = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as e:
        raise PushError(f"{path}: {e}") from None
    base = doc.get("base", doc.get("slots", {}).get("base"))
    if isinstance(base, dict):
        base = base.get("packages", [])
    return {p for p in base or [] if isinstance(p, str)}


def refusal(fragment: str, base: set[str] | None = None) -> str | None:
    """Why `fragment` cannot go with --hot, or None."""
    normal = "use the normal `r36os push` (a new build and a reboot)"
    if fragment in REFUSED:
        return f"{fragment} only changes with a reboot: {normal}"
    if fragment in (base_slot_packages() if base is None else base):
        return f"{fragment} is in the base slot, it only changes with a reboot: {normal}"
    if not fragment.startswith(PREFIXES):
        return (f"{fragment} is not a project fragment (only lume-* and r36os-* go with "
                f"--hot): {normal}")
    return None


@dataclass
class HotPackage:
    name: str
    version: str
    apk: Path
    members: list[tuple[tarfile.TarInfo, bytes]]    # data files, as in the .apk

    @property
    def files(self) -> list[str]:
        return [m.name for m, _ in self.members if not m.isdir()]

    @property
    def ram_need(self) -> int:
        """Bytes the files take in the RAM layer (whole tmpfs pages)."""
        return sum(-(-m.size // BLOCK) * BLOCK for m, _ in self.members if m.isreg())

    @property
    def init_scripts(self) -> list[str]:
        return [m.name.rsplit("/", 1)[1] for m, _ in self.members
                if m.isreg() and m.name.startswith("etc/init.d/") and m.name.count("/") == 2]


def find_package(fragment: str, arch: str) -> HotPackage:
    """The newest published version of `fragment` for `arch` and its data files."""
    try:
        hashes = read_repo_hashes(arch)
    except manifests.ManifestError as e:
        raise PushError(str(e)) from None
    entry = hashes.packages.get(fragment)
    repo = arch_repo_dir(arch)
    if entry is None:
        raise PushError(f"{fragment} is not in {repo}/{manifests.HASHES_FILE}: build it "
                        f"first (`r36os pkg <target> {fragment}`)")
    apk = repo / entry.file
    if not apk.exists():
        raise PushError(f"{apk} is missing (named by {manifests.HASHES_FILE}): build "
                        f"{fragment} again")
    try:
        members = frag._members(frag.split_apk(apk).data)
    except frag.FragmentError as e:
        raise PushError(f"{apk.name}: {e}") from None
    # anything starting with '.' at the top is control (abuild keeps it out of the data
    # part, but a hand-made .apk might not)
    members = [(m, b) for m, b in members if not m.name.lstrip("./").startswith(".")]
    for m, _ in members:
        name = m.name.lstrip("./")
        if name.startswith(BOOT_PATHS) or name.rstrip("/") in ("boot", "lib/modules"):
            raise PushError(f"{fragment} ships /{name}, a boot file: use the normal "
                            "`r36os push` (a new build and a reboot)")
    return HotPackage(fragment, entry.version, apk, members)


def hot_tar(pkg: HotPackage) -> Path:
    """The data files of the package as a plain tar (GNU format: busybox tar reads its long
    names), without the APK checksum headers."""
    out = ensure_dir(cache_dir() / "push" / "hot") / f"{pkg.name}-{pkg.version}.tar"
    with tarfile.open(out, "w", format=tarfile.GNU_FORMAT) as tf:
        for m, data in pkg.members:
            m = copy.copy(m)
            m.pax_headers = {}
            tf.addfile(m, io.BytesIO(data) if m.isreg() else None)
    return out


def services(pkg: HotPackage, aports: Path | None = None) -> list[str]:
    """The services to restart: `_lume_restart` of its APKBUILD when it has the variable
    (empty means none), else the init.d scripts it ships."""
    apkbuild = (aports or REPO_ROOT / "aports") / pkg.name / "APKBUILD"
    if apkbuild.exists():
        listed = frag._assignment(apkbuild.read_text(), "_lume_restart")
        if listed is not None:
            return listed.split()
    return pkg.init_scripts


def _q(s: str) -> str:
    return shlex.quote(s)


def restart_command(names: list[str]) -> str:
    """Restart each service that is running; one `<state> <name>` line each."""
    return (f"for s in {' '.join(_q(n) for n in names)}; do "
            'if rc-service "$s" status >/dev/null 2>&1; then '
            'if rc-service "$s" restart >/dev/null 2>&1; then echo "restarted $s"; '
            'else echo "failed $s"; fi; '
            'else echo "stopped $s"; fi; done')


def event_command(result: str, detail: str) -> str:
    """The console's own event writer (logs.sh), flushed to events.log on the card."""
    return (f". {LIBEXEC}/lib.sh && . {LIBEXEC}/logs.sh && "
            f"event push {result} {shlex.join(detail.split())} && {{ logs_flush; true; }}")


def push_hot(fragment: str, remote=None, out=print, aports: Path | None = None) -> int:
    if reason := refusal(fragment):
        raise PushError(reason)
    remote = remote or Remote()
    console = read_hot_console(remote)
    out(f"console: {console.board}, {console.machine} (repo {console.arch}), RAM layer "
        f"{console.ram_free >> 10} KiB free")
    if not console.overlay:
        raise PushError(f"/ is not the overlay with its upper layer in RAM ({UPPER}): --hot "
                        "would write to the card; use the normal `r36os push`")
    pkg = find_package(fragment, console.arch)
    need = pkg.ram_need + MARGIN
    out(f"hot:     {pkg.name} {pkg.version} ({console.arch}), {len(pkg.files)} file(s), "
        f"{pkg.ram_need >> 10} KiB")
    if console.ram_free < need:
        raise PushError(f"the RAM layer has {console.ram_free >> 10} KiB free, {pkg.name} "
                        f"needs {pkg.ram_need >> 10} KiB (plus {MARGIN >> 10} KiB): reboot "
                        "the console to empty it, or use the normal `r36os push`")
    tar = hot_tar(pkg)
    remote.run("tar -xf - -C /", stdin=tar)
    out("sent:    files extracted into the RAM layer (gone after a reboot)")
    detail = f"hot {pkg.name} {pkg.version}"
    remote.run(event_command("OK", detail))
    out(f"event:   push OK {detail}")
    names = services(pkg, aports)
    failed = []
    if names:
        if FRONTEND in names:
            out("note:    restarting frontend restarts the launcher session")
        for line in remote.run(restart_command(names)).splitlines():
            state, _, name = line.strip().partition(" ")
            if state == "restarted":
                out(f"restart: {name}")
            elif state == "stopped":
                out(f"restart: {name} not running, left stopped")
            elif state == "failed":
                failed.append(name)
    else:
        out("restart: no service")
    if failed:
        remote.run(event_command("FAIL", f"{detail} restart {' '.join(failed)}"))
        raise PushError(f"{pkg.name} {pkg.version} is on the console, but the restart of "
                        f"{', '.join(failed)} failed (see `r36os dev log`); a reboot brings "
                        "back the card's set")
    out(f"ok: {pkg.name} {pkg.version} is live until the next reboot")
    return 0


def main_push_hot(fragment: str) -> int:
    try:
        return push_hot(fragment)
    except PushError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
