"""Estágio 3: rootfs (apk --root), manifesto de pacotes e SYSTEM squashfs.

O rootfs sai como `out/<alvo>/rootfs.tar` com donos numéricos, para o host não
precisar lidar com arquivos de sub-UIDs do podman rootless. O `SYSTEM` é gerado
direto do tar (`mksquashfs -tar`).
"""

from __future__ import annotations

from pathlib import Path

from r36os import leiame, pkglists
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

cp -a /overlay/. $R/
cp /work/LEIA-ME.txt $R/usr/share/r36os/LEIA-ME.txt
cp /configure.sh $R/tmp/configure.sh
chroot $R /bin/sh /tmp/configure.sh {tty} {baud} {board}
rm -f $R/tmp/configure.sh

# Manifesto: nome e versão de cada pacote instalado, ordenado.
{{
  echo "# arch: {arch}"
  awk -F: '/^P:/{{p=$2}} /^V:/{{print p, $2}}' $R/lib/apk/db/installed | sort
}} > /out/manifest.txt

# Kernel do pacote (só VM): vai para a BOOT, não para o SYSTEM.
rm -rf /out/kernel && mkdir -p /out/kernel
if [ -n "$(ls $R/boot 2>/dev/null)" ]; then cp -a $R/boot/. /out/kernel/; fi
rm -rf $R/boot/* $R/var/cache/apk/*
mkdir -p $R/boot $R/storage

tar -C $R --numeric-owner --sort=name -cf /out/rootfs.tar .
"""


def build_rootfs(target: Target) -> Path:
    """Monta o rootfs do alvo; gera rootfs.tar, manifest.txt e kernel/ em out/<alvo>/."""
    out = ensure_dir(target_out(target))
    work = ensure_dir(out / "work")
    (work / "packages.txt").write_text("\n".join(pkglists.all_packages(target)) + "\n")
    (work / "LEIA-ME.txt").write_text(leiame.render())
    tty, baud = serial_console(target)
    script = _ROOTFS_SCRIPT.format(
        ver=ALPINE_VERSION, mirror=MIRROR, tty=tty, baud=baud, arch=target.alpine_arch,
        board=target.name,
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
    """Gera o squashfs `SYSTEM` (zstd) a partir do tar; falha acima do limite."""
    ensure_dir(dest.parent)
    volumes = {dest.parent: "/out"}
    src = f"/out/{rootfs_tar.name}"
    if rootfs_tar.parent.resolve() != dest.parent.resolve():
        volumes[rootfs_tar.parent] = "/in"
        src = f"/in/{rootfs_tar.name}"
    # mksquashfs não depende do arch alvo: usa sempre o builder x86_64.
    Container(image=ensure_builder(TARGETS["vm"]), volumes=volumes).sh(
        f"mksquashfs - /out/{dest.name} -tar -comp zstd -Xcompression-level 19 "
        f"-b 256K -noappend -quiet -mkfs-time 0 -all-time 0 < {src}"
    )
    size = dest.stat().st_size
    if size > limit_mib * 1024 * 1024:
        dest.unlink()
        raise SystemTooLargeError(
            f"SYSTEM com {size / 2**20:.1f} MiB passa do limite de {limit_mib} MiB"
        )
    return dest
