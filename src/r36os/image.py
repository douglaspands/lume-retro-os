"""Stage 4: card image (MBR + FAT32 BOOT), with no root and no loop mount.

vm: 0-16 MiB free for the bootloader; partition 1 `BOOT` (FAT32, 1 GiB) at sector 32768.
console (design D2): the first 128 MiB are the boot area of both consoles (bootarea.py:
GA36 vendor area with the shrunk boot0, the R36S factory chain and our Android boot image
at sector 172032), and `BOOT` (FAT32, 2 GiB, room for future systems and A/B updates)
starts at sector 262144. Partition 2 (`ROMS`) is created by `flash` or on the first boot.
"""

from __future__ import annotations

from pathlib import Path

from r36os import bootarea, version
from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT
from r36os.rootfs import target_out
from r36os.targets import TARGETS, ImageTarget, Target

BOOT_START = 32768  # 512 B sectors = 16 MiB (default)
BOOT_SECTORS = 2 * 1024 * 1024  # 1 GiB (default, the vm)
IMAGE_SECTORS = BOOT_START + BOOT_SECTORS

# Images with a vendor boot area: BOOT starts after it (128 MiB), with the disk signature
# of the GA36 cards (the kernels look for PARTUUID=4c554d32-01)
VENDOR_BOOT_START = {"console": bootarea.AREA_SECTORS}
DISK_ID = {"console": bootarea.DISK_ID}
# The console BOOT holds both systems: 2 GiB leaves room for the planned growth (catalog,
# Wi-Fi, a third system, A/B updates). Decided by the user on 2026-11-11; cards written
# with the older 1 GiB BOOT need a full write (`--update` refuses them).
BOOT_SIZE = {"console": 4 * 1024 * 1024}

KERNEL_NAME = {"vm": "vmlinuz", "r36s": "Image", "ga36": "zImage"}


def boot_start(target: Target | ImageTarget | str) -> int:
    name = target if isinstance(target, str) else target.name
    return VENDOR_BOOT_START.get(name, BOOT_START)


def boot_sectors(target: Target | ImageTarget | str) -> int:
    """Size of the BOOT partition of an image, in 512 B sectors."""
    name = target if isinstance(target, str) else target.name
    return BOOT_SIZE.get(name, BOOT_SECTORS)


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


# Console (design D5): BOOT with one folder per console and, at the root, the boot.ini that
# the R36S U-Boot reads. GA36: SYSTEM, DTBs (reference) and the boot images of both panels
# (the kernel with the built-in initramfs is the Android boot image at 172032). R36S:
# SYSTEM, the Image (initramfs built in) and the DTB loaded by boot.ini.
_CONSOLE = """
W=/out/imgwork
rm -rf $W && mkdir -p $W
truncate -s {boot_bytes} $W/boot.img
mkfs.vfat -F 32 -n BOOT -h {boot_start} -S 512 $W/boot.img >/dev/null
export MTOOLS_SKIP_CHECK=1
M="mcopy -i $W/boot.img"
$M /out/VERSION ::VERSION
$M /board/boot.ini ::boot.ini
# factory files the R36S U-Boot reads from the root: RG351 DTBs and the boot logo (task 4.5)
$M /out/factory-boot/* ::
mmd -i $W/boot.img ::ga36 ::ga36/dtbs ::ga36/android-boot ::r36s
$M /ga36/SYSTEM ::ga36/SYSTEM
$M /ga36/kernel/dtbs/*.dtb ::ga36/dtbs/
$M /ga36/kernel/android-boot-*.img ::ga36/android-boot/
$M /r36s/SYSTEM ::r36s/SYSTEM
$M /r36s/kernel/Image ::r36s/Image
$M /r36s/kernel/dtbs/{r36s_dtb} ::r36s/{r36s_dtb}
# at least {min_free} bytes free on BOOT (updates and the panel switch need room)
free=$(mdir -i $W/boot.img :: | sed -n 's/ *bytes free.*//p' | tr -d ' ')
echo "BOOT: $free bytes free"
if [ "$free" -lt {min_free} ]; then
  echo "error: BOOT has only $free bytes free, the console image needs {min_free}" >&2
  exit 1
fi
# Disk: MBR with the signature of the GA36 cards and only BOOT (active)
truncate -s {image_bytes} $W/disk.img
printf 'label: dos\\nlabel-id: 0x{disk_id}\\nstart={boot_start}, size={boot_sectors}, type=c, bootable\\n' \\
    | sfdisk -q $W/disk.img
# boot area of both consoles without sector 0 (the MBR is ours), then the panel 1 boot image
dd if=/out/{area_file} of=$W/disk.img bs=512 skip=1 seek=1 count={area_sectors} conv=notrunc status=none
dd if=/ga36/kernel/android-boot-panel1.img of=$W/disk.img bs=512 seek={android} conv=notrunc status=none
dd if=$W/boot.img of=$W/disk.img bs=512 seek={boot_start} conv=notrunc,sparse status=none
mv $W/disk.img /out/console.img
rm -rf $W
"""

