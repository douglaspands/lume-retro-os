"""Stage 4: card image (MBR + FAT32 BOOT), with no root and no loop mount.

vm: 0-16 MiB free for the bootloader; partition 1 `BOOT` (FAT32, 1 GiB) at sector 32768.
console (design D2): the first 128 MiB are the boot area of both consoles (bootarea.py:
GA36 vendor area with the shrunk boot0, the R36S factory chain and our Android boot image
at sector 172032), and `BOOT` (FAT32, 2 GiB, room for future systems and A/B updates)
starts at sector 262144. Partition 2 (`ROMS`) is created by `flash` or on the first boot.
"""

from __future__ import annotations

from pathlib import Path

from r36os import bootarea, version
from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT
from r36os.rootfs import target_out
from r36os.targets import TARGETS, ImageTarget, Target

BOOT_START = 32768  # 512 B sectors = 16 MiB (default)
BOOT_SECTORS = 2 * 1024 * 1024  # 1 GiB (default, the vm)
IMAGE_SECTORS = BOOT_START + BOOT_SECTORS

# Images with a vendor boot area: BOOT starts after it (128 MiB), with the disk signature
# of the GA36 cards (the kernels look for PARTUUID=4c554d32-01)
VENDOR_BOOT_START = {"console": bootarea.AREA_SECTORS}
DISK_ID = {"console": bootarea.DISK_ID}
# The console BOOT holds both systems: 2 GiB leaves room for the planned growth (catalog,
# Wi-Fi, a third system, A/B updates). Decided by the user on 2026-11-11; cards written
# with the older 1 GiB BOOT need a full write (`--update` refuses them).
BOOT_SIZE = {"console": 4 * 1024 * 1024}

KERNEL_NAME = {"vm": "vmlinuz", "r36s": "Image", "ga36": "zImage"}


def boot_start(target: Target | ImageTarget | str) -> int:
    name = target if isinstance(target, str) else target.name
    return VENDOR_BOOT_START.get(name, BOOT_START)


def boot_sectors(target: Target | ImageTarget | str) -> int:
    """Size of the BOOT partition of an image, in 512 B sectors."""
    name = target if isinstance(target, str) else target.name
    return BOOT_SIZE.get(name, BOOT_SECTORS)


def disk_id(target: Target | ImageTarget | str) -> str:
    name = target if isinstance(target, str) else target.name
    if name in DISK_ID:
        return DISK_ID[name]
    return (REPO_ROOT / "board" / name / "disk-id").read_text().strip()


_IMAGE = """
W=/out/imgwork
rm -rf $W && mkdir -p $W
# FAT32 BOOT with "hidden sectors" = partition offset (needed to boot).
truncate -s {boot_bytes} $W/boot.img
mkfs.vfat -F 32 -n BOOT -h {boot_start} -S 512 $W/boot.img >/dev/null
export MTOOLS_SKIP_CHECK=1
# No logs/: the logs live in ROMS/logs/ (D14); BOOT only gets logs/ without ROMS
{fat_files}
if [ -f /out/VERSION ]; then mcopy -i $W/boot.img /out/VERSION ::VERSION; fi
mcopy -i $W/boot.img /out/SYSTEM ::SYSTEM
{bootloader_fat}
# Disk: MBR table with a fixed signature and only BOOT (active).
truncate -s {image_bytes} $W/disk.img
printf 'label: dos\\nlabel-id: 0x{disk_id}\\nstart={boot_start}, size={boot_sectors}, type=c, bootable\\n' \\
    | sfdisk -q $W/disk.img
dd if=$W/boot.img of=$W/disk.img bs=512 seek={boot_start} conv=notrunc,sparse status=none
{bootloader_raw}
mv $W/disk.img /out/{name}.img
rm -rf $W
"""

# VM: SYSLINUX in BOOT (reads /extlinux/extlinux.conf) and mbr.bin in sector 0.
_VM_FILES = """mmd -i $W/boot.img ::extlinux
mcopy -i $W/boot.img /board/extlinux.conf ::extlinux/extlinux.conf
mcopy -i $W/boot.img /out/kernel/vmlinuz-virt ::vmlinuz
mcopy -i $W/boot.img /out/initramfs ::initramfs"""
_VM_FAT = "syslinux --install --directory /extlinux $W/boot.img"
_VM_RAW = ("dd if=/usr/share/syslinux/mbr.bin of=$W/disk.img bs=440 count=1 "
           "conv=notrunc status=none")


