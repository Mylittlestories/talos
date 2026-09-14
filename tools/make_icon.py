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
AMBER_LIGHT = (247, 199, 88, 255)
AMBER_DEEP = (216, 155, 26, 255)
SHADOW = (0, 0, 0, 120)

SIZES = (1024, 512, 256, 192, 180, 128, 96, 64, 48, 32, 16)
GRID = 11                 # tiles across the knight
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


def knight_body(mask: Image.Image, size: int, cells: int = GRID) -> Image.Image:
    """The knight as one solid piece, tiled from the inside.

    The first version built the silhouette out of separate tiles with gaps
    between them. That looked right at 1024 and fell apart by 64: the eye met
    a scatter of squares instead of a knight, and at 16 there was nothing left
    to read. So the silhouette is filled first - a single piece of amber - and
    the land tiles are then laid *into* it in a close second tone, flush, so
    the outline survives at every size and the mosaic only appears where there
    is room for it.
    """
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(AMBER, (0, 0), mask)
    if size >= 96:                       # below this the tiles are noise
        step = size / cells
        draw = ImageDraw.Draw(out)
        pixels = mask.load()
        for row in range(cells):
            for col in range(cells):
                cx = min(size - 1, int(col * step + step / 2))
                cy = min(size - 1, int(row * step + step / 2))
                if pixels[cx, cy] < 128:
                    continue
                if (row + col) % 2 == 0:
                    continue             # these keep the base amber
                draw.rectangle([col * step, row * step,
                                (col + 1) * step, (row + 1) * step],
                               fill=AMBER_DEEP)
    out.putalpha(mask)                   # the crisp edge comes back
    return out


