# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# -*- coding: utf-8 -*-
"""Отчёты об ошибках плагинов Archicad (Telegram) — то же, что _setup\\report.py у плагинов КОМПАС.

    uv run --script _setup/send_report.py --test                       проверить отправку
    uv run --script _setup/send_report.py --send --plugin X [--error-file F] [--comment-file C] [--title T]
    uv run --script _setup/send_report.py --log-path --plugin X        путь к журналу (менеджер)
    uv run --script _setup/send_report.py --inbox <папка>              забрать отчёты Archicad (разработчику)

Окно «Произошла ошибка» / «Сообщить о проблеме» — в менеджере (--report); логика — kd/report.py.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tapir-scripts", "kd_plugin"))

from kd.report import main  # noqa: E402

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Не отправилось: {e}")
        sys.exit(1)
