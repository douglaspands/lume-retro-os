"""Fixed RetroArch configuration (retroarch-lume.cfg = system name, not a theme name)."""

import re
import subprocess

from r36os.paths import REPO_ROOT

CFG = (REPO_ROOT / "aports/lume-retroarch-cfg/files/usr/share/r36os/retroarch-lume.cfg").read_text()


FACTORY = (REPO_ROOT / "aports/lume-retroarch-cfg/files/usr/share/r36os/factory/retroarch/retroarch.cfg").read_text()


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
    }
    assert _keys(CFG) == fixed
    # a key is either fixed or a user default, never both
    assert not _keys(CFG) & _keys(FACTORY)


def test_only_the_installed_cores_info_files_are_read():
    # 15.1: RetroArch reads every info file on each start; the image keeps only the ones of
    # the installed cores and points RetroArch there
    assert 'libretro_info_path = "/usr/share/r36os/libretro-info"' in CFG
    configure = (REPO_ROOT / "rootfs/configure.sh").read_text()
    assert "for so in /usr/lib/libretro/*_libretro.so; do" in configure
    assert "cp \"$info\" /usr/share/r36os/libretro-info/" in configure


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
    selftest_init = (REPO_ROOT / "aports/lume-diag/files/etc/init.d/r36os-selftest").read_text()
    assert 'quit_press_twice = \\"false\\"' in selftest_init or 'quit_press_twice = "false"' in selftest_init


SHARE = REPO_ROOT / "aports/lume-retroarch-cfg/files/usr/share/r36os"
FRONTEND = REPO_ROOT / "aports/lume-core/files/usr/libexec/r36os/frontends/retroarch"


def test_volume_buttons_belong_to_the_input_daemon():
    # lume-launcher D8: r36os-input grabs KEY_VOLUMEUP/DOWN and changes the system mixer in
    # any program, so RetroArch has no volume binding of the distro (fixed or factory)
    assert "input_volume" not in _keys(FACTORY)
    assert "input_volume" not in CFG
    # lume-hud-actions D9: the Fn never reaches RetroArch (r36os-input keeps it as the system
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
    assert re.findall(r"^(\w+) = ", ga36, re.M) == ["input_enable_hotkey", "video_refresh_rate"]
    assert 'input_enable_hotkey = "nul"' in ga36
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
grep -E '^(aspect_ratio_index|state_slot) ' "$cfg" | sed 's/^/during: /'
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
           "BOARD_FILE": str(board_file), "R36OS_SHARE": str(SHARE),
           "R36OS_EXTRA_CFG": str(extra_file), "LUME_RESTORE": str(tmp_path / "card/restore.cfg"),
           **(env_extra or {})}
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
    assert restore == ['aspect_ratio_index = "22"', 'state_slot = "1"']
    out, cfg, _ = _frontend(tmp_path, "ga36")
    assert 'during: aspect_ratio_index = "22"' in out and 'during: state_slot = "1"' in out
    assert cfg.count("aspect_ratio_index") == 1 and cfg.count("state_slot") == 1
    assert not (tmp_path / "card/restore.cfg").exists()


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
