import copy

from lume_tool import catalog, pkglists

CAT = catalog.load()


def test_catalog_is_valid():
    assert catalog.validate(CAT) == []


def test_every_core_has_package_in_common_list():
    common = set(pkglists.common_packages())
    missing = catalog.referenced_packages(CAT) - common
    assert missing == set(), f"cores without a package in packages.txt: {missing}"


def test_systems_match_design_table():
    ids = [s["id"] for s in CAT["systems"]]
    assert ids == ["nes", "snes", "mastersystem", "gamegear", "sg1000", "megadrive", "segacd",
                   "sega32x", "gb", "gbc", "gba", "arcade", "cps1", "cps2", "neogeo", "psx",
                   "love", "ports"]
    by_id = {s["id"]: s for s in CAT["systems"]}
    # SNES (game-governor D15): snes9x2005_plus everywhere, no alternatives, no per-arch swap
    assert by_id["snes"]["core"] == "snes9x2005_plus"
    assert by_id["snes"]["alt_cores"] == []
    assert by_id["snes"]["core_by_arch"] == {}
    for arch in ("x86_64", "aarch64", "armv7"):
        assert catalog.default_core(by_id["snes"], arch) == "snes9x2005_plus"
    assert not any("snes9x" in c and c != "snes9x2005_plus" for c in CAT["cores"])
    # Sega CD, Master System, Mega Drive: genesis_plus_gx on every console, picodrive as the
    # alternative (the user, 2026-11-19: same cores on both consoles at the start)
    assert by_id["segacd"]["extensions"] == ["cue", "chd", "iso", "m3u"]
    for sid in ("segacd", "mastersystem", "megadrive"):
        for arch in ("x86_64", "aarch64", "armv7"):
            assert catalog.default_core(by_id[sid], arch) == "genesis_plus_gx"
        assert by_id[sid]["alt_cores"] == ["picodrive"]
    # Game Gear and SG-1000 (the user, 2026-11-19): the same genesis_plus_gx as the rest of the
    # Sega 8/16-bit family, so one core to optimize
    assert by_id["gamegear"]["extensions"] == ["gg", "zip", "7z"]
    assert by_id["sg1000"]["extensions"] == ["sg", "zip", "7z"]
    for sid in ("gamegear", "sg1000"):
        for arch in ("x86_64", "aarch64", "armv7"):
            assert catalog.default_core(by_id[sid], arch) == "genesis_plus_gx"
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


def test_same_cores_on_both_consoles_for_now():
    # the user, 2026-11-19: at the start the GA36 (armv7) and the R36S (aarch64) run the same
    # cores; each console may take its own path later through core_by_arch (the field stays)
    for s in CAT["systems"]:
        assert s["core_by_arch"] == {}, s["id"]
        assert catalog.emulators(s, "armv7") == catalog.emulators(s, "aarch64"), s["id"]


def test_vm_core_tests_cover_what_has_a_free_rom():
    # the VM self-test runs a core with a ROM the build can generate (or Gridlee for fbneo);
    # fbalpha2012_* have no free romset: they are only checked by tests/cores/load_cores.sh
    from lume_tool import testdata

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
    assert any(e.startswith(f"{bad['systems'][3]['id']}:") for e in errs)


def test_validator_refuses_arcade_core_by_arch():
    # single card: an arcade folder must use the same core on every console
    bad = copy.deepcopy(CAT)
    cps2 = next(s for s in bad["systems"] if s["id"] == "cps2")
    cps2["core_by_arch"] = {"armv7": "fbneo"}
    errs = catalog.validate(bad)
    assert any(e.startswith("cps2:") and "core_by_arch" in e for e in errs)
    # a regular system keeps its per-architecture core
    assert not any(e.startswith("megadrive:") for e in errs)


def test_schema3_launcher_fields():
    # lume-launcher D5, D11: every system has a Dock abbreviation; love and ports have no
    # libretro core and one native runner each
    by_id = {s["id"]: s for s in CAT["systems"]}
    assert by_id["snes"]["abbr"] == "SNES" and by_id["psx"]["abbr"] == "PS1"
    assert len({s["abbr"] for s in CAT["systems"]}) == len(CAT["systems"])
    assert by_id["love"]["extensions"] == ["love"] and by_id["love"]["core"] is None
    assert by_id["ports"]["extensions"] == ["sh"] and by_id["ports"]["core"] is None
    assert catalog.emulators(by_id["love"], "armv7") == [{"runner": "love"}]
    assert catalog.emulators(by_id["ports"], "aarch64") == [{"runner": "sh"}]


def test_emulators_derived_from_core_fields():
    # the two forms agree: the libretro emulators are the default core of the architecture
    # first, then the other cores of the system, and lume-playlists keeps using `core`
    by_id = {s["id"]: s for s in CAT["systems"]}
    assert catalog.emulators(by_id["nes"], "x86_64") == [
        {"runner": "retroarch", "core": "fceumm"}, {"runner": "retroarch", "core": "nestopia"}]
    assert catalog.emulators(by_id["segacd"], "armv7") == [
        {"runner": "retroarch", "core": "genesis_plus_gx"},
        {"runner": "retroarch", "core": "picodrive"}]
    assert catalog.emulators(by_id["segacd"], "aarch64") == [
        {"runner": "retroarch", "core": "genesis_plus_gx"},
        {"runner": "retroarch", "core": "picodrive"}]
    for s in CAT["systems"]:
        for arch in ("x86_64", "aarch64", "armv7"):
            emus = catalog.emulators(s, arch)
            assert emus, s["id"]
            if s["core"] is not None:
                assert emus[0] == {"runner": "retroarch", "core": catalog.default_core(s, arch)}
                # the core of another architecture is not an alternative here
                assert {e["core"] for e in emus if "core" in e} == {
                    catalog.default_core(s, arch), s["core"], *s["alt_cores"]}


