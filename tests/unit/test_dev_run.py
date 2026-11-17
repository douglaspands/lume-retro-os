"""Unit tests of `r36os dev run` with a fake console and a fake clock: no device, no ssh."""
import re

import pytest

from r36os import dev, dev_run, scripts

SECRET = "Secret Game Title"


class Clock:
    def __init__(self):
        self.t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


class FakeConsole:
    """Answers the remote commands of the runner. `lines` is the events.log content; the
    fake does NOT cut `content=` (as a broken console filter would), so the local guard is
    what the tests exercise."""

    def __init__(self, lines=(), processes=()):
        self.lines = list(lines)
        self.processes = set(processes)
        self.cmds = []
        self.keys = []

    def __call__(self, cmd):
        self.cmds.append(cmd)
        if cmd == dev_run.count_command():
            return f"{len(self.lines)}\n"
        m = re.search(r"-v s=(\d+)", cmd)
        if m:
            skip = int(m.group(1))
            return "\n".join(self.lines[skip:] + [f"{dev_run.COUNT_MARK}{len(self.lines)}"])
        m = re.match(r"pidof (\S+) ", cmd)
        if m:
            return "present\n" if m.group(1) in self.processes else "absent\n"
        raise AssertionError(cmd)


def make(text, console=None, clock=None, **kw):
    script = scripts.loads(text)
    clock = clock or Clock()
    console = console or FakeConsole()
    ctx = dev_run.Context("h", run=console, sleep=clock.sleep, now=clock.now,
                          keys=lambda seq: console.keys.append(seq), **kw)
    return script, ctx, console, clock


def hdr(extra="", consoles='["ga36"]'):
    return f'consoles = {consoles}\n{extra}'


def test_all_steps_pass_exit_0(capsys):
    script, ctx, console, _ = make(hdr('''
[[step]]
name = "open the menu"
type = "keys"
sequence = "fn+start"
[[step]]
name = "ui is up"
type = "wait_process"
process = "lume-launcher"
state = "present"
'''), console=FakeConsole(processes={"lume-launcher"}))
    assert dev_run.run_script(script, ctx, "ga36") == 0
    assert capsys.readouterr().out.splitlines() == [
        "passo 1 open the menu: ok", "passo 2 ui is up: ok"]
    assert console.keys == ["fn+start"]


def test_step_that_times_out_fails_and_stops(capsys):
    script, ctx, console, clock = make(hdr('''
[[step]]
name = "never happens"
type = "wait_event"
pattern = "boot OK nothing"
timeout = 3
[[step]]
name = "after"
type = "keys"
sequence = "a"
'''))
    assert dev_run.run_script(script, ctx, "ga36") == 1
    out = capsys.readouterr().out
    assert out.startswith("passo 1 never happens: FALHOU (timeout after 3s")
    assert "passo 2" not in out
    assert console.keys == []
    assert clock.t >= 3


def test_wrong_console_is_refused_before_any_button(capsys):
    script, ctx, console, _ = make(hdr('''
[[step]]
name = "press"
type = "keys"
sequence = "a"
'''))
    assert dev_run.run_script(script, ctx, "r36s") == 1
    cap = capsys.readouterr()
    assert "script is for ga36, not r36s" in cap.err
    assert cap.out == ""
    assert console.keys == [] and console.cmds == []


def test_events_before_the_start_are_ignored_and_content_is_cut(capsys):
    old = "2026-11-09T21:00:00 3 game OK opened: core=X content=" + SECRET
    console = FakeConsole(lines=[old])
    script, ctx, _, _ = make(hdr('''
[[step]]
name = "old one must not match"
type = "wait_event"
pattern = "opened"
timeout = 2
'''), console=console)
    assert dev_run.run_script(script, ctx, "ga36") == 1       # the old line is not seen
    capsys.readouterr()

    class Appending(FakeConsole):
        def __call__(self, cmd):
            if "awk" in cmd:
                self.lines.append("2026-11-09T21:10:00 4 game OK opened: core=X content="
                                  + SECRET)
            return super().__call__(cmd)

    c2 = Appending(lines=[old])
    script, ctx, _, _ = make(hdr('''
[[step]]
name = "new one matches"
type = "wait_event"
pattern = "opened: core=X$"
category = "game"
'''), console=c2)
    assert dev_run.run_script(script, ctx, "ga36") == 0       # matched only after the cut
    cap = capsys.readouterr()
    assert SECRET not in cap.out + cap.err


