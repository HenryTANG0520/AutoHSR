"""Extract guide illustrations; discard every cached account/season/result field."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
CROP = (692, 289, 1658, 928)
# Coordinates are relative to the 966 x 639 poster, after 1920 x 1080 normalization.
# Whole widgets are removed, except the centre digits whose isolated components
# are removed without destroying the surrounding medal outline.
MASKS = {
    "du": [(0, 51, 245, 113), (744, 56, 941, 94), (599, 101, 940, 134), (685, 139, 940, 204),
           (56, 347, 370, 387), (416, 369, 950, 518), (576, 555, 949, 625)],
    "cw": [(0, 0, 966, 40), (654, 53, 940, 96), (646, 101, 940, 135), (659, 156, 940, 203),
           (57, 264, 382, 313), (70, 320, 369, 353), (423, 257, 940, 366),
           (417, 372, 950, 518), (656, 557, 945, 621)],
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--du", type=Path, required=True)
    parser.add_argument("--cw", type=Path, required=True)
    args = parser.parse_args()
    out = ROOT / "assets/ui/universe"
    out.mkdir(parents=True, exist_ok=True)
    assets = []
    for key in MASKS:
        source = getattr(args, key)
        with Image.open(source) as frame:
            poster = frame.convert("RGBA").resize((1920, 1080), Image.Resampling.LANCZOS).crop(CROP)
        mask = Image.new("L", poster.size)
        draw = ImageDraw.Draw(mask)
        for box in MASKS[key]:
            draw.rectangle(box, fill=255)
        # Extend neighbouring illustration colours into removed widgets. The
        # missing artwork is not claimed to be a pixel-exact original texture.
        rgb = np.asarray(poster.convert("RGB"))
        digit_box = (160, 204, 270, 278) if key == "du" else (134, 170, 312, 256)
        x1, y1, x2, y2 = digit_box
        pixels = rgb[y1:y2, x1:x2]
        bright = (np.min(pixels[:, :, :2], axis=2) > 190) if key == "du" else (np.min(pixels, axis=2) > 185)
        _, labels, stats, _ = cv2.connectedComponentsWithStats(bright.astype("uint8"))
        digits = np.zeros(bright.shape, "uint8")
        found = 0
        for index, (x, y, w, h, area) in enumerate(stats[1:], 1):
            if x > 0 and y > 0 and x+w < x2-x1 and y+h < y2-y1 and area > 500:
                digits[labels == index] = 255
                found += 1
        if found != (2 if key == "du" else 3):
            raise ValueError("The supplied reference does not match the recorded digit masks")
        mask_array = np.array(mask)
        mask_array[y1:y2, x1:x2] |= cv2.dilate(digits, np.ones((5, 5), "uint8"))
        poster = Image.fromarray(cv2.inpaint(rgb, mask_array, 7, cv2.INPAINT_TELEA))
        target = out / f"{key}.png"
        poster.save(target)
        assets.append(dict(file=target.name, source="local Star Rail CN 4.6.0 guide reference",
            source_date="2026-10-24" if key == "du" else "2026-10-26",
            source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(), baseline=[1920, 1080],
            crop=CROP, removed_regions=MASKS[key],
            digit_region=digit_box, digit_components=found, digit_mask="bright enclosed components; 5x5 dilation",
            transform="Lanczos normalization; static illustration crop; complete account, season, reward and action widgets removed with local OpenCV Telea colour extension (radius 7); reconstructed regions are not original pixels; no generative model",
            sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
            rights="HoYoverse game artwork; not relicensed under source-code GPL"))
    (out / "sources.json").write_text(json.dumps(dict(assets=assets), ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
