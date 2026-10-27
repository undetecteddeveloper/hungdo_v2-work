"""Boss-fight objects: hostile projectiles, helper pickups (energy, bouncing ball) and the player's beam.

Colour language: everything that hurts is red/orange/magenta with a dark core and spikes; things the
player wants are white/cyan (the ball) or yellow (energy), so "catch or dodge" reads at a glance.

Physics is plain floats and correct for any dt: long steps are split into sub-steps of at most
1/120 s (`config.PHYSICS_DT`), so nothing tunnels through the paddle or the boss.
"""
import logging
import math
from collections import deque

import pygame as pg

from .. import config
from .items import (MAGNET_MAX_VX, MAGNET_MIN_TIME, MAGNET_Y_STRETCH, SIDE_DRAG, add_dot, glow_circle_at,
                    mix_color, outline, regular_polygon, scale_color, step_fall)

log = logging.getLogger(config.LOGGER_NAME)

SHAPES = ("orb", "bolt", "shard")

SUBSTEP = config.PHYSICS_DT         # s, largest internal physics step
MAX_DT = 0.25                       # s, a longer frame is cut to this (avoids huge sub-step loops)
FALL_GRAVITY_SCALE = 0.8            # helper pickups fall like power-ups: gentle
FALL_START_VY = 80.0                # px/s, initial downward speed of a freshly dropped pickup
PROJECTILE_HIT_SCALE = 0.8          # forgiving hit circle
PROJECTILE_MARGIN = 3.0             # x radius outside the screen before a projectile is dropped
ENERGY_RADIUS = 15
ENERGY_HIT_SCALE = 1.15             # good things get a generous hitbox
BALL_HIT_CD = 0.1                   # s, a boss contact is not counted twice inside this window
FALL_TRAIL_LEN = 6
FLY_TRAIL_LEN = 14
TRAIL_INTERVAL = 1 / 60             # s, trail sampling while falling (flying samples every sub-step)

PAL = config.PALETTE
CYAN = PAL["cyan"]
YELLOW = PAL["yellow"]
WHITE = PAL["white"]
HARM_CORE = (22, 5, 14)             # dark core of every hostile shape
ENERGY_DARK = (54, 46, 8)
BOLT_FILL = (255, 247, 196)
# Lightning bolt outline in units of its radius (y down), top tip first
BOLT_POINTS = ((0.30, -1.0), (-0.50, 0.10), (-0.05, 0.10), (-0.30, 1.0), (0.50, -0.15), (0.05, -0.15))


#Helpers
def _resolve_color(color) -> tuple:
    """PALETTE key or colour tuple -> clamped (r, g, b) ints."""
    if isinstance(color, str):
        rgb = PAL.get(color)
        if rgb is None:
            log.warning("boss_items: unknown colour key %r, using red", color)
            rgb = PAL["red"]
        return tuple(int(c) for c in rgb[:3])
    return tuple(max(0, min(255, int(c))) for c in tuple(color)[:3])


def _glow_r(r: float) -> int:
    """Glow radius quantised to even pixels so the neon cache stays small."""
    return max(4, int(round(r / 2.0)) * 2)


def _hash01(n: int) -> float:
    """Cheap deterministic noise in [0, 1] (flicker without touching the random module)."""
    n = (n * 2654435761) & 0xFFFFFFFF
    n ^= n >> 15
    n = (n * 2246822519) & 0xFFFFFFFF
    n ^= n >> 13
    return (n & 0xFFFF) / 65535.0


def _split(dt: float, speed_mult: float = 1.0) -> tuple:
    """(steps, real seconds per step) so that every item-time step is <= SUBSTEP."""
    dt = min(dt, MAX_DT)
    n = max(1, math.ceil(dt * max(1.0, speed_mult) / SUBSTEP - 1e-9))
    return n, dt / n


def _circle_hits_rect(x: float, y: float, r: float, rect: pg.Rect) -> bool:
    """Exact disc-vs-rectangle test (touching counts)."""
    dx = x - min(max(x, rect.left), rect.right)
    dy = y - min(max(y, rect.top), rect.bottom)
    return dx * dx + dy * dy <= r * r


