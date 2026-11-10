"""Repository, output and cache paths (the cache lives outside the repository)."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def out_dir() -> Path:
    """Build artifacts directory (`out/`, ignored by git)."""
    return Path(os.environ.get("R36OS_OUT", REPO_ROOT / "out"))


def cache_dir() -> Path:
    """Persistent cache outside the repository (abuild keys, distfiles, ccache, apk).

    Order: `$R36OS_CACHE`, `$XDG_CACHE_HOME/r36os`, `~/.cache/r36os`.
    """
    env = os.environ.get("R36OS_CACHE")
    if env:
        path = Path(env)
    else:
        base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
        path = Path(base) / "r36os"
    path = path.resolve()
    if path == REPO_ROOT or REPO_ROOT in path.parents:
        raise ValueError(f"the cache must be outside the repository: {path}")
    return path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
