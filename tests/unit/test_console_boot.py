"""Boot area of the console image (single card for the GA36 and the R36S): shrunk boot0
(D3), R36S factory chain (D4) and the combined layout (D2)."""

import hashlib
import random
import struct
from compression import zstd
from pathlib import Path

import pytest

from lume_tool import bootarea, r36s_vendor, vendor
from lume_tool.paths import cache_dir

S = 512


def _sum_words(data: bytes) -> int:
    # independent of vendor.egon_checksum: the field at 0x0C counts as the stamp
    words = struct.unpack(f"<{len(data) // 4}I", data)
    return (sum(words) - words[3] + 0x5F0A6C39) & 0xFFFFFFFF


def _factory_boot0(code_bytes: int = 23 * 1024) -> bytearray:
    rnd = random.Random(16)
    boot0 = bytearray(b"\xff" * 32768)
    boot0[:code_bytes] = bytes(rnd.getrandbits(8) for _ in range(code_bytes))
    boot0[4:12] = b"eGON.BT0"
    struct.pack_into("<I", boot0, 0x10, 32768)
    struct.pack_into("<I", boot0, 0x0C, _sum_words(bytes(boot0)))
    return boot0


def _area_with(boot0: bytes, sectors: int = 128) -> bytearray:
    area = bytearray(sectors * S)
    area[16 * S:16 * S + len(boot0)] = boot0
    return area


def test_checksum_reproduces_factory_sum():
    boot0 = _factory_boot0()
    assert vendor.egon_checksum(bytes(boot0)) == struct.unpack_from("<I", boot0, 0x0C)[0]


def test_shrink_boot0_rewrites_size_and_checksum():
    boot0 = _factory_boot0()
    area = _area_with(boot0)
    vendor.shrink_boot0(area)
    new = bytes(area[16 * S:64 * S])
    assert new[4:12] == b"eGON.BT0"
    assert struct.unpack_from("<I", new, 0x10)[0] == 24576
    assert struct.unpack_from("<I", new, 0x0C)[0] == _sum_words(new)
    # code untouched, sectors 64-79 free for the R36S idbloader
    assert new[0x14:] == bytes(boot0[0x14:24576])
    assert area[64 * S:80 * S] == bytes(16 * S)


def test_shrink_boot0_refuses_code_past_24k():
    boot0 = _factory_boot0()
    boot0[24576 + 100] = 0x00
    with pytest.raises(vendor.VendorAreaError, match="past its first 24 KiB"):
        vendor.shrink_boot0(_area_with(boot0))


def test_shrink_boot0_requires_egon():
    with pytest.raises(vendor.VendorAreaError, match="eGON.BT0"):
        vendor.shrink_boot0(bytearray(128 * S))


_CACHED = cache_dir() / "vendor/ga36-factory-128M.bin"


@pytest.mark.skipif(not _CACHED.exists(), reason="GA36 factory area not in the cache")
def test_shrink_matches_sums_measured_on_device():
    # P-21: factory sum 0x67972d80; the shrunk boot0 that booted the GA36 has 0x67971580
    with open(_CACHED, "rb") as f:
        area = bytearray(f.read(128 * S))
    assert struct.unpack_from("<I", area, 16 * S + 0x0C)[0] == 0x67972D80
    vendor.shrink_boot0(area)
    assert struct.unpack_from("<I", area, 16 * S + 0x0C)[0] == 0x67971580


# --- R36S factory chain (D4) ---------------------------------------------------------

def _r36s_card() -> bytes:
    card = bytearray(r36s_vendor.READ_SECTORS * S)
    card[64 * S:65 * S] = b"\x3b" * S                     # idbloader
    card[16384 * S:16384 * S + 8] = b"LOADER  "           # uboot.img
    card[24576 * S:24576 * S + 4] = b"BL3X"               # trust.img
    return bytes(card)


