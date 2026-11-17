"""Shared formats of build-speed (task 4.0): SLOTS, boot-files.sha256 with objects,
.lume-content, the inputs hash and hashes.json."""

import json

import pytest

from r36os import image, manifests as m
from r36os.manifests import ManifestError, PackageHashes, RepoHashes, Slot, SlotSet

B, R, L, MO, C = ("b" * 64, "c" * 64, "d" * 64, "e" * 64, "f" * 64)


def test_console_folder_names_differ_on_a_case_insensitive_fat():
    # BOOT is FAT32: <console>/SLOTS and a <console>/slots/ folder were the same name, and
    # the first console image with slots failed reading SLOTS back (2026-11-17)
    names = [m.SLOTS_FILE, m.SLOTS_OLD, m.SLOTS_NEW, m.SLOTS_DIR, "SYSTEM", "SYSTEM.old",
             "modules", "Image", "zImage"]
    assert len({n.lower() for n in names}) == len(names)
    assert m.slot_file("lume", L).startswith(m.SLOTS_DIR + "/")


def slot_set(console="ga36") -> SlotSet:
    return SlotSet(build="20261116-214233", console=console, slots=(
        # given out of order on purpose: the set keeps the canonical order
        Slot("core-snes9x", C, 5000, lower=(("base", B), ("runtime", R))),
        Slot("modules", MO, 4000),
        Slot("lume", L, 3000, lower=(("base", B), ("runtime", R)),
             packages=(("lume-core", "1.0-r3"),)),
        Slot("runtime", R, 2000, lower=(("base", B),)),
        Slot("base", B, 1000, packages=(("musl", "1.2.5-r10"), ("busybox", "1.37.0-r20"))),
    ))


# the text the shell test (tests/initramfs/test_slots.sh, good()) reads
GOOD = f"""lume-slots 1
build 20261116-214233
console ga36
slot base slot/base-{B[:12]} {B} 1000 -
pkg base musl 1.2.5-r10
pkg base busybox 1.37.0-r20
slot runtime slot/runtime-{R[:12]} {R} 2000 base={B}
slot lume slot/lume-{L[:12]} {L} 3000 base={B},runtime={R}
pkg lume lume-core 1.0-r3
slot modules slot/modules-{MO[:12]} {MO} 4000 -
slot core-snes9x slot/core-snes9x-{C[:12]} {C} 5000 base={B},runtime={R}
end 5 3
"""


# ---- SLOTS ----------------------------------------------------------------------------

def test_slots_format_is_the_shell_test_text():
    assert m.format_slots(slot_set()) == GOOD


def test_slots_round_trip(tmp_path):
    p = tmp_path / "ga36" / m.SLOTS_FILE
    m.write_slots(p, slot_set())
    back = m.read_slots(p)
    assert back == slot_set()
    assert [s.name for s in back.overlay()] == ["base", "runtime", "lume"]
    assert [s.name for s in back.cores()] == ["core-snes9x"]
    assert back.get("lume").file == f"slot/lume-{L[:12]}"
    assert back.get("base").packages == (("musl", "1.2.5-r10"), ("busybox", "1.37.0-r20"))
    assert not list(p.parent.glob("*.tmp"))


def test_slot_file_name():
    assert m.slot_file("core-fbneo", "0123456789abcdef" * 4) == "slot/core-fbneo-0123456789ab"


def test_missing_slot_files(tmp_path):
    ss = slot_set()
    (tmp_path / m.SLOTS_DIR).mkdir()
    for f in ss.files()[:-1]:
        (tmp_path / f).touch()
    assert m.missing_slot_files(tmp_path, ss) == [f"slot/core-snes9x-{C[:12]}"]


