"""Build parallelism and priority (build-speed D8): one place for the number of jobs.

The value comes from `--jobs N` (the CLI stores it in `LUME_JOBS`), then from the
`LUME_JOBS` environment variable, then from what the past builds learned (below), then
defaults to half the cores (minimum 1). Every `make -j`, `abuild` JOBS, `mksquashfs
-processors` and zstd thread count uses `jobs()`.

Learning the healthy parallelism (the user, 2026-11-20: a build that keeps pausing for heat
is slower; scale up while it stays cool, come down until the heat is tolerable): at the end
of every build of at least LEARN_MIN_SECONDS, `learn()` reads what the heat guard saw and
sets the jobs of the next builds in `<cache>/build-jobs.json`:

  * 3 or more heat pauses (or a heat abort): 2 jobs fewer; 1 or 2 pauses: 1 fewer;
  * no pause and a peak below the guard's resume point (limit - 10 C): 1 more, up to the
    number of cores;
  * no pause and a peak between the two: the healthy point, kept.

A run with `--jobs`/`LUME_JOBS` is recorded in the history but never moves the learned
value. The file keeps the last HISTORY_KEEP runs.
"""

from __future__ import annotations

import contextlib
import contextvars
import datetime
import json
import os
from pathlib import Path
from typing import Iterator

ENV_VAR = "LUME_JOBS"
# prefix of every podman command: conmon and the container inherit the low priority
PRIORITY_PREFIX = ["nice", "-n", "19", "ionice", "-c", "3"]
PRIORITY_TEXT = "nice 19, ionice idle"
LEARN_FILE_NAME = "build-jobs.json"
LEARN_MIN_SECONDS = 300.0   # shorter builds (a noarch fragment) say nothing about the heat
COOL_MARGIN = 10.0          # "cool": the peak stayed below the guard's resume point
HISTORY_KEEP = 30


def default_jobs() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


def learn_file() -> Path:
    from lume_tool.paths import cache_dir
    return cache_dir() / LEARN_FILE_NAME


def _read_learned(path: Path | None = None) -> dict:
    try:
        data = json.loads((path or learn_file()).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def learned_jobs(path: Path | None = None) -> int | None:
    """The jobs the past builds settled on, None without a valid record."""
    value = _read_learned(path).get("jobs")
    if isinstance(value, int) and value >= 1:
        return min(value, os.cpu_count() or value)
    return None


def source() -> str:
    """Where `jobs()` takes its value from: share, option, learned or default."""
    if _override.get() is not None:
        return "share"
    if os.environ.get(ENV_VAR, "").strip():
        return "option"
    return "learned" if learned_jobs() is not None else "default"


def next_jobs(used: int, pauses: int, max_cpu: float | None, limit: float,
              aborted: bool = False, cores: int | None = None) -> int:
    """The jobs of the next build after a run with `used` jobs (rules in the module text)."""
    cores = cores or os.cpu_count() or used
    if aborted or pauses >= 3:
        return max(1, used - 2)
    if pauses >= 1:
        return max(1, used - 1)
    if max_cpu is not None and max_cpu < limit - COOL_MARGIN:
        return min(cores, used + 1)
    return used


def learn(used: int, seconds: float, pauses: int, max_cpu: float | None, limit: float,
          aborted: bool = False, forced: bool = False, path: Path | None = None,
          now: datetime.datetime | None = None) -> str | None:
    """Record a finished build and set the jobs of the next ones. Returns the line to print,
    None when the build was too short to say anything."""
    if seconds < LEARN_MIN_SECONDS and not aborted:
        return None
    path = path or learn_file()
    data = _read_learned(path)
    before = data.get("jobs") if isinstance(data.get("jobs"), int) else None
    nxt = next_jobs(used, pauses, max_cpu, limit, aborted)
    entry = {"date": (now or datetime.datetime.now()).isoformat(timespec="seconds"),
             "jobs": used, "seconds": round(seconds), "pauses": pauses,
             "max_cpu": None if max_cpu is None else round(max_cpu, 1),
             "aborted": aborted, "forced": forced, "next": None if forced else nxt}
    history = [h for h in data.get("history", []) if isinstance(h, dict)][-(HISTORY_KEEP - 1):]
    history.append(entry)
    learned = before if forced else nxt
    out = {"jobs": learned, "history": history} if learned is not None else {"history": history}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(out, indent=1) + "\n")
    tmp.replace(path)
    peak = "n/a" if max_cpu is None else f"{max_cpu:.1f} C"
    seen = f"{pauses} heat pauses, peak {peak}" + (", heat abort" if aborted else "")
    if forced:
        return (f"jobs learning: {used} jobs given by --jobs/LUME_JOBS ({seen}); recorded, "
                f"the learned value stays {before if before is not None else 'unset'} ({path})")
    return f"jobs learning: {used} -> {nxt} for the next builds ({seen}) ({path})"


def parse_jobs(value: str | int) -> int:
    """A jobs value as a positive integer; raise ValueError otherwise."""
    n = int(value)
    if n < 1:
        raise ValueError(f"jobs must be at least 1, got {value}")
    return n


# per-pipeline override (task 6.6): the environment is process-wide, a context variable is
# not; each pipeline thread sets its own share of the total
_override: contextvars.ContextVar[int | None] = contextvars.ContextVar("lume_jobs", default=None)


def jobs() -> int:
    """Number of parallel jobs: the pipeline's share if one is set (`share`), else
    LUME_JOBS if set, else what the past builds learned, else half the cores (minimum 1)."""
    own = _override.get()
    if own is not None:
        return own
    raw = os.environ.get(ENV_VAR, "").strip()
    if raw:
        return parse_jobs(raw)
    learned = learned_jobs()
    return learned if learned is not None else default_jobs()


def split(total: int, parts: int = 2) -> list[int]:
    """Share `total` jobs among `parts` pipelines: 8 -> [4, 4], 7 -> [4, 3]. Empty list
    when there are fewer jobs than pipelines: they then run one after the other."""
    if total < parts:
        return []
    base, extra = divmod(total, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


@contextlib.contextmanager
def share(n: int) -> Iterator[None]:
    """Inside the block (this thread/context) `jobs()` returns `n`."""
    token = _override.set(parse_jobs(n))
    try:
        yield
    finally:
        _override.reset(token)


def set_jobs(value: int | None) -> None:
    """Make `value` (the --jobs option) win over the environment; None keeps it."""
    if value is not None:
        os.environ[ENV_VAR] = str(parse_jobs(value))


def summary() -> str:
    """The one line printed at the start of a build."""
    how = {"option": ", given", "learned": ", learned from past builds"}.get(source(), "")
    return f"jobs: {jobs()} ({os.cpu_count()} cores{how}), priority: {PRIORITY_TEXT}"
