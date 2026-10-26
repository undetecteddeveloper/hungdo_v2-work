"""Boss fight overlays: intro banner, victory banner and short call-outs (pure drawing helpers).

`k` is the progress of the effect in [0, 1]; PlayScene maps elapsed time to k with the durations below.
Each function eases itself in and out and draws nothing outside (0, 1), so any k is safe to pass.
Boss data is a plain dict (name_key, number, kind, colors) - the same one the HUD gets in state["boss"].
"""
import math

import pygame as pg

from .. import config
from ..i18n import t
from .widgets import clamp, ease_out_back, ease_out_cubic, neon_text, scale_color, translucent_panel

PAL = config.PALETTE

INTRO_TIME = config.BOSS_INTRO_TIME         # k = elapsed / INTRO_TIME for draw_boss_banner
VICTORY_TIME = config.BOSS_VICTORY_TIME     # k = elapsed / VICTORY_TIME for draw_victory_banner
CALLOUT_TIME = 1.4                          # k = elapsed / CALLOUT_TIME for draw_callout

BAND_HALF_H = 70                # half height of the dark band behind the banner text
STRIPE_H = 16                   # hazard stripe strip above/below the band
STRIPE_W = 15                   # one stripe; the pattern repeats every 2 * STRIPE_W
SIDE_PAD = 24                   # min gap between banner text and the canvas edge

_fit_cache = {}
_stripe_cache = {}


#Helpers
def _smooth(x: float) -> float:
    x = clamp(x)
    return x * x * (3 - 2 * x)


def _rgb(c) -> tuple:
    """PALETTE key or RGB tuple -> RGB."""
    if isinstance(c, str):
        return PAL.get(c, PAL["white"])
    return tuple(c[:3])


def _fit_size(assets, s: str, size: int, weight: str, max_w: int, min_size: int = 20) -> int:
    """Largest font size <= size whose text still fits max_w (memoised, no rendering)."""
    key = (s, size, weight, max_w)
    hit = _fit_cache.get(key)
    if hit is not None:
        return hit
    out = size
    while out > min_size and assets.font(out, weight).size(s)[0] > max_w:
        out -= 2
    if len(_fit_cache) > 256:
        _fit_cache.clear()
    _fit_cache[key] = out
    return out


def _blit_alpha(surf, img: pg.Surface, alpha: float, **place) -> None:
    """Blit a (shared, cached) surface at 0..255 alpha, restoring its alpha afterwards. place = Rect kwargs."""
    a = int(clamp(alpha, 0, 255))
    if a <= 0:
        return
    rect = img.get_rect(**place)
    if a >= 255:
        surf.blit(img, rect)
        return
    img.set_alpha(a)
    surf.blit(img, rect)
    img.set_alpha(255)


def _scaled(img: pg.Surface, scale: float) -> pg.Surface:
    return img if abs(scale - 1.0) < 0.015 else pg.transform.smoothscale_by(img, max(0.05, scale))


def _stripes(width: int) -> pg.Surface:
    """Red diagonal hazard stripes (cached per width); wider than the canvas so it can scroll sideways."""
    key = (width, tuple(PAL["red"]))
    surf = _stripe_cache.get(key)
    if surf is None:
        period = STRIPE_W * 2
        w = width + period * 2 + STRIPE_H
        surf = pg.Surface((w, STRIPE_H), pg.SRCALPHA)
        red = (*PAL["red"], 235)
        for x in range(-STRIPE_H, w, period):
            pg.draw.polygon(surf, red, [(x, STRIPE_H), (x + STRIPE_W, STRIPE_H),
                                        (x + STRIPE_W + STRIPE_H, 0), (x + STRIPE_H, 0)])
        if pg.display.get_surface() is not None:
            surf = surf.convert_alpha()
        if len(_stripe_cache) > 6:
            _stripe_cache.clear()
        _stripe_cache[key] = surf
    return surf


def _draw_stripes(surf, cy: int, alpha: float, time_s: float) -> None:
    """Scrolling hazard strips above and below the band (they run in opposite directions)."""
    W = config.LOGICAL_W
    strip = _stripes(W)
    period = STRIPE_W * 2
    off = int(time_s * 90) % period
    top = pg.Rect(0, cy - BAND_HALF_H - STRIPE_H, W, STRIPE_H)
    bot = pg.Rect(0, cy + BAND_HALF_H, W, STRIPE_H)
    a = int(clamp(alpha, 0, 255))
    if a <= 0:
        return
    strip.set_alpha(a if a < 255 else None)
    surf.blit(strip, top, area=pg.Rect(off, 0, W, STRIPE_H))
    surf.blit(strip, bot, area=pg.Rect(period - off, 0, W, STRIPE_H))
    strip.set_alpha(None)


def _draw_band(surf, cy: int, alpha: float, tint=(8, 6, 22)) -> None:
    W = config.LOGICAL_W
    panel = translucent_panel(W, BAND_HALF_H * 2, tint, 200, 0)
    _blit_alpha(surf, panel, alpha, midleft=(0, cy))


