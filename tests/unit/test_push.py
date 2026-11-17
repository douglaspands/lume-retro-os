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
                 send_seconds=30, loops=None, cut_at=None, damaged_on_boot=None):
        self.clock = clock or Clock()
        self.fragments = None           # name -> version of the lume-*/r36os-* apk packages
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
        # BOOT files held open by loop devices: by default what the initramfs mounted
        self.loops = list(loops) if loops is not None else self.mounted_files(board)
        self.cut_at = cut_at            # "swap" or "between renames": the power goes
        self.damaged_on_boot = damaged_on_boot   # a file written damaged on BOOT

    @staticmethod
    def stale(p):
        return p.endswith((".old", ".new")) and not p.endswith("/SLOTS.old")

    # --- the initramfs (initramfs/lib/slots.sh): SLOTS, else SLOTS.old, else SYSTEM ---
    def usable_set(self, path):
        from r36os import manifests
        c = path.split("/")[0]
        if path not in self.boot:
            return None
        try:
            ss = manifests.parse_slots(self.boot[path].decode(), path)
        except manifests.ManifestError:
            return None
        if ss.console != c or any(f"{c}/{f}" not in self.boot for f in ss.files()):
            return None
        return ss

    def mounted(self, board):
        """The manifest (or legacy root) the initramfs mounts for `board`, and its set."""
        for name in ("SLOTS", "SLOTS.old"):
            if ss := self.usable_set(f"{board}/{name}"):
                return f"{board}/{name}", ss
        for name in ("SYSTEM", "SYSTEM.old"):
            if f"{board}/{name}" in self.boot:
                return f"{board}/{name}", None
        return None, None

    def mounted_files(self, board):
        man, ss = self.mounted(board)
        if ss is not None:
            return [f"/boot/{board}/{f}" for f in ss.files()]
        return [f"/boot/{man}"] + ([f"/boot/{board}/modules"]
                                   if f"{board}/modules" in self.boot else []) if man else []

    def slot_state(self):
        out = []
        for p in sorted(self.boot):
            if p.count("/") == 1 and p.split("/")[1] in ("SLOTS", "SLOTS.old"):
                out.append(f"== {p}\n{self.boot[p].decode(errors='replace')}\n== eof\n")
        out.append("== loops\n" + "".join(f"{x}\n" for x in self.loops))
        out.append("== sizes\n" + "".join(f"{-(-len(d) // 1024)}\t/boot/{p}\n"
                                          for p, d in sorted(self.boot.items())
                                          if p.count("/") == 2 and p.split("/")[1] == "slot"))
        return "".join(out)

    def slots_mounted(self):
        """The answer to push.SLOTS_MOUNTED after the reboot."""
        board = self.board
        on_boot = self.usable_set(f"{board}/SLOTS")
        head = f"{board}\n{on_boot.build if on_boot else '-'}\n"
        if f"{board}/SLOTS" in self.boot and on_boot is None:
            from r36os import manifests
            try:
                head = (f"{board}\n"
                        f"{manifests.parse_slots(self.boot[f'{board}/SLOTS'].decode()).build}\n")
            except manifests.ManifestError:
                pass
        man, ss = self.mounted(board)
        if ss is not None:
            return (head + f"[ 1.0] lume: slots: {man} (build {ss.build})\n"
                    f"[ 1.1] lume: root: {man} (lume, runtime, base; read-only) + 32 MiB "
                    "RAM layer\n")
        return head + f"[ 1.1] lume: root: {man} (read-only) + 32 MiB RAM layer\n"

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
        if cmd == push.SLOT_STATE:
            self.log.append("slot state")
            return self.slot_state()
        if cmd == push.SLOTS_MOUNTED:
            self.log.append("slots mounted")
            return self.slots_mounted()
        if cmd == push.FRAGMENT_VERSIONS:
            self.log.append("fragment versions")
            return "".join(f"{n} {v}\n" for n, v in (self.fragments or {}).items())
        if m := re.fullmatch(r"rm -f ((?:/boot/\S+ ?)+) && sync", cmd):
            gone = [p.removeprefix("/boot/") for p in m.group(1).split()]
            self.log.append("delete " + " ".join(gone))
            for p in gone:
                self.boot.pop(p, None)
            return ""
        if m := re.fullmatch(r"mkdir -p \S+ && cp /storage/\.lume-push/[^/]+/(\S+) "
                             r"/boot/(\S+)\.new && sync", cmd):
            assert m.group(1) == m.group(2)
            self.boot[m.group(2) + ".new"] = self.staging[m.group(1)]
            self.log.append(f"write {m.group(2)}.new")
            return ""
        if m := re.fullmatch(r"sync && echo 3 > /proc/sys/vm/drop_caches && cd /boot && "
                             r"sha256sum -c /storage/\.lume-push/[^/]+/(\S+) >/dev/null", cmd):
            self.log.append("check boot")
            for line in self.staging[m.group(1)].decode().splitlines():
                d, p = line.split("  ")
                if p not in self.boot or sha(self.boot[p]) != d:
                    raise push.PushError(f"on the console, sha256sum failed: {p}: FAILED")
            return ""
        if m := re.fullmatch(r"cd /boot/(\w+) && (.*)", cmd):
            c, steps = m.group(1), m.group(2)
            self.log.append(f"rename {c}/SLOTS")
            if self.cut_at == "swap":
                raise push.PushError("ssh to the console failed: no answer (power cut)")
            if steps == ("rm -f SLOTS.old && sync && mv SLOTS SLOTS.old && sync && "
                         "mv SLOTS.new SLOTS && sync"):
                self.boot.pop(f"{c}/SLOTS.old", None)
                self.boot[f"{c}/SLOTS.old"] = self.boot.pop(f"{c}/SLOTS")
                if self.cut_at == "between renames":
                    raise push.PushError("ssh to the console failed: no answer (power cut)")
            elif steps == "rm -f SLOTS && sync && mv SLOTS.new SLOTS && sync":
                self.boot.pop(f"{c}/SLOTS", None)
            else:
                raise AssertionError(f"unexpected swap: {cmd}")
            self.boot[f"{c}/SLOTS"] = self.boot.pop(f"{c}/SLOTS.new")
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
            self.boot[p] = self.staging[p] + (b"!" if p == self.damaged_on_boot else b"")
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
    # build-speed D10: every BOOT file of the build is out/images/objects/<sha256>
    objects = tmp_path / "out/images/objects"
    objects.mkdir()
    for data in NEW.values():
        (objects / sha(data)).write_bytes(data)
    return d


