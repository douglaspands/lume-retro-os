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


def test_dsi_dphy_escape_clock_not_inverted():
    # second and third boots on the R36S (2026-11-12): the init commands went through
    # but the panel showed a washed out grey screen; the factory firmware leaves
    # INVERT_TXCLKESC at 0, mainline never writes it (patch 0011)
    patch = kpatch.find("0011-").read_text()
    driver = "\n".join(kpatch.added_lines(kpatch.find("0011-"),
                                          "drivers/phy/rockchip/phy-rockchip-inno-dsidphy.c"))
    assert "rockchip,txclkesc-not-inverted;" in _node("&dsi_dphy")
    assert '"rockchip,txclkesc-not-inverted"' in driver
    assert "INVERT_TXCLKESC_MASK, INVERT_TXCLKESC_DISABLE" in driver
    assert "+  rockchip,txclkesc-not-inverted:" in patch  # binding, for dt-validate


def test_dsi_dphy_detects_px30s_and_logs_the_lane_rate():
    # eighth boot on the R36S (2026-11-12): the panel answered every read over the low
    # power path and turned the display on, still grey; the high speed video path
    # depends on the D-PHY timing, which differs on PX30S/RK3326S (patch 0013)
    driver = "\n".join(kpatch.added_lines(kpatch.find("0013-"),
                                          "drivers/phy/rockchip/phy-rockchip-inno-dsidphy.c"))
    assert "#define PX30_DDR_GRF_BASE\t0xff630000" in driver
    assert "((val >> 14) & 0x3) == 0x3" in driver  # vendor rockchip-cpuinfo.c px30_init()
    assert '"SoC revision: %s (DDR_GRF_CON1 0x%08x)\\n"' in driver
    assert "inno->pdata = &max_2_5ghz_video_phy_plat_data;" in driver
    assert "inno->txclkesc_not_inverted = true;" in driver
    assert '"lane rate %lu Hz' in driver


def test_dsi_host_times_lines_with_the_real_phy_lane_rate():
    # ninth boot on the R36S (2026-11-12): plain PX30, PLL at 198 Mbps while the host
    # timed the lines for 202 Mbps; grey screen and a whining panel (patch 0014)
    patch = kpatch.find("0014-")
    phy = "\n".join(kpatch.added_lines(patch, "drivers/phy/rockchip/phy-rockchip-inno-dsidphy.c"))
    glue = "\n".join(kpatch.added_lines(patch, "drivers/gpu/drm/rockchip/dw-mipi-dsi-rockchip.c"))
    assert ".validate = inno_dsidphy_validate," in phy
    assert "inno->pll = saved;" in phy  # validate must not change the programmed PLL
    assert "opts->mipi_dphy.hs_clk_rate = rate;" in phy
    assert "phy_validate(dsi->phy, PHY_MODE_MIPI_DPHY, 0, &dsi->phy_opts)" in glue
    assert '"lane rate %u Mbps (PHY %llu Hz)\\n"' in glue
    # boot 10: only hs_clk_rate changed, the stale D-PHY timings failed the PHY check
    # (hs_prepare), phy_configure() returned -EINVAL unseen and the PLL stayed at 0 Hz
    assert "phy_mipi_dphy_get_default_config_for_hsclk(rate, lanes," in glue
    assert '"failed to configure phy: %d\\n"' in glue


def test_panel_is_read_back_while_video_runs():
    # patch 0016: scanline twice and the DSI error count, read from enable in video mode
    panel = "\n".join(kpatch.added_lines(kpatch.find("0016-"),
                                         "drivers/gpu/drm/panel/panel-sitronix-st7703.c"))
    assert "MIPI_DCS_GET_SCANLINE, MIPI_DCS_GET_SCANLINE," in panel
    assert "MIPI_DCS_GET_ERROR_COUNT_ON_DSI" in panel
    assert "st7703_log_video(ctx);" in panel
    assert '"panel video %d %02x: %*ph\\n"' in panel


def test_dsi_link_as_the_factory_kernel_runs_it():
    # boot 14: lane rate and LP/HS transition times of the factory register dump
    # (patch 0019 reads them from the DSI node), 250 ms after exit sleep (patch 0018)
    dts = (REPO_ROOT / "board/r36s/dts/rk3326-r36s-v5.dts").read_text()
    assert "rockchip,lane-rate = <180>;" in dts
    assert "rockchip,phy-hstt = <64 64 16 20>;" in dts
    glue = "\n".join(kpatch.added_lines(kpatch.find("0019-"),
                                        "drivers/gpu/drm/rockchip/dw-mipi-dsi-rockchip.c"))
    assert 'of_property_read_u32(np, "rockchip,lane-rate", &dsi->lane_rate_mbps);' in glue
    assert 'of_property_read_u32_array(np, "rockchip,phy-hstt", hstt, 4)' in glue
    panel = "\n".join(kpatch.added_lines(kpatch.find("0018-"),
                                         "drivers/gpu/drm/panel/panel-sitronix-st7703.c"))
    assert ".sleep_out_delay_ms = 250," in panel


