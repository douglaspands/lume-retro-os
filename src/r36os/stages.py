"""Per-stage timing of a build, printed at the end (also on error).

    timer = StageTimer()
    try:
        with timer.stage("kernel"):
            ...
        timer.skip("u-boot", "not needed")
    finally:
        timer.print_summary()

Other sections (e.g. the heat guard) append their own lines with `add_line`.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Callable, Iterator


def format_duration(seconds: float) -> str:
    """1h02m03s, 4m05s or 6.2s."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    whole = int(round(seconds))
    h, rest = divmod(whole, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h{m:02d}m{s:02d}s" if h else f"{m}m{s:02d}s"


class StageTimer:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 out: Callable[[str], None] = lambda s: print(s, flush=True)) -> None:
        self._clock = clock
        self._out = out
        self._start = clock()
        # (name, seconds | None, note): seconds None means skipped
        self._rows: list[tuple[str, float | None, str]] = []
        self._extra: list[str] = []

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        t0 = self._clock()
        try:
            yield
        except BaseException:
            self._rows.append((name, self._clock() - t0, "failed"))
            raise
        self._rows.append((name, self._clock() - t0, ""))

    def skip(self, name: str, reason: str = "") -> None:
        self._rows.append((name, None, reason))

    def add_line(self, line: str) -> None:
        """An extra summary line from another section, printed after the total."""
        self._extra.append(line)

    def total(self) -> float:
        return self._clock() - self._start

    def summary(self) -> list[str]:
        width = max((len(r[0]) for r in self._rows), default=0)
        lines = ["build summary:"]
        for name, secs, note in self._rows:
            if secs is None:
                value = "skipped" + (f" ({note})" if note else "")
            else:
                value = format_duration(secs) + (f" ({note})" if note else "")
            lines.append(f"  {name.ljust(width)}  {value}")
        lines.append(f"  {'total'.ljust(width)}  {format_duration(self.total())}")
        lines.extend(self._extra)
        return lines

    def print_summary(self) -> None:
        for line in self.summary():
            self._out(line)