def extractor(tmp_path, calls=None):
    """The image unpacking of a build archived before the objects."""
    def extract(build_dir, wanted):
        if calls is not None:
            calls.append(list(wanted))
        stage = tmp_path / "stage"
        for p in wanted:
            (stage / p).parent.mkdir(parents=True, exist_ok=True)
            (stage / p).write_bytes(NEW[p])
        return stage
    return extract


def no_unpacking(build_dir, wanted):
    raise AssertionError(f"the image was unpacked for {wanted}")


def console_with(**kw):
    return push.Console(**{"board": "ga36", "build": "old", "battery": 80,
                           "roms_free": 8 << 30, "boot_free": 1 << 30,
                           "device": "/dev/mmcblk0", "boot_sums": {}, **kw})


def run_push(tmp_path, console, wait=False, **kw):
    lines = []
    clock = getattr(console, "clock", None) or Clock()
    kw.setdefault("extractor", no_unpacking)
    rc = push.push("latest", console, yes=True, out=lines.append, wait=wait,
                   sleep=clock.sleep, now=clock.now, **kw)
    return rc, lines


def sent_files(console):
    return {s[5:] for s in console.log if s.startswith("send ")} - {"SHA256SUMS",
                                                                    push.BOOT_SUMS}


# --- content-addressed archive (build-speed D10, task 4.3) --------------------------------

def test_nothing_changed_but_version_sends_nothing(build, tmp_path):
    # VERSION differs in every build: left out of the comparison
    c = FakeConsole(board="r36s", boot={**NEW, "VERSION": b"build: 20261113-090000\n"})
    rc, out = run_push(tmp_path, c, wait=True)
    assert rc == 0 and c.log == ["probe"] and c.clock.sleeps == 0
    assert out[-1] == ("nothing to send: the console already has every file of this build "
                       "(only VERSION differs)")
    # the same on the GA36 when its boot sector already holds the panel 1 image
    c = FakeConsole(board="ga36", sector=PANEL1, boot={**NEW, "VERSION": b"x"})
    rc, out = run_push(tmp_path, c)
    assert rc == 0 and "reboot" not in c.log and "only VERSION differs" in out[-1]


def test_version_goes_with_the_ga36_boot_sector_when_only_it_changed(build, tmp_path):
    c = FakeConsole(board="ga36", boot={**NEW, "VERSION": b"x"})
    rc, _ = run_push(tmp_path, c)
    assert rc == 0 and sent_files(c) == {"VERSION", push.PANEL1_IMAGE}
    assert c.sector == PANEL1 and c.boot["VERSION"] == NEW["VERSION"]


def test_one_file_changed_goes_with_version_read_from_the_objects(build, tmp_path):
    c = FakeConsole(board="r36s", boot={**NEW, "ga36/zImage": b"old z", "VERSION": b"x"})
    rc, out = run_push(tmp_path, c)                 # the extractor fails if called
    assert rc == 0 and sent_files(c) == {"ga36/zImage", "VERSION"}
    assert c.staging["ga36/zImage"] == NEW["ga36/zImage"]
    swaps = [s for s in c.log if s.startswith("swap")]
    assert swaps == ["swap ga36/zImage", "swap VERSION"]          # VERSION last
    assert not any("unpacking" in line or line.startswith("note:") for line in out)
    assert c.boot == NEW


def test_plan_files_puts_version_last_and_only_with_another_file():
    boot_list = [("a", "1" * 64), ("b", "2" * 64), ("VERSION", "3" * 64)]
    on_console = console_with(boot_sums={"a": "1" * 64, "b": "0" * 64, "VERSION": "3" * 64})
    assert push.plan_files(boot_list, on_console) == [("b", "2" * 64), ("VERSION", "3" * 64)]
    on_console.boot_sums["b"] = "2" * 64
    assert push.plan_files(boot_list, on_console) == []
    on_console.boot_sums["VERSION"] = "9" * 64
    assert push.plan_files(boot_list, on_console) == []
    assert push.plan_files(boot_list, on_console, other_change=True) == [("VERSION", "3" * 64)]


