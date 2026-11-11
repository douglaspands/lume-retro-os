"""Build pipeline of a target (D2)."""

from __future__ import annotations

from r36os import bootimg, kernel, lang, rootfs, uboot, version
from r36os.archive import archive_image
from r36os.image import build_image
from r36os.initramfs import build_initramfs
from r36os.packages import build_packages, ensure_key, local_aports, repo_dir
from r36os.targets import Target


def build_target(target: Target, rebuild_packages: bool = False,
                 language: str = lang.DEFAULT) -> None:
    lang.retro_language(language)  # validate before any stage
    out = rootfs.target_out(target)
    v = version.current()  # one timestamp per build, in every stage (D15)
    print(f"build {target.name} {v.build_id} (language {language})", flush=True)
    console = target.name in kernel.KERNEL_TARGETS
    # [2] local packages (only those missing from the repository, unless rebuilding)
    ensure_key(target)
    missing = [n for n in local_aports(target)
               if rebuild_packages or not _has_package(target, n)]
    if missing:
        build_packages(target, missing)
    if console:
        # on the consoles the initramfs is built into the kernel: it comes before stage 1
        build_initramfs(target)
        # [1] kernel, modules, DTBs and boot image, cross-compiled
        build_console_kernel(target)
    # [3] rootfs (with the stage 1 modules), manifest and SYSTEM
    tar = rootfs.build_rootfs(target, v, language)
    rootfs.make_system(target, tar, out / "SYSTEM")
    # [4] initramfs (VM: it carries modules from the rootfs) and image
    if not console:
        build_initramfs(target)
    img = build_image(target, v=v, language=language)
    # image archived with the timestamp in out/images/<target>/
    dest = archive_image(target, img, v, {**_build_info(target), "language": language})
    print(f"ok: {img}\narchived: {dest}")


def _build_info(target: Target) -> dict:
    """Build components for build.json."""
    from r36os.container import ALPINE_VERSION

    info: dict = {"alpine": ALPINE_VERSION,
                  "system_bytes": (rootfs.target_out(target) / "SYSTEM").stat().st_size}
    release = rootfs.target_out(target) / "kernel" / "release"
    if target.name in kernel.KERNEL_TARGETS and release.exists():
        info["kernel"] = release.read_text().strip()
        info["kernel_patches"] = [p.name for p in kernel.patches()]
    if target.name in uboot.UBOOT_TARGETS:
        info["u_boot"] = uboot.UBOOT_VERSION
    if target.name in ANDROID_BOOT:
        info["bootloader"] = "vendor (boot0 + U-Boot 2017, 128 MiB area)"
    return info


# target -> (kernel ARCH, folder of the SoC DTS in arch/<arch>/boot/dts/)
DTS_VENDOR = {"ga36": ("arm", "allwinner")}
# targets with the vendor bootloader: one Android boot image per panel (appended DTB)
ANDROID_BOOT = {"ga36": {"panel1": "sun8i-a33-ga36-mb-v1.2-panel1.dtb",
                         "panel2": "sun8i-a33-ga36-mb-v1.2-panel2.dtb"}}


def build_console_kernel(target: Target) -> None:
    """Stage 1: out/<target>/kernel/ with the image, modules.tar, validated dtbs/ and boot."""
    out = rootfs.target_out(target)
    kdir = out / "kernel"
    zimage = kernel.build_kernel(target.name, kdir, initramfs_dir=out)
    arch, vendor = DTS_VENDOR[target.name]
    kernel.build_dtbs(target.name, arch, vendor, kdir / "dtbs")
    if target.name in uboot.UBOOT_TARGETS:
        uboot.build_uboot(target.name, kdir)
    for panel, dtb in ANDROID_BOOT.get(target.name, {}).items():
        # zImage + appended DTB, like goodluckOS (CONFIG_ARM_APPENDED_DTB)
        kernel_blob = zimage.read_bytes() + (kdir / "dtbs" / dtb).read_bytes()
        (kdir / f"android-boot-{panel}.img").write_bytes(bootimg.make(kernel_blob))


def _has_package(target: Target, name: str) -> bool:
    return any(repo_dir(target).glob(f"{name}-[0-9]*.apk"))
