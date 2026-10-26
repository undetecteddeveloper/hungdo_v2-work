"""Pooled additive particles (glow sparks) and expanding shockwave rings.

Motion is closed-form (linear drag + gravity), so update() only advances a clock and the per-particle
work happens once per drawn frame, not once per 1/120 s physics step:
    x(t) = x0 + vx/k * (1 - e^-kt)
    y(t) = y0 + (vy/k - g/k^2) * (1 - e^-kt) + g/k * t
Sprites are tiny pre-rendered glow dots per (colour, size bucket, brightness level), shared by all
systems and blitted in one fblits(BLEND_ADD) call. No Surface is created per particle or per frame.
"""
import math
import random

import pygame as pg

from ..render import neon

MAX_SPRITE_RADIUS = 10              # size buckets 1..10 px
LEVELS = 12                         # brightness steps (fade-out)
DEFAULT_DRAG = 2.4                  # 1/s, linear velocity damping
MAX_RINGS = 16

# Slot field indices (each slot is a reusable list)
_T0, _LIFE, _X0, _Y0, _AX, _BY, _CY, _K, _R, _SET = range(10)

_sprite_sets = {}                   # colour key -> [radius][level] -> (surface, half_size)


def _color_key(color) -> tuple:
    # Quantise so near-identical colours share one sprite set
    return tuple((c >> 2) << 2 for c in neon.rgb(color))


