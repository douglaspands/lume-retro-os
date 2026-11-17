"""Fragment build (build-speed task 6.2): the plan (fragment -> consoles -> packages to
build with their reverse build deps -> slots to redo), the CLI and the build without an
image (BOOT list, objects, image parts, archive)."""

import json
from pathlib import Path

import pytest

from r36os import archive, cli, fragment_build as fb, image, manifests, slots, version
from r36os.targets import IMAGES

GROUPS = slots.Groups(patterns={"runtime": ("retroarch", "libretro-*", "mesa", "mesa-*"),
                                "lume": ("lume-*", "r36os-*"), "base": ()},
                      default="base")


def _aport(name, arches, deps=(), subs=()):
    return fb.Aport(name=name, arches=tuple(arches.split()), build_deps=tuple(deps),
                    packages=(name, *subs))


APORTS = {a.name: a for a in [
    _aport("lume-core", "noarch"),
    _aport("lume-theme", "noarch", deps=["lume-core"]),
    _aport("lume-launcher", "x86_64 armv7 aarch64", deps=["cargo", "sdl2-dev"]),
    _aport("lume-bootsel", "all", deps=["linux-headers"]),
    _aport("r36os-devmem", "armv7"),
    _aport("mesa", "x86_64", subs=["mesa-dev", "mesa-egl"]),
    _aport("libretro-common", "all", subs=["libretro-common-dev"]),
    _aport("libretro-a", "all", deps=["libretro-common-dev", "linux-headers"]),
    _aport("libretro-b", "all !aarch64", deps=["libretro-a"]),
    _aport("retroarch", "all", deps=["mesa-dev", "zlib-dev"], subs=["retroarch-doc"]),
    _aport("libretro-off", ""),
]}


def plan(names, console=None, aports=APORTS):
    return fb.plan_fragments(names, console, aports=aports, groups=GROUPS)


def test_noarch_fragment_reaches_both_consoles_and_only_the_lume_slot():
    p = plan(["lume-core"])
    assert p.consoles == ("ga36", "r36s")
    # built once, with the noarch fragment that build-depends on it
    assert p.noarch == ("lume-core", "lume-theme")
    assert p.packages == {"ga36": (), "r36s": ()}
    assert p.slots == {"ga36": ("lume",), "r36s": ("lume",)}
    assert p.stage1 == ()


def test_arch_fragment_reaches_only_the_consoles_of_its_arch():
    p = plan(["r36os-devmem"])                       # arch="armv7": the GA36 only
    assert p.consoles == ("ga36",)
    assert p.packages == {"ga36": ("r36os-devmem",)}
    assert p.noarch == ()
    assert any(line.startswith("  r36s: unchanged") for line in p.lines())


def test_reverse_build_deps_in_build_order_per_arch():
    p = plan(["libretro-common"])
    # libretro-a needs libretro-common-dev (a subpackage), libretro-b needs libretro-a;
    # libretro-b is not built for aarch64
    assert p.packages == {"ga36": ("libretro-common", "libretro-a", "libretro-b"),
                          "r36s": ("libretro-common", "libretro-a")}
    assert p.slots == {"ga36": ("runtime", "lume"), "r36s": ("runtime", "lume")}


def test_an_x86_only_dependency_does_not_pull_console_packages():
    # retroarch makedepends mesa-dev, but the local mesa is x86_64 only: on the consoles
    # mesa-dev comes from Alpine, so retroarch is not rebuilt for a console
    with pytest.raises(fb.FragmentPlanError, match="mesa is not built for any console"):
        plan(["mesa"])
    p = plan(["retroarch"])
    assert p.packages == {"ga36": ("retroarch",), "r36s": ("retroarch",)}


def test_console_option_restricts_the_plan():
    p = plan(["lume-core", "libretro-a"], console="r36s")
    assert p.consoles == ("r36s",)
    assert p.packages == {"r36s": ("libretro-a",)}       # libretro-b skips aarch64
    assert p.noarch == ("lume-core", "lume-theme")
    with pytest.raises(fb.FragmentPlanError, match="r36os-devmem is not built for the r36s"):
        plan(["r36os-devmem"], console="r36s")
    with pytest.raises(fb.FragmentPlanError, match="--console vm"):
        plan(["lume-core"], console="vm")


