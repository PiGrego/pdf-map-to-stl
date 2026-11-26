"""Languages: every text a reader touches or hears, and every message an operator reads.

The texts of each language live in ``locales/<code>.toml``: sections of short templates
with ``{name}`` placeholders. English (``en``) is complete and is the fallback for any
text another language does not have yet. Each language also has its Braille code
(``braille.BRAILLE_CODES``): Italian Braille, for one, has its own accented letters and
question mark.

The language of a build is ``output.language`` (default "it"), or ``--lang`` on the
command line. To add a language: copy ``locales/en.toml`` to ``locales/<code>.toml``,
translate the texts (keep the ``{placeholders}``), add the class labels of the
legend in ``config/default.toml`` (``label = { en = "...", <code> = "..." }``) and, if
its Braille code differs from English, its table in ``braille.py``.
"""

from __future__ import annotations

import tomllib
from functools import cache
from importlib import resources

FALLBACK = "en"
DEFAULT = "it"
_current = DEFAULT


def _locales():
    return resources.files(__package__).joinpath("locales")


def languages() -> list[str]:
    """Codes of the languages there are texts for."""
    return sorted(p.name.removesuffix(".toml") for p in _locales().iterdir() if p.name.endswith(".toml"))


@cache
def catalogue(code: str) -> dict[str, str]:
    """All texts of a language, keyed "section.name"."""
    data = tomllib.loads(_locales().joinpath(f"{code}.toml").read_text(encoding="utf-8"))
    flat: dict[str, str] = {}

    def walk(prefix: str, d: dict) -> None:
        for k, v in d.items():
            key = f"{prefix}.{k}" if prefix else k
            if isinstance(v, dict):
                walk(key, v)
            else:
                flat[key] = v

    walk("", data)
    return flat


def set_language(code: str) -> None:
    global _current
    if code not in languages():
        raise ValueError(f"unknown language {code!r}: available {', '.join(languages())} (output.language, --lang)")
    _current = code


def language() -> str:
    return _current


def t(key: str, **values) -> str:
    """The text ``key`` in the current language, with its placeholders filled in."""
    text = catalogue(_current).get(key)
    if text is None:
        text = catalogue(FALLBACK)[key]
    return text.format(**values) if values else text


def num(x: float, spec: str = "g") -> str:
    """A number written as the current language writes it (2,5 in Italian, 2.5 in English)."""
    s = format(x, spec)
    return s.replace(".", t("number.decimal_mark"))
