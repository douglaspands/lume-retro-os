"""Stage 2: local Alpine packages (abuild) and the local repository `out/repo/<arch>`."""

from __future__ import annotations

import gzip
import os
import shutil
import tarfile
from pathlib import Path

from r36os import jobs, manifests
from r36os.container import Container, ensure_builder
from r36os.paths import REPO_ROOT, cache_dir, ensure_dir, out_dir
from r36os.targets import Target

KEY_NAME = "r36os"
REPO_NAME = "r36os"  # abuild writes to $REPODEST/<parent dir name>/<arch>
NO_CCACHE_ENV = "R36OS_CCACHE"  # "0": compile everything (timing and distcc proofs)


def aport_arches(apkbuild: Path) -> list[str]:
    """The arch= value of the APKBUILD (e.g. ['all', '!armv7'])."""
    for line in apkbuild.read_text().splitlines():
        if line.startswith("arch="):
            return line.split("=", 1)[1].strip().strip('"').split()
    return ["all"]


def builds_for(apkbuild: Path, arch: str) -> bool:
    arches = aport_arches(apkbuild)
    if f"!{arch}" in arches:
        return False
    return any(a in ("all", "noarch", arch) for a in arches)


def local_aports(target: Target | None = None) -> list[str]:
    """Packages in aports/ (each subdirectory with an APKBUILD), in a stable order.

    With `target`, only those allowed by the APKBUILD arch= (the local mesa is x86_64 only).
    """
    found = sorted((REPO_ROOT / "aports").glob("*/APKBUILD"))
    return [p.parent.name for p in found
            if target is None or builds_for(p, target.alpine_arch)]


def keys_dir() -> Path:
    return cache_dir() / "abuild"


def repo_dir(target: Target) -> Path:
    return out_dir() / "repo" / target.alpine_arch


def public_key() -> Path:
    return keys_dir() / f"{KEY_NAME}.rsa.pub"


def _container(target: Target, aports: Path, cargo_target: bool = False,
               repodest: Path | None = None, distcc: bool = False) -> Container:
    """The abuild container of the target architecture.

    With `cargo_target`, the cargo `target/` of lume-launcher is `.cache/cargo/<arch>`,
    mounted where the APKBUILD builds (`stage/lume/target`), so the path cargo and rustc
    see is the one of a build without the cache (build-speed D7). One folder per
    architecture: armv7, aarch64 and x86_64 never share artifacts. `repodest` is where
    abuild writes the packages (default `out/repo`; noarch fragments use a staging area).
    With `distcc`, compiles go to the x86 cross gcc through distcc (build-speed D7, P-36),
    with their own ccache until the P-36 proof shows equal objects.
    """
    cache = cache_dir()
    repodest = repodest or out_dir() / "repo"
    ensure_dir(keys_dir())
    ensure_dir(cache / "distfiles")
    ccache = cache / "ccache" / (target.alpine_arch + ("-distcc" if distcc else ""))
    ensure_dir(ccache)
    ensure_dir(repodest)
    env = {"REPODEST": "/repodest", "CCACHE_DIR": "/cache/ccache", "USE_CCACHE": "1",
           "JOBS": str(jobs.jobs()), "MAKEFLAGS": f"-j{jobs.jobs()}"}
    if os.environ.get(NO_CCACHE_ENV) == "0":
        env["CCACHE_DISABLE"] = "1"  # ccache still runs CCACHE_PREFIX (distcc)
    if distcc:
        from r36os import distcc as dcc
        env.update(dcc.client_env(target.alpine_arch, jobs.jobs()))
    volumes = {
        aports: f"/aports/{REPO_NAME}",
        repodest: f"/repodest/{REPO_NAME}",
        keys_dir(): "/root/.abuild",
        cache / "distfiles": "/cache/distfiles",
        ccache: "/cache/ccache",
    }
    if cargo_target:
        from r36os import lume
        volumes[ensure_dir(lume.target_cache(target.alpine_arch))] = (
            f"/aports/{REPO_NAME}/lume-launcher/stage/lume/target")
    return Container(
        image=ensure_builder(target),
        platform=target.oci_platform,
        volumes=volumes,
        # USE_CCACHE=1: without it abuild does not put /usr/lib/ccache/bin in PATH, and
        # under emulation (ARM) each rebuild would take hours
        env=env,
    )


