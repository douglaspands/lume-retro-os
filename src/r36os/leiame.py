"""Renders LEIA-ME.txt for the ROMS partition from the system catalog.

The text itself is user-facing Portuguese content (one of the translated texts); the
code around it is English like the rest of the project.
"""

from __future__ import annotations

from r36os import catalog

_HEAD = """\
LUME RETRO OS - PARTIÇÃO DE JOGOS (ROMS)
=========================================

Copie os jogos para a pasta do sistema dentro de "roms" e ligue o console.
As listas de jogos são montadas a cada boot. Arquivos com extensão fora da
lista do sistema são ignorados.

Pastas:
  roms/<sistema>/   jogos
  bios/             BIOS (veja abaixo)
  saves/            saves dos jogos (uma pasta por sistema)
  states/           save states (uma pasta por sistema)
  screenshots/      capturas de tela
  system/           configuração do sistema. Apague esta pasta para voltar à
                    configuração de fábrica: jogos, saves e states continuam.

Fuso horário e nome do aparelho: crie system/etc/timezone (ex.: America/Sao_Paulo)
e system/etc/hostname com o valor desejado.

Sistemas
--------
"""


def render(cat: dict | None = None) -> str:
    cat = cat or catalog.load()
    out = [_HEAD]
    for s in cat["systems"]:
        exts = ", ".join("." + e for e in s["extensions"])
        out.append(f"\n{s['name']}\n  pasta:      roms/{s['id']}/\n  extensões:  {exts}\n")
        for b in s["bios"]:
            names = ", ".join(b["files"])
            need = "obrigatória" if b["required"] else "opcional"
            out.append(f"  BIOS ({need}), em bios/, um destes nomes: {names}\n")
            out.append(f"    {b['note']}\n")
        if s["id"] == "arcade":
            out.append("  Use o arquivo .zip do jogo sem descompactar, com o nome original.\n")
        if s["id"] == "psx":
            out.append("  Jogos de vários discos: crie um .m3u listando os .cue/.chd.\n")
    return "".join(out)
