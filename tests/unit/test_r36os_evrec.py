"""r36os-evrec (change virtual-gamepad, task 2.1, D2): the record and play binary of the
r36os-input aport, built with the host compiler and run against fake nodes (regular files in
a fake /dev/input and a fake /proc/bus/input/devices) with the fake clock or the real one."""

import hashlib
import os
import re
import shutil
import signal
import struct
import subprocess
import time

import pytest

from r36os import evrec
from r36os.paths import REPO_ROOT

APORT = REPO_ROOT / "aports/r36os-input"
CC = shutil.which("cc") or shutil.which("gcc")

# struct input_event on a 64-bit host: struct timeval (2 x long), u16 type, u16 code, s32 value
EVENT = struct.Struct("qqHHi")
EV_SYN, EV_KEY = 0, 1
BTN_A, BTN_B, BTN_START = 0x130, 0x131, 0x13B
SYN = (EV_SYN, 0, 0)

DEVICES = {
    "ga36": ('I: Bus=0019 Vendor=0001 Product=0001 Version=0100\n'
             'N: Name="GA36-MB Gamepad"\nH: Handlers=kbd event0\nB: EV=b\n\n'
             'I: Bus=0006 Vendor=1209 Product=3601 Version=0001\n'
             'N: Name="GA36-MB Gamepad"\nH: Handlers=js0 event3\nB: EV=b\n\n'),
    "r36s": ('I: Bus=0019 Vendor=0001 Product=0001 Version=0100\n'
             'N: Name="gpio-keys"\nH: Handlers=kbd event1\n\n'
             'I: Bus=0006 Vendor=1209 Product=3602 Version=0001\n'
             'N: Name="R36S Gamepad"\nH: Handlers=event4 js0\n\n'),
}
VIRTUAL_NODE = {"ga36": "event3", "r36s": "event4"}


