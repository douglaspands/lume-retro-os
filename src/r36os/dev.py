"""Test the console over the USB cable: `r36os dev wait|sh|shot|keys|log` (build-speed D12).

Every command reaches the console the way `r36os push` does (root over ssh, no password on
the cable, no known-hosts key); the address is CONSOLE_ADDR of r36os.push, overridable with
`--host` (per-console subnets come later, build-speed 3.4).

- `wait`: wait until the console answers over the cable (`--timeout` seconds).
- `sh <cmd...>`: run a command as root, stream its output, pass its exit code through.
- `shot <file.png>`: screen capture of the console with the on-device `r36os-shot`.
- `keys <sequence>`: press buttons through input_event writes (syntax below).
- `log`: the boot log of the current boot.
- `check [--console ga36|r36s]`: run the on-device `selftest device` and report which console
  answered and the failed checks by name; exit 0 only if all pass.

Key sequence syntax (tokens separated by commas, spaces ignored):

    a,b,down*3,start+select,wait:500,fn+start

- a name is a button: a b x y l1 r1 l2 r2 l3 r3 up down left right select start fn
  (`mode` is the same as `fn`); the press lasts HOLD_MS and is followed by GAP_MS;
- `name*N` repeats the press N times;
- `a+b` is a chord: all buttons go down together, then up together;
- `wait:MS` (or `w:MS`) pauses MS milliseconds;
- plain buttons go to the virtual pad published by r36os-input ("GA36-MB Gamepad" or "R36S
  Gamepad", what the launcher and RetroArch read). A chord with `fn` goes to the kernel
  pad (GA36: "GA36-MB Gamepad" on the host bus, R36S: "gpio-keys"), because the daemon
  builds the hotkeys (Fn+Start...) from the physical buttons and never from its own pad.
  `k:<token>` forces the kernel pad for any token, `v:<token>` the virtual one.

The event numbers are read from /proc/bus/input/devices on each console, so nothing is
fixed per board.
"""

from __future__ import annotations

import re
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from r36os.push import CONSOLE_ADDR, Remote

HOLD_MS = 80
GAP_MS = 120

EV_SYN, EV_KEY = 0, 1
BUS_HOST, BUS_VIRTUAL = 0x19, 0x06

# Codes of linux/input-event-codes.h. The virtual pad (and the GA36 kernel pad) use BTN_*;
# the R36S kernel pad is gpio-keys, where only some buttons keep their BTN_* code.
VIRTUAL_CODES = {
    "a": 0x130, "b": 0x131, "x": 0x133, "y": 0x134, "l1": 0x136, "r1": 0x137,
    "l2": 0x138, "r2": 0x139, "select": 0x13A, "start": 0x13B, "fn": 0x13C,
    "l3": 0x13D, "r3": 0x13E, "up": 0x220, "down": 0x221, "left": 0x222, "right": 0x223,
}
# R36S gpio-keys (aports/r36os-input/r36s.conf): face buttons are BTN_EAST/SOUTH/NORTH/WEST
# and select/start/l3/r3/fn are BTN_TRIGGER_HAPPY1..5.
R36S_KERNEL_CODES = {
    **VIRTUAL_CODES,
    "a": 0x131, "b": 0x130, "x": 0x133, "y": 0x134,
    "select": 0x2C0, "start": 0x2C1, "l3": 0x2C2, "r3": 0x2C3, "fn": 0x2C4,
}
ALIASES = {"mode": "fn", "hotkey": "fn", "dpad_up": "up", "dpad_down": "down",
           "dpad_left": "left", "dpad_right": "right"}

VIRTUAL_NAMES = {"GA36-MB Gamepad": "ga36", "R36S Gamepad": "r36s"}
KERNEL_NAME = {"ga36": "GA36-MB Gamepad", "r36s": "gpio-keys"}


class DevError(RuntimeError):
    pass


# --- ssh -----------------------------------------------------------------------------

def ssh_argv(host: str, cmd: str, tty: bool = False) -> list[str]:
    """The ssh command line that runs `cmd` as root on the console."""
    base = Remote(host).base          # the options of `r36os push`, host last
    return [*base[:-1], *(["-tt"] if tty else []), base[-1], cmd]


