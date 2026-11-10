"""Stage 4: card image (MBR + FAT32 BOOT), with no root and no loop mount.

Default layout (vm, r36s): 0-16 MiB free for the bootloader; partition 1 `BOOT` (FAT32,
1 GiB) at sector 32768. GA36 (D5): the first 128 MiB are the vendor boot area (boot0,
U-Boot, softw411 table, env) with our Android boot image at sector 172032, and `BOOT`
starts at sector 262144. Partition 2 (`ROMS`) is created on the first boot.
"""

from __future__ import annotations

from pathlib import Path

from r36os import version
from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT
from r36os.rootfs import target_out
from r36os.targets import TARGETS, Target

BOOT_START = 32768  # 512 B sectors = 16 MiB (default)
BOOT_SECTORS = 2 * 1024 * 1024  # 1 GiB
IMAGE_SECTORS = BOOT_START + BOOT_SECTORS

# Targets with a vendor bootloader: BOOT starts after its area (128 MiB)
VENDOR_BOOT_START = {"ga36": 262144}

KERNEL_NAME = {"vm": "vmlinuz", "r36s": "Image", "ga36": "zImage"}


def boot_start(target: Target | str) -> int:
    name = target if isinstance(target, str) else target.name
    return VENDOR_BOOT_START.get(name, BOOT_START)


def disk_id(target: Target) -> str:
    return (REPO_ROOT / "board" / target.name / "disk-id").read_text().strip()


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


def build_image(target: Target, bootloader_fat: str = "", bootloader_raw: str = "",
                v: version.BuildVersion | None = None, language: str = "en") -> Path:
    out = target_out(target)
    # BOOT/VERSION: the build on the card, readable on a PC (D15)
    (out / "VERSION").unlink(missing_ok=True)
    if v is not None:
        (out / "VERSION").write_text(
            version.boot_version_file(target.name, v) + f"language: {language}\n")
    volumes = {out: "/out", REPO_ROOT / "board" / target.name: "/board"}
    start = boot_start(target)
    if target.name == "vm":
        fat_files, bootloader_fat, bootloader_raw = _VM_FILES, _VM_FAT, _VM_RAW
    elif target.name == "ga36":
        from r36os import vendor

        area = vendor.vendor_area()
        volumes[area.parent] = "/vendor"
        fat_files = _GA36_FILES
        bootloader_raw = _GA36_RAW.format(area=vendor.AREA_SECTORS - 1,
                                          android=vendor.ANDROID_BOOT_SECTOR)
    else:
        raise NotImplementedError(f"the {target.name} image is not defined yet")
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
