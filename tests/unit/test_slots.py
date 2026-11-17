"""The console root as slots (build-speed D9, task 4.4): rootfs.tar split by owner in the apk
database into base, runtime and lume, rootfs/slots.toml, the SLOTS of a build and the size
limits."""

import base64
import hashlib
import io
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from r36os import manifests, pkglists, slots, stage_inputs
from r36os.paths import REPO_ROOT

MiB = 2**20


def _z(data: bytes) -> str:
    return "Q1" + base64.b64encode(hashlib.sha1(data).digest()).decode()


# package -> (version, [(dir, [(file, content-as-installed)])])
PACKAGES = {
    "musl": ("1.2.6-r3", [("lib", [("ld-musl.so.1", b"musl")])]),
    "busybox": ("1.37.0-r31", [("bin", [("busybox", b"bb")]),
                               ("etc", [("inittab", b"stock inittab")])]),
    "alpine-baselayout": ("3.7.2-r1", [("dev", []), ("etc", []), ("var/empty", [])]),
    "retroarch": ("1.22.2-r112", [("usr/bin", [("retroarch", b"ra")]),
                                  ("usr/share/retroarch", [("a.png", b"png")])]),
    "libretro-fceumm": ("0_git20241123-r0", [("usr/lib/libretro", [("fceumm.so", b"core")])]),
    "lume-core": ("1.0-r3", [("usr/libexec/r36os", [("logd", b"logd")])]),
    "mesa-egl": ("26.1.6-r0", [("usr/lib", [("libEGL.so.1", b"egl"),
                                            ("libEGL.so", b"libEGL.so.1")])]),
}
GROUPS = slots.Groups(patterns={"base": ("musl", "busybox"),
                                "runtime": ("retroarch", "libretro-*", "mesa-*"),
                                "lume": ("lume-*",)}, default="base")


def _db() -> str:
    out = []
    for pkg, (ver, dirs) in PACKAGES.items():
        out += [f"P:{pkg}", f"V:{ver}"]
        for d, files in dirs:
            out.append(f"F:{d}")
            for name, data in files:
                out += [f"R:{name}", f"Z:{_z(data)}"]
        out.append("")
    return "\n".join(out) + "\n"


def _rootfs(path: Path, mtime: int = 1794887488) -> Path:
    """A rootfs.tar as rootfs.py makes it (./ names, numeric owners, sorted)."""
    entries: dict[str, tuple] = {".": ("d", 0o755, b"")}

    def add_dirs(rel):
        parts = rel.split("/")
        for i in range(1, len(parts)):
            entries.setdefault("/".join(parts[:i]), ("d", 0o755, b""))

    for pkg, (ver, dirs) in PACKAGES.items():
        for d, files in dirs:
            add_dirs(d + "/x")
            for name, data in files:
                rel = f"{d}/{name}"
                add_dirs(rel)
                if name == "libEGL.so":
                    entries[rel] = ("l", 0o777, data)          # symlink, Z of the target
                else:
                    entries[rel] = ("f", 0o755, data)
    entries["etc/inittab"] = ("f", 0o644, b"changed by configure.sh")
    entries["etc/os-release"] = ("f", 0o644, b"NAME=Lume\n")    # no owner (overlay)
    entries["etc/apk/world"] = ("f", 0o644, b"retroarch\n")
    add_dirs("etc/apk/world")
    entries["lib/apk/db/installed"] = ("f", 0o644, _db().encode())
    add_dirs("lib/apk/db/installed")
    entries["usr/share/fonts/cache"] = ("f", 0o644, b"trigger output")
    add_dirs("usr/share/fonts/cache")
    entries["storage"] = ("d", 0o755, b"")                       # empty, no owner
    entries["bin/sh"] = ("l", 0o777, b"/bin/busybox")            # trigger output
    # hard link of a runtime file, owned by nobody: lume; the target stays in runtime
    entries["usr/share/retroarch/b.png"] = ("h", 0o644, b"./usr/share/retroarch/a.png")
    with tarfile.open(path, "w", format=tarfile.GNU_FORMAT) as t:
        for rel in sorted(entries, key=lambda r: [] if r == "." else r.split("/")):
            kind, mode, data = entries[rel]
            info = tarfile.TarInfo("." if rel == "." else f"./{rel}")
            info.mode, info.mtime, info.uid, info.gid = mode, mtime, 0, 0
            if kind == "d":
                info.type = tarfile.DIRTYPE
                t.addfile(info)
            elif kind == "l":
                info.type, info.linkname = tarfile.SYMTYPE, data.decode()
                t.addfile(info)
            elif kind == "h":
                info.type, info.linkname = tarfile.LNKTYPE, data.decode()
                t.addfile(info)
            else:
                info.size = len(data)
                t.addfile(info, io.BytesIO(data))
    return path


