#!/usr/bin/env python3
"""
Build the TALOS icon set.

The mark is a knight (Lucas Chess is a chess school, and the knight is its
signature piece) whose body is made of **square tiles** — the light and dark
land tiles of Anarchess.  One silhouette, two games.

Everything is drawn here: no external art, nothing to download, and every size
from 1024 down to 16 is regenerated from the same source.

    python tools/make_icon.py

Writes into assets/:

    talos.svg                 master vector (scales to anything)
    talos-1024.png            master raster
    talos-{512,256,192,180,128,96,64,48,32,16}.png
    talos-maskable-512.png    Android / PWA adaptive icon (safe zone padded)
    talos-maskable-192.png
    favicon.ico               multi-size Windows icon
    apple-touch-icon.png      180, for iOS home screens
"""

from __future__ import annotations

import math
import os
import subprocess

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")
FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    "/Library/Fonts/Arial Unicode.ttf",
    "C:/Windows/Fonts/seguisym.ttf",
    "C:/Windows/Fonts/arial.ttf",
)

# the TALOS midnight palette
NAVY = (14, 16, 21, 255)
NAVY_2 = (26, 30, 41, 255)
PARCHMENT = (242, 237, 225, 255)
WALNUT = (141, 106, 72, 255)
AMBER = (240, 180, 41, 255)
SHADOW = (0, 0, 0, 120)

SIZES = (1024, 512, 256, 192, 180, 128, 96, 64, 48, 32, 16)
GRID = 13                 # tiles across the knight
SUPERSAMPLE = 4


