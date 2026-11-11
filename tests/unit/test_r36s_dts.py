"""R36S V5 DTS against appendix A of the alpine-retroarch-distro design (task 4.3 of
r36s-single-card).

Reads the source (board/r36s/dts/) without compiling: dtc and dt-validate run in the build
(r36os.kernel.build_dtbs). The expected values are those of appendix A, which comes from
the factory device tree of the device.
"""

import re

import pytest

from r36os import kpatch
from r36os.paths import REPO_ROOT

DTS = (REPO_ROOT / "board/r36s/dts/rk3326-r36s-v5.dts").read_text()
BANKS = "ABCD"


def _code(text: str) -> str:
    """Strip comments (/* */ and //) to check only what dtc compiles."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


CODE = _code(DTS)


def _num(pin: str) -> int:
    """RK_PB3 -> 11."""
    return BANKS.index(pin[4]) * 8 + int(pin[5])


def _node(name: str) -> str:
    """Body of a node by name (up to the first closing brace at its indentation)."""
    m = re.search(rf"^(\t*){re.escape(name)} \{{\n(.*?)^\1\}};", CODE, re.S | re.M)
    assert m, f"{name} not found"
    return m.group(2)


def _gpio(body: str, prop: str = "gpios") -> tuple[int, int, str]:
    """(bank, pin, flags) of the first `prop = <&gpioN RK_Pxn FLAGS>` in body."""
    m = re.search(rf"\b{prop} = <&gpio(\d) (RK_P[A-D]\d) (GPIO_ACTIVE_\w+)>", body)
    assert m, f"{prop} not found"
    return int(m.group(1)), _num(m.group(2)), m.group(3)


def _hog(name: str) -> tuple[int, int, str]:
    """(bank, pin, flags) of a gpio-hog: the bank is the &gpioN node that holds it."""
    for bank in range(4):
        m = re.search(rf"^&gpio{bank} \{{\n(.*?)^\}};", CODE, re.S | re.M)
        if m and f"\t{name} {{" in m.group(1):
            hog = re.search(rf"\t{name} \{{(.*?)\}};", m.group(1), re.S).group(1)
            assert "gpio-hog;" in hog and "output-high;" in hog, name
            pin, flags = re.search(r"gpios = <(RK_P[A-D]\d) (GPIO_ACTIVE_\w+)>", hog).groups()
            return bank, _num(pin), flags
    raise AssertionError(f"{name} not found")


# Appendix A: button -> (bank, pin, code)
BUTTONS = {
    "button-up": (3, 7, "BTN_DPAD_UP"), "button-down": (3, 8, "BTN_DPAD_DOWN"),
    "button-left": (3, 10, "BTN_DPAD_LEFT"), "button-right": (3, 9, "BTN_DPAD_RIGHT"),
    "button-a": (3, 14, "BTN_EAST"), "button-b": (3, 12, "BTN_SOUTH"),
    "button-x": (3, 13, "BTN_NORTH"), "button-y": (3, 11, "BTN_WEST"),
    "button-l1": (3, 3, "BTN_TL"), "button-r1": (3, 0, "BTN_TR"),
    "button-l2": (3, 2, "BTN_TL2"), "button-r2": (3, 1, "BTN_TR2"),
    "button-f1": (3, 5, "BTN_TRIGGER_HAPPY1"), "button-f2": (3, 6, "BTN_TRIGGER_HAPPY2"),
    "button-f3": (0, 11, "BTN_TRIGGER_HAPPY3"), "button-f4": (3, 27, "BTN_TRIGGER_HAPPY4"),
    "button-f5": (3, 4, "BTN_TRIGGER_HAPPY5"),
}


@pytest.mark.parametrize("button,expected", BUTTONS.items())
def test_buttons_match_appendix_a(button, expected):
    body = _node(button)
    bank, pin, flags = _gpio(body)
    assert (bank, pin, flags) == (expected[0], expected[1], "GPIO_ACTIVE_LOW")
    assert f"linux,code = <{expected[2]}>" in body


def test_seventeen_gamepad_buttons_with_pull_ups():
    keys = _node("gpio-keys")
    assert len(re.findall(r"^\t\tbutton-", keys, re.M)) == 17
    pulls = {(int(b), _num(p)) for b, p in re.findall(r"<(\d) (RK_P[A-D]\d) RK_FUNC_GPIO &pcfg_pull_up>",
                                                       _node("btn_pins: btn-pins"))}
    assert pulls == {(b, p) for b, p, _ in BUTTONS.values()}


def test_panel():
    panel = _node("internal_display: panel@0")
    assert 'compatible = "r36s,r36s-v5-panel"' in panel
    assert _gpio(panel, "reset-gpios") == (3, 16, "GPIO_ACTIVE_LOW")
    assert "vcc-supply = <&vcc_lcd>" in panel
    # enable (gpio1 18, active low) and stbyb (gpio3 15, active high) held asserted by hogs
    assert _hog("lcd-enable-hog") == (1, 18, "GPIO_ACTIVE_LOW")
    assert _hog("lcd-stbyb-hog") == (3, 15, "GPIO_ACTIVE_HIGH")
    # panel supply: RK817 LDO_REG8 at 1.8 V (factory DTB)
    ldo8 = _node("vcc_lcd: LDO_REG8")
    assert "regulator-min-microvolt = <1800000>" in ldo8


def test_panel_compatible_matches_binding_and_driver():
    binding = kpatch.find("0009-").read_text()
    driver = "\n".join(kpatch.added_lines(kpatch.find("0010-"),
                                          "drivers/gpu/drm/panel/panel-sitronix-st7703.c"))
    assert "+      - r36s,r36s-v5-panel" in binding
    assert '"r36s,r36s-v5-panel"' in driver
    assert 'compatible = "r36s,r36s-v5", "rockchip,rk3326"' in CODE
    assert "const: r36s,r36s-v5" in kpatch.find("0008-").read_text()


def test_backlight_is_pwm1_with_161_levels():
    bl = _node("backlight: backlight")
    assert "pwms = <&pwm1 0 40000 0>" in bl
    assert "brightness-levels = <0 160>" in bl and "num-interpolated-steps = <160>" in bl
    assert "default-brightness-level = <80>" in bl


def test_sticks_on_saradc_channel_1_behind_the_mux():
    mux = _node("joystick_mux_controller: mux-controller")
    pins = re.findall(r"<&gpio(\d) (RK_P[A-D]\d) GPIO_ACTIVE_LOW>", mux)
    assert [(int(b), _num(p)) for b, p in pins] == [(0, 13), (0, 12)]  # mux A, mux B
    assert "io-channels = <&saradc 1>" in _node("joystick_mux: adc-mux")
    assert _hog("joystick-mux-en-hog") == (0, 17, "GPIO_ACTIVE_LOW")
    sticks = _node("analog_sticks: adc-joystick")
    codes = re.findall(r"linux,code = <(ABS_\w+)>", sticks)
    assert sorted(codes) == ["ABS_RX", "ABS_RY", "ABS_X", "ABS_Y"]


def test_leds():
    assert _gpio(_node("red_led: led-0")) == (0, 5, "GPIO_ACTIVE_HIGH")
    assert _gpio(_node("blue_led: led-1")) == (0, 0, "GPIO_ACTIVE_HIGH")
    assert "LED_FUNCTION_STATUS" in _node("blue_led: led-1")


def test_audio():
    amp = _node("spk_amp: audio-amplifier")
    assert _gpio(amp, "enable-gpios") == (3, 20, "GPIO_ACTIVE_HIGH")
    card = _node("rk817-sound")
    assert _gpio(card, "simple-audio-card,hp-det-gpios") == (2, 22, "GPIO_ACTIVE_LOW")
    assert "simple-audio-card,mclk-fs = <256>" in card
    assert "sound-dai = <&rk817>" in card and "sound-dai = <&i2s1_2ch>" in card


def test_battery_matches_appendix_a():
    bat = _node("battery: battery")
    assert "charge-full-design-microamp-hours = <3188000>" in bat
    assert "factory-internal-resistance-micro-ohms = <113000>" in bat
    assert "voltage-min-design-microvolt = <3300000>" in bat
    ocv = [int(v) // 1000 for v, _ in re.findall(r"<(\d+) (\d+)>", bat.split("ocv-capacity-table-0", 1)[1])]
    assert ocv[::-1] == [3400, 3444, 3493, 3529, 3559, 3582, 3599, 3615, 3634, 3660, 3701,
                         3759, 3809, 3852, 3886, 3911, 3961, 4012, 4028, 4075, 4182]
    assert "monitored-battery = <&battery>" in _node("rk817_charger: charger")


def test_cpu_supply_and_serial():
    for cpu in range(4):
        assert "cpu-supply = <&vdd_arm>" in _node(f"&cpu{cpu}")
    assert 'stdout-path = "serial2:1500000n8"' in CODE
    assert "pinctrl-0 = <&uart2m1_xfer>" in _node("&uart2")


def test_mainline_opps_and_thermal_unchanged():
    # OPPs and thermal zones come from rk3326.dtsi as they are
    assert '#include "rk3326.dtsi"' in CODE
    assert not re.search(r"opp-table|thermal-zones|&cpu0_opp_table|&soc_thermal", CODE)
