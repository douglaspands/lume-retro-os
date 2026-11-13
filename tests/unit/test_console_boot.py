"""Boot area of the console image (single card for the GA36 and the R36S): shrunk boot0
(D3), R36S factory chain (D4) and the combined layout (D2)."""

import hashlib
import random
import struct
from compression import zstd

import pytest

from r36os import bootarea, r36s_vendor, vendor
from r36os.paths import cache_dir

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
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "cache"))
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
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "cache"))
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


def _boot_sizes(ga36_system=280 * MiB, r36s_system=300 * MiB, image=45 * MiB):
    return {"boot.ini": 600, "ga36/SYSTEM": ga36_system, "r36s/SYSTEM": r36s_system,
            "r36s/Image": image, "r36s/rk3326-r36s-v5.dtb": 60_000,
            "ga36/dtbs/sun8i-a33-ga36-mb-v1.2-panel1.dtb": 30_000,
            "ga36/android-boot/android-boot-panel1.img": 12 * MiB,
            "ga36/android-boot/android-boot-panel2.img": 12 * MiB}


def test_console_boot_files_layout(tmp_path):
    from r36os import image

    files = image.console_boot_files(tmp_path / "ga36", tmp_path / "r36s")
    assert {"boot.ini", "ga36/SYSTEM", "r36s/SYSTEM", "r36s/Image",
            "r36s/rk3326-r36s-v5.dtb"} <= set(files)
    assert files["boot.ini"] == image.REPO_ROOT / "board/r36s/boot.ini"
    (tmp_path / "ga36/kernel/dtbs").mkdir(parents=True)
    (tmp_path / "ga36/kernel/dtbs/a.dtb").write_bytes(b"d")
    (tmp_path / "ga36/kernel/android-boot-panel2.img").write_bytes(b"i")
    files = image.console_boot_files(tmp_path / "ga36", tmp_path / "r36s")
    assert "ga36/dtbs/a.dtb" in files and "ga36/android-boot/android-boot-panel2.img" in files
    # task 4.5: the factory files go to the root of BOOT
    factory = {"rg351mp-kernel.dtb": tmp_path / "a", "logo.bmp": tmp_path / "b"}
    files = image.console_boot_files(tmp_path / "ga36", tmp_path / "r36s", factory)
    assert files["logo.bmp"] == tmp_path / "b" and "rg351mp-kernel.dtb" in files


def test_console_image_copies_the_factory_files_to_the_boot_root():
    from r36os import image

    assert "$M /out/factory-boot/* ::" in image._CONSOLE


def test_console_boot_within_limits():
    from r36os import image

    image.check_console_boot(_boot_sizes())
    image.check_console_boot(_boot_sizes(ga36_system=448 * MiB, r36s_system=448 * MiB,
                                         image=20 * MiB))


@pytest.mark.parametrize("which", ["ga36", "r36s"])
def test_console_boot_refuses_system_above_448_mib(which):
    from r36os import image

    sizes = _boot_sizes(**{f"{which}_system": 448 * MiB + 1})
    with pytest.raises(image.ConsoleImageError, match=f"{which}/SYSTEM.*448 MiB"):
        image.check_console_boot(sizes)


def test_console_boot_needs_64_mib_free():
    from r36os import image

    with pytest.raises(image.ConsoleImageError, match="needs at least 64 MiB"):
        image.check_console_boot(_boot_sizes(ga36_system=440 * MiB, r36s_system=440 * MiB,
                                             image=1110 * MiB))


def test_console_image_script_only_uses_mounted_paths(tmp_path, monkeypatch):
    """Every /<dir>/ the assembly script reads is a mounted volume (the first build failed:
    the boot area folder and /out were the same path, and the dict kept only one)."""
    import re as _re

    from r36os import image, version

    monkeypatch.setenv("R36OS_OUT", str(tmp_path))
    for f in ("ga36/SYSTEM", "ga36/kernel/dtbs/a.dtb", "ga36/kernel/android-boot-panel1.img",
              "r36s/SYSTEM", "r36s/kernel/Image", "r36s/kernel/dtbs/rk3326-r36s-v5.dtb"):
        (tmp_path / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / f).write_bytes(b"x")

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
    image.build_console_image(version.current())

    mounts = set(captured["volumes"].values())
    assert len(mounts) == len(captured["volumes"])
    # paths of the container itself (/dev/null) are not volumes
    used = set(_re.findall(r"(?<![\w$])(/[a-z0-9]+)/", captured["script"])) - {"/dev", "/tmp"}
    # /out/imgwork is the scratch folder inside /out
    assert used <= mounts, used - mounts
    assert {"/out", "/ga36", "/r36s", "/board"} <= used


def test_boot_ini_loads_the_r36s_kernel_and_dtb():
    from r36os import image

    ini = (image.REPO_ROOT / "board/r36s/boot.ini").read_text()
    assert ini.startswith("odroidgoa-uboot-config\n")   # the header the factory U-Boot wants
    assert "load mmc 1:1 ${loadaddr} r36s/Image" in ini
    assert f"load mmc 1:1 ${{dtb_loadaddr}} r36s/{image.R36S_DTB}" in ini
    assert "booti ${loadaddr} - ${dtb_loadaddr}" in ini      # no uInitrd: built in
    assert "bootargs" not in ini.replace("no bootargs", "")  # CMDLINE_FORCE in the kernel


@pytest.mark.skipif(not _CACHED.exists(), reason="GA36 factory area not in the cache")
def test_real_ga36_area_has_room_for_the_r36s_chain():
    data = _CACHED.read_bytes()
    for r in r36s_vendor.REGIONS:
        assert bootarea.conflicts(data, r.start, r.end) == []
