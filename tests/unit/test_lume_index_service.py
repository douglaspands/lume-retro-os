"""lume-launcher task 5.5: the lume-index service. The scan itself is tested by cargo
(lume/lume-index/tests/) and the restart on disconnect by tests/usb/test_usb_gadget.sh."""

import re

from r36os.paths import REPO_ROOT

INIT_PATH = REPO_ROOT / "rootfs/overlay/etc/init.d/lume-index"
INIT = INIT_PATH.read_text()
CONFIGURE = (REPO_ROOT / "rootfs/configure.sh").read_text()
GADGET = (REPO_ROOT / "rootfs/overlay/usr/libexec/r36os/usb-gadget").read_text()


def test_runs_in_the_background_as_the_game_user():
    assert INIT.startswith("#!/sbin/openrc-run\n")
    assert "command=/usr/bin/lume-index" in INIT
    assert 'command_user="game:game"' in INIT
    assert "command_background=yes" in INIT
    assert INIT_PATH.stat().st_mode & 0o111


def test_order_after_the_card_before_the_frontend():
    deps = re.search(r"depend\(\) \{(.*?)\n\}", INIT, re.S).group(1)
    assert "need localmount" in deps
    assert "after r36os-persist" in deps
    assert "before frontend" in deps


def test_without_roms_it_starts_nothing():
    start = re.search(r"^start\(\) \{(.*?)^\}", INIT, re.S | re.M).group(1)
    assert "mountpoint -q /storage" in start and "return 0" in start
    assert start.index("mountpoint") < start.index("default_start")


def test_enabled_before_the_frontend():
    line = re.search(r"^for s in seatd .*?; do", CONFIGURE, re.S | re.M).group(0)
    assert line.index("r36os-persist") < line.index("lume-index") < line.index("frontend")


def test_usb_gadget_restarts_it_when_the_pc_lets_go():
    assert "$RC_SERVICE lume-index restart" in GADGET
    assert "RC_SERVICE=${RC_SERVICE:-rc-service}" in GADGET