_KEY = f"""
if [ ! -f /root/.abuild/{KEY_NAME}.rsa ]; then
  openssl genrsa -out /root/.abuild/{KEY_NAME}.rsa 4096
  openssl rsa -in /root/.abuild/{KEY_NAME}.rsa -pubout -out /root/.abuild/{KEY_NAME}.rsa.pub
fi
echo 'PACKAGER_PRIVKEY=/root/.abuild/{KEY_NAME}.rsa' > /root/.abuild/abuild.conf
echo "export JOBS=$JOBS MAKEFLAGS=-j$JOBS" >> /root/.abuild/abuild.conf
cp /root/.abuild/{KEY_NAME}.rsa.pub /etc/apk/keys/
"""
_SETUP_KEY = _KEY + "apk update -q\n"


def ensure_key(target: Target) -> Path:
    """Generate the abuild signing key in the cache (once, shared by all arches)."""
    _container(target, REPO_ROOT / "aports").sh(_SETUP_KEY)
    return public_key()


def build_packages(
    target: Target, names: list[str], aports: Path | None = None, checksum: bool = False,
    force: bool = False,
) -> list[Path]:
    """Build the `aports/<name>` packages for the target architecture (build-speed D3).

    Each aport is compiled only when its inputs hash differs from the one in
    out/repo/<arch>/hashes.json (or with `force`), and published only when the content of
    what it built differs from the newest published version, with the next pkgrel. At the
    end, old versions leave out/repo/<arch>/. Returns the published .apk files.

    With `checksum=True`, only update the APKBUILD sha512sums (abuild checksum).
    """
    aports = aports or REPO_ROOT / "aports"
    lume_staged = "lume-launcher" in names and not checksum and aports == REPO_ROOT / "aports"
    if lume_staged:
        # the Rust workspace and its vendored crates (abuild only sees aports/)
        from r36os import lume
        lume.stage()
    # R36OS_DISTCC (build-speed D7, P-36): the chosen packages compile through distcc
    from r36os import distcc as dcc
    if checksum:
        script = _SETUP_KEY + "".join(
            f"(cd /aports/{REPO_NAME}/{n} && abuild -F checksum)\n" for n in names)
        _container(target, aports).sh(script)
        return []
    chosen = dcc.selected()
    arch = target.alpine_arch
    published: list[Path] = []
    for n in _order(aports, names):
        published += _build_fragment(
            target, n, aports, force,
            distcc=dcc.uses_distcc(n, arch, chosen),
            cargo=lume_staged and n == "lume-launcher")
    if clean_repo(arch):
        reindex([arch])
    return published


# --- inputs and content (build-speed D3, task 6.1) -------------------------------------
#
# A fragment is compiled in a staging repository (out/pkg-staging/<arch>/) with a generated
# copy of its APKBUILD (pkgrel replaced) mounted over the committed one, and with the
# inputs hash in ABUILD_LAST_COMMIT (abuild writes it as `commit` in .PKGINFO). What it
# built is compared by content with the newest published version; only a different content
# is published: its control area gets `.lume-content`, it is signed again and copied to
# out/repo/<arch>/, and hashes.json records version, inputs, content and file.

STAGING = "pkg-staging"


def staging_dir() -> Path:
    return out_dir() / STAGING


def hashes_path(arch: str) -> Path:
    return arch_repo_dir(arch) / manifests.HASHES_FILE


def read_repo_hashes(arch: str) -> manifests.RepoHashes:
    return manifests.read_hashes(hashes_path(arch), arch)


def _builder_identity() -> str:
    """The recipe of the builder image: the Alpine release and its Containerfile."""
    from r36os.container import ALPINE_VERSION
    recipe = REPO_ROOT / "containers/builder.Containerfile"
    return f"alpine {ALPINE_VERSION}\n" + (recipe.read_text() if recipe.exists() else "")


