"""virtual-gamepad 3.3: `lume dev`/`push` reach the vm at 127.0.0.1:<port>, and the vm
image (only it) brings up its QEMU user network with root ssh, off the boot critical path."""

import os
import re
import subprocess

import pytest

from lume_tool import dev
from lume_tool.cli import _parser
from lume_tool.paths import REPO_ROOT
from lume_tool.push import CONSOLE_ADDR, PushError, Remote, split_host

NET = REPO_ROOT / "aports/lume-net/files"
VMNET = NET / "usr/libexec/lume/vm-net"
INIT = (NET / "etc/init.d/lume-vmnet").read_text()
CONFIGURE = (REPO_ROOT / "rootfs/configure.sh").read_text()


# --- host:port in the ssh layer ---------------------------------------------------------

def test_default_cable_address_is_unchanged():
    base = Remote().base
    assert base[-1] == f"root@{CONSOLE_ADDR}" == "root@10.55.0.1"
    assert "-p" not in base


def test_host_with_port_adds_dash_p():
    r = Remote("127.0.0.1:2222")
    assert r.host == "127.0.0.1:2222"      # kept as given (wait_for_console, messages)
    assert r.base[-1] == "root@127.0.0.1"
    assert r.base[r.base.index("-p") + 1] == "2222"
    assert r.base.index("-p") < len(r.base) - 1


def test_dev_ssh_argv_with_port():
    argv = dev.ssh_argv("127.0.0.1:2222", "uname -m", tty=True)
    assert argv[-2:] == ["root@127.0.0.1", "uname -m"]
    assert argv[argv.index("-p") + 1] == "2222"
    assert "-tt" in argv
    assert "-p" not in dev.ssh_argv(CONSOLE_ADDR, "true")


@pytest.mark.parametrize("addr,want", [
    ("10.55.0.1", ("10.55.0.1", None)),
    ("127.0.0.1:2222", ("127.0.0.1", 2222)),
    ("localhost:2300", ("localhost", 2300)),
    ("fe80::1", ("fe80::1", None)),
])
def test_split_host(addr, want):
    assert split_host(addr) == want


@pytest.mark.parametrize("addr", ["127.0.0.1:", "127.0.0.1:ssh", "127.0.0.1:0",
                                  "127.0.0.1:70000"])
def test_split_host_refuses_a_bad_port(addr):
    with pytest.raises(PushError):
        split_host(addr)


def test_push_and_dev_take_host():
    p = _parser()
    assert p.parse_args(["push", "--host", "127.0.0.1:2222"]).host == "127.0.0.1:2222"
    assert p.parse_args(["push"]).host is None
    assert p.parse_args(["dev", "--host", "127.0.0.1:2222", "sh", "uname", "-m"]).host \
        == "127.0.0.1:2222"
    # after the action too (the form of the 3.3 live check); the command stays intact
    a = p.parse_args(["dev", "sh", "--host", "127.0.0.1:2222", "uname", "-m"])
    assert a.host == "127.0.0.1:2222" and a.cmd == ["uname", "-m"]
    assert p.parse_args(["dev", "--host", "h:1", "wait"]).host == "h:1"
    assert p.parse_args(["dev", "wait"]).host is None
    assert p.parse_args(["dev", "--host", "a:1", "keys", "--host", "b:2", "a"]).host == "b:2"


def test_main_push_passes_the_host(monkeypatch):
    from lume_tool import push

    seen = {}

    def fake_push(build, remote, yes, **kw):
        seen["base"] = remote.base
        return 0

    monkeypatch.setattr(push, "push", fake_push)
    assert push.main_push("latest", True, host="127.0.0.1:2222") == 0
    assert seen["base"][-1] == "root@127.0.0.1" and "2222" in seen["base"]
    assert push.main_push("latest", True) == 0
    assert seen["base"][-1] == "root@10.55.0.1"


# --- the vm image: network and dropbear ------------------------------------------------

def test_vmnet_is_enabled_on_the_vm_only():
    case = re.search(r'^case "\$BOARD" in\n(.*?)^esac', CONFIGURE, re.S | re.M).group(1)
    assert "vm) add lume-vmnet default ;;" in case
    # nowhere else: not in the common runlevel lists, not for ga36/r36s
    assert CONFIGURE.count("lume-vmnet default") == 1
    for line in CONFIGURE.splitlines():
        if "lume-vmnet" in line and "add" in line:
            assert line.strip().startswith("vm)"), line


def test_vmnet_is_not_a_console_service():
    selftest = (REPO_ROOT / "aports/lume-diag/files/usr/libexec/lume/selftest-device")
    services = re.search(r"^device_services\(\) \{(.*?)^\}", selftest.read_text(),
                         re.S | re.M).group(1)
    assert "lume-vmnet" not in services


