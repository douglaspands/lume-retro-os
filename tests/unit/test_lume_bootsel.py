"""lume-bootsel (boot-dtb-select, tasks 4.1 to 4.6): the device tree selection of the
initramfs, run on the PC against a fake root (--root).

The binary is built static once per session in the x86_64 builder (musl), with libfdt
from the dtc tarball of the aport (.cache/distfiles, fetched by
`r36os pkg vm lume-bootsel`). In the fake root a device node that is a regular file is a
description of the device:

- /dev/input/eventN: input_event records read by the list; eventN.held: the codes held at
  power on;
- /dev/gpiochipN: lines of "<offset> in|out free|used <level>";
- /dev/i2c-N: the addresses that answer, in hex.
"""

import hashlib
import os
import re
import shutil
import struct
import subprocess

import pytest

from r36os import fdt
from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT, cache_dir
from r36os.targets import TARGETS

APORT = REPO_ROOT / "aports/lume-bootsel"
SOURCE = APORT / "lume-bootsel.c"
APKBUILD = (APORT / "APKBUILD").read_text()
DTC_VER = re.search(r"^_dtcver=(\S+)$", APKBUILD, re.M).group(1)
DTC_TAR = cache_dir() / "distfiles" / f"dtc-{DTC_VER}.tar.xz"

GA36_COMPAT = ("ga36mb,ga36-mb-v1.2", "allwinner,sun8i-a33")
R36S_COMPAT = ("r36s,r36s-v5", "rockchip,rk3326")
KEY_VOLUMEDOWN, KEY_VOLUMEUP, BTN_EAST = 114, 115, 0x131
KEYS = "select=KEY_VOLUMEDOWN\nup=KEY_VOLUMEUP\ndown=KEY_VOLUMEDOWN\nok=BTN_EAST\n"

_BUILD = f"""
apk add -q linux-headers >/dev/null
mkdir -p /w
cd /w
tar xf /distfiles/dtc-{DTC_VER}.tar.xz
cc -std=gnu11 -O2 -Wall -Wextra -Werror -DLUME_CONFIRM=1 -I dtc-{DTC_VER}/libfdt -c -o bootsel.o /src/lume-bootsel.c
cc -static -O2 -I dtc-{DTC_VER}/libfdt -o /out/lume-bootsel bootsel.o dtc-{DTC_VER}/libfdt/fdt*.c
cd dtc-{DTC_VER}
make -s NO_PYTHON=1 NO_YAML=1 NO_VALGRIND=1 libfdt/libfdt.a fdtget.o util.o >/dev/null 2>&1 || true
cc -static -o /out/fdtget fdtget.o util.o libfdt/libfdt.a 2>/dev/null || true
"""


@pytest.fixture(scope="session")
def tools(tmp_path_factory):
    if shutil.which("podman") is None:
        pytest.skip("no podman")
    if not DTC_TAR.exists():
        pytest.skip(f"no {DTC_TAR.name} (run: r36os pkg vm lume-bootsel --checksum)")
    digest = hashlib.sha256(SOURCE.read_bytes() + _BUILD.encode()).hexdigest()[:16]
    out = cache_dir() / "test-bin" / f"lume-bootsel-{digest}"
    if not (out / "lume-bootsel").exists():
        out.mkdir(parents=True, exist_ok=True)
        cmd = Container(image=ensure_builder(TARGETS["vm"]),
                        volumes={APORT: "/src", DTC_TAR.parent: "/distfiles", out: "/out"}
                        ).argv(_BUILD)
        r = subprocess.run(cmd, capture_output=True, text=True)
        assert r.returncode == 0, r.stdout + r.stderr
    fdtget = out / "fdtget"
    return {"bin": out / "lume-bootsel", "fdtget": fdtget if fdtget.exists() else None}


# --- fake root ----------------------------------------------------------------------------

def _cand(ident, compat=GA36_COMPAT, priority=0, default=False, rules=None, panel_id=None):
    node = {"lume,id": fdt.s(ident), "lume,priority": fdt.u32(priority)}
    if default:
        node["lume,default"] = b""
    for name, rows in (rules or {}).items():
        node[name] = fdt.u32(*[v for row in rows for v in row])
    if panel_id is not None:
        node["lume,panel-id"] = bytes.fromhex(panel_id)
    return fdt.build(fdt.Node(
        props={"compatible": fdt.s(*compat), "model": fdt.s(ident)},
        children={"lume-select": fdt.Node(props=node),
                  "memory@40000000": fdt.Node(props={"device_type": fdt.s("memory"),
                                                     "reg": fdt.u32(0x40000000, 0)}),
                  "chosen": fdt.Node(props={"stdout-path": fdt.s("serial0")})}))


class Root:
    """A fake root: running device tree, BOOT (/boot) and ROMS (/roms)."""

    def __init__(self, path, soc="a33", compat=GA36_COMPAT, running="ga36-panel1",
                 kernel="ga36/zImage"):
        self.path, self.soc, self.kernel = path, soc, kernel
        dt = path / "proc/device-tree"
        (dt / "lume-select").mkdir(parents=True)
        (dt / "compatible").write_bytes(fdt.s(*compat))
        if running:
            (dt / "lume-select/lume,id").write_bytes(fdt.s(running))
        mem = dt / "memory@40000000"
        mem.mkdir()
        (mem / "device_type").write_bytes(fdt.s("memory"))
        (mem / "reg").write_bytes(fdt.u32(0x40000000, 0x20000000))
        (mem / "name").write_bytes(fdt.s("memory"))
        (dt / "chosen").mkdir()
        for d in ("etc", "tmp", "dev/input", "sys/bus", f"boot/dtbs/{soc}", "roms"):
            (path / d).mkdir(parents=True, exist_ok=True)
        (path / "etc/soc").write_text(soc + "\n")
        (path / "boot" / kernel).parent.mkdir(parents=True, exist_ok=True)
        (path / "boot" / kernel).write_bytes(b"kernel")

    def dtb(self, name, data, soc=None):
        f = self.path / f"boot/dtbs/{soc or self.soc}/{name}"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)

    def vendor(self, *idents):
        """Converted device trees (D12) in dtbs/<soc>/vendor/, named after their lume,id."""
        for ident in idents:
            self.dtb(f"vendor/{ident}.dtb", _cand(ident))

    def ga36_panels(self, panel2_rules=None, panel2_priority=0, panel2_id=None):
        self.dtb("sun8i-a33-ga36-mb-v1.2-panel1.dtb", _cand("ga36-panel1", default=True))
        self.dtb("sun8i-a33-ga36-mb-v1.2-panel2.dtb",
                 _cand("ga36-panel2", priority=panel2_priority, rules=panel2_rules,
                       panel_id=panel2_id))

    def iio(self, addr, name, channels):
        dev = self.path / f"sys/devices/platform/soc/{addr:x}.{name}/iio:device0"
        dev.mkdir(parents=True)
        for ch, value in channels.items():
            (dev / f"in_voltage{ch}_raw").write_text(f"{value}\n")
        bus = self.path / "sys/bus/iio/devices"
        bus.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(dev, bus), bus / "iio:device0")

    def gpiochip(self, addr, lines, n=0):
        dev = self.path / f"sys/devices/platform/soc/{addr:x}.pinctrl/gpiochip{n}"
        dev.mkdir(parents=True)
        bus = self.path / "sys/bus/gpio/devices"
        bus.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(dev, bus), bus / f"gpiochip{n}")
        (self.path / f"dev/gpiochip{n}").write_text(lines)

    def i2c(self, addr, answers, bound=(), n=0):
        dev = self.path / f"sys/devices/platform/soc/{addr:x}.i2c/i2c-{n}"
        dev.mkdir(parents=True)
        bus = self.path / "sys/bus/i2c/devices"
        bus.mkdir(parents=True, exist_ok=True)
        os.symlink(os.path.relpath(dev, bus), bus / f"i2c-{n}")
        for a in bound:
            (bus / f"{n}-{a:04x}/driver").mkdir(parents=True)
        (self.path / f"dev/i2c-{n}").write_text(" ".join(f"{a:x}" for a in answers))

    def keys(self, held=(), events=(), text=KEYS):
        (self.path / "etc/bootsel-keys").write_text(text)
        ev = self.path / "dev/input/event0"
        ev.write_bytes(b"".join(struct.pack("qqHHi", 0, 0, 1, code, 1) for code in events))
        (self.path / "dev/input/event0.held").write_text(" ".join(str(c) for c in held))
        (self.path / "dev/tty1").write_text("")

    def force(self, text):
        (self.path / "boot/dtbs/force").write_text(text)

    def panel(self, panel_id, dev="1c40000.dsi.0"):
        """The panel_id a panel driver shows (D15); "" for a panel that did not answer;
        None for a DSI device with no driver bound (its probe found no panel)."""
        d = self.path / f"sys/bus/mipi-dsi/devices/{dev}"
        d.mkdir(parents=True, exist_ok=True)
        if panel_id is None:
            (d / "panel_id").unlink(missing_ok=True)
            if (d / "driver").exists():
                (d / "driver").rmdir()
            return
        (d / "driver").mkdir(exist_ok=True)
        (d / "panel_id").write_text(panel_id + "\n")

    def learned(self, **values):
        """The learned file of the SoC: write {signature: id}, or read it back."""
        f = self.path / f"roms/system/etc/dtb-{self.soc}-learned.conf"
        if values:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("".join(f"panel:{k}={v}\n" for k, v in values.items()))
            return None
        if not f.exists():
            return {}
        return dict(re.findall(r"^panel:(\w+)=(.*)$", f.read_text(), re.M))

    def serial(self, value):
        f = self.path / "sys/devices/soc0/serial_number"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(value)

    def dt_serial(self, value):
        """The /serial-number a bootloader writes into the device tree (R36S U-Boot)."""
        (self.path / "proc/device-tree/serial-number").write_bytes(fdt.s(value))

    def after_kexec(self, ident, reason, watchdog=False):
        """The second (or third) start: the kernel runs with the tree prepared before."""
        dt = self.path / "proc/device-tree"
        (dt / "lume-select/lume,id").write_bytes(fdt.s(ident))
        (dt / "chosen/lume,dtb-selected").write_bytes(fdt.s(ident, reason))
        (dt / "chosen/lume,dtb-log").write_bytes(fdt.s(f"selected {ident} (reason: {reason})\n"))
        if watchdog:
            (dt / "chosen/lume,watchdog").write_bytes(b"")

    def watchdog(self, text=""):
        """A fake /dev/watchdog: a regular file that records what is written to it."""
        f = self.path / "dev/watchdog"
        f.write_text(text)
        return f

    def prepared(self):
        return fdt.parse((self.path / "tmp/lume-bootsel.dtb").read_bytes())

    def state(self, soc=None, device=None, **values):
        name = f"dtb-{soc or self.soc}-{device}.conf" if device else f"dtb-{soc or self.soc}.conf"
        f = self.path / f"roms/system/etc/{name}"
        if values:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
            return None
        if not f.exists():
            return {}
        return dict(re.findall(r"^(\w+)=(.*)$", f.read_text(), re.M))

    def tty(self):
        return (self.path / "dev/tty1").read_text()