def _local_repo(arch_dir: str) -> str:
    """Script lines: the published local packages (out/repo) as an apk repository."""
    return (f"if [ -f /localrepo/{arch_dir}/APKINDEX.tar.gz ]; then\n"
            "  echo /localrepo >> /etc/apk/repositories\nfi\n"
            "apk update -q\n")


def _abuild_step(name: str, commit: str = "", nodeps: bool = False) -> str:
    """`nodeps`: no dependency install or check (-d instead of -r). For the noarch fragments,
    which only copy files: their `depends` (other fragments, built in the same call and not
    yet published) are runtime dependencies, nothing to build with."""
    env = f"ABUILD_LAST_COMMIT={commit} " if commit else ""
    deps = "-d" if nodeps else "-r"
    return f"(cd /aports/{REPO_NAME}/{name} && {env}abuild -F {deps} -P /repodest)\n"


def _fragment_script(arch_dir: str, name: str, nodeps: bool = False) -> str:
    """The build script of one fragment, as hashed into its inputs (no commit, no distcc:
    neither changes what is built)."""
    return _KEY + _local_repo(arch_dir) + _abuild_step(name, nodeps=nodeps)


def _order(aports: Path, names: list[str]) -> list[str]:
    from r36os import fragments as frag
    # abuild -r installs `depends` too before building, so a fragment depending on another
    # local one (lume-net on lume-core) is built after it; only the order, not the inputs
    deps = {}
    for n in names:
        text = (aports / n / "APKBUILD").read_text()
        deps[n] = list(dict.fromkeys(frag.build_deps(text) + frag.runtime_deps(text)))
    return frag.build_order(names, deps)


def _inputs(aports: Path, name: str, arch_dir: str, dep_arch: str,
            built_now: dict[str, str] | None = None, nodeps: bool = False) -> str:
    """The inputs hash of `name`. Local build deps count by content: from hashes.json of
    `dep_arch`, or `built_now` for those built earlier in the same call."""
    from r36os import fragments as frag
    text = (aports / name / "APKBUILD").read_text()
    local_names = [p.parent.name for p in aports.glob("*/APKBUILD")]
    hashes = read_repo_hashes(dep_arch)
    for n, content in (built_now or {}).items():
        if n in hashes.packages:
            p = hashes.packages[n]
            hashes.packages[n] = manifests.PackageHashes(p.version, p.inputs, content, p.file)
        else:
            hashes.packages[n] = manifests.PackageHashes("0-r0", "0" * 64, content,
                                                         f"{n}-0-r0.apk")
    deps = frag.local_dep_contents(frag.build_deps(text), hashes, local_names)
    return manifests.inputs_hash(frag.fragment_inputs(
        aports / name, _fragment_script(arch_dir, name, nodeps), _builder_identity(), deps))


def _up_to_date(name: str, inputs: str, arches: list[str] | tuple[str, ...]) -> bool:
    """hashes.json of every arch has `name` built from these inputs, its files present."""
    for a in arches:
        h = read_repo_hashes(a)
        p = h.packages.get(name)
        if p is None or p.inputs != inputs:
            return False
        for p2 in h.packages.values():   # the subpackages of the same build
            if p2.inputs == inputs and not (arch_repo_dir(a) / p2.file).exists():
                return False
    return True


