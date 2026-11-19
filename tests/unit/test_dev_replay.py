"""Unit tests of `lume dev replay` with a fake console: no device, no ssh."""

import pytest

from lume_tool import dev

PLAYING = "GET_STATUS PLAYING some-core\n"


class FakeConsole:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.sent = []

    def __call__(self, cmd):
        if cmd == dev.status_command():
            return self.statuses.pop(0)
        self.sent.append(cmd)
        return ""


def play(action, slot, console):
    return dev.cmd_replay("h", action, slot, run=console, settle=lambda s: None)


@pytest.mark.parametrize("action,slot,wire", [
    ("record", None, "RECORD_REPLAY"),
    ("stop", None, "HALT_REPLAY"),
    ("play", 3, "PLAY_REPLAY_SLOT 3"),
])
def test_replay_sends_the_network_command(action, slot, wire, capsys):
    c = FakeConsole([PLAYING, PLAYING])
    assert play(action, slot, c) == 0
    assert c.sent == [dev.send_command(wire)]
    assert "nc -u -w1 127.0.0.1 55355" in c.sent[0]
    assert "some-core: playing" in capsys.readouterr().out


def test_replay_without_game_is_an_error_and_sends_nothing():
    c = FakeConsole(["GET_STATUS CONTENTLESS\n"])
    with pytest.raises(dev.DevError, match="no RetroArch game"):
        play("record", None, c)
    assert c.sent == []


def test_replay_no_answer_is_an_error():
    with pytest.raises(dev.DevError):
        play("stop", None, FakeConsole([""]))


def test_replay_game_gone_after_send_is_an_error():
    with pytest.raises(dev.DevError, match="no longer"):
        play("record", None, FakeConsole([PLAYING, "GET_STATUS CONTENTLESS\n"]))


def test_replay_play_needs_a_slot():
    with pytest.raises(dev.DevError, match="slot"):
        play("play", None, FakeConsole([PLAYING]))


def test_status_is_cut_before_the_game_name():
    assert "cut -d, -f1" in dev.status_command()


def test_parse_status():
    assert dev.parse_status("GET_STATUS PAUSED core-x\n") == "core-x"
    assert dev.parse_status("GET_STATUS CONTENTLESS") is None
