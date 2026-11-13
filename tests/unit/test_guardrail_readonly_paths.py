"""scripts/guardrail.py: read-only paths outside the workspace (paths.readonly_system).

Bring-up reads the device card (/run/media) and the kernel tree the build generates
(~/data/r36os/src); reading them must not ask, while writing and any other access to the
Btrfs No-COW volume (~/data) keep asking (docs/ctx/MELHORIAS.md, M-18).
"""

import importlib.util
import os

from r36os.paths import REPO_ROOT

spec = importlib.util.spec_from_file_location("guardrail", REPO_ROOT / "scripts/guardrail.py")
guardrail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guardrail)
POLICY = guardrail.load_policy()
HOME = os.path.expanduser("~")
TREE = f"{HOME}/data/r36os/src/linux-6.18.62-0123456789abcdef"


def cmd(c):
    return guardrail.evaluate_shell_command(c, POLICY)[0]


def read(p):
    return guardrail.evaluate_file_access("Read", p, POLICY)[0]


def write(p):
    return guardrail.evaluate_file_access("Write", p, POLICY)[0]


def test_reading_the_card_and_the_kernel_tree_is_allowed():
    assert cmd('rg -n "panel" /run/media/user/ROMS/logs/boot/boot-1.log') == "allow"
    assert cmd(f'rg -n "lane rate" {TREE}/drivers/phy/rockchip/x.c') == "allow"
    assert cmd("rg -n DEVMEM ~/data/r36os/kbuild/r36s-0123/.config") == "allow"
    assert cmd(f"ls {HOME}/data/r36os/src") == "allow"
    assert read(f"{TREE}/drivers/gpu/drm/panel/panel-sitronix-st7703.c") == "allow"
    assert read("/run/media/user/ROMS/logs/events.log") == "allow"


def test_writing_and_other_data_paths_still_ask():
    assert write(f"{TREE}/drivers/input/input.c") == "ask"
    assert cmd(f"cp README.md {TREE}/x") == "ask"
    assert cmd(f"rg -n x {HOME}/data/other/db") == "ask"
    assert read(f"{HOME}/data/other/db.sqlite") == "ask"
    # a read-only command mixing an allowed and a not allowed ~/data path asks
    assert cmd(f"rg -n x {TREE}/a.c {HOME}/data/vm/disk.img") == "ask"
