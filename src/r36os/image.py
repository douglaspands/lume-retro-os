"""Estágio 4: imagem do cartão (MBR + BOOT FAT32), sem root nem loop mount.

Layout: 0-16 MiB livres para o bootloader; partição 1 `BOOT` (FAT32, 1 GiB) no
setor 32768. A partição 2 (`ROMS`) é criada no primeiro boot.
"""

from __future__ import annotations

from pathlib import Path

from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT
from r36os.rootfs import target_out
from r36os.targets import TARGETS, Target

BOOT_START = 32768  # setores de 512 B = 16 MiB
BOOT_SECTORS = 2 * 1024 * 1024  # 1 GiB
IMAGE_SECTORS = BOOT_START + BOOT_SECTORS

KERNEL_NAME = {"vm": "vmlinuz", "r36s": "Image", "ga36": "zImage"}


def disk_id(target: Target) -> str:
    return (REPO_ROOT / "board" / target.name / "disk-id").read_text().strip()


_IMAGE = """
W=/out/imgwork
rm -rf $W && mkdir -p $W
# BOOT FAT32 com "hidden sectors" = offset da partição (necessário para o boot).
truncate -s {boot_bytes} $W/boot.img
mkfs.vfat -F 32 -n BOOT -h {boot_start} -S 512 $W/boot.img >/dev/null
export MTOOLS_SKIP_CHECK=1
mmd -i $W/boot.img ::extlinux ::logs
mcopy -i $W/boot.img /board/extlinux.conf ::extlinux/extlinux.conf
mcopy -i $W/boot.img /out/{kernel_src} ::{kernel}
mcopy -i $W/boot.img /out/initramfs ::initramfs
mcopy -i $W/boot.img /out/SYSTEM ::SYSTEM
{bootloader_fat}
# Disco: tabela MBR com assinatura fixa e só a BOOT (ativa).
truncate -s {image_bytes} $W/disk.img
printf 'label: dos\\nlabel-id: 0x{disk_id}\\nstart={boot_start}, size={boot_sectors}, type=c, bootable\\n' \\
    | sfdisk -q $W/disk.img
dd if=$W/boot.img of=$W/disk.img bs=512 seek={boot_start} conv=notrunc,sparse status=none
{bootloader_raw}
mv $W/disk.img /out/{name}.img
rm -rf $W
"""

# VM: SYSLINUX na BOOT (lê /extlinux/extlinux.conf) e mbr.bin no setor 0.
_VM_FAT = "syslinux --install --directory /extlinux $W/boot.img"
_VM_RAW = ("dd if=/usr/share/syslinux/mbr.bin of=$W/disk.img bs=440 count=1 "
           "conv=notrunc status=none")


def build_image(target: Target, bootloader_fat: str = "", bootloader_raw: str = "") -> Path:
    out = target_out(target)
    if target.name == "vm":
        bootloader_fat, bootloader_raw = _VM_FAT, _VM_RAW
        kernel_src = "kernel/vmlinuz-virt"
    else:
        kernel_src = f"kernel/{KERNEL_NAME[target.name]}"
    script = _IMAGE.format(
        boot_bytes=BOOT_SECTORS * 512,
        boot_start=BOOT_START,
        boot_sectors=BOOT_SECTORS,
        image_bytes=IMAGE_SECTORS * 512,
        disk_id=disk_id(target),
        kernel_src=kernel_src,
        kernel=KERNEL_NAME[target.name],
        bootloader_fat=bootloader_fat,
        bootloader_raw=bootloader_raw,
        name=target.name,
    )
    # A montagem da imagem não depende do arch alvo: usa sempre o builder x86_64.
    Container(
        image=ensure_builder(TARGETS["vm"]),
        volumes={out: "/out", REPO_ROOT / "board" / target.name: "/board"},
    ).sh(script)
    return out / f"{target.name}.img"