@pytest.fixture
def root(tmp_path):
    return Root(tmp_path / "root")


def run(tools, root, *extra, dry=True, roms=True):
    args = [str(tools["bin"]), "--root", str(root.path), "--boot", "/boot",
            "--kernel", root.kernel]
    if roms:
        args += ["--roms", "/roms"]
    if dry:
        args.append("--dry-run")
    r = subprocess.run(args + list(extra), capture_output=True, text=True, timeout=30)
    return r.returncode, r.stdout, r.stderr


def decision(out):
    return dict(re.findall(r"(\w+)=(\S+)", out))


# --- 4.1: the binary --------------------------------------------------------------------

def test_aport_builds_the_tool_and_a_static_kexec():
    assert re.search(r'^arch="all"$', APKBUILD, re.M)
    assert "-static" in APKBUILD and "--without-zlib" in APKBUILD
    assert '"$d"/lume-bootsel' in APKBUILD and '"$d"/kexec' in APKBUILD
    digest = hashlib.sha512(SOURCE.read_bytes()).hexdigest()
    assert f"{digest}  lume-bootsel.c" in APKBUILD


def test_empty_tree_logs_no_device_tree(tools, tmp_path):
    r = subprocess.run([str(tools["bin"]), "--root", str(tmp_path), "--dry-run"],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert r.stderr == "lume-bootsel: no device tree\n"


def test_bad_usage(tools):
    r = subprocess.run([str(tools["bin"]), "--bogus"], capture_output=True, text=True)
    assert r.returncode == 2 and "usage:" in r.stderr


# --- 4.2: candidates and rules ----------------------------------------------------------

def test_original_device_boots_with_the_default_without_kexec(tools, root):
    root.ga36_panels()
    rc, out, err = run(tools, root)
    assert rc == 0
    assert decision(out) == {"selected": "ga36-panel1", "reason": "default", "kexec": "no"}
    assert "no rule matched" in err
    assert "candidate ga36-panel1 (sun8i-a33-ga36-mb-v1.2-panel1.dtb) priority 0, no rules, default" in err
    assert "keeping the running device tree, no kexec" in err
    assert root.state() == {"manual": "", "good": "", "pending": "", "bad": ""}


def test_rule_that_matches(tools, root):
    root.ga36_panels(panel2_rules={"lume,adc": [(0x01c22800, 1, 800, 950)]})
    root.iio(0x01c22800, "lradc", {1: 870})
    rc, out, err = run(tools, root)
    assert decision(out)["selected"] == "ga36-panel2"
    assert decision(out)["reason"] == "rule" and decision(out)["kexec"] == "yes"
    assert "probe adc 0x1c22800 channel 1: 870 (rule 800-950) match" in err
    assert root.state()["pending"] == "ga36-panel2"    # until it reaches the frontend


def test_rule_out_of_range(tools, root):
    root.ga36_panels(panel2_rules={"lume,adc": [(0x01c22800, 1, 800, 950)]})
    root.iio(0x01c22800, "lradc", {1: 40})
    rc, out, err = run(tools, root)
    assert decision(out)["reason"] == "default"
    assert "40 (rule 800-950) no match" in err


@pytest.mark.parametrize("setup, why", [
    (lambda r: None, "no IIO device at that address"),
    (lambda r: r.iio(0x01c22800, "lradc", {0: 5}), "no channel 1 on iio:device0"),
])
def test_probe_that_fails_counts_as_no_match(tools, root, setup, why):
    root.ga36_panels(panel2_rules={"lume,adc": [(0x01c22800, 1, 800, 950)]})
    setup(root)
    rc, out, err = run(tools, root)
    assert rc == 0 and decision(out)["reason"] == "default"
    assert f"probe adc 0x1c22800 channel 1: failed ({why})" in err


def test_all_rules_of_a_candidate_must_match(tools, root):
    root.ga36_panels(panel2_rules={"lume,adc": [(0x01c22800, 1, 800, 950)],
                                   "lume,gpio": [(0x01c20800, 37, 1)]})
    root.iio(0x01c22800, "lradc", {1: 870})
    root.gpiochip(0x01c20800, "37 in free 0\n")
    rc, out, err = run(tools, root)
    assert decision(out)["reason"] == "default"
    assert "probe gpio 0x1c20800 line 37: 0 (rule 1) no match" in err


@pytest.mark.parametrize("lines, why", [
    ("37 in used 1\n", "line 37 held by a driver"),
    ("37 out free 1\n", "line 37 is not an input"),
])
def test_gpio_probe_only_reads_free_inputs(tools, root, lines, why):
    root.ga36_panels(panel2_rules={"lume,gpio": [(0x01c20800, 37, 1)]})
    root.gpiochip(0x01c20800, lines)
    rc, out, err = run(tools, root)
    assert decision(out)["reason"] == "default"
    assert f"probe gpio 0x1c20800 line 37: failed ({why})" in err


def test_gpio_rule_matches(tools, root):
    root.ga36_panels(panel2_rules={"lume,gpio": [(0x01c20800, 37, 1)]})
    root.gpiochip(0x01c20800, "36 in free 0\n37 in free 1\n")
    rc, out, err = run(tools, root)
    assert decision(out)["selected"] == "ga36-panel2"


def test_i2c_probe(tools, root):
    root.ga36_panels(panel2_rules={"lume,i2c-present": [(0x01c2ac00, 0x34), (0x01c2ac00, 0x50)]})
    root.i2c(0x01c2ac00, answers=[0x34], bound=[0x50])
    rc, out, err = run(tools, root)
    assert decision(out)["selected"] == "ga36-panel2"
    assert "probe i2c 0x1c2ac00 address 0x34: present match" in err
    assert "probe i2c 0x1c2ac00 address 0x50: present (bound to a driver) match" in err


def test_i2c_absent(tools, root):
    root.ga36_panels(panel2_rules={"lume,i2c-present": [(0x01c2ac00, 0x34)]})
    root.i2c(0x01c2ac00, answers=[0x20])
    rc, out, err = run(tools, root)
    assert decision(out)["reason"] == "default"
    assert "address 0x34: absent no match" in err


def test_highest_priority_wins(tools, root):
    rule = {"lume,adc": [(0x01c22800, 1, 0, 1000)]}
    root.dtb("a.dtb", _cand("ga36-panel1", default=True))
    root.dtb("b.dtb", _cand("low", priority=5, rules=rule))
    root.dtb("c.dtb", _cand("high", priority=10, rules=rule))
    root.dtb("d.dtb", _cand("mid", priority=7, rules=rule))
    root.iio(0x01c22800, "lradc", {1: 500})
    rc, out, err = run(tools, root)
    assert decision(out)["selected"] == "high"


def test_device_tree_of_another_soc_is_ignored(tools, root):
    root.ga36_panels()
    root.dtb("rk3326-r36s-v5.dtb", _cand("r36s-v5", compat=R36S_COMPAT, default=True))
    root.force("r36s-v5")
    rc, out, err = run(tools, root)
    assert "ignored rk3326-r36s-v5.dtb: not compatible with allwinner,sun8i-a33" in err
    assert "force ignored: 'r36s-v5'" in err
    assert decision(out)["selected"] == "ga36-panel1"


def test_new_device_tree_copied_on_the_pc_is_a_candidate(tools, root):
    root.ga36_panels()
    root.dtb("my-clone.dtb", _cand("my-clone"))
    rc, out, err = run(tools, root)
    assert "candidate my-clone (my-clone.dtb) priority 0, no rules" in err


def test_files_without_the_node_or_repeated_ids_are_ignored(tools, root):
    root.ga36_panels()
    root.dtb("bare.dtb", fdt.build(fdt.Node(props={"compatible": fdt.s(*GA36_COMPAT)})))
    root.dtb("zz.dtb", _cand("ga36-panel2"))
    root.dtb("junk.dtb", b"not a dtb")
    rc, out, err = run(tools, root)
    assert "ignored bare.dtb: no lume-select node with lume,id" in err
    assert "ignored zz.dtb: lume,id ga36-panel2 repeated" in err
    assert "ignored junk.dtb: not a valid device tree" in err


# --- 4.3: precedence and state (D6) -------------------------------------------------------

def test_force_from_the_pc(tools, root):
    root.ga36_panels()
    root.force("ga36-panel2\r\n")                          # written on Windows
    rc, out, err = run(tools, root)
    assert decision(out) == {"selected": "ga36-panel2", "reason": "forced", "kexec": "yes",
                             "dtb": str(root.path / "tmp/lume-bootsel.dtb")}
    assert root.state()["pending"] == "ga36-panel2"        # confirmed on the screen, too


def test_force_accepts_the_file_name(tools, root):
    root.ga36_panels()
    root.force("sun8i-a33-ga36-mb-v1.2-panel2.dtb")
    assert decision(run(tools, root)[1])["selected"] == "ga36-panel2"


def test_invalid_force_is_ignored_and_the_saved_choice_follows(tools, root):
    root.ga36_panels()
    root.force("ga36-panel9")
    root.state(manual="ga36-panel2", good="ga36-panel1")
    rc, out, err = run(tools, root)
    assert "force ignored: 'ga36-panel9' in BOOT/dtbs/force is not a device tree of dtbs/a33" in err
    assert decision(out)["selected"] == "ga36-panel2" and decision(out)["reason"] == "manual"


def test_force_wins_over_rules_and_saved_choice(tools, root):
    root.ga36_panels(panel2_rules={"lume,adc": [(0x01c22800, 1, 0, 9999)]})
    root.iio(0x01c22800, "lradc", {1: 1})
    root.dtb("x.dtb", _cand("other"))
    root.force("other")
    root.state(manual="ga36-panel2")
    assert decision(run(tools, root)[1])["selected"] == "other"


def test_saved_choice_wins_over_rules(tools, root):
    root.ga36_panels(panel2_rules={"lume,adc": [(0x01c22800, 1, 0, 9999)]})
    root.iio(0x01c22800, "lradc", {1: 1})
    root.dtb("x.dtb", _cand("other"))
    root.state(manual="other")
    out = decision(run(tools, root)[1])
    assert out["selected"] == "other" and out["reason"] == "manual"


def test_back_to_the_last_one_that_worked(tools, root):
    root.ga36_panels()
    root.dtb("x.dtb", _cand("other"))
    root.state(manual="ga36-panel2", good="other", pending="ga36-panel2")
    rc, out, err = run(tools, root)
    assert "fallback: ga36-panel2 was not confirmed in the previous boot; discarded" in err
    assert decision(out)["selected"] == "other" and decision(out)["reason"] == "fallback"
    st = root.state()
    assert st["bad"] == "ga36-panel2" and st["manual"] == "" and st["pending"] == ""


def test_fallback_without_a_good_one_is_the_default(tools, root):
    root.ga36_panels()
    root.state(pending="ga36-panel2")
    out = decision(run(tools, root)[1])
    assert out == {"selected": "ga36-panel1", "reason": "fallback", "kexec": "no"}


def test_discarded_one_is_skipped_by_the_rules(tools, root):
    root.ga36_panels(panel2_rules={"lume,adc": [(0x01c22800, 1, 0, 9999)]})
    root.iio(0x01c22800, "lradc", {1: 1})
    root.state(bad="ga36-panel2")
    rc, out, err = run(tools, root)
    assert "rules of ga36-panel2 skipped: discarded before (bad)" in err
    assert decision(out)["reason"] == "default"


def test_forced_one_that_hung_is_discarded_and_the_force_ignored(tools, root):
    root.ga36_panels()
    root.force("ga36-panel2")
    run(tools, root)
    assert root.state()["pending"] == "ga36-panel2"
    rc, out, err = run(tools, root)          # the next boot comes from the bootloader again
    assert decision(out) == {"selected": "ga36-panel1", "reason": "fallback", "kexec": "no"}
    assert ("force ignored: ga36-panel2 was discarded on this device (bad); delete "
            "BOOT/dtbs/force or choose it in the list") in err
    assert root.state()["bad"] == "ga36-panel2"


def test_force_of_a_discarded_one_is_ignored(tools, root):
    root.ga36_panels()
    root.dtb("x.dtb", _cand("other"))
    root.force("ga36-panel2")
    root.state(bad="ga36-panel2", manual="other", good="other")
    rc, out, err = run(tools, root)
    assert "force ignored: ga36-panel2 was discarded on this device (bad)" in err
    assert decision(out)["selected"] == "other" and decision(out)["reason"] == "manual"


def test_list_clears_the_discard_of_the_forced_one(tools, root):
    root.ga36_panels()
    root.force("ga36-panel2")
    root.state(bad="ga36-panel2")
    # starts on "Automatic": up goes to panel2
    root.keys(held=[KEY_VOLUMEDOWN], events=[KEY_VOLUMEUP, BTN_EAST])
    rc, out, err = run(tools, root)
    assert decision(out)["selected"] == "ga36-panel2"
    assert root.state()["bad"] == "" and root.state()["pending"] == "ga36-panel2"


def test_without_roms_the_choice_still_works(tools, root):
    root.ga36_panels()
    root.force("ga36-panel2")
    rc, out, err = run(tools, root, roms=False)
    assert "no ROMS: the choice is not saved" in err
    assert decision(out)["selected"] == "ga36-panel2"
    assert not (root.path / "roms/system").exists()


def test_choice_is_separate_per_soc(tools, tmp_path):
    r36s = Root(tmp_path / "r", soc="rk3326", compat=R36S_COMPAT, running="r36s-v5",
                kernel="r36s/Image")
    r36s.dtb("rk3326-r36s-v5.dtb", _cand("r36s-v5", compat=R36S_COMPAT, default=True))
    r36s.state(soc="a33", manual="ga36-panel2", pending="ga36-panel2")  # from the GA36
    rc, out, err = run(tools, r36s)
    assert decision(out) == {"selected": "r36s-v5", "reason": "default", "kexec": "no"}
    assert r36s.state(soc="a33")["pending"] == "ga36-panel2"          # untouched
    assert r36s.state()["manual"] == ""


def test_running_tree_without_the_node_counts_as_the_default(tools, tmp_path):
    root = Root(tmp_path / "r", running=None)
    root.ga36_panels()
    out = decision(run(tools, root)[1])
    assert out["selected"] == "ga36-panel1" and out["kexec"] == "no"


# --- 4.4: prepared tree and kexec (D2) ----------------------------------------------------

def test_prepared_tree_has_the_running_memory_and_the_marker(tools, root):
    root.ga36_panels()
    root.force("ga36-panel2")
    run(tools, root)
    dtb = fdt.parse((root.path / "tmp/lume-bootsel.dtb").read_bytes())
    assert dtb.path("/lume-select").string("lume,id") == "ga36-panel2"
    assert dtb.path("/memory@40000000").cells("reg") == [0x40000000, 0x20000000]
    assert "name" not in dtb.path("/memory@40000000").props
    chosen = dtb.path("/chosen")
    assert chosen.strings("lume,dtb-selected") == ["ga36-panel2", "forced"]
    assert chosen.string("stdout-path") == "serial0"           # the rest is kept
    assert "force: BOOT/dtbs/force selects ga36-panel2" in chosen.string("lume,dtb-log")


def test_prepared_tree_read_with_fdtget(tools, root):
    if tools["fdtget"] is None:
        pytest.skip("fdtget did not build")
    root.ga36_panels()
    root.force("ga36-panel2")
    run(tools, root)
    out = root.path / "tmp/lume-bootsel.dtb"

    def get(*args):
        return subprocess.run([str(tools["fdtget"]), *args], capture_output=True, text=True,
                              check=True).stdout.strip()

    assert get("-t", "x", str(out), "/memory@40000000", "reg") == "40000000 20000000"
    assert get(str(out), "/chosen", "lume,dtb-selected") == "ga36-panel2 forced"


def test_second_start_does_not_choose_again(tools, root):
    root.ga36_panels()
    root.force("ga36-panel1")                 # even if the choice would differ now
    chosen = root.path / "proc/device-tree/chosen"
    (chosen / "lume,dtb-selected").write_bytes(fdt.s("ga36-panel2", "forced"))
    (chosen / "lume,dtb-log").write_bytes(fdt.s("force: BOOT/dtbs/force selects ga36-panel2\n"
                                                "selected ga36-panel2 (reason: forced)\n"))
    rc, out, err = run(tools, root)
    assert rc == 0 and out == ""
    assert "lume-bootsel: before kexec: selected ga36-panel2 (reason: forced)" in err
    assert "device tree from kexec: ga36-panel2 (reason: forced)" in err
    assert "candidate" not in err and root.state() == {}


def _fake_kexec(tmp_path, status):
    script = tmp_path / "kexec"
    script.write_text(f'#!/bin/sh\necho "$@" > "{tmp_path}/kexec.args"\nexit {status}\n')
    script.chmod(0o755)
    return script


def test_kexec_loads_the_same_kernel_with_the_chosen_tree(tools, root, tmp_path):
    root.ga36_panels()
    root.state(manual="ga36-panel2")
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    assert rc == 10
    # -c: kexec_load, the syscall that takes the tree given in --dtb (kexec_file_load ignores
    # it on arm64 and reuses the running tree: R36S, 2026-11-15)
    assert (tmp_path / "kexec.args").read_text().split() == [
        "-c", "-l", str(root.path / "boot/ga36/zImage"),
        f"--dtb={root.path / 'tmp/lume-bootsel.dtb'}"]
    assert "switching to ga36-panel2 by kexec (/boot/ga36/zImage)" in err
    assert root.state()["pending"] == "ga36-panel2"


def test_failed_kexec_keeps_booting_without_pending(tools, root, tmp_path):
    root.ga36_panels()
    root.state(manual="ga36-panel2")
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 1)), dry=False)
    assert rc == 0
    assert "ERROR: kexec -l failed (status 1); keeping the running device tree" in err
    assert root.state()["pending"] == ""