def launch_velocity(ball_x: float, paddle: pg.Rect) -> tuple:
    """Velocity of a ball leaving the paddle at x = ball_x: angle from vertical grows with the offset
    from the paddle centre (full BOSS_BALL_MAX_ANGLE at the edge). Always upward, speed BOSS_BALL_SPEED."""
    half = paddle.w / 2
    offset = (ball_x - paddle.centerx) / half if half > 0 else 0.0
    offset = max(-1.0, min(1.0, offset))
    a = offset * math.radians(config.BOSS_BALL_MAX_ANGLE)
    speed = config.BOSS_BALL_SPEED
    return speed * math.sin(a), -speed * math.cos(a)


def ball_catch_rect(paddle: pg.Rect) -> pg.Rect:
    """Area where a ball CENTRE counts as touching the paddle top (for bots / aiming helpers)."""
    r = config.BOSS_BALL_RADIUS
    return pg.Rect(paddle.left - r, paddle.top - r, paddle.w + 2 * r, paddle.h + r)


def _keep_speed(vx: float, vy: float) -> tuple:
    """After a reflection: |vy| >= BOSS_BALL_MIN_VY * speed (no endless sideways rally), then |v| = speed."""
    speed = config.BOSS_BALL_SPEED
    min_vy = config.BOSS_BALL_MIN_VY * speed
    if abs(vy) < min_vy:
        vy = math.copysign(min_vy, vy if vy else -1.0)
        vx = math.copysign(math.sqrt(max(0.0, speed * speed - vy * vy)), vx if vx else 1.0)
        return vx, vy
    length = math.hypot(vx, vy)
    if length < 1e-9:
        return 0.0, -speed
    k = speed / length
    return vx * k, vy * k


