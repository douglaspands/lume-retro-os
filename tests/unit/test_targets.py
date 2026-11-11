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
