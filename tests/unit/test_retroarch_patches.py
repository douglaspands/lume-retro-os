"""Local RetroArch patches (aports/retroarch): checksums, order and that they apply."""

import hashlib
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from lume_tool.paths import REPO_ROOT, cache_dir

APORT = REPO_ROOT / "aports/retroarch"
APKBUILD = (APORT / "APKBUILD").read_text()
SRC = cache_dir() / "distfiles/retroarch-1.22.2.tar.gz"
PATCHES = ["0001-quit-shuts-down.patch", "0002-shut-down-asks-confirmation.patch",
           "0003-alsa-bounded-write-wait.patch", "0004-status-frame-count.patch",
           "0005-volume-percent-steps.patch", "0006-reset-to-distro-defaults.patch",
           "0007-config-autosave.patch", "0009-network-commands-on-localhost.patch",
           "0010-quit-label-follows-the-frontend.patch", "0011-lume-level-line.patch",
           "0012-lume-hud-hint-menu.patch", "0013-lume-menu-lock.patch"]
TOUCHED = ["menu/cbs/menu_cbs_ok.c", "intl/msg_hash_us.h", "intl/msg_hash_pt_br.h",
           "intl/msg_hash_es.h", "audio/drivers/alsa.c", "command.c",
           "gfx/widgets/gfx_widget_volume.c", "menu/menu_setting.c", "configuration.c",
           "configuration.h", "retroarch.c", "runloop.c", "audio/audio_driver.c", "msg_hash.c",
           "command.h", "gfx/gfx_widgets.c", "gfx/gfx_widgets.h", "menu/menu_driver.c",
           "menu/menu_driver.h"]


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


def test_wifi_and_bluetooth_menus_are_built():
    # usb-device-access D11: the Wi-Fi (nmcli) and Bluetooth (bluetoothctl) drivers
    build = re.search(r"^build\(\) \{(.*?)^\}", APKBUILD, re.S | re.M).group(1)
    assert "--enable-wifi" in build and "--enable-bluetooth" in build
    assert "--disable-wifi" not in build and "--disable-bluetooth" not in build
    assert "--disable-ssl" in build


