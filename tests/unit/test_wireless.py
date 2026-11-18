"""usb-device-access tasks 8.2 and 8.3 (P-15): Wi-Fi and Bluetooth by USB dongle. What can
be checked without a dongle: packages, NetworkManager and D-Bus configuration, services and
the RetroArch drivers. The dongle itself is proven on the consoles (task 8.4)."""

import configparser
import re

from r36os.paths import REPO_ROOT

NET = REPO_ROOT / "aports/lume-net/files"
CFG = REPO_ROOT / "aports/lume-retroarch-cfg/files"
PACKAGES = (REPO_ROOT / "rootfs/packages.txt").read_text().split()
CONFIGURE = (REPO_ROOT / "rootfs/configure.sh").read_text()
LUME_CFG = (CFG / "usr/share/lume/retroarch-lume.cfg").read_text()


FIRMWARE = ("linux-firmware-rtw88", "linux-firmware-rtlwifi", "linux-firmware-ath9k_htc",
            "linux-firmware-rtl_bt")


def test_packages_for_wifi_bluetooth_and_their_firmware():
    for name in ("dbus", "dbus-openrc", "networkmanager", "networkmanager-openrc",
                 "networkmanager-wifi", "networkmanager-cli", "wpa_supplicant", "bluez",
                 "bluez-openrc"):
        assert name in PACKAGES, name
    # the dongle firmware is hardware: both consoles list it, the vm (no dongle) does not
    for board in ("ga36", "r36s"):
        hw = (REPO_ROOT / f"board/{board}/hw-packages.txt").read_text().split()
        for name in FIRMWARE:
            assert name in hw, (board, name)
        # no 28 MiB MediaTek firmware, no catch-all firmware
        assert not {"linux-firmware-mediatek", "linux-firmware-other", "linux-firmware"} & set(hw)
    assert not (REPO_ROOT / "board/vm/hw-packages.txt").exists() or not \
        set(FIRMWARE) & set((REPO_ROOT / "board/vm/hw-packages.txt").read_text().split())


def test_networkmanager_only_manages_wifi_and_needs_no_polkit():
    conf = configparser.ConfigParser()
    conf.read_string((NET / "etc/NetworkManager/conf.d/lume.conf").read_text())
    assert conf["main"]["auth-polkit"] == "false"          # RetroArch runs as "game"
    # the USB cable network (usb0) and the vm network stay out of NetworkManager's hands
    assert conf["keyfile"]["unmanaged-devices"] == "*,except:type:wifi"
    assert conf["connectivity"]["enabled"] == "false"       # no probe to an outside server


def test_bluez_answers_the_frontend_user():
    policy = (NET / "etc/dbus-1/system.d/lume-bluetooth.conf").read_text()
    assert '<policy user="game">' in policy
    assert '<allow send_destination="org.bluez"/>' in policy


def test_services_start_without_holding_the_frontend():
    # in the list of services after the frontend (build-speed D20, tests/unit/test_boot_order.py)
    line = re.search(r'^for s in lume-playlists .*?; do', CONFIGURE, re.S | re.M).group(0)
    for service in ("dbus", "networkmanager"):
        assert re.search(rf"\b{service}\b", line), service
    # bluetooth on the consoles only: the vm kernel (linux-virt) has no Bluetooth, and
    # bluetoothd crashed there (test-vm, 2026-11-13)
    assert not re.search(r"\bbluetooth\b", line)
    early = re.search(r'^for s in seatd .*?; do', CONFIGURE, re.S | re.M).group(0)
    assert not re.search(r"\b(dbus|networkmanager|bluetooth)\b", early)
    assert re.search(r"^ga36\|r36s\) add bluetooth default ;;$", CONFIGURE, re.M)
    deps = (REPO_ROOT / "aports/lume-core/files/etc/init.d/frontend").read_text()
    assert not re.search(r"\b(net|networkmanager|bluetooth|dbus)\b",
                         re.search(r"depend\(\) \{(.*?)\n\}", deps, re.S).group(1))
    # wpa_supplicant is started by NetworkManager through D-Bus, never as a service
    assert "wpa_supplicant" not in line


def test_retroarch_drivers_for_the_menus():
    assert re.search(r'^wifi_driver = "nmcli"$', LUME_CFG, re.M)
    assert re.search(r'^bluetooth_driver = "bluetoothctl"$', LUME_CFG, re.M)
    assert re.search(r'^network_cmd_enable = "true"$', LUME_CFG, re.M)   # logd, on 127.0.0.1