def test_kexec_output_goes_to_the_log(tools, root, tmp_path):
    # the errors of kexec only reached the console (GA36 boot 20): now they are logged,
    # and a failure is retried with -d plus the RAM layout of /proc/iomem
    script = tmp_path / "kexec"
    script.write_text('#!/bin/sh\necho "$@" >> "' + str(tmp_path) + '/kexec.calls"\n'
                      'echo "Could not find a free area of memory of 0x715248 bytes..." >&2\n'
                      'echo "Cannot load /boot/ga36/zImage" >&2\nexit 255\n')
    script.chmod(0o755)
    (root.path / "proc/iomem").write_text("40000000-5fffffff : System RAM\n"
                                          "  40008000-40efffff : Kernel code\n"
                                          "01c00000-01c00fff : 1c00000.syscon\n")
    root.ga36_panels()
    root.force("ga36-panel2")
    rc, out, err = run(tools, root, "--kexec", str(script), dry=False)
    assert rc == 0
    assert "lume-bootsel: kexec: Could not find a free area of memory of 0x715248 bytes..." in err
    assert "lume-bootsel: kexec -l failed (status 255); details follow" in err
    assert "lume-bootsel: iomem: 40000000-5fffffff : System RAM" in err
    assert "syscon" not in err
    calls = (tmp_path / "kexec.calls").read_text().splitlines()
    assert calls[0].startswith("-c -l ") and calls[1].startswith("-c -d -l ")
    assert "ERROR: kexec -l failed (status 255); keeping the running device tree" in err


