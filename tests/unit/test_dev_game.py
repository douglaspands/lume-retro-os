"""Unit tests of open_game / close_game (virtual-gamepad D5): sequence building and the
console query parsed from a fake index answer. No device, no ssh."""
import pytest

from lume_tool import dev, dev_game, dev_run, scripts

SECRET = "Secret Game Title"


def test_info_command_prints_only_numbers_and_rejects_bad_ids():
    cmd = dev_game.info_command("gba")
    assert dev_game.CATALOG in cmd and dev_game.INDEX_DIR in cmd
    assert "od -An -tu4 -j8 -N4" in cmd
    assert 'echo "dock_index=$di dock_count=$((n+3)) games=$g focus=$fi"' in cmd
    assert "id -u game" in cmd and dev_game.STATE_FILE in cmd
    assert "game_path" not in cmd
    for bad in ("", "a b", "x;rm", "../x", "A$(x)"):
        with pytest.raises(dev.DevError):
            dev_game.info_command(bad)


def fixture_query(tmp_path, system, state_text):
    """Run the snippet under /bin/sh against a fake catalog, index files and state file
    (None = no state file). Dock: Favorites 0, nes 1, gba 2, Recent 3, Settings 4."""
    import struct
    import subprocess
    catalog = tmp_path / "systems.json"
    catalog.write_text('{"systems": [\n  {\n    "id": "nes",\n    "name": "NES"\n  },\n'
                       '  {\n    "id": "snes",\n    "name": "S"\n  },\n'
                       '  {\n    "id": "gba",\n    "name": "G"\n  },\n'
                       '  {\n    "id": "psx",\n    "name": "P"\n  }]}')
    idx = tmp_path / "index"
    idx.mkdir(exist_ok=True)
    for sid, count in (("nes", 3), ("gba", 12), ("psx", 0)):   # snes has no file
        (idx / f"{sid}.bin").write_bytes(b"LUMEIDX1" + struct.pack("<I", count) + b"\0" * 20)
    state = tmp_path / "state"
    if state_text is not None:
        state.write_text(state_text)
    cmd = (dev_game.info_command(system)
           .replace(dev_game.CATALOG, str(catalog)).replace(dev_game.INDEX_DIR, str(idx))
           .replace(dev_game.STATE_FILE, str(state)))
    return subprocess.run(["/bin/sh", "-c", cmd], capture_output=True, text=True).stdout.strip()


def test_info_command_runs_against_a_fixture_index(tmp_path):
    assert fixture_query(tmp_path, "gba", None) == \
        "dock_index=2 dock_count=5 games=12 focus=0"
    assert fixture_query(tmp_path, "psx", None) == \
        "dock_index=0 dock_count=5 games=0 focus=0"


@pytest.mark.parametrize("state, focus", [
    ("screen=grid\ndock=favorites\nlist=favorites\n", 0),
    ("screen=grid\ndock=sys:nes\nlist=sys:nes\n", 1),
    ("screen=grid\ndock=sys:gba\nlist=sys:gba\n", 2),
    ("dock=recent\n", 3),
    ("dock=settings\n", 4),
    ("dock=sys:snes\n", 0),          # a system with no games is not a tile: unknown -> 0
    ("dock=bogus\n", 0),
    ("screen=grid\n", 0),            # no dock= line
    ("", 0),
])
def test_focus_from_the_state_file(tmp_path, state, focus):
    assert fixture_query(tmp_path, "gba", state) == \
        f"dock_index=2 dock_count=5 games=12 focus={focus}"


def test_state_file_game_path_never_reaches_the_output(tmp_path):
    state = "screen=grid\ngame_path=/fake/roms/Fake Game.rom\ndock=sys:gba\nlist=sys:gba\n"
    out = fixture_query(tmp_path, "gba", state)
    assert out == "dock_index=2 dock_count=5 games=12 focus=2"
    assert "fake" not in out.lower() and "rom" not in out


def test_parse_info():
    assert dev_game.parse_info("dock_index=3 dock_count=9 games=12 focus=5\n") == (3, 9, 12, 5)
    with pytest.raises(dev.DevError):
        dev_game.parse_info("sh: od: not found\n")


