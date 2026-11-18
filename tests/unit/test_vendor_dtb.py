"""Vendor RK3326 device trees converted for the mainline kernel (boot-dtb-select D12, tasks
7.4 to 7.8): lume_tool.vendor_dtb and the trees it wrote to board/r36s/dts-vendor/.

The tests with real vendor DTBs use the copies in .cache/upstream (dArkOSRE-R36,
arkos4clone, EE-Clones-DTB) and the factory tree of the R36S V5 in out/r36s-factory; they
are skipped without them. The compile and the dt-validate of the converted trees run in
the build (lume_tool.kernel.build_dtbs).
"""

import re

import pytest

from lume_tool import fdt, vendor_dtb
from lume_tool.paths import REPO_ROOT

COLLECTIONS = vendor_dtb.default_sources()
FACTORY = COLLECTIONS["factory"] / "rk3326-r35s-linux.dtb"
NATIVE = (REPO_ROOT / "board/r36s/dts/rk3326-r36s-v5.dts").read_text()
VENDOR_DIR = REPO_ROOT / "board/r36s/dts-vendor"


def _need(path):
    if not path.exists():
        pytest.skip(f"no {path}")
    return path


# --- the panel ----------------------------------------------------------------------------

def test_init_sequence_is_read_command_by_command():
    # <type> <wait ms> <length> <payload>: a long write, sleep out (250 ms), display on
    blob = bytes.fromhex("390004b9f11287" "05fa0111" "05320129")
    cmds = vendor_dtb.init_sequence(blob)
    assert [(k, w, p.hex()) for k, w, p in cmds] == [
        (0x39, 0, "b9f11287"), (0x05, 0xfa, "11"), (0x05, 0x32, "29")]


@pytest.mark.parametrize("blob, why", [
    (bytes.fromhex("3900"), "truncated header"),
    (bytes.fromhex("390005b9f1"), "truncated or empty"),
    (bytes.fromhex("390000"), "truncated or empty"),
    (b"", "empty"),
])
def test_bad_init_sequence_is_refused(blob, why):
    with pytest.raises(vendor_dtb.Refused, match=why):
        vendor_dtb.init_sequence(blob)


def _panel_node(**extra):
    mode = fdt.Node(props={"clock-frequency": fdt.u32(27000000), "hactive": fdt.u32(640),
                           "hfront-porch": fdt.u32(120), "hsync-len": fdt.u32(10),
                           "hback-porch": fdt.u32(120), "vactive": fdt.u32(480),
                           "vfront-porch": fdt.u32(17), "vsync-len": fdt.u32(4),
                           "vback-porch": fdt.u32(13), "phandle": fdt.u32(7)})
    props = {"dsi,flags": fdt.u32(0xa03), "dsi,format": fdt.u32(0), "dsi,lanes": fdt.u32(4),
             "width-mm": fdt.u32(153), "height-mm": fdt.u32(85),
             "prepare-delay-ms": fdt.u32(100), "reset-delay-ms": fdt.u32(100),
             "init-delay-ms": fdt.u32(20), "enable-delay-ms": fdt.u32(200),
             "panel-init-sequence": bytes.fromhex("390004b9f11287" "05fa0111" "05320129")}
    props.update(extra)
    return fdt.Node(props=props, children={"display-timings": fdt.Node(
        props={"native-mode": fdt.u32(7)}, children={"timing0": mode})})


def test_panel_description_has_the_rocknix_format():
    lines = vendor_dtb.panel_description(_panel_node())
    assert lines == [
        "G size=153,85 delays=100,100,20,200,20 format=rgb888 lanes=4 flags=0xe03",
        "M clock=27000 horizontal=640,120,10,120 vertical=480,17,4,13 default=1",
        "I seq=b9f11287",
        "I seq=11 wait=fa",          # the driver reads wait in hex, as ROCKNIX
        "I seq=29 wait=32",
    ]


def test_repeated_commands_stay_unique_lines():
    # dt-schema wants unique strings; the driver ignores what follows '#'
    seq = bytes.fromhex("150002ff30" "15000236 02" .replace(" ", "") + "150002ff30" + "150002ff30")
    lines = vendor_dtb.panel_description(_panel_node(**{"panel-init-sequence": seq}))
    assert lines[2:] == ["I seq=ff30", "I seq=3602", "I seq=ff30 # 2", "I seq=ff30 # 3"]
    assert len(set(lines)) == len(lines)


