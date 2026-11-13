"""Image versioning (D15): build timestamp, os-release, BOOT/VERSION and archive."""

import hashlib
import json
import time

from compression import zstd

from r36os import archive, build, version
from r36os.targets import get_image, get_target

NOW = time.mktime((2026, 11, 9, 21, 42, 33, 0, 0, -1))


def test_build_id_is_timestamp():
    v = version.current(NOW)
    assert v.build_id == "20261109-214233"
    assert version.BUILD_ID_RE.match(v.build_id)
    assert v.date == "2026-11-09T21:42:33"


def test_os_release_and_boot_file_carry_build_id():
    v = version.current(NOW)
    osr = version.os_release(v)
    assert "BUILD_ID=20261109-214233\n" in osr
    assert 'PRETTY_NAME="Lume Retro OS 0.1.0 (20261109-214233)"' in osr
    boot = version.boot_version_file("console", v)
    assert "build: 20261109-214233\n" in boot and "target: console\n" in boot


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

    def fake_layer(target, v, language, rebuild_packages=False):
        calls.append((target.name, v.build_id))
        out = tmp_path / target.name
        out.mkdir(exist_ok=True)
        (out / "SYSTEM").write_bytes(b"s" * (10 if target.name == "ga36" else 20))
        (out / "manifest.txt").write_text(f"# arch: {target.alpine_arch}\n")

    def fake_console_image(v, language="en"):
        img = tmp_path / "console" / "console.img"
        img.parent.mkdir(exist_ok=True)
        img.write_bytes(b"\x00" * 4096)
        return img

    monkeypatch.setattr(build, "build_layer", fake_layer)
    monkeypatch.setattr(build.image, "build_console_image", fake_console_image)
    build.build_image_target(get_image("console"))

    assert calls == [("ga36", _V.build_id), ("r36s", _V.build_id)]
    dest = tmp_path / "images/console" / _V.build_id
    info = json.loads((dest / "build.json").read_text())
    assert info["target"] == "console" and info["build_id"] == _V.build_id
    assert info["layers"]["ga36"]["system_bytes"] == 10
    assert info["layers"]["r36s"]["system_bytes"] == 20
    assert set(info["bootloaders"]) == {"ga36", "r36s"}
    assert (dest / "manifest-ga36.txt").read_text() == "# arch: armv7\n"
    assert (dest / "manifest-r36s.txt").read_text() == "# arch: aarch64\n"
    assert (dest / f"console-{_V.build_id}.img.zst").exists()


_V = version.current(NOW)