def _draw_edge_lines(surf, cy: int, color, grow: float, alpha: float) -> None:
    """Thin accent lines on the band edges that grow from the centre outwards."""
    W = config.LOGICAL_W
    half = int((W - 2 * SIDE_PAD) / 2 * ease_out_cubic(grow))
    if half <= 0 or alpha <= 0:
        return
    col = scale_color(color, clamp(alpha / 255))
    for y in (cy - BAND_HALF_H, cy + BAND_HALF_H):
        pg.draw.line(surf, col, (W // 2 - half, y), (W // 2 + half, y), 3)


def _fmt(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


#Banners
def draw_boss_banner(surf: pg.Surface, assets, boss: dict, k: float) -> None:
    """Intro: blinking red 'WARNING!' between hazard stripes, then 'BOSS n' + the boss name in its colour."""
    if not (0.0 < k < 1.0):
        return
    W = config.LOGICAL_W
    cy = int(config.LOGICAL_H * 0.5)
    time_s = k * INTRO_TIME
    max_w = W - 2 * SIDE_PAD
    cols = boss.get("colors") or ("orange", "yellow")
    color = _rgb(cols[0])

    fade = _smooth(k / 0.07) * (1 - _smooth((k - 0.92) / 0.08))                 # whole banner in/out
    warn = _smooth(k / 0.07) * (1 - _smooth((k - 0.40) / 0.08))                 # warning phase
    name = _smooth((k - 0.48) / 0.06) * (1 - _smooth((k - 0.90) / 0.10))        # boss name phase

    _draw_band(surf, cy, 255 * fade, (24, 6, 16) if warn > 0.02 else (8, 6, 22))
    _draw_stripes(surf, cy, 255 * warn, time_s)
    _draw_edge_lines(surf, cy, color, (k - 0.48) / 0.12, 255 * name)

    if warn > 0.02:
        s = t("boss.warning")
        img = neon_text(assets, s, _fit_size(assets, s, 72, "display", max_w), PAL["red"], "display")
        blink = 0.5 + 0.5 * math.sin(time_s * 15)
        _blit_alpha(surf, img, 255 * warn * (0.35 + 0.65 * blink), center=(W // 2, cy))

    if name > 0.02:
        pop = ease_out_back(clamp((k - 0.50) / 0.12))
        num = neon_text(assets, t("boss.number", n=int(boss.get("number", 1))), 32, PAL["white"], "bold")
        name_key = boss.get("name_key") or f"boss.kind.{int(boss.get('kind', 0))}.name"
        s = t(name_key)
        img = neon_text(assets, s, _fit_size(assets, s, 76, "display", max_w), color, "display")
        _blit_alpha(surf, num, 255 * name, center=(W // 2, cy - 44))
        _blit_alpha(surf, _scaled(img, 0.6 + 0.4 * pop), 255 * name, center=(W // 2, cy + 10))


def draw_victory_banner(surf: pg.Surface, assets, bonus: int, k: float) -> None:
    """'BOSS DEFEATED!' with the bonus counting up under it."""
    if not (0.0 < k < 1.0):
        return
    W = config.LOGICAL_W
    cy = int(config.LOGICAL_H * 0.5)
    max_w = W - 2 * SIDE_PAD
    fade = _smooth(k / 0.10) * (1 - _smooth((k - 0.85) / 0.15))

    _draw_band(surf, cy, 255 * fade * 0.85, (6, 18, 20))
    _draw_edge_lines(surf, cy, PAL["green"], k / 0.2, 255 * fade)

    s = t("boss.defeated")
    img = neon_text(assets, s, _fit_size(assets, s, 68, "display", max_w), PAL["green"], "display")
    pop = ease_out_back(clamp(k / 0.18))
    _blit_alpha(surf, _scaled(img, 0.4 + 0.6 * pop), 255 * fade, center=(W // 2, cy - 18))

    # Count-up in 10 steps (each step is one cached neon text, not one per frame)
    steps = int(round(10 * ease_out_cubic((k - 0.18) / 0.35)))
    shown = int(round(bonus * steps / 10))
    s = t("boss.bonus", points=_fmt(shown))
    bimg = neon_text(assets, s, _fit_size(assets, s, 40, "bold", max_w), PAL["yellow"], "bold")
    _blit_alpha(surf, bimg, 255 * fade * _smooth((k - 0.12) / 0.08), center=(W // 2, cy + 44))


def draw_callout(surf: pg.Surface, assets, text: str, color, k: float, cy: int = None) -> None:
    """Short line near the top ('PHASE 2', 'ENRAGED!', 'BALL LOST!'): pops in, drifts up and fades."""
    if not (0.0 < k < 1.0):
        return
    W = config.LOGICAL_W
    if cy is None:
        cy = int(config.LOGICAL_H * 0.19)
    fade = _smooth(k / 0.10) * (1 - _smooth((k - 0.65) / 0.35))
    drift = int(14 * _smooth((k - 0.5) / 0.5))
    size = _fit_size(assets, text, 46, "display", W - 2 * SIDE_PAD)
    img = neon_text(assets, text, size, _rgb(color), "display")
    pop = ease_out_back(clamp(k / 0.18))
    _blit_alpha(surf, _scaled(img, 0.5 + 0.5 * pop), 255 * fade, center=(W // 2, cy - drift))
