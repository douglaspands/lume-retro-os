"""Test candidates for proof 6.4, from the native R36S V5 tree (not the default, no rule):
  blank: the panel node disabled (black screen, the kernel runs)
  hang:  no interrupt controller (the kernel panics early and stays there)
Usage: mk_test_dtb.py <blank|hang> <in.dtb> <out.dtb>"""
import sys

from r36os import fdt

mode, src, dst = sys.argv[1:4]
root = fdt.parse(open(src, "rb").read())
sel = root.path("/lume-select")
sel.props["lume,id"] = fdt.s(f"r36s-v5-{mode}")
sel.props["lume,priority"] = fdt.u32(0)
sel.props.pop("lume,default", None)
sel.props.pop("lume,panel-id", None)
if mode == "blank":
    dsi = next(k for k in root.children if k.startswith("dsi@"))
    panel = root.children[dsi].children["panel@0"]
    panel.props["status"] = fdt.s("disabled")
elif mode == "uboot":
    pass                        # proof 1.1: the same tree under another name
elif mode == "hang":
    gic = [k for k in root.children if k.startswith("interrupt-controller@")]
    assert len(gic) == 1, gic
    del root.children[gic[0]]
else:
    raise SystemExit(f"unknown mode {mode}")
data = fdt.build(root)
open(dst, "wb").write(data)
print(fdt.select_info(fdt.parse(data)), len(data), "bytes")
