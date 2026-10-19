"""Примитивы листа в миллиметрах поверх pymupdf: линии, текст, размеры,
таблицы, рамка и основная надпись в стиле образца «КД Навес»."""
from __future__ import annotations

import math
import os

import pymupdf

PT = 72 / 25.4                       # pt в 1 мм
A3L = (420, 297)
A4P = (210, 297)

FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
FONTS = {
    "gost": ["GOST_B.TTF", "GOST_BU.ttf", "GOST_A.TTF", "arial.ttf"],
    "bold": ["arialbd.ttf", "arial.ttf"],
    "arial": ["arial.ttf"],
}

# Толщины линий по ГОСТ 2.303: основная S = 0,5 мм, тонкая S/3 ≈ 0,18 мм
THIN = 0.18 * PT
MAIN = 0.5 * PT
FRAME = 0.7 * PT
FILL = (0.808, 0.796, 0.729)        # бежевая заливка деталей из образца
FILL_SIDE = (0.70, 0.69, 0.62)
FILL_DARK = (0.60, 0.59, 0.53)
BLACK = (0, 0, 0)
GREY = (0.3, 0.3, 0.3)


def _font_path(key: str) -> str:
    for name in FONTS[key]:
        p = os.path.join(FONT_DIR, name)
        if os.path.exists(p):
            return p
    raise FileNotFoundError(f"Не найден шрифт для '{key}': {FONTS[key]}")


_font_cache: dict[str, pymupdf.Font] = {}


def font(key: str) -> pymupdf.Font:
    if key not in _font_cache:
        _font_cache[key] = pymupdf.Font(fontfile=_font_path(key))
    return _font_cache[key]


GOST_HEIGHTS = (2.5, 3.5, 5, 7, 10, 14)   # ГОСТ 2.304, мм
CAP = 0.72                                  # высота прописной / кегль


def gost_mm(size_pt: float) -> float:
    """Ближайшая высота шрифта из ряда ГОСТ 2.304 (не меньше 2,5 мм)."""
    h = size_pt / PT * CAP
    return min(GOST_HEIGHTS, key=lambda g: abs(g - h))


def gost_pt(size_pt: float) -> float:
    return gost_mm(size_pt) / CAP * PT


def fmt_angle(a: float) -> str:
    if abs(a - round(a)) < 0.05:
        return f"{round(a)}°"
    return f"{a:.2f}".rstrip("0").rstrip(".").replace(".", ",") + "°"


