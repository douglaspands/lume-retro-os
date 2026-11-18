"""Tests for the lume-power service (openspec game-governor, node 2.2).

The service is POSIX shell: each test runs it with `sh` against a fake sysfs tree, talks to it
through its FIFO and reads the sysfs writes (PW_TRACE), the events and power.state.
"""

import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import pytest

from lume_tool.paths import REPO_ROOT

POWER = REPO_ROOT / "aports/lume-power/files"
SERVICE = POWER / "usr/bin/lume-power"
INIT = POWER / "etc/init.d/lume-power"
CORE_LIB = REPO_ROOT / "aports/lume-core/files/usr/libexec/lume"
GA36_CONF = POWER / "usr/share/lume/power/ga36.conf"
R36S_CONF = POWER / "usr/share/lume/power/r36s.conf"
CONFIGURE_SH = REPO_ROOT / "rootfs/configure.sh"
SYSTEMS_JSON = REPO_ROOT / "aports/lume-games/files/usr/share/lume/systems.json"

# the OPP table of the mainline sun8i-a33.dtsi, in kHz
A33_FREQS = "120000 240000 312000 408000 480000 504000 600000 648000 720000 816000 912000 1008000"


def make_sysfs(root: Path, cores=4, gov="schedutil") -> Path:
    cpu = root / "devices/system/cpu"
    cf = cpu / "cpu0/cpufreq"
    cf.mkdir(parents=True)
    files = {
        "scaling_available_frequencies": A33_FREQS,
        "scaling_available_governors": "conservative ondemand userspace powersave performance schedutil",
        "scaling_governor": gov,
        "cpuinfo_min_freq": "120000",
        "cpuinfo_max_freq": "1008000",
        "scaling_min_freq": "120000",
        "scaling_max_freq": "1008000",
    }
    for k, v in files.items():
        (cf / k).write_text(v + "\n")
    (cpu / "cpu0/online").write_text("1\n")  # some kernels have it: it must never be written
    for n in range(1, cores):
        (cpu / f"cpu{n}").mkdir()
        (cpu / f"cpu{n}/online").write_text("1\n")
    (cpu / "cpufreq/ondemand").mkdir(parents=True)
    gpu = root / "class/devfreq/1c40000.gpu"
    gpu.mkdir(parents=True)
    (gpu / "available_frequencies").write_text("144000000 240000000 384000000\n")
    (gpu / "max_freq").write_text("384000000\n")
    (gpu / "min_freq").write_text("144000000\n")
    bat = root / "class/power_supply/axp20x-battery"
    bat.mkdir(parents=True)
    (bat / "type").write_text("Battery\n")
    (bat / "capacity").write_text("80\n")
    (bat / "status").write_text("Discharging\n")
    usb = root / "class/power_supply/axp20x-usb"
    usb.mkdir(parents=True)
    (usb / "type").write_text("USB\n")
    return root


