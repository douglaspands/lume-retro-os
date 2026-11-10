"""Stage 3: rootfs (apk --root), package manifest and the SYSTEM squashfs.

The rootfs comes out as `out/<target>/rootfs.tar` with numeric owners, so the host does
not have to deal with rootless podman sub-UID files. `SYSTEM` is built straight from the
tar (`mksquashfs -tar`).
"""

from __future__ import annotations

from pathlib import Path

from r36os import lang, leiame, pkglists, version
from r36os.container import ALPINE_VERSION, Container, ensure_builder
from r36os.packages import keys_dir
from r36os.paths import REPO_ROOT, ensure_dir, out_dir
from r36os.targets import TARGETS, Target

SYSTEM_LIMIT_MIB = 768
MIRROR = "https://dl-cdn.alpinelinux.org/alpine"


class SystemTooLargeError(RuntimeError):
    pass


def target_out(target: Target) -> Path:
    return out_dir() / target.name


def serial_console(target: Target) -> tuple[str, str]:
    tty, baud = (REPO_ROOT / "board" / target.name / "serial").read_text().split()
    return tty, baud


_ROOTFS_SCRIPT = """
R=/rootfs
mkdir -p $R/etc/apk
cp -a /etc/apk/keys $R/etc/apk/
cp /keys/r36os.rsa.pub $R/etc/apk/keys/
printf '%s/v{ver}/main\\n%s/v{ver}/community\\n' {mirror} {mirror} > $R/etc/apk/repositories
apk add --root $R --initdb --update-cache --no-progress \\
    --repositories-file $R/etc/apk/repositories -X /repo \\
    $(cat /work/packages.txt)

# Modules of the cross-compiled kernel (consoles, stage 1), with modules.dep
if [ -f /out/kernel/modules.tar ]; then tar -C $R -xf /out/kernel/modules.tar; fi

cp -a /overlay/. $R/
# Version of this build (D15): timestamp in BUILD_ID
if [ -f /work/os-release ]; then cp /work/os-release $R/etc/os-release; fi
# Factory menu language, chosen at build time (r36os build --lang)
cfg=$R/usr/share/r36os/retroarch-lume.cfg
sed -i 's/^user_language = .*/user_language = "{retro_lang}"/' $cfg
grep -qx 'user_language = "{retro_lang}"' $cfg
mkdir -p $R/etc/r36os
echo {lang} > $R/etc/r36os/language
cp /work/LEIA-ME.txt $R/usr/share/r36os/LEIA-ME.txt
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
mkdir -p $R/boot $R/storage

tar -C $R --numeric-owner --sort=name -cf /out/rootfs.tar .
"""


def build_rootfs(target: Target, v: version.BuildVersion | None = None,
                 language: str = lang.DEFAULT) -> Path:
    """Build the target rootfs; write rootfs.tar, manifest.txt and kernel/ to out/<target>/.

    With `v`, /etc/os-release carries the id of this build. `language` is the factory menu
    language (default English).
    """
    retro_lang = lang.retro_language(language)
    out = ensure_dir(target_out(target))
    work = ensure_dir(out / "work")
    osr = work / "os-release"
    osr.unlink(missing_ok=True)
    if v is not None:
        osr.write_text(version.os_release(v))
    (work / "packages.txt").write_text("\n".join(pkglists.all_packages(target)) + "\n")
    (work / "LEIA-ME.txt").write_text(leiame.render())
    tty, baud = serial_console(target)
    script = _ROOTFS_SCRIPT.format(
        ver=ALPINE_VERSION, mirror=MIRROR, tty=tty, baud=baud, arch=target.alpine_arch,
        board=target.name, lang=language, retro_lang=retro_lang,
    )
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
        f"mksquashfs - /out/{dest.name} -tar -comp zstd -Xcompression-level 19 "
        f"-b 256K -noappend -quiet -mkfs-time 0 -all-time 0 < {src}"
    )
    size = dest.stat().st_size
    if size > limit_mib * 1024 * 1024:
        dest.unlink()
        raise SystemTooLargeError(
            f"SYSTEM at {size / 2**20:.1f} MiB exceeds the {limit_mib} MiB limit"
        )
    return dest
