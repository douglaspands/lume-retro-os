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
    assert ids == ["nes", "snes", "mastersystem", "megadrive", "gb", "gbc", "gba", "arcade", "psx"]
    by_id = {s["id"]: s for s in CAT["systems"]}
    # GBA: gpsp on every target (no mgba in this version)
    for arch in ("x86_64", "aarch64", "armv7"):
        assert catalog.default_core(by_id["gba"], arch) == "gpsp"
    assert "mgba" not in CAT["cores"]
    assert catalog.default_core(by_id["arcade"], "armv7") == "mame2003_plus"
    assert by_id["psx"]["bios"][0]["files"] == [
        "scph5500.bin", "scph5501.bin", "scph5502.bin", "scph1001.bin"]


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
