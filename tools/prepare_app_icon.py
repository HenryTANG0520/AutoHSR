"""Draw the original AutoHSR book-and-orbit Windows icon."""

from pathlib import Path

from PIL import Image, ImageDraw


def draw_small_icon(size):
    """Align small icon artwork to the target pixel grid."""
    image = Image.new("RGBA", (size, size))
    draw = ImageDraw.Draw(image)
    ink, gold, star = "#131629", "#FFDC91", "#FFF7E1"

    def scaled(point):
        return tuple(round(value * (size - 1) / 15) for value in point)

    draw.rounded_rectangle((*scaled((0, 0)), *scaled((15, 15))),
                           radius=round(size * .22), fill=ink)
    stroke = max(2, round(size / 9))
    draw.rectangle((*scaled((3, 2)), *scaled((13, 12))), outline=gold, width=stroke)
    draw.polygon([scaled(point) for point in ((8, 5), (9, 7), (10, 7), (9, 8),
                                               (8, 10), (7, 8), (6, 7), (7, 7))], fill=star)
    draw.line([scaled(point) for point in ((2, 10), (2, 12), (4, 13), (8, 12), (13, 9), (14, 7))],
              fill=gold, width=max(1, round(size / 14)), joint="curve")
    return image


def draw_icon():
    unit = 8
    image = Image.new("RGBA", (128 * unit, 128 * unit))
    draw = ImageDraw.Draw(image)

    def bounds(values):
        return tuple(round(value * unit) for value in values)

    def path(points, color, width):
        draw.line([bounds(point) for point in points], fill=color, width=width * unit, joint="curve")

    ink, edge, gold, star = "#16192F", "#333752", "#E5C47E", "#FFF0C2"
    draw.rounded_rectangle(bounds((6, 6, 122, 122)), radius=26 * unit, fill=ink, outline=edge, width=4 * unit)
    path(((43, 28), (34, 38), (34, 90), (43, 100), (90, 100), (90, 29), (43, 29)), gold, 7)
    path(((45, 30), (45, 83), (88, 83)), gold, 5)
    draw.polygon([bounds(point) for point in
                  ((66, 40), (70, 52), (83, 57), (70, 61), (66, 75), (62, 61), (49, 57), (62, 52))], fill=star)

    orbit = Image.new("RGBA", image.size)
    orbit_draw = ImageDraw.Draw(orbit)
    orbit_draw.arc(bounds((13, 50, 115, 90)), start=15, end=205, fill=gold, width=6 * unit)
    image.alpha_composite(orbit.rotate(27, resample=Image.Resampling.BICUBIC))
    return image.resize((256, 256), Image.Resampling.LANCZOS)


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "assets" / "ui" / "autohsr.ico"
    source = draw_icon()
    small = [draw_small_icon(size) for size in (16, 20, 24, 32)]
    large = [source.resize((size, size), Image.Resampling.LANCZOS) for size in (48, 64, 128)]
    frames = [*small, *large, source]
    source.save(target, sizes=[frame.size for frame in frames], append_images=frames[:-1])