def test_missing_kernel_keeps_the_running_tree(tools, root):
    root.ga36_panels()
    root.force("ga36-panel2")
    (root.path / "boot/ga36/zImage").unlink()
    rc, out, err = run(tools, root, dry=False)
    assert rc == 0 and "ERROR: kernel ga36/zImage not found on BOOT" in err


# --- 4.5: the list (D7) -------------------------------------------------------------------

def test_list_choice_is_used_and_saved(tools, root):
    root.ga36_panels()
    # starts on "Automatic" (last row): down wraps to panel1, down again to panel2
    root.keys(held=[KEY_VOLUMEDOWN], events=[KEY_VOLUMEDOWN, KEY_VOLUMEDOWN, BTN_EAST])
    root.state(good="ga36-panel1", bad="ga36-panel2")
    rc, out, err = run(tools, root)
    assert decision(out)["selected"] == "ga36-panel2"
    assert decision(out)["reason"] == "manual"
    assert "list: ga36-panel2 chosen and saved" in err
    st = root.state()
    assert st["manual"] == "ga36-panel2" and st["bad"] == ""    # the list clears bad
    tty = root.tty()
    assert "ga36-panel1 (auto) (ok)" in tty and "Automatic" in tty
    assert "Selected: ga36-panel2" in tty


def test_list_automatic_clears_the_saved_choice(tools, root):
    root.ga36_panels()
    root.state(manual="ga36-panel2")
    # starts on the saved one (panel2): down goes to Automatic
    root.keys(held=[KEY_VOLUMEDOWN], events=[KEY_VOLUMEDOWN, BTN_EAST])
    rc, out, err = run(tools, root)
    assert "list: automatic chosen, saved choice cleared" in err
    assert decision(out)["reason"] == "default" and root.state()["manual"] == ""


def test_list_says_when_the_pc_forces_the_choice(tools, root):
    root.ga36_panels()
    root.force("ga36-panel2")
    root.keys(held=[KEY_VOLUMEDOWN], events=[KEY_VOLUMEUP, KEY_VOLUMEUP, BTN_EAST])
    rc, out, err = run(tools, root)
    assert decision(out)["selected"] == "ga36-panel2" and decision(out)["reason"] == "forced"
    assert "BOOT/dtbs/force selects ga36-panel2" in root.tty()
    assert "ga36-panel2 (forced)" in root.tty()
    assert root.state()["manual"] == "ga36-panel1"          # saved for later


