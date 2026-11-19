"""Fixed RetroArch configuration (retroarch-lume.cfg = system name, not a theme name)."""

import re
import shutil
import subprocess

from lume_tool.paths import REPO_ROOT

CFG = (REPO_ROOT / "aports/lume-retroarch-cfg/files/usr/share/lume/retroarch-lume.cfg").read_text()


FACTORY = (REPO_ROOT / "aports/lume-retroarch-cfg/files/usr/share/lume/factory/retroarch/retroarch.cfg").read_text()


def _keys(text):
    return set(re.findall(r"^(\w+) = ", text, re.M))


def test_default_menu_and_official_assets():
    # RetroArch default menu (Ozone, official assets); no theme of our own in this change.
    assert 'menu_driver = "ozone"' in FACTORY
    assert 'assets_directory = "/usr/share/libretro/assets"' in CFG
    assert "xmb_" not in CFG + FACTORY
    packages = (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    assert "retroarch-assets" in packages
    assert not [p for p in packages if "theme" in p]


def test_fixed_config_holds_only_what_keeps_the_system_working():
    # Every key in the --appendconfig file overrides the user's choice on every start, so
    # whatever the user may tune lives in the factory config (saved on the card) instead.
    fixed = {
        "video_driver", "video_context_driver", "video_fullscreen", "audio_driver",
        "input_driver", "input_joypad_driver", "input_autodetect_enable",
        "joypad_autoconfig_dir", "rgui_browser_directory", "system_directory",
        "savefile_directory", "savestate_directory", "sort_savefiles_by_content_enable",
        "sort_savestates_by_content_enable", "sort_savefiles_enable", "sort_savestates_enable",
        "screenshot_directory", "playlist_directory", "libretro_directory",
        "libretro_info_path", "assets_directory", "video_shader_dir",
        "network_cmd_enable", "network_cmd_port",
        "menu_show_core_updater", "input_menu_toggle_gamepad_combo", "input_quit_gamepad_combo",
        "quit_press_twice", "input_exit_emulator", "input_exit_emulator_btn",
        "input_exit_emulator_axis", "input_enable_hotkey", "ozone_font_scale",
        "core_info_cache_enable", "midi_driver",
        # Wi-Fi and Bluetooth by USB dongle (usb-device-access D11)
        "wifi_driver", "bluetooth_driver",
        # the launcher has its own recents (lume-launcher 15.1)
        "history_list_enable", "content_runtime_log", "content_runtime_log_aggregate",
        # the pictures of the save states and of Fn+Y (lume-hud-actions D5, D9)
        "savestate_thumbnail_enable", "video_gpu_screenshot", "auto_screenshot_filename",
        # V-Sync on at every start (user, 2026-11-17; P-25, P-91)
        "video_vsync",
        # RetroArch's own pop-ups stay off: the console speaks through Lume (device-fixes 9.8)
        "notification_show_autoconfig", "notification_show_autoconfig_fails",
        "notification_show_cheats_applied", "notification_show_patch_applied",
        "notification_show_remap_load", "notification_show_config_override_load",
        "notification_show_set_initial_disk", "notification_show_disk_control",
        "notification_show_save_state", "notification_show_fast_forward",
        "notification_show_screenshot", "notification_show_refresh_rate",
        "notification_show_netplay_extra",
        # a game of the launcher keeps the menu in the Quick Menu (patch 0013), and "Close
        # Content" there ends RetroArch, back to the game list (device-fixes 9.9; P-101 unlocks)
        "lume_menu_lock", "quit_on_close_content",
    }
    assert _keys(CFG) == fixed
    # a key is either fixed or a user default, never both
    assert not _keys(CFG) & _keys(FACTORY)


def test_only_the_installed_cores_info_files_are_read():
    # 15.1: RetroArch reads every info file on each start; the image keeps only the ones of
    # the installed cores and points RetroArch there
    assert 'libretro_info_path = "/usr/share/lume/libretro-info"' in CFG
    configure = (REPO_ROOT / "rootfs/configure.sh").read_text()
    assert "for so in /usr/lib/libretro/*_libretro.so; do" in configure
    assert "cp \"$info\" /usr/share/lume/libretro-info/" in configure


def test_user_tunable_defaults_are_in_the_factory_config():
    for key in ("menu_driver", "menu_pause_libretro", "video_threaded",
                "input_player1_b", "input_player1_a", "input_menu_toggle"):
        assert key in _keys(FACTORY), key
        assert key not in _keys(CFG), key


def test_menu_scale_default_reaches_the_ozone_cap_at_640x480():
    # KMS reports no DPI: base scale = diagonal / 1080p diagonal; Ozone caps the scale at
    # (width / 3) / 408. The factory factor must reach the cap (a smaller menu was reported
    # as too small on the device), and the cap is why higher factors change nothing.
    import math

    base = math.hypot(640, 480) / math.hypot(1920, 1080)
    cap = (640 / 3) / 408
    factor = float(re.search(r'^menu_scale_factor = "([\d.]+)"', FACTORY, re.M).group(1))
    assert base * factor >= cap
    assert round(cap / base, 2) == 1.44


def test_readable_on_small_screen_and_user_adjustable():
    # Ozone caps its layout at a third of the width (sidebar 408 px * scale <= 640 / 3), so
    # at 640x480 menu_scale_factor stops mattering at ~0.55; the text grows with the global
    # font factor, which only applies with ozone_font_scale = 1 (numeric; "true" reads as 0).
    # The mode is fixed to Global (it kept turning itself off); the factor stays the user's.
    assert re.search(r'^ozone_font_scale = "1"$', CFG, re.M)
    assert 'ozone_font_scale_factor_global = "1.200000"' in FACTORY
    assert not [k for k in _keys(CFG) if k.startswith("ozone_font_scale_factor")]
    assert "menu_scale_factor" not in _keys(CFG)
    assert not re.search(r'^ozone_font_scale = ', FACTORY, re.M)


def test_no_recurring_errors_from_core_info_cache_and_midi():
    # task 9.11: the info dir is read-only and there is no ALSA sequencer on the consoles
    assert 'core_info_cache_enable = "false"' in CFG
    assert 'midi_driver = "null"' in CFG


def test_sysctl_override_keeps_only_keys_every_kernel_has():
    # task 9.11: Alpine's 00-alpine.conf sets network and bpf keys the console kernel lacks;
    # a file of the same name in /etc/sysctl.d replaces it (OpenRC sysctl service)
    conf = (REPO_ROOT / "aports/lume-power/files/etc/sysctl.d/00-alpine.conf").read_text()
    keys = re.findall(r"^([a-z_.]+)\s*=", conf, re.M)
    assert keys == ["kernel.panic", "fs.protected_hardlinks", "fs.protected_symlinks"]


def test_menu_has_no_clock_by_default():
    # P-31 (change hide-clock): no RTC battery and no network, the clock shows 1970. A user
    # default the menu can turn back on, never a fixed key that would override that choice.
    assert 'menu_timedate_enable = "false"' in FACTORY
    assert "menu_timedate_enable" not in _keys(CFG)


def test_menu_buttons_not_swapped():
    # RetroArch 1.22 swaps OK/Cancel in the menu by default; ours: A confirms, B goes back.
    # A user default (changeable in the menu, restored by "Reset to Default Config").
    assert 'menu_swap_ok_cancel_buttons = "false"' in FACTORY
    assert "menu_swap_ok_cancel_buttons" not in _keys(CFG)


def test_every_controller_drives_the_menu():
    # usb-device-access 7.4: a USB controller is player 2 and looked dead in the menu.
    # A user default (Settings > Input), never a fixed key.
    assert 'all_users_control_menu = "true"' in FACTORY
    assert "all_users_control_menu" not in _keys(CFG)


def test_no_quit_combo_and_menu_pauses():
    assert 'input_quit_gamepad_combo = "0"' in CFG
    assert 'input_exit_emulator = "nul"' in CFG
    assert 'menu_pause_libretro = "true"' in FACTORY
    # shutting down asks for confirmation by default (patch 0002: the menu item has to be
    # selected twice); the self-test turns it off for itself because it quits with QUIT
    assert 'quit_press_twice = "true"' in CFG
    selftest_init = (REPO_ROOT / "aports/lume-diag/files/etc/init.d/lume-selftest").read_text()
    assert 'quit_press_twice = \\"false\\"' in selftest_init or 'quit_press_twice = "false"' in selftest_init


SHARE = REPO_ROOT / "aports/lume-retroarch-cfg/files/usr/share/lume"
FRONTEND = REPO_ROOT / "aports/lume-core/files/usr/libexec/lume/frontends/retroarch"


def test_volume_buttons_belong_to_the_input_daemon():
    # lume-launcher D8: lume-input grabs KEY_VOLUMEUP/DOWN and changes the system mixer in
    # any program, so RetroArch has no volume binding of the distro (fixed or factory)
    assert "input_volume" not in _keys(FACTORY)
    assert "input_volume" not in CFG
    # lume-hud-actions D9: the Fn never reaches RetroArch (lume-input keeps it as the system
    # button), so no autoconfig binds the menu to it; Start + Select is the game's
    for pad in ("R36S Gamepad.cfg", "GA36-MB Gamepad.cfg"):
        auto = (REPO_ROOT / "aports/lume-retroarch-cfg/files/usr/share/libretro/autoconfig/udev" / pad).read_text()
        assert "input_menu_toggle_btn" not in auto, pad
    assert 'input_menu_toggle_gamepad_combo = "0"' in CFG


def test_pictures_of_states_and_screenshots_are_fixed():
    # lume-hud-actions D5, D9: a picture with every save state (not only on new cards), and
    # Fn+Y saves the core's picture (no widgets) under a dated name
    for line in ('savestate_thumbnail_enable = "true"', 'video_gpu_screenshot = "false"',
                 'auto_screenshot_filename = "true"', 'screenshot_directory = "/storage/screenshots"'):
        assert line in CFG, line


def test_ga36_has_no_keyboard_enable_hotkey():
    # a keyboard enable-hotkey key blocks every keyboard hotkey (the volume buttons are
    # keyboard keys) until it is held; the GA36 has no keyboard. The VM keeps right Shift.
    assert 'input_enable_hotkey = "rshift"' in CFG
    ga36 = (SHARE / "retroarch-ga36.cfg").read_text()
    assert re.findall(r"^(\w+) = ", ga36, re.M) == ["input_enable_hotkey", "video_refresh_rate",
                                                    "video_threaded"]
    assert 'input_enable_hotkey = "nul"' in ga36
    # P-93: on the 55.69 Hz panel the video thread brings the page flips from 42-48 to 54-55
    assert 'video_threaded = "true"' in ga36
    assert 'video_threaded = "true"' in (SHARE / "retroarch-r36s.cfg").read_text()
    assert not (SHARE / "retroarch-vm.cfg").exists()


def test_ga36_refresh_rate_matches_panel_mode():
    # RetroArch assumes 60 Hz; the GA36 panel runs slower, and a wrong rate starves the
    # audio buffer (crackle). The value must follow the kernel panel mode.
    patch = (REPO_ROOT / "kernel/patches/0005-drm-panel-add-GA36-MB-JD9366-panels.patch").read_text()
    mode = patch.split("jd9366_mode = {", 1)[1].split("};", 1)[0]
    field = {k: int(v) for k, v in re.findall(r"\.(clock|htotal|vtotal) = (\d+)", mode)}
    hz = field["clock"] * 1000 / (field["htotal"] * field["vtotal"])
    ga36 = (SHARE / "retroarch-ga36.cfg").read_text()
    value = float(re.search(r'^video_refresh_rate = "([\d.]+)"', ga36, re.M).group(1))
    assert abs(value - hz) < 1e-5


def test_r36s_refresh_rate_matches_panel_mode():
    # the R36S panel mode is in the ST7703 variant (kernel patch 0010)
    patch = (REPO_ROOT / "kernel/patches/0010-drm-panel-sitronix-st7703-add-R36S-V5-panel.patch").read_text()
    mode = patch.split("r36s_v5_mode = {", 1)[1].split("};", 1)[0]
    field = {k: eval(v, {"__builtins__": {}})  # noqa: S307 (numbers and + only)
             for k, v in re.findall(r"\+\s*\.(clock|htotal|vtotal)\s*= ([0-9 +]+),", mode)}
    hz = field["clock"] * 1000 / (field["htotal"] * field["vtotal"])
    r36s = (SHARE / "retroarch-r36s.cfg").read_text()
    value = float(re.search(r'^video_refresh_rate = "([\d.]+)"', r36s, re.M).group(1))
    assert abs(value - hz) < 1e-5 and round(value, 2) == 59.02


def test_fixed_keys_are_the_same_on_both_consoles():
    # frontend-session (single card): a key fixed for one console must have a fixed value on
    # the other, or the value written on one card start would leak to the other console
    keys = {board: set(re.findall(r"^(\w+) = ", (SHARE / f"retroarch-{board}.cfg").read_text(), re.M))
            for board in ("ga36", "r36s")}
    assert keys["ga36"] == keys["r36s"], keys
    consoles = {p.stem.removeprefix("retroarch-") for p in SHARE.glob("retroarch-*.cfg")} - {"lume"}
    assert consoles == {"ga36", "r36s"}


def test_single_card_each_console_gets_its_own_refresh_rate(tmp_path):
    # the same user config on the ROMS, started on the GA36, the R36S and the GA36 again
    _, cfg, _ = _frontend(tmp_path, "ga36", 'user_language = "4"\n')
    assert 'video_refresh_rate = "55.687557"' in cfg
    _, cfg, _ = _frontend(tmp_path, "r36s")
    assert 'video_refresh_rate = "59.021554"' in cfg and "55.687557" not in cfg
    assert 'user_language = "4"' in cfg                     # the user's choice goes along
    _, cfg, _ = _frontend(tmp_path, "ga36")
    assert 'video_refresh_rate = "55.687557"' in cfg and "59.021554" not in cfg


FAKE_RETROARCH = """#!/bin/sh
echo "$@"
echo "defaults=$LUME_RETROARCH_DEFAULTS"
echo "quit=$LUME_RETROARCH_QUIT"
cfg=$(echo "$@" | sed 's/.*--config \\([^ ]*\\).*/\\1/')
grep -E '^(aspect_ratio_index|state_slot|video_threaded|content_show_settings|menu_show_load_core) ' "$cfg" | sed 's/^/during: /'
# what RetroArch does with -e: the slot becomes the current one, saved with the config
case " $* " in *" -e "*) echo 'state_slot = "3"' >> "$cfg" ;; esac
[ -n "$FAKE_DIE" ] && kill -KILL $PPID
exit 0
"""


def _frontend(tmp_path, board: str | None, user_cfg: str | None = None, extra: str | None = None,
              args: tuple[str, ...] = (), env_extra: dict | None = None, check: bool = True):
    """Run the frontend script with a fake retroarch. Returns (args, user cfg, defaults cfg)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "retroarch"
    fake.write_text(FAKE_RETROARCH)
    fake.chmod(0o755)
    board_file = tmp_path / "board"
    if board is not None:
        board_file.write_text(board + "\n")
    home = tmp_path / "home"
    cfg = home / ".config/retroarch/retroarch.cfg"
    if user_cfg is not None:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text(user_cfg)
    run_dir = tmp_path / "run"
    run_dir.mkdir(exist_ok=True)
    extra_file = tmp_path / "extra.cfg"
    if extra is not None:
        extra_file.write_text(extra)
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(home), "XDG_RUNTIME_DIR": str(run_dir),
           "BOARD_FILE": str(board_file), "LUME_SHARE": str(SHARE),
           "LUME_EXTRA_CFG": str(extra_file), "LUME_RESTORE": str(tmp_path / "card/restore.cfg"),
           "LUME_INFO": str(tmp_path / "info"), **(env_extra or {})}
    r = subprocess.run(["sh", str(FRONTEND), *args], env=env, capture_output=True, text=True,
                       check=check)
    defaults = run_dir / "retroarch-defaults.cfg"
    return r.stdout, cfg.read_text(), defaults.read_text() if defaults.exists() else None


def test_frontend_writes_fixed_keys_into_the_user_config_without_appendconfig(tmp_path):
    # --appendconfig made RetroArch reload the config from disk on every core init (opening
    # and closing a game), throwing away menu changes not yet saved
    user = ('menu_scale_factor = "0.800000"\nvideo_driver = "vulkan"\n'
            'ozone_font_scale = "0"\nozone_font_scale_factor_global = "1.500000"\n')
    args, cfg, _ = _frontend(tmp_path, "ga36", user)
    assert "--appendconfig" not in args and "--config" in args
    lines = cfg.splitlines()
    assert 'menu_scale_factor = "0.800000"' in lines             # user choice kept
    assert 'ozone_font_scale_factor_global = "1.500000"' in lines
    assert 'video_driver = "gl"' in lines and 'video_driver = "vulkan"' not in lines
    assert 'ozone_font_scale = "1"' in lines and 'ozone_font_scale = "0"' not in lines
    assert lines.index('video_driver = "gl"') == 1               # replaced in place
    assert 'input_enable_hotkey = "nul"' in lines                # the board file wins
    assert 'video_refresh_rate = "55.687557"' in lines
    assert sum(1 for line in lines if line.startswith("input_enable_hotkey ")) == 1


def test_frontend_merge_is_stable_across_starts(tmp_path):
    _, first, _ = _frontend(tmp_path, "ga36", 'menu_driver = "xmb"\n')
    _, second, _ = _frontend(tmp_path, "ga36")
    assert first == second


def test_frontend_without_board_config_uses_only_the_common_keys(tmp_path):
    _, cfg, _ = _frontend(tmp_path, "vm", "")
    assert 'input_enable_hotkey = "rshift"' in cfg and "video_refresh_rate" not in cfg


def test_frontend_without_board_file_or_user_config(tmp_path):
    _, cfg, _ = _frontend(tmp_path, None)
    assert 'video_driver = "gl"' in cfg and 'input_enable_hotkey = "rshift"' in cfg


def test_frontend_extra_config_wins_last(tmp_path):
    _, cfg, _ = _frontend(tmp_path, "ga36", "", extra='quit_press_twice = "false"\n')
    assert 'quit_press_twice = "false"' in cfg and 'quit_press_twice = "true"' not in cfg


def test_reset_defaults_are_the_factory_config_with_the_fixed_keys(tmp_path):
    # RetroArch patch 0006: "Reset to Default Config" loads $LUME_RETROARCH_DEFAULTS
    args, _, defaults = _frontend(tmp_path, "ga36", 'ozone_font_scale_factor_global = "2.000000"\n')
    assert f"defaults={tmp_path}/run/retroarch-defaults.cfg" in args
    assert 'ozone_font_scale_factor_global = "1.200000"' in defaults   # factory, not the user's
    assert "input_volume" not in defaults
    assert 'ozone_font_scale = "1"' in defaults and 'video_refresh_rate = "55.687557"' in defaults


RUN_ARGS = ("--lume-set", "aspect_ratio_index=1", "--lume-keep", "state_slot",
            "-L", "/usr/lib/libretro/x_libretro.so", "-e", "3", "/storage/roms/snes/a b.sfc")


def test_run_only_keys_go_back_when_retroarch_ends(tmp_path):
    # lume-launcher D7: the aspect of one game and the slot of -e never become the user's
    out, cfg, _ = _frontend(tmp_path, "ga36", 'aspect_ratio_index = "22"\nmenu_driver = "ozone"\n',
                            args=RUN_ARGS)
    assert 'during: aspect_ratio_index = "1"' in out
    args = out.splitlines()[0]
    assert "--lume-set" not in args and "--lume-keep" not in args
    assert args.endswith("-L /usr/lib/libretro/x_libretro.so -e 3 /storage/roms/snes/a b.sfc")
    lines = cfg.splitlines()
    assert 'aspect_ratio_index = "22"' in lines and 'aspect_ratio_index = "1"' not in lines
    assert not [line for line in lines if line.startswith("state_slot")]   # the user had none
    assert 'menu_driver = "ozone"' in lines
    assert not (tmp_path / "card/restore.cfg").exists()


def test_run_only_keys_go_back_after_a_kill(tmp_path):
    # Fn+Start that ends in cgroup.kill: the script dies with RetroArch; the next start
    # (any start, with or without the launcher) puts the user's values back
    user = 'aspect_ratio_index = "22"\nstate_slot = "1"\n'
    _frontend(tmp_path, "ga36", user, args=RUN_ARGS, env_extra={"FAKE_DIE": "1"}, check=False)
    restore = (tmp_path / "card/restore.cfg").read_text().splitlines()
    # then the keys every game hides (retroarch-core.keys "*"), which this user never set
    assert restore[:2] == ['aspect_ratio_index = "22"', 'state_slot = "1"']
    assert restore[2:] == [f"#unset {k}" for k in MENU_LOCK_HIDDEN]
    out, cfg, _ = _frontend(tmp_path, "ga36")
    assert 'during: aspect_ratio_index = "22"' in out and 'during: state_slot = "1"' in out
    assert cfg.count("aspect_ratio_index") == 1 and cfg.count("state_slot") == 1
    assert not (tmp_path / "card/restore.cfg").exists()


def test_core_keys_count_for_that_core_only_and_go_back(tmp_path):
    # retroarch-core.keys (game-governor, 2026-11-18): the PlayStation core keeps the video
    # in the main thread (a crash after a resolution change with the video thread)
    psx = ("-L", "/usr/lib/libretro/pcsx_rearmed_libretro.so", "/storage/roms/psx/x.chd")
    out, cfg, _ = _frontend(tmp_path, "ga36", "", args=psx)
    assert 'during: video_threaded = "false"' in out
    assert 'video_threaded = "true"' in cfg.splitlines()         # the board's value comes back
    assert not (tmp_path / "card/restore.cfg").exists()
    snes = ("-L", "/usr/lib/libretro/snes9x2005_plus_libretro.so", "/storage/roms/snes/x.sfc")
    out, cfg, _ = _frontend(tmp_path, "ga36", "", args=snes)
    assert 'during: video_threaded = "true"' in out
    keys = (SHARE / "retroarch-core.keys").read_text()
    assert "pcsx_rearmed video_threaded=false" in keys
    assert not any(ord(c) > 127 for c in keys)


def _share_with_keys(tmp_path, keys: str):
    share = tmp_path / "share"
    shutil.copytree(SHARE, share)
    (share / "retroarch-core.keys").write_text(keys)
    return {"LUME_SHARE": str(share)}


CONSOLE_KEYS = """# test keys
* video_threaded=all
pcsx_rearmed video_threaded=core
ga36:* video_threaded=ga36_all
ga36:pcsx_rearmed video_threaded=ga36_core
ga36:* content_show_settings=ga36_only
foo:* content_show_settings=unknown_console
ga36:snes video_threaded=ga36_other_core
"""
PSX = ("-L", "/usr/lib/libretro/pcsx_rearmed_libretro.so", "/storage/roms/psx/x.chd")
SNES = ("-L", "/usr/lib/libretro/snes_libretro.so", "/storage/roms/snes/x.sfc")


def test_console_keys_priority_is_star_core_board_star_board_core(tmp_path):
    env = _share_with_keys(tmp_path, CONSOLE_KEYS)
    out, _, _ = _frontend(tmp_path, "ga36", "", args=PSX, env_extra=env)
    assert 'during: video_threaded = "ga36_core"' in out
    assert 'during: content_show_settings = "ga36_only"' in out
    # without the board:core line the board:* one beats the core and "*"
    out, _, _ = _frontend(tmp_path, "ga36", "", args=("-L", "/x/other_libretro.so", "g"), env_extra=env)
    assert 'during: video_threaded = "ga36_all"' in out
    # a line of another core of the same console is not applied
    out, _, _ = _frontend(tmp_path, "ga36", "", args=PSX, env_extra=env)
    assert "ga36_other_core" not in out


def test_console_only_keys_do_not_apply_on_other_consoles(tmp_path):
    env = _share_with_keys(tmp_path, CONSOLE_KEYS)
    out, cfg, _ = _frontend(tmp_path, "r36s", "", args=PSX, env_extra=env)
    assert 'during: video_threaded = "core"' in out
    assert "content_show_settings" not in out and "ga36_" not in out
    out, _, _ = _frontend(tmp_path, "r36s", "", args=SNES, env_extra=env)
    assert 'during: video_threaded = "all"' in out
    # unknown console in the board file: only "*" and the core lines count
    out, _, _ = _frontend(tmp_path, "vm", "", args=PSX, env_extra=env)
    assert 'during: video_threaded = "core"' in out and "ga36_" not in out


def test_console_keys_user_value_comes_back_once(tmp_path):
    env = _share_with_keys(tmp_path, CONSOLE_KEYS)
    _, cfg, _ = _frontend(tmp_path, "ga36", 'content_show_settings = "true"\n',
                          args=PSX, env_extra=env)
    lines = cfg.splitlines()
    # the user's own key is back; the board's fixed key (not the run's) is back for the other
    assert 'content_show_settings = "true"' in lines and 'video_threaded = "true"' in lines
    assert sum(1 for line in lines if line.startswith("video_threaded")) == 1
    assert not (tmp_path / "card/restore.cfg").exists()


def test_shipped_core_keys_keep_pcsx_rearmed_threaded_off_on_both_consoles(tmp_path):
    for board in ("ga36", "r36s"):
        out, _, _ = _frontend(tmp_path, board, "", args=PSX)
        assert 'during: video_threaded = "false"' in out


MENU_LOCK_HIDDEN = {
    "menu_show_load_core": "false", "menu_show_load_content": "false",
    "menu_show_online_updater": "false", "menu_show_information": "false",
    "menu_show_configurations": "false", "menu_show_help": "false",
    "menu_show_restart_retroarch": "false", "menu_show_quit_retroarch": "false",
    "content_show_settings": "false", "content_show_history": "false",
    "content_show_favorites": "false", "content_show_images": "false",
    "content_show_music": "false", "content_show_video": "false",
    "content_show_netplay": "false", "content_show_add_entry": "0",
    "content_show_explore": "false", "content_show_contentless_cores": "0",
    "content_show_playlists": "false", "content_show_playlist_tabs": "false",
}


def test_game_menu_is_locked_to_the_quick_menu():
    # device-fixes 9.9 (the user, 2026-11-18): during a game only the Quick Menu (patch 0013),
    # and its "Close Content" ends RetroArch when the game came on the command line (2 = CLI)
    assert 'lume_menu_lock = "true"' in CFG
    assert 'quit_on_close_content = "2"' in CFG
    # the second barrier: every game run hides the main-menu items and the sidebar tabs
    keys = (SHARE / "retroarch-core.keys").read_text()
    every = dict(kv.split("=", 1) for kv in re.findall(r"^\* (\S+)$", keys, re.M))
    assert every == MENU_LOCK_HIDDEN
    # user settings stay out of the fixed and factory configs (the menu without a game)
    assert not set(MENU_LOCK_HIDDEN) & (_keys(CFG) | _keys(FACTORY))


def test_game_runs_hide_the_main_menu_and_the_menu_alone_keeps_it(tmp_path):
    # the "*" keys count for a game run (-L) and the user's values come back after it
    game = ("-L", "/usr/lib/libretro/snes9x2005_plus_libretro.so", "/storage/roms/snes/x.sfc")
    out, cfg, _ = _frontend(tmp_path, "ga36", 'content_show_settings = "true"\n', args=game,
                            env_extra={"LUME_LAUNCHER": "1"})
    assert 'during: content_show_settings = "false"' in out
    assert 'during: menu_show_load_core = "false"' in out
    lines = cfg.splitlines()
    assert 'content_show_settings = "true"' in lines
    assert not [line for line in lines if line.startswith("menu_show_load_core")]
    assert not (tmp_path / "card/restore.cfg").exists()
    # launcher Settings > RetroArch menu: no -L, nothing hidden
    out, cfg, _ = _frontend(tmp_path, "ga36", env_extra={"LUME_LAUNCHER": "1"})
    assert 'during: content_show_settings = "true"' in out
    assert "menu_show_load_core" not in out
    # a core of its own keeps its keys along with the "*" ones
    psx = ("-L", "/usr/lib/libretro/pcsx_rearmed_libretro.so", "/storage/roms/psx/x.chd")
    out, _, _ = _frontend(tmp_path, "ga36", args=psx)
    assert 'during: video_threaded = "false"' in out
    assert 'during: content_show_settings = "false"' in out


def test_without_launcher_keys_nothing_changes(tmp_path):
    out, cfg, _ = _frontend(tmp_path, "ga36", 'aspect_ratio_index = "22"\n')
    assert 'during: aspect_ratio_index = "22"' in out and "quit=" in out.splitlines()
    assert not (tmp_path / "card/restore.cfg").exists()
    # opened by the launcher: RetroArch is told that quitting goes back to it (patch 0010)
    out, _, _ = _frontend(tmp_path, "ga36", env_extra={"LUME_LAUNCHER": "1"})
    assert "quit=launcher" in out.splitlines()


def test_start_select_opens_the_menu_only_as_the_reserve_frontend(tmp_path):
    # lume-hud-actions D9: under the launcher Start + Select is the game's (lume-run opens the
    # menu with Fn+B); as the reserve frontend nothing else could open it in a game
    _, cfg, _ = _frontend(tmp_path, "ga36", "", env_extra={"LUME_LAUNCHER": "1"})
    assert 'input_menu_toggle_gamepad_combo = "0"' in cfg.splitlines()
    _, cfg, _ = _frontend(tmp_path, "ga36")
    lines = cfg.splitlines()
    assert 'input_menu_toggle_gamepad_combo = "4"' in lines
    assert sum(1 for line in lines if line.startswith("input_menu_toggle_gamepad_combo")) == 1


def test_no_retroarch_screens_around_a_game_of_the_launcher(tmp_path):
    # the user (2026-11-17): no load animation with the system and the game name, no "press
    # again to quit"; lume-run sends one QUIT. The reserve frontend keeps the confirmation
    _, cfg, _ = _frontend(tmp_path, "ga36", "", env_extra={"LUME_LAUNCHER": "1"})
    lines = cfg.splitlines()
    assert 'menu_show_load_content_animation = "false"' in lines
    assert 'quit_press_twice = "false"' in lines and 'quit_press_twice = "true"' not in lines
    _, cfg, _ = _frontend(tmp_path, "ga36")
    assert 'quit_press_twice = "true"' in cfg.splitlines()


def test_menu_has_no_transparency():
    # simple hardware: no blending of the menu over the game, as a factory default (cards
    # with a saved config already have these values: RetroArch saved them)
    for key in ("menu_framebuffer_opacity", "menu_wallpaper_opacity", "menu_header_opacity",
                "menu_footer_opacity", "video_msg_bgcolor_opacity"):
        assert f'{key} = "1.000000"' in FACTORY, key
    assert 'menu_rgui_transparency = "false"' in FACTORY
    assert "opacity" not in CFG


# --- new factory defaults on existing cards (game-experience-tuning D3, task 1.2) ---

FACTORY_KEYS = _keys(FACTORY)
CORENAMES_FIXTURE = REPO_ROOT / "tests/fixtures/libretro-corenames.txt"
FACTORY_OPT_DIR = SHARE / "factory/retroarch/config"


def _corenames() -> dict[str, str]:
    """core -> corename of its .info (tests/fixtures/libretro-corenames.txt)."""
    text = CORENAMES_FIXTURE.read_text()
    return dict(re.findall(r'^(\w+) = "([^"]+)"$', text, re.M))


def _factory_line(key: str) -> str:
    return re.search(rf"^{key} = .*$", FACTORY, re.M).group(0)


def test_missing_factory_key_is_added_and_the_users_never_change(tmp_path):
    # a card from before a new factory default: the key it lacks arrives with the factory
    # value, a factory key the user already has keeps the user's value
    user = 'menu_driver = "xmb"\nmenu_timedate_enable = "true"\nmy_own_key = "1"\n'
    _, cfg, _ = _frontend(tmp_path, "ga36", user)
    lines = cfg.splitlines()
    assert lines[:3] == ['menu_driver = "xmb"', 'menu_timedate_enable = "true"', 'my_own_key = "1"']
    assert _keys(cfg) >= FACTORY_KEYS
    assert sum(1 for line in lines if line.startswith("menu_driver ")) == 1
    assert 'menu_timedate_enable = "false"' not in lines
    assert _factory_line("menu_swap_ok_cancel_buttons") in lines


def test_seeding_is_stable_and_keeps_the_users_choice_across_starts(tmp_path):
    _, first, _ = _frontend(tmp_path, "r36s", 'all_users_control_menu = "false"\n')
    _, second, _ = _frontend(tmp_path, "r36s")
    assert first == second
    assert 'all_users_control_menu = "false"' in second.splitlines()
    assert 'all_users_control_menu = "true"' not in second


def test_factory_key_of_a_run_the_user_never_had_gets_the_factory_value(tmp_path):
    # video_threaded is a factory key and a run key of pcsx_rearmed; a run killed on an image
    # from before the seeding left "#unset video_threaded" (the user had none): the restore
    # removes it, then the seeding gives the factory value (vm: no board value)
    (tmp_path / "card").mkdir()
    (tmp_path / "card/restore.cfg").write_text("#unset video_threaded\n")
    out, cfg, _ = _frontend(tmp_path, "vm", 'video_threaded = "true"\n')
    assert not (tmp_path / "card/restore.cfg").exists()
    assert f"during: {_factory_line('video_threaded')}" in out
    assert cfg.count("video_threaded") == 1


def _opt_env(tmp_path, opts: dict[str, str], cores: dict[str, str] | None = None,
             info_text=None) -> dict:
    """A share with factory .opt files ({corename: text}) and .info files for the cores."""
    share = tmp_path / "share"
    if not share.exists():
        shutil.copytree(SHARE, share)
    for name, text in opts.items():
        d = share / "factory/retroarch/config" / name
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{name}.opt").write_text(text)
    info = tmp_path / "info"
    info.mkdir(exist_ok=True)
    for core, name in (cores if cores is not None else _corenames()).items():
        body = info_text(name) if info_text else f'display_name = "x"\ncorename = "{name}"\n'
        (info / f"{core}_libretro.info").write_text(body)
    return {"LUME_SHARE": str(share), "LUME_INFO": str(info)}


GPGX = ("-L", "/usr/lib/libretro/genesis_plus_gx_libretro.so", "/storage/roms/megadrive/x.md")
GPGX_OPT = 'genesis_plus_gx_ym2612 = "nuked (ym2612)"\ngenesis_plus_gx_audio_filter = "low-pass"\n'


def _user_opt(tmp_path, name="Genesis Plus GX"):
    return tmp_path / "home/.config/retroarch/config" / name / f"{name}.opt"


def test_core_options_file_that_does_not_exist_is_born_equal_to_the_factory(tmp_path):
    env = _opt_env(tmp_path, {"Genesis Plus GX": GPGX_OPT})
    _frontend(tmp_path, "ga36", "", args=GPGX, env_extra=env)
    assert _user_opt(tmp_path).read_text() == GPGX_OPT
    assert not list(_user_opt(tmp_path).parent.glob("*.tmp.*"))


def test_users_core_option_stays_and_the_missing_ones_arrive(tmp_path):
    env = _opt_env(tmp_path, {"Genesis Plus GX": GPGX_OPT})
    opt = _user_opt(tmp_path)
    opt.parent.mkdir(parents=True)
    opt.write_text('genesis_plus_gx_ym2612 = "mame (ym2612)"\ngenesis_plus_gx_bram = "per game"\n')
    _frontend(tmp_path, "ga36", "", args=GPGX, env_extra=env)
    assert opt.read_text().splitlines() == [
        'genesis_plus_gx_ym2612 = "mame (ym2612)"', 'genesis_plus_gx_bram = "per game"',
        'genesis_plus_gx_audio_filter = "low-pass"']
    # complete now: the next game leaves the file alone (same inode, not rewritten)
    before = opt.stat()
    _frontend(tmp_path, "ga36", args=GPGX, env_extra=env)
    after = opt.stat()
    assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)


def test_core_options_only_for_the_core_of_the_run(tmp_path):
    env = _opt_env(tmp_path, {"Genesis Plus GX": GPGX_OPT, "PCSX-ReARMed": 'pcsx_rearmed_x = "1"\n'})
    _frontend(tmp_path, "ga36", "", args=GPGX, env_extra=env)
    assert _user_opt(tmp_path).exists()
    assert not _user_opt(tmp_path, "PCSX-ReARMed").exists()
    # the menu without a game (no -L) touches no core options
    _frontend(tmp_path, "ga36", env_extra=env)
    assert not _user_opt(tmp_path, "PCSX-ReARMed").exists()
    # a core without factory options or without a .info gets nothing
    snes = ("-L", "/usr/lib/libretro/snes9x2005_plus_libretro.so", "/storage/roms/snes/x.sfc")
    _frontend(tmp_path, "ga36", args=snes, env_extra=env)
    assert not (tmp_path / "home/.config/retroarch/config/Snes9x 2005 Plus").exists()
    (tmp_path / "b").mkdir()
    env_no_info = _opt_env(tmp_path / "b", {"Genesis Plus GX": GPGX_OPT}, cores={})
    _frontend(tmp_path / "b", "ga36", "", args=GPGX, env_extra=env_no_info)
    assert not _user_opt(tmp_path / "b").exists()


def test_corename_is_read_with_any_spacing(tmp_path):
    for i, fmt in enumerate(('corename="{}"\n', 'corename\t=\t"{}"  \n', 'corename = {}\n')):
        base = tmp_path / str(i)
        base.mkdir()
        env = _opt_env(base, {"Genesis Plus GX": GPGX_OPT}, cores={"genesis_plus_gx": "Genesis Plus GX"},
                       info_text=lambda name, fmt=fmt: f'display_name = "corename"\n{fmt.format(name)}')
        _frontend(base, "ga36", "", args=GPGX, env_extra=env)
        assert _user_opt(base).read_text() == GPGX_OPT, fmt


def test_corename_fixture_covers_every_installed_core():
    # the core files of the libretro-* packages (package name with "_" for "-")
    packages = (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    cores = {p.removeprefix("libretro-").replace("-", "_") for p in packages
             if p.startswith("libretro-") and p != "libretro-core-info"}
    assert cores == set(_corenames())


def test_factory_option_folders_are_corenames_of_installed_cores():
    # RetroArch looks for config/<corename>/<corename>.opt; a folder with another name would
    # never be seeded. No factory options yet (task 8.1 adds them): the check still runs
    names = set(_corenames().values())
    folders = sorted(p for p in FACTORY_OPT_DIR.iterdir()) if FACTORY_OPT_DIR.exists() else []
    for folder in folders:
        assert folder.is_dir() and folder.name in names, folder.name
        assert [p.name for p in folder.iterdir()] == [f"{folder.name}.opt"], folder.name
        text = folder.joinpath(f"{folder.name}.opt").read_text()
        assert all(re.match(r'^\w+ = ".*"$', line) for line in text.splitlines()), folder.name


def test_shipped_factory_options_reach_the_user_through_the_frontend(tmp_path):
    # every shipped factory .opt is found through the corename of its core's .info
    env = _opt_env(tmp_path, {})
    by_name = {name: core for core, name in _corenames().items()}
    folders = sorted(FACTORY_OPT_DIR.iterdir()) if FACTORY_OPT_DIR.exists() else []
    for folder in folders:
        core = by_name[folder.name]
        args = ("-L", f"/usr/lib/libretro/{core}_libretro.so", "/storage/roms/x/game")
        _frontend(tmp_path, "ga36", "", args=args, env_extra=env)
        user = _user_opt(tmp_path, folder.name)
        assert user.read_text() == (folder / f"{folder.name}.opt").read_text()
