"""Task 11.1: consoles are only released if the test-vm of the same build passes."""

import json

import pytest

from r36os import release
from r36os.rootfs import target_out
from r36os.targets import TARGETS


@pytest.fixture
def out(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path))
    return tmp_path


def _marked(name):
    return (target_out(TARGETS[name]) / release.MARKER).exists()


def test_vm_defect_blocks_consoles(out):
    built = []
    rc = release.build_all(build=built.append, test=lambda: 1)  # defect injected in the VM
    assert rc == 1
    assert built == ["vm", "r36s", "ga36"]  # vm first
    assert not _marked("r36s") and not _marked("ga36")
    rep = json.loads((out / "release.json").read_text())
    assert rep["targets"]["vm"]["test_vm"] == "FAIL"
    assert rep["targets"]["r36s"]["released"] is False


def test_vm_ok_releases_consoles(out):
    rc = release.build_all(build=lambda n: None, test=lambda: 0)
    assert rc == 0
    assert _marked("r36s") and _marked("ga36")


def test_stale_marker_removed(out):
    release.build_all(build=lambda n: None, test=lambda: 0)
    assert _marked("r36s")
    release.build_all(build=lambda n: None, test=lambda: 1)
    assert not _marked("r36s")


def test_console_build_failure_not_released(out):
    def build(name):
        if name == "ga36":
            raise RuntimeError("kernel did not build")

    rc = release.build_all(build=build, test=lambda: 0)
    assert rc == 1
    assert _marked("r36s") and not _marked("ga36")