def test_a_mode_listed_twice_is_kept_once():
    node = _panel_node()
    timings = node.children["display-timings"]
    twin = fdt.Node(props=dict(timings.children["timing0"].props))
    twin.props["phandle"] = fdt.u32(8)
    timings.children["timing1"] = twin
    modes = [l for l in vendor_dtb.panel_description(node) if l.startswith("M ")]
    assert modes == ["M clock=27000 horizontal=640,120,10,120 vertical=480,17,4,13 default=1"]


def test_panel_without_timings_is_refused():
    node = _panel_node()
    node.children.clear()
    with pytest.raises(vendor_dtb.Refused, match="display-timings"):
        vendor_dtb.panel_description(node)


# --- whole trees --------------------------------------------------------------------------

def test_tree_of_another_soc_is_refused():
    data = fdt.build(fdt.Node(props={"compatible": fdt.s("rockchip,rk3566")}))
    with pytest.raises(vendor_dtb.Refused, match="not an RK3326 tree"):
        vendor_dtb.extract(data)


def test_garbage_is_refused():
    with pytest.raises(vendor_dtb.Refused, match="not a device tree"):
        vendor_dtb.extract(b"not a dtb at all, but long enough for a header....")


def test_tree_without_the_pmic_is_refused():
    data = fdt.build(fdt.Node(props={"compatible": fdt.s("rockchip,rk3326")}))
    with pytest.raises(vendor_dtb.Refused, match="PMIC missing"):
        vendor_dtb.extract(data)


def _native_buttons():
    """(bank, pin, code) of the native gpio-keys and volume-keys, from the DTS."""
    codes = {"BTN_DPAD_UP": 0x220, "BTN_DPAD_DOWN": 0x221, "BTN_DPAD_LEFT": 0x222,
             "BTN_DPAD_RIGHT": 0x223, "BTN_EAST": 0x131, "BTN_SOUTH": 0x130,
             "BTN_NORTH": 0x133, "BTN_WEST": 0x134, "BTN_TL": 0x136, "BTN_TR": 0x137,
             "BTN_TL2": 0x138, "BTN_TR2": 0x139, "KEY_VOLUMEUP": 115, "KEY_VOLUMEDOWN": 114}
    codes.update({f"BTN_TRIGGER_HAPPY{i}": 0x2bf + i for i in range(1, 6)})
    out = set()
    for bank, port, idx, code in re.findall(
            r"gpios = <&gpio(\d) RK_P([A-D])(\d) GPIO_ACTIVE_LOW>;\s*label = \"[^\"]*\";\s*"
            r"linux,code = <(\w+)>;", NATIVE):
        out.add((int(bank), "ABCD".index(port) * 8 + int(idx), codes[code]))
    return out


def test_factory_tree_of_the_r36s_v5_converts_to_the_native_board():
    board = vendor_dtb.extract(_need(FACTORY).read_bytes())
    pins = {(k.pin.bank, k.pin.pin, k.code) for k in board.keys + board.volume_keys}
    assert pins == _native_buttons() and len(pins) == 19
    assert all(k.pin.active_low for k in board.keys)
    # the same stick multiplexer as the native: its measured axes are kept
    assert board.mux and board.axes is None and board.stick_adc == 1
    assert (board.mux_en.bank, board.mux_en.pin) == (0, 17)          # RK_PC1
    assert (board.amp.bank, board.amp.pin) == (3, 20)                # RK_PC4, as spk_amp
    assert (board.hp_det[0].bank, board.hp_det[0].pin) == (2, 22)    # RK_PC6
    assert (board.pmic_irq.bank, board.pmic_irq.pin) == (0, 7)       # RK_PA7
    assert (board.reset.bank, board.reset.pin, board.reset.active_low) == (3, 16, True)
    assert board.backlight["pwm"] == 1 and board.backlight["period"] == 40000
    assert board.battery["capacity_mah"] == 3188
    assert {(c, p.bank, p.pin) for c, p in board.leds} == {("red", 0, 5), ("blue", 0, 0)}
    assert board.panel[0].startswith("G size=153,85 ") and "lanes=4" in board.panel[0]


def test_speaker_gain_of_the_source_is_never_copied():
    board = vendor_dtb.extract(_need(FACTORY).read_bytes())
    assert any("spk-volume 1 ignored" in n for n in board.notes)
    body = vendor_dtb.to_dts(board, "x", "src", "0" * 64).split("*/", 1)[1]
    assert "spk-volume" not in body and "rk817_codec" not in body


