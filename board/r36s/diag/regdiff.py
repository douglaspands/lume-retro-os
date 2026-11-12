"""Compare two R36S display register dumps (task 4.6).

Each side is either a folder written by regdump.sh (<name>.txt files, every word)
or a boot log with the "regdump <name> <address> <offset> <value>" lines of
kernel patch 0017 (non-zero words only; a missing word reads as zero).

Usage: regdiff.py <factory dump dir or log> <r36os boot log or dir>
Prints the words that differ, region by region, as "<region> <offset> <a> <b>".
"""

import re
import sys
from pathlib import Path

# region -> bytes read by kernel patch 0017 (regdump.sh reads 0x800 of the D-PHY; the
# upper half mirrors the lower one, so it is left out of the comparison)
SIZES = {"dsi": 0x200, "dphy": 0x400, "vop": 0x300, "grf": 0x500, "cru": 0x300, "pmucru": 0x100}
REGIONS = tuple(SIZES)
LINE = re.compile(r"(?:regdump (\w+) )?(0x[0-9a-f]+) (0x[0-9a-f]+) (0x[0-9a-f]+)\s*$")


def load(path: Path) -> dict[str, dict[int, int]]:
    """Region -> {offset: value} from a regdump.sh folder or a boot log."""
    regs: dict[str, dict[int, int]] = {}
    if path.is_dir():
        for name in REGIONS:
            f = path / f"{name}.txt"
            if not f.exists():
                continue
            words = regs.setdefault(name, {})
            for line in f.read_text().splitlines():
                m = LINE.search(line)
                if m:
                    words[int(m.group(3), 16)] = int(m.group(4), 16)
        return regs
    for line in path.read_text(errors="replace").splitlines():
        if "regdump " not in line:
            continue
        m = LINE.search(line)
        if m and m.group(1):
            regs.setdefault(m.group(1), {})[int(m.group(3), 16)] = int(m.group(4), 16)
    return regs


def diff(a: dict[str, dict[int, int]], b: dict[str, dict[int, int]]) -> list[str]:
    out = []
    for name in REGIONS:
        if name not in a or name not in b:
            out.append(f"{name}: missing on {'the first' if name not in a else 'the second'} side")
            continue
        for off in sorted(o for o in set(a[name]) | set(b[name]) if o < SIZES[name]):
            va, vb = a[name].get(off, 0), b[name].get(off, 0)
            if va != vb:
                out.append(f"{name} {off:#06x} {va:#010x} {vb:#010x}")
    return out


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    for line in diff(load(Path(argv[1])), load(Path(argv[2]))):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
