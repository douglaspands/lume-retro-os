"""Build pipeline (D2): each hardware layer up to its SYSTEM, then the image.

`build vm` builds the vm layer and its image. `build console` (design D1) builds the ga36
and r36s layers one after the other (never in parallel), with one version for both, and
then the single card image with both systems.
"""

from __future__ import annotations

from r36os import bootimg, heat, image, kernel, lang, rootfs, stage_inputs, uboot, version
from r36os.archive import archive_image
from r36os.initramfs import build_initramfs
from r36os.packages import (REPO_ARCHES, arch_repo_dir, build_noarch, build_packages,
                            ensure_key, is_noarch_aport, local_aports, publish_noarch,
                            repo_dir)
from r36os.paths import REPO_ROOT
from r36os.stages import StageTimer
from r36os.targets import TARGETS, ImageTarget, Target


def build_image_target(img_target: ImageTarget, rebuild_packages: bool = False,
                       language: str = lang.DEFAULT) -> None:
    lang.retro_language(language)  # validate before any stage
    timer = StageTimer()
    try:
        _build_image_target(img_target, rebuild_packages, language, timer)
    finally:
        # on success and on error alike; the error then propagates as before
        heat.add_summary(timer)  # max temperature and paused time, in the same block
        timer.print_summary()


def _build_image_target(img_target: ImageTarget, rebuild_packages: bool, language: str,
                        timer: StageTimer) -> None:
    v = version.current()  # one timestamp per build, in every stage and layer (D15)
    print(f"build {img_target.name} {v.build_id} (language {language})", flush=True)
    # noarch fragments (build-speed D2) come before any per-arch package and rootfs: built
    # once, then the same .apk is in the repository of every arch
    build_noarch_fragments(rebuild_packages, timer)
    layers = {}
    for name in img_target.layers:
        target = TARGETS[name]
        print(f"layer {name} ({target.alpine_arch})", flush=True)
        build_layer(target, v, language, rebuild_packages, timer)
        layers[name] = _layer_info(target)
    extras = {}
    with timer.stage("image"):
        if img_target.name == "vm":
            img = image.build_image(TARGETS["vm"], v=v, language=language)
            info = {**layers["vm"], "alpine": _alpine()}
            manifests = {"manifest.txt": img.parent / "manifest.txt"}
        else:
            img = image.build_console_image(v, language=language)
            info = {"alpine": _alpine(), "layers": layers,
                    "bootloaders": console_bootloaders()}
            manifests = {f"manifest-{n}.txt": rootfs.target_out(TARGETS[n]) / "manifest.txt"
                         for n in img_target.layers}
            # the GA36 panel boot images: for a dd to sector 172032 from the PC, not on BOOT
            extras = image.ga36_android_boot_images(rootfs.target_out(TARGETS["ga36"]))
            # the files of BOOT with their SHA256, read back from the FAT (task 5.1): what
            # `r36os push` sends and checks on the console
            extras[image.BOOT_LIST] = img.parent / image.BOOT_LIST
    # image archived with the timestamp in out/images/<image>/
    with timer.stage("archive"):
        dest = archive_image(img_target, img, v, {**info, "language": language}, manifests,
                             extras)
    print(f"ok: {img}\narchived: {dest}")


def build_layer(target: Target, v: version.BuildVersion, language: str,
                rebuild_packages: bool = False, timer: StageTimer | None = None) -> None:
    """Packages, kernel, initramfs and SYSTEM of one hardware layer in out/<layer>/."""
    timer = timer or StageTimer()
    p = f"{target.name}: "  # prefix of the stage names in the summary
    out = rootfs.target_out(target)
    console = target.name in kernel.KERNEL_TARGETS
    # [2] local packages (only those missing from the repository, unless rebuilding)
    ensure_key(target)
    # the noarch fragments were built and published by build_noarch_fragments, not per arch
    noarch = set(noarch_fragments())
    missing = [n for n in local_aports(target) if n not in noarch
               and (rebuild_packages or not _has_package(target, n))]
    if missing:
        with timer.stage(p + "local packages"):
            build_packages(target, missing)
    else:
        timer.skip(p + "local packages", "all in the repository")
    if console:
        # on the consoles the initramfs is built into the kernel: it comes before stage 1
        _initramfs_stage(target, timer, p)
        # [1] kernel, modules, DTBs and boot image, cross-compiled
        build_console_kernel(target, timer)
    # [3] rootfs (with the stage 1 modules), manifest and SYSTEM
    tar = out / "rootfs.tar"
    stage_inputs.run_stage(
        timer, p + "rootfs", tar, lambda: rootfs.stage_inputs(target, v, language),
        lambda: rootfs.build_rootfs(target, v, language), required=[out / "manifest.txt"])
    limit = rootfs.system_limit_mib(target)
    stage_inputs.run_stage(
        timer, p + "SYSTEM", out / "SYSTEM",
        lambda: stage_inputs.system_inputs(tar, rootfs.SQUASHFS_OPTIONS, limit),
        lambda: rootfs.make_system(target, tar, out / "SYSTEM", limit))
    # [4] VM: the initramfs carries modules from the rootfs
    if not console:
        _initramfs_stage(target, timer, p)


