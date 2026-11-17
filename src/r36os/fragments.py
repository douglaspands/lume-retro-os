"""Fragment versions by content, compilation by inputs (build-speed D3, task 6.1).

The pure part of the incremental package build (no containers here; `r36os.packages`
runs abuild and signs):

- inputs of a fragment: every file of its aport dir (abuild work dirs and staged build
  caches excluded), the build script, the builder image recipe and the content of its local
  build dependencies (from hashes.json); `manifests.inputs_hash` turns them into one hash;
- the computed pkgrel: the APKBUILD pkgrel is only the minimum, the build uses the next
  one after every version already published, through a generated copy of the APKBUILD;
- the content hash of a built .apk, read from its data segment;
- the control area rewritten with `.lume-content` (the result is signed by abuild-sign);
- the cleanup plan of `out/repo/<arch>/`: newest and previous version of each package, and
  every version cited by the kept builds (`latest` and `flashed` of each image).
"""

from __future__ import annotations

import gzip
import hashlib
import io
import os
import re
import tarfile
import zlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from r36os import manifests
from r36os.manifests import ContentEntry

# abuild work dirs inside the aport ($srcdir, $pkgdir, tmp): outputs, never inputs
WORK_DIRS = frozenset({"src", "pkg", "tmp"})
# under stage/: build output (a mount point of the cargo cache) and the vendored crates,
# which are pinned by Cargo.lock and the vendor tarball name (both hashed)
STAGE_SKIP = frozenset({"target", "vendor"})
BUILD_DEP_VARS = ("makedepends", "makedepends_build", "makedepends_host", "checkdepends")
KEEP_VERSIONS = 2   # newest and previous of each package (pushing an archived build)


class FragmentError(RuntimeError):
    """An aport or a built package the incremental build cannot handle."""


# --- APKBUILD -------------------------------------------------------------------------

def _assignment(text: str, key: str) -> str | None:
    """The literal value of `key=...` (quoted values may span lines)."""
    m = re.search(rf'^{re.escape(key)}=(?:"([^"]*)"|\'([^\']*)\'|(\S*))', text, re.M)
    if not m:
        return None
    return next(g for g in m.groups() if g is not None)


def apkbuild_version(text: str, source: str = "APKBUILD") -> tuple[str, int]:
    """(pkgver, pkgrel) of an APKBUILD; both must be literals."""
    ver, rel = _assignment(text, "pkgver"), _assignment(text, "pkgrel")
    if not ver or "$" in ver or rel is None or not rel.isdigit():
        raise FragmentError(f"{source}: pkgver/pkgrel must be literals "
                            f"(pkgver={ver!r} pkgrel={rel!r})")
    return ver, int(rel)


def with_pkgrel(text: str, pkgrel: int, source: str = "APKBUILD") -> str:
    """The APKBUILD text with its pkgrel line replaced (the committed file is untouched)."""
    new, n = re.subn(r"^pkgrel=\S*$", f"pkgrel={pkgrel}", text, count=1, flags=re.M)
    if n != 1:
        raise FragmentError(f"{source}: no pkgrel= line")
    return new


def apkbuild_packages(text: str, source: str = "APKBUILD") -> list[str] | None:
    """pkgname and the subpackage names of an APKBUILD; None when a name is computed by
    something other than $pkgname (then the packages are only known after a build)."""
    name = _assignment(text, "pkgname")
    if not name or "$" in name:
        return None
    out = [name]
    for tok in (_assignment(text, "subpackages") or "").split():
        sub = tok.split(":", 1)[0].replace("${pkgname}", name).replace("$pkgname", name)
        if "$" in sub or not sub:
            return None
        if sub not in out:
            out.append(sub)
    return out


def runtime_deps(text: str) -> list[str]:
    """Package names in `depends` (version constraints and shell variables dropped)."""
    out = []
    for tok in (_assignment(text, "depends") or "").split():
        if tok.startswith(("!", "$")) or ":" in tok:
            continue
        name = re.split(r"[<>=~]", tok, maxsplit=1)[0]
        if name and name not in out:
            out.append(name)
    return out


def build_deps(text: str) -> list[str]:
    """Package names in the build-time dependency variables (version constraints and
    shell variables dropped)."""
    out = []
    for var in BUILD_DEP_VARS:
        for tok in (_assignment(text, var) or "").split():
            if tok.startswith(("!", "$")) or ":" in tok:
                continue
            name = re.split(r"[<>=~]", tok, maxsplit=1)[0]
            if name and name not in out:
                out.append(name)
    return out


