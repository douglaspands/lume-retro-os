"""lume-cardid: the fingerprint of the ROMS card read past the kernel caches (game-experience-
tuning D11, task 9.3). Tested on synthetic exFAT images built here, byte by byte."""

import hashlib
import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from lume_tool.paths import REPO_ROOT

APORT = REPO_ROOT / "aports/lume-cardid"
CC = shutil.which("cc") or shutil.which("gcc")

SECT = 512
SPC_SHIFT = 3                       # 8 sectors: 4 KiB clusters
CLUSTER = SECT << SPC_SHIFT
FAT_OFF = 24                        # sectors
HEAP_OFF = 64                       # sectors
COUNT = 64                          # clusters
EOC = 0xFFFFFFFF


def _boot_sector() -> bytes:
    b = bytearray(SECT)
    b[0:3] = b"\xeb\x76\x90"
    b[3:11] = b"EXFAT   "
    struct.pack_into("<QQIIIIIIHH", b, 64, 0, HEAP_OFF + COUNT * (CLUSTER // SECT), FAT_OFF, 8,
                     HEAP_OFF, COUNT, 4, 0x1234, 0x0100, 0)
    b[108], b[109], b[110] = 9, SPC_SHIFT, 1
    b[510:512] = b"\x55\xaa"
    return bytes(b)


def _entry_set(name: str, first: int, length: int, *, directory=False, nofat=True,
               mtime=0x5A6B7C8D, mtime_cs=42, deleted=False) -> bytes:
    names = [name[i:i + 15] for i in range(0, len(name), 15)]
    f = bytearray(32)
    f[0] = 0x05 if deleted else 0x85
    f[1] = 1 + len(names)
    struct.pack_into("<H", f, 4, 0x10 if directory else 0x20)
    struct.pack_into("<I", f, 12, mtime)
    f[21] = mtime_cs
    s = bytearray(32)
    s[0] = 0x40 if deleted else 0xC0
    s[1] = 0x01 | (0x02 if nofat else 0)
    s[3] = len(name)
    struct.pack_into("<Q", s, 8, length)
    struct.pack_into("<I", s, 20, first)
    struct.pack_into("<Q", s, 24, length)
    out = bytes(f) + bytes(s)
    for part in names:
        n = bytearray(32)
        n[0] = 0x41 if deleted else 0xC1
        n[2:2 + 2 * len(part)] = part.encode("utf-16-le")
        out += bytes(n)
    return out


class Card:
    """A small exFAT volume: bitmap in cluster 2, root in 4 (chained to 9 when asked), the
    logs folder in 5, the counter file in 6."""

    def __init__(self, path: Path):
        self.path = path
        self.img = bytearray((HEAP_OFF + COUNT * (CLUSTER // SECT)) * SECT)
        self.img[0:SECT] = _boot_sector()
        self.used = set()

    def off(self, cluster: int) -> int:
        return (HEAP_OFF + (cluster - 2) * (CLUSTER // SECT)) * SECT

    def fat(self, cluster: int, value: int):
        struct.pack_into("<I", self.img, FAT_OFF * SECT + 4 * cluster, value)

    def put(self, cluster: int, data: bytes):
        self.img[self.off(cluster):self.off(cluster) + len(data)] = data
        self.used.add(cluster)

    def bitmap(self):
        bm = bytearray(COUNT // 8)
        for c in self.used:
            bm[(c - 2) // 8] |= 1 << ((c - 2) % 8)
        self.img[self.off(2):self.off(2) + len(bm)] = bm

    def standard(self, counter=b"204\n", boot_cluster=6, root_chain=False, logs_name="logs",
                 logs_nofat=True):
        bm_entry = bytearray(32)
        bm_entry[0] = 0x81
        struct.pack_into("<IQ", bm_entry, 20, 2, COUNT // 8)
        self.used.update({2, 3})
        self.fat(2, EOC)
        self.fat(3, EOC)
        logs = _entry_set(logs_name, 5, CLUSTER, directory=True, nofat=logs_nofat)
        root = bytes(bm_entry) + _entry_set("roms", 10, CLUSTER, directory=True)
        if root_chain:
            # the first cluster full of deleted entries: logs is found in the second one (FAT)
            root += _entry_set("old", 11, 0, deleted=True)
            while len(root) < CLUSTER:
                root += b"\x05" + bytes(31)                 # deleted entries up to the end

            self.put(4, root)
            self.put(9, logs)
            self.fat(4, 9)
            self.fat(9, EOC)
        else:
            self.put(4, root + logs)
            self.fat(4, EOC)
        if not logs_nofat:
            self.fat(5, EOC)
        self.put(5, _entry_set("events.log", 7, 100) + _entry_set(".boot", boot_cluster, len(counter)))
        self.put(boot_cluster, counter)
        self.bitmap()
        return self

    def save(self) -> Path:
        self.path.write_bytes(bytes(self.img))
        return self.path


def test_aport_is_built_for_every_console_listed_and_checksummed():
    apkbuild = (APORT / "APKBUILD").read_text()
    assert re.search(r'^arch="x86_64 armv7 aarch64"$', apkbuild, re.M)
    digest = hashlib.sha512((APORT / "cardid.c").read_bytes()).hexdigest()
    assert f"{digest}  cardid.c" in apkbuild
    assert "lume-cardid" in (REPO_ROOT / "rootfs/packages.txt").read_text().split()


def test_source_and_comments_are_in_english():
    text = (APORT / "cardid.c").read_text() + (APORT / "APKBUILD").read_text()
    assert not any(ord(c) > 127 for c in text)


@pytest.fixture(scope="module")
def cardid(tmp_path_factory) -> Path:
    if CC is None:
        pytest.skip("no C compiler")
    out = tmp_path_factory.mktemp("cardid") / "lume-cardid"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-o", str(out), str(APORT / "cardid.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _run(cardid: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(cardid), *args], capture_output=True, text=True)


def _line(cardid: Path, img: Path, *path: str) -> str:
    r = _run(cardid, str(img), *path)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_reads_the_counter_its_entry_and_the_bitmap(cardid, tmp_path):
    img = Card(tmp_path / "card").standard().save()
    before = img.read_bytes()
    out = _line(cardid, img)
    assert re.fullmatch(r"boot=204 at=6:4:5a6b7c8d\.42 bitmap=[0-9a-f]{16}\n", out), out
    assert img.read_bytes() == before                          # read-only


def test_the_same_card_gives_the_same_line(cardid, tmp_path):
    a = _line(cardid, Card(tmp_path / "a").standard().save())
    b = _line(cardid, Card(tmp_path / "b").standard().save())
    assert a == b


def test_a_boot_elsewhere_changes_the_line_even_with_the_old_cluster_intact(cardid, tmp_path):
    # the other console rewrote .boot by temp + rename: a new cluster with 205, the old cluster
    # freed but still holding 204 (exFAT does not clear it). A read by the old entry would say
    # "unchanged"; the tool follows the entry on the card.
    before = _line(cardid, Card(tmp_path / "a").standard().save())
    card = Card(tmp_path / "b").standard(counter=b"205\n", boot_cluster=8)
    card.put(6, b"204\n")
    card.used.discard(6)
    card.bitmap()
    after = _line(cardid, card.save())
    assert after.startswith("boot=205 at=8:4:") and after != before


def test_the_counter_alone_changes_the_line(cardid, tmp_path):
    a = _line(cardid, Card(tmp_path / "a").standard().save())
    b = _line(cardid, Card(tmp_path / "b").standard(counter=b"215\n").save())
    assert a.split()[0] == "boot=204" and b.split()[0] == "boot=215"


def test_the_bitmap_alone_changes_the_line(cardid, tmp_path):
    a = Card(tmp_path / "a").standard()
    b = Card(tmp_path / "b").standard()
    b.used.add(40)                                             # a PC copied a file
    b.bitmap()
    la, lb = _line(cardid, a.save()), _line(cardid, b.save())
    assert la.split()[:2] == lb.split()[:2] and la != lb


def test_a_root_directory_on_a_fat_chain_and_deleted_entries(cardid, tmp_path):
    out = _line(cardid, Card(tmp_path / "card").standard(root_chain=True).save())
    assert out.startswith("boot=204 at=6:4:")


def test_a_folder_on_a_fat_chain_and_names_without_case(cardid, tmp_path):
    out = _line(cardid, Card(tmp_path / "card").standard(logs_name="LOGS", logs_nofat=False).save())
    assert out.startswith("boot=204 at=6:4:")


def test_a_missing_counter_is_a_dash(cardid, tmp_path):
    img = Card(tmp_path / "card").standard().save()
    out = _line(cardid, img, "logs/.nothing")
    assert re.fullmatch(r"boot=- at=- bitmap=[0-9a-f]{16}\n", out)
    assert _line(cardid, img, "nofolder/.boot").startswith("boot=- at=- ")


def test_not_exfat_or_missing_is_status_1(cardid, tmp_path):
    junk = tmp_path / "junk"
    junk.write_bytes(bytes(8192))
    assert _run(cardid, str(junk)).returncode == 1
    assert _run(cardid, str(tmp_path / "missing")).returncode == 1
    short = tmp_path / "short"
    short.write_bytes(_boot_sector())                          # cut after the boot sector
    assert _run(cardid, str(short)).returncode == 1


@pytest.mark.parametrize("args", [[], ["-x"], ["a", "b", "c"], ["--shutdown"]])
def test_bad_arguments_are_status_2(cardid, args):
    r = _run(cardid, *args)
    assert r.returncode == 2 and "usage" in r.stderr


def test_shutdown_outside_exfat_fails_cleanly(cardid, tmp_path):
    r = _run(cardid, "--shutdown", str(tmp_path))
    assert r.returncode == 1 and "shutdown of" in r.stderr


def test_reads_bypass_the_page_cache():
    src = (APORT / "cardid.c").read_text()
    assert "O_DIRECT" in src and "posix_memalign" in src