def test_initramfs_fragment_redoes_stage_1():
    p = plan(["lume-bootsel"])
    assert p.stage1 == ("ga36", "r36s")
    assert "initramfs and kernel again" in "\n".join(p.lines())
    assert plan(["lume-launcher"]).stage1 == ()


def test_stage1_fragments_are_the_ones_the_initramfs_installs():
    text = (Path(image.__file__).parent / "initramfs.py").read_text()
    for name in fb.STAGE1_FRAGMENTS:
        assert name in text


def test_bad_targets_are_refused():
    with pytest.raises(fb.FragmentPlanError, match="Valid targets: console, vm"):
        plan(["rg35xx"])
    with pytest.raises(fb.FragmentPlanError, match="console is an image"):
        plan(["lume-core", "console"])
    with pytest.raises(fb.FragmentPlanError, match="libretro-off is not built"):
        plan(["libretro-off"])
    clash = {**APORTS, "vm": _aport("vm", "noarch")}
    with pytest.raises(fb.FragmentPlanError, match="aports/vm has the name of an image"):
        plan(["lume-core"], aports=clash)


def test_is_fragment_target():
    assert not fb.is_fragment_target(["console"])
    assert not fb.is_fragment_target(["vm"])
    assert fb.is_fragment_target(["lume-core"])
    assert fb.is_fragment_target(["console", "lume-core"])


def test_plan_of_the_real_aports():
    aports = fb.read_aports()
    assert not set(aports) & set(IMAGES)
    p = fb.plan_fragments(["lume-core"])
    assert p.consoles == ("ga36", "r36s")
    assert p.noarch[0] == "lume-core"
    assert all(s == ("lume",) for s in p.slots.values())
    assert aports["retroarch"].packages == ("retroarch", "retroarch-doc")
    assert fb.plan_fragments(["lume-launcher"], "ga36").packages == {
        "ga36": ("lume-launcher",)}


@pytest.mark.parametrize("argv", [["build", "console", "lume-core"],
                                  ["build", "vm", "--console", "ga36"],
                                  ["build", "--all", "--console", "r36s"],
                                  ["build", "no-such-fragment"]])
def test_cli_refuses_before_creating_anything(tmp_path, monkeypatch, capsys, argv):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "cache"))
    assert cli.main(argv) == 2
    assert capsys.readouterr().err.startswith("error: ")
    assert list(tmp_path.iterdir()) == []


def test_cli_runs_a_fragment_build(monkeypatch):
    seen = {}
    monkeypatch.setattr(fb, "build_fragments",
                        lambda names, console=None, language=None:
                        seen.update(names=names, console=console, language=language))
    monkeypatch.setattr(cli, "_heat_guarded", lambda fn: fn())
    assert cli.main(["build", "lume-core", "lume-launcher", "--console", "ga36"]) == 0
    assert seen == {"names": ["lume-core", "lume-launcher"], "console": "ga36",
                    "language": None}


# --- the build without an image -------------------------------------------------------------

