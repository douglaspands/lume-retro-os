import re

import pytest

from r36os.packages import local_aports
from r36os.paths import REPO_ROOT
from r36os.targets import get_target

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
