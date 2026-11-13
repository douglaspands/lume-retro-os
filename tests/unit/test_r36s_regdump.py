"""board/r36s/diag/regdump.sh: register dump of the R36S display path (task 4.6)."""

import os
import shutil
import struct
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "board/r36s/diag/regdump.sh"

DSI = 0xFF450000
DPHY = 0xFF2E0000


def test_regdump_reads_32bit_words_of_each_region(tmp_path):
    ports = tmp_path / "ports"
    ports.mkdir()
    script = ports / "regdump.sh"
    shutil.copy(SCRIPT, script)
    mem = tmp_path / "mem"
    with mem.open("wb") as f:  # sparse stand-in for /dev/mem
        f.truncate(0xFF470000)  # past the VOP, the highest region
        f.seek(DSI + 0x04)
        f.write(struct.pack("<I", 0x3133302A))  # DSI_VERSION of the PX30 host
        f.seek(DPHY + 0x0C)
        f.write(struct.pack("<I", 0x0000002D))
    env = dict(os.environ, MEM=str(mem))
    res = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True,
                         timeout=60, check=False)
    assert res.returncode == 0, res.stdout + res.stderr
    (out,) = (tmp_path / "regdump").iterdir()
    dsi = (out / "dsi.txt").read_text().splitlines()
    assert dsi[0] == "# dsi base 0xff450000 size 0x200"
    assert len(dsi) == 1 + 0x200 // 4
    assert "0xff450004 0x0004 0x3133302a" in dsi
    assert "0xff2e000c 0x000c 0x0000002d" in (out / "dphy.txt").read_text()
    for name in ("vop", "grf", "cru", "pmucru"):
        assert (out / f"{name}.txt").exists()
    assert (out / "regs.err").read_text() == ""


def test_regdiff_compares_a_dump_folder_with_a_boot_log(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location("regdiff", REPO_ROOT / "board/r36s/diag/regdiff.py")
    regdiff = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(regdiff)

    factory = tmp_path / "factory"
    factory.mkdir()
    for name in regdiff.REGIONS:
        (factory / f"{name}.txt").write_text(f"# {name} base 0x0 size 0x8\n")
    (factory / "dsi.txt").write_text(
        "# dsi base 0xff450000 size 0x8\n"
        "0xff450000 0x0000 0x3133302a\n"
        "0xff450004 0x0004 0x00000001\n"
        "0xff450008 0x0008 0x00000a02\n")
    log = tmp_path / "boot-13.log"
    lines = [f"[ 2.8] dw-mipi-dsi-rockchip ff450000.dsi: regdump {n} 0x0 0x0000 0x0" for n in regdiff.REGIONS]
    lines += [
        "[ 2.8] dw-mipi-dsi-rockchip ff450000.dsi: regdump dsi 0xff450000 0x0000 0x3133302a",
        "[ 2.8] dw-mipi-dsi-rockchip ff450000.dsi: regdump dsi 0xff450008 0x0008 0x00000a03",
        "[ 2.8] dw-mipi-dsi-rockchip ff450000.dsi: regdump dsi 0xff45000c 0x000c 0x00000001",
    ]
    log.write_text("\n".join(lines) + "\n")
    out = regdiff.diff(regdiff.load(factory), regdiff.load(log))
    # 0x04 only on the factory side (zero in the log), 0x08 differs, 0x0c only in the log
    assert out == ["dsi 0x0004 0x00000001 0x00000000",
                   "dsi 0x0008 0x00000a02 0x00000a03",
                   "dsi 0x000c 0x00000000 0x00000001"]
