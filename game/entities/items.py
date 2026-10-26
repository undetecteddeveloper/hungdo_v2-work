"""Falling items: good catches (common/rare/epic), bombs and power-ups.

Physics is plain floats so the spawner can predict landings with the exact same
step function the live items use (see `step_fall` / `Item.predict_landing`).
"""
import logging
import math
from collections import deque

import pygame as pg

from .. import config

log = logging.getLogger(config.LOGGER_NAME)

KINDS = ("common", "rare", "epic", "bomb", "powerup")

# Base colour per kind / per power-up
KIND_COLORS = {
    "common": config.PALETTE["cyan"],
    "rare": config.PALETTE["magenta"],
    "epic": config.PALETTE["yellow"],
    "bomb": config.PALETTE["red"],
    "powerup": config.PALETTE["green"],
}
POWER_COLORS = {
    "magnet": config.PALETTE["purple"],
    "slow": (70, 150, 255),
    "wide": config.PALETTE["green"],
    "shield": config.PALETTE["cyan"],
    "heart": config.PALETTE["red"],
}
POWER_LETTERS = {"magnet": "M", "slow": "S", "wide": "W", "shield": "D", "heart": "+"}

# Hitbox scale per kind: bombs are forgiving, good items generous
HIT_SCALE = {"common": 1.0, "rare": 1.0, "epic": 1.1, "bomb": 0.75, "powerup": 1.0}

MAGNET_MAX_VX = 800                 # px/s, cap on magnet-induced sideways speed
MAGNET_MIN_TIME = 0.12              # s, homing never aims to close the gap faster than this
MAGNET_Y_STRETCH = 0.4              # magnet zone is an ellipse 2.5x taller than wide
SIDE_DRAG = 3.0                     # 1/s, non-diagonal items lose leftover sideways speed
TRAIL_LEN = 7
TRAIL_INTERVAL = 1 / 60             # item-time seconds between trail samples


#Physics shared with the spawner's prediction
def step_fall(x, y, vx, vy, dt, gravity, terminal, radius):
    """One semi-implicit Euler step; side walls reflect vx with ITEM_RESTITUTION. Returns (x, y, vx, vy)."""
    vy = min(vy + gravity * dt, terminal)
    y += vy * dt
    x += vx * dt
    if x < radius:
        x = radius
        if vx < 0:
            vx = -vx * config.ITEM_RESTITUTION
    elif x > config.LOGICAL_W - radius:
        x = config.LOGICAL_W - radius
        if vx > 0:
            vx = -vx * config.ITEM_RESTITUTION
    return x, y, vx, vy


def catch_y(radius: float) -> float:
    """Item centre y at which it first touches the top of the paddle."""
    return config.PLAYER_Y - config.PLAYER_H / 2 - radius


#Drawing helpers (neon module is optional; plain pg.draw fallback)
_neon_mod = None
_neon_state = 0                     # 0 = not tried, 1 = ok, -1 = unavailable
_fallback_cache = {}


def neon():
    """game.render.neon if importable (and not broken), else None."""
    global _neon_mod, _neon_state
    if _neon_state == 0:
        try:
            from ..render import neon as mod
            _neon_mod, _neon_state = mod, 1
        except ImportError as e:
            log.info("render.neon not available, using plain glow fallback (%s)", e)
            _neon_state = -1
    return _neon_mod if _neon_state == 1 else None


def _neon_failed(e: Exception) -> None:
    global _neon_state
    log.warning("render.neon call failed, switching to fallback glow: %s", e)
    _neon_state = -1


def scale_color(color, k: float) -> tuple:
    return (min(255, int(color[0] * k)), min(255, int(color[1] * k)), min(255, int(color[2] * k)))


def mix_color(a, b, k: float) -> tuple:
    return (int(a[0] + (b[0] - a[0]) * k), int(a[1] + (b[1] - a[1]) * k), int(a[2] + (b[2] - a[2]) * k))


def _additive_blit(surf, glow, center) -> None:
    surf.blit(glow, glow.get_rect(center=(int(center[0]), int(center[1]))), special_flags=pg.BLEND_ADD)


