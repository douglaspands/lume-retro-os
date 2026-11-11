"""Supported build targets and their validation."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Target:
    name: str
    alpine_arch: str  # architecture name in Alpine (apk --arch)
    oci_platform: str  # container platform (podman --platform)
    description: str

    @property
    def is_console(self) -> bool:
        return self.name != "vm"


TARGETS: dict[str, Target] = {
    "r36s": Target("r36s", "aarch64", "linux/arm64", "R36S V5 (Rockchip RK3326)"),
    "ga36": Target("ga36", "armv7", "linux/arm/v7", "GA36-MB V1.2 (Allwinner A33)"),
    "vm": Target("vm", "x86_64", "linux/amd64", "Test VM (QEMU x86_64)"),
}


class InvalidTargetError(ValueError):
    """Target outside the list of supported targets."""

    def __init__(self, name: str) -> None:
        self.name = name
        valid = ", ".join(TARGETS)
        super().__init__(f"invalid target: {name!r}. Valid targets: {valid}")


def get_target(name: str) -> Target:
    """Return the target by name or raise InvalidTargetError listing the valid ones."""
    try:
        return TARGETS[name]
    except KeyError:
        raise InvalidTargetError(name) from None