def _adopt(aports: Path, name: str, inputs: str,
           arches: list[str] | tuple[str, ...]) -> bool:
    """First build after hashes.json existed: adopt what is already published, no build.

    When no arch has an entry for `name` and every package of the aport (subpackages
    too) has its newest version published in every arch, with the APKBUILD pkgver, the
    same version for all of them and a pkgrel not below the APKBUILD one, hashes.json
    records the current inputs and the content of those files. Nothing is compiled
    (RetroArch and the cores under qemu would take hours, P-80).
    """
    from r36os import fragments as frag
    text = (aports / name / "APKBUILD").read_text()
    pkgs = frag.apkbuild_packages(text, f"{name}/APKBUILD")
    if pkgs is None:
        return False
    pkgver, minimum = frag.apkbuild_version(text, f"{name}/APKBUILD")
    hashes = {a: read_repo_hashes(a) for a in arches}
    if any(name in h.packages for h in hashes.values()):
        return False
    newest = {}
    for a in arches:
        files = frag.apk_files(arch_repo_dir(a))
        for p in pkgs:
            if not files.get(p):
                return False
            newest[(a, p)] = files[p][0]
    versions = {f.version for f in newest.values()}
    main = newest[(arches[0], name)]
    if versions != {main.version} or main.pkgver != pkgver or main.pkgrel < minimum:
        return False
    entries = {}
    for p in pkgs:
        apk = newest[(arches[0], p)].path
        content = frag.apk_lume_content(apk) or frag.apk_content_hash(apk)
        entries[p] = manifests.PackageHashes(main.version, inputs, content, apk.name)
    _record(arches, entries)
    print(f"pkg {name}: adopted {main.path.name} (no build)", flush=True)
    return True


def _next_pkgrel(aports: Path, name: str, arches: list[str] | tuple[str, ...]) -> int:
    from r36os import fragments as frag
    pkgver, minimum = frag.apkbuild_version((aports / name / "APKBUILD").read_text(),
                                            f"{name}/APKBUILD")
    hashes = [read_repo_hashes(a) for a in arches]
    names = {name} | {n for h in hashes for n, p in h.packages.items()
                      if name in h.packages and p.inputs == h.packages[name].inputs}
    return frag.next_pkgrel([arch_repo_dir(a) for a in arches], names, pkgver, minimum,
                            hashes)


def _generated_apkbuild(aports: Path, name: str, pkgrel: int, tag: str) -> Path:
    """A copy of the APKBUILD with the computed pkgrel, mounted over the committed one."""
    from r36os import fragments as frag
    text = (aports / name / "APKBUILD").read_text()
    dest = ensure_dir(staging_dir() / "apkbuild" / tag / name) / "APKBUILD"
    dest.write_text(frag.with_pkgrel(text, pkgrel, f"{name}/APKBUILD"))
    return dest


def _reference(arch: str, name: str) -> tuple[str, str] | None:
    """(version, content hash) of the newest published `name` in out/repo/<arch>/."""
    from r36os import fragments as frag
    p = read_repo_hashes(arch).packages.get(name)
    if p is not None and (arch_repo_dir(arch) / p.file).exists():
        return p.version, p.content
    files = frag.apk_files(arch_repo_dir(arch)).get(name)
    if not files:
        return None
    newest = files[0].path   # published before hashes.json existed
    return files[0].version, frag.apk_lume_content(newest) or frag.apk_content_hash(newest)


def _check_built(apk: Path, version: str, commit: str) -> None:
    info = dict(read_apk_pkginfo(apk))
    if info.get("pkgver") != version or info.get("commit") != commit:
        raise RuntimeError(f"{apk.name}: built as {info.get('pkgver')} with commit "
                           f"{info.get('commit')}, expected {version} and {commit}")


def _decide(built: list[Path], arches: list[str] | tuple[str, ...]
            ) -> tuple[dict[str, str], dict[str, tuple[str, str] | None]]:
    """Content hash of each built package and its published reference (first arch)."""
    from r36os import fragments as frag
    contents, refs = {}, {}
    for apk in built:
        name = dict(read_apk_pkginfo(apk))["pkgname"]
        contents[name] = frag.apk_content_hash(apk)
        ref = _reference(arches[0], name)
        # noarch: the same reference file must be in every arch, or it is published again
        if ref is not None and any(not (arch_repo_dir(a) / f"{name}-{ref[0]}.apk").exists()
                                   for a in arches):
            ref = None
        refs[name] = ref
    return contents, refs


def _record(arches, entries: dict[str, manifests.PackageHashes]) -> None:
    for a in arches:
        h = read_repo_hashes(a)
        h.packages.update(entries)
        manifests.write_hashes(hashes_path(a), h)


