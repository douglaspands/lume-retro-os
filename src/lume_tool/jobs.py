"""Build parallelism and priority (build-speed D8): one place for the number of jobs.

The value comes from `--jobs N` (the CLI stores it in `LUME_JOBS`), then from the
`LUME_JOBS` environment variable, then defaults to half the cores (minimum 1). Every
`make -j`, `abuild` JOBS, `mksquashfs -processors` and zstd thread count uses `jobs()`.
"""

from __future__ import annotations

import contextlib
import contextvars
import os
from typing import Iterator

ENV_VAR = "LUME_JOBS"
# prefix of every podman command: conmon and the container inherit the low priority
PRIORITY_PREFIX = ["nice", "-n", "19", "ionice", "-c", "3"]
PRIORITY_TEXT = "nice 19, ionice idle"


def default_jobs() -> int:
    return max(1, (os.cpu_count() or 2) // 2)


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
    LUME_JOBS if set, else half the cores (minimum 1)."""
    own = _override.get()
    if own is not None:
        return own
    raw = os.environ.get(ENV_VAR, "").strip()
    return parse_jobs(raw) if raw else default_jobs()


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
    return f"jobs: {jobs()} ({os.cpu_count()} cores), priority: {PRIORITY_TEXT}"
