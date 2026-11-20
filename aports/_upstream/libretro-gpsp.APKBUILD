# Contributor: David Demelier <markand@malikania.fr>
# Maintainer: David Demelier <markand@malikania.fr>
# Copy of community/libretro-gpsp of Alpine (the build the image installs today), kept here as
# the input of lume_tool.cores_lume, which generates ../libretro-gpsp-lume/APKBUILD from it
# (game-experience-tuning 11.1). Not an aport: nothing builds this file. Note: the default
# "unix" platform of the gpsp Makefile turns the dynarec on only for x86, so on armv7 and
# aarch64 this is the interpreter build; the ARM dynarec needs a platform= value (not part of
# the CPU-flag build).
pkgname=libretro-gpsp
pkgver=0_git20250120
pkgrel=0
_commit="b0d5d27ae51c23f514974ddffa5760f1e1d05d9b"
pkgdesc="gpSP for libretro"
url="https://github.com/libretro/gpsp"
arch="all"
license="GPL-2.0-only"
source="$pkgname-$_commit.tar.gz::https://github.com/libretro/gpsp/archive/$_commit.tar.gz"
builddir="$srcdir/gpsp-$_commit"
options="!check" # No tests

build() {
	make
}

package() {
	install -Dm644 gpsp_libretro.so "$pkgdir"/usr/lib/libretro/gpsp_libretro.so
}

sha512sums="
31b2ad127b876a25db9b9ed5e633e5a244d6bc141ebbf2cdda1fe5a2443e3e1c591e0a01e71cce3ba7eb1ad569ff6e6974816c32db8cc89f5fd27ae0b0403105  libretro-gpsp-b0d5d27ae51c23f514974ddffa5760f1e1d05d9b.tar.gz
"
