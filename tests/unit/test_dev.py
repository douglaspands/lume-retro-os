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
