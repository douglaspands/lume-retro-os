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


def _nic(q):
    return q[q.index("-nic") + 1]


def test_no_network_by_default(tmp_path):
    # `r36os vm` without --ssh and `r36os test-vm`: no NIC, no published port
    cfg = _cfg(tmp_path)
    assert _nic(qemu_argv(cfg)) == "none"
    p = podman_argv(cfg)
    assert "-p" not in p
    assert not any(a.startswith("--network") for a in p)   # the container's own network


def test_ssh_forwards_only_port_22_on_the_pc_loopback(tmp_path):
    cfg = _cfg(tmp_path, ssh_port=2222)
    q = qemu_argv(cfg)
    assert q.count("-nic") == 1
    nic = _nic(q)
    assert nic.startswith("user,") and "model=virtio-net-pci" in nic
    assert "restrict=on" in nic.split(",")           # no route out of the PC
    # bound on the PC's loopback: the guest sees the connections from 10.0.2.2 (on-link);
    # a published port (-p) brought them from the container's address and the guest,
    # without a default route, never answered (live check of 3.3)
    assert nic.endswith("hostfwd=tcp:127.0.0.1:2222-:22")
    p = podman_argv(cfg)
    assert "--network=host" in p
    assert "-p" not in p


def test_ssh_custom_port(tmp_path):
    cfg = _cfg(tmp_path, ssh_port=2300)
    assert "hostfwd=tcp:127.0.0.1:2300-:22" in _nic(qemu_argv(cfg))


def test_test_vm_has_no_user_network(tmp_path, monkeypatch):
    # selftest.test_vm builds its VmConfig without ssh_port: the same -nic none as before
    import inspect

    from r36os import selftest

    src = inspect.getsource(selftest)
    assert "ssh_port" not in src
    assert _nic(qemu_argv(VmConfig(disk=tmp_path / "t.img", headless=True,
                                   name=selftest.CONTAINER))) == "none"


def test_cli_ssh_option():
    from r36os.cli import _parser

    p = _parser()
    assert p.parse_args(["vm"]).ssh is None
    assert p.parse_args(["vm", "--ssh"]).ssh == vm.DEFAULT_SSH_PORT == 2222
    assert p.parse_args(["vm", "--ssh", "2300"]).ssh == 2300
    with pytest.raises(SystemExit):
        p.parse_args(["vm", "--ssh", "22"])
    assert not hasattr(p.parse_args(["test-vm"]), "ssh")


def test_hostshare_only_on_vm():
    from r36os.paths import REPO_ROOT

    svc = (REPO_ROOT / "aports/lume-net/files/etc/init.d/r36os-hostshare").read_text()
    assert '= vm ] || return 0' in svc
    assert "-o ro," in svc
    assert "before r36os-playlists frontend" in svc
