"""Writing the card (r36os flash): safety rules, without a real card."""

import struct

import pytest

from r36os import bootarea, flash
from r36os.image import boot_sectors, boot_start, disk_id
from r36os.targets import IMAGES

BOOT_START = boot_start("console")  # 128 MiB: after the boot area of both consoles
BOOT_SECTORS = boot_sectors("console")  # 2 GiB


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


def test_console_layout():
    # same signature and BOOT start as the older ga36 image, but a 2 GiB BOOT
    assert disk_id("console") == bootarea.DISK_ID == "4c554d32"
    assert BOOT_START == 262144
    assert BOOT_SECTORS == 4 * 1024 * 1024
    assert disk_id("vm") == "4c554d33"
    assert boot_sectors("vm") == 2 * 1024 * 1024


def test_update_refuses_card_written_with_the_old_1gib_boot():
    old_ga36_card = _mbr(disk_id=0x4C554D32, start=262144, size=2 * 1024 * 1024, p2=True)
    console_image = _mbr(disk_id=int(disk_id("console"), 16), start=BOOT_START)
    with pytest.raises(flash.FlashError, match="needs a full write"):
        flash.check_update(flash.Mbr.parse(console_image), flash.Mbr.parse(old_ga36_card))


def test_update_accepts_card_written_with_the_console_image():
    card = _mbr(p2=True)
    flash.check_update(flash.Mbr.parse(_mbr()), flash.Mbr.parse(card))