def _members(tar: Path) -> dict[str, tarfile.TarInfo]:
    with tarfile.open(tar) as t:
        return {m.name: m for m in t.getmembers()}


def _data(tar: Path, name: str) -> bytes:
    with tarfile.open(tar) as t:
        return t.extractfile(name).read()


# --- the split ---------------------------------------------------------------------------

def test_every_file_of_the_rootfs_is_in_exactly_one_slot(tmp_path):
    tar = _rootfs(tmp_path / "rootfs.tar")
    sp = slots.split_rootfs(tar, GROUPS)
    out = slots.write_slot_tars(tar, sp, tmp_path / "work")
    source = _members(tar)
    files = {n for n, m in source.items() if not m.isdir()}
    seen: dict[str, list[str]] = {}
    for name, path in out.items():
        for n, m in _members(path).items():
            if not m.isdir():
                seen.setdefault(n, []).append(name)
    assert set(seen) == files
    assert {n: s for n, s in seen.items() if len(s) != 1} == {}
    # every directory is in a slot, and in every slot above one of its members
    dirs = {n for n, m in source.items() if m.isdir() and n != "."}
    slot_dirs = {name: {n for n, m in _members(p).items() if m.isdir()}
                 for name, p in out.items()}
    assert dirs == set().union(*slot_dirs.values())
    for name, path in out.items():
        for n in _members(path):
            parts = n.split("/")
            for i in range(2, len(parts)):
                assert "/".join(parts[:i]) in slot_dirs[name], (name, n)


def test_files_go_to_the_slot_of_their_owner(tmp_path):
    tar = _rootfs(tmp_path / "rootfs.tar")
    sp = slots.split_rootfs(tar, GROUPS)
    assert sp.files["./lib/ld-musl.so.1"] == "base"
    assert sp.files["./bin/busybox"] == "base"
    assert sp.files["./usr/bin/retroarch"] == "runtime"
    assert sp.files["./usr/lib/libretro/fceumm.so"] == "runtime"
    assert sp.files["./usr/lib/libEGL.so"] == "runtime"            # symlink, Z of target
    assert sp.files["./usr/libexec/r36os/logd"] == "lume"
    # an owned empty directory stays with its owner (default group: base)
    assert sp.dirs["./var/empty"] == {"base"}
    assert sp.packages["lume"] == [("lume-core", "1.0-r3")]
    assert ("alpine-baselayout", "3.7.2-r1") in sp.packages["base"]
    assert sp.unnamed == ["alpine-baselayout"]                      # on the default


def test_unowned_changed_and_apk_files_go_to_lume(tmp_path):
    tar = _rootfs(tmp_path / "rootfs.tar")
    sp = slots.split_rootfs(tar, GROUPS)
    for name in ("./lib/apk/db/installed", "./etc/apk/world", "./etc/os-release",
                 "./usr/share/fonts/cache", "./bin/sh", "./usr/share/retroarch/b.png"):
        assert sp.files[name] == "lume", name
        assert sp.to_top[name] == "no owner"
    # owned by busybox (base) but changed after the install: the base does not change
    assert sp.files["./etc/inittab"] == "lume"
    assert sp.to_top["./etc/inittab"] == "changed after the install"
    assert sp.dirs["./storage"] == {"lume"}


