"""scripts/guardrail.py: read-only paths outside the workspace (paths.readonly_system).

Bring-up reads the device card (/run/media): reading it must not ask. The kernel tree the
build generates is in the build cache (.cache/ inside the workspace), so it needs no entry.
Any access to the Btrfs No-COW volume (~/data) keeps asking (docs/ctx/MELHORIAS.md, M-18).
"""

import importlib.util
import os

from r36os.paths import REPO_ROOT

spec = importlib.util.spec_from_file_location("guardrail", REPO_ROOT / "scripts/guardrail.py")
guardrail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guardrail)
POLICY = guardrail.load_policy()
HOME = os.path.expanduser("~")
CARD = "/run/media/user/ROMS/logs"
TREE = f"{REPO_ROOT}/.cache/src/linux-6.18.62-0123456789abcdef"


def cmd(c):
    return guardrail.evaluate_shell_command(c, POLICY)[0]


def read(p):
    return guardrail.evaluate_file_access("Read", p, POLICY)[0]


def write(p):
    return guardrail.evaluate_file_access("Write", p, POLICY)[0]


def test_reading_the_card_is_allowed():
    assert cmd(f'rg -n "panel" {CARD}/boot/boot-1.log') == "allow"
    assert cmd(f"ls {CARD}/hw") == "allow"
    assert read(f"{CARD}/events.log") == "allow"


def test_reading_the_kernel_tree_in_the_cache_is_allowed():
    assert read(f"{TREE}/drivers/gpu/drm/panel/panel-sitronix-st7703.c") == "allow"


def test_writing_the_card_and_any_data_access_ask():
    assert write(f"{CARD}/events.log") == "ask"
    assert cmd(f"rg -n x {HOME}/data/other/db") == "ask"
    assert cmd(f"ls {HOME}/data/vm") == "ask"
    assert read(f"{HOME}/data/other/db.sqlite") == "ask"
    assert write(f"{HOME}/data/other/x.txt") == "ask"
    # a read-only command mixing an allowed path and a ~/data path asks
    assert cmd(f"rg -n x {CARD}/events.log {HOME}/data/vm/disk.img") == "ask"