def test_dock_moves_wrap_and_shortest():
    assert dev_game.dock_moves(0, 0, 9) == ""
    assert dev_game.dock_moves(0, 2, 9) == "right*2"
    assert dev_game.dock_moves(0, 7, 9) == "left*2"        # wraps to the left
    assert dev_game.dock_moves(7, 1, 9) == "right*3"
    assert dev_game.dock_moves(4, 1, 8) == "left*3"


def test_grid_moves_use_four_columns():
    assert dev_game.grid_moves(1) == []
    assert dev_game.grid_moves(3) == ["right*2"]
    assert dev_game.grid_moves(5) == ["down*1"]
    assert dev_game.grid_moves(11) == ["down*2", "right*2"]


def seq_of(from_focus, dock_index, dock_count, position):
    seq = dev_game.open_sequence(from_focus, dock_index, dock_count, position)
    dev.parse_sequence(seq)          # always a valid `dev keys` sequence
    return seq


def test_sequence_first_dock_tile():
    # the first system is tile 1 (after Favorites): one Right from the start
    assert seq_of(0, 1, 9, 1) == "b*4,wait:300,right*1,wait:300,a,wait:500,a,wait:300,a"


def test_sequence_middle_dock_tile_and_grid_position():
    assert seq_of(0, 4, 11, 6) == \
        "b*4,wait:300,right*4,wait:300,a,wait:500,down*1,right*1,a,wait:300,a"


def test_sequence_last_dock_tile_wraps_left():
    # 6 systems with games: tiles 0..8, the last system is tile 6; from Favorites it is 3 left
    assert seq_of(0, 6, 9, 1) == "b*4,wait:300,left*3,wait:300,a,wait:500,a,wait:300,a"


def test_sequence_from_the_tile_already_focused_has_no_dock_move():
    assert seq_of(3, 3, 9, 1) == "b*4,wait:300,a,wait:500,a,wait:300,a"


def make_driver(answer):
    asked, keys = [], []
    driver = dev_game.GameDriver(lambda cmd: asked.append(cmd) or answer, keys.append)
    return driver, asked, keys


def test_open_builds_the_sequence_from_the_reported_focus():
    driver, asked, keys = make_driver("dock_index=4 dock_count=11 games=7 focus=0\n")
    driver.open("gba", 6)
    assert keys == [seq_of(0, 4, 11, 6)]
    assert len(asked) == 1 and "gba" in asked[0]


def test_open_from_a_non_zero_focus():
    # the launcher came back on snes (tile 2); the target is tile 4 of 11: two Rights
    driver, _, keys = make_driver("dock_index=4 dock_count=11 games=7 focus=2\n")
    driver.open("gba", 1)
    assert keys == ["b*4,wait:300,right*2,wait:300,a,wait:500,a,wait:300,a"]
    # focus on the target tile itself: no Dock move
    driver, _, keys = make_driver("dock_index=4 dock_count=11 games=7 focus=4\n")
    driver.open("gba", 1)
    assert keys == [seq_of(4, 4, 11, 1)]
    # focus on Settings (last tile of 11), target tile 1: the Dock wraps, two Rights
    driver, _, keys = make_driver("dock_index=1 dock_count=11 games=7 focus=10\n")
    driver.open("nes", 1)
    assert keys == ["b*4,wait:300,right*2,wait:300,a,wait:500,a,wait:300,a"]


@pytest.mark.parametrize("answer", [
    "dock_index=0 dock_count=8 games=0 focus=0\n",     # not a Dock tile
    "dock_index=0 dock_count=8 games=3 focus=0\n",
])
def test_system_without_games_fails_before_any_key(answer):
    driver, _, keys = make_driver(answer)
    with pytest.raises(dev.DevError, match="no games"):
        driver.open("psx", 1)
    assert keys == []


def test_position_past_the_games_fails_before_any_key():
    driver, _, keys = make_driver("dock_index=2 dock_count=9 games=3 focus=0\n")
    with pytest.raises(dev.DevError, match="past the 3 games"):
        driver.open("nes", 4)
    assert keys == []


def test_close_is_fn_start():
    driver, _, keys = make_driver("")
    driver.close()
    assert keys == ["fn+start"]