def test_a_hard_link_into_another_slot_becomes_a_file(tmp_path):
    tar = _rootfs(tmp_path / "rootfs.tar")
    sp = slots.split_rootfs(tar, GROUPS)
    assert sp.hardlinks_copied == ["./usr/share/retroarch/b.png"]
    out = slots.write_slot_tars(tar, sp, tmp_path / "work")
    m = _members(out["lume"])["./usr/share/retroarch/b.png"]
    assert m.isreg() and m.size == 3
    assert _data(out["lume"], "./usr/share/retroarch/b.png") == b"png"


def test_slot_tars_keep_the_headers_of_the_rootfs(tmp_path):
    tar = _rootfs(tmp_path / "rootfs.tar")
    out = slots.write_slot_tars(tar, slots.split_rootfs(tar, GROUPS), tmp_path / "w")
    src = _members(tar)
    for path in out.values():
        for n, m in _members(path).items():
            s = src[n]
            assert (m.mode, m.uid, m.gid, m.mtime) == (s.mode, s.uid, s.gid, s.mtime), n
            # only a hard link into another slot changes type (a regular file)
            assert m.type == s.type or n == "./usr/share/retroarch/b.png", n
    # mksquashfs ignores the root entry of a tar: it is left out
    assert not [n for p in out.values() for n in _members(p) if n == "."]


def test_slot_tars_are_the_same_on_every_run(tmp_path):
    tar = _rootfs(tmp_path / "rootfs.tar")
    a = slots.write_slot_tars(tar, slots.split_rootfs(tar, GROUPS), tmp_path / "a")
    b = slots.write_slot_tars(tar, slots.split_rootfs(tar, GROUPS), tmp_path / "b")
    for name in a:
        assert a[name].read_bytes() == b[name].read_bytes()


def test_a_file_owned_by_two_groups_goes_to_lume(tmp_path):
    db = slots.parse_apk_db("P:a\nV:1-r0\nF:x\nR:f\nZ:Q1x\n\nP:b\nV:1-r0\nF:x\nR:f\nZ:Q1x\n")
    assert db.files["x/f"] == [("a", "Q1x"), ("b", "Q1x")]
    assert db.dirs["x"] == ["a", "b"]
    assert db.versions == {"a": "1-r0", "b": "1-r0"}
    # the same in a rootfs: busybox (base) and lume-core (lume) both list etc/inittab
    PACKAGES_TWO = dict(PACKAGES)
    PACKAGES_TWO["lume-core"] = ("1.0-r3", [("usr/libexec/r36os", [("logd", b"logd")]),
                                            ("bin", [("busybox", b"bb")])])
    old = dict(PACKAGES)
    PACKAGES.clear()
    PACKAGES.update(PACKAGES_TWO)
    try:
        tar = _rootfs(tmp_path / "rootfs.tar")
    finally:
        PACKAGES.clear()
        PACKAGES.update(old)
    sp = slots.split_rootfs(tar, GROUPS)
    assert sp.files["./bin/busybox"] == "lume"
    assert sp.to_top["./bin/busybox"] == "owned by packages of different groups"


def test_a_rootfs_without_apk_database_is_refused(tmp_path):
    tar = tmp_path / "r.tar"
    with tarfile.open(tar, "w") as t:
        t.addfile(tarfile.TarInfo("./etc"))
    with pytest.raises(slots.SlotsError, match="lib/apk/db/installed"):
        slots.split_rootfs(tar, GROUPS)


# --- rootfs/slots.toml -------------------------------------------------------------------

def test_slots_toml_names_every_listed_package():
    """Every package of rootfs/packages.txt and board/*/hw-packages.txt is named by a group:
    one that would only fall on the default is listed here, so its slot is a decision."""
    groups = slots.load_groups()
    listed = set(pkglists.read_list(pkglists.COMMON))
    for hw in sorted((REPO_ROOT / "board").glob("*/hw-packages.txt")):
        listed |= set(pkglists.read_list(hw))
    unnamed = sorted(p for p in listed if not groups.named(p))
    assert unnamed == [], f"name these in rootfs/slots.toml: {unnamed}"
    for p in listed:
        groups.group_of(p)                       # in one group only