def _keep_unchanged(name: str, inputs: str, contents: dict[str, str],
                    refs: dict[str, tuple[str, str] | None], arches) -> None:
    """Same content: nothing published; hashes.json now maps the new inputs to the
    published file, so the next build does not compile it again."""
    _record(arches, {n: manifests.PackageHashes(refs[n][0], inputs, contents[n],
                                                f"{n}-{refs[n][0]}.apk")
                     for n in contents})
    versions = ", ".join(f"{n}-{refs[n][0]}" for n in sorted(contents))
    print(f"pkg {name}: same content as the published {versions}, not published",
          flush=True)


_SIGN = """
cd /work
for c in *.control.tar.gz; do
  n="${c%.control.tar.gz}"
  abuild-sign -q "$c"
  cat "$c" "$n.data.tar.gz" > "$n.signed"
done
"""


def sign_with_lume_content(apks: list[tuple[Path, str]], tag: str) -> None:
    """Rewrite each built .apk with `.lume-content` (its content hash) in the control area
    and sign it again with the local key (x86_64 builder, abuild-sign). In place."""
    from r36os import fragments as frag
    if not apks:
        return
    work = staging_dir() / f"sign-{tag}"
    shutil.rmtree(work, ignore_errors=True)
    ensure_dir(work)
    parts = {}
    for apk, content in apks:
        ctl, data = frag.control_with_lume_content(apk, content)
        (work / f"{apk.name}.control.tar.gz").write_bytes(ctl)
        (work / f"{apk.name}.data.tar.gz").write_bytes(data)
        parts[apk] = (ctl, data, content)
    c = _container(NOARCH_BUILD_TARGET, REPO_ROOT / "aports")
    c.volumes[work] = "/work"
    c.sh(_KEY + _SIGN)
    for apk, (ctl, data, content) in parts.items():
        signed = work / f"{apk.name}.signed"
        got = frag.split_apk(signed)
        if (got.control != ctl or got.data != data or not got.signature
                or frag.apk_lume_content(signed) != content):
            raise RuntimeError(f"{apk.name}: the signed package does not match its parts")
        signed.replace(apk)
    shutil.rmtree(work, ignore_errors=True)


def _build_fragment(target: Target, name: str, aports: Path, force: bool,
                    distcc: bool = False, cargo: bool = False) -> list[Path]:
    """Inputs -> maybe compile -> compare content -> maybe publish one arch fragment."""
    arch = target.alpine_arch
    arches = [arch]
    inputs = _inputs(aports, name, arch, arch)
    if not force and _up_to_date(name, inputs, arches):
        print(f"pkg {name} ({arch}): inputs unchanged, not built", flush=True)
        return []
    if not force and _adopt(aports, name, inputs, arches):
        return []
    pkgrel = _next_pkgrel(aports, name, arches)
    commit = manifests.commit_of_inputs(inputs)
    staging = staging_dir()
    shutil.rmtree(staging / arch, ignore_errors=True)
    c = _container(target, aports, cargo_target=cargo, repodest=staging, distcc=distcc)
    c.volumes[_generated_apkbuild(aports, name, pkgrel, arch)] = (
        f"/aports/{REPO_NAME}/{name}/APKBUILD")
    c.volumes[ensure_dir(out_dir() / "repo")] = "/localrepo"
    # abuild -r installs the dependencies (Alpine and the published local ones)
    script = (_KEY + _local_repo(arch) + ("apk add -q distcc\n" if distcc else "")
              + _abuild_step(name, commit))
    if distcc:
        from r36os import distcc as dcc
        with dcc.distccd(arch):
            c.sh(script)
    else:
        c.sh(script)
    return _settle(name, inputs, sorted((staging / arch).glob("*.apk")), arches, arch)


INPUTS_SIDECAR = ".inputs"   # <apk>.inputs in the noarch staging: its full inputs hash


