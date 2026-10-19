"""Журнал работы плагинов и отчёт об ошибке разработчику в Telegram.

Журнал: %LOCALAPPDATA%\\ArchicadPlugins\\logs\\<плагин>.log — туда же идёт всё, что плагин печатает.
Отчёт: бот из «_setup\\update.ini», раздел [report] (bot_token, chat_id) — сообщение + файл журнала.

    python -m kd.report --test           проверить отправку
    python -m kd.report --dialog         окно «Отправить журнал» (кнопка в менеджере)
"""
from __future__ import annotations

import configparser
import getpass
import io
import json
import os
import platform
import sys
import time
import traceback
import urllib.request
import uuid

from .config import ROOT, plugins_version

LOG_DIR = os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "ArchicadPlugins", "logs")
MAX_LOG = 2_000_000                     # байт; больше — старый журнал уходит в .1
_state = {"plugin": "plugins", "log": None, "project": ""}


# ---------- журнал ----------

class _Tee(io.TextIOBase):
    """Пишет и в исходный поток (если есть — у uvw его нет), и в журнал."""

    def __init__(self, orig, f):
        self.orig, self.f = orig, f

    def write(self, s):
        try:
            self.f.write(s)
            self.f.flush()
        except Exception:
            pass
        if self.orig is not None:
            try:
                self.orig.write(s)
            except Exception:
                pass
        return len(s)

    def flush(self):
        for x in (self.orig, self.f):
            try:
                x and x.flush()
            except Exception:
                pass


def log_path(plugin: str | None = None) -> str:
    return os.path.join(LOG_DIR, f"{plugin or _state['plugin']}.log")


def start_log(plugin: str) -> str:
    """Включает журнал плагина; вызывать первым делом в main()."""
    _state["plugin"] = plugin
    path = log_path(plugin)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        if os.path.isfile(path) and os.path.getsize(path) > MAX_LOG:
            os.replace(path, path + ".1")
        f = open(path, "a", encoding="utf-8")
    except OSError:
        return path
    _state["log"] = path
    f.write(f"\n===== {time.strftime('%Y-%m-%d %H:%M:%S')}  {plugin}  v{plugins_version()}  "
            f"{platform.node()}\\{getpass.getuser()}  argv={sys.argv[1:]}\n")
    f.flush()
    sys.stdout, sys.stderr = _Tee(sys.stdout, f), _Tee(sys.stderr, f)
    return path


def set_project(name: str):
    """Имя проекта Archicad — попадает в журнал и в отчёт."""
    _state["project"] = name or ""
    print(f"Проект: {name}")


# ---------- отправка ----------

def _settings():
    cp = configparser.ConfigParser()
    try:
        cp.read(os.path.join(ROOT, "_setup", "update.ini"), encoding="utf-8-sig")
    except Exception:
        pass
    return (cp.get("report", "bot_token", fallback="").strip(),
            cp.get("report", "chat_id", fallback="").strip())


def configured() -> bool:
    return all(_settings())


def _api(token, method, fields, file=None, timeout=30):
    url = f"https://api.telegram.org/bot{token}/{method}"
    if file is None:
        data = json.dumps(fields).encode("utf-8")
        req = urllib.request.Request(url, data, {"Content-Type": "application/json"})
    else:
        b = uuid.uuid4().hex
        body = io.BytesIO()
        for k, v in fields.items():
            body.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode("utf-8"))
        name, blob = file
        body.write(f'--{b}\r\nContent-Disposition: form-data; name="document"; filename="{name}"\r\n'
                   f"Content-Type: text/plain\r\n\r\n".encode("utf-8"))
        body.write(blob)
        body.write(f"\r\n--{b}--\r\n".encode("utf-8"))
        req = urllib.request.Request(url, body.getvalue(), {"Content-Type": f"multipart/form-data; boundary={b}"})
    res = json.loads(urllib.request.urlopen(req, timeout=timeout).read().decode("utf-8"))
    if not res.get("ok"):
        raise RuntimeError(res.get("description") or "Telegram: ошибка")
    return res


def _tail(path, limit=400_000):
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            n = f.tell()
            f.seek(max(0, n - limit))
            return f.read()
    except OSError:
        return b""


