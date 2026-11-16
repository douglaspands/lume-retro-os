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
"""

from __future__ import annotations

import gzip
import hashlib
import io
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path

from r36os.paths import REPO_ROOT, cache_dir, ensure_dir

WORKSPACE = REPO_ROOT / "lume"
STAGE = REPO_ROOT / "aports/lume-launcher/stage"
CARGO_CONFIG = """# written by r36os.lume.stage(): the crates of Cargo.lock, vendored
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


def stage() -> Path:
    """Fills aports/lume-launcher/stage/lume with the workspace and its crates."""
    tarball = ensure_vendor()
    shutil.rmtree(STAGE, ignore_errors=True)
    dest = STAGE / "lume"
    shutil.copytree(WORKSPACE, dest, ignore=shutil.ignore_patterns("target", "vendor", ".cargo"))
    with tarfile.open(tarball) as tar:
        tar.extractall(dest, filter="data")
    (dest / ".cargo").mkdir()
    (dest / ".cargo/config.toml").write_text(CARGO_CONFIG)
    return dest
