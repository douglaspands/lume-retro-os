"""usb-device-access task 5.2: `r36os push` against a fake console that answers the ssh
commands, keeps BOOT, the staging folder on ROMS and the GA36 boot sector, and records the
order of the steps."""

import hashlib
import re

import pytest

from r36os import cli, push

BUILD = "20261114-100000"


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


NEW = {"boot.ini": b"ini", "ga36/SYSTEM": b"new ga36 system", "ga36/zImage": b"new zimage",
       "r36s/SYSTEM": b"new r36s system", "VERSION": b"build: " + BUILD.encode() + b"\n"}
PANEL1 = b"android boot image panel 1"


MiB = 1 << 20


class FakeConsole:
    def __init__(self, board="ga36", battery=80, roms_free=8 << 30, boot_free=1 << 30,
                 boot=None, sector=b"old panel image", corrupt=None, ro_busy=False,
                 boot_used=300 * MiB, boot_files=300 * MiB):
        self.board, self.battery = board, battery
        self.ro_busy = ro_busy          # vfat refuses ro: a deleted file is still open
        self.roms_free, self.boot_free = roms_free, boot_free
        self.boot_used, self.boot_files = boot_used, boot_files   # df and du of BOOT
        self.cmds = []                  # every command, verbatim
        self.boot = dict(boot if boot is not None else
                         {"boot.ini": b"ini", "ga36/SYSTEM": b"old", "ga36/zImage": b"old z",
                          "r36s/SYSTEM": b"old r", "VERSION": b"build: old\n"})
        self.sector = sector
        self.staging = {}
        self.corrupt = corrupt          # a staged file that arrives damaged
        self.log = []                   # steps, in order

    @staticmethod
    def stale(p):
        return p.endswith((".old", ".new"))

    def run(self, cmd, stdin=None):
        self.cmds.append(cmd)
        if cmd == push._PROBE:
            self.log.append("probe")
            sums = "".join(f"{sha(d)}  {p}\n" for p, d in self.boot.items()
                           if not self.stale(p))
            stale_k = sum(-(-len(d) // 1024) for p, d in self.boot.items() if self.stale(p))
            return (f"old\n{self.board}\n{'-' if self.battery is None else self.battery}\n"
                    f"{self.roms_free // 1024}\n{self.boot_free // 1024}\n/dev/mmcblk0\n"
                    f"{stale_k}\n{self.boot_used // 1024}\n{self.boot_files // 1024}\n{sums}")
        if cmd == push.STALE_CLEANUP:
            self.log.append("clean stale")
            self.boot = {p: d for p, d in self.boot.items() if not self.stale(p)}
            return ""
        if m := re.match(r"dd if=/dev/mmcblk0 bs=512 skip=172032 count=\d+ 2>/dev/null \| "
                         r"head -c (\d+)", cmd):
            self.log.append("read sector")
            return sha(self.sector[:int(m.group(1))]) + "\n"
        if cmd.startswith("rm -rf /storage/.lume-push &&"):
            self.log.append("staging")
            self.staging = {}
            return ""
        if m := re.search(r"cat > /storage/\.lume-push/[^/]+/(.+)$", cmd):
            data = stdin.read_bytes()
            if m.group(1) == self.corrupt:
                data += b"!"
            self.staging[m.group(1)] = data
            self.log.append(f"send {m.group(1)}")
            return ""
        if "sha256sum -c SHA256SUMS" in cmd:
            self.log.append("check")
            for line in self.staging["SHA256SUMS"].decode().splitlines():
                d, p = line.split("  ")
                if sha(self.staging[p]) != d:
                    raise push.PushError(f"on the console, sha256sum failed: {p}: FAILED")
            return ""
        if cmd == "mount -o remount,rw /boot":
            self.log.append("boot rw")
            return ""
        if m := re.match(r"mkdir -p \S+ && cp /storage/\.lume-push/[^/]+/(\S+) /boot/\S+\.new "
                         r"&& sync && ", cmd):
            p = m.group(1)
            if f"mv /boot/{p} /boot/{p}.old" in cmd and p in self.boot:
                self.boot[f"{p}.old"] = self.boot[p]
            self.boot[p] = self.staging[p]
            self.log.append(f"swap {p}")
            return ""
        if m := re.match(r"dd if=\S+/(ga36-android-boot-panel1\.img) of=/dev/mmcblk0 bs=512 "
                         r"seek=172032", cmd):
            self.sector = self.staging[m.group(1)]
            self.log.append("write sector")
            return ""
        if cmd == "sync; mount -o remount,ro /boot":
            if self.ro_busy:
                self.log.append("boot ro refused")
                raise push.PushError("on the console, `sync; mount -o remount,ro /boot` failed "
                                     "(255): mount: mounting /dev/mmcblk0p1 on /boot failed: "
                                     "Resource busy")
            self.log.append("boot ro")
            return ""
        if cmd == "rm -rf /storage/.lume-push":
            self.log.append("cleanup")
            return ""
        if "reboot" in cmd:
            self.log.append("reboot")
            return ""
        raise AssertionError(f"unexpected command: {cmd}")


@pytest.fixture
def build(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "cache"))
    d = tmp_path / "out/images/console" / BUILD
    d.mkdir(parents=True)
    order = [p for p in sorted(NEW) if p != "VERSION"] + ["VERSION"]
    (d / "boot-files.sha256").write_text("".join(f"{sha(NEW[p])}  {p}\n" for p in order))
    (d / push.PANEL1_IMAGE).write_bytes(PANEL1)
    (tmp_path / "out/images/console/latest").symlink_to(BUILD)
    return d


def extractor(tmp_path):
    def extract(build_dir, wanted):
        stage = tmp_path / "stage"
        for p in wanted:
            (stage / p).parent.mkdir(parents=True, exist_ok=True)
            (stage / p).write_bytes(NEW[p])
        return stage
    return extract


def console_with(**kw):
    return push.Console(**{"board": "ga36", "build": "old", "battery": 80,
                           "roms_free": 8 << 30, "boot_free": 1 << 30,
                           "device": "/dev/mmcblk0", "boot_sums": {}, **kw})


def run_push(tmp_path, console, **kw):
    lines = []
    rc = push.push("latest", console, yes=True, extractor=extractor(tmp_path),
                   out=lines.append, **kw)
    return rc, lines


def test_push_sends_checks_swaps_and_reboots_in_order(build, tmp_path):
    c = FakeConsole()
    rc, out = run_push(tmp_path, c)
    assert rc == 0
    # the running SYSTEM of the GA36 keeps its name as .old (push-boot-swap D1)
    assert c.boot == {**NEW, "ga36/SYSTEM.old": b"old"}
    steps = c.log
    # sent and checked on the console before BOOT is touched
    assert steps.index("check") < steps.index("boot rw")
    assert max(i for i, s in enumerate(steps) if s.startswith("send")) < steps.index("check")
    assert steps.index("boot rw") < steps.index("clean stale") < steps.index("swap ga36/SYSTEM")
    swaps = [s for s in steps if s.startswith("swap")]
    assert swaps[-1] == "swap VERSION"                      # VERSION last
    assert steps[-3:] == ["boot ro", "cleanup", "reboot"]
    assert steps.index("boot ro") > steps.index("swap VERSION")
    assert not any(line.startswith("warning:") for line in out)


def test_swap_commands_keep_only_the_running_files_as_old(build, tmp_path):
    # push-boot-swap D1: the running SYSTEM is renamed to .old, never deleted while open;
    # a plain file and the SYSTEM of the other console are renamed over in one mv
    c = FakeConsole(board="ga36")
    run_push(tmp_path, c)
    swaps = {re.search(r"/boot/(\S+)\.new", cmd).group(1): cmd for cmd in c.cmds
             if cmd.startswith("mkdir -p /boot") and " cp " in cmd}
    st = f"/storage/.lume-push/{BUILD}"
    assert swaps["ga36/SYSTEM"] == (
        f"mkdir -p /boot/ga36 && cp {st}/ga36/SYSTEM /boot/ga36/SYSTEM.new && sync && "
        "{ [ ! -e /boot/ga36/SYSTEM ] || mv /boot/ga36/SYSTEM /boot/ga36/SYSTEM.old; } && "
        "mv /boot/ga36/SYSTEM.new /boot/ga36/SYSTEM && sync")
    for p in ("ga36/zImage", "r36s/SYSTEM"):
        d = p.split("/")[0]
        assert swaps[p] == (f"mkdir -p /boot/{d} && cp {st}/{p} /boot/{p}.new && sync && "
                            f"mv /boot/{p}.new /boot/{p} && sync")
    assert "r36s/SYSTEM.old" not in c.boot


def test_old_files_of_an_earlier_push_are_ignored_and_deleted(build, tmp_path):
    # push-boot-swap D2: after the reboot nothing holds the .old open; it is not compared
    # with the build nor sent, and it goes before the copy
    boot = {**NEW, "ga36/SYSTEM": b"old", "ga36/SYSTEM.old": b"older", "VERSION": b"x",
            "r36s/zImage.new": b"interrupted"}
    c = FakeConsole(board="ga36", boot=boot, sector=PANEL1)
    console = push.read_console(c)
    assert "ga36/SYSTEM.old" not in console.boot_sums
    assert "r36s/zImage.new" not in console.boot_sums
    assert console.boot_stale == 2 * 1024
    run_push(tmp_path, c)
    sent = {s[5:] for s in c.log if s.startswith("send ")} - {"SHA256SUMS"}
    assert sent == {"ga36/SYSTEM", "VERSION"}
    assert c.log.index("clean stale") < c.log.index("swap ga36/SYSTEM")
    assert c.boot == {**NEW, "ga36/SYSTEM.old": b"old"}     # the one of this push only


def test_boot_room_counts_the_old_files_that_will_be_deleted():
    sizes = {"ga36/SYSTEM": 100 * MiB, "ga36/zImage": 10 * MiB}
    console = console_with(boot_free=150 * MiB)
    with pytest.raises(push.PushError, match="BOOT has 150 MiB free, the push needs 200 MiB"):
        push.check_room(console, sizes)
    console.boot_stale = 60 * MiB                         # an earlier SYSTEM.old
    push.check_room(console, sizes)
    console.boot_stale = 40 * MiB
    with pytest.raises(push.PushError, match=r"190 MiB free \(with 40 MiB of an earlier"):
        push.check_room(console, sizes)


@pytest.mark.parametrize("lost, warned", [(31 * MiB, False), (290 * MiB, True)])
def test_lost_clusters_are_warned_and_the_push_goes_on(build, tmp_path, lost, warned):
    # push-boot-swap D3: df passes du by the size of the chains no file owns
    c = FakeConsole(boot_used=300 * MiB + lost, boot_files=300 * MiB)
    rc, out = run_push(tmp_path, c)
    warnings = [line for line in out if line.startswith("warning: BOOT has")]
    assert rc == 0 and "reboot" in c.log
    if warned:
        assert len(warnings) == 1
        assert "290 MiB in lost clusters" in warnings[0]
        assert "fsck.vfat -a" in warnings[0] and "FSCK*.REC" in warnings[0]
        assert "r36os flash --update" in warnings[0]
    else:
        assert not warnings


def test_boot_busy_for_read_only_after_the_swap_warns_cleans_up_and_reboots(build, tmp_path):
    # push-boot-swap D5: with the running files kept as .old, vfat refusing `remount,ro`
    # ("Resource busy") means something else holds a deleted file open; the files are
    # already written and synced, so the push goes on with a warning
    c = FakeConsole(ro_busy=True)
    rc, out = run_push(tmp_path, c)
    assert rc == 0
    assert c.boot == {**NEW, "ga36/SYSTEM.old": b"old"}
    assert c.log[-3:] == ["boot ro refused", "cleanup", "reboot"]
    assert any(line.startswith("warning: BOOT stays read-write") and "lost clusters" in line
               for line in out)


def test_a_failed_swap_is_still_the_error_shown_when_ro_is_refused(build, tmp_path):
    c = FakeConsole(ro_busy=True)
    real = c.run

    def run(cmd, stdin=None):
        if cmd.startswith("mkdir -p /boot/ga36 && cp"):
            raise push.PushError("on the console, `cp` failed (1): no space")
        return real(cmd, stdin)
    with pytest.raises(push.PushError, match="no space"):
        push.push("latest", type("R", (), {"run": staticmethod(run)})(), yes=True,
                  extractor=extractor(tmp_path), out=lambda _: None)
    assert "reboot" not in c.log


def test_only_the_files_that_differ_are_sent(build, tmp_path):
    c = FakeConsole(board="r36s")
    rc, _ = run_push(tmp_path, c)
    sent = {s[5:] for s in c.log if s.startswith("send ")} - {"SHA256SUMS"}
    assert sent == {"ga36/SYSTEM", "ga36/zImage", "r36s/SYSTEM", "VERSION"}   # not boot.ini


def test_the_same_build_sends_nothing(build, tmp_path):
    c = FakeConsole(board="r36s", boot=NEW)
    rc, out = run_push(tmp_path, c)
    assert rc == 0 and "nothing to send: the console already runs this build" in out
    assert c.log == ["probe"]


def test_ga36_boot_image_written_only_when_it_changed_and_read_back(build, tmp_path):
    c = FakeConsole(board="ga36")
    run_push(tmp_path, c)
    assert c.sector == PANEL1
    assert c.log.index("write sector") > c.log.index("boot rw")
    assert c.log.count("read sector") == 2                  # before, and read back after
    c2 = FakeConsole(board="ga36", sector=PANEL1)
    run_push(tmp_path, c2)
    assert "write sector" not in c2.log


def test_r36s_never_touches_the_ga36_sector(build, tmp_path):
    c = FakeConsole(board="r36s")
    run_push(tmp_path, c)
    assert "read sector" not in c.log and "write sector" not in c.log


def test_a_file_that_arrives_damaged_stops_before_boot(build, tmp_path):
    c = FakeConsole(corrupt="ga36/SYSTEM")
    with pytest.raises(push.PushError, match="ga36/SYSTEM: FAILED"):
        run_push(tmp_path, c)
    assert "boot rw" not in c.log and c.boot["ga36/SYSTEM"] == b"old"


@pytest.mark.parametrize("battery", [19, 5])
def test_low_battery_is_refused(build, tmp_path, battery):
    c = FakeConsole(battery=battery)
    with pytest.raises(push.PushError, match=f"battery at {battery}%"):
        run_push(tmp_path, c)
    assert c.log == ["probe"]


def test_no_room_on_roms_is_refused(build, tmp_path):
    c = FakeConsole(roms_free=1 << 20)
    with pytest.raises(push.PushError, match="ROMS has 1 MiB free"):
        run_push(tmp_path, c)
    assert not [s for s in c.log if s.startswith("send")]


def test_no_room_on_boot_is_refused(build, tmp_path):
    c = FakeConsole(boot_free=4)
    with pytest.raises(push.PushError, match="BOOT has 0 MiB free"):
        run_push(tmp_path, c)
    assert not [s for s in c.log if s.startswith("send")]


def test_boot_room_counts_the_running_modules_image():
    # kernel-modules-image D5: the running modules image stays open by its loop, as SYSTEM
    sizes = {"ga36/SYSTEM": 100 * MiB, "ga36/modules": 30 * MiB, "r36s/modules": 50 * MiB}
    push.check_room(console_with(boot_free=230 * MiB), sizes)
    with pytest.raises(push.PushError, match="needs 230 MiB"):
        push.check_room(console_with(boot_free=229 * MiB), sizes)


def test_ssh_needs_no_key_and_leaves_known_hosts_alone():
    # root has no password on the cable (D4) and the host key is new every boot: batch
    # mode, nothing read from or written to the user's known_hosts
    base = push.Remote().base
    assert base[-1] == "root@10.55.0.1"
    for opt in ("UserKnownHostsFile=/dev/null", "StrictHostKeyChecking=no", "BatchMode=yes"):
        assert opt in base
    assert "-i" not in base


def test_a_build_without_the_boot_list_is_refused(build, tmp_path):
    (build / "boot-files.sha256").unlink()
    with pytest.raises(push.PushError, match="rebuild it"):
        run_push(tmp_path, FakeConsole())


def test_cli_push():
    args = cli._parser().parse_args(["push", "--build", BUILD, "--yes"])
    assert (args.command, args.build, args.yes) == ("push", BUILD, True)
