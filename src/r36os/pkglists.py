"""Leitura das listas de pacotes (comum e por alvo)."""

from __future__ import annotations

import fnmatch
from pathlib import Path

from r36os.paths import REPO_ROOT
from r36os.targets import Target

COMMON = REPO_ROOT / "rootfs/packages.txt"

# Padrões que caracterizam a camada de hardware: nunca podem estar na lista comum.
HARDWARE_PATTERNS = (
    "linux-*",  # kernels e firmware (linux-virt, linux-lts, linux-firmware-*)
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
