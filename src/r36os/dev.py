"""Test the console over the USB cable: `r36os dev wait|sh|shot|keys|log` (build-speed D12).

Every command reaches the console the way `r36os push` does (root over ssh, no password on
the cable, no known-hosts key); the address is CONSOLE_ADDR of r36os.push, overridable with
`--host`. One card moves between the GA36 and the R36S and both answer at that address, so
every action but `wait` first says which console answered and, with `--console ga36|r36s|vm`,
refuses before running anything when the cable has the other one (build-speed 3.4).

- `wait`: wait until the console answers over the cable (`--timeout` seconds).
- `sh <cmd...>`: run a command as root, stream its output, pass its exit code through.
- `shot <file.png>`: screen capture of the console with the on-device `r36os-shot`.
  `shot --compare <screen>` / `--update <screen>`: reference captures (r36os.shots).
- `keys <sequence>`: press buttons through input_event writes (syntax below).
- `log`: the boot log of the current boot.
- `check [--console ga36|r36s]`: run the on-device `selftest device` and report which console
  answered and the failed checks by name; exit 0 only if all pass.
- `replay record|stop|play <slot>`: RetroArch's own replay (virtual-gamepad D3) through its
  network command (`nc -u` to 127.0.0.1:55355 on the console): RECORD_REPLAY, HALT_REPLAY,
  PLAY_REPLAY_SLOT <slot>. A GET_STATUS before (no game = error) and after (still PLAYING);
  UDP gives no ack, so the sent command itself is unconfirmed. Only the core is printed
  (the reply is cut before the game name on the console).
- `record` / `record --stop`: start / stop the on-device `r36os-evrec record` (detached, to
  /run/r36os/evrec/current.evrec). `--stop` brings the recording to cache/recordings/
  `<console>-<YYYYmmdd-HHMMSS>.evrec`, deletes the remote copy; an empty recording is an error.
- `play <file.evrec>`: send the recording and run `r36os-evrec play`, which prints
  `delay max=<ms> mean=<ms> events=<n>`; a recording of the other console is refused before
  anything is sent.

- `run <script>`: run a device test script (r36os.dev_run, r36os.scripts): one line
  `passo <n> <name>: ok|FALHOU (<reason>)` per step, stops at the first failure, refuses a
  console the script does not list before any button, reads events.log only from the start
  of the run and cuts every line at `content=` on the console (no game name ever leaves it).

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

from r36os.push import (CONSOLE_ADDR, PushError, Remote, console_refusal,
                        identify_console)

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
# vm (aports/r36os-input/vm.conf, `passthrough`): the daemon publishes the QEMU keyboard keys
# unchanged as "Lume VM Keyboard", so the buttons are keyboard keys: Fn = F1 and Start = Enter
# come from vm.conf (`fn`, `quit`), Select = right Shift and the face/shoulder keys are the
# RetroArch defaults the vm keeps (retroarch-lume.cfg: hotkey rshift). No l2/r2/l3/r3 key.
VM_CODES = {
    "a": 45, "b": 44, "x": 31, "y": 30, "l1": 16, "r1": 17,       # x, z, s, a, q, w
    "select": 54, "start": 28, "fn": 59,                          # rshift, enter, f1
    "up": 103, "down": 108, "left": 105, "right": 106,
}
# The kernel side of the vm is the grabbed QEMU keyboard, the SOURCE of the daemon: it builds
# the Fn chords (fn+start -> "quit") from the keys it reads there, so they must go to that
# node. The source keys are the published ones (vm.conf has no `key` mapping).
VM_SOURCE_CODES = VM_CODES
BOARD_CODES = {"ga36": VIRTUAL_CODES, "r36s": VIRTUAL_CODES, "vm": VM_CODES}
BOARD_KERNEL_CODES = {"ga36": VIRTUAL_CODES, "r36s": R36S_KERNEL_CODES, "vm": VM_SOURCE_CODES}
ALIASES = {"mode": "fn", "hotkey": "fn", "dpad_up": "up", "dpad_down": "down",
           "dpad_left": "left", "dpad_right": "right"}

VIRTUAL_NAMES = {"GA36-MB Gamepad": "ga36", "R36S Gamepad": "r36s", "Lume VM Keyboard": "vm"}
KERNEL_NAME = {"ga36": "GA36-MB Gamepad", "r36s": "gpio-keys",
               "vm": "AT Translated Set 2 keyboard"}


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
    if probe is None:
        from r36os.push import Remote
        probe = Remote(host).answers  # bounded: a probe caught by a reboot cannot hang
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
    board: str          # "ga36", "r36s" or "vm"
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
            event, table = pads.kernel, BOARD_KERNEL_CODES[pads.board]
        else:
            event, table = pads.virtual, BOARD_CODES[pads.board]
        missing = [b for b in s.buttons if b not in table]
        if missing:
            raise DevError(f"the {pads.board.upper()} has no `{missing[0]}` button "
                           f"(known: {' '.join(table)})")
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


REPO_ROOT = Path(__file__).resolve().parents[2]
SHOTS_DIR = REPO_ROOT / "tests" / "device" / "shots"
DIFF_DIR = REPO_ROOT / "cache" / "shots"


def cmd_shot_screen(host: str, screen: str, update: bool, shots_dir: Path = SHOTS_DIR,
                    diff_dir: Path = DIFF_DIR) -> int:
    """`shot --compare|--update <screen>`: press the screen's keys, capture, compare/store."""
    from r36os import shots
    try:
        screens = shots.load_screens(shots_dir)
        if screen not in screens:
            raise shots.ShotError(f"unknown screen `{screen}` (known: {' '.join(screens)})")
        board = shots.board_from_machine(run_capture(host, "uname -m"))
        keys = screens[screen]
        if keys.strip():
            cmd_keys(host, keys, HOLD_MS, GAP_MS)
            time.sleep(1.0)
        tmp = REPO_ROOT / "cache" / "tmp" / f"shot-{screen}.png"
        cmd_shot(host, tmp)
        current = tmp.read_bytes()
        ref = shots.reference_path(shots_dir, board, screen)
        if update:
            ref.parent.mkdir(parents=True, exist_ok=True)
            ref.write_bytes(current)
            print(f"reference updated: {ref}")
            return 0
        result = shots.compare_screen(ref, current, diff_dir / f"{board}-{screen}-diff.png")
    except shots.ShotError as e:
        raise DevError(str(e))
    pct = result.ratio * 100
    if result.ok:
        print(f"{board}/{screen}: ok ({result.differing} of {result.total} pixels differ, "
              f"{pct:.3f}%)")
        return 0
    print(f"{board}/{screen}: FAILED ({result.differing} of {result.total} pixels differ, "
          f"{pct:.3f}%); diff image: {diff_dir / f'{board}-{screen}-diff.png'}",
          file=sys.stderr)
    return 1


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
CONSOLES = ("ga36", "r36s", "vm")


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


