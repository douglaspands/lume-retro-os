"""`r36os clean`: free the space taken by build leftovers that a new build recreates.

Dry run by default: it lists what it would remove, with sizes, and what it leaves for a
person to review. `--yes` removes only the first list.

Removed (all of it comes back by itself on the next build or download):
  - kernel build trees of old patch sets: <cache>/kbuild/<board>-<digest> whose digest is
    not the one of the current kernel/patches/ (each is 0.3 to 2.8 GB);
  - archived images in out/images/<image>/<timestamp>/ beyond the newest `keep` of each
    image, except `latest`, `flashed` (the build last written to a card, set by `flash`;
    also the one whose decompressed copy is in <cache>/flash/) and any timestamp cited in
    docs/, openspec/ or README.md (a cited build is evidence of a test);
  - the decompressed image kept by `flash` (<cache>/flash/) when it is not the latest
    console image;
  - abuild work folders (aports/*/src, pkg, tmp) and Python caches (__pycache__,
    .pytest_cache). abuild runs in a rootless container, so part of its files belong to
    a sub-UID: those are removed through `podman unshare`.

Listed for review, never removed: unknown entries directly under out/ and git worktrees
in out/worktrees/ whose branch is already merged into the current branch.

Never touched: var/ (test ROMs), out/repo (local package repository, hours to rebuild),
out/r36s-factory and out/r36s-bootlogs (evidence from the device, not reproducible), the
current kernel tree and build, ccache, distfiles, the abuild keys, vendor/ and vm/ of the
cache, .ctx/ and .venv/.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from r36os.paths import REPO_ROOT, cache_dir, out_dir

DEFAULT_KEEP = 3
# entries of out/ that a build or a test writes on purpose; anything else is listed for review
KNOWN_OUT = {
    "console", "ga36", "r36s", "vm", "images", "repo", "worktrees",
    "r36s-factory", "r36s-bootlogs",
}
TIMESTAMP = re.compile(r"\b(\d{8}-\d{6})\b")
SKIP_DIRS = {".git", ".venv", ".ctx", "out", "var", "node_modules"}


@dataclass
class Item:
    path: Path
    size: int
    reason: str


def size_of(path: Path) -> int:
    """Bytes under `path` (files counted once, symlinks not followed)."""
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def cited_timestamps(repo: Path) -> set[str]:
    """Build timestamps cited in the docs, the OpenSpec changes and the README."""
    found: set[str] = set()
    for base in (repo / "docs", repo / "openspec"):
        for p in base.rglob("*.md") if base.is_dir() else []:
            found |= set(TIMESTAMP.findall(p.read_text(errors="replace")))
    readme = repo / "README.md"
    if readme.exists():
        found |= set(TIMESTAMP.findall(readme.read_text(errors="replace")))
    return found


def _old_kernel_builds(cache: Path, digest: str) -> list[Item]:
    items = []
    for d in sorted((cache / "kbuild").glob("*-*")):
        if d.is_dir() and not d.name.endswith(f"-{digest}"):
            items.append(Item(d, size_of(d), "kernel build of an old patch set"))
    return items


def flashed_timestamps(cache: Path) -> set[str]:
    """Builds last written to a card: `flash` keeps their decompressed image in the cache."""
    return {m for f in (cache / "flash").glob("*.img") for m in TIMESTAMP.findall(f.name)}


def _old_images(out: Path, keep: int, cited: set[str]) -> list[Item]:
    items = []
    for image in sorted((out / "images").glob("*")):
        if not image.is_dir():
            continue
        # latest: the newest build; flashed: the build last written to a card (flash)
        pinned = {os.readlink(image / n) for n in ("latest", "flashed")
                  if (image / n).is_symlink()}
        builds = sorted((d for d in image.iterdir() if d.is_dir() and not d.is_symlink()
                         and TIMESTAMP.fullmatch(d.name)), key=lambda d: d.name)
        newest = {d.name for d in builds[-keep:]} if keep > 0 else set()
        for d in builds:
            if d.name in newest or d.name in pinned or d.name in cited:
                continue
            items.append(Item(d, size_of(d), f"archived {image.name} image, older than the "
                                             f"newest {keep}"))
    return items


def _stale_flash_cache(cache: Path, out: Path) -> list[Item]:
    latest = out / "images" / "console" / "latest"
    keep = f"console-{os.readlink(latest)}.img" if latest.is_symlink() else None
    items = []
    for f in sorted((cache / "flash").glob("*")):
        if f.is_file() and f.name != keep:
            items.append(Item(f, size_of(f), "decompressed image of an older build (flash)"))
    return items


def _work_folders(repo: Path) -> list[Item]:
    items = []
    for d in sorted((repo / "aports").glob("*/*")):
        if d.is_dir() and d.name in {"src", "pkg", "tmp"}:
            items.append(Item(d, size_of(d), "abuild work folder"))
    for root, dirs, _files in os.walk(repo):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for d in list(dirs):
            if d in {"__pycache__", ".pytest_cache"}:
                p = Path(root) / d
                items.append(Item(p, size_of(p), "Python cache"))
                dirs.remove(d)
    return items


def _merged_worktrees(repo: Path, out: Path) -> list[Item]:
    """Worktrees under out/worktrees whose branch is merged into HEAD (report only)."""
    try:
        listing = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                                 capture_output=True, text=True, check=True).stdout
        merged = subprocess.run(["git", "-C", str(repo), "branch", "--merged", "HEAD",
                                 "--format=%(refname:short)"],
                                capture_output=True, text=True, check=True).stdout.split()
    except (OSError, subprocess.CalledProcessError):
        return []
    items, path = [], None
    for line in listing.splitlines():
        if line.startswith("worktree "):
            path = Path(line.split(" ", 1)[1])
        elif line.startswith("branch ") and path is not None:
            branch = line.split(" ", 1)[1].removeprefix("refs/heads/")
            if (out / "worktrees") in path.parents and branch in merged:
                items.append(Item(path, size_of(path),
                                  f"worktree of {branch}, already merged: "
                                  f"git worktree remove {path}"))
    return items


def plan(repo: Path, out: Path, cache: Path, digest: str, keep: int = DEFAULT_KEEP,
         cited: set[str] | None = None) -> tuple[list[Item], list[Item]]:
    """(to remove, to review) for the given repository, out/ and cache."""
    if cited is None:
        cited = cited_timestamps(repo)
    # the build on the card stays archived, even when its decompressed copy goes
    cited = cited | flashed_timestamps(cache)
    remove = (_old_kernel_builds(cache, digest) + _old_images(out, keep, cited)
              + _stale_flash_cache(cache, out) + _work_folders(repo))
    review = [Item(p, size_of(p), "unknown entry in out/ (a one-off test?)")
              for p in sorted(out.glob("*")) if p.name not in KNOWN_OUT]
    review += _merged_worktrees(repo, out)
    return remove, review


def _allowed(path: Path, repo: Path, out: Path, cache: Path) -> bool:
    """Last check before removing: inside out/, the cache or the repo, never in var/."""
    p = path.resolve()
    if p == (repo / "var").resolve() or (repo / "var").resolve() in p.parents:
        return False
    protected = [out / "repo", out / "r36s-factory", out / "r36s-bootlogs"]
    if any(p == x.resolve() or x.resolve() in p.parents for x in protected):
        return False
    return any(base.resolve() in p.parents for base in (out, cache, repo))


def _remove_as_container_user(path: Path) -> None:
    """Remove files owned by a sub-UID of rootless podman (left by abuild in a container)."""
    subprocess.run(["podman", "unshare", "rm", "-rf", "--", str(path)], check=True)


def remove(items: list[Item], repo: Path, out: Path, cache: Path,
           failed: list[tuple[Item, str]] | None = None) -> int:
    """Remove the items; return the bytes freed. Items that fail go to `failed`."""
    for it in items:
        if not _allowed(it.path, repo, out, cache):
            raise RuntimeError(f"refusing to remove {it.path}")
    freed = 0
    for it in items:
        try:
            if it.path.is_dir() and not it.path.is_symlink():
                try:
                    shutil.rmtree(it.path)
                except PermissionError:
                    _remove_as_container_user(it.path)
            else:
                it.path.unlink()
            freed += it.size
        except (OSError, subprocess.CalledProcessError) as e:
            if failed is None:
                raise
            failed.append((it, str(e)))
    return freed


def _human(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n} B"


def main_clean(yes: bool = False, keep: int = DEFAULT_KEEP) -> int:
    from r36os.kernel import patches_digest

    repo, out, cache = REPO_ROOT, out_dir(), cache_dir()
    to_remove, to_review = plan(repo, out, cache, patches_digest(), keep)
    total = sum(i.size for i in to_remove)
    print(f"to remove ({len(to_remove)} items, {_human(total)}):")
    for i in to_remove:
        print(f"  {_human(i.size):>10}  {i.path}  ({i.reason})")
    if to_review:
        print(f"\nleft for review ({len(to_review)} items, not removed):")
        for i in to_review:
            print(f"  {_human(i.size):>10}  {i.path}  ({i.reason})")
    if not yes:
        print("\ndry run: nothing removed (run again with --yes to remove the first list)")
        return 0
    failed: list[tuple[Item, str]] = []
    freed = remove(to_remove, repo, out, cache, failed)
    print(f"\nremoved {len(to_remove) - len(failed)} items, {_human(freed)} freed")
    for it, err in failed:
        print(f"  not removed: {it.path}: {err}")
    return 1 if failed else 0