def _file(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def _layers(tmp_path):
    outs = {}
    from r36os import kernel_packages

    for board, kernel in (("ga36", "zImage"), ("r36s", "Image")):
        out = tmp_path / board
        # the kernel and DTBs come from the published lume-kernel/lume-dtbs (task 7.3)
        boot = out / kernel_packages.PKG_DIR / "boot"
        _file(boot / kernel, f"{board} kernel".encode())
        _file(boot / "dtbs" / image.SOC_DIR[board] /
              (image.R36S_DTB if board == "r36s" else "a.dtb"), f"{board} dtb".encode())
        _file(out / "slot" / "SLOTS", f"{board} slots".encode())
        _file(out / "slot" / "lume-0123456789ab", f"{board} lume".encode())
        _file(out / "manifest.txt", b"# arch\nlume-core 1.0-r4\n")
        outs[board] = out
    _file(outs["ga36"] / "kernel" / image.PANEL1_SOURCE, b"panel1")
    _file(outs["ga36"] / "kernel" / "android-boot-panel2.img", b"panel2")
    return outs


@pytest.fixture
def console_set(tmp_path, monkeypatch):
    from r36os import r36s_vendor

    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    outs = _layers(tmp_path)
    factory = {"factory.bin": _file(tmp_path / "factory/factory.bin", b"factory")}
    monkeypatch.setattr(r36s_vendor, "factory_boot_files", lambda: factory)
    monkeypatch.setattr(image, "check_soc_dtbs", lambda files: None)
    monkeypatch.setattr(image, "console_slot_files", lambda board, out: {
        f"{board}/SLOTS": out / "slot/SLOTS",
        f"{board}/slot/lume-0123456789ab": out / "slot/lume-0123456789ab"})
    v = version.BuildVersion("20261117-030405", "2026-11-17T03:04:05", "abc", False)
    out = tmp_path / "out" / "console"
    boot_list = image.write_console_set(
        v, "pt", ga36_out=outs["ga36"], r36s_out=outs["r36s"], out=out,
        area_writer=lambda dest: _file(dest, b"boot area"))
    return {"outs": outs, "v": v, "out": out, "boot_list": boot_list}


def test_console_set_lists_every_boot_file_and_stores_the_objects(console_set):
    out, outs = console_set["out"], console_set["outs"]
    listed = manifests.read_boot_list(console_set["boot_list"])
    paths = [p for p, _ in listed]
    assert paths[-1] == "VERSION"
    assert paths[:-1] == sorted(paths[:-1])
    assert set(paths) == {"VERSION", "boot.ini", "factory.bin", "ga36/zImage", "r36s/Image",
                          "dtbs/a33/a.dtb", f"dtbs/rk3326/{image.R36S_DTB}",
                          "ga36/SLOTS", "ga36/slot/lume-0123456789ab",
                          "r36s/SLOTS", "r36s/slot/lume-0123456789ab"}
    objects = archive.objects_dir()
    for p, sha in listed:
        assert manifests.object_path(objects, sha).is_file()
    sums = dict(listed)
    assert sums["ga36/zImage"] == manifests.sha256_file(outs["ga36"] / "kernel-pkg/boot/zImage")
    assert "build: 20261117-030405" in (out / "VERSION").read_text()
    assert "language: pt" in (out / "VERSION").read_text()
    parts = image.read_image_parts(out / image.IMAGE_PARTS)
    assert manifests.object_path(objects, parts[image.PANEL1_PART]).read_bytes() == b"panel1"
    assert manifests.object_path(objects, parts[image.AREA_PART]).read_bytes() == b"boot area"
    assert not (out / "console-boot-area.bin").exists()
    assert not (out / "console.img").exists()


def test_console_set_needs_the_outputs_of_a_console_build(tmp_path, monkeypatch, console_set):
    (console_set["outs"]["r36s"] / "kernel-pkg/boot/Image").unlink()
    with pytest.raises(image.ConsoleImageError, match="last `r36os build console`.*Image"):
        image.write_console_set(console_set["v"], ga36_out=console_set["outs"]["ga36"],
                                r36s_out=console_set["outs"]["r36s"], out=console_set["out"],
                                area_writer=lambda dest: _file(dest, b"a"))


def test_archived_set_is_pushable_and_flashable(console_set):
    from r36os import flash

    out, outs, v = console_set["out"], console_set["outs"], console_set["v"]
    extras = image.ga36_android_boot_images(outs["ga36"])
    extras[image.BOOT_LIST] = console_set["boot_list"]
    extras[image.IMAGE_PARTS] = out / image.IMAGE_PARTS
    dest = archive.archive_set(IMAGES["console"], v, {"kind": "fragments"},
                               {"manifest-ga36.txt": outs["ga36"] / "manifest.txt"}, extras)
    assert dest.name == v.build_id
    assert not list(dest.glob("*.img.zst"))
    build = json.loads((dest / "build.json").read_text())
    assert build["image"] is None and build["kind"] == "fragments"
    assert build["build_id"] == v.build_id
    assert (dest / "ga36-android-boot-panel1.img").read_bytes() == b"panel1"  # push reads it
    assert (dest / "manifest-ga36.txt").is_file()
    sums = (dest / "SHA256SUMS").read_text()
    assert image.BOOT_LIST in sums and image.IMAGE_PARTS in sums
    assert (archive.images_dir(IMAGES["console"]) / "latest").resolve() == dest.resolve()
    assert flash.find_build(IMAGES["console"]) == (dest.resolve(), None)
    assert manifests.read_boot_list(dest / image.BOOT_LIST) == manifests.read_boot_list(
        console_set["boot_list"])


def test_latest_language(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    assert fb.latest_language() is None
    d = archive.images_dir(IMAGES["console"]) / "20261117-000000"
    d.mkdir(parents=True)
    (d / "build.json").write_text('{"language": "pt"}\n')
    (d.parent / "latest").symlink_to(d.name)
    assert fb.latest_language() == "pt"
