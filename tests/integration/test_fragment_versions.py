"""build-speed 6.1: a fragment compiles only when its inputs change and gets a new version
only when its content changes; old versions leave the repository.

Real abuild in the x86_64 builder, with out/ and the cache in tmp (the real out/repo and
.cache are never touched). Requires podman.
"""

import shutil

import pytest

from lume_tool import fragments, manifests, packages
from lume_tool.container import Container, ensure_builder
from lume_tool.paths import REPO_ROOT
from lume_tool.targets import get_target

pytestmark = pytest.mark.skipif(shutil.which("podman") is None, reason="no podman")

NAME = "lume-hello-arch"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("LUME_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("LUME_CACHE", str(tmp_path / "cache"))
    aports = tmp_path / "aports"
    shutil.copytree(REPO_ROOT / "tests/fixtures/aports" / NAME, aports / NAME)
    builds = []
    real = packages._container

    def counting(target, *a, **kw):
        c = real(target, *a, **kw)
        if kw.get("repodest") is not None:   # only the abuild runs use a staging repodest
            builds.append(target.alpine_arch)
        return c

    monkeypatch.setattr(packages, "_container", counting)
    return aports, builds


def _install(name: str) -> str:
    """`apk add --root` from the local repository, trusting only the local key."""
    vm = get_target("vm")
    c = Container(image=ensure_builder(vm), platform=vm.oci_platform,
                  volumes={packages.out_dir() / "repo": "/repo/lume",
                           packages.keys_dir(): "/keys"})
    out = c.sh(
        "mkdir -p /t/etc/apk/keys\n"
        f"cp /keys/{packages.KEY_NAME}.rsa.pub /t/etc/apk/keys/\n"
        "apk add --root /t --initdb --no-network --arch x86_64 "
        f"--repositories-file /dev/null --repository /repo/lume {name}\n"
        f"grep -A3 '^P:{name}$' /t/lib/apk/db/installed\n",
        capture_output=True, text=True)
    return out.stdout


def test_inputs_decide_the_build_and_content_decides_the_version(env, capsys):
    aports, builds = env
    vm = get_target("vm")
    repo = packages.arch_repo_dir("x86_64")

    # first build: published with the APKBUILD pkgrel, commit and .lume-content inside
    published = packages.build_packages(vm, [NAME], aports=aports)
    assert [p.name for p in published] == [f"{NAME}-1.0-r0.apk"]
    entry = packages.read_repo_hashes("x86_64").packages[NAME]
    apk = repo / entry.file
    assert dict(packages.read_apk_pkginfo(apk))["commit"] == entry.inputs[:40]
    assert fragments.apk_lume_content(apk) == entry.content == fragments.apk_content_hash(apk)
    assert "V:1.0-r0" in _install(NAME)   # apk accepts the extra control file and signature
    assert builds == ["x86_64"]

    # no change: nothing compiled, nothing published
    assert packages.build_packages(vm, [NAME], aports=aports) == []
    assert builds == ["x86_64"]
    assert "inputs unchanged, not built" in capsys.readouterr().out

    # --force: compiled again, same content, not published
    assert packages.build_packages(vm, [NAME], aports=aports, force=True) == []
    assert builds == ["x86_64"] * 2
    assert "same content" in capsys.readouterr().out
    assert sorted(p.name for p in repo.glob("*.apk")) == [f"{NAME}-1.0-r0.apk"]

    # a changed file: the next pkgrel, without editing the APKBUILD
    (aports / NAME / "greeting").write_text("hello again\n")
    assert [p.name for p in packages.build_packages(vm, [NAME], aports=aports)] == [
        f"{NAME}-1.0-r1.apk"]
    (aports / NAME / "greeting").write_text("hello for the third time\n")
    assert [p.name for p in packages.build_packages(vm, [NAME], aports=aports)] == [
        f"{NAME}-1.0-r2.apk"]
    assert "freed" in capsys.readouterr().out

    # newest and previous kept, the index rebuilt without the removed one
    assert sorted(p.name for p in repo.glob("*.apk")) == [f"{NAME}-1.0-r1.apk",
                                                          f"{NAME}-1.0-r2.apk"]
    assert "V:1.0-r2" in _install(NAME)
    assert "pkgrel=0" in (aports / NAME / "APKBUILD").read_text()


def test_noarch_fragment_skips_and_versions_in_every_arch(tmp_path, monkeypatch):
    monkeypatch.setenv("LUME_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("LUME_CACHE", str(tmp_path / "cache"))
    aports = REPO_ROOT / "tests/fixtures/aports"
    apks = packages.build_noarch(["lume-hello"], aports=aports)
    assert [a.name for a in apks] == ["lume-hello-1.0-r0.apk"]
    packages.publish_noarch(apks)
    for arch in packages.REPO_ARCHES:
        h = packages.read_repo_hashes(arch).packages["lume-hello"]
        assert h.version == "1.0-r0"
        assert fragments.apk_lume_content(packages.arch_repo_dir(arch) / h.file) == h.content
    assert packages.build_noarch(["lume-hello"], aports=aports) == []
    assert packages.build_noarch(["lume-hello"], aports=aports, force=True) == []
    assert manifests.read_hashes(packages.hashes_path("armv7"), "armv7").packages[
        "lume-hello"].version == "1.0-r0"
