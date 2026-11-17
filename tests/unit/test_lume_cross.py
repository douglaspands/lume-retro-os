"""build-speed D7 (task 9.2): lume-launcher compiled on the PC for armv7/aarch64, packaged by
abuild in the arch container. Fakes only: no podman."""

import re

import pytest

from r36os import lume, lume_cross, packages
from r36os.container import Container
from r36os.paths import REPO_ROOT
from r36os.targets import TARGETS

APKBUILD = (REPO_ROOT / "aports/lume-launcher/APKBUILD").read_text()


@pytest.fixture(autouse=True)
def _scratch(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    monkeypatch.delenv(lume_cross.CROSS_ENV, raising=False)


def test_cross_is_the_default_for_the_consoles_only(monkeypatch):
    assert lume_cross.enabled("armv7") and lume_cross.enabled("aarch64")
    assert not lume_cross.enabled("x86_64")      # abuild is native there already
    monkeypatch.setenv(lume_cross.CROSS_ENV, "0")  # fallback: cargo under qemu
    assert not lume_cross.enabled("armv7") and not lume_cross.enabled("aarch64")


@pytest.mark.parametrize("arch", ["armv7", "aarch64"])
def test_script_uses_the_alpine_toolchain_of_the_target(arch):
    s = lume_cross.script(arch)
    triple = lume_cross.TRIPLES[arch]
    var = triple.upper().replace("-", "_")
    # the x86_64 rustc with the target std of the same rust release
    assert "apk add -U -q rust cargo clang binutils-$A" in s
    assert "apk fetch -q --root $S --arch $A $REPOS -o /tmp/fetch rust" in s
    assert "/tmp/fetch/$XV.apk" in s and "usr/lib/rustlib/$T" in s
    # the sysroot without emulation, with the local repository key
    assert "--initdb" in s and "--no-scripts" in s and "--arch $A" in s
    assert "r36os.rsa.pub $S/etc/apk/keys/" in s
    for p in ("musl-dev", "gcc", "sdl2-dev"):
        assert p in s
    # clang drives the GNU ld of binutils-<arch>, against the sysroot
    assert '--target=$T --sysroot=$S --ld-path=/usr/bin/$T-ld' in s
    assert f"export CARGO_TARGET_{var}_LINKER=lume-cc" in s
    assert "PKG_CONFIG_SYSROOT_DIR=$S" in s and "PKG_CONFIG_LIBDIR=$S/usr/lib/pkgconfig" in s
    # the flags of a native abuild build of that arch
    assert ". /tmp/abuild/usr/share/abuild/default.conf" in s
    assert f"T={triple}\n" in s
    assert "cargo build --release --offline --frozen --target $T" in s


def test_script_builds_where_abuild_builds():
    # the same workspace path as the native build: no new path in the binaries
    assert lume_cross.WORKSPACE_GUEST == f"/aports/{packages.REPO_NAME}/lume-launcher/stage/lume"
    assert 'builddir="$startdir/stage/lume"' in APKBUILD
    assert f"cd {lume_cross.WORKSPACE_GUEST}\n" in lume_cross.script("armv7")


def test_script_does_not_depend_on_jobs(monkeypatch):
    monkeypatch.setenv("R36OS_JOBS", "2")
    a = lume_cross.script("armv7")
    monkeypatch.setenv("R36OS_JOBS", "7")
    assert lume_cross.script("armv7") == a


def test_cross_target_is_not_the_native_cargo_cache():
    for arch in lume_cross.TRIPLES:
        assert lume_cross.target_dir(arch) != lume.target_cache(arch)
    assert lume_cross.target_dir("armv7") != lume_cross.target_dir("aarch64")


def test_build_mode_enters_the_inputs(monkeypatch):
    cross = packages._fragment_script("armv7", "lume-launcher")
    other = packages._fragment_script("armv7", "retroarch")
    monkeypatch.setenv(lume_cross.CROSS_ENV, "0")
    assert packages._fragment_script("armv7", "lume-launcher") != cross
    assert packages._fragment_script("armv7", "retroarch") == other
    assert lume_cross.script("armv7") not in packages._fragment_script("x86_64", "lume-launcher")


def test_packaging_installs_only_what_it_needs(monkeypatch):
    s = packages._package_script("armv7", "lume-launcher", "c" * 40)
    assert "apk add -q sdl2 font-roboto\n" in s
    assert "abuild -F -d -P /repodest" in s and "abuild -F -r" not in s
    assert "ABUILD_LAST_COMMIT=" + "c" * 40 in s
    # the prebuilt makedepends of the APKBUILD are installed by the script
    m = re.search(r'\|\| makedepends="([^"]*)"', APKBUILD)
    assert set(m.group(1).split()) <= set(lume_cross.PACKAGE_DEPS)
    # every other fragment keeps the script (and so the inputs) it had
    for arch, name in (("armv7", "retroarch"), ("x86_64", "lume-launcher")):
        assert packages._fragment_script(arch, name) == (
            packages._KEY + packages._local_repo(arch)
            + f"(cd /aports/r36os/{name} && abuild -F -r -P /repodest)\n")
    monkeypatch.setenv(lume_cross.CROSS_ENV, "0")
    assert "abuild -F -r -P" in packages._package_script("armv7", "lume-launcher")


def test_aport_packages_prebuilt_binaries():
    assert re.search(r'^\[ -z "\$\{LUME_PREBUILT:-\}" \] \|\| makedepends="font-roboto"$',
                     APKBUILD, re.M)
    assert re.search(r'^makedepends="cargo sdl2-dev font-roboto"$', APKBUILD, re.M)
    assert 'install -Dm755 "$LUME_PREBUILT"/$b "$pkgdir"/usr/bin/$b' in APKBUILD
    assert "install -Dm755 target/release/$b" in APKBUILD   # the native fallback
    assert lume_cross.PREBUILT_ENV == "LUME_PREBUILT"


def _fake_fragment(monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(packages, "_inputs", lambda *a, **k: "a" * 64)
    monkeypatch.setattr(packages, "_up_to_date", lambda *a: False)
    monkeypatch.setattr(packages, "_adopt", lambda *a: False)
    monkeypatch.setattr(packages, "_next_pkgrel", lambda *a: 1)
    monkeypatch.setattr(packages, "ensure_builder", lambda t: "builder")
    monkeypatch.setattr(packages, "_settle", lambda *a, **k: [])
    monkeypatch.setattr(Container, "sh", lambda self, script, **kw: seen.append(self))
    prebuilt = tmp_path / "prebuilt"
    monkeypatch.setattr(lume_cross, "build",
                        lambda arch, aports: seen.append(("cross", arch)) or prebuilt)
    return seen, prebuilt


def test_console_fragment_is_cross_built_then_packaged(monkeypatch, tmp_path):
    seen, prebuilt = _fake_fragment(monkeypatch, tmp_path)
    packages._build_fragment(TARGETS["ga36"], "lume-launcher", REPO_ROOT / "aports", True,
                             cargo=True)
    assert seen[0] == ("cross", "armv7")
    c = seen[1]
    assert c.volumes[prebuilt] == lume_cross.GUEST_PREBUILT
    assert c.env[lume_cross.PREBUILT_ENV] == lume_cross.GUEST_PREBUILT
    # cargo does not run in the emulated container: no native cargo target mounted
    assert lume_cross.WORKSPACE_GUEST + "/target" not in c.volumes.values()


def test_fallback_builds_under_qemu_with_the_cargo_cache(monkeypatch, tmp_path):
    seen, _ = _fake_fragment(monkeypatch, tmp_path)
    monkeypatch.setenv(lume_cross.CROSS_ENV, "0")
    packages._build_fragment(TARGETS["r36s"], "lume-launcher", REPO_ROOT / "aports", True,
                             cargo=True)
    assert len(seen) == 1 and not isinstance(seen[0], tuple)
    c = seen[0]
    assert lume_cross.PREBUILT_ENV not in c.env
    assert c.volumes[lume.target_cache("aarch64")] == lume_cross.WORKSPACE_GUEST + "/target"
