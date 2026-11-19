"""device-fixes 1.3: the signing key became `lume.rsa`; what out/repo holds signed by the old
key is signed again once (packages.resign_published), without a container in the test."""

from __future__ import annotations

import gzip
import io
import tarfile
from pathlib import Path

import pytest

from lume_tool import fragments as frag
from lume_tool import packages

OLD = ".SIGN.RSA.r36os.rsa.pub"   # the signature of the packages built before the rename


def _segment(files: dict[str, bytes], cut: bool = True) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.GNU_FORMAT) as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    raw = buf.getvalue()
    if cut:
        raw = raw.rstrip(b"\0")
        raw += b"\0" * (-len(raw) % 512)
    return gzip.compress(raw, mtime=0)


def _apk(path: Path, signer: str, name: str = "lume-x", body: bytes = b"hi\n") -> Path:
    pkginfo = f"pkgname = {name}\npkgver = 1.0-r0\narch = noarch\n".encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_segment({signer: b"s" * 64}) + _segment({".PKGINFO": pkginfo})
                     + _segment({"usr/share/x": body}, cut=False))
    return path


def _index(path: Path, signer: str) -> Path:
    path.write_bytes(_segment({signer: b"s" * 64}) + _segment({"APKINDEX": b"P:x\n"}, cut=False))
    return path


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setenv("LUME_OUT", str(tmp_path / "out"))
    monkeypatch.setattr(packages, "_resign_done", False)
    calls = {"sign": [], "reindex": []}

    def fake_sign(apks, tag):
        calls["sign"].append((tag, [a.name for a, _c in apks]))
        for apk, _content in apks:   # what abuild-sign does: a new signature segment
            parts = frag.split_apk(apk)
            apk.write_bytes(_segment({packages.signature_name(): b"n" * 64})
                            + parts.control + parts.data)

    monkeypatch.setattr(packages, "sign_with_lume_content", fake_sign)
    monkeypatch.setattr(packages, "reindex", lambda arches: calls["reindex"].append(list(arches)))
    return tmp_path / "out" / "repo", calls


def test_signers_reads_the_signature_segment(tmp_path):
    assert frag.signers(_apk(tmp_path / "a.apk", OLD)) == [OLD]
    assert frag.signers(_index(tmp_path / "APKINDEX.tar.gz", OLD)) == [OLD]
    assert packages.signature_name() == ".SIGN.RSA.lume.rsa.pub"


def test_old_key_packages_are_signed_again_once(repo):
    root, calls = repo
    old_arm = _apk(root / "armv7" / "lume-a-1.0-r0.apk", OLD, "lume-a", b"arm")
    old_x86 = _apk(root / "x86_64" / "lume-a-1.0-r0.apk", OLD, "lume-a", b"x86")
    new = _apk(root / "armv7" / "lume-b-1.0-r0.apk", packages.signature_name(), "lume-b")
    new_bytes = new.read_bytes()
    _index(root / "armv7" / "APKINDEX.tar.gz", OLD)

    done = packages.resign_published()

    assert sorted(p.name for p in done) == ["lume-a-1.0-r0.apk"] * 2
    assert frag.signers(old_arm) == frag.signers(old_x86) == [packages.signature_name()]
    assert new.read_bytes() == new_bytes                       # already on the current key
    assert sorted(t for t, _n in calls["sign"]) == ["resign-armv7", "resign-x86_64"]
    assert calls["reindex"] == [["armv7", "x86_64"]]
    assert not (root / "armv7" / "APKINDEX.tar.gz").exists()   # made again by reindex
    assert packages.resign_published() == [] and len(calls["sign"]) == 2   # once per process


def test_identical_noarch_copies_stay_identical(repo):
    root, calls = repo
    copies = [_apk(root / a / "lume-n-1.0-r0.apk", OLD, "lume-n") for a in packages.REPO_ARCHES]

    packages.resign_published()

    assert len(calls["sign"]) == 1                              # signed once, then copied
    assert len({c.read_bytes() for c in copies}) == 1
    assert frag.signers(copies[0]) == [packages.signature_name()]


def test_nothing_to_do_on_the_current_key(repo):
    root, calls = repo
    _apk(root / "aarch64" / "lume-a-1.0-r0.apk", packages.signature_name())
    _index(root / "aarch64" / "APKINDEX.tar.gz", packages.signature_name())
    assert packages.resign_published() == []
    assert calls == {"sign": [], "reindex": []}


def test_an_index_with_the_old_signer_alone_is_made_again(repo):
    root, calls = repo
    _apk(root / "aarch64" / "lume-a-1.0-r0.apk", packages.signature_name())
    _index(root / "aarch64" / "APKINDEX.tar.gz", OLD)
    assert packages.resign_published() == []
    assert calls["reindex"] == [["aarch64"]]
