"""The paddle: weighty horizontal movement with turn boost, friction and soft walls."""
import math

import pygame as pg

from .. import config
from .items import glow_rect_at, mix_color, outline, scale_color

STOP_SPEED = 40.0                   # px/s, wall bounces slower than this just stop (no jitter)
TILT_MAX = 7.0                      # degrees at full speed
STRETCH_MAX = 0.12                  # extra width at full speed (height shrinks to match)
VISUAL_RATE = 14.0                  # 1/s, easing for tilt/stretch
GLOW_STEP = 6                       # px, glow sizes are quantised so the neon cache stays small


class Player:
    """`pos` is the paddle centre (y fixed at config.PLAYER_Y)."""

    def __init__(self, x: float = None):
        self.color = config.PALETTE["cyan"]
        self.reset(x)

    def reset(self, x: float = None) -> None:
        if x is None:
            x = config.LOGICAL_W / 2
        self.pos = pg.Vector2(x, config.PLAYER_Y)
        self.vel = pg.Vector2(0, 0)
        self._wide = False
        self.width = float(config.player_w())
        self.target_width = self.width
        self.shield = 0
        self.direction = 0
        self.tilt = 0.0             # degrees, visual only
        self.stretch = 0.0          # visual only
        self.impact = 0.0           # 0..1 squash after hitting a wall / catching
        self.wall_hit = 0           # -1/1 for the frame a wall was hit at speed, else 0
        self._clamp()

    #Properties
    @property
    def half_width(self) -> float:
        return self.width / 2

    @property
    def rect(self) -> pg.Rect:
        # Round both edges (not centre + width) so a paddle flush with a wall never pokes 1 px out
        left = round(self.pos.x - self.width / 2)
        right = round(self.pos.x + self.width / 2)
        top = round(self.pos.y - config.PLAYER_H / 2)
        return pg.Rect(left, top, right - left, config.PLAYER_H)

    @property
    def catch_rect(self) -> pg.Rect:
        """Slightly taller than `rect` upward, so fast items never skim past the top edge."""
        r = self.rect
        return pg.Rect(r.x, r.y - 6, r.w, r.h + 6)

    #Control
    def set_wide(self, active: bool) -> None:
        self._wide = active
        self.target_width = config.player_w() * (config.WIDE_FACTOR if active else 1.0)

    def refit(self, old_canvas_w: float) -> None:
        """Canvas width changed (fullscreen / window size): rescale width, keep the relative x."""
        self.pos.x *= config.LOGICAL_W / old_canvas_w
        self.target_width = config.player_w() * (config.WIDE_FACTOR if self._wide else 1.0)
        self.width = self.target_width
        self.vel.x = 0.0
        self._clamp()

    def bump(self, strength: float = 0.6) -> None:
        """Small squash, e.g. when catching an item."""
        self.impact = max(self.impact, min(1.0, strength))

    #Physics
    def update(self, dt: float, direction: int) -> None:
        direction = (direction > 0) - (direction < 0)
        self.direction = direction
        vx = self.vel.x

        if direction:
            accel = config.player_accel()
            if vx * direction < 0:
                accel *= config.PLAYER_TURN_BOOST      # snappier reversals
            vx += accel * direction * dt
            top = config.player_max_speed()
            vx = max(-top, min(top, vx))
        else:
            # Friction toward rest without overshooting zero
            drop = config.player_friction() * dt
            vx = 0.0 if abs(vx) <= drop else vx - math.copysign(drop, vx)

        self.vel.x = vx
        self.pos.x += vx * dt

        # Width eases toward its target (wide power-up), framerate independent
        k = 1.0 - math.exp(-config.PLAYER_WIDTH_RATE * dt)
        self.width += (self.target_width - self.width) * k

        self._clamp()
        self._update_visuals(dt)

    def _clamp(self) -> None:
        """Keep the paddle on screen; soft bounce only when not pushing into the wall."""
        self.wall_hit = 0
        half = self.half_width
        lo, hi = half, config.LOGICAL_W - half
        side = 0
        if self.pos.x < lo:
            self.pos.x, side = lo, -1
        elif self.pos.x > hi:
            self.pos.x, side = hi, 1
        if not side:
            return
        vx = self.vel.x
        if vx * side > 0:                              # moving into the wall
            if abs(vx) > STOP_SPEED * 4:
                self.wall_hit = side
                self.impact = max(self.impact, min(1.0, abs(vx) / config.player_max_speed()))
            bounce = -vx * config.WALL_BOUNCE
            # Holding toward the wall or a tiny rebound -> rest flush against it (no jitter)
            if self.direction == side or abs(bounce) < STOP_SPEED:
                bounce = 0.0
            self.vel.x = bounce

    def _update_visuals(self, dt: float) -> None:
        k = 1.0 - math.exp(-VISUAL_RATE * dt)
        speed = self.vel.x / config.player_max_speed()
        self.tilt += (speed * TILT_MAX - self.tilt) * k
        self.stretch += (abs(speed) * STRETCH_MAX - self.stretch) * k
        self.impact = max(0.0, self.impact - dt * 5.0)

    #Drawing
    def draw(self, surf, t: float) -> None:
        color = self.color
        squash = self.impact * 0.35
        w = self.width * (1 + self.stretch + squash * 0.5)
        h = config.PLAYER_H * (1 - self.stretch * 0.8 - squash * 0.4)
        cx, cy = self.pos.x, self.pos.y + squash * 3

        # Glow (quantised size so the neon cache does not grow per pixel)
        gw = int(w + GLOW_STEP - 1) // GLOW_STEP * GLOW_STEP
        glow_rect_at(surf, (cx, cy), gw, int(h) // 2 * 2, color, radius=int(h / 2))

        # Speed after-images
        speed = self.vel.x / config.player_max_speed()
        if abs(speed) > 0.35:
            for i in (2, 1):
                ghost = self._capsule(cx - self.vel.x * 0.018 * i, cy, w, h)
                pg.draw.polygon(surf, scale_color(color, 0.12 * (3 - i) * abs(speed)), ghost, 2)

        # Body: tilted capsule, dark fill + bright outline + inner highlight
        pts = self._capsule(cx, cy, w, h)
        pg.draw.polygon(surf, scale_color(color, 0.28), pts)
        outline(surf, color, pts, 2)
        hl = mix_color(color, config.PALETTE["white"], 0.65)
        a = math.radians(self.tilt)
        dx, dy = math.cos(a) * (w / 2 - h * 0.6), math.sin(a) * (w / 2 - h * 0.6)
        pg.draw.line(surf, hl, (cx - dx, cy - dy - 2), (cx + dx, cy + dy - 2), 2)

        if self.shield > 0:
            self._draw_shield(surf, cx, cy, w, h, t)

    def _capsule(self, cx, cy, w, h, segments: int = 6) -> list:
        """Rotated capsule (pill) polygon centred at (cx, cy)."""
        r = h / 2
        half = max(0.0, w / 2 - r)
        pts = []
        for i in range(segments + 1):                  # right cap: -90..90 deg
            a = -math.pi / 2 + math.pi * i / segments
            pts.append((half + math.cos(a) * r, math.sin(a) * r))
        for i in range(segments + 1):                  # left cap: 90..270 deg
            a = math.pi / 2 + math.pi * i / segments
            pts.append((-half + math.cos(a) * r, math.sin(a) * r))
        ang = math.radians(self.tilt)
        ca, sa = math.cos(ang), math.sin(ang)
        return [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts]

    def _draw_shield(self, surf, cx, cy, w, h, t) -> None:
        shield_col = config.PALETTE["cyan"]
        pulse = 0.5 + 0.5 * math.sin(t * 5)
        rx, ry = w / 2 + 16, h / 2 + 18
        ring = pg.Rect(0, 0, int(rx * 2) // 4 * 4, int(ry * 2) // 2 * 2)
        glow_rect_at(surf, (cx, cy - 4), ring.w, ring.h, shield_col, radius=ring.h // 2, thickness=2)
        ring.center = (int(cx), int(cy - 4))
        pg.draw.ellipse(surf, mix_color(shield_col, config.PALETTE["white"], 0.3 * pulse), ring, 2)
        # Upper arc slightly brighter: reads as a dome
        pg.draw.arc(surf, config.PALETTE["white"], ring.inflate(-6, -6), math.radians(25), math.radians(155), 1)
