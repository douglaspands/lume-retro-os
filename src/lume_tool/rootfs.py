"""Stage 3: rootfs (apk --root), package manifest and the SYSTEM squashfs.

The rootfs comes out as `out/<target>/rootfs.tar` with numeric owners, so the host does
not have to deal with rootless podman sub-UID files. `SYSTEM` is built straight from the
tar (`mksquashfs -tar`).
"""

from __future__ import annotations

from pathlib import Path

from lume_tool import catalog, jobs, lang, leiame, pkglists, version
from lume_tool.container import ALPINE_VERSION, Container, ensure_builder
from lume_tool.packages import keys_dir
from lume_tool.paths import REPO_ROOT, ensure_dir, out_dir
from lume_tool.targets import TARGETS, Target

SYSTEM_LIMIT_MIB = 768
# On the console image both systems share the 2 GiB BOOT (r36s-single-card, system-image)
CONSOLE_SYSTEM_LIMIT_MIB = 448
MIRROR = "https://dl-cdn.alpinelinux.org/alpine"
# mksquashfs options of SYSTEM (an input of its stage; -processors does not change the file)
SQUASHFS_OPTIONS = ("-comp zstd -Xcompression-level 19 -b 256K -noappend -quiet "
                    "-mkfs-time 0 -all-time 0")


class SystemTooLargeError(RuntimeError):
    pass


def target_out(target: Target) -> Path:
    return out_dir() / target.name


def system_limit_mib(target: Target) -> int:
    """Size limit of the SYSTEM of a hardware layer."""
    return CONSOLE_SYSTEM_LIMIT_MIB if target.is_console else SYSTEM_LIMIT_MIB


def serial_console(target: Target) -> tuple[str, str]:
    tty, baud = (REPO_ROOT / "board" / target.name / "serial").read_text().split()
    return tty, baud


_ROOTFS_SCRIPT = """
R=/rootfs
mkdir -p $R/etc/apk
cp -a /etc/apk/keys $R/etc/apk/
cp /keys/lume.rsa.pub $R/etc/apk/keys/
printf '%s/v{ver}/main\\n%s/v{ver}/community\\n' {mirror} {mirror} > $R/etc/apk/repositories
apk add --root $R --initdb --update-cache --no-progress \\
    --repositories-file $R/etc/apk/repositories -X /repo \\
    $(cat /work/packages.txt)

# Mount point of the console modules image (BOOT/<console>/modules, kernel-modules-image
# D3): the modules of the cross-compiled kernel stay out of SYSTEM, so a kernel-only change
# does not change it. The VM gets its modules from the packaged kernel.
mkdir -p $R/lib/modules

cp -a /overlay/. $R/
# System version (D15); the build id stays in BOOT/VERSION, so SYSTEM does not change
if [ -f /work/os-release ]; then cp /work/os-release $R/etc/os-release; fi
# Factory menu language, chosen at build time (lume build --lang)
cfg=$R/usr/share/lume/factory/retroarch/retroarch.cfg
sed -i 's/^user_language = .*/user_language = "{retro_lang}"/' $cfg
grep -qx 'user_language = "{retro_lang}"' $cfg
mkdir -p $R/etc/lume
echo {lang} > $R/etc/lume/language
cp /work/LEIA-ME.txt $R/usr/share/lume/LEIA-ME.txt
cp /configure.sh $R/tmp/configure.sh
chroot $R /bin/sh /tmp/configure.sh {tty} {baud} {board}
rm -f $R/tmp/configure.sh

# Manifest: name and version of each installed package, sorted.
{{
  echo "# arch: {arch}"
  awk -F: '/^P:/{{p=$2}} /^V:/{{print p, $2}}' $R/lib/apk/db/installed | sort
}} > /out/manifest.txt

# Packaged kernel (VM only): it goes to BOOT, not to SYSTEM. On the consoles out/kernel/
# belongs to stage 1 and is left alone.
if [ -n "$(ls $R/boot 2>/dev/null)" ]; then
  rm -rf /out/kernel && mkdir -p /out/kernel && cp -a $R/boot/. /out/kernel/
fi
rm -rf $R/boot/* $R/var/cache/apk/*
# Nothing that changes from one build to the next with the same packages, so that SYSTEM
# comes out the same and `lume push` skips it: the apk log (install times) and the
# machine-id made at install (random; every card shared it). The machine-id and dbus
# services make one at boot when it is missing.
rm -f $R/var/log/apk.log $R/etc/machine-id $R/var/lib/dbus/machine-id
mkdir -p $R/boot $R/storage

tar -C $R --numeric-owner --sort=name -cf /out/rootfs.tar .
"""


def _rootfs_script(target: Target, language: str) -> str:
    tty, baud = serial_console(target)
    return _ROOTFS_SCRIPT.format(
        ver=ALPINE_VERSION, mirror=MIRROR, tty=tty, baud=baud, arch=target.alpine_arch,
        board=target.name, lang=language, retro_lang=lang.retro_language(language),
    )


