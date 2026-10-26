"""Neon glow helpers: cached bloom sprites, polygon shapes and glowing text.

Glow surfaces are SRCALPHA with *premultiplied* colour (rgb = colour * coverage, a = coverage):
- draw_glow() blits them with BLEND_ADD (alpha ignored -> pure additive light),
- a plain blit still looks right (slightly softer), BLEND_PREMULTIPLIED is exact "over".
Every glow is built once (downscale -> gaussian blur -> smoothscale up) and cached; never per frame.
Returned surfaces are shared: never draw onto them.
"""
import logging
import math
from collections import OrderedDict

import pygame as pg

from .. import config

log = logging.getLogger(config.LOGGER_NAME)

GLOW_CACHE_SIZE = 384               # glow sprites (circles, rects, polygons, rings)
TEXT_CACHE_SIZE = 256               # neon_text surfaces
SHAPES = ("diamond", "hexagon", "star", "triangle")
# Rotational symmetry (degrees) per shape -> smaller cache for spinning items
_SYMMETRY = {"diamond": 180, "hexagon": 60, "star": 72, "triangle": 120}
ANGLE_STEP = 6                      # glow_polygon angle quantisation (degrees)

_warned = set()


class _LRU:
    """Tiny LRU dict for cached surfaces."""

    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self.data = OrderedDict()

    def get(self, key):
        surf = self.data.get(key)
        if surf is not None:
            self.data.move_to_end(key)
        return surf

    def put(self, key, surf):
        self.data[key] = surf
        if len(self.data) > self.maxsize:
            self.data.popitem(last=False)
        return surf

    def clear(self):
        self.data.clear()


_glows = _LRU(GLOW_CACHE_SIZE)
_texts = _LRU(TEXT_CACHE_SIZE)


#Colour helpers
def rgb(color) -> tuple:
    """Any colour (tuple/list/pg.Color/name, floats ok) -> clamped (r, g, b) ints."""
    if isinstance(color, str):
        c = pg.Color(color)
        return (c.r, c.g, c.b)
    return tuple(max(0, min(255, int(round(v)))) for v in tuple(color)[:3])


def lerp_color(a, b, t: float) -> tuple:
    """Linear blend a -> b (t clamped to 0..1)."""
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(3))


def scale_color(c, k: float) -> tuple:
    """Brightness multiply, clamped."""
    return tuple(max(0, min(255, int(c[i] * k))) for i in range(3))


def whiten(c, t: float) -> tuple:
    """Blend toward white: the 'hot core' of a neon tube."""
    return lerp_color(c, (255, 255, 255), t)


def _display_ready() -> bool:
    return pg.display.get_init() and pg.display.get_surface() is not None


def _finish(surf: pg.Surface) -> pg.Surface:
    return surf.convert_alpha() if _display_ready() else surf


def _warn_once(key, msg, *args):
    if key not in _warned:
        _warned.add(key)
        log.warning(msg, *args)


#Shapes
def polygon_points(key: str, center, size: float, angle: float = 0.0) -> list:
    """Vertices of a named shape inscribed in a circle of diameter `size` (angle in degrees, clockwise)."""
    r = size / 2
    cx, cy = center
    if key == "diamond":
        unit = [(0, -1), (0.72, 0), (0, 1), (-0.72, 0)]
    elif key == "triangle":
        unit = [(math.cos(math.radians(a)), math.sin(math.radians(a))) for a in (-90, 30, 150)]
    elif key == "hexagon":
        unit = [(math.cos(math.radians(-90 + 60 * i)), math.sin(math.radians(-90 + 60 * i))) for i in range(6)]
    elif key == "star":
        unit = []
        for i in range(10):
            a = math.radians(-90 + 36 * i)
            k = 1.0 if i % 2 == 0 else 0.45
            unit.append((math.cos(a) * k, math.sin(a) * k))
    else:
        raise ValueError(f"unknown shape '{key}'")
    if angle:
        ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
        unit = [(x * ca - y * sa, x * sa + y * ca) for x, y in unit]
    return [(cx + x * r, cy + y * r) for x, y in unit]


#Bloom core
def _gray(k: float, alpha: bool = True) -> tuple:
    v = max(0, min(255, int(255 * k)))
    return (v, v, v, v if alpha else 255)