#Hostile projectile
class Projectile:
    """A harmful boss shot: flies straight, no gravity, no wall bounce. `pos` is the centre."""

    def __init__(self, x: float, y: float, vx: float, vy: float, radius: float = 13.0,
                 shape: str = "orb", color="red"):
        if shape not in SHAPES:
            log.warning("boss_items: unknown projectile shape %r, using orb", shape)
            shape = "orb"
        self.pos = pg.Vector2(x, y)
        self.vel = pg.Vector2(vx, vy)
        self.radius = float(radius)
        self.shape = shape
        self.color = _resolve_color(color)
        self.alive = True
        self.age = 0.0
        self._phase = (x * 0.013 + y * 0.007) % math.tau     # de-syncs the pulse of neighbours

    @property
    def hit_radius(self) -> float:
        return self.radius * PROJECTILE_HIT_SCALE

    @property
    def rect(self) -> pg.Rect:
        r = self.hit_radius
        return pg.Rect(round(self.pos.x - r), round(self.pos.y - r), round(r * 2), round(r * 2))

    def update(self, dt: float, time_scale: float = 1.0) -> None:
        if not self.alive:
            return
        dt *= time_scale
        self.age += dt
        self.pos += self.vel * dt
        m = self.radius * PROJECTILE_MARGIN
        x, y = self.pos.x, self.pos.y
        if x < -m or x > config.LOGICAL_W + m or y > config.LOGICAL_H + m or (y < -m and self.vel.y <= 0):
            self.alive = False

    def hits(self, rect: pg.Rect) -> bool:
        return _circle_hits_rect(self.pos.x, self.pos.y, self.hit_radius, rect)

    def on_resize(self, old_w: int) -> None:
        """Canvas width changed: keep the relative x."""
        self.pos.x *= config.LOGICAL_W / old_w

    #Drawing
    def draw(self, surf, t: float, assets=None) -> None:
        if not self.alive:
            return
        cx, cy, r = self.pos.x, self.pos.y, self.radius
        m = r * 2.5
        if cx < -m or cx > config.LOGICAL_W + m or cy < -m or cy > config.LOGICAL_H + m:
            return
        getattr(self, "_draw_" + self.shape)(surf, cx, cy, r, t)

    def _tail(self, surf, cx, cy, r, length: float, dots: int = 4) -> None:
        """Fading additive dots behind the shot (it flies straight, so no history is needed)."""
        speed = self.vel.length()
        if speed < 1.0:
            return
        ux, uy = -self.vel.x / speed, -self.vel.y / speed
        for i in range(1, dots + 1):
            k = 1.0 - i / (dots + 1)
            d = length * i / dots
            add_dot(surf, (cx + ux * d, cy + uy * d), r * (0.18 + 0.4 * k), scale_color(self.color, 0.55 * k))

    def _draw_orb(self, surf, cx, cy, r, t) -> None:
        """Spiky ball with a dark core and an ember in the middle."""
        color = self.color
        beat = 0.5 + 0.5 * math.sin(t * 10 + self._phase)
        qbeat = round(beat * 2) / 2
        center = (int(cx), int(cy))
        self._tail(surf, cx, cy, r, r * 2.4)
        glow_circle_at(surf, (cx, cy), _glow_r(r * 1.05), color, 0.8 + 0.3 * qbeat)
        spin = self.age * 3.2 + self._phase
        spikes = regular_polygon(cx, cy, r * 1.3, 8, spin, r_inner=r * 0.86)
        pg.draw.polygon(surf, scale_color(color, 0.34), spikes)
        outline(surf, color, spikes, 2)
        core = max(3, int(r * 0.62))
        pg.draw.circle(surf, HARM_CORE, center, core)
        pg.draw.circle(surf, scale_color(color, 0.85), center, core, 1)
        pg.draw.circle(surf, mix_color(color, WHITE, 0.3 + 0.3 * beat), center, max(2, int(r * (0.18 + 0.1 * beat))))

    def _draw_bolt(self, surf, cx, cy, r, t) -> None:
        """Long rhombus pointing along its flight direction, bright edge, dark body."""
        color = self.color
        speed = self.vel.length()
        ang = math.atan2(self.vel.y, self.vel.x) if speed > 1.0 else math.pi / 2
        ux, uy = math.cos(ang), math.sin(ang)
        px, py = -uy, ux
        front, back, half = r * 1.9, r * 1.35, r * 0.78
        tip = (cx + ux * front, cy + uy * front)
        tail = (cx - ux * back, cy - uy * back)
        wing = (cx + ux * r * 0.25, cy + uy * r * 0.25)
        pts = [tip, (wing[0] + px * half, wing[1] + py * half), tail, (wing[0] - px * half, wing[1] - py * half)]
        flick = 0.5 + 0.5 * math.sin(t * 24 + self._phase)
        self._tail(surf, cx, cy, r, r * 3.4, 5)
        glow_circle_at(surf, (cx, cy), _glow_r(r * 1.0), color, 0.85 + 0.25 * round(flick))
        pg.draw.polygon(surf, HARM_CORE, pts)
        pg.draw.polygon(surf, scale_color(color, 0.42), pts)
        shrink = [(cx + (x - cx) * 0.55, cy + (y - cy) * 0.55) for x, y in pts]
        pg.draw.polygon(surf, HARM_CORE, shrink)
        outline(surf, color, pts, 2)
        pg.draw.aaline(surf, mix_color(color, WHITE, 0.55), tail, tip)

    def _draw_shard(self, surf, cx, cy, r, t) -> None:
        """Four sharp thorns (a caltrop) spinning fast, deep notches, dark diamond in the middle."""
        color = self.color
        spin = -self.age * 7.5 + self._phase
        center = (int(cx), int(cy))
        self._tail(surf, cx, cy, r, r * 2.2, 3)
        glow_circle_at(surf, (cx, cy), _glow_r(r * 1.0), color, 0.9)
        thorns = regular_polygon(cx, cy, r * 1.55, 4, spin, r_inner=r * 0.46)
        pg.draw.polygon(surf, scale_color(color, 0.4), thorns)
        outline(surf, color, thorns, 2)
        pg.draw.polygon(surf, HARM_CORE, regular_polygon(cx, cy, r * 0.52, 4, spin + math.pi / 4))
        pg.draw.circle(surf, mix_color(color, WHITE, 0.55), center, max(2, int(r * 0.2)))


