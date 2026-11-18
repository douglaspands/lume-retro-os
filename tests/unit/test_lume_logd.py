"""lume-logd, the sampling loop of the diagnostic logs in C (openspec game-governor 1.2, D8).

Built with the host compiler and run against a fake /proc (uptime, stat, meminfo) and /sys
(thermal zone, cpufreq policy, battery, OTG port), a fake RetroArch network command (UDP),
a fake shell logd (LOGD_CMD, records the flush/snapshot/kick calls) and real processes named
retroarch, lume-run... (copies of `sleep`). LOGD_SAMPLES and LOGD_NOWAIT run N samples back
to back. The expected lines are the ones tests/logs/test_logs.sh freezes for the shell loop,
so the card format does not change (docs/LOGS.md).
"""

import hashlib
import os
import re
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

import pytest

from r36os.paths import REPO_ROOT

APORT = REPO_ROOT / "aports/lume-logd"
SOURCE = APORT / "logd.c"
CC = shutil.which("cc") or shutil.which("gcc")
SLEEP = shutil.which("sleep")


@pytest.fixture(scope="module")
def exe(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler")
    out = tmp_path_factory.mktemp("lume-logd") / "lume-logd"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-O2", "-o", str(out), str(SOURCE)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


class RA(threading.Thread):
    """Fake RetroArch network command: answers GET_STATUS from a list of (reply, uptime of
    the next sample); the last entry repeats. reply None = no answer."""

    def __init__(self, world, script):
        super().__init__(daemon=True)
        self.world, self.script, self.i = world, script, 0
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.sock.settimeout(0.2)
        self.running = True

    def run(self):
        while self.running:
            try:
                msg, addr = self.sock.recvfrom(1024)
            except socket.timeout:
                continue
            if msg != b"GET_STATUS":
                continue
            reply, next_up = self.script[min(self.i, len(self.script) - 1)]
            self.i += 1
            if next_up is not None:
                self.world.uptime(next_up)
            if reply is not None:
                self.sock.sendto(reply.encode(), addr)

    def stop(self):
        self.running = False
        self.join(1)
        self.sock.close()


class World:
    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.proc = tmp / "proc"
        self.sys = tmp / "sys"
        self.ram = tmp / "ram"
        for d in (self.proc, self.ram):
            d.mkdir(parents=True)
        self.uptime(100.50)
        (self.proc / "stat").write_text(
            "cpu  150 0 150 1600 100 0 0 0 0 0\ncpu0 100 0 100 700 100 0 0 0 0 0\n"
            "cpu1 50 0 50 900 0 0 0 0 0 0\nintr 1 2 3\n")
        (self.proc / "meminfo").write_text(
            "MemTotal:         500000 kB\nMemFree:          100000 kB\nMemAvailable:     204800 kB\n"
            "SwapTotal:        102400 kB\nSwapFree:          51200 kB\n")
        z = self.sys / "class/thermal/thermal_zone0"
        z.mkdir(parents=True)
        (z / "temp").write_text("45678\n")
        (z / "type").write_text("cpu-thermal\n")
        (z / "trip_point_0_type").write_text("passive\n")
        (z / "trip_point_0_temp").write_text("70000\n")
        self.zone = z
        p = self.sys / "devices/system/cpu/cpufreq/policy0"
        p.mkdir(parents=True)
        (p / "scaling_cur_freq").write_text("1008000\n")
        b = self.sys / "class/power_supply/axp20x-battery"
        b.mkdir(parents=True)
        for k, v in {"type": "Battery", "capacity": "9", "voltage_now": "3700000",
                     "current_now": "-250000", "status": "Discharging"}.items():
            (b / k).write_text(v + "\n")
        self.bat = b
        self.conf = tmp / "logs.conf"
        self.conf.write_text("interval=5\nflush=60\n")
        self.frontend_log = tmp / "frontend.log"
        self.frontend_log.write_text("")
        self.interrupts = tmp / "interrupts"
        self.interrupts.write_text("")
        self.kmsg = tmp / "kmsg"
        self.kmsg.write_text("")
        self.calls = tmp / "calls"
        self.fake_logd = tmp / "fake-logd"
        self.fake_logd.write_text(
            f'#!/bin/sh\necho "$*" >> "{self.calls}"\n'
            'case "$1" in kick) exit "${FAKE_KICK:-2}" ;; esac\nexit 0\n')
        self.fake_logd.chmod(0o755)
        self.dri = tmp / "dri"
        self.dri.mkdir()
        (self.ram / "boot-n").write_text("7\n")
        self.procs = []
        self.ra = None
        self.env = {
            "PATH": os.environ["PATH"],
            "PROC_ROOT": str(self.proc), "SYS_ROOT": str(self.sys), "LOGS_RAM": str(self.ram),
            "LOGS_CONF": str(self.conf), "LUME_STATUS": str(tmp / "lume-status"),
            "FRONTEND_LOG": str(self.frontend_log), "INTERRUPTS_FILE": str(self.interrupts),
            "IRQ_SYS": str(tmp / "no-irq"), "DRI_DIR": str(self.dri),
            "ASOUND_DIR": str(tmp / "asound"), "GPU_DEVFREQ_DIR": str(tmp / "devfreq"),
            "KMSG_DEV": str(self.kmsg), "LOGD_CMD": str(self.fake_logd),
            "LUME_FRONTENDS": f"/no-such-frontends-{os.getpid()}/", "LOGD_NOWAIT": "1",
            "RA_PORT": "9", "TZ": "UTC0",
        }

    def uptime(self, v):
        (self.proc / "uptime").write_text(f"{v:.2f} 10.00\n")

    def spawn(self, name, *args):
        """a real process whose comm is <name> (a copy of sleep)"""
        b = self.tmp / "bin" / name
        b.parent.mkdir(exist_ok=True)
        if not b.exists():
            shutil.copy(SLEEP, b)
        p = subprocess.Popen([str(b), *(args or ("1000",))])
        self.procs.append(p)
        time.sleep(0.1)
        return p

    def fake_ra(self, script):
        self.ra = RA(self, script)
        self.ra.start()
        self.env["RA_PORT"] = str(self.ra.port)

    def run(self, exe, samples, **env):
        e = dict(self.env, LOGD_SAMPLES=str(samples), **{k: str(v) for k, v in env.items()})
        return subprocess.run([str(exe), "run"], env=e, capture_output=True, text=True, timeout=60)

    def lines(self, name):
        p = self.ram / name
        return p.read_text().splitlines() if p.exists() else []

    def metrics(self):
        return self.lines("metrics.pending")

    def events(self):
        return [l.split(" ", 2)[2] for l in self.lines("events.pending")]

    def trace(self):
        return [l.split(" ", 1)[1] for l in self.lines("trace.pending")]

    def shell_calls(self):
        return self.calls.read_text().splitlines() if self.calls.exists() else []

    def close(self):
        for p in self.procs:
            if p.poll() is None:
                p.kill()
            p.wait()
        if self.ra:
            self.ra.stop()


@pytest.fixture
def world(tmp_path):
    w = World(tmp_path)
    yield w
    w.close()


HEADER = ("time,uptime_s,temp_cpu_thermal_c,freq_policy0_mhz,cpu0_pct,cpu1_pct,mem_avail_mb,"
          "swap_used_mb,bat_pct,bat_mv,bat_ma,bat_status,frontend,core,content,fps,fps_nominal,"
          "lume_ui_rss_kb,lume_ui_cpu_pct,lume_run_rss_kb,lume_run_cpu_pct,input_rss_kb,input_cpu_pct")


def test_header_and_first_sample_are_the_frozen_shell_ones(exe, world):
    r = world.run(exe, 1)
    assert r.returncode == 0, r.stderr
    assert (world.ram / "metrics.header").read_text().strip() == HEADER
    m = world.metrics()
    assert len(m) == 1
    # the line tests/logs/test_logs.sh freezes for the shell ("cheap: first sample")
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d,100\.50,45\.7,1008,20,10,200,50,9,3700,-250,"
                        r"Discharging,stopped,,,,,,,,,,", m[0]), m[0]
    assert "battery FAIL below 10% (9%, 3700 mV, Discharging)" in world.events()
    assert any(re.fullmatch(r"fe=stopped pid=- gpu_mhz= vblank=", t) for t in world.trace())


