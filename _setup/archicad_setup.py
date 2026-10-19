# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# -*- coding: utf-8 -*-
"""Подключение плагинов к Archicad (палитра Tapir) и ярлыки — общее для установки и обновления.

    uv run --script _setup/archicad_setup.py --root C:\\ArchicadPlugins [--uv <путь к uv.exe>]

1. В «Документы\\Tapir\\config.json» добавляется локальная папка <корень>\\tapir-scripts
   (в палитре видны только скрипты верхнего уровня, служебные модули — нет).
   Старое подключение через репозиторий GitHub (версии 1.1–1.4) убирается,
   чтобы кнопки не задваивались; старая копия в custom-scripts — тоже.
2. Ярлыки «Менеджер плагинов Archicad» — рабочий стол и меню «Пуск»,
   «Обновление плагинов Archicad» — автозагрузка Windows (выключается в менеджере).
"""
import argparse
import json
import os
import shutil
import subprocess

REPO = ("greyka", "archicad-kd-karkas")
TITLE = "Плагины Archicad"
SCRIPTS_PATTERN = r"[^/\\]+\.py"          # только скрипты верхнего уровня tapir-scripts


def documents():
    try:
        import ctypes
        from ctypes import wintypes
        buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)   # CSIDL_PERSONAL
        if buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def archicad_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Archicad.exe", "/NH"],
                         capture_output=True, text=True, creationflags=0x08000000).stdout
    return "archicad.exe" in out.lower()


def register_tapir(root, uv=None):
    """→ список сообщений о том, что сделано."""
    notes = []
    tdir = os.path.join(documents(), "Tapir")
    cfg_path = os.path.join(tdir, "config.json")
    os.makedirs(tdir, exist_ok=True)
    if os.path.isfile(cfg_path):
        with open(cfg_path, encoding="utf-8-sig") as f:
            cfg = json.load(f)
    else:
        cfg = {"repositories": [{"displayName": "Tapir", "repoOwner": "ENZYME-APD",
                                 "repoName": "tapir-archicad-automation", "relativeLoc": "builtin-scripts",
                                 "token": "", "excludeFromDownloadPattern": "", "includePattern": "",
                                 "excludePattern": ""}],
               "localFolders": [], "askUpdatingAddOnBeforeEachExecution": False,
               "uvLocation": "", "pythonLocation": ""}

    repos = cfg.get("repositories") or []
    keep = [r for r in repos if (r.get("repoOwner"), r.get("repoName")) != REPO]
    if len(keep) != len(repos):
        notes.append("старое подключение через GitHub-репозиторий убрано")
    cfg["repositories"] = keep

    path = os.path.join(os.path.abspath(root), "tapir-scripts")
    folders = [f for f in (cfg.get("localFolders") or [])
               if os.path.normcase(os.path.abspath(f.get("path", ""))) != os.path.normcase(path)]
    folders.append({"displayName": TITLE, "path": path, "includePattern": SCRIPTS_PATTERN, "excludePattern": ""})
    cfg["localFolders"] = folders
    if uv and not cfg.get("uvLocation"):
        cfg["uvLocation"] = uv
    # Tapir перечитывает config.json на ходу, и при открытом Archicad это однажды
    # уронило его (2026-10-19) — поэтому пишем файл, только если что-то меняется.
    old = None
    if os.path.isfile(cfg_path):
        with open(cfg_path, encoding="utf-8-sig") as f:
            old = json.load(f)
    if old != cfg:
        with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        notes.append(f"палитра Tapir: подключена папка {path}")
        if archicad_running():
            notes.append("Archicad открыт — перезапустите его, чтобы палитра Tapir подхватила изменения")
    else:
        notes.append(f"палитра Tapir: папка {path} уже подключена — без изменений")

    cs = os.path.join(tdir, "custom-scripts")              # копия установщика 1.0
    for old in ("KD_Karkas_PDF.py", "kd_plugin"):
        p = os.path.join(cs, old)
        if os.path.isdir(p):
            shutil.rmtree(p, ignore_errors=True)
            notes.append("старая копия в custom-scripts убрана")
        elif os.path.isfile(p):
            os.remove(p)
    return notes


