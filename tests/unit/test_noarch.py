"""build-speed 4.1: noarch fragments (ELF check, same file in every arch repository)."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

import pytest

from lume_tool import packages
from lume_tool.manifests import sha256_file

ELF_HEAD = b"\x7fELF\x01\x01\x01" + b"\0" * 57


def _tar_segment(files: dict[str, bytes], cut: bool) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    raw = buf.getvalue()
    if cut:  # like `abuild-tar --cut`: drop the end-of-archive blocks
        raw = raw.rstrip(b"\0")
        raw += b"\0" * (-len(raw) % 512)
    return raw


def make_apk(path: Path, data: dict[str, bytes], arch: str = "noarch",
             origin: str = "lume-test") -> Path:
    """A minimal APK v2 file: signature, control and data gzip streams in a row."""
    pkginfo = (f"pkgname = {origin}\npkgver = 1.0-r0\narch = {arch}\n"
               f"origin = {origin}\n").encode()
    sig = gzip.compress(_tar_segment({".SIGN.RSA.lume.rsa.pub": b"x" * 512}, cut=True))
    ctl = gzip.compress(_tar_segment({".PKGINFO": pkginfo}, cut=True))
    dat = gzip.compress(_tar_segment(data, cut=False))
    path.write_bytes(sig + ctl + dat)
    return path


def test_pkginfo_is_read_from_the_control_segment(tmp_path):
    apk = make_apk(tmp_path / "a.apk", {"usr/share/x/readme": b"hi\n"})
    info = dict(packages.read_apk_pkginfo(apk))
    assert info["arch"] == "noarch"
    assert info["origin"] == "lume-test"


def test_noarch_apk_without_elf_passes(tmp_path):
    apk = make_apk(tmp_path / "a.apk", {"usr/bin/script": b"#!/bin/sh\necho hi\n"})
    assert packages.elf_files_in_apk(apk) == []
    packages.check_noarch_apk(apk, "lume-test")


def test_noarch_apk_with_elf_fails_naming_fragment_and_file(tmp_path):
    apk = make_apk(tmp_path / "a.apk", {"usr/share/ok.txt": b"text",
                                        "usr/lib/lume/tool": ELF_HEAD})
    assert packages.elf_files_in_apk(apk) == ["usr/lib/lume/tool"]
    with pytest.raises(packages.NoarchError) as e:
        packages.check_noarch_apk(apk, "lume-usb")
    assert "lume-usb" in str(e.value)
    assert "usr/lib/lume/tool" in str(e.value)


def test_apk_with_an_arch_is_not_published_as_noarch(tmp_path):
    apk = make_apk(tmp_path / "a.apk", {"usr/share/ok.txt": b"text"}, arch="x86_64")
    with pytest.raises(packages.NoarchError, match="arch=x86_64"):
        packages.check_noarch_apk(apk, "lume-test")


def _aport(root: Path, arch: str = "noarch") -> Path:
    d = root / "lume-usb"
    (d / "files").mkdir(parents=True)
    (d / "APKBUILD").write_text(f'pkgname=lume-usb\narch="{arch}"\n')
    (d / "files" / "usb-gadget").write_text("#!/bin/sh\n")
    return d


def test_noarch_aport_with_an_elf_file_fails_before_the_build(tmp_path):
    d = _aport(tmp_path)
    packages.check_noarch_aport(d)
    (d / "files" / "helper").write_bytes(ELF_HEAD)
    with pytest.raises(packages.NoarchError) as e:
        packages.check_noarch_aport(d)
    assert "lume-usb" in str(e.value)
    assert "files/helper" in str(e.value)


def test_aport_that_is_not_noarch_is_refused(tmp_path):
    with pytest.raises(packages.NoarchError, match="not \"noarch\""):
        packages.check_noarch_aport(_aport(tmp_path, arch="all"))


def test_publish_copies_the_same_file_to_every_arch(tmp_path, monkeypatch):
    monkeypatch.setenv("LUME_OUT", str(tmp_path / "out"))
    calls = []
    monkeypatch.setattr(packages, "reindex", lambda arches: calls.append(tuple(arches)))
    apk = make_apk(tmp_path / "lume-test-1.0-r0.apk", {"usr/share/x": b"x"})
    published = packages.publish_noarch([apk])
    assert sorted(p.parent.name for p in published) == sorted(packages.REPO_ARCHES)
    assert {sha256_file(p) for p in published} == {sha256_file(apk)}
    assert calls == [packages.REPO_ARCHES]
    # publishing again the same bytes is a no-op
    packages.publish_noarch([apk])


def test_publish_refuses_a_different_file_with_the_same_name(tmp_path, monkeypatch):
    monkeypatch.setenv("LUME_OUT", str(tmp_path / "out"))
    monkeypatch.setattr(packages, "reindex", lambda arches: None)
    apk = make_apk(tmp_path / "lume-test-1.0-r0.apk", {"usr/share/x": b"x"})
    other = packages.arch_repo_dir("armv7") / apk.name
    other.parent.mkdir(parents=True)
    other.write_bytes(b"other")
    with pytest.raises(packages.NoarchError, match="different content"):
        packages.publish_noarch([apk])


def test_publish_refuses_a_noarch_apk_with_elf(tmp_path, monkeypatch):
    monkeypatch.setenv("LUME_OUT", str(tmp_path / "out"))
    monkeypatch.setattr(packages, "reindex", lambda arches: None)
    apk = make_apk(tmp_path / "lume-test-1.0-r0.apk", {"usr/bin/tool": ELF_HEAD})
    with pytest.raises(packages.NoarchError, match="usr/bin/tool"):
        packages.publish_noarch([apk])
    assert not packages.arch_repo_dir("armv7").exists()
