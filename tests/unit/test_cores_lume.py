"""game-experience-tuning 11.1: the `_lume` builds of the cores (lume_tool.cores_lume)."""

import re
import stat
import subprocess

import pytest

from lume_tool import cores_lume as cl
from lume_tool.packages import aport_arches, local_aports
from lume_tool.paths import REPO_ROOT
from lume_tool.targets import get_target

ARMV7 = "-marm -mcpu=cortex-a7 -mfpu=neon-vfpv4 -mfloat-abi=hard"
AARCH64 = "-mcpu=cortex-a35"
DISTRO = "-Os -fstack-clash-protection"

PLAIN = [v for v in cl.VARIANTS if not v.cyclone]
CYCLONE = [v for v in cl.VARIANTS if v.cyclone]
PLAIN_IDS = [v.package for v in PLAIN]
CYCLONE_IDS = [v.package for v in CYCLONE]

INFO = ('display_name = "Nintendo - NES (FCEUmm)"\ncorename = "FCEUmm"\n'
        'supported_extensions = "nes|fds"\n')
NEON = '  Tag_Advanced_SIMD_arch: NEONv1 with Fused-MAC'


def _lines(path) -> list[str]:
    return [line.split("#", 1)[0].strip() for line in path.read_text().splitlines()
            if line.split("#", 1)[0].strip()]


def _corenames() -> dict[str, str]:
    text = (REPO_ROOT / "tests/fixtures/libretro-corenames.txt").read_text()
    return dict(re.findall(r'^(\w+) = "([^"]+)"$', text, re.M))


def _arch(text: str) -> str:
    return re.search(r'^arch="([^"]*)"$', text, re.M).group(1)


def _upstream(v) -> str:
    return cl.upstream_path(v.upstream).read_text()


def _sums(text: str) -> list[tuple[str, str]]:
    return re.findall(r"^([0-9a-f]{128})  (\S+)$", text, re.M)


# --- the generator ---

def test_every_core_of_the_image_has_a_lume_build():
    # the 16 cores of the image: 12 local aports and the 4 that come from Alpine
    assert len(PLAIN) == 16
    image = {p for p in _lines(REPO_ROOT / "rootfs/packages.txt")
             if p.startswith("libretro-") and not p.endswith("-lume")
             and p != "libretro-core-info"}
    assert {v.upstream for v in PLAIN} == image
    assert CYCLONE_IDS == ["libretro-mame2000-cyclone-lume", "libretro-mame2003-plus-cyclone-lume"]


def test_generated_aports_are_up_to_date():
    # edit the upstream aport or the generator, then run `lume cores-lume`
    assert [str(p.relative_to(REPO_ROOT)) for p in cl.stale()] == []


@pytest.mark.parametrize("v", cl.VARIANTS, ids=PLAIN_IDS + CYCLONE_IDS)
def test_nothing_but_the_lume_changes_is_in_the_generated_aport(v):
    generated = cl.target_path(v).read_text()
    upstream = _upstream(v)
    # undo the documented changes: what is left is the upstream aport, byte for byte
    body = generated.split("\n\n", 1)[1]
    body = re.sub(r"\n# --- Lume build.*?(?=\nsha512sums=)", "", body, flags=re.S)
    body = body.replace(f"pkgname={v.package}", f"pkgname={v.upstream}", 1)
    body = body.replace(f" ({v.label} build)\"", "\"", 1)
    if v.arch:
        body = body.replace(f'arch="{v.arch}"', f'arch="{_arch(upstream)}"', 1)
    body = body.replace(" libretro-core-info binutils\"", "\"", 1)
    body = body.replace('\nmakedepends="libretro-core-info binutils"', "", 1)
    body = body.replace("_upstream_build() {", "build() {", 1)
    body = body.replace("_upstream_package() {", "package() {", 1)
    body = body.replace(f"  {v.package}-", f"  {v.upstream}-")
    # (the blank lines before the checksums are the only thing the generator normalises)
    assert re.sub(r"\n+sha512sums=", "\nsha512sums=", body) == \
        re.sub(r"\n+sha512sums=", "\nsha512sums=", upstream)


