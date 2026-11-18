"""r36os-powerctl --mode auto, the bottleneck controller (openspec game-governor D17, node 2.5).

Same fake world as test_r36os_powerctl.py (fake sysfs, /proc and cgroup, fake clock), plus a
GPU devfreq and the DRM fdinfo of the game: drm-client-id, drm-page-flips (kernel patch 0036)
and drm-engine-* (patch 0035 on lima, panfrost upstream). Each tick is one 1 s window and
prints "tick <ms> cpu=<load> gpu=<busy> fps=<fps> -> <cpu khz> <gpu hz> <bottleneck>".
"""

import os
import re
import shutil
import signal
import subprocess
from pathlib import Path

import pytest

from r36os.paths import REPO_ROOT

SOURCE = REPO_ROOT / "aports/r36os-powerctl/powerctl.c"
CC = shutil.which("cc") or shutil.which("gcc")
HZ = os.sysconf("SC_CLK_TCK")

A33_FREQS = [120000, 240000, 312000, 408000, 480000, 504000, 600000, 648000, 720000, 816000,
             912000, 1008000]
GPU_FREQS = [144000000, 240000000, 384000000]


@pytest.fixture(scope="module")
def exe(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler")
    out = tmp_path_factory.mktemp("powerctl-auto") / "r36os-powerctl"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-O2", "-o", str(out), str(SOURCE)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


class World:
    def __init__(self, tmp: Path, min_khz=600000, flips=True, engines=("gp", "pp")):
        self.tmp = tmp
        self.sys = tmp / "sys"
        self.cf = self.sys / "devices/system/cpu/cpu0/cpufreq"
        self.cf.mkdir(parents=True)
        for k, v in {
            "scaling_available_frequencies": " ".join(map(str, A33_FREQS)),
            "scaling_available_governors": "ondemand userspace performance schedutil",
            "scaling_governor": "schedutil",
            "scaling_min_freq": str(min_khz),
            "scaling_max_freq": "1008000",
            "scaling_cur_freq": "1008000",
            "cpuinfo_max_freq": "1008000",
            "scaling_setspeed": "<unsupported>",
        }.items():
            (self.cf / k).write_text(v + "\n")
        self.gpu = self.sys / "class/devfreq/1c40000.gpu"
        self.gpu.mkdir(parents=True)
        for k, v in {
            "available_frequencies": " ".join(map(str, GPU_FREQS)),
            "min_freq": "144000000",
            "max_freq": "384000000",
            "cur_freq": "144000000",
        }.items():
            (self.gpu / k).write_text(v + "\n")
        self.proc = tmp / "proc"
        self.proc.mkdir()
        (self.proc / "meminfo").write_text("MemTotal: 1000000 kB\nMemAvailable: 600000 kB\nCmaFree: 50000 kB\n")
        self.cg = tmp / "cgroup"
        self.cg.mkdir()
        self.ticks = 0
        self.flips = 0
        self.eng_ns = {e: 0 for e in engines}
        self.has_flips = flips
        self.p = None
        self.state = tmp / "run/powerctl.state"
        self.state.parent.mkdir()

    def game(self, pid=100, fds=(5,), client_id=7):
        d = self.cg / "game-1"
        d.mkdir(exist_ok=True)
        (d / "cgroup.procs").write_text(f"{pid}\n")
        self.pid = pid
        self.fds = fds
        self.client_id = client_id
        (self.proc / str(pid) / "fd").mkdir(parents=True)
        (self.proc / str(pid) / "fdinfo").mkdir()
        os.symlink("/dev/null", self.proc / str(pid) / "fd" / "0")
        for fd in fds:
            os.symlink("/dev/dri/card0", self.proc / str(pid) / "fd" / str(fd))
        self._write()

    def _write(self):
        d = self.proc / str(self.pid) / "task" / str(self.pid)
        d.mkdir(parents=True, exist_ok=True)
        fields = ["S"] + ["0"] * 10 + [str(self.ticks), "0"] + ["0"] * 30
        (d / "stat").write_text(f"{self.pid} (retroarch) " + " ".join(fields) + "\n")
        info = f"pos:\t0\nflags:\t02\ndrm-driver:\tlima\ndrm-client-id:\t{self.client_id}\n"
        for e, ns in self.eng_ns.items():
            info += f"drm-engine-{e}:\t{ns} ns\n"
        if self.has_flips:
            info += f"drm-page-flips:\t{self.flips}\n"
        for fd in self.fds:
            (self.proc / str(self.pid) / "fdinfo" / str(fd)).write_text(info)

    def start(self, exe, *args):
        self.p = subprocess.Popen(
            [str(exe), "--mode", "auto", "--sys", str(self.sys), "--proc", str(self.proc),
             "--cgroup", str(self.cg), "--state", str(self.state), "--fake-clock", *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            bufsize=1)
        first = self.p.stdout.readline()
        assert first.startswith("tick 0 "), first + self.p.stderr.read()
        return self._parse(first)

    @staticmethod
    def _parse(line):
        m = re.match(r"tick (\d+) cpu=(-?\d+) gpu=(-?\d+) fps=(-?\d+) -> (-?\d+) (-?\d+) (\w+)$",
                     line.strip())
        assert m, line
        return {"cpu": int(m[2]), "gpu": int(m[3]), "fps": int(m[4]), "khz": int(m[5]),
                "hz": int(m[6]), "b": m[7]}

    def tick(self, cpu=20, gpu=20, fps=60, ms=1000):
        self.ticks += round(cpu * HZ * ms / 100000)
        # the busiest engine carries the load; the other one half of it
        names = list(self.eng_ns)
        for i, e in enumerate(names):
            self.eng_ns[e] += int(gpu * ms * 10000 / (1 if i == len(names) - 1 else 2))
        self.flips += round(fps * ms / 1000)
        self._write()
        self.p.stdin.write(f"{ms}\n")
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        assert line.startswith("tick "), line + self.p.stderr.read()
        return self._parse(line)

    def run(self, n, **kw):
        r = None
        for _ in range(n):
            r = self.tick(**kw)
        return r

    def finish(self, timeout=5):
        out, err = self.p.communicate(timeout=timeout)
        return self.p.returncode, out.strip().splitlines()[-1] if out.strip() else "", err

    def cpu(self, name):
        return (self.cf / name).read_text().strip()

    def gpu_file(self, name):
        return (self.gpu / name).read_text().strip()


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    if w.p and w.p.poll() is None:
        w.p.kill()
        w.p.wait()


def settle(w, fps=60):
    """slack on both until the CPU and the GPU reach the bottom of their ranges"""
    return w.run(40, cpu=10, gpu=10, fps=fps)


def test_starts_at_the_top_of_both_ranges(exe, world):
    world.game()
    r = world.start(exe)
    assert (r["khz"], r["hz"]) == (1008000, 384000000)
    assert world.cpu("scaling_governor") == "userspace"
    assert world.cpu("scaling_setspeed") == "1008000"
    assert world.gpu_file("min_freq") == "384000000"


def test_slack_lowers_both_down_to_the_profile_floors(exe, world):
    world.game()
    world.start(exe)
    r = settle(world)
    assert (r["khz"], r["hz"]) == (600000, 144000000)   # the CPU stops at the game floor
    assert r["b"] == "none"


def test_gpu_bound_raises_only_the_gpu(exe, world):
    world.game()
    world.start(exe)
    settle(world)
    r = world.tick(cpu=20, gpu=95, fps=60)
    assert (r["khz"], r["hz"], r["b"]) == (600000, 240000000, "gpu")
    r = world.tick(cpu=20, gpu=95, fps=60)
    assert (r["khz"], r["hz"]) == (600000, 384000000)
    assert world.gpu_file("min_freq") == "384000000"
    assert world.cpu("scaling_setspeed") == "600000"


def test_cpu_bound_raises_only_the_cpu(exe, world):
    world.game()
    world.start(exe)
    settle(world)
    r = world.run(3, cpu=95, gpu=20, fps=60)
    assert (r["khz"], r["hz"], r["b"]) == (816000, 144000000, "cpu")


def test_frames_lost_with_nothing_saturated_raise_the_busier_one(exe, world):
    world.game()
    world.start(exe)
    settle(world)
    r = world.tick(cpu=40, gpu=70, fps=50)              # below 90% of 60, nobody above 85%
    assert (r["khz"], r["hz"]) == (600000, 144000000)   # one window: it waits
    r = world.tick(cpu=40, gpu=70, fps=50)
    assert (r["khz"], r["hz"], r["b"]) == (600000, 240000000, "pacing")
    r = world.tick(cpu=70, gpu=40, fps=50)
    assert (r["khz"], r["hz"], r["b"]) == (648000, 240000000, "pacing")


def test_the_beat_of_a_60_fps_core_on_a_slower_panel_is_not_a_drop(exe, world):
    world.game()
    world.start(exe)
    settle(world, fps=55)
    for fps in (55, 53, 54, 55, 53, 51, 55, 54):        # threaded video on the 55.7 Hz panel
        r = world.tick(cpu=60, gpu=10, fps=fps)
        assert (r["khz"], r["b"]) == (600000, "none"), r


def test_frames_lost_with_both_idle_is_sync_and_never_raises_a_clock(exe, world):
    """the GA36 case: a 60 fps core on the 55.7 Hz panel delivers 42-47 frames with the CPU
    and the GPU almost idle; more clock does not help, so nothing goes up and the left-over
    clocks still go down"""
    world.game()
    world.start(exe)
    world.run(6, cpu=10, gpu=10, fps=56)                # learn the target
    r = world.tick(cpu=10, gpu=8, fps=44)
    assert r["b"] == "sync"
    # inside the 30 s target window: still sync, and both clocks went down meanwhile
    r = world.run(20, cpu=10, gpu=8, fps=44)
    assert (r["khz"], r["hz"], r["b"]) == (600000, 144000000, "sync")


def test_no_step_down_while_frames_are_lost_nor_right_after_a_step_up(exe, world):
    world.game()
    world.start(exe)
    settle(world)
    world.tick(cpu=20, gpu=95, fps=60)                  # GPU up to 240
    r = world.run(4, cpu=10, gpu=10, fps=60)            # slack, but within 5 s of the step up
    assert r["hz"] == 240000000
    r = world.run(6, cpu=10, gpu=10, fps=60)
    assert r["hz"] == 144000000


def test_a_game_drawing_at_30_is_not_slow(exe, world):
    world.game()
    world.start(exe)
    r = world.run(40, cpu=10, gpu=10, fps=30)
    assert (r["khz"], r["hz"], r["b"]) == (600000, 144000000, "none")


def test_locked_gpu_is_never_touched(exe, world):
    world.game()
    (world.gpu / "min_freq").write_text("240000000\n")
    world.start(exe, "--gpu-min", "240000000", "--gpu-max", "240000000")
    r = world.run(5, cpu=20, gpu=99, fps=40)
    assert r["hz"] == -1                                # not controlled
    assert world.gpu_file("min_freq") == "240000000"
    rc, summary, _ = world.finish()
    assert rc == 0 and " gpu: up=" in summary


def test_locked_cpu_keeps_its_governor(exe, world):
    world.game()
    r = world.start(exe, "--min", "1008000", "--max", "1008000")
    assert r["khz"] == -1
    assert world.cpu("scaling_governor") == "schedutil"
    assert world.cpu("scaling_setspeed") == "<unsupported>"
    r = world.run(3, cpu=99, gpu=99, fps=60)
    assert r["b"] == "gpu"                              # only the GPU can move


def test_without_page_flips_it_works_on_load_alone(exe, tmp_path):
    w = World(tmp_path, flips=False)
    try:
        w.game()
        w.start(exe)
        r = w.run(40, cpu=10, gpu=10, fps=0)            # no frame signal: never "slow"
        assert (r["khz"], r["hz"], r["b"], r["fps"]) == (600000, 144000000, "none", -1)
        r = w.tick(cpu=95, gpu=10)
        assert (r["khz"], r["b"]) == (648000, "cpu")
    finally:
        if w.p and w.p.poll() is None:
            w.p.kill()


def test_one_client_open_twice_counts_once(exe, tmp_path):
    w = World(tmp_path)
    try:
        w.game(fds=(5, 9))                              # the same drm-client-id on two fds
        w.start(exe)
        r = w.run(3, cpu=10, gpu=50, fps=60)
        assert r["gpu"] == 50 and r["fps"] == 60
    finally:
        if w.p and w.p.poll() is None:
            w.p.kill()


def test_thermal_cap_is_respected_and_reported(exe, world):
    world.game()
    world.start(exe)
    (world.cf / "scaling_max_freq").write_text("816000\n")
    (world.gpu / "max_freq").write_text("240000000\n")
    r = world.run(3, cpu=99, gpu=99, fps=40)
    assert (r["khz"], r["hz"], r["b"]) == (816000, 240000000, "thermal")


def test_state_file_and_summary(exe, world):
    world.game()
    world.start(exe)
    world.run(3, cpu=30, gpu=95, fps=60)
    st = dict(line.split(" ", 1) for line in world.state.read_text().splitlines())
    assert st["mode"] == "auto" and st["bottleneck"] == "gpu"
    assert st["gpu_busy"] == "95" and st["fps"] == "60.0" and st["fps_target"] == "60.0"
    assert st["mem_avail_kb"] == "600000"
    assert not any(ord(c) > 127 for c in world.state.read_text())
    world.p.send_signal(signal.SIGTERM)
    rc, summary, _ = world.finish()
    assert rc == 0
    # the GPU is saturated at its top (hardware limit, not thermal); the idle CPU stepped down
    assert re.match(r"cpu: 1008000=\d+\.\ds gpu: 384000000=\d+\.\ds up=0 down=1 "
                    r"bottleneck cpu=0 gpu=3 pacing=0 thermal=0 memory=0 sync=0 mem_min=600000k end=stop$",
                    summary), summary
    assert not world.state.exists()                     # removed at the end
    assert world.gpu_file("min_freq") == "144000000"    # the profile floor is back


def test_low_memory_is_only_reported(exe, world):
    world.game()
    (world.proc / "meminfo").write_text("MemAvailable: 20000 kB\nCmaFree: 100 kB\n")
    world.start(exe)
    r = world.tick(cpu=60, gpu=60, fps=60)
    assert r["b"] == "memory"


def test_end_of_the_game(exe, world):
    world.game()
    world.start(exe)
    world.tick()
    (world.cg / "game-1" / "cgroup.procs").write_text("")
    world.p.stdin.write("1000\n")
    world.p.stdin.flush()
    rc, summary, _ = world.finish()
    assert rc == 0 and summary.endswith("end=game")
    assert world.gpu_file("min_freq") == "144000000"
