"""Neon UI widgets: focusable list menus driven by keyboard AND mouse.

Also hosts small shared drawing helpers used by the UI scenes (glow, neon text,
item-like shapes, background/particles factories) with fallbacks for when the
EFFECTS modules are not available.
"""
import logging
import math
import random

import pygame as pg

from .. import config
from ..i18n import t

log = logging.getLogger(config.LOGGER_NAME)

PAL = config.PALETTE

# EFFECTS helpers are optional: every helper below has a plain fallback
try:
    from ..render import neon as _neon
except Exception as _e:      # module missing or broken -> fallback drawing
    _neon = None
    log.info("UI: render.neon unavailable (%s); using fallback glow", _e)

_warned = set()


def _warn_once(key, msg, *args):
    if key not in _warned:
        _warned.add(key)
        log.warning(msg, *args)


#Math & colour helpers

def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def approach(cur: float, target: float, rate: float, dt: float) -> float:
    """Frame-rate independent exponential smoothing toward target."""
    return cur + (target - cur) * (1.0 - math.exp(-rate * dt))


def ease_out_cubic(x: float) -> float:
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_out_back(x: float, s: float = 1.70158) -> float:
    x = clamp(x) - 1
    return 1 + (s + 1) * x ** 3 + s * x ** 2


def lerp_color(a, b, k: float) -> tuple:
    k = clamp(k)
    return (int(a[0] + (b[0] - a[0]) * k), int(a[1] + (b[1] - a[1]) * k), int(a[2] + (b[2] - a[2]) * k))


def scale_color(c, k: float) -> tuple:
    return (min(255, int(c[0] * k)), min(255, int(c[1] * k)), min(255, int(c[2] * k)))


#Glow helpers (cached, built once; drawn additively)

_fx_cache = {}
_FX_CACHE_MAX = 256
GLOW_LEVELS = 8          # intensity steps for dimmed() copies


def _cache_put(key, value):
    if len(_fx_cache) >= _FX_CACHE_MAX:
        _fx_cache.pop(next(iter(_fx_cache)))
    _fx_cache[key] = value
    return value


