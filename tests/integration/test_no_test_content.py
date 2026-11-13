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
from r36os.image import boot_start
from r36os.paths import out_dir
from r36os.rootfs import target_out
from r36os.targets import IMAGES, TARGETS

ROM_EXTS = {e for s in catalog.load()["systems"] for e in s["extensions"]} | {"exe"}
TEST_NAMES = {name for name, _ in testroms.ROMS.values()} | {"gridlee.zip"}
# SYSTEM of each hardware layer (ga36, r36s, vm) and each card image (console, vm)
BUILT_LAYERS = [t for t in TARGETS.values() if (target_out(t) / "rootfs.tar").exists()]
BUILT_IMAGES = [i for i in IMAGES.values() if (out_dir() / i.name / f"{i.name}.img").exists()]


@pytest.mark.skipif(not BUILT_LAYERS, reason="nenhum rootfs em out/")
@pytest.mark.parametrize("target", BUILT_LAYERS, ids=lambda t: t.name)
def test_system_has_no_test_roms(target):
    with tarfile.open(target_out(target) / "rootfs.tar") as tar:
        names = tar.getnames()
    leaked = [n for n in names if n.rsplit("/", 1)[-1] in TEST_NAMES]
    assert leaked == []
    assert not [n for n in names if n.startswith("./storage/") and n != "./storage"]


@pytest.mark.skipif(not BUILT_IMAGES or shutil.which("podman") is None, reason="sem imagem ou podman")
@pytest.mark.parametrize("image", BUILT_IMAGES, ids=lambda i: i.name)
def test_boot_has_no_roms(image):
    img = out_dir() / image.name / f"{image.name}.img"
    cmd = Container(image=ensure_builder(TARGETS["vm"]), volumes={img.parent: "/out"}).argv(
        f"MTOOLS_SKIP_CHECK=1 mdir -i /out/{img.name}@@{boot_start(image) * 512} -/ -b ::/")
    listing = subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    files = [l.rsplit("/", 1)[-1] for l in listing.splitlines()]
    assert not [f for f in files if f.rsplit(".", 1)[-1].lower() in ROM_EXTS - {"bin", "m3u"}]
    assert not set(files) & TEST_NAMES
