"""Writing the card (r36os flash): safety rules, without a real card."""

import struct

import pytest

from r36os import flash
from r36os.image import BOOT_SECTORS, boot_start

BOOT_START = boot_start("ga36")  # 128 MiB: after the vendor area


def _mbr(disk_id=0x4C554D32, start=BOOT_START, size=BOOT_SECTORS, p2=False) -> bytes:
    s = bytearray(512)
    struct.pack_into("<I", s, 440, disk_id)
    s[446 + 4] = 0x0C
    struct.pack_into("<II", s, 446 + 8, start, size)
    if p2:
        s[462 + 4] = 0x07
        struct.pack_into("<II", s, 462 + 8, start + size, 1_000_000)
    s[510:512] = b"\x55\xaa"
    return bytes(s)


def test_parse_mbr():
    m = flash.Mbr.parse(_mbr(p2=True))
    assert (m.disk_id, m.p1_start, m.p1_sectors, m.p1_type, m.has_p2) == \
        (0x4C554D32, BOOT_START, BOOT_SECTORS, 0x0C, True)
    with pytest.raises(flash.FlashError):
        flash.Mbr.parse(bytes(512))


def test_update_accepts_card_from_same_target_with_roms():
    flash.check_update(flash.Mbr.parse(_mbr()), flash.Mbr.parse(_mbr(p2=True)))


@pytest.mark.parametrize("card", [
    _mbr(disk_id=0x4C554D33),                 # image of another target (vm)
    _mbr(start=2048),                          # another system (different layout)
    _mbr(size=BOOT_SECTORS // 2),
])
def test_update_refuses_other_layouts(card):
    with pytest.raises(flash.FlashError):
        flash.check_update(flash.Mbr.parse(_mbr()), flash.Mbr.parse(card))


@pytest.mark.parametrize("target", ["ga36", "vm"])
def test_update_never_writes_sector0_nor_roms(target):
    start = boot_start(target)
    regions = flash.update_regions(target)
    assert regions[0] == (8192, start * 512 - 8192)          # boot area (bootloader)
    assert regions[1] == (start * 512, BOOT_SECTORS * 512)   # BOOT
    assert min(off for off, _ in regions) >= 512             # sector 0 untouched
    end = max(off + n for off, n in regions)
    assert end == (start + BOOT_SECTORS) * 512               # nothing past BOOT (ROMS)


def test_ga36_update_rewrites_vendor_area_and_android_boot():
    from r36os import vendor

    (off, length), _ = flash.update_regions("ga36")
    assert off <= 16 * 512                                   # boot0
    assert off + length >= (vendor.ANDROID_BOOT_SECTOR * 512 + vendor.ANDROID_BOOT_MAX)


def test_find_image(tmp_path, monkeypatch):
    from r36os.targets import get_target

    monkeypatch.setenv("R36OS_OUT", str(tmp_path))
    with pytest.raises(flash.FlashError):
        flash.find_image(get_target("ga36"))
    d = tmp_path / "images/ga36/20261109-214233"
    d.mkdir(parents=True)
    (d / "ga36-20261109-214233.img.zst").write_bytes(b"x")
    (tmp_path / "images/ga36/latest").symlink_to("20261109-214233")
    assert flash.find_image(get_target("ga36")).name == "ga36-20261109-214233.img.zst"