#Helper pickups
class _Faller:
    """Slow fall + magnet steering shared by the helper pickups. `pos` is the centre."""

    radius: float = ENERGY_RADIUS

    def __init__(self, x: float, y: float = None):
        self.pos = pg.Vector2(x, -self.radius if y is None else y)      # just above the top edge
        self.vel = pg.Vector2(0.0, FALL_START_VY)
        self.alive = True
        self.fell = False                       # True once it left the bottom of the screen
        self.magnetized = False
        self.age = 0.0
        self.trail = deque(maxlen=FLY_TRAIL_LEN)
        self._trail_t = 0.0

    def _fall_substep(self, h: float, magnet_x) -> None:
        """One item-time step: magnet steering (or sideways drag) then items.step_fall."""
        vx = self.vel.x
        self.magnetized = False
        if magnet_x is not None:
            vx = self._magnet_vx(vx, magnet_x, h)
        elif vx:
            vx *= math.exp(-SIDE_DRAG * h)
            if abs(vx) < 1:
                vx = 0.0
        x, y, vx, vy = step_fall(self.pos.x, self.pos.y, vx, self.vel.y, h,
                                 config.GRAVITY * FALL_GRAVITY_SCALE, config.BOSS_HELPER_TERMINAL, self.radius)
        self.pos.update(x, y)
        self.vel.update(vx, vy)
        self.age += h
        self._trail_t += h
        if self._trail_t >= TRAIL_INTERVAL:
            self._trail_t = 0.0
            self.trail.append((x, y))

    def _magnet_vx(self, vx: float, target_x: float, dt: float) -> float:
        """Same homing as items.Item: bend vx toward the paddle with limited acceleration."""
        dx = target_x - self.pos.x
        dy = config.PLAYER_Y - self.pos.y
        if dy < -config.PLAYER_H:               # already below the paddle
            return vx
        d = math.hypot(dx, dy * MAGNET_Y_STRETCH)
        radius = config.magnet_radius()
        if d >= radius:
            return vx
        k = 1.0 - d / radius
        t_left = max(MAGNET_MIN_TIME, max(dy, 0.0) / max(self.vel.y, 120.0))
        desired = max(-MAGNET_MAX_VX, min(MAGNET_MAX_VX, dx / t_left))
        max_dv = config.MAGNET_PULL * (0.6 + 0.4 * k) * dt
        dv = max(-max_dv, min(max_dv, desired - vx))
        self.magnetized = True
        return vx + dv

    def _left_bottom(self) -> bool:
        if self.pos.y - self.radius > config.LOGICAL_H:
            self.fell = True
            self.alive = False
            return True
        return False

    def on_resize(self, old_w: int) -> None:
        """Canvas width changed: keep the relative x (trail included)."""
        k = config.LOGICAL_W / old_w
        self.pos.x *= k
        self.trail = deque(((x * k, y) for x, y in self.trail), maxlen=self.trail.maxlen)


class EnergyItem(_Faller):
    """Energy cell falling from the sky; BOSS_ENERGY_NEED of them charge one beam shot."""

    kind = "energy"
    radius = ENERGY_RADIUS

    @property
    def rect(self) -> pg.Rect:
        r = self.radius * ENERGY_HIT_SCALE
        return pg.Rect(round(self.pos.x - r), round(self.pos.y - r), round(r * 2), round(r * 2))

    def update(self, dt: float, time_scale: float = 1.0, magnet_x=None) -> None:
        if not self.alive or dt <= 0:
            return
        n, h = _split(dt, time_scale)
        for _ in range(n):
            self._fall_substep(h * time_scale, magnet_x)
            if self._left_bottom():
                break

    def draw(self, surf, t: float, assets=None) -> None:
        if not self.alive:
            return
        cx, cy, r = self.pos.x, self.pos.y, self.radius
        if cy < -r * 3:
            return
        color = YELLOW
        trail = list(self.trail)[-FALL_TRAIL_LEN:]
        n = len(trail)
        for i, (tx, ty) in enumerate(trail):
            k = (i + 1) / (n + 1)
            add_dot(surf, (tx, ty), r * (0.2 + 0.4 * k), scale_color(color, 0.32 * k))
        if self.magnetized:
            glow_circle_at(surf, (cx, cy), int(r * 1.6), config.PALETTE["purple"], 0.5)

        pulse = 0.5 + 0.5 * math.sin(t * 8 + self.age * 2)
        glow_circle_at(surf, (cx, cy), _glow_r(r * 1.2), color, 0.8 + 0.2 * round(pulse * 2))
        spin = self.age * 0.9
        hexa = regular_polygon(cx, cy, r * 1.15, 6, spin)
        pg.draw.polygon(surf, ENERGY_DARK, hexa)
        outline(surf, mix_color(color, WHITE, 0.15), hexa, 2)
        pg.draw.aalines(surf, scale_color(color, 0.5), True, regular_polygon(cx, cy, r * 0.82, 6, spin))
        s = r * 0.72
        bolt = [(cx + bx * s, cy + by * s) for bx, by in BOLT_POINTS]
        pg.draw.polygon(surf, BOLT_FILL, bolt)
        pg.draw.aalines(surf, WHITE, True, bolt)
        self._draw_sparks(surf, cx, cy, r, t)

    def _draw_sparks(self, surf, cx, cy, r, t) -> None:
        """Short electric arcs that flicker around the cell (new shape every ~1/14 s)."""
        frame = int(t * 14)
        for i in range(3):
            if _hash01(frame * 7 + i * 131) < 0.4:
                continue
            a = math.tau * (i / 3 + 0.09 * _hash01(frame * 11 + i)) + self.age * 0.6
            ux, uy = math.cos(a), math.sin(a)
            px, py = -uy, ux
            pts = []
            for j in range(4):
                d = r * (1.15 + 0.42 * j)
                off = 0.0 if j == 0 else (_hash01(frame * 13 + i * 17 + j) - 0.5) * r * 0.7
                pts.append((cx + ux * d + px * off, cy + uy * d + py * off))
            pg.draw.lines(surf, mix_color(YELLOW, WHITE, 0.6), False, pts, 1)