@pytest.mark.parametrize("v", cl.VARIANTS, ids=PLAIN_IDS + CYCLONE_IDS)
def test_names_end_in_lume(v):
    text = cl.target_path(v).read_text()
    core = cl.core_id(_upstream(v))
    ident = core + ("_cyclone" if v.cyclone else "") + "_lume"
    assert re.search(rf"^pkgname={re.escape(v.package)}$", text, re.M)
    assert f'_lume_id="{ident}"' in text and f'_lume_core="{core}"' in text
    assert cl.lume_id(v) == ident
    # package name and core id map the way the packages.txt tests expect
    assert v.package.removeprefix("libretro-").replace("-", "_") == ident
    # the checksums follow the source file names (they carry the package name); the hashes
    # are the upstream ones, so the tarballs are too
    up, sums = _sums(_upstream(v)), _sums(text)
    assert [h for h, _ in sums] == [h for h, _ in up]
    assert all(n.startswith(v.package + "-") for _, n in sums)
    assert "$pkgname-$_commit.tar.gz" in text


def test_flags_per_architecture():
    assert cl.FLAGS == {"armv7": ARMV7, "aarch64": AARCH64, "x86_64": ""}
    assert not re.search(r"-Ofast|-flto|-O\d", ARMV7 + " " + AARCH64)


def test_upstream_cflags_are_covered_by_the_lume_flags():
    # pcsx-rearmed and picodrive pass -marm and -mfpu=neon on armv7 themselves; the lume
    # build empties that variable because its own flags have both (neon-vfpv4 is NEON)
    seen = set()
    for v in PLAIN:
        for m in re.finditer(r'\b_cflags="([^"]*)"', _upstream(v)):
            seen |= set(m.group(1).split())
    assert seen == {"-marm", "-mfpu=neon"} == cl.UPSTREAM_CFLAGS_COVERED
    assert "-marm" in ARMV7.split()


# --- build(): what make sees ---

def _bin(tmp_path, readelf=None):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "make"
    fake.write_text('#!/bin/sh\nprintf "CFLAGS=%s\\nCXXFLAGS=%s\\nARGS=%s\\n" '
                    '"$CFLAGS" "$CXXFLAGS" "$*"\n')
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    if readelf is not None:
        fake = bindir / "readelf"
        fake.write_text(f"#!/bin/sh\n{readelf}\n")
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
    return bindir


def _run_build(tmp_path, apkbuild, carch):
    """Source an APKBUILD for CARCH and run build() with a fake make on PATH; returns the
    CFLAGS, CXXFLAGS and arguments of the last make call."""
    script = f'CFLAGS="{DISTRO}"\nCXXFLAGS="{DISTRO}"\nexport CFLAGS CXXFLAGS\n. "$1"\nbuild\n'
    out = subprocess.run(["sh", "-c", script, "sh", str(apkbuild)],
                         env={"CARCH": carch, "PATH": f"{_bin(tmp_path)}:/usr/bin:/bin"},
                         capture_output=True, text=True, check=True).stdout.splitlines()
    got = dict(line.split("=", 1) for line in out[-3:])
    return got["CFLAGS"].split(), got["CXXFLAGS"].split(), got["ARGS"].split()


