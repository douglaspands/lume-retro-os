"""GPU devfreq pinning (task 9.8): the clock must not change under load at game start."""

import os
import subprocess
from pathlib import Path

from r36os.paths import REPO_ROOT

SCRIPT = REPO_ROOT / "rootfs/overlay/usr/libexec/r36os/gpu-pin"
INIT = REPO_ROOT / "rootfs/overlay/etc/init.d/r36os-gpu"
CONFIGURE_SH = REPO_ROOT / "rootfs/configure.sh"


def _device(root: Path, name: str, freqs: str, cur: int = 144000000) -> Path:
    d = root / name
    d.mkdir(parents=True)
    (d / "available_frequencies").write_text(freqs + "\n")
    (d / "cur_freq").write_text(f"{cur}\n")
    (d / "min_freq").write_text("144000000\n")
    (d / "max_freq").write_text("384000000\n")
    return d


def _run(root: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ, GPU_DEVFREQ_DIR=str(root))
    return subprocess.run(["sh", str(SCRIPT)], capture_output=True, text=True, env=env)


def test_pins_min_freq_to_the_highest_frequency(tmp_path: Path):
    # unsorted on purpose: the highest must be picked numerically, not by position
    gpu = _device(tmp_path, "1c40000.gpu", "240000000 384000000 144000000 312000000")
    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert (gpu / "min_freq").read_text().strip() == "384000000"
    assert (gpu / "max_freq").read_text().strip() == "384000000"
    assert "pinned to 384 MHz" in proc.stdout


def test_only_gpu_devices_are_touched(tmp_path: Path):
    gpu = _device(tmp_path, "1c40000.gpu", "144000000 384000000")
    other = _device(tmp_path, "1c62000.dram", "100000000 600000000")
    assert _run(tmp_path).returncode == 0
    assert (gpu / "min_freq").read_text().strip() == "384000000"
    assert (other / "min_freq").read_text().strip() == "144000000"   # unchanged


def test_without_devfreq_it_does_nothing_and_succeeds(tmp_path: Path):
    assert _run(tmp_path).returncode == 0                       # empty directory (the VM)
    assert _run(tmp_path / "missing").returncode == 0           # no devfreq class at all


def test_empty_frequency_list_leaves_the_device_alone(tmp_path: Path):
    gpu = _device(tmp_path, "1c40000.gpu", "")
    proc = _run(tmp_path)
    assert proc.returncode == 0
    assert (gpu / "min_freq").read_text().strip() == "144000000"


def test_service_runs_before_the_frontend_in_the_boot_runlevel():
    text = INIT.read_text()
    assert "#!/sbin/openrc-run" in text
    assert "/usr/libexec/r36os/gpu-pin" in text
    assert "before bootmisc" in text            # boot runlevel finishes before default (frontend)
    assert "add r36os-gpu boot" in CONFIGURE_SH.read_text()


def test_script_and_service_are_executable_and_in_english():
    for f in (SCRIPT, INIT):
        assert os.access(f, os.X_OK), f
        assert not any(ord(c) > 127 for c in f.read_text()), f
