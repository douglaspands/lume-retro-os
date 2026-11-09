"""Suítes em shell (busybox) que rodam no container do builder."""

import shutil
import subprocess

import pytest

from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT
from r36os.targets import get_target

pytestmark = pytest.mark.skipif(shutil.which("podman") is None, reason="sem podman")


@pytest.mark.parametrize("script", [
    "tests/initramfs/test_storage.sh",   # 4.1-4.3
    "tests/playlists/test_playlists.sh",  # 6.2
])
def test_shell_suite(script):
    cmd = Container(
        image=ensure_builder(get_target("vm")), volumes={REPO_ROOT: "/src"}, workdir="/src"
    ).argv(f"busybox sh {script}")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout)
    assert "FAIL" not in r.stdout
    assert r.returncode == 0, r.stdout + r.stderr
