"""Compiling ARM packages without running the compiler under qemu (build-speed D7, P-36).

Path (a) of the P-36 proof: `abuild` keeps running in the emulated `lume-builder:<arch>`
container (fetch, preprocessing, linking, packaging), but every compile goes through
`distcc` to a `distccd` running natively on x86_64 with a cross gcc built from the very
same Alpine 3.24 `main/gcc` APKBUILD as the target's gcc (same version, patches and
configure flags; `containers/cross-gcc.sh`).

Opt-in per package with `LUME_DISTCC=<name>[,<name>...]` (or `all`); nothing changes when
it is unset. Steps, each run once per architecture:

    python -m lume_tool.distcc toolchain armv7   # build the cross gcc (long: ~20-30 min)
    python -m lume_tool.distcc image armv7       # distccd image from it (a minute)
    python -m lume_tool.distcc check armv7       # same .o through distcc and under qemu?
"""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from lume_tool import jobs
from lume_tool.container import Container, builder_image, image_exists, run
from lume_tool.heat import BUILD_LABEL
from lume_tool.jobs import PRIORITY_PREFIX
from lume_tool.paths import REPO_ROOT, cache_dir, ensure_dir
from lume_tool.targets import TARGETS, Target

ENV_VAR = "LUME_DISTCC"
# aports 3.24-stable commit of main/gcc and the version it builds; cross-gcc.sh checks
# that the target repository still ships this gcc (a newer gcc there means: re-pin)
GCC_COMMIT = "fd4fecacbfd0cd40be42efa3c9d72bc03a88428c"
GCC_VERSION = "15.2.0-r5"
TRIPLETS = {"armv7": "armv7-alpine-linux-musleabihf", "aarch64": "aarch64-alpine-linux-musl"}
# one distccd per architecture, so armv7 and aarch64 builds may overlap
PORTS = {"armv7": 3632, "aarch64": 3633}
IMAGE = "localhost/lume-distcc"
LOG_LEVEL = "info"  # one line per job: the log counts the remote compiles


def selected(env: dict[str, str] | None = None) -> set[str]:
    """Package names in LUME_DISTCC ('all' is kept as a name)."""
    raw = (os.environ if env is None else env).get(ENV_VAR, "")
    return {n.strip() for n in raw.replace(" ", ",").split(",") if n.strip()}


def uses_distcc(name: str, arch: str, chosen: set[str]) -> bool:
    """Whether `name` builds through distcc on `arch` (only the emulated architectures)."""
    return arch in TRIPLETS and ("all" in chosen or name in chosen)


def groups(names: list[str], arch: str, chosen: set[str]) -> list[tuple[bool, list[str]]]:
    """Split `names` into consecutive runs of (through distcc?, names), keeping the order."""
    out: list[tuple[bool, list[str]]] = []
    for n in names:
        flag = uses_distcc(n, arch, chosen)
        if out and out[-1][0] == flag:
            out[-1][1].append(n)
        else:
            out.append((flag, [n]))
    return out


def image_name(arch: str) -> str:
    return f"{IMAGE}:{arch}"


def container_name(arch: str) -> str:
    return f"lume-distccd-{arch}"


def hosts(arch: str, n_jobs: int) -> str:
    """DISTCC_HOSTS: only the local distccd (an IP, so distcc does not run it locally)."""
    return f"127.0.0.1:{PORTS[arch]}/{n_jobs}"


def client_env(arch: str, n_jobs: int) -> dict[str, str]:
    """Environment of the abuild container: ccache hands every miss to distcc."""
    return {
        "CCACHE_PREFIX": "distcc",
        "DISTCC_HOSTS": hosts(arch, n_jobs),
        # a failed remote compile fails the build instead of silently compiling under qemu
        "DISTCC_FALLBACK": "0",
        "DISTCC_SKIP_LOCAL_RETRY": "1",
    }


def distccd_argv(arch: str, n_jobs: int) -> list[str]:
    """The detached distccd container (host network, loopback only)."""
    return [
        *PRIORITY_PREFIX, "podman", "run", "-d", "--name", container_name(arch),
        "--network=host", "--label", BUILD_LABEL, image_name(arch),
        "distccd", "--daemon", "--no-detach", "--log-stderr", "--log-level", LOG_LEVEL,
        "--listen", "127.0.0.1", "--allow", "127.0.0.1", "--port", str(PORTS[arch]),
        "--jobs", str(n_jobs),
        # absolute compiler paths (/usr/bin/cc from ccache) run as given: in this image
        # they are the cross compiler, and only loopback clients are allowed
        "--make-me-a-botnet",
    ]


def remote_compiles(log: str) -> int:
    return sum(1 for line in log.splitlines() if "COMPILE_OK" in line)


def toolchain_dir(arch: str) -> Path:
    return cache_dir() / "cross-gcc" / arch


def toolchain_apks(arch: str) -> list[Path]:
    """The x86_64-hosted packages of the cross gcc (empty until `toolchain` ran)."""
    d = toolchain_dir(arch) / "repo" / "main" / "x86_64"
    return sorted(d.glob(f"g*-{arch}-[0-9]*.apk")) + sorted(
        d.glob(f"libstdc++-dev-{arch}-[0-9]*.apk"))


def _check_arch(arch: str) -> None:
    if arch not in TRIPLETS:
        raise SystemExit(f"distcc: unknown architecture {arch!r} (valid: {', '.join(TRIPLETS)})")


def _x86_target() -> Target:
    return TARGETS["vm"]


