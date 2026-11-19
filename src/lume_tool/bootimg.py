"""Android boot image v0 (the format the GA36 vendor U-Boot loads).

Same as goodluckOS's `mkbootimg --base 0x40000000 --board sun8i --pagesize 2048`: kernel
(zImage with the appended DTB) and an empty ramdisk (the initramfs is built into the kernel).
"""

from __future__ import annotations

import hashlib
import struct

PAGE = 2048
BASE = 0x40000000
KERNEL_OFFSET = 0x00008000
RAMDISK_OFFSET = 0x01000000
SECOND_OFFSET = 0x00F00000
TAGS_OFFSET = 0x00000100


def _pad(data: bytes) -> bytes:
    return data + bytes(-len(data) % PAGE)


def make(kernel: bytes, ramdisk: bytes = b"", board: str = "sun8i", cmdline: str = "") -> bytes:
    """Build the image: 1-page header, then kernel and ramdisk aligned to the page."""
    sha = hashlib.sha1()
    for blob in (kernel, ramdisk, b""):  # kernel, ramdisk, second (like mkbootimg)
        sha.update(blob)
        sha.update(struct.pack("<I", len(blob)))
    header = struct.pack(
        "<8s10I16s512s32s1024s",
        b"ANDROID!",
        len(kernel), BASE + KERNEL_OFFSET,
        len(ramdisk), BASE + RAMDISK_OFFSET,
        0, BASE + SECOND_OFFSET,
        BASE + TAGS_OFFSET,
        PAGE,
        0, 0,                                  # header_version, os_version
        board.encode(),
        cmdline.encode(),
        sha.digest().ljust(32, b"\0"),
        b"",
    )
    return _pad(header) + _pad(kernel) + _pad(ramdisk)


def parse(img: bytes) -> dict:
    """Main fields (for tests)."""
    magic, ksize, kaddr, rsize, raddr, _ss, _sa, taddr, page = struct.unpack_from("<8s8I", img)
    board = img[48:64].rstrip(b"\0").decode()
    return {"magic": magic, "kernel_size": ksize, "kernel_addr": kaddr, "ramdisk_size": rsize,
            "ramdisk_addr": raddr, "tags_addr": taddr, "page_size": page, "board": board,
            "kernel": img[page:page + ksize]}
