"""Dev tool: render the Hứng Đồ v2 app icon procedurally (no external assets).

A neon basket catching a glowing orb on a dark navy rounded square.
Everything is drawn at 4x and downsampled for clean anti-aliasing.

    python tools/make_icon.py            # writes assets/icon.png (256) + assets/icon.ico
    python tools/make_icon.py --preview  # also writes tools/_out/icon_preview.png
"""

import argparse
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # hungdo_v2/
PNG_PATH = os.path.join(ROOT, "assets", "icon.png")
ICO_PATH = os.path.join(ROOT, "assets", "icon.ico")
ICO_SIZES = [16, 32, 48, 64, 128, 256]

#Colours (match the game's neon palette)
BG_TOP = (18, 20, 48)
BG_BOTTOM = (6, 7, 22)
CYAN = (0, 240, 255)
MAGENTA = (255, 46, 196)
YELLOW = (255, 225, 60)
WHITE = (255, 255, 255)

SS = 4  # supersampling factor


def _vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    grad = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / (size - 1)
        grad.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return grad.resize((size, size))


def _glow(layer: Image.Image, radius: float, strength: float = 1.0) -> Image.Image:
    """ Blurred copy of an RGBA layer, brightened, for additive halo """
    halo = layer.filter(ImageFilter.GaussianBlur(radius))
    if strength != 1.0:
        r, g, b, a = halo.split()
        a = a.point(lambda v: min(255, int(v * strength)))
        halo = Image.merge("RGBA", (r, g, b, a))
    return halo


def _add(base: Image.Image, layer: Image.Image) -> Image.Image:
    """ Additive blend of a premultiplied RGBA layer onto an RGB base """
    rgb = Image.new("RGB", layer.size, (0, 0, 0))
    rgb.paste(layer.convert("RGB"), mask=layer.getchannel("A"))
    return ImageChops.add(base, rgb)


def render(size: int, detail: bool = True) -> Image.Image:
    """ Render the icon at `size` px; `detail=False` drops fine strokes for tiny sizes """
    S = size * SS
    u = S / 256  # design unit: coordinates below are on a 256 grid

    #Background: rounded square with a navy gradient
    radius = 56 * u
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, S - 1, S - 1), radius, fill=255)
    base = _vertical_gradient(S, BG_TOP, BG_BOTTOM)

    #Faint inner border ring in cyan
    if detail:
        ring = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(ring).rounded_rectangle((7 * u, 7 * u, S - 7 * u, S - 7 * u), radius - 7 * u,
                                               outline=CYAN + (70,), width=int(3 * u))
        base = _add(base, ring)

    #Orb position: it sits in the mouth of the basket, just caught
    cx, cy, r = 128 * u, (124 if detail else 116) * u, (32 if detail else 44) * u

    #Motion trail above the orb (falling streaks)
    if detail:
        trail = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        td = ImageDraw.Draw(trail)
        for dx, y0, y1, alpha in ((-16, 34, 80, 90), (0, 20, 84, 150), (16, 34, 80, 90)):
            x = 128 + dx
            td.line((x * u, y0 * u, x * u, y1 * u), fill=MAGENTA + (alpha,), width=int(6 * u))
            td.ellipse(((x - 3) * u, (y0 - 3) * u, (x + 3) * u, (y0 + 3) * u), fill=MAGENTA + (alpha,))
        base = _add(base, _glow(trail, 6 * u))
        base = _add(base, trail)

    #Orb: glowing magenta ball with a hot pink-white core
    orb = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(orb).ellipse((cx - r, cy - r, cx + r, cy + r), fill=MAGENTA + (255,))
    base = _add(base, _glow(orb, 22 * u, 1.6))
    base = _add(base, orb)
    core = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    cr, off = r * 0.5, r * 0.2
    ImageDraw.Draw(core).ellipse((cx - cr - off, cy - cr - off, cx + cr - off, cy + cr - off),
                                 fill=(255, 200, 245, 210))
    base = _add(base, _glow(core, 5 * u))

    #Basket: cyan U-shaped cup (straight walls, round bottom) drawn as outer minus inner shape
    bw = (16 if detail else 26) * u
    x0, x1 = (64 if detail else 52) * u, (192 if detail else 204) * u
    y0, y1 = (112 if detail else 104) * u, (212 if detail else 222) * u
    rad = (x1 - x0) / 2
    cup = Image.new("L", (S, S), 0)
    cd = ImageDraw.Draw(cup)
    cd.rounded_rectangle((x0, y0, x1, y1), rad, fill=255, corners=(False, False, True, True))
    cd.rounded_rectangle((x0 + bw, y0 - bw, x1 - bw, y1 - bw), rad - bw, fill=0,
                         corners=(False, False, True, True))
    #Round caps on top of the walls keep the stroke flat-vector clean
    for wx in (x0 + bw / 2, x1 - bw / 2):
        cd.ellipse((wx - bw / 2, y0 - bw / 2, wx + bw / 2, y0 + bw / 2), fill=255)
    basket = Image.new("RGBA", (S, S), CYAN + (0,))
    basket.putalpha(cup)
    base = _add(base, _glow(basket, 14 * u, 1.5))
    base = _add(base, basket)

    #Sparkles where the orb meets the basket
    if detail:
        spark = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        sd = ImageDraw.Draw(spark)
        for sx, sy, sr in ((44, 96, 9), (212, 90, 8), (198, 62, 5)):
            pts = []
            for k in range(8):
                a = math.pi * k / 4 - math.pi / 2
                rr = sr if k % 2 == 0 else sr * 0.3
                pts.append(((sx + math.cos(a) * rr) * u, (sy + math.sin(a) * rr) * u))
            sd.polygon(pts, fill=YELLOW + (255,))
        base = _add(base, _glow(spark, 4 * u))
        base = _add(base, spark)

    #Clip to the rounded square and downsample
    out = base.convert("RGBA")
    out.putalpha(mask)
    return out.resize((size, size), Image.LANCZOS)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Render the app icon")
    parser.add_argument("--preview", action="store_true", help="also save a size-comparison sheet")
    args = parser.parse_args(argv)

    big = render(256)
    os.makedirs(os.path.dirname(PNG_PATH), exist_ok=True)
    big.save(PNG_PATH, optimize=True)

    #Each ICO size is rendered on its own; tiny sizes use the simplified design
    frames = {s: (big if s == 256 else render(s, detail=s >= 48)) for s in ICO_SIZES}
    big.save(ICO_PATH, format="ICO", sizes=[(s, s) for s in ICO_SIZES],
             append_images=[frames[s] for s in ICO_SIZES if s != 256])
    print(f"wrote {PNG_PATH}\nwrote {ICO_PATH}")

    if args.preview:
        out_dir = os.path.join(ROOT, "tools", "_out")
        os.makedirs(out_dir, exist_ok=True)
        sheet = Image.new("RGBA", (sum(ICO_SIZES) + 10 * (len(ICO_SIZES) + 1), 276), (40, 40, 40, 255))
        x = 10
        for s in ICO_SIZES:
            sheet.alpha_composite(frames[s], (x, 10))
            x += s + 10
        path = os.path.join(out_dir, "icon_preview.png")
        sheet.save(path)
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