def test_slots_toml_groups():
    groups = slots.load_groups()
    assert groups.default == "base"
    assert groups.group_of("retroarch") == "runtime"
    assert groups.group_of("libretro-snes9x2005-plus") == "runtime"     # the cores stay here (P-80)
    assert groups.group_of("mesa-dri-gallium") == "runtime"
    assert groups.group_of("sdl2") == "runtime"
    assert groups.group_of("lume-launcher") == "lume"
    assert groups.group_of("lume-bootsel") == "lume"
    assert groups.group_of("r36os-input") == "lume"
    assert groups.group_of("busybox") == "base"
    assert groups.group_of("musl") == "base"                    # not named: the default
    # every local aport goes to a named group
    for apkbuild in sorted((REPO_ROOT / "aports").glob("*/APKBUILD")):
        assert groups.named(apkbuild.parent.name), apkbuild.parent.name


def test_slots_toml_is_checked(tmp_path):
    bad = tmp_path / "s.toml"
    bad.write_text('default = "base"\n[groups]\ncores = ["x"]\n')
    with pytest.raises(slots.SlotsError, match="base, runtime, lume"):
        slots.load_groups(bad)
    bad.write_text('default = "nowhere"\n[groups]\nbase = ["x"]\n')
    with pytest.raises(slots.SlotsError):
        slots.load_groups(bad)
    bad.write_text('default = "base"\n[groups]\nbase = ["a*"]\nlume = ["ab"]\n')
    with pytest.raises(slots.SlotsError, match="ab is in the groups base, lume"):
        slots.load_groups(bad).group_of("ab")


# --- the slots on disk and the SLOTS of a build -----------------------------------------

def _fake_squash(slots_dir: Path, names, options):
    # stands for mksquashfs: the tar itself, without its times (as -all-time 0)
    for n in names:
        with tarfile.open(slots_dir / "work" / f"{n}.tar") as t:
            listing = "".join(f"{m.name} {m.mode} {m.type!r} {m.size}\n" for m in t)
        (slots_dir / f"{n}.squashfs").write_text(options + "\n" + listing)


def _modules(path: Path, data: bytes = b"modules image") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


def test_slot_set_of_a_build(tmp_path):
    tar = _rootfs(tmp_path / "rootfs.tar")
    sdir = tmp_path / "slots"
    made = slots.build_overlay_slots(tar, sdir, "-opts", GROUPS, squash=_fake_squash)
    assert [s.name for s in made] == ["base", "runtime", "lume"]
    assert not (sdir / "work").exists()
    for s in made:
        assert (sdir / Path(s.file).name).is_file()
        assert s.sha256 == manifests.sha256_file(sdir / Path(s.file).name)
    assert slots.overlay_files(sdir) == [sdir / Path(s.file).name for s in made]
    mod = _modules(tmp_path / "kernel" / "modules")
    ss = slots.write_slot_set("ga36", "20261117-010203", sdir, mod, "6.18.2")
    assert manifests.read_slots(sdir / "SLOTS") == ss
    assert ss.build == "20261117-010203" and ss.console == "ga36"
    base, runtime, lume, modules = ss.slots
    # each slot names the slots below it it was made with (a coherent set)
    assert runtime.lower == (("base", base.sha256),)
    assert lume.lower == (("base", base.sha256), ("runtime", runtime.sha256))
    assert modules.lower == () and modules.packages == (("linux", "6.18.2"),)
    assert modules.sha256 == manifests.sha256_file(mod)
    assert (sdir / Path(modules.file).name).read_bytes() == b"modules image"
    assert ("retroarch", "1.22.2-r112") in runtime.packages
    assert lume.packages == (("lume-core", "1.0-r3"),)
    assert slots.boot_files("ga36", sdir) == {
        "ga36/SLOTS": sdir / "SLOTS", **{f"ga36/{s.file}": sdir / Path(s.file).name
                                         for s in ss.slots}}