def test_image_runners_are_valid():
    runners = catalog.load_runners()
    assert set(runners) == {"retroarch", "love", "sh"}
    for r in runners.values():
        assert catalog.validate_runner(r) == [], r["id"]
    assert runners["retroarch"]["kind"] == "libretro"
    assert runners["retroarch"]["quit"] == "retroarch-cmd"
    assert runners["love"]["quit"] == runners["sh"]["quit"] == "sigterm"
    # lume-hud-actions D3: RetroArch declares every action and the overlay; the native
    # runners declare nothing (the system freezes them for the menu)
    assert runners["retroarch"]["overlay"] == "retroarch"
    assert runners["retroarch"]["actions"] == {
        "pause": "retroarch-pause", "app_menu": "retroarch-cmd:MENU_TOGGLE",
        "reset": "retroarch-cmd:RESET", "save_state": "retroarch-cmd:SAVE_STATE",
        "load_state": "retroarch-cmd:LOAD_STATE", "screenshot": "retroarch-cmd:SCREENSHOT"}
    for native in ("love", "sh"):
        assert "actions" not in runners[native] and "overlay" not in runners[native]


def test_validator_refuses_missing_runner():
    # game-library: an emulator citing a runner that is not installed fails the build
    bad = copy.deepcopy(CAT)
    next(s for s in bad["systems"] if s["id"] == "love")["emulators"] = [{"runner": "nope"}]
    errs = catalog.validate(bad)
    assert any(e.startswith("love:") and "nope" in e for e in errs)
    runners = catalog.load_runners()
    del runners["retroarch"]
    assert any("runner retroarch is missing" in e for e in catalog.validate(CAT, runners))


def test_validator_keeps_the_two_forms_apart():
    bad = copy.deepcopy(CAT)
    by_id = {s["id"]: s for s in bad["systems"]}
    by_id["snes"]["emulators"] = [{"runner": "retroarch", "core": "fceumm"}]
    by_id["love"]["emulators"] = []
    by_id["ports"]["emulators"] = [{"runner": "sh", "core": "fceumm"}]
    by_id["gba"]["abbr"] = "GAMEBOY"
    errs = catalog.validate(bad)
    assert any(e.startswith("snes:") and "core/alt_cores" in e for e in errs)
    assert any(e.startswith("love:") and "needs emulators" in e for e in errs)
    assert any(e.startswith("ports:") and "takes no core" in e for e in errs)
    assert any(e.startswith("gba:") and "abbr" in e for e in errs)


def test_validator_refuses_bad_runner():
    base = {"id": "x", "kind": "native", "exec": ["/bin/x", "{rom}"], "quit": "sigterm",
            "timeout": 3}
    assert catalog.validate_runner(base) == []
    cases = {
        "exec": [],
        "kind": "wine",
        "quit": "kill",
        "timeout": 0,
    }
    for field, value in cases.items():
        r = dict(base, **{field: value})
        assert catalog.validate_runner(r), field
    assert any("unknown placeholder" in e for e in
               catalog.validate_runner(dict(base, exec=["/bin/x", "{game}"])))
    assert any("whole argument" in e for e in
               catalog.validate_runner(dict(base, exec=["/bin/x", "--rom={rom}"])))
    assert any("absolute" in e for e in catalog.validate_runner(dict(base, exec=["x"])))
    # actions and overlay: the same rules as lume-core's ActionForm::parse
    ok = dict(base, overlay="retroarch", actions={"pause": "retroarch-pause", "reset": "key:KEY_F2",
                                                  "screenshot": "signal:SIGUSR1"})
    assert catalog.validate_runner(ok) == []
    for actions, why in (({"save_state": "retroarch-pause"}, "only for pause"),
                         ({"reset": "key:BTN_A"}, "KEY_"),
                         ({"reset": "signal:SIGKILL"}, "unknown signal"),
                         ({"reset": "retroarch-cmd:reset"}, "upper-case"),
                         ({"rewind": "retroarch-cmd:REWIND"}, "unknown action")):
        assert any(why in e for e in catalog.validate_runner(dict(base, actions=actions))), why
    assert any("unknown overlay" in e for e in catalog.validate_runner(dict(base, overlay="sdl")))
    assert any("unknown field" in e for e in catalog.validate_runner(dict(base, shell=True)))


def test_new_folders_created_without_deleting(tmp_path):
    # love/ and ports/ come from the catalog ids, like every other system folder; an old
    # card keeps its games
    from lume_tool import flash

    old = tmp_path / "roms/megadrive"
    old.mkdir(parents=True)
    (old / "game.md").write_bytes(b"x")
    flash.populate_roms(tmp_path)
    assert (tmp_path / "roms/love").is_dir() and (tmp_path / "roms/ports").is_dir()
    assert (old / "game.md").read_bytes() == b"x"


def test_validator_romset_must_be_null_or_text():
    bad = copy.deepcopy(CAT)
    next(s for s in bad["systems"] if s["id"] == "nes")["romset"] = ""
    del next(s for s in bad["systems"] if s["id"] == "gb")["romset"]
    errs = catalog.validate(bad)
    assert any(e.startswith("nes:") and "romset" in e for e in errs)
    assert any(e.startswith("gb:") for e in errs)
