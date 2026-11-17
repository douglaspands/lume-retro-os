"""Which console is on the cable (build-speed 3.4, D18): one card moves between the GA36 and
the R36S, both answer at push.CONSOLE_ADDR; `push`, `push --hot` and `dev` say which one
answered and `--console` refuses the other one before anything is sent or run."""

import argparse

import pytest

from r36os import dev, push
from r36os.cli import _parser
from tests.unit.test_push import FakeConsole, FakeHotConsole, build, hot, repo, run_push  # noqa: F401


# --- the shared helper -----------------------------------------------------------------

@pytest.mark.parametrize("board,machine,name", [
    ("ga36", "armv7l", "ga36"),
    ("r36s", "aarch64", "r36s"),
    ("r36s\n", "", "r36s"),             # the board file wins
    ("-", "armv7l", "ga36"),            # no board file: from the arch
    ("-", "aarch64", "r36s"),
    ("-", "x86_64", ""),                # the vm: not a console
    ("", "", ""),
])
def test_console_name_from_board_then_arch(board, machine, name):
    assert push.console_name(board, machine) == name


def test_identify_console_runs_one_probe():
    cmds = []

    def run(cmd):
        cmds.append(cmd)
        return "-\naarch64\n"
    assert push.identify_console(run) == "r36s"
    assert cmds == [push.IDENTIFY]
    assert push.identify_console(lambda cmd: "") == ""


def test_console_refusal():
    assert push.console_refusal("ga36", None) is None
    assert push.console_refusal("r36s", "r36s") is None
    assert push.console_refusal("ga36", "r36s") == \
        "the console on the cable is the GA36, not the R36S"
    assert push.console_refusal("r36s", "ga36") == \
        "the console on the cable is the R36S, not the GA36"
    assert "did not say which one" in push.console_refusal("", "ga36")


# --- push ------------------------------------------------------------------------------

def test_push_refuses_the_other_console_before_sending(build, tmp_path):
    c = FakeConsole(board="ga36")
    with pytest.raises(push.PushError,
                       match="the console on the cable is the GA36, not the R36S: nothing"):
        run_push(tmp_path, c, console_wanted="r36s")
    assert c.log == ["probe"]           # only read: nothing sent, nothing rebooted


def test_push_goes_on_with_the_right_console(build, tmp_path):
    c = FakeConsole(board="r36s")
    rc, out = run_push(tmp_path, c, console_wanted="r36s")
    assert rc == 0 and out[0].startswith("console: r36s,")


# --- push --hot ------------------------------------------------------------------------

def test_hot_refuses_the_other_console_before_sending(repo, tmp_path):
    from r36os import push_hot

    console = FakeHotConsole(machine="armv7l")          # its board file says ga36
    lines = []
    with pytest.raises(push.PushError, match="is the GA36, not the R36S: nothing was sent"):
        push_hot.push_hot("lume-core", console, out=lines.append, aports=tmp_path / "aports",
                          console_wanted="r36s")
    assert len(console.cmds) == 1 and console.cmds[0] == push_hot._PROBE
    assert lines[0].startswith("console: ga36,")


def test_hot_goes_on_with_the_right_console(repo, tmp_path):
    from r36os import push_hot

    console = FakeHotConsole()
    assert push_hot.push_hot("lume-core", console, out=[].append,
                             aports=tmp_path / "aports", console_wanted="ga36") == 0


# --- dev -------------------------------------------------------------------------------

def _dev_args(action, console=None, **kw):
    base = {"sh": {"cmd": ["true"]}, "shot": {"file": None, "compare": None, "update": None},
            "keys": {"sequence": "a", "hold": 80, "gap": 120}, "log": {}, "check": {},
            "wait": {"timeout": 1.0}}[action]
    return argparse.Namespace(dev_command=action, host=None, console=console,
                              **{**base, **kw})


@pytest.fixture
def ga36_on_cable(monkeypatch):
    """dev's ssh: the GA36 answers the identification; any other command fails the test."""
    cmds = []

    def run_capture(host, cmd):
        cmds.append(cmd)
        assert host == push.CONSOLE_ADDR
        if cmd == push.IDENTIFY:
            return "ga36\narmv7l\n"
        raise AssertionError(f"ran on the console: {cmd}")

    def no_ssh(*a, **kw):
        raise AssertionError("ssh ran past the identification")
    monkeypatch.setattr(dev, "run_capture", run_capture)
    monkeypatch.setattr(dev.subprocess, "run", no_ssh)
    monkeypatch.setattr(dev.subprocess, "call", no_ssh)
    return cmds


@pytest.mark.parametrize("action", ["sh", "shot", "keys", "log", "check"])
def test_dev_refuses_the_other_console_before_running(ga36_on_cable, capsys, action):
    assert dev.main_dev(_dev_args(action, console="r36s")) == 1
    err = capsys.readouterr().err
    assert "console: GA36 (10.55.0.1)" in err
    assert "error: the console on the cable is the GA36, not the R36S" in err
    assert ga36_on_cable == [push.IDENTIFY]


def test_dev_says_which_console_answered(ga36_on_cable, monkeypatch, capsys):
    monkeypatch.setattr(dev, "cmd_log", lambda host: 0)
    assert dev.main_dev(_dev_args("log", console="ga36")) == 0
    assert dev.main_dev(_dev_args("log")) == 0
    assert capsys.readouterr().err.count("console: GA36 (10.55.0.1)") == 2


def test_dev_wait_does_not_ask_the_console(monkeypatch):
    monkeypatch.setattr(dev, "identify_console", lambda run: pytest.fail("identified"))
    monkeypatch.setattr(dev, "cmd_wait", lambda host, timeout: 0)
    assert dev.main_dev(_dev_args("wait")) == 0


# --- command line ----------------------------------------------------------------------

def test_cli_console_option_on_push_and_dev_actions():
    p = _parser()
    assert p.parse_args(["push", "--console", "r36s"]).console == "r36s"
    assert p.parse_args(["push", "--hot", "lume-core", "--console", "ga36"]).console == "ga36"
    a = p.parse_args(["dev", "sh", "--console", "r36s", "ls", "-l"])
    assert a.console == "r36s" and a.cmd == ["ls", "-l"]
    for action in (["shot", "x.png"], ["keys", "a"], ["log"], ["check"]):
        assert p.parse_args(["dev", *action, "--console", "ga36"]).console == "ga36"
    with pytest.raises(SystemExit):
        p.parse_args(["dev", "wait", "--console", "ga36"])
    with pytest.raises(SystemExit):     # flash writes a card in a reader: no console to ask
        p.parse_args(["flash", "console", "/dev/sdx", "--console", "ga36"])