def test_clock_lane_stays_in_lp_for_lp_commands():
    # patch 0020: like the vendor kernel, no HS clock in command mode for an LPM panel
    host = "\n".join(kpatch.added_lines(kpatch.find("0020-"),
                                        "drivers/gpu/drm/bridge/synopsys/dw-mipi-dsi.c"))
    assert ("if (!(mode_flags & MIPI_DSI_MODE_VIDEO) && (dsi->mode_flags & MIPI_DSI_MODE_LPM))"
            in host)


def test_adc_joystick_inverts_with_the_axis_code():
    # patch 0022 (boot 15): channel 2 is ABS_Y; inverting with the channel index gave 0 - raw
    drv = "\n".join(kpatch.added_lines(kpatch.find("0022-"),
                                       "drivers/input/joystick/adc-joystick.c"))
    assert drv.count("adc_joystick_invert(") == 2
    assert drv.count("joy->axes[i].code, val)") == 2


def test_input_event_log_is_bring_up_only():
    # patch 0021 + CONFIG_INPUT_EVLOG (boot 15): only the R36S kernel turns it on
    core = "\n".join(kpatch.added_lines(kpatch.find("0021-"), "drivers/input/input.c"))
    assert "if (IS_ENABLED(CONFIG_INPUT_EVLOG))" in core
    assert '"evlog: %s (%s) grabbed by %s\\n"' in core
    assert "CONFIG_INPUT_EVLOG=y" in (REPO_ROOT / "board/r36s/kernel.config").read_text()
    assert "INPUT_EVLOG" not in (REPO_ROOT / "board/ga36/kernel.config").read_text()


def test_dsi_host_logs_the_px30_display_registers_once():
    # patch 0017: same regions and line format as board/r36s/diag/regdump.sh
    host = "\n".join(kpatch.added_lines(kpatch.find("0017-"),
                                        "drivers/gpu/drm/bridge/synopsys/dw-mipi-dsi.c"))
    for region in ('{ "dsi",    0xff450000, 0x200 }', '{ "dphy",   0xff2e0000, 0x400 }',
                   '{ "vop",    0xff460000, 0x300 }', '{ "grf",    0xff140000, 0x500 }'):
        assert region in host
    assert '"regdump %s %#010llx %#06x %#010x\\n"' in host
    assert "if (dsi->status_samples == 0)" in host


def test_dsi_host_logs_its_error_status_in_video_mode():
    # patch 0015: INT_ST0/INT_ST1 (read to clear) and PHY_STATUS sampled after video starts
    host = "\n".join(kpatch.added_lines(kpatch.find("0015-"),
                                        "drivers/gpu/drm/bridge/synopsys/dw-mipi-dsi.c"))
    assert "INIT_DELAYED_WORK(&dsi->status_work, dw_mipi_dsi_status_work);" in host
    assert host.count("cancel_delayed_work_sync(&dsi->status_work);") == 2  # disable, remove
    assert '"status sample %u: int_st0 0x%06x int_st1 0x%06x phy_status 0x%04x' in host


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


def test_stick_channels_and_directions_as_tested_on_the_device():
    # boot 17 (2026-11-12): left stick as read; right stick turned 90 degrees, both inverted
    sticks = _node("analog_sticks: adc-joystick")
    axes = {int(reg): (int(a), int(b), code) for reg, a, b, code in re.findall(
        r"reg = <(\d)>;.*?abs-range = <(\d+) (\d+)>;\s*linux,code = <(ABS_\w+)>", sticks, re.S)}
    assert {reg: code for reg, (_, _, code) in axes.items()} == {
        0: "ABS_X", 1: "ABS_RY", 2: "ABS_Y", 3: "ABS_RX"}
    inverted = {code for a, b, code in axes.values() if a > b}
    assert inverted == {"ABS_RX", "ABS_RY"}


def test_leds():
    assert _gpio(_node("red_led: led-0")) == (0, 5, "GPIO_ACTIVE_HIGH")
    assert _gpio(_node("blue_led: led-1")) == (0, 0, "GPIO_ACTIVE_HIGH")
    assert "LED_FUNCTION_STATUS" in _node("blue_led: led-1")


def test_audio():
    # boot 18: speaker on SPKO as ROCKNIX; the factory spk-ctl line (gpio3 20) held high
    assert _hog("speaker-enable-hog") == (3, 20, "GPIO_ACTIVE_HIGH")
    card = _node("rk817-sound")
    assert '"Internal Speakers", "SPKO"' in card and "aux-devs" not in card
    assert 'pin-switches = "Internal Speakers"' in card  # the mixer turns it on by name
    # active high, as the factory rk_headset node: active low muted the speaker (boot 16)
    assert _gpio(card, "simple-audio-card,hp-det-gpios") == (2, 22, "GPIO_ACTIVE_HIGH")
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
