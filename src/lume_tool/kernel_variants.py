"""Experiment kernels of a console (device-fixes 6.3, D12, D13):
`lume build --console ga36 kernel --variant <name>`.

A variant is `kernel/variants/<board>/<name>/`:

- `*.patch`: kernel patches applied after `kernel/patches/`, in name order;
- `board.dtsi` (optional): DTS overrides included at the end of every `board/<board>/dts/*.dts`;
- `variant.toml`: `description`, and `video_refresh_rate` when the variant changes the panel
  mode (RetroArch must get that rate while the variant runs; the default one is in
  retroarch-<board>.cfg).

It never enters the default image:

- the kernel is compiled in the default source tree and build folder (the next default build
  moves the tree back and recompiles only the files the variant touched), but the outputs go
  to out/<board>/variants/<name>/ and nothing is published to out/repo/: lume-kernel,
  lume-dtbs and lume-modules keep the default kernel for every later build;
- a variant may only patch drivers built into the kernel image (BUILTIN_FILES), so the
  modules of the default build stay valid and are not sent;
- the console build it archives is the base build (`latest`, whose kernel must be the one in
  out/<board>/kernel-pkg/) with only the kernel image, the board's DTBs, VERSION and the
  panel boot images replaced, and `latest` stays on the base build.

Sent with `lume push --console <board> --build <id>`; undone with `lume push --console
<board>` (latest is the base build): the push sends the default kernel and the boot image
of sector 172032 back.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import tomllib
from dataclasses import dataclass
from pathlib import Path

from lume_tool.paths import REPO_ROOT, ensure_dir

VARIANTS_DIR = REPO_ROOT / "kernel/variants"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
DTSI_NAME = "board.dtsi"
STAGED_DTSI = "lume-variant.dtsi"
VARIANTS_OUT = "variants"            # out/<board>/variants/<name>/
KIND = "kernel-variant"              # build.json "kind"
# Files an experiment may patch, with the option that builds each into the kernel image (a
# patched module would need the modules image too, which a variant never sends)
BUILTIN_FILES = {
    "drivers/gpu/drm/panel/panel-ga36mb-jd9366.c": "CONFIG_DRM_PANEL_GA36MB_JD9366",
    "drivers/gpu/drm/sun4i/sun6i_mipi_dsi.c": "CONFIG_DRM_SUN6I_DSI",
}


class VariantError(ValueError):
    """An experiment kernel that cannot be built (unknown, malformed, no base build)."""


@dataclass(frozen=True)
class Variant:
    board: str
    name: str
    path: Path
    description: str
    patches: tuple[Path, ...]
    dtsi: Path | None
    video_refresh_rate: str | None

    def as_dict(self) -> dict:
        return {"board": self.board, "name": self.name, "description": self.description,
                "patches": [p.name for p in self.patches], "dts": self.dtsi is not None,
                "video_refresh_rate": self.video_refresh_rate}


def available(board: str, root: Path | None = None) -> list[str]:
    """Names of the variants of `board`."""
    base = (root or VARIANTS_DIR) / board
    return sorted(p.name for p in base.iterdir() if p.is_dir()) if base.is_dir() else []


def touched_files(patch: Path) -> set[str]:
    """Paths a patch changes (its `+++ b/<path>` lines; a deleted file by `--- a/`)."""
    out = set()
    for line in patch.read_text().splitlines():
        if line.startswith("+++ b/"):
            out.add(line[6:].split("\t")[0])
        elif line.startswith("--- a/"):
            out.add(line[6:].split("\t")[0])
    return out


def load(board: str, name: str, root: Path | None = None) -> Variant:
    """The variant `name` of `board`, checked (see the module doc)."""
    if not NAME_RE.match(name):
        raise VariantError(f"bad variant name {name!r}")
    path = (root or VARIANTS_DIR) / board / name
    if not path.is_dir():
        known = ", ".join(available(board, root)) or "none"
        raise VariantError(f"no experiment kernel {name!r} for the {board} (known: {known})")
    try:
        meta = tomllib.loads((path / "variant.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise VariantError(f"{path}/variant.toml: {e}") from None
    unknown = set(meta) - {"description", "video_refresh_rate"}
    if unknown or not isinstance(meta.get("description"), str):
        raise VariantError(f"{path}/variant.toml: needs a description, and only "
                           f"description and video_refresh_rate (got {sorted(meta)})")
    rate = meta.get("video_refresh_rate")
    if rate is not None and not re.fullmatch(r"\d{2}\.\d{6}", str(rate)):
        raise VariantError(f"{path}/variant.toml: video_refresh_rate {rate!r} is not "
                           "a string like \"60.013430\"")
    patches = tuple(sorted(path.glob("*.patch")))
    for p in patches:
        outside = sorted(touched_files(p) - set(BUILTIN_FILES))
        if outside:
            raise VariantError(f"{p.name} patches {', '.join(outside)}: an experiment kernel "
                               "may only patch " + ", ".join(sorted(BUILTIN_FILES)))
    dtsi = path / DTSI_NAME if (path / DTSI_NAME).is_file() else None
    extra = sorted(f.name for f in path.iterdir()
                   if f.name not in {"variant.toml", DTSI_NAME} and f.suffix != ".patch")
    if extra:
        raise VariantError(f"{path}: unexpected files {', '.join(extra)}")
    if not patches and dtsi is None:
        raise VariantError(f"{path}: no *.patch and no {DTSI_NAME}: nothing to try")
    return Variant(board, name, path, meta["description"], patches, dtsi, rate)


def stage_dts(src: Path, dtsi: Path, dest: Path) -> Path:
    """Copy the board DTS folder to `dest` and include `dtsi` at the end of every .dts."""
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest)
    shutil.copyfile(dtsi, dest / STAGED_DTSI)
    for dts in sorted(dest.glob("*.dts")):
        text = dts.read_text()
        dts.write_text(text + ("" if text.endswith("\n") else "\n")
                       + f"\n/* experiment kernel (lume_tool.kernel_variants) */\n"
                         f"#include \"{STAGED_DTSI}\"\n")
    return dest


def replace_boot_files(base: list[tuple[str, str]], new: dict[str, str]) -> dict[str, str]:
    """The base BOOT list (path, sha256) with the shas of `new` (BOOT path -> sha256).
    Every replaced path must already be in the base (a variant adds no file to BOOT), and
    VERSION must be among the new ones."""
    from lume_tool import manifests

    files = dict(base)
    missing = sorted(set(new) - set(files))
    if missing:
        raise VariantError(f"the base build has no {', '.join(missing)}")
    if manifests.VERSION_FILE not in new:
        raise VariantError("an experiment build needs its own VERSION")
    files.update(new)
    return files


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def build_variant(board: str, name: str) -> Path:
    """Build the experiment kernel `name` of `board` and archive it as a console build that
    does not move `latest`. Returns the archived build folder."""
    from lume_tool import bootimg, build, image, kernel, kernel_packages, manifests, version
    from lume_tool.archive import archive_set, images_dir, objects_dir
    from lume_tool.rootfs import target_out
    from lume_tool.targets import IMAGES, TARGETS

    if board not in build.ANDROID_BOOT:
        raise VariantError(f"experiment kernels are only for the "
                           f"{', '.join(sorted(build.ANDROID_BOOT))}")
    variant = load(board, name)
    console = IMAGES["console"]
    latest = images_dir(console) / "latest"
    if not latest.is_symlink():
        raise VariantError("no console build yet: run `lume build --console "
                           f"{board} kernel` (the control) first")
    base_dir = latest.resolve()
    base_list = image.read_boot_list(base_dir / image.BOOT_LIST)
    base_info = json.loads((base_dir / "build.json").read_text())
    if base_info.get("kind") == KIND:
        raise VariantError(f"latest ({base_dir.name}) is an experiment kernel")
    layer_out = target_out(TARGETS[board])
    default = kernel_packages.boot_sources(board, layer_out)
    image_path = f"{board}/{kernel_packages.image_name(board)}"
    if dict(base_list).get(image_path) != _sha256(default[image_path]):
        raise VariantError(
            f"the kernel of latest ({base_dir.name}) is not the one in {layer_out}/"
            f"{kernel_packages.PKG_DIR}: run `lume build --console {board} kernel` first")

    vout = ensure_dir(layer_out / VARIANTS_OUT / name)
    soc = image.SOC_DIR[board]
    arch, vendor = build.DTS_VENDOR[board]
    print(f"experiment kernel {board}/{name}: {variant.description}", flush=True)
    with kernel.extra_patches(list(variant.patches)):
        if variant.patches:
            zimage = kernel.build_kernel(board, vout / "kernel", initramfs_dir=layer_out)
        else:
            zimage = default[image_path]         # only the DTBs change
        dtbs = {p: src for p, src in default.items()
                if p.startswith(f"dtbs/{soc}/") and p.count("/") == 2}
        if variant.dtsi is not None:
            staged = stage_dts(REPO_ROOT / "board" / board / "dts", variant.dtsi, vout / "dts")
            kernel.build_dtbs(board, arch, vendor, vout / "dtbs", dts_dir=staged)
            dtbs = {f"dtbs/{soc}/{p.name}": p for p in sorted((vout / "dtbs").glob("*.dtb"))}
    for panel, dtb in build.ANDROID_BOOT[board].items():
        blob = zimage.read_bytes() + dtbs[f"dtbs/{soc}/{dtb}"].read_bytes()
        (vout / f"android-boot-{panel}.img").write_bytes(bootimg.make(blob))

    v = version.current()
    language = base_info.get("language") or "en"
    (vout / manifests.VERSION_FILE).write_text(
        version.boot_version_file("console", v) + f"language: {language}\n"
        f"kernel variant: {board} {name} (base {base_dir.name})\n")
    objects = objects_dir()
    new = {image_path: manifests.store_object(objects, zimage),
           manifests.VERSION_FILE: manifests.store_object(objects, vout / manifests.VERSION_FILE)}
    if variant.dtsi is not None:
        new.update({p: manifests.store_object(objects, src) for p, src in dtbs.items()})
    manifests.write_boot_list(vout / image.BOOT_LIST, replace_boot_files(base_list, new))
    parts = image.read_image_parts(base_dir / image.IMAGE_PARTS)
    parts[image.PANEL1_PART] = manifests.store_object(objects, vout / image.PANEL1_SOURCE)
    manifests._write_atomic(vout / image.IMAGE_PARTS, image.format_image_parts(parts))

    info = {k: base_info[k] for k in ("alpine", "layers", "bootloaders") if k in base_info}
    info.update(kind=KIND, base=base_dir.name, language=language, variant=variant.as_dict())
    manifest_files = {p.name: p for p in sorted(base_dir.glob("manifest*.txt"))}
    extras = {image.BOOT_LIST: vout / image.BOOT_LIST,
              image.IMAGE_PARTS: vout / image.IMAGE_PARTS}
    extras.update({f"{board}-android-boot-{panel}.img": vout / f"android-boot-{panel}.img"
                   for panel in build.ANDROID_BOOT[board]})
    dest = archive_set(console, v, info, manifest_files, extras, latest=False)
    print(f"ok: experiment kernel {board}/{name} in build {v.build_id} (latest stays "
          f"{base_dir.name})\n"
          f"archived: {dest}\n"
          f"send it with: lume push --console {board} --build {v.build_id}\n"
          f"undo with:    lume push --console {board}   (latest, {base_dir.name})", flush=True)
    if variant.video_refresh_rate:
        print("RetroArch rate for this kernel (until the next boot): lume dev sh --console "
              f"{board} 'echo video_refresh_rate = \\\"{variant.video_refresh_rate}\\\" > "
              "/run/lume/retroarch-extra.cfg'", flush=True)
    return dest
