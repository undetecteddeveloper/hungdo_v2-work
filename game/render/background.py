"""Animated synthwave background: gradient sky, drifting stars, horizon glow + sun, scrolling grid.

Static layers are pre-rendered once in white and re-tinted into reusable buffers only when the
(lerping) accent colour actually changes, so a normal frame is a few blits + ~20 line draws.
"""
import math
import random

import pygame as pg

from .. import config
from . import neon

W, H = config.LOGICAL_SIZE
HORIZON_Y = int(H * 0.65)           # grid fills the bottom ~35 %
GRID_H = H - HORIZON_Y
ACCENT_TIME = 1.5                   # seconds for set_accent() to blend

# Grid (perspective: screen y below horizon = GRID_H * Z_NEAR / z)
Z_NEAR = 1.0
GRID_DZ = 0.32                      # depth between horizontal lines
GRID_MIN_GAP = 4.0                  # stop drawing lines once they are this close (px)
GRID_COLUMNS = 9                    # vertical lines each side of centre
GRID_SPACING_BOTTOM = 74            # px between vertical lines at the bottom edge
SCROLL_PERIOD = 1.1                 # seconds for one line to move one slot toward the viewer
GRID_BRIGHTNESS = 0.55

# Horizon glow / sun
GLOW_HALF_H = 150                   # glow layer spans HORIZON_Y +- this
SUN_RADIUS = 92
SUN_BRIGHTNESS = 0.15

# Stars
STAR_COUNT = 90
STAR_LEVELS = 10
STAR_COLOR = (205, 220, 255)

FLOOR_TOP = (16, 8, 36)
FLOOR_BOTTOM = (5, 4, 16)


def _smoothstep(e0: float, e1: float, x: float) -> float:
    t = (x - e0) / (e1 - e0)
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    return t * t * (3 - 2 * t)


def _opaque(surf: pg.Surface) -> pg.Surface:
    return surf.convert() if pg.display.get_init() and pg.display.get_surface() else surf


