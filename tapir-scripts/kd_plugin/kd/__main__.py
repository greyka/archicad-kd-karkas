"""Запуск:
    python -m kd --demo                 # комплект по деталям из образца
    python -m kd --archicad             # из открытого проекта Archicad
    python -m kd --archicad --selected  # только выделенные элементы
    python -m kd --parts parts.json     # из ранее выгруженного JSON
    python -m kd --archicad --layouts   # + листы на макетах Archicad
    python -m kd --archicad --publish   # только общий PDF из готовых листов
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from .config import USER_DIR, load_config
from .marking import make_groups
from .model import Part
from .sheets import build_document


def load_parts(path):
    data = json.load(open(path, encoding="utf-8"))
    return [Part(uid=d["uid"], layer=d["layer"], b=d["b"],
                 outline=[tuple(p) for p in d["outline"]], mark=d.get("mark", ""),
                 source=d.get("source", ""), mat=d.get("mat", ""), note=d.get("note", ""))
            for d in data]


def save_parts(parts, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump([p.__dict__ for p in parts], f, ensure_ascii=False)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kd", description="КД деревянного каркаса в PDF")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--demo", action="store_true")
    src.add_argument("--archicad", action="store_true")
    src.add_argument("--parts")
    ap.add_argument("--selected", action="store_true", help="только выделенное в Archicad")
    ap.add_argument("--config", help="файл настроек (по умолчанию %%APPDATA%%/kd_plugin/config.json)")
    ap.add_argument("-o", "--output")
    ap.add_argument("--name", help="наименование объекта в штампе")
    ap.add_argument("--port", type=int, help="порт Archicad (иначе — поиск)")
    ap.add_argument("--layouts", action="store_true",
                    help="нарисовать листы на макетах Archicad (подмножество КД)")
    ap.add_argument("--publish", action="store_true",
                    help="выпустить общий PDF набором публикации Archicad")
    ap.add_argument("--write-marks", action="store_true",
                    help="записать марки в ID элементов Archicad")
    a = ap.parse_args(argv)

    cfg = load_config(a.config)
    if a.name:
        cfg["project_name"] = a.name
    if a.port:
        cfg.setdefault("archicad", {})["port"] = a.port
    out = os.path.abspath(a.output or cfg.get("output") or "КД.pdf")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    # Только общий PDF из уже готовых листов Archicad — модель не трогаем
    if a.archicad and a.publish and not a.layouts:
        from .ac_layouts import publish_pdf
        out = publish_pdf(cfg, out)
        print(f"Общий PDF (публикация Archicad): {out}")
        return out

    if a.demo:
        from .demo import demo_parts
        parts = demo_parts()
    elif a.parts:
        parts = load_parts(a.parts)
    else:
        from .archicad import collect_parts
        parts, skipped = collect_parts(cfg.get("archicad", {}), selected_only=a.selected)
        os.makedirs(USER_DIR, exist_ok=True)
        save_parts(parts, os.path.join(USER_DIR, "last_parts.json"))
        if skipped:
            sk = os.path.join(USER_DIR, "last_skipped.json")
            print(f"Пропущено элементов без геометрии: {len(skipped)} (см. {sk})", file=sys.stderr)
            json.dump(skipped, open(sk, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    if not parts:
        sys.exit("Нет деталей для чертежей.")

    groups = make_groups(parts, cfg.get("layer_prefixes"), cfg.get("layer_order"))
    doc = build_document(groups, cfg)
    doc.save(out, garbage=3, deflate=True)
    print(f"Готово: {out}  листов: {doc.page_count}, марок: {len(groups)}, деталей: {len(parts)}")

    if a.layouts:
        from .ac_layouts import publish_layouts
        r = publish_layouts(groups, cfg)
        print(f"Макеты в Archicad: {r['layouts']} листов, {r['elements']} элементов, «{r['subset']}»")
    if a.publish:
        from .ac_layouts import publish_pdf
        out = publish_pdf(cfg, out)
        print(f"Общий PDF (публикация Archicad): {out}")

    if a.write_marks and a.archicad:
        from .archicad import write_marks
        n = write_marks(cfg.get("archicad", {}), groups)
        print(f"Марки записаны в ID: {n} элементов")
    return out


if __name__ == "__main__":
    main()
