"""Выбор Archicad, когда плагин запущен из менеджера (без --port от палитры Tapir).

Один Archicad — берётся он; несколько — окно со списком проектов; ни одного — None.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from .archicad import PORTS, Client


def instances():
    """[(порт, имя проекта)] всех отвечающих Archicad с Tapir."""
    out = []
    for p in PORTS:
        try:
            if not Client._post(p, {"command": "API.IsAlive"}, timeout=0.4).get("result", {}).get("isAlive"):
                continue
        except OSError:
            continue
        try:
            info = Client(p).tapir("GetProjectInfo")
            name = info.get("projectName") or "Без имени"
        except Exception:
            name = "(проект недоступен — закройте диалог в Archicad)"
        out.append((p, name))
    return out


def pick_port(title: str, port: int | None = None):
    """Порт Archicad для работы; None — нет подходящего или выбор отменён."""
    if port:
        return port
    found = instances()
    if len(found) <= 1:
        return found[0][0] if found else None

    root = tk.Tk()
    root.title(title)
    root.resizable(False, False)
    frm = ttk.Frame(root, padding=12)
    frm.grid()
    ttk.Label(frm, text="Открыто несколько Archicad. С каким проектом работать?").grid(sticky="w")
    lb = tk.Listbox(frm, height=min(8, len(found)), width=60, activestyle="none")
    for p, name in found:
        lb.insert("end", f"{name}   (порт {p})")
    lb.selection_set(0)
    lb.grid(pady=8)
    chosen = {"port": None}

    def ok(*_):
        sel = lb.curselection()
        if sel:
            chosen["port"] = found[sel[0]][0]
        root.destroy()

    lb.bind("<Double-Button-1>", ok)
    lb.bind("<Return>", ok)
    ttk.Button(frm, text="Выбрать", command=ok).grid(sticky="e")
    # из менеджера окно открывалось позади Archicad — поднимаем поверх всех
    root.attributes("-topmost", True)
    root.after(300, lambda: root.attributes("-topmost", False))
    root.lift()
    root.focus_force()
    lb.focus_set()
    root.mainloop()
    return chosen["port"]
