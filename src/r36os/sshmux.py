"""One OpenSSH master channel per console, shared by every `r36os` ssh call (virtual-gamepad 3.6).

`r36os dev`, `push` and the 1 s queries of `dev run` open one ssh connection per command, and
on the console each one costs a dropbear fork plus key exchange. With the OpenSSH multiplexing
of the PC (`ControlMaster=auto`) the first call opens a master connection that the next ones
reuse for 60 s after the last use; nothing new runs on the console.

Where it lives: `<repo>/cache/ssh/<sha1(host:port)[:12]>` (the socket) and `<same>.id` (the
identity of the channel: `<console> <boot-id>`). `R36OS_SSH_DIR` moves the folder.
`R36OS_SSH_MUX=0` turns it all off (the ssh argv is then exactly the one without mux).

Identity. Both consoles answer at the same address, every boot makes a new host key and the
client does not check host keys, so a master could silently serve the wrong console or the
previous boot. The identity (console name + /proc/sys/kernel/random/boot_id) is read through
the channel once per `r36os dev` command (`which_console`, one cheap round trip over the
already open channel) and compared with the stored one; on a mismatch the master is closed
(`ssh -O exit`) and the next call reconnects. It is also dropped, without a check, at the
points where the console restarts: after the reboot command of `push`, around the wait of
`push` and `dev wait`. Probes (`Remote.answers`) never use the channel.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from r36os.paths import REPO_ROOT

PERSIST = 60                     # seconds the master stays after the last use
SOCKET_LIMIT = 104               # sun_path limit; ssh appends a ~17 byte temporary suffix
SUFFIX_ROOM = 20
BOOT_ID_COMMAND = "cat /proc/sys/kernel/random/boot_id"
EXIT_TIMEOUT = 5


def enabled() -> bool:
    return os.environ.get("R36OS_SSH_MUX", "1").strip() != "0"


def mux_dir() -> Path:
    env = os.environ.get("R36OS_SSH_DIR")
    return Path(env) if env else REPO_ROOT / "cache" / "ssh"


def control_path(addr: str, port: int | None) -> Path | None:
    """Socket path for host:port, or None when the mux is off or the path would be too long."""
    if not enabled():
        return None
    key = hashlib.sha1(f"{addr}:{port or 22}".encode()).hexdigest()[:12]
    path = mux_dir() / key
    if len(str(path)) + SUFFIX_ROOM > SOCKET_LIMIT:
        return None
    return path


def options(addr: str, port: int | None) -> list[str]:
    """The `-o` arguments that put an ssh call on the channel ([] when there is none)."""
    path = control_path(addr, port)
    if path is None:
        return []
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError:
        return []
    return ["-o", "ControlMaster=auto", "-o", f"ControlPath={path}",
            "-o", f"ControlPersist={PERSIST}"]


def _id_file(path: Path) -> Path:
    return path.with_name(path.name + ".id")


def drop(base: list[str], run=subprocess.run) -> None:
    """Close the master of the connection `base` (the Remote.base argv) and forget its
    identity. Never raises: no master is the normal case."""
    cp = next((a.split("=", 1)[1] for a in base if a.startswith("ControlPath=")), None)
    if cp is None:
        return
    argv = [*base[:-1], "-O", "exit", base[-1]]
    try:
        run(argv, stdin=subprocess.DEVNULL, capture_output=True, timeout=EXIT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        _id_file(Path(cp)).unlink()
    except OSError:
        pass


def read_identity(base: list[str]) -> str | None:
    cp = next((a.split("=", 1)[1] for a in base if a.startswith("ControlPath=")), None)
    if cp is None:
        return None
    try:
        return _id_file(Path(cp)).read_text().strip() or None
    except OSError:
        return None


def revalidate(base: list[str], console: str, boot_id: str, drop_fn=None) -> bool:
    """Compare `<console> <boot-id>` just read through the channel with the stored identity.
    Returns True when the channel was kept; on a mismatch the master is closed (the next ssh
    call reconnects) and the new identity is stored. No-op without a channel in `base`."""
    cp = next((a.split("=", 1)[1] for a in base if a.startswith("ControlPath=")), None)
    if cp is None:
        return True
    identity = f"{console} {boot_id.strip()}"
    stored = read_identity(base)
    kept = stored is None or stored == identity
    if not kept:
        (drop_fn or drop)(base)
    try:
        _id_file(Path(cp)).write_text(identity + "\n")
    except OSError:
        pass
    return kept
