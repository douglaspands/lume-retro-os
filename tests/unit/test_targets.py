from pathlib import Path

import pytest

from r36os import cli, paths
from r36os.targets import TARGETS, InvalidTargetError, get_target


def test_valid_targets():
    assert set(TARGETS) == {"r36s", "ga36", "vm"}
    assert get_target("ga36").alpine_arch == "armv7"
    assert get_target("r36s").alpine_arch == "aarch64"
    assert get_target("vm").alpine_arch == "x86_64"


def test_invalid_target_lists_valid():
    with pytest.raises(InvalidTargetError) as exc:
        get_target("rg35xx")
    msg = str(exc.value)
    for name in TARGETS:
        assert name in msg


def test_cli_invalid_target_creates_nothing(tmp_path, monkeypatch, capsys):
    out = tmp_path / "out"
    cache = tmp_path / "cache"
    monkeypatch.setenv("R36OS_OUT", str(out))
    monkeypatch.setenv("R36OS_CACHE", str(cache))
    rc = cli.main(["build", "rg35xx"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "r36s" in err and "ga36" in err and "vm" in err
    assert not out.exists()
    assert not cache.exists()
    assert list(tmp_path.iterdir()) == []


def test_cache_outside_repo(monkeypatch, tmp_path):
    monkeypatch.setenv("R36OS_CACHE", str(tmp_path / "c"))
    assert paths.cache_dir() == (tmp_path / "c").resolve()
    monkeypatch.setenv("R36OS_CACHE", str(paths.REPO_ROOT / ".cache"))
    with pytest.raises(ValueError):
        paths.cache_dir()


def test_default_cache_is_xdg(monkeypatch, tmp_path):
    monkeypatch.delenv("R36OS_CACHE", raising=False)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert paths.cache_dir() == (tmp_path / "r36os").resolve()
    assert paths.REPO_ROOT not in paths.cache_dir().parents


def test_repo_root():
    assert (paths.REPO_ROOT / "pyproject.toml").is_file()
    assert isinstance(paths.REPO_ROOT, Path)
