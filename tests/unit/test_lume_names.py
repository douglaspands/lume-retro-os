"""Guard for the `r36os` -> `lume` rename (device-fixes D7, tasks 1.1 to 1.4).

Reads the map in docs/NOMES.md, scans the tracked files for `r36os` (in file names and in
content), leaves out the "Fica como está" items and fails on anything still pending (ENFORCE,
on since task 1.4). Run this file as a script for the full list:

    .venv/bin/python tests/unit/test_lume_names.py [--console|--pc] [--list]
"""
import re
import subprocess
import sys
import warnings
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAP_FILE = REPO_ROOT / "docs" / "NOMES.md"

# Task 1.4 turned this on: a pending `r36os` fails the test.
ENFORCE = True

# The main specs are not edited by hand: they are updated from the name-only MODIFIED deltas of
# device-fixes when the change is archived. test_main_specs_have_a_name_delta checks the deltas.
SPEC_DIR = "openspec/specs/"
DELTA_DIR = "openspec/changes/device-fixes/specs/"

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
    section = ""
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
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
                           "Tipo": cells[2].strip(), "Secao": section})
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
        if _excluded(f, paths) or f.startswith(SPEC_DIR):
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
    # no old name is kept as an alias (NOMES.md, 8 and 13: Q4)
    clash = [r["Antes"] for r in rename if r["Antes"] in kept]
    assert not clash, f"in both the rename and the keep tables: {clash}"


def _requirement_blocks(text):
    """Yield (header line, body) of each `### Requirement:` block (ends at the next `##`)."""
    for part in re.split(r"(?m)^(?=### Requirement: )", text)[1:]:
        body = re.split(r"(?m)^## ", part, maxsplit=1)[0]
        yield part.splitlines()[0].strip(), body


def test_main_specs_have_a_name_delta():
    """Every requirement of a main spec that still has r36os is MODIFIED in a device-fixes delta."""
    missing = []
    for spec in sorted((REPO_ROOT / SPEC_DIR).glob("*/spec.md")):
        for header, body in _requirement_blocks(spec.read_text(encoding="utf-8")):
            if not NEEDLE.search(body):
                continue
            delta = REPO_ROOT / DELTA_DIR / spec.parent.name / "spec.md"
            text = delta.read_text(encoding="utf-8") if delta.is_file() else ""
            modified = re.split(r"(?m)^## ", text.split("## MODIFIED Requirements", 1)[-1],
                                maxsplit=1)[0] if "## MODIFIED Requirements" in text else ""
            if header not in modified or NEEDLE.search(modified):
                missing.append(f"{spec.parent.name}: {header}")
    assert not missing, "no clean MODIFIED delta in device-fixes for:\n" + "\n".join(missing)


def test_pending_names_report():
    pending = find_pending()
    text = summary(pending)
    print(text)
    warnings.warn(text, stacklevel=1)
    if ENFORCE:
        assert not pending, text + "\n" + "\n".join(f"{p}:{n}: {t}" for p, n, t in pending[:50])


# Console mode (task 1.2): the trees that become the console image, its build inputs and the
# tests. Here the only `r36os` left may be a name of the PC tool, which task 1.3 renames.
CONSOLE_SCOPE = ("aports/", "rootfs/", "initramfs/", "board/", "kernel/", "lume/", "tests/")
# rows of the map that name the PC tool (sections 9 and 9.1 and these types elsewhere)
PC_TYPES = {"git-pc", "pasta-build", "var-pc", "identificador", "pacote-pc", "import",
            "pyproject", "modulo-pc", "comando", "rotulo-container", "container", "imagem",
            "containerfile", "identidade", "arquivo-pc", "cache-pc", "script-pc", "policy",
            "receita-ctx", "chave"}
PC_FORMS = re.compile(r"\bfrom r36os\b|\bimport r36os\b|\br36os\.[a-z_]+|\bsrc/r36os\b"
                      r"|\"src\" / \"r36os\""
                      r"|\br36os (build|push|dev|vm|flash|pkg|dtb-import|dtb|test-vm|power)\b")


