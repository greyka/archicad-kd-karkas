"""Сборка комплекта листов: ведомость чертежей, СП-1, листы деталей."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

import pymupdf

from .model import Group, fmt_mm
from .pdfdoc import A3L, A4P, BLACK, FILL, GREY, MAIN, Canvas, draw_iso, fmt_angle

SCALES = [1, 2, 2.5, 4, 5, 10, 15, 20, 25, 40, 50, 75, 100]


@dataclass
class Sheet:
    title: str
    size: tuple[float, float]
    draw: Callable[[Canvas], None]


# =================================================================== деталь

def _end_zone(L, H):
    return min(max(H * 2.5, 80), L / 3)


def part_box(g: Group, s: float):
    """Поля вокруг контура (мм листа), нужные под размеры: l, t, r, b."""
    return 14, 13, 16, 19 + (5 if g.note else 0)


def draw_part(cv: Canvas, g: Group, ox: float, oy: float, s: float):
    """Деталь в масштабе s (мм листа на мм детали); (ox, oy) — левый
    нижний угол контура на листе."""
    pts = g.outline
    L, H = g.length, g.h

    def P(x, y):
        return ox + x * s, oy - y * s

    cv.poly([P(x, y) for x, y in pts], w=MAIN, fill=FILL)

    # марка по центру
    hp = H * s
    size = max(6.0, min(12.0, hp * 0.55 * 2.83))
    cx = ox + L * s / 2
    if hp >= 4:
        cv.text(cx, oy - hp / 2, g.mark, size, key="bold", color=GREY)
    else:                                   # тонкая деталь — марка над ней
        cv.text(cx, oy - hp - 3, g.mark, 7, key="bold", color=GREY)

    def low_y(x):      # самая нижняя вершина с данным x
        return min(y for px, y in pts if px == x)

    def high_y(x):
        return max(y for px, y in pts if px == x)

    # --- низ: цепочка + габарит
    bottom = sorted({x for x, y in pts if y == 0} | {0, L})
    level = oy + 7
    if len(bottom) > 2:
        for a, b in zip(bottom, bottom[1:]):
            cv.dim_h(*P(a, low_y(a)), *P(b, low_y(b)), level, fmt_mm(b - a))
        level += 7
    cv.dim_h(*P(0, low_y(0)), *P(L, low_y(L)), level, fmt_mm(L))
    if g.note:
        cv.text(ox, level + 5, g.note, 7.5, anchor="l", key="arial", color=GREY)

    # --- верх: цепочка, если отличается от нижней
    top = sorted({x for x, y in pts if y == H} | {0, L})
    if len(top) > 2 and top != bottom:
        yl = oy - hp - 7
        for a, b in zip(top, top[1:]):
            cv.dim_h(*P(a, high_y(a)), *P(b, high_y(b)), yl, fmt_mm(b - a))

    # --- торцы: вертикальные цепочки
    ez = _end_zone(L, H)
    left = sorted({y for x, y in pts if x <= ez} | {0, H})
    right = sorted({y for x, y in pts if x >= L - ez} | {0, H})

    def x_at(ys_side, y, side):
        xs = [x for x, py in pts if py == y and ((x <= ez) if side < 0 else (x >= L - ez))]
        if not xs:
            return 0 if side < 0 else L
        return min(xs) if side < 0 else max(xs)

    xl = ox - 7
    if len(left) > 2:
        for a, b in zip(left, left[1:]):
            cv.dim_v(*P(x_at(left, a, -1), a), *P(x_at(left, b, -1), b), xl, fmt_mm(b - a))
    else:
        cv.dim_v(*P(x_at(left, 0, -1), 0), *P(x_at(left, H, -1), H), xl, fmt_mm(H))
    if len(right) > 2:
        xr = ox + L * s + 9
        for a, b in zip(right, right[1:]):
            cv.dim_v(*P(x_at(right, a, 1), a), *P(x_at(right, b, 1), b), xr, fmt_mm(b - a))

    # --- внутренние вырезы (паз F-1.1): глубина от ближайшей грани
    seen = set()
    for x, y in pts:
        if ez < x < L - ez and 0 < y < H and y not in seen:
            seen.add(y)
            edge = H if H - y < y else 0
            px, _ = P(x, 0)
            cv.dim_v(px, oy - y * s, px, oy - edge * s, px - 3, fmt_mm(abs(edge - y)))

    # --- углы наклонных кромок
    n = len(pts)
    done = set()
    for i in range(n):
        (x1, y1), (x2, y2) = pts[i], pts[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        if dx == 0 or dy == 0:
            continue
        ang = math.degrees(math.atan2(abs(dy), abs(dx)))
        if ang < 1 or ang > 89:
            continue
        if math.hypot(dx, dy) * s < 2.5:      # слишком короткая кромка — угол не читается
            continue
        # вершина — на нижней/верхней грани, если есть
        if y1 in (0, H):
            vx, vy, ex, ey = x1, y1, x2, y2
        else:
            vx, vy, ex, ey = x2, y2, x1, y1
        key = (round(vx), round(vy))
        if key in done:
            continue
        done.add(key)
        X, Y = P(vx, vy)
        EX, EY = P(ex, ey)
        a_edge = math.atan2(EY - Y, EX - X)
        # опорная горизонталь — наружу от детали
        a_ref = 0.0 if ex < vx else math.pi
        r = 6.0
        cv.dim_angle(X, Y, a_ref, a_edge, r, fmt_angle(ang))


# =================================================================== раскладка

def pick_scale(groups: list[Group], width: float) -> float:
    longest = max(g.length for g in groups)
    for n in SCALES:
        if longest / n + 32 <= width:
            return n
    return SCALES[-1]


def layout(groups: list[Group], area, blocked, s):
    """Укладка деталей рядами. area = (x0, y0, x1, y1);
    blocked — прямоугольники, которые нельзя занимать (штамп, таблица).
    Возвращает список страниц: [(group, ox, oy)]."""
    x0, y0, x1, y1 = area
    def size(g):
        l, t, r, b = part_box(g, s)
        return l, t, l + g.length * s + r, t + g.h * s + b

    def limit_at(y, h):
        lim = x1
        for (bx0, by0, bx1, by1) in blocked:
            if y < by1 and y + h > by0:
                lim = min(lim, bx0 - 2)
        return lim

    pending = sorted(groups, key=lambda g: -g.length)
    pages, cur, y = [], [], y0
    while pending:
        # ряд по принципу first-fit: берём любые детали, что помещаются
        row, rx, rh = [], x0, 0.0
        for g in list(pending):
            l, t, bw, bh = size(g)
            h_try = max(rh, bh)
            if y + h_try > y1:
                continue
            if rx + bw <= limit_at(y, h_try):
                row.append((g, rx + l, y + t + g.h * s))
                rx += bw
                rh = h_try
                pending.remove(g)
        if row:
            cur.extend(row)
            y += rh
            continue
        if y + 5 < y1 and cur or (not cur and y + 5 < y1 and y < y0 + 200):
            y += 5                       # ниже зона может быть свободнее
            continue
        if cur:
            pages.append(cur)
            cur, y = [], y0
        else:                            # не влезает даже на пустой лист
            g = pending.pop(0)
            l, t, _, _ = size(g)
            pages.append([(g, x0 + l, y0 + t + g.h * s)])
            y = y0
    if cur:
        pages.append(cur)
    return pages


# =================================================================== листы

LIST_ROWS = 36          # строк ведомости на A4 (над штампом)


def sheet_list(entries: list[tuple[int, str]]):
    def draw(cv: Canvas):
        x0, y0 = 25, 10
        cols = [15, 140, 25]
        rows = [["Лист", "Наименование", "Примечание"]]
        rows += [[str(n), t, ""] for n, t in entries]
        cv.table(x0, y0, cols, rows, [10] + [6.5] * len(entries),
                 anchors=["c", "l", "c"])
    return draw


def list_pages(n_sheets: int) -> int:
    """Сколько листов займёт ведомость, если в комплекте n_sheets других листов."""
    k = 1
    while (n_sheets + k + LIST_ROWS - 1) // LIST_ROWS > k:
        k += 1
    return k


def list_sheets(entries: list[tuple[str, str]]) -> list[Sheet]:
    chunks = [entries[i:i + LIST_ROWS] for i in range(0, len(entries), LIST_ROWS)] or [[]]
    n = len(chunks)
    return [Sheet("Ведомость чертежей" + (f" (лист {i + 1})" if n > 1 else ""), A4P, sheet_list(ch))
            for i, ch in enumerate(chunks)]


def spec_sheet(groups: list[Group], title="СП-1 Общая спецификация"):
    """Общая спецификация: две таблицы рядом, как л.3 образца."""
    cols = [17, 50, 25, 22, 18, 58]
    head = ["№", "Слой", "Mat name", "Length", "Кол-во", "Внешний вид"]
    rh, top = 11.0, 10.0
    cap_left = int((287 - top - 8 - 12) // rh)
    cap_right = int((262 - 3 - top - 8 - 12) // rh)

    def row(g):
        def iso(cv, x, y, w, h, g=g):
            draw_iso(cv, g.outline, g.b, x + 1, y + 1.5, w - 2, h - 3)
        return [g.mark, g.layer, g.section, fmt_mm(g.length), str(g.count), iso]

    chunks, rest = [], list(groups)
    while rest:
        chunks.append((rest[:cap_left], rest[cap_left:cap_left + cap_right]))
        rest = rest[cap_left + cap_right:]

    def make(left, right):
        def draw(cv: Canvas):
            for x, items in ((25, left), (220, right)):
                if not items:
                    continue
                rows = [title, head] + [row(g) for g in items]
                cv.table(x, top, cols, rows, [8, 12] + [rh] * len(items),
                         anchors=["l", "l", "c", "c", "c", "c"])
        return draw
    return [make(l, r) for l, r in chunks]


def detail_sheets(name: str, groups: list[Group], prefixes_title: dict[str, str]):
    """Листы деталей группы слоёв: мини-спецификации справа сверху +
    детали с размерами в общем масштабе."""
    W, H = A3L
    area = (25, 10, W - 8, H - 8)
    stamp = (W - 5 - 120, H - 5 - 30, W - 5, H - 5)

    # мини-спецификации по слоям
    tcols = [18, 24, 22, 16]
    tw = sum(tcols)
    tables, ty = [], 10.0
    by_layer: dict[str, list[Group]] = {}
    for g in groups:
        by_layer.setdefault(g.layer, []).append(g)
    for layer, items in by_layer.items():
        rows = [f"Спецификация: {layer}", ["№", "Сечение", "Длина", "Кол-во"]]
        rows += [[g.mark, g.section, fmt_mm(g.length), str(g.count)] for g in items]
        hts = [6, 5] + [5] * len(items)
        tables.append((ty, rows, hts))
        ty += sum(hts) + 3
    tbl_rect = (W - 8 - tw, 10, W - 8, ty)

    s_den = pick_scale(groups, area[2] - area[0])
    s = 1 / s_den
    pages = layout(groups, (area[0], area[1] + 6, area[2], area[3]), [stamp, tbl_rect], s)

    out = []
    for pi, placed in enumerate(pages):
        def draw(cv: Canvas, placed=placed, first=(pi == 0)):
            cv.text(27, 13, f"М 1:{s_den:g}", 9, anchor="l", key="arial")
            if first:
                for y, rows, hts in tables:
                    cv.table(tbl_rect[0], y, tcols, rows, hts, sizes={"title": 8, "cell": 8})
            for g, ox, oy in placed:
                draw_part(cv, g, ox, oy, s)
        suffix = f" (лист {pi + 1})" if len(pages) > 1 else ""
        out.append(Sheet(f"{name} - детали{suffix}", A3L, draw))
    return out


# =================================================================== документ

def plan_sheets(groups: list[Group], cfg: dict) -> list[Sheet]:
    """Листы комплекта без ведомости: СП-1 и листы деталей по группам слоёв."""
    sheet_groups: dict[str, list[str]] = dict(cfg.get("detail_sheet_groups", {}))
    taken = {l for ls in sheet_groups.values() for l in ls}
    order: list[tuple[str, list[str]]] = []
    seen = set()
    for g in groups:
        if g.layer in seen:
            continue
        seen.add(g.layer)
        if g.layer in taken:
            name = next(n for n, ls in sheet_groups.items() if g.layer in ls)
            if name not in [o[0] for o in order]:
                order.append((name, sheet_groups[name]))
        else:
            order.append((g.layer, [g.layer]))

    sheets: list[Sheet] = []
    for draw in spec_sheet(groups):
        sheets.append(Sheet("Общая спецификация", A3L, draw))
    for name, layers in order:
        gs = [g for g in groups if g.layer in layers]
        sheets += detail_sheets(name, gs, {})
    return sheets


def build_document(groups: list[Group], cfg: dict) -> pymupdf.Document:
    project = cfg.get("project_name", "")
    company = cfg.get("company", "")
    stage = cfg.get("stage", "КД")
    sheets = plan_sheets(groups, cfg)

    # ведомость — первыми листами; номера после неё
    k = list_pages(len(sheets))
    titles = ["Ведомость чертежей" + (f" (лист {i + 1})" if k > 1 else "") for i in range(k)]
    titles += [sh.title for sh in sheets]
    total = len(titles)
    sheets = list_sheets([(i + 1, t) for i, t in enumerate(titles)]) + sheets

    doc = pymupdf.open()
    for no, sh in enumerate(sheets, 1):
        cv = Canvas(doc, sh.size)
        sh.draw(cv)
        cv.frame(project, sh.title, stage, no, total, company)
        cv.commit()
    return doc
