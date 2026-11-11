"""Imagem ga36 (D5): MBR nossa, área do fabricante, imagem de boot Android e a BOOT.

Requer out/ga36/ga36.img (uv run r36os build ga36).
"""

import shutil
import subprocess

import pytest

from r36os import bootimg, vendor
from r36os.container import Container, ensure_builder
from r36os.image import boot_start
from r36os.rootfs import target_out
from r36os.targets import get_target

GA36 = get_target("ga36")
OUT = target_out(GA36)
IMG = OUT / "ga36.img"
START = boot_start(GA36)
pytestmark = [
    pytest.mark.skipif(shutil.which("podman") is None, reason="sem podman"),
    pytest.mark.skipif(not IMG.exists(), reason="sem out/ga36/ga36.img"),
]


def _sh(script: str) -> str:
    cmd = Container(image=ensure_builder(get_target("vm")), volumes={OUT: "/out"}).argv(script)
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def _read(offset: int, length: int) -> bytes:
    with IMG.open("rb") as f:
        f.seek(offset)
        return f.read(length)


def test_mbr_and_boot_partition_after_vendor_area():
    mbr = _read(0, 512)
    assert mbr[510:512] == b"\x55\xaa"
    assert mbr[440:444] == bytes.fromhex("4c554d32")[::-1]  # assinatura do disco
    dump = _sh("sfdisk -d /out/ga36.img")
    parts = [line for line in dump.splitlines() if " : start=" in line]
    assert len(parts) == 1 and f"start={START}" in parts[0].replace(" ", "")
    assert START == vendor.AREA_SECTORS


def test_vendor_area_is_factory_except_android_boot():
    area = vendor.vendor_area().read_bytes()
    img = _read(0, vendor.AREA_SECTORS * 512)
    boot_off = vendor.ANDROID_BOOT_SECTOR * 512
    assert img[8196:8204] == b"eGON.BT0"
    # tudo do setor 1 até a partição "boot" é do fabricante, sem alteração
    assert img[512:boot_off] == area[512:boot_off]


def test_android_boot_is_panel1_kernel_with_dtb():
    expected = (OUT / "kernel/android-boot-panel1.img").read_bytes()
    assert len(expected) <= vendor.ANDROID_BOOT_MAX
    got = _read(vendor.ANDROID_BOOT_SECTOR * 512, len(expected))
    assert got == expected
    h = bootimg.parse(got)
    dtb = (OUT / "kernel/dtbs/sun8i-a33-ga36-mb-v1.2-panel1.dtb").read_bytes()
    zimage = (OUT / "kernel/zImage").read_bytes()
    assert h["kernel"] == zimage + dtb  # DTB anexado (CONFIG_ARM_APPENDED_DTB)


def test_boot_contents():
    off = START * 512
    listing = _sh(f"MTOOLS_SKIP_CHECK=1 mdir -i /out/ga36.img@@{off} -b -/ ::/")
    for name in ("SYSTEM", "VERSION", "dtbs/sun8i-a33-ga36-mb-v1.2-panel1.dtb",
                 "android-boot/android-boot-panel1.img", "android-boot/android-boot-panel2.img"):
        assert f"::/{name}" in listing, listing
    assert "::/logs" not in listing
