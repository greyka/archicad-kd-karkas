# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///

##############################################
# ПЛОЩАДИ ПОВЕРХНОСТЕЙ
# Для Archicad с аддоном Tapir (палитра Tapir).
#
# Считает площадь всех поверхностей элементов (доски ArchiFrame —
# по контуру с запилами и толщине; перекрытия, морфы и пр. — по
# свойствам Archicad). Отчёт HTML + CSV рядом с файлом проекта.
##############################################

import argparse
import os
import sys
import threading
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

_here = os.path.dirname(os.path.abspath(__file__))
KD_PLUGIN = os.environ.get("KD_PLUGIN_DIR") or next(
    (p for p in (os.path.join(_here, "kd_plugin"), os.path.dirname(_here))
     if os.path.isdir(os.path.join(p, "kd"))), os.path.join(_here, "kd_plugin"))
sys.path.insert(0, KD_PLUGIN)

import subprocess                                  # noqa: E402

from kd.archicad import ArchicadError, Client      # noqa: E402
from kd.pick import pick_port                     # noqa: E402
from kd.config import MANAGER_EXE, load_config, plugins_version   # noqa: E402
from kd.surfaces import collect, write_report      # noqa: E402
from kd import report                             # noqa: E402

TITLE = f"Площади поверхностей  v{plugins_version()}"


def open_manager():
    """«Настройки и версия…» — Менеджер плагинов Archicad (как у «КД каркаса»)."""
    if os.path.isfile(MANAGER_EXE):
        subprocess.Popen([MANAGER_EXE, "--tab=update"], cwd=os.path.dirname(MANAGER_EXE))
    else:
        messagebox.showinfo(TITLE, "Менеджер плагинов не найден — запустите «Установить.bat» "
                                   "из комплекта «Плагины Archicad».")


def fmt(x, nd=None):
    """Число по-русски: 15,28; целые без «,0»."""
    x = float(x or 0)
    if nd is None:
        return f"{x:g}".replace(".", ",")
    return f"{x:.{nd}f}".replace(".", ",")


def default_output(info):
    path = info.get("projectPath") or info.get("projectLocation")
    name = info.get("projectName") or "проект"
    folder = os.path.dirname(path) if path and not info.get("isUntitled") else os.path.join(KD_PLUGIN, "out")
    return os.path.join(folder, f"Площади поверхностей {name}.html")


def main():
    report.start_log("Ploshchadi_Poverkhnostey")
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

    try:
        info = Client(args.port).tapir("GetProjectInfo")
    except Exception:
        messagebox.showerror(TITLE, "Нет связи с Archicad.\n\nЗапустите скрипт из палитры Tapir.")
        return
    report.set_project(info.get("projectName") or "")
    full = load_config()
    cfg = full.get("archicad", {})
    sset = full.get("surfaces", {})              # умолчания — «Менеджер плагинов» → «Площади поверхностей»

    root = tk.Tk()
    root.title(TITLE)
    root.resizable(False, False)
    report.fix_hotkeys(root)
    frm = ttk.Frame(root, padding=12)
    frm.grid()

    selected = tk.BooleanVar(value=bool(sset.get("selected", True)))
    ttk.Checkbutton(frm, text="Только выделенные элементы", variable=selected).grid(
        row=0, column=0, columnspan=2, sticky="w")

    fields = [("Слой содержит (пусто — все):", sset.get("layer") or ""),
              ("Мин. ширина, мм (0 — все):", fmt(sset.get("min_width", 0))),
              ("Толщина досок без библиотеки, мм:", fmt(sset.get("thickness", 40))),
              ("Отчёт HTML:", default_output(info))]
    vars_ = []
    for i, (label, val) in enumerate(fields, start=1):
        ttk.Label(frm, text=label).grid(row=i, column=0, sticky="w")
        v = tk.StringVar(value=val)
        ttk.Entry(frm, textvariable=v, width=48 if i == 4 else 20).grid(row=i, column=1, sticky="w", pady=2)
        vars_.append(v)
    layer, minw, thick, out = vars_
    ttk.Label(frm, foreground="#888", wraplength=420, justify="left",
              text="Доски ArchiFrame с загруженной библиотекой (.pla) считаются точно — по контуру "
                   "с запилами и своей толщине. Толщина из поля — только для досок без библиотеки."
              ).grid(row=5, column=0, columnspan=2, sticky="w", pady=(6, 0))

    status = tk.StringVar(value="")
    ttk.Label(frm, textvariable=status, foreground="#555", wraplength=420).grid(
        row=7, column=0, columnspan=2, sticky="w", pady=(6, 0))
    btn = ttk.Button(frm, text="Посчитать")
    btn.grid(row=6, column=1, sticky="e", pady=(8, 0))
    ttk.Button(frm, text="Настройки и версия…", command=open_manager).grid(
        row=6, column=0, sticky="w", pady=(8, 0))
    ttk.Button(frm, text="Сообщить о проблеме…", command=lambda: report.report_dialog(TITLE, "", root)).grid(
        row=8, column=0, sticky="w", pady=(6, 0))

    def num(v, name):
        s = v.get().strip().replace(",", ".")
        try:
            return float(s) if s else 0.0
        except ValueError:
            raise ArchicadError(f"«{name}»: нужно число, а не «{v.get()}».")

    def done(msg, path, error, crash=False):
        btn.state(["!disabled"])
        if error:
            status.set("Ошибка.")
            if crash:                           # неожиданная — с кнопкой «Отправить разработчику»
                report.report_dialog(TITLE, error, root)
            else:
                messagebox.showerror(TITLE, error)
            return
        print(msg)
        status.set(msg)
        if sset.get("open_report", True):
            try:
                os.startfile(path)
            except OSError:
                pass

    def work():
        try:
            t = num(thick, "Толщина") or None
            rows = collect(selected.get(), layer.get().strip(), num(minw, "Мин. ширина"), t,
                           args.port or cfg.get("port"), cfg.get("object_libparts"))
            path = out.get().strip()
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            note = []
            if selected.get():
                note.append("выделенные")
            if layer.get().strip():
                note.append(f"слой «{layer.get().strip()}»")
            if num(minw, "Мин. ширина"):
                note.append(f"ширина ≥ {minw.get()} мм")
            path, total, face, missing = write_report(rows, path, info.get("projectName") or "", ", ".join(note))
            msg = (f"Элементов {len(rows)}: все поверхности {fmt(total, 2)} м², пласть {fmt(face, 2)} м²"
                   + (f"; без площади {missing}" if missing else ""))
            root.after(0, done, msg, path, None)
        except ArchicadError as e:
            print(f"Ошибка Archicad: {e}")
            root.after(0, done, "", "", str(e))
        except Exception:
            tb = traceback.format_exc()
            print(tb)
            root.after(0, done, "", "", tb, True)

    def run():
        btn.state(["disabled"])
        status.set("Считаю…")
        threading.Thread(target=work, daemon=True).start()

    btn.configure(command=run)
    root.mainloop()


if __name__ == "__main__":
    main()
