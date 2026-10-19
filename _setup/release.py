# -*- coding: utf-8 -*-
"""Выпуск новой версии плагинов Archicad (для разработчика, нужен git и gh).

    python _setup/release.py 1.2.0

1. Проверяет, что в CHANGELOG.md есть раздел «## 1.2.0» (опишите изменения заранее).
2. Пишет 1.2.0 в VERSION и kd/__init__.py, коммитит ОТСЛЕЖИВАЕМЫЕ файлы
   (новые файлы сначала добавьте сами: git add <файл>), ставит тег v1.2.0, push.
3. Создаёт релиз GitHub v1.2.0 с текстом из CHANGELOG — компьютеры получат его
   при следующем входе в Windows (или кнопкой «Обновить» в менеджере).
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def sh(*args, check=True):
    print("»", " ".join(args))
    r = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if r.stdout.strip():
        print(r.stdout.strip())
    if check and r.returncode:
        sys.exit(r.stderr.strip() or f"ошибка: {' '.join(args)}")
    return r


def changelog_section(ver):
    text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()
    m = re.search(rf"^## {re.escape(ver)}\b.*?$\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return m.group(1).strip() if m else None


def main():
    if len(sys.argv) != 2 or not re.fullmatch(r"\d+\.\d+\.\d+", sys.argv[1]):
        sys.exit("использование: python _setup/release.py X.Y.Z")
    ver = sys.argv[1]
    notes = changelog_section(ver)
    if not notes:
        sys.exit(f"В CHANGELOG.md нет раздела «## {ver} — дата» с описанием изменений.")
    if sh("git", "tag", "-l", f"v{ver}").stdout.strip():
        sys.exit(f"Тег v{ver} уже есть — увеличьте номер версии.")
    with open(os.path.join(ROOT, "VERSION"), "w", encoding="utf-8", newline="\n") as f:
        f.write(ver + "\n")
    init = os.path.join(ROOT, "tapir-scripts", "kd_plugin", "kd", "__init__.py")
    txt = open(init, encoding="utf-8").read()
    with open(init, "w", encoding="utf-8", newline="\n") as f:
        f.write(re.sub(r'__version__\s*=\s*"[^"]*"', f'__version__ = "{ver}"', txt))
    sh("git", "add", "-u")              # только отслеживаемые — черновики не попадут в релиз
    sh("git", "add", "VERSION")
    if sh("git", "diff", "--cached", "--quiet", check=False).returncode:
        sh("git", "commit", "-m", f"Версия {ver}\n\n{notes}\n\n"
                                  "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
    sh("git", "tag", "-a", f"v{ver}", "-m", f"Версия {ver}")
    sh("git", "push", "origin", "HEAD", f"v{ver}")
    sh("gh", "release", "create", f"v{ver}", "--title", f"Версия {ver}", "--notes", notes, "--latest")
    print(f"\nГотово: версия {ver} выпущена.")


if __name__ == "__main__":
    main()
