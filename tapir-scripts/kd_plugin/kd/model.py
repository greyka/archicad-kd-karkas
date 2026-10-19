"""Деталь каркаса и нормализация её геометрии.

Деталь описывается боковым контуром (outline) в мм: ось X — вдоль длины,
ось Y — по высоте сечения. Толщина b — размер «в глубину» листа.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


def fmt_mm(v: float) -> str:
    """2831 -> '2 831' (как в образце: пробел-разделитель тысяч)."""
    n = int(round(v))
    s = f"{abs(n):,}".replace(",", " ")
    return ("-" if n < 0 else "") + s


@dataclass
class Part:
    uid: str
    layer: str                      # группа = слой Archicad («Ферма», «Колонны, Столбы»)
    b: float                        # толщина сечения, мм
    outline: list[tuple[float, float]]
    mark: str = ""                  # марка, если уже задана в модели
    source: str = ""
    mat: str = ""                   # имя сечения из модели («40x60»); пусто — из b и h
    note: str = ""                  # обработки, которых нет на виде (запил в плане и т.п.)

    @property
    def length(self) -> float:
        xs = [p[0] for p in self.outline]
        return max(xs) - min(xs)

    @property
    def h(self) -> float:
        ys = [p[1] for p in self.outline]
        return max(ys) - min(ys)

    @property
    def section(self) -> str:
        return self.mat or f"{fmt_mm(self.b)}x{fmt_mm(self.h)}"


@dataclass
class Group:
    """Одна марка: набор одинаковых деталей."""
    mark: str
    layer: str
    b: float
    outline: list[tuple[float, float]]   # нормализованный контур-представитель
    uids: list[str] = field(default_factory=list)
    mat: str = ""
    note: str = ""

    @property
    def count(self) -> int:
        return len(self.uids)

    @property
    def length(self) -> float:
        return max(p[0] for p in self.outline)

    @property
    def h(self) -> float:
        return max(p[1] for p in self.outline)

    @property
    def section(self) -> str:
        return self.mat or f"{fmt_mm(self.b)}x{fmt_mm(self.h)}"


# ---------------------------------------------------------------- геометрия

def _clean(poly: list[tuple[float, float]], tol: float = 0.5) -> list[tuple[float, float]]:
    """Убирает дубли и точки на прямой."""
    pts: list[tuple[float, float]] = []
    for p in poly:
        if not pts or math.dist(p, pts[-1]) > tol:
            pts.append(p)
    if len(pts) > 1 and math.dist(pts[0], pts[-1]) <= tol:
        pts.pop()
    changed = True
    while changed and len(pts) > 3:
        changed = False
        for i in range(len(pts)):
            a, b, c = pts[i - 1], pts[i], pts[(i + 1) % len(pts)]
            cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
            if abs(cross) <= tol * max(math.dist(a, c), 1.0):
                pts.pop(i)
                changed = True
                break
    return pts


def _area2(poly) -> float:
    return sum(poly[i - 1][0] * p[1] - p[0] * poly[i - 1][1] for i, p in enumerate(poly))


def normalize(poly: list[tuple[float, float]], nd: int = 0) -> list[tuple[float, float]]:
    """Сдвиг в (0,0), округление (nd знаков, 0 — до 1 мм), обход против часовой."""
    pts = _clean([(float(x), float(y)) for x, y in poly])
    mx = min(p[0] for p in pts)
    my = min(p[1] for p in pts)
    pts = [(round(x - mx, nd) if nd else round(x - mx), round(y - my, nd) if nd else round(y - my))
           for x, y in pts]
    if _area2(pts) < 0:
        pts.reverse()
    return pts


def _canon_seq(pts) -> tuple:
    i = min(range(len(pts)), key=lambda k: pts[k])
    return tuple(pts[i:] + pts[:i])


def shape_key(poly) -> tuple:
    """Ключ формы без учёта зеркалирования: деталь, перевёрнутая
    по длине или по высоте, — та же самая деталь."""
    base = normalize(poly)
    L = max(p[0] for p in base)
    H = max(p[1] for p in base)
    variants = [
        base,
        [(L - x, y) for x, y in base],
        [(x, H - y) for x, y in base],
        [(L - x, H - y) for x, y in base],
    ]
    return min(_canon_seq(normalize(v)) for v in variants)


def canonical_outline(poly) -> list[tuple[float, float]]:
    """Представитель для чертежа: из зеркальных вариантов выбирает тот,
    у которого больше вершин лежит на нижней грани (деталь «лежит» ровно)."""
    base = normalize(poly, nd=1)
    L = max(p[0] for p in base)
    H = max(p[1] for p in base)
    variants = [base,
                normalize([(L - x, y) for x, y in base], nd=1),
                normalize([(x, H - y) for x, y in base], nd=1),
                normalize([(L - x, H - y) for x, y in base], nd=1)]

    def score(v):
        bottom = [p for p in v if p[1] == 0]
        span = (max(p[0] for p in bottom) - min(p[0] for p in bottom)) if bottom else 0
        return (span, -min((p[0] for p in bottom), default=0))
    return max(variants, key=score)


def rect(length: float, h: float) -> list[tuple[float, float]]:
    return [(0, 0), (length, 0), (length, h), (0, h)]
