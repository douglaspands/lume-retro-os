"""build-speed D10, task 4.3: the content-addressed build archive (out/images/objects/),
the console image assembled from it by `flash`, and `clean` of the objects no build cites."""

import hashlib
import os
import time

import pytest

from r36os import archive, clean, flash, image, manifests
from r36os.targets import get_image

BUILD = "20261117-100000"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


FILES = {"boot.ini": b"ini", "ga36/SYSTEM": b"ga36 system", "r36s/SYSTEM": b"r36s system",
         "VERSION": b"build: " + BUILD.encode() + b"\n"}
PARTS = {image.AREA_PART: b"boot area", image.PANEL1_PART: b"panel 1 boot image"}


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "cache"))
    return tmp_path / "out"


def _sources(base, files):
    paths = {}
    for p, data in files.items():
        paths[p] = base / "src" / p
        paths[p].parent.mkdir(parents=True, exist_ok=True)
        paths[p].write_bytes(data)
    return paths


def test_the_build_stores_each_boot_file_and_the_image_parts_once(out, tmp_path):
    work = tmp_path / "console"
    manifests.write_boot_list(work / image.BOOT_LIST, {p: sha(d) for p, d in FILES.items()})
    files = _sources(tmp_path, FILES)
    parts = _sources(tmp_path / "parts", PARTS)
    image.store_build_objects(work, files, parts)
    objects = archive.objects_dir()
    assert objects == out / "images/objects"
    for data in [*FILES.values(), *PARTS.values()]:
        assert (objects / sha(data)).read_bytes() == data
    assert image.read_image_parts(work / image.IMAGE_PARTS) == {
        n: sha(d) for n, d in PARTS.items()}
    # a second build with one file changed adds one object
    before = set(os.listdir(objects))
    files["ga36/SYSTEM"].write_bytes(b"new ga36 system")
    manifests.write_boot_list(work / image.BOOT_LIST,
                              {**{p: sha(d) for p, d in FILES.items()},
                               "ga36/SYSTEM": sha(b"new ga36 system")})
    image.store_build_objects(work, files, parts)
    assert set(os.listdir(objects)) - before == {sha(b"new ga36 system")}
    assert not [n for n in os.listdir(objects) if n.endswith(".tmp")]


def test_a_source_that_differs_from_the_fat_stops_the_build(out, tmp_path):
    work = tmp_path / "console"
    manifests.write_boot_list(work / image.BOOT_LIST, {p: sha(d) for p, d in FILES.items()})
    files = _sources(tmp_path, {**FILES, "r36s/SYSTEM": b"changed meanwhile"})
    with pytest.raises(image.ConsoleImageError, match="r36s/SYSTEM on the FAT differs"):
        image.store_build_objects(work, files, _sources(tmp_path / "p", PARTS))
    del files["boot.ini"]
    with pytest.raises(image.ConsoleImageError, match="boot.ini is on BOOT but not"):
        image.store_build_objects(work, files, _sources(tmp_path / "p", PARTS))


def test_the_image_parts_list_is_strict(tmp_path):
    p = tmp_path / image.IMAGE_PARTS
    p.write_text(f"{sha(b'a')}  {image.AREA_PART}\n")
    with pytest.raises(manifests.ManifestError, match="expected boot-area"):
        image.read_image_parts(p)
    p.write_text(f"xyz  {image.AREA_PART}\n{sha(b'b')}  {image.PANEL1_PART}\n")
    with pytest.raises(manifests.ManifestError, match="bad object name"):
        image.read_image_parts(p)


def _archived_build(out, zst=False):
    """A console build in the new layout: BOOT list, image parts and their objects."""
    d = out / "images/console" / BUILD
    d.mkdir(parents=True)
    manifests.write_boot_list(d / image.BOOT_LIST, {p: sha(v) for p, v in FILES.items()})
    (d / image.IMAGE_PARTS).write_text(image.format_image_parts(
        {n: sha(v) for n, v in PARTS.items()}))
    objects = out / "images/objects"
    objects.mkdir(parents=True, exist_ok=True)
    for data in [*FILES.values(), *PARTS.values()]:
        (objects / sha(data)).write_bytes(data)
    if zst:
        (d / f"console-{BUILD}.img.zst").write_bytes(b"zst")
    (out / "images/console/latest").symlink_to(BUILD)
    return d


def test_assemble_console_image_reads_every_piece_from_the_objects(out, tmp_path):
    d = _archived_build(out)
    seen = {}

    def runner(volumes, script):
        seen["volumes"], seen["script"] = volumes, script
        work = next(h for h, g in volumes.items() if g == "/out")
        (work / "console.img").write_bytes(b"card image")
        (work / image.BOOT_LIST).write_text((d / image.BOOT_LIST).read_text())

    dest = image.assemble_console_image(d, tmp_path / "cache/console.img", runner)
    assert dest.read_bytes() == b"card image"
    assert seen["volumes"][out / "images/objects"] == "/obj"
    script = seen["script"]
    assert f'$M "/obj/{sha(FILES["ga36/SYSTEM"])}" "::ga36/SYSTEM"' in script
    assert f'$M /obj/{sha(FILES["VERSION"])} ::VERSION' in script
    assert f"dd if=/obj/{sha(PARTS[image.AREA_PART])} " in script
    assert f"dd if=/obj/{sha(PARTS[image.PANEL1_PART])} " in script
    # the work folder goes away
    assert [p.name for p in (tmp_path / "cache").iterdir()] == ["console.img"]


