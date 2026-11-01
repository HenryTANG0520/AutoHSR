"""Prepare static guide scenery and the close glyph from the known local frame."""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SOURCE_SHA256 = "6ba21f7ad3417d8bebb0224849221b59b674030e1e964c49e34f676176d28e11"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--daily", type=Path, required=True)
    args = parser.parse_args()
    raw = args.daily.read_bytes()
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA256:
        raise ValueError("The supplied frame does not match the reviewed reference")
    source = Image.open(args.daily).convert("RGB").resize((1920, 1080), Image.Resampling.LANCZOS)
    pixels = np.asarray(source)
    # All foreground UI, including the entire bottom HUD strip, is excluded.
    # The hidden middle is interpolated, not claimed as original world pixels.
    regions = [(22, 24, 282, 120), (1816, 24, 1906, 114),
               (140, 140, 1826, 1008), (0, 1008, 1920, 1080)]
    mask = np.zeros((1080, 1920), dtype="uint8")
    for x1, y1, x2, y2 in regions:
        mask[y1:y2, x1:x2] = 255
    small = cv2.resize(pixels, (240, 135), interpolation=cv2.INTER_AREA)
    small_mask = cv2.resize(mask, (240, 135), interpolation=cv2.INTER_AREA)
    small_mask = (small_mask > 0).astype("uint8")*255
    filled = cv2.inpaint(small, small_mask, 3, cv2.INPAINT_TELEA)
    filled = cv2.resize(filled, (1920, 1080), interpolation=cv2.INTER_CUBIC)
    # Feather only inside the padded mask; outside pixels stay unchanged.
    blend = np.clip(cv2.distanceTransform(mask, cv2.DIST_L2, 3)/8, 0, 1)[:, :, None]
    backdrop = np.rint(pixels*(1-blend)+filled*blend).astype("uint8")
    out = ROOT/"assets/ui/guide"
    out.mkdir(exist_ok=True)
    Image.fromarray(backdrop).save(out/"backdrop.png")
    crop = [1838, 43, 1884, 89]
    close = np.asarray(source.crop(crop)).mean(axis=2)
    glyph = Image.new("RGBA", (46, 46), "white")
    glyph.putalpha(Image.fromarray(np.clip((close-40)/215*255, 0, 255).astype("uint8")))
    glyph.save(out/"close.png")
    common = dict(source="local Star Rail 4.6.0 daily reference", source_sha256=SOURCE_SHA256,
                  baseline=[1920, 1080], rights="HoYoverse game artwork; not relicensed under source-code GPL")
    assets = {
        "backdrop.png": dict(common, excluded_rectangles=regions,
            transform="Visible background retained; foreground mask interpolated at 240x135 with 3px Telea, bicubic upsampled, then feathered 8px inside the padded mask; masked pixels are reconstruction, not original scenery"),
        "close.png": dict(common, crop=crop,
            transform="White static glyph extracted by luminance alpha; dark background removed"),
    }
    for name, record in assets.items():
        record["sha256"] = hashlib.sha256((out/name).read_bytes()).hexdigest()
    (out/"sources.json").write_text(json.dumps(dict(date="2026-10-29", assets=assets), ensure_ascii=False, indent=2)+"\n", "utf-8")
    print(json.dumps(dict(assets=list(assets), source_sha256=SOURCE_SHA256)))


if __name__ == "__main__":
    main()
