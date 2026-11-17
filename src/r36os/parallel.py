"""Running the armv7 and aarch64 pipelines side by side (build-speed task 6.6).

Each pipeline runs in its own thread with its share of the job limit (`jobs.share`), its
own StageTimer and its output lines prefixed with `[armv7]` / `[aarch64]`. The prefixing
is line-buffered per pipeline, so two pipelines never interleave inside a line:

* Python output goes through `install()`, a stdout/stderr proxy that knows which pipeline
  the writing thread belongs to;
* the output of containers goes through `run_process()`, which reads the child's merged
  output line by line and prints it (so it also goes through the proxy).

When a pipeline fails, the others are cancelled: their running child processes get a
SIGTERM (podman forwards it to the container) and their next container command is refused.
"""

from __future__ import annotations

import contextlib
import contextvars
import signal
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable, Iterator, Sequence

from r36os import jobs as jobs_mod
from r36os.stages import StageTimer


class Cancelled(Exception):
    """Another pipeline failed: this one stops at its next container command."""


@dataclass
class Pipeline:
    label: str
    cancel: threading.Event = field(default_factory=threading.Event)
    procs: set = field(default_factory=set)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def stop(self) -> None:
        """Cancel this pipeline and terminate its running child processes."""
        self.cancel.set()
        with self.lock:
            procs = list(self.procs)
        for p in procs:
            with contextlib.suppress(OSError):
                p.send_signal(signal.SIGTERM)


_current: contextvars.ContextVar[Pipeline | None] = contextvars.ContextVar(
    "r36os_pipeline", default=None)


def current() -> Pipeline | None:
    return _current.get()


def check_cancel() -> None:
    p = current()
    if p is not None and p.cancel.is_set():
        raise Cancelled(f"[{p.label}] cancelled: another pipeline failed")


class PrefixedStream:
    """File-like proxy: lines written from a pipeline get its `[label] ` prefix.

    Partial lines are held back per pipeline until their newline arrives (or `flush_all`),
    and each finished line is written under one lock, so lines never interleave.
    """

    def __init__(self, real) -> None:
        self._real = real
        self._lock = threading.Lock()
        self._partial: dict[str, str] = {}

    def write(self, s: str) -> int:
        p = current()
        with self._lock:
            if p is None:
                self._real.write(s)
                return len(s)
            buf = self._partial.get(p.label, "") + s
            *lines, rest = buf.split("\n")
            self._partial[p.label] = rest
            for line in lines:
                self._real.write(f"[{p.label}] {line}\n")
        return len(s)

    def flush(self) -> None:
        with self._lock:
            self._real.flush()

    def flush_all(self) -> None:
        """Write what is left of unfinished lines (end of the run)."""
        with self._lock:
            for label, rest in self._partial.items():
                if rest:
                    self._real.write(f"[{label}] {rest}\n")
            self._partial.clear()
            self._real.flush()

    def __getattr__(self, name):
        return getattr(self._real, name)


@contextlib.contextmanager
def install() -> Iterator[None]:
    """Replace sys.stdout/sys.stderr with prefixing proxies for the block."""
    old = sys.stdout, sys.stderr
    out, err = PrefixedStream(old[0]), PrefixedStream(old[1])
    sys.stdout, sys.stderr = out, err
    try:
        yield
    finally:
        out.flush_all()
        err.flush_all()
        sys.stdout, sys.stderr = old


def run_process(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """`subprocess.run` for a command of a pipeline: merged output, printed line by line
    (so it gets the prefix), and registered so that a failed sibling can terminate it.
    Commands that capture their own output are left alone."""
    check = kw.pop("check", False)
    if "stdout" in kw or "stderr" in kw or kw.get("capture_output"):
        return subprocess.run(cmd, check=check, **kw)
    check_cancel()
    pipe = current()
    with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                          errors="replace", **kw) as proc:
        with pipe.lock:
            pipe.procs.add(proc)
        try:
            for line in proc.stdout:
                print(line.rstrip("\n"), flush=True)
            rc = proc.wait()
        finally:
            with pipe.lock:
                pipe.procs.discard(proc)
    if pipe.cancel.is_set() and rc != 0:
        raise Cancelled(f"[{pipe.label}] cancelled: another pipeline failed")
    if check and rc != 0:
        raise subprocess.CalledProcessError(rc, cmd)
    return subprocess.CompletedProcess(cmd, rc)


@dataclass
class Result:
    label: str
    timer: StageTimer
    error: BaseException | None = None


class PipelineError(Exception):
    """One or more pipelines failed; `results` has every pipeline, in order."""

    def __init__(self, results: Sequence[Result]) -> None:
        failed = [r for r in results if r.error is not None]
        super().__init__("; ".join(f"[{r.label}] {r.error}" for r in failed))
        self.results = list(results)


def run_pipelines(specs: Sequence[tuple[str, Callable[[StageTimer], None]]],
                  total_jobs: int | None = None,
                  timer_factory: Callable[[str], StageTimer] | None = None) -> list[Result]:
    """Run each `(label, fn(timer))` in its own thread and return one Result per pipeline.

    The job limit is split with `jobs.split`; with fewer jobs than pipelines they run one
    after the other with 1 job each. The first failure cancels the others. Raises
    PipelineError (after every pipeline has stopped) when any failed.
    """
    total = jobs_mod.jobs() if total_jobs is None else total_jobs
    shares = jobs_mod.split(total, len(specs))
    sequential = not shares
    if sequential:
        shares = [1] * len(specs)
    make_timer = timer_factory or (lambda label: StageTimer())
    pipes = [Pipeline(label) for label, _ in specs]
    results = [Result(label, make_timer(label)) for label, _ in specs]
    failed = threading.Event()

    def work(i: int) -> None:
        pipe, res = pipes[i], results[i]
        _current.set(pipe)
        try:
            check_cancel()
            with jobs_mod.share(shares[i]):
                print(f"jobs: {shares[i]}", flush=True)
                specs[i][1](res.timer)
        except BaseException as e:  # noqa: BLE001 - reported by the caller
            res.error = e
            if not isinstance(e, Cancelled):
                print(f"error: {e}", flush=True)
            failed.set()
            for other in pipes:
                if other is not pipe:
                    other.stop()

    with install():
        if sequential:
            for i in range(len(specs)):
                if failed.is_set():
                    pipes[i].cancel.set()
                work(i)
        else:
            threads = [threading.Thread(target=work, args=(i,), name=f"pipeline-{p.label}")
                       for i, p in enumerate(pipes)]
            for t in threads:
                t.start()
            try:
                for t in threads:
                    t.join()
            except BaseException:  # Ctrl-C: stop the children, then wait for the threads
                for p in pipes:
                    p.stop()
                for t in threads:
                    t.join()
                raise
    if any(r.error is not None for r in results):
        raise PipelineError(results)
    return results