def run_capture(host: str, cmd: str) -> str:
    r = subprocess.run(ssh_argv(host, cmd), stdin=subprocess.DEVNULL, capture_output=True)
    if r.returncode != 0:
        err = r.stderr.decode(errors="replace").strip()
        if r.returncode == 255:
            raise DevError(f"ssh to the console failed: {err or 'no answer'}")
        raise DevError(f"on the console, `{cmd}` failed ({r.returncode}): {err}")
    return r.stdout.decode(errors="replace")


# --- wait / sh / log -------------------------------------------------------------------

def wait_for_console(host: str, timeout: float, interval: float = 2.0,
                     sleep=time.sleep, now=time.monotonic, probe=None) -> bool:
    """True when the console answers over the cable before `timeout` seconds."""
    probe = probe or (lambda: subprocess.run(
        ssh_argv(host, "true"), stdin=subprocess.DEVNULL,
        capture_output=True).returncode == 0)
    end = now() + timeout
    while True:
        if probe():
            return True
        if now() >= end:
            return False
        sleep(interval)


def boot_log_command() -> str:
    """Remote command that prints the log of the current boot: the RAM copy, else the one
    on the card (ROMS/logs/boot/boot-<n>.log, docs/LOGS.md), else the kernel buffer; then
    the events of that boot from events.log (`boot OK completed: ...` is only there)."""
    return ("n=$(cat /run/r36os/logs/boot-n 2>/dev/null); shown=; "
            'for f in "/run/r36os/logs/boot/boot-$n.log" "/storage/logs/boot/boot-$n.log"; do '
            'if [ -n "$n" ] && [ -f "$f" ]; then cat "$f"; shown=1; break; fi; done; '
            '[ -n "$shown" ] || dmesg; '
            'echo; echo "== events (boot $n)"; '
            "awk -v n=\"$n\" '$2 == n' /storage/logs/events.log 2>/dev/null")


# --- input devices ---------------------------------------------------------------------

@dataclass
class InputDevice:
    name: str
    bus: int
    event: int | None


def parse_input_devices(text: str) -> list[InputDevice]:
    """Devices of /proc/bus/input/devices with their bus and event number."""
    out = []
    for block in re.split(r"\n\s*\n", text.strip()):
        name = re.search(r'^N: Name="(.*)"', block, re.M)
        bus = re.search(r"^I: Bus=([0-9a-fA-F]+)", block, re.M)
        ev = re.search(r"\bevent(\d+)\b", block)
        if name and bus:
            out.append(InputDevice(name.group(1), int(bus.group(1), 16),
                                   int(ev.group(1)) if ev else None))
    return out


@dataclass
class Pads:
    board: str          # "ga36" or "r36s"
    virtual: int        # event number of the pad published by r36os-input
    kernel: int | None  # event number of the kernel pad (None when absent)


def find_pads(devices: list[InputDevice]) -> Pads:
    """The virtual and kernel pads of the console, by name and bus."""
    for d in devices:
        board = VIRTUAL_NAMES.get(d.name)
        if board and d.bus == BUS_VIRTUAL and d.event is not None:
            kernel = next((k.event for k in devices
                           if k.name == KERNEL_NAME[board] and k.bus != BUS_VIRTUAL
                           and k.event is not None), None)
            return Pads(board, d.event, kernel)
    raise DevError("no virtual gamepad on the console (is r36os-input running?)")


# --- key sequences ---------------------------------------------------------------------

@dataclass(frozen=True)
class Step:
    buttons: tuple[str, ...] = ()   # empty for a wait
    pad: str = "virtual"            # "virtual" or "kernel"
    wait_ms: int = 0