def test_an_older_archived_build_is_unpacked_once_and_its_files_stored(build, tmp_path):
    # a build archived before the objects: only the .img.zst and the BOOT list
    objects = tmp_path / "out/images/objects"
    for f in objects.iterdir():
        f.unlink()
    calls = []
    c = FakeConsole(board="r36s")
    rc, out = run_push(tmp_path, c, extractor=extractor(tmp_path, calls))
    assert rc == 0 and c.boot == {**NEW, "r36s/SYSTEM.old": b"old r"}
    assert calls == [["ga36/SYSTEM", "ga36/zImage", "r36s/SYSTEM", "VERSION"]]
    assert any(line.startswith(f"note: build {BUILD} has no stored object for 4 file(s)")
               for line in out)
    # the files read from the image are now objects: the next push does not unpack
    assert {f.name for f in objects.iterdir()} == {sha(NEW[p]) for p in calls[0]}
    c2 = FakeConsole(board="ga36")
    rc, out = run_push(tmp_path, c2)                # no_unpacking
    assert rc == 0 and c2.boot == {**NEW, "ga36/SYSTEM.old": b"old"}


def test_an_older_build_whose_image_differs_from_its_list_is_refused(build, tmp_path):
    for f in (tmp_path / "out/images/objects").iterdir():
        f.unlink()

    def damaged(build_dir, wanted):
        stage = extractor(tmp_path)(build_dir, wanted)
        (stage / "ga36/SYSTEM").write_bytes(b"damaged")
        return stage
    c = FakeConsole(board="r36s")
    with pytest.raises(push.PushError, match="ga36/SYSTEM read from the image does not match"):
        run_push(tmp_path, c, extractor=damaged)
    assert not [s for s in c.log if s.startswith("send")]


def test_a_garbled_boot_list_is_refused(build, tmp_path):
    (build / "boot-files.sha256").write_text(f"{sha(b'x')}  ga36/SYSTEM\n")   # no VERSION
    with pytest.raises(push.PushError, match="VERSION is not the last line"):
        run_push(tmp_path, FakeConsole())


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


# --- push --hot (build-speed D11, task 5.1) -------------------------------------------------

HOT_VERSION = "1.0-r3"
HOT_FILES = {"usr/libexec/r36os/session": b"#!/bin/sh\necho new session\n",
             "etc/init.d/frontend": b"#!/sbin/openrc-run\n",
             "etc/init.d/r36os-logd": b"#!/sbin/openrc-run\n"}


class FakeHotConsole:
    """Answers the --hot commands: probe, tar extraction (unpacked into a dict), event and
    service restarts; records every command in order."""

    def __init__(self, machine="armv7l", overlay=True, ram_free=20 << 20,
                 running=("frontend", "r36os-logd"), failing=()):
        self.machine, self.overlay, self.ram_free = machine, overlay, ram_free
        self.running, self.failing = set(running), set(failing)
        self.cmds = []
        self.root = {}

    def run(self, cmd, stdin=None):
        import tarfile

        self.cmds.append(cmd)
        if cmd.lstrip().startswith("uname -m"):
            return (f"{self.machine}\nga36\n{'overlay' if self.overlay else 'none'}\n"
                    f"{self.ram_free >> 10}\n")
        if cmd == "tar -xf - -C /":
            with tarfile.open(stdin) as tf:
                for m in tf:
                    f = tf.extractfile(m) if m.isreg() else None
                    self.root[m.name] = (f.read() if f else None, m.pax_headers)
            return ""
        if cmd.startswith("for s in"):
            names = cmd.split("for s in ", 1)[1].split("; do", 1)[0].split()
            return "".join(("failed" if n in self.failing else "restarted" if n in
                            self.running else "stopped") + f" {n}\n" for n in names)
        return ""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """out/repo/<arch>/ with lume-core published (noarch: the same file in every arch)."""
    from r36os import manifests
    from tests.unit.test_fragments import make_apk

    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "cache"))
    for arch in ("armv7", "aarch64", "x86_64"):
        d = tmp_path / "out/repo" / arch
        name = f"lume-core-{HOT_VERSION}.apk"
        make_apk(d / name, "lume-core", HOT_VERSION, files=HOT_FILES)
        manifests.write_hashes(d / "hashes.json", manifests.RepoHashes(arch, {
            "lume-core": manifests.PackageHashes(HOT_VERSION, "a" * 64, "b" * 64, name)}))
    return tmp_path / "out/repo"


def hot(console, tmp_path, fragment="lume-core", aports=None):
    from r36os import push_hot

    lines = []
    rc = push_hot.push_hot(fragment, console, out=lines.append,
                           aports=aports or tmp_path / "aports")
    return rc, lines


def test_hot_extracts_the_files_logs_the_event_and_restarts_the_services(repo, tmp_path):
    console = FakeHotConsole()
    rc, lines = hot(console, tmp_path)
    assert rc == 0
    # only the data files go, without control members or the APK checksum headers
    files = {n: d for n, (d, _) in console.root.items() if d is not None}
    assert files == HOT_FILES
    assert not any(n.lstrip("./").startswith(".") for n in console.root)
    assert all(not pax for _, pax in console.root.values())
    probe, extract, event, restart = console.cmds
    assert extract == "tar -xf - -C /"
    assert event == (". /usr/libexec/r36os/lib.sh && . /usr/libexec/r36os/logs.sh && "
                     f"event push OK hot lume-core {HOT_VERSION} && {{ logs_flush; true; }}")
    assert restart.startswith("for s in frontend r36os-logd; do")
    assert f"event:   push OK hot lume-core {HOT_VERSION}" in lines
    assert any("restarts the launcher session" in ln for ln in lines)
    assert "restart: frontend" in lines and "restart: r36os-logd" in lines
    assert lines[-1] == f"ok: lume-core {HOT_VERSION} is live until the next reboot"
    # nothing touches BOOT, the card's SYSTEM or apk
    assert not any("/boot" in c or "apk add" in c or "reboot" in c for c in console.cmds)