def _settle(name: str, inputs: str, built: list[Path], arches, tag: str,
            publish: bool = True, contents_out: dict[str, str] | None = None) -> list[Path]:
    """Publish what `name` built when its content changed; else only record the inputs.

    With `publish=False` (noarch), the changed packages are only signed in the staging
    area, with their inputs hash in `<apk>.inputs`, and returned for publish_noarch.
    `contents_out` receives the content hash of each built package.
    """
    if not built:
        raise RuntimeError(f"pkg {name}: abuild produced no .apk")
    commit = manifests.commit_of_inputs(inputs)
    version = dict(read_apk_pkginfo(built[0]))["pkgver"]
    for apk in built:
        _check_built(apk, version, commit)
    contents, refs = _decide(built, arches)
    if contents_out is not None:
        contents_out.update(contents)
    if all(refs[n] is not None and refs[n][1] == contents[n] for n in contents):
        _keep_unchanged(name, inputs, contents, refs, arches)
        return []
    sign_with_lume_content([(apk, contents[dict(read_apk_pkginfo(apk))["pkgname"]])
                            for apk in built], tag)
    if not publish:
        for apk in built:
            apk.with_name(apk.name + INPUTS_SIDECAR).write_text(inputs + "\n")
        return built
    published = [_copy_identical(apk, arch_repo_dir(a)) for a in arches for apk in built]
    _record(arches, {n: manifests.PackageHashes(version, inputs, contents[n],
                                                f"{n}-{version}.apk") for n in contents})
    reindex(list(arches))
    print(f"pkg {name}: published " + ", ".join(a.name for a in built), flush=True)
    return published


def clean_repo(arch: str) -> bool:
    """Remove old versions from out/repo/<arch>/ (build-speed D3): keep the newest and the
    previous of each package, every version a kept build cites (latest, flashed) and every
    file hashes.json names. Prints the freed space; True when something was removed (the
    index must then be rebuilt)."""
    from r36os import fragments as frag
    repo = arch_repo_dir(arch)
    protected = (frag.cited_versions(out_dir() / "images")
                 | frag.hashes_protected(read_repo_hashes(arch)))
    removed, freed = frag.remove_old_versions(repo, protected)
    print(f"repo {arch}: removed {len(removed)} old package file(s), "
          f"freed {frag.human_size(freed)}", flush=True)
    return bool(removed)


# --- noarch fragments (build-speed D2) -------------------------------------------------
#
# A noarch fragment is built once, by abuild in the x86_64 builder (no qemu), and the SAME
# .apk file is copied into out/repo/<arch>/ for every arch. abuild writes `arch = noarch` in
# .PKGINFO; each APKINDEX is rebuilt with `apk index --rewrite-arch <arch>` (as abuild does
# for its own repo), so the index says `A:<arch>`. apk fetches a package from
# <repo>/<index arch>/, so an index saying `A:noarch` would send it to <repo>/noarch/ and
# fail with "package mentioned in index not found". The .apk signature (.SIGN.RSA) covers
# the control segment and does not depend on the arch, so one signed file serves all arches.

NOARCH_BUILD_TARGET = Target("noarch", "x86_64", "linux/amd64", "noarch fragments (PC)")
REPO_ARCHES = ("armv7", "aarch64", "x86_64")
ELF_MAGIC = b"\x7fELF"


class NoarchError(RuntimeError):
    """A noarch fragment that cannot be published (ELF inside, wrong arch, collision)."""


def arch_repo_dir(arch: str) -> Path:
    return out_dir() / "repo" / arch


def noarch_staging_dir() -> Path:
    """Where abuild drops the noarch build (<staging>/x86_64/*.apk) before the checks."""
    return out_dir() / "noarch"


def is_noarch_aport(apkbuild: Path) -> bool:
    return aport_arches(apkbuild) == ["noarch"]


def _is_elf(head: bytes) -> bool:
    return head[:4] == ELF_MAGIC


def elf_files_in_dir(root: Path) -> list[str]:
    """Regular files under `root` that start with the ELF magic (relative paths, sorted)."""
    found = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and not p.is_symlink():
            with p.open("rb") as f:
                if _is_elf(f.read(4)):
                    found.append(p.relative_to(root).as_posix())
    return found


