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
	if (!strcmp(argv[1], "steps")) {
		for (p = 0; p <= 100; p++)
			printf("step %d %d %d\n", p, vol_step(p, 1, 5), vol_step(p, 0, 5));
		return 0;
	}
	if (!strcmp(argv[1], "convert")) {
		for (p = 0; p <= 192; p++)
			printf("conv %d %d\n", p, vol_convert_old(&VOL_GA36_DAC_OLD, p));
		return 0;
	}
	printf("old");
	for (int i = 2; i < argc; i++)
		printf(" %d", vol_convert_old(&VOL_GA36_DAC_OLD, atoi(argv[i])));
	printf("\n");
	return 0;
}
"""

SHELL_LIB = REPO_ROOT / "aports/lume-audio/files/usr/libexec/lume/volume.sh"
# the shell services print the raw of every percent on both controls and the conversion of
# every old DAC raw, as the C harness does
SHELL_HARNESS = r"""
. "$1"
p=0
while [ $p -le 100 ]; do
	echo "raw $p $(vol_raw 0 63 1500 $p) $(vol_raw 0 255 373 $p)"
	p=$((p + 1))
done
r=0
while [ $r -le 192 ]; do
	echo "conv $r $(vol_pct_from_raw 0 160 750 $r)"
	r=$((r + 1))
done
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


@pytest.fixture(scope="module")
def harness_exe(run, tmp_path_factory):
    # the run fixture compiled it; find it again by building a second copy (cheap)
    d = tmp_path_factory.mktemp("vol2")
    (d / "h.c").write_text(HARNESS)
    exe = d / "h"
    subprocess.run([CC, "-I", str(HEADER.parent), "-o", str(exe), str(d / "h.c")], check=True)
    return exe


def _lines(exe, mode, prefix):
    out = subprocess.run([str(exe), mode], capture_output=True, text=True, check=True).stdout
    return [list(map(int, l.split()[1:])) for l in out.splitlines() if l.startswith(prefix + " ")]


def test_key_steps_stay_on_the_5_percent_grid(harness_exe):
    steps = {p: (up, down) for p, up, down in _lines(harness_exe, "steps", "step")}
    assert steps[0] == (5, 0) and steps[100] == (100, 95)
    assert steps[87] == (90, 85) and steps[85] == (90, 80) and steps[3] == (5, 0)
    for p, (up, down) in steps.items():
        assert up == min(100, (p // 5 + 1) * 5) and down == max(0, -(-p // 5) * 5 - 5), p


def test_shell_services_use_the_same_scale(harness_exe):
    """mixer and jack (lume-audio) source volume.sh: the same table, raw positions and
    conversion of the old DAC as volume.h."""
    sh = shutil.which("busybox") or shutil.which("dash") or shutil.which("sh")
    if sh is None:
        pytest.skip("no shell")
    curve = re.search(r'^CURVE="([^"]*)"$', SHELL_LIB.read_text(), re.M).group(1)
    assert [int(n) for n in curve.split()] == _table(HEADER.read_text())
    args = [sh, "sh", "-c", SHELL_HARNESS, "x", str(SHELL_LIB)] if sh.endswith("busybox") else \
        [sh, "-c", SHELL_HARNESS, "x", str(SHELL_LIB)]
    out = subprocess.run(args, capture_output=True, text=True, check=True).stdout.splitlines()
    shell_raw = {int(l.split()[1]): tuple(map(int, l.split()[2:])) for l in out if l.startswith("raw ")}
    shell_conv = {int(l.split()[1]): int(l.split()[2]) for l in out if l.startswith("conv ")}
    out = subprocess.run([str(harness_exe), "ga36"], capture_output=True, text=True, check=True).stdout
    ga36 = {int(l.split()[0]): int(l.split()[2]) for l in out.splitlines() if l[0].isdigit()}
    out = subprocess.run([str(harness_exe), "r36s"], capture_output=True, text=True, check=True).stdout
    r36s = {int(l.split()[0]): int(l.split()[2]) for l in out.splitlines() if l[0].isdigit()}
    assert shell_raw == {p: (ga36[p], r36s[p]) for p in range(101)}
    assert shell_conv == {r: c for r, c in _lines(harness_exe, "convert", "conv")}


def test_old_digital_level_converts_to_the_nearest_position(run):
    _, old = run("ga36", 160, 166, 154, 130, 0, 1)
    assert old[0] == 100 and old[1] == 100     # 0 dB (and the old +4.5 dB) is the max clean
    assert old[2] == 85                        # 154 = -4.5 dB
    assert old[4] == 0                         # raw 0 is mute
    assert old[5] == 1                         # the lowest non-mute raw is not mute
    assert 35 <= old[3] <= 40                  # 130 = -22.5 dB, between the 40% and 35% points
