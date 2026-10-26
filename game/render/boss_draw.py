"""Boss, sweep and player-beam drawing plus hit/death particle effects (neon abstract, all vector).

Crisp polygon/line work sits on cached additive glow sprites (`items.glow_*_at`); sizes and intensities
are quantised so the neon cache stays small. The only scratch surface is the death layer, allocated once
and reused. No fonts are used (the sweep's "!" is geometry), so no `assets` are needed.

Boss fields read (duck typing): kind, colors, pos, half_w, half_h, hp_frac, phase, hit_flash, charge,
enraged, anim_t, death_t.  Sweep: x_from, x_to, width, phase, zone, beam_x, k_warn, k_fire (+ warn_time).
Beam: x, y_from, y_to, width, hit, progress.
"""
import math
import random
from types import SimpleNamespace

import pygame as pg

from .. import config
from ..entities.items import (add_dot, glow_circle_at, glow_rect_at, mix_color, outline,
                              regular_polygon, scale_color)

TAU = math.tau
PAL = config.PALETTE
WHITE = PAL["white"]
RED = PAL["red"]
ORANGE = PAL["orange"]
YELLOW = PAL["yellow"]
CYAN = PAL["cyan"]
ENRAGE_ACC = (255, 170, 70)         # accent colour of an enraged boss (main goes red)
HOT = (255, 240, 205)               # crack / spark colour

GLOW_STEP = 8                       # px, glow sizes are quantised so the neon cache stays small
DEATH_LAYER = (480, 420)            # scratch layer for the death fade (covers body + halos)
DEFAULT_COLORS = (("orange", "yellow"), ("magenta", "cyan"), ("purple", "green"))

_layer = None                       # death scratch surface, created on first use
_stripe_tiles = {}                  # brightness level -> hazard stripe tile


#Small helpers
def _rgb(c) -> tuple:
    """PALETTE key or colour -> (r, g, b) ints."""
    if isinstance(c, str):
        return PAL[c]
    return (int(c[0]), int(c[1]), int(c[2]))


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _q(v: float, step: int = GLOW_STEP) -> int:
    """Quantise a size for the glow cache."""
    return max(step, int(v / step + 0.5) * step)


def _qi(v: float) -> float:
    """Quantise a glow intensity (steps of 0.2, never fully dark)."""
    return max(0.2, round(v * 5.0) / 5.0)


def _hot(col, k: float) -> tuple:
    return mix_color(col, WHITE, k)


def _ipt(p) -> tuple:
    return (int(p[0]), int(p[1]))


class _Ctx:
    """Per-draw state shared by the three boss painters."""
    __slots__ = ("s", "cx", "cy", "hw", "hh", "a", "main", "acc", "fl", "ch", "ph", "enr", "d", "gk")


def _col(c: _Ctx, col) -> tuple:
    """Crisp line colour with the hit flash applied."""
    return mix_color(col, WHITE, c.fl * 0.6) if c.fl > 0.02 else col


def _halo(c: _Ctx, x, y, r, col, k: float) -> None:
    glow_circle_at(c.s, (x, y), _q(r, 6), col, _qi(k * c.gk * 0.7))


def _poly(c: _Ctx, pts, col, fill: float, width: int = 2) -> None:
    if fill:
        pg.draw.polygon(c.s, scale_color(col, fill), pts)
    outline(c.s, _col(c, col), pts, width)


def _charge_rings(c: _Ctx, shape: str) -> None:
    """Energy rings collapsing onto the boss while it charges a volley."""
    if c.ch <= 0.02:
        return
    s, cx, cy = c.s, c.cx, c.cy
    rmax = max(c.hw, c.hh) * 1.3 + 14
    rmin = c.hh * 0.28
    for i in range(3):
        p = (c.a * 1.5 + i / 3.0) % 1.0                  # 0 outer -> 1 inner
        b = c.ch * (4.0 * p * (1.0 - p)) ** 0.6
        if b < 0.06:
            continue
        r = rmax + (rmin - rmax) * p
        col = scale_color(_hot(c.acc, 0.35), b)
        if shape == "hex":
            outline(s, col, regular_polygon(cx, cy, r, 6, c.a * 0.7 + i), 2)
        elif shape == "diamond":
            outline(s, col, [(cx, cy - r * 0.8), (cx + r * 1.25, cy), (cx, cy + r * 0.8), (cx - r * 1.25, cy)], 2)
        else:
            pg.draw.ellipse(s, col, pg.Rect(int(cx - r * 1.2), int(cy - r * 0.8), int(r * 2.4), int(r * 1.6)), 2)


#Death cracks: fixed polylines in unit coordinates (x * half_w, y * half_h), grown with death_t
def _make_cracks() -> list:
    rnd = random.Random(20240)
    cracks = []
    for i in range(8):
        ang = TAU * i / 8 + rnd.uniform(-0.25, 0.25)
        x = y = 0.0
        pts = [(0.0, 0.0)]
        for _ in range(6):
            ang += rnd.uniform(-0.8, 0.8)
            step = rnd.uniform(0.1, 0.17)
            x += math.cos(ang) * step
            y += math.sin(ang) * step
            pts.append((x, y))
        cracks.append(pts)
    return cracks


