"""Маркировка: одинаковые детали (слой + сечение + форма) получают одну марку."""
from __future__ import annotations

import re
from collections import OrderedDict

from .model import Group, Part, canonical_outline, shape_key

_TRANSLIT = str.maketrans({
    "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E", "Ж": "ZH",
    "З": "Z", "И": "I", "Й": "I", "К": "K", "Л": "L", "М": "M", "Н": "N", "О": "O",
    "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U", "Ф": "F", "Х": "H", "Ц": "C",
    "Ч": "CH", "Ш": "SH", "Щ": "SH", "Ы": "Y", "Э": "E", "Ю": "YU", "Я": "YA",
})


def auto_prefix(layer: str) -> str:
    """«Верхняя обвязка» -> «VO», «Ферма» -> «F»."""
    words = [w for w in re.split(r"[\s,\-()]+", layer) if w and not w.isdigit()]
    if not words:
        return "D"
    if len(words) == 1:
        return words[0][0].upper().translate(_TRANSLIT)
    return "".join(w[0].upper() for w in words[:2]).translate(_TRANSLIT)


def make_groups(parts: list[Part], prefixes: dict[str, str] | None = None,
                layer_order: list[str] | None = None, tol: float = 1.0) -> list[Group]:
    prefixes = prefixes or {}
    buckets: "OrderedDict[tuple, list[Part]]" = OrderedDict()
    for p in parts:
        key = (p.layer, round(p.b), p.mat, p.note, shape_key(p.outline))
        buckets.setdefault(key, []).append(p)

    # Слияние почти одинаковых форм: 3640,5 мм округляется то в 3640, то в 3641
    keys = list(buckets)
    for i, ki in enumerate(keys):
        if ki not in buckets:
            continue
        for kj in keys[i + 1:]:
            if kj not in buckets or ki[:4] != kj[:4] or len(ki[4]) != len(kj[4]):
                continue
            if all(abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol for a, b in zip(ki[4], kj[4])):
                buckets[ki].extend(buckets.pop(kj))

    by_layer: "OrderedDict[str, list[list[Part]]]" = OrderedDict()
    for (layer, *_), items in buckets.items():
        by_layer.setdefault(layer, []).append(items)

    order = list(layer_order or [])
    order += sorted(l for l in by_layer if l not in order)

    # Префикс из конфига может быть общим для нескольких слоёв (OB: обрешётка
    # и контробрешётка) — тогда нумерация сквозная. Автопрефиксы не сливаем.
    counters: dict[str, int] = {}
    auto_owner: dict[str, str] = {}
    groups: list[Group] = []
    for layer in order:
        if layer not in by_layer:
            continue
        prefix = prefixes.get(layer)
        if not prefix:
            base = prefix = auto_prefix(layer)
            k = 2
            while (prefix in counters and auto_owner.get(prefix) != layer):
                prefix = f"{base}{k}"
                k += 1
            auto_owner[prefix] = layer
        items = sorted(by_layer[layer], key=lambda g: (-max(x for x, _ in canonical_outline(g[0].outline)),
                                                       -len(g)))
        for members in items:
            counters[prefix] = counters.get(prefix, 0) + 1
            groups.append(Group(mark=f"{prefix}-{counters[prefix]}", layer=layer, b=members[0].b,
                                outline=canonical_outline(members[0].outline),
                                uids=[m.uid for m in members],
                                mat=members[0].mat, note=members[0].note))
    return groups
