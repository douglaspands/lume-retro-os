"""lume-powerctl, the load controller (openspec game-governor D12, node 2.3).

The controller is built with the host compiler and run against a fake sysfs, a fake /proc and
a fake cgroup tree, with the fake clock: each line written to its stdin is the time that passed
(ms) and it answers "tick <now_ms> <load%|-> <khz>" after each sample.
"""

import hashlib
import os
import re
import shutil
import signal
import subprocess
from pathlib import Path

import pytest

from r36os.paths import REPO_ROOT

APORT = REPO_ROOT / "aports/lume-powerctl"
SOURCE = APORT / "powerctl.c"
CC = shutil.which("cc") or shutil.which("gcc")
HZ = os.sysconf("SC_CLK_TCK")

A33_FREQS = [120000, 240000, 312000, 408000, 480000, 504000, 600000, 648000, 720000, 816000,
             912000, 1008000]


@pytest.fixture(scope="module")
def exe(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler")
    out = tmp_path_factory.mktemp("powerctl") / "lume-powerctl"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-O2", "-o", str(out), str(SOURCE)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


class World:
    """sysfs + /proc + cgroup root, and one game process with two threads."""

    def __init__(self, tmp: Path, governors="ondemand userspace performance schedutil",
                 min_khz=600000, max_cap=1008000):
        self.tmp = tmp
        self.sys = tmp / "sys"
        self.cf = self.sys / "devices/system/cpu/cpu0/cpufreq"
        self.cf.mkdir(parents=True)
        for k, v in {
            "scaling_available_frequencies": " ".join(map(str, A33_FREQS)),
            "scaling_available_governors": governors,
            "scaling_governor": "schedutil",
            "scaling_min_freq": str(min_khz),
            "scaling_max_freq": str(max_cap),
            "cpuinfo_max_freq": "1008000",
            "scaling_setspeed": "<unsupported>",
        }.items():
            (self.cf / k).write_text(v + "\n")
        self.proc = tmp / "proc"
        self.cg = tmp / "cgroup"
        self.cg.mkdir()
        self.ticks = {}
        self.proc_ = None

    def game(self, n=1, pid=100, tids=(100, 101)):
        d = self.cg / f"game-{n}"
        d.mkdir(exist_ok=True)
        (d / "cgroup.procs").write_text(f"{pid}\n")
        for tid in tids:
            self.ticks[(pid, tid)] = 0
            self._write(pid, tid)
        return d

    def _write(self, pid, tid):
        d = self.proc / str(pid) / "task" / str(tid)
        d.mkdir(parents=True, exist_ok=True)
        # comm with spaces and parentheses, as a real one may have
        fields = ["S"] + ["0"] * 10 + [str(self.ticks[(pid, tid)]), "0"] + ["0"] * 30
        (d / "stat").write_text(f"{tid} (retro (arch) x) " + " ".join(fields) + "\n")

    def load(self, pid, tid, pct, ms=250):
        self.ticks[(pid, tid)] += round(pct * HZ * ms / 100000)
        self._write(pid, tid)

    def read(self, name):
        return (self.cf / name).read_text().strip()

    def start(self, exe, *args):
        self.proc_ = subprocess.Popen(
            [str(exe), "--sys", str(self.sys), "--proc", str(self.proc), "--cgroup",
             str(self.cg), "--fake-clock", *args],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            bufsize=1)
        first = self.proc_.stdout.readline()
        assert first.startswith("tick 0 "), first + self.proc_.stderr.read()
        return int(first.split()[3])

    def tick(self, ms=250, loads=None):
        """advances the clock one interval with the given thread loads; returns (load, khz)"""
        for (pid, tid), pct in (loads or {}).items():
            self.load(pid, tid, pct, ms)
        self.proc_.stdin.write(f"{ms}\n")
        self.proc_.stdin.flush()
        line = self.proc_.stdout.readline()
        assert line.startswith("tick "), line
        _, _, load, khz = line.split()
        return (None if load == "-" else int(load)), int(khz)

    def finish(self, timeout=5):
        out, err = self.proc_.communicate(timeout=timeout)
        return self.proc_.returncode, out.strip().splitlines()[-1] if out.strip() else "", err


def run_load(w, seconds, pct, tid=100):
    res = None
    for _ in range(int(seconds * 4)):
        res = w.tick(250, {(100, tid): pct})
    return res


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    if w.proc_ and w.proc_.poll() is None:
        w.proc_.kill()
        w.proc_.wait()


def test_refuses_without_the_userspace_governor(exe, tmp_path):
    w = World(tmp_path, governors="ondemand performance schedutil")
    r = subprocess.run([str(exe), "--sys", str(w.sys), "--proc", str(w.proc), "--cgroup",
                        str(w.cg), "--fake-clock"], capture_output=True, text=True, timeout=5)
    assert r.returncode == 3
    assert "refused: userspace governor not available" in r.stderr
    assert w.read("scaling_governor") == "schedutil"  # nothing changed
    assert w.read("scaling_setspeed") == "<unsupported>"


def test_refuses_without_a_step_in_the_range(exe, world):
    r = subprocess.run([str(exe), "--sys", str(world.sys), "--min", "1100000", "--max", "1200000",
                        "--fake-clock"], capture_output=True, text=True, timeout=5)
    assert r.returncode == 3 and "no frequency step" in r.stderr
    assert world.read("scaling_governor") == "schedutil"


def test_bad_arguments(exe):
    r = subprocess.run([str(exe), "--bogus", "1"], capture_output=True, text=True, timeout=5)
    assert r.returncode == 2 and "usage" in r.stderr


def test_starts_at_the_top_in_userspace_and_steps_down_after_3s_below_50(exe, world):
    world.game()
    assert world.start(exe) == 1008000
    assert world.read("scaling_governor") == "userspace"
    assert world.read("scaling_setspeed") == "1008000"
    # 2.75 s at 20%: not yet
    for _ in range(11):
        load, khz = world.tick(250, {(100, 100): 20})
        assert khz == 1008000
    assert load == 20
    load, khz = world.tick(250, {(100, 100): 20})
    assert khz == 912000 and world.read("scaling_setspeed") == "912000"
    # the timer restarts after a step: one step per 3 s
    _, khz = run_load(world, 2.75, 20)
    assert khz == 912000
    _, khz = world.tick(250, {(100, 100): 20})
    assert khz == 816000


def test_a_sample_inside_the_band_restarts_the_down_timer(exe, world):
    world.game()
    world.start(exe)
    run_load(world, 2.5, 20)
    _, khz = world.tick(250, {(100, 100): 60})       # 60%: neither up nor down
    run_load(world, 2.5, 20)
    assert khz == 1008000 and world.read("scaling_setspeed") == "1008000"


def test_steps_up_after_1s_above_85(exe, world):
    world.game()
    world.start(exe)
    _, khz = run_load(world, 9, 10)                   # three steps down
    assert khz == 720000
    for _ in range(3):
        _, khz = world.tick(250, {(100, 100): 95})
        assert khz == 720000
    _, khz = world.tick(250, {(100, 100): 95})
    assert khz == 816000
    _, khz = run_load(world, 1, 95)
    assert khz == 912000


def test_the_busiest_thread_counts_not_the_sum(exe, world):
    world.game()
    world.start(exe)
    run_load(world, 9, 10)
    # two threads at 60% each: 120% in total, but no single thread above 85%
    for _ in range(8):
        load, khz = world.tick(250, {(100, 100): 60, (100, 101): 60})
    assert load == 60 and khz == 720000
    for _ in range(4):
        load, khz = world.tick(250, {(100, 100): 10, (100, 101): 92})
    assert load == 92 and khz == 816000


def test_never_below_the_profile_min_nor_above_its_max(exe, world):
    world.game()
    # min defaults to scaling_min_freq (600000, the game floor the service wrote)
    assert world.start(exe, "--max", "912000") == 912000
    _, khz = run_load(world, 30, 0)
    assert khz == 600000
    _, khz = run_load(world, 10, 100)
    assert khz == 912000
    rc, summary, _ = world.finish()                    # end of stdin: stop
    assert rc == 0 and summary.endswith("end=stop")
    assert not re.search(r"\b(1008000|120000|504000)=", summary)


def test_respects_the_thermal_cap(exe, world):
    world.game()
    world.start(exe)
    (world.cf / "scaling_max_freq").write_text("816000\n")    # the kernel cooling lowered it
    _, khz = world.tick(250, {(100, 100): 100})
    assert khz == 816000 and world.read("scaling_setspeed") == "816000"
    _, khz = run_load(world, 5, 100)
    assert khz == 816000
    (world.cf / "scaling_max_freq").write_text("720000\n")
    _, khz = world.tick(250, {(100, 100): 100})
    assert khz == 720000
    # the cap goes away: back up one step per second, not a jump
    (world.cf / "scaling_max_freq").write_text("1008000\n")
    _, khz = run_load(world, 1, 100)
    assert khz == 816000
    _, khz = run_load(world, 2, 100)
    assert khz == 1008000


def test_stops_at_the_end_of_the_game_with_the_time_per_step(exe, world):
    cg = world.game()
    world.start(exe)
    run_load(world, 3, 20)                             # 3 s at 1008, then 912
    run_load(world, 2, 20)                             # 2 s at 912
    (cg / "cgroup.procs").write_text("")
    world.proc_.stdin.write("250\n")
    world.proc_.stdin.flush()
    rc, summary, err = world.finish()
    assert rc == 0, err
    assert summary == "1008000=3.0s 912000=2.2s up=0 down=1 end=game"


def test_the_cgroup_removed_also_ends_it(exe, world):
    cg = world.game()
    world.start(exe)
    world.tick()
    shutil.rmtree(cg)
    world.proc_.stdin.write("250\n")
    world.proc_.stdin.flush()
    rc, summary, _ = world.finish()
    assert rc == 0 and summary.endswith("end=game")


def test_sigterm_stops_with_the_summary(exe, world):
    world.game()
    world.start(exe)
    run_load(world, 1, 50)
    world.proc_.send_signal(signal.SIGTERM)
    rc, summary, _ = world.finish()
    assert rc == 0 and summary == "1008000=1.0s up=0 down=0 end=stop"


def test_waits_for_the_newest_game_cgroup(exe, world):
    old = world.cg / "game-3"
    old.mkdir()
    (old / "cgroup.procs").write_text("")
    os.utime(old, (1, 1))                               # an old, empty one
    world.start(exe, "--wait", "2000")
    load, khz = world.tick()
    assert load is None and khz == 1008000              # no game yet: the top
    world.game(n=1, pid=200, tids=(200,))               # lume-run numbers from 1 again
    world.tick()
    load, _ = world.tick(250, {(200, 200): 40})
    assert load == 40


def test_no_game_in_time_ends_it(exe, world):
    world.start(exe, "--wait", "1000")
    for _ in range(3):
        world.tick()
    world.proc_.stdin.write("250\n")
    world.proc_.stdin.flush()
    rc, summary, _ = world.finish()
    assert rc == 0 and summary.endswith("end=no-game")


def test_another_governor_takes_over_exit_4(exe, world):
    world.game()
    world.start(exe)
    world.tick()
    (world.cf / "scaling_governor").write_text("schedutil\n")
    world.proc_.stdin.write("250\n")
    world.proc_.stdin.flush()
    rc, summary, _ = world.finish()
    assert rc == 4 and summary.endswith("end=governor")


def test_the_owner_gone_ends_it(exe, world):
    world.game()
    dead = subprocess.Popen(["true"])
    dead.wait()
    r = subprocess.run([str(exe), "--sys", str(world.sys), "--proc", str(world.proc), "--cgroup",
                        str(world.cg), "--fake-clock", "--owner", str(dead.pid)],
                       capture_output=True, text=True, timeout=5)
    assert r.returncode == 0 and r.stdout.strip().endswith("end=owner")


def test_real_clock_samples_every_250ms(exe, world):
    """without --fake-clock: it sleeps between samples and SIGTERM ends the sleep at once"""
    world.game()
    p = subprocess.Popen([str(exe), "--sys", str(world.sys), "--proc", str(world.proc),
                          "--cgroup", str(world.cg)], stdout=subprocess.PIPE, text=True)
    try:
        p.wait(0.6)
    except subprocess.TimeoutExpired:
        pass
    p.send_signal(signal.SIGTERM)
    out, _ = p.communicate(timeout=2)
    assert p.returncode == 0 and out.strip().endswith("end=stop")
    assert world.read("scaling_setspeed") == "1008000"


def test_aport_lists_and_checksum():
    apkbuild = (APORT / "APKBUILD").read_text()
    assert re.search(r'^arch="x86_64 armv7 aarch64"$', apkbuild, re.M)
    digest = hashlib.sha512(SOURCE.read_bytes()).hexdigest()
    assert f"{digest}  powerctl.c" in apkbuild
    assert "lume-powerctl" in (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    text = "".join(p.read_text() for p in APORT.iterdir() if p.is_file())
    assert not any(ord(c) > 127 for c in text)