@pytest.mark.parametrize("v", PLAIN, ids=PLAIN_IDS)
@pytest.mark.parametrize("carch,flags", [("armv7", ARMV7), ("aarch64", AARCH64), ("x86_64", "")])
def test_flags_reach_make_and_nothing_else_changes(tmp_path, v, carch, flags):
    cflags, cxxflags, args = _run_build(tmp_path, cl.target_path(v), carch)
    expected, base = flags.split(), DISTRO.split()
    for got in (cflags, cxxflags):
        # the distro flags first, then the CPU flags, once each and at the end
        assert got[:len(base)] == base
        assert got[len(base):len(base) + len(expected)] == expected
        rest = got[len(base) + len(expected):]
        assert not [f for f in rest if f.startswith(("-O", "-flto", "-march", "-mtune", "-mfpu", "-mcpu"))]
        assert sum(f.startswith("-mcpu") for f in got) == (1 if expected else 0)
    # the make command line is the one of the upstream aport (no extra variables)
    assert args == _run_build(tmp_path, cl.upstream_path(v.upstream), carch)[2]
    assert not [a for a in args if a.startswith(("CFLAGS=", "CXXFLAGS=", "USE_CYCLONE", "USE_DRZ80", "ARM="))]


@pytest.mark.parametrize("v", CYCLONE, ids=CYCLONE_IDS)
def test_cyclone_builds_pass_the_assembly_cpu_cores(tmp_path, v):
    cflags, _, args = _run_build(tmp_path, cl.target_path(v), "armv7")
    assert cflags[-4:] == ARMV7.split()
    upstream_args = _run_build(tmp_path, cl.upstream_path(v.upstream), "armv7")[2]
    assert args[:len(upstream_args)] == upstream_args
    # mame2000 needs ARM=1 (the board platforms of its Makefile set it together with the
    # assembly cores); the mame2003-plus Makefile reads it only inside its board platforms
    assert args[len(upstream_args):] == (["ARM=1"] if v.upstream == "libretro-mame2000" else []) + [
        "USE_CYCLONE=1", "USE_DRZ80=1"]
    assert aport_arches(cl.target_path(v)) == ["armv7"]


# --- package(): library and info file ---

def _package(tmp_path, v, carch, info_text=INFO, readelf=None):
    """Run package() of the generated APKBUILD with a stub upstream package() and an info
    folder in the test directory; returns the process and $pkgdir."""
    pkgdir, infodir = tmp_path / "pkg", tmp_path / "info"
    infodir.mkdir()
    core = re.search(r'^_lume_core="(\w+)"$', cl.target_path(v).read_text(), re.M).group(1)
    (infodir / f"{core}_libretro.info").write_text(info_text)
    script = (
        'error() { echo "error: $*" >&2; }\n'
        f'pkgdir="{pkgdir}"\n'
        '. "$1"\n'
        f'_lume_infodir="{infodir}"\n'
        # the upstream package() only matters for the library it installs
        '_upstream_package() { mkdir -p "$pkgdir"/usr/lib/libretro; '
        f'echo so > "$pkgdir"/usr/lib/libretro/{core}_libretro.so; }}\n'
        'package\n'
    )
    run = subprocess.run(["sh", "-c", script, "sh", str(cl.target_path(v))],
                         env={"CARCH": carch, "PATH": f"{_bin(tmp_path, readelf)}:/usr/bin:/bin"},
                         capture_output=True, text=True)
    return run, pkgdir


def test_package_renames_the_library_and_writes_the_info(tmp_path):
    v = PLAIN[0]
    run, pkgdir = _package(tmp_path, v, "aarch64")
    assert run.returncode == 0, run.stderr
    ident = cl.lume_id(v)
    assert [p.name for p in (pkgdir / "usr/lib/libretro").iterdir()] == [f"{ident}_libretro.so"]
    lines = (pkgdir / "usr/share/libretro/info" / f"{ident}_libretro.info").read_text().splitlines()
    assert lines == ['display_name = "Nintendo - NES (FCEUmm) (Lume)"', 'corename = "FCEUmm (Lume)"',
                     'supported_extensions = "nes|fds"']      # nothing else of the info changes


def test_cyclone_info_names_the_variant(tmp_path):
    v = CYCLONE[0]
    run, pkgdir = _package(tmp_path, v, "x86_64")
    assert run.returncode == 0, run.stderr
    lines = (pkgdir / "usr/share/libretro/info" / f"{cl.lume_id(v)}_libretro.info").read_text().splitlines()
    assert 'corename = "FCEUmm (Lume, Cyclone)"' in lines


