"""Depuração: sobe a imagem vm sem tela, entra como root na serial e roda comandos.

    uv run python tests/vm/console.py 'comando 1' 'comando 2' ...

Imprime a saída da serial a partir do login. Não altera out/vm/vm.img (usa uma cópia).
"""

import subprocess
import sys
import time

from r36os.qmp import QMP
from r36os.vm import VmConfig, podman_argv, prepare_disk, run_dir

d = run_dir()
disk = prepare_disk(d / "console.img")
log = d / "console-serial.log"
sock = d / "console.sock"
for p in (log, sock):
    p.unlink(missing_ok=True)
cfg = VmConfig(disk=disk, headless=True, qmp=sock, serial_log=log)
argv = [a for a in podman_argv(cfg) if a != "-t"]
p = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, text=True)
q = QMP(sock)
t0 = time.monotonic()
while time.monotonic() - t0 < 90 and "login:" not in (log.read_text(errors="replace") if log.exists() else ""):
    time.sleep(0.5)
time.sleep(8)  # serviços do runlevel default
for line in ["root", *sys.argv[1:]]:
    p.stdin.write(line + "\n")
    p.stdin.flush()
    time.sleep(3)
time.sleep(float(__import__("os").environ.get("CONSOLE_TAIL", "2")))
q.cmd("quit")
p.wait(timeout=30)
print(log.read_text(errors="replace").split("login:", 1)[-1])
disk.unlink(missing_ok=True)
