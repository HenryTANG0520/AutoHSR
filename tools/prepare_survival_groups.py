"""Reproduce display groups from existing catalogue frames, without game access."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autohsr.dungeon_workflow import guide_rows
from autohsr.dungeons import load_catalogue
from autohsr.models import Scene, Token

LABELS = {
    "calyx_golden": ("二相乐园", "翁法罗斯", "匹诺康尼", "仙舟「罗浮」", "雅利洛-VI"),
    "calyx_crimson": ("欢愉", "毁灭", "存护", "巡猎", "丰饶", "智识", "同谐", "虚无", "记忆"),
    "stagnant_shadow": ("冰", "物理", "火", "雷", "风", "量子", "虚数"),
}
# Exact heading OCR variants in these archived frames, not gameplay matching.
ALIASES = {"浆巡猎": "巡猎", "恣智识": "智识", "擦物理": "物理"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()
    out = ROOT/"assets/ui/survival"
    expected = {(m.category, m.name, m.location) for m in load_catalogue(ROOT/"assets/dungeons.json") if m.category in LABELS}
    groups, members, evidence = {}, {}, {}
    for folder in args.sources:
        for sidecar in sorted(folder.glob("*catalogue_*.json")):
            data = json.loads(sidecar.read_text("utf-8"))
            category = data["category"]
            if category not in LABELS:
                continue
            source = sidecar.with_suffix(".png")
            reference = folder.name+"/"+source.name
            scene = Scene([Token(t["text"], t["score"], tuple(t["box"])) for t in data["tokens"]])
            events = []
            for token in scene.tokens:
                label = ALIASES.get(token.text, token.text)
                if label not in LABELS[category] or not (.37 < token.box[0] < .45 and .26 < token.box[1] < .83):
                    continue
                key = category+":"+label
                events.append((token.center[1], "heading", key))
                if key not in groups:
                    cy = round(token.center[1]*1080)
                    crop = [726, cy-20, 764, cy+20]
                    filename = "group-"+category+"-"+str(LABELS[category].index(label))+".png"
                    with Image.open(source) as image:
                        image.convert("RGB").resize((1920,1080), Image.Resampling.LANCZOS).crop(crop).save(out/filename)
                    groups[key] = dict(id=key, category=category, label=label, file=filename,
                        source=reference, source_sha256=digest(source), sidecar_sha256=digest(sidecar),
                        heading_text=token.text, baseline=[1920,1080], crop=crop, sha256=digest(out/filename))
            for mission, button in guide_rows(scene, category):
                key = mission.category, mission.name, mission.location
                if key in expected:
                    events.append((button.center[1], "mission", key))
            current = None
            for _, kind, key in sorted(events):
                if kind == "heading":
                    current = key
                elif key in members:
                    assert current is None or current == members[key]["group"], (key, current, members[key])
                    current = members[key]["group"]
                elif current is not None:
                    members[key] = dict(category=key[0], name=key[1], location=key[2], group=current, source=reference)
            if any(m["source"] == reference for m in members.values()):
                evidence[reference] = dict(source=reference, source_sha256=digest(source), sidecar_sha256=digest(sidecar))
    assert set(members) == expected, sorted(expected-set(members))
    assert len(groups) == sum(len(labels) for labels in LABELS.values())
    data = dict(client="CN 4.6.0", source_date="2026-10-20", prepared_at="2026-10-29",
        rights="HoYoverse game artwork; not relicensed under source-code GPL",
        transform="Static heading icons only. Membership follows visible headings and overlapping rows across consecutive archived frames; no player portraits, counters or account data.",
        groups=list(groups.values()), memberships=list(members.values()), evidence=list(evidence.values()))
    (out/"groups.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(dict(groups=len(groups), memberships=len(members), source_frames=len(evidence))))


if __name__ == "__main__":
    main()
