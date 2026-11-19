"""lume-input (lume-launcher tasks 3.1 to 3.3; it grew out of lume-padmerge, task 6.2 of
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

from lume_tool.paths import REPO_ROOT

APORT = REPO_ROOT / "aports/lume-input"
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
    # zlib-dev: the PNG of lume-shot, built by the same aport (lume-launcher D12)
    assert re.search(r'^makedepends="linux-headers zlib-dev"', apkbuild, re.M)
    for name in ("input.c", "volume.h", "lume-input.initd", "61-lume-input.rules", "ga36.conf",
                 "r36s.conf", "vm.conf"):
        digest = hashlib.sha512((APORT / name).read_bytes()).hexdigest()
        assert f"{digest}  {name}" in apkbuild, name
    assert "lume-input" in (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    assert not (REPO_ROOT / "aports/lume-padmerge").exists()
    assert "lume-padmerge" not in (REPO_ROOT / "board/r36s/hw-packages.txt").read_text()
    line = re.search(r"^for s in seatd .*?; do", (REPO_ROOT / "rootfs/configure.sh").read_text(),
                     re.S | re.M).group(0)
    assert line.index("lume-input") < line.index("frontend")


def test_init_runs_above_the_game_priority():
    # game-governor D13: the game gets nice -5, the input daemon nice -10 (Fn+Start on a hang)
    text = (APORT / "lume-input.initd").read_text()
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


CHORDS = {"BTN_B": "app_menu", "BTN_TR": "save_state", "BTN_TL": "load_state",
          "BTN_Y": "screenshot", "BTN_X": "hud", "BTN_START": "quit"}


def _chords(board: str) -> dict[str, str]:
    return dict(re.findall(r"^chord (\w+) (\w+)$", _profile(board), re.M))


def test_both_consoles_publish_the_same_buttons_under_the_old_names():
    for board in ("r36s", "ga36"):
        assert set(_keymap(board).values()) == GAMEPAD_KEYS, board
        assert re.search(r"^fn BTN_MODE$", _profile(board), re.M)
        # lume-hud-actions D1: the chord table of the proposal, and no older "quit" line
        assert _chords(board) == CHORDS, board
        assert re.search(r"^fn_hold_ms 500$", _profile(board), re.M)
        assert not re.search(r"^quit ", _profile(board), re.M)
        assert re.findall(r"^axis (\w+)$", _profile(board), re.M) == ["ABS_X", "ABS_Y", "ABS_RX", "ABS_RY"]
    assert re.search(r"^name R36S Gamepad$", _profile("r36s"), re.M)
    assert re.search(r"^name GA36-MB Gamepad$", _profile("ga36"), re.M)
    assert all(a == b for a, b in _keymap("ga36").items())
    # the VM keyboard: F1 is Fn, and the keys that play the gamepad (lume-ui's input.rs)
    vm = _profile("vm")
    assert "passthrough" in vm and re.search(r"^fn KEY_F1$", vm, re.M)
    assert _chords("vm") == {"KEY_Z": "app_menu", "KEY_W": "save_state", "KEY_Q": "load_state",
                             "KEY_A": "screenshot", "KEY_S": "hud", "KEY_ENTER": "quit"}


def test_autoconfig_matches_the_virtual_gamepad():
    cfg = dict(re.findall(r'^(\w+) = "([^"]*)"$', AUTOCONFIG.read_text(), re.M))
    assert cfg["input_device"] == "R36S Gamepad" and AUTOCONFIG.name == "R36S Gamepad.cfg"
    order = sorted({CODES[c] for c in _keymap("r36s").values()})  # RetroArch: keys in code order
    retropad = {"a": "BTN_A", "b": "BTN_B", "x": "BTN_X", "y": "BTN_Y", "l": "BTN_TL",
                "r": "BTN_TR", "l2": "BTN_TL2", "r2": "BTN_TR2", "select": "BTN_SELECT",
                "start": "BTN_START", "l3": "BTN_THUMBL", "r3": "BTN_THUMBR",
                "up": "BTN_DPAD_UP", "down": "BTN_DPAD_DOWN", "left": "BTN_DPAD_LEFT",
                "right": "BTN_DPAD_RIGHT"}
    for name, code in retropad.items():
        assert cfg[f"input_{name}_btn"] == str(order.index(CODES[code])), name
    # the Fn (BTN_MODE) never reaches RetroArch: no menu button (lume-hud-actions D9)
    assert "input_menu_toggle_btn" not in cfg
    assert cfg["input_l_x_plus_axis"] == "+0" and cfg["input_r_y_minus_axis"] == "-3"
    ga36 = dict(re.findall(r'^(input_\w+_btn) = "([^"]*)"$', GA36_AUTOCONFIG.read_text(), re.M))
    r36s = {k: v for k, v in cfg.items() if re.fullmatch(r"input_\w+_btn", k)}
    assert r36s == ga36


def test_udev_rule_hides_only_the_source_devices():
    rule = (APORT / "61-lume-input.rules").read_text()
    assert 'ATTRS{name}=="gpio-keys|adc-joystick", ENV{ID_INPUT_JOYSTICK}=""' in rule
    # GA36: only the kernel device (BUS_HOST 0x19), not the virtual one with the same name
    assert 'ATTRS{name}=="GA36-MB Gamepad", ATTRS{id/bustype}=="0019", ENV{ID_INPUT_JOYSTICK}=""' in rule
    assert "BUS_VIRTUAL" in SOURCE and "id.bustype != BUS_VIRTUAL" in SOURCE


def _mode_rules() -> list[list[tuple[str, str, str]]]:
    """The rules of 61-lume-input.rules that set MODE, as (key, op, value) lists."""
    out = []
    for line in (APORT / "61-lume-input.rules").read_text().splitlines():
        if line.startswith("#") or "MODE=" not in line:
            continue
        out.append(re.findall(r'([A-Za-z_]+(?:\{[^}]*\})?)\s*(==|!=|=)\s*"([^"]*)"', line))
    return out


def _mode(device: dict[str, str]) -> str:
    """Evaluate the MODE rules for a fake device (name, bus: kernel bustype hex, id_bus,
    kernel); the default is the 0660 of the system."""
    mode = "0660"
    for rule in _mode_rules():
        ok = True
        for key, op, value in rule:
            if key == "MODE":
                continue
            if key == "SUBSYSTEM":
                actual = "input"
            elif key == "KERNEL":
                actual = device["kernel"]
                ok &= re.fullmatch(value.replace("[0-9]*", r"\d+"), actual) is not None
                continue
            elif key == "ATTRS{name}":
                actual = device["name"]
            elif key == "ATTRS{id/bustype}":
                actual = device["bus"]
            elif key == "ENV{ID_BUS}":
                actual = device.get("id_bus", "")
            else:
                raise AssertionError(key)
            hit = actual in value.split("|")
            ok &= hit if op == "==" else not hit
        if ok:
            mode = [v for k, _, v in rule if k == "MODE"][0]
    return mode


def test_udev_rule_makes_builtin_and_virtual_nodes_read_only_for_the_games():
    # device-fixes D16 (P-87): matched by name and bus, never by event number
    def dev(name, bus, id_bus="", kernel="event3"):
        return {"name": name, "bus": bus, "id_bus": id_bus, "kernel": kernel}

    read_only = [
        dev("gpio-keys", "0019"), dev("adc-joystick", "0019"), dev("adc-keys", "0019"),
        dev("rk805 pwrkey", "0019"), dev("axp20x-pek", "0019"), dev("1c22800.lradc", "0019"),
        dev("GA36-MB Gamepad", "0019"),                    # GA36 kernel gamepad (BUS_HOST)
        dev("GA36-MB Gamepad", "0006", kernel="event17"),   # GA36 virtual pad (BUS_VIRTUAL)
        dev("R36S Gamepad", "0006", kernel="event12"),      # R36S virtual pad
    ]
    for d in read_only:
        assert _mode(d) == "0640", d
    # USB pads keep write (rumble, LEDs), even one that reuses a built-in name
    for d in (dev("Xbox 360 Wireless Receiver", "0003", "usb"),
              dev("8BitDo Pro 2", "0003", "usb"),
              dev("GA36-MB Gamepad", "0003", "usb")):
        assert _mode(d) == "0660", d
    # other devices are left alone, and joydev/mouse nodes are not event nodes
    assert _mode(dev("AT Translated Set 2 keyboard", "0011")) == "0660"
    assert _mode(dev("gpio-keys", "0019", kernel="js0")) == "0660"
    # the rule never keys on an event number
    text = (APORT / "61-lume-input.rules").read_text()
    assert not re.search(r'KERNEL=="event\d', text)


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
    exe = tmp_path_factory.mktemp("input") / "lume-input"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-o", str(exe), str(APORT / "input.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


class Daemon:
    def __init__(self, exe, tmp, board: str, sources: list[str], profile=None, env_extra=None):
        self.dir = tmp
        self.out = tmp / "out"
        self.sock = tmp / "input.sock"
        self.amixer_log = tmp / "amixer.log"
        # a fake mixer with a state per control (ctl-<name>.raw, .lim, .sw): "sget" prints it
        # (and fails for a control without a raw file), "sset" stores the numbers and on/off it
        # gets; a percent "sset" is only logged
        self.ctl_dir = tmp / "mixer"
        self.ctl_dir.mkdir()
        amixer = tmp / "amixer"
        amixer.write_text(
            "#!/bin/sh\n"
            f'echo "$*" >> "{self.amixer_log}"\n'
            'case "$3" in\n'
            f'sget) f="{self.ctl_dir}/ctl-$4"\n'
            '  [ -f "$f.raw" ] || exit 1\n'
            '  lim=$(cat "$f.lim" 2>/dev/null || echo "0 - 192")\n'
            '  sw=$(cat "$f.sw" 2>/dev/null || echo on)\n'
            '  printf "Simple mixer control \'%s\',0\\n  Limits: Playback %s\\n'
            '  Front Left: Playback %s [50%%] [%s]\\n" "$4" "$lim" "$(cat "$f.raw")" "$sw" ;;\n'
            f'-q) f="{self.ctl_dir}/ctl-$5"; shift 5\n'
            '  for v in "$@"; do case "$v" in on|off) echo "$v" > "$f.sw" ;; *[!0-9]*) ;;'
            ' *) echo "$v" > "$f.raw" ;; esac; done ;;\n'
            "esac\n")
        amixer.chmod(0o755)
        # the levels of the outputs (task 7.2) and the active output the jack service writes
        self.levels = tmp / "audio"
        self.output = tmp / "audio-output"
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
        # the folder of lume-sleep (device-fixes D11): absent unless a test makes it
        self.sleep = tmp / "sleep"
        self.fifos = {}
        args = [str(exe), "--profile", str(profile or APORT / f"{board}.conf"), "--test", str(self.out),
                "--socket", str(self.sock)]
        for i, name in enumerate(sources):
            fifo = tmp / f"src{i}"
            os.mkfifo(fifo)
            self.fifos[name] = fifo
            args += ["--source", f"{name}={fifo}"]
        env = {**os.environ, "LUME_INPUT_AMIXER": str(amixer), "LUME_INPUT_BACKLIGHT": str(self.backlight),
               "LUME_INPUT_RA_PORT": str(self.ra.getsockname()[1]), "LUME_INPUT_LEVEL_COLORS": str(self.colors),
               "LUME_SLEEP_DIR": str(self.sleep),
               "LUME_INPUT_LEVEL_DIR": str(self.levels), "LUME_INPUT_AUDIO_OUTPUT": str(self.output),
               "LUME_INPUT_BRIGHTNESS_FILE": str(tmp / "display" / "brightness"),
               # no calibration window unless a test asks for one (D17)
               "LUME_INPUT_CAL_MS": "0", **(env_extra or {})}
        self.proc = subprocess.Popen(args, env=env,
                                     stderr=subprocess.PIPE, text=True)
        self.writers = {name: open(f, "wb", buffering=0) for name, f in self.fifos.items()}
        for _ in range(100):
            if self.sock.exists():
                break
            time.sleep(0.02)

    def ctl(self, name: str, raw: int, lim: str = "0 - 192", sw: str = "on"):
        """Sets a control of the fake mixer."""
        (self.ctl_dir / f"ctl-{name}.raw").write_text(f"{raw}\n")
        (self.ctl_dir / f"ctl-{name}.lim").write_text(f"{lim}\n")
        (self.ctl_dir / f"ctl-{name}.sw").write_text(f"{sw}\n")

    def ctl_state(self, name: str) -> tuple[int, str]:
        """The raw value and the switch of a control of the fake mixer."""
        raw = int((self.ctl_dir / f"ctl-{name}.raw").read_text())
        sw = self.ctl_dir / f"ctl-{name}.sw"
        return raw, sw.read_text().strip() if sw.exists() else "on"

    def level(self, output: str = "speaker"):
        p = self.levels / f"level-{output}"
        return p.read_text() if p.exists() else None

    def amixer_calls(self) -> list[str]:
        return self.amixer_log.read_text().splitlines() if self.amixer_log.exists() else []

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

    def phase(self, text: str):
        """lume-sleep's notice: written to a hidden name, then renamed (as the service does)."""
        tmp = self.sleep / ".phase.tmp"
        tmp.write_text(text + "\n")
        os.replace(tmp, self.sleep / "phase")
        time.sleep(0.15)

    def requests(self) -> list[str]:
        return sorted(p.name for p in self.sleep.iterdir() if p.name in ("suspend", "poweroff"))

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
    r36s.send("adc-joystick", (EV_ABS, 0, 180), (EV_ABS, 2, 9), (EV_ABS, 3, 700), SYN)
    keys = r36s.keys()
    expected = []
    for src in sorted(_keymap("r36s")):
        if src != "BTN_TRIGGER_HAPPY5":
            dst = CODES[_keymap("r36s")[src]]
            expected += [(dst, 1), (dst, 0)]
    assert keys == expected
    # ABS_Z (2) is not an axis of the gamepad
    assert [(c, v) for t, c, v in r36s.events() if t == EV_ABS] == [(0, 180), (3, 700)]