def test_cpu_load_temperature_events_and_negative_temperature(exe, world):
    # one run: the cpu difference needs the previous sample, so the files change between
    # samples through the fake network command... here two runs show the first-sample rule
    # and the temperature events, which need no state between runs
    world.zone.joinpath("temp").write_text("71000\n")
    world.run(exe, 1)
    assert "temperature FAIL cpu-thermal 71 °C, above passive trip of 70 °C" in world.events()
    world.zone.joinpath("temp").write_text("-1250\n")
    world.run(exe, 1)
    assert world.metrics()[-1].split(",")[2] == "-1.3"


def test_temperature_back_under_the_trip_and_per_core_difference(exe, world):
    """two samples in one run: the fake network command changes the files between them"""
    world.zone.joinpath("temp").write_text("71000\n")
    rest = world.tmp / "next"
    rest.mkdir()

    def between():
        (world.proc / "stat").write_text(
            "cpu  250 0 200 1900 100 0 0 0 0 0\ncpu0 200 0 100 900 100 0 0 0 0 0\n"
            "cpu1 50 0 150 1000 0 0 0 0 0 0\nintr 1 2 3\n")
        world.zone.joinpath("temp").write_text("64000\n")
        world.uptime(101.00)
    # a retroarch makes logd ask the network command once per sample: the hook point
    world.spawn("retroarch")
    calls = {"n": 0}

    class Hook(RA):
        def run(self):
            while self.running:
                try:
                    msg, addr = self.sock.recvfrom(1024)
                except socket.timeout:
                    continue
                calls["n"] += 1
                if calls["n"] == 1:
                    between()
                self.sock.sendto(b"GET_STATUS CONTENTLESS", addr)
    world.ra = Hook(world, [])
    world.ra.start()
    world.env["RA_PORT"] = str(world.ra.port)
    world.run(exe, 2)
    m = world.metrics()
    assert m[1].split(",")[1:6] == ["101.00", "64.0", "1008", "33", "50"], m[1]
    ev = world.events()
    assert "temperature FAIL cpu-thermal 71 °C, above passive trip of 70 °C" in ev
    assert "temperature OK cpu-thermal back to 64 °C" in ev
    assert m[1].split(",")[12] == "menu"


