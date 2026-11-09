"""Tarefa 1.4: chave do abuild no cache e repositório local out/repo/<arch>.

Requer podman. Rodar com: uv run pytest tests/integration -k local_repo
"""

import shutil

import pytest

from r36os import packages
from r36os.paths import REPO_ROOT
from r36os.targets import get_target

pytestmark = pytest.mark.skipif(shutil.which("podman") is None, reason="sem podman")


def test_trivial_apkbuild_builds_and_installs(tmp_path, monkeypatch):
    monkeypatch.setenv("R36OS_OUT", str(tmp_path / "out"))  # não suja o out/repo real
    vm = get_target("vm")
    fixtures = REPO_ROOT / "tests/fixtures/aports"
    pub = packages.ensure_key(vm)
    assert pub.is_file()
    assert REPO_ROOT not in pub.parents  # chave fica no cache, fora do repositório

    packages.build_packages(vm, ["r36os-hello"], aports=fixtures)
    # noarch vai para o diretório da arquitetura do build
    repo = packages.repo_dir(vm)
    assert (repo / "APKINDEX.tar.gz").is_file()
    assert list(repo.glob("r36os-hello-1.0-r0.apk"))

    assert "r36os-hello" in packages.install_test(vm, "r36os-hello", fixtures)
