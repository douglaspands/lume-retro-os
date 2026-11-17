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
AUTOCONFIG = REPO_ROOT / "aports/lume-retroarch-cfg/files/usr/share/libretro/autoconfig/udev/R36S Gamepad.cfg"
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
    # zlib-dev: the PNG of r36os-shot, built by the same aport (lume-launcher D12)
    assert re.search(r'^makedepends="linux-headers zlib-dev"', apkbuild, re.M)
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


def test_init_runs_above_the_game_priority():
    # game-governor D13: the game gets nice -5, the input daemon nice -10 (Fn+Start on a hang)
    text = (APORT / "r36os-input.initd").read_text()
    assert re.search(r"^nice=-10$", text, re.M)
    assert not re.search(r"^(nice|ionice|ionice_class)=.*(rt|realtime|-20)", text, re.M)


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
        # a fake mixer with one raw value (0-192, as the GA36 DAC): "sget" prints it, a
        # numeric "sset" stores it, a percent "sset" is only logged
        self.mixer_raw = tmp / "mixer.raw"
        amixer = tmp / "amixer"
        amixer.write_text(
            "#!/bin/sh\n"
            f'echo "$*" >> "{self.amixer_log}"\n'
            'case "$3" in\n'
            f'sget) printf "Simple mixer control \'%s\',0\\n  Limits: Playback 0 - 192\\n'
            f'  Front Left: Playback %s [83%%] [0.00dB] [on]\\n" "$4" "$(cat "{self.mixer_raw}")" ;;\n'
            f'-q) case "$6" in *[!0-9]*) ;; *) echo "$6" > "{self.mixer_raw}" ;; esac ;;\n'
            "esac\n")
        amixer.chmod(0o755)
        self.mixer_raw.write_text("154\n")
        # a fake backlight (max 255 at 60%)
        self.backlight = tmp / "backlight"
        (self.backlight / "panel").mkdir(parents=True)
        (self.backlight / "panel/max_brightness").write_text("255\n")
        (self.backlight / "panel/brightness").write_text("153\n")
        # RetroArch's command port (LUME_LEVEL) and the theme colors lume-ui writes
        self.ra = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.ra.bind(("127.0.0.1", 0))
        self.ra.settimeout(1)
        self.colors = tmp / "level-colors"
        self.fifos = {}
        args = [str(exe), "--profile", str(APORT / f"{board}.conf"), "--test", str(self.out),
                "--socket", str(self.sock)]
        for i, name in enumerate(sources):
            fifo = tmp / f"src{i}"
            os.mkfifo(fifo)
            self.fifos[name] = fifo
            args += ["--source", f"{name}={fifo}"]
        env = {**os.environ, "R36OS_INPUT_AMIXER": str(amixer), "R36OS_INPUT_BACKLIGHT": str(self.backlight),
               "R36OS_INPUT_RA_PORT": str(self.ra.getsockname()[1]), "R36OS_INPUT_LEVEL_COLORS": str(self.colors)}
        self.proc = subprocess.Popen(args, env=env,
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
        self.ra.close()
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
    c = r36s.client()
    for code in (CODES["KEY_VOLUMEUP"], CODES["KEY_VOLUMEDOWN"]):
        r36s.press("volume-keys", code)
        r36s.send("volume-keys", (EV_KEY, code, 2), SYN)   # autorepeat: no extra step
        r36s.release("volume-keys", code)
        # the launcher hears of each step, after the mixer changed
        assert c.recv(16) == b"volume"
    time.sleep(0.2)
    # each step, then a read of the level for the line over a game (LUME_LEVEL)
    assert r36s.amixer_log.read_text().splitlines() == [
        "-c rk817int -q sset Master 5%+", "-c rk817int sget Master",
        "-c rk817int -q sset Master 5%-", "-c rk817int sget Master"]
    assert r36s.keys() == []
    c.close()


def test_fn_volume_keys_change_the_backlight(r36s):
    c = r36s.client()
    fn, up, down = CODES["BTN_TRIGGER_HAPPY5"], CODES["KEY_VOLUMEUP"], CODES["KEY_VOLUMEDOWN"]
    level = lambda: int((r36s.backlight / "panel/brightness").read_text())
    r36s.press("gpio-keys", fn)
    r36s.press("volume-keys", up)
    r36s.send("volume-keys", (EV_KEY, up, 2), SYN)   # autorepeat: no extra step
    r36s.release("volume-keys", up)
    assert c.recv(16) == b"brightness"
    assert level() == 166   # 60% + 5% of 255
    for _ in range(14):   # down to the floor of 5%, and it stays there
        r36s.press("volume-keys", down)
        r36s.release("volume-keys", down)
        assert c.recv(16) == b"brightness"
    assert level() == 13
    r36s.release("gpio-keys", fn)
    # the mixer was not touched and Fn gave no tap (it was used)
    assert not r36s.amixer_log.exists()
    assert r36s.keys() == []
    # without Fn, the volume again
    r36s.press("volume-keys", up)
    assert c.recv(16) == b"volume"
    c.close()


def test_fn_volume_on_a_coarse_backlight_moves_one_level(r36s):
    # the GA36 backlight has 11 levels (0-10): 5% can round back to the same level, so the
    # step is then one level, down to the floor (1) and up to 10
    (r36s.backlight / "panel/max_brightness").write_text("10\n")
    (r36s.backlight / "panel/brightness").write_text("10\n")
    c = r36s.client()
    fn, up, down = CODES["BTN_TRIGGER_HAPPY5"], CODES["KEY_VOLUMEUP"], CODES["KEY_VOLUMEDOWN"]
    level = lambda: int((r36s.backlight / "panel/brightness").read_text())
    r36s.press("gpio-keys", fn)
    seen = []
    for _ in range(11):
        r36s.press("volume-keys", down)
        r36s.release("volume-keys", down)
        assert c.recv(16) == b"brightness"
        seen.append(level())
    assert seen == [9, 8, 7, 6, 5, 4, 3, 2, 1, 1, 1]
    r36s.press("volume-keys", up)
    r36s.release("volume-keys", up)
    assert c.recv(16) == b"brightness" and level() == 2
    r36s.release("gpio-keys", fn)
    c.close()


def test_levels_ask_retroarch_for_the_line_over_a_game(r36s):
    # without a colors file: the default theme's accent (volume) and white (brightness)
    up, fn = CODES["KEY_VOLUMEUP"], CODES["BTN_TRIGGER_HAPPY5"]
    r36s.press("volume-keys", up)
    r36s.release("volume-keys", up)
    # the fake mixer reads 154 of 0-192 after the step: 80%
    assert r36s.ra.recv(64) == b"LUME_LEVEL right 80 4db3ff"
    r36s.press("gpio-keys", fn)
    r36s.press("volume-keys", up)
    r36s.release("volume-keys", up)
    r36s.release("gpio-keys", fn)
    assert r36s.ra.recv(64) == b"LUME_LEVEL left 65 ffffff"   # 153 of 255 + 5%
    # the colors lume-ui wrote for the chosen theme
    r36s.colors.write_text("volume=D0BCFF\nbrightness=eeeeee\n")
    r36s.press("volume-keys", up)
    r36s.release("volume-keys", up)
    assert r36s.ra.recv(64) == b"LUME_LEVEL right 80 D0BCFF"


def test_ga36_backlight_ceiling_is_100_percent(daemon_exe, tmp_path):
    # GA36: above level 7 of 10 the panel flickers (2026-11-15); the profile's backlight_max
    # makes level 7 the 100%, a higher level comes down when the daemon starts and on the
    # next step
    d = Daemon(daemon_exe, tmp_path, "ga36", ["GA36-MB Gamepad", "1c22800.lradc"])
    try:
        level = lambda: int((d.backlight / "panel/brightness").read_text())
        # the fake backlight started at 153 (of 255): brought down to the ceiling at start; the
        # daemon may apply it just after its socket appears (failed once with a build loading
        # the CPU, 2026-11-15), so wait for it
        for _ in range(100):
            if level() == 7:
                break
            time.sleep(0.02)
        assert level() == 7
        (d.backlight / "panel/max_brightness").write_text("10\n")
        (d.backlight / "panel/brightness").write_text("10\n")
        fn, up, down = CODES["BTN_MODE"], CODES["KEY_VOLUMEUP"], CODES["KEY_VOLUMEDOWN"]
        d.press("GA36-MB Gamepad", fn)
        d.press("1c22800.lradc", up)
        d.release("1c22800.lradc", up)
        assert level() == 7, "above the ceiling: back to it"
        assert d.ra.recv(64) == b"LUME_LEVEL left 100 ffffff", "the ceiling is 100%"
        for _ in range(3):
            d.press("1c22800.lradc", up)
            d.release("1c22800.lradc", up)
            assert level() == 7
        d.press("1c22800.lradc", down)
        d.release("1c22800.lradc", down)
        assert level() == 6
        d.release("GA36-MB Gamepad", fn)
    finally:
        d.stop()


def test_ga36_profile_keeps_the_codes(daemon_exe, tmp_path):
    # the LRADC of the A33 is at 0x01c22800 (the name /proc/bus/input/devices shows on the
    # GA36); with 1c21800 the volume buttons were never grabbed (2026-11-14)
    d = Daemon(daemon_exe, tmp_path, "ga36", ["GA36-MB Gamepad", "1c22800.lradc"])
    try:
        c = d.client()
        d.press("GA36-MB Gamepad", CODES["BTN_A"])
        d.release("GA36-MB Gamepad", CODES["BTN_A"])
        d.press("GA36-MB Gamepad", CODES["BTN_MODE"])
        d.press("GA36-MB Gamepad", CODES["BTN_START"])
        assert c.recv(16) == b"quit"
        d.release("GA36-MB Gamepad", CODES["BTN_START"])
        d.release("GA36-MB Gamepad", CODES["BTN_MODE"])
        assert d.keys() == [(CODES["BTN_A"], 1), (CODES["BTN_A"], 0)]
        # ceiling 160 (0 dB): 154 + 3% of 192 = 160, then Vol+ at the ceiling sets nothing,
        # and Vol- goes back to 154; the volume keys never reach the virtual gamepad. Each
        # press tells the client, the one at the ceiling too (the launcher shows the bar)
        for key, raw in (("KEY_VOLUMEUP", "160"), ("KEY_VOLUMEUP", "160"), ("KEY_VOLUMEDOWN", "154")):
            d.press("1c22800.lradc", CODES[key])
            d.release("1c22800.lradc", CODES[key])
            assert c.recv(16) == b"volume"
            assert d.mixer_raw.read_text().strip() == raw
        assert d.amixer_log.read_text().splitlines() == [
            "-c GA36MB sget DAC", "-c GA36MB -q sset DAC 160",
            "-c GA36MB sget DAC",
            "-c GA36MB sget DAC", "-c GA36MB -q sset DAC 154"]
        assert d.keys() == [(CODES["BTN_A"], 1), (CODES["BTN_A"], 0)]
    finally:
        d.stop()


def test_volume_ceiling_brings_a_louder_mixer_back(daemon_exe, tmp_path):
    # a level left above the ceiling (by an older build or by hand) comes back to it on Vol+
    d = Daemon(daemon_exe, tmp_path, "ga36", ["GA36-MB Gamepad", "1c22800.lradc"])
    try:
        d.mixer_raw.write_text("166\n")
        d.press("1c22800.lradc", CODES["KEY_VOLUMEUP"])
        d.release("1c22800.lradc", CODES["KEY_VOLUMEUP"])
        time.sleep(0.3)
        assert d.mixer_raw.read_text().strip() == "160"
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
