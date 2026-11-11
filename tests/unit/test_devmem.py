"""r36os-devmem: read or write one 32-bit register (tested on a regular file, not /dev/mem)."""

import re
import shutil
import struct
import subprocess
from pathlib import Path

import pytest

from r36os.paths import REPO_ROOT

APORT = REPO_ROOT / "aports/r36os-devmem"
CC = shutil.which("cc") or shutil.which("gcc")


def test_aport_is_armv7_only_listed_for_the_ga36_and_checksummed():
    apkbuild = (APORT / "APKBUILD").read_text()
    assert re.search(r'^arch="armv7"$', apkbuild, re.M)           # only the A33 has the problem
    import hashlib
    digest = hashlib.sha512((APORT / "devmem.c").read_bytes()).hexdigest()
    assert f"{digest}  devmem.c" in apkbuild
    ga36 = (REPO_ROOT / "board/ga36/hw-packages.txt").read_text().split()
    assert "r36os-devmem" in ga36
    assert "r36os-devmem" not in (REPO_ROOT / "rootfs/packages.txt").read_text().split()


@pytest.fixture(scope="module")
def devmem(tmp_path_factory) -> Path:
    if CC is None:
        pytest.skip("no C compiler")
    out = tmp_path_factory.mktemp("devmem") / "r36os-devmem"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-o", str(out), str(APORT / "devmem.c")],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out


def _run(devmem: Path, f: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run([str(devmem), "-f", str(f), *args], capture_output=True, text=True)


def _regfile(tmp_path: Path, size: int = 3 * 4096) -> Path:
    f = tmp_path / "regs"
    f.write_bytes(bytes(size))
    return f


def test_writes_one_32_bit_register_and_prints_it(devmem, tmp_path):
    f = _regfile(tmp_path)
    r = _run(devmem, f, "0x1004", "0xc8000a00")
    assert r.returncode == 0, r.stderr
    assert r.stdout == "0xc8000a00\n"
    data = f.read_bytes()
    assert struct.unpack_from("<I", data, 0x1004)[0] == 0xC8000A00
    assert data[:0x1004] == bytes(0x1004) and data[0x1008:] == bytes(len(data) - 0x1008)  # nothing else


def test_reads_without_writing(devmem, tmp_path):
    f = _regfile(tmp_path)
    data = bytearray(f.read_bytes())
    struct.pack_into("<I", data, 0x2008, 0x00000A00)
    f.write_bytes(bytes(data))
    r = _run(devmem, f, "0x2008")
    assert r.returncode == 0 and r.stdout == "0x00000a00\n"
    assert f.read_bytes() == bytes(data)                    # read-only: the file is unchanged


def test_page_offset_is_handled_for_a_real_register_address(devmem, tmp_path):
    # TCON_GINT0 of the A33 is 0x01c0c004: page base 0x01c0c000, offset 4 (here a plain file,
    # so use an address inside it with the same offset within the page)
    f = _regfile(tmp_path)
    assert _run(devmem, f, "0x1004", "0xc8000200").stdout == "0xc8000200\n"
    assert _run(devmem, f, "0x1004").stdout == "0xc8000200\n"


@pytest.mark.parametrize("args", [
    [],                                  # no address
    ["0x1002"],                          # unaligned
    ["zz"],                              # not a number
    ["0x1004", "0x1ffffffff"],           # value does not fit in 32 bits
    ["0x1004", "1", "2"],                # too many arguments
])
def test_bad_arguments_are_refused_with_status_2(devmem, tmp_path, args):
    f = _regfile(tmp_path)
    r = _run(devmem, f, *args)
    assert r.returncode == 2
    assert "usage" in r.stderr
    assert f.read_bytes() == bytes(3 * 4096)                # nothing was written


def test_missing_file_is_an_error(devmem, tmp_path):
    r = _run(devmem, tmp_path / "missing", "0x1004")
    assert r.returncode == 1


def test_source_and_comments_are_in_english():
    text = (APORT / "devmem.c").read_text() + (APORT / "APKBUILD").read_text()
    assert not any(ord(c) > 127 for c in text)
