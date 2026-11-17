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


class Clock:
    """Monotonic clock whose sleep only moves the time forward."""

    def __init__(self):
        self.t = 1000.0
        self.sleeps = 0

    def now(self):
        return self.t

    def sleep(self, s):
        self.sleeps += 1
        assert self.sleeps < 10_000, "runaway wait loop"
        self.t += s


class FakeConsole:
    """`gone_after`, `back_after` and `boot_ok_after` are seconds after the reboot command:
    ssh stops answering, answers again (None: never) and events.log gets `boot OK
    completed`. `booted_build` is the build of /boot/VERSION after the reboot (None: the one
    swapped in)."""

    def __init__(self, board="ga36", battery=80, roms_free=8 << 30, boot_free=1 << 30,
                 boot=None, sector=b"old panel image", corrupt=None, ro_busy=False,
                 boot_used=300 * MiB, boot_files=300 * MiB, clock=None, boot_n=43,
                 gone_after=1, back_after=40, boot_ok_after=50, booted_build=None,
                 send_seconds=30):
        self.clock = clock or Clock()
        self.boot_n, self.rebooted_at = boot_n, None
        self.gone_after, self.back_after = gone_after, back_after
        self.boot_ok_after, self.booted_build = boot_ok_after, booted_build
        self.send_seconds = send_seconds
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

    def since_reboot(self):
        return None if self.rebooted_at is None else self.clock.t - self.rebooted_at

    def answers(self):
        dt = self.since_reboot()
        if dt is None or dt < self.gone_after:
            return True
        return self.back_after is not None and dt >= self.back_after

    def boot_status(self):
        if not self.answers():
            raise push.PushError("ssh to the console failed: no answer")
        dt = self.since_reboot()
        n = self.boot_n + (dt is not None)
        build = self.booted_build or self.boot["VERSION"].decode().removeprefix("build: ")
        ok = (f"1970-01-01T00:00:43 {n} boot OK completed: frontend in 33.6s from kernel"
              if dt is not None and dt >= self.boot_ok_after else "")
        return f"{n}\n{build.strip()}\n{ok}\n"

    def run(self, cmd, stdin=None):
        self.cmds.append(cmd)
        if cmd == push.READ_BOOT_N:
            self.log.append("read boot-n")
            return f"{self.boot_n}\n"
        if cmd == push.BOOT_STATUS:
            self.log.append("boot status")
            return self.boot_status()
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
            self.clock.t += self.send_seconds
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
            self.rebooted_at = self.clock.t
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


def run_push(tmp_path, console, wait=False, **kw):
    lines = []
    clock = getattr(console, "clock", None) or Clock()
    rc = push.push("latest", console, yes=True, extractor=extractor(tmp_path),
                   out=lines.append, wait=wait, sleep=clock.sleep, now=clock.now, **kw)
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
    assert (args.command, args.build, args.yes, args.no_wait) == ("push", BUILD, True, False)
    assert cli._parser().parse_args(["push", "--no-wait"]).no_wait


# --- after the reboot (build-speed D12, task 3.3) ------------------------------------------

def test_push_waits_for_the_new_boot_and_prints_ok_with_the_times(build, tmp_path):
    c = FakeConsole(board="r36s")
    rc, out = run_push(tmp_path, c, wait=True)
    assert rc == 0
    # the boot number is read before the reboot, the new boot only after
    assert c.log.index("read boot-n") < c.log.index("reboot") < c.log.index("boot status")
    # 4 files and SHA256SUMS at 30 s each; boot OK seen at the first poll >= 50 s
    assert out[-1] == (f"ok: boot 44 completed with build {BUILD} (frontend in 33.6s from "
                       "kernel); send 2m30s, boot 50s")
    assert c.clock.sleeps < 60