def _shortcut(lnk, target, args="", workdir="", icon="", desc=""):
    ps = ("$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:LNK);"
          "$s.TargetPath=$env:TGT;$s.Arguments=$env:ARGS;$s.WorkingDirectory=$env:WD;"
          "if($env:ICO){$s.IconLocation=$env:ICO};$s.Description=$env:DSC;$s.Save()")
    env = dict(os.environ, LNK=lnk, TGT=target, ARGS=args, WD=workdir, ICO=icon, DSC=desc)
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True,
                   capture_output=True, creationflags=0x08000000)


def special(name):
    import ctypes
    from ctypes import wintypes
    ids = {"desktop": 0x10, "programs": 0x02, "startup": 0x07}
    buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(None, ids[name], None, 0, buf)
    return buf.value


def install_shortcuts(root, uvw):
    root = os.path.abspath(root)
    exe = os.path.join(root, "Менеджер плагинов Archicad.exe")
    made = []
    if os.path.isfile(exe):
        for place in ("desktop", "programs"):
            lnk = os.path.join(special(place), "Менеджер плагинов Archicad.lnk")
            _shortcut(lnk, exe, workdir=root, desc="Плагины Archicad: настройки, версия, обновление")
            made.append(lnk)
    if uvw:
        lnk = os.path.join(special("startup"), "Обновление плагинов Archicad.lnk")
        upd = os.path.join(root, "_setup", "update.py")
        _shortcut(lnk, uvw, args=f'run --quiet --script "{upd}" --root "{root}" --auto', workdir=root,
                  icon=exe if os.path.isfile(exe) else "", desc="Проверка обновлений плагинов Archicad")
        made.append(lnk)
    return made


def find_uv(name="uv.exe"):
    for p in (shutil.which(name.replace(".exe", "")),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Links", name),
              os.path.join(os.path.expanduser("~"), ".local", "bin", name),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "uv", name)):
        if p and os.path.isfile(p):
            return p
    pk = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "WinGet", "Packages")
    if os.path.isdir(pk):
        for base, _, files in os.walk(pk):
            if name in files:
                return os.path.join(base, name)
    return None


def uninstall(root):
    """Убирает папку из палитры Tapir и ярлыки (файлы удаляет «Удалить.bat»)."""
    cfg_path = os.path.join(documents(), "Tapir", "config.json")
    path = os.path.normcase(os.path.join(os.path.abspath(root), "tapir-scripts"))
    if os.path.isfile(cfg_path):
        with open(cfg_path, encoding="utf-8-sig") as f:
            cfg = json.load(f)
        cfg["localFolders"] = [x for x in (cfg.get("localFolders") or [])
                               if os.path.normcase(os.path.abspath(x.get("path", ""))) != path]
        with open(cfg_path, "w", encoding="utf-8", newline="\n") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)
        print("палитра Tapir: папка отключена")
    for place, name in (("desktop", "Менеджер плагинов Archicad.lnk"), ("programs", "Менеджер плагинов Archicad.lnk"),
                        ("startup", "Обновление плагинов Archicad.lnk")):
        lnk = os.path.join(special(place), name)
        if os.path.isfile(lnk):
            os.remove(lnk)
            print("ярлык удалён:", lnk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ap.add_argument("--uv")
    ap.add_argument("--uninstall", action="store_true")
    a = ap.parse_args()
    if a.uninstall:
        uninstall(a.root)
        return
    uv = a.uv or find_uv()
    uvw = os.path.join(os.path.dirname(uv), "uvw.exe") if uv else None
    if uvw and not os.path.isfile(uvw):
        uvw = None
    for n in register_tapir(a.root, uv):
        print(n)
    for lnk in install_shortcuts(a.root, uvw):
        print("ярлык:", lnk)


if __name__ == "__main__":
    main()
