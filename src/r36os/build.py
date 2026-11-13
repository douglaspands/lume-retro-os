"""Build pipeline (D2): each hardware layer up to its SYSTEM, then the image.

`build vm` builds the vm layer and its image. `build console` (design D1) builds the ga36
and r36s layers one after the other (never in parallel), with one version for both, and
then the single card image with both systems.
"""

from __future__ import annotations

from r36os import bootimg, image, kernel, lang, rootfs, uboot, version
from r36os.archive import archive_image
from r36os.initramfs import build_initramfs
from r36os.packages import build_packages, ensure_key, local_aports, repo_dir
from r36os.targets import TARGETS, ImageTarget, Target


def build_image_target(img_target: ImageTarget, rebuild_packages: bool = False,
                       language: str = lang.DEFAULT) -> None:
    lang.retro_language(language)  # validate before any stage
    v = version.current()  # one timestamp per build, in every stage and layer (D15)
    print(f"build {img_target.name} {v.build_id} (language {language})", flush=True)
    layers = {}
    for name in img_target.layers:
        target = TARGETS[name]
        print(f"layer {name} ({target.alpine_arch})", flush=True)
        build_layer(target, v, language, rebuild_packages)
        layers[name] = _layer_info(target)
    if img_target.name == "vm":
        img = image.build_image(TARGETS["vm"], v=v, language=language)
        info = {**layers["vm"], "alpine": _alpine()}
        manifests = {"manifest.txt": img.parent / "manifest.txt"}
    else:
        img = image.build_console_image(v, language=language)
        info = {"alpine": _alpine(), "layers": layers, "bootloaders": console_bootloaders()}
        manifests = {f"manifest-{n}.txt": rootfs.target_out(TARGETS[n]) / "manifest.txt"
                     for n in img_target.layers}
    # image archived with the timestamp in out/images/<image>/
    dest = archive_image(img_target, img, v, {**info, "language": language}, manifests)
    print(f"ok: {img}\narchived: {dest}")


def build_layer(target: Target, v: version.BuildVersion, language: str,
                rebuild_packages: bool = False) -> None:
    """Packages, kernel, initramfs and SYSTEM of one hardware layer in out/<layer>/."""
    out = rootfs.target_out(target)
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
    rootfs.make_system(target, tar, out / "SYSTEM", rootfs.system_limit_mib(target))
    # [4] VM: the initramfs carries modules from the rootfs
    if not console:
        build_initramfs(target)


def _alpine() -> str:
    from r36os.container import ALPINE_VERSION

    return ALPINE_VERSION


def _layer_info(target: Target) -> dict:
    """Components of one layer for build.json."""
    info: dict = {"system_bytes": (rootfs.target_out(target) / "SYSTEM").stat().st_size}
    release = rootfs.target_out(target) / "kernel" / "release"
    if target.name in kernel.KERNEL_TARGETS and release.exists():
        info["kernel"] = release.read_text().strip()
        info["kernel_patches"] = [p.name for p in kernel.patches()]
    if target.name in uboot.UBOOT_TARGETS:
        info["u_boot"] = uboot.UBOOT_VERSION
    return info


def console_bootloaders() -> dict:
    """The factory chains in the console boot area, with the SHA256 they were checked by."""
    from r36os import r36s_vendor, vendor

    return {
        "ga36": {"chain": "vendor boot0 (shrunk to 24 KiB) + U-Boot 2017",
                 "area_sha256": vendor.AREA_SHA256},
        "r36s": {"chain": "vendor idbloader + uboot.img + trust.img",
                 "sha256": {r.name: r.sha256 for r in r36s_vendor.REGIONS},
                 "boot_files": dict(r36s_vendor.BOOT_FILES)},
    }


# target -> (kernel ARCH, folder of the SoC DTS in arch/<arch>/boot/dts/)
DTS_VENDOR = {"ga36": ("arm", "allwinner"), "r36s": ("arm64", "rockchip")}
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
