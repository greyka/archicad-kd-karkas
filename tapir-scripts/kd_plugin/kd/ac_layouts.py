"""Листы КД внутри проекта Archicad: макеты в книге макетов.

Тот же рисунок, что и в PDF (sheets.py), но элементами Archicad —
штриховки, полилинии, тексты — на макетах с мастер-макетом проекта.
Штамп, номер листа и «Листов» даёт мастер-макет (автотекст Archicad).

Работает с любым проектом: книга макетов, мастер и сплошная заливка
ищутся по дереву навигатора и атрибутам; имена — из config.json.
"""
from __future__ import annotations

import math

from .archicad import ArchicadError, Client
from .model import Group
from .pdfdoc import A3L, A4P, BLACK, PT, Canvas, gost_mm
from .sheets import Sheet, list_pages, list_sheets, plan_sheets


# ------------------------------------------------------------------ холст

class ArchicadCanvas(Canvas):
    """Холст листа, который копит элементы и создаёт их на макете.
    Координаты — мм от левого верхнего угла (как в PDF), на макете —
    метры от левого нижнего угла листа."""

    def __init__(self, size_mm, solid_fill_guid, pen=1, pen_for=None, layer=None, font=None):
        self.w, self.h = size_mm
        self.layer = layer
        self.font = font
        self.solid = solid_fill_guid
        self.pen = pen
        self.pen_for = pen_for or (lambda rgb: pen)    # цвет -> ближайшее перо
        self.hatches, self.polylines, self.texts = [], [], []

    def _p(self, x, y):
        return {"x": x / 1000, "y": (self.h - y) / 1000}

    @staticmethod
    def _mm(w_pt):
        return round(w_pt / PT, 3)

    def line(self, x1, y1, x2, y2, w=0.18 * PT, color=BLACK):
        self.polylines.append({"coordinates": [self._p(x1, y1), self._p(x2, y2)],
                               "penWeightMm": self._mm(w), "linePenIndex": self.pen})

    def rect(self, x0, y0, x1, y1, w=0.18 * PT, color=BLACK, fill=None):
        self.poly([(x0, y0), (x1, y0), (x1, y1), (x0, y1)], w=w, color=color, fill=fill)

    def poly(self, pts, w=0.18 * PT, color=BLACK, fill=None, closed=True):
        pts = list(pts)
        if fill is not None and closed and len(pts) >= 3 and fill != (1, 1, 1):
            self.hatches.append({
                "coordinates": [self._p(x, y) for x, y in pts],
                "fillId": {"guid": self.solid},
                "fillPenIndex": self.pen_for(fill),
                "contourPenIndex": self.pen})
        ring = pts + [pts[0]] if closed else pts
        self.polylines.append({"coordinates": [self._p(x, y) for x, y in ring],
                               "penWeightMm": self._mm(w), "linePenIndex": self.pen})

    def text(self, x, y, txt, size=9.0, anchor="c", key="gost", rotate=0, color=BLACK):
        txt = str(txt)
        anc = {"l": "LeftMiddle", "c": "MiddleMiddle", "r": "RightMiddle"}[anchor]
        p = self._p(x, y)
        self.texts.append({"coordinate": {**p, "z": 0}, "text": txt,
                           "height": gost_mm(size), "pen": self.pen,
                           "angle": math.pi / 2 if rotate else 0.0,
                           "style": {"anchor": anc, "bold": key == "bold",
                                     # в ГОСТ-шрифте нет «:» — масштаб пишем шрифтом по умолчанию
                                     **({"fontIndex": self.font} if self.font and key != "arial" else {})}})
        return self.text_len(txt, size, key)

    def commit(self):
        pass

    def flush(self, c: Client):
        # порядок: заливки снизу, линии и тексты поверх
        if self.layer is not None:
            for d in self.hatches + self.polylines:
                d["layerIndex"] = self.layer
        if self.hatches:
            c.tapir("CreateHatches", {"hatchesData": self.hatches})
        if self.polylines:
            c.tapir("CreatePolylines", {"polylinesData": self.polylines})
        if self.texts:
            r = c.tapir("CreateTexts", {"textsData": self.texts})
            ids = [e for e in r.get("elements", []) if "elementId" in e]
            if self.layer is not None and ids:   # у CreateTexts нет layerIndex
                c.tapir("SetDetailsOfElements", {"elementsWithDetails": [
                    {"elementId": e["elementId"], "details": {"layerIndex": self.layer}} for e in ids]})
        n = len(self.hatches) + len(self.polylines) + len(self.texts)
        self.hatches, self.polylines, self.texts = [], [], []
        return n