def test_game_fps_slow_and_full_speed_events(exe, world):
    world.frontend_log.write_text(
        "[INFO] [Core] Geometry: 240x160, Aspect: 1.500, FPS: 59.73, Sample rate: 65536.00 Hz.\n")
    world.spawn("retroarch")
    # (reply, uptime of the next sample): 60.0, 46.7, 46.7 (slow), 59.7 (back)
    world.uptime(10.00)
    st = "GET_STATUS PLAYING gba,kart,crc32=1a2b3c,frames={}\n"
    world.fake_ra([(st.format(100), 17.50), (st.format(550), 25.00), (st.format(900), 32.50),
                   (st.format(1250), 40.00), (st.format(1600), 47.50), (st.format(2048), 55.0)])
    world.run(exe, 6, HANG_LIMIT=1000)
    fps = [l.split(",")[15] for l in world.metrics()]
    assert fps == ["", "60.0", "46.7", "46.7", "46.7", "59.7"], fps
    assert [l.split(",")[16] for l in world.metrics()] == ["59.73"] * 6
    ev = world.events()
    assert "game OK opened: core=gba content=kart" in ev
    assert ev.count("game FAIL slow: core=gba 46.7 fps (nominal 59.73) content=kart") == 1
    assert "game OK full speed again: core=gba 59.7 fps (nominal 59.73)" in ev
    line = world.metrics()[1]
    assert ",game,gba,kart,60.0,59.73," in line


def test_content_with_commas_and_crc_and_no_frames(exe, world):
    world.spawn("retroarch")
    world.fake_ra([("GET_STATUS PLAYING super_nes,A, B (U) [!],crc32=1,frames=10\n", None)])
    world.run(exe, 1, HANG_LIMIT=1000)
    f = world.metrics()[0].split(",")
    assert f[12:15] == ["game", "super_nes", "A; B (U) [!]"], f