# D17: the sticks. A test source is a FIFO, so the range is the fallback 0..1023: centre 511,
# plausible rest 511 +- 204, dead zone 5% = 51.
ADC = "adc-joystick"
CAL = {"LUME_INPUT_CAL_MS": "500"}


def _abs(d: Daemon) -> list[tuple[int, int]]:
    return [(c, v) for t, c, v in d.events() if t == EV_ABS]


def test_the_dead_zone_of_the_profile_snaps_the_sticks_to_the_centre(r36s):
    r36s.send(ADC, (EV_ABS, 0, 540), (EV_ABS, 1, 460), (EV_ABS, 3, 563), (EV_ABS, 2, 700), SYN)
    # |v - 511| <= 51 is the centre; ABS_RX (3) at 563 is just outside; ABS_Z (2) is no axis
    assert _abs(r36s) == [(0, 511), (1, 511), (3, 563)]


def test_an_offset_rest_becomes_the_centre(daemon_exe, tmp_path):
    d = Daemon(daemon_exe, tmp_path, "r36s", ["gpio-keys", ADC, "volume-keys"], env_extra=CAL)
    # the first samples of a stick at rest 600 (one spike): held back, rest is the median
    d.send(ADC, (EV_ABS, 0, 600), (EV_ABS, 0, 600), (EV_ABS, 0, 900), (EV_ABS, 0, 600), SYN)
    assert _abs(d) == []
    time.sleep(0.6)
    assert _abs(d) == [(0, 511)]   # the last sample, corrected, goes out when the window ends
    d.send(ADC, (EV_ABS, 0, 800), (EV_ABS, 0, 620), SYN)
    # 800 - 600 + 511; 620 is inside the dead zone
    assert _abs(d)[1:] == [(0, 711), (0, 511)]
    err = d.stop()
    assert "ABS_X rest 600, centre 511" in err
    assert "warning" not in err