class Canvas:
    """Лист: координаты в мм от левого верхнего угла, Y вниз."""

    def __init__(self, doc: pymupdf.Document, size_mm: tuple[float, float]):
        self.w, self.h = size_mm
        self.page = doc.new_page(width=self.w * PT, height=self.h * PT)
        for key in FONTS:
            self.page.insert_font(fontname=key, fontfile=_font_path(key))
        self.s = self.page.new_shape()

    # ------------------------------------------------------------ базовое
    @staticmethod
    def P(x, y):
        return pymupdf.Point(x * PT, y * PT)

    def line(self, x1, y1, x2, y2, w=THIN, color=BLACK):
        self.s.draw_line(self.P(x1, y1), self.P(x2, y2))
        self.s.finish(width=w, color=color)

    def rect(self, x0, y0, x1, y1, w=THIN, color=BLACK, fill=None):
        self.s.draw_rect(pymupdf.Rect(x0 * PT, y0 * PT, x1 * PT, y1 * PT))
        self.s.finish(width=w, color=color, fill=fill)

    def poly(self, pts, w=THIN, color=BLACK, fill=None, closed=True):
        self.s.draw_polyline([self.P(x, y) for x, y in pts])
        self.s.finish(width=w, color=color, fill=fill, closePath=closed)

    def text(self, x, y, txt, size=9.0, anchor="c", key="gost", rotate=0, color=BLACK):
        """size — кегль в pt; (x, y) — точка привязки, текст центрируется
        по высоте; anchor: l / c / r по горизонтали (по длине строки)."""
        txt = str(txt)
        size = gost_pt(size)
        f = font(key)
        wmm = f.text_length(txt, fontsize=size) / PT
        cap = size * CAP / PT
        shift = {"l": 0.0, "c": wmm / 2, "r": wmm}[anchor]
        if rotate == 0:
            px, py = x - shift, y + cap / 2
        else:                                   # 90: снизу вверх
            px, py = x + cap / 2, y + shift
        self.s.insert_text(self.P(px, py), txt, fontname=key, fontsize=size,
                           rotate=rotate, color=color)
        return wmm

    def text_len(self, txt, size=9.0, key="gost") -> float:
        return font(key).text_length(str(txt), fontsize=gost_pt(size)) / PT

    def commit(self):
        self.s.commit()

    # ------------------------------------------------------------ размеры
    ARROW_L, ARROW_W = 2.2, 0.75
    DIM_SIZE = 9.0

    def arrow(self, x, y, ux, uy):
        """Залитая стрелка с остриём в (x, y), направленная по (ux, uy)."""
        n = math.hypot(ux, uy) or 1
        ux, uy = ux / n, uy / n
        bx, by = x - ux * self.ARROW_L, y - uy * self.ARROW_L
        nx, ny = -uy * self.ARROW_W / 2, ux * self.ARROW_W / 2
        self.poly([(x, y), (bx + nx, by + ny), (bx - nx, by - ny)], w=0.2, fill=BLACK)

    def dim_h(self, xa, ya, xb, yb, yd, txt):
        """Горизонтальный размер между точками (xa, ya) и (xb, yb),
        размерная линия на уровне yd."""
        if xb < xa:
            xa, ya, xb, yb = xb, yb, xa, ya
        up = -1 if yd < min(ya, yb) else 1
        for x, y in ((xa, ya), (xb, yb)):
            gap = 0.8 * up
            if abs(yd - y) > 1.0:
                self.line(x, y + gap, x, yd + 1.5 * up)
        span = xb - xa
        tw = self.text_len(txt, self.DIM_SIZE)
        inside = span >= 2 * self.ARROW_L + 1.0
        if inside:
            self.line(xa, yd, xb, yd)
            self.arrow(xa, yd, -1, 0)
            self.arrow(xb, yd, 1, 0)
        else:
            self.line(xa - 4, yd, xb + 4, yd)
            self.arrow(xa, yd, 1, 0)
            self.arrow(xb, yd, -1, 0)
        ty = yd - 2.0
        if span >= tw + 1.0:
            self.text((xa + xb) / 2, ty, txt, self.DIM_SIZE)
        else:
            self.text(xb + 1.0, ty, txt, self.DIM_SIZE, anchor="l")

    def dim_v(self, xa, ya, xb, yb, xd, txt):
        """Вертикальный размер между (xa, ya) и (xb, yb), линия на x = xd."""
        if yb < ya:
            xa, ya, xb, yb = xb, yb, xa, ya
        side = -1 if xd < min(xa, xb) else 1
        for x, y in ((xa, ya), (xb, yb)):
            if abs(xd - x) > 1.0:
                self.line(x + 0.8 * side, y, xd + 1.5 * side, y)
        span = yb - ya
        tw = self.text_len(txt, self.DIM_SIZE)
        if span >= 2 * self.ARROW_L + 1.0:
            self.line(xd, ya, xd, yb)
            self.arrow(xd, ya, 0, -1)
            self.arrow(xd, yb, 0, 1)
        else:
            self.line(xd, ya - 4, xd, yb + 4)
            self.arrow(xd, ya, 0, 1)
            self.arrow(xd, yb, 0, -1)
        tx = xd - 2.0
        if span >= tw + 1.0:
            self.text(tx, (ya + yb) / 2, txt, self.DIM_SIZE, rotate=90)
        else:
            self.text(tx, ya - 1.0, txt, self.DIM_SIZE, anchor="l", rotate=90)

    def dim_angle(self, vx, vy, a0, a1, r, txt):
        """Угловой размер: дуга радиуса r вокруг (vx, vy) от угла a0 до a1
        (радианы, в координатах листа, Y вниз)."""
        if a1 < a0:
            a0, a1 = a1, a0
        if a1 - a0 > math.pi:
            a0, a1 = a1, a0 + 2 * math.pi
        n = 16
        pts = [(vx + r * math.cos(a0 + (a1 - a0) * i / n), vy + r * math.sin(a0 + (a1 - a0) * i / n))
               for i in range(n + 1)]
        self.poly(pts, closed=False)
        self.arrow(*pts[0], math.sin(a0), -math.cos(a0))
        self.arrow(*pts[-1], -math.sin(a1), math.cos(a1))
        am = (a0 + a1) / 2
        self.text(vx + (r + 3.5) * math.cos(am), vy + (r + 3.0) * math.sin(am), txt, self.DIM_SIZE)

    # ------------------------------------------------------------ таблица
    def table(self, x0, y0, cols, rows, heights, sizes=None, anchors=None, w=THIN):
        """cols — ширины колонок; rows — список строк (список ячеек или
        callable(canvas, x, y, w, h)); heights — высота каждой строки."""
        xs = [x0]
        for c in cols:
            xs.append(xs[-1] + c)
        y = y0
        for ri, (row, rh) in enumerate(zip(rows, heights)):
            self.line(x0, y, xs[-1], y, w)
            if isinstance(row, str):            # объединённая строка-заголовок
                self.text((x0 + xs[-1]) / 2, y + rh / 2, row, (sizes or {}).get("title", 9))
            else:
                for ci, cell in enumerate(row):
                    cx0, cx1 = xs[ci], xs[ci + 1]
                    if callable(cell):
                        cell(self, cx0, y, cx1 - cx0, rh)
                        continue
                    if cell in (None, ""):
                        continue
                    a = (anchors or ["c"] * len(cols))[ci]
                    tx = {"l": cx0 + 1.5, "c": (cx0 + cx1) / 2, "r": cx1 - 1.5}[a]
                    self.text(tx, y + rh / 2, cell, (sizes or {}).get("cell", 8.5), anchor=a)
            y += rh
        self.line(x0, y, xs[-1], y, w)
        # вертикали: для строк-заголовков — только внешние
        y = y0
        for row, rh in zip(rows, heights):
            for i, x in enumerate(xs):
                if isinstance(row, str) and 0 < i < len(xs) - 1:
                    continue
                self.line(x, y, x, y + rh, w)
            y += rh
        return y

    # ------------------------------------------------------------ рамка
    def frame(self, project, title, stage, sheet_no, sheets_total, company):
        W, H = self.w, self.h
        self.rect(20, 5, W - 5, H - 5, w=FRAME)
        x0, y0 = W - 5 - 120, H - 5 - 30
        x1, y1 = W - 5, H - 5
        xm = x0 + 70
        self.rect(x0, y0, x1, y1, w=MAIN, fill=(1, 1, 1))
        self.line(x0, y0 + 15, x1, y0 + 15, MAIN)
        self.line(xm, y0, xm, y1, MAIN)
        self.line(xm, y0 + 5, x1, y0 + 5, MAIN)
        c = (x1 - xm) / 3
        for i in (1, 2):
            self.line(xm + c * i, y0, xm + c * i, y0 + 15, MAIN)
        for i, (hdr, val) in enumerate((("Стадия", stage), ("Лист", sheet_no), ("Листов", sheets_total))):
            cx = xm + c * i + c / 2
            self.text(cx, y0 + 2.5, hdr, 8)
            self.text(cx, y0 + 10, val, 9)
        self.text((x0 + xm) / 2, y0 + 7.5, project, 11)
        self.text((x0 + xm) / 2, y0 + 22.5, title, 10)
        self.text((xm + x1) / 2, y0 + 22.5, company, 14)
        return (x0, y0, x1, y1)


