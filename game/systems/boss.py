"""Boss fight logic: state machine, patrol, attack patterns, sweep beams and helper drops.

Pure logic (no drawing, no entities import). PlayScene calls `BossController.update()` every physics
step and turns `BossTick.shots` / `BossTick.drops` into Projectiles / helper items.

Fairness rules (3.5) are built into the planner: every volley is checked against the
same conservative paddle model the tests use (the player reacts after REACT s, then runs flat out) and
re-rolled until a comfortable safe spot is reachable before the first shot gets to the paddle line.
Fans get a gate carved into them, rows get one gap, aimed shots lock onto the player's x at fire time
(no prediction), sweeps give a long warning: the boss slides to the player's x, then LOCKS (stops, the column is fixed) for
SWEEP_LOCK s, which is always enough to leave the column in time.
"""
from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, field

import pygame as pg

from .. import config

log = logging.getLogger(config.LOGGER_NAME)

#Local tunables (shared balance values live in config.py)
KIND_DEFS = (
    # colours (boss, accent), hitbox half size, patrol speed px/s (x field_scale ** 0.5), shot colour
    {"colors": ("orange", "yellow"), "half": (84.0, 64.0), "patrol": 82.0, "shot": "orange"},    # Hex Core
    {"colors": ("magenta", "cyan"), "half": (94.0, 56.0), "patrol": 122.0, "shot": "magenta"},   # Prism
    {"colors": ("purple", "green"), "half": (70.0, 70.0), "patrol": 68.0, "shot": "purple"},     # Void Eye
)
PATROL_PHASE_MULT = (1.0, 1.05, 1.1)    # patrol speed per phase
PATROL_MAX = 140.0                      # px/s at 540 wide, whatever the multipliers
PATROL_ACCEL = 240.0                    # px/s^2, smooth start/turn
PATROL_BRAKE = 420.0                    # px/s^2, braking before a charge / sweep
PATROL_PAUSE = (0.15, 0.7)              # s of rest at each patrol target
INTRO_Y_OFFSET = 30.0                   # px above the top edge where the boss starts its descent
HIT_FLASH_TIME = 0.18                   # s for hit_flash to fade 1 -> 0

FIRST_ATTACK_DELAY = 1.3                # s after the fight starts until the first charge
ATTACK_GAP = (2.4, 1.9, 1.5)            # s between volleys by phase (before speed / enrage divisors)
MIN_IDLE = 0.12                         # s of rest after a volley, whatever the divisors
BRAKE_EST = 0.3                         # s the boss needs to stop before charging (counted in the gap)
POST_STAGGER_IDLE = 0.4                 # s after a stagger before the next charge
REPEAT_PENALTY = 0.35                   # weight factor for an attack used in the last two volleys
MIN_AVAIL = 0.5                         # s of free paddle travel a volley must leave (else it waits)
SHOT_MAX_SPEED = 640.0                  # px/s, absolute cap (late cycles x enrage)

SWEEP_FIRST = 4.5                       # s after phase 2 starts until the first sweep
SWEEP_GAP = {2: 9.0, 3: 7.2}            # s between sweep starts by phase
SWEEP_MIN_GAP = 6.0                     # s, hard floor between sweep starts
SWEEP_QUIET = 0.6                       # s without new volleys after a sweep
SWEEP_WARN = {2: 1.8, 3: 1.6}           # s of warning by phase: sliding toward the player, then the lock
SWEEP_WARN_MIN = 1.15                   # s, floor (the contract asks for >= 1.1)
SWEEP_LOCK = 0.85                       # s at the end of the warning: boss frozen, column fixed (the fair escape window)
SWEEP_LOCK_SLIDE_MIN = 0.3              # s of sliding kept even when the warning is cut short (enrage, late cycles)
SWEEP_SLIDE = 600.0                     # px/s (x sqrt(field_scale)): how fast the boss slides to the player's x while aiming
SWEEP_SLIDE_ACCEL = 3000.0              # px/s^2 (x sqrt(field_scale))
SWEEP_EASE = 0.25                       # s before the lock in which the slide fades out (no hard stop)
SWEEP_FIRE_STATIC = 0.55                # s the column stays lethal
SWEEP_REACT = 0.3                       # s: paddle reaction assumed by zones_are_safe
LASER_OPEN_RATE = 5.0                   # 1/s: how fast the firing hatch / cannon of the boss opens (drawing only)
LASER_CLOSE_RATE = 3.0                  # 1/s: ... and closes again after the shot

# Paddle model the planner trusts (the tests use the real Player with a quicker reaction)
REACT = 0.35                            # s before the paddle starts moving
REACH_SAFETY = 0.85                     # share of the theoretical travel distance that is counted on
COMFORT = 0.5                           # x paddle width: smallest free corridor of paddle centres
BAND_PAD = 6                            # px: the hit rect reaches this far above the paddle top
GATE_PAD = 6                            # px extra half-width carved into fans / kept around gaps

# Attack tables: index = phase - 1
AIMED_N = (2, 3, 3)                     # 1-3 bullets, all on the lane locked at fire time
AIMED_DELAY = (0.30, 0.26, 0.18)
AIMED_SPEED = (290.0, 330.0, 380.0)
AIMED_RADIUS = 10.0
TRIDENT_WAVES = (1, 1, 2)
TRIDENT_WAVE_GAP = 0.45
FAN_MAX_DEG = 40.0                      # widest angle (from straight down) of any fan bullet
FAN_SLOTS = (6, 8, 11)
FAN_HALF_DEG = (26.0, 32.0, 36.0)
FAN_SPEED = (270.0, 310.0, 350.0)
SPIN_SLOTS = (9, 9, 12)
SPIN_HALF_DEG = (34.0, 34.0, 38.0)
SPIN_STEP = 0.016                       # s between consecutive bullets of a rotating fan
PRISM_SLOTS = (6, 6, 8)
PRISM_HALF_DEG = (30.0, 30.0, 32.0)
PRISM_LAYER_GAP = 0.42                  # s between the layers of a prism fan
PRISM_DRIFT = 0.10                      # x paddle width: gate drift per layer
ROW_SPEED = (235.0, 265.0, 300.0)
ROW_GAP = (1.75, 1.70, 1.65)            # x paddle width (+ 2 radius): free corridor between row bullets
ROW_PACK = 0.8                          # row spacing = ROW_PACK x (paddle width + 2 radius): never passable
ROW_ZIG_DELAY = 0.15                    # s: every other bullet of a staggered row
ROW2_GAP = 0.5                          # s between the two rows of a double row
ROW2_DRIFT = 0.12                       # x paddle width: gap drift between the two rows