class HelperBall(_Faller):
    """The bouncing ball: falls until the paddle touches it, then flies Brick Breaker style."""

    radius = config.BOSS_BALL_RADIUS

    def __init__(self, x: float, y: float = None):
        self.radius = config.BOSS_BALL_RADIUS
        super().__init__(x, y)
        self.state = "falling"                  # "falling" (not caught yet) | "flying"
        self.hit_cd = 0.0                       # s left in which a new boss contact is ignored

    @property
    def rect(self) -> pg.Rect:
        r = self.radius
        return pg.Rect(round(self.pos.x - r), round(self.pos.y - r), round(r * 2), round(r * 2))

    @property
    def flying(self) -> bool:
        return self.state == "flying"

    #Physics
    def update(self, dt: float, time_scale: float = 1.0, magnet_x=None, paddle: pg.Rect = None,
               boss_rect: pg.Rect = None) -> tuple:
        """Advance by dt; returns the events of this step as a tuple of strings (see the module contract).

        paddle:    the paddle rect, as it is now; it is treated as fixed during this call.
        boss_rect: the boss hitbox, or None when the boss cannot be hurt (then the ball passes through).
        """
        if not self.alive or dt <= 0:
            return ()
        events = []
        n, h = _split(dt, time_scale)
        for _ in range(n):
            if self.state == "falling":
                self._fall_substep(h * time_scale, magnet_x)
                if paddle is not None and paddle.colliderect(self.rect):
                    self._catch(paddle)
                    events.append("caught")
                elif self._left_bottom():
                    break                       # an uncaught ball just falls away, no penalty
            else:
                self._fly_substep(h, paddle, boss_rect, events)
                if not self.alive:
                    break
        return tuple(events) if events else ()

    def _catch(self, paddle: pg.Rect) -> None:
        self.state = "flying"
        self.magnetized = False
        self.vel.update(*launch_velocity(self.pos.x, paddle))
        self.pos.y = paddle.top - self.radius
        self.hit_cd = 0.0
        self.trail.clear()
        self._trail_t = 0.0

    def _fly_substep(self, h: float, paddle, boss_rect, events: list) -> None:
        r = self.radius
        x = self.pos.x + self.vel.x * h
        y = self.pos.y + self.vel.y * h
        vx, vy = self.vel.x, self.vel.y
        self.age += h
        self.hit_cd = max(0.0, self.hit_cd - h)
        bounced = False

        # Side walls and ceiling
        if x < r:
            x = r
            if vx < 0:
                vx, bounced = -vx, True
                events.append("wall")
        elif x > config.LOGICAL_W - r:
            x = config.LOGICAL_W - r
            if vx > 0:
                vx, bounced = -vx, True
                events.append("wall")
        if y < r:
            y = r
            if vy < 0:
                vy, bounced = -vy, True
                events.append("ceiling")
        if bounced:
            vx, vy = _keep_speed(vx, vy)

        # Paddle: only a falling ball whose centre is above the paddle's middle line bounces
        self.pos.update(x, y)
        if paddle is not None and vy > 0 and y <= paddle.centery and paddle.colliderect(self.rect):
            vx, vy = launch_velocity(x, paddle)
            y = paddle.top - r
            events.append("paddle")

        # Boss: push out along the axis of least penetration and reflect that component
        if boss_rect is not None and self.hit_cd <= 0.0 and _circle_hits_rect(x, y, r, boss_rect):
            pen_b = boss_rect.bottom - (y - r)
            pen_t = (y + r) - boss_rect.top
            pen_l = (x + r) - boss_rect.left
            pen_r = boss_rect.right - (x - r)
            least = min(pen_b, pen_t, pen_l, pen_r)
            if least == pen_b:
                y, vy = boss_rect.bottom + r, abs(vy)
            elif least == pen_t:
                y, vy = boss_rect.top - r, -abs(vy)
            elif least == pen_l:
                x, vx = boss_rect.left - r, -abs(vx)
            else:
                x, vx = boss_rect.right + r, abs(vx)
            vx, vy = _keep_speed(vx, vy)
            self.hit_cd = BALL_HIT_CD
            events.append("boss")

        self.pos.update(x, y)
        self.vel.update(vx, vy)
        self._trail_t += h
        if self._trail_t >= SUBSTEP - 1e-9:
            self._trail_t = 0.0
            self.trail.append((x, y))
        if y - r > config.LOGICAL_H:            # a flying ball got past the paddle
            self.fell = True
            self.alive = False
            events.append("lost")

    #Drawing
    def draw(self, surf, t: float, assets=None) -> None:
        if not self.alive:
            return
        cx, cy, r = self.pos.x, self.pos.y, self.radius
        if cy < -r * 3:
            return
        flying = self.state == "flying"
        center = (int(cx), int(cy))

        # Tail: the faster the ball, the longer and brighter (a falling ball keeps a short one)
        trail = list(self.trail) if flying else list(self.trail)[-FALL_TRAIL_LEN:]
        n = len(trail)
        for i, (tx, ty) in enumerate(trail):
            k = (i + 1) / (n + 1)
            add_dot(surf, (tx, ty), r * (0.18 + 0.62 * k), scale_color(CYAN, (0.6 if flying else 0.35) * k))

        if self.magnetized:
            glow_circle_at(surf, (cx, cy), int(r * 1.8), config.PALETTE["purple"], 0.5)
        glow_circle_at(surf, (cx, cy), _glow_r(r * 1.25), CYAN, 1.0 if flying else 0.85)
        if not flying:
            # "Catch me": a ring that breathes around the falling ball
            pulse = 0.5 + 0.5 * math.sin(t * 7 + self.age * 3)
            pg.draw.aacircle(surf, scale_color(CYAN, 0.45 + 0.35 * pulse), center, int(r * (1.7 + 0.25 * pulse)), 1)
        pg.draw.circle(surf, scale_color(CYAN, 0.55), center, r)
        pg.draw.aacircle(surf, CYAN, center, r, 2)
        pg.draw.circle(surf, WHITE, center, max(2, int(r * 0.74)))
        pg.draw.circle(surf, mix_color(CYAN, WHITE, 0.75), (center[0] - r // 4, center[1] - r // 4), max(1, r // 4))


#Player's beam
class Beam:
    """The player's beam. Hit or miss is decided at once (hitscan); drawing lives in render.boss_draw."""

    def __init__(self, x: float, y_from: float, boss_rect: pg.Rect = None):
        self.x = float(x)
        self.y_from = float(y_from)
        self.width = float(config.BOSS_BEAM_WIDTH)
        self.life = float(config.BOSS_BEAM_LIFE)
        self.age = 0.0
        self.alive = True
        half = self.width / 2
        self.hit = boss_rect is not None and boss_rect.left - half <= self.x <= boss_rect.right + half
        self.y_to = float(boss_rect.bottom) if self.hit else 0.0

    @property
    def progress(self) -> float:
        return 1.0 if self.life <= 0 else min(1.0, self.age / self.life)

    def update(self, dt: float) -> None:
        if not self.alive:
            return
        self.age += dt
        if self.age >= self.life:
            self.alive = False

    def on_resize(self, old_w: int) -> None:
        self.x *= config.LOGICAL_W / old_w