_CRACKS = _make_cracks()


def _draw_cracks(c: _Ctx) -> None:
    p = _clamp01(c.d / 0.6) * 6.0
    if p <= 0.0:
        return
    s, cx, cy, hw, hh = c.s, c.cx, c.cy, c.hw, c.hh
    whole = int(p)
    frac = p - whole
    for pts in _CRACKS:
        px, py = cx, cy
        for j in range(1, 7):
            if j > whole + 1:
                break
            nx, ny = pts[j]
            qx, qy = cx + nx * hw, cy + ny * hh
            if j == whole + 1:                           # growing tip
                qx, qy = px + (qx - px) * frac, py + (qy - py) * frac
            pg.draw.line(s, scale_color(c.main, 0.7), (px, py), (qx, qy), 4)
            pg.draw.line(s, HOT, (px, py), (qx, qy), 2)
            px, py = qx, qy


#Boss 0: Hex Core (orange / yellow) - nested counter-rotating hexagons in an armoured frame
def _draw_hexcore(c: _Ctx) -> None:
    s, cx, cy, hw, hh, a = c.s, c.cx, c.cy, c.hw, c.hh, c.a
    main, acc, ph = c.main, c.acc, c.ph
    k = min(hh * 0.58, hw * 0.7)
    _halo(c, cx, cy, max(hh * 1.2, hw * 0.7), main, 0.5)
    glow_rect_at(s, (cx, cy), _q(hw * 2), _q(hh * 2), main, radius=_q(hh * 0.5, 4), thickness=3)

    def frame(w, h):
        return [(cx - w, cy), (cx - w + k, cy - h), (cx + w - k, cy - h),
                (cx + w, cy), (cx + w - k, cy + h), (cx - w + k, cy + h)]

    # Phase 3: a second, pulsing outer frame
    if ph >= 3:
        grow = 9 + 3 * math.sin(a * 4)
        pg.draw.aalines(s, scale_color(main, 0.75), True, frame(hw + grow, hh + grow * 0.8))
    fr = frame(hw, hh)
    _poly(c, fr, main, 0.13, 3)
    pg.draw.aalines(s, scale_color(acc, 0.7), True, frame(hw - 9, hh - 9))

    # Counter-rotating hexagon layers
    ang1, ang2, ang3 = a * 0.45, -a * 0.8, a * 1.25
    _poly(c, regular_polygon(cx, cy, hh * 0.82, 6, ang1), acc, 0.10, 2)
    pts2 = regular_polygon(cx, cy, hh * 0.6, 6, ang2)
    pts3 = regular_polygon(cx, cy, hh * 0.38, 6, ang3)
    for p, q in zip(pts2, pts3):                         # spokes shear as the layers turn
        pg.draw.aaline(s, scale_color(acc, 0.6), p, q)
    _poly(c, pts2, main, 0.24, 3)
    node = _col(c, acc)
    for p in pts2:
        pg.draw.circle(s, node, _ipt(p), 3)
    _poly(c, pts3, acc, 0.42, 2)

    # Armour ribs pulsing outward on both wings (only when the frame is wide enough)
    n_ribs = min(3, int((hw - 16 - hh * 0.88) / 9) + 1)
    for i in range(max(0, n_ribs)):
        rh = hh * 0.3 * (1.0 - i * 0.22)
        col = scale_color(main, 0.45 + 0.55 * max(0.0, math.sin(a * 4 - i * 0.9)))
        for sgn in (-1, 1):
            x = cx + sgn * (hh * 0.88 + i * 9)
            pg.draw.line(s, _col(c, col), (x, cy - rh), (x, cy + rh), 3)

    # Phase 2: beads orbiting the frame rim; phase 3: spikes on the frame vertices
    if ph >= 2:
        for i in range(6):
            th = a * 0.9 + i * TAU / 6
            x, y = cx + math.cos(th) * hw * 0.97, cy + math.sin(th) * hh * 1.0
            add_dot(s, (x, y), 6, scale_color(acc, 0.7))
            pg.draw.polygon(s, _col(c, acc), regular_polygon(x, y, 4.5, 6, th))
    if ph >= 3:
        for vx, vy in fr:
            dx, dy = vx - cx, vy - cy
            ln = math.hypot(dx, dy) or 1.0
            dx, dy = dx / ln, dy / ln
            tri = [(vx - dy * 7, vy + dx * 7), (vx + dy * 7, vy - dx * 7), (vx + dx * 17, vy + dy * 17)]
            pg.draw.polygon(s, scale_color(main, 0.6), tri)
            outline(s, _col(c, acc), tri, 1)

    # Glowing core
    pulse = math.sin(a * 6)
    r = hh * 0.17 * (1.0 + 0.12 * pulse + 0.35 * c.ch)
    _halo(c, cx, cy, hh * 0.5, acc, 0.8)
    pg.draw.circle(s, _col(c, _hot(acc, 0.75)), _ipt((cx, cy)), max(3, int(r)))
    _charge_rings(c, "hex")


