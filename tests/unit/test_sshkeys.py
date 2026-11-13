"""usb-device-access task 4.3: `r36os flash --ssh-key` puts the user's public key and the
console host key of this PC into BOOT/ssh/, refuses a private key and keeps the keys of
the card on --update. The files go into the BOOT region before the verified write."""

import shutil

import pytest

from r36os import cli, flash, sshkeys
from r36os.targets import IMAGES

PUB = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGq6UjS0V3UlTBzxXo1gXp0wF2u0wGfbqFq3c9Hm8b1N user@pc"
OTHER = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIOtherKeyOtherKeyOtherKeyOtherKeyOtherKey1 other@pc"
needs_keygen = pytest.mark.skipif(shutil.which("ssh-keygen") is None, reason="no ssh-keygen")


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "cache"))
    return tmp_path / "config" / "r36os"


def _write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text)
    return p


def test_public_key_is_accepted(tmp_path):
    assert sshkeys.read_public_key(_write(tmp_path, "id.pub", PUB + "\n")) == PUB


def test_private_key_is_refused(tmp_path):
    key = _write(tmp_path, "id_ed25519", "-----BEGIN OPENSSH PRIVATE KEY-----\nb3Blbn\n"
                 "-----END OPENSSH PRIVATE KEY-----\n")
    with pytest.raises(sshkeys.SshKeyError, match="PRIVATE key"):
        sshkeys.read_public_key(key)


@pytest.mark.parametrize("text", ["", "not a key", PUB + "\n" + OTHER])
def test_anything_but_one_public_key_line_is_refused(tmp_path, text):
    with pytest.raises(sshkeys.SshKeyError):
        sshkeys.read_public_key(_write(tmp_path, "k.pub", text))


def test_authorized_keys_keep_the_card_lines_and_add_the_key_once():
    merged = sshkeys.merge_authorized(OTHER + "\n", PUB)
    assert merged == f"{OTHER}\n{PUB}\n"
    # the same key again (another comment) is not repeated
    assert sshkeys.merge_authorized(merged, PUB.replace("user@pc", "x")) == merged


def test_nothing_to_write_without_a_key_or_keys_on_the_card(config):
    assert sshkeys.boot_ssh_files(None, {}) == {}


@needs_keygen
def test_with_a_key_boot_ssh_has_it_and_the_host_key(config, tmp_path):
    files = sshkeys.boot_ssh_files(_write(tmp_path, "id.pub", PUB), {})
    assert files["authorized_keys"] == f"{PUB}\n".encode()
    assert b"PRIVATE KEY" in files["ssh_host_ed25519_key"]
    assert files["ssh_host_ed25519_key.pub"].startswith(b"ssh-ed25519 ")
    pub = files["ssh_host_ed25519_key.pub"].decode().split()
    assert (config / "known_hosts").read_text() == f"10.55.0.1 {pub[0]} {pub[1]}\n"


@needs_keygen
def test_two_cards_get_the_same_host_key(config, tmp_path):
    key = _write(tmp_path, "id.pub", PUB)
    first = sshkeys.boot_ssh_files(key, {})
    second = sshkeys.boot_ssh_files(key, {})
    assert first["ssh_host_ed25519_key"] == second["ssh_host_ed25519_key"]


def test_update_without_the_option_keeps_the_card_files(config):
    existing = {"authorized_keys": f"{OTHER}\n".encode(), "ssh_host_ed25519_key": b"HOST",
                "ssh_host_ed25519_key.pub": b"ssh-ed25519 AAAA host"}
    assert sshkeys.boot_ssh_files(None, existing) == existing
    assert not (config / "ssh_host_ed25519").exists()     # no key generated for that


def test_boot_copy_has_only_the_boot_region_and_runs_mtools_on_it(config, tmp_path):
    img = tmp_path / "console.img"
    data = bytes(range(256)) * 4096                        # 1 MiB, no zero chunk
    img.write_bytes(data * 4)
    seen = {}

    def runner(work, script):
        seen["script"] = script
        seen["files"] = sorted(p.name for p in (work / "ssh").iterdir())

    out = sshkeys.boot_with_ssh(img, 1 << 20, 2 << 20, {"authorized_keys": b"k\n"}, runner)
    copy = out.read_bytes()
    assert len(copy) == len(data) * 4
    assert copy[1 << 20:3 << 20] == data * 2                 # the BOOT region
    assert copy[:1 << 20] == bytes(1 << 20) and copy[3 << 20:] == bytes(1 << 20)
    assert "/w/boot.img@@1048576" in seen["script"]
    assert "mcopy -o -i $I /w/ssh/$f ::ssh/$f" in seen["script"]
    assert seen["files"] == ["authorized_keys"]


@pytest.mark.parametrize("update", [False, True])
def test_write_plan_takes_boot_from_the_copy(tmp_path, update):
    target = IMAGES["console"]
    b_off = flash.boot_start(target) * flash.SECTOR
    b_len = flash.boot_sectors(target) * flash.SECTOR
    img = tmp_path / "console.img"
    with img.open("wb") as f:
        f.truncate(b_off + b_len + (1 << 20))
    boot = tmp_path / "boot.img"
    plan = flash.write_plan(img, target, update, boot)
    assert (boot, b_off, b_len) in plan
    assert all(src == img for src, off, _ in plan if off != b_off)
    # the same bytes as without the copy, in order and without gaps
    pieces = [(off, length) for _, off, length in plan]
    start = flash.BOOTLOADER_START if update else 0
    assert pieces[0][0] == start
    assert all(a[0] + a[1] == b[0] for a, b in zip(pieces, pieces[1:]))
    without = flash.write_plan(img, target, update)
    assert sum(length for _, _, length in plan) == sum(length for _, _, length in without)


def test_write_plan_without_ssh_is_the_image():
    target = IMAGES["console"]
    img = flash.Path("/x/console.img")
    assert flash.write_plan(img, target, True) == [(img, off, length) for off, length
                                                    in flash.update_regions(target)]


def test_cli_has_the_ssh_key_option():
    args = cli._parser().parse_args(["flash", "console", "/dev/sdc", "--update",
                                          "--ssh-key", "/home/u/.ssh/id_ed25519.pub"])
    assert str(args.ssh_key) == "/home/u/.ssh/id_ed25519.pub" and args.update
