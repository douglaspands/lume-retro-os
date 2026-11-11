"""Image version (D15): the build timestamp, `YYYYMMDD-HHMMSS`.

The same value goes to /etc/os-release (BUILD_ID), to BOOT/VERSION (readable on a PC) and
to the folder and image names in out/images/<target>/. The repository commit is recorded
in the image build.json, for traceability.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import asdict, dataclass

from r36os.paths import REPO_ROOT

VERSION_ID = "0.1.0"
BUILD_ID_RE = re.compile(r"^\d{8}-\d{6}$")


def _git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


@dataclass(frozen=True)
class BuildVersion:
    build_id: str     # 20261109-214233
    date: str         # 2026-11-09T21:42:33
    commit: str       # commit hash (empty outside a git repository)
    dirty: bool       # there were uncommitted changes

    def as_dict(self) -> dict:
        return {"version": VERSION_ID, **asdict(self)}


def current(now: float | None = None) -> BuildVersion:
    """The version of this build: computed once and passed to every stage."""
    t = time.localtime(now)
    return BuildVersion(
        build_id=time.strftime("%Y%m%d-%H%M%S", t),
        date=time.strftime("%Y-%m-%dT%H:%M:%S", t),
        commit=_git("rev-parse", "HEAD"),
        dirty=bool(_git("status", "--porcelain", "--untracked-files=no")),
    )


def os_release(v: BuildVersion) -> str:
    """Contents of the image /etc/os-release."""
    return (
        'NAME="Lume Retro OS"\n'
        "ID=lumeretro\n"
        "ID_LIKE=alpine\n"
        f"VERSION_ID={VERSION_ID}\n"
        f'VERSION="{VERSION_ID} ({v.build_id})"\n'
        f"BUILD_ID={v.build_id}\n"
        f'PRETTY_NAME="Lume Retro OS {VERSION_ID} ({v.build_id})"\n'
    )


def boot_version_file(target: str, v: BuildVersion) -> str:
    """BOOT/VERSION: tells on a PC which build is on the card."""
    return (f"Lume Retro OS {VERSION_ID}\n"
            f"build: {v.build_id}\n"
            f"target: {target}\n"
            f"date: {v.date}\n"
            f"commit: {v.commit or '?'}{' (dirty)' if v.dirty else ''}\n")