@pytest.fixture(scope="module")
def exe(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler")
    if EVENT.size != 24:
        pytest.skip("the tests read the 64-bit struct input_event")
    out = tmp_path_factory.mktemp("evrec") / "r36os-evrec"
    r = subprocess.run([CC, "-O2", "-Wall", "-Wextra", "-Werror", "-o", str(out),
                        str(APORT / "evrec.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


class Console:
    """A fake console: the devices list, the /dev/input nodes (empty regular files)."""

    def __init__(self, exe, tmp, board="ga36", clock="fake"):
        self.exe, self.tmp = exe, tmp
        (tmp / "input").mkdir(parents=True)
        for node in ("event0", "event1", "event3", "event4"):
            (tmp / "input" / node).write_bytes(b"")
        (tmp / "devices").write_text(DEVICES[board])
        self.env = {**os.environ, "R36OS_EVREC_DEVICES": str(tmp / "devices"),
                    "R36OS_EVREC_INPUT_DIR": str(tmp / "input")}
        if clock:
            self.env["R36OS_EVREC_CLOCK"] = clock
        else:
            self.env.pop("R36OS_EVREC_CLOCK", None)
        self.node = tmp / "input" / VIRTUAL_NODE[board]

    def recording(self, board, lines, end):
        path = self.tmp / "rec.evrec"
        path.write_text(f"# r36os-evrec 1 {board}\n" + "".join(f"{l}\n" for l in lines)
                        + f"# end {end}\n")
        return path

    def run(self, *args, timeout=20):
        return subprocess.run([str(self.exe), *map(str, args)], env=self.env,
                              capture_output=True, text=True, timeout=timeout)

    def popen(self, *args):
        return subprocess.Popen([str(self.exe), *map(str, args)], env=self.env,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    def written(self, node=None):
        """(ms, type, code, value) of every event written to the node."""
        data = (node or self.node).read_bytes()
        assert len(data) % EVENT.size == 0
        out = []
        for i in range(0, len(data), EVENT.size):
            sec, usec, etype, code, value = EVENT.unpack_from(data, i)
            out.append(((sec * 1_000_000 + usec) / 1000, etype, code, value))
        return out


def _delay(stdout):
    m = re.search(r"^delay max=(\d+\.\d{3}) mean=(\d+\.\d{3}) events=(\d+)$", stdout, re.M)
    assert m, stdout
    return float(m.group(1)), float(m.group(2)), int(m.group(3))


def _wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


# ---- play ----

def test_play_keeps_the_recorded_times_with_the_fake_clock(exe, tmp_path):
    c = Console(exe, tmp_path, clock="fake:1500")
    rec = c.recording("ga36", [
        f"0 1 {BTN_A} 1", "0 0 0 0",
        f"100 1 {BTN_A} 0", "100 0 0 0",
        f"250 1 {BTN_B} 1",                       # no SYN in the file: play adds one
        f"1000 1 {BTN_B} 0", "1000 0 0 0",
        "1000 0 0 0",                             # an empty report is not sent
    ], end=1200)
    r = c.run("play", rec)
    assert r.returncode == 0, r.stderr
    assert c.written() == [
        (1.5, EV_KEY, BTN_A, 1), (1.5, *SYN),
        (101.5, EV_KEY, BTN_A, 0), (101.5, *SYN),
        (251.5, EV_KEY, BTN_B, 1), (251.5, *SYN),
        (1001.5, EV_KEY, BTN_B, 0), (1001.5, *SYN),
    ]
    assert _delay(r.stdout) == (1.5, 1.5, 4)


def test_play_on_time_with_the_real_clock(exe, tmp_path):
    c = Console(exe, tmp_path, clock=None)
    times = [0, 50, 120, 200, 300]
    lines = []
    for i, ms in enumerate(times):
        lines += [f"{ms} 1 {BTN_A} {1 - i % 2}", f"{ms} 0 0 0"]
    rec = c.recording("ga36", lines, end=350)
    start = time.monotonic()
    r = c.run("play", rec)
    took = time.monotonic() - start
    assert r.returncode == 0, r.stderr
    keys = [e for e in c.written() if e[1] == EV_KEY]
    assert [round(k[0]) >= ms for k, ms in zip(keys, times)] == [True] * 5
    # loose bounds for a busy host; the 10 ms target is measured on the GA36 (V1)
    assert all(k[0] - ms < 30 for k, ms in zip(keys, times)), keys
    max_ms, mean_ms, n = _delay(r.stdout)
    assert n == 5 and 0 <= mean_ms <= max_ms < 30
    assert took >= 0.35                           # waits until the end marker
    # A was pressed by the last event: released at the end
    assert len(c.written()) == 12
    assert [e[1:] for e in c.written()[-2:]] == [(EV_KEY, BTN_A, 0), SYN]


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_interrupted_play_releases_the_held_keys(exe, tmp_path, sig):
    c = Console(exe, tmp_path, clock=None)
    rec = c.recording("ga36", [f"0 1 {BTN_A} 1", f"0 1 {BTN_START} 1", "0 0 0 0",
                               f"20000 1 {BTN_A} 0", "20000 0 0 0"], end=20000)
    p = c.popen("play", rec)
    assert _wait_for(lambda: len(c.written()) >= 3)
    time.sleep(0.2)                               # in the middle of the hold
    p.send_signal(sig)
    out, err = p.communicate(timeout=3)
    assert p.returncode == 128 + sig, err
    ev = [e[1:] for e in c.written()]
    assert ev[:3] == [(EV_KEY, BTN_A, 1), (EV_KEY, BTN_START, 1), SYN]
    assert sorted(ev[3:5]) == [(EV_KEY, BTN_A, 0), (EV_KEY, BTN_START, 0)] and ev[5:] == [SYN]
    assert "released 2 key(s)" in err
    assert _delay(out)[2] == 2


def test_recording_of_another_console_is_refused_before_any_key(exe, tmp_path):
    c = Console(exe, tmp_path, board="r36s")
    r = c.run("play", c.recording("ga36", [f"0 1 {BTN_A} 1", "0 0 0 0"], end=10))
    assert r.returncode == 3
    assert "recording is for ga36, not r36s" in r.stderr
    assert c.node.read_bytes() == b""


@pytest.mark.skipif(os.geteuid() == 0, reason="root writes any file")
def test_play_without_write_permission_is_refused(exe, tmp_path):
    c = Console(exe, tmp_path)
    c.node.chmod(0o444)
    r = c.run("play", c.recording("ga36", [f"0 1 {BTN_A} 1", "0 0 0 0"], end=10))
    assert r.returncode == 3
    assert "play needs root" in r.stderr
    assert c.node.read_bytes() == b""


@pytest.mark.parametrize("body,line", [
    ("0 1 304 1\n", 3),                           # no end marker
    ("5 1 304 1\n4 1 304 0\n# end 10\n", 3),      # time goes backwards
    ("0 1 304\n# end 10\n", 2),                   # three fields
    ("0  1 304 1\n# end 10\n", 2),                # double space
    ("0 -1 304 1\n# end 10\n", 2),                # negative type
    ("\n0 1 304 1\n# end 10\n", 2),               # blank line
    ("0 1 304 1\n# end 0x\n", 3),                 # bad end time
])
def test_malformed_recording_is_refused_with_the_line(exe, tmp_path, body, line):
    c = Console(exe, tmp_path)
    path = tmp_path / "bad.evrec"
    text = "# r36os-evrec 1 ga36\n" + body
    path.write_text(text)
    with pytest.raises(evrec.EvrecError):        # the Python reader agrees
        evrec.parse(text)
    r = c.run("play", path)
    assert r.returncode == 1
    assert f"line {line}:" in r.stderr
    assert c.node.read_bytes() == b""


def test_data_after_the_end_and_bad_header_are_refused(exe, tmp_path):
    c = Console(exe, tmp_path)
    path = tmp_path / "bad.evrec"
    path.write_text("# r36os-evrec 1 ga36\n# end 0\n0 1 304 1\n")
    r = c.run("play", path)
    assert r.returncode == 1 and "line 3: data after the end marker" in r.stderr
    path.write_text("# r36os-evrec 2 ga36\n# end 0\n")
    r = c.run("play", path)
    assert r.returncode == 1 and "line 1: bad header" in r.stderr


def test_kernel_pad_on_ga36_and_refused_on_r36s(exe, tmp_path):
    c = Console(exe, tmp_path / "ga36")
    r = c.run("play", c.recording("ga36", [f"0 1 {BTN_A} 1", "0 0 0 0"], end=0),
              "--pad", "kernel")
    assert r.returncode == 0, r.stderr
    assert [e[1:] for e in c.written(tmp_path / "ga36/input/event0")][:2] == [(EV_KEY, BTN_A, 1), SYN]
    c = Console(exe, tmp_path / "r36s", board="r36s")
    r = c.run("play", c.recording("r36s", [f"0 1 {BTN_A} 1", "0 0 0 0"], end=0),
              "--pad", "kernel")
    assert r.returncode == 3 and "other codes" in r.stderr
    assert (tmp_path / "r36s/input/event1").read_bytes() == b""


def test_no_virtual_pad_and_usage(exe, tmp_path):
    c = Console(exe, tmp_path)
    (tmp_path / "devices").write_text(DEVICES["ga36"].replace("Bus=0006", "Bus=0003"))
    r = c.run("play", c.recording("ga36", [], end=0))
    assert r.returncode == 1 and "no virtual gamepad" in r.stderr
    assert c.run().returncode == 2
    assert c.run("play").returncode == 2
    assert c.run("play", "x", "--pad", "other").returncode == 2
    assert c.run("record").returncode == 2


# ---- record ----

def _source_events(path, events):
    """Write events with timestamps in ms (fake clock: relative to the start)."""
    path.write_bytes(b"".join(EVENT.pack(ms // 1000, (ms % 1000) * 1000, t, code, value)
                              for ms, t, code, value in events))


def test_record_then_play_round_trip(exe, tmp_path):
    c = Console(exe, tmp_path / "rec")
    source = [(0, EV_KEY, BTN_A, 1), (0, *SYN), (180, EV_KEY, BTN_A, 0), (180, *SYN),
              (400, EV_KEY, BTN_B, 1), (400, *SYN), (395, EV_SYN, 3, 0),   # SYN_DROPPED
              (1250, EV_KEY, BTN_B, 0), (1250, *SYN)]
    _source_events(c.node, source)
    out = tmp_path / "out.evrec"
    p = c.popen("record", out)
    assert _wait_for(lambda: out.exists() and out.read_text().count("\n") >= 9)
    p.send_signal(signal.SIGTERM)
    stdout, err = p.communicate(timeout=3)
    assert p.returncode == 0, err
    assert "recorded events=4 ms=1250" in stdout
    assert "dropped" in err
    rec = evrec.read(out, expect_console="ga36")
    assert rec.end_ms == 1250
    assert [(e.ms, e.type, e.code, e.value) for e in rec.events] == [
        (0, EV_KEY, BTN_A, 1), (0, *SYN), (180, EV_KEY, BTN_A, 0), (180, *SYN),
        (400, EV_KEY, BTN_B, 1), (400, *SYN), (1250, EV_KEY, BTN_B, 0), (1250, *SYN)]

    c2 = Console(exe, tmp_path / "play")
    r = c2.run("play", out)
    assert r.returncode == 0, r.stderr
    assert [(e[0], *e[1:]) for e in c2.written()] == [
        (float(e.ms), e.type, e.code, e.value) for e in rec.events]


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_record_with_the_real_clock_ends_promptly_on_a_signal(exe, tmp_path, sig):
    c = Console(exe, tmp_path, clock=None)
    out = tmp_path / "out.evrec"
    p = c.popen("record", out)
    assert _wait_for(lambda: out.exists() and out.read_text().startswith("# r36os-evrec 1 ga36\n"))
    time.sleep(0.3)
    # a regular file has no EVIOCSCLOCKID: times are taken when the event is read
    with open(c.node, "ab") as f:
        f.write(EVENT.pack(0, 0, EV_KEY, BTN_A, 1) + EVENT.pack(0, 0, *SYN))
    assert _wait_for(lambda: out.read_text().count("\n") >= 3)
    sent = time.monotonic()
    p.send_signal(sig)
    p.communicate(timeout=3)
    assert time.monotonic() - sent < 1.0
    assert p.returncode == 0
    rec = evrec.read(out, expect_console="ga36")
    assert [(e.type, e.code, e.value) for e in rec.events] == [(EV_KEY, BTN_A, 1), SYN]
    assert rec.events[0].ms >= 250 and rec.end_ms >= rec.events[0].ms


def test_record_refuses_without_a_virtual_pad(exe, tmp_path):
    c = Console(exe, tmp_path)
    (tmp_path / "devices").write_text(DEVICES["ga36"].split("\n\n")[0] + "\n")
    r = c.run("record", tmp_path / "out.evrec")
    assert r.returncode == 1 and "no virtual gamepad" in r.stderr
    assert not (tmp_path / "out.evrec").exists()


# ---- the aport ----

def test_aport_builds_and_installs_evrec_with_checksum():
    apkbuild = (APORT / "APKBUILD").read_text()
    digest = hashlib.sha512((APORT / "evrec.c").read_bytes()).hexdigest()
    assert f"{digest}  evrec.c" in apkbuild
    assert re.search(r"^\tevrec\.c$", apkbuild, re.M)
    assert re.search(r"-o r36os-evrec evrec\.c$", apkbuild, re.M)
    assert 'install -Dm755 r36os-evrec "$pkgdir"/usr/bin/r36os-evrec' in apkbuild
    source = (APORT / "evrec.c").read_text()
    # no grab while recording; absolute sleeps on the monotonic clock while playing
    assert "ioctl(fd, EVIOCGRAB" not in source
    assert "clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME" in source