def test_converted_dts_overrides_the_native_tree():
    board = vendor_dtb.extract(_need(FACTORY).read_bytes())
    dts = vendor_dtb.to_dts(board, "r36s-v5-factory", "factory", "0" * 64)
    assert '#include "rk3326-r36s-v5.dts"' in dts
    assert 'lume,id = "r36s-v5-factory";' in dts and "/delete-property/ lume,default;" in dts
    # the rule of the native tree (its measured panel ID) is not inherited
    assert "/delete-property/ lume,panel-id;" in dts
    assert 'compatible = "rocknix,generic-dsi";' in dts
    # the factory lane rate of the R36S V5 (the native tree measures the same 180 Mbps)
    assert "rockchip,lane-rate = <180>;" in dts and "phy-hstt" not in dts


@pytest.mark.parametrize("clock, fmt, lanes, mbps", [
    (27000, 0, 4, 180), (29000, 0, 4, 193), (62000, 0, 4, 413), (30000, 0, 2, 400),
    (200000, 0, 1, 1000)])
def test_lane_rate_is_the_vendor_one(clock, fmt, lanes, mbps):
    assert vendor_dtb.vendor_lane_mbps(clock, fmt, lanes) == mbps


# --- the supply (D18) ---------------------------------------------------------------------

EE_K36_STOCK = COLLECTIONS["ee"] / "K36/Stock (Panel1 2TF)/rk3326-evb-lp3-v12-linux.dtb"
ARKOS_K36 = COLLECTIONS["arkos4clone"] / "boot/dArkOS/consoles/k36/rk3326-k36-linux.dtb"
DARKOSRE_V11 = (COLLECTIONS["darkosre"]
                / "files/BOOT/dtb/r36s/R35S-V11 2022-08-18/rk3326-r36s-linux.dtb")


def _native_power():
    """(regulators, io domains) of the native DTS: {node: (min, max, always-on)} and
    {domain: node}."""
    code = re.sub(r"/\*.*?\*/", "", NATIVE, flags=re.S)
    labels, regs = {}, {}
    for label, node, body in re.findall(
            r"(\w+): ((?:DCDC|LDO)_REG\d|BOOST|OTG_SWITCH) \{(.*?)\n\t\t\t\};", code, re.S):
        labels[label] = node
        own = body.split("regulator-state-mem")[0]
        lo = re.search(r"regulator-min-microvolt = <(\d+)>", own)
        hi = re.search(r"regulator-max-microvolt = <(\d+)>", own)
        regs[node] = (lo and int(lo[1]), hi and int(hi[1]), "regulator-always-on;" in own)
    domains = {d: labels[l] for d, l in re.findall(r"\t(\w+)-supply = <&(\w+)>;", code)
               if d.startswith(("vccio", "pmuio"))}
    return regs, domains


def _power(path):
    return vendor_dtb.power(vendor_dtb.Tree(_need(path).read_bytes()))


def test_factory_tree_of_the_r36s_v5_keeps_the_native_supply():
    p = _power(FACTORY)
    regs, domains = _native_power()
    assert len(regs) == 15 and set(p.regulators) == set(regs)
    assert {n: (r.min_uv, r.max_uv, r.always_on) for n, r in p.regulators.items()} == regs
    assert {**p.io_domains, **p.pmu_io_domains} == domains


def test_board_with_another_supply_gets_the_source_one():
    # the spec scenario: DCDC4 at 3.0 V, vccio3 and vccio6 on the 1.8 V regulator
    board = vendor_dtb.extract(_need(ARKOS_K36).read_bytes())
    dts = vendor_dtb.to_dts(board, "k36", "src", "0" * 64)
    dcdc4 = re.search(r"\t\tDCDC_REG4 \{(.*?)\n\t\t\};", dts, re.S)[1]
    assert "regulator-min-microvolt = <3000000>;" in dcdc4
    assert "regulator-max-microvolt = <3000000>;" in dcdc4
    assert "regulator-suspend-microvolt = <3000000>;" in dcdc4   # not the native 3.3 V
    ldo2 = re.search(r"\t\tLDO_REG2 \{(.*?)\n\t\t\};", dts, re.S)[1]
    assert "regulator-max-microvolt = <1800000>;" in ldo2
    for d in ("vccio3", "vccio6"):
        assert f"\t{d}-supply = <&{{/i2c@ff180000/pmic@20/regulators/LDO_REG2}}>;" in dts
    assert "\tvccio1-supply = <&{/i2c@ff180000/pmic@20/regulators/LDO_REG7}>;" in dts
    assert "\t/delete-property/ vccio-oscgpi-supply;" in dts


