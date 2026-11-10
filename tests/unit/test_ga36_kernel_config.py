"""GA36 kernel config (task 9.4): board/ga36/kernel.config and the generated .config.

The final .config (out/ga36/kernel/config) only exists after `r36os build ga36`; without
it the tests that depend on it are skipped.
"""

import re

import pytest

from r36os.kernel import KERNEL_TARGETS, OWN_DRIVER_FILES
from r36os.paths import REPO_ROOT, out_dir

FRAGMENT = (REPO_ROOT / "board/ga36/kernel.config").read_text()
BUILT = out_dir() / "ga36/kernel/config"


def _options(text: str) -> dict[str, str]:
    return dict(re.findall(r"^(CONFIG_\w+)=(.*)$", text, re.M))


def test_fragment_enables_own_drivers_builtin():
    opts = _options(FRAGMENT)
    for o in ("CONFIG_DRM_PANEL_GA36MB_JD9366", "CONFIG_JOYSTICK_GA36MB", "CONFIG_DRM_SUN6I_DSI",
              "CONFIG_PHY_SUN6I_MIPI_DPHY", "CONFIG_FRAMEBUFFER_CONSOLE", "CONFIG_SQUASHFS_ZSTD",
              "CONFIG_OVERLAY_FS", "CONFIG_EXFAT_FS", "CONFIG_BLK_DEV_LOOP",
              "CONFIG_ZSMALLOC", "CONFIG_ZRAM", "CONFIG_ZRAM_BACKEND_LZ4", "CONFIG_ZRAM_DEF_COMP_LZ4"):
        assert opts.get(o) == "y", o  # built in (D3), not modules


def test_fragment_keeps_mainline_cpufreq_and_thermal():
    # kernel default governor and mainline OPPs/thermal: the fragment does not touch them
    assert not re.search(r"CPU_FREQ_DEFAULT_GOV|CPU_FREQ_GOV_|THERMAL_DEFAULT_GOV", FRAGMENT)
    assert KERNEL_TARGETS["ga36"][2] == "sunxi_defconfig"


def test_own_drivers_are_the_patched_files():
    patches = "".join(p.read_text() for p in (REPO_ROOT / "kernel/patches").glob("*.patch"))
    for f in OWN_DRIVER_FILES:
        assert f"+++ b/drivers/" in patches and f in patches, f


@pytest.mark.skipif(not BUILT.exists(), reason="GA36 kernel not built yet")
def test_built_config():
    opts = _options(BUILT.read_text())
    assert opts.get("CONFIG_CPUFREQ_DT") == "y"
    assert opts.get("CONFIG_SUN8I_THERMAL") == "y"
    # default governor: the kernel default (schedutil), unchanged
    assert opts.get("CONFIG_CPU_FREQ_DEFAULT_GOV_SCHEDUTIL") == "y"
    for want, value in _options(FRAGMENT).items():
        assert opts.get(want) == value, want
    kdir = BUILT.parent
    assert (kdir / "zImage").stat().st_size > 1_000_000
    dtbs = sorted(p.name for p in (kdir / "dtbs").glob("*.dtb"))
    assert dtbs == ["sun8i-a33-ga36-mb-v1.2-panel1.dtb", "sun8i-a33-ga36-mb-v1.2-panel2.dtb"]
    # no warnings in the build (those in our own drivers already fail it)
    assert "warning:" not in (kdir / "build-warnings.log").read_text()
