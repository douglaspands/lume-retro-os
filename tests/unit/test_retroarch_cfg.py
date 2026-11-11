"""Fixed RetroArch configuration (retroarch-lume.cfg = system name, not a theme name)."""

import re
import subprocess

from r36os.paths import REPO_ROOT

CFG = (REPO_ROOT / "rootfs/overlay/usr/share/r36os/retroarch-lume.cfg").read_text()


FACTORY = (REPO_ROOT / "rootfs/overlay/usr/share/r36os/factory/retroarch/retroarch.cfg").read_text()


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
        "libretro_info_path", "assets_directory", "network_cmd_enable", "network_cmd_port",
        "menu_show_core_updater", "input_menu_toggle_gamepad_combo", "input_quit_gamepad_combo",
        "quit_press_twice", "input_exit_emulator", "input_exit_emulator_btn",
        "input_exit_emulator_axis", "input_enable_hotkey", "ozone_font_scale",
        "core_info_cache_enable", "midi_driver",
    }
    assert _keys(CFG) == fixed
    # a key is either fixed or a user default, never both
    assert not _keys(CFG) & _keys(FACTORY)


def test_user_tunable_defaults_are_in_the_factory_config():
    for key in ("menu_driver", "menu_pause_libretro", "video_vsync", "video_threaded",
                "input_volume_up", "input_player1_a", "input_menu_toggle"):
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
    conf = (REPO_ROOT / "rootfs/overlay/etc/sysctl.d/00-alpine.conf").read_text()
    keys = re.findall(r"^([a-z_.]+)\s*=", conf, re.M)
    assert keys == ["kernel.panic", "fs.protected_hardlinks", "fs.protected_symlinks"]


def test_menu_buttons_not_swapped():
    # RetroArch 1.22 swaps OK/Cancel in the menu by default; ours: A confirms, B goes back.
    # A user default (changeable in the menu, restored by "Reset to Default Config").
    assert 'menu_swap_ok_cancel_buttons = "false"' in FACTORY
    assert "menu_swap_ok_cancel_buttons" not in _keys(CFG)


def test_no_quit_combo_and_menu_pauses():
    assert 'input_quit_gamepad_combo = "0"' in CFG
    assert 'input_exit_emulator = "nul"' in CFG
    assert 'menu_pause_libretro = "true"' in FACTORY
    # shutting down asks for confirmation by default (patch 0002: the menu item has to be
    # selected twice); the self-test turns it off for itself because it quits with QUIT
    assert 'quit_press_twice = "true"' in CFG
    selftest_init = (REPO_ROOT / "rootfs/overlay/etc/init.d/r36os-selftest").read_text()
    assert 'quit_press_twice = \\"false\\"' in selftest_init or 'quit_press_twice = "false"' in selftest_init


SHARE = REPO_ROOT / "rootfs/overlay/usr/share/r36os"
FRONTEND = REPO_ROOT / "rootfs/overlay/usr/libexec/r36os/frontends/retroarch"


def test_volume_buttons_are_bound():
    # the volume buttons are KEY_VOLUMEUP/DOWN, "volumeup"/"volumedown" in RetroArch;
    # upstream binds volume to the keypad +/-
    assert 'input_volume_up = "volumeup"' in FACTORY
    assert 'input_volume_down = "volumedown"' in FACTORY
    # a user default (rebindable in the menu), not forced on every start
    assert "input_volume" not in CFG


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


def _frontend(tmp_path, board: str | None, user_cfg: str | None = None, extra: str | None = None):
    """Run the frontend script with a fake retroarch. Returns (args, user cfg, defaults cfg)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    fake = bin_dir / "retroarch"
    fake.write_text('#!/bin/sh\necho "$@"\necho "defaults=$LUME_RETROARCH_DEFAULTS"\n')
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
           "R36OS_EXTRA_CFG": str(extra_file)}
    r = subprocess.run(["sh", str(FRONTEND)], env=env, capture_output=True, text=True, check=True)
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
    assert 'input_volume_up = "volumeup"' in defaults
    assert 'ozone_font_scale = "1"' in defaults and 'video_refresh_rate = "55.687557"' in defaults


def test_menu_has_no_transparency():
    # simple hardware: no blending of the menu over the game, as a factory default (cards
    # with a saved config already have these values: RetroArch saved them)
    for key in ("menu_framebuffer_opacity", "menu_wallpaper_opacity", "menu_header_opacity",
                "menu_footer_opacity", "video_msg_bgcolor_opacity"):
        assert f'{key} = "1.000000"' in FACTORY, key
    assert 'menu_rgui_transparency = "false"' in FACTORY
    assert "opacity" not in CFG
