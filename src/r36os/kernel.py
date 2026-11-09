"""Fonte do kernel mainline LTS dos consoles (D3): download fixado, patches e DTBs.

O tarball oficial é baixado uma vez para o cache e conferido pelo sha256. A árvore
usada no build é uma cópia extraída com os patches de `kernel/patches/` aplicados em
ordem; ela é refeita quando a lista ou o conteúdo dos patches muda.
"""

from __future__ import annotations

import hashlib
import shutil
import tarfile
import urllib.request
from pathlib import Path

from r36os.paths import REPO_ROOT, cache_dir, ensure_dir

KERNEL_VERSION = "6.18.62"
KERNEL_URL = f"https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-{KERNEL_VERSION}.tar.xz"
# sha256sums.asc de cdn.kernel.org/pub/linux/kernel/v6.x/
KERNEL_SHA256 = "490a7aedf1b355c565d3a6c05333ccccb5da82064eca46b590448a7099d7d651"

PATCHES_DIR = REPO_ROOT / "kernel/patches"


def patches() -> list[Path]:
    """Patches de `kernel/patches/`, na ordem do nome (0001-..., 0002-...)."""
    return sorted(PATCHES_DIR.glob("*.patch"))


def patches_digest() -> str:
    h = hashlib.sha256()
    for p in patches():
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


def tarball() -> Path:
    """O tarball do kernel no cache, baixado e conferido se preciso."""
    dest = ensure_dir(cache_dir() / "distfiles") / f"linux-{KERNEL_VERSION}.tar.xz"
    if not dest.exists():
        tmp = dest.with_suffix(".part")
        print(f"baixando {KERNEL_URL}", flush=True)
        with urllib.request.urlopen(KERNEL_URL, timeout=120) as r, tmp.open("wb") as f:
            shutil.copyfileobj(r, f)
        tmp.replace(dest)
    h = hashlib.sha256()
    with dest.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != KERNEL_SHA256:
        raise RuntimeError(f"{dest.name}: sha256 {h.hexdigest()} != {KERNEL_SHA256}")
    return dest


def source_tree() -> Path:
    """Árvore do kernel com os patches aplicados (refeita quando os patches mudam)."""
    import subprocess

    base = ensure_dir(cache_dir() / "src")
    tree = base / f"linux-{KERNEL_VERSION}-{patches_digest()}"
    stamp = tree / ".r36os-ready"
    if stamp.exists():
        return tree
    shutil.rmtree(tree, ignore_errors=True)
    for old in base.glob(f"linux-{KERNEL_VERSION}-*"):
        shutil.rmtree(old, ignore_errors=True)
    tmp = base / f"linux-{KERNEL_VERSION}.extract"
    shutil.rmtree(tmp, ignore_errors=True)
    print(f"extraindo linux-{KERNEL_VERSION}", flush=True)
    with tarfile.open(tarball()) as t:
        t.extractall(tmp, filter="data")
    (tmp / f"linux-{KERNEL_VERSION}").rename(tree)
    tmp.rmdir()
    for p in patches():
        print(f"aplicando {p.name}", flush=True)
        subprocess.run(["git", "apply", "--whitespace=nowarn", str(p)], cwd=tree, check=True)
    stamp.write_text(patches_digest() + "\n")
    return tree


# Flags do scripts/Makefile.dtbs do kernel (W=0), mais -@ para overlays
_DTC_FLAGS = ("-Wno-unit_address_vs_reg -Wno-avoid_unnecessary_addr_size -Wno-alias_paths "
              "-Wno-graph_child_address -Wno-interrupt_map -Wno-simple_bus_reg "
              "-Wno-unique_unit_address -Wunique_unit_address_if_enabled -@")

_DTBS_SCRIPT = """
set -eu
inc=/linux/scripts/dtc/include-prefixes
cd /dts
for f in *.dts; do
  n=${{f%.dts}}
  cpp -nostdinc -I /dts -I /linux/arch/{arch}/boot/dts/{vendor} -I $inc -undef -D__DTS__ \\
      -x assembler-with-cpp -o /tmp/$n.pp $f
  dtc -O dtb -b 0 {dtc_flags} -i /dts -o /out/$n.dtb /tmp/$n.pp
  echo "dtb: $n.dtb"
done
dt-mk-schema -j /linux/Documentation/devicetree/bindings > /tmp/schema.json
fail=0
for d in /out/*.dtb; do
  out=$(dt-validate -s /tmp/schema.json -m "$d" 2>&1) || fail=1
  if [ -n "$out" ]; then echo "$out"; fail=1; fi
done
[ $fail = 0 ] && echo "dt-validate: sem erros"
exit $fail
"""


def build_dtbs(board: str, arch: str, vendor: str, out: Path) -> None:
    """Compila `board/<board>/dts/*.dts` contra a árvore com patches e valida os DTBs.

    Falha se o dtc avisar algo além das exceções do kernel ou se o dt-validate
    reportar qualquer coisa.
    """
    from r36os.container import Container, ensure_cross

    tree = source_tree()
    shutil.rmtree(out, ignore_errors=True)
    ensure_dir(out)
    Container(
        image=ensure_cross(),
        volumes={tree: "/linux", REPO_ROOT / "board" / board / "dts": "/dts", out: "/out"},
    ).sh(_DTBS_SCRIPT.format(arch=arch, vendor=vendor, dtc_flags=_DTC_FLAGS))
