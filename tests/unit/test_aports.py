import re
import subprocess

import pytest

from lume_tool.packages import local_aports
from lume_tool.paths import REPO_ROOT
from lume_tool.targets import get_target

FBALPHA = {
    "cps1": "5542c1848ef81e92db311193b01dc349bc29d7cc",
    "cps2": "e3f3ae46f120228b74d41e2b2862f1fbf1d7eb5b",
    "neogeo": "e092097037d494c50d17c5144a2758d68538061b",
}


def _apkbuild(name: str) -> str:
    return (REPO_ROOT / "aports" / name / "APKBUILD").read_text()


def test_mesa_only_for_vm():
    assert "mesa" in local_aports(get_target("vm"))
    assert "mesa" not in local_aports(get_target("r36s"))
    assert "mesa" not in local_aports(get_target("ga36"))


def test_cores_for_all_targets():
    for t in ("vm", "r36s", "ga36"):
        assert "libretro-pcsx-rearmed" in local_aports(get_target(t))
        assert "retroarch" in local_aports(get_target(t))
        # PSP disabled in this version (pending 12.1): the aport exists but is not built
        assert "libretro-ppsspp" not in local_aports(get_target(t))


@pytest.mark.parametrize("board", sorted(FBALPHA))
def test_fbalpha2012_aport(board):
    # catalog-arcade-sega, D3: one aport per board, pinned commit, license installed
    name = f"libretro-fbalpha2012-{board}"
    text = _apkbuild(name)
    commit = FBALPHA[board]
    assert re.search(r'^arch="all"$', text, re.M)              # armv7, aarch64 and x86_64 (VM)
    assert re.search(r'^license="custom"$', text, re.M)
    assert f'_commit="{commit}"' in text
    assert f"libretro/fbalpha2012_{board}/archive/$_commit.tar.gz" in text
    # one sha512 for the one source tarball, named after the source file
    sums = re.findall(r"^([0-9a-f]{128})  (\S+)$", text, re.M)
    assert sums == [(sums[0][0], f"{name}-{commit}.tar.gz")]
    # the .so goes to /usr/lib/libretro and the FB Alpha license text travels with it
    package = text.split("package() {", 1)[1].split("\n}", 1)[0]
    assert f"fbalpha2012_{board}_libretro.so" in package and "/usr/lib/libretro/" in package
    assert "src/license.txt" in package
    assert "/usr/share/licenses/$pkgname/license.txt" in package
    for t in ("vm", "r36s", "ga36"):
        assert name in local_aports(get_target(t))


# game-experience-tuning 10.1: alternative arcade cores under measurement against fbneo
# aport -> (commit, upstream repo, .so, license file in the source, installed license name)
ALT_ARCADE = {
    "libretro-fbalpha2012": ("0ce31536bef3162fe7e69ff5f555334ec4913cef", "libretro/fbalpha2012",
                             "fbalpha2012_libretro.so", "src/license.txt", "license.txt"),
    "libretro-mame2003-plus": ("2a60eda71ae0fea543a76a43b5d58086a5485256",
                               "libretro/mame2003-plus-libretro", "mame2003_plus_libretro.so",
                               "LICENSE.md", "LICENSE.md"),
    "libretro-mame2000": ("181b42e5da0d2f0c7a2e59244f23633ed594de2e", "libretro/mame2000-libretro",
                          "mame2000_libretro.so", "readme.txt", "readme.txt"),
}


@pytest.mark.parametrize("name", sorted(ALT_ARCADE))
def test_alternative_arcade_aport(name):
    commit, repo, so, src_license, license_name = ALT_ARCADE[name]
    text = _apkbuild(name)
    assert re.search(r'^arch="all"$', text, re.M)              # armv7, aarch64 and x86_64 (VM)
    assert f'_commit="{commit}"' in text
    assert f"https://github.com/{repo}/archive/$_commit.tar.gz" in text
    sums = re.findall(r"^([0-9a-f]{128})  (\S+)$", text, re.M)
    assert sums == [(sums[0][0], f"{name}-{commit}.tar.gz")]
    # non-commercial licenses: declared as custom, the text travels with the binary
    assert re.search(r'^license="custom(:MAME)?"$', text, re.M)
    package = text.split("package() {", 1)[1].split("\n}", 1)[0]
    assert f"/usr/lib/libretro/{so}" in package
    assert f"{src_license} " in package
    assert f"/usr/share/licenses/$pkgname/{license_name}" in package
    # default upstream build, no per-CPU flags (P-10)
    build = text.split("build() {", 1)[1].split("\n}", 1)[0]
    assert not re.search(r"-m(arm|thumb|cpu|tune|arch|fpu)\b|platform=|ARM=|-O[0-3s]", build)
    for t in ("vm", "r36s", "ga36"):
        assert name in local_aports(get_target(t))
    packages = (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    # 10.5 (the user, 2026-11-20): mame2000 lost on every board but one and left the image;
    # its aport stays to measure it again
    assert (name in packages) is (name != "libretro-mame2000")


def test_mame2003_plus_drops_the_initial_exec_tls():
    # musl refuses initial-exec TLS in a dlopen'ed core: prepare() removes the attribute
    text = _apkbuild("libretro-mame2003-plus")
    assert "src/vidhrdw/stvvid.c" in text and 'tls_model("initial-exec")' in text


def _build_env(name: str, carch: str) -> str:
    """Source the APKBUILD for CARCH with a stub make; return the CFLAGS make sees."""
    apkbuild = REPO_ROOT / "aports" / name / "APKBUILD"
    script = (
        'CFLAGS="-Os -fstack-clash-protection"\n'
        'make() { printf "%s\\n" "$CFLAGS"; }\n'
        'cmake() { printf "%s\\n" "$CFLAGS"; }\n'
        '. "$1"\n'
        "build\n"
    )
    out = subprocess.run(["sh", "-c", script, "sh", str(apkbuild)],
                         env={"CARCH": carch, "PATH": "/usr/bin:/bin"},
                         capture_output=True, text=True, check=True)
    return out.stdout.splitlines()[0]


@pytest.mark.parametrize("carch,marm", [("armv7", True), ("aarch64", False), ("x86_64", False)])
def test_picodrive_arm_mode_on_armv7(carch, marm):
    # device-fixes D14 / P-30: picodrive stores handlers as (addr >> 1) in its memory maps,
    # so on armv7 it must be built in ARM mode (Thumb pointers are odd); only on armv7
    cflags = _build_env("libretro-picodrive", carch).split()
    assert ("-marm" in cflags) is marm
    assert "-mthumb" not in cflags
    # the distro flags still reach the build (environment, not a make override)
    assert cflags[:2] == ["-Os", "-fstack-clash-protection"]
    text = _apkbuild("libretro-picodrive")
    # passed through the environment: a make command-line CFLAGS would drop the
    # Makefile's own CFLAGS += lines
    assert re.search(r'^\tCFLAGS="\$CFLAGS \$_cflags" make -f Makefile\.libretro$', text, re.M)
    assert int(re.search(r"^pkgrel=(\d+)$", text, re.M).group(1)) >= 1


def test_ppsspp_arm_mode_on_armv7():
    # same reason and same pattern as picodrive (the JIT calls C functions in ARM mode)
    assert "-marm" in _build_env("libretro-ppsspp", "armv7").split()
    assert "-marm" not in _build_env("libretro-ppsspp", "aarch64").split()
