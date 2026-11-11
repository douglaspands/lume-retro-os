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
PATCHES = ["0001-quit-shuts-down.patch", "0002-shut-down-asks-confirmation.patch",
           "0003-alsa-bounded-write-wait.patch", "0004-status-frame-count.patch",
           "0005-volume-percent-steps.patch"]
TOUCHED = ["menu/cbs/menu_cbs_ok.c", "intl/msg_hash_us.h", "intl/msg_hash_pt_br.h",
           "intl/msg_hash_es.h", "audio/drivers/alsa.c", "command.c",
           "gfx/widgets/gfx_widget_volume.c", "menu/menu_setting.c"]


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
    assert files == TOUCHED[:4]
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
    # 0003: the playback wait is bounded, the untimed wait is gone
    alsa = (tmp_path / "audio/drivers/alsa.c").read_text()
    assert "snd_pcm_wait(alsa->pcm, -1)" not in alsa
    assert "alsa->stalled ? 0 : ALSA_WRITE_TIMEOUT_MS" in alsa
    # 0004: GET_STATUS ends with the frame counter, after crc32 (logd cuts at ",crc32=")
    command = (tmp_path / "command.c").read_text()
    assert '",crc32=%lx,frames=%llu\\n"' in command
    # 0005: volume keys in 5% steps capped at 0 dB; the widget shows no dB; menu stops at 0 dB
    assert "level            = MIN(level, 100.0f);" in command
    # only the mixer volume (not touched) keeps the +12 dB cap
    assert command.count("MIN(new_volume, 12.0f)") == 1
    widget = (tmp_path / "gfx/widgets/gfx_widget_volume.c").read_text()
    assert '" dB"' not in widget and "+%.1f dB" not in widget
    assert "pow(10, new_volume / 40)" in widget
    assert "list, list_info, -80, 0, 1.0, true, true);" in (tmp_path / "menu/menu_setting.c").read_text()


def test_volume_curve_steps_and_cap():
    # the curve in patch 0005: dB = 40 * log10(level / 100), level 0 = -80 dB, 5% steps
    import math

    def level_to_db(level):
        return -80.0 if level < 2.5 else 40 * math.log10(level / 100)

    def db_to_level(db):
        return 0.0 if db <= -80 else 100 * 10 ** (db / 40)

    def press(db, up):
        level = math.floor(min(db_to_level(db), 100) / 5 + 0.5) * 5 + (5 if up else -5)
        return level_to_db(min(max(level, 0), 100))

    assert level_to_db(100) == 0 and round(level_to_db(50), 1) == -12.0
    db = -80.0
    for _ in range(25):                     # 20 presses reach the top, then it stays there
        db = press(db, up=True)
    assert db == 0
    assert round(db_to_level(press(12.0, up=False))) == 95   # an old +12 dB joins the grid
    assert round(db_to_level(press(-29.5, up=True))) == 25    # -29.5 dB is ~18% -> 20% -> 25%


def test_alsa_patch_only_bounds_the_playback_wait():
    text = (APORT / PATCHES[2]).read_text()
    assert re.findall(r"^\+\+\+ b/(\S+)", text, re.M) == ["audio/drivers/alsa.c"]
    assert "#define ALSA_WRITE_TIMEOUT_MS 500" in text
    assert "[ALSA] Playback stalled" in text                 # logd turns it into an event
    assert "[ALSA] Playback consuming again" in text
    # the microphone wait (mic->pcm) is not touched
    assert "mic->pcm" not in text
