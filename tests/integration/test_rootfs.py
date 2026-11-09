"""Tarefas 3.1-3.3: rootfs x86_64, manifesto estável e SYSTEM squashfs.

Requer podman e os pacotes locais em out/repo/x86_64 (uv run r36os pkg vm ...).
"""

import io
import os
import shutil
import tarfile

import pytest

from r36os import rootfs
from r36os.container import Container, ensure_builder
from r36os.targets import get_target

pytestmark = pytest.mark.skipif(shutil.which("podman") is None, reason="sem podman")
VM = get_target("vm")


@pytest.fixture(scope="module")
def first_build():
    tar = rootfs.build_rootfs(VM)
    manifest = (rootfs.target_out(VM) / "manifest.txt").read_text()
    return tar, manifest


def _read(tar: tarfile.TarFile, name: str) -> str:
    return tar.extractfile(name).read().decode()


def test_rootfs_has_openrc_init_and_game_user(first_build):
    tar_path, _ = first_build
    with tarfile.open(tar_path) as tar:
        names = set(tar.getnames())
        assert "./sbin/init" in names
        assert "./sbin/openrc" in names
        inittab = _read(tar, "./etc/inittab")
        assert "::sysinit:/usr/libexec/r36os/rc-tee sysinit" in inittab
        assert "/sbin/openrc" in _read(tar, "./usr/libexec/r36os/rc-tee")
        passwd = _read(tar, "./etc/passwd")
        game = next(l for l in passwd.splitlines() if l.startswith("game:"))
        assert game.split(":")[2] == "1000"
        groups = _read(tar, "./etc/group")
        for g in ("video", "input", "audio"):
            line = next(l for l in groups.splitlines() if l.startswith(g + ":"))
            assert "game" in line.split(":")[3].split(",")
        # root sem senha, só na serial
        shadow = _read(tar, "./etc/shadow")
        assert shadow.splitlines()[0].startswith("root::")
        assert _read(tar, "./etc/securetty").split() == ["ttyS0"]
        assert "tty1::" not in _read(tar, "./etc/inittab")
        assert "Lume Retro OS" in _read(tar, "./etc/os-release")
        # /boot vazio no SYSTEM (o kernel vai para a partição BOOT)
        assert not [n for n in names if n.startswith("./boot/")]


def test_manifest_lists_packages(first_build):
    _, manifest = first_build
    pkgs = rootfs.read_manifest(rootfs.target_out(VM) / "manifest.txt")
    assert manifest.startswith("# arch: x86_64")
    assert pkgs["retroarch"].endswith("-r100")
    assert "linux-virt" in pkgs
    assert "libretro-pcsx-rearmed" in pkgs


def test_manifest_is_stable(first_build):
    _, manifest = first_build
    rootfs.build_rootfs(VM)
    assert (rootfs.target_out(VM) / "manifest.txt").read_text() == manifest


def test_system_squashfs(first_build):
    tar_path, _ = first_build
    system = rootfs.make_system(VM, tar_path, rootfs.target_out(VM) / "SYSTEM")
    assert system.stat().st_size <= 768 * 2**20
    info = Container(
        image=ensure_builder(VM), volumes={system.parent: "/out"}
    ).sh("unsquashfs -s /out/SYSTEM", capture_output=True, text=True).stdout
    assert "Compression zstd" in info


def test_inflated_rootfs_fails(tmp_path):
    # rootfs pequeno inflado com 6 MiB aleatórios (incompressíveis) e limite de 4 MiB
    tar_path = tmp_path / "rootfs.tar"
    with tarfile.open(tar_path, "w") as tar:
        data = os.urandom(6 * 2**20)
        info = tarfile.TarInfo("./var/lixo.bin")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    with pytest.raises(rootfs.SystemTooLargeError):
        rootfs.make_system(VM, tar_path, tmp_path / "out" / "SYSTEM", limit_mib=4)
    assert not (tmp_path / "out" / "SYSTEM").exists()


def test_default_limit_is_768():
    assert rootfs.SYSTEM_LIMIT_MIB == 768