def test_hot_takes_the_package_of_the_console_arch(repo, tmp_path):
    (repo / "armv7/hashes.json").unlink()
    with pytest.raises(push.PushError, match=r"not in .*armv7/hashes.json"):
        hot(FakeHotConsole(machine="armv7l"), tmp_path)
    assert hot(FakeHotConsole(machine="aarch64"), tmp_path)[0] == 0


def test_hot_restarts_what_lume_restart_lists_and_leaves_stopped_services(repo, tmp_path):
    aports = tmp_path / "aports"
    (aports / "lume-core").mkdir(parents=True)
    (aports / "lume-core/APKBUILD").write_text(
        'pkgname=lume-core\n_lume_restart="r36os-logd lume-extra"\n')
    console = FakeHotConsole(running=("r36os-logd",))
    rc, lines = hot(console, tmp_path, aports=aports)
    assert rc == 0 and console.cmds[-1].startswith("for s in r36os-logd lume-extra; do")
    assert "restart: lume-extra not running, left stopped" in lines
    assert not any("launcher session" in ln for ln in lines)


def test_hot_reports_a_failed_restart_with_a_fail_event(repo, tmp_path):
    console = FakeHotConsole(failing=("r36os-logd",))
    with pytest.raises(push.PushError, match="restart of r36os-logd failed"):
        hot(console, tmp_path)
    assert f"event push FAIL hot lume-core {HOT_VERSION} restart r36os-logd" in console.cmds[-1]


@pytest.mark.parametrize("fragment,why", [
    ("lume-kernel", "only changes with a reboot"),
    ("lume-modules", "only changes with a reboot"),
    ("lume-dtbs", "only changes with a reboot"),
    ("retroarch", "not a project fragment"),
    ("busybox", "not a project fragment"),
])
def test_hot_refuses_kernel_modules_and_foreign_packages_before_ssh(fragment, why, tmp_path):
    console = FakeHotConsole()
    with pytest.raises(push.PushError, match=why) as e:
        hot(console, tmp_path, fragment)
    assert "r36os push" in str(e.value) and console.cmds == []


def test_hot_refuses_the_base_slot(tmp_path, monkeypatch):
    from r36os import push_hot

    slots = tmp_path / "slots.toml"
    slots.write_text('[base]\npackages = ["lume-base-files"]\n')
    monkeypatch.setattr(push_hot, "SLOTS_MAP", slots)
    assert push_hot.base_slot_packages(slots) == {"lume-base-files"}
    assert "base slot" in push_hot.refusal("lume-base-files", push_hot.base_slot_packages(slots))
    with pytest.raises(push.PushError, match="base slot"):
        hot(FakeHotConsole(), tmp_path, "lume-base-files")
    assert push_hot.base_slot_packages(tmp_path / "missing.toml") == set()


def test_hot_refuses_a_fragment_that_ships_boot_files(repo, tmp_path):
    from r36os import manifests
    from tests.unit.test_fragments import make_apk

    name = "lume-odd-1.0-r0.apk"
    make_apk(repo / "armv7" / name, "lume-odd", "1.0-r0", files={"boot/zImage": b"k"})
    hashes = manifests.read_hashes(repo / "armv7/hashes.json", "armv7")
    hashes.packages["lume-odd"] = manifests.PackageHashes("1.0-r0", "a" * 64, "b" * 64, name)
    manifests.write_hashes(repo / "armv7/hashes.json", hashes)
    console = FakeHotConsole()
    with pytest.raises(push.PushError, match="boot file"):
        hot(console, tmp_path, "lume-odd")
    assert len(console.cmds) == 1          # only the probe


def test_hot_fragment_not_in_the_repo(repo, tmp_path):
    with pytest.raises(push.PushError, match="build it first"):
        hot(FakeHotConsole(), tmp_path, "lume-missing")


def test_hot_fragment_whose_apk_is_gone(repo, tmp_path):
    (repo / f"armv7/lume-core-{HOT_VERSION}.apk").unlink()
    with pytest.raises(push.PushError, match="missing"):
        hot(FakeHotConsole(), tmp_path)


def test_hot_checks_the_room_of_the_ram_layer_before_writing(repo, tmp_path):
    console = FakeHotConsole(ram_free=512 << 10)
    with pytest.raises(push.PushError, match="RAM layer has 512 KiB free"):
        hot(console, tmp_path)
    assert len(console.cmds) == 1          # only the probe: nothing written


def test_hot_reads_the_ram_layer_free_space_from_the_root(repo, tmp_path):
    # /rw lives in the initramfs and is gone after switch_root: `df /` reports the overlay's
    # upper layer (GA36, 2026-11-17)
    from r36os import push_hot

    assert "df -Pk / " in push_hot._PROBE and "df -Pk /rw" not in push_hot._PROBE


def test_hot_needs_the_ram_overlay_root(repo, tmp_path):
    console = FakeHotConsole(overlay=False)
    with pytest.raises(push.PushError, match="would write to the card"):
        hot(console, tmp_path)
    assert len(console.cmds) == 1


def test_hot_unknown_console_arch(repo, tmp_path):
    with pytest.raises(push.PushError, match="mips"):
        hot(FakeHotConsole(machine="mips"), tmp_path)


def test_cli_push_hot():
    args = cli._parser().parse_args(["push", "--hot", "lume-core"])
    assert (args.command, args.hot) == ("push", "lume-core")
    assert cli._parser().parse_args(["push"]).hot is None