def _blur(surf: pg.Surface, factor: int = 5) -> pg.Surface:
    """Cheap blur: downscale twice then upscale (built once, never per frame)."""
    w, h = surf.get_size()
    small = pg.transform.smoothscale(surf, (max(1, w // factor), max(1, h // factor)))
    tiny = pg.transform.smoothscale(small, (max(1, w // (factor * 2)), max(1, h // (factor * 2))))
    small = pg.transform.smoothscale(tiny, small.get_size())
    return pg.transform.smoothscale(small, (w, h))


def _ready(surf: pg.Surface, alpha: bool) -> pg.Surface:
    if pg.display.get_init() and pg.display.get_surface() is not None:
        return surf.convert_alpha() if alpha else surf.convert()
    return surf


def glow_rect(w: int, h: int, color, radius: int = 8, thickness: int = 0) -> pg.Surface:
    """Additive glow for a (rounded) rectangle; neon.glow_rect when available."""
    w, h = int(w), int(h)
    if _neon is not None:
        try:
            return _neon.glow_rect(w, h, tuple(color[:3]), radius=radius, thickness=thickness)
        except Exception as e:
            _warn_once("glow_rect", "neon.glow_rect failed (%s); using fallback", e)
    key = ("rect", w, h, tuple(color[:3]), radius, thickness)
    surf = _fx_cache.get(key)
    if surf is None:
        pad = 18
        surf = pg.Surface((w + pad * 2, h + pad * 2))
        surf.fill((0, 0, 0))
        pg.draw.rect(surf, color, (pad, pad, w, h), max(0, thickness * 2), border_radius=radius)
        surf = _blur(surf, 4)
        surf = _cache_put(key, _ready(surf, False))
    return surf


def glow_circle(radius: int, color, intensity: float = 1.0) -> pg.Surface:
    """Additive soft circle; neon.glow_circle when available."""
    radius = max(1, int(radius))
    if _neon is not None:
        try:
            return _neon.glow_circle(radius, tuple(color[:3]), intensity)
        except Exception as e:
            _warn_once("glow_circle", "neon.glow_circle failed (%s); using fallback", e)
    key = ("circle", radius, tuple(color[:3]), round(intensity, 2))
    surf = _fx_cache.get(key)
    if surf is None:
        size = radius * 4
        surf = pg.Surface((size, size))
        surf.fill((0, 0, 0))
        pg.draw.circle(surf, scale_color(color, 0.8 * intensity), (size // 2, size // 2), radius)
        surf = _cache_put(key, _ready(_blur(surf, 4), False))
    return surf


def draw_glow(surf: pg.Surface, glow: pg.Surface, center) -> None:
    """Blit a glow surface additively, centred on `center`."""
    if glow is None:
        return
    if _neon is not None:
        try:
            _neon.draw_glow(surf, glow, center)
            return
        except Exception as e:
            _warn_once("draw_glow", "neon.draw_glow failed (%s); using fallback", e)
    r = glow.get_rect(center=(int(center[0]), int(center[1])))
    surf.blit(glow, r, special_flags=pg.BLEND_ADD)


def dimmed(glow: pg.Surface, k: float):
    """Copy of an additive glow with RGB scaled by k (quantised + cached). None when k≈0."""
    level = int(round(clamp(k) * GLOW_LEVELS))
    if level <= 0 or glow is None:
        return None
    if level >= GLOW_LEVELS:
        return glow
    key = ("dim", id(glow), level)
    hit = _fx_cache.get(key)
    if hit is not None and hit[0] is glow:
        return hit[1]
    out = glow.copy()
    m = int(255 * level / GLOW_LEVELS)
    out.fill((m, m, m), special_flags=pg.BLEND_RGB_MULT)
    _cache_put(key, (glow, out))      # keep source alive so id() stays unique
    return out


def neon_text(assets, s: str, size: int, color, weight: str = "bold") -> pg.Surface:
    """Text with a soft glow halo (alpha surface); neon.neon_text when available."""
    if _neon is not None:
        try:
            return _neon.neon_text(assets, s, size, tuple(color[:3]), weight)
        except Exception as e:
            _warn_once("neon_text", "neon.neon_text failed (%s); using fallback", e)
    key = ("ntext", s, int(size), tuple(color[:3]), weight)
    surf = _fx_cache.get(key)
    if surf is None:
        core = assets.text(s, size, color, weight)
        pad = max(6, size // 3)
        w, h = core.get_width() + pad * 2, core.get_height() + pad * 2
        halo = pg.Surface((w, h), pg.SRCALPHA)
        halo.blit(core, (pad, pad))
        halo = _blur(halo, 4)
        surf = pg.Surface((w, h), pg.SRCALPHA)
        surf.blit(halo, (0, 0))
        surf.blit(halo, (0, 0))
        surf.blit(core, (pad, pad))
        surf = _cache_put(key, _ready(surf, True))
    return surf


def text_glow_layer(assets, s: str, size: int, color, weight: str = "display", spread: int = 4) -> pg.Surface:
    """Additive (RGB on black) blurred copy of a text, for pulsing title glows."""
    key = ("tglow", s, int(size), tuple(color[:3]), weight, spread)
    surf = _fx_cache.get(key)
    if surf is None:
        core = assets.text(s, size, color, weight)
        pad = size // 2
        w, h = core.get_width() + pad * 2, core.get_height() + pad * 2
        base = pg.Surface((w, h))
        base.fill((0, 0, 0))
        base.blit(core, (pad, pad))
        surf = _cache_put(key, _ready(_blur(base, spread), False))
    return surf


def translucent_panel(w: int, h: int, color, alpha: int, radius: int = 14) -> pg.Surface:
    """Cached alpha-filled rounded rect (for panels/rows)."""
    key = ("panel", int(w), int(h), tuple(color[:3]), int(alpha), radius)
    surf = _fx_cache.get(key)
    if surf is None:
        surf = pg.Surface((max(1, int(w)), max(1, int(h))), pg.SRCALPHA)
        pg.draw.rect(surf, (*color[:3], int(alpha)), surf.get_rect(), border_radius=radius)
        surf = _cache_put(key, _ready(surf, True))
    return surf


def dim_backdrop(alpha: int = 170) -> pg.Surface:
    """Full-canvas translucent dark layer for overlays (cached)."""
    key = ("backdrop", alpha, config.LOGICAL_SIZE)
    surf = _fx_cache.get(key)
    if surf is None:
        surf = pg.Surface(config.LOGICAL_SIZE, pg.SRCALPHA)
        surf.fill((4, 4, 16, alpha))
        surf = _cache_put(key, _ready(surf, True))
    return surf


#Item-like shapes (menu demo + howto fallback)

def shape_points(kind: str, center, r: float, angle: float = 0.0) -> list:
    """Polygon points for 'diamond', 'star', 'hexagon', 'spiky', 'triangle'."""
    cx, cy = center
    pts = []
    if kind == "diamond":
        for i in range(4):
            a = angle + i * math.pi / 2
            rr = r if i % 2 == 0 else r * 0.78
            pts.append((cx + math.sin(a) * rr, cy - math.cos(a) * rr))
    elif kind == "star":
        for i in range(10):
            a = angle + i * math.pi / 5
            rr = r if i % 2 == 0 else r * 0.45
            pts.append((cx + math.sin(a) * rr, cy - math.cos(a) * rr))
    elif kind == "spiky":
        for i in range(12):
            a = angle + i * math.pi / 6
            rr = r if i % 2 == 0 else r * 0.72
            pts.append((cx + math.sin(a) * rr, cy - math.cos(a) * rr))
    elif kind == "triangle":
        for i in range(3):
            a = angle + i * 2 * math.pi / 3
            pts.append((cx + math.sin(a) * r, cy - math.cos(a) * r))
    else:  # hexagon
        for i in range(6):
            a = angle + i * math.pi / 3
            pts.append((cx + math.cos(a) * r, cy + math.sin(a) * r))
    return pts


KIND_COLORS = {
    "common": PAL["cyan"], "rare": PAL["magenta"], "epic": PAL["yellow"],
    "bomb": PAL["red"], "powerup": PAL["green"],
}
try:        # keep HUD/menu colours identical to the real items
    from ..entities.items import POWER_COLORS
except Exception:
    POWER_COLORS = {
        "magnet": PAL["purple"], "slow": (70, 150, 255), "wide": PAL["green"],
        "shield": PAL["cyan"], "heart": PAL["red"],
    }


def draw_item_shape(surf, kind: str, center, r: float, t: float = 0.0, angle: float = 0.0,
                    power: str = None, assets=None, brightness: float = 1.0, glow: bool = True) -> None:
    """Flat neon shape for an item kind (used when entities.items is unavailable)."""
    cx, cy = int(center[0]), int(center[1])
    base = POWER_COLORS.get(power, PAL["green"]) if kind == "powerup" else KIND_COLORS.get(kind, PAL["cyan"])
    color = scale_color(base, brightness)
    core = scale_color(base, 0.22 * brightness)
    if glow:
        draw_glow(surf, dimmed(glow_circle(int(r), base), 0.55 * brightness), (cx, cy))
    if kind == "common":
        pg.draw.circle(surf, core, (cx, cy), int(r))
        pg.draw.circle(surf, color, (cx, cy), int(r), 3)
        pg.draw.circle(surf, scale_color(PAL["white"], brightness), (cx - int(r * 0.3), cy - int(r * 0.3)), max(2, int(r * 0.18)))
    elif kind in ("rare", "epic"):
        pts = shape_points("diamond" if kind == "rare" else "star", (cx, cy), r, angle)
        pg.draw.polygon(surf, core, pts)
        pg.draw.polygon(surf, color, pts, 3)
    elif kind == "bomb":
        pts = shape_points("spiky", (cx, cy), r, angle)
        pg.draw.polygon(surf, core, pts)
        pg.draw.polygon(surf, color, pts, 3)
        pulse = 0.5 + 0.5 * math.sin(t * 8)
        pg.draw.circle(surf, lerp_color(scale_color(PAL["orange"], brightness), scale_color(PAL["yellow"], brightness), pulse),
                       (cx, cy), max(3, int(r * (0.3 + 0.1 * pulse))))
    else:  # powerup
        side = int(r * 1.8)
        rect = pg.Rect(0, 0, side, side)
        rect.center = (cx, cy)
        pg.draw.rect(surf, core, rect, border_radius=side // 4)
        pg.draw.rect(surf, color, rect, 3, border_radius=side // 4)
        icon = assets.icon(power, scale_color(PAL["white"], brightness), int(side * 0.62)) if (assets and power) else None
        if icon is not None:
            surf.blit(icon, icon.get_rect(center=(cx, cy)))
        elif assets is not None and power:
            letter = assets.text(power[:1].upper(), int(side * 0.6), color, "black")
            surf.blit(letter, letter.get_rect(center=(cx, cy)))


def draw_heart(surf, center, size: int, color, filled: bool = True) -> None:
    """Procedural heart (fallback when the heart icon is missing)."""
    cx, cy = center
    r = size * 0.27
    w = 0 if filled else 2
    left, right = (cx - r * 0.95, cy - r * 0.35), (cx + r * 0.95, cy - r * 0.35)
    pts = [(cx - r * 1.9, cy - r * 0.15), (cx, cy + size * 0.42), (cx + r * 1.9, cy - r * 0.15)]
    if filled:
        pg.draw.circle(surf, color, left, r)
        pg.draw.circle(surf, color, right, r)
        pg.draw.polygon(surf, color, pts)
    else:
        pg.draw.circle(surf, color, left, r, w, draw_top_left=True, draw_top_right=True)
        pg.draw.circle(surf, color, right, r, w, draw_top_left=True, draw_top_right=True)
        pg.draw.lines(surf, color, False, pts, w)


ARROW_DIRS = {"←": (-1, 0), "→": (1, 0), "↑": (0, -1), "↓": (0, 1)}


def draw_keycap(surf, assets, label: str, topleft, size: int = 22, color=None) -> pg.Rect:
    """Small outlined key 'chip' (controls help); returns its rect."""
    color = color or PAL["cyan"]
    arrow = ARROW_DIRS.get(label)
    txt = None if arrow else assets.text(label, size, PAL["white"], "bold")
    w = size + 10 if arrow else max(txt.get_width() + 16, size + 10)
    rect = pg.Rect(topleft[0], topleft[1], w, size + 10)
    surf.blit(translucent_panel(rect.w, rect.h, color, 40, 6), rect)
    pg.draw.rect(surf, color, rect, 2, border_radius=6)
    if arrow:   # the fonts have no arrow glyphs: draw a triangle
        cx, cy = rect.center
        dx, dy = arrow
        k = size * 0.3
        tip = (cx + dx * k, cy + dy * k)
        base = [(cx - dx * k + dy * k, cy - dy * k + dx * k), (cx - dx * k - dy * k, cy - dy * k - dx * k)]
        pg.draw.polygon(surf, PAL["white"], [tip] + base)
    else:
        surf.blit(txt, txt.get_rect(center=rect.center))
    return rect


#Background & particles factories (EFFECTS with fallbacks)

class FallbackBackground:
    """Plain gradient + drifting dots; same API as render.background.Background."""

    def __init__(self, app=None):
        w, h = config.LOGICAL_SIZE
        self.base = pg.Surface((w, h))
        top, bot = PAL["bg_top"], PAL["bg_bottom"]
        for y in range(h):
            pg.draw.line(self.base, lerp_color(top, bot, y / (h - 1)), (0, y), (w, y))
        self.base = _ready(self.base, False)
        rng = random.Random(7)
        self.stars = [[rng.uniform(0, w), rng.uniform(0, h), rng.uniform(6, 22), rng.randint(60, 150)]
                      for _ in range(60)]
        self.accent = PAL["cyan"]
        self.target = PAL["cyan"]

    def set_accent(self, rgb, instant: bool = False) -> None:
        self.target = tuple(rgb[:3])
        if instant:
            self.accent = self.target

    def update(self, dt: float) -> None:
        self.accent = lerp_color(self.accent, self.target, 1 - math.exp(-dt * 2.5))
        h = config.LOGICAL_H
        for s in self.stars:
            s[1] += s[2] * dt
            if s[1] > h:
                s[1] -= h

    def draw(self, surf: pg.Surface) -> None:
        surf.blit(self.base, (0, 0))
        for x, y, _, b in self.stars:
            surf.fill((b, b, min(255, b + 40)), (int(x), int(y), 2, 2))
        # Horizon line in the accent colour
        y = config.LOGICAL_H - 150
        pg.draw.line(surf, scale_color(self.accent, 0.45), (0, y), (config.LOGICAL_W, y), 2)


def make_background(app):
    """render.background.Background(app) or a plain fallback."""
    try:
        from ..render.background import Background
        return Background(app)
    except Exception as e:
        _warn_once("bg", "UI: render.background unavailable (%s); using fallback", e)
        return FallbackBackground(app)


def make_particles(max_particles: int = 400):
    """systems.particles.ParticleSystem or None."""
    try:
        from ..systems.particles import ParticleSystem
        return ParticleSystem(max_particles=max_particles)
    except Exception as e:
        _warn_once("particles", "UI: particles unavailable (%s)", e)
        return None


#Widgets

ACCENT = PAL["cyan"]
UP_KEYS = (pg.K_w, pg.K_UP)
DOWN_KEYS = (pg.K_s, pg.K_DOWN)
LEFT_KEYS = (pg.K_a, pg.K_LEFT)
RIGHT_KEYS = (pg.K_d, pg.K_RIGHT)
ACTIVATE_KEYS = (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE)
BACK_KEYS = (pg.K_ESCAPE,)

REPEAT_DELAY = 0.38
REPEAT_RATE = 0.065


def _resolve(label) -> str:
    return label() if callable(label) else str(label)


class Widget:
    """Base row. Menu assigns `rect`; `focus_anim` eases 0..1 while focused."""

    def __init__(self, label_key: str):
        self.label_key = label_key
        self.rect = pg.Rect(0, 0, 0, 0)
        self.focus_anim = 0.0
        self.flash = 0.0            # activation flash (1 -> 0)

    @property
    def label(self) -> str:
        return t(self.label_key)

    #Interaction (return True when something changed)
    def activate(self) -> bool:
        return False

    def change(self, delta: int) -> bool:
        return False

    def press(self, pos) -> str:
        """Mouse down on this row: 'activate' | 'change' | 'drag' | None."""
        return None

    def drag(self, pos) -> bool:
        return False

    def update(self, dt: float) -> None:
        self.flash = max(0.0, self.flash - dt * 3.0)

    def control_rect(self, menu) -> pg.Rect:
        """Right part of the row that holds the value/control."""
        w = min(menu.control_w, self.rect.w // 2)
        return pg.Rect(self.rect.right - 14 - w, self.rect.y, w, self.rect.h)

    def draw_control(self, surf, menu, f: float) -> None:
        pass


class Button(Widget):
    def __init__(self, label_key: str, on_click, sound: str = "ui_select", color=None):
        super().__init__(label_key)
        self.on_click = on_click
        self.sound = sound
        self.color = color

    def activate(self) -> bool:
        self.flash = 1.0
        if self.on_click:
            self.on_click()
        return True

    def press(self, pos) -> str:
        return "activate"

    def draw_control(self, surf, menu, f):
        # Chevron on the right in row style
        if menu.style != "row":
            return
        cx, cy = self.rect.right - 26 + int(4 * f), self.rect.centery
        col = lerp_color(PAL["dim"], menu.accent_for(self), f)
        pg.draw.lines(surf, col, False, [(cx - 5, cy - 8), (cx + 3, cy), (cx - 5, cy + 8)], 3)


class Toggle(Widget):
    def __init__(self, label_key: str, get, set):
        super().__init__(label_key)
        self.get = get
        self.set = set
        self.anim = 1.0 if get() else 0.0

    def activate(self) -> bool:
        self.set(not bool(self.get()))
        self.flash = 1.0
        return True

    def change(self, delta: int) -> bool:
        want = delta > 0
        if bool(self.get()) == want:
            return False
        self.set(want)
        return True

    def press(self, pos) -> str:
        return "activate"

    def update(self, dt):
        super().update(dt)
        self.anim = approach(self.anim, 1.0 if self.get() else 0.0, 16, dt)

    def draw_control(self, surf, menu, f):
        on = self.anim
        accent = menu.accent_for(self)
        w, h = 58, 28
        rect = pg.Rect(0, 0, w, h)
        rect.midright = (self.rect.right - 18, self.rect.centery)
        track = lerp_color((40, 44, 78), scale_color(accent, 0.45), on)
        pg.draw.rect(surf, track, rect, border_radius=h // 2)
        pg.draw.rect(surf, lerp_color(PAL["dim"], accent, max(on, f * 0.6)), rect, 2, border_radius=h // 2)
        kx = rect.x + h // 2 + (w - h) * on
        if on > 0.5:
            draw_glow(surf, dimmed(glow_circle(10, accent), on), (kx, rect.centery))
        pg.draw.circle(surf, lerp_color(PAL["dim"], PAL["white"], on), (int(kx), rect.centery), h // 2 - 4)
        label = t("ui.on") if self.get() else t("ui.off")
        txt = menu.assets.text(label, menu.value_size, lerp_color(PAL["dim"], PAL["white"], on), "bold")
        surf.blit(txt, txt.get_rect(midright=(rect.x - 10, rect.centery)))


class Selector(Widget):
    """Cycles through options [(value, label)]; label may be a str or a callable.

    `options` may also be a callable returning that list (re-evaluated each use).
    """

    def __init__(self, label_key: str, options, get, set, wrap: bool = True):
        super().__init__(label_key)
        self._options = options
        self.get = get
        self.set = set
        self.wrap = wrap
        self.slide = 0.0            # value change animation (-1..1 -> 0)

    @property
    def options(self) -> list:
        opts = self._options() if callable(self._options) else self._options
        return list(opts)

    def index(self, opts=None) -> int:
        opts = self.options if opts is None else opts
        cur = self.get()
        for i, (v, _) in enumerate(opts):
            if v == cur:
                return i
        return -1

    def value_label(self) -> str:
        opts = self.options
        i = self.index(opts)
        if i < 0:
            return str(self.get())
        return _resolve(opts[i][1])

    def change(self, delta: int) -> bool:
        opts = self.options
        if not opts:
            return False
        i = self.index(opts)
        if i < 0:
            i = 0 if delta > 0 else len(opts) - 1
        else:
            j = i + delta
            if self.wrap:
                j %= len(opts)
            else:
                j = max(0, min(len(opts) - 1, j))
            if j == i:
                return False
            i = j
        self.set(opts[i][0])
        self.slide = -1.0 if delta > 0 else 1.0
        return True

    def activate(self) -> bool:
        return self.change(1)

    def press(self, pos) -> str:
        ctrl = self.control_rect(self._menu) if hasattr(self, "_menu") else self.rect
        if ctrl.collidepoint(pos) and pos[0] < ctrl.centerx:
            self._pending_delta = -1
        else:
            self._pending_delta = 1
        return "change"

    def update(self, dt):
        super().update(dt)
        self.slide = approach(self.slide, 0.0, 18, dt)

    def draw_control(self, surf, menu, f):
        ctrl = self.control_rect(menu)
        accent = menu.accent_for(self)
        col = lerp_color(PAL["dim"], accent, 0.35 + 0.65 * f)
        cy = ctrl.centery
        # Arrows
        lx, rx = ctrl.x + 10, ctrl.right - 10
        pg.draw.polygon(surf, col, [(lx, cy), (lx + 9, cy - 8), (lx + 9, cy + 8)])
        pg.draw.polygon(surf, col, [(rx, cy), (rx - 9, cy - 8), (rx - 9, cy + 8)])
        txt = menu.assets.text(self.value_label(), menu.value_size, PAL["white"], "bold")
        # Squeeze long values into the control area
        max_w = ctrl.w - 44
        if txt.get_width() > max_w:
            txt = menu.assets.text(self.value_label(), max(12, menu.value_size - 4), PAL["white"], "bold")
        off = int(self.slide * 14)
        surf.blit(txt, txt.get_rect(center=(ctrl.centerx + off, cy)))


class Slider(Widget):
    """0..1 value; keys move by `step`, mouse drag moves in 5% steps."""

    DRAG_STEP = 0.05

    def __init__(self, label_key: str, get, set, step: float = 0.1):
        super().__init__(label_key)
        self.get = get
        self.set = set
        self.step = step
        self.shown = float(get())

    def _set(self, v: float) -> bool:
        v = round(clamp(v), 3)
        if abs(v - float(self.get())) < 1e-6:
            return False
        self.set(v)
        return True

    def change(self, delta: int) -> bool:
        v = float(self.get()) + delta * self.step
        v = round(v / self.step) * self.step       # snap to the step grid
        return self._set(v)

    def track_rect(self, menu) -> pg.Rect:
        ctrl = self.control_rect(menu)
        tr = pg.Rect(0, 0, ctrl.w - 74, 8)
        tr.midright = (ctrl.right - 8, ctrl.centery)
        return tr

    def press(self, pos) -> str:
        return "drag"

    def drag(self, pos) -> bool:
        tr = self.track_rect(self._menu)
        v = (pos[0] - tr.x) / max(1, tr.w)
        v = round(clamp(v) / self.DRAG_STEP) * self.DRAG_STEP
        return self._set(v)

    def update(self, dt):
        super().update(dt)
        self.shown = approach(self.shown, float(self.get()), 20, dt)

    def draw_control(self, surf, menu, f):
        accent = menu.accent_for(self)
        tr = self.track_rect(menu)
        v = clamp(self.shown)
        pg.draw.rect(surf, (40, 44, 78), tr, border_radius=4)
        fill = tr.copy()
        fill.w = max(0, int(tr.w * v))
        if fill.w > 0:
            pg.draw.rect(surf, lerp_color(scale_color(accent, 0.6), accent, f), fill, border_radius=4)
        kx = tr.x + int(tr.w * v)
        if f > 0.05:
            draw_glow(surf, dimmed(glow_circle(11, accent), f), (kx, tr.centery))
        pg.draw.circle(surf, PAL["white"], (kx, tr.centery), 9)
        pg.draw.circle(surf, accent, (kx, tr.centery), 9, 2)
        pct = menu.assets.text(f"{int(round(float(self.get()) * 100))}%", menu.value_size, PAL["white"], "bold")
        surf.blit(pct, pct.get_rect(midright=(tr.x - 14, tr.centery)))


class Menu:
    """Vertical list of widgets.

    style "center": centred labels (main menu / pause buttons);
    style "row": label left + control right (settings). Auto: "row" if any non-Button.
    """

    def __init__(self, widgets, center_x: int, top_y: int, spacing: int, *, app=None,
                 width: int = 360, row_height: int = None, font_size: int = 30, value_size: int = None,
                 style: str = None, on_back=None, accent=None, control_w: int = 220, wrap: bool = True):
        self.widgets = list(widgets)
        self.center_x = center_x
        self.top_y = top_y
        self.spacing = spacing
        self.app = app
        self.width = width
        self.row_height = row_height or max(24, spacing - 12)
        self.font_size = font_size
        self.value_size = value_size or max(18, font_size - 6)
        self.style = style or ("center" if all(isinstance(w, Button) for w in self.widgets) else "row")
        self.on_back = on_back
        self.accent = accent or ACCENT
        self.control_w = control_w
        self.wrap = wrap
        self.focus = 0
        self.dragging = None
        self.enabled = True
        self._held = None           # (key, delta) for hold-to-repeat
        self._held_t = 0.0
        self._fallback_assets = None
        for w in self.widgets:
            w._menu = self
        self.layout()

    #Services
    @property
    def assets(self):
        if self.app is not None:
            return self.app.assets
        if self._fallback_assets is None:
            from ..assets import Assets
            self._fallback_assets = Assets()
        return self._fallback_assets

    def sound(self, name: str) -> None:
        if self.app is not None and getattr(self.app, "audio", None) is not None:
            self.app.audio.play(name)

    def accent_for(self, w) -> tuple:
        return getattr(w, "color", None) or self.accent

    #Layout
    def layout(self) -> None:
        for i, w in enumerate(self.widgets):
            r = pg.Rect(0, 0, self.width, self.row_height)
            r.midtop = (self.center_x, self.top_y + i * self.spacing)
            w.rect = r

    @property
    def bottom(self) -> int:
        return self.top_y + (len(self.widgets) - 1) * self.spacing + self.row_height

    def reset(self, focus: int = 0) -> None:
        """Call from Scene.on_enter: clears drag/hold state and snaps animations."""
        self.focus = max(0, min(focus, len(self.widgets) - 1))
        self.dragging = None
        self._held = None
        for i, w in enumerate(self.widgets):
            w.focus_anim = 1.0 if i == self.focus else 0.0
            w.flash = 0.0

    @property
    def focused(self):
        return self.widgets[self.focus] if self.widgets else None

    def set_focus(self, i: int, sound: bool = True) -> None:
        if not self.widgets:
            return
        i = max(0, min(i, len(self.widgets) - 1))
        if i != self.focus:
            self.focus = i
            if sound:
                self.sound("ui_move")

    def move(self, delta: int) -> None:
        if not self.widgets:
            return
        n = len(self.widgets)
        i = self.focus + delta
        i = i % n if self.wrap else max(0, min(n - 1, i))
        self.set_focus(i)

    def hit(self, pos):
        if pos is None:
            return None
        for i, w in enumerate(self.widgets):
            if w.rect.collidepoint(pos):
                return i
        return None

    #Actions
    def _change(self, delta: int) -> bool:
        w = self.focused
        if w is not None and w.change(delta):
            self.sound("ui_move")
            return True
        return False

    def _activate(self) -> None:
        w = self.focused
        if w is None:
            return
        snd = getattr(w, "sound", "ui_select")
        if w.activate():
            self.sound(snd)

    #Events
    def handle_event(self, event) -> bool:
        """Returns True if the event was consumed."""
        if not self.enabled or not self.widgets:
            return False
        et = event.type
        if et == pg.KEYDOWN:
            k = event.key
            if k in UP_KEYS:
                self.move(-1)
                return True
            if k in DOWN_KEYS:
                self.move(1)
                return True
            if k in LEFT_KEYS or k in RIGHT_KEYS:
                delta = -1 if k in LEFT_KEYS else 1
                self._change(delta)
                self._held, self._held_t = (k, delta), 0.0
                return True
            if k in ACTIVATE_KEYS:
                self._activate()
                return True
            if k in BACK_KEYS and self.on_back is not None:
                self.sound("ui_back")
                self.on_back()
                return True
        elif et == pg.KEYUP:
            if self._held and event.key == self._held[0]:
                self._held = None
        elif et == pg.MOUSEMOTION:
            if self.dragging is not None:
                if self.dragging.drag(event.pos):
                    self.sound("ui_move")
                return True
            i = self.hit(event.pos)
            if i is not None:
                self.set_focus(i)
                return True
        elif et == pg.MOUSEBUTTONDOWN and event.button == 1:
            i = self.hit(event.pos)
            if i is None:
                return False
            self.set_focus(i, sound=False)
            w = self.widgets[i]
            kind = w.press(event.pos)
            if kind == "activate":
                self._activate()
            elif kind == "change":
                if w.change(getattr(w, "_pending_delta", 1)):
                    self.sound("ui_move")
            elif kind == "drag":
                self.dragging = w
                if w.drag(event.pos):
                    self.sound("ui_move")
            return True
        elif et == pg.MOUSEBUTTONUP and event.button == 1:
            if self.dragging is not None:
                self.dragging = None
                return True
        elif et == pg.MOUSEWHEEL:
            pos = self.app.mouse_pos() if self.app is not None else None
            i = self.hit(pos)
            if i is not None and not isinstance(self.widgets[i], Button):
                self.set_focus(i, sound=False)
                if self.widgets[i].change(1 if event.y > 0 else -1):
                    self.sound("ui_move")
                return True
        return False

    def update(self, dt: float) -> None:
        # Hold A/D (or arrows) to keep changing a value
        if self._held is not None:
            self._held_t += dt
            if self._held_t >= REPEAT_DELAY:
                self._held_t -= REPEAT_RATE
                if not isinstance(self.focused, Slider) and not isinstance(self.focused, Selector):
                    self._held = None
                else:
                    self._change(self._held[1])
        for i, w in enumerate(self.widgets):
            w.focus_anim = approach(w.focus_anim, 1.0 if i == self.focus else 0.0, 14, dt)
            w.update(dt)

    #Drawing
    def draw(self, surf: pg.Surface) -> None:
        a = self.assets
        for i, w in enumerate(self.widgets):
            f = ease_out_cubic(w.focus_anim)
            accent = self.accent_for(w)
            r = w.rect
            radius = min(r.h // 2, 16)
            # Row panel + focus glow
            if f > 0.02:
                draw_glow(surf, dimmed(glow_rect(r.w, r.h, accent, radius, 2), f * 0.9 + w.flash * 0.3), r.center)
            base_alpha = 150 if self.style == "row" else 110
            surf.blit(translucent_panel(r.w, r.h, PAL["panel"], base_alpha, radius), r)
            if f > 0.02:
                tint = translucent_panel(r.w, r.h, accent, 46, radius)
                tint.set_alpha(int(255 * f))
                surf.blit(tint, r)
            border = lerp_color((52, 58, 104), accent, f)
            pg.draw.rect(surf, border, r, 2, border_radius=radius)

            # Label (size bump + colour when focused; quantised to keep the text cache small)
            size = self.font_size + int(round(3 * f))
            col = PAL["white"] if f > 0.5 else (196, 202, 228)
            label = a.text(w.label, size, col, "bold")
            if self.style == "center":
                lr = label.get_rect(center=r.center)
                surf.blit(label, lr)
                if f > 0.05:     # neon chevrons slide in
                    off = int(12 * (1 - f))
                    ccol = scale_color(accent, f)
                    lx, rx, cy = lr.x - 18 - off, lr.right + 18 + off, r.centery
                    pg.draw.polygon(surf, ccol, [(lx, cy - 7), (lx + 8, cy), (lx, cy + 7)])
                    pg.draw.polygon(surf, ccol, [(rx, cy - 7), (rx - 8, cy), (rx, cy + 7)])
            else:
                max_w = r.w - self.control_w - 34
                if label.get_width() > max_w:
                    label = a.text(w.label, max(14, size - 4), col, "bold")
                surf.blit(label, label.get_rect(midleft=(r.x + 18 + int(4 * f), r.centery)))
            w.draw_control(surf, self, f)
