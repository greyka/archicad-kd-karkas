"""Настройки: умолчания из плагина + правки пользователя.

config.default.json лежит в плагине и обновляется вместе с ним (GitHub).
Свои настройки — %APPDATA%\\kd_plugin\\config.json: в нём достаточно
указать только то, что отличается от умолчаний; обновления его не трогают.
"""
from __future__ import annotations

import json
import os

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_PATH = os.path.join(PLUGIN_DIR, "config.default.json")
USER_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "kd_plugin")
USER_PATH = os.path.join(USER_DIR, "config.json")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _read(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return json.load(f)


def load_config(path: str | None = None) -> dict:
    """path — явный файл (вместо пользовательского); иначе умолчания + USER_PATH."""
    cfg = _read(DEFAULT_PATH)
    return _merge(cfg, _read(path) if path else _read(USER_PATH))
