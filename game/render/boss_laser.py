"""Boss laser firing animation. PROTOTYPE: three variants for the Hex Core (A, B, C), one generic pose for the others.

The boss controller publishes `boss.laser` ("" | "aim" | "lock" | "fire"), `boss.laser_k` (0..1 inside that stage) and
`boss.laser_open` (0..1, eased: stays open through the shot, closes afterwards). boss_draw.draw_boss copies them into the
draw context `c` (fields s cx cy hw hh a main acc lz lk lo) and calls `fx(c)` after painting the body.
The beam column itself (warning, lock, fire) is drawn by boss_draw.draw_sweep, starting at the boss's bottom edge.

Variants (pick one, then delete the others):
  A "nong loi"   - hatch in the bottom edge opens, a plasma ball sinks to the port and the rings collapse into it
  B "lang kinh"  - the hexagon layers align and a ringed barrel extends below the boss; a light pulse runs down it
  C "phao canh"  - two wing cannons swing down and converge on a point under the boss, which then fires
"""
import math

import pygame as pg

from ..entities.items import add_dot, glow_circle_at, mix_color, outline, regular_polygon, scale_color

VARIANTS = ("A", "B", "C")
WHITE = (255, 255, 255)
DARK = (20, 8, 12)
GLOW_STEP = 6


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _ease(v: float) -> float:
    v = _clamp01(v)
    return v * v * (3.0 - 2.0 * v)


def _q(v: float, step: int = GLOW_STEP) -> int:
    return max(step, int(v / step + 0.5) * step)


def _hot(col, k: float) -> tuple:
    return mix_color(col, WHITE, k)


def power(lz: str, lk: float, lo: float) -> float:
    """0..1 how charged the laser is: aim 0-0.4, lock 0.4-1, fire 1; after the shot it fades with the closing hatch."""
    if lz == "aim":
        return 0.4 * _clamp01(lk)
    if lz == "lock":
        return 0.4 + 0.6 * _clamp01(lk)
    if lz == "fire":
        return 1.0
    return 0.3 * lo


def recoil(lz: str, lk: float) -> float:
    """Pixels the body is kicked upward right after the shot starts."""
    return 9.0 * (1.0 - _clamp01(lk * 3.0)) ** 2 if lz == "fire" else 0.0


def tremble(lz: str, lk: float) -> float:
    """Extra shake amplitude (px) while the laser charges."""
    return {"aim": 0.6 * lk, "lock": 1.0 + 1.8 * lk, "fire": 1.2}.get(lz, 0.0)


def align_angles(c, angs: tuple, variant: str) -> tuple:
    """Variant B: the three hexagon layers slow down and settle with a vertex pointing down (the barrel axis)."""
    if variant != "B" or c.lo <= 0.01:
        return angs
    k = _ease(c.lo)
    third = math.pi / 3.0
    out = []
    for ang in angs:
        goal = round((ang - math.pi / 2) / third) * third + math.pi / 2
        out.append(ang + (goal - ang) * k)
    return tuple(out)


def fx(c, variant: str = "A") -> None:
    """Paint the firing pose over the body. Does nothing while the cannon is closed."""
    if c.lo <= 0.01 and c.lz == "":
        return
    if c.kind != 0:
        _fx_generic(c)
    elif variant == "B":
        _fx_b(c)
    elif variant == "C":
        _fx_c(c)
    else:
        _fx_a(c)


def _muzzle(c) -> tuple:
    return c.cx, c.cy + c.hh


def _ring(s, color, pts, k: float, width: int = 2) -> None:
    """Outline with brightness k; skipped below 0.2 (drawing is opaque: a dim line would look like a black scratch)."""
    if k >= 0.2:
        outline(s, scale_color(color, min(1.0, k)), pts, width)


def _sparks(c, x, y, r, n: int, k: float) -> None:
    """Short sparks flying inward to (x, y): they sell the charging."""
    for i in range(n):
        p = (c.a * 1.9 + i / n) % 1.0
        ang = i * 2.399 + c.a * 0.3
        d = r * (1.0 - p)
        add_dot(c.s, (x + math.cos(ang) * d, y + math.sin(ang) * d * 0.8), 2, scale_color(_hot(c.acc, 0.5), k * (0.3 + 0.7 * p)))