#Boss 1: Prism (magenta / cyan) - a faceted gem flanked by bobbing rhombi and shards
SHARDS = ((-0.36, -0.74, -math.pi / 2 - 0.3), (0.36, -0.74, -math.pi / 2 + 0.3),
          (-0.36, 0.74, math.pi / 2 + 0.3), (0.36, 0.74, math.pi / 2 - 0.3))


def _draw_prism(c: _Ctx) -> None:
    s, cx, cy, hw, hh, a = c.s, c.cx, c.cy, c.hw, c.hh, c.a
    main, acc, ph = c.main, c.acc, c.ph
    _halo(c, cx, cy, max(hh * 1.15, hw * 0.65), main, 0.6)

    # Outer prism frame (phase 2+) and its breathing twin (phase 3)
    if ph >= 2:
        fw, fh = hw * 1.04, hh * 1.06
        fr = [(cx, cy - fh), (cx + fw, cy), (cx, cy + fh), (cx - fw, cy)]
        outline(s, _col(c, scale_color(acc, 0.8)), fr, 1)
    if ph >= 3:
        b = 0.9 + 0.08 * math.sin(a * 3)
        fr2 = [(cx, cy - hh * 1.06 * b), (cx + hw * 1.04 * b, cy), (cx, cy + hh * 1.06 * b), (cx - hw * 1.04 * b, cy)]
        pg.draw.aalines(s, scale_color(main, 0.8), True, fr2)
        for i, (vx, vy) in enumerate(fr):                # twinkling sparks on the frame tips
            tw = 0.5 + 0.5 * math.sin(a * 5 + i * 1.6)
            add_dot(s, (vx, vy), 5, scale_color(WHITE, 0.4 + 0.5 * tw))

    wings = []
    for sgn in (-1, 1):                                  # side rhombi, bobbing against each other
        wx = cx + sgn * hw * 0.64
        wy = cy + math.sin(a * 1.5 + (0.0 if sgn < 0 else 2.1)) * 5
        wings.append((wx, wy))
        _halo(c, wx, wy, hh * 0.55, acc, 0.35)
        ww, wh = hw * 0.34, hh * 0.66
        top, rgt, bot, lft = (wx, wy - wh), (wx + ww, wy), (wx, wy + wh), (wx - ww, wy)
        glint = 0.5 + 0.5 * math.sin(a * 2.0 + sgn)
        pg.draw.polygon(s, scale_color(acc, 0.14 + 0.2 * glint), [top, rgt, lft])
        pg.draw.polygon(s, scale_color(main, 0.12 + 0.2 * (1 - glint)), [bot, rgt, lft])
        outline(s, _col(c, acc), [top, rgt, bot, lft], 2)
        pg.draw.aaline(s, scale_color(acc, 0.7), lft, rgt)

    shards = []
    for i, (sx, sy, ang0) in enumerate(SHARDS):          # triangular shards, each on its own rhythm
        bob = math.sin(a * 1.7 + i * 1.9)
        x, y = cx + sx * hw, cy + sy * hh + bob * 4 * (1 if sy < 0 else -1)
        shards.append((x, y))
        col = acc if i % 2 == 0 else main
        _halo(c, x, y, hh * 0.32, col, 0.3)
        tri = regular_polygon(x, y, hh * 0.28, 3, ang0 + bob * 0.3)
        _poly(c, tri, col, 0.3, 2)

    # Dispersion rays from the gem to every wing / shard
    for i, (x, y) in enumerate(wings + shards):
        col = main if i % 2 else acc
        pg.draw.aaline(s, scale_color(col, 0.55), (cx, cy), (x, y))

    # Central gem: four facets with a travelling glint
    gw, gh = hw * 0.46, hh * 1.0
    pts = [(cx, cy - gh), (cx + gw, cy), (cx, cy + gh), (cx - gw, cy)]
    for i in range(4):
        glint = max(0.0, math.sin(a * 1.8 - i * 1.1))
        base, lo = (main, 0.2) if i % 2 == 0 else (acc, 0.12)
        pg.draw.polygon(s, scale_color(base, lo + 0.3 * glint), [(cx, cy), pts[i], pts[(i + 1) % 4]])
    outline(s, _col(c, main), pts, 3)
    pg.draw.aaline(s, scale_color(_hot(acc, 0.5), 0.8), (cx, cy - gh * 0.9), (cx, cy + gh * 0.9))
    r = hh * 0.14 * (1.0 + 0.12 * math.sin(a * 5) + 0.4 * c.ch)
    _halo(c, cx, cy, hh * 0.45, _hot(main, 0.3), 0.7)
    pg.draw.circle(s, _col(c, _hot(main, 0.8)), _ipt((cx, cy)), max(3, int(r)))
    _charge_rings(c, "diamond")


