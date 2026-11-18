"""`lume dev check`: parsing of the device-mode self-test output and the exit code."""

import subprocess

import pytest

from lume_tool import dev

GREEN = """\
SELFTEST roms-mounted PASS /dev/mmcblk0p3 /storage exfat rw,noatime 0 0
SELFTEST service-seatd PASS started
SELFTEST-DONE board=ga36 pass=2 fail=0
"""

RED = """\
SELFTEST roms-mounted PASS
SELFTEST service-networkmanager FAIL stopped
SELFTEST frontend-up FAIL lume-run= lume-ui=
SELFTEST-DONE board=r36s pass=1 fail=2
"""


def _fake_run(stdout, returncode, stderr=""):
    def run(argv, **kw):
        assert argv[-1] == dev.SELFTEST_COMMAND
        return subprocess.CompletedProcess(argv, returncode, stdout.encode(), stderr.encode())
    return run


def test_parse_green():
    res = dev.parse_selftest(GREEN)
    assert res.ok and res.board == "ga36" and res.passed == 2 and res.failed == []


def test_parse_red_lists_failed_checks_with_detail():
    res = dev.parse_selftest(RED)
    assert not res.ok and res.board == "r36s"
    assert res.failed == [("service-networkmanager", "stopped"),
                          ("frontend-up", "lume-run= lume-ui=")]


def test_parse_without_done_line_is_not_ok():
    assert not dev.parse_selftest("SELFTEST a PASS\n").ok


def test_parse_ignores_noise_and_reads_error():
    res = dev.parse_selftest("motd noise\nSELFTEST-ERROR device mode is for the consoles\n")
    assert res.error and not res.ok


def test_check_green_exit_0(monkeypatch, capsys):
    monkeypatch.setattr(dev.subprocess, "run", _fake_run(GREEN, 0))
    assert dev.cmd_check("10.55.0.1", None) == 0
    assert "GA36: self-test PASS (2 checks)" in capsys.readouterr().out


def test_check_red_exit_1_names_console_and_checks(monkeypatch, capsys):
    monkeypatch.setattr(dev.subprocess, "run", _fake_run(RED, 1))
    assert dev.cmd_check("10.55.0.1", "r36s") == 1
    out = capsys.readouterr().out
    assert "R36S: self-test FAIL (2 of 3 checks failed)" in out
    assert "FAIL service-networkmanager: stopped" in out


def test_check_exit_code_fail_even_if_output_looks_green(monkeypatch):
    monkeypatch.setattr(dev.subprocess, "run", _fake_run(GREEN, 1))
    assert dev.cmd_check("10.55.0.1", None) == 1


def test_check_refuses_the_other_console(monkeypatch, capsys):
    monkeypatch.setattr(dev.subprocess, "run", _fake_run(GREEN, 0))
    assert dev.cmd_check("10.55.0.1", "r36s") == 1
    assert "is the GA36, not the R36S" in capsys.readouterr().err


def test_check_script_that_did_not_finish_is_an_error(monkeypatch):
    monkeypatch.setattr(dev.subprocess, "run", _fake_run("SELFTEST a PASS\n", 1, "boom"))
    with pytest.raises(dev.DevError, match="did not finish"):
        dev.cmd_check("10.55.0.1", None)


def test_check_ssh_failure_is_an_error(monkeypatch):
    monkeypatch.setattr(dev.subprocess, "run", _fake_run("", 255, "no route"))
    with pytest.raises(dev.DevError, match="ssh to the console failed"):
        dev.cmd_check("10.55.0.1", None)
