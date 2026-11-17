"""Stage skipping (build-speed 6.3): a stage runs again only when one of its inputs changed."""

import pytest

from r36os import kernel, rootfs, stage_inputs
from r36os.stages import StageTimer
from r36os.targets import get_target

DT_PATCH = ("From: x\n---\ndiff --git a/arch/arm/boot/dts/allwinner/foo.dts "
            "b/arch/arm/boot/dts/allwinner/foo.dts\n--- a/x\n+++ b/x\n")
C_PATCH = "diff --git a/drivers/gpu/foo.c b/drivers/gpu/foo.c\n--- a/x\n+++ b/x\n"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    for rel, text in {
        "board/r36s/dts/a.dts": "a", "board/r36s/dts-vendor/v.dts": "v",
        "board/r36s/serial": "ttyS2 115200", "board/r36s/bootsel-keys": "k",
        "rootfs/overlay/etc/x": "x", "rootfs/configure.sh": "c",
        "initramfs/init": "i", "initramfs/lib/storage.sh": "s",
        "kernel/patches/0001-dt.patch": DT_PATCH, "kernel/patches/0002-c.patch": C_PATCH,
    }.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    monkeypatch.setattr(stage_inputs, "REPO_ROOT", root)
    monkeypatch.setattr(kernel, "PATCHES_DIR", root / "kernel/patches")
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    stage_inputs.set_clean(False)
    return root


def run(inputs, output, required=None):
    """True if the stage ran."""
    calls = []
    timer = StageTimer()

    def fn():
        calls.append(1)
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.name != "dtbs":
            output.write_text("built")
        else:
            output.mkdir(exist_ok=True)
            (output / "a.dtb").write_text("dtb")

    stage_inputs.run_stage(timer, "stage", output, inputs, fn, required)
    return bool(calls)


def test_a_second_run_with_the_same_inputs_is_skipped_and_recorded(repo, tmp_path):
    out = tmp_path / "o" / "SYSTEM"
    make = lambda: stage_inputs.Inputs().text("a", "1")  # noqa: E731
    assert run(make, out)
    assert not run(make, out)
    first = (tmp_path / "o" / "SYSTEM.inputs").read_text().splitlines()
    assert first[0].startswith("stage ") and first[1].startswith("input a ")
    timer = StageTimer()
    stage_inputs.run_stage(timer, "x: SYSTEM", out, make, lambda: None)
    assert any("x: SYSTEM" in l and "skipped (inputs unchanged" in l for l in timer.summary())


def test_clean_a_missing_output_and_a_failed_run_force_the_stage(repo, tmp_path):
    out = tmp_path / "o" / "SYSTEM"
    make = lambda: stage_inputs.Inputs().text("a", "1")  # noqa: E731
    run(make, out)
    stage_inputs.set_clean(True)
    assert run(make, out)
    stage_inputs.set_clean(False)
    assert not run(make, out)
    out.unlink()
    assert run(make, out)

    def boom():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        stage_inputs.run_stage(StageTimer(), "s", out, lambda: stage_inputs.Inputs().text("a", "2"),
                               boom)
    assert not (tmp_path / "o" / "SYSTEM.inputs").exists()  # no stale hash after a failure


def test_an_empty_dtbs_folder_does_not_count_as_output(repo, tmp_path):
    out = tmp_path / "k" / "dtbs"
    out.mkdir(parents=True)
    make = lambda: stage_inputs.Inputs().text("a", "1")  # noqa: E731
    stage_inputs.inputs_file(out).write_text(f"stage {make().digest()}\n")
    assert run(make, out)


def test_device_tree_patch_detection():
    assert stage_inputs.touches_device_tree(DT_PATCH)
    assert stage_inputs.touches_device_tree(
        "diff --git a/Documentation/devicetree/bindings/x.yaml b/Documentation/devicetree/"
        "bindings/x.yaml\n")
    assert stage_inputs.touches_device_tree(
        "diff --git a/include/dt-bindings/a.h b/include/dt-bindings/a.h\n")
    assert not stage_inputs.touches_device_tree(C_PATCH)


def test_dtbs_stage_runs_on_each_of_its_inputs(repo, tmp_path, monkeypatch):
    out = tmp_path / "k" / "dtbs"
    make = lambda: stage_inputs.dtb_inputs("r36s", "arm64", "rockchip")  # noqa: E731
    assert run(make, out)
    assert not run(make, out)
    # a driver patch is not an input
    (repo / "kernel/patches/0002-c.patch").write_text(C_PATCH + "+more\n")
    assert not run(make, out)
    # a device tree patch is
    (repo / "kernel/patches/0001-dt.patch").write_text(DT_PATCH + "+more\n")
    assert run(make, out)
    # a new device tree patch is
    (repo / "kernel/patches/0003-dt.patch").write_text(DT_PATCH.replace("foo", "bar"))
    assert run(make, out)
    for rel in ("board/r36s/dts/a.dts", "board/r36s/dts-vendor/v.dts"):
        assert not run(make, out)
        (repo / rel).write_text("changed " + rel)
        assert run(make, out)
    assert not run(make, out)
    monkeypatch.setattr(kernel, "_DTBS_SCRIPT", kernel._DTBS_SCRIPT + "echo more\n")
    assert run(make, out)  # validation script
    assert not run(make, out)
    monkeypatch.setattr(kernel, "KERNEL_VERSION", "9.9.9")
    assert run(make, out)