CHARGE_TIME = {"aimed": 0.65, "trident": 0.65, "fan": 0.55, "spin": 0.6, "prism": 0.6,
               "row": 0.7, "row_zig": 0.7, "row2": 0.7}
CHARGE_MIN = {"aimed": 0.55, "trident": 0.55}   # aimed attacks always telegraph for more than 0.5 s
CHARGE_MIN_DEFAULT = 0.4

# Attack pool per kind and phase: (name, weight)
POOLS = {
    0: {1: (("aimed", 3), ("fan", 2)),
        2: (("aimed", 2), ("trident", 2), ("fan", 3)),
        3: (("aimed", 1), ("trident", 2), ("fan", 3), ("spin", 2))},
    1: {1: (("row", 3), ("fan", 2)),
        2: (("row", 2), ("row_zig", 3), ("prism", 2), ("fan", 1)),
        3: (("row_zig", 2), ("row2", 3), ("prism", 3), ("fan", 1))},
    2: {1: (("aimed", 3), ("row", 2)),
        2: (("trident", 2), ("aimed", 2), ("row", 3)),
        3: (("trident", 3), ("aimed", 1), ("row_zig", 2), ("row2", 2))},
}
ROW_SHAPE = {0: "orb", 1: "shard", 2: "orb"}
FAN_SHAPE = {0: "orb", 1: "shard", 2: "orb"}

# Helper drops
DROP_WALL_MARGIN = 40                   # px between a drop's x and the side walls
BALL_RETRY = 0.5                        # s until a blocked helper-ball drop is tried again


#Data classes (contract)
@dataclass
class Shot:
    """Request for one harmful projectile (PlayScene turns it into entities.boss_items.Projectile)."""
    x: float
    y: float
    vx: float
    vy: float
    radius: float = 13.0
    shape: str = "orb"          # "orb" | "bolt" | "shard"
    color: str = "red"          # PALETTE key: only "red" | "orange" | "magenta" | "purple"


@dataclass
class Drop:
    """Request for one helper item at the top of the screen."""
    kind: str                   # "ball" (energy items are dropped by play.py after ball hits)
    x: float


@dataclass
class BossTick:
    shots: list = field(default_factory=list)       # list[Shot]
    drops: list = field(default_factory=list)       # list[Drop]
    events: list = field(default_factory=list)      # list[str]


class Boss:
    """Plain state: BossController mutates it, render/boss_draw reads it, the HUD reads it."""

    def __init__(self, kind: int, number: int):
        d = KIND_DEFS[kind]
        self.kind = kind
        self.number = number
        self.cycle = (number - 1) // config.BOSS_KINDS
        self.name_key = f"boss.kind.{kind}.name"
        self.colors = d["colors"]
        self.pos = pg.Vector2(config.LOGICAL_W / 2, config.BOSS_Y)
        self.half_w, self.half_h = d["half"]
        self.max_hp = config.boss_max_hp(number)
        self.hp = self.max_hp
        self.phase = 1
        self.hit_flash = 0.0
        self.charge = 0.0
        self.enraged = False
        self.anim_t = 0.0
        self.death_t = 0.0
        self.laser = ""                     # firing stage for the animation: "" | "aim" | "lock" | "fire"
        self.laser_k = 0.0                  # 0..1 progress inside that stage
        self.laser_open = 0.0               # 0..1 eased: how far the boss's cannon is open (stays open until the shot is over)

    @property
    def hp_frac(self) -> float:
        return max(0.0, min(1.0, self.hp / self.max_hp)) if self.max_hp > 0 else 0.0

    @property
    def rect(self) -> pg.Rect:
        left = round(self.pos.x - self.half_w)
        right = round(self.pos.x + self.half_w)
        top = round(self.pos.y - self.half_h)
        bottom = round(self.pos.y + self.half_h)
        return pg.Rect(left, top, right - left, bottom - top)


@dataclass
class Sweep:
    """Warning strip, then a beam: a vertical column from the boss's bottom edge to the screen bottom."""
    x_from: float
    x_to: float
    width: float
    warn_time: float
    fire_time: float
    age: float = 0.0
    consumed: bool = False
    lock_time: float = 0.0              # s at the end of the warning in which the column no longer follows the boss
    frozen: bool = False                # set by the controller once the lock has begun

    @property
    def lock_start(self) -> float:
        return max(0.0, self.warn_time - self.lock_time)

    @property
    def locked(self) -> bool:
        """Warning stage in which the column is fixed (the boss stands still and the player must leave)."""
        return self.lock_time > 0.0 and self.phase == "warn" and self.age >= self.lock_start

    @property
    def k_aim(self) -> float:
        """0..1 through the sliding / aiming part of the warning."""
        return _clamp01(self.age / self.lock_start) if self.lock_start > 0.0 else 1.0

    @property
    def k_lock(self) -> float:
        """0..1 through the locked part of the warning (0 while still aiming)."""
        return _clamp01((self.age - self.lock_start) / self.lock_time) if self.lock_time > 0.0 else 0.0

    @property
    def phase(self) -> str:
        if self.age < self.warn_time:
            return "warn"
        if self.age < self.warn_time + self.fire_time:
            return "fire"
        return "done"

    @property
    def zone(self) -> tuple:
        half = self.width / 2
        return min(self.x_from, self.x_to) - half, max(self.x_from, self.x_to) + half

    @property
    def k_warn(self) -> float:
        return _clamp01(self.age / self.warn_time) if self.warn_time > 0 else 1.0

    @property
    def k_fire(self) -> float:
        if self.fire_time <= 0:
            return 1.0
        return _clamp01((self.age - self.warn_time) / self.fire_time)

    @property
    def beam_x(self) -> float:
        return self.x_from + (self.x_to - self.x_from) * self.k_fire

    def update(self, dt: float) -> None:
        self.age += dt

    def hits(self, rect: pg.Rect) -> bool:
        """True while the beam is firing, has not hurt yet, and overlaps `rect` horizontally."""
        if self.phase != "fire" or self.consumed:
            return False
        bx, half = self.beam_x, self.width / 2
        return rect.right > bx - half and rect.left < bx + half