def test_list_closed_without_a_choice(tools, root):
    root.ga36_panels()
    root.keys(held=[KEY_VOLUMEDOWN], events=[KEY_VOLUMEUP])
    rc, out, err = run(tools, root)
    assert "list closed without a choice" in err
    assert decision(out)["reason"] == "default"


# --- 7.3, 7.9: converted device trees in vendor/, read only when named ---------------------

def test_converted_trees_are_not_read_in_a_normal_boot(tools, root):
    root.ga36_panels()
    root.vendor("clone-a", "clone-b")
    rc, out, err = run(tools, root)
    assert decision(out)["selected"] == "ga36-panel1"
    assert "clone-" not in err and "vendor" not in err


def test_force_loads_a_converted_tree(tools, root):
    root.ga36_panels()
    root.vendor("clone-a", "clone-b")
    root.force("clone-b")
    rc, out, err = run(tools, root)
    assert decision(out)["selected"] == "clone-b" and decision(out)["reason"] == "forced"
    assert "vendor device tree clone-b loaded on demand" in err
    assert "candidate clone-b (vendor/clone-b.dtb)" in err
    assert "clone-a" not in err


def test_saved_choice_of_a_converted_tree_is_loaded(tools, root):
    root.ga36_panels()
    root.vendor("clone-a")
    root.state(manual="clone-a", good="ga36-panel1")
    rc, out, err = run(tools, root)
    assert decision(out)["selected"] == "clone-a" and decision(out)["reason"] == "manual"


def test_force_cannot_leave_the_vendor_folder(tools, root):
    root.ga36_panels()
    root.vendor("clone-a")
    root.force("../a33/sun8i-a33-ga36-mb-v1.2-panel2")
    rc, out, err = run(tools, root)
    assert "force ignored" in err and decision(out)["reason"] == "default"


def test_list_shows_and_loads_a_converted_tree(tools, root):
    root.ga36_panels()
    root.vendor("clone-a", "clone-b")
    # rows: panel1, panel2, clone-a, clone-b, Automatic (start); up goes to clone-b
    root.keys(held=[KEY_VOLUMEDOWN], events=[KEY_VOLUMEUP, BTN_EAST])
    rc, out, err = run(tools, root)
    assert "list shown (2 candidate(s), 2 converted)" in err
    assert "clone-a (converted)" in root.tty() and "Selected: clone-b" in root.tty()
    assert decision(out)["selected"] == "clone-b" and decision(out)["reason"] == "manual"
    assert root.state()["manual"] == "clone-b"


def test_long_list_scrolls_and_jumps_a_page(tools, root):
    root.ga36_panels()
    root.vendor(*[f"clone-{i:02d}" for i in range(40)])
    BTN_TR = 0x137
    # Automatic (row 41): down wraps to row 0, page down jumps 18 rows: clone-16
    root.keys(held=[KEY_VOLUMEDOWN], events=[KEY_VOLUMEDOWN, BTN_TR, BTN_EAST],
              text=KEYS + "pagedown=BTN_TR\n")
    rc, out, err = run(tools, root)
    tty = root.tty()
    assert "more below" in tty and "more above" in tty
    assert "Page keys: jump" in tty
    assert decision(out)["selected"] == "clone-16"


def test_no_list_without_the_key_held(tools, root):
    root.ga36_panels()
    root.keys(held=[KEY_VOLUMEUP], events=[BTN_EAST])
    rc, out, err = run(tools, root)
    assert "list shown" not in err and root.tty() == ""


def test_no_list_without_the_keys_file(tools, root):
    root.ga36_panels()
    rc, out, err = run(tools, root)
    assert "no complete /etc/bootsel-keys: the list is off" in err


def test_no_input_device_waits_at_most_one_second(tools, root):
    import time

    root.ga36_panels()
    (root.path / "etc/bootsel-keys").write_text(KEYS)
    t = time.monotonic()
    rc, out, err = run(tools, root)
    assert time.monotonic() - t < 2
    assert "no input device with the selection key within 1000 ms" in err


def test_keys_file_accepts_names_and_codes(tools, root):
    root.ga36_panels()
    root.keys(held=[KEY_VOLUMEDOWN], events=[0x220, BTN_EAST],
              text="select=114\nup=0x220, KEY_VOLUMEUP\ndown=KEY_VOLUMEDOWN\nok=BTN_EAST # A\n")
    rc, out, err = run(tools, root)
    # up from Automatic: panel2
    assert decision(out)["selected"] == "ga36-panel2"


# --- 4.6: the log ---------------------------------------------------------------------------

def test_log_lines(tools, root):
    root.ga36_panels(panel2_rules={"lume,adc": [(0x01c22800, 1, 800, 950)]})
    root.iio(0x01c22800, "lradc", {1: 10})
    rc, out, err = run(tools, root)
    lines = err.splitlines()
    assert all(line.startswith("lume-bootsel: ") for line in lines)
    assert "lume-bootsel: soc a33 (allwinner,sun8i-a33), running device tree ga36-panel1" in lines
    assert "lume-bootsel: rules of ga36-panel2: no match" in lines
    assert "lume-bootsel: selected ga36-panel1 (reason: default)" in lines
    assert all(line.isascii() for line in lines)               # English, plain text


# --- 4.7: state per device (D6) ------------------------------------------------------------

def test_choice_is_separate_per_device(tools, root):
    root.ga36_panels()
    root.serial("02c00042a1b2c3d4\n")
    root.state(device="02c00042a1b2c3d4", manual="ga36-panel2", good="ga36-panel2")
    rc, out, err = run(tools, root)
    assert "device: SoC serial number 02c00042a1b2c3d4, choice in dtb-a33-02c00042a1b2c3d4.conf" in err
    assert decision(out)["selected"] == "ga36-panel2" and decision(out)["reason"] == "manual"

    root.serial("02c00042ffff0000\n")                       # the card in another GA36
    out = decision(run(tools, root)[1])
    assert out == {"selected": "ga36-panel1", "reason": "default", "kexec": "no"}
    assert root.state(device="02c00042ffff0000") == {"manual": "", "good": "", "pending": "",
                                                    "bad": ""}
    assert root.state(device="02c00042a1b2c3d4")["manual"] == "ga36-panel2"   # untouched

    root.serial("02c00042a1b2c3d4\n")                       # back in the first one
    assert decision(run(tools, root)[1])["selected"] == "ga36-panel2"


@pytest.mark.parametrize("value", [None, "", "0000000000000000\n"])
def test_without_serial_the_choice_is_per_soc_with_a_warning(tools, root, value):
    root.ga36_panels()
    if value is not None:
        root.serial(value)
    root.state(manual="ga36-panel2")
    rc, out, err = run(tools, root)
    assert "no serial number: the choice in dtb-a33.conf applies to every a33 device" in err
    assert decision(out)["selected"] == "ga36-panel2"


def test_bootloader_serial_names_the_state_without_soc0(tools, root):
    """R36S (proof 1.7): no soc0, but the factory U-Boot writes /serial-number."""
    root.ga36_panels()
    root.dt_serial("c3d9b8674f4b94f6")
    root.state(device="c3d9b8674f4b94f6", manual="ga36-panel2", good="ga36-panel2")
    rc, out, err = run(tools, root)
    assert ("device: bootloader serial number c3d9b8674f4b94f6, "
            "choice in dtb-a33-c3d9b8674f4b94f6.conf") in err
    assert decision(out)["reason"] == "manual"


def test_soc_serial_wins_over_the_bootloader_one(tools, root):
    root.ga36_panels()
    root.serial("aaaa\n")
    root.dt_serial("bbbb")
    rc, out, err = run(tools, root)
    assert "device: SoC serial number aaaa, choice in dtb-a33-aaaa.conf" in err


def test_prepared_tree_carries_the_bootloader_serial(tools, root):
    """After the kexec the second kernel names the same state file."""
    root.ga36_panels()
    root.dt_serial("c3d9b8674f4b94f6")
    root.force("ga36-panel2")
    run(tools, root)
    dtb = fdt.parse((root.path / "tmp/lume-bootsel.dtb").read_bytes())
    assert dtb.string("serial-number") == "c3d9b8674f4b94f6"