def test_factory_ee_tree_supply_and_rk809_nodes():
    p = _power(EE_K36_STOCK)
    assert p.regulators["DCDC_REG4"].max_uv == 3000000
    assert p.regulators["LDO_REG8"].min_uv == 3300000
    assert p.io_domains == {"vccio1": "LDO_REG7", "vccio2": "LDO_REG5", "vccio3": "LDO_REG2",
                            "vccio4": "DCDC_REG4", "vccio5": "DCDC_REG4"}
    # RK809 nodes are not regulators of the mainline RK817 driver
    assert not {"DCDC_REG5", "SWITCH_REG1", "SWITCH_REG2"} & set(p.regulators)
    assert any("SWITCH_REG1 is not an RK817 one" in n for n in p.notes)
    # vccio6 is not declared: the converted tree drops the native one
    dts = "\n".join(vendor_dtb._power_dts(p))
    assert "\t/delete-property/ vccio6-supply;" in dts


def test_rg351_like_tree_and_a_regulator_the_source_does_not_declare():
    board = vendor_dtb.extract(_need(DARKOSRE_V11).read_bytes())
    p = board.power
    assert (p.regulators["LDO_REG8"].min_uv, p.regulators["LDO_REG8"].max_uv) == (2800000,) * 2
    assert "LDO_REG9" not in p.regulators
    assert any("LDO_REG9" in n and "no voltage set" in n for n in board.notes)
    dts = vendor_dtb.to_dts(board, "v11", "src", "0" * 64)
    ldo9 = re.search(r"\t\tLDO_REG9 \{(.*?)\n\t\t\};", dts, re.S)[1]
    assert "/delete-property/ regulator-min-microvolt;" in ldo9
    assert "/delete-property/ regulator-max-microvolt;" in ldo9
    assert "regulator-always-on" not in ldo9 and "/delete-node/ regulator-state-mem;" in ldo9
    # LDO7 feeds the vendor panel's backlight-supply, which the converted tree does not
    # attach: the native always-on is never removed
    ldo7 = re.search(r"\t\tLDO_REG7 \{(.*?)\n\t\t\};", dts, re.S)[1]
    assert "always-on" not in ldo7 and "regulator-name = \"vcc_backlight\";" in ldo7
    assert "/delete-property/ regulator-always-on" not in dts


def _power_tree(supply_target: str = "LDO_REG5", uv: int = 3300000, regulators: bool = True):
    """A minimal RK3326 tree: an RK817 with one regulator, an outside fixed regulator and
    the IO domain vccio1 on `supply_target` (a regulator name or "fixed")."""
    reg = fdt.Node(props={"phandle": fdt.u32(1), "regulator-min-microvolt": fdt.u32(1800000),
                          "regulator-max-microvolt": fdt.u32(uv)})
    pmic = fdt.Node(props={"compatible": fdt.s("rockchip,rk817")},
                    children={"regulators": fdt.Node(children={"LDO_REG5": reg})}
                    if regulators else {})
    fixed = fdt.Node(props={"compatible": fdt.s("regulator-fixed"), "phandle": fdt.u32(2)})
    io = fdt.Node(props={"compatible": fdt.s("rockchip,px30-io-voltage-domain"),
                         "vccio1-supply": fdt.u32(2 if supply_target == "fixed" else 1)})
    return vendor_dtb.Tree(fdt.build(fdt.Node(
        props={"compatible": fdt.s("rockchip,rk3326")},
        children={"i2c@ff180000": fdt.Node(children={"pmic@20": pmic}),
                  "vcc-fixed": fixed,
                  "syscon@ff140000": fdt.Node(children={"io-domains": io})})))


def test_supply_of_the_minimal_tree_is_read():
    p = vendor_dtb.power(_power_tree())
    assert p.io_domains == {"vccio1": "LDO_REG5"} and p.pmu_io_domains == {}


@pytest.mark.parametrize("tree, why", [
    (lambda: _power_tree(regulators=False), "PMIC: no regulators node"),
    (lambda: _power_tree(supply_target="fixed"), "io domain vccio1: supply /vcc-fixed is "
                                                 "outside the PMIC"),
    (lambda: _power_tree(uv=3800000), "io domain vccio1: LDO_REG5 up to 3800000 uV, "
                                      "above 3.6 V"),
])
def test_unknown_supply_is_refused(tree, why):
    with pytest.raises(vendor_dtb.Refused, match=re.escape(why)):
        vendor_dtb.power(tree())


