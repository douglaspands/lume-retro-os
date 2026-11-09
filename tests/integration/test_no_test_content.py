"""Tarefa 6.4: nenhum jogo de teste dentro da imagem (SYSTEM e BOOT).

As ROMs de teste só existem no disco TESTDATA da VM. Vale para qualquer alvo gerado;
roda sobre os que existirem em out/.
"""

import shutil
import subprocess
import tarfile

import pytest

from r36os import catalog, testroms
from r36os.container import Container, ensure_builder
from r36os.image import BOOT_START
from r36os.rootfs import target_out
from r36os.targets import TARGETS

ROM_EXTS = {e for s in catalog.load()["systems"] for e in s["extensions"]} | {"exe"}
TEST_NAMES = {name for name, _ in testroms.ROMS.values()} | {"gridlee.zip"}
BUILT = [t for t in TARGETS.values() if (target_out(t) / f"{t.name}.img").exists()]


@pytest.mark.skipif(not BUILT, reason="nenhuma imagem em out/")
@pytest.mark.parametrize("target", BUILT, ids=lambda t: t.name)
def test_system_has_no_test_roms(target):
    with tarfile.open(target_out(target) / "rootfs.tar") as tar:
        names = tar.getnames()
    leaked = [n for n in names if n.rsplit("/", 1)[-1] in TEST_NAMES]
    assert leaked == []
    assert not [n for n in names if n.startswith("./storage/") and n != "./storage"]


@pytest.mark.skipif(not BUILT or shutil.which("podman") is None, reason="sem imagem ou podman")
@pytest.mark.parametrize("target", BUILT, ids=lambda t: t.name)
def test_boot_has_no_roms(target):
    img = target_out(target) / f"{target.name}.img"
    cmd = Container(image=ensure_builder(TARGETS["vm"]), volumes={img.parent: "/out"}).argv(
        f"MTOOLS_SKIP_CHECK=1 mdir -i /out/{img.name}@@{BOOT_START * 512} -/ -b ::/")
    listing = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    files = [l.rsplit("/", 1)[-1] for l in listing.splitlines()]
    assert not [f for f in files if f.rsplit(".", 1)[-1].lower() in ROM_EXTS - {"bin", "m3u"}]
    assert not set(files) & TEST_NAMES