#Boss 2: Void Eye (purple / green) - almond eye, concentric iris, roaming pupil, blinking lids
def _lens(cx, cy, hw, hh, o, n: int = 12) -> list:
    top = []
    for i in range(n + 1):
        u = -1.0 + 2.0 * i / n
        top.append((cx + u * hw, cy - hh * o * (1.0 - u * u) ** 0.72))
    return top + [(x, 2 * cy - y) for x, y in reversed(top[1:-1])]


def _draw_eye(c: _Ctx) -> None:
    s, cx, cy, hw, a = c.s, c.cx, c.cy, c.hw, c.a
    hh = min(c.hh, hw * 0.72)                            # keep the lens almond-shaped even in a square hitbox
    main, acc, ph, enr = c.main, c.acc, c.ph, c.enr
    # Blink: the lid closes and reopens in 0.28 s every few seconds
    period = 2.3 if enr else 3.6
    x = (a + 1.1) % period - (period - 0.28)
    blink = (1.0 - abs(2.0 * x / 0.28 - 1.0)) if x > 0 else 0.0
    o = 1.0 - 0.93 * blink

    for dx_, rr in ((-0.5, 0.85), (0.0, 1.0), (0.5, 0.85)):     # lens-shaped aura from three soft discs
        _halo(c, cx + dx_ * hw, cy, hh * rr, main, 0.55)
    # Void rings: rotating arcs around the eye (1 ring, +1 per phase)
    for i in range(c.ph):
        pad = 13 + 12 * i
        rect = pg.Rect(int(cx - hw - pad), int(cy - hh - pad * 0.8), int((hw + pad) * 2), int((hh + pad * 0.8) * 2))
        rot = a * (0.9 - 0.35 * i) * (-1 if i % 2 else 1)
        col = _col(c, acc if i % 2 == 0 else main)
        for j in range(2):
            st = rot + j * math.pi
            pg.draw.arc(s, scale_color(col, 0.85), rect, st, st + 1.15, 2)
    if ph >= 3:                                          # orbs riding the outer ring
        for i in range(3):
            th = a * 0.7 + i * TAU / 3
            ox, oy = cx + math.cos(th) * (hw + 37), cy - math.sin(th) * (hh + 30)
            add_dot(s, (ox, oy), 5, scale_color(acc, 0.8))
            pg.draw.circle(s, _col(c, _hot(acc, 0.6)), _ipt((ox, oy)), 3)

    lens = _lens(cx, cy, hw, hh, o)
    pg.draw.polygon(s, scale_color(main, 0.10), lens)

    look = 1.0 - c.ch * 0.9                              # the gaze locks on while charging
    gx = hw * 0.30 * look * (math.sin(a * 0.8) * 0.65 + math.sin(a * 1.9 + 1.0) * 0.35)
    gy = hh * 0.14 * look * math.sin(a * 1.1 + 0.5)
    ix, iy = cx + gx, cy + gy
    ri = min(hh * 0.8, hw * 0.5)
    _halo(c, ix, iy, ri * 0.7, acc, 0.7 * o)
    # Iris and pupil are clipped to the (blinking) lens band
    old_clip = s.get_clip()
    if o < 0.98:
        band = pg.Rect(int(cx - hw), int(cy - hh * o) - 1, int(hw * 2), int(hh * o * 2) + 3)
        s.set_clip(band.clip(old_clip))
    pg.draw.circle(s, scale_color(main, 0.30), _ipt((ix, iy)), int(ri))
    pg.draw.circle(s, scale_color(main, 0.48), _ipt((ix, iy)), int(ri * 0.7))
    fib = scale_color(main, 0.85)
    rot = a * 0.25
    for i in range(18):                                  # iris fibres
        th = rot + i * TAU / 18
        co, si = math.cos(th), math.sin(th)
        pg.draw.line(s, fib, (ix + co * ri * 0.4, iy + si * ri * 0.4), (ix + co * ri * 0.82, iy + si * ri * 0.82), 1)
    pg.draw.aacircle(s, _col(c, main), _ipt((ix, iy)), int(ri), 3)
    pg.draw.aacircle(s, _col(c, acc), _ipt((ix, iy)), int(ri * 0.8), 1)
    pg.draw.aacircle(s, _col(c, main), _ipt((ix, iy)), int(ri * 0.62), 2)
    rp = ri * (0.30 + 0.16 * c.ch)
    if enr:                                              # angry slit pupil
        pr = pg.Rect(0, 0, int(rp * 0.9), int(rp * 2.6))
        pr.center = _ipt((ix, iy))
        pg.draw.ellipse(s, (6, 0, 10), pr)
        pg.draw.ellipse(s, _col(c, acc), pr, 2)
    else:
        pg.draw.circle(s, (6, 0, 14), _ipt((ix, iy)), int(rp))
        pg.draw.aacircle(s, _col(c, acc), _ipt((ix, iy)), int(rp), 2)
    pg.draw.circle(s, _col(c, WHITE), (int(ix - rp * 0.45), int(iy - rp * 0.5)), max(2, int(rp * 0.22)))
    # Charging: concentric ripples collapse onto the pupil
    if c.ch > 0.02:
        for i in range(3):
            p = (a * 1.5 + i / 3.0) % 1.0
            b = c.ch * (4.0 * p * (1.0 - p)) ** 0.6
            if b >= 0.06:
                rr = int(ri * (1.15 - 0.95 * p))
                pg.draw.aacircle(s, scale_color(_hot(acc, 0.4), b), _ipt((ix, iy)), max(3, rr), 2)
    s.set_clip(old_clip)

    # Lid outline on top: bright rim + inner thin rim
    outline(s, _col(c, main), lens, 3)
    pg.draw.aalines(s, scale_color(acc, 0.75), True, _lens(cx, cy, hw * 0.93, hh * 0.9, o))
    if ph >= 2:                                          # veins running off both corners
        for sgn in (-1, 1):
            tip = (cx + sgn * hw, cy)
            p1 = (tip[0] + sgn * 10, tip[1] - 6)
            p2 = (p1[0] + sgn * 9, p1[1] + 9)
            p3 = (p2[0] + sgn * 12, p2[1] - 5)
            pg.draw.aalines(s, scale_color(main, 0.9), False, [tip, p1, p2, p3])
    # Slow void drops falling from the lower lid
    for i in range(4):
        u = (a * 0.35 + i * 0.25) % 1.0
        add_dot(s, (cx + (i - 1.5) * hw * 0.28, cy + hh * o * 0.8 + u * 34), 3, scale_color(acc, 0.55 * (1.0 - u)))


