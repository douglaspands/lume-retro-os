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


class FakeConsole:
    def __init__(self, board="ga36", battery=80, roms_free=8 << 30, boot_free=1 << 30,
                 boot=None, sector=b"old panel image", corrupt=None):
        self.board, self.battery = board, battery
        self.roms_free, self.boot_free = roms_free, boot_free
        self.boot = dict(boot if boot is not None else
                         {"boot.ini": b"ini", "ga36/SYSTEM": b"old", "ga36/zImage": b"old z",
                          "r36s/SYSTEM": b"old r", "VERSION": b"build: old\n"})
        self.sector = sector
        self.staging = {}
        self.corrupt = corrupt          # a staged file that arrives damaged
        self.log = []                   # steps, in order

    def run(self, cmd, stdin=None):
        if cmd == push._PROBE:
            self.log.append("probe")
            sums = "".join(f"{sha(d)}  {p}\n" for p, d in self.boot.items())
            return (f"old\n{self.board}\n{'-' if self.battery is None else self.battery}\n"
                    f"{self.roms_free // 1024}\n{self.boot_free // 1024}\n/dev/mmcblk0\n{sums}")
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
                         r"&& sync && mv", cmd):
            self.boot[m.group(1)] = self.staging[m.group(1)]
            self.log.append(f"swap {m.group(1)}")
            return ""
        if m := re.match(r"dd if=\S+/(ga36-android-boot-panel1\.img) of=/dev/mmcblk0 bs=512 "
                         r"seek=172032", cmd):
            self.sector = self.staging[m.group(1)]
            self.log.append("write sector")
            return ""
        if cmd == "sync; mount -o remount,ro /boot":
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


def run_push(tmp_path, console, **kw):
    lines = []
    rc = push.push("latest", console, yes=True, extractor=extractor(tmp_path),
                   out=lines.append, **kw)
    return rc, lines


def test_push_sends_checks_swaps_and_reboots_in_order(build, tmp_path):
    c = FakeConsole()
    rc, out = run_push(tmp_path, c)
    assert rc == 0
    assert c.boot == {**NEW}
    steps = c.log
    # sent and checked on the console before BOOT is touched
    assert steps.index("check") < steps.index("boot rw")
    assert max(i for i, s in enumerate(steps) if s.startswith("send")) < steps.index("check")
    swaps = [s for s in steps if s.startswith("swap")]
    assert swaps[-1] == "swap VERSION"                      # VERSION last
    assert steps[-3:] == ["boot ro", "cleanup", "reboot"]
    assert steps.index("boot ro") > steps.index("swap VERSION")


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


def test_without_the_key_of_flash_it_refuses(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "empty"))
    with pytest.raises(push.PushError, match="--ssh-key"):
        push.Remote()


def test_a_build_without_the_boot_list_is_refused(build, tmp_path):
    (build / "boot-files.sha256").unlink()
    with pytest.raises(push.PushError, match="rebuild it"):
        run_push(tmp_path, FakeConsole())


def test_cli_push():
    args = cli._parser().parse_args(["push", "--build", BUILD, "--yes"])
    assert (args.command, args.build, args.yes, args.identity) == ("push", BUILD, True, None)
