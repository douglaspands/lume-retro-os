"""device-fixes 9.1 (D15): the PC sets the console clock over the cable."""

from lume_tool import clock, dev


def test_command_sets_the_time_through_lume_clock_with_a_fallback():
    cmd = clock.set_clock_command(1790000000)
    assert "lume-clock set 1790000000 pc" in cmd
    assert "date -u -s @1790000000" in cmd and "hwclock -w" in cmd


def test_command_truncates_to_whole_seconds():
    assert "set 1790000000 " in clock.set_clock_command(1790000000.9)


def test_sync_runs_the_command_with_the_pc_time():
    sent = []
    assert clock.sync_console_clock(sent.append, now=lambda: 1790000123.4) is True
    assert sent == [clock.set_clock_command(1790000123)]


def test_sync_never_raises():
    def boom(cmd):
        raise RuntimeError("ssh dropped")

    assert clock.sync_console_clock(boom) is False


def test_dev_log_sets_the_clock_after_identifying_the_console(monkeypatch):
    sent = []
    monkeypatch.setattr(dev, "run_capture", lambda host, cmd: sent.append(cmd) or "ga36\narmv7l\n")
    monkeypatch.setattr(dev, "cmd_log", lambda host: 0)
    args = type("A", (), {"host": "10.55.0.1", "dev_command": "log", "console": None})()
    assert dev.main_dev(args) == 0
    assert any("lume-clock set" in c for c in sent)


def test_dev_wait_does_not_touch_the_clock(monkeypatch):
    sent = []
    monkeypatch.setattr(dev, "run_capture", lambda host, cmd: sent.append(cmd) or "")
    monkeypatch.setattr(dev, "cmd_wait", lambda host, timeout: 0)
    args = type("A", (), {"host": "10.55.0.1", "dev_command": "wait", "timeout": 1})()
    assert dev.main_dev(args) == 0
    assert sent == []
