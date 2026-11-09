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
