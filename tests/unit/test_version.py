"""Image versioning (D15): build timestamp, os-release, BOOT/VERSION and archive."""

import hashlib
import json
import time

from compression import zstd

from r36os import archive, version
from r36os.targets import get_target

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
    boot = version.boot_version_file("ga36", v)
    assert "build: 20261109-214233\n" in boot and "target: ga36\n" in boot


def test_archive_image(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path))
    target = get_target("ga36")
    work = tmp_path / "ga36"
    work.mkdir()
    img = work / "ga36.img"
    img.write_bytes(b"\x55\xaa" * 100_000)
    (work / "manifest.txt").write_text("# arch: armv7\nretroarch 1.22.2-r102\n")
    v = version.current(NOW)

    dest = archive.archive_image(target, img, v, {"kernel": "6.18.62-r36os"})

    assert dest == tmp_path / "images/ga36/20261109-214233"
    zst = dest / "ga36-20261109-214233.img.zst"
    assert zstd.decompress(zst.read_bytes()) == img.read_bytes()
    build = json.loads((dest / "build.json").read_text())
    assert build["build_id"] == "20261109-214233" and build["kernel"] == "6.18.62-r36os"
    assert build["image_sha256"] == hashlib.sha256(img.read_bytes()).hexdigest()
    sums = (dest / "SHA256SUMS").read_text()
    assert f"{build['image_sha256']}  ga36-20261109-214233.img\n" in sums
    assert (dest / "manifest.txt").read_text().startswith("# arch: armv7")
    assert (tmp_path / "images/ga36/latest").resolve() == dest
