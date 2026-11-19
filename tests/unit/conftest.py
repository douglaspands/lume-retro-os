import pytest


@pytest.fixture(autouse=True)
def _no_ssh_mux_by_default(monkeypatch, tmp_path):
    """The ssh channel (lume_tool.sshmux) is off in the unit tests unless a test turns it on, and
    never touches the repository's cache/ssh."""
    monkeypatch.setenv("LUME_SSH_MUX", "0")
    monkeypatch.setenv("LUME_SSH_DIR", str(tmp_path / "ssh"))


@pytest.fixture(autouse=True)
def _no_repo_resign_by_default(monkeypatch):
    """The one-time signing again of out/repo (packages.resign_published, a container) is
    off in the unit tests; test_resign_published.py turns it on with fakes."""
    from lume_tool import packages
    monkeypatch.setattr(packages, "_resign_done", True)
