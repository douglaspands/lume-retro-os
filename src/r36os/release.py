"""Release rule (11.1): the vm is built and tested first; the console images are only
marked as released if the test-vm of the same build passes."""

from __future__ import annotations

import json
import time
import traceback

from r36os.paths import ensure_dir, out_dir
from r36os.rootfs import target_out
from r36os.targets import TARGETS

MARKER = "RELEASED"


def _build(name: str, language: str = "en") -> None:
    from r36os.build import build_target

    build_target(TARGETS[name], language=language)


def _test_vm() -> int:
    from r36os.selftest import test_vm

    return test_vm()


def build_all(build=None, test=_test_vm, language: str = "en") -> int:
    """Build the vm, run the acceptance test, then the consoles. Return 0 if all released."""
    if build is None:
        def build(name: str) -> None:
            _build(name, language)
    report: dict = {"started": time.strftime("%Y-%m-%dT%H:%M:%S"), "targets": {}}
    for name in TARGETS:  # a new build never inherits the mark of an earlier one
        (target_out(TARGETS[name]) / MARKER).unlink(missing_ok=True)

    try:
        build("vm")
        vm_ok = test() == 0
    except Exception:  # noqa: BLE001 - record it and go on to the report
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
                f"released: the test-vm of the same build passed ({report['started']})\n")
        report["targets"][name] = entry

    ensure_dir(out_dir())
    (out_dir() / "release.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    for name, e in report["targets"].items():
        state = "released" if e.get("released") else ("tested" if name == "vm" else "NOT released")
        print(f"{name}: {state}")
    released = all(report["targets"][n]["released"] for n in ("r36s", "ga36"))
    return 0 if vm_ok and released else 1