def test_push_reports_a_console_that_does_not_come_back(build, tmp_path):
    c = FakeConsole(back_after=None)
    with pytest.raises(push.PushError) as e:
        run_push(tmp_path, c, wait=True)
    msg = str(e.value)
    assert f"did not come back over the cable within {push.BACK_TIMEOUT}s" in msg
    assert "last step confirmed: the console went away for the reboot" in msg
    assert "boot status" not in c.log


def test_push_reports_a_console_that_never_goes_away(build, tmp_path):
    c = FakeConsole(gone_after=10_000)
    with pytest.raises(push.PushError, match=r"still answers 60s after the reboot \(last "
                                             r"step confirmed: reboot sent\)"):
        run_push(tmp_path, c, wait=True)


def test_push_reports_the_wrong_build_with_both_ids(build, tmp_path):
    # the console came back, but /boot/VERSION is not the pushed build (e.g. another card)
    c = FakeConsole(booted_build="20261101-090000")
    with pytest.raises(push.PushError) as e:
        run_push(tmp_path, c, wait=True)
    msg = str(e.value)
    assert "build 20261101-090000" in msg and f"pushed build {BUILD}" in msg
    assert "last step confirmed: boot 44 started" in msg
    assert c.log.count("boot status") == 1      # fails at once, no wait for boot OK


def test_push_reports_a_boot_that_does_not_complete(build, tmp_path):
    c = FakeConsole(boot_ok_after=10_000)
    with pytest.raises(push.PushError) as e:
        run_push(tmp_path, c, wait=True)
    msg = str(e.value)
    assert f"boot 44 did not reach `boot OK completed` within {push.BOOT_OK_TIMEOUT}s" in msg
    assert f"last step confirmed: boot 44 started with build {BUILD}" in msg


def test_push_reports_the_same_boot_number_after_the_reboot(build, tmp_path):
    c = FakeConsole()
    real = c.boot_status
    c.boot_status = lambda: real().replace("44\n", "43\n", 1)
    with pytest.raises(push.PushError, match="still runs boot 43"):
        run_push(tmp_path, c, wait=True)


def test_extra_checks_after_the_boot_turn_ok_into_an_error(build, tmp_path):
    # the hook for the slot and fragment checks of nodes 4.6 and 8.2
    seen = []

    def slots_mounted(remote, state):
        seen.append(state.boot_n)
        return "slot ga36-base-1234 not mounted"
    c = FakeConsole()
    with pytest.raises(push.PushError, match="but: slot ga36-base-1234 not mounted"):
        run_push(tmp_path, c, wait=True, checks=[slots_mounted])
    assert seen == ["44"]
    rc, out = run_push(tmp_path, FakeConsole(), wait=True, checks=[lambda r, s: None])
    assert rc == 0 and out[-1].startswith("ok: ")


def test_no_wait_and_nothing_to_send_never_wait(build, tmp_path):
    c = FakeConsole()
    rc, out = run_push(tmp_path, c, wait=False)
    assert rc == 0 and c.log[-1] == "reboot" and "read boot-n" not in c.log
    assert not any(line.startswith("ok:") for line in out)
    same = FakeConsole(board="r36s", boot=NEW)
    rc, out = run_push(tmp_path, same, wait=True)
    assert rc == 0 and same.log == ["probe"] and same.clock.sleeps == 0


def test_ssh_drops_a_dead_connection_and_a_hung_probe_is_no_answer(monkeypatch):
    # J1 (2026-11-16): the probe started as the console rebooted and hung for minutes
    import subprocess

    base = " ".join(push.Remote().base)
    assert "ServerAliveInterval=3" in base and "ServerAliveCountMax=2" in base
    seen = {}

    def hung(argv, **kw):
        seen["timeout"] = kw.get("timeout")
        raise subprocess.TimeoutExpired(argv, kw.get("timeout"))

    monkeypatch.setattr(push.subprocess, "run", hung)
    assert push.Remote().answers() is False
    assert seen["timeout"] == push.PROBE_TIMEOUT
