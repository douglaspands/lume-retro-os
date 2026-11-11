"""Fixed RetroArch configuration (retroarch-lume.cfg = system name, not a theme name)."""

import re
import subprocess

from r36os.paths import REPO_ROOT

CFG = (REPO_ROOT / "rootfs/overlay/usr/share/r36os/retroarch-lume.cfg").read_text()


def test_default_menu_and_official_assets():
    # RetroArch default menu (Ozone, official assets); no theme of our own in this change.
    assert 'menu_driver = "ozone"' in CFG
    assert 'assets_directory = "/usr/share/libretro/assets"' in CFG
    assert "xmb_" not in CFG
    packages = (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    assert "retroarch-assets" in packages
    assert not [p for p in packages if "theme" in p]


FACTORY = (REPO_ROOT / "rootfs/overlay/usr/share/r36os/factory/retroarch/retroarch.cfg").read_text()


def test_readable_on_small_screen_and_user_adjustable():
    # The scale is a factory default of the user config: in the --appendconfig file it
    # would override, on every start, what the user set in the menu.
    assert 'menu_scale_factor = "1.500000"' in FACTORY
    assert 'ozone_font_scale_factor_global = "1.200000"' in FACTORY
    assert "menu_scale_factor" not in CFG
    assert "ozone_font_scale" not in CFG
    # ozone_font_scale is numeric: "true" is read as 0 and turns the font scaling off
    assert not re.search(r'^ozone_font_scale = "(true|false)"', FACTORY, re.M)


def test_no_quit_combo_and_menu_pauses():
    assert 'input_quit_gamepad_combo = "0"' in CFG
    assert 'input_exit_emulator = "nul"' in CFG
    assert 'menu_pause_libretro = "true"' in CFG
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
    assert 'input_volume_up = "volumeup"' in CFG
    assert 'input_volume_down = "volumedown"' in CFG
    # not in the user config: there it could be lost, here it wins on every start
    assert "input_volume" not in FACTORY


def test_ga36_has_no_keyboard_enable_hotkey():
    # a keyboard enable-hotkey key blocks every keyboard hotkey (the volume buttons are
    # keyboard keys) until it is held; the GA36 has no keyboard. The VM keeps right Shift.
    assert 'input_enable_hotkey = "rshift"' in CFG
    ga36 = (SHARE / "retroarch-ga36.cfg").read_text()
    assert re.findall(r"^(\w+) = ", ga36, re.M) == ["input_enable_hotkey"]
    assert 'input_enable_hotkey = "nul"' in ga36
    assert not (SHARE / "retroarch-vm.cfg").exists()


def _appendconfig(tmp_path, board: str | None) -> str:
    """Run the frontend script with a fake retroarch and return its --appendconfig."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "retroarch"
    fake.write_text('#!/bin/sh\nwhile [ $# -gt 0 ]; do\n'
                    '  [ "$1" = --appendconfig ] && { echo "$2"; exit 0; }\n  shift\ndone\n')
    fake.chmod(0o755)
    board_file = tmp_path / "board"
    if board is not None:
        board_file.write_text(board + "\n")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(tmp_path),
           "BOARD_FILE": str(board_file), "R36OS_SHARE": str(SHARE)}
    r = subprocess.run(["sh", str(FRONTEND)], env=env, capture_output=True, text=True, check=True)
    return r.stdout.strip()


def test_frontend_appends_the_board_config_after_the_common_one(tmp_path):
    assert _appendconfig(tmp_path, "ga36") == f"{SHARE}/retroarch-lume.cfg|{SHARE}/retroarch-ga36.cfg"


def test_frontend_without_board_config_only_appends_the_common_one(tmp_path):
    assert _appendconfig(tmp_path, "vm") == f"{SHARE}/retroarch-lume.cfg"


def test_frontend_without_board_file_only_appends_the_common_one(tmp_path):
    assert _appendconfig(tmp_path, None) == f"{SHARE}/retroarch-lume.cfg"


def test_menu_has_no_transparency():
    # simple hardware: no blending of the menu over the game. In the fixed config (not the
    # user one) so that it reaches cards that already have a saved config.
    for key in ("menu_framebuffer_opacity", "menu_wallpaper_opacity", "menu_header_opacity",
                "menu_footer_opacity", "video_msg_bgcolor_opacity"):
        assert f'{key} = "1.000000"' in CFG, key
    assert 'menu_rgui_transparency = "false"' in CFG
    assert "opacity" not in FACTORY
