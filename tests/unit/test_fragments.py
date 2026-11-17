"""build-speed 6.1: inputs hash, content hash, computed pkgrel and repository cleanup."""

from __future__ import annotations

import gzip
import io
import re
import tarfile
from pathlib import Path

import pytest

from r36os import fragments as frag
from r36os import manifests, packages
from r36os.targets import get_target

H1 = "1" * 64
H2 = "2" * 64


# --- helpers ----------------------------------------------------------------------------

def _tar(members: list[tuple[tarfile.TarInfo, bytes]], cut: bool) -> bytes:
    buf = io.BytesIO()
    tf = tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT)
    for info, data in members:
        tf.addfile(info, io.BytesIO(data) if info.isreg() else None)
    end = tf.offset
    tf.close()
    return buf.getvalue()[:end] if cut else buf.getvalue()


def _file(name: str, data: bytes, mode: int = 0o644, mtime: int = 1) -> tuple:
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(data), mode, mtime
    return info, data


def _dir(name: str, mode: int = 0o755) -> tuple:
    info = tarfile.TarInfo(name)
    info.type, info.mode = tarfile.DIRTYPE, mode
    return info, b""


def _link(name: str, target: str) -> tuple:
    info = tarfile.TarInfo(name)
    info.type, info.linkname, info.mode = tarfile.SYMTYPE, target, 0o777
    return info, b""


