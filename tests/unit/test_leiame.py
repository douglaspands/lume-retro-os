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