R36S_DTB = "rk3326-r36s-v5.dtb"
BOOT_MIN_FREE = 64 * 2**20
_CLUSTER = 4096                 # mkfs.vfat -F 32 on 1 to 2 GiB
_FAT_OVERHEAD = 16 * 2**20      # FATs, reserved sectors and directories (upper bound)


class ConsoleImageError(RuntimeError):
    pass


def console_boot_files(ga36_out: Path, r36s_out: Path,
                       factory: dict[str, Path] | None = None) -> dict[str, Path]:
    """BOOT path -> source of every file of the console BOOT except VERSION.

    `factory`: files of the R36S factory BOOT root (r36s_vendor.factory_boot_files()).
    """
    files = {**(factory or {}),
             "boot.ini": REPO_ROOT / "board/r36s/boot.ini",
             "ga36/SYSTEM": ga36_out / "SYSTEM",
             "r36s/SYSTEM": r36s_out / "SYSTEM",
             "r36s/Image": r36s_out / "kernel/Image",
             f"r36s/{R36S_DTB}": r36s_out / "kernel/dtbs" / R36S_DTB}
    for dtb in sorted((ga36_out / "kernel/dtbs").glob("*.dtb")):
        files[f"ga36/dtbs/{dtb.name}"] = dtb
    for img in sorted((ga36_out / "kernel").glob("android-boot-*.img")):
        files[f"ga36/android-boot/{img.name}"] = img
    return files


def check_console_boot(sizes: dict[str, int]) -> None:
    """Limits of the console BOOT (system-image): every SYSTEM within 448 MiB and at least
    64 MiB free on the 2 GiB BOOT. `sizes` maps the BOOT path to the file size."""
    from r36os.rootfs import CONSOLE_SYSTEM_LIMIT_MIB

    for path, size in sizes.items():
        if path.endswith("/SYSTEM") and size > CONSOLE_SYSTEM_LIMIT_MIB * 2**20:
            raise ConsoleImageError(
                f"{path} has {size / 2**20:.1f} MiB, above the {CONSOLE_SYSTEM_LIMIT_MIB} MiB "
                "limit of each system on the console image")
    used = sum(-(-size // _CLUSTER) * _CLUSTER for size in sizes.values())
    free = boot_sectors("console") * 512 - _FAT_OVERHEAD - used
    if free < BOOT_MIN_FREE:
        raise ConsoleImageError(
            f"the console BOOT would have {free / 2**20:.0f} MiB free, it needs at least "
            f"{BOOT_MIN_FREE // 2**20} MiB (files: {used / 2**20:.0f} MiB)")


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
    """The console image (out/console/console.img) from the ga36 and r36s layers (D2, D5).

    The 128 MiB before BOOT are the boot area of both consoles (bootarea.py), with the
    Android boot image of GA36 panel 1 at sector 172032; BOOT starts at sector 262144.
    """
    import shutil

    from r36os import bootarea, r36s_vendor, vendor
    from r36os.paths import ensure_dir
    from r36os.targets import IMAGES

    out = ensure_dir(target_out(IMAGES["console"]))
    ga36_out, r36s_out = target_out(TARGETS["ga36"]), target_out(TARGETS["r36s"])
    factory = r36s_vendor.factory_boot_files()
    staging = out / "factory-boot"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    for name, src in factory.items():
        shutil.copy(src, staging / name)
    files = console_boot_files(ga36_out, r36s_out, factory)
    missing = [str(src) for src in files.values() if not src.exists()]
    if missing:
        raise ConsoleImageError("missing layer outputs: " + ", ".join(missing))
    check_console_boot({path: src.stat().st_size for path, src in files.items()})
    (out / "VERSION").write_text(
        version.boot_version_file("console", v) + f"language: {language}\n")
    area = bootarea.write_console_area(out / "console-boot-area.bin")
    script = _CONSOLE.format(
        boot_bytes=boot_sectors("console") * 512,
        boot_start=boot_start("console"),
        boot_sectors=boot_sectors("console"),
        image_bytes=(boot_start("console") + boot_sectors("console")) * 512,
        disk_id=disk_id("console"),
        r36s_dtb=R36S_DTB,
        min_free=BOOT_MIN_FREE,
        area_file=area.name,
        area_sectors=bootarea.AREA_SECTORS - 1,
        android=vendor.ANDROID_BOOT_SECTOR,
    )
    # the boot area is written next to the image (out/console), so /out carries it too
    volumes = {out: "/out", ga36_out: "/ga36", r36s_out: "/r36s",
               REPO_ROOT / "board/r36s": "/board"}
    # the image does not depend on the target arch: always the x86_64 builder
    Container(image=ensure_builder(TARGETS["vm"]), volumes=volumes).sh(script)
    area.unlink()
    return out / "console.img"
