"""Fixed RetroArch configuration (retroarch-lume.cfg = system name, not a theme name)."""

import re

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


def test_menu_has_no_transparency():
    # simple hardware: no blending of the menu over the game. In the fixed config (not the
    # user one) so that it reaches cards that already have a saved config.
    for key in ("menu_framebuffer_opacity", "menu_wallpaper_opacity", "menu_header_opacity",
                "menu_footer_opacity", "video_msg_bgcolor_opacity"):
        assert f'{key} = "1.000000"' in CFG, key
    assert 'menu_rgui_transparency = "false"' in CFG
    assert "opacity" not in FACTORY
