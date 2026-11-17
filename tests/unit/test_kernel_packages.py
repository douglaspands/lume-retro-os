"""build-speed 7.3: lume-kernel, lume-modules and lume-dtbs per architecture, versioned by
content, and BOOT and the modules slot taken from the published packages."""

from __future__ import annotations

import gzip
import hashlib
import io
import tarfile

import pytest

from r36os import fragments as frag
from r36os import kernel_packages as kp
from r36os import packages


def _kdir(layer, image, soc_files, kernel=b"kernel", modules=b"modules"):
    kdir = layer / "kernel"
    (kdir / "dtbs" / "vendor").mkdir(parents=True, exist_ok=True)
    (kdir / image).write_bytes(kernel)
    (kdir / "modules").write_bytes(modules)
    for name, data in soc_files.items():
        (kdir / "dtbs" / name).write_bytes(data)
    return kdir


@pytest.fixture
def repo(tmp_path, monkeypatch):
    out = tmp_path / "out"
    monkeypatch.setenv("R36OS_OUT", str(out))
    reindexed = []
    monkeypatch.setattr(packages, "reindex", lambda arches: reindexed.append(list(arches)))

    def sign(apks, tag):   # no container: control with .lume-content, no signature
        for apk, content in apks:
            ctl, data = frag.control_with_lume_content(apk, content)
            apk.write_bytes(b"".join(frag.split_apk(apk).signature) + ctl + data)

    monkeypatch.setattr(packages, "sign_with_lume_content", sign)
    ga36 = _kdir(out / "ga36", "zImage", {"p1.dtb": b"p1", "vendor/v.dtb": b"v"},
                 kernel=b"zimage")
    r36s = _kdir(out / "r36s", "Image", {"r.dtb": b"r"}, kernel=b"image")
    return out, ga36, r36s, reindexed


def test_package_files_layout(repo):
    _, ga36, r36s, _ = repo
    g = kp.package_files("ga36", ga36)
    assert set(g) == set(kp.NAMES)
    assert g["lume-kernel"] == {"boot/zImage": ga36 / "zImage"}
    assert g["lume-modules"] == {"boot/modules.squashfs": ga36 / "modules"}
    assert g["lume-dtbs"] == {"boot/dtbs/a33/p1.dtb": ga36 / "dtbs/p1.dtb",
                              "boot/dtbs/a33/vendor/v.dtb": ga36 / "dtbs/vendor/v.dtb"}
    r = kp.package_files("r36s", r36s)
    assert r["lume-kernel"] == {"boot/Image": r36s / "Image"}
    assert set(r["lume-dtbs"]) == {"boot/dtbs/rk3326/r.dtb"}
    (r36s / "Image").unlink()
    with pytest.raises(kp.KernelPackageError, match="lume-kernel"):
        kp.package_files("r36s", r36s)


def test_apk_has_reproducible_data_and_content(tmp_path, repo):
    _, ga36, _, _ = repo
    files = kp.package_files("ga36", ga36)["lume-dtbs"]
    a = kp.make_apk(tmp_path / "a", "lume-dtbs", "6.18.62-r0", "armv7", files, "1" * 40, 7)
    b = kp.make_apk(tmp_path / "b", "lume-dtbs", "6.18.62-r4", "armv7", files, "2" * 40, 7)
    pa, pb = frag.split_apk(a), frag.split_apk(b)
    assert pa.signature == [] and pa.data == pb.data
    info = dict(packages.read_apk_pkginfo(a))
    assert info["arch"] == "armv7" and info["origin"] == "lume-dtbs"
    assert info["datahash"] == hashlib.sha256(pa.data).hexdigest()
    assert frag.apk_content_hash(a) == frag.apk_content_hash(b)
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(pa.data))) as tf:
        members = {m.name.rstrip("/"): m for m in tf}
    assert set(members) == {"boot", "boot/dtbs", "boot/dtbs/a33", "boot/dtbs/a33/vendor",
                            "boot/dtbs/a33/p1.dtb", "boot/dtbs/a33/vendor/v.dtb"}
    m = members["boot/dtbs/a33/p1.dtb"]
    assert (m.uid, m.gid, m.mode, m.mtime) == (0, 0, 0o644, 7)
    assert m.pax_headers[kp.SHA1_PAX] == hashlib.sha1(b"p1").hexdigest()
    (ga36 / "dtbs/p1.dtb").write_bytes(b"p1 changed")
    c = kp.make_apk(tmp_path / "c", "lume-dtbs", "6.18.62-r0", "armv7", files, "1" * 40, 7)
    assert frag.apk_content_hash(c) != frag.apk_content_hash(a)