def test_cut_content_and_remote_command_filter():
    assert dev_run.cut_content("t 1 game OK opened: core=X content=A B") == \
        "t 1 game OK opened: core=X"
    assert "content=" in dev_run.events_command(5) and "NR > s" in dev_run.events_command(5)


def test_failure_reason_never_carries_a_log_line(capsys):
    console = FakeConsole()
    script, ctx, _, _ = make(hdr('''
[[step]]
name = "wait"
type = "wait_event"
pattern = "zzz"
timeout = 1
'''), console=console)

    class Noisy(FakeConsole):
        def __call__(self, cmd):
            if "awk" in cmd:
                return f"t 1 game OK x content={SECRET}\n{dev_run.COUNT_MARK}0\n"
            return super().__call__(cmd)

    script, ctx, _, _ = make(hdr('''
[[step]]
name = "wait"
type = "wait_event"
pattern = "zzz"
timeout = 1
'''), console=Noisy())
    assert dev_run.run_script(script, ctx, "ga36") == 1
    cap = capsys.readouterr()
    assert SECRET not in cap.out + cap.err


def test_sh_exit_code_and_process_absent(capsys):
    script, ctx, _, _ = make(hdr('''
[[step]]
name = "fails"
type = "sh"
command = "false"
'''), sh=lambda cmd, t: 3)
    assert dev_run.run_script(script, ctx, "ga36") == 1
    assert "passo 1 fails: FALHOU (exit 3)" in capsys.readouterr().out
    script, ctx, _, _ = make(hdr('''
[[step]]
name = "gone"
type = "wait_process"
process = "retroarch"
state = "absent"
'''))
    assert dev_run.run_script(script, ctx, "ga36") == 0


def test_keys_error_and_overrun_fail(capsys):
    def boom(seq):
        raise dev.DevError("ssh to the console failed")

    script, ctx, _, _ = make(hdr('''
[[step]]
name = "press"
type = "keys"
sequence = "a"
'''))
    ctx.keys = boom
    assert dev_run.run_script(script, ctx, "ga36") == 1
    assert "FALHOU (ssh to the console failed)" in capsys.readouterr().out
    script, ctx, _, clock = make(hdr('''
[[step]]
name = "slow"
type = "keys"
sequence = "a"
timeout = 5
'''))
    ctx.keys = lambda seq: clock.sleep(9)
    assert dev_run.run_script(script, ctx, "ga36") == 1
    assert "FALHOU (timeout after 5s)" in capsys.readouterr().out


def test_shot_result_and_hooks(capsys):
    script, ctx, _, _ = make(hdr('''
[[step]]
name = "look"
type = "shot"
screen = "home"
'''), shot=lambda s: (False, "12 of 100 pixels differ"))
    assert dev_run.run_script(script, ctx, "ga36") == 1
    assert "FALHOU (12 of 100 pixels differ)" in capsys.readouterr().out
    opened = []
    console = FakeConsole()

    def open_game(s, p):
        opened.append((s, p))
        console.lines.append("2026-11-09T21:10:00 4 game OK opened: core=X content=" + SECRET)

    script, ctx, _, _ = make(hdr('''
[[step]]
name = "open"
type = "open_game"
system = "nes"
position = 2
'''), console=console, open_game=open_game)
    assert dev_run.run_script(script, ctx, "ga36") == 0
    assert opened == [("nes", 2)]
    assert SECRET not in capsys.readouterr().out


def test_resolve_script(tmp_path):
    assert dev_run.resolve_script("smoke", tmp_path) == \
        tmp_path / "tests" / "device" / "scripts" / "smoke.toml"
    assert str(dev_run.resolve_script("a/b.toml", tmp_path)) == "a/b.toml"


def test_cmd_run_bad_script_is_a_dev_error(tmp_path):
    with pytest.raises(dev.DevError):
        dev_run.cmd_run("h", str(tmp_path / "missing.toml"), None)
