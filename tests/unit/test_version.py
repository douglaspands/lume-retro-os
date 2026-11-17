"""Image versioning (D15): build timestamp, os-release, BOOT/VERSION and archive."""

import hashlib
import json
import time

from compression import zstd

from r36os import archive, build, manifests, version
from r36os.targets import get_image, get_target

NOW = time.mktime((2026, 11, 9, 21, 42, 33, 0, 0, -1))


def test_build_id_is_timestamp():
    v = version.current(NOW)
    assert v.build_id == "20261109-214233"
    assert version.BUILD_ID_RE.match(v.build_id)
    assert v.date == "2026-11-09T21:42:33"


def test_boot_file_carries_build_id_and_os_release_does_not():
    # os-release lives in SYSTEM: with the build id in it, SYSTEM changed on every build
    # and `r36os push` resent it (310 MB of the R36S for a GA36 kernel change)
    v = version.current(NOW)
    osr = version.os_release()
    assert 'PRETTY_NAME="Lume Retro OS 0.1.0"' in osr
    assert "BUILD_ID" not in osr and v.build_id not in osr
    boot = version.boot_version_file("console", v)
    assert "build: 20261109-214233\n" in boot and "target: console\n" in boot


def test_rootfs_drops_what_changes_between_builds():
    # the only files that differed between two R36S SYSTEMs with the same packages
    # (2026-11-13): the apk log, the random machine-id and os-release (test above)
    from r36os.rootfs import _ROOTFS_SCRIPT
    drop = next(line for line in _ROOTFS_SCRIPT.splitlines() if line.startswith("rm -f $R/var"))
    for f in ("$R/var/log/apk.log", "$R/etc/machine-id", "$R/var/lib/dbus/machine-id"):
        assert f in drop.split(), f
    assert _ROOTFS_SCRIPT.index(drop) > _ROOTFS_SCRIPT.index("configure.sh {tty}")


def test_archive_image(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path))
    target = get_image("vm")
    work = tmp_path / "vm"
    work.mkdir()
    img = work / "vm.img"
    img.write_bytes(b"\x55\xaa" * 100_000)
    (work / "manifest.txt").write_text("# arch: x86_64\nretroarch 1.22.2-r102\n")
    v = version.current(NOW)

    dest = archive.archive_image(target, img, v, {"kernel": "6.18.62-r36os"})

    assert dest == tmp_path / "images/vm/20261109-214233"
    zst = dest / "vm-20261109-214233.img.zst"
    assert zstd.decompress(zst.read_bytes()) == img.read_bytes()
    build = json.loads((dest / "build.json").read_text())
    assert build["build_id"] == "20261109-214233" and build["kernel"] == "6.18.62-r36os"
    assert build["image_sha256"] == hashlib.sha256(img.read_bytes()).hexdigest()
    sums = (dest / "SHA256SUMS").read_text()
    assert f"{build['image_sha256']}  vm-20261109-214233.img\n" in sums
    assert (dest / "manifest.txt").read_text().startswith("# arch: x86_64")
    assert (tmp_path / "images/vm/latest").resolve() == dest


def test_build_console_runs_both_layers_with_one_version(tmp_path, monkeypatch):
    """build console (D1): ga36 then r36s, one version, build.json with both layers."""
    monkeypatch.setenv("R36OS_OUT", str(tmp_path))
    monkeypatch.setattr(build.version, "current", lambda: _V)
    calls = []

    def fake_layer(target, v, language, rebuild_packages=False, timer=None):
        calls.append((target.name, v.build_id))
        out = tmp_path / target.name
        out.mkdir(exist_ok=True)
        # the root of a console is its slot set (build-speed D9)
        size = 10 if target.name == "ga36" else 20
        sha = hashlib.sha256(target.name.encode()).hexdigest()
        set_ = manifests.SlotSet(build=v.build_id, console=target.name, slots=(
            manifests.Slot("base", sha, size), manifests.Slot("runtime", sha, 1),
            manifests.Slot("lume", sha, 1), manifests.Slot("modules", sha, 1)))
        manifests.write_slots(out / "slots" / "SLOTS", set_)
        (out / "manifest.txt").write_text(f"# arch: {target.alpine_arch}\n")
        if target.name == "ga36":
            (out / "kernel").mkdir(exist_ok=True)
            for panel in ("panel1", "panel2"):
                (out / f"kernel/android-boot-{panel}.img").write_bytes(panel.encode())

    def fake_console_image(v, language="en"):
        img = tmp_path / "console" / "console.img"
        img.parent.mkdir(exist_ok=True)
        img.write_bytes(b"\x00" * 4096)
        # the BOOT list read back from the FAT (usb-device-access 5.1)
        (img.parent / "boot-files.sha256").write_text("ab  ga36/SYSTEM\ncd  VERSION\n")
        return img

    monkeypatch.setattr(build, "build_layer", fake_layer)
    monkeypatch.setattr(build, "build_noarch_fragments", lambda rebuild, timer: None)
    monkeypatch.setattr(build.image, "build_console_image", fake_console_image)
    build.build_image_target(get_image("console"))

    assert calls == [("ga36", _V.build_id), ("r36s", _V.build_id)]
    dest = tmp_path / "images/console" / _V.build_id
    info = json.loads((dest / "build.json").read_text())
    assert info["target"] == "console" and info["build_id"] == _V.build_id
    for console, size in (("ga36", 10), ("r36s", 20)):
        base = info["layers"][console]["slots"]["base"]
        assert base["bytes"] == size and base["file"].startswith("slots/base-")
        assert set(info["layers"][console]["slots"]) == {"base", "runtime", "lume",
                                                         "modules"}
        assert "system_bytes" not in info["layers"][console]
    assert set(info["bootloaders"]) == {"ga36", "r36s"}
    assert (dest / "manifest-ga36.txt").read_text() == "# arch: armv7\n"
    assert (dest / "manifest-r36s.txt").read_text() == "# arch: aarch64\n"
    assert (dest / f"console-{_V.build_id}.img.zst").exists()
    # the GA36 panel boot images are archived with the build (not on BOOT), with their sums
    sums = (dest / "SHA256SUMS").read_text()
    for panel in ("panel1", "panel2"):
        name = f"ga36-android-boot-{panel}.img"
        assert (dest / name).read_bytes() == panel.encode()
        assert f"{hashlib.sha256(panel.encode()).hexdigest()}  {name}\n" in sums
    # the BOOT list goes with the build, for r36os push
    assert (dest / "boot-files.sha256").read_text() == "ab  ga36/SYSTEM\ncd  VERSION\n"


_V = version.current(NOW)
