"""Tiny i18n: flat JSON string tables in lang/<code>.json."""
import json
import logging

from . import config
from .paths import resource_path

log = logging.getLogger(config.LOGGER_NAME)

_language = None
_strings = {}
_warned = set()       # missing keys already logged


def _load(code: str) -> dict:
    try:
        with open(resource_path(f"lang/{code}.json"), "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError) as e:
        log.warning("Language file for '%s' unavailable: %s", code, e)
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def set_language(code: str) -> None:
    """Switch the active language (unknown codes fall back to the default)."""
    global _language, _strings
    if code not in config.LANGUAGES:
        log.warning("Unknown language '%s', using '%s'", code, config.DEFAULT_LANGUAGE)
        code = config.DEFAULT_LANGUAGE
    if code == _language:
        return
    _language = code
    _strings = _load(code)
    _warned.clear()


def get_language() -> str:
    if _language is None:
        set_language(config.DEFAULT_LANGUAGE)
    return _language


def t(key: str, **fmt) -> str:
    """Translate key; missing keys return the key itself (logged once)."""
    if _language is None:
        set_language(config.DEFAULT_LANGUAGE)
    s = _strings.get(key)
    if s is None:
        if key not in _warned:
            _warned.add(key)
            log.warning("Missing i18n key '%s' (%s)", key, _language)
        return key
    if fmt:
        try:
            return s.format(**fmt)
        except (KeyError, IndexError, ValueError):
            return s
    return s


def has(key: str) -> bool:
    """True if the active language defines key."""
    get_language()
    return key in _strings
