"""Teste de host do protocolo do controle do GA36 (tarefa 9.2), compilado no container de cross.

O ga36mb-gamepad-proto.h é extraído da kernel/patches/0006 (a mesma fonte do kernel) e
compilado com tests/kernel/gamepad_proto_test.c.
"""

import shutil
import subprocess

import pytest

from r36os import kpatch
from r36os.container import Container, ensure_cross
from r36os.paths import REPO_ROOT

pytestmark = pytest.mark.skipif(shutil.which("podman") is None, reason="sem podman")


def test_gamepad_protocol(tmp_path):
    proto = kpatch.new_file(kpatch.find("0006-"), "drivers/input/joystick/ga36mb-gamepad-proto.h")
    (tmp_path / "ga36mb-gamepad-proto.h").write_text(proto)
    shutil.copy(REPO_ROOT / "tests/kernel/gamepad_proto_test.c", tmp_path)
    cmd = Container(image=ensure_cross(), volumes={tmp_path: "/t"}, workdir="/t").argv(
        "gcc -std=c99 -Wall -Wextra -Werror -o /tmp/proto gamepad_proto_test.c && /tmp/proto")
    r = subprocess.run(cmd, capture_output=True, text=True)
    print(r.stdout, r.stderr)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stdout + r.stderr
