"""Unit tests of r36os.dev: pure functions, no device."""

import pytest

from r36os import dev

GA36_DEVICES = """\
I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="GA36-MB Gamepad"
H: Handlers=event2 js0

I: Bus=0019 Vendor=0000 Product=0000 Version=0000
N: Name="1c22800.lradc"
H: Handlers=event0

I: Bus=0006 Vendor=1209 Product=3633 Version=0001
N: Name="GA36-MB Gamepad"
H: Handlers=event3 js1
"""

R36S_DEVICES = """\
I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="gpio-keys"
H: Handlers=kbd event1

I: Bus=0019 Vendor=0001 Product=0001 Version=0100
N: Name="adc-joystick"
H: Handlers=event2

I: Bus=0006 Vendor=1209 Product=3653 Version=0001
N: Name="R36S Gamepad"
H: Handlers=event4 js0
"""


VM_DEVICES = """\
I: Bus=0011 Vendor=0001 Product=0001 Version=ab41
N: Name="AT Translated Set 2 keyboard"
H: Handlers=sysrq kbd event1 leds

I: Bus=0006 Vendor=1209 Product=3600 Version=0001
N: Name="Lume VM Keyboard"
H: Handlers=sysrq kbd event3 leds
"""


def test_find_pads_vm():
    pads = dev.find_pads(dev.parse_input_devices(VM_DEVICES))
    assert pads == dev.Pads("vm", virtual=3, kernel=1)


def test_vm_buttons_are_the_keys_of_vm_conf():
    # vm.conf: `fn KEY_F1`, `quit KEY_ENTER` (Fn + Start); passthrough publishes the keys as is
    assert dev.VM_CODES["fn"] == 59 and dev.VM_CODES["start"] == 28
    assert dev.VM_CODES["select"] == 54          # right Shift (RetroArch hotkey of the vm)
    assert {"a", "b", "up", "down", "left", "right"} <= set(dev.VM_CODES)
    assert dev.VM_SOURCE_CODES == dev.VM_CODES


def test_build_script_vm_buttons_use_keyboard_codes():
    pads = dev.Pads("vm", 3, 1)
    script = dev.build_script(dev.parse_sequence("a,start"), pads, "x86_64")
    assert "> /dev/input/event3" in script
    assert "\\055\\000\\001\\000\\000\\000" in script    # KEY_X (45) = a
    assert "\\034\\000\\001\\000\\000\\000" in script    # KEY_ENTER (28) = start


def test_build_script_vm_fn_chord_goes_to_the_source_keyboard():
    pads = dev.Pads("vm", 3, 1)
    script = dev.build_script(dev.parse_sequence("fn+start"), pads, "x86_64")
    assert "> /dev/input/event1" in script and "event3" not in script
    assert "\\073\\000\\001\\000\\000\\000" in script    # KEY_F1 (59)
    assert "\\034\\000\\001\\000\\000\\000" in script    # KEY_ENTER (28)


def test_build_script_vm_has_no_trigger_buttons():
    with pytest.raises(dev.DevError, match="VM has no `l2` button"):
        dev.build_script(dev.parse_sequence("l2"), dev.Pads("vm", 3, 1), "x86_64")
    # the consoles keep every button
    dev.build_script(dev.parse_sequence("l2"), dev.Pads("ga36", 3, 2), "armv7l")


@pytest.mark.parametrize("probe,name", [
    ("vm\nx86_64\n", "vm"),
    ("-\nx86_64\n", "vm"),
    ("ga36\narmv7l\n", ""),
    ("-\naarch64\n", ""),
    ("", ""),
])
def test_vm_machine(probe, name):
    assert dev.vm_machine(probe) == (name == "vm")


def test_which_console_answers_vm(monkeypatch, capsys):
    monkeypatch.setattr(dev, "run_capture", lambda host, cmd: "-\nx86_64\n")
    assert dev.which_console("127.0.0.1:2222", None) == "vm"
    assert "console: VM" in capsys.readouterr().err
    with pytest.raises(dev.DevError, match="is the VM, not the GA36"):
        dev.which_console("127.0.0.1:2222", "ga36")


def test_which_console_vm_wanted_on_a_console(monkeypatch):
    monkeypatch.setattr(dev, "run_capture", lambda host, cmd: "r36s\naarch64\n")
    with pytest.raises(dev.DevError, match="is the R36S, not the VM"):
        dev.which_console("10.55.0.1", "vm")


def test_ssh_argv_uses_cable_options():
    argv = dev.ssh_argv("10.55.0.1", "true")
    assert argv[0] == "ssh"
    assert "UserKnownHostsFile=/dev/null" in argv
    assert argv[-2:] == ["root@10.55.0.1", "true"]


def test_ssh_argv_host_override_and_tty():
    argv = dev.ssh_argv("10.55.1.1", "ls", tty=True)
    assert "-tt" in argv
    assert argv[-2] == "root@10.55.1.1"


