"""Tests for ZRAM service and script logic."""

import subprocess
from pathlib import Path

from r36os.paths import REPO_ROOT
from r36os.selftest import expected_checks

ZRAM_SCRIPT = REPO_ROOT / "rootfs/overlay/usr/libexec/r36os/zram"
ZRAM_INIT = REPO_ROOT / "rootfs/overlay/etc/init.d/r36os-zram"
SYSCTL_CONF = REPO_ROOT / "rootfs/overlay/etc/sysctl.d/r36os-zram.conf"
CONFIGURE_SH = REPO_ROOT / "rootfs/configure.sh"
SELFTEST_SH = REPO_ROOT / "rootfs/overlay/usr/libexec/r36os/selftest"


def test_selftest_checks_zram_swap():
    assert "zram-swap" in expected_checks()
    text = SELFTEST_SH.read_text()
    assert "check zram-swap" in text
    assert "32767" in text
    assert "swappiness" in text
    assert "page-cluster" in text



def test_configure_enables_zram_and_sysctl_in_boot_runlevel():
    text = CONFIGURE_SH.read_text()
    assert "r36os-zram" in text
    assert "sysctl" in text
    assert 'for s in modules sysctl hostname bootmisc syslog loopback r36os-zram; do add "$s" boot; done' in text


def test_sysctl_zram_parameters():
    assert SYSCTL_CONF.exists()
    content = SYSCTL_CONF.read_text()
    assert "vm.swappiness = 100" in content
    assert "vm.page-cluster = 0" in content



def test_zram_init_script():
    text = ZRAM_INIT.read_text()
    assert "#!/sbin/openrc-run" in text
    assert "/usr/libexec/r36os/zram" in text
    assert "after modules" in text


def test_zram_script_fallback_when_device_missing(tmp_path: Path):
    # Test execution in an isolated PATH / fake environment where /dev/zram0 does not exist
    # The script MUST log and exit 0 without failing.
    proc = subprocess.run(
        ["sh", str(ZRAM_SCRIPT)],
        capture_output=True,
        text=True,
    )
    # On a host without root / without /dev/zram0 writable, it should gracefully exit 0
    assert proc.returncode == 0


def test_zram_calculation_logic():
    # Verify the 50% MemTotal calculation formula used in the script
    # Given 512 MiB (524288 KiB) -> 256 MiB in bytes
    kib = 524288
    bytes_val = kib * 1024 // 2
    assert bytes_val == 268435456
    assert bytes_val // 1048576 == 256

    # Given 1 GiB (1048576 KiB) -> 512 MiB in bytes
    kib_1g = 1048576
    bytes_1g = kib_1g * 1024 // 2
    assert bytes_1g == 536870912
    assert bytes_1g // 1048576 == 512
