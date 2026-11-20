"""Open and close a game through the launcher, without naming it (virtual-gamepad D5).

`open_game`: one console command prints ONLY numbers (the system's position in the Dock and the
number of games, read from the launcher's own index files); the PC builds the button sequence
from them and sends it with `dev keys`. The game name never leaves the console.

Navigation model, derived from lume/lume-ui/src/app.rs (see docs/BUILD.md):
- Dock tiles, left to right: Favorites, one tile per system WITH games in the catalog order
  (library.rs `Library::load` skips an empty or missing index), Recent, Settings. Left/Right
  wrap around; A enters the system's grid, with the focus on the first game (`open_grid`).
- The grid is sorted by name (lume-index sort_key), `cols` columns (4 in every shipped theme).
  Right moves +1 (no wrap), Down moves +cols (the last row clamps to the last game).
- A on a game opens its menu with "Start" first; A again launches.
- B closes an overlay, clears a filter, leaves the grid or Settings for the Dock; on the Dock
  it does nothing. Four B presses reach the Dock from any screen.
- The Dock focus is read from the launcher's state file (`dock=` line only, see
  lume-ui state.rs): written when the launcher leaves for a game and on every Dock move
  (since the R36S V2: before that a Dock moved by hand left the file stale and open_game
  started from the wrong tile), read when it starts again, on tmpfs, so a fresh boot has none
  (Favorites).
- `home`: B four times, then the Dock run to Favorites (tile 0).
"""
from __future__ import annotations

import re
import time

from lume_tool.dev import DevError

CATALOG = "/usr/share/lume/systems.json"
INDEX_DIR = "/storage/system/lume/cache/index"
GRID_COLS = 4
BACK_PRESSES = 4            # B from the deepest screen: submenu, menu, filter, grid -> Dock
FIXED_DOCK_TILES = 3        # Favorites + Recent + Settings around the systems
SYSTEM_ID = re.compile(r"[a-z0-9][a-z0-9_-]*")
STATE_FILE = "/run/user/$u/lume/state"     # $u = uid of the games user, 0 as fallback
INFO_LINE = re.compile(r"dock_index=(\d+) dock_count=(\d+) games=(\d+) focus=(\d+)")
SETTLE_MS = 300             # let the Dock/grid animations and the menu finish
GRID_MS = 500               # the grid maps the index before it takes input
CLOSE_SEQUENCE = "fn+start"
STATUS_FILE = "/run/user/$u/lume/status"   # lume-run: ui | game:<runner> | off
READY_TIMEOUT_S = 30.0      # the launcher starts again within a few seconds after a game
READY_POLL_S = 0.5
READY_SETTLE_S = 0.5        # first frame and the Dock state after the input is open


def info_command(system: str) -> str:
    """Remote POSIX sh (busybox) command:
    `dock_index=<n> dock_count=<n> games=<n> focus=<n>`.

    The system ids come from the image catalog in order; the games count is the u32 at offset
    8 of the system's index file (lume-index header). A system with no games (or no index) is
    not a Dock tile, so it prints dock_index=0 games=0. `focus` is the Dock tile the launcher
    will have focused: only the `dock=` line of the state file is read (never `game_path`):
    favorites -> 0, sys:<id> -> its Dock index, recent -> count-2, settings -> count-1; no
    file or an unknown value -> 0. Only numbers are printed."""
    if not SYSTEM_ID.fullmatch(system):
        raise DevError(f"bad system id `{system}`")
    return (
        f"u=$(id -u game 2>/dev/null || echo 0); "
        f"d=$(sed -n 's/^dock=//p' {STATE_FILE} 2>/dev/null | head -n 1); "
        f"n=0; di=0; g=0; fi=0; "
        f"for id in $(grep -o '\"id\": *\"[^\"]*\"' {CATALOG} | cut -d'\"' -f4); do "
        f"f={INDEX_DIR}/$id.bin; c=0; "
        f"[ -r \"$f\" ] && c=$(od -An -tu4 -j8 -N4 \"$f\" | tr -d ' '); "
        f"[ \"${{c:-0}}\" -gt 0 ] 2>/dev/null || continue; "
        f"n=$((n+1)); "
        f"if [ \"$id\" = {system} ]; then di=$n; g=$c; fi; "
        f"if [ \"$d\" = \"sys:$id\" ]; then fi=$n; fi; "
        f"done; "
        f"case \"$d\" in recent) fi=$((n+1));; settings) fi=$((n+2));; esac; "
        f"echo \"dock_index=$di dock_count=$((n+{FIXED_DOCK_TILES})) games=$g focus=$fi\""
    )


def parse_info(text: str) -> tuple[int, int, int, int]:
    """(dock_index, dock_count, games, focus) from the console output; else an error."""
    for line in text.splitlines():
        m = INFO_LINE.fullmatch(line.strip())
        if m:
            return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))
    raise DevError("unexpected answer to the game index query")