def noarch_fragments() -> list[str]:
    """The aports that say arch="noarch" (fragments built once for every architecture)."""
    return [n for n in local_aports()
            if is_noarch_aport(REPO_ROOT / "aports" / n / "APKBUILD")]


def _missing_noarch(rebuild_packages: bool) -> list[str]:
    """Fragments with no .apk in the repository of some architecture (all, if rebuilding)."""
    return [n for n in noarch_fragments()
            if rebuild_packages
            or any(not list(arch_repo_dir(a).glob(f"{n}-[0-9]*.apk")) for a in REPO_ARCHES)]


def build_noarch_fragments(rebuild_packages: bool = False,
                           timer: StageTimer | None = None) -> None:
    """Build the missing noarch fragments once (x86_64 builder) and publish the same .apk
    in out/repo/<arch> for every arch, each index rebuilt. Runs before the arch packages."""
    timer = timer or StageTimer()
    missing = _missing_noarch(rebuild_packages)
    if not missing:
        timer.skip("noarch fragments", "all in the repository")
        return
    with timer.stage("noarch fragments"):
        apks = build_noarch(missing)  # makes the abuild key too
        if rebuild_packages:
            # a rebuild is a different file under the same name: publish refuses to mix them
            for n in missing:
                for a in REPO_ARCHES:
                    for old in arch_repo_dir(a).glob(f"{n}-[0-9]*.apk"):
                        old.unlink()
        publish_noarch(apks)


def _initramfs_stage(target: Target, timer: StageTimer, prefix: str) -> None:
    out = rootfs.target_out(target)
    stage_inputs.run_stage(
        timer, prefix + "initramfs", out / "initramfs",
        lambda: stage_inputs.initramfs_inputs(target, out / "rootfs.tar"),
        lambda: build_initramfs(target))


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


def build_console_kernel(target: Target, timer: StageTimer | None = None) -> None:
    """Stage 1: out/<target>/kernel/ with the image, modules.tar, the modules image (BOOT
    <console>/modules, outside SYSTEM), validated dtbs/ and boot."""
    timer = timer or StageTimer()
    p = f"{target.name}: "
    out = rootfs.target_out(target)
    kdir = out / "kernel"
    with timer.stage(p + "kernel"):
        zimage = kernel.build_kernel(target.name, kdir, initramfs_dir=out)
    stage_inputs.run_stage(
        timer, p + "modules image", kdir / "modules",
        lambda: stage_inputs.modules_inputs(kdir / "modules.tar", rootfs.MODULES_SCRIPT),
        lambda: rootfs.make_modules_image(kdir / "modules.tar", kdir / "modules"))
    arch, vendor = DTS_VENDOR[target.name]
    stage_inputs.run_stage(
        timer, p + "DTBs + validation", kdir / "dtbs",
        lambda: stage_inputs.dtb_inputs(target.name, arch, vendor),
        lambda: kernel.build_dtbs(target.name, arch, vendor, kdir / "dtbs"))
    if target.name in uboot.UBOOT_TARGETS:
        with timer.stage(p + "u-boot"):
            uboot.build_uboot(target.name, kdir)
    else:
        timer.skip(p + "u-boot", "no U-Boot for this console")
    with timer.stage(p + "boot images"):
        for panel, dtb in ANDROID_BOOT.get(target.name, {}).items():
            # zImage + appended DTB, like goodluckOS (CONFIG_ARM_APPENDED_DTB)
            kernel_blob = zimage.read_bytes() + (kdir / "dtbs" / dtb).read_bytes()
            (kdir / f"android-boot-{panel}.img").write_bytes(bootimg.make(kernel_blob))


def _has_package(target: Target, name: str) -> bool:
    return any(repo_dir(target).glob(f"{name}-[0-9]*.apk"))
