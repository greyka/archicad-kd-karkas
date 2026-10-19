"""Площадь всех поверхностей элементов открытого проекта Archicad.

Запуск:
    python -m kd.surfaces                       # все элементы проекта
    python -m kd.surfaces --selected            # только выделенные (Tapir)
    python -m kd.surfaces --layer лестниц --min-width 100 --t 40

Способ расчёта по элементу:
  1. Доска ArchiFramePlank с загруженной библиотекой — по GDL-параметрам:
     боковой контур с запилами (plank_geometry) и толщина:
     S = 2·площадь контура + периметр·толщина.
  2. Доска/объект без 3D (библиотека не загружена) — брусок W × L × t,
     W = General_Width, L = длина объекта, t — толщина из окна/--t.
  3. Остальное (перекрытия, стены, балки, морфы…) — встроенные свойства
     Archicad: верх + низ + кромки, иначе General_SurfaceArea.
"""
from __future__ import annotations

import argparse
import csv
import html
import math
import os
from datetime import date

from .archicad import ArchicadError, Client, plank_geometry
from .config import load_config

PROPS = ["General_ElementID", "General_LibraryPartName", "ModelView_LayerName",
         "General_Width", "General_Height", "ObjectLamp_Length",
         "General_GrossTopSurfaceArea", "General_GrossBottomSurfaceArea",
         "General_GrossEdgeSurfaceArea", "General_SurfaceArea"]


def _num(v):
    return float(v) if isinstance(v, (int, float)) else 0.0


def _poly(outline):
    """Площадь и периметр контура (мм², мм)."""
    a = sum(outline[i - 1][0] * p[1] - p[0] * outline[i - 1][1] for i, p in enumerate(outline))
    per = sum(math.dist(outline[i - 1], p) for i, p in enumerate(outline))
    return abs(a) / 2, per


def _gdl(c: Client, elements):
    """GDL-параметры по элементам; None там, где библиотека не загружена."""
    try:
        res = c.tapir("GetGDLParametersOfElements", {"elements": elements})
    except ArchicadError:
        return [None] * len(elements)
    out = []
    for g in res.get("gdlParametersOfElements", []):
        out.append(None if "error" in g else {x["name"]: x.get("value") for x in g["parameters"]})
    return out + [None] * (len(elements) - len(out))