def test_launcher_states_and_no_names_under_the_launcher(exe, world):
    status = world.tmp / "lume-status"
    world.spawn("lume-run")
    world.spawn("lume-ui")
    world.spawn("r36os-input")
    status.write_text("ui\n")
    world.run(exe, 2)
    m = world.metrics()
    assert re.search(r",launcher,,,,,[0-9]+,[0-9.]*,[0-9]+,[0-9.]*,[0-9]+,[0-9.]*$", m[-1]), m[-1]
    assert any(re.fullmatch(r"fe=launcher pid=- gpu_mhz= vblank=", t) for t in world.trace())
    status.write_text("game:love\n")
    world.run(exe, 1)
    f = world.metrics()[-1].split(",")
    assert f[12:15] == ["game", "love", ""]
    # a RetroArch game under the launcher: no content name, and no opened/closed lines
    world.spawn("retroarch")
    status.write_text("game:retroarch\n")
    world.fake_ra([("GET_STATUS PLAYING super_nes,Secret Title (U),crc32=1,frames=10\n", None)])
    world.run(exe, 1, HANG_LIMIT=1000)
    assert world.metrics()[-1].split(",")[12:15] == ["game", "super_nes", ""]
    assert not any(e.startswith("game ") for e in world.events())


def test_no_answer_hang_snapshot_and_recovery(exe, world):
    world.interrupts.write_text("171:       2842          7 GIC-0 118 Level     1c0c000.lcd-controller\n")
    ra = world.spawn("retroarch")
    world.fake_ra([(None, None)])            # alive but no answer
    world.run(exe, 3, RECOVER_MAX=2, KICK_MAX=0)
    ev = world.events()
    assert any(re.fullmatch(rf"frontend FAIL retroarch pid {ra.pid} hung: blocked with no CPU and no display "
                            rf"vblank for 10s \(state no_answer\); see trace/boot-7.log", e) for e in ev), ev
    assert any(f"frontend OK recovery 1 of 2: killed the hung retroarch pid {ra.pid}" in e for e in ev)
    assert any(e == f"frontend FAIL retroarch pid {ra.pid} alive but no answer for 15s; see trace/boot-7.log"
               for e in ev)
    ra.wait(5)
    assert ra.returncode == -signal.SIGKILL
    calls = world.shell_calls()
    assert f"snapshot {ra.pid} no_answer" in calls and "flush" in calls
    t = [x for x in world.trace() if x.startswith("fe=no_answer")]
    assert re.fullmatch(rf"fe=no_answer pid={ra.pid} st=[A-Z] utime=\d+ stime=\d+ threads=\d+ dri_fds=0 "
                        rf"gpu_mhz= vblank=2849 pcm=- tasks= {ra.pid}:[A-Z]:\S*", t[0]), t[0]


def test_hang_with_recovery_off_only_logs(exe, world):
    world.interrupts.write_text("171:       100          0 GIC-0 118 Level     1c0c000.lcd-controller\n")
    ra = world.spawn("retroarch")
    world.fake_ra([("GET_STATUS CONTENTLESS", None)])
    world.run(exe, 3, RECOVER_MAX=0, KICK_MAX=0)
    assert ra.poll() is None
    assert any(" hung: blocked" in e for e in world.events())
    assert not any("recovery" in e for e in world.events())


def test_kick_brings_the_display_back_and_the_process_lives(exe, world):
    world.interrupts.write_text("171:       100          0 GIC-0 118 Level     1c0c000.lcd-controller\n")
    ra = world.spawn("retroarch")
    world.fake_ra([("GET_STATUS CONTENTLESS", None)])
    world.run(exe, 2, RECOVER_MAX=2, KICK_MAX=5, FAKE_KICK=0)
    assert ra.poll() is None
    assert any(f"frontend OK recovery: re-enabled the masked display vblank interrupt; the display runs again, "
               f"watching retroarch pid {ra.pid} (kick 1 of 5)" == e for e in world.events())
    assert "kick" in world.shell_calls()


def test_no_vblank_counter_never_hangs_by_the_first_rule(exe, world):
    """without a display controller the snapshot and kick are not tried on the first
    blocked sample (the shell's [ -n "$vb" ]); the hang is still declared"""
    ra = world.spawn("retroarch")
    world.fake_ra([("GET_STATUS CONTENTLESS", None)])
    world.run(exe, 3, RECOVER_MAX=0)
    assert "kick" not in world.shell_calls()
    assert any(" hung: blocked" in e for e in world.events())
    assert ra.poll() is None


