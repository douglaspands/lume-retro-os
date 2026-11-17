"""The shared ssh channel (virtual-gamepad 3.6)."""

import subprocess

import pytest

from r36os import dev, dev_run, push, sshmux

PLAIN = ["ssh", "-o", "UserKnownHostsFile=/dev/null", "-o", "StrictHostKeyChecking=no",
         "-o", "LogLevel=ERROR", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5",
         "-o", "ServerAliveInterval=3", "-o", "ServerAliveCountMax=2", "root@10.55.0.1"]


@pytest.fixture
def mux(monkeypatch):
    monkeypatch.setenv("R36OS_SSH_MUX", "1")


def test_without_the_option_the_argv_is_the_old_one():
    assert push.Remote().base == PLAIN
    assert dev.ssh_argv("10.55.0.1", "true") == [*PLAIN, "true"]
    assert push.Remote("127.0.0.1:2222").base[-3:-1] == ["-p", "2222"]


def test_with_the_option_the_argv_has_the_channel(mux, tmp_path):
    base = push.Remote().base
    assert base[-1] == "root@10.55.0.1"
    opts = " ".join(base)
    assert "ControlMaster=auto" in opts and "ControlPersist=60" in opts
    assert "ServerAliveInterval=3" in opts and "ServerAliveCountMax=2" in opts
    path = next(a for a in base if a.startswith("ControlPath=")).split("=", 1)[1]
    assert path.startswith(str(tmp_path / "ssh"))
    assert (tmp_path / "ssh").is_dir()
    argv = dev.ssh_argv("10.55.0.1", "true", tty=True)
    assert "-tt" in argv and argv[-2:] == ["root@10.55.0.1", "true"]
    assert "ControlMaster=auto" in argv


def test_one_socket_per_host_and_port(mux):
    a = sshmux.control_path("127.0.0.1", 2222)
    b = sshmux.control_path("127.0.0.1", 2223)
    c = sshmux.control_path("10.55.0.1", None)
    assert len({a, b, c}) == 3


def test_a_too_long_path_falls_back_to_no_mux(mux, monkeypatch, tmp_path):
    monkeypatch.setenv("R36OS_SSH_DIR", str(tmp_path / ("d" * 120)))
    assert push.Remote().base == PLAIN


def test_the_probe_never_uses_the_channel(mux, monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: seen.append(argv) or subprocess.CompletedProcess(argv, 0))
    assert push.Remote().answers() is True
    assert seen == [[*PLAIN, "true"]]


def test_a_new_boot_drops_the_channel(mux):
    base = push.Remote().base
    dropped = []
    assert sshmux.revalidate(base, "ga36", "boot-a\n", drop_fn=dropped.append) is True
    assert sshmux.revalidate(base, "ga36", "boot-a", drop_fn=dropped.append) is True
    assert dropped == []
    assert sshmux.revalidate(base, "ga36", "boot-b", drop_fn=dropped.append) is False
    assert dropped == [base]
    assert sshmux.read_identity(base) == "ga36 boot-b"


def test_another_console_on_the_cable_drops_the_channel(mux):
    base = push.Remote().base
    dropped = []
    sshmux.revalidate(base, "ga36", "same", drop_fn=dropped.append)
    assert sshmux.revalidate(base, "r36s", "same", drop_fn=dropped.append) is False
    assert dropped == [base]


def test_drop_runs_ssh_O_exit_on_the_same_channel(mux):
    base = push.Remote().base
    sshmux.revalidate(base, "ga36", "x")
    calls = []
    sshmux.drop(base, run=lambda argv, **kw: calls.append(argv))
    assert calls[0][-3:] == ["-O", "exit", "root@10.55.0.1"]
    assert [a for a in calls[0] if a.startswith("ControlPath=")] == \
        [a for a in base if a.startswith("ControlPath=")]
    assert sshmux.read_identity(base) is None


def test_drop_without_a_channel_does_nothing(monkeypatch):
    calls = []
    sshmux.drop(push.Remote().base, run=lambda *a, **kw: calls.append(a))
    assert calls == []


def test_which_console_reads_the_identity_through_the_channel(mux, monkeypatch):
    answers = {"boot": "b1\n"}

    def run_capture(host, cmd):
        return answers["boot"] if cmd == sshmux.BOOT_ID_COMMAND else "ga36\narmv7l\n"

    monkeypatch.setattr(dev, "run_capture", run_capture)
    dropped = []
    monkeypatch.setattr(sshmux, "drop", lambda base, **kw: dropped.append(base))
    assert dev.which_console("10.55.0.1", None) == "ga36"
    assert dev.which_console("10.55.0.1", None) == "ga36"
    assert dropped == []
    answers["boot"] = "b2\n"
    dev.which_console("10.55.0.1", None)
    assert len(dropped) == 1


def test_which_console_asks_nothing_extra_without_the_option(monkeypatch):
    cmds = []
    monkeypatch.setattr(dev, "run_capture", lambda h, c: cmds.append(c) or "ga36\narmv7l\n")
    dev.which_console("10.55.0.1", None)
    assert cmds == [push.IDENTIFY]


def test_dev_wait_drops_the_channel(monkeypatch):
    calls = []
    monkeypatch.setattr(push.Remote, "drop_channel", lambda self: calls.append("drop"))
    monkeypatch.setattr(dev, "wait_for_console", lambda host, timeout: True)
    assert dev.cmd_wait("10.55.0.1", 1) == 0
    assert calls == ["drop"]


class _Remote:
    host = "10.55.0.1"

    def __init__(self):
        self.events = []

    def drop_channel(self):
        self.events.append("drop")

    def answers(self):
        self.events.append("answers")
        return len([e for e in self.events if e == "answers"]) > 1

    def run(self, cmd, stdin=None):
        self.events.append("run")
        return ""


def test_push_drops_the_channel_around_the_reboot(monkeypatch):
    remote = _Remote()
    monkeypatch.setattr(push, "read_boot_state",
                        lambda r: push.BootState("2", "b1", "boot OK completed", {}) if False
                        else (_ for _ in ()).throw(push.PushError("stop")))
    with pytest.raises(push.PushError):
        push.verify_boot(remote, "b1", "1", sleep=lambda s: None, now=iter(range(0, 10**6)).__next__,
                         checks=[])
    # dropped before waiting for the console to go away and again once it is back
    assert remote.events.count("drop") == 2
    assert remote.events.index("drop") < remote.events.index("answers")


def test_dev_run_uses_the_channel(mux, monkeypatch):
    seen = []
    monkeypatch.setattr(subprocess, "run",
                        lambda argv, **kw: seen.append(argv)
                        or subprocess.CompletedProcess(argv, 0, stdout=b"x", stderr=b""))
    ctx = dev_run.Context(host="10.55.0.1")
    ctx.run("echo hi")
    ctx._default_sh("true", 5)
    assert len(seen) == 2
    assert all("ControlMaster=auto" in a for a in seen)
