"""Suítes em shell (busybox) que rodam no container do builder."""

import shutil
import subprocess

import pytest

from lume_tool.container import Container, ensure_builder
from lume_tool.paths import REPO_ROOT
from lume_tool.targets import get_target

pytestmark = pytest.mark.skipif(shutil.which("podman") is None, reason="sem podman")


@pytest.mark.parametrize("script", [
    "tests/initramfs/test_storage.sh",   # 4.1-4.3
    "tests/initramfs/test_slots.sh",     # build-speed 4.0
    "tests/initramfs/test_brightness.sh",  # device-fixes 9.16
    "tests/playlists/test_playlists.sh",  # 6.2
    "tests/logs/test_logs.sh",            # 5.5
    "tests/audio/test_mixer.sh",          # 9.8
    "tests/audio/test_jack.sh",           # r36s-single-card 6.6
    "tests/audio/test_audiotest.sh",      # r36s-single-card 4.6 (bring-up)
    "tests/usb/test_usb_gadget.sh",       # usb-device-access 3.2, 3.3
    "tests/usb/test_usb_storage.sh",      # usb-device-access 7.3
    "tests/session/test_session.sh",      # lume-launcher 6.1
    "tests/net/test_ssh_wifi.sh",         # lume-launcher 12.5, game-governor 7.2
    "tests/saves/test_persist.sh",        # game-governor 7.2
    "tests/saves/test_savesync.sh",       # game-governor 7.2
    "tests/selftest/test_selftest_device.sh",  # build-speed 3.2
    "tests/card/test_card.sh",            # device-fixes 5.3
    "tests/clock/test_clock.sh",          # device-fixes 9.1
    "tests/sleep/test_sleep.sh",          # device-fixes 8.3
])
def test_shell_suite(script):
    cmd = Container(
        image=ensure_builder(get_target("vm")), volumes={REPO_ROOT: "/src"}, workdir="/src"
    ).argv(f"busybox sh {script}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout)
    assert "FAIL" not in r.stdout
    assert r.returncode == 0, r.stdout + r.stderr
