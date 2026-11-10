"""Default interface language, chosen at build time (`r36os build <target> --lang <code>`).

The value becomes RetroArch's factory `user_language` (factory/retroarch/retroarch.cfg, the
user config seed, not the --appendconfig file). The user can still change it in the menu,
and the choice is persisted. Without `--lang`, English.
System messages for the user follow the same value (ui_lang in lib.sh); logs are always
in English.
"""

from __future__ import annotations

DEFAULT = "en"

# code -> RETRO_LANGUAGE_* from libretro.h
LANGUAGES: dict[str, int] = {
    "en": 0,      # RETRO_LANGUAGE_ENGLISH
    "fr": 2,      # RETRO_LANGUAGE_FRENCH
    "es": 3,      # RETRO_LANGUAGE_SPANISH
    "de": 4,      # RETRO_LANGUAGE_GERMAN
    "it": 5,      # RETRO_LANGUAGE_ITALIAN
    "pt_BR": 7,   # RETRO_LANGUAGE_PORTUGUESE_BRAZIL
    "pt_PT": 8,   # RETRO_LANGUAGE_PORTUGUESE_PORTUGAL
}


class InvalidLanguageError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(f"invalid language: {code!r}. Valid: {', '.join(LANGUAGES)}")


def retro_language(code: str) -> int:
    try:
        return LANGUAGES[code]
    except KeyError:
        raise InvalidLanguageError(code) from None
