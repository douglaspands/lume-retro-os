"""scripts/guardrail.py: `rm` inside ./cache/ needs no confirmation (commands.rm_free).

The user asked (2026-11-18) for removals in the project scratch folder to go through without a
prompt. Everything else keeps asking: the folder itself, the build cache ./.cache/, a path that
escapes with `..`, a symlink that points outside, an unknown option, a mix of targets.
"""

import importlib.util
import os

from r36os.paths import REPO_ROOT

spec = importlib.util.spec_from_file_location("guardrail", REPO_ROOT / "scripts/guardrail.py")
guardrail = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guardrail)
POLICY = guardrail.load_policy()


def cmd(c):
    return guardrail.evaluate_shell_command(c, POLICY)[0]


def test_rm_inside_the_scratch_folder_is_allowed():
    assert cmd("rm cache/tmp/x.png") == "allow"
    assert cmd("rm -f cache/tmp/a.txt cache/tmp/b.txt") == "allow"
    assert cmd("rm -rf cache/tmp/old-dir") == "allow"
    assert cmd(f"rm {REPO_ROOT}/cache/tmp/x.png") == "allow"


def test_rm_elsewhere_still_asks():
    assert cmd("rm cache") == "ask"                      # the folder itself
    assert cmd("rm -rf cache/") == "ask"
    assert cmd("rm .cache/src/x") == "ask"               # the build cache
    assert cmd("rm cache/../docs/LOGS.md") == "ask"      # escapes with ..
    assert cmd("rm docs/LOGS.md") == "ask"
    assert cmd("rm cache/tmp/x docs/y") == "ask"         # one target outside
    assert cmd("rm -i cache/tmp/x") == "ask"             # unknown option
    assert cmd("rm") == "ask"


def test_symlink_pointing_outside_asks(tmp_path):
    link = REPO_ROOT / "cache" / "tmp" / f"guardrail-link-{os.getpid()}"
    link.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "outside"
    target.write_text("x")
    link.symlink_to(target)
    try:
        assert cmd(f"rm cache/tmp/{link.name}") == "ask"
    finally:
        link.unlink()
