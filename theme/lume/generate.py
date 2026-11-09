#!/usr/bin/env python3
"""Gera os assets do tema Lume para o XMB do RetroArch (D11).

    generate.py --out <dir> --lucide <lucide.ttf> --codepoints <codepoints.json> \
                --catalog <systems.json> [--theme <dir de theme/lume>]

Saída (relativa a --out):
    xmb/custom/png/<Nome do sistema>.png e <Nome>-content.png   ícones redondos
    xmb/custom/png/<ícone de interface>.png                     Lucide em branco
    xmb/custom/png/bg.png                                       Aurora 640x480
    xmb/custom/font.ttf                                         Plus Jakarta Sans Medium
    licenses/OFL.txt, licenses/LUCIDE-LICENSE.txt

Usa só a biblioteca padrão e o Pillow (py3-pillow no Alpine).
"""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
SS = 4  # superamostragem para bordas suaves


def hex_rgb(c: str) -> tuple[int, int, int]:
    c = c.lstrip("#")
    return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def system_icon(name: str, color: str, font_path: Path, px: int) -> Image.Image:
    """Círculo colorido com a inicial do nome em Plus Jakarta Sans ExtraBold branca."""
    big = px * SS
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.ellipse((0, 0, big - 1, big - 1), fill=hex_rgb(color) + (255,))
    font = ImageFont.truetype(str(font_path), int(big * 0.56))
    initial = name.strip()[0].upper()
    d.text((big / 2, big / 2), initial, font=font, fill=(255, 255, 255, 255), anchor="mm")
    return im.resize((px, px), Image.LANCZOS)


def lucide_icon(codepoint: int, font: ImageFont.FreeTypeFont, px: int) -> Image.Image:
    big = px * SS
    im = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((big / 2, big / 2), chr(codepoint), font=font,
                            fill=(255, 255, 255, 255), anchor="mm")
    return im.resize((px, px), Image.LANCZOS)


def wallpaper(master: Path, w: int, h: int, band_px: int, band_alpha: int) -> Image.Image:
    """Recorte central 4:3 do Aurora, 640x480, com uma faixa escura sutil no topo."""
    im = Image.open(master).convert("RGB")
    sw, sh = im.size
    cw = min(sw, sh * w // h)
    ch = cw * h // w
    left, top = (sw - cw) // 2, (sh - ch) // 2
    im = im.crop((left, top, left + cw, top + ch)).resize((w, h), Image.LANCZOS)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for y in range(band_px):
        a = int(band_alpha * (1 - y / band_px))
        od.line([(0, y), (w, y)], fill=(0, 0, 0, a))
    return Image.alpha_composite(im.convert("RGBA"), overlay).convert("RGB")


def generate(out: Path, lucide: Path, codepoints: Path, catalog: Path, theme: Path = HERE) -> list[Path]:
    cfg = json.loads((theme / "theme.json").read_text())
    cat = json.loads(catalog.read_text())
    cps = json.loads(codepoints.read_text())
    px = cfg["icon_px"]
    png = out / "xmb/custom/png"
    png.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    extrabold = theme / "fonts/PlusJakartaSans-ExtraBold.ttf"
    for s in cat["systems"]:
        color = cfg["system_colors"][s["id"]]
        icon = system_icon(s["name"], color, extrabold, px)
        for fname in (f"{s['name']}.png", f"{s['name']}-content.png"):
            icon.save(png / fname, optimize=True)
            written.append(png / fname)

    lfont = ImageFont.truetype(str(lucide), int(px * SS * 0.72))
    for fname, lname in cfg["ui_icons"].items():
        lucide_icon(int(cps[lname]), lfont, px).save(png / f"{fname}.png", optimize=True)
        written.append(png / f"{fname}.png")

    wp = cfg["wallpaper"]
    wallpaper(theme / "wallpaper/aurora.png", wp["width"], wp["height"],
              wp["top_band_px"], wp["top_band_alpha"]).save(png / "bg.png", optimize=True)
    written.append(png / "bg.png")

    shutil.copy(theme / "fonts/PlusJakartaSans-Medium.ttf", out / "xmb/custom/font.ttf")
    lic = out / "licenses"
    lic.mkdir(parents=True, exist_ok=True)
    shutil.copy(theme / "fonts/OFL.txt", lic / "OFL.txt")
    shutil.copy(theme / "fonts/LUCIDE-LICENSE.txt", lic / "LUCIDE-LICENSE.txt")
    return written


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--lucide", type=Path, required=True)
    p.add_argument("--codepoints", type=Path, required=True)
    p.add_argument("--catalog", type=Path, required=True)
    p.add_argument("--theme", type=Path, default=HERE)
    a = p.parse_args()
    n = len(generate(a.out, a.lucide, a.codepoints, a.catalog, a.theme))
    print(f"tema Lume: {n} imagens em {a.out}")


if __name__ == "__main__":
    main()