def test_assemble_refuses_missing_objects_and_a_different_fat(out, tmp_path):
    d = _archived_build(out)

    def runner(volumes, script):
        work = next(h for h, g in volumes.items() if g == "/out")
        (work / "console.img").write_bytes(b"card image")
        manifests.write_boot_list(work / image.BOOT_LIST,
                                  {**{p: sha(v) for p, v in FILES.items()}, "boot.ini": sha(b"?")})

    (tmp_path / "cache").mkdir()
    with pytest.raises(image.ConsoleImageError, match="differs from its boot-files.sha256"):
        image.assemble_console_image(d, tmp_path / "cache/console.img", runner)
    assert not (tmp_path / "cache/console.img").exists()
    (out / "images/objects" / sha(PARTS[image.PANEL1_PART])).unlink()
    with pytest.raises(image.ConsoleImageError, match="no object .* for android-boot-panel1"):
        image.assemble_console_image(d, tmp_path / "cache/console.img", runner)


def test_flash_uses_the_zst_or_assembles_from_the_objects(out, tmp_path, monkeypatch):
    console = get_image("console")
    d = _archived_build(out)
    assert flash.find_build(console) == (d, None)
    calls = []

    def assemble(build_dir, dest, runner=None):
        calls.append(build_dir)
        dest.write_bytes(b"card image")
        return dest
    monkeypatch.setattr(image, "assemble_console_image", assemble)
    img = flash.image_file(d, None)
    assert img == tmp_path / f"cache/flash/console-{BUILD}.img"
    assert img.read_bytes() == b"card image" and calls == [d]
    flash.image_file(d, None)                       # reused, not assembled again
    assert calls == [d]
    # with a .img.zst it is the one written
    (d / f"console-{BUILD}.img.zst").write_bytes(b"zst")
    assert flash.find_build(console) == (d, d / f"console-{BUILD}.img.zst")
    # neither: refused
    (d / f"console-{BUILD}.img.zst").unlink()
    (d / image.IMAGE_PARTS).unlink()
    with pytest.raises(flash.FlashError, match="r36os build console"):
        flash.find_build(console)


def test_archive_keeps_the_image_parts_with_the_build(out, tmp_path):
    from r36os import version

    work = tmp_path / "console"
    work.mkdir()
    img = work / "console.img"
    img.write_bytes(b"\x00" * 4096)
    (work / image.IMAGE_PARTS).write_text(image.format_image_parts(
        {n: sha(v) for n, v in PARTS.items()}))
    v = version.current(time.mktime((2026, 11, 17, 10, 0, 0, 0, 0, -1)))
    dest = archive.archive_image(get_image("console"), img, v, manifests={})
    assert (dest / image.IMAGE_PARTS).read_text() == (work / image.IMAGE_PARTS).read_text()
    assert f"  {image.IMAGE_PARTS}\n" in (dest / "SHA256SUMS").read_text()


# --- r36os clean -----------------------------------------------------------------------

def _old(path):
    t = time.time() - 2 * clean.OBJECT_MIN_AGE
    os.utime(path, (t, t))


def _clean_tree(tmp_path):
    repo, out, cache = tmp_path / "repo", tmp_path / "repo/out", tmp_path / "cache"
    objects = out / "images/objects"
    objects.mkdir(parents=True)
    stamps = [f"2026111{d}-120000" for d in range(5)]
    for i, s in enumerate(stamps):
        d = out / "images/console" / s
        d.mkdir(parents=True)
        own = f"system {i}".encode()
        manifests.write_boot_list(d / image.BOOT_LIST, {"boot.ini": sha(b"ini"),
                                                         "ga36/SYSTEM": sha(own),
                                                         "VERSION": sha(s.encode())})
        for data in (b"ini", own, s.encode()):
            (objects / sha(data)).write_bytes(data)
    (out / "images/console/latest").symlink_to(stamps[-1])
    (objects / sha(b"orphan")).write_bytes(b"orphan")
    (objects / f"{sha(b'storing')}.tmp").write_bytes(b"storing")
    for f in objects.iterdir():
        _old(f)
    (objects / sha(b"just stored")).write_bytes(b"just stored")     # a build running now
    return repo, out, cache, stamps, objects


def test_clean_removes_the_objects_no_kept_build_cites(tmp_path):
    repo, out, cache, stamps, objects = _clean_tree(tmp_path)
    to_remove, review = clean.plan(repo, out, cache, "d" * 16, keep=3, cited=set())
    builds = {i.path.name for i in to_remove if i.path.parent.name == "console"}
    assert builds == {stamps[0], stamps[1]}
    (item,) = [i for i in to_remove if i.path == objects]
    gone = {p.name for p in item.members}
    # the files only the two removed builds had, and the orphan; the shared boot.ini stays
    assert gone == {sha(b"system 0"), sha(b"system 1"), sha(stamps[0].encode()),
                    sha(stamps[1].encode()), sha(b"orphan")}
    assert item.size == sum(len(x) for x in (b"system 0", b"system 1", b"orphan")) + 2 * 15
    clean.remove(to_remove, repo, out, cache)
    left = {p.name for p in objects.iterdir()}
    assert sha(b"ini") in left and sha(b"system 4") in left
    assert sha(b"just stored") in left and f"{sha(b'storing')}.tmp" in left
    assert not gone & left
    # every kept build still has all its objects (push and flash need them)
    for s in stamps[2:]:
        lst = manifests.read_boot_list(out / "images/console" / s / image.BOOT_LIST)
        assert manifests.missing_objects(objects, lst) == []


def test_clean_keeps_every_object_when_a_kept_list_is_garbled(tmp_path):
    repo, out, cache, stamps, objects = _clean_tree(tmp_path)
    bad = out / "images/console" / stamps[-1] / image.BOOT_LIST
    bad.write_text("garbled\n")
    to_remove, review = clean.plan(repo, out, cache, "d" * 16, keep=3, cited=set())
    assert not [i for i in to_remove if i.path == objects]
    assert [i.path for i in review if "objects stay" in i.reason] == [bad]
