"""GA36 drivers in kernel/patches/ (tasks 9.1 and 9.2): checks without building the kernel.

- JD9366 panel (0005): the panel 1 sequence is the lcd.ko table of appendix C of the
  design, the mode is the FEX timing (appendix B) and the compatibles are those of the
  binding (0003) and the DTS;
- gamepad (0006): the compatible is the binding's (0004) and every DTS button exists in the
  driver.
"""

import re

from r36os import kpatch
from r36os.paths import REPO_ROOT

DESIGN = (REPO_ROOT / "openspec/changes/archive/2026-11-11-alpine-retroarch-distro/design.md").read_text()
PANEL = kpatch.new_file(kpatch.find("0005-"), "drivers/gpu/drm/panel/panel-ga36mb-jd9366.c")
GAMEPAD_PATCH = kpatch.find("0006-")
GAMEPAD = kpatch.new_file(GAMEPAD_PATCH, "drivers/input/joystick/ga36mb-gamepad.c")
DTS_DIR = REPO_ROOT / "board/ga36/dts"
DCS = {"MIPI_DCS_EXIT_SLEEP_MODE": 0x11, "MIPI_DCS_SET_DISPLAY_ON": 0x29}


def _steps(array: str) -> list[tuple]:
    """Steps of a driver table: ("cmd", reg, value|None) or ("delay", ms)."""
    body = re.search(rf"static const struct jd9366_step {array}\[\] = \{{(.*?)\n\}};", PANEL, re.S).group(1)
    out: list[tuple] = []
    for macro, args in re.findall(r"JD9366_(PAGE|CMD0|CMD|DELAY)\(([^)]*)\)", body):
        a = [x.strip() for x in args.split(",")]
        if macro == "PAGE":
            out += [("cmd", 0xFF, 0x30), ("cmd", 0xFF, 0x52), ("cmd", 0xFF, int(a[0], 16))]
        elif macro == "CMD":
            out.append(("cmd", int(a[0], 16), int(a[1], 16)))
        elif macro == "CMD0":
            out.append(("cmd", DCS.get(a[0]) or int(a[0], 16), None))
        else:
            out.append(("delay", int(a[0])))
    return out


def _appendix_c_panel1() -> list[tuple]:
    """GA36 panel 1 sequence from appendix C (the design is written in Portuguese)."""
    block = DESIGN.split("**GA36 painel 1**", 1)[1].split("```", 2)[1]
    out: list[tuple] = []
    for page, rest in re.findall(r"página ([0-9A-F]{2}):(.*?)(?=página |\Z)", block, re.S):
        out += [("cmd", 0xFF, 0x30), ("cmd", 0xFF, 0x52), ("cmd", 0xFF, int(page, 16))]
        out += [("cmd", int(r, 16), int(v, 16)) for r, v in re.findall(r"\b([0-9A-F]{2})=([0-9A-F]{2})\b", rest)]
        tail = re.search(r"depois 11 \(sleep out\) \+ (\d+) ms, depois 29 \(display on\) \+ (\d+) ms", rest)
        if tail:
            out += [("cmd", 0x11, None), ("delay", int(tail.group(1))),
                    ("cmd", 0x29, None), ("delay", int(tail.group(2)))]
    return out


def test_panel1_is_appendix_c():
    expected = _appendix_c_panel1()
    assert len(expected) == 150  # the 150 steps of the lcd.ko table
    assert _steps("jd9366_panel1") == expected


def test_panel2_is_goodluckos_sequence():
    steps = _steps("jd9366_panel2")
    # the goodluckOS sequence starts with E0 00 and differs from panel 1 in the gamma
    assert steps[0] == ("cmd", 0xE0, 0x00)
    assert steps != _steps("jd9366_panel1")
    assert steps[-4:] == [("cmd", 0x11, None), ("delay", 120), ("cmd", 0x29, None), ("delay", 20)]


def test_mode_is_fex_timing():
    body = re.search(r"jd9366_mode = \{(.*?)\};", PANEL, re.S).group(1)
    m = {k: eval(v, {"__builtins__": {}})  # noqa: S307 (numbers and + only)
         for k, v in re.findall(r"\.(\w+) = ([0-9 +]+),", body)}
    # Appendix B: 30 MHz, htotal 1040, hbp 120 (sync included), hsync 40, vtotal 518, vbp 12, vsync 6
    assert m["clock"] == 30000 and m["hdisplay"] == 640 and m["vdisplay"] == 480
    assert m["htotal"] == 1040 and m["htotal"] - m["hsync_start"] == 120
    assert m["hsync_end"] - m["hsync_start"] == 40
    assert m["vtotal"] == 518 and m["vtotal"] - m["vsync_start"] == 12
    assert m["vsync_end"] - m["vsync_start"] == 6
    assert (m["width_mm"], m["height_mm"]) == (71, 53)


def test_panel_compatibles_match_binding_and_dts():
    driver = set(re.findall(r'\.compatible = "([^"]+)"', PANEL))
    binding = kpatch.find("0003-").read_text()
    assert driver == set(re.findall(r"^\+\s+- (ga36mb,jd9366-panel\d)$", binding, re.M))
    dts = {c for f in DTS_DIR.glob("*.dts") for c in re.findall(r'"(ga36mb,jd9366-panel\d)"', f.read_text())}
    assert dts == driver
    assert "obj-$(CONFIG_DRM_PANEL_GA36MB_JD9366) += panel-ga36mb-jd9366.o" in \
        kpatch.added_lines(kpatch.find("0005-"), "drivers/gpu/drm/panel/Makefile")


def test_gamepad_matches_binding_and_dts():
    assert re.findall(r'\.compatible = "([^"]+)"', GAMEPAD) == ["ga36mb,ga36-gamepad"]
    names = set(re.findall(r'\{ "([a-z-]+)", (?:BTN_\w+) \}', GAMEPAD))
    dtsi = (DTS_DIR / "sun8i-a33-ga36-mb-v1.2.dtsi").read_text()
    used = set(re.findall(r"\b((?:dpad|btn)-[a-z]+)-gpios", dtsi))
    assert used and used <= names, used - names
    # the property pattern of the binding (0004) covers every button of the driver
    pattern = re.search(r'"\^\((.*)\)-gpios\$"', kpatch.find("0004-").read_text()).group(1)
    assert all(re.fullmatch(pattern, n) for n in names), names
    assert "obj-$(CONFIG_JOYSTICK_GA36MB)\t\t+= ga36mb-gamepad.o" in \
        kpatch.added_lines(GAMEPAD_PATCH, "drivers/input/joystick/Makefile")
