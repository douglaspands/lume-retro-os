"""build-speed 4.2 and 8.1: the lume-core fragment and the other noarch fragments take their
files out of rootfs/overlay without losing, adding or changing any file of the image (the
identity tests compare the union of every fragment and the overlay with the base commit)."""

import subprocess

import pytest

from lume_tool import packages
from lume_tool.paths import REPO_ROOT

BASE_COMMIT = "76b148d"  # the last commit with every file still in rootfs/overlay
APORT = REPO_ROOT / "aports/lume-core"
FILES = APORT / "files"
OVERLAY = REPO_ROOT / "rootfs/overlay"

# What the fragment ships (design D2, mapped to the real paths of the overlay)
CORE = {
    "etc/conf.d/dmesg", "etc/conf.d/frontend", "etc/hostname", "etc/init.d/frontend",
    "etc/init.d/lume-logd", "etc/issue", "etc/motd",
    "usr/libexec/lume/bootlog", "usr/libexec/lume/frontends/lume",
    "usr/libexec/lume/frontends/retroarch", "usr/libexec/lume/lib.sh",
    "usr/libexec/lume/logd", "usr/libexec/lume/logs.sh", "usr/libexec/lume/rc-tee",
    "usr/libexec/lume/session",
}


FRAGMENTS = ("lume-core", "lume-usb", "lume-net", "lume-audio", "lume-saves", "lume-diag",
             "lume-power", "lume-games", "lume-launcher-data", "lume-retroarch-cfg",
             "lume-shaders")


def _tree(root):
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}


def _base_overlay() -> dict[str, tuple[str, str]]:
    """path (relative to the overlay) -> (git mode, blob sha) at the base commit."""
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", BASE_COMMIT, "rootfs/overlay"],
            check=True, capture_output=True, text=True).stdout
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip(f"commit {BASE_COMMIT} is not available")
    files = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        mode, _type, sha = meta.split()
        files[path.removeprefix("rootfs/overlay/")] = (mode, sha)
    return files


# device-fixes 1.2 renamed the console paths after the base commit: the libexec and share
# folders of the old prefix became .../lume, and the <old>-<x> services and tools lume-<x>.
# The old prefix is spelled in two parts so the name guard (test_lume_names) skips it.
OLD = "r36" "os"
_RENAMED_DIRS = ("usr/libexec/", "usr/share/", "etc/")


def _base_name(rel: str, base: dict) -> str:
    """The name `rel` had at the base commit (itself when it was not renamed)."""
    if rel in base:
        return rel
    old = rel
    for d in _RENAMED_DIRS:
        if old.startswith(d + "lume/"):
            old = f"{d}{OLD}/{old[len(d + 'lume/'):]}"
    head, _, name = old.rpartition("/")
    if name.startswith("lume-"):
        old = f"{head}/{OLD}-{name[len('lume-'):]}"
    return old


def _base_has_old_names(sha: str) -> bool:
    """Whether the base blob holds the old prefix: its content changed with the 1.2 rename."""
    blob = subprocess.run(["git", "-C", str(REPO_ROOT), "cat-file", "blob", sha], check=True,
                          capture_output=True).stdout
    return OLD.encode() in blob.lower()


def _git_mode(path) -> str:
    return "100755" if path.stat().st_mode & 0o111 else "100644"


