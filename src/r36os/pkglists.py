"""Package lists (common and per target)."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from r36os.paths import REPO_ROOT
from r36os.targets import Target

COMMON = REPO_ROOT / "rootfs/packages.txt"

# Patterns of the hardware layer: they can never be in the common list.
HARDWARE_PATTERNS = (
    "linux-*",  # kernels and firmware (linux-virt, linux-lts, linux-firmware-*)
    "*-firmware*",
    "u-boot*",
    "syslinux",
    "grub*",
    "raspberrypi*",
    "r36os-padmerge",
)


def read_list(path: Path) -> list[str]:
    names = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    return names


def common_packages() -> list[str]:
    return read_list(COMMON)


def hw_packages(target: Target) -> list[str]:
    return read_list(REPO_ROOT / "board" / target.name / "hw-packages.txt")


def is_hardware(name: str) -> bool:
    return any(fnmatch.fnmatch(name, p) for p in HARDWARE_PATTERNS)


def all_packages(target: Target) -> list[str]:
    return common_packages() + hw_packages(target)
