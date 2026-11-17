"""Copy one file to the console over the cable ssh and check it: put.py LOCAL console:PATH [HOST].

The destination carries the `console:` prefix, so it is never taken for a path of the PC (the
guardrail checks absolute paths). The ctx recipe `console-put` (policy.toml) runs it. The file goes through the ssh of
`r36os dev` (the shared master channel), then `sync` and the sha256 on the console must match
the local one; exit 1 otherwise. HOST defaults to the cable's address (10.55.0.1); for the vm,
127.0.0.1:2222.
"""
import hashlib
import shlex
import subprocess
import sys
from pathlib import Path

from r36os import dev


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__.strip().splitlines()[0], file=sys.stderr)
        return 2
    local, remote = Path(sys.argv[1]), sys.argv[2]
    if not remote.startswith("console:/"):
        print("the destination is console:/<absolute path on the console>", file=sys.stderr)
        return 2
    remote = remote[len("console:"):]
    host = sys.argv[3] if len(sys.argv) > 3 else "10.55.0.1"
    data = local.read_bytes()
    want = hashlib.sha256(data).hexdigest()
    q = shlex.quote(remote)
    r = subprocess.run(dev.ssh_argv(host, f"cat > {q} && sync && sha256sum {q}"), input=data,
                       capture_output=True)
    out = (r.stdout + r.stderr).decode(errors="replace").strip()
    got = out.split()[0] if r.returncode == 0 and out else ""
    if got != want:
        print(f"put {local} -> {remote}: FAILED ({out or 'no answer'})")
        return 1
    print(f"put {local} -> {remote}: ok, {len(data)} bytes, sha256 {want[:16]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