def parse_sequence(seq: str) -> list[Step]:
    """`a,b,down*3,start+select,wait:500,fn+start` -> steps (repeats expanded)."""
    steps: list[Step] = []
    for raw in seq.split(","):
        tok = raw.strip().lower()
        if not tok:
            continue
        m = re.fullmatch(r"(?:wait|w):(\d+)", tok)
        if m:
            steps.append(Step(wait_ms=int(m.group(1))))
            continue
        force = None
        if tok[:2] in ("k:", "v:"):
            force = "kernel" if tok[0] == "k" else "virtual"
            tok = tok[2:]
        count = 1
        if "*" in tok:
            tok, _, n = tok.partition("*")
            if not n.isdigit() or int(n) < 1:
                raise DevError(f"bad repeat in `{raw.strip()}`")
            count = int(n)
        names = tuple(ALIASES.get(n.strip(), n.strip()) for n in tok.split("+"))
        for n in names:
            if n not in VIRTUAL_CODES:
                raise DevError(f"unknown button `{n}` (known: {' '.join(VIRTUAL_CODES)})")
        pad = force or ("kernel" if len(names) > 1 and "fn" in names else "virtual")
        steps.extend([Step(names, pad)] * count)
    if not steps:
        raise DevError("empty key sequence")
    return steps


def input_event(etype: int, code: int, value: int, wordsize: int) -> bytes:
    """One struct input_event: the timestamp is left zero (the kernel stamps it)."""
    if wordsize == 8:
        return struct.pack("<qqHHi", 0, 0, etype, code, value)
    return struct.pack("<iiHHi", 0, 0, etype, code, value)


def _printf(data: bytes) -> str:
    return "".join(f"\\{b:03o}" for b in data)


def key_events(codes: list[int], value: int, wordsize: int) -> bytes:
    """The key events of one press or release followed by one SYN_REPORT."""
    data = b"".join(input_event(EV_KEY, c, value, wordsize) for c in codes)
    return data + input_event(EV_SYN, 0, 0, wordsize)


def _sleep_cmd(ms: int) -> str:
    return f"sleep {ms // 1000}.{ms % 1000:03d}"


def build_script(steps: list[Step], pads: Pads, machine: str,
                 hold_ms: int = HOLD_MS, gap_ms: int = GAP_MS) -> str:
    """Shell script (one line per command) that plays `steps` on the console."""
    wordsize = 8 if machine in ("aarch64", "x86_64") else 4
    lines = []
    for s in steps:
        if not s.buttons:
            lines.append(_sleep_cmd(s.wait_ms))
            continue
        if s.pad == "kernel":
            if pads.kernel is None:
                raise DevError("no kernel gamepad found for a chord with the hotkey")
            event, table = pads.kernel, (R36S_KERNEL_CODES if pads.board == "r36s"
                                         else VIRTUAL_CODES)
        else:
            event, table = pads.virtual, VIRTUAL_CODES
        codes = [table[b] for b in s.buttons]
        dev = f"/dev/input/event{event}"
        lines.append(f"printf '{_printf(key_events(codes, 1, wordsize))}' > {dev}")
        lines.append(_sleep_cmd(hold_ms))
        lines.append(f"printf '{_printf(key_events(codes, 0, wordsize))}' > {dev}")
        lines.append(_sleep_cmd(gap_ms))
    return "\n".join(lines) + "\n"


# --- commands --------------------------------------------------------------------------

def cmd_wait(host: str, timeout: float) -> int:
    print(f"waiting for {host} (up to {timeout:g}s)...", file=sys.stderr)
    if wait_for_console(host, timeout):
        print("console answers")
        return 0
    print(f"error: no answer from {host} after {timeout:g}s", file=sys.stderr)
    return 1


def cmd_sh(host: str, command: list[str]) -> int:
    if not command:
        print("error: give a command", file=sys.stderr)
        return 2
    return subprocess.call(ssh_argv(host, " ".join(command)), stdin=subprocess.DEVNULL)


def cmd_shot(host: str, out: Path) -> int:
    remote = "/tmp/r36os-shot.png"
    run_capture(host, f"r36os-shot {remote}")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("wb") as f:
        r = subprocess.run(ssh_argv(host, f"cat {remote}; rm -f {remote}"),
                           stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.PIPE)
    if r.returncode != 0 or out.stat().st_size == 0:
        raise DevError(f"could not read the capture: {r.stderr.decode(errors='replace')}")
    if out.read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
        raise DevError(f"{out} is not a PNG")
    print(out)
    return 0