def test_a_stick_held_at_start_uses_the_centre_and_warns(daemon_exe, tmp_path):
    d = Daemon(daemon_exe, tmp_path, "r36s", ["gpio-keys", ADC, "volume-keys"], env_extra=CAL)
    d.send(ADC, (EV_ABS, 0, 980), (EV_ABS, 0, 985), (EV_ABS, 1, 515), SYN)
    time.sleep(0.6)
    # ABS_X held: rest stays the DTS centre, so the value goes out as it is
    assert _abs(d) == [(0, 985), (1, 511)]
    d.send(ADC, (EV_ABS, 0, 700), SYN)
    assert _abs(d)[2:] == [(0, 700)]
    err = d.stop()
    assert "warning: ABS_X rest 985 is outside 307..715 (stick held at start?), using the centre 511" in err
    assert "ABS_Y rest 515, centre 511" in err


def test_the_calibration_survives_a_suspend_and_resume(daemon_exe, tmp_path):
    d = Daemon(daemon_exe, tmp_path, "ga36", GA36_SOURCES, env_extra=CAL)
    d.sleep.mkdir()
    pad = "GA36-MB Gamepad"
    d.send(pad, (EV_ABS, 0, 560), SYN)
    time.sleep(0.6)
    assert _abs(d) == [(0, 511)]
    d.phase("suspend 9")
    d.phase("resume 9")
    d.send(pad, (EV_ABS, 0, 700), SYN)
    assert _abs(d)[-1] == (0, 651)
    d.stop()


def test_a_bad_deadzone_line_is_refused(daemon_exe, tmp_path):
    prof = tmp_path / "p.conf"
    prof.write_text("name Pad\nsource Pad\npassthrough\ndeadzone 90\n")
    r = subprocess.run([str(daemon_exe), "--profile", str(prof), "--test", str(tmp_path / "o")],
                       capture_output=True, text=True)
    assert r.returncode == 1 and "bad line" in r.stderr


FN =CODES["BTN_TRIGGER_HAPPY5"]   # the R36S Fn (BTN_MODE out)
HOLD_MSG = (b"fn_hold B=app_menu R1=save_state L1=load_state Y=screenshot X=hud Start=quit "
            b"Vol=brightness")


def _recv_all(c: socket.socket, wait: float = 0.3) -> list[bytes]:
    """Every message the client has, until `wait` seconds of silence."""
    got = []
    c.settimeout(wait)
    try:
        while True:
            got.append(c.recv(512))
    except (TimeoutError, socket.timeout):
        pass
    c.settimeout(1)
    return got


def test_fn_tap_is_a_gesture_and_never_goes_out(r36s):
    c = r36s.client()
    r36s.press("gpio-keys", FN)
    r36s.release("gpio-keys", FN)
    assert _recv_all(c) == [b"fn_tap"]
    assert r36s.keys() == []
    c.close()


def test_fn_held_sends_the_chord_table_then_the_release(r36s):
    c = r36s.client()
    r36s.press("gpio-keys", FN)
    time.sleep(0.6)
    r36s.release("gpio-keys", FN)
    assert _recv_all(c) == [HOLD_MSG, b"fn_release"]
    assert r36s.keys() == []
    c.close()


def test_fn_held_then_a_chord_takes_the_hint_away_first(r36s):
    c = r36s.client()
    r1 = CODES["BTN_TR"]
    r36s.press("gpio-keys", FN)
    time.sleep(0.6)
    r36s.press("gpio-keys", r1)
    r36s.release("gpio-keys", r1)
    r36s.release("gpio-keys", FN)
    assert _recv_all(c) == [HOLD_MSG, b"fn_release", b"save_state"]
    assert r36s.keys() == []
    c.close()


@pytest.mark.parametrize("button,action", [("BTN_TR", b"save_state"), ("BTN_TL", b"load_state"),
                                           ("BTN_SOUTH", b"app_menu"), ("BTN_WEST", b"screenshot"),
                                           ("BTN_NORTH", b"hud"), ("BTN_TRIGGER_HAPPY2", b"quit")])
