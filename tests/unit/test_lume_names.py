"""Guard for the `r36os` -> `lume` rename (device-fixes D7, tasks 1.1 to 1.4).

Reads the map in docs/NOMES.md, scans the tracked files for `r36os` (in file names and in
content), leaves out the "Fica como está" items and reports what is still pending. Until task
1.4 flips ENFORCE the report never fails the run; run this file as a script for the full list:

    .venv/bin/python tests/unit/test_lume_names.py [--list]
"""
import re
import subprocess
import sys
import warnings
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_FILE = REPO_ROOT / "docs" / "NOMES.md"

# Task 1.4 sets this to True: a pending `r36os` then fails the test.
ENFORCE = False

NEEDLE = re.compile(r"r36os", re.IGNORECASE)
MAX_BYTES = 2_000_000


def _cells(line):
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _strip_ticks(text):
    return text.strip().strip("`").strip()


def parse_map(text=None):
    """Return (rename_rows, keep_rows).

    rename_rows: list of dicts with the columns Antes, Depois, Tipo (backticks removed).
    keep_rows: list of (item_cell, reason) with the item cell as written (backticks kept).
    """
    if text is None:
        text = MAP_FILE.read_text(encoding="utf-8")
    rename, keep = [], []
    header = None
    for line in text.splitlines():
        if not line.startswith("|"):
            header = None
            continue
        cells = _cells(line)
        if cells and cells[0] in ("Antes", "Item"):
            header = cells
            continue
        if header is None or set("".join(cells)) <= set("-: "):
            continue
        if header[0] == "Antes" and len(cells) >= 3:
            rename.append({"Antes": _strip_ticks(cells[0]), "Depois": _strip_ticks(cells[1]),
                           "Tipo": cells[2].strip()})
        elif header[0] == "Item" and len(cells) >= 2:
            keep.append((cells[0], cells[1]))
    return rename, keep


def tracked_files():
    out = subprocess.run(["git", "-C", str(REPO_ROOT), "ls-files"], capture_output=True,
                         text=True, check=True).stdout
    return [f for f in out.splitlines() if (REPO_ROOT / f).is_file()]


def keep_rules(keep_rows, files):
    """Split the backtick tokens of the "Item" cells into path exclusions and literal texts."""
    paths, literals = [], []
    for item, _reason in keep_rows:
        for token in re.findall(r"`([^`]+)`", item):
            is_path = any(f == token or (token.endswith("/") and f.startswith(token))
                          for f in files)
            (paths if is_path else literals).append(token)
    return paths, literals


def _excluded(path, paths):
    return any(path == p or (p.endswith("/") and path.startswith(p)) for p in paths)


def find_pending(files=None, rename_rows=None, keep_rows=None):
    """Return the list of (path, line_number or 0 for the file name, text) still holding r36os."""
    if files is None:
        files = tracked_files()
    if rename_rows is None or keep_rows is None:
        rename_rows, keep_rows = parse_map()
    paths, literals = keep_rules(keep_rows, files)
    # longest first so a longer kept text is removed before its own prefix
    literals = sorted(set(literals), key=len, reverse=True)
    pending = []
    for f in files:
        if _excluded(f, paths):
            continue
        if NEEDLE.search(f):
            pending.append((f, 0, f))
        try:
            data = (REPO_ROOT / f).read_bytes()
        except OSError:
            continue
        if len(data) > MAX_BYTES or b"\0" in data[:4096] or b"r36os" not in data.lower():
            continue
        for n, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
            if not NEEDLE.search(line):
                continue
            rest = line
            for lit in literals:
                rest = rest.replace(lit, "")
            if NEEDLE.search(rest):
                pending.append((f, n, line.strip()[:160]))
    return pending


def area(path):
    parts = path.split("/")
    if parts[0] in ("aports", "lume", "openspec", "docs", "tests", "src", "board") and len(parts) > 1:
        return "/".join(parts[:2])
    return parts[0]


def summary(pending):
    by_area = Counter(area(p) for p, _n, _t in pending)
    files = len({p for p, _n, _t in pending})
    lines = [f"lume names: {len(pending)} pending r36os occurrences in {files} files "
             f"(ENFORCE={ENFORCE})"]
    lines += [f"  {n:5d}  {a}" for a, n in by_area.most_common()]
    return "\n".join(lines)


def test_map_parses_and_has_no_duplicate_antes():
    rename, keep = parse_map()
    assert len(rename) > 50, "the Antes | Depois | Tipo tables are missing from docs/NOMES.md"
    assert len(keep) > 3, "the Item | Motivo table is missing from docs/NOMES.md"
    seen = {}
    for row in rename:
        assert row["Antes"] and row["Depois"] and row["Tipo"], f"incomplete row: {row}"
        assert row["Antes"] not in seen, f"duplicate Antes: {row['Antes']}"
        seen[row["Antes"]] = row["Depois"]
    for item, reason in keep:
        assert re.search(r"`[^`]+`", item), f"Item without a backtick token: {item}"
        assert reason, f"Item without a reason: {item}"


def test_new_names_do_not_keep_the_old_prefix():
    rename, _keep = parse_map()
    for row in rename:
        assert not NEEDLE.search(row["Depois"]), f"Depois still has r36os: {row}"
        if row["Antes"].startswith("R36OS_"):
            assert row["Depois"] == "LUME_" + row["Antes"][len("R36OS_"):] or row["Antes"] == "R36OS_LUME_CROSS"


def test_kept_items_are_not_renamed():
    rename, keep = parse_map()
    kept = {t for item, _r in keep for t in re.findall(r"`([^`]+)`", item)}
    # the factory variables are renamed AND the old name stays as a read-only alias (NOMES.md, 8)
    alias_ok = {"R36OS_GA36_FACTORY", "R36OS_R36S_FACTORY"}
    clash = [r["Antes"] for r in rename if r["Antes"] in kept and r["Antes"] not in alias_ok]
    assert not clash, f"in both the rename and the keep tables: {clash}"


def test_pending_names_report():
    pending = find_pending()
    text = summary(pending)
    print(text)
    warnings.warn(text, stacklevel=1)
    if ENFORCE:
        assert not pending, text + "\n" + "\n".join(f"{p}:{n}: {t}" for p, n, t in pending[:50])


if __name__ == "__main__":
    result = find_pending()
    if "--list" in sys.argv:
        for path, num, text in result:
            print(f"{path}:{num}: {text}")
    print(summary(result))