# --------------------------------------------------------------------------
# the knight
# --------------------------------------------------------------------------
def knight_mask(size: int) -> Image.Image:
    """A crisp knight silhouette, as an 8-bit mask."""
    font_path = next((p for p in FONT_CANDIDATES if os.path.exists(p)), None)
    if font_path is None:
        raise SystemExit("no font with chess glyphs found")
    scale = size * SUPERSAMPLE
    font = ImageFont.truetype(font_path, int(scale * 1.02))
    image = Image.new("L", (scale, scale), 0)
    draw = ImageDraw.Draw(image)
    glyph = "\u265E"                     # black chess knight
    box = draw.textbbox((0, 0), glyph, font=font)
    draw.text((-box[0], -box[1]), glyph, font=font, fill=255)
    bbox = image.getbbox()
    if bbox is None:
        raise SystemExit("the font did not draw a knight")
    image = image.crop(bbox)
    # pad to a square so the tile grid stays square
    w, h = image.size
    side = max(w, h)
    square = Image.new("L", (side, side), 0)
    square.paste(image, ((side - w) // 2, (side - h) // 2))
    return square.resize((size, size), Image.LANCZOS)


def tile_grid(mask: Image.Image, size: int, cells: int = GRID) -> Image.Image:
    """Fill the silhouette with square land tiles (the Anarchess motif)."""
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)
    step = size / cells
    gap = step * 0.10
    pixels = mask.load()
    for row in range(cells):
        for col in range(cells):
            x0 = col * step
            y0 = row * step
            cx = min(size - 1, int(x0 + step / 2))
            cy = min(size - 1, int(y0 + step / 2))
            if pixels[cx, cy] < 128:
                continue
            # a light tile, a dark tile: the two colours of the land
            colour = PARCHMENT if (row + col) % 2 == 0 else WALNUT
            inset = gap
            radius = step * 0.16
            draw.rounded_rectangle(
                [x0 + inset, y0 + inset, x0 + step - inset, y0 + step - inset],
                radius=radius, fill=colour)
    return out


def amber_glow(tiles: Image.Image, blur: float) -> Image.Image:
    """An amber halo behind the tiles so the mark reads on dark backgrounds."""
    alpha = tiles.split()[-1]
    grown = alpha.filter(ImageFilter.MaxFilter(5))
    glow = Image.new("RGBA", tiles.size, AMBER)
    glow.putalpha(grown.point(lambda v: int(v * 0.55)))
    return glow.filter(ImageFilter.GaussianBlur(blur))


def compose(size: int, maskable: bool = False) -> Image.Image:
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pad = int(size * 0.15) if maskable else 0
    inner = size - pad * 2

    # rounded-square plate with a vertical gradient
    plate = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    plate_draw = ImageDraw.Draw(plate)
    for y in range(size):
        t = y / max(1, size - 1)
        colour = tuple(int(NAVY[i] + (NAVY_2[i] - NAVY[i]) * t) for i in range(3))
        plate_draw.line([(0, y), (size, y)], fill=colour + (255,))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * 0.235), fill=255)
    canvas.paste(plate, (0, 0), mask)

    # a thin amber rim, inset
    rim = ImageDraw.Draw(canvas)
    rim.rounded_rectangle([size * 0.045, size * 0.045,
                           size * 0.955, size * 0.955],
                          radius=int(size * 0.20),
                          outline=AMBER[:3] + (int(150 if maskable else 210),),
                          width=max(1, int(size * 0.014)))

    # the knight, made of tiles.  The glyph is taller than it is wide, so the
    # mark is trimmed to its own bounds and normalised: the longest side is a
    # fixed fraction of the plate and the margins come out even.
    knight = int(inner * 0.92)
    mask_img = knight_mask(knight)
    tiles = tile_grid(mask_img, knight)
    tiles = tiles.crop(tiles.getbbox())
    scale = (inner * (0.86 if maskable else 0.72)) / max(tiles.size)
    tiles = tiles.resize((max(1, int(tiles.width * scale)),
                          max(1, int(tiles.height * scale))), Image.LANCZOS)
    blur = max(1.0, tiles.width * 0.035)
    glow = amber_glow(tiles, blur)

    # drop shadow
    shadow = Image.new("RGBA", tiles.size, (0, 0, 0, 0))
    shadow.paste(tiles.split()[-1].point(lambda v: int(v * 0.55)),
                 (0, int(tiles.height * 0.045)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(blur))

    x = (size - tiles.width) // 2
    y = (size - tiles.height) // 2
    canvas.alpha_composite(glow, (x, y))
    canvas.alpha_composite(shadow, (x, y))
    canvas.alpha_composite(tiles, (x, y))
    return canvas


def write_svg(path: str) -> None:
    """The same mark as vectors: a 13x13 tile grid cut to the knight."""
    mask = knight_mask(GRID)
    pixels = mask.load()
    rects = []
    for row in range(GRID):
        for col in range(GRID):
            if pixels[col, row] >= 128:
                fill = "#f2ede1" if (row + col) % 2 == 0 else "#8d6a48"
                rects.append(
                    f'<rect x="{col + 0.10:.2f}" y="{row + 0.10:.2f}" '
                    f'width="0.80" height="0.80" rx="0.13" fill="{fill}"/>')
    body = "\n    ".join(rects)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 13 13"
     width="512" height="512" role="img" aria-label="TALOS">
  <title>TALOS - The Living Chess Studio</title>
  <defs>
    <linearGradient id="plate" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#0e1015"/>
      <stop offset="1" stop-color="#1a1e29"/>
    </linearGradient>
  </defs>
  <rect width="13" height="13" rx="3.05" fill="url(#plate)"/>
  <rect x="0.58" y="0.58" width="11.84" height="11.84" rx="2.6"
        fill="none" stroke="#f0b429" stroke-opacity="0.82" stroke-width="0.18"/>
  <g>
    {body}
  </g>
</svg>
'''
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(svg)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    write_svg(os.path.join(OUT, "talos.svg"))

    master = compose(1024)
    master.save(os.path.join(OUT, "talos-1024.png"))
    for size in SIZES:
        if size == 1024:
            continue
        master.resize((size, size), Image.LANCZOS).save(
            os.path.join(OUT, f"talos-{size}.png"))

    for size in (512, 192):
        compose(size, maskable=True).save(
            os.path.join(OUT, f"talos-maskable-{size}.png"))

    master.resize((180, 180), Image.LANCZOS).save(
        os.path.join(OUT, "apple-touch-icon.png"))

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                 (128, 128), (256, 256)]
    master.save(os.path.join(OUT, "favicon.ico"), sizes=ico_sizes)

    # a bare 512 png is what the Linux .desktop file points at
    master.resize((512, 512), Image.LANCZOS).save(
        os.path.join(OUT, "talos.png"))

    # sanity: the mark must actually cover a sensible part of the plate
    alpha = master.split()[-1]
    opaque = sum(alpha.histogram()[201:])
    print(f"plate coverage: {opaque / (1024 * 1024) * 100:.1f}% of the square")
    print("wrote", len(os.listdir(OUT)), "files to", OUT)
    try:
        subprocess.run(["python", "-c", "import PIL; print('pillow ok')"],
                       check=False)
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
