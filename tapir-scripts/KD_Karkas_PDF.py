# /// script
# requires-python = ">=3.11"
# dependencies = ["pymupdf"]
# ///

##############################################
# КД КАРКАСА В PDF
# Для Archicad с аддоном Tapir (палитра Tapir).
#
# Разбирает доски ArchiFrame открытого проекта на марки и выпускает
# комплект PDF: ведомость чертежей, СП-1, листы деталей с размерами.
# PDF сохраняется рядом с файлом проекта.
##############################################

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import urllib.request
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

# Плагин лежит рядом со скриптом (custom-scripts\kd_plugin) — так его ставит
# install.bat; KD_PLUGIN_DIR позволяет запускать из папки разработки.
_here = os.path.dirname(os.path.abspath(__file__))
KD_PLUGIN = os.environ.get("KD_PLUGIN_DIR") or next(
    (p for p in (os.path.join(_here, "kd_plugin"), os.path.dirname(_here))
     if os.path.isdir(os.path.join(p, "kd"))), os.path.join(_here, "kd_plugin"))
sys.path.insert(0, KD_PLUGIN)

from kd.__main__ import main as kd_main            # noqa: E402
from kd.archicad import ArchicadError, Client      # noqa: E402
from kd.pick import pick_port                     # noqa: E402
from kd.config import MANAGER_EXE, USER_PATH, load_config, plugins_version   # noqa: E402
from kd import report                             # noqa: E402

VERSION = plugins_version()
TITLE = f"КД каркаса  v{VERSION}"
REPO = "greyka/archicad-kd-karkas"
RELEASES_URL = f"https://github.com/{REPO}/releases"

MODES = [
    ("pdf",     "Только PDF-файл (быстро, проект не меняется)"),
    ("layouts", "Листы в Archicad (книга макетов)"),
    ("publish", "Общий PDF из готовых листов Archicad (без перестройки)"),
    ("both",    "Пересоздать листы в Archicad + общий PDF"),
    ("props",   "Марки и параметры в свойства досок (для интерактивного каталога)"),
]


def _vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def remote_version():
    """Последняя выпущенная версия на GitHub (тег релиза), None — нет сети."""
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{REPO}/releases/latest",
                                     headers={"User-Agent": "archicad-plugins"})
        tag = json.loads(urllib.request.urlopen(req, timeout=6).read().decode("utf-8"))["tag_name"]
        return tag.lstrip("vV")
    except Exception:
        return None


def open_manager():
    """«Настройки и версия…» — Менеджер плагинов Archicad на вкладке обновления."""
    if os.path.isfile(MANAGER_EXE):
        subprocess.Popen([MANAGER_EXE, "--tab=update"], cwd=os.path.dirname(MANAGER_EXE))
        return True
    return False


def existing_sheets(port, cfg):
    """Сколько листов уже в подмножестве КД (0 — нет подмножества)."""
    try:
        from kd.ac_layouts import _children, _items, layout_book
        c = Client(port)
        name = cfg.get("archicad", {}).get("subset_name", "КД каркаса (авто)")
        for it in _items(layout_book(c)):
            if it.get("type") == "SubSetItem" and it.get("name") == name:
                return sum(1 for ch in _children(it) if ch.get("type") == "LayoutItem")
    except Exception:
        pass
    return 0


def project_info(port):
    try:
        return Client(port).tapir("GetProjectInfo")
    except Exception:
        return {}


def default_output(info):
    path = info.get("projectPath") or info.get("projectLocation")
    name = info.get("projectName") or "проект"
    if path and not info.get("isUntitled"):
        return os.path.join(os.path.dirname(path), f"КД {name}.pdf")
    return os.path.join(KD_PLUGIN, "out", f"КД {name}.pdf")


