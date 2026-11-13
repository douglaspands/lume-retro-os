"""Root over the USB cable (usb-device-access D4): the keys that `r36os flash --ssh-key`
puts in BOOT/ssh/.

- `authorized_keys`: the public keys the console's SSH server accepts (no password login);
- `ssh_host_ed25519_key` (+ `.pub`): the console's host key, generated once on this PC in
  ~/.config/r36os/, so every card written here has the same host key and the PC never
  warns when the card or the console changes. The console converts it to the dropbear
  format in RAM at every boot (dropbearconvert); nothing is written to the card there.
- ~/.config/r36os/known_hosts: that host key for 10.55.0.1, used by `r36os push`
  (UserKnownHostsFile), so the user's own known_hosts is never touched.

The files go into a copy of the BOOT region before it is written (`boot_with_ssh`), so
they are part of the big verified write of `flash` and never a small write of their own
(the USB reader 14cd:125d corrupts small writes).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

from r36os.paths import cache_dir, ensure_dir

CONSOLE_ADDR = "10.55.0.1"   # the console on the USB network (D5)
SSH_DIR = "ssh"               # BOOT/ssh/
AUTHORIZED = "authorized_keys"
HOST_KEY = "ssh_host_ed25519_key"
CHUNK = 1 << 22
_PUBLIC = re.compile(r"^(ssh-(ed25519|rsa|dss)|ecdsa-sha2-nistp\d+|sk-[\w.@-]+) [A-Za-z0-9+/]+=* ?.*$")


class SshKeyError(RuntimeError):
    pass


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "r36os"


def host_key_path() -> Path:
    return config_dir() / "ssh_host_ed25519"


def known_hosts_path() -> Path:
    return config_dir() / "known_hosts"


def read_public_key(path: Path) -> str:
    """The one public key line of `path`; a private key (or anything else) is refused."""
    try:
        text = Path(path).read_text().strip()
    except (OSError, UnicodeDecodeError) as e:
        raise SshKeyError(f"cannot read the public key {path}: {e}") from None
    if "PRIVATE KEY" in text:
        raise SshKeyError(f"{path} is a PRIVATE key: pass the public one (usually {path}.pub); "
                          "the private key never leaves this PC")
    lines = [line for line in text.splitlines() if line.strip()]
    if len(lines) != 1 or not _PUBLIC.match(lines[0]):
        raise SshKeyError(f"{path} is not one OpenSSH public key line (ssh-ed25519 AAAA...)")
    return lines[0].strip()


def ensure_host_key() -> tuple[Path, str]:
    """The console host key of this PC (created on first use) and its public line; also
    keeps ~/.config/r36os/known_hosts pointing 10.55.0.1 at it."""
    key = host_key_path()
    if not key.exists():
        ensure_dir(key.parent)
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "lume-console",
                        "-f", str(key)], check=True)
    pub = read_public_key(key.with_name(key.name + ".pub"))
    known = known_hosts_path()
    line = f"{CONSOLE_ADDR} {' '.join(pub.split()[:2])}\n"
    if not known.exists() or known.read_text() != line:
        known.write_text(line)
    return key, pub


def merge_authorized(existing: str | None, key: str | None) -> str:
    """authorized_keys with the lines already on the card and the new key, once."""
    lines = [line.strip() for line in (existing or "").splitlines() if line.strip()]
    if key:
        blob = key.split()[1]
        if not any(len(line.split()) > 1 and line.split()[1] == blob for line in lines):
            lines.append(key)
    return "".join(f"{line}\n" for line in lines)


def boot_ssh_files(pub_key_file: Path | None, existing: dict[str, bytes]) -> dict[str, bytes]:
    """Files of BOOT/ssh/: the existing ones of the card (kept by --update) with the new
    key added and the host key of this PC. Empty when there is nothing to write."""
    if pub_key_file is None and not existing:
        return {}
    files = dict(existing)
    key = read_public_key(pub_key_file) if pub_key_file is not None else None
    if key is not None or AUTHORIZED in files:
        old = files.get(AUTHORIZED, b"").decode(errors="replace")
        files[AUTHORIZED] = merge_authorized(old, key).encode()
    if key is not None:
        host, _ = ensure_host_key()
        files[HOST_KEY] = host.read_bytes()
        files[HOST_KEY + ".pub"] = host.with_name(host.name + ".pub").read_bytes()
    return files


def _sparse_copy(src: Path, dst: Path, offset: int, length: int, size: int) -> None:
    """dst: a file of `size` bytes with only [offset, offset + length) of src, zero ranges
    left as holes (the BOOT partition is mostly free space)."""
    with src.open("rb") as fin, dst.open("wb") as fout:
        fout.truncate(size)
        fin.seek(offset)
        fout.seek(offset)
        left = length
        while left:
            chunk = fin.read(min(CHUNK, left))
            if not chunk:
                break
            if chunk.count(0) == len(chunk):
                fout.seek(len(chunk), os.SEEK_CUR)
            else:
                fout.write(chunk)
            left -= len(chunk)


def boot_with_ssh(img: Path, boot_offset: int, boot_length: int,
                  files: dict[str, bytes], runner=None) -> Path:
    """A copy of `img` (same size, sparse) holding only the BOOT region, with BOOT/ssh/
    written into its FAT by mtools in the builder container."""
    work = ensure_dir(cache_dir() / "flash-ssh")
    for old in work.iterdir():
        if old.is_dir():
            shutil.rmtree(old)
        else:
            old.unlink()
    out = work / "boot.img"
    _sparse_copy(img, out, boot_offset, boot_length, img.stat().st_size)
    src = ensure_dir(work / "ssh")
    for name, data in files.items():
        (src / name).write_bytes(data)
    names = " ".join(sorted(files))
    script = (f"export MTOOLS_SKIP_CHECK=1; I=/w/boot.img@@{boot_offset}; "
              f"mmd -i $I ::{SSH_DIR} 2>/dev/null || true; "
              f"for f in {names}; do mcopy -o -i $I /w/ssh/$f ::{SSH_DIR}/$f; done; "
              f"mdir -b -i $I ::{SSH_DIR}")
    (runner or _run_in_builder)(work, script)
    return out


def _run_in_builder(work: Path, script: str) -> None:
    from r36os.container import Container, ensure_builder
    from r36os.targets import TARGETS

    cmd = Container(image=ensure_builder(TARGETS["vm"]), volumes={work: "/w"}).argv(script)
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SshKeyError(f"could not write BOOT/{SSH_DIR}/ into the image: "
                          f"{(r.stdout + r.stderr).strip()}")


def read_card_ssh(boot_mount: Path) -> dict[str, bytes]:
    """BOOT/ssh/ of a mounted card (kept by --update, which rewrites BOOT whole)."""
    d = boot_mount / SSH_DIR
    if not d.is_dir():
        return {}
    return {p.name: p.read_bytes() for p in sorted(d.iterdir()) if p.is_file()}
