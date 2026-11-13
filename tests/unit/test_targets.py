import subprocess
from pathlib import Path

import pytest

from r36os import cli, paths
from r36os.targets import IMAGES, TARGETS, InvalidTargetError, get_image, get_target


def test_hardware_layers():
    assert set(TARGETS) == {"r36s", "ga36", "vm"}
    assert get_target("ga36").alpine_arch == "armv7"
    assert get_target("r36s").alpine_arch == "aarch64"
    assert get_target("vm").alpine_arch == "x86_64"


def test_image_targets_are_console_and_vm():
    assert set(IMAGES) == {"console", "vm"}
    # both console layers, never in parallel: GA36 first, as before
    assert get_image("console").layers == ("ga36", "r36s")
    assert get_image("vm").layers == ("vm",)
    assert all(layer in TARGETS for img in IMAGES.values() for layer in img.layers)


@pytest.mark.parametrize("name", ["rg35xx", "ga36", "r36s"])
def test_invalid_image_lists_console_and_vm(name):
    # the layers are no longer images of their own
    with pytest.raises(InvalidTargetError) as exc:
        get_image(name)
    assert "Valid targets: console, vm" in str(exc.value)


def test_invalid_layer_lists_layers():
    with pytest.raises(InvalidTargetError) as exc:
        get_target("console")
    for name in TARGETS:
        assert name in str(exc.value)


@pytest.mark.parametrize("command", [["build", "rg35xx"], ["build", "ga36"],
                                     ["flash", "r36s", "/dev/sdc"]])
def test_cli_invalid_target_creates_nothing(tmp_path, monkeypatch, capsys, command):
    out = tmp_path / "out"
    cache = tmp_path / "cache"
    monkeypatch.setenv("R36OS_OUT", str(out))
    monkeypatch.setenv("R36OS_CACHE", str(cache))
    rc = cli.main(command)
    assert rc == 2
    err = capsys.readouterr().err
    assert "console, vm" in err
    assert not out.exists()
    assert not cache.exists()
    assert list(tmp_path.iterdir()) == []


def test_cli_pkg_still_takes_a_layer():
    args = cli._parser().parse_args(["pkg", "r36s", "retroarch"])
    assert get_target(args.target).alpine_arch == "aarch64"


def test_cache_env_anywhere(monkeypatch, tmp_path):
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "c"))
    assert paths.cache_dir() == (tmp_path / "c").resolve()
    # a cache inside the repository is accepted (it is ignored by git)
    monkeypatch.setenv("R36OS_CACHE", str(paths.REPO_ROOT / "var" / "c"))
    assert paths.cache_dir() == (paths.REPO_ROOT / "var" / "c").resolve()


def test_default_cache_is_repo_dot_cache(monkeypatch, tmp_path):
    monkeypatch.delenv("R36OS_CACHE", raising=False)
    # XDG_CACHE_HOME and ~/.cache/r36os are no longer used
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    cache = paths.cache_dir()
    assert cache == paths._main_repo_root(paths.REPO_ROOT) / ".cache"
    assert tmp_path not in cache.parents


def test_cache_dir_creates_nothing(monkeypatch, tmp_path):
    monkeypatch.delenv("R36OS_CACHE", raising=False)
    monkeypatch.setattr(paths, "REPO_ROOT", tmp_path)
    assert paths.cache_dir() == tmp_path / ".cache"
    assert list(tmp_path.iterdir()) == []


def _git(*args, cwd):
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


def test_worktree_uses_main_repo_cache(monkeypatch, tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    _git("init", "-q", cwd=main)
    _git("commit", "-q", "--allow-empty", "-m", "init", cwd=main)
    _git("worktree", "add", "-q", str(main / "out/worktrees/wt"), cwd=main)
    monkeypatch.delenv("R36OS_CACHE", raising=False)
    monkeypatch.setattr(paths, "REPO_ROOT", main / "out/worktrees/wt")
    assert paths.cache_dir() == (main / ".cache").resolve()
    monkeypatch.setattr(paths, "REPO_ROOT", main)
    assert paths.cache_dir() == (main / ".cache").resolve()


def test_no_git_uses_own_cache(monkeypatch, tmp_path):
    project = tmp_path / "extracted"
    project.mkdir()
    monkeypatch.delenv("R36OS_CACHE", raising=False)
    monkeypatch.setattr(paths, "REPO_ROOT", project)
    assert paths.cache_dir() == (project / ".cache").resolve()


def test_copy_inside_other_repo_uses_own_cache(monkeypatch, tmp_path):
    # an extracted project that sits inside another checkout keeps its own cache
    _git("init", "-q", cwd=tmp_path)
    project = tmp_path / "extracted"
    project.mkdir()
    monkeypatch.delenv("R36OS_CACHE", raising=False)
    monkeypatch.setattr(paths, "REPO_ROOT", project)
    assert paths.cache_dir() == (project / ".cache").resolve()


class _FakeRun:
    def __init__(self, returncode=0, stderr="", missing=False):
        self.calls = []
        self.returncode, self.stderr, self.missing = returncode, stderr, missing

    def __call__(self, cmd, **kwargs):
        self.calls.append(cmd)
        if self.missing:
            raise FileNotFoundError(2, "No such file or directory", cmd[0])
        return subprocess.CompletedProcess(cmd, self.returncode, "", self.stderr)


@pytest.fixture
def cache_env(monkeypatch, tmp_path):
    root = tmp_path / "cache"
    monkeypatch.setenv("R36OS_CACHE", str(root))
    return root.resolve()


def test_ensure_dir_sets_nocow_on_new_cache(monkeypatch, capsys, cache_env):
    fake = _FakeRun()
    monkeypatch.setattr(paths.subprocess, "run", fake)
    sub = paths.ensure_dir(paths.cache_dir() / "src")
    assert sub.is_dir()
    assert fake.calls == [["chattr", "+C", str(cache_env)]]
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("fake", [
    _FakeRun(returncode=1, stderr="chattr: Operation not supported while setting flags\n"),
    _FakeRun(missing=True),
])
def test_ensure_dir_warns_when_nocow_fails(monkeypatch, capsys, cache_env, fake):
    monkeypatch.setattr(paths.subprocess, "run", fake)
    paths.ensure_dir(paths.cache_dir() / "kbuild" / "x")
    assert (cache_env / "kbuild" / "x").is_dir()
    err = capsys.readouterr().err
    assert err.startswith(f"warning: could not set No-COW on {cache_env}: ")
    assert err.count("\n") == 1


def test_ensure_dir_leaves_existing_cache_alone(monkeypatch, capsys, cache_env):
    cache_env.mkdir()
    fake = _FakeRun()
    monkeypatch.setattr(paths.subprocess, "run", fake)
    paths.ensure_dir(paths.cache_dir() / "distfiles")
    paths.ensure_dir(paths.cache_dir())
    assert fake.calls == []
    assert (cache_env / "distfiles").is_dir()


def test_ensure_dir_outside_cache_does_not_touch_it(monkeypatch, tmp_path, cache_env):
    fake = _FakeRun()
    monkeypatch.setattr(paths.subprocess, "run", fake)
    paths.ensure_dir(tmp_path / "out" / "x")
    assert fake.calls == []
    assert not cache_env.exists()


def test_repo_root():
    assert (paths.REPO_ROOT / "pyproject.toml").is_file()
    assert isinstance(paths.REPO_ROOT, Path)
