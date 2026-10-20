"""Survival Index missions and their resource/count rules.

The bundled catalogue is observed from the client; a local scan can extend it
when a new version adds missions. Catalogue entries never authorize a click:
the workflow must find the name, map and entry together in a fresh screenshot.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .models import normalize


@dataclass(frozen=True)
class DungeonCategory:
    key: str
    label: str
    cost: int
    batch: int = 1
    weekly_limit: int | None = None


CATEGORIES = (
    DungeonCategory("calyx_golden", "拟造花萼（金）", 10, 6),
    DungeonCategory("calyx_crimson", "拟造花萼（赤）", 10, 6),
    DungeonCategory("stagnant_shadow", "凝滞虚影", 30, 6),
    DungeonCategory("cavern", "侵蚀隧洞", 40, 6),
    DungeonCategory("echo_of_war", "历战余响", 30, 3, weekly_limit=3),
    DungeonCategory("planar", "饰品提取", 40, 6),
)
BY_KEY = {item.key: item for item in CATEGORIES}

# Exact OCR variants observed in the 4.6 client samples. No fuzzy matching:
# category, canonical name, map and entry must still agree in one visible row.
NAME_OCR = {
    "stagnant_shadow": {"塞王之形": "塞壬之形", "灼之形": "燔灼之形",
                         "机狼之形機": "机狼之形", "役轮之形機": "役轮之形"},
    "echo_of_war": {"蛀星的旧魔": "蛀星的旧魇"},
}
MAP_OCR = {"「语密林」神悟树庭": "「呓语密林」神悟树庭", "筑梦边培": "筑梦边境",
           "T造司": "工造司", "迥星港": "迴星港", "苏乐达TM热砂海选会场": "苏乐达™热砂海选会场"}


def mission_name(category, text):
    return NAME_OCR.get(category, {}).get(text.strip(), text.strip())


def mission_map(text):
    value = text.strip().lstrip("?？)）●•·9")
    return MAP_OCR.get(value, value)


def category_for(settings) -> DungeonCategory:
    key = getattr(settings, "dungeon_category", "auto")
    if key == "auto":  # Existing configurations retain their original meaning.
        key = "calyx_golden" if settings.target_name in ("回忆之蕾", "以太之蕾", "藏珍之蕾") else "calyx_crimson"
    if not isinstance(key, str) or key not in BY_KEY:
        raise ValueError("未知副本分类，请从生存索引分类中选择。")
    return BY_KEY[key]


def count_limit(category: DungeonCategory, stamina=240) -> int:
    return min(stamina // category.cost, category.weekly_limit or 24)


@dataclass(frozen=True)
class Dungeon:
    category: str
    name: str
    location: str


def load_catalogue(bundled: Path, local: Path | None = None) -> list[Dungeon]:
    missions = {}
    for path in (bundled, local):
        if path is None or not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("missions"), list):
            raise ValueError(f"副本目录格式错误：{path}")
        for entry in data["missions"]:
            item = Dungeon(**entry)
            if (item.category not in BY_KEY or not isinstance(item.name, str) or not item.name.strip()
                    or not isinstance(item.location, str) or not item.location.strip()):
                raise ValueError(f"副本目录条目错误：{path}")
            missions[(item.category, normalize(item.name), normalize(item.location))] = item
    return list(missions.values())


def save_catalogue(path: Path, missions: list[Dungeon], **metadata) -> None:
    data = dict(version=1, **metadata, missions=[asdict(item) for item in missions])
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
