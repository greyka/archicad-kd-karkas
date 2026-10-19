# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
# -*- coding: utf-8 -*-
"""Окно «Сообщить о проблеме» — журнал плагина + комментарий разработчику (Telegram).

    uv run --script _setup/send_report.py [--plugin KD_Karkas_PDF] [--test]

Запускается кнопкой «Сообщить о проблеме…» в менеджере; сама логика — kd/report.py.
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tapir-scripts", "kd_plugin"))

from kd.report import main  # noqa: E402

if __name__ == "__main__":
    main()
