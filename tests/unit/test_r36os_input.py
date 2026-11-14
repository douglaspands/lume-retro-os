"""r36os-input (lume-launcher tasks 3.1 to 3.3; it grew out of r36os-padmerge, task 6.2 of
r36s-single-card): the aport, the profiles against the board DTS and the RetroArch
autoconfig, and the daemon itself run in --test mode, with FIFOs as the source devices and a
file as the virtual gamepad, for the three profiles."""

import hashlib
import os
import re
import shutil
import socket
import struct
import subprocess
import time

import pytest

from r36os.paths import REPO_ROOT

APORT = REPO_ROOT / "aports/r36os-input"
SOURCE = (APORT / "input.c").read_text()
DTS = (REPO_ROOT / "board/r36s/dts/rk3326-r36s-v5.dts").read_text()
AUTOCONFIG = REPO_ROOT / "rootfs/overlay/usr/share/libretro/autoconfig/udev/R36S Gamepad.cfg"
GA36_AUTOCONFIG = AUTOCONFIG.with_name("GA36-MB Gamepad.cfg")
CC = shutil.which("cc") or shutil.which("gcc")

# linux/input-event-codes.h
CODES = {"BTN_A": 0x130, "BTN_SOUTH": 0x130, "BTN_B": 0x131, "BTN_EAST": 0x131,
         "BTN_X": 0x133, "BTN_NORTH": 0x133, "BTN_Y": 0x134, "BTN_WEST": 0x134,
         "BTN_TL": 0x136, "BTN_TR": 0x137, "BTN_TL2": 0x138, "BTN_TR2": 0x139,
         "BTN_SELECT": 0x13A, "BTN_START": 0x13B, "BTN_MODE": 0x13C, "BTN_THUMBL": 0x13D,
         "BTN_THUMBR": 0x13E, "BTN_DPAD_UP": 0x220, "BTN_DPAD_DOWN": 0x221,
         "BTN_DPAD_LEFT": 0x222, "BTN_DPAD_RIGHT": 0x223, "BTN_TRIGGER_HAPPY1": 0x2C0,
         "BTN_TRIGGER_HAPPY2": 0x2C1, "BTN_TRIGGER_HAPPY3": 0x2C2,
         "BTN_TRIGGER_HAPPY4": 0x2C3, "BTN_TRIGGER_HAPPY5": 0x2C4,
         "KEY_F1": 59, "KEY_ENTER": 28, "KEY_A": 30, "KEY_VOLUMEUP": 115, "KEY_VOLUMEDOWN": 114}
GAMEPAD_KEYS = {"BTN_A", "BTN_B", "BTN_X", "BTN_Y", "BTN_TL", "BTN_TR", "BTN_TL2", "BTN_TR2",
                "BTN_SELECT", "BTN_START", "BTN_MODE", "BTN_THUMBL", "BTN_THUMBR",
                "BTN_DPAD_UP", "BTN_DPAD_DOWN", "BTN_DPAD_LEFT", "BTN_DPAD_RIGHT"}


def _profile(board: str) -> str:
    return (APORT / f"{board}.conf").read_text()


def _keymap(board: str) -> dict[str, str]:
    return dict(re.findall(r"^key (\w+) (\w+)$", _profile(board), re.M))