def test_a_new_set_removes_the_files_of_the_old_one(tmp_path):
    tar = _rootfs(tmp_path / "rootfs.tar")
    sdir = tmp_path / "slots"
    slots.build_overlay_slots(tar, sdir, "-a", GROUPS, squash=_fake_squash)
    old = slots.write_slot_set("r36s", "1", sdir, _modules(tmp_path / "m1", b"m1"))
    slots.build_overlay_slots(tar, sdir, "-b", GROUPS, squash=_fake_squash)
    new = slots.write_slot_set("r36s", "2", sdir, _modules(tmp_path / "m2", b"m2"))
    kept = {p.name for p in sdir.iterdir()}
    assert kept == {"SLOTS", slots.OVERLAY_RECORD, *(Path(f).name for f in new.files())}
    assert not set(old.files()) & set(new.files())


def test_the_slots_of_a_console_have_a_limit(tmp_path):
    tar = _rootfs(tmp_path / "rootfs.tar")
    sdir = tmp_path / "slots"
    slots.build_overlay_slots(tar, sdir, "-a", GROUPS, squash=_fake_squash)
    big = _modules(tmp_path / "m", b"x" * (MiB + 1))
    with pytest.raises(slots.SlotsTooLargeError, match="ga36 take .* above the 1 MiB limit"):
        slots.write_slot_set("ga36", "1", sdir, big, limit_mib=1)
    assert not (sdir / "SLOTS").exists()
    assert slots.CONSOLE_SLOTS_LIMIT_MIB == 448


def test_slot_set_without_overlay_slots_is_refused(tmp_path):
    with pytest.raises(slots.SlotsError, match="overlay.json"):
        slots.write_slot_set("ga36", "1", tmp_path, _modules(tmp_path / "m"))


# --- stage skipping ----------------------------------------------------------------------

def test_slots_stage_inputs(tmp_path):
    tar = _rootfs(tmp_path / "rootfs.tar")
    toml = tmp_path / "slots.toml"
    shutil.copy(slots.SLOTS_TOML, toml)
    first = stage_inputs.slots_inputs(tar, toml, "-x").digest()
    # rootfs.tar made again with other times (apk writes new ones): the same slots
    _rootfs(tmp_path / "rootfs.tar", mtime=1)
    assert stage_inputs.slots_inputs(tar, toml, "-x").digest() == first
    assert stage_inputs.slots_inputs(tar, toml, "-y").digest() != first
    toml.write_text(toml.read_text() + "\n# changed\n")
    assert stage_inputs.slots_inputs(tar, toml, "-x").digest() != first
    assert stage_inputs.slots_inputs(tmp_path / "none.tar", toml, "-x").unknown


def test_build_console_slots_skips_an_unchanged_rootfs(tmp_path, monkeypatch):
    from r36os import build, rootfs, version
    from r36os.stages import StageTimer
    from r36os.targets import TARGETS

    out = tmp_path / "ga36"
    monkeypatch.setattr(rootfs, "target_out", lambda target: out)
    out.mkdir()
    _rootfs(out / "rootfs.tar")
    # the modules slot is the image of the published lume-modules (build-speed 7.3)
    _modules(out / "kernel-pkg" / "boot" / "modules.squashfs")
    (out / "kernel").mkdir()
    (out / "kernel" / "release").write_text("6.18.2\n")
    runs = []

    def squash(sdir, names, options):
        runs.append(options)
        _fake_squash(sdir, names, options)

    real = slots.build_overlay_slots
    monkeypatch.setattr(slots, "build_overlay_slots",
                        lambda tar, sdir, options, **kw: real(tar, sdir, options,
                                                              squash=squash, **kw))
    v = version.current()
    timer = StageTimer()
    build.build_console_slots(TARGETS["ga36"], v, timer)
    first = manifests.read_slots(out / manifests.SLOTS_DIR / "SLOTS")
    _rootfs(out / "rootfs.tar", mtime=5)                 # same files, new times
    build.build_console_slots(TARGETS["ga36"], v, timer)
    assert len(runs) == 1
    assert any("ga36: slots" in line and "skipped (inputs unchanged" in line
               for line in timer.summary())
    assert manifests.read_slots(out / manifests.SLOTS_DIR / "SLOTS") == first
    # a slot file gone: the stage runs again
    (out / manifests.SLOTS_DIR / Path(first.get("lume").file).name).unlink()
    build.build_console_slots(TARGETS["ga36"], v, timer)
    assert len(runs) == 2