# --- inputs ---------------------------------------------------------------------------

def _skipped(rel: tuple[str, ...]) -> bool:
    return rel[0] in WORK_DIRS or (rel[0] == "stage"
                                   and any(part in STAGE_SKIP for part in rel[1:]))


def aport_files(aport_dir: Path) -> list[tuple[str, Path]]:
    """(relative path, path) of every input file of an aport, sorted; skipped dirs are
    not even walked (the vendored crates)."""
    out = []
    for root, dirs, files in os.walk(aport_dir):
        base = Path(root).relative_to(aport_dir).parts
        dirs[:] = [d for d in dirs if not _skipped((*base, d))
                   and not (Path(root) / d).is_symlink()]
        links = [d for d in os.listdir(root) if (Path(root) / d).is_symlink()
                 and (Path(root) / d).is_dir()]
        for f in [*files, *links]:
            rel = (*base, f)
            if not _skipped(rel):
                out.append(("/".join(rel), Path(root) / f))
    return sorted(out)


def _sha(data: bytes | str) -> str:
    return hashlib.sha256(data.encode() if isinstance(data, str) else data).hexdigest()


def tree_inputs(aport_dir: Path) -> dict[str, str]:
    """`file:<path>` -> sha256 for each input file (a symlink: sha256 of its target)."""
    out = {}
    for rel, p in aport_files(aport_dir):
        label = "file:" + quote(rel, safe="/-_.+~@,=")
        if p.is_symlink():
            out[label] = _sha("symlink " + str(p.readlink()))
        else:
            out[label] = manifests.sha256_file(p)
    return out


def fragment_inputs(aport_dir: Path, script: str, builder: str,
                    local_deps: Mapping[str, str]) -> dict[str, str]:
    """Every input of a fragment build, label -> sha256.

    `script` is the build script text, `builder` the identity of the builder image (its
    recipe), `local_deps` the content hash of each local build dependency (or the hash of a
    marker when it is not published yet).
    """
    inputs = tree_inputs(aport_dir)
    inputs["script"] = _sha(script)
    inputs["builder"] = _sha(builder)
    for name, content in local_deps.items():
        inputs[f"dep:{name}"] = content
    return inputs


UNPUBLISHED = _sha("unpublished local dependency")


def local_dep_contents(deps: Iterable[str], hashes: manifests.RepoHashes,
                       local_names: Iterable[str]) -> dict[str, str]:
    """Content hash of the deps that are local packages (published or still to build)."""
    local = set(local_names)
    out = {}
    for d in deps:
        if d in hashes.packages:
            out[d] = hashes.packages[d].content
        elif d in local:
            out[d] = UNPUBLISHED
    return out


def build_order(names: list[str], deps_of: Mapping[str, list[str]]) -> list[str]:
    """`names` with each local build dependency before its users (stable otherwise).

    A dependency is local when it is one of `names` or a subpackage of one
    (`mesa-dev` -> `mesa`).
    """
    def origin(dep: str) -> str | None:
        if dep in names:
            return dep
        cands = [n for n in names if dep.startswith(n + "-")]
        return max(cands, key=len) if cands else None

    out: list[str] = []
    visiting: set[str] = set()

    def visit(n: str) -> None:
        if n in out or n in visiting:
            return
        visiting.add(n)
        for d in deps_of.get(n, []):
            o = origin(d)
            if o and o != n:
                visit(o)
        visiting.discard(n)
        out.append(n)

    for n in names:
        visit(n)
    return out


# --- package files and versions -------------------------------------------------------

_APK_FILE = re.compile(r"^(?P<name>.+)-(?P<ver>[0-9][^-]*)-r(?P<rel>[0-9]+)\.apk$")


@dataclass(frozen=True)
class ApkFile:
    name: str
    pkgver: str
    pkgrel: int
    path: Path

    @property
    def version(self) -> str:
        return f"{self.pkgver}-r{self.pkgrel}"


def parse_apk_file(path: Path) -> ApkFile | None:
    m = _APK_FILE.match(path.name)
    if not m:
        return None
    return ApkFile(m["name"], m["ver"], int(m["rel"]), path)


def _ver_tokens(ver: str) -> tuple:
    return tuple((1, int(t), "") if t.isdigit() else (0, 0, t)
                 for t in re.findall(r"[0-9]+|[A-Za-z]+", ver))