# Console (design D5; boot-dtb-select D8): BOOT with one folder per console, one folder of
# DTBs per SoC (dtbs/<soc>/, read by lume-bootsel) and, at the root, the boot.ini that the
# R36S U-Boot reads. Only what the consoles read: the GA36 slot set (SLOTS, slot/; build-
# speed D9) and the zImage without an appended DTB (reloaded by kexec; the kernel with the
# built-in initramfs and the appended DTB is the Android boot image at sector 172032,
# outside BOOT, and the images of both panels are archived next to the card image for a dd
# from the PC). R36S: the slot set and the Image (initramfs built in); boot.ini loads the
# default DTB from dtbs/rk3326/.
_CONSOLE = """
W=/out/imgwork
rm -rf $W && mkdir -p $W
truncate -s {boot_bytes} $W/boot.img
mkfs.vfat -F 32 -n BOOT -h {boot_start} -S 512 $W/boot.img >/dev/null
export MTOOLS_SKIP_CHECK=1
M="mcopy -i $W/boot.img"
$M {version} ::VERSION
# every other file from console_boot_files() (the same list flash and push use, task 5.1)
mmd -i $W/boot.img {dirs}
{copies}
# what really is on the FAT, as "<sha256>  <path>" (the BOOT list of the build)
mkdir -p $W/check
for f in {paths}; do
  mcopy -n -i $W/boot.img "::$f" $W/check/x
  echo "$(sha256sum $W/check/x | cut -d' ' -f1)  $f"
done > /out/boot-files.sha256
rm -rf $W/check
# at least {min_free} bytes free on BOOT (updates and the panel switch need room)
free=$(mdir -i $W/boot.img :: | sed -n 's/ *bytes free.*//p' | tr -d ' ')
echo "BOOT: $free bytes free"
if [ "$free" -lt {min_free} ]; then
  echo "error: BOOT has only $free bytes free, the console image needs {min_free}" >&2
  exit 1
fi
# Disk: MBR with the signature of the GA36 cards and only BOOT (active)
truncate -s {image_bytes} $W/disk.img
printf 'label: dos\\nlabel-id: 0x{disk_id}\\nstart={boot_start}, size={boot_sectors}, type=c, bootable\\n' \\
    | sfdisk -q $W/disk.img
# boot area of both consoles without sector 0 (the MBR is ours), then the panel 1 boot image
dd if={area_file} of=$W/disk.img bs=512 skip=1 seek=1 count={area_sectors} conv=notrunc status=none
dd if={panel1} of=$W/disk.img bs=512 seek={android} conv=notrunc status=none
dd if=$W/boot.img of=$W/disk.img bs=512 seek={boot_start} conv=notrunc,sparse status=none
mv $W/disk.img /out/console.img
rm -rf $W
"""

R36S_DTB = "rk3326-r36s-v5.dtb"
# console -> folder of its SoC under BOOT/dtbs/ (the initramfs reads it from /etc/soc)
SOC_DIR = {"ga36": "a33", "r36s": "rk3326"}
BOOT_MIN_FREE = 64 * 2**20
_CLUSTER = 4096                 # mkfs.vfat -F 32 on 1 to 2 GiB
_FAT_OVERHEAD = 16 * 2**20      # FATs, reserved sectors and directories (upper bound)


class ConsoleImageError(RuntimeError):
    pass


def console_boot_files(ga36_out: Path, r36s_out: Path,
                       factory: dict[str, Path] | None = None) -> dict[str, Path]:
    """BOOT path -> source of every file of the console BOOT except VERSION.

    `factory`: files of the R36S factory BOOT root (r36s_vendor.factory_boot_files()).
    """
    files = {**(factory or {}),
             "boot.ini": REPO_ROOT / "board/r36s/boot.ini",
             "ga36/zImage": ga36_out / "kernel/zImage",
             "r36s/Image": r36s_out / "kernel/Image",
             f"dtbs/{SOC_DIR['r36s']}/{R36S_DTB}": r36s_out / "kernel/dtbs" / R36S_DTB}
    for board, out in (("ga36", ga36_out), ("r36s", r36s_out)):
        # the root of each console is its slot set (build-speed D9): <console>/SLOTS and
        # <console>/slot/<name>-<sha12>, the kernel modules among them; no SYSTEM and no
        # <console>/modules on a new card (an old one keeps them until the push of 4.6)
        files.update(console_slot_files(board, out))
        for dtb in sorted((out / "kernel/dtbs").glob("*.dtb")):
            files[f"dtbs/{SOC_DIR[board]}/{dtb.name}"] = dtb
        # trees converted from vendor DTBs (boot-dtb-select D12), read only on demand
        for dtb in sorted((out / "kernel/dtbs/vendor").glob("*.dtb")):
            files[f"dtbs/{SOC_DIR[board]}/vendor/{dtb.name}"] = dtb
    return files