def _level_setup(tmp_path, monkeypatch, pad_fast=0):
    from r36os import rootfs

    out = tmp_path / "ga36"
    monkeypatch.setattr(rootfs, "target_out", lambda target: out)
    out.mkdir()
    _rootfs(out / "rootfs.tar")
    from r36os import kernel_packages

    # the modules slot comes from the published lume-modules (build-speed 7.3)
    _modules(kernel_packages.modules_image(out))
    (out / "kernel").mkdir(exist_ok=True)
    (out / "kernel" / "release").write_text("6.18.2\n")
    levels = []

    def squash(sdir, names, options):
        levels.append(int(options.split("-Xcompression-level ")[1].split()[0]))
        _fake_squash(sdir, names, options)
        if levels[-1] == slots.LEVEL_FAST:
            for n in names:
                with (sdir / f"{n}.squashfs").open("a") as f:
                    f.write("x" * pad_fast)

    real = slots.build_overlay_slots
    monkeypatch.setattr(slots, "build_overlay_slots",
                        lambda tar, sdir, options, **kw: real(tar, sdir, options,
                                                              squash=squash, **kw))
    return levels


def test_fast_slots_are_not_reused_by_the_full_build_and_back(tmp_path, monkeypatch):
    from r36os import build, version
    from r36os.stages import StageTimer
    from r36os.targets import TARGETS

    levels = _level_setup(tmp_path, monkeypatch)
    v, timer = version.current(), StageTimer()
    build.build_console_slots(TARGETS["ga36"], v, timer, level=slots.LEVEL_FAST)
    build.build_console_slots(TARGETS["ga36"], v, timer, level=slots.LEVEL_FAST)
    assert levels == [slots.LEVEL_FAST]                  # same level: skipped
    build.build_console_slots(TARGETS["ga36"], v, timer)
    assert levels == [slots.LEVEL_FAST, slots.LEVEL_FULL]
    build.build_console_slots(TARGETS["ga36"], v, timer)
    assert levels == [slots.LEVEL_FAST, slots.LEVEL_FULL]
    # a fragment build keeps the full-level slots whose content did not change (task 6.2):
    # only the other way (a fast slot in a full build) is refused
    build.build_console_slots(TARGETS["ga36"], v, timer, level=slots.LEVEL_FAST)
    assert levels == [slots.LEVEL_FAST, slots.LEVEL_FULL]


def test_fast_slots_over_the_limit_fall_back_to_the_full_level(tmp_path, monkeypatch, capsys):
    from r36os import build, version
    from r36os.stages import StageTimer
    from r36os.targets import TARGETS

    monkeypatch.setattr(slots, "CONSOLE_SLOTS_LIMIT_MIB", 1)
    levels = _level_setup(tmp_path, monkeypatch, pad_fast=600_000)
    v, timer = version.current(), StageTimer()
    build.build_console_slots(TARGETS["ga36"], v, timer, level=slots.LEVEL_FAST)
    assert levels == [slots.LEVEL_FAST, slots.LEVEL_FULL]
    assert "warning: the slots of ga36 take" in capsys.readouterr().out
    out = tmp_path / "ga36"
    assert (out / manifests.SLOTS_DIR / "SLOTS").is_file()
    # the full build right after keeps what the fallback made
    build.build_console_slots(TARGETS["ga36"], v, timer)
    assert levels == [slots.LEVEL_FAST, slots.LEVEL_FULL]


