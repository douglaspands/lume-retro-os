"""build-speed 2.2: low priority podman and a single place for the number of jobs (D8)."""

import os

import pytest

from lume_tool import cli, jobs, kernel, packages, rootfs, uboot
from lume_tool.container import Container


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