def test_aport_for_every_target_in_the_common_list_and_checksummed():
    apkbuild = (APORT / "APKBUILD").read_text()
    assert re.search(r'^arch="x86_64 armv7 aarch64"$', apkbuild, re.M)
    assert re.search(r'^makedepends="linux-headers"', apkbuild, re.M)
    for name in ("input.c", "r36os-input.initd", "61-r36os-input.rules", "ga36.conf",
                 "r36s.conf", "vm.conf"):
        digest = hashlib.sha512((APORT / name).read_bytes()).hexdigest()
        assert f"{digest}  {name}" in apkbuild, name
    assert "r36os-input" in (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    assert not (REPO_ROOT / "aports/r36os-padmerge").exists()
    assert "r36os-padmerge" not in (REPO_ROOT / "board/r36s/hw-packages.txt").read_text()
    line = re.search(r"^for s in seatd .*?; do", (REPO_ROOT / "rootfs/configure.sh").read_text(),
                     re.S | re.M).group(0)
    assert line.index("r36os-input") < line.index("frontend")


def test_every_r36s_dts_button_is_mapped():
    keys = DTS.split("\tgpio-keys {", 1)[1].split("\n\t};", 1)[0]
    dts_codes = set(re.findall(r"linux,code = <(BTN_\w+)>", keys))
    assert len(dts_codes) == 17
    assert dts_codes == set(_keymap("r36s"))
    # printed labels: A is the right button (BTN_EAST in the DTS), B the bottom one; F5 is Fn
    assert _keymap("r36s")["BTN_EAST"] == "BTN_A" and _keymap("r36s")["BTN_SOUTH"] == "BTN_B"
    assert _keymap("r36s")["BTN_TRIGGER_HAPPY5"] == "BTN_MODE"


def test_both_consoles_publish_the_same_buttons_under_the_old_names():
    for board in ("r36s", "ga36"):
        assert set(_keymap(board).values()) == GAMEPAD_KEYS, board
        assert re.search(r"^fn BTN_MODE$", _profile(board), re.M)
        assert re.search(r"^quit BTN_START$", _profile(board), re.M)
        assert re.findall(r"^axis (\w+)$", _profile(board), re.M) == ["ABS_X", "ABS_Y", "ABS_RX", "ABS_RY"]
    assert re.search(r"^name R36S Gamepad$", _profile("r36s"), re.M)
    assert re.search(r"^name GA36-MB Gamepad$", _profile("ga36"), re.M)
    assert all(a == b for a, b in _keymap("ga36").items())
    # the VM keyboard: F1 is Fn, Enter is Start
    vm = _profile("vm")
    assert "passthrough" in vm and re.search(r"^fn KEY_F1$", vm, re.M) and re.search(r"^quit KEY_ENTER$", vm, re.M)


def test_autoconfig_matches_the_virtual_gamepad():
    cfg = dict(re.findall(r'^(\w+) = "([^"]*)"$', AUTOCONFIG.read_text(), re.M))
    assert cfg["input_device"] == "R36S Gamepad" and AUTOCONFIG.name == "R36S Gamepad.cfg"
    order = sorted({CODES[c] for c in _keymap("r36s").values()})  # RetroArch: keys in code order
    retropad = {"a": "BTN_A", "b": "BTN_B", "x": "BTN_X", "y": "BTN_Y", "l": "BTN_TL",
                "r": "BTN_TR", "l2": "BTN_TL2", "r2": "BTN_TR2", "select": "BTN_SELECT",
                "start": "BTN_START", "l3": "BTN_THUMBL", "r3": "BTN_THUMBR",
                "up": "BTN_DPAD_UP", "down": "BTN_DPAD_DOWN", "left": "BTN_DPAD_LEFT",
                "right": "BTN_DPAD_RIGHT", "menu_toggle": "BTN_MODE"}
    for name, code in retropad.items():
        assert cfg[f"input_{name}_btn"] == str(order.index(CODES[code])), name
    assert cfg["input_l_x_plus_axis"] == "+0" and cfg["input_r_y_minus_axis"] == "-3"
    ga36 = dict(re.findall(r'^(input_\w+_btn) = "([^"]*)"$', GA36_AUTOCONFIG.read_text(), re.M))
    r36s = {k: v for k, v in cfg.items() if re.fullmatch(r"input_\w+_btn", k)}
    assert r36s == ga36


def test_udev_rule_hides_only_the_source_devices():
    rule = (APORT / "61-r36os-input.rules").read_text()
    assert 'ATTRS{name}=="gpio-keys|adc-joystick", ENV{ID_INPUT_JOYSTICK}=""' in rule
    # GA36: only the kernel device (BUS_HOST 0x19), not the virtual one with the same name
    assert 'ATTRS{name}=="GA36-MB Gamepad", ATTRS{id/bustype}=="0019", ENV{ID_INPUT_JOYSTICK}=""' in rule
    assert "BUS_VIRTUAL" in SOURCE and "id.bustype != BUS_VIRTUAL" in SOURCE


def test_source_and_comments_are_in_english():
    text = "".join(p.read_text() for p in APORT.iterdir() if p.is_file())
    assert not any(ord(c) > 127 for c in text)


# ---- the daemon in --test mode ----

# struct input_event on a 64-bit host: struct timeval (2 x long), u16 type, u16 code, s32 value
EVENT = struct.Struct("qqHHi")
EV_SYN, EV_KEY, EV_ABS, SYN = 0, 1, 3, (0, 0, 0)


@pytest.fixture(scope="module")
def daemon_exe(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler")
    exe = tmp_path_factory.mktemp("input") / "r36os-input"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-o", str(exe), str(APORT / "input.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


class Daemon:
    def __init__(self, exe, tmp, board: str, sources: list[str]):
        self.dir = tmp
        self.out = tmp / "out"
        self.sock = tmp / "input.sock"
        self.amixer_log = tmp / "amixer.log"
        amixer = tmp / "amixer"
        amixer.write_text(f'#!/bin/sh\necho "$*" >> "{self.amixer_log}"\n')
        amixer.chmod(0o755)
        self.fifos = {}
        args = [str(exe), "--profile", str(APORT / f"{board}.conf"), "--test", str(self.out),
                "--socket", str(self.sock)]
        for i, name in enumerate(sources):
            fifo = tmp / f"src{i}"
            os.mkfifo(fifo)
            self.fifos[name] = fifo
            args += ["--source", f"{name}={fifo}"]
        self.proc = subprocess.Popen(args, env={**os.environ, "R36OS_INPUT_AMIXER": str(amixer)},
                                     stderr=subprocess.PIPE, text=True)
        self.writers = {name: open(f, "wb", buffering=0) for name, f in self.fifos.items()}
        for _ in range(100):
            if self.sock.exists():
                break
            time.sleep(0.02)

    def send(self, source: str, *events):
        self.writers[source].write(b"".join(EVENT.pack(0, 0, *e) for e in events))
        time.sleep(0.15)

    def press(self, source: str, code: int):
        self.send(source, (EV_KEY, code, 1), SYN)

    def release(self, source: str, code: int):
        self.send(source, (EV_KEY, code, 0), SYN)

    def events(self) -> list[tuple[int, int, int]]:
        data = self.out.read_bytes()
        return [EVENT.unpack_from(data, i)[2:] for i in range(0, len(data), EVENT.size)]

    def keys(self) -> list[tuple[int, int]]:
        return [(c, v) for t, c, v in self.events() if t == EV_KEY]

    def client(self) -> socket.socket:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        s.connect(str(self.sock))
        s.settimeout(1)
        time.sleep(0.1)
        return s

    def stop(self) -> str:
        for w in self.writers.values():
            w.close()
        self.proc.terminate()
        _, err = self.proc.communicate(timeout=5)
        return err


@pytest.fixture
def r36s(daemon_exe, tmp_path):
    d = Daemon(daemon_exe, tmp_path, "r36s", ["gpio-keys", "adc-joystick", "volume-keys"])
    yield d
    d.stop()


def test_buttons_are_translated_and_sticks_forwarded(r36s):
    for src in sorted(_keymap("r36s")):
        if src == "BTN_TRIGGER_HAPPY5":
            continue  # Fn: see the chord tests
        r36s.press("gpio-keys", CODES[src])
        r36s.release("gpio-keys", CODES[src])
    r36s.send("adc-joystick", (EV_ABS, 0, 180), (EV_ABS, 2, 9), (EV_ABS, 3, 500), SYN)
    keys = r36s.keys()
    expected = []
    for src in sorted(_keymap("r36s")):
        if src != "BTN_TRIGGER_HAPPY5":
            dst = CODES[_keymap("r36s")[src]]
            expected += [(dst, 1), (dst, 0)]
    assert keys == expected
    # ABS_Z (2) is not an axis of the gamepad
    assert [(c, v) for t, c, v in r36s.events() if t == EV_ABS] == [(0, 180), (3, 500)]


def test_fn_alone_is_a_tap_on_release(r36s):
    fn = CODES["BTN_TRIGGER_HAPPY5"]
    r36s.press("gpio-keys", fn)
    assert r36s.keys() == []
    r36s.release("gpio-keys", fn)
    assert r36s.keys() == [(CODES["BTN_MODE"], 1), (CODES["BTN_MODE"], 0)]


def test_fn_start_sends_quit_and_forwards_nothing(r36s):
    c = r36s.client()
    fn, start = CODES["BTN_TRIGGER_HAPPY5"], CODES["BTN_TRIGGER_HAPPY2"]
    r36s.press("gpio-keys", fn)
    r36s.press("gpio-keys", start)
    assert c.recv(16) == b"quit"
    r36s.release("gpio-keys", start)
    r36s.release("gpio-keys", fn)
    assert r36s.keys() == []
    c.close()


def test_fn_with_another_key_forwards_both(r36s):
    fn, a = CODES["BTN_TRIGGER_HAPPY5"], CODES["BTN_EAST"]
    r36s.press("gpio-keys", fn)
    r36s.press("gpio-keys", a)
    r36s.release("gpio-keys", a)
    r36s.release("gpio-keys", fn)
    mode, ba = CODES["BTN_MODE"], CODES["BTN_A"]
    assert r36s.keys() == [(mode, 1), (ba, 1), (ba, 0), (mode, 0)]


def test_fn_start_without_a_client_does_nothing(r36s):
    fn, start = CODES["BTN_TRIGGER_HAPPY5"], CODES["BTN_TRIGGER_HAPPY2"]
    r36s.press("gpio-keys", fn)
    r36s.press("gpio-keys", start)
    r36s.release("gpio-keys", start)
    r36s.release("gpio-keys", fn)
    assert r36s.keys() == []
    assert r36s.proc.poll() is None
    # a client that went away (lume-run between two games) is dropped, not fatal
    c = r36s.client()
    c.close()
    time.sleep(0.1)
    r36s.press("gpio-keys", fn)
    r36s.press("gpio-keys", start)
    assert r36s.proc.poll() is None


def test_volume_keys_change_the_mixer_and_are_not_forwarded(r36s):
    for code in (CODES["KEY_VOLUMEUP"], CODES["KEY_VOLUMEDOWN"]):
        r36s.press("volume-keys", code)
        r36s.send("volume-keys", (EV_KEY, code, 2), SYN)   # autorepeat: no extra step
        r36s.release("volume-keys", code)
    time.sleep(0.2)
    assert r36s.amixer_log.read_text().splitlines() == [
        "-c rk817int -q sset Master 5%+", "-c rk817int -q sset Master 5%-"]
    assert r36s.keys() == []


def test_ga36_profile_keeps_the_codes(daemon_exe, tmp_path):
    d = Daemon(daemon_exe, tmp_path, "ga36", ["GA36-MB Gamepad", "1c21800.lradc"])
    try:
        c = d.client()
        d.press("GA36-MB Gamepad", CODES["BTN_A"])
        d.release("GA36-MB Gamepad", CODES["BTN_A"])
        d.press("GA36-MB Gamepad", CODES["BTN_MODE"])
        d.press("GA36-MB Gamepad", CODES["BTN_START"])
        assert c.recv(16) == b"quit"
        d.release("GA36-MB Gamepad", CODES["BTN_START"])
        d.release("GA36-MB Gamepad", CODES["BTN_MODE"])
        d.press("1c21800.lradc", CODES["KEY_VOLUMEUP"])
        assert d.keys() == [(CODES["BTN_A"], 1), (CODES["BTN_A"], 0)]
        time.sleep(0.2)
        assert d.amixer_log.read_text().strip() == "-c GA36MB -q sset DAC 3%+"
    finally:
        d.stop()


def test_vm_profile_passes_the_keyboard_through(daemon_exe, tmp_path):
    kb = "AT Translated Set 2 keyboard"
    d = Daemon(daemon_exe, tmp_path, "vm", [kb])
    try:
        c = d.client()
        d.press(kb, CODES["KEY_A"])
        d.release(kb, CODES["KEY_A"])
        d.press(kb, CODES["KEY_F1"])
        d.release(kb, CODES["KEY_F1"])
        d.press(kb, CODES["KEY_F1"])
        d.press(kb, CODES["KEY_ENTER"])
        assert c.recv(16) == b"quit"
        d.release(kb, CODES["KEY_ENTER"])
        d.release(kb, CODES["KEY_F1"])
        f1, a = CODES["KEY_F1"], CODES["KEY_A"]
        assert d.keys() == [(a, 1), (a, 0), (f1, 1), (f1, 0)]
    finally:
        d.stop()


def test_missing_required_source_and_bad_profile(daemon_exe, tmp_path):
    r = subprocess.run([str(daemon_exe), "--profile", str(APORT / "r36s.conf"), "--test",
                        str(tmp_path / "out"), "--socket", str(tmp_path / "s")],
                       capture_output=True, text=True, timeout=10)
    assert r.returncode == 1 and 'no input device named "gpio-keys"' in r.stderr
    bad = tmp_path / "bad.conf"
    bad.write_text("name X\nsource y\nkey BTN_A NOT_A_CODE\n")
    r = subprocess.run([str(daemon_exe), "--profile", str(bad)], capture_output=True, text=True)
    assert r.returncode == 1 and "bad.conf:3: bad line" in r.stderr
    r = subprocess.run([str(daemon_exe), "--bogus"], capture_output=True, text=True)
    assert r.returncode == 2 and "usage" in r.stderr