def test_a_quick_chord_sends_only_its_action(r36s, button, action):
    # R36S sources: BTN_SOUTH is B, BTN_WEST is Y, BTN_NORTH is X, HAPPY2 is Start
    c = r36s.client()
    code = CODES[button]
    r36s.press("gpio-keys", FN)
    r36s.press("gpio-keys", code)
    r36s.send("gpio-keys", (EV_KEY, code, 2), SYN)   # autorepeat: swallowed too
    r36s.release("gpio-keys", code)
    r36s.release("gpio-keys", FN)
    assert _recv_all(c) == [action]   # no fn_tap after a chord
    assert r36s.keys() == []
    c.close()


def test_a_chord_out_of_the_table_is_reserved(r36s):
    c = r36s.client()
    for button in ("BTN_EAST", "BTN_TRIGGER_HAPPY1"):   # Fn+A, Fn+Select
        r36s.press("gpio-keys", FN)
        r36s.press("gpio-keys", CODES[button])
        r36s.release("gpio-keys", CODES[button])
        r36s.release("gpio-keys", FN)
    assert _recv_all(c) == []
    assert r36s.keys() == []
    # the keys work again after the Fn is let go
    r36s.press("gpio-keys", CODES["BTN_EAST"])
    r36s.release("gpio-keys", CODES["BTN_EAST"])
    assert r36s.keys() == [(CODES["BTN_A"], 1), (CODES["BTN_A"], 0)]
    c.close()


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


def test_tap_from_a_client_presses_and_releases_a_key(r36s):
    c = r36s.client()
    c.send(b"tap KEY_F2")
    time.sleep(0.2)
    assert r36s.keys() == [(60, 1), (60, 0)]   # KEY_F2
    # only keyboard keys of the table: a button, an unknown name or a number are refused
    # KEY_UP..KEY_DOWN would shift RetroArch's button indices: never declared, never tapped
    for bad in (b"tap BTN_A", b"tap KEY_NOPE", b"tap 60", b"tap KEY_VOLUMEUP", b"tap KEY_UP"):
        c.send(bad)
    time.sleep(0.2)
    assert r36s.keys() == [(60, 1), (60, 0)]
    c.close()
    assert "tap refused" in r36s.stop()


def test_capture_turns_the_buttons_into_nav_and_releases_held_keys(r36s):
    c = r36s.client()
    a, up, b = CODES["BTN_EAST"], CODES["BTN_DPAD_UP"], CODES["BTN_SOUTH"]
    r36s.press("gpio-keys", CODES["BTN_DPAD_RIGHT"])   # held in the game
    c.send(b"capture on")
    time.sleep(0.15)
    # the held key is released at once: nothing stays stuck in the game
    assert r36s.keys() == [(CODES["BTN_DPAD_RIGHT"], 1), (CODES["BTN_DPAD_RIGHT"], 0)]
    for code in (up, a, b):
        r36s.press("gpio-keys", code)
        r36s.release("gpio-keys", code)
    r36s.send("adc-joystick", (EV_ABS, 0, 180), SYN)   # the sticks do not reach the game
    assert _recv_all(c) == [b"nav up", b"nav a", b"nav b"]
    # the Fn chords keep working: Fn+Start quits, a tap is still a tap
    r36s.press("gpio-keys", FN)
    r36s.press("gpio-keys", CODES["BTN_TRIGGER_HAPPY2"])
    r36s.release("gpio-keys", CODES["BTN_TRIGGER_HAPPY2"])
    r36s.release("gpio-keys", FN)
    r36s.press("gpio-keys", FN)
    r36s.release("gpio-keys", FN)
    assert _recv_all(c) == [b"quit", b"fn_tap"]
    assert r36s.keys() == [(CODES["BTN_DPAD_RIGHT"], 1), (CODES["BTN_DPAD_RIGHT"], 0)]
    assert [(t, cc) for t, cc, v in r36s.events() if t == EV_ABS] == []
    # capture off: forwarding again
    c.send(b"capture off")
    time.sleep(0.1)
    r36s.press("gpio-keys", a)
    assert r36s.keys()[-1] == (CODES["BTN_A"], 1)
    c.close()


def test_capture_ends_when_its_client_goes_away(r36s):
    c = r36s.client()
    c.send(b"capture on")
    time.sleep(0.1)
    c.close()
    time.sleep(0.15)
    r36s.press("gpio-keys", CODES["BTN_EAST"])
    assert r36s.keys() == [(CODES["BTN_A"], 1)]


def test_capture_ends_after_two_seconds_without_a_message(r36s):
    c = r36s.client()
    c.send(b"capture on")
    time.sleep(1.2)
    c.send(b"capture on")   # the renewal of every second keeps it
    time.sleep(1.2)
    r36s.press("gpio-keys", CODES["BTN_EAST"])
    r36s.release("gpio-keys", CODES["BTN_EAST"])
    assert r36s.keys() == []
    assert _recv_all(c) == [b"nav a"]
    time.sleep(2.2)
    r36s.press("gpio-keys", CODES["BTN_EAST"])
    assert r36s.keys() == [(CODES["BTN_A"], 1)]
    c.close()
    assert "capture off (no message in 2 s)" in r36s.stop()


def test_older_quit_line_is_read_as_a_chord(daemon_exe, tmp_path):
    old = tmp_path / "old.conf"
    old.write_text((APORT / "r36s.conf").read_text().split("# the Fn chords")[0]
                   + "quit BTN_START\nmixer rk817int Master 5\n")
    exe_dir = tmp_path / "d"
    exe_dir.mkdir()
    d = Daemon(daemon_exe, exe_dir, "r36s", ["gpio-keys", "adc-joystick", "volume-keys"], profile=old)
    try:
        c = d.client()
        d.press("gpio-keys", FN)
        d.press("gpio-keys", CODES["BTN_TRIGGER_HAPPY2"])
        assert c.recv(16) == b"quit"
        d.release("gpio-keys", CODES["BTN_TRIGGER_HAPPY2"])
        d.release("gpio-keys", FN)
        d.press("gpio-keys", FN)
        time.sleep(0.6)
        d.release("gpio-keys", FN)
        assert _recv_all(c) == [b"fn_hold Start=quit Vol=brightness", b"fn_release"]
    finally:
        d.stop()


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
    # device-fixes 7.2: 5% of the user scale on the Master (volume.h, 3.4); no level file and
    # a Master that cannot be read: 70%, so 75% (-8 dB, raw 234), then back to 70% (raw 228)
    # from the saved file
    assert r36s.amixer_calls() == [
        "-c rk817int sget Master", "-c rk817int -q sset Master 234",
        "-c rk817int -q sset Master 228"]
    assert r36s.level() == "70\n"
    assert r36s.keys() == []
    c.close()


