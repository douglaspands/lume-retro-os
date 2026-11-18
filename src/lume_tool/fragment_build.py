"""Fragment build (build-speed task 6.2): `lume build <fragment>... [--console ga36|r36s]`.

A fragment is a local aport (aports/<name>/). The build compiles only the requested
fragments and the local aports that build-depend on them, redoes the root of the consoles
they reach (rootfs, then only the slots whose content changed) and writes a new console
build without an image: the BOOT list and objects of the content-addressed archive (4.3),
ready for `lume push`. `lume build console` keeps making the full image.

The plan (pure, unit tested):

- consoles: a noarch fragment reaches both consoles, an arch fragment the consoles whose
  architecture its APKBUILD builds for; `--console` keeps only that one. A fragment that
  reaches none of them is refused (mesa is x86_64 only, a disabled aport has arch="").
- packages: per console, the requested fragments that build for its arch and, transitively,
  every local aport of that arch whose makedepends name one of them (or a subpackage,
  `mesa-dev` -> mesa); in build order. The noarch ones are built once, before the consoles.
  Each is still compiled only when its inputs changed and published only when its content
  changed (task 6.1).
- slots: per console, the overlay slots of the packages' groups (rootfs/slots.toml), plus
  `lume`, where the apk database lives. The slot stage packs again only the slots whose
  content changed and reports a slot outside the plan (an Alpine update, say).
- stage 1: a fragment the initramfs installs is built into the kernel, so the plan redoes
  the initramfs and the kernel of that console (STAGE1_FRAGMENTS). `kernel` (or lume-kernel,
  lume-modules, lume-dtbs; KERNEL_FRAGMENTS, task 7.3) asks for stage 1 alone: the kernel,
  its modules image and the DTBs of the consoles asked, no package.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from lume_tool import fragments as frag
from lume_tool.manifests import OVERLAY_SLOTS
from lume_tool.paths import REPO_ROOT
from lume_tool.targets import IMAGES, TARGETS

CONSOLES = IMAGES["console"].layers        # ("ga36", "r36s")
TOP_SLOT = "lume"                          # the apk database: changes with any package

# Fragments of stage 1: the initramfs installs them (initramfs.py, `apk add ...
# lume-initramfs-static lume-bootsel`) and is built into the console kernel, so a change
# needs the initramfs and the kernel again. Extension point of task 7.3: the kernel,
# modules and DTB fragments (lume-kernel...) join this set.
STAGE1_FRAGMENTS = frozenset({"lume-initramfs-static", "lume-bootsel"})
# The kernel of a console as a fragment (task 7.3; the user, 2026-11-17: a driver or a kernel
# patch without the whole image): not an aport. It redoes stage 1 of the consoles asked (the
# kernel builds only what changed in its tree), publishes lume-kernel, lume-modules and
# lume-dtbs when their content changed, and the push sends only the boot files that differ.
KERNEL_FRAGMENTS = frozenset({"kernel", "lume-kernel", "lume-modules", "lume-dtbs"})


class FragmentPlanError(ValueError):
    """Fragments the build cannot plan (unknown, on no console, a name of an image)."""


@dataclass(frozen=True)
class Aport:
    name: str
    arches: tuple[str, ...]
    build_deps: tuple[str, ...]
    packages: tuple[str, ...]      # pkgname and subpackages (only the name when computed)

    @property
    def noarch(self) -> bool:
        return self.arches == ("noarch",)

    def builds_for(self, arch: str) -> bool:
        if f"!{arch}" in self.arches:
            return False
        return any(a in ("all", "noarch", arch) for a in self.arches)


def read_aports(aports_dir: Path | None = None) -> dict[str, Aport]:
    """The local aports by name (each subdirectory with an APKBUILD), sorted."""
    from lume_tool.packages import aport_arches

    aports_dir = aports_dir or REPO_ROOT / "aports"
    out = {}
    for apkbuild in sorted(aports_dir.glob("*/APKBUILD")):
        name = apkbuild.parent.name
        text = apkbuild.read_text()
        out[name] = Aport(name=name, arches=tuple(aport_arches(apkbuild)),
                          build_deps=tuple(frag.build_deps(text)),
                          packages=tuple(frag.apkbuild_packages(text, str(apkbuild))
                                         or [name]))
    return out


def _origin(dep: str, names) -> str | None:
    """The aport of `names` that makes the package `dep` (itself or `<aport>-<sub>`)."""
    if dep in names:
        return dep
    cands = [n for n in names if dep.startswith(n + "-")]
    return max(cands, key=len) if cands else None


def with_reverse_deps(aports: dict[str, Aport], seeds: list[str],
                      candidates: list[str]) -> list[str]:
    """`seeds` and every aport of `candidates` that build-depends on one of them, directly
    or through another, in build order (each dependency before its users)."""
    chosen = list(dict.fromkeys(seeds))
    changed = True
    while changed:
        changed = False
        for c in candidates:
            if c in chosen:
                continue
            if any(_origin(d, chosen) not in (None, c) for d in aports[c].build_deps):
                chosen.append(c)
                changed = True
    return frag.build_order(chosen, {n: list(aports[n].build_deps) for n in chosen})


@dataclass(frozen=True)
class FragmentPlan:
    fragments: tuple[str, ...]                 # as requested
    consoles: tuple[str, ...]                  # reached, in the order of the console image
    noarch: tuple[str, ...]                    # built once for every arch, build order
    packages: dict[str, tuple[str, ...]]       # console -> its arch aports, build order
    slots: dict[str, tuple[str, ...]]          # console -> overlay slots expected to change
    stage1: tuple[str, ...]                    # consoles whose initramfs and kernel redo

    def lines(self) -> list[str]:
        out = [f"plan: fragments {', '.join(self.fragments)}",
               f"  noarch (once): {', '.join(self.noarch) or '-'}"]
        for c in self.consoles:
            arch = TARGETS[c].alpine_arch
            out.append(f"  {c} ({arch}): packages {', '.join(self.packages[c]) or '-'}; "
                       f"slots {', '.join(self.slots[c])}"
                       + ("; initramfs and kernel again" if c in self.stage1 else ""))
        for c in CONSOLES:
            if c not in self.consoles:
                out.append(f"  {c}: unchanged (its slot set of the last build)")
        return out

    def as_dict(self) -> dict:
        return {"fragments": list(self.fragments), "consoles": list(self.consoles),
                "noarch": list(self.noarch),
                "packages": {c: list(p) for c, p in self.packages.items()},
                "slots": {c: list(s) for c, s in self.slots.items()},
                "stage1": list(self.stage1)}


def is_fragment_target(names: list[str]) -> bool:
    """True when `names` asks for a fragment build (not one image name)."""
    return not (len(names) == 1 and names[0] in IMAGES)


def plan_fragments(names: list[str], console: str | None = None,
                   aports: dict[str, Aport] | None = None, groups=None) -> FragmentPlan:
    """The plan of a fragment build (see the module doc)."""
    from lume_tool import slots

    aports = read_aports() if aports is None else aports
    clash = sorted(set(aports) & set(IMAGES))
    if clash:
        raise FragmentPlanError(f"aports/{clash[0]} has the name of an image: rename it")
    names = list(dict.fromkeys(names))
    images = [n for n in names if n in IMAGES]
    if images:
        raise FragmentPlanError(f"{images[0]} is an image: build it alone "
                                f"(`lume build {images[0]}`), not with fragments")
    kernel_asked = [n for n in names if n in KERNEL_FRAGMENTS and n not in aports]
    unknown = [n for n in names if n not in aports and n not in kernel_asked]
    if unknown:
        raise FragmentPlanError(
            f"invalid target: {unknown[0]!r}. Valid targets: {', '.join(IMAGES)}, kernel, or "
            f"fragments (aports/): {', '.join(aports)}")
    if console is not None and console not in CONSOLES:
        raise FragmentPlanError(f"--console {console}: expected {' or '.join(CONSOLES)}")
    groups = groups or slots.load_groups()
    wanted = (console,) if console else CONSOLES
    per_console: dict[str, list[str]] = {}
    for c in wanted:
        arch = TARGETS[c].alpine_arch
        candidates = [n for n in aports if aports[n].builds_for(arch)]
        seeds = [n for n in names if n in candidates]
        if seeds:
            per_console[c] = with_reverse_deps(aports, seeds, candidates)
        elif kernel_asked:
            per_console[c] = []
    for n in names:
        if n in kernel_asked:
            continue
        if not any(n in chosen for chosen in per_console.values()):
            where = f"the {console}" if console else "any console"
            raise FragmentPlanError(
                f"fragment {n} is not built for {where} (APKBUILD arch="
                f"\"{' '.join(aports[n].arches)}\")")
    consoles = tuple(c for c in CONSOLES if c in per_console)
    every = [n for c in consoles for n in per_console[c]]
    noarch_names = [n for n in dict.fromkeys(every) if aports[n].noarch]
    noarch = tuple(frag.build_order(noarch_names,
                                    {n: list(aports[n].build_deps) for n in noarch_names}))
    packages = {c: tuple(n for n in per_console[c] if not aports[n].noarch) for c in consoles}
    slot_plan = {}
    for c in consoles:
        touched = {groups.group_of(p) for n in per_console[c] for p in aports[n].packages}
        touched.add(TOP_SLOT)
        slot_plan[c] = tuple(s for s in OVERLAY_SLOTS if s in touched)
    stage1 = tuple(c for c in consoles
                   if kernel_asked or STAGE1_FRAGMENTS & set(per_console[c]))
    return FragmentPlan(fragments=tuple(names), consoles=consoles, noarch=noarch,
                        packages=packages, slots=slot_plan, stage1=stage1)


def latest_language() -> str | None:
    """The factory language of the latest console build (a fragment build keeps it, or
    the rootfs would be made again in another language)."""
    from lume_tool.archive import images_dir

    try:
        info = json.loads((images_dir(IMAGES["console"]) / "latest" / "build.json")
                          .read_text())
        return info.get("language")
    except (OSError, ValueError, AttributeError):
        return None


def build_fragments(names: list[str], console: str | None = None,
                    language: str | None = None) -> Path:
    """Run the plan; return the archived build folder (no image)."""
    from lume_tool import heat, lang
    from lume_tool.stages import StageTimer

    language = language or latest_language() or lang.DEFAULT
    lang.retro_language(language)
    plan = plan_fragments(names, console)
    timer = StageTimer()
    arch_timers: list[StageTimer] = []
    try:
        return _run(plan, language, timer, arch_timers)
    finally:
        heat.add_summary(timer)
        if arch_timers:
            timer.title = "build summary (common steps, set, archive):"
        for t in arch_timers:
            t.print_summary()
        timer.print_summary()


def _run(plan: FragmentPlan, language: str, timer, arch_timers: list) -> Path:
    from lume_tool import build, image, kernel, parallel, rootfs, slots, version
    from lume_tool.archive import archive_set
    from lume_tool.packages import build_noarch, publish_noarch
    from lume_tool.stages import StageTimer

    v = version.current()
    print(f"build {' '.join(plan.fragments)} {v.build_id} (fragment build, no image, "
          f"language {language})", flush=True)
    for line in plan.lines():
        print(line, flush=True)
    if plan.noarch:
        with timer.stage("noarch fragments"):
            apks = build_noarch(list(plan.noarch))
            if apks:
                publish_noarch(apks)
    else:
        timer.skip("noarch fragments", "none in the plan")
    targets = [TARGETS[c] for c in plan.consoles]

    def layer(target, t):
        print(f"layer {target.name} ({target.alpine_arch})", flush=True)
        build.build_fragment_layer(target, v, language, list(plan.packages[target.name]),
                                   target.name in plan.stage1, t)

    if len(plan.stage1) > 1:
        with timer.stage("kernel source tree"):
            kernel.source_tree()
    if len(targets) > 1:
        def pipeline(target):
            return build.arch_label(target), lambda t: layer(target, t)

        def new_timer(label: str) -> StageTimer:
            t = StageTimer(title=f"build summary [{label}]:")
            arch_timers.append(t)
            return t

        parallel.run_pipelines([pipeline(t) for t in targets], timer_factory=new_timer)
    else:
        for target in targets:
            layer(target, timer)
    for c in plan.consoles:
        rebuilt = slots.rebuilt_slots(slots.slots_dir(rootfs.target_out(TARGETS[c])))
        outside = [s for s in rebuilt if s not in plan.slots[c]]
        print(f"{c}: slots packed again: {', '.join(rebuilt) or 'none'}"
              + (f" (outside the plan: {', '.join(outside)}: an Alpine package or a "
                 "shared file changed)" if outside else ""), flush=True)
    with timer.stage("boot list + objects"):
        boot_list = image.write_console_set(v, language=language)
    out = boot_list.parent
    layers = {c: build._layer_info(TARGETS[c]) for c in CONSOLES}
    info = {"kind": "fragments", "plan": plan.as_dict(), "alpine": build._alpine(),
            "layers": layers, "bootloaders": build.console_bootloaders(),
            "language": language}
    manifests = {f"manifest-{c}.txt": rootfs.target_out(TARGETS[c]) / "manifest.txt"
                 for c in CONSOLES}
    extras = image.ga36_android_boot_images(rootfs.target_out(TARGETS["ga36"]))
    extras[image.BOOT_LIST] = boot_list
    extras[image.IMAGE_PARTS] = out / image.IMAGE_PARTS
    with timer.stage("archive"):
        dest = archive_set(IMAGES["console"], v, info, manifests, extras)
    print(f"ok: build {v.build_id} (no image)\narchived: {dest}\n"
          "send it with: lume push", flush=True)
    return dest