RA_NC = "nc -u -w1 127.0.0.1 55355"


def status_command() -> str:
    """Remote command: RetroArch GET_STATUS, cut after the core field so the game name
    (the content) never crosses the cable."""
    return f"printf GET_STATUS | {RA_NC} 2>/dev/null | cut -d, -f1; true"


def send_command(cmd: str) -> str:
    """Remote command: send one RetroArch network command (UDP, no reply expected)."""
    return f"printf '%s' '{cmd}' | {RA_NC} >/dev/null 2>&1; true"


def parse_status(text: str) -> str | None:
    """The core of a PLAYING/PAUSED `GET_STATUS` reply (already cut after the core field),
    else None (no game: CONTENTLESS, no answer)."""
    parts = text.strip().split(None, 2)
    if len(parts) >= 3 and parts[0] == "GET_STATUS" and parts[1] in ("PLAYING", "PAUSED"):
        return parts[2].strip() or "unknown"
    return None


def cmd_replay(host: str, action: str, slot: int | None = None, run=None,
               settle=time.sleep) -> int:
    """`replay record|stop|play <slot>`: RetroArch's own replay (input recording with a
    savestate, exact repetition) through its network command. UDP has no ack, so a
    GET_STATUS first (no game = error) and another after (game still PLAYING). Only the
    core is ever printed, never the game name."""
    run = run or (lambda c: run_capture(host, c))
    wire = {"record": "RECORD_REPLAY", "stop": "HALT_REPLAY"}.get(action)
    if action == "play":
        if slot is None or slot < 0:
            raise DevError("play needs a replay slot number (0 or more)")
        wire = f"PLAY_REPLAY_SLOT {slot}"
    if wire is None:
        raise DevError(f"unknown replay action `{action}`")
    core = parse_status(run(status_command()))
    if core is None:
        raise DevError("no RetroArch game is running (GET_STATUS has no PLAYING answer)")
    run(send_command(wire))
    settle(1.0)
    after = parse_status(run(status_command()))
    if after is None:
        raise DevError(f"sent {wire}, but RetroArch no longer reports a running game")
    what = {"record": "recording to the current replay slot", "stop": "replay halted",
            "play": f"playing replay slot {slot}"}[action]
    print(f"{core}: playing; {wire} sent ({what}); game still PLAYING "
          "(UDP gives no ack: confirm on screen/capture)")
    return 0


