"""r36os-padmerge (task 6.2 of r36s-single-card): the aport, the key map against the board
DTS and the RetroArch autoconfig of "R36S Gamepad"."""

import hashlib
import re
import shutil
import struct
import subprocess

import pytest

from r36os.paths import REPO_ROOT

APORT = REPO_ROOT / "aports/r36os-padmerge"
SOURCE = (APORT / "padmerge.c").read_text()
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
         "BTN_TRIGGER_HAPPY4": 0x2C3, "BTN_TRIGGER_HAPPY5": 0x2C4}


def _keymap() -> dict[str, str]:
    table = re.search(r"static const struct keymap KEYS\[\] = \{(.*?)\n\};", SOURCE, re.S).group(1)
    return dict(re.findall(r"\{ (BTN_\w+), (BTN_\w+) \}", table))


def test_aport_is_aarch64_only_listed_for_the_r36s_and_checksummed():
    apkbuild = (APORT / "APKBUILD").read_text()
    assert re.search(r'^arch="aarch64"$', apkbuild, re.M)
    for name in ("padmerge.c", "r36os-padmerge.initd", "61-r36os-padmerge.rules"):
        digest = hashlib.sha512((APORT / name).read_bytes()).hexdigest()
        assert f"{digest}  {name}" in apkbuild, name
    assert "r36os-padmerge" in (REPO_ROOT / "board/r36s/hw-packages.txt").read_text().split()
    assert "r36os-padmerge" not in (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    # the service is enabled only where the package installed it
    configure = (REPO_ROOT / "rootfs/configure.sh").read_text()
    assert 'if [ -f "/etc/init.d/$s" ]; then add "$s" default; fi' in configure


def test_every_dts_button_is_mapped():
    keys = DTS.split("\tgpio-keys {", 1)[1].split("\n\t};", 1)[0]
    dts_codes = set(re.findall(r"linux,code = <(BTN_\w+)>", keys))
    assert len(dts_codes) == 17
    assert dts_codes == set(_keymap())


def test_merged_gamepad_has_the_ga36_buttons():
    # same codes as the GA36 driver, so both consoles share the button indices
    assert set(_keymap().values()) == {
        "BTN_A", "BTN_B", "BTN_X", "BTN_Y", "BTN_TL", "BTN_TR", "BTN_TL2", "BTN_TR2",
        "BTN_SELECT", "BTN_START", "BTN_MODE", "BTN_THUMBL", "BTN_THUMBR",
        "BTN_DPAD_UP", "BTN_DPAD_DOWN", "BTN_DPAD_LEFT", "BTN_DPAD_RIGHT"}
    # printed labels: A is the right button (BTN_EAST in the DTS), B the bottom one
    assert _keymap()["BTN_EAST"] == "BTN_A" and _keymap()["BTN_SOUTH"] == "BTN_B"
    assert re.search(r'#define GAMEPAD_NAME "R36S Gamepad"', SOURCE)


def test_autoconfig_matches_the_merged_gamepad():
    cfg = dict(re.findall(r'^(\w+) = "([^"]*)"$', AUTOCONFIG.read_text(), re.M))
    assert cfg["input_device"] == "R36S Gamepad" and AUTOCONFIG.name == "R36S Gamepad.cfg"
    order = sorted({CODES[c] for c in _keymap().values()})  # RetroArch: keys in code order
    retropad = {"a": "BTN_A", "b": "BTN_B", "x": "BTN_X", "y": "BTN_Y", "l": "BTN_TL",
                "r": "BTN_TR", "l2": "BTN_TL2", "r2": "BTN_TR2", "select": "BTN_SELECT",
                "start": "BTN_START", "l3": "BTN_THUMBL", "r3": "BTN_THUMBR",
                "up": "BTN_DPAD_UP", "down": "BTN_DPAD_DOWN", "left": "BTN_DPAD_LEFT",
                "right": "BTN_DPAD_RIGHT", "menu_toggle": "BTN_MODE"}
    for name, code in retropad.items():
        assert cfg[f"input_{name}_btn"] == str(order.index(CODES[code])), name
    # ABS_X, ABS_Y, ABS_RX, ABS_RY -> axes 0..3
    assert cfg["input_l_x_plus_axis"] == "+0" and cfg["input_r_y_minus_axis"] == "-3"
    # same button indices as the GA36
    ga36 = dict(re.findall(r'^(input_\w+_btn) = "([^"]*)"$', GA36_AUTOCONFIG.read_text(), re.M))
    r36s = {k: v for k, v in cfg.items() if re.fullmatch(r"input_\w+_btn", k)}
    assert r36s == ga36


def test_udev_rule_hides_only_the_source_devices():
    rule = (APORT / "61-r36os-padmerge.rules").read_text()
    assert 'ATTRS{name}=="gpio-keys|adc-joystick", ENV{ID_INPUT_JOYSTICK}=""' in rule
    # the volume keys are another gpio-keys node, with another input name
    assert "volume-keys {" in DTS


@pytest.fixture(scope="module")
def padmerge(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler")
    exe = tmp_path_factory.mktemp("padmerge") / "padmerge"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-o", str(exe), str(APORT / "padmerge.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return exe


def test_bad_arguments_print_usage(padmerge):
    r = subprocess.run([str(padmerge), "--bogus"], capture_output=True, text=True)
    assert r.returncode == 2 and "usage" in r.stderr


# struct input_event on a 64-bit host: struct timeval (2 x long), u16 type, u16 code, s32 value
EVENT = struct.Struct("qqHHi")
EV_SYN, EV_KEY, EV_ABS, SYN_REPORT = 0, 1, 3, 0
ABS = {"ABS_X": 0, "ABS_Y": 1, "ABS_Z": 2, "ABS_RX": 3, "ABS_RY": 4}


def _events(*items) -> bytes:
    return b"".join(EVENT.pack(0, 0, t, c, v) for t, c, v in items)


def _read_events(path) -> list[tuple[int, int, int]]:
    data = path.read_bytes()
    return [EVENT.unpack_from(data, i)[2:] for i in range(0, len(data), EVENT.size)]


def test_replay_translates_buttons_and_forwards_sticks(padmerge, tmp_path):
    """The translation of the merged gamepad, with no device and no uinput (task 6.2)."""
    keys = tmp_path / "keys"
    sticks = tmp_path / "sticks"
    out = tmp_path / "out"
    keymap = _keymap()
    # every DTS button pressed and released, then one unknown key (dropped) and a MSC event
    presses = []
    for src in sorted(keymap):
        presses += [(EV_KEY, CODES[src], 1), (EV_SYN, SYN_REPORT, 0),
                    (EV_KEY, CODES[src], 0), (EV_SYN, SYN_REPORT, 0)]
    keys.write_bytes(_events(*presses, (EV_KEY, 0x74, 1), (4, 4, 7), (EV_SYN, SYN_REPORT, 0)))
    # the four stick axes, and ABS_Z, which the merged gamepad does not have
    sticks.write_bytes(_events((EV_ABS, ABS["ABS_X"], 180), (EV_ABS, ABS["ABS_Y"], 800),
                               (EV_ABS, ABS["ABS_RX"], 500), (EV_ABS, ABS["ABS_RY"], 501),
                               (EV_ABS, ABS["ABS_Z"], 9), (EV_SYN, SYN_REPORT, 0)))
    r = subprocess.run([str(padmerge), "--replay", str(keys), str(sticks), str(out)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    got = _read_events(out)

    expected = []
    for src in sorted(keymap):
        dst = CODES[keymap[src]]
        expected += [(EV_KEY, dst, 1), (EV_SYN, SYN_REPORT, 0),
                     (EV_KEY, dst, 0), (EV_SYN, SYN_REPORT, 0)]
    expected += [(EV_SYN, SYN_REPORT, 0)]                       # the unknown key and MSC: dropped
    expected += [(EV_ABS, ABS["ABS_X"], 180), (EV_ABS, ABS["ABS_Y"], 800),
                 (EV_ABS, ABS["ABS_RX"], 500), (EV_ABS, ABS["ABS_RY"], 501),
                 (EV_SYN, SYN_REPORT, 0)]                       # ABS_Z dropped
    assert got == expected
    # the printed labels: BTN_EAST (the right button in the DTS) comes out as BTN_A and
    # BTN_SOUTH (the bottom one) as BTN_B; F5 is the menu key
    pressed = {src: got[4 * i] for i, src in enumerate(sorted(keymap))}
    assert pressed["BTN_EAST"] == (EV_KEY, CODES["BTN_A"], 1)
    assert pressed["BTN_SOUTH"] == (EV_KEY, CODES["BTN_B"], 1)
    assert pressed["BTN_TRIGGER_HAPPY5"] == (EV_KEY, CODES["BTN_MODE"], 1)


def test_replay_missing_file_is_an_error(padmerge, tmp_path):
    r = subprocess.run([str(padmerge), "--replay", str(tmp_path / "none"), str(tmp_path / "none"),
                        str(tmp_path / "out")], capture_output=True, text=True)
    assert r.returncode == 1


def test_source_and_comments_are_in_english():
    text = "".join(p.read_text() for p in APORT.iterdir())
    assert not any(ord(c) > 127 for c in text)
