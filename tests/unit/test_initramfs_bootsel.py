"""Initramfs of each layer (boot-dtb-select task 3.3): /etc/soc, /etc/bootsel-keys and the
lume-bootsel package. The pack step (container) is replaced by a copy of the stage."""

import re
import shutil

import pytest

from lume_tool import initramfs
from lume_tool.paths import REPO_ROOT
from lume_tool.targets import TARGETS

# linux/input-event-codes.h (the names the keys files use)
CODES = {"KEY_VOLUMEDOWN": 114, "KEY_VOLUMEUP": 115, "BTN_SOUTH": 0x130, "BTN_EAST": 0x131,
         "BTN_DPAD_UP": 0x220, "BTN_DPAD_DOWN": 0x221, "BTN_DPAD_LEFT": 0x222,
         "BTN_DPAD_RIGHT": 0x223, "BTN_TL": 0x136, "BTN_TR": 0x137}


@pytest.fixture
def staged(tmp_path, monkeypatch):
    monkeypatch.setenv("LUME_OUT", str(tmp_path / "out"))
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
    # pageup/pagedown are optional (the long list of converted trees, D17)
    assert {"select", "up", "down", "ok"} <= set(roles)
    assert set(roles) <= {"select", "up", "down", "ok", "pageup", "pagedown"}
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


def test_ga36_switches_by_its_boot_image_and_the_r36s_by_kexec(staged):
    # D16: the GA36 rewrites the boot image the vendor U-Boot loads (the sector the build and
    # push write) and reboots; the R36S keeps kexec (no bootsel-switch)
    from lume_tool import vendor
    stage, _ = staged("ga36")
    assert (stage / "etc/bootsel-switch").read_text() == \
        f"android-boot {vendor.ANDROID_BOOT_SECTOR}\n"
    stage, _ = staged("r36s")
    assert not (stage / "etc/bootsel-switch").exists()
    init = (REPO_ROOT / "initramfs/init").read_text()
    assert '--disk "$DISK"' in init and "[ $rc = 11 ]" in init and "reboot -f" in init


def test_held_list_key_is_not_echoed_on_the_screen():
    # 6.7: the volume keys are a keyboard; a Vol- held at power on repeated its characters
    # on tty1. The echo goes off before anything else reads keys, and back on for the
    # emergency shell.
    init = (REPO_ROOT / "initramfs/init").read_text()
    off = init.index("stty -F /dev/tty1 -echo")
    assert off < init.index("select_dtb\n") and off < init.index(". /lib/storage.sh")
    rescue = init[init.index("rescue() {"):init.index("exec setsid cttyhack sh")]
    assert "stty -F /dev/tty1 echo" in rescue


@pytest.mark.parametrize("board", ["ga36", "r36s", "vm"])
def test_every_library_the_init_sources_is_staged(staged, board):
    # build-speed 4.5: a library the init sources and the stage lacks stops the init (no root)
    stage, _ = staged(board)
    init = (REPO_ROOT / "initramfs/init").read_text()
    libs = re.findall(r"^\. (/lib/\S+)$", init, re.M)
    assert "/lib/slots.sh" in libs and "/lib/storage.sh" in libs
    for lib in libs:
        assert (stage / lib.lstrip("/")).read_text() == \
            (REPO_ROOT / "initramfs" / lib.lstrip("/")).read_text(), lib


def test_soc_folders_match_the_image():
    from lume_tool.image import SOC_DIR
    assert SOC_DIR == {"ga36": "a33", "r36s": "rk3326"}