def console_slot_files(board: str, layer_out: Path) -> dict[str, Path]:
    """BOOT path -> source of the slot set of a console: <console>/SLOTS (listed even when
    the layer has none yet, so the image build reports it missing) and the slot files it
    names."""
    from r36os import manifests, slots

    sdir = slots.slots_dir(layer_out)
    if not (sdir / manifests.SLOTS_FILE).is_file():
        return {f"{board}/{manifests.SLOTS_FILE}": sdir / manifests.SLOTS_FILE}
    return slots.boot_files(board, sdir)


BOOT_LIST = "boot-files.sha256"   # "<sha256>  <BOOT path>" of every file, VERSION last


def _in_container(src: Path, volumes: dict[Path, str]) -> str:
    for host, guest in volumes.items():
        if src.is_relative_to(host):
            return f"{guest}/{src.relative_to(host)}"
    raise ConsoleImageError(f"{src} is outside the volumes of the image build")


def boot_copy_commands(files: dict[str, Path], volumes: dict[Path, str]) -> dict[str, str]:
    """The mmd/mcopy lines of the console BOOT from `files` (BOOT path -> host source), and
    the list of paths to check back, VERSION last: one list for the FAT, flash and push."""
    dirs = sorted({"/".join(p.split("/")[:i]) for p in files
                   for i in range(1, p.count("/") + 1)})
    copies = "\n".join(f'$M "{_in_container(src, volumes)}" "::{path}"'
                       for path, src in sorted(files.items()))
    paths = " ".join(f'"{p}"' for p in [*sorted(files), "VERSION"])
    return {"dirs": " ".join(f"::{d}" for d in dirs), "copies": copies, "paths": paths}


def read_boot_list(path: Path) -> list[tuple[str, str]]:
    """(BOOT path, sha256) of a build's boot-files.sha256, in order (VERSION last)."""
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            digest, name = line.split("  ", 1)
            out.append((name, digest))
    return out


def ga36_android_boot_images(ga36_out: Path) -> dict[str, Path]:
    """Archived name -> boot image of each GA36 panel (written to sector 172032 with dd
    from the PC; they are not on BOOT, which keeps only what the consoles read)."""
    return {f"ga36-{img.name}": img
            for img in sorted((ga36_out / "kernel").glob("android-boot-*.img"))}


def check_soc_dtbs(files: dict[str, Path]) -> None:
    """Every BOOT/dtbs/<soc>/ folder (boot-dtb-select D3): each DTB has the lume-select
    node, the ids are unique and exactly one DTB is the default of its SoC. A converted DTB
    of dtbs/<soc>/vendor/ (D12) is named after its lume,id (lume-bootsel finds it by the
    name) and is never the default."""
    from r36os import fdt

    by_soc: dict[str, dict[str, dict]] = {}
    for path, src in sorted(files.items()):
        parts = path.split("/")
        vendor = len(parts) == 4 and parts[2] == "vendor"
        if parts[0] != "dtbs" or not path.endswith(".dtb") or not (len(parts) == 3 or vendor):
            continue
        info = fdt.select_info(fdt.parse(src.read_bytes()))
        if info is None or not info["id"]:
            raise ConsoleImageError(f"{path} has no lume-select node with lume,id")
        if vendor and (info["id"] != parts[3][:-4] or info["default"]):
            raise ConsoleImageError(f"{path}: a vendor DTB is named after its lume,id "
                                    f"({info['id']}) and is not the default")
        by_soc.setdefault(parts[1], {})[path] = info
    for soc, dtbs in by_soc.items():
        ids = [i["id"] for i in dtbs.values()]
        dup = sorted({i for i in ids if ids.count(i) > 1})
        if dup:
            raise ConsoleImageError(f"dtbs/{soc}/: repeated lume,id {', '.join(dup)}")
        defaults = [p for p, i in dtbs.items() if i["default"]]
        if len(defaults) != 1:
            raise ConsoleImageError(
                f"dtbs/{soc}/ needs exactly one default DTB, has {len(defaults)}"
                + (f": {', '.join(defaults)}" if defaults else ""))