# ------------------------------------------------------------ изометрия

def iso_faces(outline, b):
    """Грани выдавленного контура в аксонометрии (u, v — Y вверх).
    Возвращает [(points, fill)], уже упорядоченные для «художника»."""
    def pr(x, y, z):
        return (x * 0.985 + z * 0.62, y + z * 0.42 + x * 0.075)
    front = [pr(x, y, 0) for x, y in outline]
    back = [pr(x, y, b) for x, y in outline]
    faces = [(back, FILL_DARK)]
    sides = []
    n = len(outline)
    for i in range(n):
        j = (i + 1) % n
        quad = [front[i], front[j], back[j], back[i]]
        (x1, y1), (x2, y2) = outline[i], outline[j]
        # верхние грани светлее боковых
        shade = FILL_SIDE if abs(y2 - y1) > abs(x2 - x1) else (0.86, 0.85, 0.79)
        depth = -((outline[i][1] + outline[j][1]) / 2)
        sides.append((depth, quad, shade))
    sides.sort(key=lambda t: t[0])
    faces += [(q, sh) for _, q, sh in sides]
    faces.append((front, FILL))
    return faces


def draw_iso(cv: Canvas, outline, b, x, y, w, h, pad=1.5):
    """Миниатюра «Внешний вид» в прямоугольнике (x, y, w, h) листа."""
    faces = iso_faces(outline, b)
    us = [p[0] for f, _ in faces for p in f]
    vs = [p[1] for f, _ in faces for p in f]
    du, dv = (max(us) - min(us)) or 1, (max(vs) - min(vs)) or 1
    k = min((w - 2 * pad) / du, (h - 2 * pad) / dv)
    ox = x + (w - du * k) / 2 - min(us) * k
    oy = y + (h + dv * k) / 2 + min(vs) * k
    for pts, fill in faces:
        cv.poly([(ox + u * k, oy - v * k) for u, v in pts], w=0.25, color=GREY, fill=fill)