def sprite_set(color) -> list:
    """[radius][level] -> (surface, half_size); level LEVELS-1 is brightest (whitened 'hot' spark)."""
    key = _color_key(color)
    sets = _sprite_sets.get(key)
    if sets is not None:
        return sets
    sets = [None]
    for r in range(1, MAX_SPRITE_RADIUS + 1):
        halo = neon.build_glow_circle(r, key, 0.9, max(2.0, r * 1.3))     # one bloom per radius
        c = halo.get_width() / 2
        levels = []
        for lv in range(LEVELS):
            b = (lv + 1) / LEVELS
            # Freshest sparks run hot (core toward white), then cool to the pure colour while dimming
            dot = halo.copy()
            core = neon.whiten(key, 0.45 + max(0.0, (b - 0.75) * 1.6))
            pg.draw.circle(dot, (*core, 255), (c, c), max(1, r * 0.6))
            if b < 1.0:
                dot.fill((int(255 * b),) * 4, special_flags=pg.BLEND_RGBA_MULT)
            levels.append((dot, dot.get_width() // 2))
        sets.append(levels)
    _sprite_sets[key] = sets
    return sets


def prewarm(colors) -> None:
    """Build sprite sets up front (call during a loading moment to avoid a first-burst hitch)."""
    for c in colors:
        sprite_set(c)


class ParticleSystem:
    def __init__(self, max_particles: int = 600):
        self.max_particles = max(1, int(max_particles))
        self._pool = [[0.0] * 10 for _ in range(self.max_particles)]
        self._n = 0                 # active slots are _pool[:_n]
        self._next_steal = 0        # round-robin victim when the pool is full
        self._sets = []             # sprite sets referenced by slots (index -> set)
        self._set_ids = {}
        self._rings = []
        self._ring_buf = None
        self._blits = []            # reused fblits sequence
        self.time = 0.0
        self.rng = random.Random()

    def __len__(self) -> int:
        return self._n

    @property
    def count(self) -> int:
        return self._n

    def _set_id(self, color) -> int:
        key = _color_key(color)
        sid = self._set_ids.get(key)
        if sid is None:
            sid = len(self._sets)
            self._sets.append(sprite_set(key))
            self._set_ids[key] = sid
        return sid

    def _slot(self) -> list:
        if self._n < self.max_particles:
            slot = self._pool[self._n]
            self._n += 1
            return slot
        # Full: recycle an active particle (round-robin keeps it cheap and fair)
        self._next_steal = (self._next_steal + 1) % self.max_particles
        return self._pool[self._next_steal]

    #Emitters
    def burst(self, pos, color, count: int = 20, speed=(80, 360), life=(0.3, 0.8), size=(2, 5),
              gravity: float = 300, drag: float = DEFAULT_DRAG, angle: float = None, spread: float = math.tau) -> None:
        """Radial spark burst. `angle`/`spread` (radians) make it directional, e.g. angle=-pi/2 for upward."""
        if count <= 0:
            return
        sid = self._set_id(color)
        rnd = self.rng.uniform
        k = max(0.05, float(drag))
        g = float(gravity)
        t0 = self.time
        x0, y0 = float(pos[0]), float(pos[1])
        base = -math.pi / 2 if angle is None else angle
        half = spread / 2
        for _ in range(int(count)):
            a = base + rnd(-half, half) if angle is not None else rnd(0.0, math.tau)
            sp = rnd(speed[0], speed[1])
            vx, vy = math.cos(a) * sp, math.sin(a) * sp
            p = self._slot()
            p[_T0] = t0
            p[_LIFE] = rnd(life[0], life[1])
            p[_X0] = x0
            p[_Y0] = y0
            p[_AX] = vx / k
            p[_BY] = vy / k - g / (k * k)
            p[_CY] = g / k
            p[_K] = k
            p[_R] = rnd(size[0], size[1])
            p[_SET] = sid

    def ring(self, pos, color, radius: float = 60, duration: float = 0.45, width: int = 4) -> None:
        """Expanding shockwave ring (ease-out radius, fading)."""
        if len(self._rings) >= MAX_RINGS:
            self._rings.pop(0)
        self._rings.append([self.time, float(duration), float(pos[0]), float(pos[1]),
                            float(radius), neon.rgb(color), int(width)])
        need = int(radius + width * 3 + 8) * 2
        if self._ring_buf is None or self._ring_buf.get_width() < need:
            self._ring_buf = pg.Surface((need, need))   # black RGB scratch, blitted additively

    #Frame
    def update(self, dt: float) -> None:
        self.time += dt

    def clear(self) -> None:
        self._n = 0
        self._rings.clear()

    def draw(self, surf: pg.Surface) -> None:
        if self._n:
            self._draw_particles(surf)
        if self._rings:
            self._draw_rings(surf)

    def _draw_particles(self, surf: pg.Surface) -> None:
        now = self.time
        pool = self._pool
        sets = self._sets
        blits = self._blits
        blits.clear()
        append = blits.append
        exp = math.exp
        top_level = LEVELS - 1
        max_r = MAX_SPRITE_RADIUS
        n = self._n
        i = 0
        while i < n:
            p = pool[i]
            age = now - p[0]
            life = p[1]
            if age >= life:
                # Dead: swap the last active slot in (slot objects move, values are not copied)
                n -= 1
                pool[i], pool[n] = pool[n], p
                continue
            i += 1
            k = p[7]
            e = 1.0 - exp(-k * age)
            frac = age / life
            fade = 1.0 - frac
            r = int(p[8] * (0.45 + 0.55 * fade) + 0.5)
            if r < 1:
                r = 1
            elif r > max_r:
                r = max_r
            lv = int(fade ** 1.3 * top_level + 0.999)
            spr, half = sets[p[9]][r][lv if lv <= top_level else top_level]
            append((spr, (p[2] + p[4] * e - half, p[3] + p[5] * e + p[6] * age - half)))
        self._n = n
        if blits:
            surf.fblits(blits, pg.BLEND_ADD)

    def _draw_rings(self, surf: pg.Surface) -> None:
        now = self.time
        buf = self._ring_buf
        alive = []
        for ring in self._rings:
            t0, dur, x, y, radius, color, width = ring
            p = (now - t0) / dur
            if p >= 1.0:
                continue
            alive.append(ring)
            if p < 0:
                continue
            ease = 1.0 - (1.0 - p) ** 3
            r = max(2, int(radius * (0.15 + 0.85 * ease)))
            b = (1.0 - p) ** 1.5
            w = max(1, int(round(width * (1.0 - 0.6 * p))))
            pad = width * 3 + 4
            size = (r + pad) * 2
            c = size // 2
            area = pg.Rect(0, 0, size, size)
            buf.fill((0, 0, 0), area)
            # Wide dim halo -> mid -> whitened core: a soft neon tube from three plain circles
            pg.draw.circle(buf, neon.scale_color(color, 0.22 * b), (c, c), r + w, w * 3)
            pg.draw.circle(buf, neon.scale_color(color, 0.55 * b), (c, c), r + w // 2, w * 2)
            pg.draw.circle(buf, neon.scale_color(neon.whiten(color, 0.4), b), (c, c), r, w)
            surf.blit(buf, (int(x) - c, int(y) - c), area, special_flags=pg.BLEND_ADD)
        self._rings = alive