def test_r36s_each_output_has_its_own_level(r36s):
    # the jack service writes the active output; the keys move that output's level only
    r36s.levels.mkdir()
    (r36s.levels / "level-speaker").write_text("70\n")
    (r36s.levels / "level-headphones").write_text("30\n")
    r36s.output.write_text("headphones\n")
    c = r36s.client()
    r36s.press("volume-keys", CODES["KEY_VOLUMEUP"])
    r36s.release("volume-keys", CODES["KEY_VOLUMEUP"])
    assert c.recv(16) == b"volume"
    assert r36s.ra.recv(64) == b"LUME_LEVEL right 35 4db3ff"
    assert r36s.ctl_state("Master")[0] == 191      # 35% = -24 dB
    assert r36s.level("headphones") == "35\n" and r36s.level("speaker") == "70\n"
    r36s.output.write_text("speaker\n")
    r36s.press("volume-keys", CODES["KEY_VOLUMEDOWN"])
    r36s.release("volume-keys", CODES["KEY_VOLUMEDOWN"])
    assert c.recv(16) == b"volume"
    assert r36s.ra.recv(64) == b"LUME_LEVEL right 65 4db3ff"
    assert r36s.ctl_state("Master")[0] == 223      # 65% = -12 dB
    assert r36s.level("headphones") == "35\n" and r36s.level("speaker") == "65\n"
    # an unknown word in the output file is the speaker
    r36s.output.write_text("hdmi\n")
    r36s.press("volume-keys", CODES["KEY_VOLUMEDOWN"])
    r36s.release("volume-keys", CODES["KEY_VOLUMEDOWN"])
    assert c.recv(16) == b"volume"
    assert r36s.level("speaker") == "60\n"
    # the R36S Master has no switch: never "on"/"off" on it
    assert not any(l.endswith((" on", " off")) for l in r36s.amixer_calls())
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


def test_the_brightness_keys_save_the_level_on_the_card(r36s):
    # device-fixes 9.15: the percent of the bar, a hidden file renamed over the file
    bfile = r36s.dir / "display" / "brightness"
    assert not bfile.exists(), "nothing is saved until the user changes it"
    c = r36s.client()
    fn, up = CODES["BTN_TRIGGER_HAPPY5"], CODES["KEY_VOLUMEUP"]
    r36s.press("gpio-keys", fn)
    r36s.press("volume-keys", up)
    r36s.release("volume-keys", up)
    assert c.recv(16) == b"brightness"
    assert bfile.read_text() == "65\n"   # 166 of 255
    assert [p.name for p in bfile.parent.iterdir()] == ["brightness"], "no temporary left"
    r36s.release("gpio-keys", fn)
    c.close()


def _with_saved_brightness(daemon_exe, tmp_path, board, sources, text):
    (tmp_path / "display").mkdir()
    (tmp_path / "display" / "brightness").write_text(text)
    return Daemon(daemon_exe, tmp_path, board, sources)


def _wait_level(d, want):
    for _ in range(100):
        if int((d.backlight / "panel/brightness").read_text()) == want:
            break
        time.sleep(0.02)
    return int((d.backlight / "panel/brightness").read_text())


def test_start_applies_the_saved_brightness(daemon_exe, tmp_path):
    # the fake backlight starts at 153 of 255; 30% is 77 (rounded)
    d = _with_saved_brightness(daemon_exe, tmp_path, "r36s", ["gpio-keys", "adc-joystick", "volume-keys"], "30\n")
    try:
        assert _wait_level(d, 77) == 77
        # the 5% floor: a saved 0 is level 13 of 255
    finally:
        d.stop()
    (tmp_path / "display" / "brightness").write_text("0\n")
    (tmp_path / "again").mkdir()
    d = Daemon(daemon_exe, tmp_path / "again", "r36s", ["gpio-keys", "adc-joystick", "volume-keys"],
               env_extra={"LUME_INPUT_BRIGHTNESS_FILE": str(tmp_path / "display" / "brightness")})
    try:
        assert _wait_level(d, 13) == 13
    finally:
        d.stop()


def test_a_saved_brightness_never_goes_above_the_ceiling(daemon_exe, tmp_path):
    # GA36 ceiling 7 is 100%: a saved 100 is level 7 (the fake starts at 153), 60% is 4
    d = _with_saved_brightness(daemon_exe, tmp_path, "ga36", ["GA36-MB Gamepad", "1c22800.lradc"], "100\n")
    try:
        assert _wait_level(d, 7) == 7
    finally:
        d.stop()
    (tmp_path / "display" / "brightness").write_text("60\n")
    (tmp_path / "again").mkdir()
    d = Daemon(daemon_exe, tmp_path / "again", "ga36", ["GA36-MB Gamepad", "1c22800.lradc"],
               env_extra={"LUME_INPUT_BRIGHTNESS_FILE": str(tmp_path / "display" / "brightness")})
    try:
        assert _wait_level(d, 4) == 4
    finally:
        d.stop()


@pytest.mark.parametrize("junk", ["loud\n", "150\n", "-3\n", "\n", "40 50\n"])
def test_a_bad_brightness_file_is_ignored_with_a_log_line(daemon_exe, tmp_path, junk):
    # the behaviour of before: the ceiling clamp of the GA36 (153 comes down to 7)
    d = _with_saved_brightness(daemon_exe, tmp_path, "ga36", ["GA36-MB Gamepad", "1c22800.lradc"], junk)
    try:
        assert _wait_level(d, 7) == 7
    finally:
        err = d.stop()
    assert "brightness: ignoring the bad file" in err


def test_without_a_brightness_file_the_start_is_as_before(daemon_exe, tmp_path):
    d = Daemon(daemon_exe, tmp_path, "r36s", ["gpio-keys", "adc-joystick", "volume-keys"])
    try:
        time.sleep(0.3)
        assert (d.backlight / "panel/brightness").read_text() == "153\n"
    finally:
        err = d.stop()
    assert "brightness: ignoring" not in err