def make_apk(path: Path, name: str = "lume-x", version: str = "1.0-r0",
             files: dict[str, bytes] | None = None, commit: str = "c" * 40,
             builddate: int = 1, extra_info: str = "", modes: dict[str, int] | None = None,
             links: dict[str, str] | None = None) -> Path:
    """An .apk v2 like abuild writes: signature, control (.PKGINFO) and data segments."""
    files = {"usr/share/x/readme": b"hi\n"} if files is None else files
    modes = modes or {}
    pkginfo = (f"pkgname = {name}\npkgver = {version}\narch = x86_64\norigin = {name}\n"
               f"builddate = {builddate}\nsize = 123\ncommit = {commit}\n{extra_info}"
               f"datahash = {'d' * 64}\n").encode()
    data = [_dir("usr"), _dir("usr/share"), _dir("usr/share/x")]
    data += [_file(n, d, modes.get(n, 0o644)) for n, d in files.items()]
    data += [_link(n, t) for n, t in (links or {}).items()]
    sig = gzip.compress(_tar([_file(".SIGN.RSA.r36os.rsa.pub", b"s" * 256)], cut=True))
    ctl = gzip.compress(_tar([_file(".PKGINFO", pkginfo)], cut=True))
    dat = gzip.compress(_tar(data, cut=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(sig + ctl + dat)
    return path


# --- APKBUILD -----------------------------------------------------------------------------

APKBUILD = """pkgname=lume-x
pkgver=0.1.0
pkgrel=27
makedepends="cargo sdl2-dev
\tmesa-dev>=26 $pkgname-extra"
depends="retroarch"
"""


def test_apkbuild_version_and_generated_pkgrel():
    assert frag.apkbuild_version(APKBUILD) == ("0.1.0", 27)
    new = frag.with_pkgrel(APKBUILD, 31)
    assert "pkgrel=31\n" in new and "pkgrel=27" not in new
    assert new.replace("pkgrel=31", "pkgrel=27") == APKBUILD


def test_apkbuild_with_a_computed_pkgver_is_refused():
    with pytest.raises(frag.FragmentError, match="literals"):
        frag.apkbuild_version("pkgver=$_v\npkgrel=0\n")
    with pytest.raises(frag.FragmentError, match="no pkgrel"):
        frag.with_pkgrel("pkgver=1\n", 2)


def test_build_deps_are_the_build_time_names_without_constraints():
    # runtime depends do not change what is built
    assert frag.build_deps(APKBUILD) == ["cargo", "sdl2-dev", "mesa-dev"]


def test_build_order_puts_local_deps_and_subpackage_origins_first():
    deps = {"lume-launcher": ["retroarch"], "retroarch": ["mesa-dev", "zlib-dev"],
            "mesa": [], "libretro-snes9x2005-plus": []}
    order = frag.build_order(["libretro-snes9x2005-plus", "lume-launcher", "mesa", "retroarch"], deps)
    assert order.index("mesa") < order.index("retroarch") < order.index("lume-launcher")
    assert order[0] == "libretro-snes9x2005-plus"


# --- inputs ---------------------------------------------------------------------------

def _aport(root: Path) -> Path:
    d = root / "lume-launcher"
    for rel, data in {"APKBUILD": APKBUILD, "FONTS": "Roboto\n",
                      "stage/lume/Cargo.lock": "lock\n", "stage/lume/src/main.rs": "fn main(){}\n",
                      "stage/lume/.cargo/vendor-tarball": "lume-vendor-ab.tar.gz",
                      "stage/lume/target/release/lume-ui": "binary",
                      "stage/lume/vendor/serde/lib.rs": "crate",
                      "src/build.log": "x", "pkg/lume-launcher/usr/bin/x": "y"}.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(data)
    return d


def test_inputs_cover_the_aport_and_staged_sources_but_not_caches(tmp_path):
    d = _aport(tmp_path)
    labels = set(frag.tree_inputs(d))
    assert labels == {"file:APKBUILD", "file:FONTS", "file:stage/lume/Cargo.lock",
                      "file:stage/lume/src/main.rs", "file:stage/lume/.cargo/vendor-tarball"}


def test_inputs_hash_changes_with_a_source_file_and_not_with_a_cache(tmp_path):
    d = _aport(tmp_path)

    def h():
        return manifests.inputs_hash(frag.fragment_inputs(d, "script", "builder", {}))

    first = h()
    (d / "stage/lume/target/release/lume-ui").write_text("other binary")
    (d / "src/build.log").write_text("other log")
    assert h() == first
    (d / "stage/lume/src/main.rs").write_text("fn main(){ println!() }\n")
    assert h() != first


def test_inputs_hash_changes_with_script_builder_and_local_dep_content(tmp_path):
    d = _aport(tmp_path)
    base = manifests.inputs_hash(frag.fragment_inputs(d, "s", "b", {"retroarch": H1}))
    assert manifests.inputs_hash(frag.fragment_inputs(d, "s2", "b", {"retroarch": H1})) != base
    assert manifests.inputs_hash(frag.fragment_inputs(d, "s", "b2", {"retroarch": H1})) != base
    assert manifests.inputs_hash(frag.fragment_inputs(d, "s", "b", {"retroarch": H2})) != base


def test_local_dep_contents_come_from_hashes_or_mark_unpublished():
    hashes = manifests.RepoHashes("armv7", {"mesa-dev": manifests.PackageHashes(
        "26.1.6-r100", H1, H2, "mesa-dev-26.1.6-r100.apk")})
    got = frag.local_dep_contents(["mesa-dev", "retroarch", "zlib-dev"], hashes,
                                  ["retroarch", "mesa"])
    assert got == {"mesa-dev": H2, "retroarch": frag.UNPUBLISHED}


# --- versions -------------------------------------------------------------------------

def test_apk_file_names_and_version_order(tmp_path):
    a = frag.parse_apk_file(Path("libretro-fbalpha2012-cps1-0.2.97.29-r3.apk"))
    assert (a.name, a.pkgver, a.pkgrel) == ("libretro-fbalpha2012-cps1", "0.2.97.29", 3)
    assert frag.parse_apk_file(Path("APKINDEX.tar.gz")) is None
    for v in ("1.0-r2", "1.0-r10", "1.0-r9", "0.9-r30"):
        (tmp_path / f"p-{v}.apk").write_bytes(b"")
    assert [f.version for f in frag.apk_files(tmp_path)["p"]] == [
        "1.0-r10", "1.0-r9", "1.0-r2", "0.9-r30"]


def test_next_pkgrel_follows_published_files_and_hashes(tmp_path):
    repo = tmp_path / "armv7"
    repo.mkdir()
    assert frag.next_pkgrel([repo], {"lume-x"}, "0.1.0", 27) == 27   # first build
    (repo / "lume-x-0.1.0-r27.apk").write_bytes(b"")
    (repo / "lume-x-0.0.9-r40.apk").write_bytes(b"")                # other pkgver
    assert frag.next_pkgrel([repo], {"lume-x"}, "0.1.0", 27) == 28
    hashes = manifests.RepoHashes("armv7", {"lume-x": manifests.PackageHashes(
        "0.1.0-r33", H1, H2, "lume-x-0.1.0-r33.apk")})                # file removed by hand
    assert frag.next_pkgrel([repo], {"lume-x"}, "0.1.0", 27, [hashes]) == 34
    assert frag.next_pkgrel([repo], {"lume-x"}, "0.2.0", 0, [hashes]) == 0  # new pkgver


# --- content hash ---------------------------------------------------------------------

def test_content_hash_ignores_pkgrel_builddate_commit_and_own_version(tmp_path):
    own = "provides = cmd:lume-x={v}\ninstall_if = docs lume-x={v}\n"
    a = make_apk(tmp_path / "a.apk", version="1.0-r3", commit="a" * 40, builddate=10,
                 extra_info=own.format(v="1.0-r3"))
    b = make_apk(tmp_path / "b.apk", version="1.0-r4", commit="b" * 40, builddate=99,
                 extra_info=own.format(v="1.0-r4"))
    assert frag.apk_content_hash(a) == frag.apk_content_hash(b)


@pytest.mark.parametrize("change", [
    {"files": {"usr/share/x/readme": b"changed\n"}},
    {"modes": {"usr/share/x/readme": 0o755}},
    {"files": {"usr/share/x/readme": b"hi\n", "usr/share/x/new": b"n"}},
    {"links": {"usr/share/x/link": "readme"}},
    {"version": "1.1-r0"},
    {"extra_info": "depend = sdl2\n"},
])
def test_content_hash_sees_files_modes_links_version_and_metadata(tmp_path, change):
    base = frag.apk_content_hash(make_apk(tmp_path / "a.apk"))
    assert frag.apk_content_hash(make_apk(tmp_path / "b.apk", **change)) != base


def test_lume_content_is_added_to_the_control_and_data_is_kept(tmp_path):
    apk = make_apk(tmp_path / "a.apk")
    content = frag.apk_content_hash(apk)
    ctl, data = frag.control_with_lume_content(apk, content)
    assert data == frag.split_apk(apk).data
    raw = gzip.decompress(ctl)
    assert not raw.endswith(b"\0" * 1024)   # cut like abuild-tar --cut
    # what abuild-sign does: a signature segment in front
    signed = tmp_path / "signed.apk"
    signed.write_bytes(frag.split_apk(apk).signature[0] + ctl + data)
    assert list(frag.control_files(signed)) == [".PKGINFO", manifests.LUME_CONTENT]
    assert frag.apk_lume_content(signed) == content
    assert frag.apk_content_hash(signed) == content   # the control file is not content
    # rewriting again replaces it, never duplicates
    ctl2, _ = frag.control_with_lume_content(signed, H1)
    signed.write_bytes(frag.split_apk(apk).signature[0] + ctl2 + data)
    assert list(frag.control_files(signed)) == [".PKGINFO", manifests.LUME_CONTENT]
    assert frag.apk_lume_content(signed) == H1


def test_apk_without_lume_content_has_none(tmp_path):
    assert frag.apk_lume_content(make_apk(tmp_path / "a.apk")) is None


def test_truncated_apk_is_refused(tmp_path):
    apk = make_apk(tmp_path / "a.apk")
    apk.write_bytes(apk.read_bytes()[:-20])
    with pytest.raises(frag.FragmentError, match="truncated"):
        frag.split_apk(apk)


# --- cleanup --------------------------------------------------------------------------

def _repo(tmp_path: Path, files: list[str]) -> Path:
    repo = tmp_path / "repo" / "armv7"
    repo.mkdir(parents=True)
    for f in files:
        (repo / f).write_bytes(b"x" * 1000)
    return repo


def test_cleanup_keeps_newest_and_previous_of_each_package(tmp_path):
    repo = _repo(tmp_path, [f"lume-launcher-0.1.0-r{n}.apk" for n in range(1, 28)]
                 + ["retroarch-1.22.2-r111.apk", "retroarch-1.22.2-r112.apk",
                    "r36os-devmem-1.0-r0.apk", "APKINDEX.tar.gz", "hashes.json"])
    removed, freed = frag.remove_old_versions(repo, set())
    assert len(removed) == 25 and freed == 25 * 1000
    assert sorted(p.name for p in repo.iterdir()) == [
        "APKINDEX.tar.gz", "hashes.json", "lume-launcher-0.1.0-r26.apk",
        "lume-launcher-0.1.0-r27.apk", "r36os-devmem-1.0-r0.apk",
        "retroarch-1.22.2-r111.apk", "retroarch-1.22.2-r112.apk"]


def test_cleanup_never_removes_a_version_cited_by_a_kept_build(tmp_path):
    repo = _repo(tmp_path, [f"lume-launcher-0.1.0-r{n}.apk" for n in (5, 20, 26, 27)]
                 + ["retroarch-1.22.2-r100.apk", "retroarch-1.22.2-r112.apk"])
    images = tmp_path / "images"
    for image, build, lines in [("console", "20261101-000000", "lume-launcher 0.1.0-r20\n"),
                                ("console", "20261116-233612", "lume-launcher 0.1.0-r27\n"),
                                ("console", "20261010-000000", "lume-launcher 0.1.0-r5\n"),
                                ("vm", "20261102-000000", "retroarch 1.22.2-r100\n")]:
        (images / image / build).mkdir(parents=True)
        (images / image / build / "manifest-r36s.txt").write_text("# header\n" + lines)
    (images / "console" / "latest").symlink_to("20261116-233612")
    (images / "console" / "flashed").symlink_to("20261101-000000")
    (images / "vm" / "latest").symlink_to("20261102-000000")
    cited = frag.cited_versions(images)
    assert cited == {("lume-launcher", "0.1.0-r27"), ("lume-launcher", "0.1.0-r20"),
                     ("retroarch", "1.22.2-r100")}
    plan = frag.cleanup_plan(repo, cited)
    # r5 is only cited by a build that is neither latest nor flashed
    assert [p.name for p in plan] == ["lume-launcher-0.1.0-r5.apk"]


def test_cited_versions_without_images_is_empty(tmp_path):
    assert frag.cited_versions(tmp_path / "missing") == set()


# --- the build flow, containers faked -------------------------------------------------

class FakeBuilder:
    """Stands in for the abuild container: "builds" from the aport's `data` file."""

    def __init__(self, calls, target, aports, repodest=None, **kw):
        self.calls, self.target, self.aports, self.repodest = calls, target, aports, repodest
        self.volumes, self.env = {}, {}

    def sh(self, script, **kw):
        if self.repodest is None:   # key/reindex containers
            return None
        name = re.search(r"/aports/r36os/([^ )]+) &&", script)[1]
        commit = re.search(r"ABUILD_LAST_COMMIT=([0-9a-f]+)", script)[1]
        gen = next(h for h, g in self.volumes.items() if g.endswith(f"{name}/APKBUILD"))
        ver, rel = frag.apkbuild_version(Path(gen).read_text())
        self.calls.append(f"{name}-{ver}-r{rel}")
        data = (self.aports / name / "data").read_bytes()
        make_apk(self.repodest / self.target.alpine_arch / f"{name}-{ver}-r{rel}.apk",
                 name=name, version=f"{ver}-r{rel}", commit=commit,
                 files={"usr/share/x/data": data})


@pytest.fixture
def fake_build(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))
    calls: list[str] = []
    monkeypatch.setattr(packages, "_container",
                        lambda target, aports, **kw: FakeBuilder(calls, target, aports, **kw))
    reindexed: list[list[str]] = []
    monkeypatch.setattr(packages, "reindex", lambda arches: reindexed.append(list(arches)))

    def sign(apks, tag):
        for apk, content in apks:
            ctl, data = frag.control_with_lume_content(apk, content)
            apk.write_bytes(frag.split_apk(apk).signature[0] + ctl + data)

    monkeypatch.setattr(packages, "sign_with_lume_content", sign)
    aports = tmp_path / "aports"
    for name, deps in (("lume-x", 'makedepends="lume-base"'), ("lume-base", "")):
        (aports / name).mkdir(parents=True)
        (aports / name / "APKBUILD").write_text(
            f"pkgname={name}\npkgver=1.0\npkgrel=3\narch=\"armv7\"\n{deps}\n")
        (aports / name / "data").write_bytes(b"v1")
    return aports, calls, reindexed


def test_flow_builds_once_then_skips_bumps_on_change_and_cleans(fake_build, capsys):
    aports, calls, reindexed = fake_build
    ga36 = get_target("ga36")
    repo = packages.arch_repo_dir("armv7")
    out = packages.build_packages(ga36, ["lume-x", "lume-base"], aports=aports)
    # the local build dep first; the APKBUILD pkgrel is the minimum
    assert calls == ["lume-base-1.0-r3", "lume-x-1.0-r3"]
    assert sorted(p.name for p in out) == ["lume-base-1.0-r3.apk", "lume-x-1.0-r3.apk"]
    h = packages.read_repo_hashes("armv7").packages
    assert h["lume-x"].file == "lume-x-1.0-r3.apk"
    assert dict(packages.read_apk_pkginfo(repo / "lume-x-1.0-r3.apk"))["commit"] == \
        h["lume-x"].inputs[:40]
    assert frag.apk_lume_content(repo / "lume-x-1.0-r3.apk") == h["lume-x"].content

    # same inputs: nothing compiled
    assert packages.build_packages(ga36, ["lume-x", "lume-base"], aports=aports) == []
    assert len(calls) == 2

    # force: compiled, same content, nothing published, inputs kept
    assert packages.build_packages(ga36, ["lume-x"], aports=aports, force=True) == []
    assert calls[-1] == "lume-x-1.0-r4" and not (repo / "lume-x-1.0-r4.apk").exists()
    assert packages.read_repo_hashes("armv7").packages["lume-x"].version == "1.0-r3"

    # a changed file: the next pkgrel, APKBUILD untouched
    (aports / "lume-x" / "data").write_bytes(b"v2")
    out = packages.build_packages(ga36, ["lume-x"], aports=aports)
    assert [p.name for p in out] == ["lume-x-1.0-r4.apk"]
    assert "pkgrel=3" in (aports / "lume-x" / "APKBUILD").read_text()

    # a dependency that changes content rebuilds its user (the user keeps its content)
    (aports / "lume-base" / "data").write_bytes(b"v2")
    n = len(calls)
    packages.build_packages(ga36, ["lume-x", "lume-base"], aports=aports)
    assert calls[n:] == ["lume-base-1.0-r4", "lume-x-1.0-r5"]
    assert not (repo / "lume-x-1.0-r5.apk").exists()

    # third version of lume-x (r5 again: the discarded r5 was never published): the
    # oldest leaves, the index is rebuilt
    (aports / "lume-x" / "data").write_bytes(b"v3")
    reindexed.clear()
    packages.build_packages(ga36, ["lume-x"], aports=aports)
    assert sorted(p.name for p in repo.glob("lume-x-*.apk")) == [
        "lume-x-1.0-r4.apk", "lume-x-1.0-r5.apk"]
    assert reindexed == [["armv7"], ["armv7"]]   # after the publish and after the cleanup
    assert "repo armv7: removed 1 old package file(s), freed" in capsys.readouterr().out


def test_flow_adopts_a_package_published_before_hashes_json(fake_build, capsys):
    aports, calls, _ = fake_build
    ga36 = get_target("ga36")
    repo = packages.arch_repo_dir("armv7")
    old = make_apk(repo / "lume-base-1.0-r7.apk", name="lume-base", version="1.0-r7",
                   files={"usr/share/x/data": b"published"})
    # no hashes.json yet: adopted without any container
    assert packages.build_packages(ga36, ["lume-base"], aports=aports) == []
    assert calls == []
    assert "pkg lume-base: adopted lume-base-1.0-r7.apk (no build)" in capsys.readouterr().out
    h = packages.read_repo_hashes("armv7").packages["lume-base"]
    assert (h.version, h.file) == ("1.0-r7", "lume-base-1.0-r7.apk")
    assert h.content == frag.apk_content_hash(old)
    assert h.inputs == packages._inputs(aports, "lume-base", "armv7", "armv7")
    # next build: inputs unchanged
    assert packages.build_packages(ga36, ["lume-base"], aports=aports) == []
    assert calls == []
    # an input change compiles and bumps the pkgrel as before
    (aports / "lume-base" / "data").write_bytes(b"v2")
    out = packages.build_packages(ga36, ["lume-base"], aports=aports)
    assert calls == ["lume-base-1.0-r8"]
    assert [p.name for p in out] == ["lume-base-1.0-r8.apk"]


def test_flow_force_compiles_instead_of_adopting(fake_build):
    aports, calls, _ = fake_build
    make_apk(packages.arch_repo_dir("armv7") / "lume-base-1.0-r7.apk", name="lume-base",
             version="1.0-r7", files={"usr/share/x/data": b"v1"})
    assert packages.build_packages(get_target("ga36"), ["lume-base"], aports=aports,
                                   force=True) == []   # same content: not published
    assert calls == ["lume-base-1.0-r8"]


def test_flow_compiles_when_a_subpackage_or_the_version_is_not_published(fake_build):
    aports, calls, _ = fake_build
    ga36 = get_target("ga36")
    repo = packages.arch_repo_dir("armv7")
    apkbuild = aports / "lume-base" / "APKBUILD"
    apkbuild.write_text(apkbuild.read_text() + 'subpackages="$pkgname-doc"\n')
    make_apk(repo / "lume-base-1.0-r7.apk", name="lume-base", version="1.0-r7")
    packages.build_packages(ga36, ["lume-base"], aports=aports)
    assert calls == ["lume-base-1.0-r8"]      # lume-base-doc missing: compiled

    calls.clear()
    make_apk(repo / "lume-x-0.9-r9.apk", name="lume-x", version="0.9-r9")
    packages.build_packages(ga36, ["lume-x"], aports=aports)   # APKBUILD says 1.0
    assert calls == ["lume-x-1.0-r3"]


def test_apkbuild_packages_expand_pkgname_or_give_up():
    text = 'pkgname=mesa\nsubpackages="\n\t$pkgname-dri-gallium:_gallium\n\t${pkgname}-egl\n"\n'
    assert frag.apkbuild_packages(text) == ["mesa", "mesa-dri-gallium", "mesa-egl"]
    assert frag.apkbuild_packages('pkgname=x\nsubpackages="$_py-x"\n') is None
