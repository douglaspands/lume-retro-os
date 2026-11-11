"""Stage 4: card image (MBR + FAT32 BOOT), with no root and no loop mount.

vm: 0-16 MiB free for the bootloader; partition 1 `BOOT` (FAT32, 1 GiB) at sector 32768.
console (design D2): the first 128 MiB are the boot area of both consoles (bootarea.py:
GA36 vendor area with the shrunk boot0, the R36S factory chain and our Android boot image
at sector 172032), and `BOOT` starts at sector 262144. Partition 2 (`ROMS`) is created by
`flash` or on the first boot.
"""

from __future__ import annotations

from pathlib import Path

from r36os import bootarea, version
from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT
from r36os.rootfs import target_out
from r36os.targets import TARGETS, ImageTarget, Target

BOOT_START = 32768  # 512 B sectors = 16 MiB (default)
BOOT_SECTORS = 2 * 1024 * 1024  # 1 GiB
IMAGE_SECTORS = BOOT_START + BOOT_SECTORS

# Images with a vendor boot area: BOOT starts after it (128 MiB). The console keeps the
# start and the disk signature of the GA36 cards written before, so `--update` works on them
VENDOR_BOOT_START = {"console": bootarea.AREA_SECTORS}
DISK_ID = {"console": bootarea.DISK_ID}

KERNEL_NAME = {"vm": "vmlinuz", "r36s": "Image", "ga36": "zImage"}


def boot_start(target: Target | ImageTarget | str) -> int:
    name = target if isinstance(target, str) else target.name
    return VENDOR_BOOT_START.get(name, BOOT_START)


def disk_id(target: Target | ImageTarget | str) -> str:
    name = target if isinstance(target, str) else target.name
    if name in DISK_ID:
        return DISK_ID[name]
    return (REPO_ROOT / "board" / name / "disk-id").read_text().strip()


_IMAGE = """
W=/out/imgwork
rm -rf $W && mkdir -p $W
# FAT32 BOOT with "hidden sectors" = partition offset (needed to boot).
truncate -s {boot_bytes} $W/boot.img
mkfs.vfat -F 32 -n BOOT -h {boot_start} -S 512 $W/boot.img >/dev/null
export MTOOLS_SKIP_CHECK=1
# No logs/: the logs live in ROMS/logs/ (D14); BOOT only gets logs/ without ROMS
{fat_files}
if [ -f /out/VERSION ]; then mcopy -i $W/boot.img /out/VERSION ::VERSION; fi
mcopy -i $W/boot.img /out/SYSTEM ::SYSTEM
{bootloader_fat}
# Disk: MBR table with a fixed signature and only BOOT (active).
truncate -s {image_bytes} $W/disk.img
printf 'label: dos\\nlabel-id: 0x{disk_id}\\nstart={boot_start}, size={boot_sectors}, type=c, bootable\\n' \\
    | sfdisk -q $W/disk.img
dd if=$W/boot.img of=$W/disk.img bs=512 seek={boot_start} conv=notrunc,sparse status=none
{bootloader_raw}
mv $W/disk.img /out/{name}.img
rm -rf $W
"""

# VM: SYSLINUX in BOOT (reads /extlinux/extlinux.conf) and mbr.bin in sector 0.
_VM_FILES = """mmd -i $W/boot.img ::extlinux
mcopy -i $W/boot.img /board/extlinux.conf ::extlinux/extlinux.conf
mcopy -i $W/boot.img /out/kernel/vmlinuz-virt ::vmlinuz
mcopy -i $W/boot.img /out/initramfs ::initramfs"""
_VM_FAT = "syslinux --install --directory /extlinux $W/boot.img"
_VM_RAW = ("dd if=/usr/share/syslinux/mbr.bin of=$W/disk.img bs=440 count=1 "
           "conv=notrunc status=none")

# GA36: BOOT only holds what Linux uses (SYSTEM) and references (DTBs, the boot images of
# both panels). The kernel with the built-in initramfs is the Android boot image at 172032.
_GA36_FILES = """mmd -i $W/boot.img ::dtbs ::android-boot
mcopy -i $W/boot.img /out/kernel/dtbs/*.dtb ::dtbs/
mcopy -i $W/boot.img /out/kernel/android-boot-*.img ::android-boot/"""
# Vendor area without sector 0 (the MBR is ours) and the panel 1 boot image
_GA36_RAW = """dd if=/vendor/ga36-factory-128M.bin of=$W/disk.img bs=512 skip=1 seek=1 count={area} \\
    conv=notrunc status=none
dd if=/out/kernel/android-boot-panel1.img of=$W/disk.img bs=512 seek={android} conv=notrunc status=none"""


def build_image(target: Target, v: version.BuildVersion | None = None,
                language: str = "en") -> Path:
    """The vm image (out/vm/vm.img)."""
    out = target_out(target)
    # BOOT/VERSION: the build on the card, readable on a PC (D15)
    (out / "VERSION").unlink(missing_ok=True)
    if v is not None:
        (out / "VERSION").write_text(
            version.boot_version_file(target.name, v) + f"language: {language}\n")
    volumes = {out: "/out", REPO_ROOT / "board" / target.name: "/board"}
    start = boot_start(target)
    if target.name != "vm":
        raise ValueError(f"{target.name} is a hardware layer: its image is the console one")
    fat_files, bootloader_fat, bootloader_raw = _VM_FILES, _VM_FAT, _VM_RAW
    script = _IMAGE.format(
        boot_bytes=BOOT_SECTORS * 512,
        boot_start=start,
        boot_sectors=BOOT_SECTORS,
        image_bytes=(start + BOOT_SECTORS) * 512,
        disk_id=disk_id(target),
        fat_files=fat_files,
        bootloader_fat=bootloader_fat,
        bootloader_raw=bootloader_raw,
        name=target.name,
    )
    # Building the image does not depend on the target arch: always the x86_64 builder.
    Container(image=ensure_builder(TARGETS["vm"]), volumes=volumes).sh(script)
    return out / f"{target.name}.img"


def build_console_image(v: version.BuildVersion, language: str = "en") -> Path:
    """The console image (out/console/console.img) from the ga36 and r36s layers.

    BOOT with one folder per console and the combined boot area: tasks 5.2 and 5.3.
    """
    raise NotImplementedError("the console image is assembled in tasks 5.2 and 5.3")
