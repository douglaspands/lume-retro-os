"""Overlay services and scripts are executable (rc-update refuses a service without +x)."""

import os

import pytest

from r36os.paths import REPO_ROOT

OVERLAY = REPO_ROOT / "rootfs/overlay"
EXECUTABLES = sorted(
    p for d in ("etc/init.d", "usr/libexec/r36os", "usr/libexec/r36os/frontends", "usr/bin")
    for p in (OVERLAY / d).glob("*")
    if p.is_file() and p.suffix != ".sh"  # *.sh are libraries (lib.sh, logs.sh)
)


@pytest.mark.parametrize("path", EXECUTABLES, ids=lambda p: str(p.relative_to(OVERLAY)))
def test_executable(path):
    assert os.access(path, os.X_OK), f"{path.relative_to(OVERLAY)} is not executable"