ROCKNIX_EECLONE = (REPO_ROOT / ".cache/upstream/rocknix/projects/ROCKNIX/devices/RK3326/linux/"
                   "dts/rockchip/rk3326-gameconsole-eeclone.dts")
# where the factory EE trees and the ROCKNIX eeclone DTS differ, none of them an IO domain
# supply: the boost and DCDC2 floors, the card vmmc range (LDO6), the second slot or camera
# rail (LDO8: 3.3 V in the factory trees, 3.0 V in ROCKNIX) and the LDO9 of the G30
EE_KNOWN_DIFFERENCES = {"BOOST", "DCDC_REG2", "LDO_REG6", "LDO_REG8", "LDO_REG9"}


def _rocknix_eeclone():
    text = _need(ROCKNIX_EECLONE).read_text()
    labels, regs = {}, {}
    for label, node, body in re.findall(
            r"(\w+): ((?:DCDC|LDO)_REG\d|BOOST|OTG_SWITCH) \{(.*?)\n\s*\};", text, re.S):
        labels[label] = node
        own = body.split("regulator-state-mem")[0]
        lo = re.search(r"regulator-min-microvolt = <(\d+)>", own)
        hi = re.search(r"regulator-max-microvolt = <(\d+)>", own)
        regs[node] = (lo and int(lo[1]), hi and int(hi[1]))
    domains = {d: labels[l] for d, l in re.findall(r"(\w+)-supply = <&(\w+)>;", text)
               if d.startswith(("vccio", "pmuio"))}
    return regs, domains


def _check_against_rocknix(p, regs, domains, what):
    got = {**p.io_domains, **p.pmu_io_domains}
    assert got and all(domains[d] == r for d, r in got.items()), what
    for name in set(got.values()):   # the rails behind the IO domains: the same voltages
        r = p.regulators[name]
        assert (r.min_uv, r.max_uv) == regs[name], f"{what}: {name}"
    other = {n for n, r in p.regulators.items() if (r.min_uv, r.max_uv) != regs[n]}
    assert other <= EE_KNOWN_DIFFERENCES, f"{what}: {other}"


def test_factory_ee_trees_match_the_rocknix_eeclone_supply():
    regs, domains = _rocknix_eeclone()
    trees = sorted(_need(COLLECTIONS["ee"]).rglob("*.dtb"))
    assert len(trees) >= 50
    for f in trees:
        _check_against_rocknix(_power(f), regs, domains, f.name)


def test_converted_ee_family_board_matches_the_rocknix_eeclone_supply():
    regs, domains = _rocknix_eeclone()
    board = vendor_dtb.extract(_need(ARKOS_K36).read_bytes())
    _check_against_rocknix(board.power, regs, domains, "arkos4clone-k36")
    got = _dts_supply((VENDOR_DIR / "arkos4clone-k36.dts").read_text())[1]
    assert got == domains


@pytest.mark.parametrize("collection, rel, expected", [
    ("arkos4clone", "boot/dArkOS/consoles/r36max/rk3326-r36max-linux.dtb", "arkos4clone-r36max"),
    ("arkos4clone", "boot/dArkOS/consoles/go2/5.10/rk3326-go2-linux.dtb", "arkos4clone-go2-5.10"),
    ("darkosre", "files/BOOT/dtb/soysauce/Y3506_v03_20241210 2533/rk3326-r36s-linux.dtb",
     "darkosre-soysauce-y3506-v03-20241210-2533"),
    ("ee", "K36/Stock (Panel1 2TF)/rk3326-evb-lp3-v12-linux.dtb", "ee-k36-panel1-2tf"),
    ("ee", "MyMini (emmc)/Stock (shared by WhatPriceLJN)/rf35mg3ka.dtb", "ee-mymini"),
])
def test_ids_come_from_the_folders(collection, rel, expected):
    assert vendor_dtb.slug(collection, rel) == expected


# --- the collections (7.8) ----------------------------------------------------------------