def _bloom(w: int, h: int, draw, spread: float) -> pg.Surface:
    """White premultiplied bloom of the shape that draw(surface, ox, oy) paints in opaque white.

    Two blurs (tight + wide) are summed: bright near the edge, long soft tail -> neon tube look.
    Result size is (w + 2*pad, h + 2*pad) with pad = glow_pad(spread).
    """
    pad = glow_pad(spread)
    W, H = int(w) + 2 * pad, int(h) + 2 * pad
    mask = pg.Surface((W, H), pg.SRCALPHA)
    draw(mask, pad, pad)

    f = 1 if spread < 5 else 2 if spread < 14 else 3
    small = pg.transform.smoothscale(mask, (max(1, W // f), max(1, H // f))) if f > 1 else mask
    tight = pg.transform.gaussian_blur(small, max(1, round(spread * 0.4 / f)), False)
    wide = pg.transform.gaussian_blur(small, max(1, round(spread * 1.6 / f)), False)
    tight.fill(_gray(0.8), special_flags=pg.BLEND_RGBA_MULT)
    # Wide tail weighted > 1: add it once fully and once at 0.3 (saturating add)
    tight.blit(wide, (0, 0), special_flags=pg.BLEND_RGBA_ADD)
    wide.fill(_gray(0.3), special_flags=pg.BLEND_RGBA_MULT)
    tight.blit(wide, (0, 0), special_flags=pg.BLEND_RGBA_ADD)
    return pg.transform.smoothscale(tight, (W, H)) if f > 1 else tight


def glow_pad(spread: float) -> int:
    """Transparent margin a bloom of this spread adds on each side."""
    return int(spread * 2.8) + 2


def _tint(mask: pg.Surface, color, intensity: float) -> pg.Surface:
    """Scale a white premultiplied mask by intensity, then colour it (stays premultiplied)."""
    if intensity < 1.0:
        mask.fill(_gray(max(0.0, intensity)), special_flags=pg.BLEND_RGBA_MULT)
    elif intensity > 1.0:
        extra = mask.copy()
        extra.fill(_gray(min(1.0, intensity - 1.0)), special_flags=pg.BLEND_RGBA_MULT)
        mask.blit(extra, (0, 0), special_flags=pg.BLEND_RGBA_ADD)
    r, g, b = color
    mask.fill((r, g, b, 255), special_flags=pg.BLEND_RGBA_MULT)
    return _finish(mask)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


#Public glow builders (all cached)
def glow_circle(radius: float, color, intensity: float = 1.0, spread: float = None) -> pg.Surface:
    """Bloom for a disc of `radius`; centre it on the shape and draw the crisp shape on top."""
    radius = max(1, int(round(radius)))
    color = rgb(color)
    spread = float(spread) if spread else _clamp(radius * 0.8, 4.0, 28.0)
    key = ("c", radius, color, round(intensity, 2), round(spread, 1))
    surf = _glows.get(key)
    if surf is None:
        surf = _glows.put(key, build_glow_circle(radius, color, intensity, spread))
    return surf


def build_glow_circle(radius: int, color, intensity: float, spread: float) -> pg.Surface:
    """Uncached glow_circle (for callers that keep their own cache, e.g. particle sprites)."""
    radius = max(1, int(round(radius)))
    d = radius * 2
    mask = _bloom(d, d, lambda s, ox, oy: pg.draw.circle(
        s, (255, 255, 255, 255), (ox + radius, oy + radius), radius), spread)
    return _tint(mask, rgb(color), intensity)


def glow_rect(w: float, h: float, color, radius: int = 8, thickness: int = 0,
              intensity: float = 1.0, spread: float = None) -> pg.Surface:
    """Bloom for a rounded rect (filled when thickness == 0, outline otherwise)."""
    w, h = max(1, int(round(w))), max(1, int(round(h)))
    color = rgb(color)
    thickness = max(0, int(thickness))
    if not spread:
        spread = _clamp(4 + thickness * 2.0, 5.0, 14.0) if thickness else _clamp(min(w, h) * 0.45, 5.0, 16.0)
    key = ("r", w, h, color, int(radius), thickness, round(intensity, 2), round(spread, 1))
    surf = _glows.get(key)
    if surf is None:
        def draw(s, ox, oy):
            pg.draw.rect(s, (255, 255, 255, 255), (ox, oy, w, h), thickness, border_radius=int(radius))
        surf = _glows.put(key, _tint(_bloom(w, h, draw, spread), color, intensity))
    return surf


def glow_polygon(points_key: str, size: float, color, angle: float = 0.0,
                 intensity: float = 1.0, spread: float = None) -> pg.Surface:
    """Bloom for a named shape ('diamond', 'hexagon', 'star', 'triangle') of diameter `size`.

    `angle` (degrees) is quantised to ANGLE_STEP and folded by the shape's symmetry.
    Unknown keys log once and fall back to a circle glow.
    """
    if points_key not in _SYMMETRY:
        _warn_once(("shape", points_key), "glow_polygon: unknown shape '%s', using circle", points_key)
        return glow_circle(size / 2, color, intensity, spread)
    size = max(2, int(round(size)))
    color = rgb(color)
    sym = _SYMMETRY[points_key]
    angle = int(round((angle % sym) / ANGLE_STEP)) * ANGLE_STEP % sym
    spread = float(spread) if spread else _clamp(size * 0.35, 4.0, 22.0)
    key = ("p", points_key, size, color, angle, round(intensity, 2), round(spread, 1))
    surf = _glows.get(key)
    if surf is None:
        def draw(s, ox, oy):
            pts = polygon_points(points_key, (ox + size / 2, oy + size / 2), size, angle)
            pg.draw.polygon(s, (255, 255, 255, 255), pts)
        surf = _glows.put(key, _tint(_bloom(size, size, draw, spread), color, intensity))
    return surf


def glow_ring(radius: float, color, thickness: int = 3, intensity: float = 1.0,
              spread: float = None) -> pg.Surface:
    """Bloom for a circle outline (shield bubbles, target rings)."""
    radius = max(2, int(round(radius)))
    thickness = max(1, int(thickness))
    color = rgb(color)
    spread = float(spread) if spread else _clamp(thickness * 3.0, 5.0, 14.0)
    key = ("o", radius, color, thickness, round(intensity, 2), round(spread, 1))
    surf = _glows.get(key)
    if surf is None:
        d = radius * 2
        mask = _bloom(d, d, lambda s, ox, oy: pg.draw.circle(
            s, (255, 255, 255, 255), (ox + radius, oy + radius), radius, thickness), spread)
        surf = _glows.put(key, _tint(mask, color, intensity))
    return surf


def draw_glow(surf: pg.Surface, glow_surf: pg.Surface, center) -> pg.Rect:
    """Additively blit a glow centred on `center`; returns the affected rect."""
    w, h = glow_surf.get_size()
    return surf.blit(glow_surf, (int(center[0] - w / 2), int(center[1] - h / 2)), special_flags=pg.BLEND_ADD)


#Text
def neon_text(assets, s: str, size: int, color, weight: str = "bold") -> pg.Surface:
    """Text with a whitened core and a coloured glow halo (straight alpha: use a normal blit).

    The surface includes the halo margin on every side, so position it by its centre.
    """
    s = str(s)
    size = max(1, int(size))
    color = rgb(color)
    key = (s, size, color, weight)
    surf = _texts.get(key)
    if surf is not None:
        return surf

    core = assets.text(s, size, whiten(color, 0.35), weight)
    white = assets.text(s, size, (255, 255, 255), weight)
    tw, th = white.get_size()
    spread = max(3.0, size * 0.2)
    pad = glow_pad(spread)
    W, H = tw + 2 * pad, th + 2 * pad

    # Alpha-only mask: rgb stays white, alpha = glyph coverage
    mask = pg.Surface((W, H), pg.SRCALPHA)
    mask.fill((255, 255, 255, 0))
    mask.blit(white, (pad, pad), special_flags=pg.BLEND_RGBA_MAX)

    f = 2 if spread >= 6 else 1
    small = pg.transform.smoothscale(mask, (max(1, W // f), max(1, H // f))) if f > 1 else mask
    tight = pg.transform.gaussian_blur(small, max(1, round(spread * 0.3 / f)), False)
    wide = pg.transform.gaussian_blur(small, max(1, round(spread / f)), False)
    tight.blit(wide, (0, 0), special_flags=pg.BLEND_RGBA_ADD)
    halo = pg.transform.smoothscale(tight, (W, H)) if f > 1 else tight

    # Straight-alpha colour halo, then the crisp core on top
    r, g, b = color
    halo.fill((r, g, b, 215), special_flags=pg.BLEND_RGBA_MULT)
    halo.blit(core, (pad, pad))
    return _texts.put(key, _finish(halo))


def clear_cache() -> None:
    """Drop every cached glow and neon text (e.g. after a display re-init)."""
    _glows.clear()
    _texts.clear()
