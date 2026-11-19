"""GA36 boot through the vendor chain (D5): Android boot image, cmdline, boot area and
the gamepad autoconfig."""

import hashlib
import re
import struct

import pytest

from lume_tool import bootarea, bootimg, build, kpatch, vendor
from lume_tool.image import BOOT_SECTORS, boot_start
from lume_tool.paths import REPO_ROOT

BOARD = REPO_ROOT / "board/ga36"
FRAGMENT = (BOARD / "kernel.config").read_text()
AUTOCONFIG = REPO_ROOT / "aports/lume-retroarch-cfg/files/usr/share/libretro/autoconfig/udev/GA36-MB Gamepad.cfg"


def test_ga36_factory_logo_is_the_boot_logo():
    """boot-dtb-select 2.2 / D9: one boot logo on both consoles. The factory U-Boot of the
    GA36 draws bootlogo.bmp from its internal FAT (sector 73728) and cannot draw a BMP of
    BOOT (proof 1.4: sunxi_bmp_display fails from bootcmd), so the logo stays the factory
    one; it is the same file as BOOT/logo.bmp of the R36S, checked here."""
    from lume_tool import r36s_vendor
    from lume_tool.paths import cache_dir

    area = cache_dir() / "vendor" / "ga36-factory-128M.bin"
    if not area.exists():
        pytest.skip("GA36 factory area not in the cache")
    fat = area.read_bytes()[73728 * 512:139264 * 512]
    start = fat.find(b"BM" + struct.pack("<I", 921654))
    assert start >= 0, "no 640x480 24-bit BMP in the bootloader FAT"
    logo = fat[start:start + 921654]
    assert hashlib.sha256(logo).hexdigest() == dict(r36s_vendor.BOOT_FILES)["logo.bmp"]


def test_android_boot_image_matches_mkbootimg_layout():
    kernel = b"Z" * 5000
    img = bootimg.make(kernel)
    h = bootimg.parse(img)
    # mkbootimg --base 0x40000000 --board sun8i --pagesize 2048 (goodluckOS)
    assert h["magic"] == b"ANDROID!" and h["page_size"] == 2048 and h["board"] == "sun8i"
    assert h["kernel_addr"] == 0x40008000 and h["ramdisk_addr"] == 0x41000000
    assert h["tags_addr"] == 0x40000100 and h["ramdisk_size"] == 0
    assert h["kernel"] == kernel and len(img) % 2048 == 0
    # id = SHA1 of (kernel, size, ramdisk, size, second, size)
    sha = hashlib.sha1(kernel + struct.pack("<I", 5000) + struct.pack("<I", 0) * 2).digest()
    assert img[576:576 + 20] == sha


def test_kernel_cmdline_and_boot_options():
    tty, baud = (BOARD / "serial").read_text().split()
    disk = bootarea.DISK_ID  # the console image signature
    cmdline = re.search(r'^CONFIG_CMDLINE="(.*)"$', FRAGMENT, re.M).group(1)
    assert f"root=PARTUUID={disk}-01" in cmdline and "rootwait" in cmdline
    # debug serial and the panel; tty1 last becomes /dev/console
    assert cmdline.index(f"console={tty},{baud}") < cmdline.index("console=tty1")
    assert "quiet" not in cmdline
    # the initramfs log (lume-bootsel) is not rate limited
    assert "printk.devkmsg=on" in cmdline.split()
    for opt in ("CONFIG_CMDLINE_FORCE=y", "CONFIG_ARM_APPENDED_DTB=y",
                "CONFIG_ARM_ATAG_DTB_COMPAT=y", "CONFIG_BLK_DEV_INITRD=y",
                'CONFIG_INITRAMFS_SOURCE="/initramfs/initramfs.cpio"',
                # seen on the first boot: without them no js device and no sound card
                "CONFIG_INPUT_JOYDEV=y", "CONFIG_SND_SOC_SIMPLE_AMPLIFIER=y"):
        assert re.search(rf"^{re.escape(opt)}$", FRAGMENT, re.M), opt