def test_levels_ask_retroarch_for_the_line_over_a_game(r36s):
    # without a colors file: the default theme's accent (volume) and white (brightness)
    up, fn = CODES["KEY_VOLUMEUP"], CODES["BTN_TRIGGER_HAPPY5"]
    r36s.press("volume-keys", up)
    r36s.release("volume-keys", up)
    # the user percent of the scale: no file and no mixer read, 70% + 5%
    assert r36s.ra.recv(64) == b"LUME_LEVEL right 75 4db3ff"
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
        # device-fixes 7.2: the analog Headphone (0-63, 1.5 dB per step) on the user scale,
        # the DAC set again to 0 dB and on at every step. No level file and the DAC at 0 dB
        # (the boot mixer's): the level is the Headphone's position, 43 = -30 dB = 20%; then
        # 25% (44), 30% (46) and back to 25%. The volume keys never reach the virtual gamepad,
        # and each press tells the client
        d.ctl("DAC", 160)
        d.ctl("Headphone", 43, lim="0 - 63")
        for key, raw, pct in (("KEY_VOLUMEUP", 44, 25), ("KEY_VOLUMEUP", 46, 30), ("KEY_VOLUMEDOWN", 44, 25)):
            d.press("1c22800.lradc", CODES[key])
            d.release("1c22800.lradc", CODES[key])
            assert c.recv(16) == b"volume"
            assert d.ctl_state("Headphone") == (raw, "on")
            assert d.level() == f"{pct}\n"
            assert d.ra.recv(64) == f"LUME_LEVEL right {pct} 4db3ff".encode()
        assert d.amixer_calls() == [
            "-c GA36MB sget DAC", "-c GA36MB sget Headphone",
            "-c GA36MB -q sset Headphone 44 on", "-c GA36MB -q sset DAC 160 on", "-c GA36MB -q sset Speaker on",
            "-c GA36MB -q sset Headphone 46 on", "-c GA36MB -q sset DAC 160 on", "-c GA36MB -q sset Speaker on",
            "-c GA36MB -q sset Headphone 44 on", "-c GA36MB -q sset DAC 160 on", "-c GA36MB -q sset Speaker on"]
        assert d.keys() == [(CODES["BTN_A"], 1), (CODES["BTN_A"], 0)]
    finally:
        d.stop()


def _ga36(daemon_exe, tmp_path):
    return Daemon(daemon_exe, tmp_path, "ga36", ["GA36-MB Gamepad", "1c22800.lradc"])


def _vol(d, key, client):
    d.press("1c22800.lradc", CODES[key])
    d.release("1c22800.lradc", CODES[key])
    assert client.recv(16) == b"volume"


def test_ga36_old_dac_level_converts_once(daemon_exe, tmp_path):
    # the DAC still holds a level of the old volume (154 = -4.5 dB, e.g. after "lume push
    # --hot" restarted only lume-input): 85%, so Vol- is 80% (-6 dB, Headphone 59), the DAC
    # goes back to 0 dB and the file is the truth from then on (the DAC is not read again)
    d = _ga36(daemon_exe, tmp_path)
    try:
        c = d.client()
        d.ctl("DAC", 154)
        d.ctl("Headphone", 43, lim="0 - 63")
        _vol(d, "KEY_VOLUMEDOWN", c)
        assert d.ctl_state("Headphone") == (59, "on") and d.ctl_state("DAC") == (160, "on")
        assert d.level() == "80\n"
        d.ctl("DAC", 154)   # even if something put it back
        _vol(d, "KEY_VOLUMEUP", c)
        assert d.level() == "85\n" and d.ctl_state("Headphone") == (60, "on")
        assert d.amixer_calls().count("-c GA36MB sget DAC") == 1
        assert not any("sget Headphone" in l for l in d.amixer_calls())
    finally:
        d.stop()


def test_ga36_zero_is_mute_and_the_switches_come_back_on(daemon_exe, tmp_path):
    # J1 (2026-11-18): the Headphone and DAC switches were found off in a game. Any step
    # above 0% turns both on again; 0% switches only the Headphone off (mute)
    d = _ga36(daemon_exe, tmp_path)
    try:
        c = d.client()
        d.levels.mkdir()
        (d.levels / "level-speaker").write_text("10\n")
        d.ctl("DAC", 160, sw="off")
        d.ctl("Headphone", 40, lim="0 - 63", sw="off")
        _vol(d, "KEY_VOLUMEDOWN", c)
        assert d.ctl_state("Headphone") == (37, "on") and d.ctl_state("DAC") == (160, "on")
        _vol(d, "KEY_VOLUMEDOWN", c)
        assert d.ctl_state("Headphone") == (0, "off"), "0% is mute: minimum and switch off"
        assert d.ctl_state("DAC") == (160, "on")
        assert d.level() == "0\n"
        assert d.ra.recv(64) == b"LUME_LEVEL right 5 4db3ff"
        assert d.ra.recv(64) == b"LUME_LEVEL right 0 4db3ff"
        _vol(d, "KEY_VOLUMEDOWN", c)   # at the bottom it stays muted
        assert d.ctl_state("Headphone") == (0, "off") and d.level() == "0\n"
        _vol(d, "KEY_VOLUMEUP", c)
        assert d.ctl_state("Headphone") == (37, "on") and d.level() == "5\n"
    finally:
        d.stop()


def test_ga36_speaker_amplifier_is_off_at_zero_and_on_above(daemon_exe, tmp_path):
    # task 7.5: at 0% the Speaker (amplifier) switch goes off with the Headphone, at 5% both on
    d = _ga36(daemon_exe, tmp_path)
    try:
        c = d.client()
        d.levels.mkdir()
        (d.levels / "level-speaker").write_text("10\n")
        d.ctl("DAC", 160)
        d.ctl("Headphone", 40, lim="0 - 63")
        d.ctl("Speaker", 1, lim="0 - 1")
        _vol(d, "KEY_VOLUMEDOWN", c)   # 5%
        assert d.ctl_state("Headphone") == (37, "on") and d.ctl_state("Speaker")[1] == "on"
        _vol(d, "KEY_VOLUMEDOWN", c)   # 0%
        assert d.ctl_state("Headphone") == (0, "off") and d.ctl_state("Speaker")[1] == "off"
        _vol(d, "KEY_VOLUMEUP", c)     # 5% again: both on
        assert d.ctl_state("Headphone") == (37, "on") and d.ctl_state("Speaker")[1] == "on"
    finally:
        d.stop()


def test_ga36_full_scale_in_5_percent_steps(daemon_exe, tmp_path):
    # 20 presses from mute to the loudest clean position (63), on the raw of volume.h, and
    # a broken level file counts as no file
    d = _ga36(daemon_exe, tmp_path)
    try:
        c = d.client()
        d.levels.mkdir()
        (d.levels / "level-speaker").write_text("loud\n")
        d.ctl("DAC", 160)
        d.ctl("Headphone", 0, lim="0 - 63", sw="off")
        raws = []
        for _ in range(21):
            _vol(d, "KEY_VOLUMEUP", c)
            raws.append(d.ctl_state("Headphone")[0])
        assert raws[:3] == [37, 39, 41] and raws[9] == 51 and raws[-2:] == [63, 63]
        assert raws == sorted(raws) and d.level() == "100\n"
        assert not any(p.name.startswith(".level") for p in d.levels.iterdir()), "no temporary left"
    finally:
        d.stop()


