"""Capturas do menu do RetroArch na VM (calibração de legibilidade a 640x480).

    uv run python tests/vm/capture_menu.py [saída]

Sobe a vm sem tela e sem virgl (o RetroArch desenha o mesmo XMB por software e o QMP
screendump funciona em qualquer GPU), cria jogos vazios para o menu ter sistemas,
reinicia o frontend e navega pelo teclado (QMP send-key), salvando uma captura por tela.
"""

import shutil
import subprocess
import sys
import time
from pathlib import Path

from r36os.paths import REPO_ROOT
from r36os.qmp import QMP
from r36os.vm import VmConfig, podman_argv, prepare_disk, run_dir

OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO_ROOT / "out/vm/capturas"
OUT.mkdir(parents=True, exist_ok=True)
d = run_dir()
disk = prepare_disk(d / "capture.img")
log, sock = d / "capture-serial.log", d / "capture.sock"
for p in (log, sock):
    p.unlink(missing_ok=True)
cfg = VmConfig(disk=disk, headless=True, qmp=sock, serial_log=log, gl=False)
p = subprocess.Popen([a for a in podman_argv(cfg) if a != "-t"], stdin=subprocess.PIPE,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, text=True)
q = QMP(sock)
t0 = time.monotonic()
while time.monotonic() - t0 < 90 and "login:" not in (log.read_text(errors="replace") if log.exists() else ""):
    time.sleep(0.5)


def serial(cmd: str, wait: float = 2) -> None:
    p.stdin.write(cmd + "\n")
    p.stdin.flush()
    time.sleep(wait)


serial("root")
games = {"nes": "Aventura.nes", "snes": "Corrida.sfc", "megadrive": "Plataforma.md",
         "gba": "Puzzle.gba", "psx": "Disco.cue", "arcade": "gridlee.zip"}
for sysid, name in games.items():
    serial(f"touch '/storage/roms/{sysid}/{name}'", 0.2)
serial("r36os-playlists >/dev/null; chown -R game:game /home/game/.config/retroarch")
serial("rc-service frontend restart", 12)

shots = []


def shot(name: str) -> None:
    time.sleep(1.5)
    q.screendump(f"/vm/{name}.png")
    shots.append(name)


def key(*k: str, n: int = 1, pause: float = 0.6) -> None:
    for _ in range(n):
        q.send_keys(*k)
        time.sleep(pause)


shot("01-menu-principal")
key("right")
shot("02-configuracoes")
key("right")
shot("03-favoritos")
key("right")
shot("04-historico")
key("right")
shot("05-sistema-arcade")  # abas dos sistemas em ordem alfabética
key("right", n=5)
shot("06-sistema-super-nintendo")
key("down")
shot("07-sistema-super-nintendo-jogo")
key("left", n=9)
key("right")
key("down", n=6)
shot("08-configuracoes-fim")
q.cmd("quit")
p.wait(timeout=30)
disk.unlink(missing_ok=True)
for s in shots:
    shutil.move(d / f"{s}.png", OUT / f"{s}.png")
print("\n".join(str(OUT / f"{s}.png") for s in shots))