def test_network_commands_listen_on_localhost_only():
    # usb-device-access D11: with Wi-Fi, UDP 55355 must not be reachable from the network
    text = (APORT / "0009-network-commands-on-localhost.patch").read_text()
    assert '-   int fd = socket_init((void**)&res, port, NULL,' in text
    assert '+   int fd = socket_init((void**)&res, port, "127.0.0.1",' in text
    assert text.count("\n+") - text.count("\n+++") == 3 and text.count("\n-") - text.count("\n---") == 1


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
    # 0006: the reset loads the distro defaults right after RetroArch's built-in ones
    ra = (tmp_path / "retroarch.c").read_text()
    reset = ra.split("case CMD_EVENT_MENU_RESET_TO_DEFAULT_CONFIG:", 1)[1].split("break;", 1)[0]
    assert reset.index("config_set_defaults(") < reset.index("config_load_distro_defaults();")
    assert 'getenv("LUME_RETROARCH_DEFAULTS")' in (tmp_path / "configuration.c").read_text()
    assert "bool config_load_distro_defaults(void);" in (tmp_path / "configuration.h").read_text()
    # 0007: menu changes and the volume keys mark the config dirty; the main loop saves it
    handler = (tmp_path / "menu/menu_setting.c").read_text().split(
        "static void general_write_handler(rarch_setting_t *setting)", 1)[1][:400]
    assert "config_mark_dirty();" in handler
    assert "config_mark_dirty();" in command.split("void command_event_set_volume(", 1)[1][:2000]
    assert "config_autosave_tick(current_time);" in (tmp_path / "runloop.c").read_text()
    cfg = (tmp_path / "configuration.c").read_text()
    tick = cfg.split("void config_autosave_tick(int64_t now)", 1)[1].split("\n}\n", 1)[0]
    assert "RUNLOOP_FLAG_OVERRIDES_ACTIVE" in tick and "config_save_on_exit" in tick
    # 0008 (3 dB headroom) was removed on 2026-11-13: 100% volume is 0 dB again
    drv = (tmp_path / "audio/audio_driver.c").read_text()
    assert "LUME_AUDIO_HEADROOM_DB" not in drv
    # 0010: under the launcher the quit item keeps the upstream wording and no confirmation
    msg = (tmp_path / "msg_hash.c").read_text()
    assert 'getenv("LUME_RETROARCH_QUIT")' in msg
    assert msg.index("lume_quit_returns_to_launcher())") < msg.index("#ifdef HAVE_LANGEXTRA\n   switch")
    assert "settings->bools.quit_press_twice && !lume_quit_returns_to_launcher()" in quit_fn
    # 0011: LUME_LEVEL draws the launcher's level line, a registered graphics widget
    assert '{ "LUME_LEVEL",       command_lume_level,' in (tmp_path / "command.h").read_text()
    assert "gfx_widget_lume_level_show(string_is_equal(side, \"left\"), percent, rgb);" in command
    assert "&gfx_widget_lume_level," in (tmp_path / "gfx/gfx_widgets.c").read_text()
    assert "extern const gfx_widget_t gfx_widget_lume_level;" in (tmp_path / "gfx/gfx_widgets.h").read_text()
    assert "#define LUME_LEVEL_DURATION 1500" in widget
    # 0012 (lume-hud-actions D8): the bar, the hint and the menu, registered commands and one
    # graphics widget that hides 3 s after the last command
    h = (tmp_path / "command.h").read_text()
    for name, fn in (("LUME_HUD", "command_lume_hud"), ("LUME_HINT", "command_lume_hint"),
                     ("LUME_MENU", "command_lume_menu")):
        assert re.search(rf'\{{ "{name}", +{fn},', h), name
    assert "gfx_widget_lume_show(GFX_WIDGET_LUME_MENU, arg);" in command
    assert "&gfx_widget_lume," in (tmp_path / "gfx/gfx_widgets.c").read_text()
    assert "#define LUME_WIDGET_TIMEOUT 3000" in widget
    # "-" hides, so lume-run never sends a bare command (RetroArch reads past its end)
    assert 'string_is_equal(text, "-")' in widget
    # 0013 (device-fixes 9.9): lume_menu_lock is a registered key, off upstream-wise; locked
    # (a game of the command line), Back at the Quick Menu root resumes the game and the main
    # menu never stays on screen
    cfg = (tmp_path / "configuration.c").read_text()
    assert ('SETTING_BOOL("lume_menu_lock",                &settings->bools.lume_menu_lock, '
            'true, false, false);') in cfg
    assert "bool lume_menu_lock;" in (tmp_path / "configuration.h").read_text()
    assert "bool menu_lume_locked(void);" in (tmp_path / "menu/menu_driver.h").read_text()
    drv = (tmp_path / "menu/menu_driver.c").read_text()
    locked = drv.split("bool menu_lume_locked(void)\n{", 1)[1].split("\n}\n", 1)[0]
    for cond in ("settings->bools.lume_menu_lock", "GLOB_FLG_LAUNCHED_FROM_CLI",
                 "RUNLOOP_FLAG_CORE_RUNNING", "RARCH_CTL_IS_DUMMY_CORE"):
        assert cond in locked, cond
    cancel = drv.split("int generic_menu_entry_action(", 1)[1].split("case MENU_ACTION_CANCEL:", 1)[1]
    cancel = cancel.split("case MENU_ACTION_OK:", 1)[0]
    assert cancel.index("menu_lume_locked()") < cancel.index("command_event(CMD_EVENT_RESUME, NULL);")
    assert cancel.index("command_event(CMD_EVENT_RESUME, NULL);") < cancel.index("cbs->action_cancel(")
    assert "MENU_ENUM_LABEL_CONTENT_SETTINGS" in cancel
    loop = (tmp_path / "runloop.c").read_text()
    barrier = loop.split("/* Iterate the menu driver for one frame. */", 1)[1]
    assert barrier.index("menu_lume_locked()") < barrier.index(
        "if (menu_st->flags & MENU_ST_FLAG_PENDING_QUICK_MENU)")
    assert "menu_driver_ctl(RARCH_MENU_CTL_SET_PENDING_QUICK_MENU, NULL);" in barrier[:800]


@pytest.mark.skipif(not SRC.exists(), reason="needs the cached RetroArch tarball")
def test_menu_lock_keys_exist_in_the_pinned_source():
    # device-fixes 9.9: every key of the lock and of its second barrier (the "*" lines of
    # retroarch-core.keys) is a config key of RetroArch 1.22.2, so none is silently ignored
    keys = (REPO_ROOT / "aports/lume-retroarch-cfg/files/usr/share/lume/retroarch-core.keys").read_text()
    names = re.findall(r"^\* (\w+)=", keys, re.M) + ["quit_on_close_content"]
    assert len(names) == 21
    with tarfile.open(SRC) as tar:
        cfg = tar.extractfile("RetroArch-1.22.2/configuration.c").read().decode()
    for name in names:
        assert re.search(rf'SETTING_(BOOL|UINT)\("{name}",', cfg), name


def test_quit_label_patch_keeps_the_three_languages():
    text = (APORT / "0010-quit-label-follows-the-frontend.patch").read_text()
    assert re.findall(r"^\+\+\+ b/(\S+)", text, re.M) == ["msg_hash.c", "menu/cbs/menu_cbs_ok.c"]
    for words in ('"Quit"', '"Sair"', '"Cerrar RetroArch"', "volta à lista de jogos",
                  "go back to the game list", "vuelve a la lista de juegos"):
        assert words in text, words
    # the frontend script sets the variable only when the launcher opens RetroArch
    script = (REPO_ROOT / "aports/lume-core/files/usr/libexec/lume/frontends/retroarch").read_text()
    assert "LUME_RETROARCH_QUIT=launcher" in script


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
