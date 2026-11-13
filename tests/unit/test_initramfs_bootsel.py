"""Initramfs of each layer (boot-dtb-select task 3.3): /etc/soc, /etc/bootsel-keys and the
lume-bootsel package. The pack step (container) is replaced by a copy of the stage."""

import re
import shutil

import pytest

from r36os import initramfs
from r36os.paths import REPO_ROOT
from r36os.targets import TARGETS

# linux/input-event-codes.h (the names the keys files use)
CODES = {"KEY_VOLUMEDOWN": 114, "KEY_VOLUMEUP": 115, "BTN_SOUTH": 0x130, "BTN_EAST": 0x131,
         "BTN_DPAD_UP": 0x220, "BTN_DPAD_DOWN": 0x221}


@pytest.fixture
def staged(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    captured = {}

    class FakeContainer:
        def __init__(self, image, platform, volumes):
            self.volumes = volumes

        def sh(self, script):
            stage = next(h for h, g in self.volumes.items() if g == "/stage")
            shutil.copytree(stage, tmp_path / "stage")
            captured["script"] = script

    monkeypatch.setattr(initramfs, "Container", FakeContainer)
    monkeypatch.setattr(initramfs, "ensure_builder", lambda target: "builder")
    monkeypatch.setattr(initramfs, "stage_modules", lambda *a: [])

    def build(name):
        shutil.rmtree(tmp_path / "stage", ignore_errors=True)
        initramfs.build_initramfs(TARGETS[name])
        return tmp_path / "stage", captured["script"]

    return build


@pytest.mark.parametrize("board, soc, ok", [("ga36", "a33", "BTN_SOUTH"),
                                            ("r36s", "rk3326", "BTN_EAST")])
def test_console_initramfs_has_the_soc_and_the_keys(staged, board, soc, ok):
    stage, script = staged(board)
    assert (stage / "etc/soc").read_text() == soc + "\n"
    keys = (stage / "etc/bootsel-keys").read_text()
    assert keys == (REPO_ROOT / f"board/{board}/bootsel-keys").read_text()
    roles = dict(re.findall(r"^(\w+)=(\S+)$", keys, re.M))
    assert set(roles) == {"select", "up", "down", "ok"}
    assert roles["select"] == "KEY_VOLUMEDOWN" and roles["ok"] == ok
    for value in roles.values():
        assert all(k in CODES for k in value.split(",")), value
    assert "lume-bootsel" in script.split("apk add", 1)[1].splitlines()[0]


def test_vm_initramfs_has_neither(staged):
    stage, script = staged("vm")
    assert not (stage / "etc/soc").exists() and not (stage / "etc/bootsel-keys").exists()
    assert "lume-bootsel" in script        # the binary logs "no device tree" there


def test_keys_of_the_list_are_known_to_lume_bootsel():
    source = (REPO_ROOT / "aports/lume-bootsel/lume-bootsel.c").read_text()
    for board in ("ga36", "r36s"):
        keys = (REPO_ROOT / f"board/{board}/bootsel-keys").read_text()
        for name in set(re.findall(r"\b(KEY_\w+|BTN_\w+)\b", keys.split("\nselect=", 1)[1])):
            assert f'"{name}", {name}' in source, (board, name)


def test_soc_folders_match_the_image():
    from r36os.image import SOC_DIR
    assert SOC_DIR == {"ga36": "a33", "r36s": "rk3326"}
