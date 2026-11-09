"""Regra de liberação (11.1): a vm é gerada e testada primeiro; as imagens dos consoles
só são marcadas como liberadas se o test-vm do mesmo build passar."""

from __future__ import annotations

import json
import time
import traceback

from r36os.paths import ensure_dir, out_dir
from r36os.rootfs import target_out
from r36os.targets import TARGETS

MARKER = "RELEASED"


def _build(name: str) -> None:
    from r36os.build import build_target

    build_target(TARGETS[name])


def _test_vm() -> int:
    from r36os.selftest import test_vm

    return test_vm()


def build_all(build=_build, test=_test_vm) -> int:
    """Gera vm, roda o teste de aceitação e depois os consoles. Devolve 0 se tudo liberado."""
    report: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "targets": {}}
    for name in TARGETS:  # um build novo nunca herda a marca de um anterior
        (target_out(TARGETS[name]) / MARKER).unlink(missing_ok=True)

    try:
        build("vm")
        vm_ok = test() == 0
    except Exception:  # noqa: BLE001 - registra e segue para o relatório
        traceback.print_exc()
        vm_ok = False
    report["targets"]["vm"] = {"built": True, "test_vm": "PASS" if vm_ok else "FAIL"}

    for name in ("r36s", "ga36"):
        entry: dict = {}
        try:
            build(name)
            entry["built"] = True
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            entry["built"] = False
            entry["error"] = str(e)
        entry["released"] = bool(entry["built"] and vm_ok)
        if entry["released"]:
            ensure_dir(target_out(TARGETS[name]))
            (target_out(TARGETS[name]) / MARKER).write_text(
                f"liberada: test-vm do mesmo build passou ({report['started']})\n")
        report["targets"][name] = entry

    ensure_dir(out_dir())
    (out_dir() / "release.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    for name, e in report["targets"].items():
        state = "liberada" if e.get("released") else ("testada" if name == "vm" else "NÃO liberada")
        print(f"{name}: {state}")
    released = all(report["targets"][n]["released"] for n in ("r36s", "ga36"))
    return 0 if vm_ok and released else 1
