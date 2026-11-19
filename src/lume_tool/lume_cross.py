"""lume-launcher without emulation (build-speed D7, step 2).

cargo runs on the PC, in the x86_64 builder container, for the console architecture, and
the abuild container of that architecture (still under qemu) only packages the binaries:

- the compiler is Alpine's x86_64 `rust` and the target std comes from the `rust` package
  of the target architecture, the same version and release (Alpine builds every
  `*-alpine-linux-musl*` target into rustc, so the target spec is the native one);
- the linker driver is clang (`--target`, `--sysroot`) with the GNU ld of Alpine's
  `binutils-<arch>` (the binutils of the native build), and the crt files, libgcc, musl
  and SDL2 come from a sysroot of the target installed by `apk --root --arch --no-scripts`
  (no emulation), kept in the cache and upgraded on each build;
- RUSTFLAGS and the cargo profile come from the target's own abuild `default.conf`, so the
  flags are those of a native abuild build (aarch64 links with pack-relative-relocs,
  armv7 does not);
- the workspace is mounted at the path abuild uses (`/aports/lume/lume-launcher/stage/
  lume`), so no new path enters the binaries.

The binaries are not byte-identical to a native build: cargo's per-crate metadata hash
includes the rustc host and the `--target` kind, so symbol hashes and the function order
change (same sections and sizes; on armv7 one page of padding may move).

`LUME_CROSS=0` brings back the native build (cargo under qemu, with the
`.cache/cargo/<arch>` target of build-speed 9.1).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from lume_tool.paths import cache_dir, ensure_dir, out_dir

CROSS_ENV = "LUME_CROSS"   # "0": cargo under qemu in the arch container (fallback)
TRIPLES = {
    "armv7": "armv7-alpine-linux-musleabihf",
    "aarch64": "aarch64-alpine-linux-musl",
}
BINARIES = ("lume-run", "lume-ui", "lume-index", "lume-menu")
GUEST_PREBUILT = "/lume-prebuilt"   # where the abuild container sees the binaries
PREBUILT_ENV = "LUME_PREBUILT"      # read by aports/lume-launcher/APKBUILD
WORKSPACE_GUEST = "/aports/lume/lume-launcher/stage/lume"
SYSROOT_PACKAGES = ("musl-dev", "gcc", "sdl2-dev")
# what the packaging (abuild -d, in the arch container) needs: the fonts it installs and
# sdl2, against which abuild traces the so: dependency of lume-ui
PACKAGE_DEPS = ("sdl2", "font-roboto")
PACKAGE_DEPS_STEP = f"apk add -q {' '.join(PACKAGE_DEPS)}\n"


def enabled(arch: str) -> bool:
    """The cross build is the default for the console architectures."""
    return arch in TRIPLES and os.environ.get(CROSS_ENV, "1") != "0"


def work_dir(arch: str) -> Path:
    """Sysroot, target std and apk cache of one architecture (kept between builds)."""
    return cache_dir() / "lume-cross" / arch


def target_dir(arch: str) -> Path:
    """The cargo `target/` of the cross build (host build scripts are x86_64 here, so it
    never shares a folder with the native `.cache/cargo/<arch>`)."""
    return cache_dir() / "cargo" / f"{arch}-cross"


def prebuilt_dir(arch: str) -> Path:
    return out_dir() / "pkg-staging" / "lume-prebuilt" / arch


def script(arch: str) -> str:
    """The build script (x86_64 builder container). `$JOBS` comes from the environment,
    so the text, which enters the fragment inputs, does not depend on --jobs."""
    triple = TRIPLES[arch]
    var = triple.upper().replace("-", "_")
    return rf"""
