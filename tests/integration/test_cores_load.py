"""Tarefa 2.2: os cores locais carregam no RetroArch (x86_64), sem conteúdo."""

import shutil
import subprocess

import pytest

from r36os.packages import keys_dir, repo_dir
from r36os.paths import REPO_ROOT, out_dir
from r36os.targets import get_target

pytestmark = [
    pytest.mark.skipif(shutil.which("podman") is None, reason="sem podman"),
    pytest.mark.skipif(not repo_dir(get_target("vm")).exists(), reason="sem out/repo/x86_64"),
]


def test_local_cores_load():
    r = subprocess.run(
        ["podman", "run", "--rm",
         "-v", f"{out_dir() / 'repo'}:/repo:z", "-v", f"{keys_dir()}:/keys:z",
         "-v", f"{REPO_ROOT / 'tests/cores'}:/t:z,ro",
         "docker.io/library/alpine:3.24", "sh", "/t/load_cores.sh"],
        capture_output=True, text=True,
    )
    print(r.stdout)
    assert r.returncode == 0, r.stdout + r.stderr
    # 5 local cores of the catalog + the 3 fbalpha2012_* (catalog-arcade-sega)
    assert r.stdout.count("PASS") == 8