def main():
    report.start_log("KD_Karkas_PDF")
    report.install_hooks(TITLE)
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--host")
    args, _ = ap.parse_known_args()
    # из палитры Tapir порт приходит в --port; из менеджера — выбираем Archicad сами
    args.port = pick_port(TITLE, args.port)
    if not args.port:
        messagebox.showerror(TITLE, "Не найден открытый Archicad с аддоном Tapir.\n\n"
                                    "Откройте проект в Archicad и запустите плагин снова.")
        return

    info = project_info(args.port)
    if not info:
        messagebox.showerror(TITLE, "Нет связи с Archicad.\n\nЗапустите скрипт из палитры Tapir.")
        return
    report.set_project(info.get("projectName") or "")

    cfg = load_config()

    root = tk.Tk()
    root.title(TITLE)
    root.resizable(False, False)
    report.fix_hotkeys(root)
    frm = ttk.Frame(root, padding=12)
    frm.grid()

    ttk.Label(frm, text="Объект (в штампе):").grid(row=0, column=0, sticky="w")
    name = tk.StringVar(value=info.get("projectName") or cfg.get("project_name", ""))
    ttk.Entry(frm, textvariable=name, width=42).grid(row=0, column=1, pady=2)

    ttk.Label(frm, text="Файл PDF:").grid(row=1, column=0, sticky="w")
    out = tk.StringVar(value=default_output(info))
    ttk.Entry(frm, textvariable=out, width=42).grid(row=1, column=1, pady=2)

    selected = tk.BooleanVar(value=False)
    ttk.Checkbutton(frm, text="Только выделенные элементы", variable=selected).grid(
        row=2, column=1, sticky="w", pady=(4, 0))
    mode = tk.StringVar(value="pdf")
    box = ttk.LabelFrame(frm, text=" Что сделать ", padding=(8, 4))
    box.grid(row=3, column=0, columnspan=2, sticky="we", pady=6)
    for key, text in MODES:
        ttk.Radiobutton(box, text=text, value=key, variable=mode).grid(sticky="w")
    ttk.Label(frm, text=f"Настройки: {USER_PATH}", foreground="#888").grid(
        row=6, column=0, columnspan=2, sticky="w")

    status = tk.StringVar(value="")
    ttk.Label(frm, textvariable=status, foreground="#555", wraplength=380).grid(
        row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

    btn = ttk.Button(frm, text="Выпустить КД")
    btn.grid(row=4, column=1, sticky="e")
    upd = ttk.Button(frm, text="Настройки и версия…")
    upd.grid(row=4, column=0, sticky="w")
    news = tk.StringVar(value="")
    ttk.Label(frm, textvariable=news, foreground="#1a7f37").grid(row=7, column=0, columnspan=2, sticky="w")
    ttk.Button(frm, text="Сообщить о проблеме…", command=lambda: report.report_dialog(TITLE, "", root)).grid(
        row=8, column=0, sticky="w", pady=(6, 0))

    def show_version(rv):
        if rv and _vt(rv) > _vt(VERSION):
            news.set(f"Доступна версия {rv} — «Настройки и версия…» → Обновить")
        elif rv:
            news.set(f"Установлена последняя версия ({VERSION})")
        else:
            news.set("")

    threading.Thread(target=lambda: root.after(0, show_version, remote_version()), daemon=True).start()

    def settings_and_version():
        if not open_manager():
            if messagebox.askyesno(
                    TITLE, "Менеджер плагинов не найден — плагин запущен не из папки «Плагины Archicad».\n\n"
                           "Скачайте последнюю версию с GitHub и запустите «Установить.bat» "
                           "(один раз на компьютер). Открыть страницу загрузки?"):
                import webbrowser
                webbrowser.open(RELEASES_URL)

    upd.configure(command=settings_and_version)

    def done(result, error, crash=False):
        btn.state(["!disabled"])
        if error:
            status.set("Ошибка.")
            if crash:                           # неожиданная — с кнопкой «Отправить разработчику»
                report.report_dialog(TITLE, error, root)
            else:
                messagebox.showerror(TITLE, error)
            return
        if result and os.path.isfile(result):
            status.set(f"Готово: {result}")
            try:
                os.startfile(result)
            except OSError:
                pass
        else:                                   # режим без PDF (свойства)
            status.set(f"Готово. {result or ''}  Обновите каталог в Archicad.")

    def work():
        argv = ["--archicad", "--name", name.get(), "-o", out.get()]
        if args.port:
            argv += ["--port", str(args.port)]
        if selected.get():
            argv.append("--selected")
        m = mode.get()
        if m in ("layouts", "both"):
            argv.append("--layouts")
        if m in ("publish", "both"):
            argv.append("--publish")
        if m == "props":
            argv += ["--props", "--no-pdf"]
        print(f"Режим: {m}  argv={argv}")
        try:
            res = kd_main(argv)
            print(f"Готово: {res}")
            root.after(0, done, res, None)
        except ArchicadError as e:
            print(f"Ошибка Archicad: {e}")
            root.after(0, done, None, str(e))
        except SystemExit as e:
            print(f"Прервано: {e.code}")
            root.after(0, done, None, str(e.code or "Прервано"))
        except Exception:
            tb = traceback.format_exc()
            print(tb)
            root.after(0, done, None, tb, True)

    def run():
        m = mode.get()
        if m in ("layouts", "both"):
            n = existing_sheets(args.port, cfg)
            if n and not messagebox.askyesno(
                    TITLE, f"В проекте уже есть листы КД: {n} шт.\n\n"
                           "Они будут удалены и построены заново —\n"
                           "ручные правки на этих листах пропадут.\n\nПересоздать?",
                    icon="warning", default="no"):
                return
        btn.state(["disabled"])
        status.set({"pdf": "Читаю модель и строю PDF…",
                    "layouts": "Строю листы в Archicad… (2–3 мин)",
                    "publish": "Публикую листы Archicad в PDF… (~1 мин)",
                    "both": "Строю листы и публикую PDF… (3–4 мин)",
                    "props": "Пишу марки и параметры в свойства досок…"}[m])
        threading.Thread(target=work, daemon=True).start()

    btn.configure(command=run)
    root.mainloop()


if __name__ == "__main__":
    main()
