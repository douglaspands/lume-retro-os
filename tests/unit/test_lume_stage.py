"""lume-launcher task 2.3: the package sources (r36os.lume) and the aport."""

import hashlib
import re

from r36os import lume
from r36os.paths import REPO_ROOT

APKBUILD = (REPO_ROOT / "aports/lume-launcher/APKBUILD").read_text()
CARGO = (REPO_ROOT / "lume/Cargo.toml").read_text()


def test_vendor_tarball_is_reproducible(tmp_path):
    src = tmp_path / "vendor"
    (src / "a-1.0/src").mkdir(parents=True)
    (src / "a-1.0/src/lib.rs").write_text("pub fn x() {}\n")
    (src / "b-2.0").mkdir()
    (src / "b-2.0/Cargo.toml").write_text("[package]\n")
    first = lume._deterministic_tar(src, "vendor")
    (src / "b-2.0/Cargo.toml").touch()          # another mtime, same content
    assert lume._deterministic_tar(src, "vendor") == first
    assert hashlib.sha512(first).hexdigest()


def test_tarball_is_named_by_the_lock():
    assert re.fullmatch(r"lume-vendor-[0-9a-f]{16}\.tar\.gz", lume.vendor_tarball().name)


def test_aport_builds_offline_from_the_stage():
    assert 'builddir="$startdir/stage/lume"' in APKBUILD
    assert "cargo build --release --offline --frozen" in APKBUILD
    assert re.search(r'^arch="x86_64 armv7 aarch64"$', APKBUILD, re.M)
    for b in ("lume-run", "lume-ui", "lume-index"):
        assert f"{b}" in APKBUILD
    # the prototype's font, in the three weights the launcher draws with
    for face in ("Roboto-Regular", "Roboto-Medium", "Roboto-Bold"):
        assert face in APKBUILD
    assert "font-roboto" in APKBUILD and "Apache-2.0" in APKBUILD
    assert "/aports/*/stage/" in (REPO_ROOT / ".gitignore").read_text()
    assert "lume-launcher" in (REPO_ROOT / "rootfs/packages.txt").read_text().split()


def test_workspace_profile_and_msrv():
    # D2: small binaries, musl, the rustc of Alpine 3.24
    for line in ('opt-level = "s"', "lto = true", 'panic = "abort"', "strip = true",
                 'rust-version = "1.96"', 'resolver = "3"'):
        assert line in CARGO, line
    assert (REPO_ROOT / "lume/Cargo.lock").exists()


def test_no_logo_files_in_the_package():
    # frontend-session: no console maker logo is shipped by the launcher package
    shipped = APKBUILD + "".join(p.read_text() for p in (REPO_ROOT / "rootfs/overlay/usr/share/lume").rglob("*") if p.is_file())
    assert not re.search(r"logo|\.png|\.svg", shipped, re.I)