def test_every_collection_tree_converts_or_is_refused_with_a_reason(tmp_path):
    sources = {k: v for k, v in COLLECTIONS.items() if v.exists()}
    if len(sources) != len(COLLECTIONS):
        pytest.skip("vendor collections not in .cache/upstream")
    rows = vendor_dtb.import_collections(sources, tmp_path)
    assert {r["status"] for r in rows} <= {"converted", "refused", "same"}
    assert all(r["reason"] for r in rows if r["status"] != "converted")
    converted = [r for r in rows if r["status"] == "converted"]
    assert len(converted) >= 150
    ids = [r["id"] for r in converted]
    assert len(ids) == len(set(ids)) and all(len(i) < 64 for i in ids)
    # the committed trees are what the importer writes today
    committed = {p.name: p.read_text() for p in VENDOR_DIR.glob("*")}
    fresh = {p.name: p.read_text() for p in tmp_path.glob("*")}
    assert committed == fresh, "board/r36s/dts-vendor is stale: run lume dtb-import"


def _source_supply(data: bytes):
    """The supply of a source DTB read on its own (the task 7.2 survey, not the converter):
    {regulator: (min, max)} of the RK817 and {domain: regulator} of both IO domain nodes."""
    root = fdt.parse(data)

    def walk(node, path=""):
        yield path, node
        for name, child in node.children.items():
            yield from walk(child, f"{path}/{name}")

    nodes = dict(walk(root))
    by_phandle = {(n.cells("phandle") or n.cells("linux,phandle"))[0]: p
                  for p, n in nodes.items() if n.cells("phandle") or n.cells("linux,phandle")}
    regs, domains = {}, {}
    for path, n in nodes.items():
        if "rockchip,rk817" in n.strings("compatible"):
            for name, r in n.children["regulators"].children.items():
                lo, hi = r.cells("regulator-min-microvolt"), r.cells("regulator-max-microvolt")
                regs[name] = (lo[0] if lo else None, hi[0] if hi else None)
        if any(c.endswith("io-voltage-domain") for c in n.strings("compatible")):
            for prop in n.props:
                if prop.endswith("-supply"):
                    domains[prop[:-7]] = by_phandle[n.cells(prop)[0]].rsplit("/", 1)[1]
    return regs, domains


def _dts_supply(text: str):
    """The same, read back from a converted DTS."""
    regs = {}
    block = re.search(r"&rk817 \{\n\tregulators \{\n(.*?)\n\t\};\n\};", text, re.S)[1]
    for name, body in re.findall(r"\t\t(\w+) \{\n(.*?)\n\t\t\};", block, re.S):
        own = body.split("regulator-state-mem")[0]
        lo = re.search(r"\tregulator-min-microvolt = <(\d+)>", own)
        hi = re.search(r"\tregulator-max-microvolt = <(\d+)>", own)
        regs[name] = (lo and int(lo[1]), hi and int(hi[1]))
    domains = dict(re.findall(r"\t([\w-]+)-supply = <&\{/i2c@ff180000/pmic@20/regulators/"
                              r"(\w+)\}>;", text))
    return regs, domains


def test_every_converted_tree_keeps_the_supply_of_its_source():
    rows = [line.split("\t") for line in (VENDOR_DIR / "SOURCES.tsv").read_text().splitlines()
            if line.startswith("converted\t")]
    checked = 0
    for _, lid, collection, rel, _sha, _reason in rows:
        src = COLLECTIONS[collection] / rel
        if not src.exists():
            continue
        regs, domains = _source_supply(src.read_bytes())
        got_regs, got_domains = _dts_supply((VENDOR_DIR / f"{lid}.dts").read_text())
        mainline = set(vendor_dtb.RK817_REGULATORS)
        assert set(got_regs) == mainline, lid
        assert {k: v for k, v in regs.items() if k in mainline} == {
            k: v for k, v in got_regs.items() if k in regs}, lid
        # what the source does not declare has no voltage in the converted tree
        assert all(got_regs[k] == (None, None) for k in mainline - set(regs)), lid
        assert got_domains == domains, lid
        checked += 1
    if not checked:
        pytest.skip("vendor collections not in .cache/upstream")
    assert checked == len(rows)


def test_committed_trees_have_a_source_line_each():
    rows = [line.split("\t") for line in (VENDOR_DIR / "SOURCES.tsv").read_text().splitlines()
            if line and not line.startswith(("#", "status\t"))]
    converted = {r[1] for r in rows if r[0] == "converted"}
    assert converted == {p.stem for p in VENDOR_DIR.glob("*.dts")}
    for dts in VENDOR_DIR.glob("*.dts"):
        assert f'lume,id = "{dts.stem}";' in dts.read_text()
