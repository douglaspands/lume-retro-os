"""The per-output volume scale (device-fixes D9, D10, task 3.4): the C header of lume-input
and its Rust mirror in lume-ui hold the same curve, and the conversions behave."""
import re
import shutil
import subprocess

import pytest

from lume_tool.paths import REPO_ROOT

HEADER = REPO_ROOT / "aports/lume-input/volume.h"
RUST = REPO_ROOT / "lume/lume-ui/src/volume.rs"
DOC = REPO_ROOT / "docs/LAUNCHER.md"
CC = shutil.which("cc") or shutil.which("gcc")

HARNESS = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "volume.h"
int main(int argc, char **argv)
{
	const struct vol_control *c = !strcmp(argv[1], "ga36") ? &VOL_GA36_HEADPHONE : &VOL_R36S_MASTER;
	int p;

	for (p = 0; p <= 100; p++)
		printf("%d %d %d %d\n", p, vol_db(p), vol_raw(c, p), vol_pct_from_raw(c, vol_raw(c, p)));
	printf("old");
	for (int i = 2; i < argc; i++)
		printf(" %d", vol_convert_old(&VOL_GA36_DAC_OLD, atoi(argv[i])));
	printf("\n");
	return 0;
}
"""


def _table(text: str) -> list[int]:
    body = re.search(r"CURVE_MDB[^=]*=\s*\[(.*?)\];|vol_curve_mdb\[[^\]]*\]\s*=\s*\{(.*?)\};", text, re.S)
    nums = body.group(1) or body.group(2)
    return [int(n) for n in re.findall(r"-?\d+", nums)]


@pytest.fixture(scope="module")
def run(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler")
    d = tmp_path_factory.mktemp("vol")
    (d / "h.c").write_text(HARNESS)
    exe = d / "h"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-I", str(HEADER.parent), "-o", str(exe), str(d / "h.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr

    def go(console, *old):
        out = subprocess.run([str(exe), console, *map(str, old)], capture_output=True, text=True, check=True).stdout
        lines = [l.split() for l in out.splitlines()]
        rows = {int(l[0]): tuple(map(int, l[1:])) for l in lines if l[0] != "old"}
        return rows, [int(x) for x in lines[-1][1:]]
    return go


def test_c_and_rust_curves_agree():
    c, rs = _table(HEADER.read_text()), _table(RUST.read_text())
    assert c == rs and len(c) == 21
    # the doc shows the same numbers (dB = mdB / 1000)
    doc = DOC.read_text()
    for i in range(1, 21):
        assert f"| {i * 5} | {c[i] / 1000:.1f}".replace(".", ",") in doc, i * 5


@pytest.mark.parametrize("console,ref,lo", [("ga36", 63, 0), ("r36s", 255, 0)])
def test_scale_ends_and_monotonic(run, console, ref, lo):
    rows, _ = run(console)
    assert rows[0][1] == lo                    # 0 is mute: the control minimum
    assert rows[100][0] == 0 and rows[100][1] == ref  # 100 is the loudest clean position
    assert all(rows[p][1] > lo for p in range(1, 101))
    assert all(rows[p][0] >= rows[p - 1][0] for p in range(1, 101))   # dB never falls with the percent up
    assert all(rows[p][1] >= rows[p - 1][1] for p in range(1, 101))   # nor the raw position
    assert rows[100][0] - rows[95][0] <= 2000   # the first step down from 100 is small
    # every 5% step is 1.5 to 3 dB from 100 down to 5%
    assert all(1500 <= rows[p][0] - rows[p - 5][0] <= 3000 for p in range(10, 101, 5))
    assert -42000 <= rows[5][0] <= -38000      # the useful end is near -40 dB
    assert all(rows[p][2] == p or abs(rows[p][2] - p) <= 5 for p in range(5, 101))  # read back near the percent


def test_ga36_headphone_raw_values(run):
    rows, _ = run("ga36")
    assert rows[100][1] == 63 and rows[95][1] == 62 and rows[50][1] == 51 and rows[5][1] == 37


def test_old_digital_level_converts_to_the_nearest_position(run):
    _, old = run("ga36", 160, 166, 154, 130, 0, 1)
    assert old[0] == 100 and old[1] == 100     # 0 dB (and the old +4.5 dB) is the max clean
    assert old[2] == 85                        # 154 = -4.5 dB
    assert old[4] == 0                         # raw 0 is mute
    assert old[5] == 1                         # the lowest non-mute raw is not mute
    assert 35 <= old[3] <= 40                  # 130 = -22.5 dB, between the 40% and 35% points