def test_bad_mixer_scale_lines_are_refused(daemon_exe, tmp_path):
    for line in ("mixer_scale 63 0 63 1500", "mixer_scale 0 63 64 1500", "mixer_scale 0 63 63 0",
                 "mixer_switch on", "mixer_amp", "mixer_keep 160 on", "mixer_old DAC 0 192 160"):
        prof = tmp_path / "p.conf"
        prof.write_text(f"name Pad\nsource Pad\npassthrough\n{line}\n")
        r = subprocess.run([str(daemon_exe), "--profile", str(prof), "--test", str(tmp_path / "o")],
                           capture_output=True, text=True)
        assert r.returncode == 1 and "bad line" in r.stderr, line


def test_vm_profile_passes_the_keyboard_through(daemon_exe, tmp_path):
    kb = "AT Translated Set 2 keyboard"
    d = Daemon(daemon_exe, tmp_path, "vm", [kb])
    try:
        c = d.client()
        d.press(kb, CODES["KEY_A"])
        d.release(kb, CODES["KEY_A"])
        d.press(kb, CODES["KEY_F1"])
        d.release(kb, CODES["KEY_F1"])
        assert c.recv(16) == b"fn_tap"
        d.press(kb, CODES["KEY_F1"])
        d.press(kb, CODES["KEY_ENTER"])
        assert c.recv(16) == b"quit"
        d.release(kb, CODES["KEY_ENTER"])
        d.release(kb, CODES["KEY_F1"])
        # F1 never goes out; the hint names the gamepad buttons the keys play
        a = CODES["KEY_A"]
        assert d.keys() == [(a, 1), (a, 0)]
        d.press(kb, CODES["KEY_F1"])
        time.sleep(0.6)
        d.release(kb, CODES["KEY_F1"])
        assert _recv_all(c)[0] == HOLD_MSG
    finally:
        d.stop()


# ---- the power button and the sleep protocol (device-fixes D11, task 8.2) ----

KEY_POWER = 116
GA36_SOURCES = ["GA36-MB Gamepad", "1c22800.lradc", "axp20x-pek"]
PWR = "axp20x-pek"


def test_each_console_names_its_power_button():
    assert re.findall(r"^power (.+)$", _profile("ga36"), re.M) == ["axp20x-pek"]
    # the rk805-pwrkey driver names its input device "rk805 pwrkey"
    assert re.findall(r"^power (.+)$", _profile("r36s"), re.M) == ["rk805 pwrkey"]
    assert not re.search(r"^power ", _profile("vm"), re.M)
    # the frozen protocol: the times of lume_core::sleep
    sleep_rs = (REPO_ROOT / "lume/lume-core/src/sleep.rs").read_text()
    for name, ms in (("TAP_MAX", 1000), ("HOLD", 2000), ("CLIENT_REPLY", 2000), ("WAKE_GUARD", 1000)):
        assert re.search(rf"pub const {name}: Duration = Duration::from_secs\({ms // 1000}\);", sleep_rs), name
    for name, ms in (("POWER_TAP_MS", 1000), ("POWER_HOLD_MS", 2000), ("CLIENT_REPLY_MS", 2000),
                     ("WAKE_GUARD_MS", 1000)):
        assert re.search(rf"^#define {name} {ms}\b", SOURCE, re.M), name


@pytest.fixture
def ga36(daemon_exe, tmp_path):
    d = Daemon(daemon_exe, tmp_path, "ga36", GA36_SOURCES)
    d.sleep.mkdir()
    yield d
    d.stop()


def _tap_power(d: Daemon, source: str = PWR):
    d.press(source, KEY_POWER)
    d.release(source, KEY_POWER)


def test_a_short_power_tap_requests_the_suspension(ga36):
    c = ga36.client()
    _tap_power(ga36)
    assert ga36.requests() == ["suspend"]
    assert _recv_all(c) == [b"power_tap"]
    # nothing of the button reaches the game, not even its SYN
    assert ga36.events() == []
    c.close()


def test_power_held_two_seconds_requests_the_shutdown_once(ga36):
    c = ga36.client()
    ga36.press(PWR, KEY_POWER)
    time.sleep(2.1)
    assert ga36.requests() == ["poweroff"]
    # still held, with autorepeat: no second request nor notice
    for _ in range(3):
        ga36.send(PWR, (EV_KEY, KEY_POWER, 2), SYN)
    time.sleep(0.5)
    ga36.release(PWR, KEY_POWER)
    assert _recv_all(c) == [b"power_hold"]
    assert ga36.requests() == ["poweroff"]
    assert ga36.events() == []
    c.close()


def test_power_let_go_at_one_and_a_half_seconds_does_nothing(ga36):
    c = ga36.client()
    ga36.press(PWR, KEY_POWER)
    time.sleep(1.35)
    ga36.release(PWR, KEY_POWER)
    time.sleep(1)
    assert _recv_all(c) == []
    assert ga36.requests() == []
    c.close()


def test_a_repeated_tap_does_not_duplicate_the_request(ga36):
    c = ga36.client()
    _tap_power(ga36)
    _tap_power(ga36)   # lume-sleep has not taken the first one yet
    assert ga36.requests() == ["suspend"]
    assert _recv_all(c) == [b"power_tap"]
    # taken by lume-sleep: the next tap is a new request
    (ga36.sleep / "suspend").unlink()
    _tap_power(ga36)
    assert ga36.requests() == ["suspend"]
    assert _recv_all(c) == [b"power_tap"]
    c.close()
    assert "suspend request already pending" in ga36.stop()


def test_without_the_sleep_service_a_tap_is_one_log_line(daemon_exe, tmp_path):
    d = Daemon(daemon_exe, tmp_path, "ga36", GA36_SOURCES)
    try:
        c = d.client()
        _tap_power(d)
        assert _recv_all(c) == []
        assert not d.sleep.exists()
        c.close()
    finally:
        err = d.stop()
    assert f"no sleep service ({d.sleep} missing): power button request dropped" in err


def test_the_power_key_of_another_source_never_goes_out(r36s):
    # a profile source that also reports KEY_POWER (the VM keyboard passes everything)
    r36s.sleep.mkdir()
    c = r36s.client()
    _tap_power(r36s, "gpio-keys")
    assert _recv_all(c) == [b"power_tap"]
    assert r36s.keys() == []
    c.close()


def _clients_file(d: Daemon, seq: int, wait: float = 3.0) -> str:
    """The `clients` answer of `seq`, once it is there ("" if it never comes)."""
    for _ in range(int(wait / 0.05)):
        f = d.sleep / "clients"
        if f.exists() and f.read_text().startswith(f"suspend {seq} "):
            return f.read_text()
        time.sleep(0.05)
    return ""


