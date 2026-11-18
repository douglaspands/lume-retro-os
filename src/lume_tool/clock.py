"""The PC as a real time source for the console (device-fixes 9.1, D15).

The console has no battery-backed clock, so `lume push` and `lume dev` set it over the cable.
One function builds the remote command and both commands use it. The console side is
`lume-clock set` (system time, RTC and the saved clock on the card, plus the `clock` event);
an image that does not have it yet falls back to `date -u -s` and `hwclock -w`.
"""

from __future__ import annotations

import time
from typing import Callable


def set_clock_command(epoch: int, source: str = "pc") -> str:
    """The shell command that sets the console clock to `epoch` (seconds, UTC)."""
    e = int(epoch)
    return (f"if [ -x /usr/bin/lume-clock ]; then lume-clock set {e} {source}; "
            f"else date -u -s @{e} >/dev/null && hwclock -w -u; fi")


def sync_console_clock(run: Callable[[str], object], now: Callable[[], float] = time.time) -> bool:
    """Set the console clock from this PC. Best effort: a failure never stops the caller
    (the clock is a convenience; True when the command ran without an error)."""
    try:
        run(set_clock_command(int(now())))
    except Exception:
        return False
    return True
