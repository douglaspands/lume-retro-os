"""`r36os dev run <script>`: run a device test script over the cable (virtual-gamepad D4).

The script format is frozen in r36os.scripts. Steps run in order, each with its own timeout;
one line per step on stdout, in this exact (user-facing, Portuguese) form:

    passo <n> <name>: ok
    passo <n> <name>: FALHOU (<reason>)

The run stops at the first failed step (the later ones depend on the earlier) and the exit
code is 0 only if every step passed. The console on the cable is identified and checked
against the script's `consoles` BEFORE the first step, so no button reaches the wrong one.

Step types:
- keys: `dev keys` (cmd_keys); fails on a console error or when it overran its timeout.
- play: replays a `.evrec` (node 2.2 `dev play`); handler hook `ctx.play`.
- wait_event: polls events.log (past the start offset) plus the RAM events.pending (every
  ~1 s, deduplicated by cut line) for a line written after the run
  started, matching `pattern` (regex, search) and `category` (3rd field) if given.
- wait_process: polls `pidof` until the process is present/absent.
- shot: `dev shot --compare <screen>` (reference capture within tolerance).
- sh: command as root; passes on exit 0 (its output is not printed).
- open_game / close_game: hooks `ctx.open_game` / `ctx.close_game` (r36os.dev_game: the
  button sequence), then wait for the lume-run lines within the step timeout: open = `game OK <system> ...
  start` (fails fast on `game FAIL <system> ... start-failed`), close = `game OK|FAIL
  <system> ... end=` (either means the game ended).

Privacy: a game name only exists in events.log after `content=`. The filter that cuts every
line at ` content=` runs ON THE CONSOLE (awk), and again locally as a second guard, so the
name never crosses the cable nor reaches any output of this tool. Matching sees only the cut
line, and no line is ever printed (a failure reason names the pattern, never a log line).
"""
from __future__ import annotations

import contextlib
import io
import re
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from r36os import dev, dev_game, scripts

EVENTS_LOG = "/storage/logs/events.log"
POLL_S = 1.0
COUNT_MARK = "@@count "
GAME_CATEGORY = "game"
EVENTS_PENDING = "/run/lume/logs/events.pending"


# lume-run lines (lume/lume-run/src/events.rs), after the PC-side cut at ` content=`:
#   <time> <boot> game OK <system> <runner> <core> start
#   <time> <boot> game OK|FAIL <system> <runner> <core> exit=<..> end=<..> secs=<n>
#   <time> <boot> game FAIL <system> <runner> <core> start-failed ...
def opened_pattern(system: str) -> str:
    return rf"\bOK {re.escape(system)} .*\bstart$"


def start_failed_pattern(system: str) -> str:
    return rf"\bFAIL {re.escape(system)} .*\bstart-failed\b"


def closed_pattern(system: str | None) -> str:
    sysre = re.escape(system) if system else r"\S+"
    return rf"\b(OK|FAIL) {sysre} .*\bend="


class StepFailed(Exception):
    """A step did not pass; the message is the reason printed in `FALHOU (...)`."""


def cut_content(line: str) -> str:
    """Drop `content=...` (and the space before it) from an events.log line."""
    return re.sub(r"\s*content=.*", "", line)


def events_command(skip: int) -> str:
    """Remote command: the events.log lines after the first `skip`, cut at ` content=` on the
    console, then a closing `@@count <total lines>` marker."""
    return (f"awk -v s={int(skip)} 'NR > s {{ sub(/ ?content=.*/, \"\"); print }} "
            f"END {{ print \"{COUNT_MARK}\" NR }}' {EVENTS_LOG} 2>/dev/null")


def pending_command() -> str:
    """Remote command: the RAM events.pending lines (not yet drained to the card log), cut at
    ` content=` on the console. The file may be absent or shrink between polls."""
    return f"awk '{{ sub(/ ?content=.*/, \"\"); print }}' {EVENTS_PENDING} 2>/dev/null"


def count_command() -> str:
    return f"wc -l < {EVENTS_LOG} 2>/dev/null || echo 0"


def process_command(name: str) -> str:
    return f"pidof {shlex.quote(name)} >/dev/null 2>&1 && echo present || echo absent"


