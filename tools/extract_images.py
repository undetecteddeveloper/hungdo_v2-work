"""Dev tool: safely unpack downloaded image packs and prepare icon glyphs.

Downloaded archives are untrusted data, so this script never executes anything
from them. It only copies media files out, rejects unsafe member paths, and
caps the uncompressed size. Run it isolated, passing every path as an argument:

    python -I tools/extract_images.py extract <archive.zip> <out_dir>
    python -I tools/extract_images.py whiten <src.png> <dst.png> [--size 128] [--pad 8]
    python -I tools/extract_images.py glyph <magnet|bomb|star> <dst.png>

`whiten` turns any glyph into a white-on-transparent PNG (rgb = 255,
alpha = original alpha), trims it and fits it centred on a square canvas, so the
game can tint it to any neon colour by multiplying. `glyph` draws the few icons
no CC0 pack provided in a usable form (magnet, bomb, star) in the same flat style.
"""

import argparse
import math
import os
import sys
import zipfile

#Only these file types ever leave an archive
MEDIA_EXTS = {".png", ".ttf", ".otf", ".ogg", ".wav", ".mp3"}
MAX_TOTAL_BYTES = 200 * 1024 * 1024  # zip-bomb guard
MAX_MEMBER_BYTES = 20 * 1024 * 1024


def _safe_target(out_dir: str, member: str) -> str | None:
    """ Map an archive member to a path inside out_dir, or None if unsafe """
    name = member.replace("\\", "/")
    if name.startswith("/") or ":" in name:
        return None
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        return None
    target = os.path.realpath(os.path.join(out_dir, *parts))
    root = os.path.realpath(out_dir)
    if os.path.commonpath([root, target]) != root:
        return None
    return target


def extract(archive: str, out_dir: str) -> int:
    """ Copy media members of a zip into out_dir; returns the number of files written """
    os.makedirs(out_dir, exist_ok=True)
    written = 0
    total = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            if os.path.splitext(info.filename)[1].lower() not in MEDIA_EXTS:
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                print(f"skip (too big): {info.filename}")
                continue
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise RuntimeError("archive exceeds size limit")
            target = _safe_target(out_dir, info.filename)
            if target is None:
                print(f"skip (unsafe path): {info.filename}")
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            # Stream with a hard cap instead of trusting the header size
            with zf.open(info) as src, open(target, "wb") as dst:
                remaining = MAX_MEMBER_BYTES
                while chunk := src.read(65536):
                    remaining -= len(chunk)
                    if remaining < 0:
                        raise RuntimeError(f"member exceeds size limit: {info.filename}")
                    dst.write(chunk)
            written += 1
    return written


