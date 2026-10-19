# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# -*- coding: utf-8 -*-
"""Обновление плагинов Archicad с GitHub (git на компьютере не нужен).

Запуск:  uv run --script <корень>\\_setup\\update.py --root <корень> [--auto]
  --auto   — автозагрузка Windows: молча, окно только если обновилось или ошибка;
             ничего не делает, если в настройках выключено «Проверять обновления».
  --check  — только узнать версии (JSON в stdout) — для «Менеджера плагинов».
  --quiet  — без окон (вывод в консоль).
  --force  — поставить заново, даже если версия та же.

Канал (настройки → Обновление → «Что устанавливать»):
  releases — только выпущенные версии (релизы GitHub, тег vX.Y.Z) — по умолчанию;
  main     — последние изменения ветки main.

Что делает: скачивает архив версии, копирует tapir-scripts (плагины палитры Tapir),
_setup и файлы корня (VERSION, CHANGELOG.md, менеджер, …) в <корень>. Файл настроек
settings.ini не трогает. Занятые файлы (запущенный менеджер) переименовываются в *.old
и заменяются — новая версия заработает после перезапуска.
"""
import argparse
import configparser
import ctypes
import glob
import io
import json
import os
import shutil
import sys
import tempfile
import traceback
import urllib.error
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
TITLE = "Обновление плагинов Archicad"
ROOT_FILES = ("VERSION", "CHANGELOG.md", "ПРОЧТИ.txt", "README.md", "Обновить.bat", "Установить.bat",
              "Удалить.bat", "Менеджер плагинов Archicad.exe")
PLUGIN_DIRS = ("tapir-scripts",)
AUTO = QUIET = False


def msg(text, flags=0x40):
    if QUIET or (AUTO and not flags & 0x10 and not text.startswith("Плагины обновлены")):
        print(text)
        return 1
    return ctypes.windll.user32.MessageBoxW(None, text, TITLE, flags | 0x40000)  # поверх окон


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "archicad-plugins-updater"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def repo_config():
    cp = configparser.ConfigParser(inline_comment_prefixes=(";",))
    cp.read(os.path.join(HERE, "update.ini"), encoding="utf-8")
    return cp["update"]["repo"].strip(), cp["update"].get("branch", "main").strip()


def user_setting(root, key, default):
    cp = configparser.ConfigParser(interpolation=None, inline_comment_prefixes=(";",))
    cp.read(os.path.join(root, "settings.ini"), encoding="utf-8-sig")
    return cp.get("update", key, fallback=default).strip() or default


def installed(root):
    """(id, версия) установленной копии: id — тег или коммит из version.txt."""
    vid = ""
    if os.path.isfile(os.path.join(root, "version.txt")):
        vid = open(os.path.join(root, "version.txt"), encoding="utf-8").read().split("\n")[0].strip()
    ver = "?"
    if os.path.isfile(os.path.join(root, "VERSION")):
        ver = open(os.path.join(root, "VERSION"), encoding="utf-8").read().strip()
    return vid, ver


def latest(repo, branch, channel):
    """→ dict(id, version, title, notes, zip, channel). Нет релизов — берём ветку."""
    if channel == "releases":
        try:
            r = json.loads(get(f"https://api.github.com/repos/{repo}/releases/latest"))
            tag = r["tag_name"]
            return dict(id=tag, version=tag.lstrip("vV"), title=r.get("name") or tag,
                        notes=(r.get("body") or "").strip(), channel="releases",
                        zip=f"https://codeload.github.com/{repo}/zip/refs/tags/{tag}")
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
    c = json.loads(get(f"https://api.github.com/repos/{repo}/commits/{branch}"))
    sha = c["sha"]
    try:
        ver = get(f"https://raw.githubusercontent.com/{repo}/{sha}/VERSION").decode("utf-8").strip()
    except Exception:
        ver = "?"
    return dict(id=sha, version=f"{ver} ({sha[:7]})", title=c["commit"]["message"].split("\n")[0],
                notes="\n".join(l for l in c["commit"]["message"].strip().split("\n")
                                if not l.lower().startswith("co-authored-by")).strip(), channel="main",
                zip=f"https://codeload.github.com/{repo}/zip/{sha}")


def same_file(a, b):
    if not os.path.isfile(b) or os.path.getsize(a) != os.path.getsize(b):
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        return fa.read() == fb.read()


