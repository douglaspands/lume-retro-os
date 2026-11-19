"""scripts/guardrail.py: `timeout <duration>` is transparent (M-31).

The user asked (2026-11-18) for `timeout` to be allowed safely: the guardrail strips only the
`timeout` prefix and judges the command inside with the usual rules, so a timeout never makes a
command safer or more dangerous than it is on its own.
"""

import importlib.util

from lume_tool.paths import REPO_ROOT

spec = importlib.util.spec_from_file_location("guardrail", REPO_ROOT / "scripts/guardrail.py")
guardrail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guardrail)
POLICY = guardrail.load_policy()


def cmd(c):
    return guardrail.evaluate_shell_command(c, POLICY)[0]


def test_timeout_takes_the_decision_of_the_command_inside():
    for inner in (
        ".venv/bin/lume dev wait --timeout 60",
        "git status -s -b",
        "rm cache/tmp/x.png",
        "rm docs/LOGS.md",
        ".venv/bin/lume dev sh 'uptime'",
        "ping -c 3 10.55.0.1",
    ):
        assert cmd(f"timeout 70 {inner}") == cmd(inner), inner


def test_timeout_options_and_units():
    inner = ".venv/bin/lume dev wait"
    assert cmd(f"timeout 1.5m {inner}") == cmd(inner)
    assert cmd(f"timeout -s KILL 30 {inner}") == cmd(inner)
    assert cmd(f"timeout --kill-after=5 30 {inner}") == cmd(inner)
    assert cmd(f"timeout --preserve-status 30 {inner}") == cmd(inner)
    assert cmd(f"/usr/bin/timeout 30 {inner}") == cmd(inner)
    assert cmd(f"timeout 30 git status | head -5") == cmd("git status | head -5")
    assert cmd(f"timeout 10 timeout 5 {inner}") == cmd(inner)


def test_timeout_never_hides_a_dangerous_command():
    assert cmd("timeout 5 sudo ls") == "ask"
    assert cmd("timeout 5 env FOO=1 ls") == "ask"
    assert cmd("timeout 5 sh -c 'ls'") == "ask"
    assert cmd("timeout 5 python3 x.py") == "deny"      # global toolchain
    assert cmd("timeout 5 rm -rf /") == "deny"
    assert cmd("timeout 5 cat README.md") == cmd("cat README.md")


def test_timeout_without_a_command_still_asks():
    assert cmd("timeout 5") == "ask"
    assert cmd("timeout") == "ask"
    assert cmd("timeout abc ls") == "ask"                # not a duration