# --- slot sets: push, swap, cleanup and migration (build-speed D9, task 4.6) -------------

OLD_CARD = {"boot.ini": b"ini", "ga36/SYSTEM": b"old ga36 system",
            "ga36/modules": b"old ga36 modules", "ga36/zImage": b"old z",
            "r36s/SYSTEM": b"old r36s system", "r36s/modules": b"old r36s modules",
            "VERSION": b"build: old\n"}
B, C, D = "20261117-100000", "20261117-110000", "20261117-120000"


def slot_set(console, build_id, contents):
    """BOOT path -> bytes of a console's set: <console>/SLOTS and its slot files."""
    from r36os import manifests

    ss = manifests.SlotSet(build=build_id, console=console, slots=tuple(
        manifests.Slot(name=n, sha256=sha(d), size=len(d)) for n, d in contents.items()))
    files = {f"{console}/SLOTS": manifests.format_slots(ss).encode()}
    for s in ss.slots:
        files[f"{console}/{s.file}"] = contents[s.name]
    return files


def contents(console, **changed):
    c = {n: f"{console} {n} A".encode() for n in ("base", "runtime", "lume", "modules")}
    c.update({k: v.encode() for k, v in changed.items()})
    return c


def slot_boot(build_id, ga=None, r=None):
    """The BOOT list of a slot build: both consoles' sets, as the image has them."""
    files = {"boot.ini": b"ini", "ga36/zImage": b"new zimage"}
    files.update(slot_set("ga36", build_id, ga or contents("ga36")))
    files.update(slot_set("r36s", build_id, r or contents("r36s")))
    files["VERSION"] = f"build: {build_id}\n".encode()
    return files


def slot_file_of(files, console, name):
    return next(p for p in files if p.startswith(f"{console}/slot/{name}-"))


@pytest.fixture
def builds(tmp_path, monkeypatch):
    """Builds B, C (GA36 lume changed) and D (changed again) archived with their objects."""
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "cache"))
    objects = tmp_path / "out/images/objects"
    objects.mkdir(parents=True)
    made = {B: slot_boot(B), C: slot_boot(C, ga=contents("ga36", lume="ga36 lume C")),
            D: slot_boot(D, ga=contents("ga36", lume="ga36 lume D"))}
    for build_id, files in made.items():
        d = tmp_path / "out/images/console" / build_id
        d.mkdir(parents=True)
        order = [p for p in files if p != "VERSION"] + ["VERSION"]
        (d / "boot-files.sha256").write_text("".join(f"{sha(files[p])}  {p}\n"
                                                     for p in order))
        for data in files.values():
            (objects / sha(data)).write_bytes(data)
    return made


def slot_push(console, build_id, wait=False, **kw):
    lines = []
    clock = console.clock
    rc = push.push(build_id, console, yes=True, out=lines.append, wait=wait,
                   extractor=no_unpacking, sleep=clock.sleep, now=clock.now, **kw)
    return rc, lines


def rebooted(c, **kw):
    """The same card after the reboot: what the initramfs mounted is held by loops."""
    return FakeConsole(board=c.board, boot=dict(c.boot), sector=c.sector, **kw)


def pushed_to_old_card(builds):
    c = FakeConsole(board="ga36", boot=OLD_CARD)
    rc, out = slot_push(c, B)
    assert rc == 0
    return c, out


def test_old_card_first_push_writes_the_sets_beside_system(builds):
    c, out = pushed_to_old_card(builds)
    new = builds[B]
    assert sent_files(c) == set(new) - {"boot.ini"}
    # the slot sets of both consoles are on BOOT; SYSTEM and modules stay (the fallback)
    for p in new:
        assert c.boot[p] == new[p]
    for p in ("ga36/SYSTEM", "ga36/modules", "r36s/SYSTEM", "r36s/modules"):
        assert c.boot[p] == OLD_CARD[p]
    assert not [p for p in c.boot if p.endswith((".new", ".old"))]
    assert not [s for s in c.log if s.startswith("delete")]
    assert not any(line.startswith("migrate:") for line in out)
    # no SLOTS before: SLOTS.new takes the name with no SLOTS.old to keep
    assert "cd /boot/ga36 && rm -f SLOTS && sync && mv SLOTS.new SLOTS && sync" in c.cmds
    # order: slot files and SLOTS.new, checked on BOOT, other files, renames, VERSION last
    log = c.log
    copies = [i for i, s in enumerate(log) if s.startswith("swap ") and "/slot/" in s]
    assert len(copies) == 8
    assert max(copies) < log.index("write ga36/SLOTS.new") < log.index("check boot")
    assert log.index("check boot") < log.index("swap ga36/zImage") \
        < log.index("rename ga36/SLOTS") < log.index("rename r36s/SLOTS") \
        < log.index("swap VERSION") < log.index("boot ro")
    # the next boot mounts the slot set of each console
    assert c.mounted("ga36")[0] == "ga36/SLOTS" and c.mounted("r36s")[0] == "r36s/SLOTS"


