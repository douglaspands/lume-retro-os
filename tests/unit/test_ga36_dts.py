"""DTS do GA36-MB V1.2 contra o Apêndice B do design (tarefa 9.3).

Lê o fonte (board/ga36/dts/) sem compilar: o dtc e o dt-validate rodam no build
(r36os.kernel.build_dtbs). Os valores esperados são os do Apêndice B.
"""

import re

import pytest

from r36os.paths import REPO_ROOT

DTS_DIR = REPO_ROOT / "board/ga36/dts"
DTSI = (DTS_DIR / "sun8i-a33-ga36-mb-v1.2.dtsi").read_text()
VARIANTS = {
    "sun8i-a33-ga36-mb-v1.2-panel1.dts": "ga36mb,jd9366-panel1",
    "sun8i-a33-ga36-mb-v1.2-panel2.dts": "ga36mb,jd9366-panel2",
}
ALL_SOURCES = [DTSI] + [(DTS_DIR / n).read_text() for n in VARIANTS]

# Apêndice B: botão -> pino
GAMEPAD = {
    "dpad-up": "PE9", "dpad-down": "PE8", "dpad-left": "PE7", "dpad-right": "PE6",
    "btn-a": "PE13", "btn-b": "PE12", "btn-x": "PE11", "btn-y": "PE10",
    "btn-lb": "PE15", "btn-lt": "PE14", "btn-rb": "PE17", "btn-rt": "PE16",
    "btn-thumbl": "PB3", "btn-thumbr": "PB2",
    "btn-start": "PE4", "btn-select": "PE5", "btn-fn": "PE1",
}


def _code(text: str) -> str:
    """Remove comentários (/* */ e //) para checar só o que o dtc compila."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", text)


def _pin(ctrl: str, bank: int, num: int) -> str:
    """<&pio 4 13 ...> -> PE13; <&r_pio 0 4 ...> -> PL4."""
    if ctrl == "r_pio":
        return f"P{chr(ord('L') + bank)}{num}"
    return f"P{chr(ord('A') + bank)}{num}"


def _gpio(prop: str) -> tuple[str, str]:
    m = re.search(rf"\b{re.escape(prop)}\s*=\s*<&(pio|r_pio) (\d+) (\d+) (GPIO_ACTIVE_\w+)>",
                  _code(DTSI))
    assert m, f"{prop} não encontrado"
    return _pin(m.group(1), int(m.group(2)), int(m.group(3))), m.group(4)


def _node(label: str) -> str:
    m = re.search(rf"^&{re.escape(label)} \{{(.*?)^\}};", _code(DTSI), flags=re.S | re.M)
    assert m, f"&{label} não encontrado"
    return m.group(1)


@pytest.mark.parametrize("button,pin", GAMEPAD.items())
def test_gamepad_pins_match_appendix_b(button, pin):
    assert _gpio(f"{button}-gpios") == (pin, "GPIO_ACTIVE_LOW")


def test_a_and_b_are_not_swapped():
    # o goodluckOS tem PE12/PE13 invertidos; o Apêndice B corrige
    assert _gpio("btn-a-gpios")[0] == "PE13"
    assert _gpio("btn-b-gpios")[0] == "PE12"


def test_gamepad_on_uart1_as_mcu():
    uart1 = _node("uart1")
    assert "&uart1_pg_pins" in uart1
    assert re.search(r"\bmcu \{\s*compatible = \"ga36mb,ga36-gamepad\";", uart1)


def test_board_pins():
    assert _gpio("reset-gpios") == ("PH7", "GPIO_ACTIVE_LOW")       # painel
    assert _gpio("enable-gpios") == ("PH9", "GPIO_ACTIVE_HIGH")     # amplificador
    assert _gpio("usb0_id_det-gpios") == ("PH8", "GPIO_ACTIVE_HIGH")
    leds = re.findall(r"gpios = <&(pio|r_pio) (\d+) (\d+) GPIO_ACTIVE_HIGH>",
                      re.search(r"leds \{(.*?)\n\t\};", _code(DTSI), re.S).group(1))
    assert [_pin(c, int(b), int(n)) for c, b, n in leds] == ["PL4", "PG13"]  # azul, vermelho
    assert '"PB0", "PB1"' in DTSI and 'function = "uart2"' in DTSI       # serial de debug
    assert 'stdout-path = "serial1:115200n8"' in DTSI


def test_backlight_and_volume_keys():
    code = _code(DTSI)
    assert "pwms = <&pwm 0 50000 0>" in code                    # PWM0, 20 kHz
    assert "brightness-levels = <0 10 20 30 40 50 60 70 80 90 100>" in code
    assert "default-brightness-level = <8>" in code              # 80
    assert re.search(r"KEY_VOLUMEUP>;\s*channel = <0>;\s*voltage = <200000>", code)
    assert re.search(r"KEY_VOLUMEDOWN>;\s*channel = <0>;\s*voltage = <400000>", code)


def test_pmic_and_regulators():
    code = _code(DTSI)
    assert re.search(r'pmic@3a3 \{\s*compatible = "x-powers,axp223";\s*reg = <0x3a3>', code)
    assert "cpu-supply = <&reg_dcdc3>" in _node("cpu0")
    dcdc3 = _node("reg_dcdc3")
    assert "regulator-min-microvolt = <1040000>" in dcdc3
    assert "regulator-max-microvolt = <1320000>" in dcdc3
    dldo3 = _node("reg_dldo3")
    assert "regulator-min-microvolt = <3000000>" in dldo3
    assert "regulator-max-microvolt = <3000000>" in dldo3
    assert "regulator-boot-on" in _node("reg_dc1sw")
    assert "power-supply = <&reg_dc1sw>" in _node("dsi")
    assert "vcc-dsi-supply = <&reg_dldo3>" in _node("dsi")
    for reg in ("dcdc1", "dcdc2", "dcdc3", "dcdc5", "aldo1", "aldo2", "aldo3", "dc5ldo"):
        assert "regulator-always-on" in _node(f"reg_{reg}"), reg


def test_battery():
    code = _code(DTSI)
    assert "charge-full-design-microamp-hours = <3000000>" in code
    assert "factory-internal-resistance-micro-ohms = <119000>" in code
    assert "voltage-max-design-microvolt = <4200000>" in code
    assert "voltage-min-design-microvolt = <3300000>" in code


@pytest.mark.parametrize("name,compatible", VARIANTS.items())
def test_variants(name, compatible):
    src = (DTS_DIR / name).read_text()
    assert '#include "sun8i-a33-ga36-mb-v1.2.dtsi"' in src
    assert f'compatible = "{compatible}";' in src
    assert 'compatible = "ga36mb,ga36-mb-v1.2", "allwinner,sun8i-a33";' in src


@pytest.mark.parametrize("forbidden", [
    "opp-", "opp_table", "operating-points", "thermal-zones", "trips", "cooling-maps",
    "polling-delay", "#cooling-cells", "&ths", "memory@", "device_type",
])
def test_mainline_cpu_thermal_and_memory_untouched(forbidden):
    # OPPs e zonas térmicas vêm do sun8i-a33.dtsi sem alteração (até 1008 MHz) e o
    # tamanho da DRAM vem do U-Boot
    for src in ALL_SOURCES:
        assert forbidden not in _code(src)