def build_toolchain(arch: str) -> None:
    """Build the cross gcc with the Alpine APKBUILD, natively on x86_64 (long)."""
    from lume_tool.container import ensure_builder
    from lume_tool.packages import KEY_NAME, keys_dir

    _check_arch(arch)
    if not (keys_dir() / f"{KEY_NAME}.rsa").exists():
        raise SystemExit("distcc: no abuild key yet; build any package once (lume pkg)")
    out = ensure_dir(toolchain_dir(arch))
    ensure_dir(cache_dir() / "distfiles")
    c = Container(
        image=ensure_builder(_x86_target()),
        platform="linux/amd64",
        volumes={
            REPO_ROOT / "containers" / "cross-gcc.sh": "/cross-gcc.sh",
            out: "/cross",
            cache_dir() / "distfiles": "/cache/distfiles",
            keys_dir(): "/root/.abuild",
        },
        env={"CTARGET_ARCH": arch, "GCC_COMMIT": GCC_COMMIT, "GCC_VERSION": GCC_VERSION,
             "REPODEST": "/cross/repo", "SRCDEST": "/cache/distfiles",
             "JOBS": str(jobs.jobs()), "MAKEFLAGS": f"-j{jobs.jobs()}"},
        extra=["--label", BUILD_LABEL],
    )
    c.sh("sh /cross-gcc.sh")


def ensure_image(arch: str) -> str:
    """Build (if missing) the distccd image from the cross gcc packages."""
    _check_arch(arch)
    name = image_name(arch)
    if image_exists(name):
        return name
    if not toolchain_apks(arch):
        raise SystemExit(f"distcc: no cross gcc for {arch} in {toolchain_dir(arch)}; "
                         f"run: python -m lume_tool.distcc toolchain {arch}")
    from lume_tool.container import ALPINE_VERSION

    run([
        "podman", "build", "-t", name, "--platform", "linux/amd64",
        "--build-arg", f"ALPINE_VERSION={ALPINE_VERSION}",
        "--build-arg", f"CTARGET_ARCH={arch}", "--build-arg", f"CTARGET={TRIPLETS[arch]}",
        "-f", str(REPO_ROOT / "containers" / "distcc.Containerfile"),
        str(toolchain_dir(arch) / "repo" / "main"),
    ])
    return name


def _wait_port(port: int, timeout: float = 30.0) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with socket.socket() as s:
            s.settimeout(1.0)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise SystemExit(f"distcc: distccd did not open port {port} in {timeout:.0f} s")


@contextmanager
def distccd(arch: str, n_jobs: int | None = None) -> Iterator[None]:
    """Run distccd for `arch` while the block runs; save its log next to the toolchain."""
    n_jobs = n_jobs or jobs.jobs()
    ensure_image(arch)
    name = container_name(arch)
    subprocess.run(["podman", "rm", "-f", name], check=False,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run(distccd_argv(arch, n_jobs))
    try:
        _wait_port(PORTS[arch])
        yield
    finally:
        subprocess.run(["podman", "stop", "-t", "2", name], check=False,
                       stdout=subprocess.DEVNULL)
        logs = subprocess.run(["podman", "logs", name], check=False,
                              capture_output=True, text=True)
        log = logs.stdout + logs.stderr
        path = toolchain_dir(arch) / "distccd.log"
        ensure_dir(path.parent)
        path.write_text(log)
        subprocess.run(["podman", "rm", "-f", name], check=False,
                       stdout=subprocess.DEVNULL)
        print(f"distcc: {remote_compiles(log)} remote compiles on {arch} (log: {path})",
              flush=True)


_CHECK = r"""
apk add -q distcc
mkdir -p /t && cd /t
cat > t.c <<'EOF'
#include <stdio.h>
#include <string.h>
struct s { int a; double b; char c[13]; };
static int cmp(const void *x, const void *y) { return *(const int *)x - *(const int *)y; }
int work(struct s *v, int n, int *buf) {
    int acc = 0;
    for (int i = 0; i < n; i++) {
        acc += v[i].a * 3 + (int)(v[i].b * 1.5);
        acc ^= (int)strlen(v[i].c);
        buf[i] = acc;
    }
    qsort(buf, n, sizeof *buf, cmp);
    printf("%d\n", acc);
    return acc;
}
EOF
for o in -O2 -Os; do
  cc $CFLAGS $o -fPIC -c t.c -o qemu$o.o
  distcc /usr/bin/cc $CFLAGS $o -fPIC -c t.c -o distcc$o.o
done
sha256sum *.o
for o in -O2 -Os; do cmp qemu$o.o distcc$o.o && echo "same object ($o)"; done
"""


def check(arch: str) -> None:
    """Compile a small C file under qemu and through distcc; the objects must match."""
    _check_arch(arch)
    target = next(t for t in TARGETS.values() if t.alpine_arch == arch)
    with distccd(arch, 2):
        Container(
            image=builder_image(target), platform=target.oci_platform,
            env={**client_env(arch, 2), "CFLAGS": "-fstack-clash-protection -Wformat"},
        ).sh(_CHECK)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m lume_tool.distcc", description=__doc__.split("\n")[0])
    p.add_argument("step", choices=["toolchain", "image", "check"])
    p.add_argument("arch", choices=sorted(TRIPLETS))
    a = p.parse_args(argv)
    if a.step == "toolchain":
        from lume_tool.cli import _heat_guarded

        _heat_guarded(lambda: build_toolchain(a.arch))
    elif a.step == "image":
        print(ensure_image(a.arch))
    else:
        check(a.arch)
    return 0


if __name__ == "__main__":
    sys.exit(main())
