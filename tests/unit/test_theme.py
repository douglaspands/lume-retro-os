"""Tarefa 7.4: gerador do tema Lume (ícones, wallpaper, fonte, licenças)."""

import importlib.util
import json

import pytest
from PIL import Image

from r36os import catalog
from r36os.paths import REPO_ROOT

THEME = REPO_ROOT / "theme/lume"
CFG = json.loads((THEME / "theme.json").read_text())
LUME_CFG = (REPO_ROOT / "rootfs/overlay/usr/share/r36os/retroarch-lume.cfg").read_text()


def _gen():
    spec = importlib.util.spec_from_file_location("lume_generate", THEME / "generate.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    try:
        from r36os.theme import lucide_font

        ttf, cps = lucide_font()
    except OSError as e:  # sem rede e sem cache
        pytest.skip(f"lucide-static indisponível: {e}")
    out = tmp_path_factory.mktemp("theme")
    _gen().generate(out, ttf, cps, catalog.CATALOG, THEME)
    return out / "xmb/custom"


def test_color_for_every_system():
    ids = {s["id"] for s in catalog.load()["systems"]}
    assert ids == set(CFG["system_colors"])


def test_icon_for_every_system(generated):
    for s in catalog.load()["systems"]:
        for name in (f"{s['name']}.png", f"{s['name']}-content.png"):
            im = Image.open(generated / "png" / name)
            assert im.size == (128, 128) and im.mode == "RGBA"
            assert im.getpixel((2, 2))[3] == 0  # fora do círculo: transparente
            r, g, b, _ = im.getpixel((64, 20))  # dentro do círculo: cor do sistema
            want = tuple(int(CFG["system_colors"][s["id"]][i:i + 2], 16) for i in (1, 3, 5))
            assert max(abs(x - y) for x, y in zip((r, g, b), want)) < 8, s["id"]


def test_icon_for_every_ui_icon(generated):
    for name in CFG["ui_icons"]:
        im = Image.open(generated / "png" / f"{name}.png")
        assert im.getbbox() is not None, f"{name} vazio"


# Texturas que o XMB do RetroArch 1.22.2 carrega (menu/drivers/xmb.c, xmb_texture_path).
# Se faltar uma, o XMB marca assets_missing e não desenha ícone nenhum nem o fundo.
XMB_TEXTURES_1_22 = """
Libretro - Pad,achievement-list,add-favorite,add,arrow,battery-20,battery-40,battery-60,
battery-80,battery-charging,battery-full,bluetooth,clock,close,core-cheat-options,
core-disk-options,core-infos,core-input-remapping-options,core-options,core-shader-options,
core,cursor,database,default-content,default,dialog-slice,disc,favorites-content,favorites,
file,folder,history,image,images,input_ADC,input_BIND_ALL,input_BTN-D,input_BTN-L,input_BTN-R,
input_BTN-U,input_DPAD-D,input_DPAD-L,input_DPAD-R,input_DPAD-U,input_LB,input_LGUN,input_LT,
input_MOUSE,input_RB,input_RT,input_SELECT,input_START,input_STCK-D,input_STCK-L,input_STCK-P,
input_STCK-R,input_STCK-U,input_TURBO,key-hover,key,lakka,loadstate,menu_achievements,menu_add,
menu_apply_cog,menu_apply_toggle,menu_audio,menu_brightness,menu_check,menu_drivers,menu_exit,
menu_frameskip,menu_help,menu_info,menu_latency,menu_log,menu_mixer,menu_network,
menu_notifications,menu_osd,menu_overlay,menu_override,menu_pause,menu_playlist,menu_power,
menu_privacy,menu_quickmenu,menu_record,menu_rewind,menu_room,menu_room_lan,menu_room_relay,
menu_saving,menu_shutdown,menu_stream,menu_ui,menu_updater,menu_user,menu_video,movie,movies,
music,musics,netplay,off,on,pointer,reload,rename,resume,retroarch,run,savestate,screenshot,
setting,settings,subsetting,undo,wifi,zip
"""


def test_every_xmb_texture_present():
    want = {n.strip() for n in XMB_TEXTURES_1_22.replace("\n", "").split(",")}
    assert want - set(CFG["ui_icons"]) == set()


def test_ui_icons_cover_design():
    # D11: engrenagem, relógio (histórico), estrela (favoritos), seta e check
    ui = CFG["ui_icons"]
    assert ui["settings"] == "settings" and ui["history"] == "clock"
    assert ui["favorites"] == "star" and ui["arrow"] == "chevron-right" and ui["check"] == "check"


def test_wallpaper_and_font(generated):
    bg = Image.open(generated / "png/bg.png")
    assert bg.size == (640, 480)
    assert (generated / "font.ttf").read_bytes() == (THEME / "fonts/PlusJakartaSans-Medium.ttf").read_bytes()
    lic = generated.parent.parent / "licenses"
    assert (lic / "OFL.txt").is_file() and (lic / "LUCIDE-LICENSE.txt").is_file()


def test_lume_cfg_uses_custom_xmb_theme():
    # RetroArch 1.22: menu/menu_defines.h, XMB_ICON_THEME_CUSTOM é o 7º valor (6)
    assert 'xmb_theme = "6"' in LUME_CFG


def test_lume_cfg_points_to_theme():
    assert 'assets_directory = "/usr/share/r36os/retroarch-assets"' in LUME_CFG
    assert 'xmb_font = "/usr/share/r36os/retroarch-assets/xmb/custom/font.ttf"' in LUME_CFG
    assert 'menu_wallpaper = "/usr/share/r36os/retroarch-assets/xmb/custom/png/bg.png"' in LUME_CFG