def _fallback_circle(radius: int, color, intensity: float) -> pg.Surface:
    """Concentric dim circles on black (halo ~2x the shape radius), meant for BLEND_ADD."""
    key = ("c", radius, tuple(color[:3]), round(intensity, 2))
    s = _fallback_cache.get(key)
    if s is None:
        radius *= 2
        size = radius * 2 + 2
        s = pg.Surface((size, size))
        steps = 6
        for i in range(steps):
            r = int(radius * (1 - i / steps))
            k = 0.07 * intensity * (i + 1)
            pg.draw.circle(s, scale_color(color, k), (size // 2, size // 2), max(1, r))
        _fallback_cache[key] = s
    return s


def _fallback_rect(w: int, h: int, color, radius: int, thickness: int = 0) -> pg.Surface:
    key = ("r", w, h, tuple(color[:3]), radius, thickness)
    s = _fallback_cache.get(key)
    if s is None:
        pad = 14
        s = pg.Surface((w + pad * 2, h + pad * 2))
        steps = 5
        for i in range(steps):
            grow = int(pad * (1 - i / steps))
            rect = pg.Rect(pad - grow, pad - grow, w + grow * 2, h + grow * 2)
            width = 0 if not thickness else thickness + grow * 2
            pg.draw.rect(s, scale_color(color, 0.08 * (i + 1)), rect, width, border_radius=radius + grow)
        _fallback_cache[key] = s
    return s


def glow_circle_at(surf, center, radius: int, color, intensity: float = 1.0) -> None:
    """Additive halo around a disc of `radius` (the shape size, not the halo size)."""
    radius = max(2, int(radius))
    intensity = round(intensity * 10) / 10       # bounded cache keys for pulsing glows
    mod = neon()
    if mod is not None:
        try:
            mod.draw_glow(surf, mod.glow_circle(radius, tuple(color[:3]), intensity), (int(center[0]), int(center[1])))
            return
        except (TypeError, ValueError, AttributeError, pg.error) as e:
            _neon_failed(e)
    _additive_blit(surf, _fallback_circle(radius, color, intensity), center)


def glow_rect_at(surf, center, w: int, h: int, color, radius: int = 8, thickness: int = 0) -> None:
    """Additive halo around a w x h rounded rect (outline when thickness > 0). Pass quantised sizes."""
    w, h = max(2, int(w)), max(2, int(h))
    mod = neon()
    if mod is not None:
        try:
            glow = mod.glow_rect(w, h, tuple(color[:3]), radius=int(radius), thickness=int(thickness))
            mod.draw_glow(surf, glow, (int(center[0]), int(center[1])))
            return
        except (TypeError, ValueError, AttributeError, pg.error) as e:
            _neon_failed(e)
    _additive_blit(surf, _fallback_rect(w, h, color, int(radius), int(thickness)), center)


def add_dot(surf, center, radius: int, color) -> None:
    """Small additive dot (trails, sparks); cached per size/colour."""
    radius = max(1, int(radius))
    key = ("d", radius, tuple(color[:3]))
    s = _fallback_cache.get(key)
    if s is None:
        s = pg.Surface((radius * 2 + 1, radius * 2 + 1))
        pg.draw.circle(s, color[:3], (radius, radius), radius)
        _fallback_cache[key] = s
    _additive_blit(surf, s, center)


def regular_polygon(cx, cy, r, n, angle, r_inner=None) -> list:
    """Points of a regular polygon (or star when r_inner is given)."""
    pts = []
    count = n * 2 if r_inner is not None else n
    for i in range(count):
        a = angle + math.tau * i / count
        rr = r if (r_inner is None or i % 2 == 0) else r_inner
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    return pts


def outline(surf, color, pts, width: int = 2) -> None:
    """Crisp polygon outline with an antialiased edge."""
    pg.draw.polygon(surf, color, pts, width)
    pg.draw.aalines(surf, color, True, pts)


#Item
class Item:
    """A falling object. `pos` is the centre; physics runs in item time (dt * time_scale)."""

    def __init__(self, kind: str, x: float, y: float = None, vx: float = 0.0, vy: float = 0.0,
                 power: str = None, terminal_mult: float = 1.0):
        if kind not in KINDS:
            raise ValueError(f"Unknown item kind '{kind}'")
        self.kind = kind
        self.power = power if kind == "powerup" else None
        self.radius = config.ITEM_RADIUS[kind]
        if y is None:
            y = -self.radius                     # just above the top edge
        self.pos = pg.Vector2(x, y)
        self.vel = pg.Vector2(vx, vy)
        self.terminal = config.ITEM_TERMINAL_SPEED[kind] * terminal_mult
        self.gravity_scale = config.ITEM_GRAVITY_SCALE[kind]
        self.diagonal = vx != 0                  # keeps its sideways speed (bounces off walls)
        self.alive = True
        self.fell = False                        # True once it left the bottom of the screen
        self.magnetized = False
        self.spin = 0.0                          # radians, visual only
        self.spin_speed = {"rare": 2.2, "epic": 3.4, "bomb": 0.8}.get(kind, 0.0)
        if vx < 0:
            self.spin_speed = -self.spin_speed
        self.age = 0.0
        self.color = POWER_COLORS.get(self.power, KIND_COLORS[kind])
        self.trail = deque(maxlen=TRAIL_LEN)
        self._trail_t = 0.0

    #Info
    @property
    def is_good(self) -> bool:
        return self.kind in config.GOOD_KINDS

    @property
    def value(self) -> int:
        return config.POINTS.get(self.kind, 0)

    @property
    def hit_radius(self) -> float:
        return self.radius * HIT_SCALE[self.kind]

    @property
    def rect(self) -> pg.Rect:
        r = self.hit_radius
        return pg.Rect(round(self.pos.x - r), round(self.pos.y - r), round(r * 2), round(r * 2))

    #Physics
    def update(self, dt: float, gravity: float, time_scale: float = 1.0, magnet_target_x=None) -> None:
        """gravity = config.GRAVITY * level gravity_mult; magnet_target_x = player x while magnet is active."""
        if not self.alive:
            return
        dt *= time_scale
        self.age += dt
        self.spin += self.spin_speed * dt

        vx = self.vel.x
        self.magnetized = False
        if magnet_target_x is not None and self.is_good:
            vx = self._magnet_vx(vx, magnet_target_x, dt)
        elif not self.diagonal and vx:
            vx *= math.exp(-SIDE_DRAG * dt)      # drift left over from the magnet fades out
            if abs(vx) < 1:
                vx = 0.0

        x, y, vx, vy = step_fall(self.pos.x, self.pos.y, vx, self.vel.y, dt,
                                 gravity * self.gravity_scale, self.terminal, self.radius)
        self.pos.update(x, y)
        self.vel.update(vx, vy)

        # Short trail sampled in item time
        self._trail_t += dt
        if self._trail_t >= TRAIL_INTERVAL:
            self._trail_t = 0.0
            self.trail.append((x, y))

        if y - self.radius > config.LOGICAL_H:
            self.fell = True
            self.alive = False

    def _magnet_vx(self, vx: float, target_x: float, dt: float) -> float:
        """Steer vx toward the paddle with limited acceleration (smooth bend, no snapping)."""
        dx = target_x - self.pos.x
        dy = config.PLAYER_Y - self.pos.y
        if dy < -config.PLAYER_H:                # already below the paddle
            return vx
        d = math.hypot(dx, dy * MAGNET_Y_STRETCH)
        if d >= config.MAGNET_RADIUS:
            return vx
        k = 1.0 - d / config.MAGNET_RADIUS       # 0 at the edge, 1 at the paddle
        # Homing: sideways speed that arrives over the paddle just as the item reaches it
        t_left = max(MAGNET_MIN_TIME, max(dy, 0.0) / max(self.vel.y, 120.0))
        desired = max(-MAGNET_MAX_VX, min(MAGNET_MAX_VX, dx / t_left))
        max_dv = config.MAGNET_PULL * (0.6 + 0.4 * k) * dt
        dv = max(-max_dv, min(max_dv, desired - vx))
        self.magnetized = True
        return vx + dv

    def predict_landing(self, gravity: float, target_y: float = None, max_time: float = 10.0):
        """(seconds, x) when the centre reaches target_y (default: paddle top), ignoring magnet/slow.

        Uses the same fixed-step integration as update(), so it matches live items exactly.
        """
        if target_y is None:
            target_y = catch_y(self.radius)
        dt = config.PHYSICS_DT
        g = gravity * self.gravity_scale
        x, y, vx, vy = self.pos.x, self.pos.y, self.vel.x, self.vel.y
        t = 0.0
        while y < target_y and t < max_time:
            x, y, vx, vy = step_fall(x, y, vx, vy, dt, g, self.terminal, self.radius)
            t += dt
        return t, x

    #Drawing
    def draw(self, surf, t: float, assets=None) -> None:
        if not self.alive:
            return
        cx, cy = self.pos.x, self.pos.y
        r = self.radius
        color = self.color

        # Trail: fading additive dots, oldest first
        n = len(self.trail)
        for i, (tx, ty) in enumerate(self.trail):
            k = (i + 1) / (n + 1)
            add_dot(surf, (tx, ty), r * (0.25 + 0.45 * k), scale_color(color, 0.35 * k))

        if self.magnetized:
            glow_circle_at(surf, (cx, cy), int(r * 1.6), POWER_COLORS["magnet"], 0.5)

        draw = getattr(self, "_draw_" + self.kind)
        draw(surf, cx, cy, r, color, t, assets)

    def _draw_common(self, surf, cx, cy, r, color, t, assets):
        glow_circle_at(surf, (cx, cy), r, color, 0.9)
        center = (int(cx), int(cy))
        pg.draw.circle(surf, scale_color(color, 0.3), center, r)
        pg.draw.aacircle(surf, color, center, r, 3)
        pg.draw.circle(surf, mix_color(color, config.PALETTE["white"], 0.6), center, max(2, r // 3))

    def _draw_rare(self, surf, cx, cy, r, color, t, assets):
        glow_circle_at(surf, (cx, cy), int(r * 1.05), color, 0.9)
        # Diamond squashes horizontally as it spins (fake 3D turn)
        sx = 0.55 + 0.45 * abs(math.cos(self.spin))
        rr = r * 1.3
        pts = [(cx, cy - rr), (cx + rr * 0.8 * sx, cy), (cx, cy + rr), (cx - rr * 0.8 * sx, cy)]
        pg.draw.polygon(surf, scale_color(color, 0.32), pts)
        outline(surf, color, pts, 2)
        pg.draw.aaline(surf, mix_color(color, config.PALETTE["white"], 0.5), (cx, cy - rr * 0.6), (cx, cy + rr * 0.6))

    def _draw_epic(self, surf, cx, cy, r, color, t, assets):
        pulse = 1.0 + 0.08 * math.sin(t * 12 + self.age * 3)
        glow_circle_at(surf, (cx, cy), int(r * 1.1), color, 1.0)
        pts = regular_polygon(cx, cy, r * 1.45 * pulse, 5, self.spin - math.pi / 2, r_inner=r * 0.62 * pulse)
        pg.draw.polygon(surf, color, pts)
        outline(surf, mix_color(color, config.PALETTE["white"], 0.7), pts, 2)
        pg.draw.circle(surf, config.PALETTE["white"], (int(cx), int(cy)), max(2, int(r * 0.32)))

    def _draw_bomb(self, surf, cx, cy, r, color, t, assets):
        beat = 0.5 + 0.5 * math.sin(t * 9 + self.age * 2)
        qbeat = round(beat * 4) / 4                  # quantised for the glow cache
        orange = config.PALETTE["orange"]
        glow_circle_at(surf, (cx, cy), int(r * 1.1), mix_color(color, orange, qbeat * 0.5), 0.7 + 0.4 * qbeat)
        # Spiky hexagon: hexagon body + a spike on each vertex
        spikes = regular_polygon(cx, cy, r * 1.35, 6, self.spin, r_inner=r * 0.92)
        pg.draw.polygon(surf, scale_color(color, 0.35), spikes)
        outline(surf, color, spikes, 2)
        hexa = regular_polygon(cx, cy, r * 0.8, 6, self.spin + math.pi / 6)
        pg.draw.polygon(surf, (24, 6, 14), hexa)
        outline(surf, scale_color(orange, 0.9), hexa, 1)
        core_r = max(2, int(r * (0.32 + 0.14 * beat)))
        pg.draw.circle(surf, mix_color(orange, config.PALETTE["yellow"], beat), (int(cx), int(cy)), core_r)
        icon = assets.icon("bomb", config.PALETTE["white"], int(r * 0.9)) if assets is not None else None
        if icon is not None:
            surf.blit(icon, icon.get_rect(center=(int(cx), int(cy))))

    def _draw_powerup(self, surf, cx, cy, r, color, t, assets):
        bob = 1.0 + 0.06 * math.sin(t * 6 + self.age * 4)
        size = int(r * 2 * bob)
        glow_rect_at(surf, (cx, cy), size // 4 * 4, size // 4 * 4, color, radius=8)
        rect = pg.Rect(0, 0, size, size)
        rect.center = (int(cx), int(cy))
        pg.draw.rect(surf, scale_color(color, 0.22), rect, border_radius=8)
        pg.draw.rect(surf, color, rect, 2, border_radius=8)
        icon = assets.icon(self.power, color, int(r * 1.3)) if assets is not None and self.power else None
        if icon is not None:
            surf.blit(icon, icon.get_rect(center=rect.center))
        elif assets is not None:
            letter = assets.text(POWER_LETTERS.get(self.power, "?"), int(r * 1.4), color, "bold")
            surf.blit(letter, letter.get_rect(center=rect.center))
        else:
            pg.draw.circle(surf, color, rect.center, max(2, r // 3))