def test_rootfs_stage_runs_on_each_of_its_inputs(repo, tmp_path):
    target = get_target("r36s")
    out = tmp_path / "o" / "rootfs.tar"
    index = tmp_path / "out" / "repo" / target.alpine_arch / "APKINDEX.tar.gz"
    index.parent.mkdir(parents=True)
    index.write_text("i1")
    base = dict(script="s", packages=["a", "b"], language="en", os_release="os",
                leiame_text="l", mirror_hash="m1")

    def make(**kw):
        args = {**base, **kw}
        return lambda: stage_inputs.rootfs_inputs(target, **args)

    assert run(make(), out)
    assert not run(make(), out)
    for change in ({"script": "s2"}, {"packages": ["a"]}, {"language": "pt"},
                   {"os_release": "os2"}, {"leiame_text": "l2"}, {"mirror_hash": "m2"}):
        assert run(make(**change), out), change
        assert run(make(), out), change  # back to the base
    for rel in ("rootfs/configure.sh", "rootfs/overlay/etc/x", "board/r36s/serial"):
        assert not run(make(), out)
        (repo / rel).write_text("changed")
        assert run(make(), out), rel
    (repo / "rootfs/overlay/etc/new").write_text("n")
    assert run(make(), out)
    index.write_text("i2")  # a rebuilt local package
    assert run(make(), out)
    assert not run(make(), out)


def test_rootfs_without_a_reachable_mirror_always_runs(repo, tmp_path):
    target = get_target("r36s")
    out = tmp_path / "o" / "rootfs.tar"
    make = lambda: stage_inputs.rootfs_inputs(  # noqa: E731
        target, "s", ["a"], "en", "os", "l", "")
    assert run(make, out)
    assert run(make, out)


def test_rootfs_inputs_do_not_include_the_build_id(repo, monkeypatch):
    from r36os import version

    monkeypatch.setattr(version, "os_release", lambda: "same")
    monkeypatch.setattr(stage_inputs, "mirror_index_hash", lambda *a: "m")
    target = get_target("r36s")
    a = rootfs.stage_inputs(target, version.current(now=1_000_000), "en")
    b = rootfs.stage_inputs(target, version.current(now=2_000_000), "en")
    assert a.digest() == b.digest()


def test_initramfs_stage_runs_on_each_of_its_inputs(repo, tmp_path):
    target = get_target("r36s")
    out = tmp_path / "o" / "initramfs"
    tar = tmp_path / "o" / "rootfs.tar"
    tar.parent.mkdir(parents=True)
    tar.write_text("t1")
    (repo / "initramfs/modules-r36s.txt").write_text("m")
    make = lambda: stage_inputs.initramfs_inputs(target, tar)  # noqa: E731
    assert run(make, out)
    assert not run(make, out)
    for rel in ("initramfs/init", "initramfs/lib/storage.sh", "board/r36s/bootsel-keys",
                "initramfs/modules-r36s.txt"):
        (repo / rel).write_text("changed " + rel)
        assert run(make, out), rel
        assert not run(make, out)
    tar.write_text("t2")  # the modules come out of the rootfs
    assert run(make, out)
    assert not run(make, out)
    index = tmp_path / "out" / "repo" / target.alpine_arch / "APKINDEX.tar.gz"
    index.parent.mkdir(parents=True)
    index.write_text("i")  # lume-bootsel rebuilt
    assert run(make, out)


def test_system_stage_runs_on_the_tar_the_options_and_the_limit(repo, tmp_path):
    out = tmp_path / "o" / "SYSTEM"
    tar = tmp_path / "o" / "rootfs.tar"
    tar.parent.mkdir(parents=True)
    tar.write_text("t1")

    def make(opts=rootfs.SQUASHFS_OPTIONS, limit=448):
        return lambda: stage_inputs.system_inputs(tar, opts, limit)

    assert run(make(), out)
    assert not run(make(), out)
    assert run(make(opts="-comp zstd -Xcompression-level 3"), out)
    assert run(make(limit=768), out)
    assert run(make(), out)
    tar.write_text("t2")
    assert run(make(), out)
    assert not run(make(), out)


def test_modules_image_stage_runs_on_the_modules_tar_and_the_script(repo, tmp_path):
    # a build without changes must not call mksquashfs for <console>/modules either
    import io
    import tarfile

    out = tmp_path / "k" / "modules"
    tar = tmp_path / "k" / "modules.tar"
    tar.parent.mkdir(parents=True)

    def write_tar(content: bytes, mtime: int) -> None:
        with tarfile.open(tar, "w") as t:
            info = tarfile.TarInfo("lib/modules/6.18.62-r36os/kernel/x.ko")
            info.size, info.mtime = len(content), mtime
            t.addfile(info, io.BytesIO(content))

    def make(script=rootfs.MODULES_SCRIPT):
        return lambda: stage_inputs.modules_inputs(tar, script)

    write_tar(b"m1", 1000)
    assert run(make(), out)
    assert not run(make(), out)
    # modules_install writes new times on every build: same modules, stage skipped
    write_tar(b"m1", 2000)
    assert not run(make(), out)
    assert run(make(script=rootfs.MODULES_SCRIPT + "# changed\n"), out)
    assert run(make(), out)
    write_tar(b"m2", 2000)
    assert run(make(), out)
    assert not run(make(), out)
