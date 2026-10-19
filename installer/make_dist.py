"""Собирает папку-установщик KD_karkas_setup (без архива):

    python installer/make_dist.py [куда]

    KD_karkas_setup/
        Установить.bat, Удалить.bat, README.md
        setup/install.ps1
        tapir-scripts/   — копия плагина: прогрев окружения при установке
                           (сам плагин палитра Tapir берёт с GitHub)
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
dst = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(ROOT), "dist", "KD_karkas_setup")

shutil.rmtree(dst, ignore_errors=True)
shutil.copytree(os.path.join(ROOT, "tapir-scripts"), os.path.join(dst, "tapir-scripts"),
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
os.makedirs(os.path.join(dst, "setup"))
# PowerShell 5.1 читает .ps1 без BOM как ANSI — сохраняем с BOM
src = open(os.path.join(HERE, "install.ps1"), encoding="utf-8-sig").read()
open(os.path.join(dst, "setup", "install.ps1"), "w", encoding="utf-8-sig").write(src)
shutil.copy2(os.path.join(HERE, "install.bat"), os.path.join(dst, "Установить.bat"))
shutil.copy2(os.path.join(HERE, "uninstall.bat"), os.path.join(dst, "Удалить.bat"))
shutil.copy2(os.path.join(ROOT, "README.md"), dst)

n = sum(len(fs) for _, _, fs in os.walk(dst))
print(f"{dst}  ({n} файлов)")