def _blur(surf: pg.Surface, factor: int, radius: int) -> pg.Surface:
    """Downscale -> gaussian blur -> smoothscale back up."""
    w, h = surf.get_size()
    small = pg.transform.smoothscale(surf, (max(1, w // factor), max(1, h // factor)))
    small = pg.transform.gaussian_blur(small, radius, False)
    return pg.transform.smoothscale(small, (w, h))


class Background:
    def __init__(self, app=None, accent=None):
        self.app = app
        accent = neon.rgb(accent or config.LEVEL_HUES[0])
        self.accent = accent                    # current (lerped) colour, int tuple
        self._acc_from = accent
        self._acc_to = accent
        self._acc_t = 1.0
        self.speed = 1.0                        # grid/star speed multiplier (e.g. faster at high level)
        self.time = 0.0
        self._scroll = 0.0                      # 0..1 phase between two horizontal lines
        self._pulse = 0.0
        self._tint_key = None
        self.rng = random.Random(7)

        self._base = self._build_base()
        self._vert_white = self._build_vertical_grid()
        self._glow_white = self._build_horizon_glow()
        self._vert = self._vert_white.copy()
        self._glow = self._glow_white.copy()
        self._grid_buf = self._vert_white.copy()
        self._star_sprites = self._build_star_sprites()
        self._stars = [self._new_star(self.rng.uniform(0, HORIZON_Y)) for _ in range(STAR_COUNT)]
        self._blits = []
        self._retint()

    #Pre-rendered layers
    def _build_base(self) -> pg.Surface:
        base = pg.Surface((W, H))
        top, bottom = config.PALETTE["bg_top"], config.PALETTE["bg_bottom"]
        for y in range(HORIZON_Y):
            base.fill(neon.lerp_color(top, bottom, (y / HORIZON_Y) ** 1.4), (0, y, W, 1))
        for y in range(HORIZON_Y, H):
            base.fill(neon.lerp_color(FLOOR_TOP, FLOOR_BOTTOM, ((y - HORIZON_Y) / GRID_H) ** 0.7), (0, y, W, 1))
        # Vignette: multiply by a blurred bright ellipse on a darker field
        vig = pg.Surface((W, H))
        vig.fill((120, 120, 140))
        pg.draw.ellipse(vig, (255, 255, 255), (-W * 0.25, H * 0.02, W * 1.5, H * 0.96))
        base.blit(_blur(vig, 8, 10), (0, 0), special_flags=pg.BLEND_MULT)
        return _opaque(base)

    def _build_vertical_grid(self) -> pg.Surface:
        """White converging lines on black, faded toward the horizon, with a soft glow."""
        lines = pg.Surface((W, GRID_H))
        cx = W / 2
        for k in range(-GRID_COLUMNS, GRID_COLUMNS + 1):
            pg.draw.aaline(lines, (255, 255, 255), (cx, 0), (cx + k * GRID_SPACING_BOTTOM, GRID_H))
        glow = _blur(lines, 2, 3)
        glow.fill((150, 150, 150), special_flags=pg.BLEND_MULT)
        lines.blit(glow, (0, 0), special_flags=pg.BLEND_ADD)
        lines.blit(glow, (0, 0), special_flags=pg.BLEND_ADD)
        # Depth fade: invisible at the horizon, GRID_BRIGHTNESS at the bottom
        fade = pg.Surface((W, GRID_H))
        for y in range(GRID_H):
            v = int(255 * GRID_BRIGHTNESS * _smoothstep(0.0, 1.0, y / GRID_H) ** 0.8)
            fade.fill((v, v, v), (0, y, W, 1))
        lines.blit(fade, (0, 0), special_flags=pg.BLEND_MULT)
        return _opaque(lines)

    def _build_horizon_glow(self) -> pg.Surface:
        """White mask: wide soft glow band + striped synthwave sun sitting on the horizon."""
        hh = GLOW_HALF_H
        layer = pg.Surface((W, hh * 2))
        band = pg.Surface((W, hh * 2))
        pg.draw.ellipse(band, (255, 255, 255), (-W * 0.15, hh - 26, W * 1.3, 52))
        band = _blur(band, 4, 10)
        band.fill((105, 105, 105), special_flags=pg.BLEND_MULT)
        layer.blit(band, (0, 0), special_flags=pg.BLEND_ADD)

        # Sun: brighter at the top, horizontal slits widening toward the horizon
        sun = pg.Surface((SUN_RADIUS * 2, SUN_RADIUS))
        r = SUN_RADIUS
        for y in range(r):
            half = math.sqrt(max(0.0, r * r - (r - y) ** 2))
            v = int(255 * SUN_BRIGHTNESS * (1.0 - 0.45 * y / r))
            sun.fill((v, v, v), (r - half, y, half * 2, 1))
        for i in range(6):
            gy = int(r * 0.45 + i * r * 0.1)
            sun.fill((0, 0, 0), (0, gy, r * 2, 2 + i))
        sx, sy = W // 2 - r, hh - r
        sun_glow = pg.Surface((W, hh * 2))
        sun_glow.blit(sun, (sx, sy))
        sun_glow = _blur(sun_glow, 4, 8)
        layer.blit(sun_glow, (0, 0), special_flags=pg.BLEND_ADD)
        layer.blit(sun, (sx, sy), special_flags=pg.BLEND_ADD)
        # Nothing of the sun below the horizon line
        layer.fill((0, 0, 0), (0, hh + 1, W, hh), special_flags=pg.BLEND_MULT)
        layer.blit(band, (0, 0), special_flags=pg.BLEND_ADD)
        return _opaque(layer)

    def _build_star_sprites(self) -> list:
        """[size 1..3][level] -> (surface, half)."""
        sprites = [None]
        for size in (1, 2, 3):
            levels = []
            for lv in range(STAR_LEVELS):
                b = (lv + 1) / STAR_LEVELS
                dot = neon.build_glow_circle(size, STAR_COLOR, 0.6, 1.5 + size)
                c = dot.get_width() / 2
                pg.draw.circle(dot, (255, 255, 255, 255), (c, c), max(1.0, size * 0.5))
                dot.fill((int(255 * b),) * 4, special_flags=pg.BLEND_RGBA_MULT)
                levels.append((dot, dot.get_width() // 2))
            sprites.append(levels)
        return sprites

    def _new_star(self, y: float) -> list:
        rnd = self.rng
        size = rnd.choices((1, 2, 3), (70, 24, 6))[0]
        # [x, y, speed px/s, size, base brightness, twinkle phase, twinkle freq]
        return [rnd.uniform(0, W), y, rnd.uniform(3, 9) * size, size,
                rnd.uniform(0.35, 1.0), rnd.uniform(0, math.tau), rnd.uniform(0.6, 2.2)]

    #Accent
    def set_accent(self, color, instant: bool = False) -> None:
        """Blend the accent (grid, horizon, sun) toward `color` over ACCENT_TIME seconds."""
        color = neon.rgb(color)
        if color == self._acc_to and not instant:
            return
        self._acc_from = self.accent
        self._acc_to = color
        self._acc_t = 1.0 if instant else 0.0
        if instant:
            self.accent = color
            self._retint()

    def pulse(self, strength: float = 1.0) -> None:
        """Brief brightening of grid + horizon (level up, big combo)."""
        self._pulse = min(1.5, self._pulse + strength)

    def _retint(self) -> None:
        q = int(self._pulse * 20)               # pulse quantised -> bounded retint rate
        key = (self.accent, q)
        if key == self._tint_key:
            return
        self._tint_key = key
        boost = 1.0 + 0.6 * q / 20
        grid_col = neon.scale_color(self.accent, boost)
        glow_col = neon.scale_color(neon.whiten(self.accent, 0.12), boost)
        self._vert.blit(self._vert_white, (0, 0))
        self._vert.fill(grid_col, special_flags=pg.BLEND_MULT)
        self._glow.blit(self._glow_white, (0, 0))
        self._glow.fill(glow_col, special_flags=pg.BLEND_MULT)

    #Frame
    def update(self, dt: float) -> None:
        self.time += dt
        self._scroll = (self._scroll + dt * self.speed / SCROLL_PERIOD) % 1.0
        if self._acc_t < 1.0:
            self._acc_t = min(1.0, self._acc_t + dt / ACCENT_TIME)
            self.accent = neon.lerp_color(self._acc_from, self._acc_to, _smoothstep(0.0, 1.0, self._acc_t))
        if self._pulse > 0:
            self._pulse = max(0.0, self._pulse - dt * 1.4)
        for s in self._stars:
            s[1] += s[2] * self.speed * dt
            s[0] += s[2] * 0.08 * dt * (1 if s[0] > W / 2 else -1)   # gentle outward drift
            if s[1] > HORIZON_Y or s[0] < -4 or s[0] > W + 4:
                s[:] = self._new_star(-4.0)

    def draw(self, surf: pg.Surface) -> None:
        self._retint()
        surf.blit(self._base, (0, 0))
        self._draw_stars(surf)
        surf.blit(self._glow, (0, HORIZON_Y - GLOW_HALF_H), special_flags=pg.BLEND_ADD)
        self._draw_grid(surf)

    def _draw_stars(self, surf: pg.Surface) -> None:
        t = self.time
        sprites = self._star_sprites
        top = STAR_LEVELS - 1
        blits = self._blits
        blits.clear()
        sin = math.sin
        for x, y, _sp, size, b, ph, f in self._stars:
            b *= 0.7 + 0.3 * sin(t * f + ph)
            if y > HORIZON_Y - 90:
                b *= max(0.0, (HORIZON_Y - y) / 90)
            lv = int(b * top + 0.5)
            if lv <= 0:
                continue
            spr, half = sprites[size][lv]
            blits.append((spr, (x - half, y - half)))
        if blits:
            surf.fblits(blits, pg.BLEND_ADD)

    def _draw_grid(self, surf: pg.Surface) -> None:
        buf = self._grid_buf
        buf.blit(self._vert, (0, 0))
        accent = self.accent
        boost = 1.0 + 0.6 * self._pulse
        line = pg.draw.line
        # Horizontal lines: depth z shrinks as the grid scrolls toward the viewer
        i = 0
        prev_y = None
        while True:
            z = Z_NEAR + (i - self._scroll) * GRID_DZ
            i += 1
            if z < Z_NEAR * 0.999:
                continue
            y = GRID_H * Z_NEAR / z
            if prev_y is not None and prev_y - y < GRID_MIN_GAP:
                break
            prev_y = y
            d = y / GRID_H                                  # 1 at the bottom, -> 0 at the horizon
            b = GRID_BRIGHTNESS * boost * _smoothstep(0.0, 1.0, d) ** 0.8
            iy = int(y)
            if d > 0.25:
                line(buf, neon.scale_color(accent, b * 0.35), (0, iy - 1), (W, iy - 1), 3)
            line(buf, neon.scale_color(neon.whiten(accent, 0.15), b), (0, iy), (W, iy), 1)
        surf.blit(buf, (0, HORIZON_Y), special_flags=pg.BLEND_ADD)
        # Crisp horizon line on top of the glow
        line(surf, neon.scale_color(neon.whiten(accent, 0.3), 0.75 * boost), (0, HORIZON_Y), (W, HORIZON_Y), 1)