def stage_inputs(target: Target, v: version.BuildVersion | None, language: str):
    """Inputs of the rootfs stage (build-speed D6); the build id is never one of them."""
    from lume_tool import stage_inputs

    return stage_inputs.rootfs_inputs(
        target, _rootfs_script(target, language), pkglists.all_packages(target), language,
        version.os_release() if v is not None else "", leiame.render(),
        stage_inputs.mirror_index_hash(ALPINE_VERSION, MIRROR, target.alpine_arch))


def build_rootfs(target: Target, v: version.BuildVersion | None = None,
                 language: str = lang.DEFAULT) -> Path:
    """Build the target rootfs; write rootfs.tar, manifest.txt and kernel/ to out/<target>/.

    With `v`, /etc/os-release is the Lume one (the system version; the build id stays in
    BOOT/VERSION). `language` is the factory menu language (default English).
    """
    retro_lang = lang.retro_language(language)
    out = ensure_dir(target_out(target))
    work = ensure_dir(out / "work")
    osr = work / "os-release"
    osr.unlink(missing_ok=True)
    if v is not None:
        osr.write_text(version.os_release())
    (work / "packages.txt").write_text("\n".join(pkglists.all_packages(target)) + "\n")
    # The catalog and the launcher runners of the image are checked before any build step
    # (game-library: an emulator citing a missing runner stops the build)
    errs = catalog.validate(catalog.load())
    if errs:
        raise RuntimeError("invalid catalog: " + "; ".join(errs))
    (work / "LEIA-ME.txt").write_text(leiame.render())
    script = _rootfs_script(target, language)
    Container(
        image=ensure_builder(target),
        platform=target.oci_platform,
        volumes={
            out: "/out",
            work: "/work",
            out_dir() / "repo": "/repo",
            keys_dir(): "/keys",
            REPO_ROOT / "rootfs/overlay": "/overlay",
            REPO_ROOT / "rootfs/configure.sh": "/configure.sh",
        },
    ).sh(script)
    return out / "rootfs.tar"


def read_manifest(path: Path) -> dict[str, str]:
    pkgs = {}
    for line in path.read_text().splitlines():
        if line and not line.startswith("#"):
            name, ver = line.split()
            pkgs[name] = ver
    return pkgs


def make_system(target: Target, rootfs_tar: Path, dest: Path,
                limit_mib: int = SYSTEM_LIMIT_MIB) -> Path:
    """Build the `SYSTEM` squashfs (zstd) from the tar; fail above the limit."""
    ensure_dir(dest.parent)
    volumes = {dest.parent: "/out"}
    src = f"/out/{rootfs_tar.name}"
    if rootfs_tar.parent.resolve() != dest.parent.resolve():
        volumes[rootfs_tar.parent] = "/in"
        src = f"/in/{rootfs_tar.name}"
    # mksquashfs does not depend on the target arch: always the x86_64 builder.
    Container(image=ensure_builder(TARGETS["vm"]), volumes=volumes).sh(
        f"mksquashfs - /out/{dest.name} -tar {SQUASHFS_OPTIONS} "
        f"-processors {jobs.jobs()} < {src}"
    )
    size = dest.stat().st_size
    if size > limit_mib * 1024 * 1024:
        dest.unlink()
        raise SystemTooLargeError(
            f"SYSTEM at {size / 2**20:.1f} MiB exceeds the {limit_mib} MiB limit"
        )
    return dest


# The modules image of a console (kernel-modules-image D1, D2): the content of lib/modules/
# at the root (one <release>/ folder), owned by root, with no build times, so the same
# modules.tar always gives the same file. Same compression as SYSTEM.
MODULES_SCRIPT = """
rm -rf /tmp/m
mkdir -p /tmp/m
tar -C /tmp/m -xf {src}
tar -C /tmp/m/lib/modules --numeric-owner --owner=0 --group=0 --sort=name -cf /tmp/modules.tar .
mksquashfs - /out/{dest} -tar -comp zstd -Xcompression-level 19 \\
    -b 256K -noappend -quiet -mkfs-time 0 -all-time 0 -processors {jobs} < /tmp/modules.tar
"""


def make_modules_image(modules_tar: Path, dest: Path) -> Path:
    """Build the console modules squashfs `dest` from the kernel modules.tar
    (`lib/modules/<release>/...`), with the `lib/modules/` prefix taken off."""
    ensure_dir(dest.parent)
    # one volume when both are in the same folder (out/<console>/kernel/): a dict with the
    # same path twice keeps only one of the mounts
    volumes = {dest.parent: "/out"}
    src = f"/out/{modules_tar.name}"
    if modules_tar.parent.resolve() != dest.parent.resolve():
        volumes[modules_tar.parent] = "/in"
        src = f"/in/{modules_tar.name}"
    # mksquashfs does not depend on the target arch: always the x86_64 builder.
    Container(image=ensure_builder(TARGETS["vm"]), volumes=volumes).sh(
        MODULES_SCRIPT.format(src=src, dest=dest.name, jobs=jobs.jobs()))
    return dest
