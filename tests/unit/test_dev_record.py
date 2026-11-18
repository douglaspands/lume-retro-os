"""Unit tests of `r36os dev record|play` with a fake console: no device, no ssh."""
import time

import pytest

from r36os import dev, evrec

GOOD = "# lume-evrec 1 ga36\n10 1 304 1\n90 1 304 0\n# end 100\n"
EMPTY = "# lume-evrec 1 ga36\n# end 100\n"


class FakeRun:
    def __init__(self, answers):
        self.answers = answers      # command -> reply
        self.cmds = []

    def __call__(self, cmd):
        self.cmds.append(cmd)
        return self.answers.get(cmd, "")


def stop(run, tmp_path, console="ga36"):
    return dev.cmd_record("h", console, True, run=run, recordings_dir=tmp_path,
                          now=lambda: time.gmtime(0))


def test_record_start_sends_the_script(capsys):
    run = FakeRun({dev.record_start_command(): "recording\n"})
    assert dev.cmd_record("h", "ga36", False, run=run) == 0
    assert run.cmds == [dev.record_start_command()]
    assert "lume-evrec record /run/lume/evrec/current.evrec" in run.cmds[0]
    assert "recording on the GA36" in capsys.readouterr().out


def test_record_refused_when_already_recording():
    run = FakeRun({dev.record_start_command(): "busy\n"})
    with pytest.raises(dev.DevError, match="already running"):
        dev.cmd_record("h", "ga36", False, run=run)


def test_record_start_failure():
    run = FakeRun({dev.record_start_command(): "failed\n"})
    with pytest.raises(dev.DevError, match="did not start"):
        dev.cmd_record("h", "ga36", False, run=run)


def test_stop_saves_fetches_and_cleans(tmp_path, capsys):
    run = FakeRun({dev.record_stop_command(): "stopped\n", dev.record_fetch_command(): GOOD})
    assert stop(run, tmp_path) == 0
    saved = tmp_path / "ga36-19700101-000000.evrec"
    assert evrec.read(saved).events[0].code == 304
    assert run.cmds == [dev.record_stop_command(), dev.record_fetch_command(),
                        dev.record_clean_command()]
    assert "2 events" in capsys.readouterr().out


def test_stop_empty_recording_is_an_error_and_not_saved(tmp_path):
    run = FakeRun({dev.record_stop_command(): "stopped\n", dev.record_fetch_command(): EMPTY})
    with pytest.raises(dev.DevError, match="empty"):
        stop(run, tmp_path)
    assert list(tmp_path.iterdir()) == []
    assert run.cmds[-1] == dev.record_clean_command()


def test_stop_recording_of_another_console_is_refused(tmp_path):
    run = FakeRun({dev.record_stop_command(): "stopped\n", dev.record_fetch_command(): GOOD})
    with pytest.raises(dev.DevError, match="not valid"):
        stop(run, tmp_path, console="r36s")
    assert list(tmp_path.iterdir()) == []


def test_stop_without_recording_and_timeout(tmp_path):
    with pytest.raises(dev.DevError, match="no recording"):
        stop(FakeRun({dev.record_stop_command(): "none\n"}), tmp_path)
    with pytest.raises(dev.DevError, match="did not stop"):
        stop(FakeRun({dev.record_stop_command(): "timeout\n"}), tmp_path)


class FakeSend:
    def __init__(self, play_rc=0, play_out="delay max=3 mean=1 events=2\n"):
        self.calls = []
        self.play_rc, self.play_out = play_rc, play_out

    def __call__(self, cmd, data=None):
        self.calls.append((cmd, data))
        if cmd == dev.play_command():
            return self.play_rc, self.play_out
        return 0, ""


def test_play_sends_plays_and_prints_the_delay(tmp_path, capsys):
    f = tmp_path / "a.evrec"
    f.write_text(GOOD)
    send = FakeSend()
    assert dev.cmd_play("h", "ga36", f, send=send) == 0
    assert [c for c, _ in send.calls] == [dev.play_upload_command(), dev.play_command(),
                                          dev.play_clean_command()]
    assert send.calls[0][1] == GOOD.encode()
    assert "delay max=3" in capsys.readouterr().out


def test_play_other_console_refused_before_sending(tmp_path):
    f = tmp_path / "a.evrec"
    f.write_text(GOOD)
    send = FakeSend()
    with pytest.raises(dev.DevError, match="for ga36, not r36s"):
        dev.cmd_play("h", "r36s", f, send=send)
    assert send.calls == []


def test_play_failure_is_propagated_and_cleans(tmp_path):
    f = tmp_path / "a.evrec"
    f.write_text(GOOD)
    send = FakeSend(play_rc=2, play_out="refused\n")
    with pytest.raises(dev.DevError, match="play failed"):
        dev.cmd_play("h", "ga36", f, send=send)
    assert send.calls[-1][0] == dev.play_clean_command()


def test_play_empty_or_bad_file_is_an_error(tmp_path):
    f = tmp_path / "a.evrec"
    f.write_text(EMPTY)
    send = FakeSend()
    with pytest.raises(dev.DevError, match="no events"):
        dev.cmd_play("h", "ga36", f, send=send)
    f.write_text("junk\n")
    with pytest.raises(dev.DevError, match="cannot play"):
        dev.cmd_play("h", "ga36", f, send=send)
    assert send.calls == []
