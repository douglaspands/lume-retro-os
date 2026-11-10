"""Archive of the built images (D15): each build goes to out/images/<target>/<timestamp>/.

    out/images/ga36/20261109-214233/
      ga36-20261109-214233.img.zst   card image, compressed (zstd)
      manifest.txt                   rootfs packages and versions
      build.json                     timestamp, commit, kernel, bootloader, Alpine, sizes
      SHA256SUMS                     of the uncompressed image and of the .zst
    out/images/ga36/latest -> 20261109-214233

Write it to a card: `uv run r36os flash <target> /dev/sdX`.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from r36os.paths import ensure_dir, out_dir
from r36os.targets import Target
from r36os.version import BuildVersion

CHUNK = 1 << 22  # 4 MiB


def images_dir(target: Target) -> Path:
    return out_dir() / "images" / target.name


def _compress(src: Path, dest: Path) -> tuple[str, str]:
    """Compress with zstd; return (sha256 of the original, sha256 of the .zst)."""
    from compression import zstd

    h_raw, h_zst = hashlib.sha256(), hashlib.sha256()
    tmp = dest.with_suffix(dest.suffix + ".part")
    with src.open("rb") as fin, zstd.open(tmp, "wb", level=10) as fout:
        while chunk := fin.read(CHUNK):
            h_raw.update(chunk)
            fout.write(chunk)
    with tmp.open("rb") as f:
        while chunk := f.read(CHUNK):
            h_zst.update(chunk)
    tmp.replace(dest)
    return h_raw.hexdigest(), h_zst.hexdigest()


def archive_image(target: Target, img: Path, v: BuildVersion, info: dict | None = None) -> Path:
    """Keep the image of this build with its manifest, build.json and sums; update `latest`."""
    dest = ensure_dir(images_dir(target) / v.build_id)
    name = f"{target.name}-{v.build_id}.img"
    sha_raw, sha_zst = _compress(img, dest / f"{name}.zst")
    manifest = img.parent / "manifest.txt"
    if manifest.exists():
        shutil.copy(manifest, dest / "manifest.txt")
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
    (dest / "SHA256SUMS").write_text(f"{sha_raw}  {name}\n{sha_zst}  {name}.zst\n")
    latest = images_dir(target) / "latest"
    latest.unlink(missing_ok=True)
    latest.symlink_to(v.build_id)
    return dest
