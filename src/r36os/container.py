"""Running rootless containers (podman) for the build stages."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from r36os.paths import REPO_ROOT
from r36os.targets import Target

ALPINE_VERSION = "3.24"
CROSS_IMAGE = "localhost/r36os-cross"


def builder_image(target: Target) -> str:
    return f"localhost/r36os-builder:{target.alpine_arch}"


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    print("+ " + " ".join(cmd), flush=True)
    kw.setdefault("check", True)
    return subprocess.run(cmd, **kw)


def image_exists(name: str) -> bool:
    return subprocess.run(
        ["podman", "image", "exists", name], check=False
    ).returncode == 0


def ensure_builder(target: Target) -> str:
    """Build (if missing) the Alpine builder image for the target architecture."""
    name = builder_image(target)
    if not image_exists(name):
        run([
            "podman", "build", "-t", name, "--platform", target.oci_platform,
            "--build-arg", f"ALPINE_VERSION={ALPINE_VERSION}",
            "-f", str(REPO_ROOT / "containers/builder.Containerfile"),
            str(REPO_ROOT / "containers"),
        ])
    return name


def ensure_cross() -> str:
    if not image_exists(CROSS_IMAGE):
        run([
            # fixed --platform: with qemu-user in binfmt, the base image tag may point
            # to an ARM variant pulled by another build
            "podman", "build", "-t", CROSS_IMAGE, "--platform", "linux/amd64",
            "-f", str(REPO_ROOT / "containers/cross.Containerfile"),
            str(REPO_ROOT / "containers"),
        ])
    return CROSS_IMAGE


@dataclass
class Container:
    """A `podman run --rm` with volumes. Root in the container = host user (rootless)."""

    image: str
    platform: str | None = None
    volumes: dict[Path, str] = field(default_factory=dict)
    env: dict[str, str] = field(default_factory=dict)
    workdir: str = "/"
    extra: list[str] = field(default_factory=list)

    def argv(self, script: str) -> list[str]:
        cmd = ["podman", "run", "--rm", "--network=host"]
        if self.platform:
            cmd += ["--platform", self.platform]
        for host, guest in self.volumes.items():
            # :z (shared SELinux label): the cache and the repository are used by several
            # containers at once; :Z would lock the others out.
            cmd += ["-v", f"{host}:{guest}:z"]
        for k, v in self.env.items():
            cmd += ["-e", f"{k}={v}"]
        cmd += ["-w", self.workdir, *self.extra, self.image, "sh", "-euc", script]
        return cmd

    def sh(self, script: str, **kw) -> subprocess.CompletedProcess:
        return run(self.argv(script), **kw)
