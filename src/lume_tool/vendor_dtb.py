"""Device trees of the Rockchip 4.4 kernel (dArkOS, arkos4clone, factory) as Lume DTS.

boot-dtb-select D12 (revised 2026-11-16): the conversion runs on the PC, at import time,
not at boot. `extract()` reads a vendor RK3326 DTB (the Rockchip BSP kernel 4.4 or 5.10
bindings) and keeps only what differs between the R36S-like boards: the panel (init
sequence, timings, delays, pins), the backlight, the buttons, the sticks, the speaker
amplifier and the headphone detection, the battery, the LEDs, the PMIC interrupt and the
supply (D18: the RK817 regulators and the IO domain map).
`to_dts()` writes that board as a small DTS that includes the native R36S V5 tree
(`rk3326-r36s-v5.dts`) and overrides those nodes; the build compiles it with the kernel
tree and checks it with dt-validate like any native DTS.

The panel becomes a `rocknix,generic-dsi` node (kernel patch 0033): its text description is
the format of the ROCKNIX `panel-generic-dsi` driver. The panel and stick logic follows
`rocknix_dtbo.py` of ROCKNIX (stolen/overlay_server, MIT, Danil Zagoskin) and the ROCKNIX
`rocknix-singleadc-joypad` driver (GPL-2.0); the battery and LED conversion is ours.

Nothing here touches the source DTB, and a board that cannot be described safely raises
`Refused` with the reason (the import lists it). The speaker gain of the source codec
(`spk-volume`) is never carried over: the mainline codec keeps the safe value of the
native tree, and the import records the value it ignored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from lume_tool import fdt

# PX30/RK3326 MMIO addresses -> the bank or controller number of rk3326.dtsi (mainline)
GPIO_BANKS = {0xFF040000: 0, 0xFF250000: 1, 0xFF260000: 2, 0xFF270000: 3}
PWMS = {0xFF200000: 0, 0xFF200010: 1, 0xFF200020: 2, 0xFF200030: 3,
        0xFF208000: 4, 0xFF208010: 5, 0xFF208020: 6, 0xFF208030: 7}
SARADC = 0xFF288000

# the pins of the native R36S V5 stick multiplexer (A, B): same board, same measured axes
NATIVE_MUX = ((0, 13), (0, 12))

# key codes of the 4.4 joypads that are volume keys (the native keeps them apart)
KEY_VOLUMEDOWN, KEY_VOLUMEUP = 114, 115
ABS_X, ABS_Y, ABS_RX, ABS_RY = 0, 1, 3, 4
ABS_NAMES = {ABS_X: "ABS_X", ABS_Y: "ABS_Y", ABS_RX: "ABS_RX", ABS_RY: "ABS_RY"}

# the 4.4 dsi,format value -> panel_description format, and its bits per pixel
DSI_FORMATS = ["rgb888", "rgb666", "rgb666_packed", "rgb565"]
DSI_BPP = [24, 18, 18, 16]
PX30_MAX_LANE_MBPS = 1000

# the RK817 regulators of the mainline driver (rk808-regulator.c, rk817_reg), which are the
# nodes of the native tree; some vendor trees also list RK809 ones (DCDC_REG5, SWITCH_REG*)
RK817_REGULATORS = (tuple(f"DCDC_REG{i}" for i in range(1, 5))
                    + tuple(f"LDO_REG{i}" for i in range(1, 10)) + ("BOOST", "OTG_SWITCH"))
# the PX30 IO domains of the mainline io-domain driver (soc_data_px30, soc_data_px30_pmu)
IO_DOMAINS = ("vccio1", "vccio2", "vccio3", "vccio4", "vccio5", "vccio6", "vccio-oscgpi")
PMU_IO_DOMAINS = ("pmuio1", "pmuio2")
IO_DOMAIN_MAX_UV = 3600000   # MAX_VOLTAGE_3_3 of the io-domain driver
NATIVE_REGULATORS = "/i2c@ff180000/pmic@20/regulators"   # the RK817 of the native tree


def vendor_lane_mbps(clock_khz: int, fmt: int, lanes: int) -> int:
    """The DSI lane rate the Rockchip 4.4 driver picks for a mode (dw-mipi-dsi.c,
    dw_mipi_dsi_get_lane_rate): the pixel bandwidth per lane over 0.9, capped. Our kernel
    gets it as rockchip,lane-rate (patch 0019): its own estimate differs, and the R36S V5
    shows no image without the factory rate (180 Mbps for 27 MHz, RGB888, 4 lanes)."""
    rate = clock_khz * 1000 * DSI_BPP[fmt] // lanes * 10 // 9
    return min(rate // 1_000_000, PX30_MAX_LANE_MBPS)


class Refused(Exception):
    """The source DTB cannot be converted; the message is the reason (English, for logs)."""


@dataclass(frozen=True)
class Pin:
    bank: int
    pin: int
    active_low: bool = False

    @property
    def macro(self) -> str:
        return f"RK_P{'ABCD'[self.pin // 8]}{self.pin % 8}"

    def spec(self) -> str:
        level = "GPIO_ACTIVE_LOW" if self.active_low else "GPIO_ACTIVE_HIGH"
        return f"<&gpio{self.bank} {self.macro} {level}>"

    def pinctrl(self, pull: str) -> str:
        return f"<{self.bank} {self.macro} RK_FUNC_GPIO &pcfg_{pull}>"


@dataclass
class Key:
    name: str
    label: str
    code: int
    pin: Pin


@dataclass
class Axis:
    code: int
    invert: bool
    channel: int  # mux state, or SARADC channel without a mux


@dataclass
class Regulator:
    name: str | None
    min_uv: int | None
    max_uv: int | None
    always_on: bool
    boot_on: bool
    suspend: dict | None   # regulator-state-mem: {"on": True/False/None, "uv": int | None}


@dataclass
class Power:
    """The supply layout of the source board (D18): its RK817 regulators and which of them
    feeds each IO domain of the SoC."""
    regulators: dict[str, Regulator]
    io_domains: dict[str, str]        # vccio1 -> LDO_REG5
    pmu_io_domains: dict[str, str]    # pmuio1 -> LDO_REG4
    notes: list[str] = field(default_factory=list)


@dataclass
class Board:
    model: str
    panel: list[str]
    reset: Pin
    lane_mbps: int = 0
    enable: Pin | None = None
    stbyb: Pin | None = None
    lcd_power: tuple[Pin, bool] | None = None   # gpio, enable-active-high
    backlight: dict = field(default_factory=dict)
    keys: list[Key] = field(default_factory=list)
    volume_keys: list[Key] = field(default_factory=list)
    adc_keys: dict | None = None
    mux: tuple[Pin, Pin] | None = None
    mux_en: Pin | None = None
    stick_adc: int = 1
    axes: list[Axis] | None = None   # None: the native, measured axes
    amp: Pin | None = None
    hp_det: tuple[Pin, str] | None = None   # pin, pull
    battery: dict | None = None
    leds: list[tuple[str, Pin]] = field(default_factory=list)
    pmic_irq: Pin | None = None
    power: Power | None = None
    notes: list[str] = field(default_factory=list)


# --- reading the source tree ------------------------------------------------------------

class Tree:
    def __init__(self, data: bytes):
        self.root = fdt.parse(data)
        self.by_phandle: dict[int, tuple[str, fdt.Node]] = {}
        self._index(self.root, "")

    def _index(self, node: fdt.Node, path: str) -> None:
        ph = node.cells("phandle") or node.cells("linux,phandle")
        if ph:
            self.by_phandle[ph[0]] = (path or "/", node)
        for name, child in node.children.items():
            self._index(child, f"{path}/{name}")

    def walk(self, node: fdt.Node | None = None, path: str = ""):
        node = node or self.root
        yield path or "/", node
        for name, child in node.children.items():
            yield from self.walk(child, f"{path}/{name}")

    def node(self, phandle: int) -> tuple[str, fdt.Node]:
        try:
            return self.by_phandle[phandle]
        except KeyError:
            raise Refused(f"phandle {phandle:#x} points nowhere") from None

    def find(self, *compatibles: str) -> list[tuple[str, fdt.Node]]:
        return [(p, n) for p, n in self.walk() if set(n.strings("compatible")) & set(compatibles)
                and n.string("status") not in ("disabled",)]

    def unit_address(self, phandle: int) -> int:
        path, _ = self.node(phandle)
        m = re.search(r"@([0-9a-f]+)$", path)
        if not m:
            raise Refused(f"{path}: no unit address")
        return int(m.group(1), 16)

    def pin(self, cells: list[int], what: str) -> Pin:
        if len(cells) < 3:
            raise Refused(f"{what}: not a <phandle pin flags> GPIO")
        addr = self.unit_address(cells[0])
        if addr not in GPIO_BANKS:
            raise Refused(f"{what}: GPIO controller at {addr:#x} is not a PX30 bank")
        if cells[1] > 31:
            raise Refused(f"{what}: pin {cells[1]} out of range")
        return Pin(GPIO_BANKS[addr], cells[1], bool(cells[2] & 1))

    def pull(self, pin: Pin, default: str = "pull_up") -> str:
        """The bias the source pinctrl gives a pin (pull_up, pull_down or pull_none)."""
        for _, n in self.walk():
            pins = n.cells("rockchip,pins")
            for i in range(0, len(pins) - 3, 4):
                if (pins[i], pins[i + 1]) == (pin.bank, pin.pin):
                    _, conf = self.by_phandle.get(pins[i + 3], ("", fdt.Node()))
                    if "bias-pull-up" in conf.props:
                        return "pull_up"
                    if "bias-pull-down" in conf.props:
                        return "pull_down"
                    if "bias-disable" in conf.props:
                        return "pull_none"
        return default


# --- panel ------------------------------------------------------------------------------

def init_sequence(data: bytes) -> list[tuple[int, int, bytes]]:
    """The Rockchip `panel-init-sequence` blob: (type, wait ms, payload) per command."""
    out, pos = [], 0
    while pos < len(data):
        if pos + 3 > len(data):
            raise Refused("panel-init-sequence: truncated header")
        kind, wait, size = data[pos], data[pos + 1], data[pos + 2]
        payload = data[pos + 3:pos + 3 + size]
        if len(payload) != size or size == 0:
            raise Refused("panel-init-sequence: truncated or empty command")
        out.append((kind, wait, payload))
        pos += 3 + size
    if not out:
        raise Refused("panel-init-sequence: empty")
    return out


def _u32(node: fdt.Node, name: str, default: int | None = None) -> int:
    v = node.cells(name)
    if v:
        return v[0]
    if default is None:
        raise Refused(f"panel: no {name}")
    return default


def panel_description(panel: fdt.Node) -> list[str]:
    """`panel_description` lines of the generic DSI driver (format of `rocknix_dtbo.py`).

    Unlike rocknix_dtbo.py the modes are the vendor ones as they are (no synthesized
    refresh rates): what the vendor kernel ran is what is known to work.
    """
    delays = [_u32(panel, "prepare-delay-ms", 50), _u32(panel, "reset-delay-ms", 50),
              _u32(panel, "init-delay-ms", 50), _u32(panel, "enable-delay-ms", 50), 20]
    fmt_cells = panel.cells("dsi,format")
    fmt = fmt_cells[0] if fmt_cells else 0
    if fmt >= len(DSI_FORMATS):
        raise Refused(f"panel: dsi,format {fmt} unknown")
    lanes = _u32(panel, "dsi,lanes")
    if lanes not in (1, 2, 3, 4):
        raise Refused(f"panel: {lanes} DSI lanes")
    flags = _u32(panel, "dsi,flags") | 0x0400   # + clock non-continuous, as ROCKNIX
    timings = panel.children.get("display-timings")
    if timings is None or not any(c.cells("clock-frequency") for c in timings.children.values()):
        raise Refused("panel: no display-timings")
    native = (timings.cells("native-mode") or [None])[0]
    modes, have_default = [], False
    for t in timings.children.values():
        if not t.cells("clock-frequency"):
            continue
        hor = [_u32(t, k) for k in ("hactive", "hfront-porch", "hsync-len", "hback-porch")]
        ver = [_u32(t, k) for k in ("vactive", "vfront-porch", "vsync-len", "vback-porch")]
        clock = round(_u32(t, "clock-frequency") / 1000)
        is_default = (t.cells("phandle") or [None])[0] == native and not have_default
        have_default |= is_default
        modes.append((clock, hor, ver, is_default))
    if not have_default:
        modes[0] = modes[0][:3] + (True,)
    # only the modes of the resolution of the default one (the panel has one size)
    first = next(m for m in modes if m[3])
    modes = [m for m in modes if m[1][0] == first[1][0] and m[2][0] == first[2][0]]
    # some vendor trees list the same mode twice: once is enough (the default one stays)
    modes = [m for i, m in enumerate(modes)
             if m[3] or not any(o[:3] == m[:3] for o in modes[:i] + [first])]
    w, h = _u32(panel, "width-mm", 0), _u32(panel, "height-mm", 0)
    if not (w and h):
        raise Refused("panel: no width-mm/height-mm")
    lines = [f"G size={w},{h} delays={','.join(map(str, delays))} format={DSI_FORMATS[fmt]} "
             f"lanes={lanes} flags=0x{flags:x}"]
    for clock, hor, ver, is_default in modes:
        lines.append(f"M clock={clock} horizontal={','.join(map(str, hor))} "
                     f"vertical={','.join(map(str, ver))}" + (" default=1" if is_default else ""))
    seq = panel.props.get("panel-init-sequence")
    if not seq:
        raise Refused("panel: no panel-init-sequence")
    seen: dict[str, int] = {}
    for _kind, wait, payload in init_sequence(seq):
        # the driver reads wait in hex (panel-generic-dsi, as ROCKNIX)
        line = f"I seq={payload.hex()}" + (f" wait={wait:x}" if wait else "")
        # a string-array must have unique items (dt-schema), and sequences repeat commands
        # (page selects): a repeated line gets a comment, which the driver ignores
        seen[line] = seen.get(line, 0) + 1
        lines.append(line + (f" # {seen[line]}" if seen[line] > 1 else ""))
    return lines


# --- the conversion ---------------------------------------------------------------------

def _pmic(t: Tree) -> tuple[str, fdt.Node]:
    found = t.find("rockchip,rk817")
    if not found:
        other = t.find("rockchip,rk809", "rockchip,rk808", "rockchip,rk818")
        raise Refused("PMIC " + (other[0][1].strings("compatible")[0] if other else "missing")
                      + ": only the RK817 of the R36S is known")
    return found[0]


def _panel(t: Tree, b: Board) -> None:
    panels = [(p, n) for p, n in t.walk() if re.match(r"/dsi@[0-9a-f]+/panel@0$", p)]
    if not panels:
        raise Refused("no DSI panel node (dsi/panel@0)")
    path, panel = panels[0]
    if "simple-panel-dsi" not in panel.strings("compatible"):
        raise Refused(f"{path}: panel {panel.strings('compatible')} is not simple-panel-dsi")
    b.panel = panel_description(panel)
    m = re.search(r"^M clock=(\d+) .* default=1", "\n".join(b.panel), re.M)
    fmt = (panel.cells("dsi,format") or [0])[0]
    b.lane_mbps = vendor_lane_mbps(int(m.group(1)), fmt, panel.cells("dsi,lanes")[0])
    if not panel.cells("reset-gpios"):
        raise Refused(f"{path}: no reset-gpios")
    b.reset = t.pin(panel.cells("reset-gpios"), "panel reset")
    if panel.cells("enable-gpios"):
        b.enable = t.pin(panel.cells("enable-gpios"), "panel enable")
    if panel.cells("stbyb-gpios"):
        b.stbyb = t.pin(panel.cells("stbyb-gpios"), "panel stbyb")
    for name in sorted(panel.props):
        m = re.match(r"led-([a-z]+?)\d*-gpios$", name)
        if m:
            b.leds.append((m.group(1), t.pin(panel.cells(name), name)))
    supply = panel.cells("power-supply")
    if supply:
        _, reg = t.node(supply[0])
        if "regulator-fixed" in reg.strings("compatible") and reg.cells("gpio"):
            b.lcd_power = (t.pin(reg.cells("gpio"), "panel power"),
                           "enable-active-high" in reg.props)


def _backlight(t: Tree, b: Board) -> None:
    found = t.find("pwm-backlight")
    if not found:
        raise Refused("no pwm-backlight")
    _, bl = found[0]
    pwms = bl.cells("pwms")
    if len(pwms) < 3:
        raise Refused("backlight: no pwms")
    addr = t.unit_address(pwms[0])
    if addr not in PWMS:
        raise Refused(f"backlight: PWM at {addr:#x} unknown")
    levels = bl.cells("brightness-levels")
    if len(levels) < 2:
        raise Refused("backlight: no brightness-levels")
    default = (bl.cells("default-brightness-level") or [len(levels) // 2])[0]
    b.backlight = {"pwm": PWMS[addr], "period": pwms[2],
                   "inverted": bool(pwms[3] & 1) if len(pwms) > 3 else False,
                   "levels": levels, "default": min(default, len(levels) - 1)}


def _keys(t: Tree, b: Board, joypad: fdt.Node) -> None:
    seen = set()
    for name, sw in joypad.children.items():
        if not sw.cells("gpios"):
            continue
        code = (sw.cells("linux,code") or [0])[0]
        pin = t.pin(sw.cells("gpios"), f"button {name}")
        if (pin.bank, pin.pin) in seen:
            raise Refused(f"button {name}: pin used twice")
        seen.add((pin.bank, pin.pin))
        key = Key(name, (sw.string("label") or name).replace("GPIO ", ""), code, pin)
        (b.volume_keys if code in (KEY_VOLUMEUP, KEY_VOLUMEDOWN) else b.keys).append(key)
    if not b.keys:
        raise Refused("joypad: no buttons")
    for path, node in t.find("gpio-keys"):
        for name, k in node.children.items():
            code = (k.cells("linux,code") or [0])[0]
            if k.cells("gpios") and code in (KEY_VOLUMEUP, KEY_VOLUMEDOWN):
                pin = t.pin(k.cells("gpios"), f"{path}/{name}")
                if (pin.bank, pin.pin) not in seen:
                    seen.add((pin.bank, pin.pin))
                    b.volume_keys.append(Key(name, k.string("label") or name, code, pin))
    for path, node in t.find("adc-keys"):
        chans = node.cells("io-channels")
        if len(chans) != 2 or t.unit_address(chans[0]) != SARADC:
            raise Refused(f"{path}: not on the SARADC")
        buttons = [(n, (k.cells("linux,code") or [0])[0], k.cells("press-threshold-microvolt"))
                   for n, k in node.children.items() if k.cells("press-threshold-microvolt")]
        if buttons:
            b.adc_keys = {"channel": chans[1], "buttons": buttons,
                          "keyup": (node.cells("keyup-threshold-microvolt") or [1800000])[0]}


def _sticks(t: Tree, b: Board, joypad: fdt.Node) -> None:
    chans = joypad.cells("io-channels")
    if not chans:
        b.axes = []   # a board without sticks
        return
    for i in range(0, len(chans), 2):
        if t.unit_address(chans[i]) != SARADC:
            raise Refused("joypad: ADC channel not on the SARADC")
    inverted = {ABS_X: "invert-absx" in joypad.props, ABS_Y: "invert-absy" in joypad.props,
                ABS_RX: "invert-absrx" in joypad.props, ABS_RY: "invert-absry" in joypad.props}
    if "direct-adc" in joypad.props:
        names = joypad.strings("io-channel-names")
        codes = {"joy_x": ABS_X, "joy_y": ABS_Y, "joy_rx": ABS_RX, "joy_ry": ABS_RY}
        if len(names) != len(chans) // 2 or any(n not in codes for n in names):
            raise Refused(f"joypad: direct ADC channels {names} unknown")
        b.axes = [Axis(codes[n], inverted[codes[n]], chans[2 * i + 1])
                  for i, n in enumerate(names)]
        return
    if not (joypad.cells("amux-a-gpios") and joypad.cells("amux-b-gpios")):
        raise Refused("joypad: neither a stick multiplexer nor direct ADC channels")
    if (joypad.cells("amux-count") or [0])[0] != 4 or len(chans) != 2:
        raise Refused("joypad: only a 4-way multiplexer on one ADC channel is known")
    a = t.pin(joypad.cells("amux-a-gpios"), "stick mux A")
    bb = t.pin(joypad.cells("amux-b-gpios"), "stick mux B")
    b.mux = (a, bb)
    b.stick_adc = chans[1]
    if joypad.cells("amux-en-gpios"):
        b.mux_en = t.pin(joypad.cells("amux-en-gpios"), "stick mux enable")
    if ((a.bank, a.pin), (bb.bank, bb.pin)) == NATIVE_MUX:
        b.axes = None   # the native board: its measured axes
        return
    mapping = joypad.cells("amux-channel-mapping") or [0, 1, 2, 3]
    if sorted(mapping) != [0, 1, 2, 3]:
        raise Refused(f"joypad: amux-channel-mapping {mapping} is not a permutation")
    # rocknix-singleadc-joypad: axis slot k (RY, RX, Y, X) reads mux channel mapping[k];
    # channel m drives (A, B) = (1,1), (1,0), (0,1), (0,0) as logical levels, which is the
    # gpio-mux state A + 2B: 3, 1, 2, 0
    state = {0: 3, 1: 1, 2: 2, 3: 0}
    b.axes = [Axis(code, inverted[code], state[mapping[k]])
              for k, code in enumerate((ABS_RY, ABS_RX, ABS_Y, ABS_X))]
    b.notes.append("sticks: axes from the ROCKNIX joypad mapping, not measured")


def _sound(t: Tree, b: Board) -> None:
    amp = hp = None
    for _, card in t.find("simple-audio-card", "rockchip,multicodecs-card"):
        hp = hp or card.cells("simple-audio-card,hp-det-gpio") or card.cells("hp-det-gpio")
        amp = amp or card.cells("spk-con-gpio")
    for _, hs in t.find("rockchip_headset"):
        hp = hp or hs.cells("headset_gpio")
    _, pmic = _pmic(t)
    codec = pmic.children.get("codec")
    if codec is not None:
        amp = amp or codec.cells("spk-ctl-gpios")
        gain = codec.cells("spk-volume")
        if gain:
            b.notes.append(f"speaker gain: source spk-volume {gain[0]} ignored, "
                           "the native safe value is used")
    if amp:
        b.amp = t.pin(amp, "speaker amplifier")
    if hp:
        pin = t.pin(hp, "headphone detect")
        b.hp_det = (pin, t.pull(pin))


def _battery(t: Tree, b: Board) -> None:
    _, pmic = _pmic(t)
    bat = pmic.children.get("battery")
    if bat is None:
        return
    ocv, cap = bat.cells("ocv_table"), bat.cells("design_capacity")
    if len(ocv) != 21 or ocv != sorted(ocv) or not cap or not 500 <= cap[0] <= 20000:
        b.notes.append("battery: source table not usable, native kept")
        return
    b.battery = {"capacity_mah": cap[0], "ocv_mv": ocv}


def _leds(t: Tree, b: Board) -> None:
    for path, node in t.find("gpio-leds"):
        for name, led in node.children.items():
            if led.cells("gpios"):
                text = (led.string("label") or name).lower()
                color = next((c for c in ("red", "green", "blue", "white", "yellow")
                              if c in text), "")
                b.leds.append((color, t.pin(led.cells("gpios"), f"{path}/{name}")))


def _first(node: fdt.Node, name: str) -> int | None:
    v = node.cells(name)
    return v[0] if v else None


def power(t: Tree) -> Power:
    """The RK817 regulators and the IO domain map of the source (D18), or Refused."""
    pmic_path, pmic = _pmic(t)
    regs = pmic.children.get("regulators")
    if regs is None or not regs.children:
        raise Refused("PMIC: no regulators node")
    p = Power({}, {}, {})
    for name, r in regs.children.items():
        if name not in RK817_REGULATORS:
            p.notes.append(f"power: source regulator {name} is not an RK817 one, ignored")
            continue
        mem = r.children.get("regulator-state-mem")
        suspend = None
        if mem is not None:
            on = (True if "regulator-on-in-suspend" in mem.props
                  else False if "regulator-off-in-suspend" in mem.props else None)
            suspend = {"on": on, "uv": _first(mem, "regulator-suspend-microvolt")}
        p.regulators[name] = Regulator(
            r.string("regulator-name"), _first(r, "regulator-min-microvolt"),
            _first(r, "regulator-max-microvolt"), "regulator-always-on" in r.props,
            "regulator-boot-on" in r.props, suspend)
    missing = [n for n in RK817_REGULATORS if n not in p.regulators]
    if missing:
        p.notes.append(f"power: {', '.join(missing)} not declared by the source: "
                       "no voltage set, left on")
    for compat, known, out in (
            ("rockchip,px30-io-voltage-domain", IO_DOMAINS, p.io_domains),
            ("rockchip,px30-pmu-io-voltage-domain", PMU_IO_DOMAINS, p.pmu_io_domains)):
        for _, node in t.find(compat):
            for prop in sorted(node.props):
                if not prop.endswith("-supply"):
                    continue
                domain = prop.removesuffix("-supply")
                if domain not in known:
                    raise Refused(f"io domain {domain}: unknown to the PX30 driver")
                path, _ = t.node(node.cells(prop)[0])
                parent, _, reg = path.rpartition("/")
                if parent != f"{pmic_path}/regulators":
                    raise Refused(f"io domain {domain}: supply {path} is outside the PMIC")
                if reg not in p.regulators:
                    raise Refused(f"io domain {domain}: supply {reg} is not an RK817 regulator")
                uv = p.regulators[reg].max_uv
                if uv is not None and uv > IO_DOMAIN_MAX_UV:
                    raise Refused(f"io domain {domain}: {reg} up to {uv} uV, above 3.6 V")
                out[domain] = reg
    return p


def extract(data: bytes) -> Board:
    """The board a vendor RK3326 DTB describes, or Refused with the reason."""
    try:
        t = Tree(data)
    except (ValueError, IndexError, UnicodeDecodeError) as e:
        raise Refused(f"not a device tree ({e})") from None
    if "rockchip,rk3326" not in t.root.strings("compatible"):
        raise Refused(f"not an RK3326 tree ({t.root.strings('compatible')})")
    _, pmic = _pmic(t)
    b = Board(model=t.root.string("model") or "", panel=[], reset=Pin(0, 0))
    b.power = power(t)
    b.notes += b.power.notes
    _panel(t, b)
    _backlight(t, b)
    pads = t.find("odroidgo3-joypad")
    if not pads:
        other = [n.strings("compatible")[0] for _, n in t.walk()
                 if n.strings("compatible")[:1] and any(
                     w in n.strings("compatible")[0] for w in ("joy", "gamepad", "rockchip,key"))]
        raise Refused(f"joypad {other[0] if other else 'missing'}: only odroidgo3-joypad is known")
    _keys(t, b, pads[0][1])
    _sticks(t, b, pads[0][1])
    _sound(t, b)
    _battery(t, b)
    _leds(t, b)
    irq = pmic.cells("interrupts")
    parent = pmic.cells("interrupt-parent")
    if irq and parent:
        b.pmic_irq = t.pin([parent[0], irq[0], 0], "PMIC interrupt")
    used: dict[tuple[int, int], str] = {}
    for what, pin in _pins(b):
        if (pin.bank, pin.pin) in used and used[(pin.bank, pin.pin)] != what:
            raise Refused(f"pin gpio{pin.bank} {pin.pin} used by {used[(pin.bank, pin.pin)]} "
                          f"and {what}")
        used[(pin.bank, pin.pin)] = what
    return b


def _pins(b: Board):
    yield "panel reset", b.reset
    for what, pin in (("panel enable", b.enable), ("panel stbyb", b.stbyb),
                      ("stick mux enable", b.mux_en), ("speaker amplifier", b.amp),
                      ("PMIC interrupt", b.pmic_irq)):
        if pin:
            yield what, pin
    if b.lcd_power:
        yield "panel power", b.lcd_power[0]
    if b.hp_det:
        yield "headphone detect", b.hp_det[0]
    if b.mux:
        yield "stick mux A", b.mux[0]
        yield "stick mux B", b.mux[1]
    for k in b.keys + b.volume_keys:
        yield f"button {k.name}", k.pin
    for i, (_, pin) in enumerate(b.leds):
        yield f"led {i}", pin


# --- the DTS ----------------------------------------------------------------------------

def slug(collection: str, rel: str, limit: int = 56) -> str:
    """The lume,id of a source DTB: the collection plus its folders (or the file name when
    it is the only thing that tells the board), lowercase, without credits in brackets."""
    parts = rel.split("/")
    name = parts[-1].removesuffix(".dtb")
    folders = []
    for p in parts[:-1]:
        p = re.sub(r"\((shared|from|by) [^)]*\)|\(emmc\)|\bstock\b", "", p, flags=re.I).strip()
        if p and p.lower() not in ("boot", "files", "dtb", "consoles", "darkos"):
            folders.append(p)
    generic = re.fullmatch(r"rk3326-(r36s|evb-lp3-v12|r35s)-linux|rf\w+|rk3326-g80-1-lp3-v12-linux",
                           name)
    short = re.sub(r"^rk3326-|-linux$", "", name).lower()
    known = folders and (generic or any(short in f.lower().replace(" ", "")
                                        for f in folders))
    words = folders if known else folders + [name]
    text = " ".join(re.sub(r"\((shared|from|by) [^)]*\)", "", w, flags=re.I) for w in words)
    text = re.sub(r"rk3326-|-linux|\(emmc\)", "", text, flags=re.I)
    s = re.sub(r"[^a-z0-9.]+", "-", f"{collection} {text}".lower()).strip("-.")
    s = re.sub(r"-+", "-", s)
    return s[:limit].rstrip("-.")


def default_sources() -> dict[str, "Path"]:
    """The collections of board/r36s/dts-vendor/: the three public ones (clones in
    .cache/upstream, outside git; `lume dtb-import` requires them, so the folder is the
    same on any machine) plus the copy of a factory card in out/r36s-factory (used when
    it exists)."""
    from lume_tool.paths import REPO_ROOT, cache_dir

    up = cache_dir() / "upstream"
    return {"darkosre": up / "dArkOSRE-R36", "arkos4clone": up / "arkos4clone",
            "ee": up / "EE-Clones-DTB", "factory": REPO_ROOT / "out/r36s-factory"}


def import_collections(sources: dict[str, "Path"], out: "Path") -> list[dict]:
    """Convert every DTB of the collections into `out` (one DTS per distinct source DTB) and
    write `out/SOURCES.tsv` with what came from where, refused ones included."""
    import hashlib
    from pathlib import Path

    out.mkdir(parents=True, exist_ok=True)
    for old in list(out.glob("*.dts")) + [out / "SOURCES.tsv"]:
        old.unlink(missing_ok=True)
    rows: list[dict] = []
    by_sha: dict[str, dict] = {}
    ids: set[str] = set()
    by_board: dict[str, str] = {}
    for collection, root in sources.items():
        # the 4.4 trees before the 5.10 copies of the same board (arkos4clone has both), and
        # the shallower files first (they name a repeated board)
        for f in sorted(Path(root).rglob("*.dtb"),
                        key=lambda p: ("/5.10/" in p.as_posix(), len(p.parts), p)):
            if re.fullmatch(r"rg351\w*-uboot\.dtb", f.name):   # U-Boot's, not the kernel's
                continue
            rel = f.relative_to(root).as_posix()
            data = f.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            row = {"collection": collection, "path": rel, "sha256": sha}
            rows.append(row)
            if sha in by_sha:
                row.update(status="same", id=by_sha[sha].get("id", ""),
                           reason=f"same file as {by_sha[sha]['collection']}/"
                                  f"{by_sha[sha]['path']}")
                continue
            by_sha[sha] = row
            try:
                board = extract(data)
            except Refused as e:
                row.update(status="refused", id="", reason=str(e))
                continue
            body = to_dts(board, "-", "-", "-")
            if body in by_board:
                row.update(status="same", id=by_board[body],
                           reason=f"converts to the same tree as {by_board[body]}")
                continue
            lid = slug(collection, rel)
            if lid in ids:
                lid = f"{lid[:49]}-{sha[:6]}"
            ids.add(lid)
            by_board[body] = lid
            (out / f"{lid}.dts").write_text(to_dts(board, lid, f"{collection}/{rel}", sha))
            row.update(status="converted", id=lid, reason="; ".join(board.notes))
    lines = ["# DTBs read by `lume dtb-import` (boot-dtb-select D12): status, lume,id, "
             "collection, path, sha256, reason or notes",
             "\t".join(("status", "id", "collection", "path", "sha256", "reason"))]
    lines += ["\t".join((r["status"], r["id"], r["collection"], r["path"], r["sha256"],
                         r["reason"])) for r in rows]
    (out / "SOURCES.tsv").write_text("\n".join(lines) + "\n")
    return rows


def _q(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _node_name(text: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", text.lower()).strip("-") or "key"


def _key_nodes(keys: list[Key], indent: str) -> list[str]:
    out, names = [], set()
    for k in keys:
        name = f"button-{_node_name(k.label)}"
        while name in names:
            name += "-x"
        names.add(name)
        out += [f"{indent}{name} {{",
                f"{indent}\tgpios = {k.pin.spec()};",
                f'{indent}\tlabel = "{_q(k.label)}";',
                f"{indent}\tlinux,code = <{k.code:#x}>;",
                f"{indent}}};", ""]
    return out


def _pinlist(pins: list[str], indent: str) -> str:
    return (",\n" + indent).join(pins)


def _power_dts(p: Power) -> list[str]:
    """The supply of the source over the native RK817 and IO domains (D18).

    Voltages, names and the suspend state come from the source. The always-on and boot-on
    flags are added, never removed: a regulator the native keeps on may feed something of
    the source board that the converted tree does not attach (the vendor panel's
    backlight-supply, for one), and the kernel would switch it off as unused. A regulator
    the source does not declare loses its voltage (the kernel keeps what the bootloader
    set) and stays on."""
    L = ["&rk817 {", "\tregulators {"]
    for name in RK817_REGULATORS:
        r = p.regulators.get(name)
        L.append(f"\t\t{name} {{")
        if r is None:
            L += ["\t\t\t/delete-property/ regulator-min-microvolt;",
                  "\t\t\t/delete-property/ regulator-max-microvolt;",
                  "\t\t\t/delete-node/ regulator-state-mem;", "\t\t};"]
            continue
        L += [f"\t\t\t{flag};" for flag, on in (("regulator-always-on", r.always_on),
                                                 ("regulator-boot-on", r.boot_on)) if on]
        for prop, uv in (("regulator-min-microvolt", r.min_uv),
                         ("regulator-max-microvolt", r.max_uv)):
            L.append(f"\t\t\t{prop} = <{uv}>;" if uv is not None
                     else f"\t\t\t/delete-property/ {prop};")
        if r.name:
            L.append(f'\t\t\tregulator-name = "{_q(r.name)}";')
        if r.suspend is None:
            L.append("\t\t\t/delete-node/ regulator-state-mem;")
        else:
            on, uv = r.suspend["on"], r.suspend["uv"]
            L += ["", "\t\t\tregulator-state-mem {"]
            L.append("\t\t\t\tregulator-on-in-suspend;" if on is True
                     else "\t\t\t\t/delete-property/ regulator-on-in-suspend;")
            L.append("\t\t\t\tregulator-off-in-suspend;" if on is False
                     else "\t\t\t\t/delete-property/ regulator-off-in-suspend;")
            L.append(f"\t\t\t\tregulator-suspend-microvolt = <{uv}>;" if uv is not None
                     else "\t\t\t\t/delete-property/ regulator-suspend-microvolt;")
            L.append("\t\t\t};")
        L.append("\t\t};")
    L += ["\t};", "};", ""]
    for label, known, domains in (("io_domains", IO_DOMAINS, p.io_domains),
                                  ("pmu_io_domains", PMU_IO_DOMAINS, p.pmu_io_domains)):
        L.append(f"&{label} {{")
        for d in known:
            L.append(f"\t{d}-supply = <&{{{NATIVE_REGULATORS}/{domains[d]}}}>;" if d in domains
                     else f"\t/delete-property/ {d}-supply;")
        L += ["};", ""]
    return L


def to_dts(b: Board, lume_id: str, source: str, sha256: str) -> str:
    """The Lume DTS of a converted board (includes the native R36S V5 tree)."""
    L: list[str] = [
        "// SPDX-License-Identifier: (GPL-2.0+ OR MIT)",
        "/*",
        f" * {b.model or lume_id}, converted from a vendor RK3326 device tree by",
        " * `lume dtb import` (boot-dtb-select D12). Do not edit: import again.",
        f" * Source: {source}",
        f" * SHA-256: {sha256}",
    ]
    L += [f" * Note: {n}" for n in b.notes]
    L += [" */", "", '#include "rk3326-r36s-v5.dts"', "", "/ {",
          f'\tmodel = "{_q(b.model or lume_id)} (converted)";', "",
          "\tlume-select {", f'\t\tlume,id = "{lume_id}";', "\t\tlume,priority = <0>;",
          "\t\t/delete-property/ lume,default;",
          # the panel ID measured on the R36S V5 is not this board's (D15)
          "\t\t/delete-property/ lume,panel-id;", "\t};", ""]
    hogs: dict[int, list[str]] = {}

    def hog(name: str, pin: Pin, high: bool) -> None:
        level = "GPIO_ACTIVE_LOW" if pin.active_low else "GPIO_ACTIVE_HIGH"
        hogs.setdefault(pin.bank, []).extend([
            f"\t{name}-hog {{", "\t\tgpio-hog;", f"\t\tgpios = <{pin.macro} {level}>;",
            f"\t\t{'output-high' if high else 'output-low'};", f'\t\tline-name = "{name}";',
            "\t};", ""])

    # buttons: the native gpio-keys and volume-keys nodes are replaced
    L += ["\t/delete-node/ gpio-keys;", "\t/delete-node/ volume-keys;", "",
          "\tgpio-keys {", '\t\tcompatible = "gpio-keys";', '\t\tpinctrl-names = "default";',
          "\t\tpinctrl-0 = <&btn_pins>;", ""]
    L += _key_nodes(b.keys, "\t\t")
    L[-1:] = ["\t};", ""]
    if b.volume_keys:
        L += ["\tvolume-keys {", '\t\tcompatible = "gpio-keys";',
              '\t\tpinctrl-names = "default";', "\t\tpinctrl-0 = <&vol_pins>;",
              "\t\tautorepeat;", ""]
        L += _key_nodes(b.volume_keys, "\t\t")
        L[-1:] = ["\t};", ""]
    if b.adc_keys:
        L += ["\tadc-keys {", '\t\tcompatible = "adc-keys";',
              f"\t\tio-channels = <&saradc {b.adc_keys['channel']}>;",
              '\t\tio-channel-names = "buttons";',
              f"\t\tkeyup-threshold-microvolt = <{b.adc_keys['keyup']}>;",
              "\t\tpoll-interval = <100>;", ""]
        for name, code, thr in b.adc_keys["buttons"]:
            L += [f"\t\tbutton-{_node_name(name)} {{", f'\t\t\tlabel = "{_q(name)}";',
                  f"\t\t\tlinux,code = <{code:#x}>;",
                  f"\t\t\tpress-threshold-microvolt = <{thr[0]}>;", "\t\t};", ""]
        L[-1:] = ["\t};", ""]

    # sticks
    if b.axes == []:
        L += ["\t/delete-node/ adc-joystick;", "\t/delete-node/ adc-mux;",
              "\t/delete-node/ mux-controller;", ""]
    elif b.axes is not None:
        L += ["\t/delete-node/ adc-joystick;", ""]
        if b.mux:
            L += ["\tadc-joystick {"]
            chans = [f"<&joystick_mux {a.channel}>" for a in b.axes]
        else:
            L += ["\t/delete-node/ adc-mux;", "\t/delete-node/ mux-controller;", "",
                  "\tadc-joystick {"]
            chans = [f"<&saradc {a.channel}>" for a in b.axes]
        L += ['\t\tcompatible = "adc-joystick";',
              "\t\tio-channels = " + _pinlist(chans, "\t\t\t      ") + ";",
              "\t\tpoll-interval = <10>;", "\t\t#address-cells = <1>;", "\t\t#size-cells = <0>;",
              ""]
        for i, a in enumerate(b.axes):
            rng = "<1023 0>" if a.invert else "<0 1023>"
            L += [f"\t\taxis@{i} {{", f"\t\t\treg = <{i}>;", "\t\t\tabs-flat = <32>;",
                  "\t\t\tabs-fuzz = <32>;", f"\t\t\tabs-range = {rng};",
                  f"\t\t\tlinux,code = <{ABS_NAMES[a.code]}>;", "\t\t};", ""]
        L[-1:] = ["\t};", ""]
    if b.mux:
        L += ["\tmux-controller {", "\t\tmux-gpios = " + _pinlist(
            [b.mux[0].spec(), b.mux[1].spec()], "\t\t\t    ") + ";", "\t};", "",
              "\tadc-mux {", f"\t\tio-channels = <&saradc {b.stick_adc}>;", "\t};", ""]

    # panel power, LEDs, sound
    if b.lcd_power:
        pin, high = b.lcd_power
        L += ["\tlcd_power: regulator-lcd-power {", '\t\tcompatible = "regulator-fixed";',
              '\t\tregulator-name = "lcd_power";', f"\t\tgpio = {pin.spec()};"]
        L += ["\t\tenable-active-high;"] if high else []
        L += ["\t\tregulator-min-microvolt = <1800000>;",
              "\t\tregulator-max-microvolt = <1800000>;", "\t\tvin-supply = <&vcc_lcd>;",
              "\t};", ""]
    L += ["\t/delete-node/ gpio-leds;", ""]
    if b.leds:
        L += ["\tgpio-leds {", '\t\tcompatible = "gpio-leds";', '\t\tpinctrl-names = "default";',
              "\t\tpinctrl-0 = <&led_pins>;", ""]
        status_done = False
        for i, (color, pin) in enumerate(b.leds):
            func = "LED_FUNCTION_INDICATOR"
            if color == "blue" and not status_done:
                func, status_done = "LED_FUNCTION_STATUS", True
            L += [f"\t\tled-{i} {{"]
            if color:
                L += [f"\t\t\tcolor = <LED_COLOR_ID_{color.upper()}>;"]
            L += [f"\t\t\tfunction = {func};", f"\t\t\tgpios = {pin.spec()};", "\t\t};", ""]
        L[-1:] = ["\t};", ""]
    L += ["\trk817-sound {"]
    if b.hp_det:
        L += [f"\t\tsimple-audio-card,hp-det-gpios = {b.hp_det[0].spec()};"]
    else:
        L += ["\t\t/delete-property/ simple-audio-card,hp-det-gpios;",
              "\t\t/delete-property/ pinctrl-names;", "\t\t/delete-property/ pinctrl-0;"]
    L += ["\t};", "};", ""]

    # the panel
    vdd = "&lcd_power" if b.lcd_power else "&vcc_lcd"
    L += ["&internal_display {", '\tcompatible = "rocknix,generic-dsi";',
          "\t/delete-property/ vcc-supply;", f"\tvdd-supply = <{vdd}>;",
          f"\treset-gpios = {b.reset.spec()};"]
    if b.enable:
        L += [f"\tenable-gpios = {b.enable.spec()};"]
    L += ["\tpanel_description =", "\t\t" + ",\n\t\t".join(f'"{_q(x)}"' for x in b.panel) + ";",
          "};", "",
          # the lane rate the vendor kernel ran (the PHY transition times of the native
          # tree are the constants of that driver, so they stay)
          "&dsi {", f"\trockchip,lane-rate = <{b.lane_mbps}>;", "};", ""]
    if b.stbyb:
        hog("lcd-stbyb", b.stbyb, True)
    if b.mux_en:
        hog("joystick-mux-en", b.mux_en, True)

    # backlight
    bl = b.backlight
    levels = bl["levels"]
    L += ["&backlight {",
          f"\tpwms = <&pwm{bl['pwm']} 0 {bl['period']} {1 if bl['inverted'] else 0}>;",
          "\t/delete-property/ num-interpolated-steps;",
          "\tbrightness-levels = <" + " ".join(map(str, levels)) + ">;",
          f"\tdefault-brightness-level = <{bl['default']}>;", "};", ""]
    if bl["pwm"] != 1:
        L += ["&pwm1 {", '\tstatus = "disabled";', "};", "",
              f"&pwm{bl['pwm']} {{", '\tstatus = "okay";', "};", ""]

    # battery
    if b.battery:
        ocv = b.battery["ocv_mv"]
        pairs = [f"<{ocv[20 - i] * 1000} {100 - 5 * i}>" for i in range(21)]
        L += ["&battery {",
              f"\tcharge-full-design-microamp-hours = <{b.battery['capacity_mah'] * 1000}>;",
              f"\tvoltage-max-design-microvolt = <{ocv[20] * 1000}>;",
              f"\tvoltage-min-design-microvolt = <{ocv[0] * 1000}>;",
              "\tocv-capacity-table-0 = " + _pinlist(pairs, "\t\t\t\t") + ";", "};", ""]

    # speaker amplifier
    if b.amp:
        L += ["&spk_amp {", f"\tenable-gpios = {b.amp.spec()};", "};", ""]
    else:
        L += ["&spk_amp {", "\t/delete-property/ enable-gpios;",
              "\t/delete-property/ pinctrl-names;", "\t/delete-property/ pinctrl-0;", "};", ""]

    # PMIC interrupt
    if b.pmic_irq:
        p = b.pmic_irq
        L += ["&rk817 {", f"\tinterrupt-parent = <&gpio{p.bank}>;",
              f"\tinterrupts = <{p.macro} IRQ_TYPE_LEVEL_LOW>;", "};", ""]

    if b.power:
        L += _power_dts(b.power)

    # the hogs of the native board go; ours come in
    for bank, name in ((0, "joystick-mux-en-hog"), (1, "lcd-enable-hog"), (3, "lcd-stbyb-hog")):
        hogs.setdefault(bank, [])
        hogs[bank][:0] = [f"\t/delete-node/ {name};"]
    for bank in sorted(hogs):
        body = hogs[bank]
        if body and body[-1] == "":
            body = body[:-1]
        L += [f"&gpio{bank} {{"] + body + ["};", ""]

    # pin configuration
    L += ["&btn_pins {", "\trockchip,pins =\n\t\t" + _pinlist(
        [k.pin.pinctrl("pull_up") for k in b.keys], "\t\t") + ";", "};", ""]
    if b.volume_keys:
        L += ["&vol_pins {", "\trockchip,pins =\n\t\t" + _pinlist(
            [k.pin.pinctrl("pull_up") for k in b.volume_keys], "\t\t") + ";", "};", ""]
    if b.leds:
        L += ["&led_pins {", "\trockchip,pins =\n\t\t" + _pinlist(
            [p.pinctrl("pull_none") for _, p in b.leds], "\t\t") + ";", "};", ""]
    if b.hp_det:
        L += ["&hp_det {", f"\trockchip,pins = {b.hp_det[0].pinctrl(b.hp_det[1])};", "};", ""]
    if b.amp:
        L += ["&spk_amp_enable_h {", f"\trockchip,pins = {b.amp.pinctrl('pull_none')};", "};",
              ""]
    if b.pmic_irq:
        L += ["&pmic_int {", f"\trockchip,pins = {b.pmic_irq.pinctrl('pull_up')};", "};", ""]
    return "\n".join(L).rstrip() + "\n"
