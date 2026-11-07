"""Draw the original AutoHSR book-and-orbit Windows icon."""

from pathlib import Path

from PIL import Image, ImageDraw


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
    draw_icon().save(target, sizes=[(size, size) for size in (16, 20, 24, 32, 48, 64, 128, 256)])