def _apk_stream(apk: Path):
    """The tar members of an .apk (v2: signature, control and data gzip streams in a row,
    the first two without end-of-archive blocks, so they read as one tar)."""
    with gzip.open(apk, "rb") as gz, tarfile.open(fileobj=gz, mode="r|") as tf:
        for m in tf:
            head = b""
            if m.isreg():
                f = tf.extractfile(m)
                head = f.read(4) if f else b""
            yield m, head


def read_apk_pkginfo(apk: Path) -> list[tuple[str, str]]:
    """(key, value) pairs of the .PKGINFO inside an .apk."""
    with gzip.open(apk, "rb") as gz, tarfile.open(fileobj=gz, mode="r|") as tf:
        for m in tf:
            if m.name == ".PKGINFO":
                f = tf.extractfile(m)
                return manifests.parse_pkginfo(f.read().decode() if f else "")
    raise NoarchError(f"{apk.name}: no .PKGINFO")


def elf_files_in_apk(apk: Path) -> list[str]:
    """Data files of an .apk that are ELF (control files, which start with '.', skipped)."""
    return sorted(m.name for m, head in _apk_stream(apk)
                  if not m.name.startswith(".") and _is_elf(head))


def check_noarch_apk(apk: Path, fragment: str) -> None:
    """Fail unless `apk` is a noarch package without ELF files, naming fragment and file."""
    arch = dict(read_apk_pkginfo(apk)).get("arch")
    if arch != "noarch":
        raise NoarchError(f"fragment {fragment}: {apk.name} has arch={arch}, not noarch")
    elf = elf_files_in_apk(apk)
    if elf:
        raise NoarchError(f"noarch fragment {fragment} contains ELF file(s): "
                          + ", ".join(elf) + f" (in {apk.name})")


def check_noarch_aport(aport_dir: Path) -> None:
    """Before the build: the aport must say arch="noarch" and ship no ELF file."""
    fragment = aport_dir.name
    if not is_noarch_aport(aport_dir / "APKBUILD"):
        raise NoarchError(f"fragment {fragment}: APKBUILD arch is not \"noarch\"")
    elf = elf_files_in_dir(aport_dir)
    if elf:
        raise NoarchError(f"noarch fragment {fragment} contains ELF file(s): "
                          + ", ".join(elf))


def build_noarch(names: list[str], aports: Path | None = None,
                 force: bool = False) -> list[Path]:
    """Build the noarch `aports/<name>` fragments in the x86_64 builder and check them.

    Like build_packages (build-speed D3): a fragment whose inputs match hashes.json of
    every arch is not built (unless `force`), and one whose content matches the published
    version is not returned. Returns the changed .apk files, signed with `.lume-content`,
    in the staging dir; nothing is published yet (publish_noarch). Fails with NoarchError
    if a fragment is not noarch or contains an ELF file.
    """
    aports = aports or REPO_ROOT / "aports"
    for n in names:
        check_noarch_aport(aports / n)
    staging = noarch_staging_dir()
    build_arch = NOARCH_BUILD_TARGET.alpine_arch
    shutil.rmtree(staging / build_arch, ignore_errors=True)
    out: list[Path] = []
    built_now: dict[str, str] = {}
    for n in _order(aports, names):
        inputs = _inputs(aports, n, build_arch, build_arch, built_now, nodeps=True)
        if not force and _up_to_date(n, inputs, REPO_ARCHES):
            print(f"pkg {n} (noarch): inputs unchanged, not built", flush=True)
            continue
        if not force and _adopt(aports, n, inputs, REPO_ARCHES):
            continue
        before = set((staging / build_arch).glob("*.apk"))
        c = _container(NOARCH_BUILD_TARGET, aports, repodest=staging)
        c.volumes[_generated_apkbuild(aports, n, _next_pkgrel(aports, n, REPO_ARCHES),
                                      "noarch")] = f"/aports/{REPO_NAME}/{n}/APKBUILD"
        # dependencies may be other local fragments, already in out/repo/x86_64 or built
        # earlier in this call (the staging repository, which abuild -r also reads)
        c.volumes[ensure_dir(out_dir() / "repo")] = "/localrepo"
        c.sh(_KEY + _local_repo(build_arch)
             + _abuild_step(n, manifests.commit_of_inputs(inputs), nodeps=True))
        built = sorted(set((staging / build_arch).glob("*.apk")) - before)
        origins = {dict(read_apk_pkginfo(apk)).get("origin", "") for apk in built}
        if not built or origins != {n}:
            raise NoarchError(f"fragment {n}: abuild produced no .apk of its own "
                              f"({', '.join(a.name for a in built) or 'none'})")
        for apk in built:
            check_noarch_apk(apk, n)
        out += _settle(n, inputs, built, REPO_ARCHES, "noarch", publish=False,
                       contents_out=built_now)
    return out


