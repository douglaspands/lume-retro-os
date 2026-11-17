"""build-speed 4.2 and 8.1: the lume-core fragment and the other noarch fragments take their
files out of rootfs/overlay without losing, adding or changing any file of the image (the
identity tests compare the union of every fragment and the overlay with the base commit)."""

import subprocess

import pytest

from r36os import packages
from r36os.paths import REPO_ROOT

BASE_COMMIT = "76b148d"  # the last commit with every file still in rootfs/overlay
APORT = REPO_ROOT / "aports/lume-core"
FILES = APORT / "files"
OVERLAY = REPO_ROOT / "rootfs/overlay"

# What the fragment ships (design D2, mapped to the real paths of the overlay)
CORE = {
    "etc/conf.d/dmesg", "etc/conf.d/frontend", "etc/hostname", "etc/init.d/frontend",
    "etc/init.d/r36os-logd", "etc/issue", "etc/motd",
    "usr/libexec/r36os/bootlog", "usr/libexec/r36os/frontends/lume",
    "usr/libexec/r36os/frontends/retroarch", "usr/libexec/r36os/lib.sh",
    "usr/libexec/r36os/logd", "usr/libexec/r36os/logs.sh", "usr/libexec/r36os/rc-tee",
    "usr/libexec/r36os/session",
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
    "usr/libexec/r36os/power-profiles.sh",  # game-governor 1.1: profile validator (lume-power)
    "usr/bin/r36os-power",                  # game-governor 2.2: the power service (lume-power)
    "etc/init.d/r36os-power",
    "usr/share/lume/power/ga36.conf",
    "usr/share/lume/power/r36s.conf",
    "usr/libexec/r36os/vm-net",             # virtual-gamepad 3.3: the vm's ssh network (lume-net)
    "etc/init.d/r36os-vmnet",
}


def test_aports_and_overlay_together_are_the_overlay_before_the_move():
    base = _base_overlay()
    seen: dict[str, str] = {}
    for root in _roots():
        for rel in _tree(root):
            assert rel not in seen, f"{rel} is in {seen[rel]} and in {root}"
            seen[rel] = str(root)
    assert set(seen) - ADDED_AFTER_MOVE == set(base)


# files edited on purpose after the move (only their mode is still held to the base commit)
EDITED_AFTER_MOVE = {
    "usr/libexec/r36os/hwinfo",     # 8.2: the fragments section
    "usr/libexec/r36os/jack",       # R36S 2026-11-17: dd reads the jack events (od failed)
    "usr/share/lume/i18n/en.toml",  # game-governor 3.2: the low-battery text
    "usr/share/lume/i18n/pt.toml",
    "usr/share/lume/i18n/es.toml",
    "usr/libexec/r36os/logd",       # game-governor 1.2: the sample without external processes
    "usr/libexec/r36os/logs.sh",
    "usr/libexec/r36os/selftest",   # lume-hud-actions D9: Start + Select stays in the game
    "usr/share/lume/runners.d/retroarch.toml",  # lume-hud-actions D3: actions and overlay
    # lume-hud-actions D5, D9: the pictures and the menu keys of RetroArch
    "usr/share/r36os/retroarch-lume.cfg",
    "usr/share/r36os/factory/retroarch/retroarch.cfg",
    "usr/share/libretro/autoconfig/udev/R36S Gamepad.cfg",
    "usr/share/libretro/autoconfig/udev/GA36-MB Gamepad.cfg",
}


def test_every_file_keeps_its_content_and_mode():
    base = _base_overlay()
    for root in _roots():
        for rel in _tree(root) - ADDED_AFTER_MOVE:
            mode, sha = base[rel]
            if rel in EDITED_AFTER_MOVE:
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