def test_the_push_after_the_first_deletes_system_and_modules(builds):
    first, _ = pushed_to_old_card(builds)
    c = rebooted(first)
    rc, out = slot_push(c, C, wait=True)
    assert rc == 0 and out[-1].startswith(f"ok: boot 44 completed with build {C}")
    lume_c = slot_file_of(builds[C], "ga36", "lume")
    assert sent_files(c) == {lume_c, "ga36/SLOTS", "r36s/SLOTS", "VERSION"}
    for p in ("ga36/SYSTEM", "ga36/modules", "r36s/SYSTEM", "r36s/modules"):
        assert p not in c.boot
    assert c.log.index("swap VERSION") < next(i for i, s in enumerate(c.log)
                                              if s.startswith("delete"))
    assert [line for line in out if line.startswith("migrate:")] == [
        "migrate: ga36 has its slot set since an earlier push: ga36/SYSTEM, ga36/modules "
        "deleted after the swap",
        "migrate: r36s has its slot set since an earlier push: r36s/SYSTEM, r36s/modules "
        "deleted after the swap"]
    # the set of the first push is SLOTS.old, every file of it kept
    assert c.boot["ga36/SLOTS.old"] == builds[B]["ga36/SLOTS"]
    assert c.boot["r36s/SLOTS.old"] == builds[B]["r36s/SLOTS"]
    for p in builds[B]:
        if "/slot/" in p:
            assert p in c.boot
    assert "slots mounted" in c.log


def test_running_system_is_kept_when_the_slots_did_not_mount(builds):
    # the first set did not mount on the GA36: it runs from SYSTEM, which stays
    first, _ = pushed_to_old_card(builds)
    c = rebooted(first, loops=["/boot/ga36/SYSTEM", "/boot/ga36/modules"])
    rc, out = slot_push(c, C)
    assert rc == 0
    assert "ga36/SYSTEM" in c.boot and "ga36/modules" in c.boot
    assert "r36s/SYSTEM" not in c.boot and "r36s/modules" not in c.boot
    assert "note: ga36/SYSTEM kept: the console runs from it (its slot set did not mount, " \
        "see `r36os dev log`)" in out


def test_normal_push_of_a_changed_slot_cleans_the_set_before_the_previous(builds):
    first, _ = pushed_to_old_card(builds)
    second = rebooted(first)
    slot_push(second, C)
    c = rebooted(second)
    rc, out = slot_push(c, D)
    assert rc == 0
    lume = {b: slot_file_of(builds[b], "ga36", "lume") for b in (B, C, D)}
    assert sent_files(c) == {lume[D], "ga36/SLOTS", "r36s/SLOTS", "VERSION"}
    # SLOTS cites D, SLOTS.old cites C: the lume of B goes, after the swap
    assert c.boot["ga36/SLOTS"] == builds[D]["ga36/SLOTS"]
    assert c.boot["ga36/SLOTS.old"] == builds[C]["ga36/SLOTS"]
    assert lume[B] not in c.boot and lume[C] in c.boot and lume[D] in c.boot
    assert f"delete {lume[B]}" in c.log
    assert c.log.index(f"delete {lume[B]}") > c.log.index("rename ga36/SLOTS")
    # the slots every set shares stay
    for name in ("base", "runtime", "modules"):
        assert slot_file_of(builds[D], "ga36", name) in c.boot
    assert "cd /boot/ga36 && rm -f SLOTS.old && sync && mv SLOTS SLOTS.old && sync && " \
        "mv SLOTS.new SLOTS && sync" in c.cmds


def card_after_two_pushes(builds):
    first, _ = pushed_to_old_card(builds)
    second = rebooted(first)
    slot_push(second, C)
    return second


def test_power_cut_between_the_copy_and_the_rename_leaves_slots_intact(builds):
    c = rebooted(card_after_two_pushes(builds), cut_at="swap")
    with pytest.raises(push.PushError, match="power cut"):
        slot_push(c, D)
    lume_d = slot_file_of(builds[D], "ga36", "lume")
    assert lume_d in c.boot and "ga36/SLOTS.new" in c.boot      # copied, not swapped
    assert c.boot["ga36/SLOTS"] == builds[C]["ga36/SLOTS"]
    assert c.boot["VERSION"] == builds[C]["VERSION"]
    man, ss = c.mounted("ga36")
    assert man == "ga36/SLOTS" and ss.build == C                 # the old set, whole
    assert "reboot" not in c.log
    # the next push finishes it: the slot file already there is not sent again
    again = rebooted(c)
    rc, _ = slot_push(again, D)
    assert rc == 0 and lume_d not in sent_files(again)
    assert again.boot["ga36/SLOTS"] == builds[D]["ga36/SLOTS"]
    assert again.boot["ga36/SLOTS.old"] == builds[C]["ga36/SLOTS"]


def test_power_cut_between_the_two_renames_boots_the_previous_set(builds):
    c = rebooted(card_after_two_pushes(builds), cut_at="between renames")
    with pytest.raises(push.PushError, match="power cut"):
        slot_push(c, D)
    assert "ga36/SLOTS" not in c.boot
    man, ss = c.mounted("ga36")
    assert man == "ga36/SLOTS.old" and ss.build == C             # the set that was running
    again = rebooted(c)
    rc, _ = slot_push(again, D)
    assert rc == 0
    # SLOTS was missing: SLOTS.old (the running set) stays, SLOTS.new takes the name
    assert "cd /boot/ga36 && rm -f SLOTS && sync && mv SLOTS.new SLOTS && sync" in again.cmds
    assert again.boot["ga36/SLOTS"] == builds[D]["ga36/SLOTS"]
    assert again.boot["ga36/SLOTS.old"] == builds[C]["ga36/SLOTS"]
    assert slot_file_of(builds[B], "ga36", "lume") not in again.boot


