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
cc -std=gnu11 -O2 -Wall -Wextra -Werror -I dtc-{DTC_VER}/libfdt -c -o bootsel.o /src/lume-bootsel.c
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

def _cand(ident, compat=GA36_COMPAT, priority=0, default=False, rules=None):
    node = {"lume,id": fdt.s(ident), "lume,priority": fdt.u32(priority)}
    if default:
        node["lume,default"] = b""
    for name, rows in (rules or {}).items():
        node[name] = fdt.u32(*[v for row in rows for v in row])
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
        (self.path / f"boot/dtbs/{soc or self.soc}/{name}").write_bytes(data)

    def ga36_panels(self, panel2_rules=None, panel2_priority=0):
        self.dtb("sun8i-a33-ga36-mb-v1.2-panel1.dtb", _cand("ga36-panel1", default=True))
        self.dtb("sun8i-a33-ga36-mb-v1.2-panel2.dtb",
                 _cand("ga36-panel2", priority=panel2_priority, rules=panel2_rules))

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

    def state(self, soc=None, **values):
        f = self.path / f"roms/system/etc/dtb-{soc or self.soc}.conf"
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
    assert root.state()["pending"] == ""                   # the forced one is never discarded


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
    assert ("fallback: ga36-panel2 did not reach the frontend in the previous boot; "
            "discarded") in err
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


def test_forced_one_is_never_discarded(tools, root):
    root.ga36_panels()
    root.force("ga36-panel2")
    run(tools, root)
    assert root.state()["pending"] == ""
    out = decision(run(tools, root)[1])                    # the next boot: still forced
    assert out["reason"] == "forced" and root.state()["bad"] == ""


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
    assert (tmp_path / "kexec.args").read_text().split() == [
        "-l", str(root.path / "boot/ga36/zImage"),
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