def test_with_level_changes_only_the_zstd_level():
    from r36os import rootfs

    assert slots.with_level(rootfs.SQUASHFS_OPTIONS, 19) == rootfs.SQUASHFS_OPTIONS
    fast = slots.with_level(rootfs.SQUASHFS_OPTIONS, 3)
    assert "-Xcompression-level 3 " in fast and "-b 256K" in fast
    with pytest.raises(slots.SlotsError):
        slots.with_level("-comp gzip", 3)


def _recording_squash(runs):
    def squash(sdir, names, options):
        runs.append(list(names))
        _fake_squash(sdir, names, options)
    return squash


def test_only_the_slots_whose_content_changed_are_packed_again(tmp_path, monkeypatch):
    sdir = tmp_path / "slots"
    runs = []
    first = slots.build_overlay_slots(_rootfs(tmp_path / "rootfs.tar"), sdir, "-a", GROUPS,
                                      squash=_recording_squash(runs))
    assert runs == [["base", "runtime", "lume"]]
    assert slots.rebuilt_slots(sdir) == ["base", "runtime", "lume"]
    # a new lume-core: its file and the apk database (no owner) are both in lume
    monkeypatch.setitem(PACKAGES, "lume-core",
                        ("1.1-r0", [("usr/libexec/r36os", [("logd", b"new logd")])]))
    again = slots.build_overlay_slots(_rootfs(tmp_path / "rootfs.tar", mtime=7), sdir, "-a",
                                      GROUPS, squash=_recording_squash(runs))
    assert runs[1:] == [["lume"]]
    assert slots.rebuilt_slots(sdir) == ["lume"]
    assert again[0] == first[0] and again[1] == first[1]       # base and runtime kept
    assert again[2].sha256 != first[2].sha256
    assert again[2].lower == (("base", first[0].sha256), ("runtime", first[1].sha256))
    assert slots.overlay_files(sdir) == [sdir / Path(s.file).name for s in again]
    assert all(p.is_file() for p in slots.overlay_files(sdir))
    # nothing changed: nothing packed
    slots.build_overlay_slots(_rootfs(tmp_path / "rootfs.tar"), sdir, "-a", GROUPS,
                              squash=_recording_squash(runs))
    assert len(runs) == 2
    assert slots.rebuilt_slots(sdir) == []


def test_other_options_pack_again_unless_a_fragment_build(tmp_path):
    sdir = tmp_path / "slots"
    tar = _rootfs(tmp_path / "rootfs.tar")
    runs = []
    slots.build_overlay_slots(tar, sdir, "-level19", GROUPS, squash=_recording_squash(runs))
    # a fragment build (other, faster options) keeps the slots of the same content
    slots.build_overlay_slots(tar, sdir, "-level3", GROUPS, squash=_recording_squash(runs),
                              reuse_any_options=True)
    assert len(runs) == 1
    record = (sdir / slots.OVERLAY_RECORD).read_text()
    assert "-level19" in record and "-level3" not in record
    # `build console` with its options packs again what a fast build packed
    slots.build_overlay_slots(tar, sdir, "-level19", GROUPS, squash=_recording_squash(runs))
    assert len(runs) == 1                                      # they were level 19 already
    slots.build_overlay_slots(tar, sdir, "-other", GROUPS, squash=_recording_squash(runs))
    assert runs[1:] == [["base", "runtime", "lume"]]


def test_two_runs_give_the_same_squashfs(tmp_path):
    """The real mksquashfs (builder container): rootfs.tar made again with other times
    gives byte-identical slots, so a build without changes keeps the slot names."""
    from r36os import rootfs

    if shutil.which("podman") is None:
        pytest.skip("no podman")
    r = subprocess.run(["podman", "image", "exists", "localhost/r36os-builder:x86_64"])
    if r.returncode != 0:
        pytest.skip("no builder image")
    names = []
    for i, mtime in enumerate((1794887488, 1700000000)):
        tar = _rootfs(tmp_path / f"rootfs{i}.tar", mtime=mtime)
        made = slots.build_overlay_slots(tar, tmp_path / f"s{i}", rootfs.SQUASHFS_OPTIONS,
                                         GROUPS)
        names.append([s.file for s in made])
    assert names[0] == names[1]
