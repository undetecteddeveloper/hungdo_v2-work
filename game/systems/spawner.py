"""Item spawner with fairness rules.

Every good item's landing (time, x) is predicted with the items' own physics. A new good
item is only placed where the paddle can travel from every other pending good landing in
time (conservative paddle model: turn-around + accelerate from rest, x HUMAN_FACTOR), so
consecutive catches are always possible. Bombs never spawn above another recent bomb and
never land right on top of a good item.
"""
import math
import random

from .. import config
from ..entities.items import Item, catch_y

SPAWN_MARGIN = 14                   # px between an item's edge and the side walls
SPAWN_JITTER = 0.15                 # +-15% randomness on spawn intervals
SPAWN_VY = (25.0, 70.0)             # px/s initial fall speed (x level fall-speed mult)
DIAGONAL_VX = (70.0, 150.0)         # px/s sideways speed at level 1 (upper bound grows)

# Paddle model used for fairness (deliberately pessimistic vs. the real Player)
HUMAN_FACTOR = 1.15                 # extra time a human needs vs. perfect input
CATCH_TOLERANCE = config.PLAYER_W / 2   # paddle centre within this of the item x catches it
TURN_TIME = config.PLAYER_MAX_SPEED / (config.PLAYER_ACCEL * config.PLAYER_TURN_BOOST)

BOMB_REPEAT_TIME = 0.4              # s: no bomb directly above another one spawned this recently
BOMB_MIN_DX = config.PLAYER_W * 0.9 # px: "directly above" = closer than this horizontally
BOMB_GOOD_TIME = 0.35               # s: a bomb may not land this close in time to a good item ...
BOMB_GOOD_DX = CATCH_TOLERANCE + 40 # px: ... at less than this horizontal distance
MAX_BOMB_RUN = 2                    # never more than this many bombs in a row

BURST_DX = 34                       # px between items in a burst line
BURST_DY = 90                       # px vertical spacing (arrival rhythm)
RETRY_DELAY = 0.12                  # s: retry soon when no fair spot exists right now
PENDING_WINDOW = 3.0                # s: landings closer than this in time are cross-checked

POWER_WEIGHTS = {"magnet": 3, "slow": 2, "wide": 3, "shield": 2, "heart": 1}


#Paddle travel model (shared with tests)
def travel_time(distance: float) -> float:
    """Seconds for the paddle to move `distance` px from rest (accel-limited, then max speed)."""
    if distance <= 0:
        return 0.0
    a, v = config.PLAYER_ACCEL, config.PLAYER_MAX_SPEED
    d_acc = v * v / (2 * a)
    if distance <= d_acc:
        return math.sqrt(2 * distance / a)
    return v / a + (distance - d_acc) / v


def fair_time(distance: float) -> float:
    """Time the fairness rule demands between two catches `distance` px apart."""
    need = distance - CATCH_TOLERANCE
    if need <= 0:
        return 0.0
    return HUMAN_FACTOR * (TURN_TIME + travel_time(need))


def fair_distance(gap: float) -> float:
    """Inverse of fair_time: max horizontal distance between catches `gap` seconds apart."""
    t = gap / HUMAN_FACTOR - TURN_TIME
    reach = 0.0
    if t > 0:
        a, v = config.PLAYER_ACCEL, config.PLAYER_MAX_SPEED
        t_acc = v / a
        reach = 0.5 * a * t * t if t <= t_acc else v * v / (2 * a) + v * (t - t_acc)
    return CATCH_TOLERANCE + reach


