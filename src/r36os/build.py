"""Build pipeline (D2): each hardware layer up to its root (the slot set of a console,
build-speed D9; the SYSTEM of the vm), then the image.

`build vm` builds the vm layer and its image. `build console` (design D1) builds the ga36
and r36s layers at the same time (task 6.6: the armv7 and aarch64 pipelines, half the job
limit each, output prefixed, one summary per arch), with one version for both, and then
the single card image with both systems.
"""

from __future__ import annotations

from r36os import (bootimg, heat, image, kernel, lang, manifests, parallel, rootfs, slots,
                   stage_inputs, uboot, version)
from r36os.archive import archive_image
from r36os.initramfs import build_initramfs
from r36os.packages import (build_noarch, build_packages, ensure_key, is_noarch_aport,
                            local_aports, publish_noarch)
from r36os.paths import REPO_ROOT
from r36os.stages import StageTimer
from r36os.targets import TARGETS, ImageTarget, Target


def build_image_target(img_target: ImageTarget, rebuild_packages: bool = False,
                       language: str = lang.DEFAULT) -> None:
    lang.retro_language(language)  # validate before any stage
    timer = StageTimer()
    arch_timers: list[StageTimer] = []  # one per pipeline of a parallel build
    try:
        _build_image_target(img_target, rebuild_packages, language, timer, arch_timers)
    finally:
        # on success and on error alike; the error then propagates as before
        heat.add_summary(timer)  # max temperature and paused time, in the same block
        if arch_timers:
            timer.title = "build summary (common steps, image, archive):"
        for t in arch_timers:  # the summary of each arch, then the common one
            t.print_summary()
        timer.print_summary()


def arch_label(target: Target) -> str:
    """Prefix and summary label of a layer's pipeline: its Alpine architecture."""
    return target.alpine_arch


def _build_layers(img_target: ImageTarget, v: version.BuildVersion, language: str,
                  rebuild_packages: bool, timer: StageTimer,
                  arch_timers: list[StageTimer]) -> dict:
    """Build every layer of the image. The console layers (two architectures) run at the
    same time, each with half the job limit; what both use is done once before."""
    targets = [TARGETS[n] for n in img_target.layers]
    if len(targets) > 1:
        if any(t.name in kernel.KERNEL_TARGETS for t in targets):
            # both kernels build from the one patched source tree: prepare it once
            with timer.stage("kernel source tree"):
                kernel.source_tree()

        def pipeline(target: Target):
            def run(arch_timer: StageTimer) -> None:
                print(f"layer {target.name} ({target.alpine_arch})", flush=True)
                build_layer(target, v, language, rebuild_packages, arch_timer)
            return arch_label(target), run

        def new_timer(label: str) -> StageTimer:
            t = StageTimer(title=f"build summary [{label}]:")
            arch_timers.append(t)
            return t

        parallel.run_pipelines([pipeline(t) for t in targets], timer_factory=new_timer)
    else:
        for target in targets:
            print(f"layer {target.name} ({target.alpine_arch})", flush=True)
            build_layer(target, v, language, rebuild_packages, timer)
    return {t.name: _layer_info(t) for t in targets}


