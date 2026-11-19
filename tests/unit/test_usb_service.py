"""usb-device-access task 3.4: the lume-usb service. The gadget script itself is tested in
busybox (tests/usb/test_usb_gadget.sh)."""

import re

from lume_tool.paths import REPO_ROOT

INIT = (REPO_ROOT / "aports/lume-usb/files/etc/init.d/lume-usb").read_text()
CONFIGURE = (REPO_ROOT / "rootfs/configure.sh").read_text()
GADGET = REPO_ROOT / "aports/lume-usb/files/usr/libexec/lume/usb-gadget"


def test_service_runs_the_gadget_under_supervision():
    assert INIT.startswith("#!/sbin/openrc-run\n")
    assert 'supervisor="supervise-daemon"' in INIT
    assert 'command="/usr/libexec/lume/usb-gadget"' in INIT
    assert 'command_args="run"' in INIT


def test_service_order_after_mounts_and_logd_before_the_frontend():
    deps = re.search(r"depend\(\) \{(.*?)\n\}", INIT, re.S).group(1)
    assert "need localmount" in deps
    assert "after lume-logd" in deps
    assert "before frontend" in deps


def test_without_a_udc_the_service_starts_nothing():
    # the vm: no /sys/class/udc entry, so no supervised process and no boot delay
    start = re.search(r"^start\(\) \{(.*?)^\}", INIT, re.S | re.M).group(1)
    assert "has_udc" in start and "return 0" in start
    assert start.index("has_udc") < start.index("default_start")


def test_service_is_enabled_on_every_system():
    line = re.search(r'^for s in seatd .*?; do', CONFIGURE, re.S | re.M).group(0)
    assert "lume-usb" in line
    assert line.index("lume-logd") < line.index("lume-usb") < line.index("frontend")


def test_the_usb_network_has_its_dhcp_server():
    # Alpine's busybox has no udhcpd applet: it comes with busybox-extras (GA36 proof with
    # build 20261113-192923, the PC got no address)
    packages = (REPO_ROOT / "rootfs/packages.txt").read_text().split()
    for name in ("umtprd", "dropbear", "busybox-extras"):
        assert name in packages, name
    assert "dropbear-convert" not in packages      # no host key on the card any more (D4)


def test_root_logs_in_without_a_password_on_the_cable_only():
    # D4 (decided 2026-11-13): open root over ssh, on the USB network address only
    gadget = GADGET.read_text()
    assert '"$DROPBEAR" -F -E -R -B -j -k -p "$CONSOLE_ADDR:22"' in gadget
    assert "CONSOLE_ADDR=10.55.0.1" in gadget
    assert "passwd -d root" in CONFIGURE


def test_overlay_scripts_are_executable():
    assert GADGET.stat().st_mode & 0o111
    assert (REPO_ROOT / "aports/lume-usb/files/etc/init.d/lume-usb").stat().st_mode & 0o111
