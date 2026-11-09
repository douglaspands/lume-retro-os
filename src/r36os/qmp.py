"""Cliente QMP mínimo (socket unix) para controlar a VM nos testes."""

from __future__ import annotations

import base64
import json
import socket
import time
from pathlib import Path


class QMP:
    def __init__(self, path: Path, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while True:
            try:
                self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                self.sock.connect(str(path))
                break
            except (FileNotFoundError, ConnectionRefusedError):
                self.sock.close()
                if time.monotonic() > deadline:
                    raise
                time.sleep(0.2)
        self.sock.settimeout(timeout)
        self.file = self.sock.makefile("rw")
        self._recv()  # greeting
        self.cmd("qmp_capabilities")

    def _recv(self) -> dict:
        while True:
            line = self.file.readline()
            if not line:
                raise ConnectionError("QMP fechado")
            msg = json.loads(line)
            if "event" not in msg:
                return msg

    def cmd(self, name: str, **args) -> dict:
        req = {"execute": name}
        if args:
            req["arguments"] = args
        self.file.write(json.dumps(req) + "\n")
        self.file.flush()
        resp = self._recv()
        if "error" in resp:
            raise RuntimeError(f"QMP {name}: {resp['error']}")
        return resp.get("return", {})

    def send_keys(self, *keys: str, hold_ms: int = 200) -> None:
        """Pressiona as teclas juntas (nomes qcode: 'x', 'ret', 'up', 'shift'...)."""
        self.cmd("send-key", keys=[{"type": "qcode", "data": k} for k in keys],
                 **{"hold-time": hold_ms})

    def screendump(self, guest_path: str) -> None:
        self.cmd("screendump", filename=guest_path, format="png")

    def hmp(self, line: str) -> str:
        return self.cmd("human-monitor-command", **{"command-line": line})

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def b64(s: str) -> str:
    return base64.b64encode(s.encode()).decode()