#Planner geometry
@dataclass
class _Planned:
    """One scheduled shot of a volley (internal)."""
    delay: float
    shot: Shot
    layer: int = 0
    lane_x: float = 0.0         # x at the paddle line; used to carve gates


class _Ctx:
    """Everything a pattern needs to know when it fires."""
    __slots__ = ("bx", "by", "half_w", "half_h", "px", "speed", "phase", "kind", "color", "rng",
                 "W", "w", "free", "my")

    def __init__(self, boss: Boss, px: float, speed: float, rng: random.Random, free: float, w_scale: float = 1.0):
        self.bx, self.by = boss.pos.x, boss.pos.y
        self.half_w, self.half_h = boss.half_w, boss.half_h
        self.W = float(config.LOGICAL_W)
        self.px = min(max(px, 0.0), self.W)
        self.speed = speed
        self.phase = boss.phase
        self.kind = boss.kind
        self.color = "red" if boss.enraged else KIND_DEFS[boss.kind]["shot"]
        self.rng = rng
        self.w = float(config.player_w()) * w_scale
        self.free = free                    # s until the previous volley has left the paddle line
        self.my = self.by + self.half_h * 0.55      # muzzle y


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v


def _band() -> tuple:
    """(top, bottom) of the zone where a shot centre row can touch the paddle (top includes BAND_PAD)."""
    return (config.PLAYER_Y - config.PLAYER_H / 2 - BAND_PAD, config.PLAYER_Y + config.PLAYER_H / 2)


def reach_distance(t: float) -> float:
    """Max px the paddle can cover and come to rest within `t` s, starting from rest at full effort."""
    if t <= 0:
        return 0.0
    a = config.player_accel()
    vmax = config.player_max_speed()
    b = a * config.PLAYER_TURN_BOOST
    t_ramp = vmax / a + vmax / b
    if t <= t_ramp:
        vp = t / (1.0 / a + 1.0 / b)
        return 0.5 * vp * t
    d_ramp = vmax * vmax / (2 * a) + vmax * vmax / (2 * b)
    return d_ramp + vmax * (t - t_ramp)


def _lane(p: _Planned, w: float) -> tuple | None:
    """(t_in, t_out, c_lo, c_hi): when the shot is in the paddle band and which paddle centres it blocks."""
    s = p.shot
    if s.vy <= 1e-6:
        return None
    top, bottom = _band()
    r = s.radius
    t_in = max(0.0, (top - r - s.y) / s.vy)
    t_out = max(t_in, (bottom + r - s.y) / s.vy)
    xa, xb = s.x + s.vx * t_in, s.x + s.vx * t_out
    lo, hi = min(xa, xb) - w / 2 - r, max(xa, xb) + w / 2 + r
    return p.delay + t_in, p.delay + t_out, lo, hi


def first_arrival(plan: list, w: float = None) -> float:
    """Seconds until the first shot of the plan reaches the paddle band (inf if none ever does)."""
    w = config.player_w() if w is None else w
    arr = [lane[0] for lane in (_lane(p, w) for p in plan) if lane is not None]
    return min(arr) if arr else math.inf


def _free_spans(blocked: list, lo: float, hi: float) -> list:
    """Complement of the blocked (a, b) intervals inside [lo, hi]."""
    spans, cur = [], lo
    for a, b in sorted(blocked):
        if b <= cur:
            continue
        if a > cur:
            spans.append((cur, min(a, hi)))
        cur = max(cur, b)
        if cur >= hi:
            break
    if cur < hi:
        spans.append((cur, hi))
    return [(a, b) for a, b in spans if b - a > 1e-6]


def _reachable(spans: list, px: float, w: float, t_avail: float) -> bool:
    """Is some comfortable span's core within reach of the paddle (px) in `t_avail` s?"""
    reach = reach_distance(t_avail) * REACH_SAFETY
    for a, b in spans:
        if b - a < COMFORT * w:
            continue
        q = min(0.15 * w, 0.3 * (b - a))
        d = max(0.0, a + q - px, px - (b - q))
        if d <= reach:
            return True
    return False


def plan_is_safe(plan: list, px: float, free: float = 0.0, w: float = None) -> bool:
    """Conservative check: a comfortable free corridor exists and the paddle can get there in time.

    `free` = seconds before the paddle may start moving because earlier shots are still passing;
    `w` = paddle width (default config.player_w()).
    """
    w = config.player_w() if w is None else w
    W = float(config.LOGICAL_W)
    lanes = [lane for lane in (_lane(p, w) for p in plan) if lane is not None]
    if not lanes:
        return True
    t_first = min(l[0] for l in lanes)
    spans = _free_spans([(l[2], l[3]) for l in lanes], w / 2, W - w / 2)
    return _reachable(spans, px, w, t_first - max(REACT, free))


def zones_are_safe(zones: list, px: float, warn: float, w: float = None) -> bool:
    """Same idea for sweep zones: the paddle must leave all of them before the beam fires."""
    w = config.player_w() if w is None else w
    W = float(config.LOGICAL_W)
    spans = _free_spans([(z0 - w / 2, z1 + w / 2) for z0, z1 in zones], w / 2, W - w / 2)
    return _reachable(spans, px, w, warn - SWEEP_REACT)