def collect(selected=False, layer="", min_width_mm=0.0, t_mm=None, port=None, libparts=None):
    """Строки по элементам: площадь всех поверхностей, пласть, способ."""
    c = Client(port)
    if selected:
        els = c.tapir("GetSelectedElements").get("elements", [])
        if not els:
            raise ArchicadError("Ничего не выделено — выделите элементы в Archicad.")
    else:
        els = c.call("API.GetAllElements")["elements"]
    types = c.call("API.GetTypesOfElements", {"elements": els})["typesOfElements"]
    props = c.property_values(els, PROPS)

    picked = []
    for e, ty, pr in zip(els, types, props):
        lay = pr.get("ModelView_LayerName") or ""
        if layer and layer.lower() not in lay.lower():
            continue
        if min_width_mm and _num(pr.get("General_Width")) * 1000 < min_width_mm - 0.01:
            continue
        picked.append((e, ty.get("typeOfElement", {}).get("elementType", "?"), pr))
    if not picked:
        raise ArchicadError("Нет элементов под условия (слой / ширина / выделение).")

    libparts = set(libparts or ["ArchiFramePlank"])
    planks = [i for i, (_, ty, pr) in enumerate(picked)
              if ty == "Object" and pr.get("General_LibraryPartName") in libparts]
    gdl = dict(zip(planks, _gdl(c, [picked[i][0] for i in planks]))) if planks else {}

    rows = []
    for i, (e, ty, pr) in enumerate(picked):
        r = {"guid": e["elementId"]["guid"], "type": ty, "id": pr.get("General_ElementID") or "",
             "layer": pr.get("ModelView_LayerName") or "", "libpart": pr.get("General_LibraryPartName") or "",
             "size": "", "area": None, "face": None, "method": ""}
        g = gdl.get(i)
        if g:
            try:
                outline, thick, _ = plank_geometry(g)
                a, per = _poly(outline)
                xs = [p[0] for p in outline]
                ys = [p[1] for p in outline]
                L, h = max(xs) - min(xs), max(ys) - min(ys)
                r.update(area=(2 * a + per * thick) / 1e6, face=max(a, L * thick) / 1e6,
                         size=f"{L:.0f}×{h:.0f}×{thick:.0f}", method="ArchiFrame: контур × толщина")
                rows.append(r)
                continue
            except (KeyError, TypeError, ValueError):
                pass
        top, bot, edge = (_num(pr.get(k)) for k in ("General_GrossTopSurfaceArea",
                                                    "General_GrossBottomSurfaceArea",
                                                    "General_GrossEdgeSurfaceArea"))
        if top + bot + edge > 0:
            r.update(area=top + bot + edge, face=max(top, bot), method="свойства: верх+низ+кромки")
        elif _num(pr.get("General_SurfaceArea")) > 0:
            r.update(area=_num(pr.get("General_SurfaceArea")), method="свойства: площадь поверхности")
        elif ty == "Object":
            w = _num(pr.get("General_Width"))
            L = _num(pr.get("ObjectLamp_Length")) or _num(pr.get("General_Height"))
            if w and L:
                r["face"] = w * L
                if t_mm:
                    t = t_mm / 1000
                    r.update(area=2 * (w * L + w * t + L * t), size=f"{L*1000:.0f}×{w*1000:.0f}×{t_mm:.0f}",
                             method=f"брусок W×L×t (t={t_mm:g} мм из окна)")
                else:
                    r.update(size=f"{L*1000:.0f}×{w*1000:.0f}", method="нет толщины — только пласть")
            else:
                r["method"] = "нет данных"
        else:
            r["method"] = "нет данных"
        rows.append(r)
    return rows


def group_rows(rows):
    groups = {}
    for r in rows:
        k = (r["layer"], r["libpart"] or r["type"], r["size"], r["method"])
        g = groups.setdefault(k, {"layer": k[0], "name": k[1], "size": k[2], "method": k[3],
                                  "count": 0, "area": [], "face": []})
        g["count"] += 1
        if r["area"] is not None:
            g["area"].append(r["area"])
        if r["face"] is not None:
            g["face"].append(r["face"])
    out = []
    for g in groups.values():
        g["one"] = g["area"][0] if g["area"] else None
        g["area"] = math.fsum(g["area"]) if g["area"] else None
        g["face"] = math.fsum(g["face"]) if g["face"] else None
        out.append(g)
    return sorted(out, key=lambda g: (g["layer"], g["name"], g["size"]))


def _f(x, n=3):
    return "—" if x is None else f"{x:,.{n}f}".replace(",", " ").replace(".", ",")