def header(title: str) -> str:
    return "\n".join([
        title,
        f"Плагин: {_state['plugin']}  v{plugins_version()}",
        f"Проект: {_state['project'] or '—'}",
        f"Компьютер: {platform.node()}  пользователь: {getpass.getuser()}",
        f"Windows {platform.release()} ({platform.version()}), Python {platform.python_version()}",
        f"Время: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    ])


def send(title: str, error: str = "", comment: str = "", log: str | None = None) -> str:
    """Отправляет отчёт; → текст для пользователя. Исключение — не удалось."""
    token, chat = _settings()
    if not (token and chat):
        raise RuntimeError("Отправка не настроена: в «_setup\\update.ini» нет раздела [report].")
    text = header(title)
    if comment.strip():
        text += f"\n\nКомментарий: {comment.strip()}"
    if error.strip():
        err = error.strip()
        text += "\n\nОшибка:\n" + (err if len(err) < 2500 else "…" + err[-2500:])
    _api(token, "sendMessage", {"chat_id": chat, "text": text[:4000]})
    log = log or _state["log"] or log_path()
    blob = _tail(log)
    if blob:
        _api(token, "sendDocument", {"chat_id": chat, "caption": f"Журнал {os.path.basename(log)}"},
             (os.path.basename(log), blob), timeout=60)
    return "Отчёт отправлен разработчику."


# ---------- окна ----------

def fix_hotkeys(win):
    """Ctrl+V/C/X/A в русской раскладке: Tk их не узнаёт (keysym кириллический) — дотягиваем по коду клавиши."""
    events = {86: "<<Paste>>", 67: "<<Copy>>", 88: "<<Cut>>", 65: "<<SelectAll>>"}

    def on_key(e):
        if e.keycode in events and e.keysym.lower() not in ("v", "c", "x", "a"):
            e.widget.event_generate(events[e.keycode])
            return "break"

    win.bind_all("<Control-KeyPress>", on_key, add="+")


def report_dialog(title: str, error: str = "", parent=None, heading: str | None = None):
    """Окно «Ошибка» (или «Отправить журнал», если error пуст) с кнопкой «Отправить разработчику»."""
    import threading
    import tkinter as tk
    from tkinter import ttk

    own = parent is None
    win = tk.Tk() if own else tk.Toplevel(parent)
    win.title(title)
    win.resizable(False, False)
    if own:
        fix_hotkeys(win)
    else:
        win.transient(parent)
    frm = ttk.Frame(win, padding=12)
    frm.grid()
    ttk.Label(frm, text=heading or ("Произошла ошибка." if error else "Отправить журнал работы разработчику."),
              font=("Segoe UI", 10, "bold")).grid(sticky="w")
    if error:
        box = tk.Text(frm, width=78, height=10, wrap="word", font=("Consolas", 9))
        box.insert("1.0", error.strip())
        box.configure(state="disabled")
        box.grid(pady=(6, 6), sticky="we")
    ttk.Label(frm, text="Что делали перед этим (необязательно):").grid(sticky="w")
    note = tk.Text(frm, width=78, height=3, wrap="word")
    note.grid(pady=(2, 6), sticky="we")
    status = tk.StringVar(value=f"Журнал: {_state['log'] or log_path()}")
    ttk.Label(frm, textvariable=status, foreground="#666", wraplength=560).grid(sticky="w")
    bar = ttk.Frame(frm)
    bar.grid(sticky="e", pady=(8, 0))

    def open_log():
        p = _state["log"] or log_path()
        if os.path.isfile(p):
            os.startfile(p)

    def do_send():
        b_send.state(["disabled"])
        status.set("Отправляю…")
        comment = note.get("1.0", "end")

        def work():
            try:
                msg = send("ОШИБКА" if error else "Журнал по запросу пользователя", error, comment)
            except Exception as e:
                msg = f"Не отправилось: {e}. Перешлите файл журнала вручную."
                win.after(0, lambda: b_send.state(["!disabled"]))
            win.after(0, status.set, msg)

        threading.Thread(target=work, daemon=True).start()

    b_send = ttk.Button(bar, text="Отправить разработчику", command=do_send)
    b_send.grid(row=0, column=0, padx=(0, 6))
    if not configured():
        b_send.state(["disabled"])
        status.set("Отправка не настроена — перешлите файл журнала вручную.")
    ttk.Button(bar, text="Открыть журнал", command=open_log).grid(row=0, column=1, padx=(0, 6))
    ttk.Button(bar, text="Закрыть", command=win.destroy).grid(row=0, column=2)
    win.attributes("-topmost", True)
    win.after(300, lambda: win.attributes("-topmost", False))
    win.focus_force()
    if own:
        win.mainloop()
    else:
        win.grab_set()
        parent.wait_window(win)


def install_hooks(title: str):
    """Любая непойманная ошибка (в том числе в обработчиках окна) → журнал + окно отчёта."""
    def hook(et, ev, tb):
        text = "".join(traceback.format_exception(et, ev, tb))
        print(text, file=sys.stderr)
        try:
            report_dialog(title, text)
        except Exception:
            pass

    sys.excepthook = hook
    try:
        import tkinter as tk
        tk.Tk.report_callback_exception = lambda self, et, ev, tb: hook(et, ev, tb)
    except Exception:
        pass


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="отправить тестовое сообщение")
    ap.add_argument("--dialog", action="store_true", help="окно «Отправить журнал»")
    ap.add_argument("--plugin", default="plugins", help="чей журнал отправлять")
    a = ap.parse_args(argv)
    _state["plugin"] = a.plugin
    if a.test:
        print(send("Проверка отправки отчётов", comment="тест"))
    else:
        logs = sorted((os.path.join(LOG_DIR, f) for f in os.listdir(LOG_DIR) if f.endswith(".log")),
                      key=os.path.getmtime, reverse=True) if os.path.isdir(LOG_DIR) else []
        if logs and a.plugin == "plugins":            # последний по времени журнал
            _state["plugin"] = os.path.splitext(os.path.basename(logs[0]))[0]
        _state["log"] = log_path()
        report_dialog(f"Плагины Archicad  v{plugins_version()}")


if __name__ == "__main__":
    main()