def test_layout_keeps_vendor_area():
    # BOOT after the 128 MiB vendor area; the boot image fits in the "boot" partition
    assert boot_start("console") == vendor.AREA_SECTORS == 262144
    assert vendor.ANDROID_BOOT_SECTOR + vendor.ANDROID_BOOT_MAX // 512 <= vendor.AREA_SECTORS
    assert boot_start("vm") == 32768 and BOOT_SECTORS == 2 * 1024 * 1024
    assert set(build.ANDROID_BOOT["ga36"]) == {"panel1", "panel2"}


def test_vendor_area_digest_skips_sector0():
    area = bytearray(vendor.AREA_SECTORS * 512)
    area[16 * 512 + 4:16 * 512 + 12] = b"eGON.BT0"
    d1 = vendor.area_digest(bytes(area))
    area[0:512] = b"\x01" * 512  # a different MBR (ours) does not change the digest
    assert vendor.area_digest(bytes(area)) == d1
    area[8192] = 0xFF            # but boot0 does
    assert vendor.area_digest(bytes(area)) != d1


def test_vendor_area_requires_factory_image(tmp_path, monkeypatch):
    monkeypatch.setenv("LUME_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv(vendor.ENV_VAR, raising=False)
    with pytest.raises(vendor.VendorAreaError, match=vendor.ENV_VAR):
        vendor.vendor_area()
    wrong = tmp_path / "other.img"
    wrong.write_bytes(bytes(vendor.AREA_SECTORS * 512))
    monkeypatch.setenv(vendor.ENV_VAR, str(wrong))
    with pytest.raises(vendor.VendorAreaError, match="does not match"):
        vendor.vendor_area()


# RetroArch udev numbering: keys in code order from BTN_MISC (udev_joypad.c)
_KEY_CODES = {"BTN_A": 0x130, "BTN_B": 0x131, "BTN_X": 0x133, "BTN_Y": 0x134,
              "BTN_TL": 0x136, "BTN_TR": 0x137, "BTN_TL2": 0x138, "BTN_TR2": 0x139,
              "BTN_SELECT": 0x13A, "BTN_START": 0x13B, "BTN_MODE": 0x13C,
              "BTN_THUMBL": 0x13D, "BTN_THUMBR": 0x13E, "BTN_DPAD_UP": 0x220,
              "BTN_DPAD_DOWN": 0x221, "BTN_DPAD_LEFT": 0x222, "BTN_DPAD_RIGHT": 0x223}
_RETROPAD = {"a": "BTN_A", "b": "BTN_B", "x": "BTN_X", "y": "BTN_Y", "l": "BTN_TL",
             "r": "BTN_TR", "l2": "BTN_TL2", "r2": "BTN_TR2", "select": "BTN_SELECT",
             "start": "BTN_START", "l3": "BTN_THUMBL", "r3": "BTN_THUMBR",
             "up": "BTN_DPAD_UP", "down": "BTN_DPAD_DOWN", "left": "BTN_DPAD_LEFT",
             "right": "BTN_DPAD_RIGHT"}   # BTN_MODE is the Fn, kept by lume-input (lume-hud-actions D9)


def test_gamepad_autoconfig_matches_driver():
    driver = kpatch.new_file(kpatch.find("0006-"), "drivers/input/joystick/ga36mb-gamepad.c")
    name = re.search(r'idev->name = "([^"]+)"', driver).group(1)
    codes = re.findall(r'\{ "[a-z-]+", (BTN_\w+) \}', driver)
    order = sorted(codes, key=_KEY_CODES.__getitem__)  # every button is declared in the DTS
    cfg = dict(re.findall(r'^(\w+) = "([^"]*)"$', AUTOCONFIG.read_text(), re.M))
    assert AUTOCONFIG.name == f"{name}.cfg" and cfg["input_device"] == name
    for retropad, code in _RETROPAD.items():
        assert cfg[f"input_{retropad}_btn"] == str(order.index(code)), retropad
    # ABS_X, ABS_Y, ABS_RX, ABS_RY -> axes 0..3
    assert cfg["input_l_x_plus_axis"] == "+0" and cfg["input_r_y_minus_axis"] == "-3"
