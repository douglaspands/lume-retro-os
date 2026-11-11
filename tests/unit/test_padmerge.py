"""r36os-padmerge (task 6.2 of r36s-single-card): the aport, the key map against the board
DTS and the RetroArch autoconfig of "R36S Gamepad"."""

import hashlib
import re
import shutil
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


@pytest.mark.skipif(CC is None, reason="no C compiler")
def test_builds_without_warnings(tmp_path):
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-o", str(tmp_path / "padmerge"),
                        str(APORT / "padmerge.c")], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    r = subprocess.run([str(tmp_path / "padmerge"), "--bogus"], capture_output=True, text=True)
    assert r.returncode == 2 and "usage" in r.stderr


def test_source_and_comments_are_in_english():
    text = "".join(p.read_text() for p in APORT.iterdir())
    assert not any(ord(c) > 127 for c in text)
