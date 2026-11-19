"""Incremental console kernel (build-speed 7.2, D5): one kept build folder per architecture,
configuration and checks applied again on every run, initramfs relinked only on change."""

import os

import pytest

from lume_tool import clean, kernel


@pytest.fixture
def fake_build(tmp_path, monkeypatch):
    """build_kernel with the container, the source tree and the cache faked; returns the
    calls (volumes and script of each container run)."""
    from lume_tool import container, jobs

    cache = tmp_path / "cache"
    monkeypatch.setattr(kernel, "cache_dir", lambda: cache)
    monkeypatch.setattr(kernel, "source_tree", lambda: tmp_path / "linux")
    monkeypatch.setattr(jobs, "jobs", lambda: 4)
    monkeypatch.setattr(container, "ensure_cross", lambda: "cross")
    calls = []

    class FakeContainer:
        def __init__(self, image, volumes):
            self.volumes = volumes

        def sh(self, script):
            calls.append({"volumes": dict(self.volumes), "script": script})

    monkeypatch.setattr(container, "Container", FakeContainer)
    return cache, calls


def _guest(volumes, guest):
    return next(h for h, g in volumes.items() if g == guest)


def test_build_folder_is_fixed_per_architecture(fake_build, tmp_path, monkeypatch):
    cache, calls = fake_build
    assert kernel.kbuild_dir("ga36") == cache / "kbuild" / "armv7"
    assert kernel.kbuild_dir("r36s") == cache / "kbuild" / "aarch64"
    kernel.build_kernel("ga36", tmp_path / "out-ga36")
    # a changed patch set keeps the same folder (make recompiles only what changed)
    monkeypatch.setattr(kernel, "patches_digest", lambda: "ffffffffffffffff")
    kernel.build_kernel("ga36", tmp_path / "out-ga36")
    kernel.build_kernel("r36s", tmp_path / "out-r36s")
    builds = [_guest(c["volumes"], "/build") for c in calls]
    assert builds == [cache / "kbuild" / "armv7"] * 2 + [cache / "kbuild" / "aarch64"]
    # the host path never reaches the kernel: always mounted at /build
    assert all("O=$B" in c["script"] and "B=/build" in c["script"] for c in calls)


def test_clean_build_starts_from_an_empty_build_folder(fake_build, tmp_path, monkeypatch):
    # build-speed 7.4: `lume build --clean` gives the clean kernel the incremental one is
    # compared with
    from lume_tool import stage_inputs

    cache, _ = fake_build
    old = cache / "kbuild" / "armv7" / "drivers" / "x.o"
    old.parent.mkdir(parents=True)
    old.write_text("stale")
    kernel.build_kernel("ga36", tmp_path / "out")
    assert old.exists()                     # incremental: the folder is kept
    monkeypatch.setattr(stage_inputs, "_clean", True)
    kernel.build_kernel("ga36", tmp_path / "out")
    assert not old.exists() and (cache / "kbuild" / "armv7").is_dir()


def test_configuration_is_rebuilt_and_checked_every_run(fake_build, tmp_path):
    _cache, calls = fake_build
    kernel.build_kernel("r36s", tmp_path / "out")
    s = calls[0]["script"]
    # defconfig overwrites whatever .config the kept folder has, then the fragment, then
    # olddefconfig; the fragment checks read the resulting .config before make compiles
    order = ["make -s O=$B defconfig", "merge_config.sh", "make -s O=$B olddefconfig",
             "did not end up in .config", "must stay off", "make O=$B -j4 Image modules"]
    positions = [s.index(x) for x in order]
    assert positions == sorted(positions)


def test_own_driver_warning_fails_and_is_not_lost_by_the_next_run(fake_build, tmp_path):
    _cache, calls = fake_build
    kernel.build_kernel("ga36", tmp_path / "out")
    s = calls[0]["script"]
    check = s.index("grep -E 'panel-ga36mb-jd9366.c|")
    # checked before any output is copied, and the warned objects are deleted so the
    # next incremental run compiles them again (and shows the warning again)
    assert s.index("make O=$B -j4 zImage modules") < check < s.index("cp $B/arch/arm/boot/zImage")
    tail = s[check:s.index("exit 1", check)]
    assert 'find $B -name "${f%.c}.o" -delete' in tail


def test_make_log_lists_the_compiled_objects(fake_build, tmp_path):
    _cache, calls = fake_build
    kernel.build_kernel("ga36", tmp_path / "out")
    s = calls[0]["script"]
    assert s.index("touch /tmp/make-start") < s.index("make O=$B -j4")
    assert "-newer /tmp/make-start" in s and "/out/rebuilt-objects.txt" in s


def test_initramfs_is_staged_by_content(fake_build, tmp_path):
    cache, calls = fake_build
    src = tmp_path / "layer"
    src.mkdir()
    (src / "initramfs.cpio").write_bytes(b"one")
    kernel.build_kernel("ga36", tmp_path / "out", initramfs_dir=src)
    staged = _guest(calls[0]["volumes"], "/initramfs")
    assert staged == cache / "kbuild" / "armv7" / "lume-initramfs"
    cpio = staged / "initramfs.cpio"
    assert cpio.read_bytes() == b"one"
    os.utime(cpio, (1_000_000, 1_000_000))
    # the initramfs stage rewrites the file with the same bytes: the staged copy (what
    # make compares with the embedded one) keeps its mtime and the image is not relinked
    (src / "initramfs.cpio").write_bytes(b"one")
    kernel.build_kernel("ga36", tmp_path / "out", initramfs_dir=src)
    assert cpio.stat().st_mtime == 1_000_000
    # a changed initramfs gets a new mtime: make relinks the image
    (src / "initramfs.cpio").write_bytes(b"two")
    kernel.build_kernel("ga36", tmp_path / "out", initramfs_dir=src)
    assert cpio.read_bytes() == b"two" and cpio.stat().st_mtime > 1_000_000
    assert not list(staged.glob(".*.part"))


def test_without_initramfs_nothing_is_mounted(fake_build, tmp_path):
    _cache, calls = fake_build
    kernel.build_kernel("r36s", tmp_path / "out")
    assert "/initramfs" not in calls[0]["volumes"].values()


def test_clean_never_removes_the_per_architecture_folders(tmp_path):
    cache = tmp_path / "cache"
    for name in ("armv7", "aarch64", "r36s-bbbbbbbbbbbbbbbb"):
        (cache / "kbuild" / name).mkdir(parents=True)
        (cache / "kbuild" / name / ".config").write_text("x")
    remove, _ = clean.plan(tmp_path / "repo", tmp_path / "repo" / "out", cache,
                           "aaaaaaaaaaaaaaaa", cited=set())
    assert {i.path for i in remove} == {cache / "kbuild" / "r36s-bbbbbbbbbbbbbbbb"}