def version_key(a: ApkFile) -> tuple:
    """Sort key close to apk version order (numbers as numbers, then the pkgrel)."""
    return (_ver_tokens(a.pkgver), a.pkgrel)


def apk_files(repo_arch: Path) -> dict[str, list[ApkFile]]:
    """The .apk files of a repository dir by package name, newest first."""
    by_name: dict[str, list[ApkFile]] = {}
    if repo_arch.is_dir():
        for p in repo_arch.glob("*.apk"):
            a = parse_apk_file(p)
            if a:
                by_name.setdefault(a.name, []).append(a)
    for files in by_name.values():
        files.sort(key=version_key, reverse=True)
    return by_name


def next_pkgrel(repo_arches: Iterable[Path], names: Iterable[str], pkgver: str,
                minimum: int, hashes: Iterable[manifests.RepoHashes] = ()) -> int:
    """The pkgrel of the next build: above every published file of `names` with the same
    pkgver (and every version hashes.json remembers), never below the APKBUILD pkgrel."""
    names = set(names)
    rel = minimum
    for d in repo_arches:
        for name, files in apk_files(d).items():
            if name in names:
                for a in files:
                    if a.pkgver == pkgver:
                        rel = max(rel, a.pkgrel + 1)
    for h in hashes:
        for name, p in h.packages.items():
            ver, _, r = p.version.rpartition("-r")
            if name in names and ver == pkgver:
                rel = max(rel, int(r) + 1)
    return rel


# --- .apk segments, content hash, control with .lume-content --------------------------

def apk_segments(data: bytes) -> list[bytes]:
    """The gzip members of an .apk v2, compressed, in order (signature, control, data)."""
    out = []
    rest = data
    while rest:
        d = zlib.decompressobj(31)
        try:
            d.decompress(rest)
        except zlib.error as e:
            raise FragmentError(f"not a gzip stream at byte {len(data) - len(rest)}: {e}")
        if not d.eof:
            raise FragmentError("truncated gzip stream")
        used = len(rest) - len(d.unused_data)
        out.append(rest[:used])
        rest = d.unused_data
    return out


def _members(segment: bytes) -> list[tuple[tarfile.TarInfo, bytes]]:
    out = []
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(segment)), mode="r:") as tf:
        for m in tf:
            f = tf.extractfile(m) if m.isreg() else None
            out.append((m, f.read() if f else b""))
    return out


@dataclass(frozen=True)
class ApkParts:
    signature: list[bytes]   # gzip members before the control (one per signature)
    control: bytes           # gzip member with .PKGINFO
    data: bytes              # gzip member with the files


def split_apk(apk: Path) -> ApkParts:
    segs = apk_segments(apk.read_bytes())
    for i, seg in enumerate(segs[:-1]):
        if any(m.name == ".PKGINFO" for m, _ in _members(seg)):
            return ApkParts(segs[:i], seg, segs[-1])
    raise FragmentError(f"{apk.name}: no .PKGINFO in its control segment")


def control_files(apk: Path) -> dict[str, bytes]:
    return {m.name: data for m, data in _members(split_apk(apk).control)}


def _entry_path(name: str) -> str:
    # ContentEntry refuses spaces; percent-encoding keeps every path one field
    return quote(name.rstrip("/"), safe="/-_.+~@,=:")


