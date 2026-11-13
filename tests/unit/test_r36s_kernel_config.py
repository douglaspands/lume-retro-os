"""R36S kernel config (task 4.1 of r36s-single-card): board/r36s/kernel.config and the
generated .config.

The final .config (out/r36s/kernel/config) only exists after `r36os build console`;
without it the tests that depend on it are skipped.
"""

import re

import pytest

from r36os import bootarea, build
from r36os.kernel import KERNEL_TARGETS, OWN_DRIVER_FILES
from r36os.paths import REPO_ROOT, out_dir

BOARD = REPO_ROOT / "board/r36s"
FRAGMENT = (BOARD / "kernel.config").read_text()
BUILT = out_dir() / "r36s/kernel/config"


def _options(text: str) -> dict[str, str]:
    return dict(re.findall(r"^(CONFIG_\w+)=(.*)$", text, re.M))


def test_kernel_target_is_arm64():
    assert KERNEL_TARGETS["r36s"] == ("arm64", "aarch64-linux-gnu-", "defconfig", "Image")
    assert build.DTS_VENDOR["r36s"] == ("arm64", "rockchip")
    assert "panel-sitronix-st7703.c" in OWN_DRIVER_FILES


@pytest.mark.parametrize("option", [
    # panel, GPU and fbcon (D7): the verbose boot shows on the panel early
    "CONFIG_DRM", "CONFIG_DRM_ROCKCHIP", "CONFIG_ROCKCHIP_VOP",
    "CONFIG_PHY_ROCKCHIP_INNO_DSIDPHY", "CONFIG_DRM_PANEL_SITRONIX_ST7703",
    "CONFIG_BACKLIGHT_PWM", "CONFIG_DRM_FBDEV_EMULATION", "CONFIG_FRAMEBUFFER_CONSOLE",
    "CONFIG_DRM_PANFROST",
    # PMIC RK817: charger, codec and the speaker amplifier
    "CONFIG_CHARGER_RK817", "CONFIG_SND", "CONFIG_SND_SOC_ROCKCHIP_I2S",
    "CONFIG_SND_SOC_RK817", "CONFIG_SND_SIMPLE_CARD", "CONFIG_SND_SOC_SIMPLE_AMPLIFIER",
    # gamepad: sticks on the SARADC behind a GPIO mux
    "CONFIG_ROCKCHIP_SARADC", "CONFIG_IIO_MUX", "CONFIG_MUX_GPIO", "CONFIG_JOYSTICK_ADC",
    "CONFIG_INPUT_JOYDEV", "CONFIG_INPUT_UINPUT",
    # boot (D6) and memory
    "CONFIG_MMC_DW_ROCKCHIP", "CONFIG_SQUASHFS_ZSTD", "CONFIG_OVERLAY_FS", "CONFIG_EXFAT_FS",
    "CONFIG_TMPFS_XATTR", "CONFIG_ZSMALLOC", "CONFIG_ZRAM", "CONFIG_ZRAM_BACKEND_LZ4",
    "CONFIG_ZRAM_DEF_COMP_LZ4",
])
def test_fragment_builds_in(option):
    assert _options(FRAGMENT).get(option) == "y", option  # built in, not a module


def test_kernel_cmdline_and_boot_options():
    tty, baud = (BOARD / "serial").read_text().split()
    assert (tty, baud) == ("ttyS2", "1500000")  # the speed of the factory bootloader
    cmdline = re.search(r'^CONFIG_CMDLINE="(.*)"$', FRAGMENT, re.M).group(1)
    assert f"root=PARTUUID={bootarea.DISK_ID}-01" in cmdline and "rootwait" in cmdline
    # debug serial and the panel; tty1 last becomes /dev/console
    assert cmdline.index(f"console={tty},{baud}") < cmdline.index("console=tty1")
    assert "quiet" not in cmdline
    opts = _options(FRAGMENT)
    assert opts["CONFIG_CMDLINE_FORCE"] == "y"
    assert opts["CONFIG_INITRAMFS_SOURCE"] == '"/initramfs/initramfs.cpio"'
    assert opts["CONFIG_LOCALVERSION"] == '"-r36os"'


def test_fragment_keeps_mainline_cpufreq_and_thermal():
    assert not re.search(r"CPU_FREQ_DEFAULT_GOV|CPU_FREQ_GOV_|THERMAL_DEFAULT_GOV", FRAGMENT)


@pytest.mark.skipif(not BUILT.exists(), reason="R36S kernel not built yet")
def test_built_config():
    opts = _options(BUILT.read_text())
    for want, value in _options(FRAGMENT).items():
        assert opts.get(want) == value, want
    kdir = BUILT.parent
    assert (kdir / "Image").stat().st_size > 1_000_000
    assert "warning:" not in (kdir / "build-warnings.log").read_text()