@dataclass
class Context:
    """Everything a step handler needs; every console action is injectable for the tests."""
    host: str
    run: object = None            # run(cmd) -> stdout, raises DevError on failure
    sleep: object = time.sleep
    now: object = time.monotonic
    keys: object = None           # keys(sequence)
    sh: object = None             # sh(command, timeout) -> exit code
    shot: object = None           # shot(screen) -> (ok, detail)
    play: object = None           # play(recording)
    open_game: object = None      # open_game(system, position)   (node 3.2)
    close_game: object = None     # close_game()                  (node 3.2)
    console: str | None = None    # ga36 | r36s, the console that answered (for play)
    start_lines: int = 0          # events.log line count when the run started
    seen: int = field(default=0)  # lines already read by wait_event
    seen_lines: set = field(default_factory=set)   # cut lines already processed or baseline
    last_system: str | None = None   # system of the last open_game (close_game matches it)
    game_end: str | None = None      # OK | FAIL of the last close_game

    def __post_init__(self):
        host = self.host
        self.run = self.run or (lambda c: dev.run_capture(host, c))
        self.keys = self.keys or (
            lambda seq: dev.cmd_keys(host, seq, dev.HOLD_MS, dev.GAP_MS))
        self.sh = self.sh or self._default_sh
        self.shot = self.shot or self._default_shot
        self.play = self.play or self._default_play
        games = dev_game.GameDriver(self.run, lambda seq: self.keys(seq))
        self.open_game = self.open_game or games.open
        self.close_game = self.close_game or games.close
        self.seen = self.start_lines

    def _default_sh(self, command: str, timeout: float) -> int:
        try:
            r = subprocess.run(dev.ssh_argv(self.host, command), stdin=subprocess.DEVNULL,
                               capture_output=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise StepFailed(f"timeout after {timeout:g}s") from None
        return r.returncode

    def _default_shot(self, screen: str):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = dev.cmd_shot_screen(self.host, screen, update=False)
        return rc == 0, (err.getvalue() or out.getvalue()).strip()

    def _default_play(self, recording: str):
        # `dev play` (node 2.2): it refuses a recording of the other console before sending
        console = self.console or dev.which_console(self.host, None)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            try:
                rc = dev.cmd_play(self.host, console, dev.REPO_ROOT / recording)
            except dev.DevError as e:
                raise StepFailed(str(e)) from None
        if rc != 0:
            raise StepFailed((err.getvalue() or out.getvalue()).strip() or f"exit {rc}")


# --- step handlers -----------------------------------------------------------------------

def _deadline(ctx: Context, step) -> float:
    return ctx.now() + step.timeout


def do_keys(ctx: Context, step) -> None:
    start = ctx.now()
    try:
        ctx.keys(step.fields["sequence"])
    except dev.DevError as e:
        raise StepFailed(str(e)) from None
    if ctx.now() - start > step.timeout:
        raise StepFailed(f"timeout after {step.timeout:g}s")


def do_play(ctx: Context, step) -> None:
    start = ctx.now()
    try:
        ctx.play(step.fields["recording"])
    except dev.DevError as e:
        raise StepFailed(str(e)) from None
    if ctx.now() - start > step.timeout:
        raise StepFailed(f"timeout after {step.timeout:g}s")


def read_pending(ctx: Context) -> list[str]:
    """The current RAM events.pending lines, each cut at `content=` on the console."""
    out = ctx.run(pending_command())
    return [ln for ln in (cut_content(x) for x in out.splitlines()) if ln.strip()]


def read_new_events(ctx: Context) -> list[str]:
    """The events not seen yet: events.log lines past the start offset plus the current
    events.pending, each cut at `content=`. A line already processed (or present in
    events.pending when the run started) is never returned again: it is deduplicated by its
    full cut line, which carries a timestamp and the boot number."""
    out = ctx.run(events_command(ctx.seen))
    lines = [cut_content(ln) for ln in out.splitlines()]
    if lines and lines[-1].startswith(COUNT_MARK):
        try:
            total = int(lines.pop().removeprefix(COUNT_MARK))
        except ValueError:
            total = ctx.seen
        ctx.seen = total if total >= ctx.seen else 0     # the log rotated: start over
    fresh = []
    for ln in lines + read_pending(ctx):
        if not ln.strip() or ln in ctx.seen_lines:
            continue
        ctx.seen_lines.add(ln)
        fresh.append(ln)
    return fresh


def do_wait_event(ctx: Context, step) -> None:
    wait_event(ctx, step, step.fields["pattern"], step.fields.get("category"))


def wait_event(ctx: Context, step, pattern_text: str, category: str | None,
               fail_pattern: str | None = None) -> str:
    """Poll the new events until one matches, within the step timeout; returns the matching
    (cut) line. A line matching `fail_pattern` fails the step at once."""
    pattern = re.compile(pattern_text)
    failing = re.compile(fail_pattern) if fail_pattern else None
    end = _deadline(ctx, step)
    while True:
        try:
            for line in read_new_events(ctx):
                parts = line.split()
                if category and (len(parts) < 3 or parts[2] != category):
                    continue
                if failing and failing.search(line):
                    raise StepFailed("the launcher reported start-failed")
                if pattern.search(line):
                    return line
        except dev.DevError as e:
            raise StepFailed(str(e)) from None
        if ctx.now() >= end:
            what = f"category {category}, " if category else ""
            raise StepFailed(f"timeout after {step.timeout:g}s waiting for an event "
                             f"({what}pattern {pattern_text})")
        ctx.sleep(POLL_S)


def do_wait_process(ctx: Context, step) -> None:
    want = step.fields["state"]
    name = step.fields["process"]
    end = _deadline(ctx, step)
    while True:
        try:
            state = ctx.run(process_command(name)).strip()
        except dev.DevError as e:
            raise StepFailed(str(e)) from None
        if state == want:
            return
        if ctx.now() >= end:
            raise StepFailed(f"timeout after {step.timeout:g}s: {name} still {state}")
        ctx.sleep(POLL_S)


def do_shot(ctx: Context, step) -> None:
    start = ctx.now()
    try:
        ok, detail = ctx.shot(step.fields["screen"])
    except dev.DevError as e:
        raise StepFailed(str(e)) from None
    if ctx.now() - start > step.timeout:
        raise StepFailed(f"timeout after {step.timeout:g}s")
    if not ok:
        raise StepFailed(detail or "screen differs from the reference")


def do_sh(ctx: Context, step) -> None:
    try:
        rc = ctx.sh(step.fields["command"], step.timeout)
    except dev.DevError as e:
        raise StepFailed(str(e)) from None
    if rc != 0:
        raise StepFailed(f"exit {rc}")


def do_open_game(ctx: Context, step) -> None:
    try:
        ctx.open_game(step.fields["system"], step.fields["position"])
    except dev.DevError as e:
        raise StepFailed(str(e)) from None
    system = step.fields["system"]
    ctx.last_system = system
    wait_event(ctx, step, opened_pattern(system), GAME_CATEGORY, start_failed_pattern(system))


def do_close_game(ctx: Context, step) -> None:
    try:
        ctx.close_game()
    except dev.DevError as e:
        raise StepFailed(str(e)) from None
    line = wait_event(ctx, step, closed_pattern(ctx.last_system), GAME_CATEGORY)
    ctx.game_end = "FAIL" if re.search(r"\bFAIL\b", line) else "OK"   # either way it ended


HANDLERS = {
    "keys": do_keys, "play": do_play, "wait_event": do_wait_event,
    "wait_process": do_wait_process, "shot": do_shot, "sh": do_sh,
    "open_game": do_open_game, "close_game": do_close_game,
}


# --- runner ------------------------------------------------------------------------------

def run_script(script: scripts.Script, ctx: Context, console: str, out=None) -> int:
    """Run the steps of `script` on `console`; 0 if all passed, 1 at the first failure or
    when the console is not one the script lists (nothing runs then)."""
    out = out or sys.stdout
    try:
        scripts.check_console(script, console)
    except scripts.ScriptError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    try:                                  # only the events after this point count
        ctx.start_lines = ctx.seen = int(ctx.run(count_command()).strip() or 0)
    except (dev.DevError, ValueError):
        ctx.start_lines = ctx.seen = 0
    try:                                  # events.pending lines of before the run never match,
        ctx.seen_lines = set(read_pending(ctx))   # not even once drained into events.log
    except dev.DevError:
        ctx.seen_lines = set()
    for n, step in enumerate(script.steps, 1):
        try:
            HANDLERS[step.type](ctx, step)
        except StepFailed as e:
            print(f"passo {n} {step.name}: FALHOU ({e})", file=out)
            return 1
        print(f"passo {n} {step.name}: ok", file=out)
    return 0


def resolve_script(ref: str, root: Path | None = None) -> Path:
    """A bare name is tests/device/scripts/<name>.toml; anything else is a path."""
    root = root or dev.REPO_ROOT
    if "/" not in ref and not ref.endswith(".toml"):
        return root / "tests" / "device" / "scripts" / f"{ref}.toml"
    return Path(ref)


def cmd_run(host: str, ref: str, console: str | None) -> int:
    try:
        script = scripts.load(resolve_script(ref))
    except (scripts.ScriptError, OSError) as e:
        raise dev.DevError(str(e)) from None
    name = dev.which_console(host, console)     # refuses a wrong --console before anything
    return run_script(script, Context(host, console=name), name)
