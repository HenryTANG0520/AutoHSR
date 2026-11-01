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


def card_frame(daily):
    """Keep the paper trim; discard every source task/status/reward pixel."""
    box = (278, 404, 566, 776)
    pixels = np.asarray(daily.crop(box).convert("RGB")).copy()
    alpha = np.full(pixels.shape[:2], 255, dtype="uint8")
    # Only the outer edge needs a matte. The gold dotted border and pale map
    # inside it retain their original color, including their antialiasing.
    edge = np.zeros(alpha.shape, dtype=bool)
    edge[:8] = True
    edge[:, :3] = edge[:, -3:] = True
    edge[-6:] = True
    background = np.full(alpha.shape, 225.)
    background[-6:] = 135.  # Shadow at the perforated paper/footer seam.
    coverage = np.clip((pixels.min(2)-background)/(246-background), 0, 1)
    alpha[edge] = np.rint(coverage[edge]*255).astype("uint8")
    # Clear RGB too: hidden source labels must not remain in transparent PNGs.
    for left, top, right, bottom in ((0, 12, 163, 49), (16, 65, 271, 352)):
        alpha[top:bottom, left:right] = 0
        pixels[top:bottom, left:right] = 0
    pixels[alpha == 0] = 0
    frame = Image.fromarray(np.dstack((pixels, alpha)), "RGBA")
    return "card-frame.png", frame, "daily", box, (
        "static paper map, dotted border and perforated trim; outer 3px sides/"
        "8px top/6px bottom luminance matte; status [0,12,163,49] and content "
        "[16,65,271,352] cleared in RGBA; source task, counters and rewards excluded")