T={triple}
A={arch}
S=/cross/sysroot
M=$(sed -n 1p /etc/apk/repositories | sed 's#/main$##')
REPOS="-X $M/main -X $M/community"
LOCAL=""
if [ -f /localrepo/$A/APKINDEX.tar.gz ]; then LOCAL="-X /localrepo"; fi
apk add -U -q rust cargo clang binutils-$A
# the sysroot of the target: crt files, libgcc, musl and SDL2, without emulation
INIT=""
if [ ! -f $S/lib/apk/db/installed ]; then
  rm -rf $S
  mkdir -p $S/etc/apk/keys
  cp /usr/share/apk/keys/$A/* $S/etc/apk/keys/
  INIT=--initdb
fi
if [ -f /root/.abuild/lume.rsa.pub ]; then cp /root/.abuild/lume.rsa.pub $S/etc/apk/keys/; fi
apk --root $S --arch $A $INIT --no-scripts $REPOS $LOCAL add -u -q {" ".join(SYSROOT_PACKAGES)}
# the target std: from the target's rust package, the same version as the x86_64 rustc
XV=$(apk info -v 2>/dev/null | grep '^rust-[0-9]')
R=/cross/rust/$XV
if [ ! -d $R/usr/lib/rustlib/$T/lib ]; then
  rm -rf /cross/rust /tmp/fetch
  mkdir -p $R /tmp/fetch
  apk fetch -q --root $S --arch $A $REPOS -o /tmp/fetch rust
  if [ ! -f /tmp/fetch/$XV.apk ]; then
    echo "lume cross: x86_64 has $XV, $A has $(ls /tmp/fetch); set {CROSS_ENV}=0 for the native build" >&2
    exit 1
  fi
  tar -xzif /tmp/fetch/$XV.apk -C $R usr/lib/rustlib/$T
fi
ln -sfn $R/usr/lib/rustlib/$T /usr/lib/rustlib/$T
# the abuild flags of the target (RUSTFLAGS, cargo profile)
mkdir -p /tmp/abuild
apk fetch -q --root $S --arch $A $REPOS -o /tmp/abuild abuild
tar -xzif /tmp/abuild/abuild-*.apk -C /tmp/abuild usr/share/abuild/default.conf
cat > /usr/local/bin/lume-cc <<EOF
#!/bin/sh
exec clang --target=$T --sysroot=$S --ld-path=/usr/bin/$T-ld "\$@"
EOF
chmod +x /usr/local/bin/lume-cc
set +u
. /tmp/abuild/usr/share/abuild/default.conf
set -u
export CARGO_TARGET_{var}_LINKER=lume-cc
export PKG_CONFIG_SYSROOT_DIR=$S PKG_CONFIG_LIBDIR=$S/usr/lib/pkgconfig:$S/usr/share/pkgconfig
export CARGO_HOME=/tmp/cargo-home
cd {WORKSPACE_GUEST}
cargo build --release --offline --frozen --target $T
for b in {" ".join(BINARIES)}; do
  install -Dm755 target/$T/release/$b /prebuilt/$b
done
"""


def build(arch: str, aports: Path) -> Path:
    """Cross-compile the staged workspace (lume_tool.launcher_stage.stage() already ran) for `arch`.
    Returns the folder with the binaries, to be mounted at GUEST_PREBUILT."""
    from lume_tool import jobs, packages
    from lume_tool.container import Container, ensure_builder

    work = ensure_dir(work_dir(arch))
    prebuilt = prebuilt_dir(arch)
    shutil.rmtree(prebuilt, ignore_errors=True)
    ensure_dir(prebuilt)
    builder = packages.NOARCH_BUILD_TARGET
    volumes = {
        aports: "/aports/lume",
        ensure_dir(target_dir(arch)): f"{WORKSPACE_GUEST}/target",
        work: "/cross",
        ensure_dir(work / "apk-cache"): "/etc/apk/cache",
        prebuilt: "/prebuilt",
        ensure_dir(packages.keys_dir()): "/root/.abuild",
        ensure_dir(out_dir() / "repo"): "/localrepo",
    }
    Container(image=ensure_builder(builder), platform=builder.oci_platform,
              volumes=volumes, env={"JOBS": str(jobs.jobs())}).sh(script(arch))
    missing = [b for b in BINARIES if not (prebuilt / b).is_file()]
    if missing:
        raise RuntimeError(f"lume cross ({arch}): no {', '.join(missing)} in {prebuilt}")
    return prebuilt
