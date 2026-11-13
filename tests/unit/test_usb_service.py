"""usb-device-access task 3.4: the r36os-usb service. The gadget script itself is tested in
busybox (tests/usb/test_usb_gadget.sh)."""

import re

from r36os.paths import REPO_ROOT

INIT = (REPO_ROOT / "rootfs/overlay/etc/init.d/r36os-usb").read_text()
CONFIGURE = (REPO_ROOT / "rootfs/configure.sh").read_text()
GADGET = REPO_ROOT / "rootfs/overlay/usr/libexec/r36os/usb-gadget"


def test_service_runs_the_gadget_under_supervision():
    assert INIT.startswith("#!/sbin/openrc-run\n")
    assert 'supervisor="supervise-daemon"' in INIT
    assert 'command="/usr/libexec/r36os/usb-gadget"' in INIT
    assert 'command_args="run"' in INIT


def test_service_order_after_mounts_and_logd_before_the_frontend():
    deps = re.search(r"depend\(\) \{(.*?)\n\}", INIT, re.S).group(1)
    assert "need localmount" in deps
    assert "after r36os-logd" in deps
    assert "before frontend" in deps


def test_without_a_udc_the_service_starts_nothing():
    # the vm: no /sys/class/udc entry, so no supervised process and no boot delay
    start = re.search(r"^start\(\) \{(.*?)^\}", INIT, re.S | re.M).group(1)
    assert "has_udc" in start and "return 0" in start
    assert start.index("has_udc") < start.index("default_start")


def test_service_is_enabled_on_every_system():
    line = re.search(r'^for s in seatd .*?; do', CONFIGURE, re.S | re.M).group(0)
    assert "r36os-usb" in line
    assert line.index("r36os-logd") < line.index("r36os-usb") < line.index("frontend")


def test_overlay_scripts_are_executable():
    assert GADGET.stat().st_mode & 0o111
    assert (REPO_ROOT / "rootfs/overlay/etc/init.d/r36os-usb").stat().st_mode & 0o111
