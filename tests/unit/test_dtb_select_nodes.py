"""The lume-select node of the board DTBs (boot-dtb-select D3, task 3.2) and the build
check of every BOOT/dtbs/<soc>/ folder.

The DTS are compiled and validated (dtc + dt-validate, with the binding of kernel patch
0026) by the build; the tests of the compiled DTBs read out/<board>/kernel/dtbs/ and are
skipped before a build that has the node.
"""

import re

import pytest

from r36os import fdt, image
from r36os.paths import REPO_ROOT, out_dir

DTS = {"ga36": sorted((REPO_ROOT / "board/ga36/dts").glob("*.dts")),
       "r36s": sorted((REPO_ROOT / "board/r36s/dts").glob("*.dts"))}


def _node(text: str) -> dict:
    body = re.search(r"\n\tlume-select \{(.*?)\n\t\};", text, re.S).group(1)
    return {"id": re.search(r'lume,id = "([^"]+)";', body).group(1),
            "priority": int(re.search(r"lume,priority = <(\d+)>;", body).group(1)),
            "default": bool(re.search(r"^\s*lume,default;", body, re.M))}


@pytest.mark.parametrize("board", ["ga36", "r36s"])
def test_every_board_dts_has_the_node_with_one_default(board):
    nodes = [_node(p.read_text()) for p in DTS[board]]
    assert nodes
    ids = [n["id"] for n in nodes]
    assert len(set(ids)) == len(ids)
    assert sum(n["default"] for n in nodes) == 1


def test_ids_and_defaults_of_today():
    nodes = {p.stem: _node(p.read_text()) for b in DTS for p in DTS[b]}
    assert nodes["sun8i-a33-ga36-mb-v1.2-panel1"] == {"id": "ga36-panel1", "priority": 0,
                                                     "default": True}
    assert nodes["sun8i-a33-ga36-mb-v1.2-panel2"] == {"id": "ga36-panel2", "priority": 0,
                                                     "default": False}
    assert nodes["rk3326-r36s-v5"] == {"id": "r36s-v5", "priority": 0, "default": True}


def test_no_rules_until_a_signature_is_measured():
    for board in DTS:
        for p in DTS[board]:
            body = re.search(r"\n\tlume-select \{(.*?)\n\t\};", p.read_text(), re.S).group(1)
            assert not re.search(r"lume,(adc|gpio|i2c-present)\s*=", body), p.name


def test_binding_patch_documents_the_node():
    patch = (REPO_ROOT / "kernel/patches"
             / "0026-dt-bindings-add-the-Lume-device-tree-selection-node.patch").read_text()
    assert '+  "^lume,.*":' in patch
    for prop in ("lume,id", "lume,priority", "lume,default", "lume,adc", "lume,gpio",
                 "lume,i2c-present"):
        assert f"+  {prop}:" in patch, prop


def _built(board: str):
    dtbs = sorted((out_dir() / board / "kernel/dtbs").glob("*.dtb"))
    infos = {p.name: fdt.select_info(fdt.parse(p.read_bytes())) for p in dtbs}
    if not infos or None in infos.values():
        pytest.skip(f"{board} DTBs not built with the lume-select node yet")
    return dtbs, infos


@pytest.mark.parametrize("board", ["ga36", "r36s"])
def test_built_dtbs_pass_the_build_check(board):
    dtbs, infos = _built(board)
    image.check_soc_dtbs({f"dtbs/{image.SOC_DIR[board]}/{p.name}": p for p in dtbs})
    assert sum(i["default"] for i in infos.values()) == 1


# --- build check of the folders --------------------------------------------------------

def _dtb(tmp_path, name, ident, default=False):
    props = {"lume,id": fdt.s(ident), "lume,priority": fdt.u32(0)}
    if default:
        props["lume,default"] = b""
    root = fdt.Node(props={"compatible": fdt.s("x,board", "rockchip,rk3326")},
                    children={"lume-select": fdt.Node(props=props)})
    path = tmp_path / name
    path.write_bytes(fdt.build(root))
    return path


def test_build_check_accepts_one_default_per_soc(tmp_path):
    image.check_soc_dtbs({
        "dtbs/a33/a.dtb": _dtb(tmp_path, "a.dtb", "a", default=True),
        "dtbs/a33/b.dtb": _dtb(tmp_path, "b.dtb", "b"),
        "dtbs/rk3326/c.dtb": _dtb(tmp_path, "c.dtb", "c", default=True),
        "r36s/Image": tmp_path / "not-read"})


@pytest.mark.parametrize("defaults, match", [((), "has 0"), (("a", "b"), "has 2")])
def test_build_check_needs_exactly_one_default(tmp_path, defaults, match):
    files = {f"dtbs/a33/{n}.dtb": _dtb(tmp_path, f"{n}.dtb", n, default=n in defaults)
             for n in ("a", "b")}
    with pytest.raises(image.ConsoleImageError, match=match):
        image.check_soc_dtbs(files)


def test_build_check_refuses_repeated_ids_and_dtbs_without_the_node(tmp_path):
    files = {"dtbs/a33/a.dtb": _dtb(tmp_path, "a.dtb", "same", default=True),
             "dtbs/a33/b.dtb": _dtb(tmp_path, "b.dtb", "same")}
    with pytest.raises(image.ConsoleImageError, match="repeated lume,id same"):
        image.check_soc_dtbs(files)
    bare = tmp_path / "bare.dtb"
    bare.write_bytes(fdt.build(fdt.Node(props={"compatible": fdt.s("x")})))
    with pytest.raises(image.ConsoleImageError, match="no lume-select node"):
        image.check_soc_dtbs({"dtbs/a33/bare.dtb": bare})


def test_fdt_round_trip_of_a_compiled_dtb():
    # the compiled DTBs of the scratch build or of out/: the reader handles dtc output
    dtbs = sorted((out_dir() / "r36s/kernel/dtbs").glob("*.dtb"))
    if not dtbs:
        pytest.skip("no compiled DTB")
    root = fdt.parse(dtbs[0].read_bytes())
    assert "rockchip,rk3326" in root.strings("compatible")
    again = fdt.parse(fdt.build(root))
    assert again.props == root.props and again.children.keys() == root.children.keys()
