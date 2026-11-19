"""Drive the running vm over QMP (the socket of `lume vm`, .cache/vm/qmp.sock).

  vm_qmp.py shot NAME             screen to cache/tmp/shots/vm/NAME.png (plain virtio-vga only)
  vm_qmp.py keys K1+K2 [HOLD_MS]  press qcodes together (f1, f1+w, down, x, z, ret...)
  vm_qmp.py holdshot NAME KEY     hold KEY 3 s and capture after 1.5 s (the Fn hint)

The ctx recipes `vm-shot`, `vm-keys` and `vm-holdshot` (policy.toml) run it.
"""
import shutil
import sys
import time

from lume_tool.paths import REPO_ROOT
from lume_tool.qmp import QMP
from lume_tool.vm import run_dir

OUT = REPO_ROOT / "cache/tmp/shots/vm"


def _dump(q: QMP, name: str) -> None:
    d = run_dir()
    q.screendump(f"/vm/{name}.png")
    time.sleep(0.5)
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.move(str(d / f"{name}.png"), OUT / f"{name}.png")
    print(OUT / f"{name}.png")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    q = QMP(run_dir() / "qmp.sock", timeout=10)
    try:
        cmd = sys.argv[1]
        if cmd == "shot":
            _dump(q, sys.argv[2])
        elif cmd == "keys":
            hold = int(sys.argv[3]) if len(sys.argv) > 3 else 120
            q.send_keys(*sys.argv[2].split("+"), hold_ms=hold)
            time.sleep(hold / 1000 + 0.3)
            print("sent", sys.argv[2], hold)
        elif cmd == "holdshot" and len(sys.argv) > 3:
            q.send_keys(sys.argv[3], hold_ms=3000)
            time.sleep(1.5)
            _dump(q, sys.argv[2])
            time.sleep(1.5)
        else:
            print(__doc__, file=sys.stderr)
            return 2
    finally:
        q.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