def board_strip(size: int, plate: Image.Image) -> Image.Image:
    """A chessboard along the foot of the plate, for the knight to stand on.

    Kept faint and clipped to the plate: it gives the mark its board without
    competing with the silhouette at small sizes.
    """
    from PIL import ImageChops

    strip = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(strip)
    rows, cols = 2, 6
    top = size * 0.80
    row_h = (size - top) / rows
    col_w = size / cols
    for row in range(rows):
        for col in range(cols):
            light = (row + col) % 2 == 0
            draw.rectangle([col * col_w, top + row * row_h,
                            (col + 1) * col_w, top + (row + 1) * row_h],
                           fill=(PARCHMENT if light else WALNUT)[:3] + (52,))
    strip.putalpha(ImageChops.darker(strip.split()[-1], plate))
    return strip


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
    if maskable:
        # Full bleed. A launcher crops this to a circle, a squircle or a
        # teardrop, so the plate has to reach every corner or the mark ends up
        # floating on the launcher's own background.
        ImageDraw.Draw(mask).rectangle(
            [0, 0, size - 1, size - 1], fill=255)
    else:
        ImageDraw.Draw(mask).rounded_rectangle(
            [0, 0, size - 1, size - 1], radius=int(size * 0.235), fill=255)
    canvas.paste(plate, (0, 0), mask)

    # a thin amber rim, inset
    rim = ImageDraw.Draw(canvas)
    if maskable:
        # a circle at the safe-zone edge: whatever shape the launcher cuts,
        # this ring survives it
        rim.ellipse([size * 0.085, size * 0.085, size * 0.915, size * 0.915],
                    outline=AMBER[:3] + (150,),
                    width=max(1, int(size * 0.016)))
    else:
        rim.rounded_rectangle([size * 0.045, size * 0.045,
                               size * 0.955, size * 0.955],
                              radius=int(size * 0.20),
                              outline=AMBER[:3] + (210,),
                              width=max(1, int(size * 0.014)))

    # the knight, made of tiles.  The glyph is taller than it is wide, so the
    # mark is trimmed to its own bounds and normalised: the longest side is a
    # fixed fraction of the plate and the margins come out even.
    canvas.alpha_composite(board_strip(size, mask))

    knight = int(inner * 0.92)
    mask_img = knight_mask(knight)
    tiles = knight_body(mask_img, knight)
    tiles = tiles.crop(tiles.getbbox())
    scale = (inner * (0.74 if maskable else 0.72)) / max(tiles.size)
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
    """The same mark as vectors: a tile grid cut to the knight."""
    mask = knight_mask(GRID)
    pixels = mask.load()
    rects = []
    for row in range(GRID):
        for col in range(GRID):
            if pixels[col, row] >= 128:
                # flush, so the vector silhouette is whole like the raster one
                fill = "#f7c758" if (row + col) % 2 == 0 else "#cd8f14"
                rects.append(
                    f'<rect x="{col:.2f}" y="{row:.2f}" '
                    f'width="1.00" height="1.00" rx="0.09" fill="{fill}"/>')
    body = "\n    ".join(rects)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 11 11"
     width="512" height="512" role="img" aria-label="TALOS">
  <title>TALOS - The Living Chess Studio</title>
  <defs>
    <linearGradient id="plate" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#0e1015"/>
      <stop offset="1" stop-color="#1a1e29"/>
    </linearGradient>
  </defs>
  <rect width="11" height="11" rx="2.58" fill="url(#plate)"/>
  <g opacity="0.20">
    <rect x="0" y="8.8" width="1.83" height="1.10" fill="#f2ede1"/>
    <rect x="1.83" y="8.8" width="1.83" height="1.10" fill="#8d6a48"/>
    <rect x="3.67" y="8.8" width="1.83" height="1.10" fill="#f2ede1"/>
    <rect x="5.50" y="8.8" width="1.83" height="1.10" fill="#8d6a48"/>
    <rect x="7.33" y="8.8" width="1.83" height="1.10" fill="#f2ede1"/>
    <rect x="9.17" y="8.8" width="1.83" height="1.10" fill="#8d6a48"/>
    <rect x="0" y="9.90" width="1.83" height="1.10" fill="#8d6a48"/>
    <rect x="1.83" y="9.90" width="1.83" height="1.10" fill="#f2ede1"/>
    <rect x="3.67" y="9.90" width="1.83" height="1.10" fill="#8d6a48"/>
    <rect x="5.50" y="9.90" width="1.83" height="1.10" fill="#f2ede1"/>
    <rect x="7.33" y="9.90" width="1.83" height="1.10" fill="#8d6a48"/>
    <rect x="9.17" y="9.90" width="1.83" height="1.10" fill="#f2ede1"/>
  </g>
  <rect x="0.50" y="0.50" width="10.00" height="10.00" rx="2.20"
        fill="none" stroke="#f0b429" stroke-opacity="0.82" stroke-width="0.16"/>
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

    # Every size is drawn for itself rather than shrunk from the master. A
    # mosaic that reads as detail at 1024 turns into stripes at 32, and an
    # icon has to survive being 16 pixels wide on a taskbar.
    for size in SIZES:
        if size == 1024:
            continue
        compose(size).save(os.path.join(OUT, f"talos-{size}.png"))

    for size in (512, 192):
        compose(size, maskable=True).save(
            os.path.join(OUT, f"talos-maskable-{size}.png"))

    compose(180).save(os.path.join(OUT, "apple-touch-icon.png"))

    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64),
                 (128, 128), (256, 256)]
    try:
        master.save(os.path.join(OUT, "favicon.ico"), sizes=ico_sizes,
                    append_images=[compose(w) for w in (16, 24, 32, 48, 64, 128)])
    except Exception:                                     # pragma: no cover
        master.save(os.path.join(OUT, "favicon.ico"), sizes=ico_sizes)

    # a bare 512 png is what the Linux .desktop file points at
    compose(512).save(os.path.join(OUT, "talos.png"))

    # macOS: PyInstaller refuses an .ico here and wants a real .icns
    icns_sizes = [(16, 16), (32, 32), (64, 64), (128, 128), (256, 256),
                  (512, 512), (1024, 1024)]
    try:
        master.save(os.path.join(OUT, "talos.icns"), sizes=icns_sizes,
                    append_images=[compose(w) for w in (16, 32, 64, 128, 256, 512)])
    except Exception:                                     # pragma: no cover
        try:
            master.save(os.path.join(OUT, "talos.icns"), sizes=icns_sizes)
        except Exception as exc:
            print("  could not write talos.icns: " + str(exc), file=sys.stderr)

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
