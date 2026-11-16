"""Build parallelism and priority (build-speed D8): one place for the number of jobs.

The value comes from `--jobs N` (the CLI stores it in `R36OS_JOBS`), then from the
`R36OS_JOBS` environment variable, then defaults to half the cores (minimum 1). Every
`make -j`, `abuild` JOBS, `mksquashfs -processors` and zstd thread count uses `jobs()`.
"""

from __future__ import annotations

import os

ENV_VAR = "R36OS_JOBS"
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


def jobs() -> int:
    """Number of parallel jobs: R36OS_JOBS if set, else half the cores (minimum 1)."""
    raw = os.environ.get(ENV_VAR, "").strip()
    return parse_jobs(raw) if raw else default_jobs()


def set_jobs(value: int | None) -> None:
    """Make `value` (the --jobs option) win over the environment; None keeps it."""
    if value is not None:
        os.environ[ENV_VAR] = str(parse_jobs(value))


def summary() -> str:
    """The one line printed at the start of a build."""
    return f"jobs: {jobs()} ({os.cpu_count()} cores), priority: {PRIORITY_TEXT}"
