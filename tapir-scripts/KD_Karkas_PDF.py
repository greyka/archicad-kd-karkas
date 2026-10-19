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
import io
import os
import re
import sys
import threading
import urllib.request
import zipfile
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

from kd import __version__                         # noqa: E402
from kd.__main__ import main as kd_main            # noqa: E402
from kd.archicad import ArchicadError, Client      # noqa: E402
from kd.config import USER_PATH, load_config       # noqa: E402

TITLE = f"КД каркаса  v{__version__}"
REPO = "greyka/archicad-kd-karkas"
VERSION_FILE = "tapir-scripts/kd_plugin/kd/__init__.py"
API_VERSION = f"https://api.github.com/repos/{REPO}/contents/{VERSION_FILE}?ref=main"
RAW_VERSION = f"https://raw.githubusercontent.com/{REPO}/main/{VERSION_FILE}"
ZIP_URL = f"https://codeload.github.com/{REPO}/zip/refs/heads/main"
# обновлять себя можно только в установленной раскладке (скрипт + kd_plugin рядом)
INSTALLED = (os.path.normcase(KD_PLUGIN) == os.path.normcase(os.path.join(_here, "kd_plugin"))
             and not os.path.isdir(os.path.join(os.path.dirname(_here), ".git")))

MODES = [
    ("pdf",     "Только PDF-файл (быстро, проект не меняется)"),
    ("layouts", "Листы в Archicad (книга макетов)"),
    ("publish", "Общий PDF из готовых листов Archicad (без перестройки)"),
    ("both",    "Пересоздать листы в Archicad + общий PDF"),
]


def _vt(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0"))


def remote_version():
    """Версия плагина в ветке main на GitHub (None — нет сети)."""
    # API отдаёт свежее сразу; raw.githubusercontent кэширует до 5 минут — запасной
    for url, hdr in ((API_VERSION, {"Accept": "application/vnd.github.raw", "User-Agent": "kd-plugin"}),
                     (RAW_VERSION, {"Cache-Control": "no-cache"})):
        try:
            txt = urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=6).read().decode("utf-8")
            m = re.search(r'__version__\s*=\s*"([^"]+)"', txt)
            if m:
                return m.group(1)
        except Exception:
            continue
    return None


def self_update():
    """Скачивает tapir-scripts/ из GitHub поверх своей папки."""
    data = urllib.request.urlopen(ZIP_URL, timeout=60).read()
    z = zipfile.ZipFile(io.BytesIO(data))
    root = z.namelist()[0].split("/")[0] + "/tapir-scripts/"
    n = 0
    for name in z.namelist():
        if not name.startswith(root) or name.endswith("/"):
            continue
        path = os.path.join(_here, *name[len(root):].split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(z.read(name))
        n += 1
    return n


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
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int)
    ap.add_argument("--host")
    args, _ = ap.parse_known_args()

    info = project_info(args.port)
    if not info:
        messagebox.showerror(TITLE, "Нет связи с Archicad.\n\nЗапустите скрипт из палитры Tapir.")
        return

    cfg = load_config()

    root = tk.Tk()
    root.title(TITLE)
    root.resizable(False, False)
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
    upd = ttk.Button(frm, text="Обновить")
    upd.grid(row=4, column=0, sticky="w")
    news = tk.StringVar(value="")
    ttk.Label(frm, textvariable=news, foreground="#1a7f37").grid(row=7, column=0, columnspan=2, sticky="w")

    def show_version(rv):
        if rv and _vt(rv) > _vt(__version__):
            news.set(f"Доступна версия {rv} — нажмите «Обновить»")
        elif rv:
            news.set(f"Установлена последняя версия ({__version__})")
        else:
            news.set("")

    threading.Thread(target=lambda: root.after(0, show_version, remote_version()), daemon=True).start()

    def do_update():
        if not INSTALLED:
            messagebox.showinfo(TITLE, "Запуск из папки разработки — обновляйте через git pull.")
            return
        upd.state(["disabled"]); btn.state(["disabled"])
        status.set("Проверяю обновления на GitHub…")

        def work_upd():
            rv = remote_version()
            if rv is None:
                root.after(0, lambda: (status.set("Нет связи с GitHub."), upd.state(["!disabled"]),
                                       btn.state(["!disabled"])))
                return
            if _vt(rv) <= _vt(__version__):
                root.after(0, lambda: (status.set(f"Обновлений нет — у вас последняя версия {__version__}."),
                                       upd.state(["!disabled"]), btn.state(["!disabled"])))
                return
            try:
                root.after(0, status.set, f"Скачиваю версию {rv}…")
                self_update()
            except Exception as e:
                root.after(0, lambda: (messagebox.showerror(TITLE, f"Не удалось обновить: {e}"),
                                       upd.state(["!disabled"]), btn.state(["!disabled"])))
                return

            def restart():
                messagebox.showinfo(TITLE, f"Обновлено до версии {rv}. Окно откроется заново.")
                root.destroy()
                os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + sys.argv[1:])
            root.after(0, restart)
        threading.Thread(target=work_upd, daemon=True).start()

    upd.configure(command=do_update)

    def done(result, error):
        btn.state(["!disabled"])
        if error:
            status.set("Ошибка.")
            messagebox.showerror(TITLE, error)
            return
        status.set(f"Готово: {result}")
        try:
            os.startfile(result)
        except OSError:
            pass

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
        try:
            res = kd_main(argv)
            root.after(0, done, res, None)
        except ArchicadError as e:
            root.after(0, done, None, str(e))
        except SystemExit as e:
            root.after(0, done, None, str(e.code or "Прервано"))
        except Exception:
            root.after(0, done, None, traceback.format_exc(limit=3))

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
                    "both": "Строю листы и публикую PDF… (3–4 мин)"}[m])
        threading.Thread(target=work, daemon=True).start()

    btn.configure(command=run)
    root.mainloop()


if __name__ == "__main__":
    main()