def _build_image_target(img_target: ImageTarget, rebuild_packages: bool, language: str,
                        timer: StageTimer, arch_timers: list[StageTimer] | None = None
                        ) -> None:
    v = version.current()  # one timestamp per build, in every stage and layer (D15)
    print(f"build {img_target.name} {v.build_id} (language {language})", flush=True)
    # noarch fragments (build-speed D2) come before any per-arch package and rootfs: built
    # once, then the same .apk is in the repository of every arch; then the arch
    # pipelines (in parallel on the console, build-speed D17)
    build_noarch_fragments(rebuild_packages, timer)
    layers = _build_layers(img_target, v, language, rebuild_packages, timer,
                           [] if arch_timers is None else arch_timers)
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
    """Packages, kernel, initramfs and root (slots or SYSTEM) of one layer in out/<layer>/."""
    timer = timer or StageTimer()
    p = f"{target.name}: "  # prefix of the stage names in the summary
    out = rootfs.target_out(target)
    console = target.name in kernel.KERNEL_TARGETS
    # [2] local packages: each compiles only when its inputs changed and is published only
    # when its content changed (build-speed D3); rebuild_packages compiles them all
    ensure_key(target)
    # the noarch fragments were built and published by build_noarch_fragments, not per arch
    noarch = set(noarch_fragments())
    with timer.stage(p + "local packages"):
        build_packages(target, [n for n in local_aports(target) if n not in noarch],
                       force=rebuild_packages)
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
    if console:
        # the console root is a slot set (build-speed D9): base, runtime and lume split
        # from rootfs.tar by owner, the modules image as the modules slot, and SLOTS
        build_console_slots(target, v, timer)
        return
    # the vm keeps its single SYSTEM (design D13)
    limit = rootfs.system_limit_mib(target)
    stage_inputs.run_stage(
        timer, p + "SYSTEM", out / "SYSTEM",
        lambda: stage_inputs.system_inputs(tar, rootfs.SQUASHFS_OPTIONS, limit),
        lambda: rootfs.make_system(target, tar, out / "SYSTEM", limit))
    # [4] VM: the initramfs carries modules from the rootfs
    _initramfs_stage(target, timer, p)


def build_console_slots(target: Target, v: version.BuildVersion,
                        timer: StageTimer | None = None) -> None:
    """out/<console>/slot/: the overlay slots (skipped when rootfs.tar holds the same
    files, slots.toml and the options did not change) and the set of this build (SLOTS
    with the build id, the modules slot, the 448 MiB limit)."""
    timer = timer or StageTimer()
    p = f"{target.name}: "
    out = rootfs.target_out(target)
    tar = out / "rootfs.tar"
    sdir = slots.slots_dir(out)
    stage_inputs.run_stage(
        timer, p + "slots", sdir / slots.OVERLAY_RECORD,
        lambda: stage_inputs.slots_inputs(tar, slots.SLOTS_TOML, rootfs.SQUASHFS_OPTIONS),
        lambda: slots.build_overlay_slots(tar, sdir, rootfs.SQUASHFS_OPTIONS),
        required=slots.overlay_files(sdir))
    release = out / "kernel" / "release"
    build_id = (v or version.current()).build_id
    with timer.stage(p + "slot set"):
        slots.write_slot_set(target.name, build_id, sdir, out / "kernel" / "modules",
                             release.read_text().strip() if release.exists() else "")


def noarch_fragments() -> list[str]:
    """The aports that say arch="noarch" (fragments built once for every architecture)."""
    return [n for n in local_aports()
            if is_noarch_aport(REPO_ROOT / "aports" / n / "APKBUILD")]


def build_noarch_fragments(rebuild_packages: bool = False,
                           timer: StageTimer | None = None) -> None:
    """Build the noarch fragments once (x86_64 builder) and publish the same .apk in
    out/repo/<arch> for every arch, each index rebuilt. Runs before the arch packages.

    build_noarch decides by content (build-speed D3): a fragment whose inputs did not
    change is not built, one whose content did not change is not published, and a changed
    one gets the next pkgrel; `rebuild_packages` compiles them all (same content is still
    not published)."""
    timer = timer or StageTimer()
    names = noarch_fragments()
    if not names:
        timer.skip("noarch fragments", "none")
        return
    with timer.stage("noarch fragments"):
        apks = build_noarch(names, force=rebuild_packages)  # makes the abuild key too
        if apks:
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
    out = rootfs.target_out(target)
    if target.name in kernel.KERNEL_TARGETS:
        ss = manifests.read_slots(slots.slots_dir(out) / manifests.SLOTS_FILE)
        info: dict = {"slots": {s.name: {"file": s.file, "bytes": s.size}
                                for s in ss.slots}}
    else:
        info = {"system_bytes": (out / "SYSTEM").stat().st_size}
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
    """Stage 1: out/<target>/kernel/ with the image, modules.tar, the modules image (the
    modules slot of the console, build-speed D9), validated dtbs/ and boot."""
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