def test_prepared_tree_without_a_bootloader_serial_has_none(tools, root):
    root.ga36_panels()
    root.force("ga36-panel2")
    run(tools, root)
    dtb = fdt.parse((root.path / "tmp/lume-bootsel.dtb").read_bytes())
    assert "serial-number" not in dtb.props


def test_serial_keeps_only_letters_and_digits(tools, root):
    root.ga36_panels()
    root.serial("12:ab/../CD\n")
    run(tools, root)
    assert (root.path / "roms/system/etc/dtb-a33-12abCD.conf").exists()


def test_bad_on_one_device_does_not_block_the_force_on_another(tools, root):
    root.ga36_panels()
    root.force("ga36-panel2")
    root.serial("aaaa")
    root.state(device="aaaa", bad="ga36-panel2")
    assert decision(run(tools, root)[1])["reason"] == "default"
    root.serial("bbbb")
    assert decision(run(tools, root)[1])["reason"] == "forced"


# --- 4.8: confirmation on the screen (D10) -------------------------------------------------

def test_new_device_tree_confirmed_on_the_screen(tools, root):
    root.ga36_panels()
    root.state(pending="ga36-panel2", manual="ga36-panel2")
    root.keys(events=[BTN_EAST])
    root.after_kexec("ga36-panel2", "manual")
    rc, out, err = run(tools, root)
    assert rc == 0 and out == ""
    assert "question shown: keep ga36-panel2? (15 s)" in err
    assert "confirmed on screen: ga36-panel2 kept" in err
    tty = root.tty()
    assert "Lume Retro OS - new device tree: ga36-panel2" in tty
    assert "If you can read this, press A to keep it." in tty
    assert "Going back to ga36-panel1 in 15 s..." in tty
    assert "Kept: ga36-panel2" in tty
    assert root.state() == {"manual": "ga36-panel2", "good": "ga36-panel2", "pending": "",
                            "bad": ""}
    # the boots after it with the same device tree do not ask any more
    (root.path / "dev/tty1").write_text("")
    rc, out, err = run(tools, root)
    assert "question shown" not in err and root.tty() == ""


def test_no_answer_goes_back_to_the_default(tools, root, tmp_path):
    root.ga36_panels()
    root.force("ga36-panel2")
    root.state(pending="ga36-panel2")
    root.keys(events=[KEY_VOLUMEUP])                         # not the confirm key
    root.after_kexec("ga36-panel2", "forced")
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    assert rc == 10
    assert ("not confirmed within 15 s: ga36-panel2 discarded on this device, going back "
            "to ga36-panel1") in err
    assert "selected ga36-panel1 (reason: reverted)" in err
    assert "No answer: going back to ga36-panel1." in root.tty()
    assert root.state() == {"manual": "", "good": "", "pending": "", "bad": "ga36-panel2"}
    dtb = root.prepared()
    assert dtb.path("/lume-select").string("lume,id") == "ga36-panel1"
    assert dtb.path("/chosen").strings("lume,dtb-selected") == ["ga36-panel1", "reverted"]
    assert (tmp_path / "kexec.args").read_text().split()[2] == str(root.path / "boot/ga36/zImage")


def test_no_answer_goes_back_to_the_last_confirmed_one(tools, root, tmp_path):
    root.ga36_panels()
    root.dtb("x.dtb", _cand("other"))
    root.state(pending="ga36-panel2", manual="ga36-panel2", good="other")
    root.keys(events=[])
    root.after_kexec("ga36-panel2", "manual")
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    assert rc == 10 and "going back to other" in err
    assert root.state() == {"manual": "", "good": "other", "pending": "", "bad": "ga36-panel2"}
    assert root.prepared().path("/lume-select").string("lume,id") == "other"


def test_reverted_tree_read_with_fdtget(tools, root, tmp_path):
    if tools["fdtget"] is None:
        pytest.skip("fdtget did not build")
    root.ga36_panels()
    root.state(pending="ga36-panel2")
    root.keys(events=[])
    root.after_kexec("ga36-panel2", "rule")
    run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    r = subprocess.run([str(tools["fdtget"]), str(root.path / "tmp/lume-bootsel.dtb"),
                        "/chosen", "lume,dtb-selected"], capture_output=True, text=True)
    assert r.stdout.strip() == "ga36-panel1 reverted"


def test_third_start_after_the_revert_goes_on(tools, root):
    root.ga36_panels()
    root.state(bad="ga36-panel2")
    root.keys(events=[BTN_EAST])
    root.after_kexec("ga36-panel1", "reverted")
    rc, out, err = run(tools, root)
    assert rc == 0 and out == ""
    assert "back from a device tree that was not confirmed: no question, no switch" in err
    assert root.tty() == "" and root.state()["bad"] == "ga36-panel2"


@pytest.mark.parametrize("keys_file, devices", [(False, False), (True, False)])
def test_without_a_confirm_key_there_is_no_question(tools, root, keys_file, devices):
    root.ga36_panels()
    root.state(pending="ga36-panel2")
    if keys_file:
        (root.path / "etc/bootsel-keys").write_text(KEYS)
    root.after_kexec("ga36-panel2", "rule")
    rc, out, err = run(tools, root)
    assert rc == 0
    assert ("no question on the screen (no confirm key or tty1): ga36-panel2 stays pending "
            "until the frontend starts") in err
    assert root.state()["pending"] == "ga36-panel2"          # for lume-logd


def test_the_package_builds_with_the_question():
    # D10: the question on the screen is on in the package (it was off during the
    # usb-device-access device tests, until 2026-11-15)
    source = SOURCE.read_text()
    assert re.search(r"#ifndef LUME_CONFIRM\n#define LUME_CONFIRM 1\n#endif", source)
    assert "LUME_CONFIRM" not in APKBUILD


# --- 8: signature by the panel ID and learning (D15) ------------------------------------------

def test_panel_id_rule_picks_its_device_tree(tools, root):
    root.ga36_panels(panel2_id="aabbcc", panel2_priority=10)
    root.panel("aabbcc")
    rc, out, err = run(tools, root)
    assert "signature: panel id aabbcc (1c40000.dsi.0)" in err
    assert "probe panel id aabbcc: aabbcc match" in err
    assert decision(out) == {"selected": "ga36-panel2", "reason": "rule", "kexec": "yes",
                             "dtb": str(root.path / "tmp/lume-bootsel.dtb")}


def test_panel_id_rule_of_the_running_tree_needs_no_switch(tools, root):
    # the R36S V5 since task 8.4: the default tree carries the ID its panel answers
    root.dtb("sun8i-a33-ga36-mb-v1.2-panel1.dtb",
             _cand("ga36-panel1", default=True, panel_id="fe5202"))
    root.dtb("sun8i-a33-ga36-mb-v1.2-panel2.dtb", _cand("ga36-panel2"))
    root.panel("fe5202")
    rc, out, err = run(tools, root)
    assert "probe panel id fe5202: fe5202 match" in err
    assert decision(out) == {"selected": "ga36-panel1", "reason": "rule", "kexec": "no"}


@pytest.mark.parametrize("silent_first", [True, False])
def test_panel_id_with_two_dsi_devices(tools, root, silent_first):
    # one DSI host without an answering panel does not hide the one that answered
    root.ga36_panels(panel2_id="aabbcc", panel2_priority=10)
    root.panel("" if silent_first else "aabbcc", dev="1c40000.dsi.0")
    root.panel("aabbcc" if silent_first else "", dev="1c50000.dsi.0")
    rc, out, err = run(tools, root)
    assert "signature: panel id aabbcc" in err
    assert "the panel did not answer its driver" not in err
    assert decision(out)["selected"] == "ga36-panel2" and decision(out)["reason"] == "rule"


def test_panel_id_rule_without_an_answer_does_not_match(tools, root):
    root.ga36_panels(panel2_id="aabbcc", panel2_priority=10)
    root.panel("unsupported")
    rc, out, err = run(tools, root)
    assert "probe panel id aabbcc: unknown no match" in err
    assert decision(out)["reason"] == "default"