def guide_details(frames):
    """Use unobstructed static regions, retaining antialiasing and icon color."""
    for name, source, box in (
        ("tab-daily.png", "universe", (336, 184, 393, 240)),
        ("tab-survival.png", "daily", (454, 184, 510, 240)),
        ("tab-universe.png", "daily", (569, 186, 632, 238)),
    ):
        crop = frames[source].crop(box)
        gray = np.asarray(crop).mean(axis=2)
        # Unselected tabs have a neutral dark background and light glyph.
        # In particular, the selected daily reference contains a mouse cursor.
        background = np.median(np.concatenate((gray[0], gray[-1], gray[:, 0], gray[:, -1])))
        # Resizing can undershoot the dark surround or overshoot the light ink;
        # use the surround and dominant ink instead of those ringing extremes.
        ink = np.bincount(np.rint(gray[gray > 100]).astype(int)).argmax()
        alpha = np.clip((gray-background)/(ink-background), 0, 1)
        glyph = Image.new("RGBA", crop.size, "white")
        glyph.putalpha(Image.fromarray(np.rint(alpha*255).astype("uint8")))
        yield name, glyph, source, box, "unselected static glyph without cursor; continuous alpha from neutral background and ink; recolored at render time"

    # The task-card emblem has a flat surround; the meter emblem is over spokes.
    # Preserve its gold gradient and opaque white inner rings, not just gold pixels.
    import cv2
    box = (332, 665, 396, 755)
    pixels = np.asarray(frames["daily"].crop(box)).astype(float)
    background = np.median(pixels[:, (0, 1, -2, -1)], axis=1)
    chroma = pixels[:, :, 0]-pixels[:, :, 2]
    ink = np.full((pixels.shape[0], 3), np.nan)
    for row in range(pixels.shape[0]):
        if chroma[row].max() > 20:
            ink[row] = np.median(pixels[row, chroma[row] >= chroma[row].max()*.9], axis=0)
    present = np.flatnonzero(np.isfinite(ink[:, 0]))
    for channel in range(3):
        ink[:, channel] = np.interp(np.arange(len(ink)), present, ink[present, channel])
    delta = ink-background
    alpha = np.clip(((pixels-background[:, None, :])*delta[:, None, :]).sum(2)/(delta*delta).sum(1)[:, None], 0, 1)
    contours, _ = cv2.findContours((alpha > .1).astype("uint8"), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    silhouette = np.zeros(alpha.shape, dtype="uint8")
    cv2.drawContours(silhouette, [max(contours, key=cv2.contourArea)], -1, 1, cv2.FILLED)
    interior = cv2.erode(silhouette, np.ones((3, 3), dtype="uint8"))
    alpha[interior.astype(bool)] = 1
    rgb = np.clip((pixels-(1-alpha[:, :, None])*background[:, None, :])/np.maximum(alpha[:, :, None], .001), 0, 255)
    emblem = Image.fromarray(np.rint(np.dstack((rgb, alpha*255))).astype("uint8"), "RGBA")
    yield "activity.png", emblem, "daily", box, "static task-card emblem without radial backdrop, text or numbers; continuous edge alpha with background removed, gold gradient and opaque white inner rings retained"

    # The fourth title is one line, leaving this motif region unobstructed.
    # Reject the gold emblem entering its bottom-left corner and any dark ink.
    box = (1318, 510, 1530, 679)
    crop = frames["daily"].crop(box)
    pixels = np.asarray(crop).astype(float)
    gray = pixels.mean(2)
    alpha = np.where((gray > 235) & (pixels.max(2)-pixels.min(2) <= 6), 255-pixels.min(2), 0)
    rgb = np.clip(255+(pixels-255)*255/np.maximum(alpha[:, :, None], 1), 0, 255)
    watermark = Image.fromarray(np.rint(np.dstack((rgb, alpha))).astype("uint8"), "RGBA")
    yield "card-watermark.png", watermark, "daily", box, "static motif below fourth card title; warm tint and continuous alpha over white, gold emblem and dark ink excluded; native aspect retained at render time"


def paper_pattern(frame):
    """Retain the visible full-width star chart, without the live reset timer."""
    box = (236, 892, 1694, 964)
    pixels = np.array(frame.crop(box).convert("RGB"))
    # Paper and timer ink are neutral; the static chart is warm gold. Remove
    # the neutral surround with continuous alpha, retaining the source color
    # when composited on the same #e1e1e1 paper without opaque edge halos.
    channels = pixels.astype(float)
    chroma = channels[:, :, 0] - channels[:, :, 2]
    visible = (chroma > 0) & (channels.min(2) > 160)
    # Exclude the complete timer and hanging ornament, including their edges.
    visible[10:58, 1090:1430] = False
    visible[:, 1402:] = False
    alpha = np.clip(np.maximum(chroma/40, np.maximum((225-channels.min(2))/225,
                    (channels.max(2)-225)/30)), 0, 1)
    alpha[~visible] = 0
    rgb = np.clip(225+(channels-225)/np.maximum(alpha[:, :, None], .001), 0, 255)
    rgb[~visible] = 0
    image = Image.fromarray(np.rint(np.dstack((rgb, alpha*255))).astype("uint8"))
    return "paper-pattern.png", image, "daily", box, (
        "full-width visible bottom star-chart strip; continuous warm-chroma alpha "
        "with neutral paper removed and source color recovered over #e1e1e1; neutral ink excluded; timer "
        "[1326,902,1666,950] and ornament x>=1638 cleared in RGBA; no reconstruction")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", type=Path, required=True)
    for name in ("guide", "universe", "font"):
        parser.add_argument("--"+name, type=Path)
    parser.add_argument("--paper-only", action="store_true", help="Update only the existing daily-reference paper strip and its manifest")
    args = parser.parse_args()
    if not args.paper_only and any(getattr(args, name) is None for name in ("guide", "universe", "font")):
        parser.error("--guide, --universe and --font are required unless --paper-only is used")
    out = ROOT/"assets"/"ui"
    out.mkdir(exist_ok=True)
    frames = {name: Image.open(getattr(args, name)).convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
              for name in (("daily",) if args.paper_only else ("daily", "guide", "universe"))}
    hashes = {name: hashlib.sha256(getattr(args, name).read_bytes()).hexdigest() for name in frames}
    sources = {}

    def save(name, im, source, box, method):
        im.save(out/name)
        sources[name] = dict(source="local Star Rail 4.6.0 "+source+" reference", source_sha256=hashes[source],
                             baseline=[1920, 1080], crop=box, transform=method,
                             sha256=hashlib.sha256((out/name).read_bytes()).hexdigest(),
                             rights="HoYoverse game artwork; not relicensed under source-code GPL")

    if args.paper_only:
        manifest = json.loads((out/"sources.json").read_text("utf-8"))
        if hashes["daily"] != manifest["assets"]["paper-pattern.png"]["source_sha256"]:
            parser.error("The daily reference hash differs from the recorded paper source")
        save(*paper_pattern(frames["daily"]))
        manifest["assets"].update(sources)
        manifest["updated"] = "2026-10-29"
        (out/"sources.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n", "utf-8")
        print("Prepared the recorded paper strip only; other assets unchanged.")
        return

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
    save(*card_frame(frames["daily"]))
    for name, im, source, box, method in guide_details(frames):
        save(name, im, source, box, method)
    glyph("tab-records.png", "daily", (690, 187, 750, 239), "light")
    glyph("tab-settings.png", "daily", (809, 184, 868, 241), "light")
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

    save(*paper_pattern(frames["daily"]))

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
    (out/"sources.json").write_text(json.dumps(dict(date="2026-10-28", updated="2026-10-29", assets=sources), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    print(f"Prepared {len(sources)} static assets; no full screenshots or account fields copied.")


if __name__ == "__main__":
    main()
