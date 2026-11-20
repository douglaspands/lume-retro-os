"""The `_lume` builds of the libretro cores (game-experience-tuning 11.1, P-114).

One mechanism for every core: `aports/libretro-<core>-lume/APKBUILD` is generated from the
APKBUILD of the upstream build of that core (the local `aports/libretro-<core>/APKBUILD`, or
for the four cores the image takes from Alpine a copy in `aports/_upstream/`), so a change of
the upstream aport (commit, sources, build steps) shows up in the `_lume` one after a
`lume cores-lume`, and a test fails until it does. The generated file is a complete APKBUILD
(abuild and the fingerprint of `lume pkg` read only this folder), with these changes and no
others:

* the package name gets the suffix `-lume`, and the source file names and the checksums
  list follow it (the tarballs are the same);
* the upstream `build()` and `package()` stay as they are, renamed `_upstream_build()` and
  `_upstream_package()`, and new ones wrap them;
* the new `build()` appends the CPU flags of the architecture to CFLAGS and CXXFLAGS (armv7:
  `-marm -mcpu=cortex-a7 -mfpu=neon-vfpv4 -mfloat-abi=hard`; aarch64: `-mcpu=cortex-a35`;
  x86_64: none, that build is the upstream one) and empties `_cflags`, the per-architecture
  flags some upstream aports pass themselves (`-marm`, `-mfpu=neon`, covered by these);
* the new `package()` renames the library to `<core>_lume_libretro.so`, writes
  `<core>_lume_libretro.info` from the info file of libretro-core-info with the `corename` and
  the `display_name` marked "(Lume)", and checks the result (NEON on armv7);
* the Cyclone (68000) and DrZ80 (Z80) variants of the two MAME cores, armv7 only, run the
  upstream build with `USE_CYCLONE=1 USE_DRZ80=1` (and `ARM=1` for mame2000, as the board
  platforms of its Makefile do) through a `make` function.

No `-Ofast`, no LTO: the optimisation level is the one of the upstream Makefile.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path

from lume_tool.paths import REPO_ROOT

APORTS = REPO_ROOT / "aports"
UPSTREAM_COPIES = APORTS / "_upstream"

FLAGS = {
    "armv7": "-marm -mcpu=cortex-a7 -mfpu=neon-vfpv4 -mfloat-abi=hard",
    "aarch64": "-mcpu=cortex-a35",
    "x86_64": "",
}

# The per-architecture flags the upstream aports put in `_cflags`: the generated build drops
# them because FLAGS already has these (neon-vfpv4 is a NEON FPU of the Cortex-A7).
UPSTREAM_CFLAGS_COVERED = {"-marm", "-mfpu=neon"}


@dataclass(frozen=True)
class Variant:
    upstream: str                  # upstream aport name, e.g. "libretro-mame2000"
    cyclone: bool = False          # the Cyclone/DrZ80 build of a MAME core (armv7 only)
    make_args: str = ""            # added to every make call of the build
    label: str = "Lume"            # appended to corename and display_name, in parentheses
    arch: str | None = None        # replaces the arch= of the upstream aport

    @property
    def package(self) -> str:
        return self.upstream + ("-cyclone" if self.cyclone else "") + "-lume"


# The 12 local cores and the 4 Alpine ones (copies in aports/_upstream)
CORES = (
    "libretro-fceumm", "libretro-nestopia", "libretro-gambatte", "libretro-gpsp",
    "libretro-snes9x2005-plus", "libretro-genesis-plus-gx", "libretro-picodrive",
    "libretro-fbneo", "libretro-fbalpha2012", "libretro-fbalpha2012-cps1",
    "libretro-fbalpha2012-cps2", "libretro-fbalpha2012-neogeo", "libretro-pcsx-rearmed",
    "libretro-mednafen-pce-fast", "libretro-mame2003-plus", "libretro-mame2000",
)

VARIANTS = tuple(Variant(c) for c in CORES) + (
    Variant("libretro-mame2000", True, "ARM=1 USE_CYCLONE=1 USE_DRZ80=1", "Lume, Cyclone",
            "armv7"),
    Variant("libretro-mame2003-plus", True, "USE_CYCLONE=1 USE_DRZ80=1", "Lume, Cyclone",
            "armv7"),
)

# Variants whose aport is kept but which are out of the image (commented out in their package
# list), with the reason. GA36, 2026-11-20: abuild refuses the Cyclone/DrZ80 builds for text
# relocations (the assembly is not position independent); the user decides the way out (P-114).
SUSPENDED = {
    "libretro-mame2000-cyclone-lume": "text relocations (P-114)",
    "libretro-mame2003-plus-cyclone-lume": "text relocations (P-114)",
}


# The _lume builds that won against the upstream build (game-experience-tuning 11.3, the
# user's decision of 2026-11-20) and replace it in the image (rootfs/packages.txt) and in the
# catalog. Every other _lume aport stays out of the image, ready to be measured again.
ADOPTED = (
    "libretro-snes9x2005-plus-lume",
    "libretro-genesis-plus-gx-lume",
    "libretro-pcsx-rearmed-lume",
)


class CoresLumeError(Exception):
    pass


def upstream_path(name: str) -> Path:
    local = APORTS / name / "APKBUILD"
    return local if local.is_file() else UPSTREAM_COPIES / f"{name}.APKBUILD"


def core_id(text: str) -> str:
    """The core id of an upstream APKBUILD (`fbneo` for fbneo_libretro.so)."""
    ids = set(re.findall(r"/usr/lib/libretro/(\w+)_libretro\.so", text))
    if len(ids) != 1:
        raise CoresLumeError(f"expected one core library in package(), found {sorted(ids)}")
    return ids.pop()


def lume_id(v: Variant) -> str:
    """The new core id: the library is `<id>_libretro.so`, the info `<id>_libretro.info`."""
    return core_id(upstream_path(v.upstream).read_text()) + ("_cyclone" if v.cyclone else "") + "_lume"


def _sub1(pattern: str, repl: str, text: str, what: str) -> str:
    new, n = re.subn(pattern, repl, text, count=1, flags=re.M)
    if n != 1:
        raise CoresLumeError(f"no {what} in the upstream APKBUILD")
    return new


def _assignment(text: str, key: str) -> str | None:
    m = re.search(rf'^{key}=(?:"([^"]*)"|(\S*))$', text, re.M)
    return None if m is None else (m.group(1) if m.group(1) is not None else m.group(2))


_WRAPPER = r'''
# --- Lume build (generated by lume_tool.cores_lume from the upstream aport; edit the generator,
# not this block). CPU flags of the architecture, nothing else changed (no -Ofast, no LTO) ---
_lume_core="@CORE@"
_lume_id="@ID@"
_lume_label="@LABEL@"
_lume_infodir=/usr/share/libretro/info   # where libretro-core-info installs the info files
case "$CARCH" in
armv7) _lume_flags="@ARMV7@" ;;
aarch64) _lume_flags="@AARCH64@" ;;
*) _lume_flags="" ;;
esac
@MAKE@
build() {
	# the flags go last in the CFLAGS/CXXFLAGS of the environment, which every Makefile of this
	# core takes (checked with make -n); `_cflags` is the per-arch part that some upstream
	# aports add themselves, covered by the flags
	_cflags=""
	if [ -n "$_lume_flags" ]; then
		export CFLAGS="$CFLAGS $_lume_flags"
		export CXXFLAGS="$CXXFLAGS $_lume_flags"
	fi
	_upstream_build
}

package() {
	_upstream_package
	_libdir="$pkgdir"/usr/lib/libretro
	_so="$_libdir/${_lume_id}_libretro.so"
	mv "$_libdir/${_lume_core}_libretro.so" "$_so" || return 1
	# the info file of the upstream core (libretro-core-info) under the new core id; its
	# corename names the folder of the options of the core, so it must differ
	_info="$_lume_infodir/${_lume_core}_libretro.info"
	_out="$pkgdir"/usr/share/libretro/info/${_lume_id}_libretro.info
	[ -f "$_info" ] || { error "$_info is missing (libretro-core-info)"; return 1; }
	install -dm755 "$pkgdir"/usr/share/libretro/info
	sed -e "s/^\(corename *= *\"[^\"]*\)\"/\1 (${_lume_label})\"/" \
		-e "s/^\(display_name *= *\"[^\"]*\)\"/\1 (${_lume_label})\"/" \
		"$_info" > "$_out"
	grep -q "^corename *= *\".*(${_lume_label})\"" "$_out" \
		|| { error "no corename in $_info"; return 1; }
	# armv7: the flags reached the compiler (the FPU default of the distro is vfpv3-d16, no NEON)
	if [ "$CARCH" = armv7 ]; then
		_attrs=$(readelf -A "$_so") || return 1
		echo "$_attrs" | grep -E 'Tag_(CPU_name|CPU_arch|FP_arch|Advanced_SIMD_arch)'
		echo "$_attrs" | grep -q Tag_Advanced_SIMD_arch \
			|| { error "no NEON in $_so: the CPU flags did not reach the compiler"; return 1; }
@CYCLONE_CHECK@	fi
}
'''

_MAKE = '''
# Cyclone (68000) and DrZ80 (Z80): the ARM assembly CPU cores of this emulator
make() {
	command make "$@" @ARGS@
}
'''

_CYCLONE_CHECK = '''		# the assembly CPU cores really are in the library
		_syms=$(readelf -sW "$_so") || return 1
		for _s in CycloneRun DrZ80Run; do
			echo "$_syms" | grep -q "$_s" || { error "$_s is not in $_so"; return 1; }
		done
'''


def _wrapper(v: Variant, text: str) -> str:
    out = _WRAPPER
    for key, value in (
        ("@CORE@", core_id(text)), ("@ID@", lume_id(v)), ("@LABEL@", v.label),
        ("@ARMV7@", FLAGS["armv7"]), ("@AARCH64@", FLAGS["aarch64"]),
        ("@MAKE@", _MAKE.replace("@ARGS@", v.make_args) if v.make_args else ""),
        ("@CYCLONE_CHECK@", _CYCLONE_CHECK if v.cyclone else ""),
    ):
        out = out.replace(key, value)
    return out


def generate(v: Variant) -> str:
    src = upstream_path(v.upstream)
    text = src.read_text()
    old = _assignment(text, "pkgname")
    if old != v.upstream:
        raise CoresLumeError(f"{src}: pkgname is {old!r}, not {v.upstream}")
    for m in re.finditer(r'\b_cflags="([^"]*)"', text):
        extra = set(m.group(1).split()) - UPSTREAM_CFLAGS_COVERED
        if extra:
            raise CoresLumeError(f"{src}: _cflags has {sorted(extra)} that FLAGS does not cover")
    new = v.package
    wrapper = _wrapper(v, text)

    text = _sub1(r"^pkgname=\S+$", f"pkgname={new}", text, "pkgname")
    text = _sub1(r'^pkgdesc="(.*)"$', rf'pkgdesc="\1 ({v.label} build)"', text, "pkgdesc")
    # a suspended variant is not built at all (arch="", like the disabled ppsspp): the full
    # console build compiles every local aport of the architecture, not only the listed ones
    arch = "" if v.package in SUSPENDED else v.arch
    if arch is not None and (arch or v.package in SUSPENDED):
        text = _sub1(r'^arch="[^"]*"$', f'arch="{arch}"', text, "arch")
    # libretro-core-info for the info file, binutils for readelf (both only to build)
    if re.search(r'^makedepends="', text, re.M):
        text = _sub1(r'^makedepends="([^"]*)"$',
                     r'makedepends="\1 libretro-core-info binutils"', text, "makedepends")
    else:
        text = _sub1(r'^(license="[^"]*")$',
                     r'\1\nmakedepends="libretro-core-info binutils"', text, "license")
    text = _sub1(r"^build\(\) \{$", "_upstream_build() {", text, "build()")
    text = _sub1(r"^package\(\) \{$", "_upstream_package() {", text, "package()")
    # the checksums are named after the source files, which carry the package name
    text, n = re.subn(rf"^([0-9a-f]{{128}})  {re.escape(old)}-", rf"\g<1>  {new}-", text,
                      flags=re.M)
    if n == 0:
        raise CoresLumeError(f"{src}: no checksum line named {old}-*")
    marker = '\nsha512sums="'
    if text.count(marker) != 1:
        raise CoresLumeError(f"{src}: expected one sha512sums block")
    head, tail = text.split(marker)
    text = head.rstrip("\n") + "\n" + wrapper + marker + tail

    header = (
        f"# GENERATED by `lume cores-lume` (lume_tool.cores_lume) from {src.relative_to(REPO_ROOT)}.\n"
        "# Do not edit: change the upstream aport or the generator and generate again.\n"
        "# Lume Retro OS build of the core with the CPU flags of the console, next to the build\n"
        "# of the upstream (game-experience-tuning 11, P-114). Not in the catalog until 11.5.\n"
        "# The comments below are the ones of the upstream aport, which describes its own build.\n"
        "\n"
    )
    return header + text


def target_path(v: Variant) -> Path:
    return APORTS / v.package / "APKBUILD"


def write_all() -> list[Path]:
    out = []
    for v in VARIANTS:
        path = target_path(v)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(generate(v))
        out.append(path)
    return out


def stale() -> list[Path]:
    """The generated APKBUILDs that are missing or differ from what the generator writes."""
    return [target_path(v) for v in VARIANTS
            if not target_path(v).is_file() or target_path(v).read_text() != generate(v)]


def main(check: bool = False) -> int:
    if check:
        old = stale()
        for p in old:
            print(f"stale: {p.relative_to(REPO_ROOT)}")
        return 1 if old else 0
    for p in write_all():
        print(p.relative_to(REPO_ROOT))
    return 0


if __name__ == "__main__":
    sys.exit(main(check="--check" in sys.argv[1:]))