def test_answering_panel_keeps_and_learns_the_running_tree(tools, root):
    # another panel answers: the rule of panel 2 does not match, the running tree serves
    root.ga36_panels(panel2_id="aabbcc", panel2_priority=10)
    root.panel("112233")
    rc, out, err = run(tools, root)
    assert "probe panel id aabbcc: 112233 no match" in err
    assert decision(out)["reason"] == "auto" and decision(out)["kexec"] == "no"
    assert "learned: ga36-panel1 for panel:112233" in err
    assert root.learned() == {"112233": "ga36-panel1"}
    # the next boot uses what was learned
    rc, out, err = run(tools, root)
    assert decision(out) == {"selected": "ga36-panel1", "reason": "learned", "kexec": "no"}


def test_learned_device_tree_is_chosen_for_the_same_signature_only(tools, root):
    root.ga36_panels()
    root.learned(aabbcc="ga36-panel2")
    root.panel("aabbcc")
    out = run(tools, root)[1]
    assert decision(out)["selected"] == "ga36-panel2" and decision(out)["reason"] == "learned"
    root.state(manual="", good="", pending="", bad="")   # the dry run left panel 2 pending
    root.panel("112233")
    out = run(tools, root)[1]
    assert decision(out)["reason"] == "auto"


def test_silent_panel_starts_the_search(tools, root, tmp_path):
    root.ga36_panels()
    root.panel("")
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    assert rc == 10
    assert "no signature: the panel did not answer its driver" in err
    assert "selected ga36-panel2 (reason: search)" in err
    # the running tree did not make the panel answer: it does not serve this device
    assert root.state()["pending"] == "ga36-panel2" and root.state()["bad"] == "ga36-panel1"
    assert root.prepared().path("/chosen").strings("lume,dtb-selected") == ["ga36-panel2",
                                                                           "search"]


def test_panel_without_a_driver_bound_starts_the_search(tools, root):
    # the GA36 jd9366 refuses its probe when the panel does not answer: no panel_id at all
    root.ga36_panels()
    root.panel(None)
    rc, out, err = run(tools, root)
    assert "panel 1c40000.dsi.0: no driver bound, the panel did not answer its probe" in err
    assert decision(out)["reason"] == "search" and decision(out)["selected"] == "ga36-panel2"


def test_blank_panel_id_is_no_signature(tools, root):
    # the JD9366 of the GA36 answers 000000 (ID never programmed): the panel works, but the
    # ID says nothing, so nothing is learned for it and nothing is searched
    root.ga36_panels()
    root.panel("000000")
    rc, out, err = run(tools, root)
    assert "panel id 000000 (1c40000.dsi.0): the panel answered, but the ID is blank" in err
    assert decision(out)["reason"] == "default"
    assert root.learned() == {} and root.state()["bad"] == ""


def test_search_accepts_a_panel_with_a_blank_id(tools, root):
    root.ga36_panels()
    root.state(pending="ga36-panel2", bad="ga36-panel1")
    root.after_kexec("ga36-panel2", "search")
    root.panel("ffffff")
    rc, out, err = run(tools, root)
    assert rc == 0 and "search: ga36-panel2 works, the panel answered" in err
    assert root.state()["good"] == "ga36-panel2" and root.learned() == {}


def test_unsupported_panel_id_read_means_no_search(tools, root):
    # the DSI host cannot read the ID (GA36, a 3-byte read, 2026-11-15): that says nothing
    # about the panel, so nothing is discarded or tried
    root.ga36_panels()
    root.panel("unsupported")
    rc, out, err = run(tools, root)
    assert "panel id of 1c40000.dsi.0: unsupported" in err
    assert "no signature: no panel driver shows panel_id" in err
    assert decision(out)["reason"] == "default" and root.state()["bad"] == ""


def test_no_panel_driver_means_no_search(tools, root):
    # no panel_id anywhere (a kernel without the read, the VM): nothing is tried blind
    root.ga36_panels()
    rc, out, err = run(tools, root)
    assert "no signature: no panel driver shows panel_id" in err
    assert decision(out)["reason"] == "default"


def test_search_learns_the_device_tree_whose_panel_answers(tools, root):
    root.ga36_panels()
    root.state(pending="ga36-panel2")
    root.after_kexec("ga36-panel2", "search")
    root.panel("aabbcc")
    rc, out, err = run(tools, root)
    assert rc == 0
    assert "search: ga36-panel2 works, the panel answered" in err
    assert root.state() == {"manual": "", "good": "ga36-panel2", "pending": "", "bad": ""}
    assert root.learned() == {"aabbcc": "ga36-panel2"}


def test_search_goes_on_when_the_panel_stays_silent(tools, root, tmp_path):
    root.ga36_panels()
    root.dtb("sun8i-a33-ga36-mb-v1.2-panel3.dtb", _cand("ga36-panel3"))
    root.state(pending="ga36-panel2", bad="ga36-panel1")      # as the first start left it
    root.after_kexec("ga36-panel2", "search")
    root.panel("")
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    assert rc == 10
    assert "search: ga36-panel2 does not work (the panel did not answer)" in err
    assert "selected ga36-panel3 (reason: search)" in err
    assert root.state()["bad"] == "ga36-panel1,ga36-panel2"
    assert root.state()["pending"] == "ga36-panel3"
    assert root.learned() == {}


def test_search_without_more_device_trees_goes_back(tools, root, tmp_path):
    root.ga36_panels()
    root.state(pending="ga36-panel2", bad="ga36-panel1")      # as the first start left it
    root.after_kexec("ga36-panel2", "search")
    root.panel("")
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    assert rc == 10
    assert "search: no device tree left; selected ga36-panel1 (reason: reverted)" in err
    assert root.prepared().path("/lume-select").string("lume,id") == "ga36-panel1"
    # and the search does not start again on the next boots: everything else is bad
    root.after_kexec("ga36-panel1", "reverted")
    assert "no switch" in run(tools, root)[2]


def test_discarded_device_tree_is_forgotten(tools, root):
    # learned, then not confirmed in the previous boot: it leaves the learned file
    root.ga36_panels()
    root.learned(aabbcc="ga36-panel2")
    root.state(pending="ga36-panel2")
    root.panel("aabbcc")
    rc, out, err = run(tools, root)
    assert "forgotten: nothing learned for panel:aabbcc any more" in err
    assert root.learned() == {}
    assert decision(out)["reason"] == "fallback"


def test_choice_confirmed_on_the_screen_is_learned(tools, root):
    root.ga36_panels()
    root.state(pending="ga36-panel2", manual="ga36-panel2")
    root.keys(events=[BTN_EAST])
    root.after_kexec("ga36-panel2", "manual")
    root.panel("aabbcc")
    rc, out, err = run(tools, root)
    assert "confirmed on screen: ga36-panel2 kept" in err
    assert root.learned() == {"aabbcc": "ga36-panel2"}


# --- 9: GA36, switch by rewriting the boot image and rebooting (D16) -------------------------

SECTOR = 8  # 172032 on the GA36; small here so the fake card stays small


def _android(root):
    """The GA36 switch: /etc/bootsel-switch and a fake card (sparse file)."""
    (root.path / "etc/bootsel-switch").write_text(f"android-boot {SECTOR}\n")
    disk = root.path / "disk.img"
    with open(disk, "wb") as f:
        f.truncate(16 << 20)
    return disk


def _image_on(disk, size):
    with open(disk, "rb") as f:
        f.seek(SECTOR * 512)
        return f.read(size)


def _expected_image(root, dtb_name):
    from r36os import bootimg
    zimage = (root.path / "boot/ga36/zImage").read_bytes()
    dtb = (root.path / f"boot/dtbs/a33/{dtb_name}").read_bytes()
    return bootimg.make(zimage + dtb)


def _running(root, ident):
    """The kernel runs with the tree of the boot image: no /chosen from a first start."""
    (root.path / "proc/device-tree/lume-select/lume,id").write_bytes(fdt.s(ident))


def test_switch_by_boot_image_writes_it_and_asks_for_a_reboot(tools, root):
    disk = _android(root)
    root.ga36_panels()
    root.force("ga36-panel2")
    rc, out, err = run(tools, root, "--disk", "/disk.img", dry=False)
    assert rc == 11
    want = _expected_image(root, "sun8i-a33-ga36-mb-v1.2-panel2.dtb")
    assert _image_on(disk, len(want)) == want            # byte for byte what bootimg.py makes
    assert "boot image with ga36-panel2 written at sector 8 of /disk.img" in err
    assert root.state()["pending"] == "ga36-panel2"
    assert root.state()["pending_reason"] == "forced"
    assert "kexec" not in err.replace("--kexec", "")