def put_file(src, dst):
    """Копирует файл; занятый (запущенный .exe) — в .old и кладёт новый."""
    if same_file(src, dst):
        return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        shutil.copy2(src, dst)
    except PermissionError:
        old, n = dst + ".old", 1
        while os.path.exists(old):
            try:
                os.remove(old)
            except OSError:
                old, n = f"{dst}.old{n}", n + 1
        os.replace(dst, old)
        shutil.copy2(src, dst)
    return True


def put_tree(src, dst):
    changed = []
    for base, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            rel = os.path.relpath(os.path.join(base, f), src)
            if put_file(os.path.join(base, f), os.path.join(dst, rel)):
                changed.append(rel)
    return changed


def cleanup_old(root):
    for f in glob.glob(os.path.join(root, "*.old*")) + glob.glob(os.path.join(root, "*", "*.old*")):
        try:
            os.remove(f)
        except OSError:
            pass   # ещё занят — удалим в следующий раз


def install(root, info):
    tmp = tempfile.mkdtemp(prefix="acp_update_")
    try:
        zipfile.ZipFile(io.BytesIO(get(info["zip"], 180))).extractall(tmp)
        src = os.path.join(tmp, os.listdir(tmp)[0])          # <repo>-<версия>\
        updated = []
        for d in PLUGIN_DIRS:
            if os.path.isdir(os.path.join(src, d)):
                updated += put_tree(os.path.join(src, d), os.path.join(root, d))
        put_tree(os.path.join(src, "_setup"), os.path.join(root, "_setup"))
        for f in ROOT_FILES:
            if os.path.isfile(os.path.join(src, f)):
                put_file(os.path.join(src, f), os.path.join(root, f))

        sys.path.insert(0, os.path.join(root, "_setup"))
        import archicad_setup as acs
        notes = []
        try:
            uv = acs.find_uv()
            notes += acs.register_tapir(root, uv)
            uvw = os.path.join(os.path.dirname(uv), "uvw.exe") if uv else None
            acs.install_shortcuts(root, uvw if uvw and os.path.isfile(uvw) else None)
        except Exception:
            traceback.print_exc()
        running = acs.archicad_running()

        with open(os.path.join(root, "version.txt"), "w", encoding="utf-8") as f:
            f.write(f"{info['id']}\n{info['version']}\n{info['title']}\n")
        return updated, running
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    global AUTO, QUIET
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(HERE))
    ap.add_argument("--auto", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()
    AUTO, QUIET = a.auto, a.quiet or a.check
    root = os.path.abspath(a.root)
    if a.auto and user_setting(root, "auto", "true").lower() not in ("1", "true", "yes", "да", "on"):
        return
    cleanup_old(root)

    repo, branch = repo_config()
    channel = user_setting(root, "channel", "releases")
    cur_id, cur_ver = installed(root)
    try:
        info = latest(repo, branch, channel)
    except Exception as e:
        if a.check:
            print(json.dumps(dict(error=str(e), installed_version=cur_ver), ensure_ascii=False))
        elif not AUTO:
            msg(f"Не удалось связаться с GitHub ({repo}):\n{e}", 0x10)
        return
    available = info["id"] != cur_id

    if a.check:
        print(json.dumps(dict(installed_version=cur_ver, installed_id=cur_id,
                              latest_version=info["version"], latest_id=info["id"],
                              title=info["title"], notes=info["notes"], channel=info["channel"],
                              update_available=available, register_pending=False,
                              repo=repo), ensure_ascii=False))
        return
    if not available and not a.force:
        msg(f"Установлена последняя версия: {cur_ver}.")
        return

    updated, running = install(root, info)
    changes = f"{len(updated)} файл(ов)" if updated else "служебные файлы"
    notes = f"\n\n{info['notes'][:1500]}" if info["notes"] and info["notes"] != info["title"] else ""
    tail = ("\n\nArchicad открыт: в палитре Tapir выберите «Reload scripts…» "
            "(или перезапустите Archicad)." if running else "")
    msg(f"Плагины обновлены: {cur_ver} → {info['version']}\n«{info['title']}»{notes}"
        f"\n\nОбновлено: {changes}{tail}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        msg("Ошибка обновления:\n\n" + traceback.format_exc(), 0x10)
        raise
