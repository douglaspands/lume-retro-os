"""Reader and writer of the `r36os-evrec` recording format (change virtual-gamepad, D2).

Text format, version 1:

    # r36os-evrec 1 <ga36|r36s|vm>
    <ms> <type> <code> <value>          (one line per event, decimal integers)
    # end <ms>

`ms` is the time since the start of the recording, non-decreasing. `type` and `code` are
non-negative (Linux input_event type/code); `value` may be negative. The last line marks the
end and its `ms` must not be smaller than the last event. Blank lines are not allowed.
Recordings hold buttons only (no game names) and live in cache/, never in the repository.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

MAGIC = "# r36os-evrec"
VERSION = 1
CONSOLES = ("ga36", "r36s", "vm")


class EvrecError(ValueError):
    """A malformed recording; the message carries the line number when there is one."""


@dataclass(frozen=True)
class Event:
    ms: int
    type: int
    code: int
    value: int


@dataclass
class Recording:
    console: str
    events: list[Event] = field(default_factory=list)
    end_ms: int = 0


def _int(text: str, lineno: int, what: str) -> int:
    try:
        if text != text.strip() or not text.lstrip("-").isdigit():
            raise ValueError
        return int(text)
    except ValueError:
        raise EvrecError(f"line {lineno}: bad {what} `{text}`") from None


def parse(text: str, expect_console: str | None = None) -> Recording:
    """Parse a recording strictly; `expect_console` refuses a recording of another console."""
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    if not lines:
        raise EvrecError("line 1: empty recording")
    head = lines[0].split(" ")
    if len(head) != 4 or " ".join(head[:2]) != MAGIC:
        raise EvrecError("line 1: bad header (want `# r36os-evrec 1 <ga36|r36s|vm>`)")
    if head[2] != str(VERSION):
        raise EvrecError(f"line 1: unsupported version `{head[2]}`")
    if head[3] not in CONSOLES:
        raise EvrecError(f"line 1: unknown console `{head[3]}`")
    if expect_console is not None and head[3] != expect_console:
        raise EvrecError(f"recording is for {head[3]}, not {expect_console}")
    rec = Recording(head[3])
    last = 0
    ended = False
    for lineno, line in enumerate(lines[1:], start=2):
        if ended:
            raise EvrecError(f"line {lineno}: data after the end marker")
        if line.startswith("# end "):
            end = _int(line[6:], lineno, "end time")
            if end < last or end < 0:
                raise EvrecError(f"line {lineno}: end time before the last event")
            rec.end_ms = end
            ended = True
            continue
        parts = line.split(" ")
        if len(parts) != 4:
            raise EvrecError(f"line {lineno}: want `<ms> <type> <code> <value>`")
        ms, etype, code, value = (_int(p, lineno, n) for p, n in
                                  zip(parts, ("time", "type", "code", "value")))
        if ms < 0 or etype < 0 or code < 0:
            raise EvrecError(f"line {lineno}: negative time, type or code")
        if ms < last:
            raise EvrecError(f"line {lineno}: time goes backwards ({ms} < {last})")
        last = ms
        rec.events.append(Event(ms, etype, code, value))
    if not ended:
        raise EvrecError(f"line {len(lines) + 1}: missing end marker (`# end <ms>`)")
    return rec


def dumps(rec: Recording) -> str:
    """Serialize a recording (validates it by parsing the result back)."""
    out = [f"{MAGIC} {VERSION} {rec.console}"]
    out += [f"{e.ms} {e.type} {e.code} {e.value}" for e in rec.events]
    out.append(f"# end {rec.end_ms}")
    text = "\n".join(out) + "\n"
    parse(text)
    return text


def read(path: str | Path, expect_console: str | None = None) -> Recording:
    return parse(Path(path).read_text(encoding="ascii"), expect_console)


def write(path: str | Path, rec: Recording) -> None:
    Path(path).write_text(dumps(rec), encoding="ascii")