# ------------------------------------------------------------------ навигатор

def _items(node):
    it = node.get("navigatorItem", node)
    yield it
    for ch in it.get("children") or []:
        yield from _items(ch)


def _children(item):
    return [ch.get("navigatorItem", ch) for ch in item.get("children") or []]


def layout_book(c: Client):
    return c.tapir("GetNavigatorItemTree", {"navigatorMapId": "LayoutBook"})["navigatorItemTree"]


def find_solid_fill(c: Client) -> str:
    fills = c.tapir("GetAttributesByType", {"attributeType": "Fill"}).get("attributes", [])
    det = c.tapir("GetFills", {"attributeIds": [{"attributeId": f["attributeId"]} for f in fills]})
    solids = [f for f in det.get("fills", []) if f.get("subType") == "Solid" and f.get("useForDraft", True)]
    # «75 %», «50 %» — тоже Solid, но с растром; нужна 100 %
    solids.sort(key=lambda f: -f.get("percent", 0))
    if solids:
        return solids[0]["attributeId"]["guid"]
    raise ArchicadError("В проекте нет сплошной заливки (тип Solid) — создайте её в Реквизиты → Штриховки.")


def ensure_layer(c: Client, name: str) -> int:
    """Видимый слой для элементов КД (текущий слой может быть скрыт)."""
    def find():
        for a in c.tapir("GetAttributesByType", {"attributeType": "Layer"}).get("attributes", []):
            if a.get("name") == name:
                return a
    a = find()
    if a is None:
        c.tapir("CreateLayers", {"layerDataArray": [{"name": name, "isHidden": False, "isLocked": False}]})
        a = find()
    else:
        info = c.tapir("GetLayers", {"attributeIds": [{"attributeId": a["attributeId"]}]})["layers"][0]
        if info.get("isHidden") or info.get("isLocked"):
            c.tapir("CreateLayers", {"overwriteExisting": True, "layerDataArray": [
                {"name": name, "attributeId": a["attributeId"], "isHidden": False, "isLocked": False}]})
    if a is None:
        raise ArchicadError(f"Не удалось создать слой «{name}».")
    return a["index"]


def master_font(c: Client, tree, master_name):
    """Шрифт штампа мастер-макета (обычно ГОСТ 2.304) — им же пишем листы."""
    import collections
    m = next((it for it in _items(tree) if it.get("type") == "MasterLayoutItem"
              and it.get("name") == master_name), None)
    if not m:
        return None
    try:
        db = c.tapir("GetDatabaseIdFromNavigatorItemId",
                     {"navigatorItemIds": [{"navigatorItemId": m["navigatorItemId"]}]})
        dbid = next(v for v in db.values() if isinstance(v, list))[0]["databaseId"]
        c.tapir("ChangeWindow", {"windowType": "MasterLayout", "databaseId": dbid})
        tx = c.tapir("GetElementsByType", {"elementType": "Text"}).get("elements", [])
        if not tx:
            return None
        det = c.tapir("GetDetailsOfElements", {"elements": tx})["detailsOfElements"]
        cnt = collections.Counter((d.get("details", {}).get("style") or {}).get("fontIndex") for d in det)
        cnt.pop(None, None)
        return cnt.most_common(1)[0][0] if cnt else None
    except ArchicadError:
        return None


def pen_matcher(c: Client):
    """Ближайшее по цвету перо таблицы перьев книги макетов: заливка
    штриховки на экране и в публикации рисуется цветом пера."""
    pid = c.call("API.GetActivePenTables")["layoutBookPenTableId"]
    r = c.tapir("GetPenTables", {"attributeIds": [pid]})
    pens = next(v for v in r.values() if isinstance(v, list))[0].get("pens", [])
    cache = {}

    def match(rgb):
        rgb = tuple(rgb)
        if rgb not in cache:
            cache[rgb] = min(pens, key=lambda p: sum((p["color"][k] - t) ** 2 for k, t in
                                                     zip(("red", "green", "blue"), rgb)))["index"]
        return cache[rgb]
    return match


