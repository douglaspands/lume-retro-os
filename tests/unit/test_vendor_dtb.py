"""Vendor RK3326 device trees converted for the mainline kernel (boot-dtb-select D12, tasks
7.4 to 7.8): r36os.vendor_dtb and the trees it wrote to board/r36s/dts-vendor/.

The tests with real vendor DTBs use the copies in .cache/upstream (dArkOSRE-R36,
arkos4clone, EE-Clones-DTB) and the factory tree of the R36S V5 in out/r36s-factory; they
are skipped without them. The compile and the dt-validate of the converted trees run in
the build (r36os.kernel.build_dtbs).
"""

import re

import pytest

from r36os import fdt, vendor_dtb
from r36os.paths import REPO_ROOT

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
    assert 'compatible = "rocknix,generic-dsi";' in dts
    # the factory lane rate of the R36S V5 (the native tree measures the same 180 Mbps)
    assert "rockchip,lane-rate = <180>;" in dts and "phy-hstt" not in dts


@pytest.mark.parametrize("clock, fmt, lanes, mbps", [
    (27000, 0, 4, 180), (29000, 0, 4, 193), (62000, 0, 4, 413), (30000, 0, 2, 400),
    (200000, 0, 1, 1000)])
def test_lane_rate_is_the_vendor_one(clock, fmt, lanes, mbps):
    assert vendor_dtb.vendor_lane_mbps(clock, fmt, lanes) == mbps


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
    assert committed == fresh, "board/r36s/dts-vendor is stale: run r36os dtb-import"


def test_committed_trees_have_a_source_line_each():
    rows = [line.split("\t") for line in (VENDOR_DIR / "SOURCES.tsv").read_text().splitlines()
            if line and not line.startswith(("#", "status\t"))]
    converted = {r[1] for r in rows if r[0] == "converted"}
    assert converted == {p.stem for p in VENDOR_DIR.glob("*.dts")}
    for dts in VENDOR_DIR.glob("*.dts"):
        assert f'lume,id = "{dts.stem}";' in dts.read_text()