@pytest.mark.parametrize("text, why", [
    ("", "empty"),
    (GOOD[:-1], "no newline at the end"),
    ("\n".join(GOOD.splitlines()[:7]) + "\n", "no `end` line"),
    (GOOD.replace("lume-slots 1", "lume-slots 2"), "not a SLOTS manifest"),
    (GOOD.replace("pkg lume lume-core 1.0-r3\n", ""), "end counts"),
    (GOOD.replace(f" {R} 2000", f" {R.upper()} 2000"), "bad sha256 of slot runtime"),
    (GOOD.replace(f"runtime={R}", f"runtime={'a' * 64}"), "incoherent set"),
    (GOOD.replace(f"slot/lume-{L[:12]}", f"slot/lume-{B[:12]}"), "is not"),
    (GOOD.replace("slot base ", "slot  base "), "unknown line"),
    (GOOD.replace("slot base ", "slot\tbase "), "unknown line"),
    (GOOD + "slot extra\n", "after the `end` line"),
    (GOOD.replace(" 1000 -", " 1k -"), "bad size"),
    ("".join(line + "\n" for line in GOOD.splitlines() if not line.startswith("slot modules"))
     .replace("end 5 3", "end 4 3"), "no modules slot"),
    (GOOD.replace("pkg base musl", "pkg lume musl"), "not right after its slot line"),
    (GOOD.replace("build 20261116-214233", "build"), "expected `build <id>`"),
])
def test_slots_refused(text, why):
    with pytest.raises(ManifestError, match=why.replace("`", ".").replace("(", r"\(")):
        m.parse_slots(text)


def test_slots_out_of_order_refused():
    lines = GOOD.splitlines()
    # runtime above lume
    swapped = [*lines[:6], lines[7], lines[8], lines[6], *lines[9:]]
    with pytest.raises(ManifestError, match="out of order"):
        m.parse_slots("\n".join(swapped) + "\n")


def test_slots_writer_refuses_incoherent_or_incomplete_sets():
    good = slot_set()
    bad_lower = SlotSet(good.build, good.console, tuple(
        Slot(s.name, s.sha256, s.size, lower=(("base", "a" * 64),)) if s.name == "lume" else s
        for s in good.slots))
    with pytest.raises(ManifestError, match="incoherent"):
        m.format_slots(bad_lower)
    above = SlotSet(good.build, good.console, tuple(
        Slot(s.name, s.sha256, s.size, lower=(("lume", L),)) if s.name == "runtime" else s
        for s in good.slots))
    with pytest.raises(ManifestError, match="not a slot below it"):
        m.format_slots(above)
    with pytest.raises(ManifestError, match="no modules"):
        m.format_slots(SlotSet(good.build, good.console,
                               tuple(s for s in good.slots if s.name != "modules")))
    with pytest.raises(ManifestError, match="bad slot name"):
        m.format_slots(SlotSet(good.build, good.console, (*good.slots, Slot("Extra", B, 1))))


def test_read_slots_missing(tmp_path):
    with pytest.raises(ManifestError, match="missing"):
        m.read_slots(tmp_path / "SLOTS")


# ---- boot-files.sha256 and objects -------------------------------------------------------

BOOT = {"ga36/zImage": "1" * 64, "VERSION": "2" * 64, "dtbs/rk3326/a.dtb": "3" * 64,
        "ga36/slot/base-bbbbbbbbbbbb": B}


def test_boot_list_round_trip(tmp_path):
    p = tmp_path / m.BOOT_LIST
    m.write_boot_list(p, BOOT)
    text = p.read_text()
    assert text.splitlines()[-1] == f"{'2' * 64}  VERSION"
    assert text.splitlines()[0] == f"{'3' * 64}  dtbs/rk3326/a.dtb"
    back = m.read_boot_list(p)
    assert dict(back) == BOOT
    assert back[-1][0] == "VERSION"
    # what push reads today (image.read_boot_list) reads the same file the same way
    assert image.read_boot_list(p) == back


def test_boot_list_is_sha256sum_compatible(tmp_path):
    """The lines `sha256sum` prints (and `sha256sum -c` reads)."""
    import hashlib
    (tmp_path / "ga36").mkdir()
    (tmp_path / "ga36" / "zImage").write_bytes(b"kernel")
    (tmp_path / "VERSION").write_text("build: x\n")
    files = {p: hashlib.sha256((tmp_path / p).read_bytes()).hexdigest()
             for p in ("ga36/zImage", "VERSION")}
    assert m.format_boot_list(files) == "".join(
        f"{files[p]}  {p}\n" for p in ("ga36/zImage", "VERSION"))