class Spawner:
    def __init__(self, rng: random.Random = None):
        self.rng = rng if rng is not None else random.Random()
        self.allow_heart = True     # play scene may set False while lives are full
        self.reset()

    def reset(self) -> None:
        self.time = 0.0
        self._spawn_timer = 0.35    # first item shortly after GO
        self._power_timer = None    # set from level params on first update
        self._pending = []          # good landings: [t_abs, x, kind]
        self._bombs = []            # bomb spawns: [t_spawn, x, t_land, x_land]
        self._bomb_run = 0
        self._last_power = None
        self.spawned = 0            # stats (debug/tests)

    #Main tick
    def update(self, dt: float, params) -> list:
        """Advance spawn timers; returns newly created Items (caller adds them to the world).

        Pass dt * time_scale while slow-motion is active so spawning slows with the items.
        """
        self.time += dt
        out = []
        if self._power_timer is None:
            self._power_timer = params.powerup_interval * 0.6
        self._spawn_timer -= dt
        if self._spawn_timer <= 0:
            if self.rng.random() < params.burst_chance:
                items = self._spawn_burst(params)
                extra = len(items) - 1
            else:
                items = self._spawn_single(params)
                extra = 0
            if items:
                out.extend(items)
                jitter = self.rng.uniform(1 - SPAWN_JITTER, 1 + SPAWN_JITTER)
                # Bursts count as more than one spawn so the overall rate stays fair
                self._spawn_timer = params.spawn_interval * jitter * (1 + 0.6 * extra)
            else:
                self._spawn_timer = RETRY_DELAY

        self._power_timer -= dt
        if self._power_timer <= 0:
            self._power_timer = params.powerup_interval * self.rng.uniform(0.9, 1.1)
            out.append(self._spawn_powerup(params))

        # Forget landings/bombs that can no longer matter
        horizon = self.time - PENDING_WINDOW
        self._pending = [p for p in self._pending if p[0] > horizon]
        self._bombs = [b for b in self._bombs if b[0] > self.time - BOMB_REPEAT_TIME or b[2] > self.time - 1.0]
        self.spawned += len(out)
        return out

    #Helpers
    def _x_range(self, kind: str) -> tuple:
        m = config.ITEM_RADIUS[kind] + SPAWN_MARGIN
        return m, config.LOGICAL_W - m

    def _vy(self, params) -> float:
        return self.rng.uniform(*SPAWN_VY) * params.max_fall_speed_mult

    def _vx(self, params) -> float:
        t = (params.level - 1) / max(1, config.DIFFICULTY_MAX_LEVEL - 1)
        speed = self.rng.uniform(DIAGONAL_VX[0], DIAGONAL_VX[1] + 60 * t)
        return speed if self.rng.random() < 0.5 else -speed

    def _pick_good_kind(self, params) -> str:
        kinds = list(params.weights)
        return self.rng.choices(kinds, weights=[params.weights[k] for k in kinds])[0]

    def _make(self, kind, x, y, vx, vy, params, power=None) -> Item:
        return Item(kind, x, y, vx, vy, power=power, terminal_mult=params.max_fall_speed_mult)

    def _allowed_interval(self, t_land: float, lo: float, hi: float) -> tuple:
        """Intersect [lo, hi] with every pending landing's fair reach window."""
        for pt, px, _ in self._pending:
            d = fair_distance(abs(t_land - pt))
            lo, hi = max(lo, px - d), min(hi, px + d)
        return lo, hi

    def _near_bomb(self, t_land: float, x: float) -> bool:
        for _, _, bt, bx in self._bombs:
            if abs(bt - t_land) < BOMB_GOOD_TIME and abs(bx - x) < BOMB_GOOD_DX:
                return True
        return False

    #Good items
    def _place_good(self, kind, params, y=None, x_hint=None, allow_diag=True):
        """Create a good item at a fair x, or None if no fair spot exists right now."""
        lo, hi = self._x_range(kind)
        vy = self._vy(params)
        probe = self._make(kind, (lo + hi) / 2, y, 0.0, vy, params)
        t_fall, _ = probe.predict_landing(params.gravity)
        t_land = self.time + t_fall
        a_lo, a_hi = self._allowed_interval(t_land, lo, hi)
        if a_lo > a_hi:
            return None

        vx = self._vx(params) if allow_diag and self.rng.random() < params.diagonal_chance else 0.0
        item = None
        for attempt in range(6):
            if x_hint is not None and attempt == 0:
                x = min(max(x_hint, a_lo), a_hi)
            else:
                x = self.rng.uniform(a_lo, a_hi)
            cand = self._make(kind, x, y, vx, vy, params)
            if vx:
                _, x_land = cand.predict_landing(params.gravity)
                if not (a_lo <= x_land <= a_hi):
                    # Bounce would carry it somewhere unfair: drop it straight instead
                    cand = self._make(kind, x, y, 0.0, vy, params)
                    x_land = x
            else:
                x_land = x
            item = (cand, x_land)
            if not self._near_bomb(t_land, x_land):
                break
        cand, x_land = item
        self._pending.append([t_land, x_land, kind])
        return cand

    def _spawn_single(self, params) -> list:
        if (params.bomb_chance > 0 and self._bomb_run < MAX_BOMB_RUN
                and self.rng.random() < params.bomb_chance):
            bomb = self._place_bomb(params)
            if bomb is not None:
                self._bomb_run += 1
                return [bomb]
        item = self._place_good(self._pick_good_kind(params), params)
        if item is None:
            return []
        self._bomb_run = 0
        return [item]

    def _spawn_burst(self, params) -> list:
        """A short diagonal line of 2-3 good items arriving in a quick rhythm."""
        n = self.rng.choice((2, 3))
        step = BURST_DX if self.rng.random() < 0.5 else -BURST_DX
        lo, hi = self._x_range("common")
        x0 = self.rng.uniform(lo + (abs(step) * (n - 1) if step < 0 else 0),
                              hi - (step * (n - 1) if step > 0 else 0))
        items = []
        for i in range(n):
            kind = self._pick_good_kind(params)
            y = -config.ITEM_RADIUS[kind] - BURST_DY * i
            item = self._place_good(kind, params, y=y, x_hint=x0 + step * i, allow_diag=False)
            if item is None:
                break
            items.append(item)
        if items:
            self._bomb_run = 0
        return items

    #Bombs
    def _place_bomb(self, params):
        lo, hi = self._x_range("bomb")
        vy = self._vy(params)
        diag = self.rng.random() < params.diagonal_chance * 0.5
        for _ in range(10):
            x = self.rng.uniform(lo, hi)
            if self._bomb_too_close(x):
                continue
            vx = self._vx(params) if diag else 0.0
            bomb = self._make("bomb", x, None, vx, vy, params)
            t_fall, x_land = bomb.predict_landing(params.gravity)
            t_land = self.time + t_fall
            if any(abs(t_land - pt) < BOMB_GOOD_TIME and abs(x_land - px) < BOMB_GOOD_DX
                   for pt, px, _ in self._pending):
                continue
            self._bombs.append([self.time, x, t_land, x_land])
            return bomb
        return None                 # no safe spot: caller spawns a good item instead

    def _bomb_too_close(self, x: float) -> bool:
        """Rule: never a bomb directly above another bomb spawned within BOMB_REPEAT_TIME."""
        return any(self.time - bt < BOMB_REPEAT_TIME and abs(bx - x) < BOMB_MIN_DX
                   for bt, bx, _, _ in self._bombs)

    #Power-ups
    def _spawn_powerup(self, params) -> Item:
        names = [n for n in POWER_WEIGHTS if n != "heart" or self.allow_heart]
        weights = [POWER_WEIGHTS[n] for n in names]
        name = self.rng.choices(names, weights=weights)[0]
        if name == self._last_power and len(names) > 1:
            name = self.rng.choices(names, weights=weights)[0]      # discourage repeats
        self._last_power = name
        lo, hi = self._x_range("powerup")
        vy = self._vy(params) * 0.6
        return self._make("powerup", self.rng.uniform(lo, hi), None, 0.0, vy, params, power=name)

    #Introspection (tests / debug overlay)
    def pending_landings(self) -> list:
        return [(t, x, k) for t, x, k in self._pending]


def landing_y(kind: str) -> float:
    """Centre y at which an item of `kind` touches the paddle (re-exported for tests)."""
    return catch_y(config.ITEM_RADIUS[kind])