def test_info_without_corename_fails_the_package(tmp_path):
    run, _ = _package(tmp_path, PLAIN[0], "x86_64", info_text='display_name = "x"\n')
    assert run.returncode != 0 and "no corename" in run.stderr


def test_armv7_package_needs_neon(tmp_path):
    run, _ = _package(tmp_path, PLAIN[0], "armv7", readelf=f"echo '{NEON}'")
    assert run.returncode == 0, run.stderr
    (tmp_path / "b").mkdir()
    run, _ = _package(tmp_path / "b", PLAIN[0], "armv7", readelf="echo '  Tag_CPU_arch: v7'")
    assert run.returncode != 0 and "no NEON" in run.stderr


def test_cyclone_package_needs_the_assembly_cpu_cores(tmp_path):
    run, _ = _package(tmp_path, CYCLONE[0], "armv7",
                      readelf=f"echo '{NEON}'; echo '0: CycloneRun'; echo '1: DrZ80Run'")
    assert run.returncode == 0, run.stderr
    (tmp_path / "b").mkdir()
    run, _ = _package(tmp_path / "b", CYCLONE[0], "armv7", readelf=f"echo '{NEON}'")
    assert run.returncode != 0 and "CycloneRun is not in" in run.stderr


# --- lists, fixtures, pins ---

def test_arch_and_placement_in_the_lists():
    common = _lines(REPO_ROOT / "rootfs/packages.txt")
    ga36 = _lines(REPO_ROOT / "board/ga36/hw-packages.txt")
    r36s = _lines(REPO_ROOT / "board/r36s/hw-packages.txt")
    for v in PLAIN:
        # the arch of the upstream aport (all: x86_64 is the upstream build, not built)
        assert aport_arches(cl.target_path(v)) == aport_arches(cl.upstream_path(v.upstream))
        assert v.package in common
    ga36_text = (REPO_ROOT / "board/ga36/hw-packages.txt").read_text()
    for v in CYCLONE:
        assert v.package not in common and v.package not in r36s
        if v.package in cl.SUSPENDED:
            # out of the image for a recorded reason, the line kept commented out
            assert v.package not in ga36 and f"#{v.package}" in ga36_text
        else:
            assert v.package in ga36
    for t in ("vm", "r36s", "ga36"):
        names = local_aports(get_target(t))
        assert all(v.package in names for v in PLAIN), t
        assert all((v.package in names) is (t == "ga36") for v in CYCLONE), t
    # the upstream copies of the Alpine cores are not aports
    assert not [n for n in local_aports() if n.startswith("_")]


def test_corename_fixture_has_the_lume_names():
    names = _corenames()
    for v in cl.VARIANTS:
        base = names[cl.core_id(_upstream(v))]
        assert names[cl.lume_id(v)] == f"{base} ({v.label})", v.package


def test_the_four_alpine_cores_are_pinned_to_the_commit_the_image_has_today():
    pinned = {"libretro-fceumm": "449db5de6b56e9d44fc685e1b38399f0b233bd28",
              "libretro-nestopia": "5b56b6b98ed5f0d7871be4c957fc9d39a608a7c0",
              "libretro-gambatte": "cd1e180b1edf6e6853cf4d501adac0538076de34",
              "libretro-gpsp": "b0d5d27ae51c23f514974ddffa5760f1e1d05d9b"}
    for name, commit in pinned.items():
        text = (cl.APORTS / f"{name}-lume" / "APKBUILD").read_text()
        assert f'_commit="{commit}"' in text
        assert [n for _, n in _sums(text)] == [f"{name}-lume-{commit}.tar.gz"]
        assert not (cl.APORTS / name).exists()      # Alpine keeps providing the upstream build