#Pattern builders (all return list[_Planned])
def _spd(ctx: _Ctx, base: float) -> float:
    return min(SHOT_MAX_SPEED, base * ctx.speed)


def _mk(ctx: _Ctx, delay: float, x: float, y: float, vx: float, vy: float, radius: float,
        shape: str, layer: int = 0) -> _Planned:
    shot = Shot(x, y, vx, vy, radius, shape, ctx.color)
    lane_x = x + vx * (config.PLAYER_Y - y) / vy if vy > 1e-6 else x
    return _Planned(delay, shot, layer, lane_x)


def _aim(ctx: _Ctx, delay: float, sx: float, tx: float, v: float, radius: float, shape: str,
         layer: int = 0) -> _Planned:
    dx, dy = tx - sx, config.PLAYER_Y - ctx.my
    d = math.hypot(dx, dy)
    return _mk(ctx, delay, sx, ctx.my, v * dx / d, v * dy / d, radius, shape, layer)


def _build_aimed(ctx: _Ctx) -> list:
    i = ctx.phase - 1
    v = _spd(ctx, AIMED_SPEED[i])
    out = []
    for j in range(AIMED_N[i]):
        sx = ctx.bx + (j % 3 - 1) * ctx.half_w * 0.45       # muzzles alternate across the body
        out.append(_aim(ctx, j * AIMED_DELAY[i], sx, ctx.px, v, AIMED_RADIUS, "bolt"))
    return out


def _build_trident(ctx: _Ctx) -> list:
    """Three simultaneous lanes around the player: the safe spots are the two corridors between them."""
    i = ctx.phase - 1
    v = _spd(ctx, AIMED_SPEED[i])
    r = AIMED_RADIUS
    span = ctx.w * (1.0 + 0.7) + 2 * r + 4                  # lane spacing: corridor of 0.7 x paddle width
    out = []
    for wave in range(TRIDENT_WAVES[i]):
        for j, off in enumerate((-span, 0.0, span)):
            sx = ctx.bx + (j - 1) * ctx.half_w * 0.45
            out.append(_aim(ctx, wave * TRIDENT_WAVE_GAP, sx, ctx.px + off, v, r, "bolt"))
    return out


def _fan_layer(ctx: _Ctx, slots: int, half_deg: float, v: float, lean: float, layer: int, delay: float,
               shape: str, phase_shift: float = 0.0, step_delay: float = 0.0, reverse: bool = False) -> list:
    """`slots` bullets evenly spread over [lean - half, lean + half] degrees from the body (0 deg = straight down)."""
    out = []
    step = 2 * half_deg / (slots - 1) if slots > 1 else 0.0
    for j in range(slots):
        a = math.radians(lean - half_deg + j * step + phase_shift * step)
        rank = (slots - 1 - j) if reverse else j
        out.append(_mk(ctx, delay + rank * step_delay, ctx.bx, ctx.my, v * math.sin(a), v * math.cos(a),
                       13.0, shape, layer))
    return out


def _carve(plan: list, centers: dict, half: float) -> list:
    """Drop every shot whose lane is closer than `half` to its layer's gate centre."""
    return [p for p in plan if abs(p.lane_x - centers[p.layer]) >= half]


def _gated(ctx: _Ctx, build) -> list:
    """Use `build(gc)` (gc=None: no gate); only carve a gate when the raw pattern would leave no way out."""
    raw = build(None)
    if plan_is_safe(raw, ctx.px, ctx.free, ctx.w):
        return raw
    return _search_gap(ctx, build)


def _search_gap(ctx: _Ctx, build, margin: float = None) -> list:
    """Sample gap centres near the paddle's reach; the first safe plan wins, the gap at the paddle is the fallback.

    `margin` = nearest a gap centre may get to a side wall (default 0.75 paddle widths).
    """
    w, W = ctx.w, ctx.W
    margin = 0.75 * w if margin is None else margin
    lo, hi = min(margin, W / 2), max(W - margin, W / 2)
    here = build(min(max(ctx.px, lo), hi))
    t_first = first_arrival(here, w)
    avail = t_first - max(REACT, ctx.free)
    reach = W if math.isinf(avail) else reach_distance(avail) * REACH_SAFETY
    for _ in range(10):
        gc = min(max(ctx.px + ctx.rng.uniform(-reach, reach), lo), hi)
        plan = build(gc)
        if plan_is_safe(plan, ctx.px, ctx.free, ctx.w):
            return plan
    return here


def _build_fan(ctx: _Ctx) -> list:
    i = ctx.phase - 1
    half_deg = FAN_HALF_DEG[i]
    lean = ctx.rng.uniform(-1.0, 1.0) * (FAN_MAX_DEG - half_deg)
    v = _spd(ctx, FAN_SPEED[i])
    shape = FAN_SHAPE[ctx.kind]
    gap_half = 0.85 * ctx.w + 13.0 + GATE_PAD

    def build(gc):
        plan = _fan_layer(ctx, FAN_SLOTS[i], half_deg, v, lean, 0, 0.0, shape)
        return plan if gc is None else _carve(plan, {0: gc}, gap_half)

    return _gated(ctx, build)


def _build_spin(ctx: _Ctx) -> list:
    """A fan whose bullets leave one after another, so it looks like a spray rotating across the cone."""
    i = ctx.phase - 1
    half_deg = SPIN_HALF_DEG[i]
    v = _spd(ctx, FAN_SPEED[i])
    reverse = ctx.rng.random() < 0.5
    gap_half = 0.85 * ctx.w + 13.0 + GATE_PAD

    def build(gc):
        plan = _fan_layer(ctx, SPIN_SLOTS[i], half_deg, v, 0.0, 0, 0.0, "orb", step_delay=SPIN_STEP, reverse=reverse)
        return plan if gc is None else _carve(plan, {0: gc}, gap_half)

    return _gated(ctx, build)


