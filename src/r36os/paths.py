"""Repository, output and cache paths.

The build cache (kernel and U-Boot sources, build trees, ccache, distfiles, abuild keys,
factory areas, VM disk) lives in `.cache/` at the root of the main repository, ignored by
git. `$R36OS_CACHE` points it somewhere else. A git worktree shares the cache of the main
repository, so it does not rebuild the kernel from scratch.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def out_dir() -> Path:
    """Build artifacts directory (`out/`, ignored by git)."""
    return Path(os.environ.get("R36OS_OUT", REPO_ROOT / "out"))


@functools.lru_cache(maxsize=None)
def _main_repo_root(root: Path) -> Path:
    """Root of the main repository that `root` belongs to (itself when not a git checkout).

    In a git worktree, `--git-common-dir` is the `.git` of the main repository. The
    project must be the top level of the checkout: an extracted copy that happens to sit
    inside another repository keeps its own root.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--path-format=absolute",
             "--show-toplevel", "--git-common-dir"],
            capture_output=True, text=True, check=False)
    except OSError:
        return root
    lines = result.stdout.splitlines()
    if result.returncode != 0 or len(lines) != 2:
        return root
    toplevel, common_dir = (Path(line).resolve() for line in lines)
    if toplevel != root.resolve():
        return root
    return common_dir.parent


def cache_dir() -> Path:
    """Persistent build cache. Never creates anything (see `ensure_dir`).

    Order: `$R36OS_CACHE` (inside or outside the project), then `.cache/` at the root of
    the main repository (for a worktree, the repository it was added from; without git,
    `REPO_ROOT/.cache`).
    """
    env = os.environ.get("R36OS_CACHE")
    path = Path(env) if env else _main_repo_root(REPO_ROOT) / ".cache"
    return path.resolve()


def _create_cache_root(root: Path) -> None:
    """Create the cache root and mark it No-COW (Btrfs `C` attribute) so its files inherit it.

    The attribute only applies to files created afterwards, so it is set only here, on
    creation; a failure (no `chattr`, filesystem without No-COW) is a one-line warning.
    """
    root.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(["chattr", "+C", str(root)],
                                capture_output=True, text=True, check=False)
    except OSError as exc:
        reason = exc.strerror or str(exc)
    else:
        if result.returncode == 0:
            return
        lines = (result.stderr or result.stdout).strip().splitlines()
        reason = lines[-1] if lines else f"chattr exited with {result.returncode}"
    print(f"warning: could not set No-COW on {root}: {reason}", file=sys.stderr)


def ensure_dir(path: Path) -> Path:
    """Create `path`; when it is the first thing created in the cache, set up the cache root."""
    path = Path(path)
    root = cache_dir()
    target = path.resolve()
    if (target == root or root in target.parents) and not root.exists():
        _create_cache_root(root)
    path.mkdir(parents=True, exist_ok=True)
    return path
