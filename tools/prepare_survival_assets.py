"""Extract static row artwork from existing, local catalogue evidence only."""
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("sources", nargs="+", type=Path)
    args = parser.parse_args()
    out = ROOT/"assets/ui/survival"
    out.mkdir(exist_ok=True)
    catalogue = load_catalogue(ROOT/"assets/dungeons.json")
    expected = {(m.category, m.name, m.location) for m in catalogue}
    found = {}
    for folder in args.sources:
        for sidecar in sorted(folder.glob("*catalogue_*.json")):
            data = json.loads(sidecar.read_text("utf-8"))
            category = data["category"]
            scene = Scene([Token(t["text"], t["score"], tuple(t["box"])) for t in data["tokens"]])
            path = sidecar.with_suffix(".png")
            for mission, button in guide_rows(scene, category):
                key = mission.category, mission.name, mission.location
                if key not in expected or key in found:
                    continue
                cy = round(button.center[1]*1080)
                box = [704, cy-116, 860, cy+60] if category == "echo_of_war" else [704, cy-66, 860, cy+64]
                # The whole static icon must remain inside the guide list.
                if box[1] < 288 or box[3] > 885:
                    continue
                filename = hashlib.sha256("|".join(key).encode()).hexdigest()[:16]+".png"
                with Image.open(path) as source:
                    source.convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS).crop(box).save(out/filename)
                found[key] = dict(category=key[0], name=key[1], location=key[2], file=filename,
                    source=folder.name+"/"+path.name, source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                    baseline=[1920, 1080], crop=box,
                    transform="Static reward or boss medallion crop; no labels, counters, player portraits or account data",
                    sha256=hashlib.sha256((out/filename).read_bytes()).hexdigest())
    manifest = dict(client="CN 4.6.0", source_date="2026-10-20", prepared_at="2026-10-29",
        rights="HoYoverse game artwork; not relicensed under source-code GPL",
        assets=[found[k] for k in sorted(found)])
    (out/"sources.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(dict(extracted=len(found), missing=[k for k in sorted(expected-found.keys())]), ensure_ascii=False))


if __name__ == "__main__":
    main()
