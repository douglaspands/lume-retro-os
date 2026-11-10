"""Tarefa 4.4: layout da imagem vm (MBR, BOOT FAT32 em 16 MiB) e conteúdo da BOOT.

Requer out/vm/vm.img (uv run r36os build vm).
"""

import shutil
import subprocess

import pytest

from r36os.container import Container, ensure_builder
from r36os.rootfs import target_out
from r36os.targets import get_target

VM = get_target("vm")
IMG = target_out(VM) / "vm.img"
pytestmark = [
    pytest.mark.skipif(shutil.which("podman") is None, reason="sem podman"),
    pytest.mark.skipif(not IMG.exists(), reason="sem out/vm/vm.img"),
]


def _sh(script: str) -> str:
    cmd = Container(image=ensure_builder(VM), volumes={IMG.parent: "/out"}).argv(script)
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout


def test_partition_table():
    dump = _sh("sfdisk -d /out/vm.img")
    assert "label: dos" in dump
    assert "label-id: 0x4c554d33" in dump
    parts = [l for l in dump.splitlines() if " : start=" in l]
    assert len(parts) == 1
    fields = parts[0].replace(" ", "").split(":", 1)[1]
    assert "start=32768" in fields
    assert "size=2097152" in fields
    assert "type=c" in fields
    assert "bootable" in fields


def test_boot_contents():
    off = 32768 * 512
    listing = _sh(f"MTOOLS_SKIP_CHECK=1 mdir -i /out/vm.img@@{off} -b ::/")
    for name in ("vmlinuz", "initramfs", "extlinux", "SYSTEM"):
        assert f"::/{name}" in listing, listing
    # logs centralizados em ROMS/logs/ (D14): a BOOT não tem logs/
    assert "::/logs" not in listing, listing
    ext = _sh(f"MTOOLS_SKIP_CHECK=1 mtype -i /out/vm.img@@{off} ::/extlinux/extlinux.conf")
    assert "root=PARTUUID=4c554d33-01" in ext
    assert "video=640x480" in ext
    assert "quiet" not in ext.split("APPEND", 1)[1]
    label = _sh(f"MTOOLS_SKIP_CHECK=1 mlabel -i /out/vm.img@@{off} -s ::")
    assert "BOOT" in label


def test_mbr_has_syslinux():
    with IMG.open("rb") as f:
        head = f.read(512)
    assert head[510:512] == b"\x55\xaa"
    assert head[:440].strip(b"\x00"), "MBR sem código de boot"
