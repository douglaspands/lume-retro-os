"""R36S kernel config fragment tests: board/r36s/kernel.config."""

import re

from r36os.paths import REPO_ROOT

FRAGMENT = (REPO_ROOT / "board/r36s/kernel.config").read_text()


def _options(text: str) -> dict[str, str]:
    return dict(re.findall(r"^(CONFIG_\w+)=(.*)$", text, re.M))


def test_r36s_fragment_enables_zram_lz4():
    opts = _options(FRAGMENT)
    for o in ("CONFIG_ZSMALLOC", "CONFIG_ZRAM", "CONFIG_ZRAM_BACKEND_LZ4", "CONFIG_ZRAM_DEF_COMP_LZ4"):
        assert opts.get(o) == "y", o
