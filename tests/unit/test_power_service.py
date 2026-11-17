"""Tests for the r36os-power service (openspec game-governor, node 2.2).

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

from r36os.paths import REPO_ROOT

POWER = REPO_ROOT / "aports/lume-power/files"
SERVICE = POWER / "usr/bin/r36os-power"
INIT = POWER / "etc/init.d/r36os-power"
CORE_LIB = REPO_ROOT / "aports/lume-core/files/usr/libexec/r36os"
GA36_CONF = POWER / "usr/share/lume/power/ga36.conf"
R36S_CONF = POWER / "usr/share/lume/power/r36s.conf"
CONFIGURE_SH = REPO_ROOT / "rootfs/configure.sh"
SYSTEMS_JSON = REPO_ROOT / "aports/lume-games/files/usr/share/r36os/systems.json"

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
        shutil.copy(POWER / "usr/libexec/r36os/power-profiles.sh", lib)
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


def test_no_class_uses_game_with_the_floor_and_menu_without_profile_is_the_kernel_default(
        tmp_path, services):
    s = services(tmp_path, conf=GA36_CONF.read_text()).start()
    s.wait_event("profile: boot -> default")
    assert s.writes() == []  # no boot profile: nothing changes
    assert "current -" in s.state()
    s.send("game nes fceumm")
    s.wait_event("profile: game -> game")
    assert s.writes() == [f"{CF}/scaling_min_freq 600000"]
    assert s.sysfs(f"{CF}/scaling_governor") == "schedutil"
    s.send("end")
    s.wait_event("profile: menu -> default")
    assert s.sysfs(f"{CF}/scaling_min_freq") == "120000"


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
    assert ["profile", "gba", "min=1008000"] in entries
    assert ["profile", "heavy", "min=1008000"] in entries
    assert ["profile", "game"] in entries
    for sysid in ("n64", "psp", "nds"):
        assert ["class", sysid, "heavy"] in entries
    assert ["class", "gba", "gba"] in entries
    # no boot, menu or idle profile: the kernel default
    assert not any(e[0] == "profile" and e[1] in ("boot", "menu", "idle") for e in entries)
    for khz in ("600000", "1008000"):
        assert khz in A33_FREQS.split()
    r36s = [line.split("#")[0].split() for line in R36S_CONF.read_text().splitlines()]
    assert [e for e in r36s if e] == [["battery", "warn=5", "critical=3"]]


def test_service_is_in_the_boot_runlevel_and_supervised():
    assert "add r36os-power boot" in CONFIGURE_SH.read_text()
    text = INIT.read_text()
    assert text.startswith("#!/sbin/openrc-run")
    assert 'command="/usr/bin/r36os-power"' in text and 'command_args="run"' in text
    assert 'supervisor="supervise-daemon"' in text
    assert os.access(SERVICE, os.X_OK) and os.access(INIT, os.X_OK)
