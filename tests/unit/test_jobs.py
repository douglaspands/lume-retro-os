"""build-speed 2.2: low priority podman and a single place for the number of jobs (D8)."""

import os

import pytest

from lume_tool import cli, jobs, kernel, packages, rootfs, uboot
from lume_tool.container import Container


@pytest.fixture(autouse=True)
def _own_cache(tmp_path, monkeypatch):
    # the learned jobs live in the cache: never read or write the PC's real one
    monkeypatch.setenv("LUME_CACHE", str(tmp_path / "cache"))


def test_podman_argv_starts_with_nice_and_ionice():
    argv = Container(image="img").argv("true")
    assert argv[:8] == ["nice", "-n", "19", "ionice", "-c", "3", "podman", "run"]


def test_jobs_default_is_half_the_cores_minimum_one(monkeypatch):
    monkeypatch.delenv("LUME_JOBS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert jobs.jobs() == 8
    monkeypatch.setattr(os, "cpu_count", lambda: 1)
    assert jobs.jobs() == 1
    monkeypatch.setattr(os, "cpu_count", lambda: None)
    assert jobs.jobs() >= 1


def test_jobs_env_and_option_precedence(monkeypatch):
    monkeypatch.setenv("LUME_JOBS", "3")
    assert jobs.jobs() == 3
    jobs.set_jobs(5)  # the option beats the environment
    assert jobs.jobs() == 5
    jobs.set_jobs(None)
    assert jobs.jobs() == 5
    with pytest.raises(ValueError):
        jobs.set_jobs(0)


def test_cli_prints_one_line_and_applies_option(monkeypatch, capsys):
    monkeypatch.setenv("LUME_JOBS", "2")
    monkeypatch.setattr(packages, "build_packages", lambda *a, **k: None)
    assert cli.main(["pkg", "vm", "x", "--jobs", "4"]) == 0
    out = capsys.readouterr().out
    assert out.count("jobs: 4") == 1
    assert "nice 19" in out and "ionice" in out


def test_make_scripts_carry_jobs(monkeypatch):
    monkeypatch.setenv("LUME_JOBS", "6")
    assert "-j{jobs}" in kernel._KERNEL_SCRIPT
    assert "-j{jobs}" in uboot._SCRIPT
    assert "nproc" not in kernel._KERNEL_SCRIPT + uboot._SCRIPT


def test_mksquashfs_carries_processors(tmp_path, monkeypatch):
    monkeypatch.setenv("LUME_JOBS", "6")
    seen = []

    class FakeContainer:
        def __init__(self, image, volumes):
            pass

        def sh(self, script):
            seen.append(script)

    monkeypatch.setattr(rootfs, "Container", FakeContainer)
    monkeypatch.setattr(rootfs, "ensure_builder", lambda t: "b")
    rootfs.make_modules_image(tmp_path / "modules.tar", tmp_path / "modules")
    assert "-processors 6" in seen[0]
    dest = tmp_path / "SYSTEM"
    dest.write_bytes(b"x")
    rootfs.make_system(None, tmp_path / "rootfs.tar", dest)
    assert "-processors 6" in seen[1]


def test_abuild_container_env_carries_jobs(monkeypatch):
    from lume_tool.targets import get_target

    monkeypatch.setenv("LUME_JOBS", "6")
    monkeypatch.setattr(packages, "ensure_builder", lambda t: "b")
    c = packages._container(get_target("vm"), packages.REPO_ROOT / "aports")
    assert c.env["JOBS"] == "6" and c.env["MAKEFLAGS"] == "-j6"
    assert "$JOBS" in packages._SETUP_KEY


def test_archive_zstd_uses_jobs_workers(tmp_path, monkeypatch):
    from lume_tool import archive

    monkeypatch.setenv("LUME_JOBS", "2")
    src = tmp_path / "a.img"
    src.write_bytes(b"abc" * 1000)
    raw, _ = archive._compress(src, tmp_path / "a.img.zst")
    assert (tmp_path / "a.img.zst").exists() and raw


# --- learning the healthy parallelism (the user, 2026-11-20) ---

def test_next_jobs_rules():
    # 3+ pauses: 2 fewer; 1-2 pauses: 1 fewer; cool (below limit - 10): 1 more; else kept
    assert jobs.next_jobs(8, 22, 85.1, 85.0, cores=16) == 6
    assert jobs.next_jobs(8, 3, 85.0, 85.0, cores=16) == 6
    assert jobs.next_jobs(8, 1, 85.0, 85.0, cores=16) == 7
    assert jobs.next_jobs(8, 0, 74.9, 85.0, cores=16) == 9
    assert jobs.next_jobs(8, 0, 75.0, 85.0, cores=16) == 8
    assert jobs.next_jobs(8, 0, 84.9, 85.0, cores=16) == 8
    assert jobs.next_jobs(8, 0, None, 85.0, cores=16) == 8
    # a heat abort counts as many pauses; never below 1 nor above the cores
    assert jobs.next_jobs(8, 0, 92.5, 85.0, aborted=True, cores=16) == 6
    assert jobs.next_jobs(2, 5, 85.0, 85.0, cores=16) == 1
    assert jobs.next_jobs(1, 1, 85.0, 85.0, cores=16) == 1
    assert jobs.next_jobs(16, 0, 60.0, 85.0, cores=16) == 16


def test_learning_moves_the_default_and_keeps_a_history(monkeypatch, tmp_path):
    monkeypatch.delenv("LUME_JOBS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert (jobs.jobs(), jobs.source()) == (8, "default")
    line = jobs.learn(8, 3600, 22, 85.1, 85.0)
    assert "8 -> 6" in line and "22 heat pauses" in line
    assert (jobs.jobs(), jobs.source()) == (6, "learned")
    assert "learned from past builds" in jobs.summary()
    # a cool build scales up again, one at a time
    jobs.learn(6, 3600, 0, 70.0, 85.0)
    assert jobs.jobs() == 7
    data = __import__("json").loads(jobs.learn_file().read_text())
    assert data["jobs"] == 7 and [h["jobs"] for h in data["history"]] == [8, 6]
    assert data["history"][0] == {**data["history"][0], "pauses": 22, "max_cpu": 85.1,
                                  "next": 6, "forced": False, "aborted": False}
    assert not list(jobs.learn_file().parent.glob("*.tmp"))


def test_short_builds_teach_nothing(monkeypatch):
    # a noarch fragment of a minute says nothing about the heat of a compile
    assert jobs.learn(8, jobs.LEARN_MIN_SECONDS - 1, 0, 60.0, 85.0) is None
    assert not jobs.learn_file().exists()
    # but a heat abort always counts
    assert "8 -> 6" in jobs.learn(8, 30, 0, 93.0, 85.0, aborted=True)


def test_a_given_jobs_value_is_recorded_but_never_moves_the_learned_one(monkeypatch):
    monkeypatch.delenv("LUME_JOBS", raising=False)
    jobs.learn(8, 3600, 1, 85.0, 85.0)                 # learned: 7
    line = jobs.learn(12, 3600, 30, 86.0, 85.0, forced=True)
    assert "stays 7" in line
    assert jobs.learned_jobs() == 7
    monkeypatch.setenv("LUME_JOBS", "3")
    assert (jobs.jobs(), jobs.source()) == (3, "option")


def test_history_is_bounded_and_a_broken_file_is_ignored(monkeypatch):
    monkeypatch.delenv("LUME_JOBS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    for _ in range(jobs.HISTORY_KEEP + 5):
        jobs.learn(8, 3600, 0, 80.0, 85.0)
    data = __import__("json").loads(jobs.learn_file().read_text())
    assert len(data["history"]) == jobs.HISTORY_KEEP
    jobs.learn_file().write_text("{broken")
    assert jobs.learned_jobs() is None and jobs.jobs() == 8
    # the learned value never exceeds the cores of this PC
    jobs.learn_file().write_text('{"jobs": 64}')
    assert jobs.jobs() == 16


def test_build_step_learns_from_the_heat_guard(monkeypatch, capsys):
    from lume_tool import heat

    class FakeGuard:
        log_only, limit, error, reported = False, 85.0, None, True
        summary = heat.HeatSummary("k10temp Tctl", max_cpu=85.2, pauses=4)

        def start(self):
            return self

        def stop(self):
            return self.summary

        def check(self):
            pass

    clock = iter([0.0, 1200.0])
    monkeypatch.setattr("time.monotonic", lambda: next(clock))
    monkeypatch.setattr(heat, "guard_from_env", lambda: FakeGuard())
    monkeypatch.delenv("LUME_JOBS", raising=False)
    monkeypatch.setattr(os, "cpu_count", lambda: 16)
    assert cli._heat_guarded(lambda: 0) == 0
    assert "jobs learning: 8 -> 6" in capsys.readouterr().out
    assert jobs.learned_jobs() == 6
