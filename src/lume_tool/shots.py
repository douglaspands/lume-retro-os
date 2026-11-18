"""Reference screen captures for `lume dev shot --compare|--update` (build-speed D19).

References live in tests/device/shots/<console>/<screen>.png; the button sequence that reaches
each screen from the launcher home is in tests/device/shots/screens.toml. The console is the
one that reports it (`uname -m`: armv7l = ga36, aarch64 = r36s), since one card moves between
the two consoles.

PNGs are decoded and encoded with zlib/struct (no image library): lume-shot writes plain
8-bit RGB images, and the decoder also accepts RGBA and every scanline filter.

The comparison is per pixel: a pixel differs when any channel differs by more than
CHANNEL_TOLERANCE; the screen fails when more than MAX_DIFF_RATIO of the pixels differ.
The diff image shows the unchanged pixels dimmed and the differing ones in red.
"""

from __future__ import annotations

import struct
import tomllib
import zlib
from dataclasses import dataclass
from pathlib import Path

CHANNEL_TOLERANCE = 16      # per-channel difference (0-255) that counts as a different pixel
MAX_DIFF_RATIO = 0.002      # fraction of differing pixels above which the screen fails

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
BOARDS = {"armv7l": "ga36", "aarch64": "r36s"}


class ShotError(RuntimeError):
    pass


@dataclass
class Image:
    width: int
    height: int
    rgb: bytes          # width * height * 3 bytes


def board_from_machine(machine: str) -> str:
    """`uname -m` of the console -> board directory name."""
    board = BOARDS.get(machine.strip())
    if board is None:
        raise ShotError(f"unknown console architecture `{machine.strip()}`")
    return board


# --- PNG -------------------------------------------------------------------------------

def _chunks(data: bytes):
    pos = len(PNG_MAGIC)
    while pos + 8 <= len(data):
        length, kind = struct.unpack(">I4s", data[pos:pos + 8])
        yield kind, data[pos + 8:pos + 8 + length]
        pos += 12 + length


def decode_png(data: bytes) -> Image:
    if data[:8] != PNG_MAGIC:
        raise ShotError("not a PNG")
    width = height = depth = ctype = interlace = None
    idat = []
    for kind, body in _chunks(data):
        if kind == b"IHDR":
            width, height, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat.append(body)
    if width is None:
        raise ShotError("PNG without a header")
    if depth != 8 or ctype not in (2, 6) or interlace != 0:
        raise ShotError("only 8-bit RGB/RGBA PNGs without interlacing are supported")
    bpp = 3 if ctype == 2 else 4
    stride = width * bpp
    raw = zlib.decompress(b"".join(idat))
    if len(raw) != (stride + 1) * height:
        raise ShotError("PNG data has the wrong size")
    rows: list[bytearray] = []
    prev = bytearray(stride)
    for y in range(height):
        base = y * (stride + 1)
        ftype = raw[base]
        cur = bytearray(raw[base + 1:base + 1 + stride])
        if ftype == 1:
            for i in range(bpp, stride):
                cur[i] = (cur[i] + cur[i - bpp]) & 255
        elif ftype == 2:
            for i in range(stride):
                cur[i] = (cur[i] + prev[i]) & 255
        elif ftype == 3:
            for i in range(stride):
                left = cur[i - bpp] if i >= bpp else 0
                cur[i] = (cur[i] + ((left + prev[i]) >> 1)) & 255
        elif ftype == 4:
            for i in range(stride):
                a = cur[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
                cur[i] = (cur[i] + pred) & 255
        elif ftype != 0:
            raise ShotError(f"bad PNG filter {ftype}")
        rows.append(cur)
        prev = cur
    if bpp == 4:
        rows = [bytearray(b for i, b in enumerate(r) if i % 4 != 3) for r in rows]
    return Image(width, height, b"".join(rows))


def encode_png(img: Image) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        crc = zlib.crc32(kind + body) & 0xFFFFFFFF
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)

    stride = img.width * 3
    raw = b"".join(b"\x00" + img.rgb[y * stride:(y + 1) * stride] for y in range(img.height))
    ihdr = struct.pack(">IIBBBBB", img.width, img.height, 8, 2, 0, 0, 0)
    return (PNG_MAGIC + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 6))
            + chunk(b"IEND", b""))


# --- comparison ------------------------------------------------------------------------

@dataclass
class Comparison:
    differing: int
    total: int
    ratio: float
    ok: bool
    diff: Image | None  # None when the sizes match and nothing differs


def compare_images(ref: Image, cur: Image, tolerance: int = CHANNEL_TOLERANCE,
                   max_ratio: float = MAX_DIFF_RATIO) -> Comparison:
    """Per-pixel comparison; differing pixels are red in the diff, the rest is dimmed."""
    if (ref.width, ref.height) != (cur.width, cur.height):
        w, h = cur.width, cur.height
        red = b"\xff\x00\x00" * (w * h)
        return Comparison(w * h, w * h, 1.0, False, Image(w, h, red))
    total = ref.width * ref.height
    out = bytearray(total * 3)
    differing = 0
    a, b = ref.rgb, cur.rgb
    for p in range(total):
        i = p * 3
        if (abs(a[i] - b[i]) > tolerance or abs(a[i + 1] - b[i + 1]) > tolerance
                or abs(a[i + 2] - b[i + 2]) > tolerance):
            differing += 1
            out[i] = 255
        else:
            out[i] = b[i] // 4
            out[i + 1] = b[i + 1] // 4
            out[i + 2] = b[i + 2] // 4
    ratio = differing / total if total else 0.0
    return Comparison(differing, total, ratio, ratio <= max_ratio,
                      Image(ref.width, ref.height, bytes(out)))


# --- references and screens ------------------------------------------------------------

def reference_path(shots_dir: Path, board: str, screen: str) -> Path:
    return shots_dir / board / f"{screen}.png"


def load_screens(shots_dir: Path) -> dict[str, str]:
    """screen name -> key sequence from the launcher home (`screens.toml`)."""
    path = shots_dir / "screens.toml"
    try:
        data = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise ShotError(f"cannot read {path}: {e}")
    return {name: str(spec.get("keys", "")) for name, spec in data.get("screens", {}).items()}


def compare_screen(ref_path: Path, cur_png: bytes, diff_path: Path) -> Comparison:
    """Compare a capture with its reference; on failure write the diff image to diff_path."""
    if not ref_path.is_file():
        raise ShotError(f"no reference at {ref_path} (record it with --update)")
    result = compare_images(decode_png(ref_path.read_bytes()), decode_png(cur_png))
    if not result.ok and result.diff is not None:
        diff_path.parent.mkdir(parents=True, exist_ok=True)
        diff_path.write_bytes(encode_png(result.diff))
    return result