class FakeConsole:
    """The runner's console: the index query, the events.log and process checks."""

    def __init__(self, info, events_on_keys):
        self.info = info
        self.events_on_keys = events_on_keys
        self.lines = []
        self.pending = []
        self.keys = []

    def __call__(self, cmd):
        if cmd == dev_run.pending_command():
            return "\n".join(self.pending) + "\n"
        if cmd == dev_run.count_command():
            return f"{len(self.lines)}\n"
        if cmd.startswith("u=$(id -u game"):
            return self.info
        if "-v s=" in cmd:
            skip = int(cmd.split("-v s=")[1].split()[0])
            return "\n".join(self.lines[skip:] + [f"{dev_run.COUNT_MARK}{len(self.lines)}"])
        raise AssertionError(cmd)

    def press(self, seq):
        self.keys.append(seq)
        if seq in self.events_on_keys:
            self.lines.append(self.events_on_keys[seq])


SCRIPT = '''consoles = ["ga36"]
[[step]]
name = "open one"
type = "open_game"
system = "gba"
position = 1
[[step]]
name = "close it"
type = "close_game"
'''


class Clock:
    t = 0.0

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s


def run_script(console, capsys):
    clock = Clock()
    ctx = dev_run.Context("h", run=console, keys=console.press, sleep=clock.sleep, now=clock.now)
    rc = dev_run.run_script(scripts.loads(SCRIPT), ctx, "ga36")
    return rc, capsys.readouterr().out


def test_open_then_close_script_passes_and_never_prints_the_game(capsys):
    opened_seq = dev_game.open_sequence(0, 2, 9, 1)
    console = FakeConsole("dock_index=2 dock_count=9 games=5 focus=0\n", {
        opened_seq: f"2026-11-09T21:10:00 4 game OK gba retroarch mgba start content={SECRET}",
        "fn+start": "2026-11-09T21:11:00 4 game OK gba retroarch mgba exit=0 "
                    f"end=quit-combo secs=60 content={SECRET}",
    })
    rc, out = run_script(console, capsys)
    assert rc == 0
    assert out.splitlines() == ["passo 1 open one: ok", "passo 2 close it: ok"]
    assert SECRET not in out


def test_open_ignores_another_system_and_close_accepts_fail(capsys):
    opened_seq = dev_game.open_sequence(0, 2, 9, 1)
    console = FakeConsole("dock_index=2 dock_count=9 games=5 focus=0\n", {
        opened_seq: "2026-11-09T21:10:00 4 game OK nes retroarch fceumm start",
    })
    rc, out = run_script(console, capsys)
    assert rc == 1 and out.startswith("passo 1 open one: FALHOU (timeout")
    console = FakeConsole("dock_index=2 dock_count=9 games=5 focus=0\n", {
        opened_seq: "2026-11-09T21:10:00 4 game OK gba retroarch mgba start",
        "fn+start": "2026-11-09T21:11:00 4 game FAIL gba retroarch mgba exit=1 end=normal secs=2",
    })
    rc, out = run_script(console, capsys)
    assert rc == 0


def test_open_fails_fast_on_start_failed(capsys):
    opened_seq = dev_game.open_sequence(0, 2, 9, 1)
    console = FakeConsole("dock_index=2 dock_count=9 games=5 focus=0\n", {
        opened_seq: "2026-11-09T21:10:00 4 game FAIL gba retroarch mgba start-failed no core",
    })
    rc, out = run_script(console, capsys)
    assert rc == 1
    assert out.startswith("passo 1 open one: FALHOU (the launcher reported start-failed)")


def test_open_fails_when_the_game_never_opens(capsys):
    console = FakeConsole("dock_index=2 dock_count=9 games=5 focus=0\n", {})
    rc, out = run_script(console, capsys)
    assert rc == 1
    assert out.startswith("passo 1 open one: FALHOU (timeout after 60s waiting for an event")


def test_open_of_a_system_without_games_presses_nothing(capsys):
    console = FakeConsole("dock_index=0 dock_count=8 games=0 focus=0\n", {})
    rc, out = run_script(console, capsys)
    assert rc == 1
    assert "FALHOU (system gba has no games in the launcher index)" in out
    assert console.keys == []
