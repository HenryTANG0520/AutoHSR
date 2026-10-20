"""Re-read saved catalogue fields at native resolution; never accesses the game."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autohsr.dungeon_workflow import guide_rows
from autohsr.models import Scene, Token, normalize
from autohsr.vision import Vision


def audit(directory: Path, output: Path):
    import cv2
    import numpy as np
    vision = Vision()
    missions = {}
    counts = Counter()
    samples = []
    for path in sorted(directory.glob("*catalogue_*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        category = data["category"]
        pixels = cv2.imdecode(np.frombuffer(path.with_suffix(".png").read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        scene = Scene([Token(t["text"], t["score"], tuple(t["box"])) for t in data["tokens"]], pixels)
        vision.refine_dungeon_rows(scene, category)
        rows = guide_rows(scene, category)
        for mission, button in rows:
            key = (category, normalize(mission.name), normalize(mission.location))
            missions[key] = dict(category=category, name=mission.name, location=mission.location)
            counts[key] += 1
        samples.append(dict(source=path.name, category=category,
                            missions=[dict(name=m.name, location=m.location) for m,b in rows],
                            tokens=[dict(text=t.text,score=t.score,box=t.box) for t in scene.tokens
                                    if t.within((.40,.26,.88,.83))]))
    result = dict(version=1, source=str(directory), game_accessed=False, native_field_ocr=True,
                  missions=list(missions.values()), samples=samples,
                  observations=[dict(category=k[0], name=missions[k]["name"], location=missions[k]["location"], count=n)
                                for k,n in counts.items()])
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(dict(path=str(output), count=len(missions),
                         categories=dict(Counter(k[0] for k in missions))), ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    audit(args.directory, args.output)