def pick_masters(c: Client, tree, cfg):
    """Имена мастер-макетов для A3 альбомного и A4 книжного."""
    masters = [it for it in _items(tree) if it.get("type") == "MasterLayoutItem"]
    names = [m["name"] for m in masters]
    want = {"a3": cfg.get("master_a3"), "a4": cfg.get("master_a4")}
    out = {}
    for k, v in want.items():
        if v and v in names:
            out[k] = v
    if len(out) < 2 and masters:
        st = c.tapir("GetLayoutSettings", {"layoutDatabaseIds": [
            {"navigatorItemId": m["navigatorItemId"]} for m in masters]})
        lst = next((v for v in st.values() if isinstance(v, list)), [])
        for m, s in zip(masters, lst):
            size = (round(s.get("horizontalSize", 0)), round(s.get("verticalSize", 0)))
            if "a3" not in out and size == A3L:
                out["a3"] = m["name"]
            if "a4" not in out and size == A4P:
                out["a4"] = m["name"]
    return out.get("a3"), out.get("a4")


def ensure_subset(c: Client, name: str):
    """Подмножество КД в первой книге макетов; старые листы в нём удаляются."""
    tree = layout_book(c)
    books = [it for it in _children(tree) if it.get("type") == "BookItem"]
    parent = books[0] if books else tree
    subset = next((it for it in _children(parent)
                   if it.get("type") == "SubSetItem" and it.get("name") == name), None)
    if subset:
        old = [{"navigatorItemId": it["navigatorItemId"]} for it in _children(subset)
               if it.get("type") == "LayoutItem"]
        if old:
            c.tapir("DeleteNavigatorItems", {"navigatorItemIds": old})
    else:
        c.tapir("CreateLayoutSubset", {"subsetsData": [
            {"name": name, "parentNavigatorItemId": parent["navigatorItemId"]}]})
        tree = layout_book(c)
        books = [it for it in _children(tree) if it.get("type") == "BookItem"]
        parent = books[0] if books else tree
        subset = next((it for it in _children(parent)
                       if it.get("type") == "SubSetItem" and it.get("name") == name), None)
        if not subset:
            raise ArchicadError(f"Не удалось создать подмножество «{name}» в книге макетов.")
    return subset["navigatorItemId"], tree


# ------------------------------------------------------------------ выпуск

def publish_layouts(groups: list[Group], cfg: dict, log=print) -> dict:
    acfg = cfg.get("archicad", {})
    c = Client(acfg.get("port"))
    subset_name = acfg.get("subset_name", "КД каркаса (авто)")

    sheets = plan_sheets(groups, cfg)
    subset_id, tree = ensure_subset(c, subset_name)
    m_a3, m_a4 = pick_masters(c, tree, acfg)
    solid = find_solid_fill(c)
    pen_for = pen_matcher(c)
    layer = ensure_layer(c, acfg.get("layer_name", "КД - чертежи (авто)"))
    font = acfg.get("font_index") or master_font(c, tree, m_a3)
    log(f"Шрифт: индекс {font} (из мастер-макета)" if font else "Шрифт: по умолчанию инструмента «Текст»")
    log(f"Мастер A3: {m_a3}, A4: {m_a4}; подмножество «{subset_name}»")

    # 1) все макеты разом — ведомость первой. Archicad вставляет новый
    #    макет в начало подмножества, поэтому создаём в обратном порядке.
    k = list_pages(len(sheets))
    all_sheets = [Sheet("Ведомость чертежей" + (f" (лист {i + 1})" if k > 1 else ""), A4P, None)
                  for i in range(k)] + sheets
    data = []
    for sh in reversed(all_sheets):
        d = {"layoutName": sh.title, "parentNavigatorItemId": subset_id}
        m = m_a4 if sh.size == A4P else m_a3
        if m:
            d["masterLayoutName"] = m
        data.append(d)
    dbs = c.tapir("CreateLayout", {"layoutsData": data}).get("databases", [])
    if len(dbs) != len(all_sheets) or any("error" in d for d in dbs):
        raise ArchicadError(f"Не все макеты созданы: {dbs[:3]}")
    dbs.reverse()

    # 2) номера листов, которые присвоил Archicad
    tree = layout_book(c)
    sub = next(it for it in _items(tree) if it["navigatorItemId"] == subset_id)
    kids = [it for it in _children(sub) if it.get("type") == "LayoutItem"]
    if [it["name"] for it in kids] == [sh.title for sh in all_sheets]:
        nums = [it.get("uiId") or "" for it in kids]
    else:
        nums = [str(i + 1) for i in range(len(all_sheets))]
    lists = list_sheets([(n, sh.title) for n, sh in zip(nums, all_sheets)])
    all_sheets[:k] = [Sheet(all_sheets[i].title, A4P, lists[i].draw) for i in range(k)]

    # 3) рисуем каждый лист в его макете
    total = 0
    for i, (sh, db) in enumerate(zip(all_sheets, dbs), 1):
        c.tapir("ChangeWindow", {"windowType": "Layout", "databaseId": db["databaseId"]})
        cv = ArchicadCanvas(sh.size, solid, pen=acfg.get("pen", 1), pen_for=pen_for, layer=layer, font=font)
        sh.draw(cv)
        total += cv.flush(c)
        log(f"  [{i}/{len(all_sheets)}] {sh.title}")
    c.tapir("ChangeWindow", {"windowType": "Layout", "databaseId": dbs[0]["databaseId"]})
    return {"layouts": len(all_sheets), "elements": total, "subset": subset_name}


