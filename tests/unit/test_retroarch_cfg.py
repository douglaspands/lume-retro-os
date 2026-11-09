"""Configuração fixa do RetroArch (retroarch-lume.cfg = nome do sistema, não do tema)."""

from r36os.paths import REPO_ROOT

CFG = (REPO_ROOT / "rootfs/overlay/usr/share/r36os/retroarch-lume.cfg").read_text()


def test_default_menu_and_official_assets():
    # Menu no padrão do RetroArch (Ozone, assets oficiais); sem tema próprio nesta change.
    assert 'menu_driver = "ozone"' in CFG
    assert 'assets_directory = "/usr/share/libretro/assets"' in CFG
    assert "xmb_" not in CFG
    packages = (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    assert "retroarch-assets" in packages
    assert not [p for p in packages if "theme" in p]


def test_readable_on_small_screen():
    assert 'menu_scale_factor = "1.500000"' in CFG


def test_no_quit_combo_and_menu_pauses():
    assert 'input_quit_gamepad_combo = "0"' in CFG
    assert 'input_exit_emulator = "nul"' in CFG
    assert 'menu_pause_libretro = "true"' in CFG
    # sem isto um QUIT só mostra "aperte de novo" e o console não desliga
    assert 'quit_press_twice = "false"' in CFG
