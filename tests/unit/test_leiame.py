from r36os import catalog, leiame


def test_every_system_in_leiame():
    text = leiame.render()
    for s in catalog.load()["systems"]:
        assert s["name"] in text
        assert f"roms/{s['id']}/" in text
        for e in s["extensions"]:
            assert f".{e}" in text


def test_psx_bios_names_and_hle():
    text = leiame.render()
    for name in ("scph5500.bin", "scph5501.bin", "scph5502.bin", "scph1001.bin"):
        assert name in text
    assert "HLE" in text
    assert "bios/" in text


def _section(text: str, folder: str) -> str:
    """The LEIA-ME block of one system (from its `pasta:` line to the next system)."""
    start = text.index(f"pasta:      roms/{folder}/")
    end = text.find("\n\n", start)
    return text[start:] if end < 0 else text[start:end]


def test_arcade_folders_say_the_romset():
    # catalog-arcade-sega: each arcade folder names the romset of the default core
    text = leiame.render()
    for sid in ("cps1", "cps2", "neogeo"):
        block = _section(text, sid)
        assert "Romset: FB Alpha v0.2.97.29" in block
        assert "Core alternativo: fbneo" in block and "outro romset" in block
    block = _section(text, "arcade")
    assert "Romset: FBNeo" in block
    assert "Core alternativo" not in block
    # the other systems do not get a romset line
    assert "Romset" not in _section(text, "nes")


def test_neogeo_bios_goes_in_the_game_folder():
    block = _section(leiame.render(), "neogeo")
    assert "BIOS (obrigatória), em roms/neogeo/, este nome: neogeo.zip" in block
    assert "em bios/, " not in block


def test_segacd_bios_in_bios_folder():
    block = _section(leiame.render(), "segacd")
    for name in ("bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin"):
        assert name in block
    assert "BIOS (obrigatória), em bios/" in block


def test_factory_reset_explained():
    assert "Apague esta pasta" in leiame.render()


def test_single_card_explained():
    # r36s-single-card, task 5.4: the same card on both consoles; .srm saves carry over,
    # save states may not (armv7 and aarch64)
    text = leiame.render()
    assert "o mesmo cartão inicia no GA36 e no R36S" in text
    assert "saves (.srm) funcionam nos dois" in text
    assert "save states podem não" in text and "armv7" in text and "aarch64" in text
    assert "cada log diz em qual console" in text