def cmd_keys(host: str, sequence: str, hold_ms: int, gap_ms: int) -> int:
    steps = parse_sequence(sequence)
    info = run_capture(host, "uname -m; cat /proc/bus/input/devices")
    machine, _, devices = info.partition("\n")
    pads = find_pads(parse_input_devices(devices))
    run_capture(host, build_script(steps, pads, machine.strip(), hold_ms, gap_ms))
    return 0


def cmd_log(host: str) -> int:
    sys.stdout.write(run_capture(host, boot_log_command()))
    return 0


SELFTEST_COMMAND = "/usr/libexec/r36os/selftest device"
CONSOLES = ("ga36", "r36s")


@dataclass
class SelftestResult:
    board: str | None = None
    passed: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)   # (check, detail)
    done: bool = False          # the SELFTEST-DONE line arrived
    error: str | None = None    # a SELFTEST-ERROR line (device mode refused)

    @property
    def ok(self) -> bool:
        return self.done and self.error is None and not self.failed


def parse_selftest(text: str) -> SelftestResult:
    """Parse the output of `selftest device`: `SELFTEST <name> PASS|FAIL [detail]` lines and
    the closing `SELFTEST-DONE board=<b> pass=<n> fail=<n>`."""
    res = SelftestResult()
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("SELFTEST-ERROR"):
            res.error = line[len("SELFTEST-ERROR"):].strip() or "refused"
        elif line.startswith("SELFTEST-DONE"):
            fields = dict(re.findall(r"(\w+)=(\S+)", line))
            res.board = fields.get("board")
            res.done = True
        else:
            m = re.fullmatch(r"SELFTEST (\S+) (PASS|FAIL)(?: (.*))?", line)
            if not m:
                continue
            if m.group(2) == "PASS":
                res.passed += 1
            else:
                res.failed.append((m.group(1), m.group(3) or ""))
    return res


def cmd_check(host: str, console: str | None) -> int:
    """Run the self-test in device mode over the cable; exit 0 only if every check passed."""
    r = subprocess.run(ssh_argv(host, SELFTEST_COMMAND), stdin=subprocess.DEVNULL,
                       capture_output=True)
    out = r.stdout.decode(errors="replace")
    res = parse_selftest(out)
    if r.returncode == 255:
        raise DevError(f"ssh to the console failed: "
                       f"{r.stderr.decode(errors='replace').strip() or 'no answer'}")
    if res.error:
        raise DevError(f"self-test refused: {res.error}")
    if not res.done:
        err = r.stderr.decode(errors="replace").strip()
        raise DevError(f"the self-test did not finish (exit {r.returncode}): "
                       f"{err or out.strip()[-200:] or 'no output'}")
    name = res.board or "unknown"
    if console and name != console:
        print(f"error: the console on the cable is the {name.upper()}, not the "
              f"{console.upper()}", file=sys.stderr)
        return 1
    total = res.passed + len(res.failed)
    if res.ok and r.returncode == 0:
        print(f"{name.upper()}: self-test PASS ({total} checks)")
        return 0
    print(f"{name.upper()}: self-test FAIL ({len(res.failed)} of {total} checks failed)")
    for check, detail in res.failed:
        print(f"  FAIL {check}" + (f": {detail}" if detail else ""))
    return 1


def main_dev(args) -> int:
    host = args.host or CONSOLE_ADDR
    try:
        if args.dev_command == "wait":
            return cmd_wait(host, args.timeout)
        if args.dev_command == "sh":
            return cmd_sh(host, args.cmd)
        if args.dev_command == "shot":
            return cmd_shot(host, args.file)
        if args.dev_command == "keys":
            return cmd_keys(host, args.sequence, args.hold, args.gap)
        if args.dev_command == "log":
            return cmd_log(host)
        if args.dev_command == "check":
            return cmd_check(host, args.console)
    except DevError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 2