def test_find_pads_ga36():
    pads = dev.find_pads(dev.parse_input_devices(GA36_DEVICES))
    assert pads == dev.Pads("ga36", virtual=3, kernel=2)


def test_find_pads_r36s():
    pads = dev.find_pads(dev.parse_input_devices(R36S_DEVICES))
    assert pads == dev.Pads("r36s", virtual=4, kernel=1)


def test_find_pads_missing():
    with pytest.raises(dev.DevError):
        dev.find_pads(dev.parse_input_devices(GA36_DEVICES.split("\n\n")[0]))


def test_parse_sequence_repeat_chord_wait():
    steps = dev.parse_sequence("a, down*3,start+select,wait:500,fn+start")
    assert [s.buttons for s in steps] == [
        ("a",), ("down",), ("down",), ("down",), ("start", "select"), (), ("fn", "start")]
    assert steps[5].wait_ms == 500
    assert steps[4].pad == "virtual"
    assert steps[6].pad == "kernel"


def test_parse_sequence_prefix_and_alias():
    steps = dev.parse_sequence("k:a,v:mode")
    assert steps[0].pad == "kernel"
    assert steps[1] == dev.Step(("fn",), "virtual")


@pytest.mark.parametrize("bad", ["", "zz", "a*0", "a*x"])
def test_parse_sequence_errors(bad):
    with pytest.raises(dev.DevError):
        dev.parse_sequence(bad)


def test_input_event_sizes():
    assert len(dev.input_event(1, 0x130, 1, 8)) == 24
    assert len(dev.input_event(1, 0x130, 1, 4)) == 16
    assert dev.input_event(1, 0x130, 1, 4)[8:] == bytes([1, 0, 0x30, 1, 1, 0, 0, 0])


def test_build_script_virtual_press():
    pads = dev.Pads("ga36", 3, 2)
    script = dev.build_script(dev.parse_sequence("a"), pads, "armv7l")
    lines = script.splitlines()
    assert lines[0].startswith("printf '") and lines[0].endswith("> /dev/input/event3")
    assert "\\060\\001\\001\\000\\000\\000" in lines[0]   # EV_KEY 0x130 value 1
    assert lines[1] == "sleep 0.080"
    assert "\\060\\001\\000\\000\\000\\000" in lines[2]   # value 0
    assert lines[3] == "sleep 0.120"


def test_build_script_hotkey_goes_to_kernel_pad_r36s_codes():
    pads = dev.Pads("r36s", 4, 1)
    script = dev.build_script(dev.parse_sequence("fn+start"), pads, "aarch64")
    assert "> /dev/input/event1" in script
    assert "\\304\\002" in script    # BTN_TRIGGER_HAPPY5 (0x2c4)
    assert "\\301\\002" in script    # BTN_TRIGGER_HAPPY2 (0x2c1)


def test_build_script_wait_and_missing_kernel_pad():
    pads = dev.Pads("ga36", 3, None)
    assert dev.build_script(dev.parse_sequence("wait:1500"), pads, "armv7l") == "sleep 1.500\n"
    with pytest.raises(dev.DevError):
        dev.build_script(dev.parse_sequence("fn+start"), pads, "armv7l")


def test_wait_for_console_times_out_and_succeeds():
    t = [0.0]
    calls = []

    def sleep(s):
        t[0] += s

    assert not dev.wait_for_console("h", 5, 2, sleep=sleep, now=lambda: t[0],
                                    probe=lambda: calls.append(1) or False)
    assert len(calls) == 4
    assert dev.wait_for_console("h", 5, 2, sleep=sleep, now=lambda: t[0], probe=lambda: True)


def test_boot_log_command_reads_current_boot():
    cmd = dev.boot_log_command()
    assert "boot-n" in cmd and "boot/boot-$n.log" in cmd and "dmesg" in cmd
    # boot OK completed is only in events.log, so the events of this boot follow the log
    assert "/storage/logs/events.log" in cmd and "$2 == n" in cmd


def test_boot_log_command_runs_in_busybox_sh(tmp_path):
    import shutil
    import subprocess

    sh = shutil.which("sh")
    if sh is None:
        import pytest
        pytest.skip("no sh")
    # same command against a fake tree: the paths are rewritten under tmp_path
    run = tmp_path / "run/r36os/logs"
    (run / "boot").mkdir(parents=True)
    (run / "boot-n").write_text("7\n")
    (run / "boot/boot-7.log").write_text("== boot 7\n")
    logs = tmp_path / "storage/logs"
    logs.mkdir(parents=True)
    (logs / "events.log").write_text(
        "t1 6 boot OK completed: frontend in 30s from kernel\n"
        "t2 7 boot OK completed: frontend in 33s from kernel\n")
    cmd = (dev.boot_log_command().replace("/run/", f"{tmp_path}/run/")
           .replace("/storage/", f"{tmp_path}/storage/"))
    out = subprocess.run([sh, "-c", cmd], capture_output=True, text=True).stdout
    assert out.startswith("== boot 7\n")
    assert "frontend in 33s" in out and "frontend in 30s" not in out