def _clusters(size: int) -> int:
    return -(-size // _CLUSTER) * _CLUSTER


def check_console_boot(sizes: dict[str, int]) -> None:
    """Limits of the console BOOT (system-image, build-speed D9): the slots of each console
    (<console>/slot/*) within 448 MiB together, and at least 64 MiB free on the 2 GiB BOOT
    counting the previous set a push keeps (SLOTS.old): every slot is counted twice, the
    previous set taken as large as the new one. `sizes` maps the BOOT path to the size."""
    from r36os.manifests import SLOTS_DIR
    from r36os.slots import CONSOLE_SLOTS_LIMIT_MIB

    per_console: dict[str, int] = {}
    for path, size in sizes.items():
        parts = path.split("/")
        if len(parts) == 3 and parts[1] == SLOTS_DIR:
            per_console[parts[0]] = per_console.get(parts[0], 0) + size
    for console, total in sorted(per_console.items()):
        if total > CONSOLE_SLOTS_LIMIT_MIB * 2**20:
            raise ConsoleImageError(
                f"the slots of {console} take {total / 2**20:.1f} MiB, above the "
                f"{CONSOLE_SLOTS_LIMIT_MIB} MiB limit of each console on the image")
    used = sum(_clusters(size) for size in sizes.values())
    previous = sum(_clusters(size) for path, size in sizes.items()
                   if path.split("/")[1:2] == [SLOTS_DIR])
    free = boot_sectors("console") * 512 - _FAT_OVERHEAD - used - previous
    if free < BOOT_MIN_FREE:
        raise ConsoleImageError(
            f"the console BOOT would have {free / 2**20:.0f} MiB free, it needs at least "
            f"{BOOT_MIN_FREE // 2**20} MiB (files: {used / 2**20:.0f} MiB, the previous "
            f"slot set: {previous / 2**20:.0f} MiB)")


def build_image(target: Target, v: version.BuildVersion | None = None,
                language: str = "en") -> Path:
    """The vm image (out/vm/vm.img)."""
    out = target_out(target)
    # BOOT/VERSION: the build on the card, readable on a PC (D15)
    (out / "VERSION").unlink(missing_ok=True)
    if v is not None:
        (out / "VERSION").write_text(
            version.boot_version_file(target.name, v) + f"language: {language}\n")
    volumes = {out: "/out", REPO_ROOT / "board" / target.name: "/board"}
    start = boot_start(target)
    if target.name != "vm":
        raise ValueError(f"{target.name} is a hardware layer: its image is the console one")
    fat_files, bootloader_fat, bootloader_raw = _VM_FILES, _VM_FAT, _VM_RAW
    script = _IMAGE.format(
        boot_bytes=BOOT_SECTORS * 512,
        boot_start=start,
        boot_sectors=BOOT_SECTORS,
        image_bytes=(start + BOOT_SECTORS) * 512,
        disk_id=disk_id(target),
        fat_files=fat_files,
        bootloader_fat=bootloader_fat,
        bootloader_raw=bootloader_raw,
        name=target.name,
    )
    # Building the image does not depend on the target arch: always the x86_64 builder.
    Container(image=ensure_builder(TARGETS["vm"]), volumes=volumes).sh(script)
    return out / f"{target.name}.img"


def build_console_image(v: version.BuildVersion, language: str = "en") -> Path:
    """The console image (out/console/console.img) from the ga36 and r36s layers (D2, D5).

    The 128 MiB before BOOT are the boot area of both consoles (bootarea.py), with the
    Android boot image of GA36 panel 1 at sector 172032; BOOT starts at sector 262144.
    """
    import shutil

    from r36os import r36s_vendor
    from r36os.paths import ensure_dir
    from r36os.targets import IMAGES

    out = ensure_dir(target_out(IMAGES["console"]))
    ga36_out, r36s_out = target_out(TARGETS["ga36"]), target_out(TARGETS["r36s"])
    factory = r36s_vendor.factory_boot_files()
    staging = out / "factory-boot"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir()
    for name, src in factory.items():
        shutil.copy(src, staging / name)
    files = console_boot_files(ga36_out, r36s_out, factory)
    missing = [str(src) for src in files.values() if not src.exists()]
    if missing:
        raise ConsoleImageError("missing layer outputs: " + ", ".join(missing))
    check_soc_dtbs(files)
    check_console_boot({path: src.stat().st_size for path, src in files.items()})
    (out / "VERSION").write_text(
        version.boot_version_file("console", v) + f"language: {language}\n")
    area = bootarea.write_console_area(out / "console-boot-area.bin")
    # the factory files are staged in out/factory-boot/ (under /out in the container)
    staged = {**files, **{name: staging / name for name in factory}}
    volumes = {out: "/out", ga36_out: "/ga36", r36s_out: "/r36s",
               REPO_ROOT / "board/r36s": "/board"}
    panel1 = ga36_out / "kernel" / PANEL1_SOURCE
    script = _console_script(staged, volumes, "/out/VERSION", f"/out/{area.name}",
                             f"/ga36/kernel/{PANEL1_SOURCE}")
    # the image does not depend on the target arch: always the x86_64 builder
    Container(image=ensure_builder(TARGETS["vm"]), volumes=volumes).sh(script)
    # build-speed D10: every file of BOOT and both pieces outside it, once in objects/
    store_build_objects(out, {**staged, VERSION_FILE: out / "VERSION"},
                        {AREA_PART: area, PANEL1_PART: panel1})
    area.unlink()
    return out / "console.img"


def write_console_set(v: version.BuildVersion, language: str = "en",
                      ga36_out: Path | None = None, r36s_out: Path | None = None,
                      out: Path | None = None, area_writer=None) -> Path:
    """A console build without its image (fragment build, build-speed 6.2): the BOOT list
    out/console/boot-files.sha256 of every file the card's BOOT would hold (kernels, DTBs,
    the slot sets of both consoles, the R36S factory files, VERSION last), each file and the
    two image parts stored in objects/, and image-parts.sha256. No FAT and no 2 GiB image:
    the sha256 comes from the sources, which is what mcopy writes to the FAT. `r36os push`
    compares the whole card with this list; `r36os flash` assembles the image from it.
    Returns the BOOT list."""
    from r36os import manifests, r36s_vendor
    from r36os.archive import objects_dir
    from r36os.paths import ensure_dir
    from r36os.targets import IMAGES

    out = ensure_dir(out or target_out(IMAGES["console"]))
    ga36_out = ga36_out or target_out(TARGETS["ga36"])
    r36s_out = r36s_out or target_out(TARGETS["r36s"])
    files = console_boot_files(ga36_out, r36s_out, r36s_vendor.factory_boot_files())
    panel1 = ga36_out / "kernel" / PANEL1_SOURCE
    missing = [str(src) for src in [*files.values(), panel1] if not src.exists()]
    if missing:
        raise ConsoleImageError("a fragment build reuses the kernel, DTBs and slot sets of "
                                "the last `r36os build console`; missing: " + ", ".join(missing))
    check_soc_dtbs(files)
    check_console_boot({path: src.stat().st_size for path, src in files.items()})
    (out / VERSION_FILE).write_text(
        version.boot_version_file("console", v) + f"language: {language}\n")
    files = {**files, VERSION_FILE: out / VERSION_FILE}
    objects = objects_dir()
    # one read of each file: store_object hashes it and copies it only when it is new
    shas = {p: manifests.store_object(objects, src) for p, src in files.items()}
    area = (area_writer or bootarea.write_console_area)(out / "console-boot-area.bin")
    try:
        parts = {AREA_PART: manifests.store_object(objects, area),
                 PANEL1_PART: manifests.store_object(objects, panel1)}
    finally:
        area.unlink(missing_ok=True)
    manifests._write_atomic(out / IMAGE_PARTS, format_image_parts(parts))
    manifests.write_boot_list(out / BOOT_LIST, shas)
    return out / BOOT_LIST


def _console_script(files: dict[str, Path], volumes: dict[Path, str], version_src: str,
                    area_src: str, panel1_src: str) -> str:
    """The script that makes console.img and its BOOT list in /out (paths in the container)."""
    from r36os import vendor

    return _CONSOLE.format(
        **boot_copy_commands(files, volumes),
        version=version_src,
        boot_bytes=boot_sectors("console") * 512,
        boot_start=boot_start("console"),
        boot_sectors=boot_sectors("console"),
        image_bytes=(boot_start("console") + boot_sectors("console")) * 512,
        disk_id=disk_id("console"),
        min_free=BOOT_MIN_FREE,
        area_file=area_src,
        area_sectors=bootarea.AREA_SECTORS - 1,
        android=vendor.ANDROID_BOOT_SECTOR,
        panel1=panel1_src,
    )


# --- content-addressed archive (build-speed D10) ----------------------------------------
#
# Each file of BOOT is out/images/objects/<sha256>, stored once for every build that has it
# (boot-files.sha256 names them). The two pieces of the console image outside BOOT are
# objects too, named by image-parts.sha256 (same `<sha256>  <name>` lines): with both lists
# `flash` assembles the image of a build that has no .img.zst.

IMAGE_PARTS = "image-parts.sha256"
AREA_PART = "boot-area"                     # bootarea.write_console_area(), 128 MiB
PANEL1_PART = "android-boot-panel1"         # GA36 kernel boot image at sector 172032
PANEL1_SOURCE = "android-boot-panel1.img"   # in out/ga36/kernel/
VERSION_FILE = "VERSION"


def format_image_parts(parts: dict[str, str]) -> str:
    from r36os import manifests

    if set(parts) != {AREA_PART, PANEL1_PART}:
        raise manifests.ManifestError(f"{IMAGE_PARTS}: expected {AREA_PART} and "
                                      f"{PANEL1_PART}, got {sorted(parts)}")
    for name, sha in parts.items():
        manifests.object_path(Path("."), sha)           # checks the sha256
    return "".join(f"{parts[n]}  {n}\n" for n in (AREA_PART, PANEL1_PART))


def read_image_parts(path: Path) -> dict[str, str]:
    """name -> sha256 of the pieces of the image outside BOOT."""
    from r36os import manifests

    try:
        text = path.read_text()
    except FileNotFoundError:
        raise manifests.ManifestError(f"{path}: missing") from None
    parts = {}
    for n, line in enumerate(text.splitlines(), start=1):
        sha, sep, name = line.partition("  ")
        if not sep or name in parts:
            raise manifests.ManifestError(f"{path}: line {n}: not `<sha256>  <name>`")
        parts[name] = sha
    format_image_parts(parts)                           # same checks as the writer
    return parts


def store_build_objects(out: Path, files: dict[str, Path], parts: dict[str, Path]) -> None:
    """Store every file of out/boot-files.sha256 (BOOT path -> source in `files`) and the
    image `parts` in objects/, and write out/image-parts.sha256. A source that differs from
    what the FAT holds stops the build."""
    from r36os import manifests
    from r36os.archive import objects_dir

    objects = objects_dir()
    for path, sha in manifests.read_boot_list(out / BOOT_LIST):
        src = files.get(path)
        if src is None:
            raise ConsoleImageError(f"{path} is on BOOT but not in the files of the build")
        if manifests.store_object(objects, src) != sha:
            raise ConsoleImageError(f"{path} on the FAT differs from its source {src}")
    stored = {name: manifests.store_object(objects, src) for name, src in parts.items()}
    manifests._write_atomic(out / IMAGE_PARTS, format_image_parts(stored))


def assemble_console_image(build_dir: Path, dest: Path, runner=None) -> Path:
    """The card image of an archived console build, made again from its objects (for a
    build without .img.zst). The BOOT list read back from the new FAT must be the archived
    one."""
    import shutil

    from r36os import manifests
    from r36os.archive import objects_dir

    objects = objects_dir()
    boot_list = manifests.read_boot_list(build_dir / BOOT_LIST)
    parts = read_image_parts(build_dir / IMAGE_PARTS)
    missing = manifests.missing_objects(objects, [*boot_list, *parts.items()])
    if missing:
        raise ConsoleImageError(f"build {build_dir.name}: no object in {objects} for "
                                + ", ".join(missing))
    work = dest.parent / f"assemble-{build_dir.name}"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    volumes = {work: "/out", objects: "/obj"}
    files = {p: manifests.object_path(objects, sha) for p, sha in boot_list
             if p != VERSION_FILE}
    script = _console_script(files, volumes, f"/obj/{dict(boot_list)[VERSION_FILE]}",
                             f"/obj/{parts[AREA_PART]}", f"/obj/{parts[PANEL1_PART]}")
    try:
        if runner is not None:
            runner(volumes, script)
        else:
            Container(image=ensure_builder(TARGETS["vm"]), volumes=volumes).sh(script)
        built = manifests.read_boot_list(work / BOOT_LIST)
        if dict(built) != dict(boot_list):
            raise ConsoleImageError(f"the BOOT assembled from the objects of {build_dir.name} "
                                    f"differs from its {BOOT_LIST}")
        (work / "console.img").replace(dest)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return dest
