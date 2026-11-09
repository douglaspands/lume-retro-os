"""Argumentos do QEMU/podman da VM: controles do PC e pasta compartilhada (7.8)."""

from pathlib import Path

import pytest

from r36os import vm
from r36os.vm import VmConfig, podman_argv, qemu_argv

PAD = "/dev/input/event7"


@pytest.fixture(autouse=True)
def _no_host_side_effects(monkeypatch):
    monkeypatch.setattr(vm, "ensure_vm_image", lambda: "localhost/r36os-vm")
    monkeypatch.setattr(vm, "gpu_driver", lambda: "amdgpu")


def _cfg(tmp_path: Path, **kw) -> VmConfig:
    return VmConfig(disk=tmp_path / "run.img", headless=True, **kw)


def test_gamepad_passthrough(tmp_path):
    cfg = _cfg(tmp_path, gamepads=[PAD])
    assert f"virtio-input-host-pci,evdev={PAD}" in qemu_argv(cfg)
    p = podman_argv(cfg)
    assert p[p.index(PAD) - 1] == "--device"


def test_no_share_by_default(tmp_path):
    cfg = _cfg(tmp_path)
    assert "-virtfs" not in qemu_argv(cfg)
    assert not any(a.endswith(":/share:ro") for a in podman_argv(cfg))


def test_share_is_read_only(tmp_path):
    roms = tmp_path / "Jogos"
    roms.mkdir()
    cfg = _cfg(tmp_path, share_dir=roms)
    q = qemu_argv(cfg)
    virtfs = q[q.index("-virtfs") + 1]
    assert "mount_tag=hostshare" in virtfs and "readonly=on" in virtfs
    assert f"{roms}:/share:ro" in podman_argv(cfg)


def test_container_name(tmp_path):
    assert "--name" not in podman_argv(_cfg(tmp_path))
    p = podman_argv(_cfg(tmp_path, name="r36os-test-vm"))
    assert p[p.index("--name") + 1] == "r36os-test-vm"


def test_test_vm_uses_fixed_container_name():
    from r36os import selftest

    assert selftest.CONTAINER == "r36os-test-vm"


def test_share_missing_dir_fails(tmp_path):
    with pytest.raises(NotADirectoryError):
        podman_argv(_cfg(tmp_path, share_dir=tmp_path / "nao-existe"))


def test_hostshare_only_on_vm():
    from r36os.paths import REPO_ROOT

    svc = (REPO_ROOT / "rootfs/overlay/etc/init.d/r36os-hostshare").read_text()
    assert '= vm ] || return 0' in svc
    assert "-o ro," in svc
    assert "before r36os-playlists frontend" in svc
