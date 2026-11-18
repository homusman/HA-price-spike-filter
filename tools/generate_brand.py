"""Regenerate the integration's chart icon using Pillow."""

from pathlib import Path

from PIL import Image, ImageDraw

destination = Path("custom_components/price_spike_filter/brand")
destination.mkdir(exist_ok=True)
for size, filename in ((256, "icon.png"), (512, "icon@2x.png")):
    scale = size * 4 / 256
    image = Image.new("RGBA", (size * 4, size * 4))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (12 * scale, 12 * scale, 244 * scale, 244 * scale),
        radius=44 * scale,
        fill="#16324f",
    )
    for points, color, width in (
        ([(34, 162), (74, 158), (102, 160), (130, 52), (154, 160), (222, 158)], "#ffa64d", 8),
        ([(34, 182), (74, 178), (112, 170), (142, 168), (180, 176), (222, 172)], "#52e0ca", 11),
    ):
        draw.line([(x * scale, y * scale) for x, y in points], fill=color, width=round(width * scale), joint="curve")
    image.resize((size, size), Image.Resampling.LANCZOS).save(destination / filename)