def _normalized_pkginfo(pairs: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """.PKGINFO pairs with this build's `<pkgver>-r<N>` cut to `<pkgver>` everywhere
    (provides = cmd:x=<ver>, install_if = ... <name>=<ver> of the subpackages)."""
    full = dict(pairs).get("pkgver", "")
    base = re.sub(r"-r[0-9]+$", "", full)
    if not full or full == base:
        return pairs
    return [(k, v.replace(full, base)) for k, v in pairs]


def apk_content_hash(apk: Path) -> str:
    """The content hash (manifests.content_hash) of a built .apk: its data files with mode,
    owner and sha256, and its .PKGINFO without the fields that change on every build."""
    parts = split_apk(apk)
    pkginfo = control_files(apk).get(".PKGINFO", b"").decode()
    entries = []
    digests: dict[str, str] = {}
    for m, data in _members(parts.data):
        path = _entry_path(m.name)
        if path in ("", "."):
            continue
        mode = m.mode & 0o7777
        if m.isreg():
            digests[m.name] = _sha(data)
            entries.append(ContentEntry(path, "f", mode, digests[m.name], m.uid, m.gid))
        elif m.islnk():   # hard link: same bytes as its target
            if m.linkname not in digests:
                raise FragmentError(f"{apk.name}: hard link {m.name} before its target")
            entries.append(ContentEntry(path, "f", mode, digests[m.linkname], m.uid, m.gid))
        elif m.issym():
            entries.append(ContentEntry(path, "l", mode, _sha(m.linkname), m.uid, m.gid))
        elif m.isdir():
            entries.append(ContentEntry(path, "d", mode, "-", m.uid, m.gid))
        else:
            raise FragmentError(f"{apk.name}: {m.name} is not a file, link or directory")
    return manifests.content_hash(entries,
                                  _normalized_pkginfo(manifests.parse_pkginfo(pkginfo)))


def apk_lume_content(apk: Path) -> str | None:
    """The content hash recorded in the .apk (.lume-content), None if it has none."""
    raw = control_files(apk).get(manifests.LUME_CONTENT)
    return None if raw is None else manifests.parse_lume_content(raw.decode(), apk.name)


def control_with_lume_content(apk: Path, content: str) -> tuple[bytes, bytes]:
    """(unsigned control segment with `.lume-content` appended, data segment) of `apk`.

    The control tar keeps the members of abuild in their order (.PKGINFO first) and ends
    without the end-of-archive blocks, like `abuild-tar --cut`; `abuild-sign` then
    prepends the signature. The data segment is kept byte for byte, so the `datahash` of
    .PKGINFO still holds.
    """
    parts = split_apk(apk)
    members = [(m, d) for m, d in _members(parts.control) if m.name != manifests.LUME_CONTENT]
    if not members or members[0][0].name != ".PKGINFO":
        raise FragmentError(f"{apk.name}: control does not start with .PKGINFO")
    ref = members[0][0]
    extra = tarfile.TarInfo(manifests.LUME_CONTENT)
    body = manifests.format_lume_content(content).encode()
    extra.size, extra.mode, extra.mtime = len(body), 0o644, ref.mtime
    extra.uid, extra.gid, extra.uname, extra.gname = 0, 0, ref.uname, ref.gname
    buf = io.BytesIO()
    tf = tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT)
    for m, data in [*members, (extra, body)]:
        tf.addfile(m, io.BytesIO(data) if m.isreg() else None)
    end = tf.offset          # before close() writes the end-of-archive blocks
    tf.close()
    raw = buf.getvalue()[:end]
    return gzip.compress(raw, compresslevel=9, mtime=0), parts.data


# --- cleanup --------------------------------------------------------------------------

_MANIFEST_LINE = re.compile(r"^(\S+) ([A-Za-z0-9_.+~]+-r[0-9]+)$")


def cited_versions(images: Path) -> set[tuple[str, str]]:
    """(package, version) of the rootfs of the kept builds: `latest` and `flashed` of each
    image in out/images/ (their manifest*.txt lists `<package> <version>`)."""
    out: set[tuple[str, str]] = set()
    if not images.is_dir():
        return out
    for image in sorted(images.iterdir()):
        for link in ("latest", "flashed"):
            build = image / link
            if not build.is_dir():
                continue
            for manifest in sorted(build.glob("manifest*.txt")):
                for line in manifest.read_text(errors="replace").splitlines():
                    m = _MANIFEST_LINE.match(line.strip())
                    if m:
                        out.add((m[1], m[2]))
    return out


def cleanup_plan(repo_arch: Path, protected: set[tuple[str, str]],
                 keep: int = KEEP_VERSIONS) -> list[Path]:
    """Files of `repo_arch` to remove: every version of a package beyond the newest `keep`,
    unless (package, version) is protected (cited by a kept build or by hashes.json)."""
    remove = []
    for name, files in sorted(apk_files(repo_arch).items()):
        for a in files[keep:]:
            if (name, a.version) not in protected:
                remove.append(a.path)
    return remove


def hashes_protected(hashes: manifests.RepoHashes) -> set[tuple[str, str]]:
    return {(n, p.version) for n, p in hashes.packages.items()}


def human_size(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    raise AssertionError


def remove_old_versions(repo_arch: Path, protected: set[tuple[str, str]],
                        keep: int = KEEP_VERSIONS) -> tuple[list[Path], int]:
    """Remove the old versions (cleanup_plan); return the files and the bytes freed."""
    files = cleanup_plan(repo_arch, protected, keep)
    freed = 0
    for p in files:
        freed += p.stat().st_size
        p.unlink()
    return files, freed
