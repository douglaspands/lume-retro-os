"""Overlay services and scripts are executable (rc-update refuses a service without +x)."""

import os

import pytest

from lume_tool.paths import REPO_ROOT

OVERLAY = REPO_ROOT / "rootfs/overlay"
# the noarch fragments (lume-*) ship their files at the image paths; the package keeps the git modes
FRAGMENT_TREES = sorted((REPO_ROOT / "aports").glob("lume-*/files"))
EXECUTABLES = sorted(
    p for tree in (OVERLAY, *FRAGMENT_TREES)
    for d in ("etc/init.d", "usr/libexec/lume", "usr/libexec/lume/frontends", "usr/bin")
    for p in (tree / d).glob("*")
    if p.is_file() and p.suffix != ".sh"  # *.sh are libraries (lib.sh, logs.sh)
)


@pytest.mark.parametrize("path", EXECUTABLES, ids=lambda p: str(p.relative_to(REPO_ROOT)))
def test_executable(path):
    assert os.access(path, os.X_OK), f"{path.relative_to(REPO_ROOT)} is not executable"
