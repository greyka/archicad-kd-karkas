"""Свойства «КД каркаса» в доски — для интерактивного каталога Archicad.

Archicad не даёт пользовательских свойств неклассифицированным элементам,
поэтому доскам присваивается позиция «Деталь каркаса» в отдельной системе
классификации «КД каркаса» (классификацию ARCHICAD это не трогает).
Свойства доступны только для этой позиции. Схема каталога настраивается
один раз: критерий «КД каркаса / Марка» не пусто, поля из группы «КД каркаса».
"""
from __future__ import annotations

from .archicad import ArchicadError, Client
from .model import Group

SYSTEM = "КД каркаса"
ITEM_ID, ITEM_NAME = "КД-1", "Деталь каркаса"
PROP_GROUP = "КД каркаса"
PROPS = [                      # имя, тип Archicad
    ("Марка", "string"),
    ("Группа", "string"),
    ("Сечение", "string"),
    ("Длина, мм", "integer"),
    ("Кол-во в марке", "integer"),
    ("Примечание", "string"),
]


def _classification_item(c: Client):
    """id системы «КД каркаса» и позиции «Деталь каркаса» (создаёт при отсутствии)."""
    def find():
        for s in c.call("API.GetAllClassificationSystems")["classificationSystems"]:
            if s["name"] == SYSTEM:
                items = c.call("API.GetAllClassificationsInSystem",
                               {"classificationSystemId": s["classificationSystemId"]})["classificationItems"]
                for it in items:
                    ci = it["classificationItem"]
                    if ci.get("id") == ITEM_ID:
                        return s["classificationSystemId"], ci["classificationItemId"]
        return None
    found = find()
    if not found:
        c.tapir("CreateClassificationSystems", {"classificationSystemsWithItems": [{
            "classificationSystem": {"name": SYSTEM, "description": "Детали деревянного каркаса (плагин КД каркаса)",
                                     "source": "github.com/greyka/archicad-kd-karkas", "version": "1",
                                     "date": "2026-10-19"},
            "classificationItems": [{"id": ITEM_ID, "name": ITEM_NAME,
                                     "description": "Доска/брус каркаса ArchiFrame"}]}]})
        found = find()
    if not found:
        raise ArchicadError(f"Не удалось создать классификацию «{SYSTEM}».")
    return found


def _property_ids(c: Client, item_id) -> dict[str, dict]:
    """id свойств группы «КД каркаса» (создаёт недостающие)."""
    def lookup():
        r = c.call("API.GetPropertyIds", {"properties": [
            {"type": "UserDefined", "localizedName": [PROP_GROUP, n]} for n, _ in PROPS]})
        return {n: p.get("propertyId") for (n, _), p in zip(PROPS, r["properties"])}

    ids = lookup()
    missing = [(n, t) for n, t in PROPS if not ids.get(n)]
    if missing:
        try:
            c.tapir("CreatePropertyGroups", {"propertyGroups": [{"propertyGroup": {"name": PROP_GROUP}}]})
        except ArchicadError:
            pass                                    # группа уже есть
        default = {"string": {"type": "string", "status": "normal", "value": ""},
                   "integer": {"type": "integer", "status": "normal", "value": 0}}
        c.tapir("CreatePropertyDefinitions", {"propertyDefinitions": [{"propertyDefinition": {
            "name": n, "description": "Плагин «КД каркаса»", "type": t, "isEditable": True,
            "defaultValue": {"basicDefaultValue": default[t]},
            "availability": [{"classificationItemId": item_id}],
            "group": {"name": PROP_GROUP}}} for n, t in missing]})
        ids = lookup()
    if any(not v for v in ids.values()):
        raise ArchicadError(f"Не удалось создать свойства группы «{PROP_GROUP}».")
    return ids


def write_properties(groups: list[Group], cfg: dict, log=print) -> dict:
    c = Client(cfg.get("archicad", {}).get("port"))
    sys_id, item_id = _classification_item(c)
    pids = _property_ids(c, item_id)

    guids = [u for g in groups for u in g.uids if "#" not in u]
    if not guids:
        raise ArchicadError("Нет досок из модели для записи свойств.")

    # 1) позиция «Деталь каркаса» в своей системе классификации
    c.call("API.SetClassificationsOfElements", {"elementClassifications": [
        {"elementId": {"guid": u},
         "classificationId": {"classificationSystemId": sys_id, "classificationItemId": item_id}}
        for u in guids]})

    # 2) значения свойств
    def val(t, v):
        return {"type": t, "status": "normal", "value": v}
    items = []
    for g in groups:
        values = {"Марка": g.mark, "Группа": g.layer, "Сечение": g.section,
                  "Длина, мм": int(round(g.length)), "Кол-во в марке": g.count, "Примечание": g.note or ""}
        for u in g.uids:
            if "#" in u:
                continue
            for n, t in PROPS:
                items.append({"elementId": {"guid": u}, "propertyId": pids[n], "propertyValue": val(t, values[n])})
    res = c.call("API.SetPropertyValuesOfElements", {"elementPropertyValues": items})
    bad = [r for r in res.get("executionResults", []) if not r.get("success")]
    if bad:
        log(f"  [!] не записано значений: {len(bad)} — {bad[0].get('error', {}).get('message')}")
    return {"elements": len(guids), "values": len(items) - len(bad), "marks": len(groups)}
