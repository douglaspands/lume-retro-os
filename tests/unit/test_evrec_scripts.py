"""Tests of the evrec recording format and the device script schema (virtual-gamepad 1.1)."""
import subprocess
from pathlib import Path

import pytest

from r36os import evrec, scripts

ROOT = Path(__file__).resolve().parents[2]

REC = evrec.Recording("ga36", [
    evrec.Event(0, 1, 304, 1), evrec.Event(0, 0, 0, 0),
    evrec.Event(80, 1, 304, 0), evrec.Event(80, 0, 0, 0),
], 500)

GOOD = """
description = "smoke"
consoles = ["ga36", "r36s"]

[[step]]
name = "go home"
type = "keys"
sequence = "fn+start,wait:500"

[[step]]
name = "replay"
type = "play"
recording = "cache/recordings/ga36-1.evrec"
timeout = 90

[[step]]
name = "see it"
type = "wait_event"
pattern = "boot OK"
category = "boot"

[[step]]
name = "frontend up"
type = "wait_process"
process = "lume-ui"
state = "present"

[[step]]
name = "home screen"
type = "shot"
screen = "home"

[[step]]
name = "uname"
type = "sh"
command = "uname -a"

[[step]]
name = "open"
type = "open_game"
system = "gba"
position = 1

[[step]]
name = "close"
type = "close_game"
"""


def test_evrec_round_trip(tmp_path):
    text = evrec.dumps(REC)
    assert text.splitlines()[0] == "# r36os-evrec 1 ga36"
    assert text.splitlines()[-1] == "# end 500"
    assert evrec.parse(text) == REC
    f = tmp_path / "a.evrec"
    evrec.write(f, REC)
    assert evrec.read(f, "ga36") == REC


def test_evrec_wrong_console_refused(tmp_path):
    f = tmp_path / "a.evrec"
    evrec.write(f, REC)
    with pytest.raises(evrec.EvrecError, match="not r36s"):
        evrec.read(f, "r36s")


@pytest.mark.parametrize("text,msg", [
    ("", "empty"),
    ("# r36os-evrec 2 ga36\n# end 0\n", "version"),
    ("# r36os-evrec 1 gba\n# end 0\n", "unknown console"),
    ("# r36os-evrec 1 ga36\n0 1 2\n# end 0\n", "line 2"),
    ("# r36os-evrec 1 ga36\n0 1 x 1\n# end 0\n", "line 2: bad code"),
    ("# r36os-evrec 1 ga36\n5 1 2 1\n3 1 2 0\n# end 9\n", "line 3: time goes backwards"),
    ("# r36os-evrec 1 ga36\n5 1 2 1\n", "missing end"),
    ("# r36os-evrec 1 ga36\n5 1 2 1\n# end 4\n", "end time"),
    ("# r36os-evrec 1 ga36\n# end 0\n1 1 2 1\n", "line 3: data after"),
])
def test_evrec_strict_reader(text, msg):
    with pytest.raises(evrec.EvrecError, match=msg):
        evrec.parse(text)


def test_script_valid():
    s = scripts.loads(GOOD)
    assert s.consoles == ["ga36", "r36s"]
    assert [st.type for st in s.steps] == list(scripts.TYPES)
    assert s.steps[0].timeout == 60 and s.steps[1].timeout == 90
    scripts.check_console(s, "r36s")


def test_script_console_not_listed():
    s = scripts.loads(GOOD.replace('["ga36", "r36s"]', '["ga36"]'))
    with pytest.raises(scripts.ScriptError, match="not r36s"):
        scripts.check_console(s, "r36s")


@pytest.mark.parametrize("old,new,msg", [
    ('type = "close_game"', 'type = "dance"', "unknown type"),
    ('type = "close_game"', 'type = "close_game"\nextra = 1', "unknown field"),
    ('type = "close_game"', 'type = "close_game"\ngame = "x"', "forbidden"),
    ('type = "close_game"', 'type = "close_game"\nrom = "x"', "forbidden"),
    ('type = "close_game"', 'type = "close_game"\ncontent = "x"', "forbidden"),
    ('type = "close_game"', 'type = "close_game"\ntitle = "x"', "forbidden"),
    ('type = "sh"', 'type = "sh"\npath = "/roms/x"', "forbidden"),
    ('name = "close"', 'name = "x.gba"', "ROM file"),
    ('position = 1', 'position = 0', "position"),
    ('state = "present"', 'state = "maybe"', "state"),
    ('recording = "cache/recordings/ga36-1.evrec"', 'recording = "tests/a.evrec"', "cache/"),
    ('recording = "cache/recordings/ga36-1.evrec"', 'recording = "cache/../a.evrec"', "cache/"),
    ('timeout = 90', 'timeout = 0', "timeout"),
    ('sequence = "fn+start,wait:500"', 'sequence = "zzz"', "unknown button"),
    ('pattern = "boot OK"', 'pattern = "("', "pattern"),
    ('consoles = ["ga36", "r36s"]', 'consoles = ["gba"]', "consoles"),
    ('consoles = ["ga36", "r36s"]', 'consoles = []', "consoles"),
])
def test_script_refused(old, new, msg):
    assert old in GOOD
    with pytest.raises(scripts.ScriptError, match=msg):
        scripts.loads(GOOD.replace(old, new, 1))


def test_script_missing_field_and_no_steps():
    with pytest.raises(scripts.ScriptError, match="needs `process`"):
        scripts.loads('consoles = ["ga36"]\n[[step]]\nname="a"\ntype="wait_process"\n'
                      'state="absent"\n')
    with pytest.raises(scripts.ScriptError, match="at least one"):
        scripts.loads('consoles = ["ga36"]\n')


def _tracked() -> list[str]:
    r = subprocess.run(["git", "-C", str(ROOT), "ls-files"], capture_output=True, text=True)
    if r.returncode != 0:
        pytest.skip("not a git checkout")
    return r.stdout.splitlines()


def test_repo_has_no_recordings():
    assert [f for f in _tracked() if f.endswith(".evrec")] == []


def test_repo_scripts_are_valid_and_clean():
    for f in _tracked():
        if f.startswith("tests/device/scripts/") and f.endswith(".toml"):
            scripts.load(ROOT / f)    # refuses name/path of a ROM and every forbidden field