@pytest.mark.parametrize("card", [
    _mbr(disk_id=0x4C554D33, start=32768),     # card written with the vm image
    _mbr(disk_id=0x4C554D33),                  # another signature
    _mbr(start=2048),                          # another system (different layout)
    _mbr(size=BOOT_SECTORS // 2),
])
def test_update_refuses_other_layouts_asking_for_a_full_write(card):
    with pytest.raises(flash.FlashError, match="needs a full write"):
        flash.check_update(flash.Mbr.parse(_mbr()), flash.Mbr.parse(card))


@pytest.mark.parametrize("target", ["console", "vm"])
def test_update_never_writes_sector0_nor_roms(target):
    start, size = boot_start(target), boot_sectors(target)
    regions = flash.update_regions(target)
    assert regions[0] == (8192, start * 512 - 8192)          # boot area (bootloader)
    assert regions[1] == (start * 512, size * 512)           # BOOT
    assert min(off for off, _ in regions) >= 512             # sector 0 untouched
    end = max(off + n for off, n in regions)
    assert end == (start + size) * 512                       # nothing past BOOT (ROMS)


def test_console_update_rewrites_both_chains_and_android_boot():
    from r36os import r36s_vendor, vendor

    (off, length), _ = flash.update_regions("console")
    assert off <= 16 * 512                                   # shrunk boot0
    assert all(off <= r.start * 512 and r.end * 512 <= off + length
               for r in r36s_vendor.REGIONS)                 # R36S chain
    assert off + length >= (vendor.ANDROID_BOOT_SECTOR * 512 + vendor.ANDROID_BOOT_MAX)


def test_find_image(tmp_path, monkeypatch):
    from r36os.targets import get_image

    monkeypatch.setenv("R36OS_OUT", str(tmp_path))
    with pytest.raises(flash.FlashError, match="r36os build console"):
        flash.find_image(get_image("console"))
    d = tmp_path / "images/console/20261109-214233"
    d.mkdir(parents=True)
    (d / "console-20261109-214233.img.zst").write_bytes(b"x")
    (tmp_path / "images/console/latest").symlink_to("20261109-214233")
    assert flash.find_image(get_image("console")).name == "console-20261109-214233.img.zst"


def test_cli_parser_eject_flag():
    from r36os.cli import _parser

    p = _parser()
    args = p.parse_args(["flash", "console", "/dev/sdc", "--eject", "--update"])
    assert args.eject is True
    assert args.update is True

    args_no_eject = p.parse_args(["flash", "console", "/dev/sdc"])
    assert args_no_eject.eject is False


def test_cli_parser_full_flag_is_the_default_and_excludes_update():
    from r36os.cli import _parser

    p = _parser()
    assert p.parse_args(["flash", "console", "/dev/sdc", "--full"]).update is False
    assert p.parse_args(["flash", "console", "/dev/sdc"]).update is False
    with pytest.raises(SystemExit):
        p.parse_args(["flash", "console", "/dev/sdc", "--full", "--update"])


def test_eject_calls_udisksctl_power_off(monkeypatch):
    commands = []

    def mock_run(cmd, *args, **kwargs):
        commands.append(cmd)
        class Ret:
            returncode = 0
        return Ret()

    monkeypatch.setattr("subprocess.run", mock_run)
    flash._eject("/dev/sdc")
    assert any("udisksctl" in c and "power-off" in c and "/dev/sdc" in c for c in commands)
    # eject never asks for a password: any sudo in it is non-interactive (-n)
    assert all("-n" in c for c in commands if c and c[0] == "sudo")


def test_roms_takes_the_rest_of_the_card_from_the_first_mib_after_boot():
    image = flash.Mbr.parse(_mbr())
    card = 30_597_120                                         # 14.6 GB card, in sectors
    start, sectors = flash.roms_layout(card, image)
    assert start == BOOT_START + BOOT_SECTORS                 # BOOT already ends on 1 MiB
    assert start % 2048 == 0 and start + sectors == card
    odd = flash.Mbr.parse(_mbr(size=BOOT_SECTORS - 1))
    assert flash.roms_layout(card, odd)[0] == BOOT_START + BOOT_SECTORS


def test_roms_layout_matches_the_initramfs_rule():
    # the console's first boot creates ROMS with the same start (free_start, storage.sh)
    storage = (flash.REPO_ROOT / "initramfs/lib/storage.sh").read_text()
    assert f"ALIGN={flash.ALIGN} " in storage and f"MIN_ROMS={flash.MIN_ROMS} " in storage
    assert "echo $(( (s + z + ALIGN - 1) / ALIGN * ALIGN ))" in storage


def test_roms_refuses_a_card_without_room():
    image = flash.Mbr.parse(_mbr())
    with pytest.raises(flash.FlashError):
        flash.roms_layout(BOOT_START + BOOT_SECTORS + 1000, image)


def test_build_language_from_build_json(tmp_path):
    zst = tmp_path / "ga36-1.img.zst"
    assert flash.build_language(zst) == "en"                  # no build.json: default
    (tmp_path / "build.json").write_text('{"language": "pt_BR"}')
    assert flash.build_language(zst) == "pt_BR"


def test_populate_roms_has_the_default_folders_and_factory_config(tmp_path):
    import json

    from r36os import lang

    flash.populate_roms(tmp_path, "pt_BR")
    ids = [s["id"] for s in json.loads(flash.CATALOG.read_text())["systems"]]
    for sid in ids:
        assert (tmp_path / "roms" / sid).is_dir(), sid
    for sid in ("neogeo", "cps1", "cps2", "segacd", "sega32x"):    # catalog-arcade-sega
        assert sid in ids and (tmp_path / "roms" / sid).is_dir(), sid
    for name in ("bios", "saves", "states", "screenshots", "system"):
        assert (tmp_path / name).is_dir(), name
    cfg = (tmp_path / "system/retroarch/retroarch.cfg").read_text()
    factory = (flash.FACTORY / "retroarch/retroarch.cfg").read_text()
    assert f'user_language = "{lang.retro_language("pt_BR")}"' in cfg
    # the rest is the factory file as is (what lume-persist would seed)
    strip = lambda t: [l for l in t.splitlines() if not l.startswith("user_language")]  # noqa: E731
    assert strip(cfg) == strip(factory)
    flash.populate_roms(tmp_path, "en")                         # idempotent
    assert 'user_language = "0"' in (tmp_path / "system/retroarch/retroarch.cfg").read_text()


def test_mount_roms_takes_the_desktop_automount_that_won_the_race(monkeypatch):
    # what happened on 2026-11-11: the desktop automounted the fresh ROMS, our udisksctl
    # mount failed with "already mounted" and the folders were never created
    calls = {"mp": 0}

    def fake_mountpoint(node):
        calls["mp"] += 1
        return "/run/media/u/ROMS" if calls["mp"] > 3 else None

    class Ret:
        returncode = 1
        stdout = ""
        stderr = "Error mounting /dev/sdc2: already mounted"

    monkeypatch.setattr(flash, "_mountpoint", fake_mountpoint)
    monkeypatch.setattr(flash.subprocess, "run", lambda *a, **k: Ret())
    monkeypatch.setattr(flash.time, "sleep", lambda s: None)
    assert flash._mount_roms("/dev/sdc2", wait=0) == "/run/media/u/ROMS"


def test_mount_roms_fails_clearly_when_nothing_mounts(monkeypatch):
    class Ret:
        returncode = 1
        stdout = ""
        stderr = "Error mounting /dev/sdc2: bad superblock"

    monkeypatch.setattr(flash, "_mountpoint", lambda node: None)
    monkeypatch.setattr(flash.subprocess, "run", lambda *a, **k: Ret())
    monkeypatch.setattr(flash.time, "sleep", lambda s: None)
    with pytest.raises(flash.FlashError, match="bad superblock"):
        flash._mount_roms("/dev/sdc2", wait=0)


def test_eject_command(monkeypatch, capsys):
    from r36os.cli import _parser, main

    assert _parser().parse_args(["eject", "/dev/sdc"]).device == "/dev/sdc"
    monkeypatch.setattr(flash, "_check_device", lambda d: f"{d} (card)")
    monkeypatch.setattr(flash, "_eject", lambda d: True)
    assert main(["eject", "/dev/sdc"]) == 0
    assert "powered off" in capsys.readouterr().out
    monkeypatch.setattr(flash, "_eject", lambda d: False)
    assert main(["eject", "/dev/sdc"]) == 1


def test_eject_refuses_what_is_not_a_removable_disk(monkeypatch):
    def refuse(d):
        raise flash.FlashError(f"{d} is not removable")

    monkeypatch.setattr(flash, "_check_device", refuse)
    assert flash.main_eject("/dev/sda") == 1


def _fake_usb_card(sys_root, vendor, product):
    # /sys/block/sdc/device -> .../usb1/1-7/1-7:1.0/host0/target0:0:0/0:0:0:0, as on the PC
    usb = sys_root / "devices/pci0000:00/usb1/1-7"
    scsi = usb / "1-7:1.0/host0/target0:0:0/0:0:0:0"
    scsi.mkdir(parents=True)
    (usb / "idVendor").write_text(vendor + "\n")
    (usb / "idProduct").write_text(product + "\n")
    (sys_root / "block/sdc").mkdir(parents=True)
    (sys_root / "block/sdc/device").symlink_to(scsi)


def test_flash_warns_about_the_reader_that_corrupts_cards(tmp_path):
    _fake_usb_card(tmp_path, "14cd", "125d")
    assert flash.usb_reader_ids("/dev/sdc", tmp_path) == ("14cd", "125d")
    warning = flash.reader_warning("/dev/sdc", tmp_path)
    assert "14cd:125d" in warning and "USBC" in warning and "/dev/sdc2" in warning


def test_flash_does_not_warn_about_other_readers(tmp_path):
    _fake_usb_card(tmp_path, "0bda", "0109")
    assert flash.reader_warning("/dev/sdc", tmp_path) is None


def test_reader_ids_of_a_non_usb_disk(tmp_path):
    (tmp_path / "devices/platform/mmc0").mkdir(parents=True)
    (tmp_path / "block/mmcblk0").mkdir(parents=True)
    (tmp_path / "block/mmcblk0/device").symlink_to(tmp_path / "devices/platform/mmc0")
    assert flash.usb_reader_ids("/dev/mmcblk0", tmp_path) is None


def test_card_is_written_and_read_back_with_direct_io():
    # the write must not fill the page cache (it froze the whole PC through the global
    # dirty limit), and the read-back must come from the card, not from that cache
    w = flash.write_cmd("/dev/sdc", 8192)
    assert "oflag=direct,seek_bytes" in w and "conv=notrunc,fsync" in w
    assert "iflag=fullblock" in w and "status=none" in w     # whole blocks from the pipe
    r = flash.read_cmd("/dev/sdc", 8192, 1 << 20)
    assert "iflag=direct,skip_bytes,count_bytes" in r


@pytest.fixture
def no_sudo(monkeypatch):
    # the real dd on plain files, without sudo (direct I/O works on files too)
    for name in ("write_cmd", "read_cmd"):
        real = getattr(flash, name)
        monkeypatch.setattr(flash, name, lambda *a, _r=real: _r(*a)[1:])


def test_write_and_check_a_region_with_one_progress_total(tmp_path, no_sudo):
    import hashlib
    import io
    import os

    img, card = tmp_path / "console.img", tmp_path / "card"
    data = os.urandom(9 * 2**20 + 3 * 512)          # not a multiple of the 4 MiB block
    img.write_bytes(data)
    card.write_bytes(bytes(len(data)))
    regions = [(512, 8192 - 512), (8192, len(data) - 8192)]
    out = io.StringIO()
    bar = flash.Progress("writing", sum(n for _, n in regions), out=out)
    sums = [flash._sudo_write(img, str(card), off, n, bar) for off, n in regions]
    bar.finish()
    assert card.read_bytes()[512:] == data[512:] and card.read_bytes()[:512] == bytes(512)
    assert sums == [hashlib.sha256(data[o:o + n]).hexdigest() for o, n in regions]
    # one total for every region: never past it
    assert bar.count == bar.total and "100%" in out.getvalue().splitlines()[-1]
    check = flash.Progress("checking", bar.total, out=io.StringIO())
    assert [flash._sudo_read(str(card), o, n, check) for o, n in regions] == sums
    assert check.count == check.total


def test_a_failed_dd_stops_the_flash(tmp_path, monkeypatch):
    img = tmp_path / "console.img"
    img.write_bytes(bytes(8 * 2**20))
    monkeypatch.setattr(flash, "write_cmd", lambda device, offset: ["false"])
    with pytest.raises(flash.FlashError, match="failed"):
        flash._sudo_write(img, "/dev/null", 0, 8 * 2**20)


def test_progress_line():
    import io

    bar = flash.Progress("writing", 2 * 2**30, out=io.StringIO())
    bar.count = 2**30
    line = bar.line(bar.t0 + 100)
    assert line.startswith("writing      1.00 / 2.00 GiB")
    assert " 50%" in line and "10.7 MB/s" in line and "1:40 left" in line
    bar.count = bar.total
    assert "100%" in bar.line(bar.t0 + 200) and "3:20 total" in bar.line(bar.t0 + 200)
    small = flash.Progress("checking", 512 * 2**20, out=io.StringIO())
    assert "/ 512.00 MiB" in small.line(small.t0 + 1)


@pytest.mark.parametrize("target", ["console", "vm"])
def test_regions_are_whole_sectors_for_direct_io(target):
    # O_DIRECT needs offsets and lengths in whole 512-byte sectors
    for offset, length in flash.update_regions(IMAGES[target]):
        assert offset % flash.SECTOR == 0 and length % flash.SECTOR == 0


def test_wipe_disk_and_rereadpt(monkeypatch):
    commands = []

    def mock_run(cmd, *args, **kwargs):
        commands.append(cmd)
        class Ret:
            returncode = 0
        return Ret()

    monkeypatch.setattr("subprocess.run", mock_run)
    flash._wipe_disk("/dev/sdc", 1_000_000)
    assert any("wipefs" in c and "-a" in c and "/dev/sdc" in c for c in commands)
    assert any("dd" in c and "if=/dev/zero" in c and "of=/dev/sdc" in c for c in commands)

    commands.clear()
    flash._rereadpt("/dev/sdc")
    assert any("blockdev" in c and "--rereadpt" in c and "/dev/sdc" in c for c in commands)


