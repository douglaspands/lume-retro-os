"""Pipeline de build de um alvo (D2)."""

from __future__ import annotations

from r36os import rootfs
from r36os.image import build_image
from r36os.initramfs import build_initramfs
from r36os.packages import build_packages, ensure_key, local_aports, repo_dir
from r36os.targets import Target


def build_target(target: Target, rebuild_packages: bool = False) -> None:
    out = rootfs.target_out(target)
    # [2] pacotes locais (só os que faltam no repositório, salvo rebuild)
    ensure_key(target)
    missing = [n for n in local_aports() if rebuild_packages or not _has_package(target, n)]
    if missing:
        build_packages(target, missing)
    # [3] rootfs, manifesto e SYSTEM
    tar = rootfs.build_rootfs(target)
    rootfs.make_system(target, tar, out / "SYSTEM")
    # [4] initramfs e imagem
    build_initramfs(target)
    img = build_image(target)
    print(f"ok: {img}")


def _has_package(target: Target, name: str) -> bool:
    return any(repo_dir(target).glob(f"{name}-[0-9]*.apk"))
