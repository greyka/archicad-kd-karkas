"""Сбор деталей из открытого проекта Archicad (JSON API + аддон Tapir).

Источник — объекты ArchiFramePlank. Нужна загруженная библиотека ArchiFrame
(проект в виде .pla с вложенной библиотекой подходит; сам аддон не нужен):
геометрия доски восстанавливается из её GDL-параметров.

Расшифровка iMc (по 16 чисел на обработку):
  [0] код: 101 — запил начала, 201 — запил конца, 301 — произвольный рез
  [1] угол в плане (по ширине b), [2] угол по высоте h; 90° — без запила
  [3] вылет за опорную линию
iLen — длина опорной линии. По высоте опорная линия — нижняя грань:
верхняя грань начинается в x = h·cot(a_beg) и кончается в L − h·cot(a_end).
"""
from __future__ import annotations

import json
import math
import urllib.request

from .model import Part

PORTS = range(19723, 19745)


class ArchicadError(RuntimeError):
    pass


class Client:
    def __init__(self, port: int | None = None):
        self.port = port or self._find_port()

    @staticmethod
    def _post(port, payload, timeout=60):
        req = urllib.request.Request(f"http://127.0.0.1:{port}", data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _find_port(self):
        for p in PORTS:
            try:
                if self._post(p, {"command": "API.IsAlive"}, timeout=0.5).get("result", {}).get("isAlive"):
                    return p
            except OSError:
                continue
        raise ArchicadError("Archicad не найден: запустите его и откройте проект.")

    def call(self, command, params=None):
        payload = {"command": command}
        if params is not None:
            payload["parameters"] = params
        r = self._post(self.port, payload, timeout=600)
        if not r.get("succeeded"):
            err = r.get("error", {})
            if err.get("code") == 4001:
                raise ArchicadError("В Archicad открыт диалог или идёт ввод — закройте его и повторите.")
            raise ArchicadError(f"{command}: {err}")
        return r.get("result", {})

    def tapir(self, name, params=None):
        r = self.call("API.ExecuteAddOnCommand", {
            "addOnCommandId": {"commandNamespace": "TapirCommand", "commandName": name},
            "addOnCommandParameters": params or {}})
        resp = r.get("addOnCommandResponse", {})
        if isinstance(resp, dict) and resp.get("error"):
            raise ArchicadError(f"Tapir {name}: {resp['error']}")
        return resp

    def property_values(self, elements, names):
        ids = self.call("API.GetPropertyIds", {"properties": [
            {"type": "BuiltIn", "nonLocalizedName": n} for n in names]})["properties"]
        res = self.call("API.GetPropertyValuesOfElements", {
            "elements": elements, "properties": [{"propertyId": i["propertyId"]} for i in ids]})
        out = []
        for pv in res["propertyValuesForElements"]:
            row = {}
            for n, v in zip(names, pv["propertyValues"]):
                val = v.get("propertyValue", {}).get("value") if "propertyValue" in v else None
                if isinstance(val, dict):
                    val = val.get("nonLocalizedValue") or val.get("displayValue")
                row[n] = val
            out.append(row)
        return out


# ---------------------------------------------------------------- геометрия доски

def _cot(a_deg):
    t = math.tan(math.radians(a_deg))
    return 0.0 if abs(t) > 1e9 else (1 / t if abs(t) > 1e-9 else 0.0)


def plank_geometry(p: dict):
    """По GDL-параметрам ArchiFramePlank: контур (мм), толщина, примечание."""
    L = p["iLen"] * 1000
    b = p["iWidth"] * 1000
    h = p["iHeight"] * 1000
    mc = p.get("iMc") or []
    recs = [mc[i:i + 16] for i in range(0, len(mc), 16) if len(mc[i:i + 16]) == 16 and mc[i]]

    beg_h = end_h = 90.0
    beg_w = end_w = 90.0
    other = 0
    for r in recs:
        code = int(r[0])
        if code == 101:
            beg_w, beg_h = r[1], r[2]
        elif code == 201:
            end_w, end_h = r[1], r[2]
        else:
            other += 1

    def side(L, H, a0, a1):
        """Контур на виде: нижняя грань — опорная линия длины L."""
        x_top0 = H * _cot(a0)
        x_top1 = L - H * _cot(a1)
        return [(0, 0), (L, 0), (x_top1, H), (x_top0, H)]

    def plan(L, B, a0, a1):
        """Вид в плане: опорная линия — ось, грани ±B/2."""
        d0 = B / 2 * _cot(a0)
        d1 = B / 2 * _cot(a1)
        return [(-d0, 0), (L + d1, 0), (L - d1, B), (d0, B)]

    has_h = abs(beg_h - 90) > 0.05 or abs(end_h - 90) > 0.05
    has_w = abs(beg_w - 90) > 0.05 or abs(end_w - 90) > 0.05
    notes = []
    if has_w and not has_h:
        outline, thick = plan(L, b, beg_w, end_w), h
        notes.append("вид в плане")
    else:
        outline, thick = side(L, h, beg_h, end_h), b
        if has_w:
            ws = [f"{abs(90 - a):.4g}°" for a in (beg_w, end_w) if abs(a - 90) > 0.05]
            notes.append("запил в плане " + ", ".join(ws).replace(".", ","))
    if other:
        notes.append(f"доп. резы: {other} шт — см. 3D")
    if int(p.get("iMatShape") or 1) != 1:
        notes.append("профильное сечение")
    return outline, thick, "; ".join(notes)


# ---------------------------------------------------------------- сбор

def collect_parts(cfg: dict, selected_only=False):
    c = Client(cfg.get("port"))
    libparts = set(cfg.get("object_libparts", ["ArchiFramePlank"]))
    skip_layers = set(cfg.get("skip_layers", []))

    if selected_only:
        els = c.tapir("GetSelectedElements").get("elements", [])
    else:
        els = c.call("API.GetElementsByType", {"elementType": "Object"})["elements"]
    if not els:
        raise ArchicadError("Нет элементов (ничего не выделено?).")

    props = c.property_values(els, ["General_ElementID", "ModelView_LayerName",
                                    "General_LibraryPartName"])
    picked = [(e, pr) for e, pr in zip(els, props)
              if pr.get("General_LibraryPartName") in libparts
              and pr.get("ModelView_LayerName") not in skip_layers]
    if not picked:
        raise ArchicadError(f"Среди элементов нет объектов {sorted(libparts)}.")

    gdl = c.tapir("GetGDLParametersOfElements", {"elements": [e for e, _ in picked]})
    gdl = gdl.get("gdlParametersOfElements", [])

    parts, skipped = [], []
    for (e, pr), g in zip(picked, gdl):
        guid = e["elementId"]["guid"]
        if "error" in g:
            skipped.append({"guid": guid, "layer": pr.get("ModelView_LayerName"),
                            "reason": g["error"].get("message")})
            continue
        p = {x["name"]: x.get("value") for x in g["parameters"]}
        try:
            outline, thick, note = plank_geometry(p)
        except (KeyError, TypeError, ValueError) as ex:
            skipped.append({"guid": guid, "layer": pr.get("ModelView_LayerName"), "reason": str(ex)})
            continue
        parts.append(Part(uid=guid, layer=pr.get("ModelView_LayerName") or "Без слоя",
                          b=round(thick), outline=outline, mark=pr.get("General_ElementID") or "",
                          source="ArchiFramePlank", mat=p.get("iMatName") or "", note=note))
    if not parts and skipped:
        raise ArchicadError(
            "Параметры досок не читаются — библиотека ArchiFrame не загружена. "
            "Откройте проект как .pla с вложенной библиотекой.")
    return parts, skipped


def write_marks(cfg: dict, groups) -> int:
    """Записывает марки в ID элементов (General_ElementID)."""
    c = Client(cfg.get("port"))
    pid = c.call("API.GetPropertyIds", {"properties": [
        {"type": "BuiltIn", "nonLocalizedName": "General_ElementID"}]})["properties"][0]["propertyId"]
    items = [{"elementId": {"guid": u}, "propertyId": pid,
              "propertyValue": {"value": g.mark}}
             for g in groups for u in g.uids if not u.count("#")]
    if items:
        c.call("API.SetPropertyValuesOfElements", {"elementPropertyValues": items})
    return len(items)
