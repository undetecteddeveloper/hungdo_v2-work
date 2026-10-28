"""Dev tool: render the Hứng Đồ v2 app icon procedurally (no external assets).

The game's straight neon paddle catching a golden star (the real "epic" item) on a dark navy rounded square.
Everything is drawn at 4x and downsampled for clean anti-aliasing.

    python tools/make_icon.py            # writes assets/icon.png (256) + assets/icon.ico
    python tools/make_icon.py --preview  # also writes tools/_out/icon_preview.png
"""

import argparse
import math
import os
import sys

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root
PNG_PATH = os.path.join(ROOT, "assets", "icon.png")
ICO_PATH = os.path.join(ROOT, "assets", "icon.ico")
ICO_SIZES = [16, 32, 48, 64, 128, 256]

#Colours (match the game's neon palette)
BG_TOP = (18, 20, 48)
BG_BOTTOM = (6, 7, 22)
CYAN = (0, 240, 255)
MAGENTA = (255, 46, 196)  # kept for the palette; the icon itself uses cyan + yellow
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

    #Star: the game's "epic" item (5-point star, dark yellow fill, bright yellow outline), tilted a little as if it spins
    cx, cy = 128 * u, (108 if detail else 104) * u
    R = (50 if detail else 62) * u
    star = [(cx + math.cos(-math.pi / 2 + 0.2 + math.pi * k / 5) * R * (1.0 if k % 2 == 0 else 0.45),
             cy + math.sin(-math.pi / 2 + 0.2 + math.pi * k / 5) * R * (1.0 if k % 2 == 0 else 0.45)) for k in range(10)]

    #Motion trail above the star (falling streaks)
    if detail:
        trail = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        td = ImageDraw.Draw(trail)
        for dx, y0, y1, alpha in ((-26, 30, 58, 80), (0, 14, 46, 140), (26, 30, 58, 80)):
            x = 128 + dx
            td.line((x * u, y0 * u, x * u, y1 * u), fill=YELLOW + (alpha,), width=int(6 * u))
            td.ellipse(((x - 3) * u, (y0 - 3) * u, (x + 3) * u, (y0 + 3) * u), fill=YELLOW + (alpha,))
        base = _add(base, _glow(trail, 6 * u))
        base = _add(base, trail)

    body = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(body).polygon(star, fill=YELLOW + (255,))
    base = _add(base, _glow(body, 20 * u, 1.4))
    fill = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(fill).polygon(star, fill=(70, 60, 12, 255))
    base = _add(base, fill)
    edge = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(edge).line(star + [star[0], star[1]], fill=YELLOW + (255,), width=int((7 if detail else 10) * u), joint="curve")
    base = _add(base, edge)

    #Paddle: the in-game capsule, straight (dark cyan fill, bright cyan outline, light highlight line)
    px0, px1 = (46 if detail else 36) * u, (210 if detail else 220) * u
    py0, py1 = (178 if detail else 170) * u, (208 if detail else 214) * u
    cap = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(cap).rounded_rectangle((px0, py0, px1, py1), (py1 - py0) / 2, fill=CYAN + (255,))
    base = _add(base, _glow(cap, 14 * u, 1.5))
    inner = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ow = (6 if detail else 9) * u
    ImageDraw.Draw(inner).rounded_rectangle((px0 + ow, py0 + ow, px1 - ow, py1 - ow), (py1 - py0) / 2 - ow, fill=(0, 62, 70, 255))
    rim = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(rim).rounded_rectangle((px0, py0, px1, py1), (py1 - py0) / 2, fill=CYAN + (255,))
    ImageDraw.Draw(rim).rounded_rectangle((px0 + ow, py0 + ow, px1 - ow, py1 - ow), (py1 - py0) / 2 - ow, fill=(0, 0, 0, 0))
    base = _add(base, inner)
    base = _add(base, rim)
    if detail:
        hl = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ImageDraw.Draw(hl).line((px0 + 26 * u, (py0 + 12 * u), px1 - 26 * u, (py0 + 12 * u)), fill=(200, 255, 255, 230), width=int(3 * u))
        base = _add(base, hl)

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