def dock_moves(from_focus: int, to_focus: int, count: int) -> str:
    """The shortest wrapping Left/Right run from one Dock tile to another ('' if none)."""
    right = (to_focus - from_focus) % count
    left = count - right
    if right == 0:
        return ""
    return f"right*{right}" if right <= left else f"left*{left}"


def grid_moves(position: int, cols: int = GRID_COLS) -> list[str]:
    """Down/Right presses from the first game to the game at `position` (1-based)."""
    row, col = divmod(position - 1, cols)
    return ([f"down*{row}"] if row else []) + ([f"right*{col}"] if col else [])


def open_sequence(from_focus: int, dock_index: int, dock_count: int, position: int) -> str:
    """The `dev keys` sequence that opens game `position` of the system on `dock_index`."""
    parts = [f"b*{BACK_PRESSES}", f"wait:{SETTLE_MS}"]
    moves = dock_moves(from_focus, dock_index, dock_count)
    if moves:
        parts += [moves, f"wait:{SETTLE_MS}"]
    parts += ["a", f"wait:{GRID_MS}", *grid_moves(position)]
    parts += ["a", f"wait:{SETTLE_MS}", "a"]       # enter the grid; game menu; Start
    return ",".join(parts)


def home_sequence(from_focus: int, dock_count: int) -> str:
    """The `dev keys` sequence from any screen to the Dock focused on Favorites."""
    parts = [f"b*{BACK_PRESSES}", f"wait:{SETTLE_MS}"]
    moves = dock_moves(from_focus, 0, dock_count)
    if moves:
        parts += [moves, f"wait:{SETTLE_MS}"]
    return ",".join(parts)


def ready_command() -> str:
    """Remote POSIX sh command: `ready` when the launcher is back on the screen and takes
    input, else `wait <state>` (task 6.4). Ready = lume-run's status file says `ui` (written
    before it starts lume-ui, read by lume-logd for the frontend state) AND a lume-ui process
    holds an evdev node open (lume-ui input.rs opens /dev/input/event* at start; a key sent
    before that is lost, which is how open_game right after close_game hit the previous
    game's menu). Prints only the state word (`ui`, `game:<runner>`, `off`)."""
    return (
        "u=$(id -u game 2>/dev/null || echo 0); "
        f"s=$(head -n 1 {STATUS_FILE} 2>/dev/null); s=${{s%% *}}; "
        "r=\"wait ${s:-none}\"; "
        "if [ \"$s\" = ui ]; then r='wait no-input'; "
        "for p in $(pidof lume-ui 2>/dev/null); do "
        "for f in /proc/$p/fd/*; do case \"$(readlink \"$f\" 2>/dev/null)\" in "
        "/dev/input/event*) r=ready; break 2;; esac; done; done; fi; "
        "echo \"$r\""
    )


class GameDriver:
    """`open` and `close` hooks of the runner's Context; `run`, `keys`, `sleep` and `now` are
    injectable."""

    def __init__(self, run, keys, sleep=time.sleep, now=time.monotonic,
                 ready_timeout: float = READY_TIMEOUT_S, settle_s: float = READY_SETTLE_S):
        self.run = run
        self.keys = keys
        self.sleep = sleep
        self.now = now
        self.ready_timeout = ready_timeout
        self.settle_s = settle_s

    def wait_ready(self) -> None:
        """Wait until the launcher is back on the screen (task 6.4), instead of a fixed
        time: after close_game the launcher takes a moment to start again."""
        end = self.now() + self.ready_timeout
        while True:
            state = self.run(ready_command()).strip()
            if state == "ready":
                if self.settle_s:
                    self.sleep(self.settle_s)
                return
            if self.now() >= end:
                raise DevError(f"the launcher is not back on the screen after "
                               f"{self.ready_timeout:g}s ({state or 'no answer'})")
            self.sleep(READY_POLL_S)

    def open(self, system: str, position: int) -> None:
        self.wait_ready()
        dock_index, dock_count, games, focus = parse_info(self.run(info_command(system)))
        if games == 0 or dock_index == 0:
            raise DevError(f"system {system} has no games in the launcher index")
        if position > games:
            raise DevError(f"position {position} is past the {games} games of {system}")
        self.keys(open_sequence(focus % dock_count, dock_index, dock_count, position))

    def close(self) -> None:
        self.keys(CLOSE_SEQUENCE)

    def home(self) -> None:
        """Back to the Dock with the focus on Favorites (tile 0), from wherever it is."""
        self.wait_ready()
        _, dock_count, _, focus = parse_info(self.run(info_command("none")))
        self.keys(home_sequence(focus % dock_count, dock_count))