class Service:
    def __init__(self, tmp: Path, conf: str | None = None, card: str | None = None, board="ga36",
                 tick=60, boot_n=True, cores=4, gov="schedutil", ra_port=1, lang=None):
        self.tmp = tmp
        self.sys = make_sysfs(tmp / "sys", cores=cores, gov=gov)
        self.run = tmp / "run"
        self.run.mkdir()
        self.logs = tmp / "logs"
        self.logs.mkdir()
        if boot_n:
            (self.logs / "boot-n").write_text("7\n")
        lib = tmp / "lib"
        lib.mkdir()
        for f in ("lib.sh", "logs.sh"):
            shutil.copy(CORE_LIB / f, lib / f)
        shutil.copy(POWER / "usr/libexec/lume/power-profiles.sh", lib)
        share = tmp / "share"
        share.mkdir()
        if conf is not None:
            (share / f"{board}.conf").write_text(conf)
        self.card = tmp / "power.conf"
        if card is not None:
            self.card.write_text(card)
        (tmp / "board").write_text(board + "\n")
        self.trace = tmp / "trace"
        self.poweroff = tmp / "poweroff"
        fake_poweroff = tmp / "fake-poweroff"
        fake_poweroff.write_text(f"#!/bin/sh\necho off >> '{self.poweroff}'\n")
        fake_poweroff.chmod(0o755)
        ra_cfg = tmp / "retroarch.cfg"
        if lang is not None:
            ra_cfg.write_text(f'user_language = "{lang}"\n')
        self.env = {
            **os.environ,
            "PP_SYS": str(self.sys),
            "PW_RUN": str(self.run),
            "PW_SHARE": str(share),
            "PW_CARD": str(self.card),
            "PW_TICK": str(tick),
            "PW_LIBDIR": str(lib),
            "PW_RA_PORT": str(ra_port),
            "PW_POWEROFF": str(fake_poweroff),
            "PW_GROUP": str(os.getgid()),
            "PW_TRACE": str(self.trace),
            "BOARD_FILE": str(tmp / "board"),
            "LOGS_RAM": str(self.logs),
            "RA_USER_CFG": str(ra_cfg),
            "RA_FACTORY_CFG": str(tmp / "none.cfg"),
        }
        self.proc = None

    # --- process ---
    def start(self):
        self.proc = subprocess.Popen(["sh", str(SERVICE), "run"], env=self.env,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.wait(lambda: (self.run / "power.state").exists(), "power.state")
        return self

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.proc.wait(5)

    def cli(self, *args):
        return subprocess.run(["sh", str(SERVICE), *args], env=self.env, capture_output=True,
                              text=True, timeout=10)

    def send(self, line: str):
        fd = os.open(self.run / "power", os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, (line + "\n").encode())
        finally:
            os.close(fd)

    def wait(self, cond, what, timeout=10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if cond():
                return
            if self.proc and self.proc.poll() is not None:
                raise AssertionError(f"service exited: {self.proc.stderr.read()}")
            time.sleep(0.05)
        raise AssertionError(f"timeout waiting for {what}")

    # --- observations ---
    def events(self):
        p = self.logs / "events.pending"
        return [line.split(" ", 2)[2] for line in p.read_text().splitlines()] if p.exists() else []

    def wait_event(self, text, count=1):
        self.wait(lambda: sum(text in e for e in self.events()) >= count, text)

    def writes(self):
        return self.trace.read_text().splitlines() if self.trace.exists() else []

    def clear_writes(self):
        self.trace.write_text("")

    def state(self):
        return (self.run / "power.state").read_text().splitlines()

    def sysfs(self, rel):
        return (self.sys / rel).read_text().strip()

    def set_battery(self, capacity, status="Discharging"):
        bat = self.sys / "class/power_supply/axp20x-battery"
        (bat / "capacity").write_text(f"{capacity}\n")
        (bat / "status").write_text(f"{status}\n")


@pytest.fixture
def services():
    started = []

    def make(tmp, **kw):
        s = Service(tmp, **kw)
        started.append(s)
        return s

    yield make
    for s in started:
        s.stop()


CF = "devices/system/cpu/cpu0/cpufreq"

PROFILES = """\
limit game_min=600000
profile boot  governor=performance
profile menu  governor=ondemand min=120000 max=816000 cores=2 up_threshold=30 gpu_max=144000000
profile idle  governor=schedutil min=120000 max=480000 cores=1
profile game
profile gba   min=1008000
class gba gba
battery warn=5 critical=3
"""


def test_boot_profile_at_start_and_d4_write_order(tmp_path, services):
    s = services(tmp_path, conf=PROFILES).start()
    assert s.writes() == [f"{CF}/scaling_governor performance"]
    s.wait_event("profile: boot -> boot")
    assert "scenario boot" in s.state() and "current boot" in s.state()

    s.clear_writes()
    s.send("menu")
    s.wait_event("profile: menu -> menu")
    # lowering: min first, then max; governor; parameter; extra cores; GPU last
    assert s.writes() == [
        f"{CF}/scaling_max_freq 816000",
        f"{CF}/scaling_governor ondemand",
        "devices/system/cpu/cpufreq/ondemand/up_threshold 30",
        "devices/system/cpu/cpu2/online 0",
        "devices/system/cpu/cpu3/online 0",
        "class/devfreq/1c40000.gpu/max_freq 144000000",
    ]

    s.clear_writes()
    s.send("idle")
    s.wait_event("profile: idle -> idle")
    assert s.writes() == [
        f"{CF}/scaling_max_freq 480000",
        f"{CF}/scaling_governor schedutil",
        "devices/system/cpu/cpu1/online 0",
        "class/devfreq/1c40000.gpu/max_freq 384000000",  # back to the kernel default
    ]

    # raising above the current max: max first, then min; missing cores come first
    s.clear_writes()
    s.send("game gba gpsp")
    s.wait_event("profile: game -> gba")
    assert s.writes() == [
        "devices/system/cpu/cpu1/online 1",
        "devices/system/cpu/cpu2/online 1",
        "devices/system/cpu/cpu3/online 1",
        f"{CF}/scaling_max_freq 1008000",
        f"{CF}/scaling_min_freq 1008000",
    ]
    assert "scenario game" in s.state() and "current gba" in s.state()

    s.clear_writes()
    s.send("end")
    s.wait_event("profile: menu -> menu", count=2)
    assert s.writes()[0] == f"{CF}/scaling_min_freq 120000"  # lowering: min first


def test_cpu0_is_never_taken_offline(tmp_path, services):
    conf = "profile menu cores=1\nprofile idle cores=1 governor=powersave\n"
    s = services(tmp_path, conf=conf).start()
    s.send("menu")
    s.wait_event("profile: menu -> menu")
    s.send("idle")
    s.wait_event("profile: idle -> idle")
    assert s.sysfs("devices/system/cpu/cpu1/online") == "0"
    assert s.sysfs("devices/system/cpu/cpu3/online") == "0"
    assert not any("cpu0/online" in w for w in s.writes())
    assert s.sysfs("devices/system/cpu/cpu0/online") == "1"


def test_ga36_conf_boot_default_game_floor_and_slow_launcher_rate(tmp_path, services):
    s = services(tmp_path, conf=GA36_CONF.read_text())
    (s.sys / "devices/system/cpu/cpufreq/schedutil").mkdir(parents=True, exist_ok=True)
    fake_controller(s)                       # the GA36 game profiles run controller=auto
    s.start()
    s.wait_event("profile: boot -> default")
    assert s.writes() == []  # no boot profile: nothing changes
    assert "current -" in s.state()
    s.send("game nes fceumm")
    s.wait_event("profile: game -> game")
    assert s.writes() == [f"{CF}/scaling_min_freq 600000",
                          "devices/system/cpu/cpufreq/schedutil/rate_limit_us 2000"]
    assert s.sysfs(f"{CF}/scaling_governor") == "schedutil"
    s.send("end")
    s.wait_event("profile: menu -> menu")
    assert s.sysfs(f"{CF}/scaling_min_freq") == "120000"
    assert s.sysfs("devices/system/cpu/cpufreq/schedutil/rate_limit_us") == "100000"
    s.send("idle")
    s.wait_event("profile: idle -> idle")
    assert s.sysfs("devices/system/cpu/cpufreq/schedutil/rate_limit_us") == "200000"


def test_a_profile_without_rate_limit_puts_the_kernel_one_back(tmp_path, services):
    s = services(tmp_path, conf=GA36_CONF.read_text(), card="enabled 0\n")
    su = s.sys / "devices/system/cpu/cpufreq/schedutil"
    su.mkdir(parents=True, exist_ok=True)
    (su / "rate_limit_us").write_text("366\n")
    s.start()
    s.wait_event("disabled: enabled 0")
    # profiles off from the start: the menu stays on the kernel rate
    s.send("menu")
    s.wait_event("profile: menu -> default")
    assert s.sysfs("devices/system/cpu/cpufreq/schedutil/rate_limit_us") == "366"
    # profiles on: the menu slows it down; switched off again, the kernel rate comes back
    s.card.write_text("")
    s.send("reload")
    s.wait_event("profile: menu -> menu")
    assert s.sysfs("devices/system/cpu/cpufreq/schedutil/rate_limit_us") == "100000"
    s.card.write_text("enabled 0\n")
    s.send("reload")
    s.wait_event("profile: menu -> default", count=2)
    assert s.sysfs("devices/system/cpu/cpufreq/schedutil/rate_limit_us") == "366"


def test_refused_game_profile_keeps_the_floor(tmp_path, services):
    conf = "limit game_min=600000\nprofile psxp governor=ondemand min=240000\nclass psx psxp\n"
    s = services(tmp_path, conf=conf).start()
    s.wait_event("rejected profile psxp: min 240000 below game floor 600000")
    s.send("game psx pcsx_rearmed")
    s.wait_event("profile: game -> default")
    assert s.sysfs(f"{CF}/scaling_min_freq") == "600000"
    assert s.sysfs(f"{CF}/scaling_governor") == "schedutil"  # kernel governor
    assert any(x.startswith("refused image profile psxp") for x in s.state())


def test_enabled_0_keeps_only_the_game_floor(tmp_path, services):
    s = services(tmp_path, conf=PROFILES, card="enabled 0\n").start()
    s.wait_event("disabled: enabled 0")
    s.wait_event("profile: boot -> default")
    assert s.writes() == []
    s.send("menu")
    s.wait_event("profile: menu -> default")
    s.send("game gba gpsp")
    s.wait_event("profile: game -> default")
    assert s.sysfs(f"{CF}/scaling_min_freq") == "600000"  # floor, not the gba 1008000
    assert s.sysfs(f"{CF}/scaling_governor") == "schedutil"
    assert "enabled card 0" in s.state()


def test_reload_changes_the_profile_of_the_next_game_only(tmp_path, services):
    s = services(tmp_path, conf=PROFILES).start()
    s.send("game nes fceumm")
    s.wait_event("profile: game -> game")
    s.card.write_text("profile light min=816000\nclass nes light\n")
    s.send("reload")
    s.wait(lambda: "class card nes light" in s.state(), "reloaded state")
    # mid-game nothing changes
    assert "current game" in s.state()
    assert s.sysfs(f"{CF}/scaling_min_freq") == "600000"
    assert "profile card light min=816000" in s.state()
    s.send("end")
    s.send("game nes fceumm")
    s.wait_event("profile: game -> light")
    assert s.sysfs(f"{CF}/scaling_min_freq") == "816000"


def test_reload_outside_a_game_applies_now(tmp_path, services):
    s = services(tmp_path, conf=PROFILES).start()
    s.send("menu")
    s.wait_event("profile: menu -> menu")
    s.card.write_text("profile menu max=648000\n")
    s.send("reload")
    s.wait(lambda: s.sysfs(f"{CF}/scaling_max_freq") == "648000", "menu reapplied")
    assert "profile card menu max=648000" in s.state()


def test_power_state_content(tmp_path, services):
    s = services(tmp_path, conf=PROFILES, card="idle after=300\n").start()
    st = s.state()
    assert st[0] == "console ga36"
    assert "enabled default 1" in st
    assert f"cpu_freqs {A33_FREQS}" in st
    assert "cpu_cores 4" in st
    assert "gpu_freqs 144000000 240000000 384000000" in st
    assert "game_min 600000" in st
    assert "profile image gba min=1008000" in st
    assert "profile image game min=600000" in st
    assert "class image gba gba" in st
    assert "battery image warn=5 critical=3" in st
    assert "idle card after=300" in st
    assert st[-2:] == ["scenario boot", "current boot"]
    mode = (s.run / "power.state").stat().st_mode & 0o777
    assert mode == 0o640
    assert not (s.run / "power.state.tmp").exists()
    fifo = s.run / "power"
    assert fifo.is_fifo() and fifo.stat().st_mode & 0o777 == 0o620


def test_battery_default_line_without_battery_entry(tmp_path, services):
    s = services(tmp_path, conf=R36S_CONF.read_text().replace("battery warn=5 critical=3", ""),
                 board="r36s").start()
    assert "battery default warn=5 critical=3" in s.state()
    assert not any(x.startswith("game_min") for x in s.state())


def test_manual_mode_applies_now_and_auto_goes_back(tmp_path, services):
    s = services(tmp_path, conf=PROFILES).start()
    s.send("game nes fceumm")
    s.wait_event("profile: game -> game")
    r = s.cli("set", "idle")
    assert r.returncode == 0, r.stderr
    s.wait_event("manual: idle")
    s.wait_event("profile: game -> idle (manual)")
    assert s.sysfs(f"{CF}/scaling_max_freq") == "480000"
    assert "manual idle" in s.state()
    # scenario changes keep the manual profile
    s.send("end")
    s.wait_event("profile: menu -> idle (manual)")
    r = s.cli("set", "nosuch")
    assert r.returncode == 1 and "unknown profile" in r.stderr
    r = s.cli("auto")
    assert r.returncode == 0, r.stderr
    s.wait(lambda: "power OK auto" in s.events(), "auto event")
    s.wait_event("profile: menu -> menu")
    assert s.sysfs(f"{CF}/scaling_max_freq") == "816000"
    assert not any(x.startswith("manual") for x in s.state())


def test_cli_without_service_fails_cleanly(tmp_path):
    s = Service(tmp_path, conf=PROFILES)
    r = s.cli("reload")
    assert r.returncode == 1 and "not running" in r.stderr
    assert not (s.run / "power").exists()


def test_events_before_logd_wait_for_the_boot_number(tmp_path, services):
    s = services(tmp_path, conf=PROFILES + "turbo on\n", boot_n=False).start()
    assert s.events() == []
    early = (s.run / "power.early").read_text()
    assert "FAIL image: rejected turbo" in early and "OK profile: boot -> boot" in early
    (s.logs / "boot-n").write_text("12\n")
    s.send("menu")
    s.wait_event("profile: menu -> menu")
    lines = (s.logs / "events.pending").read_text().splitlines()
    assert all(line.split()[1] == "12" for line in lines)
    assert [line.split(" ", 2)[2] for line in lines][:2] == [
        "power FAIL image: rejected turbo -: unknown line turbo",
        "power OK profile: boot -> boot",
    ]
    assert not (s.run / "power.early").exists()


def test_battery_warning_once_and_not_while_charging(tmp_path, services):
    ra = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ra.bind(("127.0.0.1", 0))
    ra.settimeout(5)
    port = ra.getsockname()[1]
    try:
        s = services(tmp_path, conf=PROFILES, ra_port=port, lang="7").start()
        s.send("game nes fceumm")
        s.wait_event("profile: game -> game")
        # charging at the warning level: nothing
        s.set_battery(5, "Charging")
        s.send("game nes fceumm")
        s.wait_event("profile: game -> game", count=2)
        time.sleep(0.3)
        assert not any("warning" in e for e in s.events())
        # discharging: one warning, with SHOW_MSG to RetroArch in the system language
        s.set_battery(5)
        s.send("game nes fceumm")
        s.wait_event("warning: battery 5%")
        msg, _ = ra.recvfrom(512)
        assert msg.decode() == "SHOW_MSG Bateria fraca (5%): ligue o carregador"
        s.set_battery(4)
        s.send("game nes fceumm")
        s.wait_event("profile: game -> game", count=4)
        time.sleep(0.3)
        assert sum("warning" in e for e in s.events()) == 1
        # charger plugged and pulled again: a new discharge warns again
        s.set_battery(4, "Charging")
        s.send("menu")
        s.wait_event("profile: menu -> menu")
        s.set_battery(4)
        s.send("game nes fceumm")
        s.wait_event("warning: battery 4%")
    finally:
        ra.close()


def test_battery_warning_in_the_launcher_sends_no_show_msg(tmp_path, services):
    ra = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    ra.bind(("127.0.0.1", 0))
    ra.settimeout(1.5)
    try:
        s = services(tmp_path, conf=PROFILES, ra_port=ra.getsockname()[1]).start()
        s.set_battery(5)
        s.send("menu")
        s.wait_event("warning: battery 5%")
        with pytest.raises(socket.timeout):
            ra.recvfrom(512)
    finally:
        ra.close()


def test_critical_needs_two_readings_in_a_row_while_discharging(tmp_path, services):
    s = services(tmp_path, conf=PROFILES).start()
    s.set_battery(3)
    s.send("menu")
    s.wait_event("profile: menu -> menu")
    s.set_battery(4)  # a voltage dip under load: back above, the count restarts
    s.send("idle")
    s.wait_event("profile: idle -> idle")
    s.set_battery(3)
    s.send("menu")
    s.wait_event("profile: menu -> menu", count=2)
    s.set_battery(2, "Charging")  # charging: never shuts down
    s.send("idle")
    s.wait_event("profile: idle -> idle", count=2)
    time.sleep(0.3)
    assert not s.poweroff.exists()
    assert not any("shutdown" in e for e in s.events())
    s.set_battery(3)
    s.send("menu")
    s.wait_event("profile: menu -> menu", count=3)
    assert not s.poweroff.exists()
    s.set_battery(2)
    s.send("idle")
    s.wait_event("shutdown: battery critical")
    s.wait(lambda: s.poweroff.exists(), "poweroff")
    s.send("menu")
    s.wait_event("profile: menu -> menu", count=4)
    assert s.poweroff.read_text() == "off\n"  # only once
    assert "power OK shutdown: battery critical" in s.events()


def test_suspend_applies_the_lowest_and_resume_restores_the_exact_scenario(tmp_path, services):
    s = services(tmp_path, conf=PROFILES).start()
    s.send("game gba gpsp")
    s.wait_event("profile: game -> gba")
    before = {k: s.sysfs(k) for k in (f"{CF}/scaling_min_freq", f"{CF}/scaling_max_freq",
                                      f"{CF}/scaling_governor", "devices/system/cpu/cpu3/online",
                                      "class/devfreq/1c40000.gpu/max_freq")}
    s.clear_writes()
    s.send("suspend")
    s.wait_event("profile: game -> suspend")
    assert s.sysfs(f"{CF}/scaling_min_freq") == "120000"
    assert s.sysfs(f"{CF}/scaling_max_freq") == "120000"
    for n in (1, 2, 3):
        assert s.sysfs(f"devices/system/cpu/cpu{n}/online") == "0"
    assert s.sysfs("class/devfreq/1c40000.gpu/max_freq") == "144000000"
    assert not any("cpu0/online" in w for w in s.writes())
    assert "scenario suspend" in s.state() and "current suspend" in s.state()
    # scenario messages wait for the resume; a second suspend is a no-op
    s.send("menu")
    s.send("suspend")
    s.send("bogus message")
    s.send("resume")
    s.wait_event("profile: suspend -> gba")
    assert {k: s.sysfs(k) for k in before} == before
    assert "scenario game" in s.state() and "current gba" in s.state()
    assert not any("-> menu" in e for e in s.events())  # the queued menu was not applied
    assert sum("-> suspend" in e for e in s.events()) == 1
    # a resume without a suspend is ignored
    n = len(s.events())
    s.send("resume")
    s.send("idle")
    s.wait_event("profile: idle -> idle")
    assert len(s.events()) == n + 1


def test_critical_battery_during_the_suspend_powers_off(tmp_path, services):
    s = services(tmp_path, conf=PROFILES, tick=1).start()
    s.send("menu")
    s.wait_event("profile: menu -> menu")
    s.send("suspend")
    s.wait_event("profile: menu -> suspend")
    assert not s.poweroff.exists()
    s.set_battery(2)  # the ticks keep reading the battery: two readings in a row
    s.wait(lambda: s.poweroff.exists(), "poweroff during the suspend", timeout=6)
    assert "power OK shutdown: battery critical" in s.events()


def test_battery_read_on_the_tick_without_messages(tmp_path, services):
    s = services(tmp_path, conf=PROFILES, tick=1).start()
    s.set_battery(1)
    s.wait(lambda: s.poweroff.exists(), "poweroff from two ticks", timeout=6)


def test_idle_service_does_not_spin(tmp_path, services):
    s = services(tmp_path, conf=PROFILES).start()
    s.send("menu")
    s.wait_event("profile: menu -> menu")
    time.sleep(0.3)

    def cpu_ticks():
        fields = Path(f"/proc/{s.proc.pid}/stat").read_text().rsplit(")", 1)[1].split()
        return int(fields[11]) + int(fields[12])  # utime + stime

    before = cpu_ticks()
    time.sleep(2)
    assert cpu_ticks() - before <= 2  # sleeping in read -t, not polling


def prio_setup(s: Service, step=100):
    """Fake cgroup root, /proc and renice/ionice that log "<tool> <args>" to a file."""
    cg = s.tmp / "cg"
    proc = s.tmp / "proc"
    cg.mkdir()
    proc.mkdir()
    log = s.tmp / "prio.log"
    for tool in ("renice", "ionice"):
        f = s.tmp / f"fake-{tool}"
        f.write_text(f"#!/bin/sh\necho {tool} \"$@\" >> '{log}'\n")
        f.chmod(0o755)
        s.env[f"PW_{tool.upper()}"] = str(f)
    s.env.update(PW_CGROOT=str(cg), PW_PROC=str(proc), PW_PRIO_STEP=str(step))
    return cg, proc, log


def prio_log(log: Path):
    return log.read_text().splitlines() if log.exists() else []


def make_game_cgroup(cg: Path, proc: Path, name: str, pids: dict[int, list[int]], age=0):
    d = cg / name
    d.mkdir()
    (d / "cgroup.procs").write_text("".join(f"{p}\n" for p in pids))
    for pid, tids in pids.items():
        for t in tids:
            (proc / str(pid) / "task" / str(t)).mkdir(parents=True)
    os.utime(d, (time.time() - age, time.time() - age))


def test_game_priority_reaches_every_pid_and_thread_twice_and_never_realtime(tmp_path, services):
    s = services(tmp_path, conf=PROFILES)
    cg, proc, log = prio_setup(s)
    make_game_cgroup(cg, proc, "game-1", {10: [10]}, age=50)  # old: must be left alone
    make_game_cgroup(cg, proc, "game-2", {20: [20, 21, 22], 30: [30]})
    s.start()
    s.send("game nes fceumm")
    s.wait(lambda: len(prio_log(log)) >= 10, "two applications", timeout=8)
    time.sleep(1.5)
    lines = prio_log(log)
    assert len(lines) == 16  # (4 tids) x (renice + ionice) x 2 rounds
    for tid in (20, 21, 22, 30):
        assert lines.count(f"renice -5 -p {tid}") == 2
        assert lines.count(f"ionice -c 2 -n 2 -p {tid}") == 2
    assert not any(" -p 10" in line for line in lines)
    assert not any("-c 1" in line or "-c 3" in line for line in lines)


def test_game_priority_service_still_reads_messages_while_waiting(tmp_path, services):
    s = services(tmp_path, conf=PROFILES)
    prio_setup(s, step=300)
    s.start()
    s.send("game nes fceumm")
    s.wait_event("profile: game -> game")
    s.send("menu")
    s.wait_event("profile: menu -> menu")  # answered long before the +3 s application


def test_game_priority_empty_or_missing_cgroup_does_not_fail(tmp_path, services):
    s = services(tmp_path, conf=PROFILES)
    cg, proc, log = prio_setup(s)
    (cg / "game-1").mkdir()
    (cg / "game-1/cgroup.procs").write_text("")
    s.start()
    s.send("game nes fceumm")
    time.sleep(2.6)
    assert prio_log(log) == []
    assert s.proc.poll() is None
    assert not any("FAIL" in e for e in s.events())
    shutil.rmtree(cg)
    s.send("game nes fceumm")
    time.sleep(2.6)
    assert s.proc.poll() is None


def test_game_priority_does_nothing_if_the_game_ended_first(tmp_path, services):
    s = services(tmp_path, conf=PROFILES)
    cg, proc, log = prio_setup(s)
    make_game_cgroup(cg, proc, "game-1", {20: [20]})
    s.start()
    s.send("game nes fceumm")
    s.wait_event("profile: game -> game")
    s.send("end")
    time.sleep(2.6)
    assert prio_log(log) == []


# ---- the load controller (D12, node 2.3) ----

CTL_PROFILES = PROFILES + "profile heavy governor=ondemand controller=load max=912000\nclass psx heavy\n"
CC = shutil.which("cc") or shutil.which("gcc")


def fake_controller(s: Service, mode="run"):
    """A controller that records its arguments; `run` waits for SIGTERM and prints a summary,
    `crash` dies at once with exit 1."""
    args = s.tmp / "ctl.args"
    f = s.tmp / "fake-powerctl"
    if mode == "crash":
        gov = s.sys / CF / "scaling_governor"
        body = f"echo userspace > '{gov}'\necho 'segfault here'\nexit 1\n"
    else:
        body = ("trap 'echo \"1008000=1.0s 912000=0.5s up=1 down=1 end=stop\"; exit 0' TERM\n"
                "while :; do sleep 0.05; done\n")
    f.write_text(f"#!/bin/sh\necho \"$@\" >> '{args}'\n{body}")
    f.chmod(0o755)
    s.env["PW_CTL_BIN"] = str(f)
    return args


def lines_of(p: Path):
    return p.read_text().splitlines() if p.exists() else []


def test_controller_starts_in_a_load_profile_and_is_stopped_at_the_end(tmp_path, services):
    s = services(tmp_path, conf=CTL_PROFILES)
    cg, _, _ = prio_setup(s)
    args = fake_controller(s)
    s.start()
    s.send("game nes fceumm")                       # no controller=load: never started
    s.wait_event("profile: game -> game")
    s.send("end")
    s.wait_event("profile: menu -> menu")
    assert lines_of(args) == []

    s.send("game psx pcsx_rearmed")
    s.wait_event("profile: game -> heavy")
    s.wait(lambda: lines_of(args), "controller started")
    a = lines_of(args)[0].split()
    assert a[a.index("--sys") + 1] == str(s.sys) and a[a.index("--cgroup") + 1] == str(cg)
    assert a[a.index("--max") + 1] == "912000" and a[a.index("--owner") + 1] == str(s.proc.pid)
    assert "--min" not in a                          # the floor is already in scaling_min_freq
    assert s.sysfs(f"{CF}/scaling_min_freq") == "600000"
    time.sleep(0.3)
    s.clear_writes()
    s.send("end")
    s.wait_event("profile: menu -> menu", count=2)
    ev = s.events()
    i = ev.index("power OK controller: 1008000=1.0s 912000=0.5s up=1 down=1 end=stop")
    assert i < max(j for j, e in enumerate(ev) if "profile: menu -> menu" in e)
    assert not any("without controller" in e for e in ev)
    assert f"{CF}/scaling_max_freq 816000" in s.writes()  # the menu profile, after the stop


def test_controller_crash_goes_back_to_the_profile_without_it(tmp_path, services):
    s = services(tmp_path, conf=CTL_PROFILES)
    prio_setup(s)
    fake_controller(s, mode="crash")
    s.start()
    s.send("game psx pcsx_rearmed")
    s.wait_event("profile: game -> heavy (without controller)")
    assert "power FAIL controller: exit 1: segfault here" in s.events()
    assert s.sysfs(f"{CF}/scaling_governor") == "ondemand"
    # no restart, and the next boundary works as usual
    s.send("end")
    s.wait_event("profile: menu -> menu")
    assert sum("controller: exit" in e for e in s.events()) == 1


def test_forged_controller_message_is_ignored(tmp_path, services):
    s = services(tmp_path, conf=CTL_PROFILES)
    prio_setup(s)
    fake_controller(s)
    s.start()
    s.send("game psx pcsx_rearmed")
    s.wait_event("profile: game -> heavy")
    s.send("controller 1")
    s.send("menu")                                   # the service still answers at once
    s.wait_event("profile: menu -> menu")
    assert not any("without controller" in e for e in s.events())


@pytest.fixture(scope="module")
def powerctl(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler")
    exe = tmp_path_factory.mktemp("powerctl") / "lume-powerctl"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-o", str(exe),
                        str(REPO_ROOT / "aports/lume-powerctl/powerctl.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def test_real_controller_drives_setspeed_and_logs_the_time_per_step(tmp_path, services, powerctl):
    s = services(tmp_path, conf=CTL_PROFILES)
    cg, proc, _ = prio_setup(s)
    make_game_cgroup(cg, proc, "game-1", {20: [20]})
    (proc / "20/task/20/stat").write_text("20 (retroarch) S" + " 0" * 40 + "\n")
    (s.sys / CF / "scaling_setspeed").write_text("<unsupported>\n")
    s.env["PW_CTL_BIN"] = str(powerctl)
    s.start()
    s.send("game psx pcsx_rearmed")
    s.wait(lambda: s.sysfs(f"{CF}/scaling_setspeed") == "912000", "setspeed at the profile max")
    assert s.sysfs(f"{CF}/scaling_governor") == "userspace"
    time.sleep(0.6)
    s.send("end")
    s.wait_event("profile: menu -> menu")
    ctl = [e for e in s.events() if "controller:" in e]
    assert len(ctl) == 1 and ctl[0].startswith("power OK controller: 912000=")
    assert ctl[0].endswith("up=0 down=0 end=stop")
    assert s.sysfs(f"{CF}/scaling_governor") == "ondemand"


def test_real_controller_refuses_without_userspace_and_the_profile_stays(tmp_path, services,
                                                                        powerctl):
    s = services(tmp_path, conf=CTL_PROFILES)
    prio_setup(s)
    (s.sys / CF / "scaling_available_governors").write_text("ondemand performance schedutil\n")
    s.env["PW_CTL_BIN"] = str(powerctl)
    s.start()
    s.send("game psx pcsx_rearmed")
    s.wait_event("profile: game -> heavy (without controller)")
    assert ("power FAIL controller: exit 3: lume-powerctl: refused: userspace governor not available"
            in s.events())
    assert s.sysfs(f"{CF}/scaling_governor") == "ondemand"


def test_real_controller_ends_with_the_game_and_the_service_takes_the_profile_back(
        tmp_path, services, powerctl):
    s = services(tmp_path, conf=CTL_PROFILES)
    cg, proc, _ = prio_setup(s)
    make_game_cgroup(cg, proc, "game-1", {20: [20]})
    (proc / "20/task/20/stat").write_text("20 (retroarch) S" + " 0" * 40 + "\n")
    s.env["PW_CTL_BIN"] = str(powerctl)
    s.start()
    s.send("game psx pcsx_rearmed")
    s.wait(lambda: s.sysfs(f"{CF}/scaling_governor") == "userspace", "userspace")
    (cg / "game-1/cgroup.procs").write_text("")      # the game is over before the `end`
    s.wait_event("profile: game -> heavy (without controller)")
    assert any(e.startswith("power OK controller: ") and e.endswith("end=game")
               for e in s.events())
    assert s.sysfs(f"{CF}/scaling_governor") == "ondemand"


def test_service_stopped_takes_the_controller_down(tmp_path, services, powerctl):
    s = services(tmp_path, conf=CTL_PROFILES)
    cg, proc, _ = prio_setup(s)
    make_game_cgroup(cg, proc, "game-1", {20: [20]})
    (proc / "20/task/20/stat").write_text("20 (retroarch) S" + " 0" * 40 + "\n")
    s.env["PW_CTL_BIN"] = str(powerctl)
    s.start()
    s.send("game psx pcsx_rearmed")
    s.wait(lambda: s.sysfs(f"{CF}/scaling_governor") == "userspace", "userspace")
    s.proc.kill()
    s.proc.wait(5)
    s.proc = None                                    # wait() must not stop on the dead service
    s.wait_event("end=owner")
    assert s.sysfs(f"{CF}/scaling_governor") == "userspace"  # the respawn applies its profile


# ---- bottleneck controller and per-game profiles (D17, D18, nodes 2.5 and 2.6) ----

AUTO_PROFILES = PROFILES + (
    "profile auto controller=auto gpu_min=144000000 gpu_max=384000000\n"
    "profile gpulock min=816000 gpu_min=240000000 gpu_max=240000000\n"
    "class snes auto\n"
)
KEY = "0123456789abcdef"


def test_auto_profile_starts_the_controller_with_the_gpu_range(tmp_path, services):
    s = services(tmp_path, conf=AUTO_PROFILES)
    prio_setup(s)
    args = fake_controller(s)
    s.start()
    s.send("game snes snes9x2005_plus")
    s.wait_event("profile: game -> auto")
    s.wait(lambda: lines_of(args), "controller started")
    a = lines_of(args)[0].split()
    assert a[a.index("--mode") + 1] == "auto"
    assert a[a.index("--gpu-min") + 1] == "144000000" and a[a.index("--gpu-max") + 1] == "384000000"
    assert a[a.index("--gpu") + 1] == str(s.sys / "class/devfreq/1c40000.gpu")
    assert a[a.index("--state") + 1] == str(s.run / "powerctl.state")
    s.send("end")
    s.wait_event("power OK controller:")


def test_load_profile_does_not_get_the_auto_mode(tmp_path, services):
    s = services(tmp_path, conf=CTL_PROFILES)
    prio_setup(s)
    args = fake_controller(s)
    s.start()
    s.send("game psx pcsx_rearmed")
    s.wait(lambda: lines_of(args), "controller started")
    assert "--mode" not in lines_of(args)[0].split()


def test_gpu_min_and_max_are_applied_raising_the_ceiling_first(tmp_path, services):
    s = services(tmp_path, conf=AUTO_PROFILES, card=f"game {KEY} gpulock\n")
    prio_setup(s)
    s.start()
    (s.sys / "class/devfreq/1c40000.gpu/max_freq").write_text("144000000\n")
    s.clear_writes()
    s.send(f"game nes fceumm {KEY}")
    s.wait_event("profile: game -> gpulock")
    w = [x for x in s.writes() if "devfreq" in x]
    assert w == ["class/devfreq/1c40000.gpu/max_freq 240000000",
                 "class/devfreq/1c40000.gpu/min_freq 240000000"]
    s.clear_writes()
    s.send("end")
    s.wait_event("profile: menu -> menu")
    w = [x for x in s.writes() if "devfreq" in x]
    # the menu profile (gpu_max=144000000, default floor): the floor goes down first
    assert w == ["class/devfreq/1c40000.gpu/min_freq 144000000",
                 "class/devfreq/1c40000.gpu/max_freq 144000000"]


def test_game_key_wins_over_core_and_class_and_keeps_the_floor(tmp_path, services):
    s = services(tmp_path, conf=AUTO_PROFILES + "core snes9x2005_plus gba\n",
                 card=f"profile mine gpu_min=384000000\ngame {KEY} mine\n")
    prio_setup(s)
    s.start()
    s.send(f"game snes snes9x2005_plus {KEY}")
    s.wait_event("profile: game -> mine")
    assert s.sysfs(f"{CF}/scaling_min_freq") == "600000"        # the GA36 game floor
    assert f"game card {KEY} mine" in s.state()
    s.send("end")
    s.send("game snes snes9x2005_plus ffffffffffffffff")       # another game: the core
    s.wait_event("profile: game -> gba")
    s.send("end")
    s.send("game snes snes9x2005_plus")                         # an old 3-word writer
    s.wait_event("profile: game -> gba", count=2)
    s.send("end")
    s.send("game snes snes9x2005_plus not-a-key")               # a bad key is ignored
    s.wait_event("profile: game -> gba", count=3)
    assert not any("ffff" in e or "not-a-key" in e for e in s.events())


def test_vm_without_cpufreq_or_profiles(tmp_path, services):
    s = services(tmp_path, conf=None, board="vm")
    shutil.rmtree(s.sys / "devices/system/cpu/cpu0/cpufreq")
    s.start()
    s.wait_event("no profiles file for vm: kernel default")
    s.wait_event("no cpufreq: kernel default")
    assert not any("FAIL" in e for e in s.events())
    s.send("game nes fceumm")
    s.wait_event("profile: game -> default")
    assert s.writes() == []


def test_ga36_conf_initial_values():
    sys_ids = {line.split('"')[3] for line in SYSTEMS_JSON.read_text().splitlines()
               if '"id":' in line}
    assert "gba" in sys_ids
    text = GA36_CONF.read_text()
    entries = [line.split("#")[0].split() for line in text.splitlines()]
    entries = [e for e in entries if e]
    assert ["limit", "game_min=600000"] in entries
    # battery first (user, 2026-11-18): the GBA runs on the controller from the game floor
    assert not any(e[:2] in (["profile", "gba"], ["class", "gba"]) for e in entries)
    assert ["profile", "heavy", "min=1008000", "controller=auto", "rate_limit_us=2000"] in entries
    assert ["profile", "game", "controller=auto", "rate_limit_us=2000"] in entries
    # P-60: the launcher with a slow schedutil rate limit (sugov:0 at 30% of a core with 0.37 ms)
    assert ["profile", "menu", "governor=schedutil", "rate_limit_us=100000"] in entries
    assert ["profile", "idle", "governor=schedutil", "rate_limit_us=200000"] in entries
    for sysid in ("n64", "psp", "nds"):
        assert ["class", sysid, "heavy"] in entries
    # no boot profile: the kernel default
    assert not any(e[0] == "profile" and e[1] == "boot" for e in entries)
    for khz in ("600000", "1008000"):
        assert khz in A33_FREQS.split()
    r36s = [line.split("#")[0].split() for line in R36S_CONF.read_text().splitlines()]
    assert [e for e in r36s if e] == [["battery", "warn=5", "critical=3"]]


def test_service_is_in_the_boot_runlevel_and_supervised():
    assert "add lume-power boot" in CONFIGURE_SH.read_text()
    text = INIT.read_text()
    assert text.startswith("#!/sbin/openrc-run")
    assert 'command="/usr/bin/lume-power"' in text and 'command_args="run"' in text
    assert 'supervisor="supervise-daemon"' in text
    assert os.access(SERVICE, os.X_OK) and os.access(INIT, os.X_OK)