# --------------------------------------------------------------------------- A: core cannon
def _fx_a(c) -> None:
    s, cx, cy, hw, hh, a = c.s, c.cx, c.cy, c.hw, c.hh, c.a
    lo, pw = _ease(c.lo), power(c.lz, c.lk, c.lo)
    mx, my = _muzzle(c)
    # Hatch: two plates slide apart on the bottom edge and reveal a glowing slot
    slot = hw * 0.8
    gap = slot * 0.75 * lo
    if gap > 1.0:
        inner = scale_color(_hot(c.acc, 0.4), 0.35 + 0.65 * pw)
        pg.draw.rect(s, DARK, pg.Rect(int(mx - gap / 2), int(my - 8), int(gap), 13), border_radius=4)
        pg.draw.rect(s, inner, pg.Rect(int(mx - gap / 2 + 2), int(my - 5), max(1, int(gap - 4)), 7), border_radius=3)
        glow_circle_at(s, (mx, my), _q(gap * 0.6 + 10), c.acc, 0.4 + 0.6 * pw)
    for sgn in (-1, 1):
        x0 = mx + sgn * gap / 2
        x1 = mx + sgn * (gap / 2 + slot * 0.5)
        pts = [(x0, my - 11), (x1, my - 11), (x1 + sgn * 8, my + 7), (x0 + sgn * 3, my + 7)]
        pg.draw.polygon(s, scale_color(c.main, 0.3), pts)
        outline(s, mix_color(c.main, WHITE, 0.25 * pw), pts, 2)
    # Plasma ball sinks from the core to the port
    sink = _ease((pw - 0.25) / 0.55)
    oy = cy + (my - 7 - cy) * sink
    pulse = 0.5 + 0.5 * math.sin(a * 24)
    r = hh * (0.13 + 0.17 * pw) * (1.0 + 0.18 * pulse * (1.0 if c.lz == "fire" else pw))
    glow_circle_at(s, (cx, oy), _q(r * 2.4), c.acc, 0.5 + 0.5 * pw)
    pg.draw.circle(s, _hot(c.acc, 0.35 + 0.5 * pw), (int(cx), int(oy)), max(3, int(r)))
    pg.draw.circle(s, WHITE, (int(cx), int(oy)), max(2, int(r * 0.45)))
    # Rings collapse into the port while the column is locked
    if c.lz in ("lock", "fire"):
        k = 1.0 if c.lz == "fire" else c.lk
        for i in range(3):
            p = (a * 2.4 + i / 3.0) % 1.0
            rr = hh * 1.1 * (1.0 - p) + 5
            _ring(s, _hot(c.acc, 0.4), regular_polygon(mx, my - 4, rr, 6, a * 0.8 + i), (0.3 + 0.9 * k) * (4 * p * (1 - p)) ** 0.7)
        _sparks(c, mx, my - 4, hh * 1.0, 8, 0.4 + 0.6 * k)
    if c.lz == "fire":
        k = _clamp01(c.lk)
        glow_circle_at(s, (mx, my), _q(hh * (0.38 + 0.2 * (1.0 - k))), WHITE, 0.6)
        ring = 12 + 90 * min(1.0, k * 2.5)
        _ring(s, _hot(c.acc, 0.5), regular_polygon(mx, my, ring, 6, 0.0), 1.2 - min(1.0, k * 2.5) * 1.1, 3)


# --------------------------------------------------------------------------- B: focusing barrel
def _squashed_hex(cx, cy, r, squash: float, ang: float = 0.0) -> list:
    return [(x, cy + (y - cy) * squash) for x, y in regular_polygon(cx, cy, r, 6, ang)]


def _fx_b(c) -> None:
    s, cx, cy, hw, hh, a = c.s, c.cx, c.cy, c.hw, c.hh, c.a
    lo, pw = _ease(c.lo), power(c.lz, c.lk, c.lo)
    mx, my = _muzzle(c)
    rings = 5
    length = hh * 1.05 * lo
    base_r = hh * 0.62
    pts = []
    for i in range(rings):
        t = i / (rings - 1)
        y = my - 6 + length * t
        r = base_r * (1.0 - 0.52 * t)
        pts.append((y, r))
    # Barrel walls first, then the rings on top (nearest ring = widest)
    if lo > 0.05:
        left = [(mx - r, y) for y, r in pts]
        right = [(mx + r, y) for y, r in pts]
        pg.draw.polygon(s, scale_color(c.main, 0.22), left + right[::-1])
        pg.draw.aalines(s, scale_color(c.main, 0.8), False, left)
        pg.draw.aalines(s, scale_color(c.main, 0.8), False, right)
        wave = (a * (1.6 + 3.2 * pw)) % 1.0                  # a light pulse running down the barrel
        for i, (y, r) in enumerate(pts):
            t = i / (rings - 1)
            lit = max(0.0, 1.0 - abs(wave - t) * 3.2) * pw
            col = mix_color(scale_color(c.main, 0.65 + 0.35 * pw), WHITE, 0.15 + 0.7 * lit)
            outline(s, col, _squashed_hex(mx, y, r, 0.42), 2)
        yt, rt = pts[-1]
        glow_circle_at(s, (mx, yt), _q(rt * 1.8), c.acc, 0.35 + 0.65 * pw)
    if c.lz in ("lock", "fire"):
        k = 1.0 if c.lz == "fire" else c.lk
        yt, rt = pts[-1]
        pg.draw.ellipse(s, _hot(c.acc, 0.35 + 0.5 * k), pg.Rect(int(mx - rt * 0.8), int(yt - rt * 0.28), int(rt * 1.6), int(rt * 0.56)))
        _sparks(c, mx, yt, hh * 0.9, 7, 0.3 + 0.7 * k)
    if c.lz == "fire":
        k = _clamp01(c.lk)
        yt, rt = pts[-1]
        glow_circle_at(s, (mx, yt), _q(hh * (0.4 + 0.2 * (1.0 - k))), WHITE, 0.6)
        for i in range(rings):                              # the rings flash outward once, like a shockwave
            y, r = pts[i]
            grow = 1.0 + 0.9 * min(1.0, k * 3.0)
            _ring(s, _hot(c.acc, 0.6), _squashed_hex(mx, y, r * grow, 0.42), 1.3 - min(1.0, k * 3.0) * 1.2)


