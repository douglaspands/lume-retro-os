#!/bin/sh
# Cross gcc for distcc (build-speed D7, P-36): an x86_64-hosted gcc that generates the same
# code as the target's Alpine gcc. It is the Alpine 3.24 aports main/gcc APKBUILD (same
# source, patches and configure flags), built the way aports scripts/bootstrap.sh builds its
# "Full cross GCC" step, but with the target's musl-dev and libucontext-dev taken from the
# Alpine binary repository instead of being bootstrapped (no gcc-pass2, no musl build).
# binutils-<arch> already ships in Alpine (same version as the target's binutils).
#
# Runs natively in localhost/lume-builder:x86_64 (no qemu). Inputs (environment):
#   CTARGET_ARCH  armv7 | aarch64
#   GCC_COMMIT    aports commit of main/gcc (pinned in src/lume_tool/distcc.py)
#   GCC_VERSION   expected <pkgver>-r<pkgrel>; must match the target repository's gcc
#   STOP_AFTER    optional: "prepare" stops after deps + fetch + unpack + patches
# Output: /cross/repo/main/x86_64/{gcc,g++,libstdc++-dev}-<arch>-*.apk (and the
# arch=<arch> subpackages in /cross/repo/main/<arch>/). Signing key: /root/.abuild.
set -eu

: "${CTARGET_ARCH:?}" "${GCC_COMMIT:?}" "${GCC_VERSION:?}"
log() { echo ">>> cross-gcc-$CTARGET_ARCH: $*"; }

apk update -q

# 1. main/gcc of aports at the pinned commit (only that directory)
work=/work/aports/main
mkdir -p "$work"
cd "$work"
wget -qO gcc.tar.gz \
	"https://gitlab.alpinelinux.org/alpine/aports/-/archive/$GCC_COMMIT/aports-$GCC_COMMIT.tar.gz?path=main/gcc"
tar -xzf gcc.tar.gz --strip-components=2
rm gcc.tar.gz
ver=$(sed -n 's/^pkgver=//p' gcc/APKBUILD)-r$(sed -n 's/^pkgrel=//p' gcc/APKBUILD)
[ "$ver" = "$GCC_VERSION" ] || { echo "aports main/gcc is $ver, expected $GCC_VERSION" >&2; exit 1; }

# 2. target sysroot from the Alpine binary repository (abuild's default CBUILDROOT)
sysroot="$HOME/sysroot-$CTARGET_ARCH"
mkdir -p "$sysroot/etc/apk/keys"
cp /usr/share/apk/keys/"$CTARGET_ARCH"/*.pub "$sysroot/etc/apk/keys/"
cp /etc/apk/repositories "$sysroot/etc/apk/repositories"
apk add --quiet --initdb --no-scripts --arch "$CTARGET_ARCH" --root "$sysroot"
apk update -q --root "$sysroot"
target_ver=$(apk --root "$sysroot" list gcc | sed -n 's/^gcc-\([^ ]*\) .*/\1/p' | head -n1)
[ "$target_ver" = "$GCC_VERSION" ] || {
	echo "the $CTARGET_ARCH repository has gcc $target_ver, expected $GCC_VERSION" >&2
	exit 1
}
log "gcc $GCC_VERSION (aports $GCC_COMMIT), target repository gcc $target_ver"

# 3. the cross compiler: C and C++ only (D and Ada would only add front ends)
export CTARGET="$CTARGET_ARCH" BOOTSTRAP=nobase LANG_D=false LANG_ADA=false
export EXTRADEPENDS_TARGET="musl-dev libucontext-dev"
cd "$work/gcc"
if [ "${STOP_AFTER:-}" = prepare ]; then
	abuild -F deps
	abuild -F fetch unpack prepare
	log "stopped after prepare"
	exit 0
fi
abuild -F -r
ls -l /cross/repo/main/x86_64/ /cross/repo/main/"$CTARGET_ARCH"/
log "done"
