"""build-speed 8.1: the noarch fragments split from rootfs/overlay (design D2)."""

import re

import pytest

from r36os import fragments as frag
from r36os import packages
from r36os.paths import REPO_ROOT

FRAGMENTS = ("lume-usb", "lume-net", "lume-audio", "lume-saves", "lume-diag", "lume-power",
             "lume-games", "lume-launcher-data", "lume-retroarch-cfg", "lume-shaders")

# services that `push --hot` restarts (empty: applied at the next boot or not restartable)
RESTART = {
    "lume-usb": "", "lume-net": "bluetooth r36os-hostshare", "lume-audio": "r36os-mixer r36os-jack",
    "lume-saves": "r36os-persist r36os-savesync", "lume-diag": "", "lume-power": "",
    "lume-games": "lume-index r36os-playlists", "lume-launcher-data": "",
    "lume-retroarch-cfg": "", "lume-shaders": "",
}

# the only file left in the overlay: the build writes it (version.os_release())
OVERLAY_KEEPS = {"etc/os-release"}


def _apkbuild(name):
    return (REPO_ROOT / "aports" / name / "APKBUILD").read_text()


@pytest.mark.parametrize("name", FRAGMENTS)
def test_fragment_is_noarch_without_elf(name):
    aport = REPO_ROOT / "aports" / name
    assert packages.is_noarch_aport(aport / "APKBUILD")
    packages.check_noarch_aport(aport)


@pytest.mark.parametrize("name", FRAGMENTS)
def test_fragment_depends_on_core_and_lists_its_restarts(name):
    text = _apkbuild(name)
    assert re.search(r'^depends="lume-core"$', text, re.M)
    assert f'_lume_restart="{RESTART[name]}"' in text
    assert frag._assignment(text, "_lume_restart") == RESTART[name]


@pytest.mark.parametrize("name", FRAGMENTS)
def test_fragment_restarts_only_services_it_ships(name):
    shipped = {p.name for p in (REPO_ROOT / "aports" / name / "files/etc/init.d").glob("*")}
    for svc in RESTART[name].split():
        assert svc in shipped or svc in {"bluetooth"}, svc  # bluetooth is bluez-openrc's


def test_a_fragment_is_built_after_the_fragment_it_depends_on(tmp_path):
    # abuild -r installs `depends` before building: lume-core must come first
    order = packages._order(REPO_ROOT / "aports", ["lume-usb", "lume-net", "lume-core"])
    assert order.index("lume-core") < order.index("lume-usb")
    assert order.index("lume-core") < order.index("lume-net")


def test_image_installs_every_fragment():
    names = {line.split("#")[0].strip() for line in
             (REPO_ROOT / "rootfs/packages.txt").read_text().splitlines()}
    assert set(FRAGMENTS) <= names


def test_overlay_keeps_only_what_the_build_generates():
    root = REPO_ROOT / "rootfs/overlay"
    left = {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()}
    assert left == OVERLAY_KEEPS


def test_packages_that_shadow_alpine_files_take_them_over():
    for name in ("lume-net", "lume-power"):
        text = _apkbuild(name)
        assert "replaces_priority=" in text and "replaces=" in text, name
