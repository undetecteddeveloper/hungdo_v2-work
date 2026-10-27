"""Download the Python and Claude logos (SVG) and render them as PNG for the splash screen.

Usage (from repo root, needs internet):  python tools/make_logos.py
Output: assets/images/logos/python.png, claude.png (512 px tall, transparent background).
Sources are listed in CREDITS.md.
"""
import os
import re
import sys
import tempfile
import urllib.request

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame as pg  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(os.path.dirname(HERE), "assets", "images", "logos")
SIZE = 512
CLAUDE_ORANGE = "#D97757"       # pygame's SVG reader does not understand the hsl() fill used upstream

LOGOS = {
    "python": "https://upload.wikimedia.org/wikipedia/commons/c/c3/Python-logo-notext.svg",
    "claude": "https://upload.wikimedia.org/wikipedia/commons/b/b0/Claude_AI_symbol.svg",
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8")


def prepare(name: str, svg: str) -> str:
    """Make the SVG render crisply at SIZE px and without colour functions pygame cannot parse."""
    if name == "claude":
        svg = re.sub(r'fill="hsl\([^"]*\)"', f'fill="{CLAUDE_ORANGE}"', svg)
    svg = re.sub(r'\bwidth="[^"]*"', "", svg, count=1)
    svg = re.sub(r'\bheight="[^"]*"', "", svg, count=1)
    return svg.replace("<svg ", f'<svg width="{SIZE}px" height="{SIZE}px" ', 1)


def main() -> int:
    pg.display.init()
    pg.display.set_mode((1, 1))
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, url in LOGOS.items():
        svg = prepare(name, fetch(url))
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, name + ".svg")
            with open(path, "w", encoding="utf-8") as f:
                f.write(svg)
            surf = pg.image.load(path).convert_alpha()
        dest = os.path.join(OUT_DIR, name + ".png")
        pg.image.save(surf, dest)
        print(f"{name}: {surf.get_size()} -> {dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
