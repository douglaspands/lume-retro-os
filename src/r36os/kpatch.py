"""Reading `kernel/patches/`: contents of the new files a patch creates.

The host tests use this to check the drivers without extracting the whole kernel.
"""

from __future__ import annotations

import re
from pathlib import Path

from r36os.paths import REPO_ROOT

PATCHES_DIR = REPO_ROOT / "kernel/patches"


def find(prefix: str) -> Path:
    """The patch whose name starts with `prefix` (e.g. "0005-")."""
    found = sorted(PATCHES_DIR.glob(f"{prefix}*.patch"))
    if len(found) != 1:
        raise FileNotFoundError(f"{prefix}*.patch: {found}")
    return found[0]


def new_file(patch: Path, path: str) -> str:
    """Contents of a file the patch creates (`new file mode`, hunk @@ -0,0 ...)."""
    text = patch.read_text()
    m = re.search(rf"^\+\+\+ b/{re.escape(path)}\n@@ -0,0 \+1,(\d+) @@[^\n]*\n", text, re.M)
    if not m:
        raise KeyError(f"{patch.name}: {path} is not a new file")
    lines = text[m.end():].split("\n")[: int(m.group(1))]
    assert all(line.startswith("+") for line in lines), path
    return "\n".join(line[1:] for line in lines) + "\n"


def added_lines(patch: Path, path: str) -> list[str]:
    """Lines added to an existing file (without the '+')."""
    out: list[str] = []
    current = None
    for line in patch.read_text().splitlines():
        if line.startswith("+++ b/"):
            current = line[6:]
        elif current == path and line.startswith("+") and not line.startswith("+++"):
            out.append(line[1:])
    return out