# --- record / play (virtual-gamepad D3) ----------------------------------------------------

EVREC_DIR = "/run/r36os/evrec"
EVREC_CURRENT = f"{EVREC_DIR}/current.evrec"
EVREC_PID = f"{EVREC_DIR}/record.pid"
EVREC_PLAY = f"{EVREC_DIR}/play.evrec"
RECORDINGS_DIR = REPO_ROOT / "cache" / "recordings"


def record_start_command() -> str:
    """Remote script: start `r36os-evrec record` detached; print `recording` or `busy`."""
    return (f"mkdir -p {EVREC_DIR}; "
            f"if [ -s {EVREC_PID} ] && kill -0 $(cat {EVREC_PID}) 2>/dev/null; "
            "then echo busy; exit 0; fi; "
            f"rm -f {EVREC_CURRENT}; "
            f"nohup r36os-evrec record {EVREC_CURRENT} >/dev/null 2>&1 </dev/null & "
            f"echo $! > {EVREC_PID}; sleep 0.3; "
            f"if kill -0 $(cat {EVREC_PID}) 2>/dev/null; then echo recording; "
            "else echo failed; fi")


def record_stop_command() -> str:
    """Remote script: SIGTERM the recorder and wait (at most 5 s) for it to write `# end`;
    print `none` (nothing recording), `stopped` or `timeout`."""
    return (f"pid=$(cat {EVREC_PID} 2>/dev/null); "
            "if [ -z \"$pid\" ]; then echo none; exit 0; fi; "
            "kill -TERM $pid 2>/dev/null; n=0; "
            "while kill -0 $pid 2>/dev/null && [ $n -lt 50 ]; do sleep 0.1; n=$((n+1)); done; "
            f"rm -f {EVREC_PID}; "
            "if kill -0 $pid 2>/dev/null; then echo timeout; else echo stopped; fi")


def record_fetch_command() -> str:
    return f"cat {EVREC_CURRENT}"


def record_clean_command() -> str:
    return f"rm -f {EVREC_CURRENT}"


def play_upload_command() -> str:
    return f"mkdir -p {EVREC_DIR} && cat > {EVREC_PLAY}"


def play_command() -> str:
    return f"r36os-evrec play {EVREC_PLAY}"


def play_clean_command() -> str:
    return f"rm -f {EVREC_PLAY}"


def cmd_record(host: str, console: str, stop: bool, run=None,
               recordings_dir: Path | None = None, now=time.localtime) -> int:
    """`record` starts the on-device recorder; `record --stop` stops it, brings the
    recording to cache/recordings/ and deletes the remote copy. A recording without a
    single event is an error and is not saved."""
    from r36os import evrec

    run = run or (lambda c: run_capture(host, c))
    if not stop:
        answer = run(record_start_command()).strip()
        if answer == "busy":
            raise DevError("a recording is already running on the console "
                           "(`r36os dev record --stop` ends it)")
        if answer != "recording":
            raise DevError("the recorder did not start (is r36os-evrec installed and "
                           "is this the right image?)")
        print(f"recording on the {console.upper()}: press buttons, then "
              "`r36os dev record --stop`")
        return 0
    answer = run(record_stop_command()).strip()
    if answer == "none":
        raise DevError("no recording is running on the console")
    if answer == "timeout":
        run(record_clean_command())
        raise DevError("the recorder did not stop within 5 s")
    try:
        rec = evrec.parse(run(record_fetch_command()), expect_console=console)
    except evrec.EvrecError as e:
        raise DevError(f"the recording from the console is not valid: {e}") from None
    finally:
        run(record_clean_command())
    if not rec.events:
        raise DevError("the recording is empty (no button event was captured); not saved")
    out_dir = recordings_dir or RECORDINGS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{console}-{time.strftime('%Y%m%d-%H%M%S', now())}.evrec"
    evrec.write(path, rec)
    print(f"saved {path} ({len(rec.events)} events, {rec.end_ms} ms)")
    return 0


