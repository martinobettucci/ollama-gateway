"""Internationalisation (i18n) du panel d'admin : un fichier YAML par langue dans `app/locales/`.

- La **source** est `fr` (français) : elle définit l'ensemble des clés. Les autres langues sont des
  traductions clé-à-clé ; toute clé absente retombe sur le français, puis sur la clé brute.
- Clés **imbriquées** dans le YAML (`nav.dashboard`), aplaties en clés pointées au chargement.
- La langue courante est négociée par requête : session admin → cookie → en-tête `Accept-Language`
  → défaut (`fr`). Le panel expose un sélecteur qui écrit `session['lang']`.
- Aucune dépendance externe hormis PyYAML. Interpolation simple `{param}` via `str.format_map`.
"""
from __future__ import annotations

import os
from pathlib import Path

import yaml

LOCALES_DIR = Path(__file__).parent / "locales"
DEFAULT_LANG = "fr"

# 24 langues officielles de l'Union européenne (code ISO 639-1 → nom natif affiché au sélecteur).
LANGUAGES: dict[str, str] = {
    "bg": "Български", "cs": "Čeština", "da": "Dansk", "de": "Deutsch", "el": "Ελληνικά",
    "en": "English", "es": "Español", "et": "Eesti", "fi": "Suomi", "fr": "Français",
    "ga": "Gaeilge", "hr": "Hrvatski", "hu": "Magyar", "it": "Italiano", "lt": "Lietuvių",
    "lv": "Latviešu", "mt": "Malti", "nl": "Nederlands", "pl": "Polski", "pt": "Português",
    "ro": "Română", "sk": "Slovenčina", "sl": "Slovenščina", "sv": "Svenska",
}
SUPPORTED = tuple(LANGUAGES.keys())

# Autoriser la restriction du sous-ensemble proposé via env (ex. "fr,en,de"). Vide = toutes.
_env = os.environ.get("SUPPORTED_LANGS", "").strip()
ENABLED = tuple(c for c in (x.strip() for x in _env.split(",")) if c in LANGUAGES) or SUPPORTED

_CATALOG: dict[str, dict[str, str]] = {}


def _flatten(d: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in (d or {}).items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = "" if v is None else str(v)
    return out


def load_catalog() -> dict[str, dict[str, str]]:
    """(Re)charge tous les fichiers `locales/*.yaml` en clés pointées. Idempotent."""
    cat: dict[str, dict[str, str]] = {}
    for code in LANGUAGES:
        path = LOCALES_DIR / f"{code}.yaml"
        if path.exists():
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            cat[code] = _flatten(data)
    _CATALOG.clear()
    _CATALOG.update(cat)
    return _CATALOG


class _Safe(dict):
    def __missing__(self, key):  # placeholder inconnu → laissé tel quel
        return "{" + key + "}"


def translate(key: str, lang: str | None = None, **params) -> str:
    """Traduit `key` dans `lang` (fallback fr → clé brute). `params` interpolés via `{nom}`."""
    if not _CATALOG:
        load_catalog()
    lang = lang if lang in _CATALOG else DEFAULT_LANG
    val = _CATALOG.get(lang, {}).get(key)
    if val is None:
        val = _CATALOG.get(DEFAULT_LANG, {}).get(key, key)
    if params:
        try:
            return val.format_map(_Safe(params))
        except (ValueError, IndexError):
            return val
    return val


def available(lang: str | None) -> str:
    return lang if lang in _CATALOG else DEFAULT_LANG


def negotiate(request) -> str:
    """Langue de la requête : session → cookie `lang` → Accept-Language → défaut. Bornée à ENABLED."""
    sess = getattr(request, "session", {}) or {}
    for cand in (sess.get("lang"), request.cookies.get("lang")):
        if cand in ENABLED:
            return cand
    accept = request.headers.get("accept-language", "")
    for part in accept.split(","):
        code = part.split(";")[0].strip().lower().split("-")[0]
        if code in ENABLED:
            return code
    return DEFAULT_LANG if DEFAULT_LANG in ENABLED else ENABLED[0]


def languages() -> list[tuple[str, str]]:
    """Liste (code, nom natif) des langues ACTIVÉES, pour le sélecteur, langue par défaut en tête."""
    ordered = sorted(ENABLED, key=lambda c: (c != DEFAULT_LANG, LANGUAGES[c].lower()))
    return [(c, LANGUAGES[c]) for c in ordered]


def native_name(lang: str) -> str:
    return LANGUAGES.get(lang, lang)


load_catalog()