def _copy_identical(apk: Path, dest_dir: Path) -> Path:
    """Copy `apk` into `dest_dir`; refuse a different file already under the same name."""
    dest = ensure_dir(dest_dir) / apk.name
    want = manifests.sha256_file(apk)
    if dest.exists():
        if manifests.sha256_file(dest) != want:
            raise NoarchError(f"{dest}: already published with different content")
        return dest
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.copyfile(apk, tmp)
    if manifests.sha256_file(tmp) != want:
        tmp.unlink()
        raise NoarchError(f"{dest}: copy does not match {apk}")
    tmp.replace(dest)
    return dest


_REINDEX = f"""
for a in $ARCHES; do
  cd /repodest/{REPO_NAME}/$a
  old=
  if [ -f APKINDEX.tar.gz ]; then old="--index APKINDEX.tar.gz"; fi
  apk index --no-warnings --quiet $old --output APKINDEX.tar.gz.new \\
    --description {REPO_NAME} --rewrite-arch $a *.apk
  abuild-sign -q APKINDEX.tar.gz.new
  chmod 644 APKINDEX.tar.gz.new
  mv APKINDEX.tar.gz.new APKINDEX.tar.gz
done
"""


def reindex(arches: tuple[str, ...] | list[str] = REPO_ARCHES) -> None:
    """Rebuild and sign out/repo/<arch>/APKINDEX.tar.gz (A:<arch> for every package).

    Runs in the x86_64 builder: `apk index` only reads the files, no emulation needed.
    Uses the ARCH:<arch> resource: no `r36os pkg` of that arch may run at the same time.
    """
    c = _container(NOARCH_BUILD_TARGET, REPO_ROOT / "aports")
    c.env["ARCHES"] = " ".join(arches)
    c.sh(_KEY + _REINDEX)


def publish_noarch(apks: list[Path], arches: tuple[str, ...] = REPO_ARCHES) -> list[Path]:
    """Publish the same .apk files in out/repo/<arch>/ for every arch and reindex them.

    A package built by build_noarch (with `<apk>.inputs` next to it) also enters
    hashes.json of every arch; old versions then leave each arch (clean_repo).
    """
    from r36os import fragments as frag
    for apk in apks:
        check_noarch_apk(apk, dict(read_apk_pkginfo(apk)).get("origin", apk.name))
    published = [_copy_identical(apk, arch_repo_dir(a)) for a in arches for apk in apks]
    entries = {}
    for apk in apks:
        sidecar = apk.with_name(apk.name + INPUTS_SIDECAR)
        if not sidecar.exists():
            continue
        info = dict(read_apk_pkginfo(apk))
        content = frag.apk_lume_content(apk) or frag.apk_content_hash(apk)
        entries[info["pkgname"]] = manifests.PackageHashes(
            info["pkgver"], sidecar.read_text().strip(), content, apk.name)
    if entries:
        _record(arches, entries)
    for a in arches:
        clean_repo(a)
    reindex(arches)
    return published


def install_test(target: Target, name: str, aports: Path) -> str:
    """Install `name` in a clean container from the local repository; return `apk info`."""
    c = _container(target, aports)
    out = c.sh(
        _SETUP_KEY
        + f"apk add --repository /repodest/{REPO_NAME} {name} >/dev/null\n"
        + f"apk info -e {name}\n",
        capture_output=True,
        text=True,
    )
    return out.stdout
