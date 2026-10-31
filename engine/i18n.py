"""English / Japanese text for the app and the reports.

Every string the teacher sees lives in ``i18n/en.json`` and ``i18n/ja.json``
under the same keys. Placeholders use ``{name}``. A missing Japanese string
falls back to English, and a missing English string to the key itself, so a
gap never crashes the app (a test keeps the two files in step).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache

LANGUAGES = ("en", "ja")
DEFAULT_LANGUAGE = "en"
I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "i18n")


@lru_cache(maxsize=None)
def strings(language: str) -> dict:
    if language not in LANGUAGES:
        language = DEFAULT_LANGUAGE
    with open(os.path.join(I18N_DIR, f"{language}.json"), encoding="utf-8") as fh:
        return json.load(fh)


class _KeepMissing(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def t(key: str, language: str = DEFAULT_LANGUAGE, /, **params) -> str:
    # key and language are positional-only so a placeholder may be called {language}.
    text = strings(language).get(key)
    if text is None and language != DEFAULT_LANGUAGE:
        text = strings(DEFAULT_LANGUAGE).get(key)
    if text is None:
        return key
    return text.format_map(_KeepMissing(params))


def error_text(error, language: str = DEFAULT_LANGUAGE) -> str:
    """Translate a :class:`engine.errors.UserError` for the teacher."""
    return t(error.i18n_key, language, **error.params)
