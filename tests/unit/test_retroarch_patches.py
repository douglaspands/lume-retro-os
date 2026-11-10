"""Local RetroArch patches (aports/retroarch): checksums, order and that they apply."""

import hashlib
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from r36os.paths import REPO_ROOT, cache_dir

APORT = REPO_ROOT / "aports/retroarch"
APKBUILD = (APORT / "APKBUILD").read_text()
SRC = cache_dir() / "distfiles/retroarch-1.22.2.tar.gz"
PATCHES = ["0001-quit-shuts-down.patch", "0002-shut-down-asks-confirmation.patch"]
TOUCHED = ["menu/cbs/menu_cbs_ok.c", "intl/msg_hash_us.h", "intl/msg_hash_pt_br.h",
           "intl/msg_hash_es.h"]


def test_patches_are_listed_in_order_with_matching_checksums():
    sources = re.search(r'^source="(.*?)"', APKBUILD, re.M | re.S).group(1).split()
    listed = [s for s in sources if s.endswith(".patch")]
    assert listed == ["config.patch"] + PATCHES
    sums = dict(reversed(line.split()) for line in
                re.search(r'^sha512sums="(.*?)"', APKBUILD, re.M | re.S).group(1).split("\n") if line.strip())
    for name in ["config.patch"] + PATCHES:
        assert sums[name] == hashlib.sha512((APORT / name).read_bytes()).hexdigest(), name


def test_pkgrel_is_high_so_the_local_package_wins():
    assert int(re.search(r"^pkgrel=(\d+)", APKBUILD, re.M).group(1)) >= 100


def test_confirmation_patch_only_touches_the_menu_item_and_the_message():
    text = (APORT / PATCHES[1]).read_text()
    assert "quit_press_twice" in text                       # follows the existing setting
    assert "generic_action_ok_command(CMD_EVENT_QUIT)" in text
    assert "MSG_PRESS_AGAIN_TO_QUIT" in text
    files = re.findall(r"^\+\+\+ b/(\S+)", text, re.M)
    assert files == TOUCHED
    # the message is reworded in the three shipped languages
    assert "Press again to shut down..." in text
    assert "Pressione novamente para desligar..." in text
    assert "Vuelve a pulsar para apagar..." in text


@pytest.mark.skipif(not SRC.exists() or shutil.which("patch") is None,
                    reason="needs the cached RetroArch tarball and patch(1)")
def test_patches_apply_in_order_to_the_pristine_source(tmp_path: Path):
    with tarfile.open(SRC) as tar:
        for name in TOUCHED:
            member = tar.getmember(f"RetroArch-1.22.2/{name}")
            member.name = name
            tar.extract(member, tmp_path, filter="data")
    for name in PATCHES:
        r = subprocess.run(["patch", "-p1", "--no-backup-if-mismatch", "-i", str(APORT / name)],
                           cwd=tmp_path, capture_output=True, text=True)
        assert r.returncode == 0, f"{name}: {r.stdout}{r.stderr}"
    quit_fn = (tmp_path / "menu/cbs/menu_cbs_ok.c").read_text()
    assert "static int action_ok_quit(" in quit_fn
    assert "STATIC_DEFAULT_ACTION_OK_CMD_FUNC(action_ok_quit," not in quit_fn
    assert '"Press again to shut down..."' in (tmp_path / "intl/msg_hash_us.h").read_text()
    # 0001 is still in effect after 0002
    assert '"Desligar"' in (tmp_path / "intl/msg_hash_pt_br.h").read_text()
