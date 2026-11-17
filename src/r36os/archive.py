"""Archive of the built images (D15): each build goes to out/images/<image>/<timestamp>/.

    out/images/console/20261109-214233/
      console-20261109-214233.img.zst  card image, compressed (zstd)
      manifest-ga36.txt                rootfs packages and versions of each system
      manifest-r36s.txt                (the vm has a single manifest.txt)
      build.json                       timestamp, commit, layers (kernel, patches, slots of
                                       a console or SYSTEM size of the vm), bootloaders,
                                       Alpine, sizes
      SHA256SUMS                       of the uncompressed image and of the .zst
      boot-files.sha256                console: every file of BOOT with its SHA256, read
                                       back from the FAT, VERSION last (r36os push)
      image-parts.sha256               console: the boot area and the GA36 panel 1 boot
                                       image (the image outside BOOT), by SHA256
    out/images/console/latest -> 20261109-214233
    out/images/objects/<sha256>        each file of BOOT and each image part, once for every
                                       build that has it (build-speed D10)

`r36os push` reads the files it sends from objects/ (no unpacking); `r36os flash` writes the
.img.zst, or assembles the image from the objects of a build that has none. `r36os clean`
deletes the objects no kept build cites.

Write it to a card: `uv run r36os flash <image> /dev/sdX`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from r36os.paths import ensure_dir, out_dir
from r36os.targets import ImageTarget, Target
from r36os.version import BuildVersion

CHUNK = 1 << 22  # 4 MiB


def images_dir(target: ImageTarget | Target) -> Path:
    return out_dir() / "images" / target.name


def objects_dir() -> Path:
    """out/images/objects/: the files of every archived build, by SHA256 (D10)."""
    from r36os.manifests import OBJECTS_DIR

    return out_dir() / "images" / OBJECTS_DIR


def _compress(src: Path, dest: Path) -> tuple[str, str]:
    """Compress with zstd; return (sha256 of the original, sha256 of the .zst)."""
    from compression import zstd

    from r36os import jobs

    h_raw, h_zst = hashlib.sha256(), hashlib.sha256()
    tmp = dest.with_suffix(dest.suffix + ".part")
    # nb_workers = the build's jobs (zstd -T)
    # (level and options are exclusive: the level goes in the options)
    opts = {zstd.CompressionParameter.compression_level: 10,
            zstd.CompressionParameter.nb_workers: jobs.jobs()}
    with src.open("rb") as fin, zstd.open(tmp, "wb", options=opts) as fout:
        while chunk := fin.read(CHUNK):
            h_raw.update(chunk)
            fout.write(chunk)
    with tmp.open("rb") as f:
        while chunk := f.read(CHUNK):
            h_zst.update(chunk)
    tmp.replace(dest)
    return h_raw.hexdigest(), h_zst.hexdigest()


def archive_image(target: ImageTarget | Target, img: Path, v: BuildVersion,
                  info: dict | None = None, manifests: dict[str, Path] | None = None,
                  extras: dict[str, Path] | None = None) -> Path:
    """Keep the image of this build with its manifests, build.json and sums; update `latest`.

    `manifests` maps the archived name to the manifest of each system (default: the
    manifest.txt next to the image). `extras` maps the archived name to other files of the
    build kept next to the image (the GA36 panel boot images), listed in SHA256SUMS.
    """
    dest = ensure_dir(images_dir(target) / v.build_id)
    name = f"{target.name}-{v.build_id}.img"
    sha_raw, sha_zst = _compress(img, dest / f"{name}.zst")
    if manifests is None:
        manifests = {"manifest.txt": img.parent / "manifest.txt"}
    for archived, manifest in manifests.items():
        if manifest.exists():
            shutil.copy(manifest, dest / archived)
    build = {
        "target": target.name,
        **v.as_dict(),
        "image": name,
        "image_bytes": img.stat().st_size,
        "image_sha256": sha_raw,
        "zst_bytes": (dest / f"{name}.zst").stat().st_size,
        **(info or {}),
    }
    (dest / "build.json").write_text(json.dumps(build, indent=2, ensure_ascii=False) + "\n")
    sums = f"{sha_raw}  {name}\n{sha_zst}  {name}.zst\n"
    extras = dict(extras or {})
    # the console image parts in objects/ (image.store_build_objects), for flash (D10)
    parts = img.parent / "image-parts.sha256"
    if parts.exists():
        extras.setdefault(parts.name, parts)
    _finish(target, v, dest, sums, extras)
    return dest


def archive_set(target: ImageTarget, v: BuildVersion, info: dict,
                manifests: dict[str, Path], extras: dict[str, Path]) -> Path:
    """Keep a console build without an image (fragment build, build-speed 6.2): no
    .img.zst, its BOOT list and image parts (in `extras`, the files already in objects/),
    the manifests and build.json (`image` null); update `latest`. `r36os push` sends it,
    `r36os flash` assembles its image from the objects."""
    dest = ensure_dir(images_dir(target) / v.build_id)
    for archived, manifest in manifests.items():
        if manifest.exists():
            shutil.copy(manifest, dest / archived)
    build = {"target": target.name, **v.as_dict(), "image": None, **info}
    (dest / "build.json").write_text(json.dumps(build, indent=2, ensure_ascii=False) + "\n")
    _finish(target, v, dest, "", dict(extras))
    return dest


def _finish(target, v: BuildVersion, dest: Path, sums: str, extras: dict[str, Path]) -> None:
    """Copy the extras (listed in SHA256SUMS) and point `latest` at this build."""
    for archived, src in sorted(extras.items()):
        shutil.copy(src, dest / archived)
        sums += f"{hashlib.sha256((dest / archived).read_bytes()).hexdigest()}  {archived}\n"
    (dest / "SHA256SUMS").write_text(sums)
    latest = images_dir(target) / "latest"
    latest.unlink(missing_ok=True)
    latest.symlink_to(v.build_id)
