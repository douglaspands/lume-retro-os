"""r36os clean: what goes, what is only listed, and what is never touched."""

import os

import pytest

from r36os import clean

DIGEST = "aaaaaaaaaaaaaaaa"


def _mk(path, data=b"x" * 10):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


@pytest.fixture
def tree(tmp_path):
    repo, out, cache = tmp_path / "repo", tmp_path / "repo" / "out", tmp_path / "cache"
    # kernel builds: one current, two old
    for name in (f"r36s-{DIGEST}", "r36s-bbbbbbbbbbbbbbbb", "ga36-cccccccccccccccc"):
        _mk(cache / "kbuild" / name / ".config")
    for keep in ("ccache/kernel-r36s/x", "distfiles/linux.tar.xz", "abuild/key.rsa",
                 "src/linux-6.18.62-" + DIGEST + "/Makefile"):
        _mk(cache / keep)
    # archived console images: six, latest is the newest, one old one cited in the docs
    stamps = [f"2026111{d}-120000" for d in range(6)]
    for s in stamps:
        _mk(out / "images" / "console" / s / f"console-{s}.img.zst")
    os.symlink(stamps[-1], out / "images" / "console" / "latest")
    _mk(repo / "docs" / "BRINGUP.md", f"tested on build {stamps[0]}\n".encode())
    # flash cache: the latest image and an old one
    _mk(cache / "flash" / f"console-{stamps[-1]}.img")
    _mk(cache / "flash" / f"console-{stamps[1]}.img")
    # work folders, evidence and the things never to touch
    _mk(repo / "aports" / "libretro-ppsspp" / "src" / "big.tar")
    _mk(repo / "aports" / "libretro-ppsspp" / "APKBUILD")
    _mk(repo / "src" / "r36os" / "__pycache__" / "x.pyc")
    _mk(repo / "var" / "sd_roms" / "game.zip")
    _mk(repo / "var" / "__pycache__" / "x.pyc")
    _mk(out / "repo" / "aarch64" / "pkg.apk")
    _mk(out / "r36s-factory" / "regdump" / "dsi.txt")
    _mk(out / "one-off-test" / "x")
    return repo, out, cache, stamps


def test_plan_removes_only_what_a_build_recreates(tree):
    repo, out, cache, stamps = tree
    remove, review = clean.plan(repo, out, cache, DIGEST, keep=3)
    paths = {i.path for i in remove}
    assert paths == {
        cache / "kbuild" / "r36s-bbbbbbbbbbbbbbbb",
        cache / "kbuild" / "ga36-cccccccccccccccc",
        out / "images" / "console" / stamps[2],
        cache / "flash" / f"console-{stamps[1]}.img",
        repo / "aports" / "libretro-ppsspp" / "src",
        repo / "src" / "r36os" / "__pycache__",
    }
    # stamps[0] is cited in the docs, stamps[1] is on the card (its decompressed copy in
    # flash/ goes, the archive stays), 3..5 are the newest three (5 is latest)
    assert {i.path for i in review} == {out / "one-off-test"}


def test_python_caches_inside_the_repo_cache_are_not_walked(tmp_path):
    # the default cache is <repo>/.cache, with millions of kernel build files
    repo = tmp_path / "repo"
    cache = repo / ".cache"
    _mk(cache / "x" / "__pycache__" / "y.pyc")
    _mk(cache / "src" / "linux" / "scripts" / "__pycache__" / "z.pyc")
    _mk(repo / "src" / "r36os" / "__pycache__" / "x.pyc")
    remove, _review = clean.plan(repo, repo / "out", cache, DIGEST, cited=set())
    assert {i.path for i in remove} == {repo / "src" / "r36os" / "__pycache__"}


def test_remove_frees_the_plan_and_keeps_the_rest(tree):
    repo, out, cache, stamps = tree
    to_remove, _ = clean.plan(repo, out, cache, DIGEST, keep=3)
    clean.remove(to_remove, repo, out, cache)
    for p in (cache / "kbuild" / f"r36s-{DIGEST}", cache / "ccache", cache / "distfiles",
              cache / "abuild", repo / "var" / "sd_roms" / "game.zip",
              repo / "var" / "__pycache__", out / "repo", out / "r36s-factory",
              out / "one-off-test", repo / "aports" / "libretro-ppsspp" / "APKBUILD",
              out / "images" / "console" / stamps[0], out / "images" / "console" / "latest"):
        assert p.exists() or p.is_symlink(), p
    assert not (cache / "kbuild" / "r36s-bbbbbbbbbbbbbbbb").exists()


def test_the_flashed_build_stays_without_the_flash_cache(tree):
    repo, out, cache, stamps = tree
    for f in (cache / "flash").glob("*"):
        f.unlink()
    os.symlink(stamps[2], out / "images" / "console" / "flashed")
    remove, _ = clean.plan(repo, out, cache, DIGEST, keep=3)
    images = {i.path.name for i in remove if "images" in i.path.parts}
    # stamps[2] is pinned by `flashed`; stamps[1] lost its flash cache, so it may go now
    assert images == {stamps[1]}


def test_flash_marks_the_build_written(tmp_path):
    from r36os.flash import mark_flashed

    b = tmp_path / "console" / "20261112-170732"
    b.mkdir(parents=True)
    mark_flashed(b)
    assert os.readlink(tmp_path / "console" / "flashed") == "20261112-170732"


def test_remove_falls_back_to_podman_unshare_and_goes_on(tree, monkeypatch):
    repo, out, cache, _ = tree
    src = repo / "aports" / "libretro-ppsspp" / "src"
    other = cache / "kbuild" / "r36s-bbbbbbbbbbbbbbbb"
    calls = []

    def denied(path, *a, **k):
        raise PermissionError(13, "Permission denied", str(path))

    real_rmtree = clean.shutil.rmtree
    monkeypatch.setattr(clean.shutil, "rmtree",
                        lambda p, *a, **k: denied(p) if p == src else real_rmtree(p))
    monkeypatch.setattr(clean, "_remove_as_container_user", lambda p: calls.append(p))
    items = [clean.Item(src, 10, "abuild"), clean.Item(other, 10, "kbuild")]
    failed = []
    assert clean.remove(items, repo, out, cache, failed) == 20
    assert calls == [src] and failed == [] and not other.exists()


def test_remove_refuses_var_and_the_evidence(tree):
    repo, out, cache, _ = tree
    for p in (repo / "var" / "sd_roms", out / "repo", out / "r36s-factory"):
        with pytest.raises(RuntimeError):
            clean.remove([clean.Item(p, 0, "test")], repo, out, cache)
        assert p.exists()