def _fit_alpha(alpha, size: int, pad: int):
    """ Trim an alpha mask and centre it, aspect kept, on a white size x size glyph """
    from PIL import Image

    bbox = alpha.getbbox()
    if bbox is None:
        raise ValueError("empty glyph")
    alpha = alpha.crop(bbox)

    #Fit the trimmed glyph inside the padded box, keeping aspect ratio
    box = size - 2 * pad
    w, h = alpha.size
    scale = min(box / w, box / h)
    new_size = (max(1, round(w * scale)), max(1, round(h * scale)))
    alpha = alpha.resize(new_size, Image.LANCZOS)

    out = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    glyph = Image.new("RGBA", new_size, (255, 255, 255, 255))
    glyph.putalpha(alpha)
    out.paste(glyph, ((size - new_size[0]) // 2, (size - new_size[1]) // 2))
    return out


def _save(img, dst: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    img.save(dst, optimize=True)


def whiten(src: str, dst: str, size: int = 128, pad: int = 8) -> None:
    """ Save src as a white glyph (alpha kept) centred on a size x size canvas """
    from PIL import Image

    alpha = Image.open(src).convert("RGBA").getchannel("A")
    _save(_fit_alpha(alpha, size, pad), dst)


# ---------------------------------------------------------------- procedural glyphs
# Drawn as a 1-bit-ish mask at 4x the final size per unit square (S = 512),
# then downsampled with LANCZOS for clean anti-aliased edges.
S = 512


def _draw_magnet(draw) -> None:
    """ Horseshoe magnet, opening up, with cut-off pole tips """
    cx, cy = S / 2, S * 0.52
    r_out, r_in = S * 0.38, S * 0.17
    top = S * 0.08
    #Lower half ring
    draw.pieslice((cx - r_out, cy - r_out, cx + r_out, cy + r_out), 0, 180, fill=255)
    draw.pieslice((cx - r_in, cy - r_in, cx + r_in, cy + r_in), 0, 180, fill=0)
    #Two legs going up
    draw.rectangle((cx - r_out, top, cx - r_in, cy), fill=255)
    draw.rectangle((cx + r_in, top, cx + r_out, cy), fill=255)
    #Gap that separates the pole tips
    gap_y = top + S * 0.15
    draw.rectangle((0, gap_y, S, gap_y + S * 0.035), fill=0)


def _draw_bomb(draw) -> None:
    """ Round bomb with cap, curved fuse, spark and a highlight cut-out """
    cx, cy, r = S * 0.44, S * 0.58, S * 0.33
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    #Cap: small rotated square on the upper right of the body
    a = math.radians(-45)
    ux, uy = math.cos(a), math.sin(a)          # direction towards upper right
    px, py = -uy, ux                           # perpendicular
    base = r * 0.82
    hw, l0, l1 = S * 0.075, base, base + S * 0.11
    cap = [(cx + ux * l0 + px * hw, cy + uy * l0 + py * hw),
           (cx + ux * l1 + px * hw, cy + uy * l1 + py * hw),
           (cx + ux * l1 - px * hw, cy + uy * l1 - py * hw),
           (cx + ux * l0 - px * hw, cy + uy * l0 - py * hw)]
    draw.polygon(cap, fill=255)
    #Fuse: thick quadratic curve leaving the cap, bending to the right
    fx, fy = cx + ux * l1, cy + uy * l1
    p0, p1, p2 = (fx, fy), (fx + S * 0.02, fy - S * 0.12), (fx + S * 0.13, fy - S * 0.13)
    curve = []
    for i in range(25):
        t = i / 24
        curve.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t * t * p2[0],
                      (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t * t * p2[1]))
    fw = int(S * 0.045)
    draw.line(curve, fill=255, width=fw, joint="curve")
    draw.ellipse((p0[0] - fw / 2, p0[1] - fw / 2, p0[0] + fw / 2, p0[1] + fw / 2), fill=255)
    #Spark: four-point star past the fuse end, with a small gap
    _star(draw, p2[0] + S * 0.075, p2[1] - S * 0.02, S * 0.1, S * 0.03, 4)
    #Highlight cut-out on the body (gives the flat-vector shine)
    hr = r * 0.62
    draw.arc((cx - hr, cy - hr, cx + hr, cy + hr), 200, 250, fill=0, width=int(S * 0.04))


def _star(draw, cx: float, cy: float, r_out: float, r_in: float, points: int) -> None:
    """ Filled star polygon with the first point straight up """
    pts = []
    for k in range(points * 2):
        ang = math.pi * k / points - math.pi / 2
        rr = r_out if k % 2 == 0 else r_in
        pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    draw.polygon(pts, fill=255)


def _draw_star(draw) -> None:
    """ Five-point star (corners get rounded by the post-pass) """
    _star(draw, S / 2, S * 0.54, S * 0.46, S * 0.2, 5)


GLYPHS = {"magnet": _draw_magnet, "bomb": _draw_bomb, "star": _draw_star}
#Glyphs whose corners are softened (blur + threshold) for the rounded flat look
ROUNDED = {"star": 10}


def draw_glyph(name: str, dst: str, size: int = 128, pad: int = 8) -> None:
    """ Render a procedural glyph to a white-on-transparent PNG """
    from PIL import Image, ImageDraw, ImageFilter

    mask = Image.new("L", (S, S), 0)
    GLYPHS[name](ImageDraw.Draw(mask))
    if name in ROUNDED:
        mask = mask.filter(ImageFilter.GaussianBlur(ROUNDED[name]))
        mask = mask.point(lambda v: 255 if v >= 128 else 0)
    _save(_fit_alpha(mask, size, pad), dst)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_ex = sub.add_parser("extract", help="copy media files out of a zip")
    p_ex.add_argument("archive")
    p_ex.add_argument("out_dir")
    p_wh = sub.add_parser("whiten", help="make a white-on-transparent square glyph")
    p_wh.add_argument("src")
    p_wh.add_argument("dst")
    p_wh.add_argument("--size", type=int, default=128)
    p_wh.add_argument("--pad", type=int, default=8)
    p_gl = sub.add_parser("glyph", help="draw a procedural glyph: " + ", ".join(GLYPHS))
    p_gl.add_argument("name", choices=sorted(GLYPHS))
    p_gl.add_argument("dst")
    p_gl.add_argument("--size", type=int, default=128)
    p_gl.add_argument("--pad", type=int, default=8)
    args = parser.parse_args(argv)

    if args.cmd == "extract":
        n = extract(args.archive, args.out_dir)
        print(f"extracted {n} media files -> {args.out_dir}")
    elif args.cmd == "whiten":
        whiten(args.src, args.dst, args.size, args.pad)
        print(f"wrote {args.dst}")
    else:
        draw_glyph(args.name, args.dst, args.size, args.pad)
        print(f"wrote {args.dst}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
