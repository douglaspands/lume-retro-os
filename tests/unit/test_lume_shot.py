"""lume-shot (lume-launcher D12, task 8.3): the screen capture over the cable. The DRM
part only runs on the console; here the --raw mode feeds a framebuffer from a file, and the
PNG is decoded back to check every pixel, the row pitch and the refused formats."""

import shutil
import struct
import subprocess
import zlib

import pytest

from lume_tool.paths import REPO_ROOT

APORT = REPO_ROOT / "aports/lume-input"
CC = shutil.which("cc") or shutil.which("gcc")


@pytest.fixture(scope="module")
def shot(tmp_path_factory):
    if CC is None:
        pytest.skip("no C compiler")
    exe = tmp_path_factory.mktemp("shot") / "lume-shot"
    r = subprocess.run([CC, "-Wall", "-Wextra", "-Werror", "-o", str(exe),
                        str(APORT / "shot.c"), "-lz"], capture_output=True, text=True)
    if r.returncode != 0 and "zlib.h" in r.stderr:
        pytest.skip("no zlib headers on this host")
    assert r.returncode == 0, r.stderr
    return exe


def read_png(path):
    """(width, height, rows of (r, g, b)) of an 8-bit RGB PNG without filters."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        crc, = struct.unpack(">I", data[pos + 8 + length:pos + 12 + length])
        assert crc == zlib.crc32(kind + body), kind
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + length
    w, h, depth, color = ihdr[:4]
    assert (depth, color) == (8, 2)
    raw = zlib.decompress(idat)
    rows = []
    for y in range(h):
        line = raw[y * (w * 3 + 1):(y + 1) * (w * 3 + 1)]
        assert line[0] == 0  # no filter
        rows.append([tuple(line[1 + 3 * x:4 + 3 * x]) for x in range(w)])
    return w, h, rows


def run(shot, tmp_path, fb: bytes, size, fmt, pitch=None):
    src, out = tmp_path / "fb.raw", tmp_path / "out.png"
    src.write_bytes(fb)
    argv = [str(shot), "--raw", str(src), "--size", size, "--format", fmt, str(out)]
    if pitch:
        argv[1:1] = ["--pitch", str(pitch)]
    return subprocess.run(argv, capture_output=True, text=True), out


COLORS = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (18, 52, 86)]


def test_xrgb8888_little_endian(shot, tmp_path):
    fb = b"".join(bytes((b, g, r, 0xff)) for r, g, b in COLORS)
    r, out = run(shot, tmp_path, fb, "2x2", "XR24")
    assert r.returncode == 0, r.stderr
    assert read_png(out) == (2, 2, [COLORS[:2], COLORS[2:]])


def test_xbgr8888(shot, tmp_path):
    fb = b"".join(bytes((r, g, b, 0)) for r, g, b in COLORS)
    r, out = run(shot, tmp_path, fb, "2x2", "XB24")
    assert r.returncode == 0, r.stderr
    assert read_png(out)[2] == [COLORS[:2], COLORS[2:]]


def test_rgb565_expands_to_8_bits(shot, tmp_path):
    def px(r5, g6, b5):
        return struct.pack("<H", (r5 << 11) | (g6 << 5) | b5)
    fb = px(31, 0, 0) + px(0, 63, 0) + px(0, 0, 31) + px(0, 0, 0)
    r, out = run(shot, tmp_path, fb, "2x2", "RG16")
    assert r.returncode == 0, r.stderr
    assert read_png(out)[2] == [[(255, 0, 0), (0, 255, 0)], [(0, 0, 255), (0, 0, 0)]]


def test_row_pitch_wider_than_the_image(shot, tmp_path):
    # 2 pixels per row, 16-byte pitch: the 8 padding bytes of each row are not pixels
    rows = [bytes((0, 0, 255, 0)) * 2 + b"\xee" * 8, bytes((255, 0, 0, 0)) * 2 + b"\xee" * 8]
    r, out = run(shot, tmp_path, b"".join(rows), "2x2", "XR24", pitch=16)
    assert r.returncode == 0, r.stderr
    assert read_png(out)[2] == [[(255, 0, 0)] * 2, [(0, 0, 255)] * 2]


def test_unknown_format_is_refused_by_name(shot, tmp_path):
    r, out = run(shot, tmp_path, b"\0" * 64, "2x2", "NV12", pitch=8)
    assert r.returncode == 1
    assert "pixel format NV12 not supported" in r.stderr
    assert not out.exists() and not out.with_name("out.png.tmp").exists()


def test_short_framebuffer_is_refused(shot, tmp_path):
    r, _ = run(shot, tmp_path, b"\0" * 4, "2x2", "XR24")
    assert r.returncode == 1 and "too short" in r.stderr


def test_aport_ships_the_tool():
    apkbuild = (APORT / "APKBUILD").read_text()
    assert "shot.c" in apkbuild and "zlib-dev" in apkbuild
    assert '/usr/bin/lume-shot' in apkbuild