def _build_prism(ctx: _Ctx) -> list:
    """Two fan layers with interleaved lanes and a gate that drifts a little between them."""
    i = ctx.phase - 1
    half_deg = PRISM_HALF_DEG[i]
    v = _spd(ctx, FAN_SPEED[i])
    drift = ctx.rng.choice((-1.0, 1.0)) * PRISM_DRIFT * ctx.w
    gap_half = 0.85 * ctx.w + 13.0 + GATE_PAD

    def build(gc):
        plan = (_fan_layer(ctx, PRISM_SLOTS[i], half_deg, v, 0.0, 0, 0.0, "shard")
                + _fan_layer(ctx, PRISM_SLOTS[i], half_deg, v, 0.0, 1, PRISM_LAYER_GAP, "shard", phase_shift=0.5))
        return plan if gc is None else _carve(plan, {0: gc, 1: gc + drift}, gap_half)

    return _gated(ctx, build)


def _row_layer(ctx: _Ctx, gc: float, gap: float, v: float, delay: float, layer: int, zig: bool) -> list:
    """Bullets across the whole field except one gap (centre gc, bullet-to-bullet width `gap`)."""
    r = 13.0
    step = ROW_PACK * (ctx.w + 2 * r)
    y0 = ctx.by + ctx.half_h + 6.0
    shape = ROW_SHAPE[ctx.kind]
    xs = []
    x = gc - gap / 2
    while x > -r:
        xs.append(x)
        x -= step
    x = gc + gap / 2
    while x < ctx.W + r:
        xs.append(x)
        x += step
    xs.sort()
    return [_mk(ctx, delay + (ROW_ZIG_DELAY if zig and k % 2 else 0.0), x, y0, 0.0, v, r, shape, layer)
            for k, x in enumerate(xs)]


def _build_row(ctx: _Ctx, zig: bool = False, double: bool = False) -> list:
    i = ctx.phase - 1
    v = _spd(ctx, ROW_SPEED[i])
    gap = ROW_GAP[i] * ctx.w + 2 * 13.0
    drift = ctx.rng.choice((-1.0, 1.0)) * ROW2_DRIFT * ctx.w
    lo, hi = gap / 2 + 2.0, ctx.W - gap / 2 - 2.0

    def build(gc):
        plan = _row_layer(ctx, gc, gap, v, 0.0, 0, zig)
        if double:
            gc2 = gc + drift if lo <= gc + drift <= hi else gc - drift      # keep both rows' gaps inside the field
            plan += _row_layer(ctx, gc2, gap, v, ROW2_GAP, 1, zig)
        return plan

    return _search_gap(ctx, build, margin=gap / 2 + 2.0)


BUILDERS = {
    "aimed": _build_aimed,
    "trident": _build_trident,
    "fan": _build_fan,
    "spin": _build_spin,
    "prism": _build_prism,
    "row": _build_row,
    "row_zig": lambda ctx: _build_row(ctx, zig=True),
    "row2": lambda ctx: _build_row(ctx, zig=True, double=True),
}


def _beam_width() -> float:
    return max(90.0, min(150.0, 100.0 * config.field_scale() ** 0.35))


