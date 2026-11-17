"""GA36 kernel config (task 9.4): board/ga36/kernel.config and the generated .config.

The final .config (out/ga36/kernel/config) only exists after `r36os build console`; without
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
    # kernel default governors (schedutil, step_wise) and mainline OPPs/thermal: the
    # fragment never picks a default, set or unset
    assert not re.search(r"CPU_FREQ_DEFAULT_GOV|THERMAL_DEFAULT_GOV", FRAGMENT)
    assert KERNEL_TARGETS["ga36"][2] == "sunxi_defconfig"


def test_fragment_adds_the_game_governor_cpufreq_governors():
    # game-governor D10: ondemand and conservative for the profile candidates; D12: the
    # load controller writes scaling_setspeed under userspace. Built in, never modules.
    opts = _options(FRAGMENT)
    for o in ("CONFIG_CPU_FREQ_GOV_ONDEMAND", "CONFIG_CPU_FREQ_GOV_CONSERVATIVE",
              "CONFIG_CPU_FREQ_GOV_USERSPACE"):
        assert opts.get(o) == "y", o
    # no other CPU_FREQ_GOV_* option is set or unset by the fragment
    govs = set(re.findall(r"^#? ?(CONFIG_CPU_FREQ_GOV_\w+)", FRAGMENT, re.M))
    assert govs == {"CONFIG_CPU_FREQ_GOV_ONDEMAND", "CONFIG_CPU_FREQ_GOV_CONSERVATIVE",
                    "CONFIG_CPU_FREQ_GOV_USERSPACE"}


def test_fragment_enables_cpufreq_stats():
    # game-governor D5: the measurements read stats/time_in_state per clock.
    assert _options(FRAGMENT).get("CONFIG_CPU_FREQ_STAT") == "y"


def test_fragment_enables_thermal_sensor_and_gpu_cooling():
    # the A33 THS is driven by the GPADC IIO driver (SUN8I_THERMAL covers newer SoCs), and
    # the GPU is a cooling device only with DEVFREQ_THERMAL (tasks 9.8 follow-up and 9.10)
    opts = _options(FRAGMENT)
    assert opts.get("CONFIG_SUN4I_GPADC") == "y"
    assert opts.get("CONFIG_DEVFREQ_THERMAL") == "y"


def test_fragment_enables_kexec_and_the_selection_keys():
    # boot-dtb-select D2/D7: kexec to switch the DTB, and the volume keys on the LRADC
    # built in (the build fails if an option of the fragment does not stick)
    opts = _options(FRAGMENT)
    for o in ("CONFIG_KEXEC", "CONFIG_HOTPLUG_CPU", "CONFIG_INPUT_EVDEV",
              "CONFIG_KEYBOARD_SUN4I_LRADC", "CONFIG_WATCHDOG", "CONFIG_SUNXI_WATCHDOG"):
        assert opts.get(o) == "y", o
    # D11: a watchdog armed before the switch must reset a start that never opens it
    assert opts.get("CONFIG_WATCHDOG_OPEN_TIMEOUT") == "30"


def test_fragment_builds_in_the_usb_gadget():
    # usb-device-access D2: configfs gadget with MTP (FunctionFS) and NCM, built in, on the
    # MUSB in dual-role
    opts = _options(FRAGMENT)
    for o in ("CONFIG_USB_MUSB_DUAL_ROLE", "CONFIG_USB_CONFIGFS", "CONFIG_USB_CONFIGFS_F_FS",
              "CONFIG_USB_CONFIGFS_NCM"):
        assert opts.get(o) == "y", o
    # umtprd's control channel: without it "msgget error 38" on every boot
    assert opts.get("CONFIG_SYSVIPC") == "y"


HOST_BUILTIN = ("CONFIG_USB_STORAGE", "CONFIG_HID_GENERIC", "CONFIG_FW_LOADER_COMPRESS",
                "CONFIG_FW_LOADER_COMPRESS_ZSTD", "CONFIG_WIRELESS", "CONFIG_WLAN",
                "CONFIG_BT_BREDR", "CONFIG_BT_LE", "CONFIG_BT_HCIBTUSB_RTL")
HOST_MODULES = ("CONFIG_JOYSTICK_XPAD", "CONFIG_LEDS_CLASS_MULTICOLOR",
                "CONFIG_HID_PLAYSTATION", "CONFIG_HID_SONY",
                "CONFIG_HID_NINTENDO", "CONFIG_CFG80211", "CONFIG_MAC80211", "CONFIG_RFKILL",
                "CONFIG_RTW88", "CONFIG_RTW88_8821CU", "CONFIG_RTL8XXXU", "CONFIG_ATH9K_HTC",
                "CONFIG_BT", "CONFIG_BT_HIDP", "CONFIG_BT_HCIBTUSB", "CONFIG_UHID")


def test_fragment_has_the_host_role_and_the_usb_radios():
    # usb-device-access D8-D10 (P-38, P-15): pendrive built in, the rest as modules that
    # udev loads when the device shows up; zstd firmware (Alpine's linux-firmware-*)
    opts = _options(FRAGMENT)
    for o in HOST_BUILTIN:
        assert opts.get(o) == "y", o
    for o in HOST_MODULES:
        assert opts.get(o) == "m", o


def test_a33_secondary_cpus_can_be_killed_for_kexec():
    # machine_kexec_prepare() refuses SMP without .cpu_kill (GA36 boot 20): patch 0027
    # gives the sun8i enable method of the A33 .cpu_die and .cpu_kill
    patch = (REPO_ROOT / "kernel/patches/0027-ARM-sunxi-sun8i-add-CPU-hotplug-so-kexec-can-run.patch"
             ).read_text()
    assert "+++ b/arch/arm/mach-sunxi/platsmp.c" in patch
    assert "+\t.cpu_kill\t\t= sun8i_cpu_kill," in patch
    assert "+\t.cpu_die\t\t= sun8i_cpu_die," in patch


def test_musb_gadget_keeps_an_rx_packet_that_arrived_early():
    # mainline 3fc137386c46 flushes the Rx FIFO when a request is queued, dropping the
    # MTP command libmtp sends right after an answer (umtprd reads one command at a
    # time): patch 0028 hands that packet to musb_g_rx() from a work item instead
    patch = (REPO_ROOT / "kernel/patches/"
             "0028-usb-musb-gadget-keep-an-Rx-packet-that-arrived-before-the-request.patch"
             ).read_text()
    assert "+++ b/drivers/usb/musb/musb_gadget.c" in patch
    assert "+\t\tif (csr & MUSB_RXCSR_RXPKTRDY)\n+\t\t\tschedule_work(&musb->rx_pending_work);" in patch
    # no flush of a FIFO that looked empty: it dropped 1 command in ~700 (first version)
    assert "-\t\tcsr |= MUSB_RXCSR_FLUSHFIFO | MUSB_RXCSR_P_WZC_BITS;" in patch
    assert "+\t\tcsr |= MUSB_RXCSR_FLUSHFIFO" not in patch
    assert "+\tINIT_WORK(&musb->rx_pending_work, musb_g_rx_pending_work);" in patch
    assert "+\tcancel_work_sync(&musb->rx_pending_work);" in patch
    assert "musb_gadget.c" in OWN_DRIVER_FILES


def _off(text: str) -> set[str]:
    return set(re.findall(r"^# (CONFIG_\w+) is not set$", text, re.M))


def test_boot_screen_is_the_same_on_both_consoles():
    # no Tux on fbcon on either console (the arm64 defconfig of the R36S turns it on)
    r36s = (REPO_ROOT / "board/r36s/kernel.config").read_text()
    assert "CONFIG_LOGO" in _off(FRAGMENT) and "CONFIG_LOGO" in _off(r36s)


def test_build_checks_the_options_that_stay_off():
    from r36os.kernel import _KERNEL_SCRIPT
    assert "must stay off" in _KERNEL_SCRIPT


def test_fragment_gives_the_overlay_upper_layer_xattrs():
    # the root overlay's upper layer is a tmpfs: without xattrs the kernel logs
    # "overlayfs: failed to set xattr on upper" on every boot (task 9.11)
    assert _options(FRAGMENT).get("CONFIG_TMPFS_XATTR") == "y"


def test_kernel_image_does_not_carry_the_build_time_or_machine():
    # the same inputs must give the same zImage/Image, or `r36os push` resends it every
    # time (the R36S Image changed between two builds that only touched the GA36)
    from r36os.kernel import _KERNEL_SCRIPT, build_stamp, kernel_inputs
    for v in ('KBUILD_BUILD_TIMESTAMP="{stamp}"', "KBUILD_BUILD_VERSION=1",
              "KBUILD_BUILD_USER=lume", "KBUILD_BUILD_HOST=lume"):
        assert v in _KERNEL_SCRIPT, v
    assert re.fullmatch(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\d UTC", build_stamp("ga36"))
    assert REPO_ROOT / "board/ga36/kernel.config" in kernel_inputs("ga36")


def test_build_stamp_is_the_kernel_release_date_and_ignores_git(monkeypatch):
    import subprocess
    from r36os import kernel
    # same value for both consoles, and no git call at all
    def no_git(*a, **k):
        raise AssertionError("build_stamp must not run git")
    monkeypatch.setattr(subprocess, "run", no_git)
    assert kernel.build_stamp("ga36") == kernel.build_stamp("r36s")
    assert kernel.build_stamp("r36s") == kernel.KERNEL_RELEASE_DATES[kernel.KERNEL_VERSION]
    # `date -d` must accept it
    monkeypatch.undo()
    assert subprocess.run(["date", "-d", kernel.build_stamp("r36s")]).returncode == 0
    # a version without a date fails loudly
    monkeypatch.setattr(kernel, "KERNEL_VERSION", "0.0.0")
    with pytest.raises(RuntimeError, match="no release date"):
        kernel.build_stamp("r36s")


def test_initramfs_files_have_a_fixed_mtime():
    from r36os.initramfs import _PACK
    assert _PACK.index("touch -h -d @0") < _PACK.index("cpio -o")
    # newc carries inode numbers: two identical stages gave different archives without it
    assert "--reproducible" in _PACK


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
    for off in _off(FRAGMENT):
        assert off not in opts, off
    kdir = BUILT.parent
    assert (kdir / "zImage").stat().st_size > 1_000_000
    dtbs = sorted(p.name for p in (kdir / "dtbs").glob("*.dtb"))
    assert dtbs == ["sun8i-a33-ga36-mb-v1.2-panel1.dtb", "sun8i-a33-ga36-mb-v1.2-panel2.dtb"]
    # no warnings in the build (those in our own drivers already fail it)
    assert "warning:" not in (kdir / "build-warnings.log").read_text()
