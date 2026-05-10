"""ULID helpers with short typed prefixes used in store.json (e.g. ``u_``, ``wi_``)."""

from __future__ import annotations

from ulid import ULID

_PREFIXES = {
    "user": "u_",
    "watch_item": "wi_",
    "source_document": "sd_",
    "security_event": "se_",
    "alert": "al_",
    "run": "rn_",
}


def new_id(kind: str) -> str:
    if kind not in _PREFIXES:
        raise KeyError(f"unknown id kind: {kind}")
    return f"{_PREFIXES[kind]}{ULID()!s}"
