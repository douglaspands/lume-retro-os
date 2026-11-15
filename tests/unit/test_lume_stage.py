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


def test_card_has_a_folder_for_the_users_themes():
    # lume-index makes ROMS/system/lume/themes/ once, with the guide, on new and old cards
    init = (REPO_ROOT / "rootfs/overlay/etc/init.d/lume-index").read_text()
    assert "themes=/storage/system/lume/themes" in init
    assert 'if [ ! -d "$themes" ]' in init
    assert "cp /usr/share/lume/LEIA-ME-temas.txt" in init
    guide = (REPO_ROOT / "rootfs/overlay/usr/share/lume/LEIA-ME-temas.txt").read_text()
    for needed in ("theme.toml", "icons/", "extends", 'id = "meu-tema"', "_lume-original"):
        assert needed in guide, needed
    # the model of the original theme goes next to it, refreshed only when it differs
    assert "model=/usr/share/lume/theme-template/_lume-original/theme.toml" in init
    assert 'if ! cmp -s "$model"' in init
    assert (REPO_ROOT / "rootfs/overlay/usr/share/lume/theme-template/_lume-original/theme.toml").is_file()


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
    # frontend-session: no console maker logo is shipped by the launcher package. No image
    # file (by name or by content), the aport installs none, and no image theme points to
    # one. The guide of the card's themes folder (a .txt) may tell the user how to add theirs.
    files = [p for p in (REPO_ROOT / "rootfs/overlay/usr/share/lume").rglob("*") if p.is_file()]
    for p in files:
        assert p.suffix.lower() not in (".png", ".svg", ".jpg", ".jpeg", ".webp"), p
        head = p.read_bytes()[:8]
        assert not head.startswith(b"\x89PNG") and not head.startswith(b"\xff\xd8") and b"<svg" not in p.read_bytes()[:256], p
    assert not re.search(r"logo|\.png|\.svg", APKBUILD, re.I)
    themes = "".join(p.read_text() for p in files if p.suffix == ".toml" and "themes" in p.parts)
    assert not re.search(r"\.png|\.svg", themes, re.I)
