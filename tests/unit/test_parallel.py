"""Parallel armv7/aarch64 pipelines (build-speed task 6.6)."""

import io
import sys
import threading

import pytest

from lume_tool import jobs, parallel
from lume_tool.stages import StageTimer


def test_split_even_odd_and_too_few():
    assert jobs.split(8) == [4, 4]
    assert jobs.split(7) == [4, 3]
    assert jobs.split(2) == [1, 1]
    assert jobs.split(1) == []  # fewer jobs than pipelines: sequential


def test_share_overrides_jobs_only_inside_the_block(monkeypatch):
    monkeypatch.setenv(jobs.ENV_VAR, "8")
    with jobs.share(3):
        assert jobs.jobs() == 3
    assert jobs.jobs() == 8


def test_prefixed_stream_keeps_lines_whole_and_prefixed():
    real = io.StringIO()
    stream = parallel.PrefixedStream(real)
    a, b = parallel.Pipeline("armv7"), parallel.Pipeline("aarch64")

    def write(pipe, text):
        parallel._current.set(pipe)
        stream.write(text)

    def in_thread(pipe, text):
        t = threading.Thread(target=write, args=(pipe, text))
        t.start()
        t.join()

    in_thread(a, "one ")
    in_thread(b, "other\nsecond")
    in_thread(a, "line\n")
    stream.write("plain\n")  # not in a pipeline: untouched
    stream.flush_all()
    lines = real.getvalue().splitlines()
    assert "[armv7] one line" in lines
    assert "[aarch64] other" in lines
    assert "[aarch64] second" in lines
    assert "plain" in lines


def test_run_pipelines_splits_jobs_prefixes_and_keeps_timers_apart(capsys):
    seen = {}

    def make(label):
        def run(timer):
            seen[label] = jobs.jobs()
            with timer.stage("work"):
                print(f"hello from {label}")
        return label, run

    timers = {}

    def factory(label):
        timers[label] = StageTimer(title=f"build summary [{label}]:")
        return timers[label]

    results = parallel.run_pipelines([make("armv7"), make("aarch64")], total_jobs=7,
                                     timer_factory=factory)
    out = capsys.readouterr().out
    assert seen == {"armv7": 4, "aarch64": 3}
    assert "[armv7] hello from armv7" in out
    assert "[aarch64] hello from aarch64" in out
    assert [r.label for r in results] == ["armv7", "aarch64"]
    assert timers["armv7"].summary()[0] == "build summary [armv7]:"
    assert any("work" in line for line in timers["aarch64"].summary())
    assert sys.stdout is not None and not isinstance(sys.stdout, parallel.PrefixedStream)


def test_run_pipelines_with_one_job_runs_one_after_the_other():
    order = []
    active = []

    def make(label):
        def run(timer):
            active.append(label)
            assert len(active) == 1
            order.append((label, jobs.jobs()))
            active.remove(label)
        return label, run

    parallel.run_pipelines([make("armv7"), make("aarch64")], total_jobs=1)
    assert order == [("armv7", 1), ("aarch64", 1)]


def test_failure_cancels_the_other_pipeline_and_reports_both():
    started = threading.Event()

    def failing(timer):
        started.wait(5)
        with timer.stage("boom"):
            raise RuntimeError("compile failed")

    def waiting(timer):
        started.set()
        pipe = parallel.current()
        assert pipe.cancel.wait(5)
        parallel.check_cancel()  # what the next container command does

    with pytest.raises(parallel.PipelineError) as info:
        parallel.run_pipelines([("armv7", failing), ("aarch64", waiting)], total_jobs=4)
    r = {x.label: x for x in info.value.results}
    assert isinstance(r["armv7"].error, RuntimeError)
    assert isinstance(r["aarch64"].error, parallel.Cancelled)
    assert "compile failed" in str(info.value)
    assert any("failed" in line for line in r["armv7"].timer.summary())


def test_run_process_prefixes_child_output_and_honours_check(capsys):
    def run(timer):
        parallel.run_process([sys.executable, "-c", "print('a'); print('b')"], check=True)
        with pytest.raises(Exception):
            parallel.run_process([sys.executable, "-c", "raise SystemExit(3)"], check=True)

    parallel.run_pipelines([("armv7", run)], total_jobs=2)
    out = capsys.readouterr().out
    assert "[armv7] a" in out and "[armv7] b" in out
