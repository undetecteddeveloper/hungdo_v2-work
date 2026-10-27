"""Autoplay helper for boss fights: steer the real paddle to a safe spot near a goal.

The planner replays the paddle's own physics towards each candidate x and checks the whole path against
the straight-line flight of every shot and against the sweep zones (look-ahead 6.5 s). It prefers the
spot closest to the goal (a ball to keep alive, the boss to line up under) whose approach is clean, and
settles for the one that delays the first hit longest when nothing is. The idea comes from the dodging
bot in tests/test_boss.py, which takes (almost) no hits over whole fights.
"""
import math

import numpy as np

from .. import config
from .boss import BAND_PAD

STEP = 1 / 60                       # the bot's own paddle model step
MOVE_STEPS = 90                     # the paddle model runs 1.5 s, then it is assumed to stand still
LOOK = np.concatenate((np.arange(1, MOVE_STEPS + 1) * STEP, 1.5 + np.arange(1, 101) / 20.0))   # grid, 6.5 s
N_LOOK = len(LOOK)


def drive(x: float, v: float, target: float, brake: float) -> int:
    """Input direction (-1/0/1) steering the paddle to `target`: bang-bang with active braking."""
    err = target - x
    stop = v * abs(v) / (2 * brake)
    if v * err < 0:
        return 1 if err > 0 else -1
    if abs(stop) >= abs(err) - 1.0 and v != 0:
        return -1 if v > 0 else 1
    return 0 if abs(err) < 2.0 else (1 if err > 0 else -1)


def path(x0: float, v0: float, target: float, width: float) -> np.ndarray:
    """Paddle x on the look-ahead grid when steered to `target` (mirrors Player + `drive`)."""
    a, vmax = config.player_accel(), config.player_max_speed()
    fric, boost = config.player_friction(), config.PLAYER_TURN_BOOST
    brake = a * boost
    lo, hi = width / 2, config.LOGICAL_W - width / 2
    xs = np.empty(N_LOOK)
    x, v = x0, v0
    for k in range(MOVE_STEPS):
        d = drive(x, v, target, brake)
        if d:
            v = max(-vmax, min(vmax, v + a * (boost if v * d < 0 else 1.0) * d * STEP))
        else:
            drop = fric * STEP
            v = 0.0 if abs(v) <= drop else v - math.copysign(drop, v)
        x += v * STEP
        if x < lo or x > hi:
            x, v = min(max(x, lo), hi), 0.0
        xs[k] = x
    xs[MOVE_STEPS:] = x
    return xs


def first_hit(xs: np.ndarray, width: float, shots: np.ndarray, sweeps: list, margin: float, n: int = N_LOOK) -> int:
    """Index of the first of the first `n` look-ahead steps at which the path is hit (`n` if never)."""
    top = config.PLAYER_Y - config.PLAYER_H / 2 - BAND_PAD
    bottom = config.PLAYER_Y + config.PLAYER_H / 2
    look, xs = LOOK[:n], xs[:n]
    first = n
    if len(shots):
        bx = shots[:, 0:1] + shots[:, 2:3] * look[None, :]
        by = shots[:, 1:2] + shots[:, 3:4] * look[None, :]
        rad = 0.8 * shots[:, 4:5] + margin
        dx = np.maximum(xs[None, :] - width / 2 - bx, 0.0) + np.maximum(bx - (xs[None, :] + width / 2), 0.0)
        dy = np.maximum(top - by, 0.0) + np.maximum(by - bottom, 0.0)
        idx = np.nonzero(((dx ** 2 + dy ** 2) <= rad ** 2).any(axis=0))[0]
        if len(idx):
            first = int(idx[0])
    for z0, z1, t_on, t_off in sweeps:
        on = (look >= t_on - 0.05) & (look <= t_off + 0.05)
        over = on & (xs + width / 2 + margin > z0) & (xs - width / 2 - margin < z1)
        idx = np.nonzero(over)[0]
        if len(idx):
            first = min(first, int(idx[0]))
    return first


def choose(x0: float, v0: float, width: float, goal: float, shots: list, sweeps: list, until: float = None,
           tol: float = None, commit: bool = False, arrive: float = None) -> float:
    """Paddle centre to steer to: the spot nearest to `goal` whose approach path is clean.

    `until` (s): the goal only has to be reached and used within this time (catching a ball, firing a beam),
    so the path only has to be clean until then; later threats are dealt with by the next call.
    `tol` (px): how far from `goal` the paddle may stand and still serve it (default 0.6 of the half width).

    shots  = [(x, y, vx, vy, radius)] in px and px/s of real time;
    sweeps = [(zone_x0, zone_x1, seconds_until_fire, seconds_until_done)].
    """
    lo, hi = width / 2, config.LOGICAL_W - width / 2
    goal = min(max(goal, lo), hi)
    if not shots and not sweeps:
        return goal
    arr = np.array(shots) if shots else np.empty((0, 5))
    cands = [goal] + sorted((float(c) for c in np.arange(lo, hi + 1e-9, max(8.0, width / 3))),
                            key=lambda c: abs(c - goal))
    paths = {}
    # Anything within `tol` of the goal still serves it (the ball is still caught, the beam still lines up)
    tol = 0.6 * width / 2 if tol is None else tol
    near = [c for c in cands if abs(c - goal) <= tol]
    n = N_LOOK if until is None else int(min(N_LOOK, max(1, np.searchsorted(LOOK, until) + 1)))
    for margin in (0.35 * width, 0.12 * width, 5.0):
        for c in near:
            xs = paths.get(c)
            if xs is None:
                xs = paths[c] = path(x0, v0, c, width)
            if first_hit(xs, width, arr, sweeps, margin, n) >= n:
                return c
    if arrive is not None:
        # Wait where we are and dash over just in time (standing at the goal early is what gets us hit)
        for margin in (0.12 * width, 5.0):
            for c in near:
                xs = paths.get(c)
                if xs is None:
                    xs = paths[c] = path(x0, v0, c, width)
                reached = np.nonzero(np.abs(xs[:MOVE_STEPS] - c) < 6.0)[0]
                t_go = (int(reached[0]) + 1) * STEP if len(reached) else MOVE_STEPS * STEP
                dk = int(max(0.0, arrive - t_go - 0.10) / STEP)
                if dk <= 0 or dk > 80:
                    continue
                late = path(x0, 0.0, c, width)
                xs2 = np.concatenate((np.full(dk, x0), late))[:N_LOOK]
                if first_hit(xs2, width, arr, sweeps, margin, n) >= n:
                    return x0
    if commit:      # stay with the goal, delaying the hit if possible
        return max(near, key=lambda c: first_hit(paths.setdefault(c, path(x0, v0, c, width)), width, arr, sweeps, 5.0, n))
    best, best_key = x0, None
    for margin in (0.35 * width, 0.12 * width, 5.0):           # prefer roomy spots, settle for tight ones
        for c in cands:
            xs = paths.get(c)
            if xs is None:
                xs = paths[c] = path(x0, v0, c, width)
            first = first_hit(xs, width, arr, sweeps, margin)
            if first >= N_LOOK:
                return c
            if margin == 5.0 and (best_key is None or first > best_key):
                best, best_key = c, first                       # nothing is clean: delay the hit as long as possible
    return best
