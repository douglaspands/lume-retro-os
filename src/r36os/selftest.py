"""`r36os test-vm`: teste de aceitação da imagem vm (D12).

Sobe a VM sem tela com r36os.selftest=1 e o disco TESTDATA, segue a serial, atende os
pedidos do self-test do convidado (reset abrupto, teclas via QMP) e confere o
desligamento ao sair. Guarda o log serial completo em out/vm/test-vm/.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from r36os import catalog, testdata
from r36os.container import Container, ensure_builder
from r36os.paths import ensure_dir
from r36os.qmp import QMP
from r36os.rootfs import target_out
from r36os.targets import TARGETS
from r36os.vm import VmConfig, podman_argv, prepare_disk, run_dir

TIMEOUT_S = 1200
_MARK = re.compile(r"SELFTEST (\S+) (PASS|FAIL)(?: (.*))?$")
_REQ = re.compile(r"SELFTEST REQUEST (\S+)")
_TS = re.compile(r"^\[\s*(\d+\.\d+)\]")

KEYS = {
    "keys-menu": ("shift_r", "s"),        # Select + X
    "keys-quit-combo": ("shift_r", "ret"),  # Select + Start
    "keys-esc": ("esc",),
}


def expected_checks() -> list[str]:
    base = [
        "roms-created", "roms-first-boot-msg", "roms-folders", "roms-owner", "boot-readonly",
        "root-overlay", "hwsummary", "hwsummary-battery-absent", "frontend-up",
        "frontend-not-root", "frontend-gles", "frontend-kms", "bootlog-written",
        "bootlog-boot-ro-again", "frontend-stop-no-poweroff", "playlists",
        "persist-sync", "state-saved", "state-synced",
        "var-tmp-gone", "persist-after-reboot", "roms-preserved", "roms-checked-at-boot",
        "state-survived-reset", "game-running-before-menu", "hotkey-menu-opens",
        "menu-closes-resumes", "select-start-no-quit", "esc-no-quit",
        "frontend-fail-loop-stops", "frontend-fail-log", "frontend-fail-no-restart",
        "frontend-swap", "factory-reset", "factory-keeps-games", "timezone", "hostname",
        "bootlog-rotation", "bootlog-newest", "poweroff-on-quit",
    ]
    cores = [f"core-loaded-{c}" for c in sorted(testdata.core_tests(catalog.load()))]
    return base + cores


class SerialFollower:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.pos = 0
        self.partial = ""

    def lines(self) -> list[str]:
        if not self.path.exists():
            return []
        with self.path.open("rb") as f:
            f.seek(self.pos)
            data = f.read()
        self.pos += len(data)
        text = self.partial + data.decode(errors="replace").replace("\r", "")
        *done, self.partial = text.split("\n")
        return done


def _copy_results(td: Path, dest: Path) -> None:
    Container(image=ensure_builder(TARGETS["vm"]), volumes={td.parent: "/vm", dest: "/out"}).sh(
        f"MTOOLS_SKIP_CHECK=1 mcopy -s -n -i /vm/{td.name} ::results.txt ::results /out/ 2>/dev/null || true",
        check=False,
    )


def test_vm(keep: bool = False) -> int:
    out = target_out(TARGETS["vm"]) / "test-vm"
    shutil.rmtree(out, ignore_errors=True)
    ensure_dir(out)
    d = run_dir()
    disk = prepare_disk(d / "test.img", append="r36os.selftest=1")
    td = testdata.build_testdata(d / "testdata.img")
    serial = d / "test-serial.log"
    sock = d / "test.sock"
    for p in (serial, sock):
        p.unlink(missing_ok=True)
    cfg = VmConfig(disk=disk, headless=True, extra_disks=[td], qmp=sock, serial_log=serial)
    argv = [a for a in podman_argv(cfg) if a != "-t"]

    t0 = time.monotonic()
    proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.PIPE, text=True)
    results: dict[str, tuple[str, str]] = {}
    frontend_kernel_s: list[float] = []
    frontend_wall_s: list[float] = []
    all_done = expect_poweroff = quit_seen = False
    follower = SerialFollower(serial)
    qmp = None
    try:
        qmp = QMP(sock)
        while proc.poll() is None and time.monotonic() - t0 < TIMEOUT_S:
            for line in follower.lines():
                if m := _MARK.search(line):
                    name, res, detail = m.group(1), m.group(2), (m.group(3) or "").strip()
                    results[name] = (res, detail)
                    print(f"  {res}  {name}" + (f"  ({detail})" if detail and res == "FAIL" else ""),
                          flush=True)
                elif m := _REQ.search(line):
                    req = m.group(1)
                    if req == "reset-in-5":
                        time.sleep(5)
                        qmp.cmd("system_reset")
                    elif req == "reset":
                        time.sleep(1)
                        qmp.cmd("system_reset")
                    elif req in KEYS:
                        time.sleep(0.5)
                        qmp.send_keys(*KEYS[req])
                    elif req == "expect-poweroff":
                        expect_poweroff = True
                elif "SELFTEST PHASE" in line:
                    print(f"- fase {line.split('SELFTEST PHASE', 1)[1].strip()}", flush=True)
                elif "SELFTEST ALL-CHECKS-DONE" in line:
                    all_done = True
                elif "lume: frontend iniciado" in line:
                    frontend_wall_s.append(time.monotonic() - t0)
                    if ts := _TS.search(line):
                        frontend_kernel_s.append(float(ts.group(1)))
                elif "frontend encerrado pelo usuário" in line:
                    quit_seen = True
            time.sleep(0.2)
    finally:
        if qmp:
            qmp.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=30)

    powered_off = proc.returncode == 0 and expect_poweroff and quit_seen
    results["poweroff-on-quit"] = ("PASS" if powered_off else "FAIL",
                                   f"rc={proc.returncode} quit={quit_seen}")
    if not all_done:
        results.setdefault("all-checks-done", ("FAIL", "o self-test não chegou ao fim"))
    for name in expected_checks():
        results.setdefault(name, ("FAIL", "não executada"))

    shutil.copy(serial, out / "serial.log")
    _copy_results(td, out)
    failed = {k: v for k, v in results.items() if v[0] != "PASS"}
    elapsed = time.monotonic() - t0
    print()
    print(f"test-vm: {len(results) - len(failed)}/{len(results)} verificações ok em {elapsed:.0f} s")
    if frontend_kernel_s:
        print(f"tempo até o frontend (1º boot): {frontend_kernel_s[0]:.1f} s desde o kernel, "
              f"{frontend_wall_s[0]:.1f} s desde o início da VM")
    print(f"log serial: {out / 'serial.log'}")
    for name, (_, detail) in sorted(failed.items()):
        print(f"FALHOU: {name}" + (f" ({detail})" if detail else ""))
    (out / "summary.txt").write_text(
        "".join(f"{v[0]} {k} {v[1]}\n" for k, v in sorted(results.items()))
        + (f"frontend_kernel_s {frontend_kernel_s[0]:.1f}\n" if frontend_kernel_s else ""))
    if not keep:
        disk.unlink(missing_ok=True)
    return 1 if failed else 0