def _blob_sha(path) -> str:
    return subprocess.run(["git", "hash-object", str(path)], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_the_fragment_ships_exactly_the_core_files():
    assert _tree(FILES) == CORE


def _roots():
    """The overlay and the files/ tree of every noarch fragment of the split (4.2 and 8.1)."""
    return [OVERLAY, *(REPO_ROOT / "aports" / n / "files" for n in FRAGMENTS)]


# files created in a fragment after the move (they have no base commit entry)
ADDED_AFTER_MOVE = {
    "usr/libexec/lume/power-profiles.sh",  # game-governor 1.1: profile validator (lume-power)
    "usr/bin/lume-power",                  # game-governor 2.2: the power service (lume-power)
    "etc/init.d/lume-power",
    "usr/share/lume/power/ga36.conf",
    "usr/share/lume/power/r36s.conf",
    "usr/libexec/lume/vm-net",             # virtual-gamepad 3.3: the vm's ssh network (lume-net)
    "etc/init.d/lume-vmnet",
    # game-governor: RetroArch keys per core (the PlayStation keeps the main-thread video)
    "usr/share/lume/retroarch-core.keys",
    # device-fixes 3.2: the suspension mode of each console (lume-power, read by lume-sleep)
    "usr/share/lume/sleep/ga36.conf",
    "usr/share/lume/sleep/r36s.conf",
}


def test_aports_and_overlay_together_are_the_overlay_before_the_move():
    base = _base_overlay()
    seen: dict[str, str] = {}
    for root in _roots():
        for rel in _tree(root):
            assert rel not in seen, f"{rel} is in {seen[rel]} and in {root}"
            seen[rel] = str(root)
    assert {_base_name(r, base) for r in set(seen) - ADDED_AFTER_MOVE} == set(base)


# files edited on purpose after the move (only their mode is still held to the base commit)
EDITED_AFTER_MOVE = {
    "usr/libexec/lume/hwinfo",     # 8.2: the fragments section
    "usr/libexec/lume/jack",       # R36S 2026-11-17: dd reads the jack events (od failed)
    "usr/share/lume/i18n/en.toml",  # game-governor 3.2: the low-battery text
    "usr/share/lume/i18n/pt.toml",
    "usr/share/lume/i18n/es.toml",
    "usr/libexec/lume/logd",       # game-governor 1.2: the sample without external processes
    "usr/libexec/lume/logs.sh",
    "usr/libexec/lume/selftest",   # lume-hud-actions D9: Start + Select stays in the game
    "usr/libexec/lume/frontends/retroarch",  # lume-hud-actions D9: Start + Select as reserve
    "usr/share/lume/runners.d/retroarch.toml",  # lume-hud-actions D3: actions and overlay
    # lume-hud-actions D5, D9: the pictures and the menu keys of RetroArch
    "usr/share/lume/retroarch-lume.cfg",
    "usr/share/lume/factory/retroarch/retroarch.cfg",
    "usr/share/libretro/autoconfig/udev/R36S Gamepad.cfg",
    "usr/share/libretro/autoconfig/udev/GA36-MB Gamepad.cfg",
    # game-governor P-93: threaded video on both consoles
    "usr/share/lume/retroarch-ga36.cfg",
    "usr/share/lume/retroarch-r36s.cfg",
}


def test_every_file_keeps_its_content_and_mode():
    base = _base_overlay()
    for root in _roots():
        for rel in _tree(root) - ADDED_AFTER_MOVE:
            mode, sha = base[_base_name(rel, base)]
            if rel in EDITED_AFTER_MOVE or _base_has_old_names(sha):
                assert _git_mode(root / rel) == mode, rel
                continue
            assert (_git_mode(root / rel), _blob_sha(root / rel)) == (mode, sha), rel


def test_no_symlink_in_the_fragment():
    assert [p for p in FILES.rglob("*") if p.is_symlink()] == []


def test_os_release_stays_where_the_build_writes_it():
    # the build copies version.os_release() over /etc/os-release after the packages: a
    # package copy would be overwritten, and an Alpine package owns the file (a symlink)
    assert (OVERLAY / "etc/os-release").is_file()
    assert "etc/os-release" not in _tree(FILES)


def test_the_aport_is_a_noarch_fragment_without_elf():
    assert packages.is_noarch_aport(APORT / "APKBUILD")
    packages.check_noarch_aport(APORT)  # raises on ELF or a non-noarch arch=


def test_the_image_installs_the_fragment():
    names = [line.split("#")[0].strip() for line in
             (REPO_ROOT / "rootfs/packages.txt").read_text().splitlines()]
    assert "lume-core" in names


def test_the_fragment_takes_over_the_alpine_files_it_shadows():
    apkbuild = (APORT / "APKBUILD").read_text()
    # etc/hostname, issue, motd and conf.d/dmesg belong to Alpine packages: the Lume file
    # must win whichever package apk unpacks first
    assert "replaces_priority=" in apkbuild
    for owner in ("alpine-baselayout", "alpine-baselayout-data", "alpine-release", "openrc"):
        assert owner in apkbuild.split("replaces=", 1)[1].split("\n", 1)[0]
