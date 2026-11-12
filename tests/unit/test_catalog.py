import copy

from r36os import catalog, pkglists

CAT = catalog.load()


def test_catalog_is_valid():
    assert catalog.validate(CAT) == []


def test_every_core_has_package_in_common_list():
    common = set(pkglists.common_packages())
    missing = catalog.referenced_packages(CAT) - common
    assert missing == set(), f"cores without a package in packages.txt: {missing}"


def test_systems_match_design_table():
    ids = [s["id"] for s in CAT["systems"]]
    assert ids == ["nes", "snes", "mastersystem", "megadrive", "segacd", "sega32x", "gb", "gbc",
                   "gba", "arcade", "cps1", "cps2", "neogeo", "psx"]
    by_id = {s["id"]: s for s in CAT["systems"]}
    # Sega CD: genesis_plus_gx, picodrive on the GA36 (armv7); required BIOS by region
    assert by_id["segacd"]["extensions"] == ["cue", "chd", "iso", "m3u"]
    assert catalog.default_core(by_id["segacd"], "aarch64") == "genesis_plus_gx"
    assert catalog.default_core(by_id["segacd"], "x86_64") == "genesis_plus_gx"
    assert catalog.default_core(by_id["segacd"], "armv7") == "picodrive"
    assert by_id["segacd"]["alt_cores"] == ["picodrive"]
    assert by_id["segacd"]["bios"][0]["files"] == [
        "bios_CD_U.bin", "bios_CD_E.bin", "bios_CD_J.bin"]
    assert by_id["segacd"]["bios"][0]["required"] is True
    # 32X: picodrive everywhere
    assert by_id["sega32x"]["extensions"] == ["32x", "zip", "7z"]
    for arch in ("x86_64", "aarch64", "armv7"):
        assert catalog.default_core(by_id["sega32x"], arch) == "picodrive"
    # CPS-1, CPS-2, Neo Geo: FB Alpha 2012 cut per board, fbneo as the only alternative
    for sid in ("cps1", "cps2", "neogeo"):
        assert by_id[sid]["extensions"] == ["zip"]
        assert by_id[sid]["core_by_arch"] == {}
        assert by_id[sid]["alt_cores"] == ["fbneo"]
        assert by_id[sid]["romset"] == "FB Alpha v0.2.97.29"
        for arch in ("x86_64", "aarch64", "armv7"):
            assert catalog.default_core(by_id[sid], arch) == f"fbalpha2012_{sid}"
        assert f"fbalpha2012_{sid}" in CAT["cores"]
    assert by_id["neogeo"]["bios"][0]["files"] == ["neogeo.zip"]
    assert by_id["neogeo"]["bios"][0]["required"] is True
    assert "roms/neogeo/" in by_id["neogeo"]["bios"][0]["note"]
    assert by_id["arcade"]["romset"].startswith("FBNeo")
    # only the arcade systems carry a romset
    assert {s["id"] for s in CAT["systems"] if s["romset"]} == {"arcade", "cps1", "cps2", "neogeo"}
    # GBA: gpsp on every target (no mgba in this version)
    for arch in ("x86_64", "aarch64", "armv7"):
        assert catalog.default_core(by_id["gba"], arch) == "gpsp"
    assert "mgba" not in CAT["cores"]
    # arcade: fbneo on every console, so a romset works on both consoles of the single card
    # (mame2003_plus left out on the user's request, 2026-11-11)
    for arch in ("x86_64", "aarch64", "armv7"):
        assert catalog.default_core(by_id["arcade"], arch) == "fbneo"
    assert "mame2003_plus" not in CAT["cores"]
    assert by_id["psx"]["bios"][0]["files"] == [
        "scph5500.bin", "scph5501.bin", "scph5502.bin", "scph1001.bin"]


def test_vm_core_tests_cover_what_has_a_free_rom():
    # the VM self-test runs a core with a ROM the build can generate (or Gridlee for fbneo);
    # fbalpha2012_* have no free romset: they are only checked by tests/cores/load_cores.sh
    from r36os import testdata

    tests = testdata.core_tests(CAT)
    assert tests["fbneo"] == ("arcade", "roms/arcade/gridlee.zip")
    assert tests["picodrive"][0] in ("mastersystem", "megadrive")
    assert tests["genesis_plus_gx"][0] in ("mastersystem", "megadrive")
    assert not any(core.startswith("fbalpha2012_") for core in tests)
    assert all(system not in testdata.NO_TEST_ROM for system, _ in tests.values())


def test_validator_catches_errors():
    bad = copy.deepcopy(CAT)
    bad["systems"][0]["core"] = "doesnotexist"
    bad["systems"][1]["extensions"] = [".SFC"]
    bad["systems"][2]["core_by_arch"] = {"mips": "picodrive"}
    del bad["systems"][3]["bios"]
    errs = catalog.validate(bad)
    assert any("doesnotexist" in e for e in errs)
    assert any("snes: extensions" in e for e in errs)
    assert any("architecture" in e for e in errs)
    assert any(e.startswith("megadrive:") for e in errs)


def test_validator_refuses_arcade_core_by_arch():
    # single card: an arcade folder must use the same core on every console
    bad = copy.deepcopy(CAT)
    cps2 = next(s for s in bad["systems"] if s["id"] == "cps2")
    cps2["core_by_arch"] = {"armv7": "fbneo"}
    errs = catalog.validate(bad)
    assert any(e.startswith("cps2:") and "core_by_arch" in e for e in errs)
    # a regular system keeps its per-architecture core
    assert not any(e.startswith("megadrive:") for e in errs)


def test_validator_romset_must_be_null_or_text():
    bad = copy.deepcopy(CAT)
    next(s for s in bad["systems"] if s["id"] == "nes")["romset"] = ""
    del next(s for s in bad["systems"] if s["id"] == "gb")["romset"]
    errs = catalog.validate(bad)
    assert any(e.startswith("nes:") and "romset" in e for e in errs)
    assert any(e.startswith("gb:") for e in errs)