def test_service_starts_after_the_frontend_and_only_with_a_vm_nic():
    deps = re.search(r"depend\(\) \{(.*?)\n\}", INIT, re.S).group(1)
    assert "after frontend" in deps and "before" not in deps
    assert 'supervisor="supervise-daemon"' in INIT
    assert 'command="/usr/libexec/lume/vm-net"' in INIT and 'command_args="run"' in INIT
    start = re.search(r"^start\(\) \{(.*?)^\}", INIT, re.S | re.M).group(1)
    assert start.index("has_vm_nic") < start.index("return 0") < start.index("default_start")
    nic = re.search(r"^has_vm_nic\(\) \{(.*?)^\}", INIT, re.S | re.M).group(1)
    assert '= vm ] || return 1' in nic


def test_dropbear_on_the_leased_address_like_the_cable():
    text = VMNET.read_text()
    assert 'exec "$DROPBEAR" -F -E -R -B -j -k -p "$addr:22"' in text
    # address only from DHCP: no default route, no resolv.conf
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    assert "route" not in code and "resolv.conf" not in code


def test_scripts_are_executable():
    assert VMNET.stat().st_mode & 0o111
    assert (NET / "etc/init.d/lume-vmnet").stat().st_mode & 0o111


# --- vm-net in a shell with a fake sysfs and fake tools ---------------------------------

def _fake_tools(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "calls.log"
    for name in ("ip", "dropbear"):
        f = bin_dir / name
        f.write_text(f'#!/bin/sh\necho "{name} $*" >> "{log}"\n')
        f.chmod(0o755)
    # udhcpc: calls its -s script with "bound", like busybox after a lease
    udhcpc = bin_dir / "udhcpc"
    udhcpc.write_text(
        '#!/bin/sh\n'
        f'echo "udhcpc $*" >> "{log}"\n'
        'while [ $# -gt 0 ]; do case "$1" in -s) s="$2"; shift ;; -i) i="$2"; shift ;; esac; '
        'shift; done\n'
        'interface="$i" ip=10.0.2.15 mask=24 "$s" bound\n')
    udhcpc.chmod(0o755)
    return bin_dir, log


def _sysfs(tmp_path, drivers):
    net = tmp_path / "net"
    for ifc, drv in drivers.items():
        d = net / ifc / "device"
        d.mkdir(parents=True)
        (tmp_path / "drivers" / drv).mkdir(parents=True, exist_ok=True)
        os.symlink(tmp_path / "drivers" / drv, d / "driver")
    net.mkdir(exist_ok=True)
    return net


def _run(tmp_path, board, drivers, *args):
    bin_dir, log = _fake_tools(tmp_path)
    board_file = tmp_path / "board"
    board_file.write_text(board + "\n")
    env = {"PATH": f"{bin_dir}:/usr/bin:/bin", "BOARD_FILE": str(board_file),
           "NET_CLASS": str(_sysfs(tmp_path, drivers)), "KMSG": str(tmp_path / "kmsg"),
           "SELF": str(VMNET), "RUN_DIR": str(tmp_path / "run")}
    r = subprocess.run(["/bin/sh", str(VMNET), *args], env=env, capture_output=True,
                       text=True)
    return r, (log.read_text() if log.exists() else "")


def test_ifname_finds_only_virtio_net(tmp_path):
    r, _ = _run(tmp_path, "vm", {"lo": "none", "eth0": "virtio_net"}, "ifname")
    assert r.returncode == 0 and r.stdout.strip() == "eth0"


def test_ifname_fails_without_a_virtio_nic(tmp_path):
    # test-vm (-nic none) and the consoles (usb0 is the NCM gadget)
    r, _ = _run(tmp_path, "vm", {"usb0": "g_ncm"}, "ifname")
    assert r.returncode == 1 and r.stdout == ""


def test_run_takes_a_lease_then_dropbear_on_that_address(tmp_path):
    r, calls = _run(tmp_path, "vm", {"eth0": "virtio_net"}, "run")
    assert r.returncode == 0, r.stderr
    lines = calls.splitlines()
    assert lines[0] == "ip link set eth0 up"
    assert lines[1].startswith("udhcpc -i eth0 -f -q -n ")
    assert "ip -4 addr add 10.0.2.15/24 dev eth0" in lines
    assert lines[-1] == "dropbear -F -E -R -B -j -k -p 10.0.2.15:22"
    assert not any("route" in line for line in lines)


def test_run_does_nothing_on_a_console(tmp_path):
    r, calls = _run(tmp_path, "r36s", {"eth0": "virtio_net"}, "run")
    assert r.returncode == 1
    assert calls == ""