_PAINTERS = (_draw_hexcore, _draw_prism, _draw_eye)


#Public: boss
def _get_layer() -> pg.Surface:
    global _layer
    if _layer is None:
        _layer = pg.Surface(DEATH_LAYER)
    return _layer


def draw_boss(surf: pg.Surface, boss, t: float, assets=None) -> None:
    """Draw one boss (any state). `t` is app time; the boss' own `anim_t` drives its animation."""
    a = float(getattr(boss, "anim_t", t))
    kind = int(boss.kind) % 3
    colors = getattr(boss, "colors", None) or DEFAULT_COLORS[kind]
    main, acc = _rgb(colors[0]), _rgb(colors[1])
    enr = bool(getattr(boss, "enraged", False))
    ph = max(1, min(3, int(getattr(boss, "phase", 1))))
    d = _clamp01(float(getattr(boss, "death_t", 0.0)))
    fl = _clamp01(float(getattr(boss, "hit_flash", 0.0)))
    ch = _clamp01(float(getattr(boss, "charge", 0.0)))
    if enr:                                              # red-hot, but the accent keeps the identity
        main, acc = mix_color(main, RED, 0.85), mix_color(acc, ENRAGE_ACC, 0.8)
    if ph > 1:                                           # later phases shift toward the accent colour
        main = mix_color(main, acc, 0.12 * (ph - 1))
    pulse = 0.5 + 0.5 * math.sin(a * (9.0 if enr else 3.2))

    c = _Ctx()
    c.a, c.main, c.acc, c.ph, c.enr, c.ch, c.d = a, main, acc, ph, enr, ch, d
    c.fl = max(fl, d * 0.5 + 0.2 * d * math.sin(a * 50.0)) if d > 0 else fl
    c.gk = 1.0 + 0.55 * ch + (0.25 if enr else 0.08) * pulse
    swell = 1.0 + 0.16 * (1.0 - (1.0 - d) ** 3)          # death: the body bloats
    c.hw = float(boss.half_w) * swell
    c.hh = float(boss.half_h) * swell
    amp = (1.4 if enr else 0.0) + 1.6 * ch + 5.0 * d     # tremble: rage, charge, dying
    jx, jy = amp * math.sin(a * 61.0), amp * 0.7 * math.sin(a * 47.0 + 1.3)

    layer = None
    if d > 0.0:                                          # dying: draw onto the layer, fade, add back
        layer = _get_layer()
        layer.fill((0, 0, 0))
        c.s = layer
        c.cx, c.cy = layer.get_width() / 2 + jx, layer.get_height() / 2 + jy
    else:
        c.s = surf
        c.cx, c.cy = boss.pos.x + jx, boss.pos.y + jy

    _PAINTERS[kind](c)
    if c.fl > 0.12:                                      # white-out flash on top of the body
        glow_circle_at(c.s, (c.cx, c.cy), _q(max(c.hw, c.hh) * 0.9, 6), WHITE, _qi(c.fl * 0.5))
    if d > 0.0:
        _draw_cracks(c)
        fade = _clamp01((d - 0.5) / 0.5) ** 1.3
        if fade > 0.0:
            v = int(255 * (1.0 - fade))
            layer.fill((v, v, v), special_flags=pg.BLEND_MULT)
        surf.blit(layer, (int(boss.pos.x - layer.get_width() / 2), int(boss.pos.y - layer.get_height() / 2)),
                  special_flags=pg.BLEND_ADD)


