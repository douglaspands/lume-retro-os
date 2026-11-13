"""Build targets: hardware layers (one per system) and the images built from them.

A layer (`ga36`, `r36s`, `vm`) has its own architecture, container platform and
`board/<name>/` folder: packages, kernel, initramfs and SYSTEM are built per layer. The
images are what `build` and `flash` take: `console` (one card for the GA36 and the R36S,
with both layers) and `vm`.
"""

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


@dataclass(frozen=True)
class ImageTarget:
    name: str
    layers: tuple[str, ...]  # names in TARGETS, built in this order
    description: str


IMAGES: dict[str, ImageTarget] = {
    "console": ImageTarget("console", ("ga36", "r36s"),
                           "single card for the GA36 and the R36S V5"),
    "vm": ImageTarget("vm", ("vm",), "test VM (QEMU x86_64)"),
}


class InvalidTargetError(ValueError):
    """Target outside the list of valid targets."""

    def __init__(self, name: str, valid: list[str] | None = None) -> None:
        self.name = name
        valid = valid if valid is not None else list(IMAGES)
        super().__init__(f"invalid target: {name!r}. Valid targets: {', '.join(valid)}")


def get_target(name: str) -> Target:
    """Return the hardware layer by name or raise InvalidTargetError listing the layers."""
    try:
        return TARGETS[name]
    except KeyError:
        raise InvalidTargetError(name, list(TARGETS)) from None


def get_image(name: str) -> ImageTarget:
    """Return the image target by name or raise InvalidTargetError listing console, vm."""
    try:
        return IMAGES[name]
    except KeyError:
        raise InvalidTargetError(name, list(IMAGES)) from None
