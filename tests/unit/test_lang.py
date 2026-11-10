"""Factory language chosen at build time (default English)."""

import re

import pytest

from r36os import cli, lang
from r36os.paths import REPO_ROOT


def test_default_is_english():
    assert lang.DEFAULT == "en" and lang.retro_language("en") == 0
    assert lang.retro_language("pt_BR") == 7 and lang.retro_language("es") == 3


def test_invalid_language_fails_before_build(capsys):
    with pytest.raises(lang.InvalidLanguageError):
        lang.retro_language("xx")
    assert cli.main(["build", "vm", "--lang", "xx"]) == 2
    assert "invalid language" in capsys.readouterr().err


def test_overlay_default_matches_and_build_replaces_it():
    cfg = (REPO_ROOT / "rootfs/overlay/usr/share/r36os/retroarch-lume.cfg").read_text()
    assert re.findall(r'^user_language = "(\d+)"$', cfg, re.M) == ["0"]
    from r36os import rootfs
    assert 'user_language = "{retro_lang}"' in rootfs._ROOTFS_SCRIPT