#Controller
class BossController:
    """Owns one boss fight. `update()` returns what to spawn; `damage()` is called by balls / beams."""

    def __init__(self, rng: random.Random = None):
        self.rng = rng if rng is not None else random.Random()
        self.state = "idle"                 # idle | intro | fight | enrage | victory | done
        self.boss = None                    # type: Boss | None
        self.sweeps = []                    # list[Sweep] alive (warn or fire)
        self.time_left = 0.0                # s until the boss enrages (0 once enraged)
        self.attack = ""                    # name of the attack being charged / last fired (UI, tests)
        self.paddle_scale = 1.0             # PlayScene may set paddle.width / config.player_w() (wide power-up)
        self.charge_time = 0.0              # s of wind-up of that attack
        self._reset_runtime()

    def _reset_runtime(self) -> None:
        self._clock = 0.0                   # s of fight time (drives clear_at)
        self._state_t = 0.0
        self._events = []                   # queued events delivered by the next update()
        self._queue = []                    # [delay, Shot] still to be emitted
        self._astate = "idle"               # idle | brake | charge
        self._next = "attack"               # what the current brake leads to: "attack" | "sweep"
        self._idle_t = FIRST_ATTACK_DELAY
        self._charge_t = 0.0
        self._charge_dur = 0.0
        self._hold_t = 0.0
        self._stagger_t = 0.0
        self._sweep_t = math.inf            # armed when phase 2 starts
        self._sweep_pending = False
        self._fire_sent = False
        self._clear_at = 0.0                # fight time when the last fired shot has left the paddle band
        self._recent = []                   # last attack names
        self._ball_t = config.BOSS_FIRST_BALL
        self._vx = 0.0
        self._target = None
        self._pause = 0.0
        self._y0 = -80.0

    #Contract helpers
    @staticmethod
    def design(number: int) -> tuple:
        """(kind, cycle) of boss `number` (1-based)."""
        n = max(1, int(number))
        return (n - 1) % config.BOSS_KINDS, (n - 1) // config.BOSS_KINDS

    @property
    def active(self) -> bool:
        return self.state not in ("idle", "done")

    @property
    def fighting(self) -> bool:
        return self.state in ("fight", "enrage")

    @property
    def damageable(self) -> bool:
        return self.fighting

    @property
    def hit_rect(self):
        return self.boss.rect if self.damageable and self.boss is not None else None

    @property
    def speed(self) -> float:
        """Attack speed multiplier from the cycle (not counting the enrage bonus)."""
        return 1.0 + config.BOSS_SPEED_GROWTH * (self.boss.cycle if self.boss else 0)

    #Lifecycle
    def start(self, number: int) -> Boss:
        number = max(1, int(number))
        kind, _ = self.design(number)
        self._reset_runtime()
        boss = Boss(kind, number)
        self._y0 = -boss.half_h - INTRO_Y_OFFSET
        boss.pos.update(config.LOGICAL_W / 2, self._y0)
        self.boss = boss
        self.sweeps.clear()
        self.state = "intro"
        self.time_left = float(config.BOSS_TIME_LIMIT)
        self.attack = ""
        self.charge_time = 0.0
        log.debug("boss %d start: kind %d cycle %d hp %.0f", number, kind, boss.cycle, boss.max_hp)
        return boss

    def stop(self) -> None:
        self.state = "idle"
        self.boss = None
        self.sweeps.clear()
        self.time_left = 0.0
        self.attack = ""
        self.charge_time = 0.0
        self._reset_runtime()

    def on_resize(self, old_w: int) -> None:
        """Canvas width changed: keep the relative x of the boss, sweeps and anything still queued."""
        if not old_w or old_w == config.LOGICAL_W or self.boss is None:
            return
        k = config.LOGICAL_W / old_w
        lo, hi = self._x_range()
        self.boss.pos.x = min(max(self.boss.pos.x * k, lo), hi)
        if self._target is not None:
            self._target = min(max(self._target * k, lo), hi)
        self._vx *= k
        bw = _beam_width()
        for sw in self.sweeps:
            sw.x_from *= k
            sw.x_to *= k
            sw.width = bw
        for item in self._queue:
            item[1].x *= k

    #Damage
    def damage(self, amount: float, source: str = "beam") -> float:
        """Hurt the boss. Returns the hp actually removed (0 outside fight / enrage)."""
        if not self.damageable or self.boss is None:
            return 0.0
        amount = float(amount)
        if not amount > 0.0:                # also rejects NaN
            return 0.0
        b = self.boss
        dealt = min(amount, b.hp)
        b.hp -= dealt
        b.hit_flash = 1.0
        if b.hp <= 1e-9:
            b.hp = 0.0
            self._die()
        else:
            self._check_phase()
        return dealt

    def ball_lost(self) -> None:
        """A helper ball fell past the paddle: the next one is dropped no sooner than BOSS_BALL_RESPAWN from now."""
        self._ball_t = max(self._ball_t, config.BOSS_BALL_RESPAWN)

    def sweep_hits(self, rect: pg.Rect) -> bool:
        """True if a firing sweep touches `rect`; that sweep is then consumed (hurts once)."""
        for sw in self.sweeps:
            if sw.hits(rect):
                sw.consumed = True
                return True
        return False

    def _die(self) -> None:
        self.state = "victory"
        self._state_t = 0.0
        b = self.boss
        b.charge = 0.0
        b.death_t = 0.0
        b.laser, b.laser_k, b.laser_open = "", 0.0, 0.0
        self._queue.clear()
        self.sweeps.clear()
        self._astate = "idle"
        self._events.append("dead")

    def _check_phase(self) -> None:
        b = self.boss
        frac = b.hp_frac
        new = 1 + (frac <= config.BOSS_PHASE_AT[0]) + (frac <= config.BOSS_PHASE_AT[1])
        if new <= b.phase:
            return
        for ph in range(b.phase + 1, new + 1):
            self._events.append(f"phase{ph}")
        if b.phase < 2 <= new and self._sweep_t == math.inf:
            self._sweep_t = SWEEP_FIRST
        b.phase = new
        self._stagger_t = float(config.BOSS_STAGGER_TIME)
        self._astate = "idle"
        self._queue.clear()
        b.charge = 0.0
        self._hold_t = 0.0

    #Update
    def update(self, dt: float, player_x: float, balls_alive: int = 0) -> BossTick:
        tick = BossTick([], [], [])
        if self._events:
            tick.events.extend(self._events)
            self._events.clear()
        b = self.boss
        if b is None or dt <= 0.0 or self.state == "idle":
            return tick
        if not math.isfinite(player_x):
            player_x = config.LOGICAL_W / 2
        if self.state != "done":
            b.anim_t += dt
        b.hit_flash = max(0.0, b.hit_flash - dt / HIT_FLASH_TIME)

        if self.state == "intro":
            self._update_intro(dt, tick)
        elif self.state in ("fight", "enrage"):
            self._update_fight(dt, player_x, balls_alive, tick)
        elif self.state == "victory":
            self._state_t += dt
            b.death_t = _clamp01(self._state_t / config.BOSS_VICTORY_TIME)
            if self._state_t >= config.BOSS_VICTORY_TIME:
                self.state = "done"
                b.death_t = 1.0
                tick.events.append("done")
        return tick

    def _update_intro(self, dt: float, tick: BossTick) -> None:
        b = self.boss
        self._state_t += dt
        k = _clamp01(self._state_t / config.BOSS_INTRO_TIME)
        e = 1.0 - (1.0 - k) ** 3
        b.pos.y = self._y0 + (config.BOSS_Y - self._y0) * e
        if k >= 1.0:
            b.pos.y = float(config.BOSS_Y)
            self.state = "fight"
            self._state_t = 0.0
            tick.events.append("intro_end")

    def _update_fight(self, dt: float, px: float, balls_alive: int, tick: BossTick) -> None:
        b = self.boss
        self._clock += dt
        if self.state == "fight":
            self.time_left = max(0.0, self.time_left - dt)
            if self.time_left <= 0.0:
                self.state = "enrage"
                b.enraged = True
                tick.events.append("enrage")
        if self._stagger_t > 0.0:
            self._stagger_t -= dt
            if self._stagger_t <= 0.0:
                self._idle_t = max(self._idle_t, POST_STAGGER_IDLE)
        self._update_sweeps(dt, tick)
        self._step_attacks(dt, px, tick)
        self._flush_queue(dt, tick)
        if self._aiming():
            self._slide(dt, px)
        else:
            self._patrol(dt, hold=self._holding())
        self._sync_laser(dt)
        self._step_drops(dt, balls_alive, tick)

    #Sweeps
    def _update_sweeps(self, dt: float, tick: BossTick) -> None:
        if self.boss.phase >= 2 and not self._sweep_pending and not math.isinf(self._sweep_t):
            self._sweep_t -= dt
            if self._sweep_t <= 0.0:
                self._sweep_pending = True
        if not self.sweeps:
            return
        for sw in self.sweeps:
            sw.update(dt)
            if sw.locked and not sw.frozen:
                sw.frozen = True                    # the column stays where the boss stands, and the boss stands still
                self._vx = 0.0
                self._target = None
        if not self._fire_sent and any(sw.phase == "fire" for sw in self.sweeps):
            self._fire_sent = True
            tick.events.append("sweep_fire")
        self.sweeps[:] = [sw for sw in self.sweeps if sw.phase != "done"]
        if not self.sweeps:
            self._idle_t = max(self._idle_t, SWEEP_QUIET)

    def _aiming(self) -> bool:
        """A sweep is in its aiming part: the boss slides toward the player and the column follows the boss."""
        sw = self.sweeps[0] if self.sweeps else None
        return sw is not None and sw.lock_time > 0.0 and sw.phase == "warn" and not sw.locked

    def _slide(self, dt: float, px: float) -> None:
        """Glide toward the player's x (fast, eased out before the lock)."""
        b = self.boss
        sw = self.sweeps[0]
        scale = math.sqrt(config.field_scale())
        lo, hi = self._x_range()
        dist = min(max(px, lo), hi) - b.pos.x
        accel = SWEEP_SLIDE_ACCEL * scale
        t_left = max(0.0, sw.lock_start - sw.age)
        cap = SWEEP_SLIDE * scale * min(1.0, t_left / SWEEP_EASE)
        v_des = math.copysign(min(cap, math.sqrt(2 * accel * 0.8 * abs(dist))), dist) if abs(dist) > 1.0 else 0.0
        dv = accel * dt
        if abs(v_des - self._vx) <= dv:
            self._vx = v_des
        else:
            self._vx += math.copysign(dv, v_des - self._vx)
        b.pos.x += self._vx * dt
        if b.pos.x < lo or b.pos.x > hi:
            b.pos.x = min(max(b.pos.x, lo), hi)
            self._vx = 0.0
        self._target = None

    def _sync_laser(self, dt: float) -> None:
        """Keep the unlocked column under the boss and publish the firing stage for the animation."""
        b = self.boss
        sw = self.sweeps[0] if self.sweeps else None
        if sw is None:
            b.laser, b.laser_k = "", 0.0
        else:
            for other in self.sweeps:
                if other.lock_time > 0.0 and not other.frozen and other.phase == "warn":
                    other.x_from = other.x_to = b.pos.x
            if sw.phase == "fire":
                b.laser, b.laser_k = "fire", sw.k_fire
            elif sw.locked:
                b.laser, b.laser_k = "lock", sw.k_lock
            else:
                b.laser, b.laser_k = "aim", sw.k_aim
        goal = 1.0 if sw is not None else 0.0
        if goal > b.laser_open:
            b.laser_open = min(goal, b.laser_open + LASER_OPEN_RATE * dt)
        else:
            b.laser_open = max(goal, b.laser_open - LASER_CLOSE_RATE * dt)

    def plan_sweeps(self, player_x: float = None) -> list:
        """The sweep the boss would start now: a column under the boss's CURRENT x (it follows the boss while it slides to the
        player, then freezes). Sizes and timing follow phase, speed and enrage. Test / debug hook."""
        b = self.boss
        ph = min(3, max(2, b.phase))
        div = math.sqrt(self.speed * (config.BOSS_ENRAGE_RATE if b.enraged else 1.0))
        warn = max(SWEEP_WARN_MIN, SWEEP_WARN[ph] / div)
        lock = min(SWEEP_LOCK, warn - SWEEP_LOCK_SLIDE_MIN)
        return [Sweep(b.pos.x, b.pos.x, _beam_width(), warn, SWEEP_FIRE_STATIC, lock_time=lock)]

    def _start_sweep(self, px: float, tick: BossTick) -> None:
        b = self.boss
        ph = min(3, max(2, b.phase))
        self.sweeps[:] = self.plan_sweeps(px)
        self._vx = 0.0
        self._sweep_pending = False
        self._fire_sent = False
        gap = SWEEP_GAP[ph] / (self.speed * (config.BOSS_ENRAGE_RATE if b.enraged else 1.0))
        self._sweep_t = max(SWEEP_MIN_GAP, gap * self.rng.uniform(0.92, 1.08))
        tick.events.append("sweep_warn")

    #Attacks
    def _shot_speed(self) -> float:
        return self.speed * (config.BOSS_ENRAGE_SPEED if self.boss.enraged else 1.0)

    def _gap(self) -> float:
        b = self.boss
        return ATTACK_GAP[b.phase - 1] / (self.speed * (config.BOSS_ENRAGE_RATE if b.enraged else 1.0))

    def attack_pool(self) -> tuple:
        """Attack names the boss may pick right now."""
        b = self.boss
        return tuple(n for n, _ in POOLS[b.kind][b.phase])

    def plan_attack(self, name: str, player_x: float, free: float = 0.0) -> list:
        """Build attack `name` for the boss as it is now: list of (delay s, Shot). Test / debug hook."""
        ctx = _Ctx(self.boss, player_x, self._shot_speed(), self.rng, free, self.paddle_scale)
        return [(p.delay, p.shot) for p in BUILDERS[name](ctx)]

    def _pick_attack(self) -> str:
        b = self.boss
        pool = POOLS[b.kind][b.phase]
        weights = [w * (REPEAT_PENALTY if n in self._recent[-2:] else 1.0) for n, w in pool]
        return self.rng.choices([n for n, _ in pool], weights=weights)[0]

    def _holding(self) -> bool:
        """The boss stands still: braking, charging, firing a staggered volley, sweeping or staggered."""
        return (self._astate != "idle" or bool(self.sweeps) or bool(self._queue)
                or self._stagger_t > 0.0)

    def _step_attacks(self, dt: float, px: float, tick: BossTick) -> None:
        b = self.boss
        st = self._astate
        if st == "idle":
            self._idle_t = max(0.0, self._idle_t - dt)
            if self.sweeps or self._stagger_t > 0.0 or self._queue:
                return
            if self._sweep_pending:
                if self._clock >= self._clear_at:
                    self._astate, self._next = "brake", "sweep"
            elif self._idle_t <= 0.0:
                self._astate, self._next = "brake", "attack"
        elif st == "brake":
            if self._vx != 0.0:
                return
            if self._next == "sweep":
                self._astate = "idle"
                self._start_sweep(px, tick)
            else:
                name = self._pick_attack()
                self._astate = "charge"
                self._charge_t = 0.0
                self._hold_t = 0.0
                self.attack = name
                base = CHARGE_TIME[name]
                self._charge_dur = max(CHARGE_MIN.get(name, CHARGE_MIN_DEFAULT), base / math.sqrt(self._shot_speed()))
                self.charge_time = self._charge_dur
                tick.events.append("charge")
        elif st == "charge":
            if self._hold_t > 0.0:
                self._hold_t -= dt
                return
            self._charge_t += dt
            b.charge = _clamp01(self._charge_t / self._charge_dur)
            if self._charge_t >= self._charge_dur:
                self._fire(px, tick)

    def _fire(self, px: float, tick: BossTick) -> None:
        b = self.boss
        free = max(0.0, self._clear_at - self._clock)
        ctx = _Ctx(b, px, self._shot_speed(), self.rng, free, self.paddle_scale)
        plan = BUILDERS[self.attack](ctx)
        if free > 0.0:
            # Earlier shots are still passing: wait until this volley leaves enough time to react
            avail = first_arrival(plan, ctx.w) - max(REACT, free)
            if avail < MIN_AVAIL:
                self._hold_t = max(0.02, MIN_AVAIL - avail)
                return
        plan.sort(key=lambda p: p.delay)
        w = ctx.w
        for p in plan:
            self._queue.append([p.delay, p.shot])
            lane = _lane(p, w)
            if lane is not None:
                self._clear_at = max(self._clear_at, self._clock + lane[1])
        self._recent.append(self.attack)
        del self._recent[:-4]
        b.charge = 0.0
        self._astate = "idle"
        self._idle_t = max(MIN_IDLE, self._gap() - self._charge_dur - BRAKE_EST)
        tick.events.append("volley")

    def _flush_queue(self, dt: float, tick: BossTick) -> None:
        if not self._queue:
            return
        rest = []
        for item in self._queue:
            item[0] -= dt
            if item[0] <= 0.0:
                tick.shots.append(item[1])
            else:
                rest.append(item)
        self._queue = rest

    #Patrol
    def _x_range(self) -> tuple:
        b = self.boss
        lo = b.half_w + config.BOSS_MARGIN
        hi = config.LOGICAL_W - lo
        if hi < lo:
            lo = hi = config.LOGICAL_W / 2
        return lo, hi

    def _patrol(self, dt: float, hold: bool) -> None:
        b = self.boss
        scale = math.sqrt(config.field_scale())
        lo, hi = self._x_range()
        if hold:
            dv = PATROL_BRAKE * scale * dt
            self._vx = 0.0 if abs(self._vx) <= dv else self._vx - math.copysign(dv, self._vx)
        else:
            speed = min(PATROL_MAX, KIND_DEFS[b.kind]["patrol"] * PATROL_PHASE_MULT[b.phase - 1]) * scale
            accel = PATROL_ACCEL * scale
            v_des = 0.0
            if self._pause > 0.0:
                self._pause -= dt
            else:
                if self._target is None:
                    self._target = self._pick_target(lo, hi)
                dist = self._target - b.pos.x
                if abs(dist) < 1.5 and abs(self._vx) < 8.0:
                    self._target = self._pick_target(lo, hi)
                    self._pause = self.rng.uniform(*PATROL_PAUSE)
                else:
                    v_des = math.copysign(min(speed, math.sqrt(2 * accel * 0.8 * abs(dist))), dist)
            dv = accel * dt
            if abs(v_des - self._vx) <= dv:
                self._vx = v_des
            else:
                self._vx += math.copysign(dv, v_des - self._vx)
        if self._vx:
            b.pos.x += self._vx * dt
            if b.pos.x < lo or b.pos.x > hi:
                b.pos.x = min(max(b.pos.x, lo), hi)
                self._vx = 0.0

    def _pick_target(self, lo: float, hi: float) -> float:
        span = hi - lo
        if span <= 0.0:
            return lo
        for _ in range(6):
            t = self.rng.uniform(lo, hi)
            if abs(t - self.boss.pos.x) >= 0.25 * span:
                return t
        return lo if self.boss.pos.x > (lo + hi) / 2 else hi

    #Helper drops
    def _drop_x(self) -> float:
        return self.rng.uniform(DROP_WALL_MARGIN, config.LOGICAL_W - DROP_WALL_MARGIN)

    def _jitter(self, interval: float) -> float:
        j = config.BOSS_HELPER_JITTER
        return interval * self.rng.uniform(1.0 - j, 1.0 + j)

    def _step_drops(self, dt: float, balls_alive: int, tick: BossTick) -> None:
        # Energy items are not scheduled: play.py drops one every BOSS_HITS_PER_ENERGY ball hits on the boss
        self._ball_t -= dt
        if self._ball_t <= 0.0:
            if balls_alive < config.BOSS_MAX_BALLS:
                tick.drops.append(Drop("ball", self._drop_x()))
                self._ball_t = self._jitter(config.BOSS_BALL_INTERVAL)
            else:
                self._ball_t = BALL_RETRY