def test_a_slot_written_damaged_on_boot_stops_before_the_swap(builds):
    lume_d = slot_file_of(builds[D], "ga36", "lume")
    c = rebooted(card_after_two_pushes(builds), damaged_on_boot=lume_d)
    with pytest.raises(push.PushError, match=f"{lume_d}: FAILED"):
        slot_push(c, D)
    assert not [s for s in c.log if s.startswith("rename")]
    assert c.boot["ga36/SLOTS"] == builds[C]["ga36/SLOTS"]
    assert c.log[-1] == "boot ro"


def test_cleanup_keeps_what_slots_and_slots_old_cite(builds):
    c = rebooted(card_after_two_pushes(builds))
    stray = "ga36/slot/lume-0123456789ab"          # left by an interrupted push
    held = "ga36/slot/core-x-0123456789ab"         # cited by nothing but held by a loop
    c.boot[stray] = b"stray"
    c.boot[held] = b"held"
    c.loops.append(f"/boot/{held}")
    # a SLOTS.old that does not parse: what it cites is unknown, nothing of r36s goes
    r_stray = "r36s/slot/lume-0123456789ab"
    c.boot[r_stray] = b"r stray"
    c.boot["r36s/SLOTS.old"] = b"lume-slots 1\nbuild x\n"
    rc, _ = slot_push(c, D)
    assert rc == 0
    assert stray not in c.boot and held in c.boot
    # deleted before the copy, for room
    first_delete = next(i for i, s in enumerate(c.log) if s.startswith("delete"))
    assert stray in c.log[first_delete]
    assert first_delete < c.log.index(f"swap {slot_file_of(builds[D], 'ga36', 'lume')}")
    # every file of SLOTS and SLOTS.old is still there
    for console in ("ga36", "r36s"):
        for name in ("SLOTS", "SLOTS.old"):
            assert c.usable_set(f"{console}/{name}") is not None, f"{console}/{name}"
    # the unreadable SLOTS.old was replaced by the running SLOTS, then r36s was cleaned
    assert c.boot["r36s/SLOTS.old"] == builds[C]["r36s/SLOTS"]
    assert r_stray not in c.boot


def test_the_build_must_list_every_slot_its_slots_cites(builds, tmp_path):
    d = tmp_path / "out/images/console" / D
    lume_d = slot_file_of(builds[D], "ga36", "lume")
    lines = [ln for ln in (d / "boot-files.sha256").read_text().splitlines()
             if not ln.endswith(lume_d)]
    (d / "boot-files.sha256").write_text("\n".join(lines) + "\n")
    c = rebooted(card_after_two_pushes(builds))
    with pytest.raises(push.PushError, match=f"cites {lume_d}, not in its"):
        slot_push(c, D)
    assert not [s for s in c.log if s.startswith("send")]


def test_boot_room_counts_every_new_slot_and_keeps_the_running_set():
    sizes = {"ga36/slot/base-0123456789ab": 200 * MiB, "ga36/slot/lume-0123456789ab": 50 * MiB,
             "ga36/SLOTS": 1 * MiB, "ga36/zImage": 10 * MiB}
    push.check_room(console_with(boot_free=261 * MiB), sizes)
    with pytest.raises(push.PushError, match=r"BOOT has 260 MiB free, the push needs 261 MiB "
                                             r"to swap the files \(251 MiB of new slots; the "
                                             r"running set is kept as SLOTS.old\)"):
        push.check_room(console_with(boot_free=260 * MiB), sizes)
    # slot files no manifest cites are deleted first: their room counts
    push.check_room(console_with(boot_free=200 * MiB), sizes, reclaim=61 * MiB)
    with pytest.raises(push.PushError, match=r"with 60 MiB of slots no SLOTS cites"):
        push.check_room(console_with(boot_free=200 * MiB), sizes, reclaim=60 * MiB)


def test_push_counts_the_orphans_as_room(builds):
    c = rebooted(card_after_two_pushes(builds))
    c.boot["ga36/slot/runtime-0123456789ab"] = b"x" * (3 * 1024 * 1024)
    lume_d = slot_file_of(builds[D], "ga36", "lume")
    # room for the new files only once the 3 MiB orphan goes
    c.boot_free = 0
    rc, _ = slot_push(c, D)
    assert rc == 0 and lume_d in c.boot and "ga36/slot/runtime-0123456789ab" not in c.boot


class Answers:
    def __init__(self, text):
        self.text = text

    def run(self, cmd, stdin=None):
        assert cmd == push.SLOTS_MOUNTED
        return self.text


STATE = push.BootState(boot_n="44", build=D, boot_ok="x boot OK completed")


@pytest.mark.parametrize("log, problem", [
    (f"[ 1.0] lume: slots: ga36/SLOTS (build {D})\n[ 1.1] lume: root: ga36/SLOTS (lume, "
     "runtime, base; read-only) + 32 MiB RAM layer\n", None),
    (f"[ 0.5] lume: before kexec: lume: root: ga36/SYSTEM (read-only)\n"
     f"lume: slots: ga36/SLOTS (build {D})\nlume: root: ga36/SLOTS (lume, runtime, base; "
     "read-only) + 32 MiB RAM layer\n", None),
    (f"lume: ERROR: ga36/SLOTS is missing; using ga36/SLOTS.old from the previous build\n"
     f"lume: slots: ga36/SLOTS.old (build {C})\nlume: root: ga36/SLOTS.old (lume, runtime, "
     "base; read-only) + 32 MiB RAM layer\n",
     "boot 44 mounted ga36/SLOTS.old (the previous set), not the pushed set ga36/SLOTS "
     f"(build {D})"),
    ("lume: ERROR: no slot set of ga36 to mount; trying the old ga36/SYSTEM\n"
     "lume: root: ga36/SYSTEM (read-only) + 32 MiB RAM layer\n",
     "boot 44 mounted ga36/SYSTEM (the old root image), not the pushed set ga36/SLOTS"),
    ("", "no `lume: root:` line in the log of boot 44"),
    (f"lume: slots: ga36/SLOTS (build {C})\nlume: root: ga36/SLOTS (lume, runtime, base; "
     "read-only) + 32 MiB RAM layer\n",
     f"logged `slots: ga36/SLOTS (build {C})`, expected `slots: ga36/SLOTS (build {D})`"),
])
def test_after_boot_check_confirms_the_pushed_set_was_mounted(log, problem):
    found = push.check_slots_mounted(Answers(f"ga36\n{D}\n{log}"), STATE)
    if problem is None:
        assert found is None
    else:
        assert found is not None and problem in found