def prewarm_glows_iter(boss):
    """Generator: builds the neon glow sprites this boss needs (normal/enraged, all phases), one draw per step.

    A cold draw costs up to ~20 ms, so spread the steps over several frames of the intro (about 70 steps).
    """
    dummy = pg.Surface((4, 4))
    fields = {k: getattr(boss, k) for k in ("kind", "colors", "half_w", "half_h")}
    for enr in (False, True):
        for ph in (1, 2, 3):
            for ch in (0.0, 1.0):
                for i in range(6):
                    b = SimpleNamespace(**fields, pos=pg.Vector2(0, 0), phase=ph, enraged=enr, charge=ch,
                                        hit_flash=0.0 if i < 5 else 0.9, death_t=0.0, anim_t=i * 0.37, hp_frac=1.0)
                    draw_boss(dummy, b, 0.0)
                    yield


def prewarm_glows(boss) -> None:
    """Build all glow sprites for `boss` at once (about 0.3 s): optional hitch-avoidance before a fight."""
    for _ in prewarm_glows_iter(boss):
        pass


#Sweep
_STRIPE_P = 48                      # px, stripe period along x + y
_TILE = 96                          # tile edge: two periods, so tiles line up seamlessly


def _stripe_tile(level: int) -> pg.Surface:
    tile = _stripe_tiles.get(level)
    if tile is None:
        k = (0.5, 0.8, 1.1)[level]
        tile = pg.Surface((_TILE, _TILE))
        tile.fill(scale_color(ORANGE, 0.12 * k))
        half = _STRIPE_P // 2
        for n in range(_TILE // _STRIPE_P * 2):          # red bands where (x + y) mod period < half
            o = n * _STRIPE_P
            pg.draw.polygon(tile, scale_color(mix_color(RED, ORANGE, 0.45), 0.42 * k), [(o, 0), (o + half, 0), (0, o + half), (0, o)])
        _stripe_tiles[level] = tile
    return tile


def _warn_sign(surf, cx, cy, size, col, pulse: float) -> None:
    """Hazard triangle with a geometric '!' (no font needed)."""
    size *= 1.0 + 0.08 * pulse
    glow_circle_at(surf, (cx, cy), _q(size * 0.75, 6), col, 0.8)
    tri = regular_polygon(cx, cy, size * 0.62, 3, -math.pi / 2)
    pg.draw.polygon(surf, (52, 8, 16), tri)
    outline(surf, mix_color(col, WHITE, 0.25 * pulse), tri, 4)
    bar = pg.Rect(0, 0, max(3, int(size * 0.12)), int(size * 0.38))
    bar.midtop = (int(cx), int(cy - size * 0.30))
    pg.draw.rect(surf, WHITE, bar, border_radius=2)
    pg.draw.circle(surf, WHITE, (int(cx), int(cy + size * 0.21)), max(2, int(size * 0.07)))


def _fill_add(surf, rect, col) -> None:
    surf.fill(col, rect, special_flags=pg.BLEND_ADD)


def draw_sweep(surf: pg.Surface, sweep, boss_bottom: float, t: float) -> None:
    """Warning strip (hazard stripes, accelerating flicker, '!') then the sweeping beam column."""
    phase = sweep.phase
    if phase == "done":
        return
    W, H = surf.get_size()
    y0 = int(boss_bottom)
    h = H - y0
    if h <= 6:
        return
    x0, x1 = sweep.zone
    left, right = max(0, int(x0)), min(W, int(x1 + 0.5))
    if right <= left:
        return
    zone = pg.Rect(left, y0, right - left, h)
    warn = phase == "warn"
    old_clip = surf.get_clip()
    surf.set_clip(pg.Rect(0, y0, W, h).clip(old_clip))               # the strip belongs below the boss
    kw = _clamp01(sweep.k_warn) if warn else 1.0
    kf = 0.0 if warn else _clamp01(sweep.k_fire)

    # Flicker speeds up through the warning (2 Hz -> 10 Hz)
    T = max(0.5, float(getattr(sweep, "warn_time", 1.2)))
    cycles = T * (2.0 * kw + 4.0 * kw * kw)
    flick = 0.5 + 0.5 * math.sin(TAU * cycles)
    strength = (0.55 + 0.45 * kw) if warn else (1.0 - kf) * 0.8
    if strength > 0.02:
        level = 0 if flick < 0.33 else 1 if flick < 0.7 else 2
        base = scale_color(RED, (0.05 + 0.08 * flick) * strength)
        _fill_add(surf, zone, base)
        tile = _stripe_tile(level if warn else 0 if kf > 0.5 else 1)
        old = surf.get_clip()
        surf.set_clip(zone.clip(old))
        ox = zone.x - _TILE + int(t * 70) % _STRIPE_P
        blits = [(tile, (x, y)) for y in range(zone.y - _TILE + int(t * 40) % _STRIPE_P, zone.bottom, _TILE)
                 for x in range(ox, zone.right, _TILE)]
        surf.fblits(blits, pg.BLEND_ADD)
        # Chevrons point where the beam is going
        dx = sweep.x_to - sweep.x_from
        if warn and abs(dx) > 8:
            sgn = 1 if dx > 0 else -1
            col = scale_color(_hot(ORANGE, 0.3), 0.5 + 0.5 * flick)
            cy = y0 + int(h * 0.55)
            sp = 44
            off = (t * 120) % sp * sgn
            xx = zone.x - sp + off
            while xx < zone.right + sp:
                pg.draw.lines(surf, col, False, [(xx - sgn * 9, cy - 16), (xx + sgn * 9, cy), (xx - sgn * 9, cy + 16)], 3)
                xx += sp
        surf.set_clip(old)

        # Edges: stepped glow + bright rim
        edge = (0.3 + 0.7 * (flick if warn else 1.0)) * strength
        for ex in (zone.x, zone.right - 1):
            for wd, k in ((15, 0.14), (8, 0.3), (3, 0.9)):
                _fill_add(surf, pg.Rect(ex - wd // 2, y0, wd, h), scale_color(_hot(RED, 0.3 if wd == 3 else 0.0), k * edge))
        # Where the beam will start (warn only): brightens as the hit gets closer
        if warn:
            w2 = sweep.width / 2
            fx0 = max(0, int(sweep.x_from - w2))
            fx1 = min(W, int(sweep.x_from + w2))
            _fill_add(surf, pg.Rect(fx0, y0, fx1 - fx0, h), scale_color(RED, 0.10 + 0.32 * kw * kw))
            cxm = (zone.x + zone.right) // 2
            _warn_sign(surf, cxm, y0 + 56, 58, ORANGE if flick < 0.5 else RED, flick)

    surf.set_clip(old_clip)
    if not warn:
        _draw_sweep_beam(surf, sweep, y0, H, t, kf)


def _draw_sweep_beam(surf, sweep, y0: int, H: int, t: float, kf: float) -> None:
    W = surf.get_width()
    env = min(1.0, 0.45 + kf / 0.08 * 0.55, 0.6 + (1.0 - kf) * 0.4)     # onset ramp, never weak while lethal
    w = sweep.width * (0.94 + 0.06 * math.sin(t * 58))
    bx = sweep.beam_x
    h = H - y0
    # Swept area stays lit behind the beam
    lx0 = int(min(sweep.x_from, bx) - w / 2)
    lx1 = int(max(sweep.x_from, bx) + w / 2)
    if lx1 > lx0:
        r = pg.Rect(max(0, lx0), y0, min(W, lx1) - max(0, lx0), h)
        _fill_add(surf, r, scale_color(RED, 0.16 * (1.0 - kf)))
    # Soft halo as nested additive columns, then the white-hot core
    for mult, col, k in ((2.1, RED, 0.12), (1.55, RED, 0.22), (1.2, ORANGE, 0.34), (0.8, _hot(ORANGE, 0.45), 0.6),
                         (0.36, WHITE, 1.0)):
        ww = max(2, int(w * mult))
        r = pg.Rect(int(bx - ww / 2), y0, ww, h)
        _fill_add(surf, r, scale_color(col, k * env))
    # Energy dashes racing down the column
    for i in range(5):
        y = y0 + int((t * 1100 + i * 170) % h)
        _fill_add(surf, pg.Rect(int(bx - w * 0.14), y, max(2, int(w * 0.28)), 26), scale_color(WHITE, 0.55 * env))
    # Muzzle flare at the top, scorch line at the bottom
    glow_circle_at(surf, (bx, y0), _q(w * 0.7, 6), _hot(RED, 0.3), _qi(0.9 * env))
    glow_rect_at(surf, (bx, H - 6), _q(w * 1.5, 8), 12, _hot(ORANGE, 0.3), radius=6)
    pg.draw.line(surf, scale_color(WHITE, env), (int(bx - w * 0.32), H - 3), (int(bx + w * 0.32), H - 3), 3)


#Player beam
def draw_beam(surf: pg.Surface, beam, t: float) -> None:
    """Vertical hitscan beam from the paddle up to the boss (or off screen), shrinking and fading."""
    p = _clamp01(float(beam.progress))
    y_from, y_to = int(beam.y_from), int(beam.y_to)
    if y_from <= y_to:
        return
    pe = p ** 0.7
    w = beam.width * (1.1 * (1.0 - pe) + 0.12)
    fade = (1.0 - p) ** 0.8
    x = beam.x
    h = y_from - y_to
    # Nested additive columns: cyan halo -> yellow body -> white core
    for mult, col, k in ((2.4, CYAN, 0.14), (1.7, CYAN, 0.3), (1.2, _hot(CYAN, 0.35), 0.5),
                         (0.75, _hot(YELLOW, 0.35), 0.75), (0.34, WHITE, 1.0)):
        ww = max(2, int(w * mult))
        _fill_add(surf, pg.Rect(int(x - ww / 2), y_to, ww, h), scale_color(col, k * fade))
    pg.draw.line(surf, scale_color(WHITE, fade), (int(x), y_to), (int(x), y_from), 2)
    for sgn in (-1, 1):                                  # crisp rims
        ex = int(x + sgn * w * 0.55)
        pg.draw.line(surf, scale_color(CYAN, 0.9 * fade), (ex, y_to), (ex, y_from), 1)
    # Pulses travelling up the beam
    for i in range(4):
        y = y_from - int((t * 900 + i * 140) % h)
        _fill_add(surf, pg.Rect(int(x - w * 0.5), y, max(2, int(w)), 3), scale_color(WHITE, 0.6 * fade))
    # Muzzle flash at the paddle
    glow_circle_at(surf, (x, y_from), _q(max(10, w * 1.1), 6), _hot(CYAN, 0.4), _qi(fade))
    if beam.hit:
        glow_circle_at(surf, (x, y_to), _q(24 + 20 * (1.0 - p), 6), _hot(YELLOW, 0.5), _qi(fade))
        r = int(10 + 70 * (1.0 - (1.0 - p) ** 2))
        pg.draw.aacircle(surf, scale_color(_hot(YELLOW, 0.5), fade), (int(x), y_to), r, 3)
        pg.draw.aacircle(surf, scale_color(CYAN, 0.8 * fade), (int(x), y_to), int(r * 0.6), 2)
        for i in range(8):                               # starburst
            th = i * TAU / 8 + 0.4
            r0, r1 = r * 0.35, r * (0.7 + 0.5 * ((i % 2) == 0))
            pg.draw.line(surf, scale_color(WHITE, fade), (x + math.cos(th) * r0, y_to + math.sin(th) * r0),
                         (x + math.cos(th) * r1, y_to + math.sin(th) * r1), 2)


#Particle effects
def boss_hit_fx(particles, pos, color, heavy: bool = False) -> None:
    """Sparks where the boss was hit. Beam hit = heavy, ball hit = light."""
    col = _rgb(color)
    if heavy:
        particles.burst(pos, col, 26, speed=(160, 520), life=(0.35, 0.9), size=(2, 5), gravity=420,
                        angle=math.pi / 2, spread=2.6)
        particles.burst(pos, WHITE, 12, speed=(80, 300), life=(0.2, 0.5), size=(1, 3), gravity=0)
        particles.ring(pos, col, 84, 0.5, 5)
        particles.ring(pos, WHITE, 46, 0.3, 3)
    else:
        particles.burst(pos, col, 9, speed=(90, 300), life=(0.25, 0.6), size=(1.5, 4), gravity=380,
                        angle=math.pi / 2, spread=2.4)
        particles.burst(pos, WHITE, 4, speed=(60, 200), life=(0.15, 0.3), size=(1, 2.5), gravity=0)
        particles.ring(pos, col, 34, 0.3, 3)


def boss_death_fx(particles, boss, rng) -> None:
    """One chain-explosion pop somewhere on the body; call about every 0.08 s while the boss dies."""
    d = _clamp01(float(getattr(boss, "death_t", 0.0)))
    hw, hh = float(boss.half_w), float(boss.half_h)
    colors = getattr(boss, "colors", None) or DEFAULT_COLORS[int(boss.kind) % 3]
    pool = (_rgb(colors[0]), _rgb(colors[1]), ORANGE, YELLOW, WHITE)
    px = boss.pos.x + rng.uniform(-hw, hw) * 0.9
    py = boss.pos.y + rng.uniform(-hh, hh) * 0.9
    col = pool[rng.randrange(len(pool))]
    particles.burst((px, py), col, 8 + int(10 * d), speed=(120, 420 + 200 * d), life=(0.4, 1.0), size=(2, 5),
                    gravity=260)
    if rng.random() < 0.45:
        particles.ring((px, py), col, rng.uniform(36, 70) * (1.0 + d), 0.5, 4)
    if rng.random() < 0.3:
        particles.burst((px, py), WHITE, 6, speed=(60, 260), life=(0.15, 0.4), size=(1, 3), gravity=0)
    if d > 0.88:                                         # finale: a big flash at the centre
        particles.burst(boss.pos, WHITE, 24, speed=(200, 760), life=(0.5, 1.2), size=(2, 5), gravity=120)
        particles.ring(boss.pos, WHITE, 150, 0.6, 6)


def prewarm_colors() -> list:
    """Colours the effects use, for `particles.prewarm()`."""
    keys = ("orange", "yellow", "magenta", "cyan", "purple", "green", "red", "white")
    return [PAL[k] for k in keys]
