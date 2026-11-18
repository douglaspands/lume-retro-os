"""`lume dev watch <fragment>`: build and hot-push a fragment on every saved file (D19).

Dependency-free: the input files of the fragment are polled (mtime and size, every 0.5 s).
Changes are grouped: the build starts after DEBOUNCE seconds without a new change, one line
is printed per cycle, and a change made while a cycle runs starts another cycle after it.
"""

from __future__ import annotations

import contextlib
import os
import time
from pathlib import Path

from lume_tool import fragments as frag
from lume_tool.paths import REPO_ROOT

POLL = 0.5
DEBOUNCE = 1.0
SOURCE_TREES = {"lume-launcher": "lume"}   # fragment -> source tree staged into its aport
SKIP_DIRS = frozenset({"target", "vendor", ".git"})


def snapshot(fragment: str, repo: Path | None = None) -> dict[str, tuple[int, int]]:
    """path -> (mtime_ns, size) of every input file of the fragment."""
    repo = repo or REPO_ROOT
    out: dict[str, tuple[int, int]] = {}

    def add(p: Path) -> None:
        try:
            st = p.lstat()
        except OSError:
            return
        out[str(p)] = (st.st_mtime_ns, st.st_size)

    for _, p in frag.aport_files(repo / "aports" / fragment):
        add(p)
    tree = SOURCE_TREES.get(fragment)
    if tree:
        for root, dirs, files in os.walk(repo / tree):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
            for f in files:
                add(Path(root) / f)
    return out


def changed_paths(old: dict, new: dict) -> set[str]:
    return {p for p in old.keys() | new.keys() if old.get(p) != new.get(p)}


class Watcher:
    """Change grouping with an injectable clock, snapshot, build and push."""

    def __init__(self, fragment: str, take, build, push, emit=print, clock=time.monotonic,
                 debounce: float = DEBOUNCE):
        self.fragment = fragment
        self.take, self.build, self.push = take, build, push
        self.emit, self.clock, self.debounce = emit, clock, debounce
        self.seen = take()          # last snapshot looked at
        self.pending: set[str] = set()
        self.last_change = 0.0

    def poll(self) -> bool:
        """One look at the files; run a cycle when the changes settled. True if one ran."""
        cur = self.take()
        if cur != self.seen:
            self.pending |= changed_paths(self.seen, cur)
            self.seen = cur
            self.last_change = self.clock()
            return False
        if self.pending and self.clock() - self.last_change >= self.debounce:
            self.cycle()
            return True
        return False

    def cycle(self) -> None:
        count = len(self.pending)
        self.pending = set()
        start = self.clock()
        head = (f"watch {self.fragment}: changed {count} file{'s' if count != 1 else ''}")
        try:
            self.build(self.fragment)
        except (Exception, SystemExit) as e:
            self.emit(f"{head}, build failed: {_why(e)}")
        else:
            built = self.clock() - start
            try:
                detail = self.push(self.fragment)
            except (Exception, SystemExit) as e:
                self.emit(f"{head}, build {built:.0f}s, hot push failed: {_why(e)}")
            else:
                self.emit(f"{head}, build {built:.0f}s, hot push ok" +
                          (f" ({detail})" if detail else ""))
        # what changed while the cycle ran starts another one
        cur = self.take()
        if cur != self.seen:
            self.pending |= changed_paths(self.seen, cur)
            self.seen = cur
            self.last_change = self.clock()


def _why(e: BaseException) -> str:
    return " ".join(str(e).split()) or type(e).__name__


@contextlib.contextmanager
def _output_to(log: Path):
    """Send stdout and stderr, at the file descriptor level (so child processes too), to
    `log` (rewritten each cycle) while the block runs."""
    import sys

    log.parent.mkdir(parents=True, exist_ok=True)
    sys.stdout.flush()
    sys.stderr.flush()
    saved = os.dup(1), os.dup(2)
    with open(log, "w", buffering=1) as f:
        os.dup2(f.fileno(), 1)
        os.dup2(f.fileno(), 2)
        try:
            with contextlib.redirect_stdout(f), contextlib.redirect_stderr(f):
                yield
        finally:
            sys.stdout.flush()
            sys.stderr.flush()
            os.dup2(saved[0], 1)
            os.dup2(saved[1], 2)
            os.close(saved[0])
            os.close(saved[1])


def cmd_watch(fragment: str, host: str | None) -> int:
    from lume_tool import fragment_build, push_hot
    from lume_tool.push import PushError, Remote

    if reason := push_hot.refusal(fragment):
        raise PushError(reason)
    fragment_build.plan_fragments([fragment])      # unknown names fail before the loop
    remote = Remote(host) if host else Remote()

    log = REPO_ROOT / "out" / "dev-watch" / f"{fragment}.log"

    def build(name: str) -> None:
        # one line per cycle: the build output (podman included) goes to the log
        try:
            with _output_to(log):
                fragment_build.build_fragments([name])
        except (Exception, SystemExit) as e:
            raise RuntimeError(f"{_why(e)} (log: {log})") from e

    def push(name: str) -> str:
        lines: list[str] = []
        push_hot.push_hot(name, remote=remote, out=lines.append)
        names = [ln.split(":", 1)[1].split()[0] for ln in lines if ln.startswith("restart: ")
                 and "no service" not in ln]
        return "restart " + ", ".join(names) if names else "no service restarted"

    def take():
        return snapshot(fragment)

    w = Watcher(fragment, take, build, push, emit=lambda s: print(s, flush=True))
    print(f"watching {fragment} ({len(w.seen)} files); Ctrl-C to stop", flush=True)
    try:
        while True:
            time.sleep(POLL)
            w.poll()
    except KeyboardInterrupt:
        print("\nwatch stopped")
    return 0
