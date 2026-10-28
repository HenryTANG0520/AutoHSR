"""Extract static guide artwork from supplied local references, never account data.

Coordinates use a 1920x1080 reference plane. Source frames are never bundled.
The font is copied byte-for-byte with its name/copyright/licensing table intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    for name in ("daily", "guide", "universe", "font"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    out = ROOT/"assets"/"ui"
    out.mkdir(exist_ok=True)
    frames = {name: Image.open(getattr(args, name)).convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
              for name in ("daily", "guide", "universe")}
    hashes = {name: hashlib.sha256(getattr(args, name).read_bytes()).hexdigest() for name in frames}
    sources = {}

    def save(name, im, source, box, method):
        im.save(out/name)
        sources[name] = dict(source="local Star Rail 4.6.0 "+source+" reference", source_sha256=hashes[source],
                             baseline=[1920, 1080], crop=box, transform=method,
                             sha256=hashlib.sha256((out/name).read_bytes()).hexdigest(),
                             rights="HoYoverse game artwork; not relicensed under source-code GPL")

    def glyph(name, source, box, kind="dark"):
        crop = frames[source].crop(box)
        a = np.asarray(crop).astype(float)
        gray = a.mean(axis=2)
        if kind == "dark":
            alpha = np.clip((160-gray)/80, 0, 1)*255
        elif kind == "light":
            alpha = np.clip((gray-65)/100, 0, 1)*255
        else:
            alpha = np.where((a[:,:,0]>120)&(a[:,:,1]>105)&(a[:,:,2]<a[:,:,0]*.85), 255, 0)
        rgba = Image.new("RGBA", crop.size, "white")
        rgba.putalpha(Image.fromarray(alpha.astype("uint8")))
        save(name, rgba, source, box, "static glyph alpha mask; recolored at render time")

    glyph("guide-mark.png", "daily", (43, 42, 94, 89), "gold")
    glyph("tab-daily.png", "daily", (336, 184, 393, 240))
    glyph("tab-survival.png", "guide", (454, 184, 510, 240))
    glyph("tab-universe.png", "universe", (569, 186, 632, 238))
    glyph("tab-records.png", "daily", (690, 187, 750, 239), "light")
    glyph("tab-settings.png", "daily", (809, 184, 868, 241), "light")
    glyph("activity.png", "daily", (322, 268, 369, 341), "gold")
    glyph("reward-check.png", "daily", (608, 278, 669, 339), "gold")
    glyph("guide-seal.png", "daily", (1614, 182, 1676, 234), "gold")

    box = (278, 776, 566, 880)
    crop = frames["daily"].crop(box)
    a = np.asarray(crop)
    # Separate the bright action text from the dark, low-contrast map artwork.
    # The source's action label must never appear underneath live app labels.
    import cv2
    mask = ((a[:,:,0]>135)&(a[:,:,1]>105)).astype("uint8")*255
    mask[:23] = 0
    mask[78:] = 0
    mask = cv2.dilate(mask, np.ones((5,5), dtype="uint8"))
    clean = cv2.inpaint(a, mask, 5, cv2.INPAINT_TELEA)
    save("card-footer.png", Image.fromarray(clean), "daily", box,
         "static footer texture; bright action-label color mask, 2px mask dilation and 5px Telea inpainting; live label rendered separately")

    box = (236, 892, 565, 964)
    crop = frames["daily"].crop(box)
    a = np.asarray(crop).astype(float)
    alpha = np.clip((224-a.mean(axis=2))*6,0,100).astype("uint8")
    paper = Image.new("RGBA", crop.size, "#c9c5b6")
    paper.putalpha(Image.fromarray(alpha))
    save("paper-pattern.png", paper, "daily", box, "static paper map texture luminance matte; no labels or counters")

    # The watermark is a static low-contrast motif. Black task text and gold
    # progress numerals are outside this crop or rejected by the matte.
    box = (317, 531, 521, 668)
    crop = frames["daily"].crop(box)
    a = np.asarray(crop).astype(float)
    gray = a.mean(axis=2)
    alpha = np.where(gray > 218, np.clip((253-gray)*5, 0, 110), 0).astype("uint8")
    im = Image.new("RGBA", crop.size, "#d7d7d7")
    im.putalpha(Image.fromarray(alpha))
    save("card-watermark.png", im, "daily", box, "static watermark luminance matte; text excluded")

    # Hand-traced outlines isolate the two ornaments from the blurred world.
    for name, box, points in (
        ("guide-charm-left.png", (152, 282, 267, 505),
         [(66,1),(72,6),(81,30),(91,62),(94,76),(101,88),(95,97),(98,111),(90,124),(102,136),(108,151),(112,161),(109,179),(99,187),(83,191),(80,205),(70,218),(51,220),(37,211),(30,195),(28,188),(16,188),(6,180),(2,169),(4,156),(14,146),(29,141),(31,129),(42,117),(34,109),(36,99),(30,90),(39,78),(46,57),(54,27)]),
    ):
        crop = frames["daily"].crop(box).convert("RGBA")
        mask = Image.new("L", crop.size)
        ImageDraw.Draw(mask).polygon(points, fill=255)
        crop.putalpha(mask)
        save(name, crop, "daily", box, "static ornament polygon matte; no account, text or counters")

    box = (1638, 650, 1814, 944)
    crop = frames["daily"].crop(box).convert("RGBA")
    mask = Image.new("L", crop.size)
    draw = ImageDraw.Draw(mask)
    outlines = [
        [(70,2),(90,11),(100,9),(110,19),(115,31),(129,52),(140,63),(148,78),(151,92),(149,102),(120,103),(105,96),(97,93),(70,93)],
        [(70,119),(69,114),(72,108),(79,104),(88,101),(97,103),(104,102),(112,105),(119,110),(122,119),(130,119),(139,123),(144,129),(149,139),(150,144),(152,153),(149,164),(144,169),(141,170),(141,176),(144,184),(140,193),(132,198),(123,201),(119,202),(115,207),(106,211),(97,211),(92,207),(87,211),(76,211),(67,207),(62,201),(57,199),(52,194),(48,190),(47,183),(47,178),(49,170),(43,168),(40,162),(39,153),(40,144),(43,139),(44,133),(48,127),(54,122),(60,120)],
        [(150,144),(154,142),(162,139),(160,145),(159,151),(161,157),(166,154),(167,162),(167,167),(164,172),(155,175),(151,175),(147,180),(143,182),(143,177),(148,171),(151,166),(151,158)],
        [(100,209),(104,209),(107,213),(114,210),(122,209),(129,212),(129,216),(124,216),(120,221),(119,229),(115,236),(108,240),(101,240),(98,235),(101,226),(100,219),(94,216),(92,211)],
        [(59,220),(54,216),(48,214),(42,214),(38,216),(35,219),(33,225),(33,229),(28,236),(28,241),(30,249),(34,253),(42,256),(47,256),(45,262),(43,268),(44,274),(48,279),(55,282),(62,282),(68,281),(72,283),(78,282),(83,280),(86,276),(86,271),(84,263),(80,259),(88,259),(94,255),(99,248),(100,242),(98,237),(94,232),(92,226),(88,221),(82,219),(75,219),(70,221),(67,225),(64,226),(63,221)],
    ]
    for points in outlines:
        draw.polygon(points, fill=255)
    crop.putalpha(mask)
    save("guide-charm-right.png", crop, "daily", box, "five separate static ornament and stem polygon mattes; account and world excluded")

    template = ROOT/"assets"/"templates"/"planar_stamina_cost_single.png"
    shutil.copyfile(template, out/"stamina.png")
    sources["stamina.png"] = dict(source="../templates/planar_stamina_cost_single.png", provenance="../templates/planar_stamina_cost_single.json",
        source_sha256=hashlib.sha256(template.read_bytes()).hexdigest(), transform="unmodified static currency icon",
        sha256=hashlib.sha256((out/"stamina.png").read_bytes()).hexdigest(), rights="HoYoverse game artwork; not relicensed under source-code GPL")
    template = ROOT/"assets"/"templates"/"daily_reward.png"
    with Image.open(template) as source:
        crop = source.convert("RGB").crop((18,21,44,52))
    gray = np.asarray(crop).mean(axis=2)
    gift = Image.new("RGBA", crop.size, "white")
    gift.putalpha(Image.fromarray((np.clip((150-gray)/90,0,1)*255).astype("uint8")))
    gift.save(out/"reward-gift.png")
    sources["reward-gift.png"] = dict(source="../templates/daily_reward.png", provenance="../ATTRIBUTION.md#honkai-star-rail---one-dragon",
        source_sha256=hashlib.sha256(template.read_bytes()).hexdigest(), crop=[18,21,44,52], transform="dark gift glyph alpha matte; notification badge excluded",
        sha256=hashlib.sha256((out/"reward-gift.png").read_bytes()).hexdigest(), rights="HoYoverse game artwork; not relicensed under source-code GPL")

    shutil.copyfile(args.font, out/"hsr-sc.ttf")
    sources["hsr-sc.ttf"] = dict(source="local Star Rail 4.6.0 SDK_SC_Web font", transform="unmodified byte-for-byte copy",
        source_sha256=hashlib.sha256(args.font.read_bytes()).hexdigest(),
        sha256=hashlib.sha256((out/"hsr-sc.ttf").read_bytes()).hexdigest(),
        rights="Beijing Hanyi Innovation Technology; original font license and metadata retained")
    (out/"sources.json").write_text(json.dumps(dict(date="2026-10-28", assets=sources), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Prepared {len(sources)} static assets; no full screenshots or account fields copied.")


if __name__ == "__main__":
    main()
