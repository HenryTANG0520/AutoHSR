"""Draw the original AutoHSR book-and-orbit Windows icon."""

from pathlib import Path

from PIL import Image, ImageDraw


def draw_icon(size=256):
    unit = 8
    small = size <= 32
    pixel = 128 / size
    image = Image.new("RGBA", (128 * unit, 128 * unit))
    draw = ImageDraw.Draw(image)

    def bounds(values):
        return tuple(round(value * unit) for value in values)

    def path(points, color, width):
        if small:
            # Give the original cover and spine one solid row or column.
            # The orbit and star retain their curved and diagonal edges.
            stroke = max(1, round(width / pixel))
            center = .5 if stroke % 2 else 0
            points = [tuple((round(value / pixel - center) + center) * pixel for value in point)
                      for point in points]
            width = stroke * pixel
        draw.line([bounds(point) for point in points], fill=color, width=round(width * unit), joint="curve")

    ink, edge, gold, star = "#16192F", "#333752", "#E5C47E", "#FFF0C2"
    if small:
        gold = "#EED08B"
    draw.rounded_rectangle(bounds((6, 6, 122, 122)), radius=26 * unit, fill=ink, outline=edge, width=4 * unit)
    path(((43, 28), (34, 38), (34, 90), (43, 100), (90, 100), (90, 29), (43, 29)), gold, 7)
    path(((45, 30), (45, 83), (88, 83)), gold, 5)
    draw.polygon([bounds(point) for point in
                  ((66, 40), (70, 52), (83, 57), (70, 61), (66, 75), (62, 61), (49, 57), (62, 52))], fill=star)

    orbit = Image.new("RGBA", image.size)
    orbit_draw = ImageDraw.Draw(orbit)
    orbit_width = max(6, pixel * .95) if small else 6
    orbit_draw.arc(bounds((13, 50, 115, 90)), start=15, end=205, fill=gold, width=round(orbit_width * unit))
    image.alpha_composite(orbit.rotate(27, resample=Image.Resampling.BICUBIC))
    resample = Image.Resampling.BOX if small else Image.Resampling.LANCZOS
    return image.resize((size, size), resample)


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "assets" / "ui" / "autohsr.ico"
    source = draw_icon()
    small = [draw_icon(size) for size in (16, 20, 24, 32)]
    large = [source.resize((size, size), Image.Resampling.LANCZOS) for size in (48, 64, 128)]
    frames = [*small, *large, source]
    source.save(target, sizes=[frame.size for frame in frames], append_images=frames[:-1])