# --------------------------------------------------------------------------- C: twin wing cannons
def _fx_c(c) -> None:
    s, cx, cy, hw, hh, a = c.s, c.cx, c.cy, c.hw, c.hh, c.a
    lo, pw = _ease(c.lo), power(c.lz, c.lk, c.lo)
    mx, my = _muzzle(c)
    focus = (mx, my + hh * 0.95 * (0.3 + 0.7 * lo))        # where the two barrels converge, under the boss
    tips = []
    for sgn in (-1, 1):
        bx, by = cx + sgn * hw * 0.92, cy + hh * 0.3        # pivot on the wing
        rest = math.atan2(1.0, sgn * 0.35)                  # resting: hanging down along the side of the frame
        goal = math.atan2(focus[1] - by, focus[0] - bx)
        d = (goal - rest + math.pi) % math.tau - math.pi
        ang = rest + d * lo
        length = hh * (0.55 + 0.75 * lo)
        ux, uy = math.cos(ang), math.sin(ang)
        px, py = -uy, ux
        wd = hh * 0.2
        tip = (bx + ux * length, by + uy * length)
        quad = [(bx + px * wd, by + py * wd), (tip[0] + px * wd * 0.6, tip[1] + py * wd * 0.6),
                (tip[0] - px * wd * 0.6, tip[1] - py * wd * 0.6), (bx - px * wd, by - py * wd)]
        pg.draw.polygon(s, DARK, quad)
        pg.draw.polygon(s, scale_color(c.main, 0.3), quad)
        outline(s, mix_color(c.main, WHITE, 0.2 * pw), quad, 2)
        pg.draw.circle(s, mix_color(c.main, WHITE, 0.3), (int(bx), int(by)), max(3, int(wd * 0.9)))
        recoil_k = 0.0
        if c.lz == "fire":
            recoil_k = 4.0 * (1.0 - _clamp01(c.lk * 3.0))
        tip = (tip[0] - ux * recoil_k, tip[1] - uy * recoil_k)
        tips.append(tip)
        glow_circle_at(s, tip, _q(wd * 2.0 + 6), c.acc, 0.3 + 0.7 * pw)
    if c.lz in ("lock", "fire") or pw > 0.3:
        k = 1.0 if c.lz == "fire" else _clamp01((pw - 0.3) / 0.7)
        for tip in tips:                                    # thin charge beams from each tip to the focus
            pg.draw.line(s, scale_color(_hot(c.acc, 0.4), 0.3 + 0.6 * k), tip, focus, 2)
            pg.draw.line(s, scale_color(WHITE, 0.2 + 0.5 * k), tip, focus, 1)
        r = hh * (0.08 + 0.2 * k) * (1.0 + 0.2 * math.sin(a * 26))
        glow_circle_at(s, focus, _q(r * 2.6), c.acc, 0.4 + 0.6 * k)
        pg.draw.circle(s, _hot(c.acc, 0.5), (int(focus[0]), int(focus[1])), max(3, int(r)))
        pg.draw.circle(s, WHITE, (int(focus[0]), int(focus[1])), max(2, int(r * 0.5)))
        _sparks(c, focus[0], focus[1], hh * 0.8, 6, 0.3 + 0.7 * k)
    if c.lz == "fire":
        k = _clamp01(c.lk)
        glow_circle_at(s, focus, _q(hh * (0.4 + 0.2 * (1.0 - k))), WHITE, 0.6)


# --------------------------------------------------------------------------- generic pose (other bosses)
def _fx_generic(c) -> None:
    s, cx, cy, hh, a = c.s, c.cx, c.cy, c.hh, c.a
    pw = power(c.lz, c.lk, c.lo)
    mx, my = _muzzle(c)
    glow_circle_at(s, (mx, my), _q(hh * (0.35 + 0.5 * pw)), c.acc, 0.3 + 0.7 * pw)
    if c.lz in ("lock", "fire"):
        k = 1.0 if c.lz == "fire" else c.lk
        for i in range(3):
            p = (a * 2.4 + i / 3.0) % 1.0
            rr = hh * 1.0 * (1.0 - p) + 5
            _ring(s, _hot(c.acc, 0.4), regular_polygon(mx, my, rr, 6, a * 0.8 + i), (0.3 + 0.9 * k) * (4 * p * (1 - p)) ** 0.7)
        pg.draw.circle(s, _hot(c.acc, 0.5 + 0.4 * k), (int(mx), int(my)), max(3, int(hh * 0.14 * (0.5 + 0.5 * k))))
    if c.lz == "fire":
        glow_circle_at(s, (mx, my), _q(hh * (0.4 + 0.2 * (1.0 - _clamp01(c.lk)))), WHITE, 0.6)