def _ssh_send(host: str):
    def send(cmd: str, data: bytes | None = None) -> tuple[int, str]:
        r = subprocess.run(ssh_argv(host, cmd), input=data if data is not None else b"",
                           capture_output=True)
        if r.returncode == 255:
            raise DevError(f"ssh to the console failed: "
                           f"{r.stderr.decode(errors='replace').strip() or 'no answer'}")
        return r.returncode, (r.stdout + r.stderr).decode(errors="replace")
    return send


def cmd_play(host: str, console: str, file: Path, send=None) -> int:
    """`play <file>`: send a recording to the console and play it with `r36os-evrec play`,
    printing the measured delay line. A recording of the other console is refused before
    anything is sent; a failing player (refusal, no permission) fails the command."""
    from r36os import evrec

    send = send or _ssh_send(host)
    try:
        rec = evrec.read(file, expect_console=console)
    except (evrec.EvrecError, OSError, UnicodeDecodeError) as e:
        raise DevError(f"cannot play {file}: {e}") from None
    if not rec.events:
        raise DevError(f"{file} has no events")
    try:
        rc, out = send(play_upload_command(), evrec.dumps(rec).encode("ascii"))
        if rc != 0:
            raise DevError(f"could not send the recording to the console: {out.strip()}")
        rc, out = send(play_command())
    finally:
        send(play_clean_command())
    out = out.strip()
    if out:
        print(out)
    if rc != 0:
        raise DevError(f"r36os-evrec play failed ({rc})")
    return 0


def vm_machine(identify_output: str) -> bool:
    """True when the identify probe describes the vm image (board `vm`, or x86_64 with no
    console board): `push` still treats the vm as no console, `dev` has the `vm` console."""
    lines = identify_output.splitlines() + ["", ""]
    return lines[0].strip() == "vm" or (lines[0].strip() in ("", "-")
                                        and lines[1].strip() == "x86_64")


def which_console(host: str, wanted: str | None) -> str:
    """Say which console answered on the cable (stderr) and refuse, before anything runs,
    when `--console` names the other one (build-speed 3.4, push.console_refusal)."""
    seen: list[str] = []

    def probe(cmd: str) -> str:
        seen.append(run_capture(host, cmd))
        return seen[-1]

    name = identify_console(probe)
    if not name and seen and vm_machine(seen[-1]):
        name = "vm"
    print(f"console: {name.upper() or 'unknown'} ({host})", file=sys.stderr)
    if reason := console_refusal(name, wanted):
        raise DevError(reason)
    return name


def main_dev(args) -> int:
    host = args.host or CONSOLE_ADDR
    try:
        if args.dev_command == "wait":
            return cmd_wait(host, args.timeout)
        if args.dev_command == "run":      # identifies the console itself, after loading
            from r36os.dev_run import cmd_run

            return cmd_run(host, args.script, args.console)
        console_name = which_console(host, getattr(args, "console", None))  # not wait: may be off
        if args.dev_command == "record":
            return cmd_record(host, console_name, args.stop)
        if args.dev_command == "play":
            return cmd_play(host, console_name, args.file)
        if args.dev_command == "sh":
            return cmd_sh(host, args.cmd)
        if args.dev_command == "shot":
            screen = args.compare or args.update
            if screen:
                if args.compare and args.update:
                    raise DevError("use --compare or --update, not both")
                return cmd_shot_screen(host, screen, update=bool(args.update))
            if args.file is None:
                raise DevError("give a file, or --compare/--update <screen>")
            return cmd_shot(host, args.file)
        if args.dev_command == "keys":
            return cmd_keys(host, args.sequence, args.hold, args.gap)
        if args.dev_command == "log":
            return cmd_log(host)
        if args.dev_command == "check":
            return cmd_check(host, args.console)
        if args.dev_command == "replay":
            return cmd_replay(host, args.action, args.slot)
        if args.dev_command == "watch":
            from r36os.dev_watch import cmd_watch

            return cmd_watch(args.fragment, args.host)
    except PushError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except DevError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 2