def test_usb_trace_and_events(exe, world):
    s = world.sys
    for d in ("class/extcon/extcon0", "bus/platform/devices/musb-hdrc.1.auto", "class/udc/musb-hdrc.1.auto",
              "class/power_supply/axp20x-usb", "bus/usb/devices/usb1", "bus/usb/devices/1-0:1.0"):
        (s / d).mkdir(parents=True)
    (s / "class/extcon/extcon0/name").write_text("1c19400.phy\n")
    (s / "class/extcon/extcon0/state").write_text("USB=1\nUSB-HOST=0\n")
    (s / "bus/platform/devices/musb-hdrc.1.auto/mode").write_text("b_peripheral\n")
    (s / "class/udc/musb-hdrc.1.auto/state").write_text("configured\n")
    (s / "class/power_supply/axp20x-usb/type").write_text("USB\n")
    (s / "class/power_supply/axp20x-usb/online").write_text("1\n")
    world.run(exe, 2)
    want = ("extcon=1c19400.phy:USB=1,USB-HOST=0 musb=b_peripheral udc=musb-hdrc.1.auto:configured "
            "vbus=axp20x-usb:1 host_devs=0")
    assert [t for t in world.trace() if t.startswith("usb: ")] == [f"usb: {want}"] * 2
    ev = world.events()
    assert ev.count(f"usb OK otg: {want}") == 1
    assert ev.count("usb OK device: connected") == 1


def test_usb_none_on_the_vm(exe, world):
    world.run(exe, 1)
    assert "usb: none" in world.trace()
    assert not any(e.startswith("usb ") for e in world.events())


def test_kernel_messages_are_traced_once_from_the_start(exe, world):
    world.uptime(2.00)
    world.kmsg.write_text("6,1,1000000,-;old message\n6,2,12345678,-;lume: hello kernel\n SUBSYSTEM=usb\n"
                          "4,3,123000001,-;second line\n6,1,1000000,-;old message\n")
    world.run(exe, 2)
    k = [t for t in world.trace() if t.startswith("k ")]
    assert k == ["k [   12.345678] lume: hello kernel", "k [  123.000001] second line"], k


def test_audio_stall_and_resume_events(exe, world):
    world.frontend_log.write_text("[ERROR] [ALSA] Playback stalled: no room in the buffer after 500 ms.\n")
    world.run(exe, 1)
    ev = world.events()
    assert ev.count("audio FAIL playback stalled: the sound device stopped consuming, the game keeps running "
                    "without sound; see frontend/boot-7.log") == 1
    with world.frontend_log.open("a") as f:
        f.write("[INFO] [ALSA] Playback consuming again, audio resumed.\n")
    world.run(exe, 1)
    assert "audio OK playback consuming again, sound resumed" in world.events()


def test_vblank_from_the_irq_directory(exe, world):
    irq = world.tmp / "irq"
    for n, act, cnt in (("25", "arch_timer", "9061,8051"), ("171", "1c0c000.lcd-controller", "2842,7")):
        (irq / n).mkdir(parents=True)
        (irq / n / "actions").write_text(act + "\n")
        (irq / n / "per_cpu_count").write_text(cnt + "\n")
    # only with the real /proc/interrupts does logd use the irq directory
    world.run(exe, 1, IRQ_SYS=irq, INTERRUPTS_FILE="/proc/interrupts")
    assert any(t.endswith("vblank=2849") for t in world.trace()), world.trace()


def test_flush_every_interval_and_on_term(exe, world):
    world.conf.write_text("interval=1\nflush=5\n")
    e = dict(world.env)
    e.pop("LOGD_NOWAIT")
    p = subprocess.Popen([str(exe), "run"], env=e)
    time.sleep(1.5)
    p.send_signal(signal.SIGTERM)
    assert p.wait(5) == 0
    assert len(world.metrics()) >= 2
    assert world.shell_calls()[-1] == "flush"


def test_aport_and_image():
    apkbuild = (APORT / "APKBUILD").read_text()
    assert re.search(r'^arch="x86_64 armv7 aarch64"$', apkbuild, re.M)
    assert f"{hashlib.sha512(SOURCE.read_bytes()).hexdigest()}  logd.c" in apkbuild
    assert "lume-logd" in (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    logd = (REPO_ROOT / "aports/lume-core/files/usr/libexec/r36os/logd").read_text()
    assert 'exec "$LUME_LOGD" run' in logd and "snapshot) cmd_snapshot" in logd and "kick) cmd_kick" in logd
    assert not any(ord(c) > 127 for c in (APORT / "APKBUILD").read_text())