def test_log_of_the_start_that_reboots_reaches_the_next_one(tools, root):
    # the start that rewrites the boot image reboots from the initramfs, before any log is
    # written to the card: its lines wait on ROMS and the next start repeats them
    _android(root)
    root.ga36_panels()
    root.force("ga36-panel2")
    rc, out, err = run(tools, root, "--disk", "/disk.img", dry=False)
    assert rc == 11
    saved = root.path / "roms/system/etc/dtb-a33-before-reboot.log"
    text = saved.read_text()
    assert "force: BOOT/dtbs/force selects ga36-panel2" in text
    assert "rebooting into the boot image with ga36-panel2" in text
    _running(root, "ga36-panel2")
    root.keys(events=[BTN_EAST])
    rc, out, err = run(tools, root, "--disk", "/disk.img", dry=False)
    assert rc == 0
    assert "before reboot: force: BOOT/dtbs/force selects ga36-panel2" in err
    assert "before reboot: rebooting into the boot image with ga36-panel2" in err
    assert not saved.exists()


def test_switch_by_boot_image_dry_run(tools, root):
    _android(root)
    root.ga36_panels()
    root.force("ga36-panel2")
    rc, out, err = run(tools, root, "--disk", "/disk.img")
    assert rc == 0
    assert decision(out) == {"selected": "ga36-panel2", "reason": "forced", "reboot": "yes"}


def test_boot_image_needs_the_disk(tools, root):
    (root.path / "etc/bootsel-switch").write_text(f"android-boot {SECTOR}\n")
    root.ga36_panels()
    rc, out, err = run(tools, root)
    assert "switch by the boot image needs --disk" in err


def test_second_start_after_the_reboot_confirms_on_the_screen(tools, root):
    _android(root)
    root.ga36_panels()
    root.state(pending="ga36-panel2", pending_reason="forced")
    _running(root, "ga36-panel2")
    root.keys(events=[BTN_EAST])
    rc, out, err = run(tools, root, "--disk", "/disk.img", dry=False)
    assert rc == 0
    assert "device tree from the boot image: ga36-panel2 (reason: forced)" in err
    assert "confirmed on screen: ga36-panel2 kept" in err
    assert root.state() == {"manual": "", "good": "ga36-panel2", "pending": "", "bad": ""}


def test_second_start_after_the_reboot_goes_back_by_the_boot_image(tools, root):
    disk = _android(root)
    root.ga36_panels()
    root.state(pending="ga36-panel2", pending_reason="manual")
    _running(root, "ga36-panel2")
    root.keys(events=[KEY_VOLUMEUP])                            # not the confirm key
    rc, out, err = run(tools, root, "--disk", "/disk.img", dry=False)
    assert rc == 11
    assert "selected ga36-panel1 (reason: reverted)" in err
    want = _expected_image(root, "sun8i-a33-ga36-mb-v1.2-panel1.dtb")
    assert _image_on(disk, len(want)) == want
    assert root.state()["bad"] == "ga36-panel2" and root.state()["pending"] == ""


def test_search_by_boot_image(tools, root):
    disk = _android(root)
    root.ga36_panels()
    root.panel("")
    rc, out, err = run(tools, root, "--disk", "/disk.img", dry=False)
    assert rc == 11
    assert root.state()["pending"] == "ga36-panel2"
    assert root.state()["pending_reason"] == "search"
    want = _expected_image(root, "sun8i-a33-ga36-mb-v1.2-panel2.dtb")
    assert _image_on(disk, len(want)) == want
    # after the reboot the panel answers: found and learned, no more switch
    _running(root, "ga36-panel2")
    root.panel("aabbcc")
    rc, out, err = run(tools, root, "--disk", "/disk.img", dry=False)
    assert rc == 0
    assert "search: ga36-panel2 works, the panel answered" in err
    assert root.learned() == {"aabbcc": "ga36-panel2"}


def test_confirmed_or_default_trees_never_ask(tools, root):
    root.ga36_panels()
    root.state(manual="ga36-panel2", good="ga36-panel2")
    root.keys(events=[BTN_EAST])
    root.after_kexec("ga36-panel2", "manual")
    rc, out, err = run(tools, root)
    assert "question shown" not in err and root.tty() == ""


# --- 4.9: watchdog (D11) ------------------------------------------------------------------

def test_watchdog_armed_before_the_kexec_to_a_new_one(tools, root, tmp_path):
    root.ga36_panels()
    root.state(manual="ga36-panel2")
    wd = root.watchdog()
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    assert rc == 10
    assert wd.read_text() == "timeout 60\n"                 # closed without 'V'
    assert "watchdog armed: 60 s" in err
    assert "lume,watchdog" in root.prepared().path("/chosen").props


def test_watchdog_not_armed_for_a_confirmed_one(tools, root, tmp_path):
    root.ga36_panels()
    root.state(manual="ga36-panel2", good="ga36-panel2")
    wd = root.watchdog()
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    assert rc == 10 and wd.read_text() == ""
    assert "lume,watchdog" not in root.prepared().path("/chosen").props


def test_watchdog_not_armed_when_kexec_fails(tools, root, tmp_path):
    root.ga36_panels()
    root.state(manual="ga36-panel2")
    wd = root.watchdog()
    run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 1)), dry=False)
    assert wd.read_text() == ""


def test_dry_run_does_not_touch_the_watchdog(tools, root):
    root.ga36_panels()
    root.state(manual="ga36-panel2")
    wd = root.watchdog()
    run(tools, root)
    assert wd.read_text() == ""
    assert "lume,watchdog" not in root.prepared().path("/chosen").props


def test_without_a_watchdog_the_log_says_so(tools, root, tmp_path):
    root.ga36_panels()
    root.state(manual="ga36-panel2")
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    assert rc == 10
    assert "no /dev/watchdog: a hang with ga36-panel2 needs a power cycle to go back" in err


def test_watchdog_fed_during_the_question_and_stopped_on_confirm(tools, root):
    root.ga36_panels()
    root.state(pending="ga36-panel2")
    root.keys(events=[BTN_EAST])
    root.after_kexec("ga36-panel2", "rule", watchdog=True)
    wd = root.watchdog("timeout 60\n")
    rc, out, err = run(tools, root, dry=False)
    assert rc == 0
    assert re.fullmatch(r"timeout 60\n\.+V", wd.read_text())
    assert "watchdog stopped" in err


def test_watchdog_stopped_before_going_back_and_armed_again(tools, root, tmp_path):
    root.ga36_panels()
    root.state(pending="ga36-panel2")
    root.keys(events=[])
    root.after_kexec("ga36-panel2", "rule", watchdog=True)
    wd = root.watchdog("timeout 60\n")
    rc, out, err = run(tools, root, "--kexec", str(_fake_kexec(tmp_path, 0)), dry=False)
    assert rc == 10
    assert re.fullmatch(r"timeout 60\n\.+Vtimeout 60\n", wd.read_text())
    assert "lume,watchdog" in root.prepared().path("/chosen").props


@pytest.mark.parametrize("state, reason", [
    ({"bad": "ga36-panel2"}, "reverted"),                   # third start
    ({"good": "ga36-panel2"}, "manual"),                    # confirmed before
    ({"pending": "ga36-panel2"}, "rule"),                   # no question (no keys)
])
def test_watchdog_stopped_when_there_is_no_question(tools, root, state, reason):
    root.ga36_panels()
    root.state(**state)
    root.after_kexec("ga36-panel2" if reason != "reverted" else "ga36-panel1", reason,
                     watchdog=True)
    wd = root.watchdog("timeout 60\n")
    rc, out, err = run(tools, root, dry=False)
    assert rc == 0 and wd.read_text() == "timeout 60\nV"


def test_kexec_failed_clears_pending_and_stops_the_watchdog(tools, root):
    root.ga36_panels()
    root.state(pending="ga36-panel2", manual="ga36-panel2")
    wd = root.watchdog("timeout 60\n")
    rc, out, err = run(tools, root, "--kexec-failed", dry=False)
    assert rc == 0
    assert "kexec -e failed: ga36-panel2 is no longer pending" in err
    assert root.state() == {"manual": "ga36-panel2", "good": "", "pending": "", "bad": ""}
    assert wd.read_text() == "timeout 60\nV"
