"""Lume shaders for GB, GBC and GBA (change lume-shaders): copied unchanged from the user's
earlier GA36 project, available in the RetroArch menu and off by default."""

import hashlib
import re

import pytest

from r36os.paths import REPO_ROOT

SHADERS = REPO_ROOT / "rootfs/overlay/usr/share/libretro/shaders"
LUME = SHADERS / "lume-shaders"
CFG = (REPO_ROOT / "rootfs/overlay/usr/share/r36os/retroarch-lume.cfg").read_text()
FACTORY = (REPO_ROOT / "rootfs/overlay/usr/share/r36os/factory/retroarch/retroarch.cfg").read_text()

# SHA256 of the files of "R36S GA36-MB V1.2-20260416" (features 54-shaders-gba and
# 55-shaders-gb-gbc), copied without changes on 2026-11-11
SOURCE_SHA256 = {
    "gb/gb-modern-dmg.glsl": "86d75f94530bf28b6ddf427112b246dcfbbe7c38ce34c4e36bbf35449c40d04f",
    "gb/gb-modern-dmg.glslp": "701acb2e50d436e403e811967d541bda4f1590879144379e01bd5b2c818d0aa4",
    "gbc/gbc-modern-remaster.glsl": "3b3a203ccf086da7c63b7f678bb71c8c2ac4ca387024c4a0664f16b615431f0e",
    "gbc/gbc-modern-remaster.glslp": "4a43deeab339a498d743007cebaaa9d6036c22c5249f9847bee74519759094ab",
    "gba/gba-modern-remaster.glsl": "c4f653cbc55fe9ff9ece77d683a03c7de0936eddc267a36faa94a2708027c468",
    "gba/gba-modern-remaster.glslp": "168fef7e0c877b40edecd4f52b04b23aae2455a5d5aeecfce0b5858701b93e86",
}


def test_exactly_the_three_shaders_unchanged():
    files = sorted(p.relative_to(LUME).as_posix() for p in LUME.rglob("*") if p.is_file())
    assert files == sorted(SOURCE_SHA256)
    for name, digest in SOURCE_SHA256.items():
        assert hashlib.sha256((LUME / name).read_bytes()).hexdigest() == digest, name


@pytest.mark.parametrize("preset", sorted(n for n in SOURCE_SHA256 if n.endswith(".glslp")))
def test_preset_is_one_pass_over_its_own_shader(preset):
    text = (LUME / preset).read_text()
    keys = dict(re.findall(r'^(\w+) = "([^"]*)"$', text, re.M))
    assert keys["shaders"] == "1"
    shader = (LUME / preset).parent / keys["shader0"]
    assert shader.is_file() and shader.suffix == ".glsl"
    body = shader.read_text()
    # GLSL for GLES 2: vertex and fragment in one file, mediump on GLES
    assert "#if defined(VERTEX)" in body and "#elif defined(FRAGMENT)" in body
    assert "precision mediump float" in body


def test_menu_opens_the_system_shader_folder():
    assert 'video_shader_dir = "/usr/share/libretro/shaders"' in CFG
    assert SHADERS.name == "shaders" and LUME.parent == SHADERS


def test_no_shader_on_by_default():
    for text in (CFG, FACTORY):
        assert not re.search(r'^video_shader = ', text, re.M)
        assert not re.search(r'^video_shader_enable = "true"', text, re.M)
    # no preset dropped into the user's config (auto presets) by the image
    factory_dir = REPO_ROOT / "rootfs/overlay/usr/share/r36os/factory/retroarch"
    assert not [p for p in factory_dir.rglob("*") if p.suffix in (".glslp", ".slangp")]


def test_origin_credited_in_readme():
    readme = (REPO_ROOT / "README.md").read_text()
    assert "lume-shaders" in readme