@pytest.mark.parametrize("text, why", [
    ("", "empty"),
    (f"{'1' * 64}  ga36/zImage\n{'2' * 64}  VERSION", "no newline"),
    (f"{'2' * 64}  VERSION\n{'1' * 64}  ga36/zImage\n", "VERSION is not the last"),
    (f"{'1' * 64}  ga36/zImage\n", "VERSION is not the last"),
    (f"{'1' * 63}  ga36/zImage\n{'2' * 64}  VERSION\n", "not `<sha256>  <path>`"),
    (f"{'1' * 64} *ga36/zImage\n{'2' * 64}  VERSION\n", "not `<sha256>  <path>`"),
    (f"{'1' * 64}  ../zImage\n{'2' * 64}  VERSION\n", "bad BOOT path"),
    (f"{'1' * 64}  /zImage\n{'2' * 64}  VERSION\n", "bad BOOT path"),
    (f"{'1' * 64}  VERSION\n{'2' * 64}  VERSION\n", "twice"),
])
def test_boot_list_refused(text, why):
    with pytest.raises(ManifestError, match=why.replace("`", ".").replace("*", r"\*")):
        m.parse_boot_list(text)


def test_boot_list_writer_needs_version():
    with pytest.raises(ManifestError, match="no VERSION"):
        m.format_boot_list({"ga36/zImage": "1" * 64})


def test_objects_stored_once(tmp_path):
    src = tmp_path / "zImage"
    src.write_bytes(b"kernel")
    objects = tmp_path / "images" / m.OBJECTS_DIR
    sha = m.store_object(objects, src)
    assert m.object_path(objects, sha).read_bytes() == b"kernel"
    mtime = m.object_path(objects, sha).stat().st_mtime_ns
    assert m.store_object(objects, src) == sha
    assert m.object_path(objects, sha).stat().st_mtime_ns == mtime
    assert [p.name for p in objects.iterdir()] == [sha]
    assert m.missing_objects(objects, [("ga36/zImage", sha), ("VERSION", "2" * 64)]) == \
        ["VERSION"]
    with pytest.raises(ManifestError):
        m.object_path(objects, "../x")


# ---- .lume-content and the inputs hash ---------------------------------------------------

def test_lume_content_round_trip():
    text = m.format_lume_content(C)
    assert text == f"lume-content 1 {C}\n"
    assert m.parse_lume_content(text) == C


@pytest.mark.parametrize("text", ["", f"lume-content 1 {C}", f"lume-content 2 {C}\n",
                                  f"lume-content 1 {C[:40]}\n", f"{C}\n"])
def test_lume_content_refused(text):
    with pytest.raises(ManifestError):
        m.parse_lume_content(text)


def _pkgdir(root):
    (root / "usr/bin").mkdir(parents=True)
    (root / "usr/bin/tool").write_text("#!/bin/sh\n")
    (root / "usr/bin/tool").chmod(0o755)
    (root / "usr/bin/link").symlink_to("tool")
    return root


PKGINFO = """# Generated by abuild
pkgname = lume-core
pkgver = 1.0-r3
pkgdesc = core
builddate = 1763300000
packager = Buildozer
size = 4096
arch = noarch
depend = busybox
commit = 0123456789abcdef0123456789abcdef01234567
datahash = 99
"""


def test_content_hash_ignores_build_noise(tmp_path):
    entries = m.content_entries(_pkgdir(tmp_path / "a"))
    info = m.parse_pkginfo(PKGINFO)
    h = m.content_hash(entries, info)
    rebuilt = PKGINFO.replace("1.0-r3", "1.0-r4").replace("1763300000", "1763399999") \
        .replace("0123456789abcdef", "fedcba9876543210")
    assert m.content_hash(m.content_entries(_pkgdir(tmp_path / "b")),
                          m.parse_pkginfo(rebuilt)) == h
    listing = m.content_listing(entries, info)
    assert "f 0755 0:0 " in listing and "l 0777 0:0 " in listing and "d 0755 0:0 - usr\n" \
        in listing
    assert "m pkgver 1.0\n" in listing and "builddate" not in listing