def test_every_client_answering_ends_the_wait_at_once(ga36):
    a, b = ga36.client(), ga36.client()
    t0 = time.monotonic()
    ga36.phase("suspend 4")
    assert a.recv(32) == b"suspend 4" and b.recv(32) == b"suspend 4"
    a.send(b"suspend_ok 4")
    b.send(b"suspend_ok 4")
    assert _clients_file(ga36, 4) == "suspend 4 ok 2/2\n"
    assert time.monotonic() - t0 < 1.5
    assert not (ga36.sleep / ".clients.tmp").exists()
    a.close()
    b.close()


def test_a_mute_client_ends_the_wait_at_the_deadline(ga36):
    talker, mute = ga36.client(), ga36.client()
    t0 = time.monotonic()
    ga36.phase("suspend 7")
    assert talker.recv(32) == b"suspend 7" and mute.recv(32) == b"suspend 7"
    # an answer to an older sequence, then the right one twice: one counts
    talker.send(b"suspend_ok 6")
    talker.send(b"suspend_ok 7")
    talker.send(b"suspend_ok 7")
    time.sleep(0.5)
    assert not (ga36.sleep / "clients").exists(), "the mute client is still awaited"
    assert _clients_file(ga36, 7) == "suspend 7 timeout 1/2\n"
    assert 1.8 < time.monotonic() - t0 < 3
    # a late answer changes nothing
    mute.send(b"suspend_ok 7")
    time.sleep(0.2)
    assert (ga36.sleep / "clients").read_text() == "suspend 7 timeout 1/2\n"
    talker.close()
    mute.close()
    assert "suspend 7: 1 of 2 client(s) answered within 2 s" in ga36.stop()


def test_no_client_or_one_that_hangs_up_is_not_awaited(ga36):
    ga36.phase("suspend 1")
    assert _clients_file(ga36, 1, 0.5) == "suspend 1 ok 0/0\n"
    ga36.phase("resume 1")
    stays, leaves = ga36.client(), ga36.client()
    ga36.phase("suspend 2")
    assert stays.recv(32) == b"suspend 2"
    leaves.close()
    stays.send(b"suspend_ok 2")
    assert _clients_file(ga36, 2, 1.0) == "suspend 2 ok 1/1\n"
    # a client that connects after the notice is not awaited either
    ga36.phase("resume 2")
    assert stays.recv(32) == b"resume 2"
    ga36.phase("suspend 3")
    late = ga36.client()
    assert stays.recv(32) == b"suspend 3"
    stays.send(b"suspend_ok 3")
    assert _clients_file(ga36, 3, 1.0) == "suspend 3 ok 1/1\n"
    stays.close()
    late.close()


def test_nothing_is_forwarded_asleep_and_the_resume_releases_held_keys(ga36):
    c = ga36.client()
    pad, vol = "GA36-MB Gamepad", "1c22800.lradc"
    a, b = CODES["BTN_A"], CODES["BTN_B"]
    ga36.press(pad, a)   # held in the game when the console goes to sleep
    ga36.phase("suspend 5")
    assert c.recv(32) == b"suspend 5"
    c.send(b"suspend_ok 5")
    # asleep: buttons, sticks, Fn, volume, the power button and a client's tap all dropped
    ga36.press(pad, b)
    ga36.release(pad, a)
    ga36.send(pad, (EV_ABS, 0, 900), SYN)
    ga36.press(pad, CODES["BTN_MODE"])
    ga36.release(pad, CODES["BTN_MODE"])
    ga36.press(vol, CODES["KEY_VOLUMEUP"])
    ga36.release(vol, CODES["KEY_VOLUMEUP"])
    _tap_power(ga36)
    c.send(b"tap KEY_F2")
    time.sleep(0.2)
    assert _recv_all(c) == []
    assert ga36.keys() == [(a, 1)]
    assert [e for e in ga36.events() if e[0] == EV_ABS] == []
    assert ga36.requests() == []
    assert not ga36.amixer_log.exists()
    # the resume: the held key is released, then the clients hear of it
    ga36.phase("resume 5")
    assert _recv_all(c) == [b"resume 5"]
    assert ga36.keys() == [(a, 1), (a, 0)]
    # B, pressed asleep, is let go and pressed again: a whole new press
    ga36.release(pad, b)
    ga36.press(pad, b)
    assert ga36.keys() == [(a, 1), (a, 0), (b, 1)]
    c.close()
    assert "resume 5: " in ga36.stop()


def test_the_press_that_woke_the_console_does_not_suspend_it_again(ga36):
    c = ga36.client()
    ga36.phase("suspend 8")
    ga36.press(PWR, KEY_POWER)   # the waking press, read before the resume
    ga36.phase("resume 8")
    assert _recv_all(c) == [b"suspend 8", b"resume 8"]
    # its release, then a bounce within the guard: nothing
    ga36.release(PWR, KEY_POWER)
    _tap_power(ga36)
    time.sleep(0.2)
    assert ga36.requests() == [] and _recv_all(c) == []
    # past the guard a tap suspends again
    time.sleep(1.0)
    _tap_power(ga36)
    assert ga36.requests() == ["suspend"]
    assert _recv_all(c) == [b"power_tap"]
    c.close()


def test_a_release_dropped_asleep_does_not_eat_the_next_tap(ga36):
    # the waking tap was pressed and let go while asleep: no release comes after the resume,
    # and a tap after the guard still suspends
    c = ga36.client()
    ga36.phase("suspend 9")
    _tap_power(ga36)
    ga36.phase("resume 9")
    time.sleep(1.1)
    _tap_power(ga36)
    assert ga36.requests() == ["suspend"]
    assert _recv_all(c) == [b"suspend 9", b"resume 9", b"power_tap"]
    c.close()


def test_the_sleep_folder_may_appear_after_the_daemon(daemon_exe, tmp_path):
    d = Daemon(daemon_exe, tmp_path, "ga36", GA36_SOURCES)
    try:
        c = d.client()
        d.sleep.mkdir()
        time.sleep(0.2)
        d.phase("suspend 1")
        assert c.recv(32) == b"suspend 1"
        c.send(b"suspend_ok 1")
        assert _clients_file(d, 1, 1.0) == "suspend 1 ok 1/1\n"
        d.phase("resume 1")
        assert c.recv(32) == b"resume 1"
        # the same phase seen twice is acted on once; a broken one is only logged
        d.phase("resume 1")
        d.phase("suspend 0")
        d.phase("hibernate 2")
        assert _recv_all(c) == []
        c.close()
    finally:
        err = d.stop()
    assert 'bad phase "suspend 0"' in err and 'bad phase "hibernate 2"' in err


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