def _versions(arch):
    return {n: p.version for n, p in packages.read_repo_hashes(arch).packages.items()}


def test_publish_versions_by_content_per_arch(repo, monkeypatch):
    out, ga36, r36s, reindexed = repo
    first = kp.publish("ga36", ga36)
    assert [(o.name, o.version, o.published) for o in first] == [
        (n, "6.18.62-r0", True) for n in kp.NAMES]
    kp.publish("r36s", r36s)
    assert _versions("aarch64") == {n: "6.18.62-r0" for n in kp.NAMES}
    for n in kp.NAMES:
        apk = packages.arch_repo_dir("armv7") / f"{n}-6.18.62-r0.apk"
        assert frag.apk_lume_content(apk) == packages.read_repo_hashes("armv7").packages[n].content
    aarch64_hashes = packages.hashes_path("aarch64").read_bytes()
    # a GA36 driver patch: only the armv7 packages that changed get the next pkgrel
    (ga36 / "zImage").write_bytes(b"zimage patched")
    (ga36 / "modules").write_bytes(b"modules patched")
    reindexed.clear()
    res = {o.name: (o.version, o.published) for o in kp.publish("ga36", ga36)}
    assert res == {"lume-kernel": ("6.18.62-r1", True), "lume-modules": ("6.18.62-r1", True),
                   "lume-dtbs": ("6.18.62-r0", False)}
    assert reindexed and all(r == ["armv7"] for r in reindexed)
    # the R36S kernel came out byte-identical: nothing packaged, nothing published
    reindexed.clear()
    res = kp.publish("r36s", r36s)
    assert not any(o.published for o in res) and reindexed == []
    assert packages.hashes_path("aarch64").read_bytes() == aarch64_hashes
    assert sorted(p.name for p in packages.arch_repo_dir("aarch64").glob("*.apk")) == sorted(
        f"{n}-6.18.62-r0.apk" for n in kp.NAMES)
    # new inputs with the same content (e.g. this module changed): packaged again, but the
    # version stays and no file is added
    monkeypatch.setattr(kp, "inputs_of", lambda *a: "e" * 64)
    res = kp.publish("r36s", r36s)
    assert {o.version for o in res} == {"6.18.62-r0"} and not any(o.published for o in res)
    assert {p.inputs for p in packages.read_repo_hashes("aarch64").packages.values()} == {
        "e" * 64}
    assert len(list(packages.arch_repo_dir("aarch64").glob("*.apk"))) == 3


def test_boot_and_modules_slot_come_from_the_published_packages(repo):
    out, ga36, _, _ = repo
    kp.publish("ga36", ga36)
    # the outputs of the kernel stage change after the publish: BOOT keeps the published
    (ga36 / "zImage").write_bytes(b"not published")
    dest = kp.extract_published("ga36", out / "ga36")
    assert dest == out / "ga36" / kp.PKG_DIR
    assert (dest / kp.PACKAGES_LIST).read_text().splitlines() == [
        f"{n} 6.18.62-r0" for n in kp.NAMES]
    files = kp.boot_sources("ga36", out / "ga36")
    assert {p: f.read_bytes() for p, f in files.items()} == {
        "ga36/zImage": b"zimage", "dtbs/a33/p1.dtb": b"p1", "dtbs/a33/vendor/v.dtb": b"v"}
    assert kp.modules_image(out / "ga36").read_bytes() == b"modules"
    # a published file that does not match hashes.json is refused
    apk = packages.arch_repo_dir("armv7") / "lume-dtbs-6.18.62-r0.apk"
    other = kp.make_apk(out / "x", "lume-dtbs", "6.18.62-r0", "armv7",
                        {"boot/x.dtb": ga36 / "zImage"}, "1" * 40, 0)
    ctl, data = frag.control_with_lume_content(other, "f" * 64)
    apk.write_bytes(ctl + data)
    with pytest.raises(kp.KernelPackageError, match="differs from hashes.json"):
        kp.extract_published("ga36", out / "ga36")


def test_paths_outside_boot_are_refused(tmp_path):
    src = tmp_path / "f"
    src.write_bytes(b"x")
    for bad in ("etc/x", "/boot/x", "boot/../etc/x"):
        with pytest.raises(kp.KernelPackageError, match="bad path"):
            kp.data_segment({bad: src}, 0)
