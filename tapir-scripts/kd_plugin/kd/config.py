"""Настройки плагина — три слоя, каждый следующий перекрывает предыдущий:

1. config.default.json — в плагине, обновляется вместе с ним (GitHub);
2. %APPDATA%\\kd_plugin\\config.json — расширенные настройки (префиксы марок,
   порядок слоёв…), правятся Блокнотом;
3. <папка плагинов>\\settings.ini — то, что правится в «Менеджере плагинов
   Archicad» (поля описаны в _setup\\settings_schema.json, ключ "path" —
   куда значение попадает в конфиг).

Обновления не трогают ни 2, ни 3.
"""
from __future__ import annotations

import configparser
import json
import os

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))     # …\tapir-scripts\kd_plugin
ROOT = os.path.dirname(os.path.dirname(PLUGIN_DIR))                           # C:\ArchicadPlugins
DEFAULT_PATH = os.path.join(PLUGIN_DIR, "config.default.json")
USER_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "kd_plugin")
USER_PATH = os.path.join(USER_DIR, "config.json")
SETTINGS_INI = os.path.join(ROOT, "settings.ini")
SCHEMA_PATH = os.path.join(ROOT, "_setup", "settings_schema.json")
MANAGER_EXE = os.path.join(ROOT, "Менеджер плагинов Archicad.exe")


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


def _set_path(d: dict, path: str, value) -> None:
    keys = path.split(".")
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


def schema_sections() -> list:
    """Разделы настроек: <плагин>.settings.json рядом со скриптами + общий _setup\\settings_schema.json."""
    import glob
    files = sorted(glob.glob(os.path.join(ROOT, "tapir-scripts", "*.settings.json"))) + [SCHEMA_PATH]
    out = []
    for f in files:
        if os.path.isfile(f):
            out += _read(f).get("sections", [])
    return out


def _from_settings_ini() -> dict:
    """Значения из settings.ini → вложенный словарь по "path" схемы."""
    if not os.path.isfile(SETTINGS_INI):
        return {}
    cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
    cp.read(SETTINGS_INI, encoding="utf-8-sig")
    out: dict = {}
    for sec in schema_sections():
        for it in sec["items"]:
            path = it.get("path")
            raw = cp.get(sec["id"], it["key"], fallback=None)
            if not path or raw is None:
                continue
            raw = raw.strip()
            t = it["type"]
            try:
                if t == "bool":
                    val = raw.lower() in ("1", "true", "yes", "да", "on")
                elif t == "int":
                    val = int(raw or 0) or None          # 0 — «по умолчанию»
                elif t == "float":
                    val = float(raw.replace(",", "."))
                elif t == "list":
                    val = [x.strip() for x in raw.split(",") if x.strip()]
                else:
                    val = raw or (None if path.endswith("publisher_set") else "")
            except ValueError:
                continue
            _set_path(out, path, val)
    return out


def load_config(path: str | None = None) -> dict:
    """path — явный файл вместо пользовательского config.json."""
    cfg = _merge(_read(DEFAULT_PATH), _read(path) if path else _read(USER_PATH))
    return _merge(cfg, _from_settings_ini())


def plugins_version() -> str:
    """Версия комплекта (VERSION в папке плагинов), иначе — версия ядра."""
    try:
        with open(os.path.join(ROOT, "VERSION"), encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        from . import __version__
        return __version__