def publish_pdf(cfg: dict, output_path: str, log=print) -> str:
    """Общий PDF: набор публикации Archicad по выбранным подмножествам книги
    макетов (по умолчанию — подмножество КД), результат — один файл."""
    import glob
    import os
    import shutil
    import tempfile

    import pymupdf

    acfg = cfg.get("archicad", {})
    c = Client(acfg.get("port"))
    sets = c.call("API.GetPublisherSetNames").get("publisherSetNames", [])
    name = acfg.get("publisher_set") or next((s for s in sets if "макет" in s.lower()), sets[0] if sets else None)
    if name not in sets:
        raise ArchicadError(f"Набор публикации «{name}» не найден. Есть: {sets}")

    wanted = acfg.get("publish_subsets") or [acfg.get("subset_name", "КД каркаса (авто)")]
    tree = c.tapir("GetNavigatorItemTree", {"navigatorMapId": "PublisherSets",
                                            "publisherSetName": name})["navigatorItemTree"]
    items = list(_items(tree))
    picked = []
    for w in wanted:
        it = next((i for i in items if i.get("name") == w and i.get("type") != "LayoutItem"), None)
        if it is None:
            log(f"  [!] в наборе «{name}» нет подмножества «{w}» — пропущено")
        else:
            picked.append({"navigatorItemId": it["navigatorItemId"]})
    if not picked:
        own = acfg.get("subset_name", "КД каркаса (авто)")
        if own in wanted:
            raise ArchicadError("Листов КД в проекте ещё нет.\n\n"
                                "Сначала выберите «Листы в Archicad» или «Пересоздать листы + общий PDF».")
        raise ArchicadError(f"В наборе публикации «{name}» нет подмножеств: {', '.join(wanted)}.")

    tmp = tempfile.mkdtemp(prefix="kd_publish_")
    try:
        log(f"Публикация «{name}»: {', '.join(wanted)}…")
        c.tapir("PublishPublisherSet", {"publisherSetName": name, "outputPath": tmp,
                                        "selectedNavigatorItemIds": picked})
        pdfs = sorted(glob.glob(os.path.join(tmp, "**", "*.pdf"), recursive=True))
        if not pdfs:
            raise ArchicadError("Набор публикации не выдал PDF — проверьте формат вывода в его настройках.")
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
        if len(pdfs) == 1:
            shutil.copyfile(pdfs[0], output_path)
        else:                                  # набор без «объединить в один файл»
            doc = pymupdf.open()
            for f in pdfs:
                doc.insert_pdf(pymupdf.open(f))
            doc.save(output_path, garbage=3, deflate=True)
        return output_path
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