def write_report(rows, out_html, project="", note=""):
    """HTML-отчёт + CSV рядом (тот же путь, .csv). Возвращает путь HTML."""
    groups = group_rows(rows)
    total = math.fsum(r["area"] for r in rows if r["area"] is not None)
    face = math.fsum(r["face"] for r in rows if r["face"] is not None)
    missing = sum(1 for r in rows if r["area"] is None)
    e = html.escape
    grows = "".join(
        f"<tr><td>{e(g['layer'])}</td><td>{e(g['name'])}</td><td class=n>{e(g['size'])}</td>"
        f"<td class=n>{g['count']}</td><td class=n>{_f(g['one'], 4)}</td><td class=n>{_f(g['face'])}</td>"
        f"<td class=n><b>{_f(g['area'])}</b></td><td class=m>{e(g['method'])}</td></tr>" for g in groups)
    warn = (f"<p class=warn>Без площади: {missing} эл. — не хватает данных (см. «Способ»). "
            f"Для досок без библиотеки укажите толщину.</p>") if missing else ""
    page = f"""<!doctype html><html lang=ru><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1"><title>Площади поверхностей</title><style>
:root{{--bg:#f7f7f5;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e3e2dd;--acc:#2f6f4f;--warn:#fff4d6}}
@media (prefers-color-scheme:dark){{:root{{--bg:#161615;--fg:#ecebe6;--mut:#9a9992;--card:#1f1f1d;--line:#33332f;--acc:#7cc4a0;--warn:#3a3218}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,Segoe UI,sans-serif}}
main{{max-width:1100px;margin:auto;padding:24px 16px 60px}}h1{{font-size:24px;margin:0 0 4px}}.mut{{color:var(--mut)}}
.kpi{{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px;margin:20px 0}}
.kpi div{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}}
.kpi b{{display:block;font-size:26px;color:var(--acc)}}.scroll{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;background:var(--card);font-size:14px}}
th,td{{border-bottom:1px solid var(--line);padding:6px 10px;text-align:left;white-space:nowrap}}
th{{color:var(--mut);font-weight:600}}td.n{{text-align:right;font-variant-numeric:tabular-nums}}td.m{{color:var(--mut)}}
.warn{{background:var(--warn);padding:8px 12px;border-radius:8px}}
</style></head><body><main><h1>Площади поверхностей</h1>
<div class=mut>{e(project)} · {date.today():%d.%m.%Y}{(' · ' + e(note)) if note else ''}</div>
<div class=kpi><div>Все поверхности<b>{_f(total, 2)} м²</b></div><div>Пласть (наибольшая грань)<b>{_f(face, 2)} м²</b></div>
<div>Элементов<b>{len(rows)}</b></div></div>{warn}
<div class=scroll><table><thead><tr><th>Слой</th><th>Элемент</th><th>Размер, мм</th><th>Кол-во</th><th>1 шт, м²</th>
<th>Пласть, м²</th><th>Все пов-ти, м²</th><th>Способ</th></tr></thead><tbody>{grows}
<tr><td><b>Итого</b></td><td></td><td></td><td class=n><b>{len(rows)}</b></td><td></td><td class=n><b>{_f(face)}</b></td>
<td class=n><b>{_f(total)}</b></td><td></td></tr></tbody></table></div>
<p class=mut>Все поверхности доски = 2·площадь бокового контура + периметр·толщина (запилы учтены).
Пласть — наибольшая грань (у ступени — проступь). Подробно по элементам — CSV рядом.</p></main></body></html>"""
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(page)
    with open(os.path.splitext(out_html)[0] + ".csv", "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["Слой", "Тип", "Библ. элемент", "ID", "Размер, мм", "Пласть, м²", "Все пов-ти, м²", "Способ", "GUID"])
        for r in sorted(rows, key=lambda r: (r["layer"], r["libpart"], r["size"])):
            w.writerow([r["layer"], r["type"], r["libpart"], r["id"], r["size"],
                        _f(r["face"], 4), _f(r["area"], 4), r["method"], r["guid"]])
    return out_html, total, face, missing


def main(argv=None):
    ap = argparse.ArgumentParser(prog="kd.surfaces", description="Площадь всех поверхностей элементов")
    ap.add_argument("--selected", action="store_true")
    ap.add_argument("--layer", default="", help="подстрока имени слоя")
    ap.add_argument("--min-width", type=float, default=0, help="мм; отсечь узкие (косоуры, стойки)")
    ap.add_argument("--t", type=float, help="толщина досок без библиотеки, мм")
    ap.add_argument("--port", type=int)
    ap.add_argument("-o", "--output", default="Площади поверхностей.html")
    a = ap.parse_args(argv)
    cfg = load_config().get("archicad", {})
    rows = collect(a.selected, a.layer, a.min_width, a.t, a.port or cfg.get("port"),
                   cfg.get("object_libparts"))
    path, total, face, missing = write_report(rows, os.path.abspath(a.output))
    print(f"Готово: {path}\nЭлементов {len(rows)}, все поверхности {total:.3f} м², пласть {face:.3f} м²"
          + (f", без площади {missing}" if missing else ""))
    return path


if __name__ == "__main__":
    main()