@pytest.fixture
def synthetic_chain(monkeypatch, tmp_path):
    """REGIONS with the SHA256 of the synthetic card, and an empty cache."""
    card = _r36s_card()
    regions = tuple(
        r36s_vendor.FactoryRegion(r.name, r.start, r.end,
                                  hashlib.sha256(card[r.start * S:r.end * S]).hexdigest())
        for r in r36s_vendor.REGIONS)
    monkeypatch.setattr(r36s_vendor, "REGIONS", regions)
    monkeypatch.setenv("LUME_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv(r36s_vendor.ENV_VAR, raising=False)
    return card


def test_r36s_regions_match_the_measured_card():
    # the layout the BROM and the factory U-Boot read (P-21)
    assert [(r.start, r.end) for r in r36s_vendor.REGIONS] == [(64, 406), (16384, 32768)]
    assert r36s_vendor.READ_SECTORS * S == 16 * 1024 * 1024


@pytest.mark.parametrize("compressed", [False, True])
def test_r36s_chain_from_card_copy(synthetic_chain, tmp_path, monkeypatch, compressed):
    card = synthetic_chain + bytes(S * 8)  # a longer copy is fine
    path = tmp_path / ("card.img.zst" if compressed else "card.img")
    path.write_bytes(zstd.compress(card) if compressed else card)
    monkeypatch.setenv(r36s_vendor.ENV_VAR, str(path))
    regions = r36s_vendor.factory_regions()
    assert regions["idbloader"] == card[64 * S:406 * S]
    assert regions["uboot-trust"][:8] == b"LOADER  "
    # cached: works without the variable
    monkeypatch.delenv(r36s_vendor.ENV_VAR)
    assert r36s_vendor.factory_regions() == regions


def test_r36s_chain_requires_variable(synthetic_chain):
    with pytest.raises(r36s_vendor.R36SFactoryError, match=r36s_vendor.ENV_VAR):
        r36s_vendor.factory_regions()


def test_r36s_chain_refuses_other_card(synthetic_chain, tmp_path, monkeypatch):
    other = bytearray(synthetic_chain)
    other[20000 * S] = 1  # another U-Boot revision
    path = tmp_path / "other.img"
    path.write_bytes(bytes(other))
    monkeypatch.setenv(r36s_vendor.ENV_VAR, str(path))
    with pytest.raises(r36s_vendor.R36SFactoryError, match="uboot-trust.*SHA256"):
        r36s_vendor.factory_regions()


def test_r36s_chain_refuses_short_copy(synthetic_chain, tmp_path, monkeypatch):
    path = tmp_path / "short.img"
    path.write_bytes(synthetic_chain[:20000 * S])
    monkeypatch.setenv(r36s_vendor.ENV_VAR, str(path))
    with pytest.raises(r36s_vendor.R36SFactoryError, match="first 16 MiB"):
        r36s_vendor.factory_regions()


# --- R36S factory BOOT files (task 4.5) ------------------------------------------------

def _fat32(files: dict[str, bytes]) -> bytes:
    """A minimal FAT32 volume (512-byte sectors, one sector per cluster, one FAT) holding
    `files` at the root under long (VFAT) names, as mkfs.vfat + mcopy would."""
    import math
    import struct

    clusters = {n: max(1, math.ceil(len(d) / S)) for n, d in files.items()}
    total = 1 + sum(clusters.values())            # root dir + files
    fat_sectors = math.ceil((total + 2) * 4 / S)
    reserved = 32
    fs = bytearray((reserved + fat_sectors + total) * S)
    bpb = struct.pack("<HBHBHHBHHHII", S, 1, reserved, 1, 0, 0, 0xF8, 0, 0, 0, 0,
                      len(fs) // S)
    fs[11:11 + len(bpb)] = bpb
    struct.pack_into("<IHHI", fs, 36, fat_sectors, 0, 0, 2)  # FAT size, flags, ver, root
    fs[510:512] = b"\x55\xaa"
    fat = reserved * S
    data = (reserved + fat_sectors) * S

    def link(first, count):
        for c in range(first, first + count):
            struct.pack_into("<I", fs, fat + 4 * c, c + 1 if c < first + count - 1 else 0x0FFFFFFF)

    link(2, 1)                                    # root directory
    entries, cluster = b"", 3
    for i, (name, content) in enumerate(files.items()):
        short = f"F{i:07d}TXT".encode()
        chk = 0
        for b in short:
            chk = (((chk & 1) << 7) + (chk >> 1) + b) & 0xFF
        units = [ord(c) for c in name] + [0]
        units += [0xFFFF] * (-len(units) % 13)
        parts = [units[k:k + 13] for k in range(0, len(units), 13)]
        for seq in range(len(parts), 0, -1):
            u = parts[seq - 1]
            e = bytearray(32)
            e[0] = seq | (0x40 if seq == len(parts) else 0)
            e[1:11] = struct.pack("<5H", *u[0:5])
            e[11], e[13] = 0x0F, chk
            e[14:26] = struct.pack("<6H", *u[5:11])
            e[28:32] = struct.pack("<2H", *u[11:13])
            entries += bytes(e)
        e = bytearray(32)
        e[0:11] = short
        struct.pack_into("<H", e, 20, cluster >> 16)
        struct.pack_into("<HI", e, 26, cluster & 0xFFFF, len(content))
        entries += bytes(e)
        link(cluster, clusters[name])
        off = data + (cluster - 2) * S
        fs[off:off + len(content)] = content
        cluster += clusters[name]
    fs[data:data + len(entries)] = entries       # root directory (one cluster is enough)
    return bytes(fs)


BOOT_CONTENT = {"rg351mp-kernel.dtb": b"\xd0\x0d\xfe\xed dtb" * 40,
                "rg351p-kernel.dtb": b"\xd0\x0d\xfe\xed dtb" * 40,
                "logo.bmp": b"BM" + bytes(1500),
                "boot.ini": b"odroidgoa-uboot-config\n"}


def _card_with_boot(files: dict[str, bytes]) -> bytes:
    import struct

    start = 2048
    fs = _fat32(files)
    card = bytearray(start * S) + fs
    struct.pack_into("<II", card, 446 + 8, start, len(fs) // S)
    card[446 + 4] = 0x0B
    card[510:512] = b"\x55\xaa"
    return bytes(card)


@pytest.fixture
def synthetic_boot(monkeypatch, tmp_path):
    """BOOT_FILES with the SHA256 of the synthetic files, and an empty cache."""
    monkeypatch.setattr(r36s_vendor, "BOOT_FILES", {
        n: hashlib.sha256(BOOT_CONTENT[n]).hexdigest()
        for n in ("rg351mp-kernel.dtb", "rg351p-kernel.dtb", "logo.bmp")})
    monkeypatch.setenv("LUME_CACHE", str(tmp_path / "cache"))
    monkeypatch.delenv(r36s_vendor.ENV_VAR, raising=False)


def test_fat32_reader_finds_long_names():
    files = r36s_vendor.fat32_root_files(_fat32(BOOT_CONTENT))
    assert files == {n.lower(): d for n, d in BOOT_CONTENT.items()}


@pytest.mark.parametrize("compressed", [False, True])
def test_r36s_boot_files_from_card_copy(synthetic_boot, tmp_path, monkeypatch, compressed):
    card = _card_with_boot(BOOT_CONTENT)
    path = tmp_path / ("card.img.zst" if compressed else "card.img")
    path.write_bytes(zstd.compress(card) if compressed else card)
    monkeypatch.setenv(r36s_vendor.ENV_VAR, str(path))
    files = r36s_vendor.factory_boot_files()
    assert set(files) == {"rg351mp-kernel.dtb", "rg351p-kernel.dtb", "logo.bmp"}
    assert files["logo.bmp"].read_bytes() == BOOT_CONTENT["logo.bmp"]
    monkeypatch.delenv(r36s_vendor.ENV_VAR)          # cached: no copy needed any more
    assert r36s_vendor.factory_boot_files() == files


def test_r36s_boot_files_require_variable(synthetic_boot):
    with pytest.raises(r36s_vendor.R36SFactoryError, match=r36s_vendor.ENV_VAR):
        r36s_vendor.factory_boot_files()


def test_r36s_boot_files_refuse_other_logo(synthetic_boot, tmp_path, monkeypatch):
    other = dict(BOOT_CONTENT, **{"logo.bmp": b"BM" + bytes(1499) + b"\x01"})
    path = tmp_path / "other.img"
    path.write_bytes(_card_with_boot(other))
    monkeypatch.setenv(r36s_vendor.ENV_VAR, str(path))
    with pytest.raises(r36s_vendor.R36SFactoryError, match="logo.bmp has SHA256"):
        r36s_vendor.factory_boot_files()


def test_r36s_boot_files_refuse_missing_file(synthetic_boot, tmp_path, monkeypatch):
    path = tmp_path / "nologo.img"
    path.write_bytes(_card_with_boot({k: v for k, v in BOOT_CONTENT.items() if k != "logo.bmp"}))
    monkeypatch.setenv(r36s_vendor.ENV_VAR, str(path))
    with pytest.raises(r36s_vendor.R36SFactoryError, match="no logo.bmp"):
        r36s_vendor.factory_boot_files()


def test_r36s_boot_files_match_the_measured_card():
    from pathlib import Path

    boot = Path(__file__).resolve().parents[2] / "out/r36s-factory/boot.img"
    if not boot.exists():
        pytest.skip("no copy of the factory BOOT in out/r36s-factory")
    files = r36s_vendor.fat32_root_files(boot.read_bytes())
    for name, sha in r36s_vendor.BOOT_FILES.items():
        assert hashlib.sha256(files[name]).hexdigest() == sha, name


# --- combined area (D2) --------------------------------------------------------------

def _ga36_area() -> bytearray:
    area = bytearray(bootarea.AREA_SECTORS * S)
    area[1 * S:2 * S] = b"\x11" * S                      # factory area
    boot0 = _factory_boot0()
    area[16 * S:16 * S + len(boot0)] = boot0
    area[80 * S:278 * S] = b"\x22" * (198 * S)            # RSAK, unused
    area[38192 * S:38192 * S + 8] = b"UBOOT2017"[:8]      # vendor U-Boot
    area[172032 * S:172032 * S + 8] = b"ANDROID!"
    return area


def _r36s_regions() -> dict[str, bytes]:
    card = _r36s_card()
    return {r.name: card[r.start * S:r.end * S] for r in r36s_vendor.REGIONS}


def test_layout_table_is_ordered_and_disjoint():
    starts = [(r.start, r.end) for r in bootarea.LAYOUT]
    assert starts == sorted(starts)
    for (_, end), (start, _) in zip(starts, starts[1:]):
        assert end <= start
    assert bootarea.LAYOUT[-1].end <= bootarea.AREA_SECTORS == 262144
    assert {(r.start, r.end) for r in bootarea.LAYOUT if r.origin == "r36s"} == {
        (r.start, r.end) for r in r36s_vendor.REGIONS}


def test_assemble_places_both_chains():
    area = bootarea.assemble(bytes(_ga36_area()), _r36s_regions())
    assert len(area) == 128 * 1024 * 1024
    assert area[1 * S:2 * S] == b"\x11" * S                              # sector 1
    assert area[16 * S + 4:16 * S + 12] == b"eGON.BT0"                   # sector 16
    assert struct.unpack_from("<I", area, 16 * S + 0x10)[0] == 24576
    assert area[64 * S:65 * S] == b"\x3b" * S                            # sector 64
    assert area[80 * S:406 * S] == bytes(326 * S)                        # RSAK gone
    assert area[16384 * S:16384 * S + 8] == b"LOADER  "                  # sector 16384
    assert area[24576 * S:24576 * S + 4] == b"BL3X"                      # sector 24576
    assert area[38192 * S:38192 * S + 8] == b"UBOOT201"                  # sector 38192
    assert area[172032 * S:172032 * S + 8] == b"ANDROID!"                # sector 172032


def test_assemble_lists_conflicting_sectors():
    ga36 = _ga36_area()
    ga36[300 * S] = 1                      # data after the RSAK, under the idbloader
    ga36[20000 * S:20002 * S] = b"\x01" * (2 * S)  # data under uboot.img
    with pytest.raises(bootarea.BootAreaError,
                       match=r"idbloader: 300; uboot-trust: 20000-20001"):
        bootarea.assemble(bytes(ga36), _r36s_regions())


# --- console BOOT (D5, task 5.2) ------------------------------------------------------

MiB = 2**20


def _boot_sizes(ga36_runtime=260 * MiB, r36s_runtime=262 * MiB, image=45 * MiB,
                r36s_modules=15 * MiB):
    sizes = {"boot.ini": 600, "r36s/Image": image, "dtbs/rk3326/rk3326-r36s-v5.dtb": 60_000,
             "ga36/zImage": 6 * MiB, "dtbs/a33/sun8i-a33-ga36-mb-v1.2-panel1.dtb": 30_000,
             "ga36/SLOTS": 6000, "r36s/SLOTS": 6000}
    for console, runtime, modules in (("ga36", ga36_runtime, 2 * MiB),
                                      ("r36s", r36s_runtime, r36s_modules)):
        sizes.update({f"{console}/slot/base-000000000000": 22 * MiB,
                      f"{console}/slot/runtime-000000000000": runtime,
                      f"{console}/slot/lume-000000000000": 3 * MiB,
                      f"{console}/slot/modules-000000000000": modules})
    return sizes


def _slot_set(layer_out: Path, console: str) -> dict[str, Path]:
    """A slot set in <layer>/slot/ as the build leaves it; BOOT path -> file."""
    from lume_tool import manifests

    sdir = layer_out / manifests.SLOTS_DIR
    sdir.mkdir(parents=True, exist_ok=True)
    made, lower = [], ()
    for name in manifests.REQUIRED_SLOTS:
        data = f"{console} {name}".encode()
        sha = hashlib.sha256(data).hexdigest()
        slot = manifests.Slot(name=name, sha256=sha, size=len(data),
                              lower=lower if name != "modules" else ())
        (sdir / Path(slot.file).name).write_bytes(data)
        if name != "modules":
            lower = (*lower, (name, sha))
        made.append(slot)
    manifests.write_slots(sdir / "SLOTS", manifests.SlotSet(build="1", console=console,
                                                             slots=tuple(made)))
    return {f"{console}/SLOTS": sdir / "SLOTS",
            **{f"{console}/{s.file}": sdir / Path(s.file).name for s in made}}


def test_console_boot_files_layout(tmp_path):
    from lume_tool import image

    files = image.console_boot_files(tmp_path / "ga36", tmp_path / "r36s")
    assert {"boot.ini", "ga36/SLOTS", "ga36/zImage", "r36s/SLOTS", "r36s/Image",
            "dtbs/rk3326/rk3326-r36s-v5.dtb"} <= set(files)
    assert files["boot.ini"] == image.REPO_ROOT / "board/r36s/boot.ini"
    # build-speed 7.3: the kernel is the data of the published lume-kernel
    assert files["ga36/zImage"] == tmp_path / "ga36/kernel-pkg/boot/zImage"
    assert files["r36s/Image"] == tmp_path / "r36s/kernel-pkg/boot/Image"
    # build-speed D9: the root of each console is its slot set; without one the SLOTS path
    # is still listed, so the image build says it is missing
    assert files["ga36/SLOTS"] == tmp_path / "ga36/slot/SLOTS"
    # no SYSTEM and no modules image of their own on a new card: the slots replace them
    assert not [p for p in files if p.endswith(("/SYSTEM", "/modules"))]
    want = {**_slot_set(tmp_path / "ga36", "ga36"), **_slot_set(tmp_path / "r36s", "r36s")}
    files = image.console_boot_files(tmp_path / "ga36", tmp_path / "r36s")
    assert {p: s for p, s in files.items() if p.split("/")[0] in ("ga36", "r36s")
            and p.split("/")[1] in ("SLOTS", "slot")} == want
    assert len([p for p in files if p.startswith("r36s/slot/")]) == 4
    # a set of the other console in the folder of this one is refused
    (tmp_path / "x").mkdir()
    _slot_set(tmp_path / "x", "r36s")
    with pytest.raises(Exception, match="not ga36"):
        image.console_boot_files(tmp_path / "x", tmp_path / "r36s")
    (tmp_path / "ga36/kernel-pkg/boot/dtbs/a33/vendor").mkdir(parents=True)
    (tmp_path / "ga36/kernel-pkg/boot/dtbs/a33/a.dtb").write_bytes(b"d")
    (tmp_path / "ga36/kernel-pkg/boot/dtbs/a33/vendor/v.dtb").write_bytes(b"d")
    (tmp_path / "r36s/kernel-pkg/boot/dtbs/rk3326").mkdir(parents=True)
    (tmp_path / "r36s/kernel-pkg/boot/dtbs/rk3326/b.dtb").write_bytes(b"d")
    (tmp_path / "ga36/kernel").mkdir(parents=True)
    (tmp_path / "ga36/kernel/android-boot-panel2.img").write_bytes(b"i")
    files = image.console_boot_files(tmp_path / "ga36", tmp_path / "r36s")
    assert "dtbs/a33/a.dtb" in files and "dtbs/rk3326/b.dtb" in files
    assert files["dtbs/a33/vendor/v.dtb"] == tmp_path / "ga36/kernel-pkg/boot/dtbs/a33/vendor/v.dtb"
    # only what the consoles read: the panel boot images are archived with the build
    assert not [p for p in files if "android-boot" in p]
    assert image.ga36_android_boot_images(tmp_path / "ga36") == {
        "ga36-android-boot-panel2.img": tmp_path / "ga36/kernel/android-boot-panel2.img"}
    assert "android-boot" not in image._CONSOLE.split("# Disk:")[0]
    # boot-dtb-select D8: the DTBs only live in the SoC folders
    assert not [p for p in files if p.startswith("ga36/dtbs/") or p.startswith("r36s/r")]
    # task 4.5: the factory files go to the root of BOOT
    factory = {"rg351mp-kernel.dtb": tmp_path / "a", "logo.bmp": tmp_path / "b"}
    files = image.console_boot_files(tmp_path / "ga36", tmp_path / "r36s", factory)
    assert files["logo.bmp"] == tmp_path / "b" and "rg351mp-kernel.dtb" in files


def test_boot_copy_commands_come_from_the_one_boot_list(tmp_path):
    # usb-device-access 5.1: the FAT is filled from console_boot_files(), the list that
    # flash and push use, with no glob of its own
    from lume_tool import image

    files = {"logo.bmp": tmp_path / "out/factory-boot/logo.bmp",
             "ga36/SYSTEM": tmp_path / "ga36/SYSTEM",
             "dtbs/a33/x.dtb": tmp_path / "ga36/kernel/dtbs/x.dtb"}
    cmds = image.boot_copy_commands(files, {tmp_path / "out": "/out", tmp_path / "ga36": "/ga36"})
    assert cmds["dirs"] == "::dtbs ::dtbs/a33 ::ga36"
    assert cmds["copies"].splitlines() == [
        '$M "/ga36/kernel/dtbs/x.dtb" "::dtbs/a33/x.dtb"', '$M "/ga36/SYSTEM" "::ga36/SYSTEM"',
        '$M "/out/factory-boot/logo.bmp" "::logo.bmp"']
    assert cmds["paths"] == '"dtbs/a33/x.dtb" "ga36/SYSTEM" "logo.bmp" "VERSION"'
    assert not [line for line in image._CONSOLE.splitlines()
                if line.startswith("$M") and "*" in line]          # no glob copies left
    with pytest.raises(image.ConsoleImageError, match="outside the volumes"):
        image.boot_copy_commands({"x": Path("/elsewhere/x")}, {tmp_path: "/out"})


def test_boot_list_is_the_fat_content(tmp_path):
    # the list read back from a real FAT holds every file once, VERSION last, with the
    # SHA256 of what was copied (mtools in the builder, as the image build)
    import hashlib
    import shutil
    import subprocess

    from lume_tool import image
    from lume_tool.container import Container, ensure_builder
    from lume_tool.targets import TARGETS

    if shutil.which("podman") is None:
        pytest.skip("no podman")
    src = tmp_path / "src"
    files = {"boot.ini": b"ini", "ga36/SYSTEM": b"sys" * 1000, "dtbs/a33/p1.dtb": b"d1",
             "dtbs/rk3326/r.dtb": b"d2"}
    for path, data in files.items():
        (src / path).parent.mkdir(parents=True, exist_ok=True)
        (src / path).write_bytes(data)
    (tmp_path / "VERSION").write_text("v\n")
    cmds = image.boot_copy_commands({p: src / p for p in files}, {tmp_path: "/out"})
    script = image._CONSOLE.split("# at least")[0].format(
        boot_bytes=64 * 2**20, boot_start=0, version="/out/VERSION",
        **cmds)                                         # FAT32 needs some size
    r = subprocess.run(Container(image=ensure_builder(TARGETS["vm"]),
                                 volumes={tmp_path: "/out"}).argv(script),
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    listed = image.read_boot_list(tmp_path / image.BOOT_LIST)
    want = {**files, "VERSION": b"v\n"}
    assert [p for p, _ in listed] == [*sorted(files), "VERSION"]
    assert dict(listed) == {p: hashlib.sha256(d).hexdigest() for p, d in want.items()}


def test_archived_boot_list_matches_the_build():
    # the latest console build: its boot-files.sha256 names what console_boot_files lists
    from lume_tool import image
    from lume_tool.archive import images_dir
    from lume_tool.targets import IMAGES

    path = images_dir(IMAGES["console"]) / "latest" / image.BOOT_LIST
    if not path.exists():
        pytest.skip("no console build with a BOOT list yet")
    names = [p for p, _ in image.read_boot_list(path)]
    assert names[-1] == "VERSION" and len(set(names)) == len(names)
    for want in ("boot.ini", "ga36/zImage", "r36s/Image", f"dtbs/rk3326/{image.R36S_DTB}"):
        assert want in names, want
    if "ga36/SLOTS" not in names:
        # a build before the slots (build-speed D9) carries the SYSTEM of each console
        assert "ga36/SYSTEM" in names and "r36s/SYSTEM" in names
        pytest.skip("latest console build is older than the slots")
    for console in ("ga36", "r36s"):
        slots = sorted(p.split("/")[2].split("-")[0] for p in names
                       if p.startswith(f"{console}/slot/"))
        assert slots == ["base", "lume", "modules", "runtime"], (console, slots)
        assert f"{console}/SYSTEM" not in names


def test_console_boot_within_limits():
    from lume_tool import image

    image.check_console_boot(_boot_sizes())
    # both consoles with ~330 MiB of slots, counted twice (the previous sets): ~1.4 GiB
    image.check_console_boot(_boot_sizes(ga36_runtime=300 * MiB, r36s_runtime=300 * MiB))


@pytest.mark.parametrize("which", ["ga36", "r36s"])
def test_console_boot_refuses_slots_above_448_mib(which):
    from lume_tool import image

    sizes = _boot_sizes(**{f"{which}_runtime": 448 * MiB - 22 * MiB - 3 * MiB})
    with pytest.raises(image.ConsoleImageError, match=f"slots of {which}.*448 MiB"):
        image.check_console_boot(sizes)
    sizes = _boot_sizes(**{f"{which}_runtime": 200 * MiB})
    sizes[f"{which}/slot/core-x-000000000000"] = 300 * MiB    # every slot counts
    with pytest.raises(image.ConsoleImageError, match=f"slots of {which}.*448 MiB"):
        image.check_console_boot(sizes)


def test_console_boot_needs_64_mib_free():
    from lume_tool import image

    with pytest.raises(image.ConsoleImageError, match="needs at least 64 MiB"):
        image.check_console_boot(_boot_sizes(image=900 * MiB))


def test_console_boot_counts_the_previous_slot_set():
    # system-image: 64 MiB free counting the previous set a push keeps (SLOTS.old), taken
    # as large as the new one: a slot of 60 MiB more takes 120 MiB of the free space
    from lume_tool import image

    sizes = _boot_sizes(ga36_runtime=400 * MiB, r36s_runtime=400 * MiB)
    files = sum(-(-s // 4096) * 4096 for s in sizes.values())
    slots = sum(-(-s // 4096) * 4096 for p, s in sizes.items() if "/slot/" in p)
    free = 4 * 2**30 // 2 - 16 * MiB - files - slots
    sizes["r36s/Image"] += free - 64 * MiB               # exactly 64 MiB left
    image.check_console_boot(sizes)
    sizes["r36s/Image"] += 4096
    with pytest.raises(image.ConsoleImageError, match="previous slot set"):
        image.check_console_boot(sizes)


def test_console_image_script_only_uses_mounted_paths(tmp_path, monkeypatch):
    """Every /<dir>/ the assembly script reads is a mounted volume (the first build failed:
    the boot area folder and /out were the same path, and the dict kept only one)."""
    import re as _re

    from lume_tool import image, version

    monkeypatch.setenv("LUME_OUT", str(tmp_path))
    # the kernel and the DTBs as extracted from the published packages (build-speed 7.3)
    for f in ("ga36/kernel-pkg/boot/zImage", "ga36/kernel-pkg/boot/dtbs/a33/a.dtb",
              "ga36/kernel/android-boot-panel1.img", "r36s/kernel-pkg/boot/Image",
              "r36s/kernel-pkg/boot/dtbs/rk3326/rk3326-r36s-v5.dtb"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes(b"x")
    ga36_set = _slot_set(tmp_path / "ga36", "ga36")
    _slot_set(tmp_path / "r36s", "r36s")
    # the build checks the lume-select node of every DTB (boot-dtb-select D3)
    from lume_tool import fdt
    for f, ident in (("ga36/kernel-pkg/boot/dtbs/a33/a.dtb", "a"),
                     ("r36s/kernel-pkg/boot/dtbs/rk3326/rk3326-r36s-v5.dtb", "r36s-v5")):
        node = fdt.Node(props={"lume,id": fdt.s(ident), "lume,priority": fdt.u32(0),
                               "lume,default": b""})
        (tmp_path / f).write_bytes(fdt.build(fdt.Node(children={"lume-select": node})))

    def fake_area(dest):
        dest.write_bytes(b"area")
        return dest

    captured = {}

    class FakeContainer:
        def __init__(self, image, volumes):
            captured["volumes"] = volumes

        def sh(self, script):
            captured["script"] = script

    factory = tmp_path / "factory"
    factory.mkdir()
    for n in r36s_vendor.BOOT_FILES:
        (factory / n).write_bytes(b"f")
    monkeypatch.setattr(r36s_vendor, "factory_boot_files",
                        lambda: {n: factory / n for n in r36s_vendor.BOOT_FILES})
    monkeypatch.setattr(image.bootarea, "write_console_area", fake_area)
    monkeypatch.setattr(image, "Container", FakeContainer)
    monkeypatch.setattr(image, "ensure_builder", lambda target: "builder")
    stored = {}
    monkeypatch.setattr(image, "store_build_objects",
                        lambda out, files, parts: stored.update(files=files, parts=parts))
    image.build_console_image(version.current())
    # every BOOT file, VERSION and both image parts go to the objects (build-speed D10)
    assert {"VERSION", "ga36/SLOTS", "r36s/SLOTS", *ga36_set} <= set(stored["files"])
    assert not [p for p in stored["files"] if p.endswith(("/SYSTEM", "/modules"))]
    for path in ga36_set:                                    # slots copied to the FAT
        assert f'"::{path}"' in captured["script"]
    assert set(stored["parts"]) == {image.AREA_PART, image.PANEL1_PART}

    mounts = set(captured["volumes"].values())
    assert len(mounts) == len(captured["volumes"])
    # paths of the container itself (/dev/null) are not volumes
    used = set(_re.findall(r"(?<![\w$])(/[a-z0-9]+)/", captured["script"])) - {"/dev", "/tmp"}
    # /out/imgwork is the scratch folder inside /out
    assert used <= mounts, used - mounts
    assert {"/out", "/ga36", "/r36s", "/board"} <= used


def test_boot_ini_loads_the_r36s_kernel_and_dtb():
    from lume_tool import image

    ini = (image.REPO_ROOT / "board/r36s/boot.ini").read_text()
    assert ini.startswith("odroidgoa-uboot-config\n")   # the header the factory U-Boot wants
    assert "load mmc 1:1 ${loadaddr} r36s/Image" in ini
    assert f"load mmc 1:1 ${{dtb_loadaddr}} dtbs/rk3326/{image.R36S_DTB}" in ini
    assert "booti ${loadaddr} - ${dtb_loadaddr}" in ini      # no uInitrd: built in
    assert "bootargs" not in ini.replace("no bootargs", "")  # CMDLINE_FORCE in the kernel


@pytest.mark.skipif(not _CACHED.exists(), reason="GA36 factory area not in the cache")
def test_real_ga36_area_has_room_for_the_r36s_chain():
    data = _CACHED.read_bytes()
    for r in r36s_vendor.REGIONS:
        assert bootarea.conflicts(data, r.start, r.end) == []