def pc_literals(rename_rows):
    """The old PC names, longest first (the bare command `r36os` is left out: it would hide
    every console name too)."""
    lits = {r["Antes"] for r in rename_rows
            if r["Antes"] != "r36os"
            and (r["Tipo"] in PC_TYPES or r["Secao"].startswith("9")
                 or r["Antes"].startswith(("src/r36os", "r36os/")))}
    return sorted(lits, key=len, reverse=True)


def find_console_pending(files=None, rename_rows=None, keep_rows=None):
    """Like find_pending, limited to CONSOLE_SCOPE and without the names of the PC tool."""
    if files is None:
        files = tracked_files()
    if rename_rows is None or keep_rows is None:
        rename_rows, keep_rows = parse_map()
    files = [f for f in files if f.startswith(CONSOLE_SCOPE)]
    pc = pc_patterns(rename_rows)
    out = []
    for path, n, text in find_pending(files, rename_rows, keep_rows):
        if n == 0:
            out.append((path, n, text))
            continue
        line = (REPO_ROOT / path).read_text(encoding="utf-8", errors="replace").splitlines()[n - 1]
        if console_rest(line, pc):
            out.append((path, n, text))
    return out


def pc_patterns(rename_rows):
    """One regex per PC literal; a literal that ends in a letter or digit must end there, so
    the PC folder `r36os-initramfs` does not hide the console package `r36os-initramfs-static`."""
    return [re.compile(re.escape(lit) + (r"(?![A-Za-z0-9_-])" if lit[-1].isalnum() else ""))
            for lit in pc_literals(rename_rows)]


def console_rest(line, pc):
    """Whether `line` still has r36os once the PC names are taken out."""
    for rx in pc:
        line = rx.sub("", line)
    return bool(NEEDLE.search(PC_FORMS.sub("", line)))


def test_console_check_only_forgives_pc_names():
    rename, _keep = parse_map()
    pc = pc_patterns(rename)
    assert not console_rest('from r36os.paths import REPO_ROOT; os.environ["R36OS_OUT"]', pc)
    assert not console_rest("cp /keys/r36os.rsa.pub x; uv run r36os build vm", pc)
    assert not console_rest('build / "r36os-initramfs"', pc)
    for console in ("apk add r36os-initramfs-static", "/usr/libexec/r36os/lib.sh",
                    "R36OS_RUN=/run/r36os", "rc-update add r36os-logd", "/etc/r36os/board"):
        assert console_rest(console, pc), console


def test_console_names_have_no_r36os():
    """Task 1.2 closed the console side: this check is enforced (ENFORCE is for 1.4)."""
    pending = find_console_pending()
    assert not pending, "\n".join(f"{p}:{n}: {t}" for p, n, t in pending[:50])


# PC mode (task 1.3): the PC tool, its tests, helpers, containers, the ctx policy and the
# agent skills. Nothing named r36os may be left here but the "Fica como está" items (the old
# evrec header and the old signature, read for compatibility).
PC_SCOPE = ("src/", "tests/", "scripts/", "containers/", "pyproject.toml", "policy.toml",
            ".claude/", ".agents/", ".gitignore")


def find_pc_pending(files=None, rename_rows=None, keep_rows=None):
    """Like find_pending, limited to PC_SCOPE."""
    if files is None:
        files = tracked_files()
    return find_pending([f for f in files if f.startswith(PC_SCOPE)], rename_rows, keep_rows)


def test_pc_names_have_no_r36os():
    """Task 1.3 closed the PC tool side: this check is enforced (ENFORCE is for 1.4)."""
    pending = find_pc_pending()
    assert not pending, "\n".join(f"{p}:{n}: {t}" for p, n, t in pending[:50])


if __name__ == "__main__":
    result = find_pending()
    if "--console" in sys.argv:
        result = find_console_pending()
    if "--pc" in sys.argv:
        result = find_pc_pending()
    if "--list" in sys.argv:
        for path, num, text in result:
            print(f"{path}:{num}: {text}")
    print(summary(result))
