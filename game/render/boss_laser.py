"""Boss laser firing animation: the boss shows where the laser comes from before it fires.

The boss controller publishes `boss.laser` ("" | "aim" | "lock" | "fire"), `boss.laser_k` (0..1 inside that stage) and
`boss.laser_open` (0..1, eased: stays open through the shot, closes afterwards). boss_draw.draw_boss copies them into the
draw context `c` (fields s cx cy hw hh a main acc kind lz lk lo) and calls `fx(c)` after painting the body.
The beam column itself (warning, lock, fire) is drawn by boss_draw.draw_sweep, starting at the boss's bottom edge.

All three bosses use the same idea: two cannons aim at one point just under the boss, charge beams run to it, an orb
grows there, and the column fires from it.
  Hex Core   - two wing cannons swing down from the wings
  Prism      - the two lower shards stretch into spikes and point at the focus
  Void Eye   - the gaze drops to the lower lid and the two corners of the eye cast the charge beams
"""
import math

import pygame as pg

from ..entities.items import add_dot, glow_circle_at, mix_color, outline, scale_color

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
    """0..1 how charged the laser is: aim 0-0.4, lock 0.4-1, fire 1; after the shot it fades with the closing cannons."""
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


def eye_drop(c, hh: float) -> float:
    """Void Eye: how far (px) the iris sinks toward the lower lid while the laser is open."""
    return hh * 0.32 * _ease(c.lo)


def fx(c) -> None:
    """Paint the firing pose over the body. Does nothing while the cannons are closed."""
    if c.lo <= 0.01 and c.lz == "":
        return
    if c.kind == 1:
        _fx_prism(c)
    elif c.kind == 2:
        _fx_eye(c)
    else:
        _fx_hex(c)


def _sparks(c, x, y, r, n: int, k: float) -> None:
    """Short sparks flying inward to (x, y): they sell the charging."""
    for i in range(n):
        p = (c.a * 1.9 + i / n) % 1.0
        ang = i * 2.399 + c.a * 0.3
        d = r * (1.0 - p)
        add_dot(c.s, (x + math.cos(ang) * d, y + math.sin(ang) * d * 0.8), 2, scale_color(_hot(c.acc, 0.5), k * (0.3 + 0.7 * p)))


def _focus(c, tips: list, focus: tuple, pw: float) -> None:
    """Charge beams from the cannon tips to the focus, the orb that grows there and the flash when the laser fires."""
    s, hh, a = c.s, c.hh, c.a
    if c.lz in ("lock", "fire") or pw > 0.3:
        k = 1.0 if c.lz == "fire" else _clamp01((pw - 0.3) / 0.7)
        for tip in tips:
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


def _cannons(c, pivots: list, rest_down: float, length: tuple, focus: tuple, wd: float, taper: float, pw: float) -> list:
    """Draw one cannon per pivot, swinging from hanging down (`rest_down` = sideways lean) to aiming at `focus`.
    Returns the muzzle points. `taper` < 1 narrows the tip (spike), 1 = straight barrel."""
    s, lo = c.s, _ease(c.lo)
    tips = []
    for sgn, (bx, by) in zip((-1, 1), pivots):
        rest = math.atan2(1.0, sgn * rest_down)
        goal = math.atan2(focus[1] - by, focus[0] - bx)
        ang = rest + ((goal - rest + math.pi) % math.tau - math.pi) * lo
        ln = length[0] + length[1] * lo
        ux, uy = math.cos(ang), math.sin(ang)
        px, py = -uy, ux
        tip = (bx + ux * ln, by + uy * ln)
        quad = [(bx + px * wd, by + py * wd), (tip[0] + px * wd * taper, tip[1] + py * wd * taper),
                (tip[0] - px * wd * taper, tip[1] - py * wd * taper), (bx - px * wd, by - py * wd)]
        pg.draw.polygon(s, DARK, quad)
        pg.draw.polygon(s, scale_color(c.main, 0.3), quad)
        outline(s, mix_color(c.main, WHITE, 0.2 * pw), quad, 2)
        pg.draw.circle(s, mix_color(c.main, WHITE, 0.3), (int(bx), int(by)), max(3, int(wd * 0.9)))
        kick = 4.0 * (1.0 - _clamp01(c.lk * 3.0)) if c.lz == "fire" else 0.0
        tip = (tip[0] - ux * kick, tip[1] - uy * kick)
        tips.append(tip)
        glow_circle_at(s, tip, _q(wd * 2.0 + 6), c.acc, 0.3 + 0.7 * pw)
    return tips


# --------------------------------------------------------------------------- Hex Core: twin wing cannons
def _fx_hex(c) -> None:
    cx, cy, hw, hh = c.cx, c.cy, c.hw, c.hh
    lo, pw = _ease(c.lo), power(c.lz, c.lk, c.lo)
    focus = (cx, cy + hh + hh * 0.95 * (0.3 + 0.7 * lo))
    pivots = [(cx + sgn * hw * 0.92, cy + hh * 0.3) for sgn in (-1, 1)]
    tips = _cannons(c, pivots, 0.35, (hh * 0.55, hh * 0.75), focus, hh * 0.2, 0.6, pw)
    _focus(c, tips, focus, pw)


# --------------------------------------------------------------------------- Prism: the lower shards become spikes
def _fx_prism(c) -> None:
    cx, cy, hw, hh = c.cx, c.cy, c.hw, c.hh
    lo, pw = _ease(c.lo), power(c.lz, c.lk, c.lo)
    focus = (cx, cy + hh + hh * 0.9 * (0.3 + 0.7 * lo))
    pivots = [(cx + sgn * hw * 0.36, cy + hh * 0.7) for sgn in (-1, 1)]
    tips = _cannons(c, pivots, 0.2, (hh * 0.35, hh * 0.65), focus, hh * 0.17, 0.12, pw)
    _focus(c, tips, focus, pw)


# --------------------------------------------------------------------------- Void Eye: the corners cast the beams
def _fx_eye(c) -> None:
    s, cx, cy, hw, hh = c.s, c.cx, c.cy, c.hw, c.hh
    lo, pw = _ease(c.lo), power(c.lz, c.lk, c.lo)
    eh = min(hh, hw * 0.72)                                 # the lens is drawn at this half height
    focus = (cx, cy + hh + 14.0 * (0.3 + 0.7 * lo))
    corners = [(cx + sgn * hw, cy) for sgn in (-1, 1)]
    lid = (cx, cy + eh * 0.95)
    # A slit of light opens in the lower lid, the corners glow like muzzles
    if lo > 0.05:
        slit = max(2.0, hw * 0.5 * lo)
        glow_circle_at(s, lid, _q(slit * 1.2 + 8), c.acc, 0.3 + 0.7 * pw)
        pg.draw.ellipse(s, scale_color(_hot(c.acc, 0.4), 0.35 + 0.65 * pw), pg.Rect(int(lid[0] - slit), int(lid[1] - 4), int(slit * 2), 8))
    for tip in corners:
        glow_circle_at(s, tip, _q(12 + 10 * pw), c.acc, 0.3 + 0.7 * pw)
    _focus(c, corners, focus, pw)
    if c.lz in ("lock", "fire"):                            # the slit and the focus are joined by a thin bright thread
        pg.draw.line(s, scale_color(_hot(c.acc, 0.5), 0.5 + 0.5 * pw), lid, focus, 2)