def test_after_boot_check_skips_a_console_without_slots():
    text = "ga36\n-\nlume: root: ga36/SYSTEM (read-only) + 32 MiB RAM layer\n"
    assert push.check_slots_mounted(Answers(text), STATE) is None
    assert push.check_slots_mounted in push.AFTER_BOOT_CHECKS


def test_a_push_whose_console_fell_back_to_slots_old_fails(builds):
    first, _ = pushed_to_old_card(builds)
    c = rebooted(first)
    real = c.slots_mounted

    def fell_back():
        return real().replace("ga36/SLOTS (", "ga36/SLOTS.old (")
    c.slots_mounted = fell_back
    with pytest.raises(push.PushError, match=r"boot 44 completed with build .*, but: boot 44 "
                                             r"mounted ga36/SLOTS.old \(the previous set\)"):
        slot_push(c, C, wait=True)


# --- fragment versions after the boot (build-speed task 8.2) ---------------------------------

E = "20261117-130000"
SENT = {"lume-core": "1.0-r5", "lume-diag": "1.0-r2", "r36os-logd": "1.0-r1"}


def build_with_packages(tmp_path):
    """Build E archived with its objects; the GA36 lume slot carries the fragments SENT (and
    a package that is not a fragment)."""
    from r36os import manifests

    files = slot_boot(E)
    lume = b"ga36 lume E"
    ss = manifests.SlotSet(build=E, console="ga36", slots=tuple(
        manifests.Slot(name=n, sha256=sha(d), size=len(d),
                       packages=(*SENT.items(), ("busybox", "1.36-r0")) if n == "lume" else ())
        for n, d in {**contents("ga36"), "lume": lume}.items()))
    files["ga36/SLOTS"] = manifests.format_slots(ss).encode()
    for s in ss.slots:
        files[f"ga36/{s.file}"] = {**contents("ga36"), "lume": lume}[s.name]
    d = tmp_path / "out/images/console" / E
    d.mkdir(parents=True)
    order = [p for p in files if p != "VERSION"] + ["VERSION"]
    (d / "boot-files.sha256").write_text("".join(f"{sha(files[p])}  {p}\n" for p in order))
    for data in files.values():
        (tmp_path / "out/images/objects" / sha(data)).write_bytes(data)
    return files


def test_expected_fragments_come_from_the_slots_of_the_pushed_build(builds, tmp_path):
    files = build_with_packages(tmp_path)
    boot_list = [(p, sha(d)) for p, d in files.items()]
    # the manifest is read from the stored object, also when this push does not send it
    assert push.expected_fragments(boot_list, "ga36", {}) == SENT
    assert push.expected_fragments([(p, d) for p, d in boot_list if p != "ga36/SLOTS"],
                                   "ga36", {}) == {}
    assert push.expected_fragments(boot_list, "r36s", {}) == {}     # the r36s set has none


def test_fragment_mismatches_name_both_versions():
    assert push.fragment_mismatches(SENT, dict(SENT, extra="1")) == []
    got = push.fragment_mismatches(SENT, {**SENT, "lume-core": "1.0-r4"})
    assert got == ["the console runs lume-core 1.0-r4, the push sent 1.0-r5"]
    got = push.fragment_mismatches(SENT, {"lume-core": "1.0-r5"})
    assert got == ["the console has no lume-diag, the push sent 1.0-r2",
                   "the console has no r36os-logd, the push sent 1.0-r1"]


def test_push_confirms_the_fragments_installed_after_the_boot(builds, tmp_path):
    build_with_packages(tmp_path)
    first = FakeConsole(board="ga36", boot=OLD_CARD)
    rc, _ = slot_push(first, E)
    assert rc == 0
    c = rebooted(first)
    c.fragments = dict(SENT)
    rc, out = slot_push(c, E, wait=True)
    assert rc == 0 and out[-1].startswith("ok: boot 44 completed")
    assert c.log.count("fragment versions") == 1


def test_push_fails_when_the_console_runs_another_fragment_version(builds, tmp_path):
    build_with_packages(tmp_path)
    first = FakeConsole(board="ga36", boot=OLD_CARD)
    slot_push(first, E)
    c = rebooted(first)
    c.fragments = {**SENT, "lume-core": "1.0-r4"}
    with pytest.raises(push.PushError) as e:
        slot_push(c, E, wait=True)
    assert "but: the console runs lume-core 1.0-r4, the push sent 1.0-r5" in str(e.value)


def test_a_build_with_no_fragment_in_its_slots_asks_nothing(builds):
    first, _ = pushed_to_old_card(builds)
    c = rebooted(first)
    rc, _ = slot_push(c, C, wait=True)
    assert rc == 0 and "fragment versions" not in c.log