def test_content_hash_sees_real_changes(tmp_path):
    root = _pkgdir(tmp_path / "a")
    info = m.parse_pkginfo(PKGINFO)
    h = m.content_hash(m.content_entries(root), info)
    (root / "usr/bin/tool").chmod(0o700)
    assert m.content_hash(m.content_entries(root), info) != h
    (root / "usr/bin/tool").chmod(0o755)
    assert m.content_hash(m.content_entries(root), info) == h
    (root / "usr/bin/tool").write_text("#!/bin/sh\necho\n")
    assert m.content_hash(m.content_entries(root), info) != h
    assert m.content_hash(m.content_entries(_pkgdir(tmp_path / "b")),
                          m.parse_pkginfo(PKGINFO.replace("busybox", "musl"))) != h
    assert m.content_hash(m.content_entries(_pkgdir(tmp_path / "c")),
                          m.parse_pkginfo(PKGINFO.replace("1.0-r3", "1.1-r0"))) != h


def test_inputs_hash_and_commit():
    a = m.inputs_hash({"APKBUILD": B, "src/lib.sh": C})
    assert a == m.inputs_hash({"src/lib.sh": C, "APKBUILD": B})     # order free
    assert a != m.inputs_hash({"APKBUILD": B, "src/lib.sh": R})
    assert m.commit_of_inputs(a) == a[:40]
    assert m.pkginfo_commit(PKGINFO + "") == "0123456789abcdef0123456789abcdef01234567"
    assert m.pkginfo_commit("pkgname = x\n") is None
    with pytest.raises(ManifestError):
        m.inputs_hash({"a b": B})
    with pytest.raises(ManifestError):
        m.parse_pkginfo("pkgname=x\n")


# ---- hashes.json -------------------------------------------------------------------------

def repo() -> RepoHashes:
    return RepoHashes(arch="armv7", packages={
        "lume-net": PackageHashes("1.0-r1", B, C, "lume-net-1.0-r1.apk"),
        "lume-core": PackageHashes("1.0-r3", R, L, "lume-core-1.0-r3.apk"),
    })


def test_hashes_round_trip(tmp_path):
    p = tmp_path / "armv7" / m.HASHES_FILE
    m.write_hashes(p, repo())
    doc = json.loads(p.read_text())
    assert doc["format"] == 1 and doc["arch"] == "armv7"
    assert list(doc["packages"]) == ["lume-core", "lume-net"]
    assert doc["packages"]["lume-core"] == {"version": "1.0-r3", "inputs": R,
                                            "content": L, "file": "lume-core-1.0-r3.apk"}
    assert m.read_hashes(p, "armv7") == repo()


def test_hashes_missing_is_empty(tmp_path):
    assert m.read_hashes(tmp_path / "hashes.json", "aarch64") == RepoHashes("aarch64")
    with pytest.raises(ManifestError, match="missing"):
        m.read_hashes(tmp_path / "hashes.json")


@pytest.mark.parametrize("mutate, why", [
    (lambda t: t[: len(t) // 2], "truncated or garbled"),
    (lambda t: t.replace('"format": 1', '"format": 2'), "unsupported format"),
    (lambda t: t.replace('"arch": "armv7"', '"arch": "aarch64"'), "expected armv7"),
    (lambda t: t.replace("lume-core-1.0-r3.apk", "lume-core-1.0-r2.apk"), "is not"),
    (lambda t: t.replace('"1.0-r3"', '"1.0"'), "bad version"),
    (lambda t: t.replace(L, L[:40]), "bad content hash"),
    (lambda t: t.replace('"file"', '"name"'), "expected the keys"),
])
def test_hashes_refused(mutate, why):
    text = m.format_hashes(repo())
    with pytest.raises(ManifestError, match=why):
        m.parse_hashes(mutate(text), arch="armv7")
