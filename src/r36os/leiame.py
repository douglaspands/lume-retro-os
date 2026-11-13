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

Um cartão, dois consoles: o mesmo cartão inicia no GA36 e no R36S, sem regravar.
Os dois usam esta partição: jogos, BIOS, saves e configuração passam de um console
para o outro. Os saves (.srm) funcionam nos dois; os save states podem não
funcionar no outro console (o GA36 é armv7 e o R36S é aarch64). Os logs dos dois
ficam juntos em logs/, e cada log diz em qual console foi gerado.

Sistemas
--------
"""


# Romset accepted by each alternative core offered in the arcade folders.
_ALT_ROMSET = {"fbneo": "FBNeo, da versão do core da imagem"}


def render(cat: dict | None = None) -> str:
    cat = cat or catalog.load()
    out = [_HEAD]
    for s in cat["systems"]:
        exts = ", ".join("." + e for e in s["extensions"])
        out.append(f"\n{s['name']}\n  pasta:      roms/{s['id']}/\n  extensões:  {exts}\n")
        for b in s["bios"]:
            names = ", ".join(b["files"])
            need = "obrigatória" if b["required"] else "opcional"
            # The Neo Geo BIOS (neogeo.zip) is looked up next to the games, not in bios/
            where = f"em roms/{s['id']}/" if s["id"] == "neogeo" else "em bios/"
            kind = "este nome" if len(b["files"]) == 1 else "um destes nomes"
            out.append(f"  BIOS ({need}), {where}, {kind}: {names}\n")
            out.append(f"    {b['note']}\n")
        if s["romset"]:
            out.append(f"  Romset: {s['romset']}.\n")
            out.append("  Use o arquivo .zip do jogo sem descompactar, com o nome original.\n")
            for alt in s["alt_cores"]:
                out.append(
                    f"  Core alternativo: {alt} (escolha no menu do RetroArch). Ele usa\n"
                    f"  outro romset ({_ALT_ROMSET[alt]}): um jogo que abre num core pode\n"
                    f"  não abrir no outro.\n")
        if s["id"] == "psx":
            out.append("  Jogos de vários discos: crie um .m3u listando os .cue/.chd.\n")
    return "".join(out)
