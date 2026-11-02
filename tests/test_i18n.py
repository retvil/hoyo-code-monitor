"""Regression test: every language block must cover the English key set."""

from __future__ import annotations

from src.i18n import STRINGS

_LANGS = ["ru", "de", "fr", "ja", "zh"]


def test_all_languages_superset_of_english() -> None:
    en_keys = set(STRINGS["en"].keys())
    for lang in _LANGS:
        assert set(STRINGS[lang].keys()) >= en_keys, (
            f"language {lang!r} is missing keys: {sorted(en_keys - set(STRINGS[lang].keys()))}"
        )
