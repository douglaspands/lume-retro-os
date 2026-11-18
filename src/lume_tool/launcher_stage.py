"""Sources of the lume-launcher package (aports/lume-launcher, lume-launcher task 2.3).

abuild only sees `aports/` in its container, and the build has no network. Before the
package is built, `stage()` puts in `aports/lume-launcher/stage/` (ignored by git):

- `lume/`: the Rust workspace (`lume/` of the repository, without `target/`);
- `lume/vendor/` and `lume/.cargo/config.toml`: every crate of `Cargo.lock`, so
  `cargo build --offline --frozen` needs nothing else.

The crates come from a tarball in the distfiles cache named by the hash of `Cargo.lock`
(`lume-vendor-<hash>.tar.gz`, with its SHA512 in `.sha512` next to it). It is made once, with
`cargo vendor` on the host (the only step with network), in a fixed order and with fixed
dates, and checked against the SHA512 on every use.

The cargo `target/` lives in `.cache/cargo/<arch>` (build-speed D7), mounted by
`lume_tool.packages` on `stage/lume/target` in the abuild container of that architecture: one
changed line recompiles only the lume crates. The mount point is the same path the build
used without the cache, so no new path enters the binaries.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import shutil
import subprocess
import tarfile
import tempfile
import threading
from pathlib import Path

from lume_tool.paths import REPO_ROOT, cache_dir, ensure_dir

WORKSPACE = REPO_ROOT / "lume"
STAGE = REPO_ROOT / "aports/lume-launcher/stage"
# never copied from lume/: the build output (a mount point in the container) and the
# crates and cargo config that stage() writes itself
STAGE_SKIP = frozenset({"target", "vendor", ".cargo"})
CARGO_CONFIG = """# written by lume_tool.launcher_stage.stage(): the crates of Cargo.lock, vendored
[source.crates-io]
replace-with = "vendored-sources"

[source.vendored-sources]
directory = "vendor"
"""


def lock_hash() -> str:
    return hashlib.sha256((WORKSPACE / "Cargo.lock").read_bytes()).hexdigest()[:16]


def vendor_tarball() -> Path:
    return cache_dir() / "distfiles" / f"lume-vendor-{lock_hash()}.tar.gz"


def _deterministic_tar(src: Path, arcname: str) -> bytes:
    """A gzip'd tar of `src` with sorted names, no owners and a fixed date."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.GNU_FORMAT) as tar:
        for path in sorted([src, *src.rglob("*")]):
            info = tar.gettarinfo(str(path), arcname=f"{arcname}/{path.relative_to(src)}".rstrip("/."))
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            if path.is_file():
                with path.open("rb") as f:
                    tar.addfile(info, f)
            else:
                tar.addfile(info)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz:
        gz.write(raw.getvalue())
    return out.getvalue()


def ensure_vendor() -> Path:
    """The vendored crates tarball of the current Cargo.lock, made if missing, checked."""
    tarball = vendor_tarball()
    sums = tarball.with_name(tarball.name + ".sha512")
    if not tarball.exists():
        ensure_dir(tarball.parent)
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "vendor"
            subprocess.run(["cargo", "vendor", "--locked", "--versioned-dirs",
                            "--manifest-path", str(WORKSPACE / "Cargo.toml"), str(out)],
                           check=True, stdout=subprocess.DEVNULL)
            data = _deterministic_tar(out, "vendor")
        tarball.write_bytes(data)
        sums.write_text(f"{hashlib.sha512(data).hexdigest()}  {tarball.name}\n")
    want = sums.read_text().split()[0]
    got = hashlib.sha512(tarball.read_bytes()).hexdigest()
    if got != want:
        raise RuntimeError(f"{tarball.name}: SHA512 does not match {sums.name}")
    return tarball


def target_cache(arch: str) -> Path:
    """The cargo `target/` of one architecture, kept between builds (build-speed D7)."""
    return cache_dir() / "cargo" / arch


def _sync_tree(src: Path, dest: Path, skip: frozenset[str]) -> None:
    """Make `dest` a copy of `src` by content, ignoring the names in `skip` (at any depth).

    A file whose bytes did not change keeps its staged mtime; a new or changed file is
    written again, so it gets the current time, newer than any artifact of the cached
    `target/` (build-speed D7). Cargo decides freshness of the workspace crates by mtime,
    so it sees exactly the files whose content changed, whatever their mtime in `lume/`
    (a branch switch, a restored backup). Files and folders gone from `src` are removed.
    """
    dest.mkdir(parents=True, exist_ok=True)
    wanted = {p.name for p in src.iterdir()}
    for old in dest.iterdir():
        if old.name in skip or old.name in wanted:
            continue
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
        else:
            old.unlink()
    for s in sorted(src.iterdir()):
        if s.name in skip:
            continue
        d = dest / s.name
        if s.is_dir() and not s.is_symlink():
            if d.exists() and not d.is_dir():
                d.unlink()
            _sync_tree(s, d, skip)
        else:
            if d.is_dir() and not d.is_symlink():
                shutil.rmtree(d)
            if not d.exists() or d.read_bytes() != s.read_bytes():
                d.unlink(missing_ok=True)
                shutil.copyfile(s, d)
            shutil.copymode(s, d)


_STAGE_LOCK = threading.Lock()


def stage() -> Path:
    """Fills aports/lume-launcher/stage/lume with the workspace and its crates.

    The stage is updated in place, by content (`_sync_tree`), and its `target/` is left
    alone: in the abuild container it is the mount point of `target_cache(<arch>)`. One
    caller at a time: both arch pipelines of a parallel build (build-speed D17) stage it.
    """
    with _STAGE_LOCK:
        return _stage()


def _stage() -> Path:
    tarball = ensure_vendor()
    dest = STAGE / "lume"
    _sync_tree(WORKSPACE, dest, STAGE_SKIP)
    # only a mount point: empty it (artifacts of builds before the cache), never remove it,
    # since the container of another architecture may have it mounted right now
    mount_point = dest / "target"
    mount_point.mkdir(exist_ok=True)
    for old in mount_point.iterdir():
        if old.is_dir() and not old.is_symlink():
            shutil.rmtree(old)
        else:
            old.unlink()
    # the crates are extracted again only when the tarball (that is, Cargo.lock) changes
    marker = dest / ".cargo/vendor-tarball"
    if (marker.exists() and marker.read_text() == tarball.name and (dest / "vendor").is_dir()
            and (dest / ".cargo/config.toml").exists()
            and (dest / ".cargo/config.toml").read_text() == CARGO_CONFIG):
        return dest
    shutil.rmtree(dest / "vendor", ignore_errors=True)
    shutil.rmtree(dest / ".cargo", ignore_errors=True)
    with tarfile.open(tarball) as tar:
        tar.extractall(dest, filter="data")
    (dest / ".cargo").mkdir()
    (dest / ".cargo/config.toml").write_text(CARGO_CONFIG)
    marker.write_text(tarball.name)
    return dest
