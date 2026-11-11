"""Unit tests for scripts/eject.py."""

import importlib.util
from pathlib import Path

from r36os.paths import REPO_ROOT

EJECT_SCRIPT = REPO_ROOT / "scripts/eject.py"


def _load_eject_module():
    import sys
    spec = importlib.util.spec_from_file_location("eject_module", EJECT_SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["eject_module"] = mod
    spec.loader.exec_module(mod)
    return mod



def test_eject_module_loads():
    mod = _load_eject_module()
    assert hasattr(mod, "list_removable_devices")
    assert hasattr(mod, "eject_device")
    assert hasattr(mod, "unmount_device")


def test_list_removable_devices_filters(monkeypatch, tmp_path: Path):
    mod = _load_eject_module()
    # Mock /sys/block with a non-removable and a removable device
    sys_block = tmp_path / "sys_block"
    sys_block.mkdir()

    sda = sys_block / "sda"
    sda.mkdir()
    (sda / "removable").write_text("0\n")
    (sda / "size").write_text("1000000\n")

    sdc = sys_block / "sdc"
    sdc.mkdir()
    (sdc / "removable").write_text("1\n")
    (sdc / "size").write_text("30000000\n")
    (sdc / "device").mkdir()
    (sdc / "device/model").write_text("SD Card Reader\n")

    monkeypatch.setattr(mod, "SYS_BLOCK", sys_block)
    devs = mod.list_removable_devices()
    assert len(devs) == 1
    assert devs[0].name == "sdc"
    assert "SD Card Reader" in devs[0].label



def test_eject_device_runs_power_off(monkeypatch):
    mod = _load_eject_module()
    commands = []

    def mock_run(cmd, *args, **kwargs):
        commands.append(cmd)
        class Ret:
            returncode = 0
            stdout = ""
            stderr = ""
        return Ret()

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr(Path, "is_block_device", lambda self: True)
    rc = mod.eject_device("/dev/sdc")
    assert rc == 0
    assert any("sync" in c for c in commands)
    assert any("blockdev" in c and "--flushbufs" in c and "/dev/sdc" in c for c in commands)
    assert any("udisksctl" in c and "power-off" in c and "/dev/sdc" in c for c in commands)

