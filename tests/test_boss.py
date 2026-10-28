"""Boss logic tests (plain asserts, no pytest).

Run from the repo root:   python -m tests.test_boss
"""
import itertools
import math
import os
import random
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import numpy as np  # noqa: E402
import pygame as pg  # noqa: E402

from game import config  # noqa: E402
from game.entities.player import Player  # noqa: E402
from game.systems import boss as boss_mod  # noqa: E402
from game.systems.boss import Boss, BossController, BossTick, Drop, Shot, Sweep  # noqa: E402

DT = config.PHYSICS_DT
WIDTHS = (540, 960, 1960)
PAIRS = 40                  # random (boss x, player x) pairs per pattern / width
REACT_PATTERN = 0.3         # s a human keeps standing still before reacting to a volley
REACT_SWEEP = 0.25
COMFORT_TEST = 0.4          # smallest free corridor of paddle centres (x paddle width) the test accepts
SHOT_COLORS = {"red", "orange", "magenta", "purple"}
SHAPES = {"orb", "bolt", "shard"}


#Helpers
def approx(a, b, eps=1e-6):
    return abs(a - b) <= eps


class width:
    """Context manager: run with a given canvas width, then restore the old one."""

    def __init__(self, w):
        self.w, self.old = w, None

    def __enter__(self):
        self.old = config.LOGICAL_W
        config.set_logical_width(self.w)
        return self

    def __exit__(self, *exc):
        config.set_logical_width(self.old)


def fight_ctrl(kind=0, phase=1, seed=1, cycle=0, enraged=False):
    """A controller dropped straight into fight state (phase / enrage forced)."""
    c = BossController(random.Random(seed))
    c.start(kind + 1 + config.BOSS_KINDS * cycle)
    c.state = "enrage" if enraged else "fight"
    c.boss.pos.y = float(config.BOSS_Y)
    c.boss.phase = phase
    c.boss.enraged = enraged
    return c


def run(c, seconds, px=None, balls=0, on_tick=None):
    """Step the controller; px may be a number, a callable(t) or None (centre). Returns all events."""
    events = []
    steps = int(round(seconds / DT))
    for i in range(steps):
        t = i * DT
        x = px(t) if callable(px) else (config.LOGICAL_W / 2 if px is None else px)
        tick = c.update(DT, x, balls)
        events.extend(tick.events)
        if on_tick:
            on_tick(c, tick, t)
    return events


def to_fight(c, number=1, px=None):
    c.start(number)
    steps = 0
    while c.state == "intro" and steps < 20000:
        c.update(DT, config.LOGICAL_W / 2 if px is None else px)
        steps += 1
    assert c.state == "fight"
    return c


def speed_of(shot):
    return math.hypot(shot.vx, shot.vy)


#Brute-force ground truth for the fairness tests (independent of the planner's geometry)
def blocked_centres(plan, w, W):
    """(centres, hit): `hit[i]` is True where a paddle standing still at centres[i] gets touched by the volley."""
    top = config.PLAYER_Y - config.PLAYER_H / 2 - boss_mod.BAND_PAD
    bottom = config.PLAYER_Y + config.PLAYER_H / 2
    cs = np.arange(w / 2, W - w / 2 + 1e-9, 2.0)
    hit = np.zeros(len(cs), dtype=bool)
    t_first = math.inf
    for delay, s in plan:
        if s.vy <= 1e-6:
            continue
        t0 = (top - s.radius - s.y) / s.vy
        t1 = (bottom + s.radius - s.y) / s.vy
        t_first = min(t_first, delay + max(0.0, t0))
        ts = np.linspace(max(0.0, t0), t1, 48)
        xs, ys = s.x + s.vx * ts, s.y + s.vy * ts
        left, right = (cs - w / 2)[:, None], (cs + w / 2)[:, None]
        dx = np.maximum(left - xs[None, :], 0.0) + np.maximum(xs[None, :] - right, 0.0)
        dy = np.maximum(top - ys, 0.0) + np.maximum(ys - bottom, 0.0)
        hit |= ((dx ** 2 + dy[None, :] ** 2) <= s.radius ** 2).any(axis=1)
    return cs, hit, t_first


def free_spans(cs, hit, min_len):
    """Runs of safe paddle centres at least `min_len` px long, as (a, b)."""
    spans, i, n = [], 0, len(cs)
    while i < n:
        if hit[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and not hit[j + 1]:
            j += 1
        if cs[j] - cs[i] >= min_len:
            spans.append((float(cs[i]), float(cs[j])))
        i = j + 1
    return spans


def arrive_one(px, a, b, limit, react, v0=0.0, width_scale=1.0):
    """Real Player, standing at px with velocity v0: first time it is *committed* inside [a, b], else inf.

    Committed = inside, and even braking at full effort it would stay inside. It keeps the old input for
    `react` s (the wrong way if v0 points away), then runs bang-bang to the nearest point of the span's core.
    """
    w = config.player_w() * width_scale
    q = min(0.1 * w, 0.25 * (b - a))
    target = min(max(px, a + q), b - q)
    pl = Player(px)
    pl.width = pl.target_width = w
    pl.vel.x = v0
    keep = (v0 > 0) - (v0 < 0)
    brake = config.player_accel() * config.PLAYER_TURN_BOOST
    t = 0.0
    while t <= limit:
        v = pl.vel.x
        stop = v * abs(v) / (2 * brake)
        if a <= pl.pos.x <= b and a <= pl.pos.x + stop <= b:
            return t
        if t < react:
            d = keep
        else:
            err = target - pl.pos.x
            if v * err < 0:
                d = 1 if err > 0 else -1
            elif abs(stop) >= abs(err) - 1.0 and v != 0:
                d = -1 if v > 0 else 1
            else:
                d = 0 if abs(err) < 0.5 else (1 if err > 0 else -1)
        pl.update(DT, d)
        t += DT
    return math.inf


def arrive(px, spans, limit, react, v0=0.0, width_scale=1.0):
    best = math.inf
    for a, b in spans:
        best = min(best, arrive_one(px, a, b, min(limit, best), react, v0, width_scale))
    return best


def volley_is_fair(plan, px, react=REACT_PATTERN, v0=0.0):
    """True if the real Player can reach a comfortable safe spot before the first shot hits the paddle band."""
    w, W = config.player_w(), config.LOGICAL_W
    cs, hit, t_first = blocked_centres(plan, w, W)
    spans = free_spans(cs, hit, COMFORT_TEST * w)
    if not spans:
        return False
    return arrive(px, spans, t_first, react, v0) <= t_first


#Design / data
def test_design_and_boss_data():
    assert BossController.design(1) == (0, 0)
    assert BossController.design(2) == (1, 0)
    assert BossController.design(3) == (2, 0)
    assert BossController.design(4) == (0, 1)
    assert BossController.design(7) == (0, 2)
    assert [BossController.design(n)[0] for n in range(1, 8)] == [0, 1, 2, 0, 1, 2, 0]
    assert BossController.design(0) == (0, 0)                      # clamped
    c = BossController(random.Random(3))
    for n in range(1, 8):
        b = c.start(n)
        kind, cycle = BossController.design(n)
        assert isinstance(b, Boss) and (b.kind, b.cycle, b.number) == (kind, cycle, n)
        assert b.name_key == f"boss.kind.{kind}.name"
        assert len(b.colors) == 2 and all(k in config.PALETTE for k in b.colors)
        assert 60 <= b.half_w <= 100 and 50 <= b.half_h <= 75
        assert approx(b.max_hp, config.BOSS_BASE_HP * n * (1 + config.BOSS_HP_GROWTH * cycle))
        assert approx(b.max_hp, config.boss_max_hp(n))
        assert b.hp == b.max_hp and b.hp_frac == 1.0 and b.phase == 1 and b.charge == 0 and not b.enraged
        assert b.death_t == 0 and b.hit_flash == 0
        assert approx(c.speed, 1 + config.BOSS_SPEED_GROWTH * cycle)
        assert c.state == "intro" and c.active and not c.fighting and not c.damageable and c.hit_rect is None
        assert c.boss is b and c.sweeps == []
    # The three designs look different (colours and size) and every kind shoots a danger colour
    cols = {BossController(random.Random(1)).start(n).colors for n in (1, 2, 3)}
    assert len(cols) == 3
    for kind in range(3):
        assert boss_mod.KIND_DEFS[kind]["shot"] in SHOT_COLORS
    # rect follows the contract
    b = c.start(1)
    b.pos.update(300, 250)
    assert b.rect == pg.Rect(300 - b.half_w, 250 - b.half_h, 2 * b.half_w, 2 * b.half_h)
    # Dataclass defaults
    s = Shot(1, 2, 3, 4)
    assert (s.radius, s.shape, s.color) == (13.0, "orb", "red")
    assert Drop("ball", 5).kind == "ball"
    t = BossTick([], [], [])
    assert t.shots == [] and t.drops == [] and t.events == []
    assert BossTick().events == []


#State machine
def test_state_machine():
    c = BossController(random.Random(5))
    # idle: nothing happens
    tick = c.update(DT, 270)
    assert (tick.shots, tick.drops, tick.events) == ([], [], []) and c.state == "idle" and not c.active
    assert c.damage(10) == 0.0 and c.sweep_hits(pg.Rect(0, 0, 999, 999)) is False
    b = c.start(1)
    # intro: boss descends with ease-out, nothing shoots / drops / hurts
    y_prev = b.pos.y
    assert y_prev < 0 and approx(b.pos.x, config.LOGICAL_W / 2)
    events, half_checked = [], False
    for i in range(int(config.BOSS_INTRO_TIME / DT) + 5):
        tick = c.update(DT, 270, 0)
        events += tick.events
        if c.state == "intro":
            assert tick.shots == [] and tick.drops == [] and not c.damageable
            assert b.pos.y >= y_prev - 1e-9
            assert c.damage(50) == 0.0 and b.hp == b.max_hp
            assert b.charge == 0 and c.hit_rect is None
        y_prev = b.pos.y
        if not half_checked and (i + 1) * DT >= config.BOSS_INTRO_TIME / 2:
            half_checked = True
            span = config.BOSS_Y - (-b.half_h - boss_mod.INTRO_Y_OFFSET)
            assert (b.pos.y - (-b.half_h - boss_mod.INTRO_Y_OFFSET)) / span > 0.8      # ease-out: fast start
        if c.state == "fight":
            break
    assert events == ["intro_end"] and c.state == "fight" and c.fighting and c.damageable and c.active
    assert b.pos.y == config.BOSS_Y and c.hit_rect == b.rect and b.anim_t >= config.BOSS_INTRO_TIME - 1e-6
    assert approx(c.time_left, config.BOSS_TIME_LIMIT, 0.05)
    # fight: charge always precedes volley, nothing enrages early
    ev = run(c, 30, px=270)
    assert "enrage" not in ev and not b.enraged and c.state == "fight"
    assert "charge" in ev and "volley" in ev
    pending = 0
    for e in ev:
        if e == "charge":
            assert pending == 0
            pending = 1
        elif e == "volley":
            assert pending == 1
            pending = 0
    assert approx(c.time_left, config.BOSS_TIME_LIMIT - 30, 0.05)
    # enrage exactly when the clock runs out, once, one-way
    ev = run(c, config.BOSS_TIME_LIMIT - 30 + 0.5, px=270)
    assert ev.count("enrage") == 1 and c.state == "enrage" and b.enraged and c.time_left == 0.0
    assert c.fighting and c.damageable
    ev = run(c, 5, px=270)
    assert "enrage" not in ev and c.state == "enrage"
    # kill: events are queued for the next update, boss stops shooting
    left = b.hp
    dealt = c.damage(1000)
    assert approx(dealt, left) and b.hp == 0 and c.state == "victory" and not c.damageable and c.hit_rect is None
    assert c.damage(5) == 0.0 and b.hp == 0
    tick = c.update(DT, 270, 0)
    assert tick.events == ["dead"] and tick.shots == [] and tick.drops == []
    assert c.sweeps == []
    # victory: death_t runs 0 -> 1 over BOSS_VICTORY_TIME, then "done" once
    ev, last = [], 0.0
    steps = int(config.BOSS_VICTORY_TIME / DT) + 20
    for i in range(steps):
        tick = c.update(DT, 270, 0)
        ev += tick.events
        assert tick.shots == [] and tick.drops == []
        assert b.death_t >= last - 1e-12
        last = b.death_t
        if c.state == "done":
            break
    assert ev == ["done"] and b.death_t == 1.0 and not c.active and not c.fighting
    assert c.update(DT, 270, 0).events == []
    assert c.damage(5) == 0.0
    c.stop()
    assert c.state == "idle" and c.boss is None and c.sweeps == [] and not c.active
    # restart works after stop
    b2 = c.start(2)
    assert b2.kind == 1 and c.state == "intro" and c.time_left == config.BOSS_TIME_LIMIT


def test_enrage_on_time():
    """The enrage event comes exactly BOSS_TIME_LIMIT s after the fight starts (not during the intro)."""
    c = BossController(random.Random(12))
    c.start(2)
    t_fight, t_enrage, t = None, None, 0.0
    for _ in range(int((config.BOSS_INTRO_TIME + config.BOSS_TIME_LIMIT + 3) / DT)):
        tick = c.update(DT, 270)
        t += DT
        if "intro_end" in tick.events:
            t_fight = t
        if "enrage" in tick.events:
            t_enrage = t
            break
        if t_fight is not None and t - t_fight < config.BOSS_TIME_LIMIT - 0.05:
            assert c.state == "fight" and not c.boss.enraged and c.time_left > 0
    assert t_fight is not None and t_enrage is not None
    assert abs((t_enrage - t_fight) - config.BOSS_TIME_LIMIT) < 0.03, (t_enrage - t_fight)
    assert c.time_left == 0.0 and c.state == "enrage" and c.boss.enraged


def test_event_order_full_fight():
    """Phases, sweeps and enrage show up in a believable order over a whole fight."""
    c = to_fight(BossController(random.Random(11)), 1)
    log = []

    def hook(ctrl, tick, t):
        log.extend((round(t, 3), e) for e in tick.events)
        if abs(t - 20.0) < DT / 2:
            ctrl.damage(36)                 # -> 64 hp: phase 2
        if abs(t - 40.0) < DT / 2:
            ctrl.damage(35)                 # -> 29 hp: phase 3
    run(c, 100, px=lambda t: 270 + 150 * math.sin(t), on_tick=hook)
    names = [e for _, e in log]
    assert names.index("phase2") < names.index("phase3") < names.index("enrage")
    assert "sweep_warn" in names and names.index("sweep_warn") > names.index("phase2")
    assert "sweep_fire" in names
    seq = [e for e in names if e.startswith("sweep")]
    assert seq[0] == "sweep_warn"
    for a, b in zip(seq, seq[1:]):
        assert a != b                       # warn / fire alternate: no overlapping sweeps
    p2 = next(t for t, e in log if e == "phase2")
    assert 20.0 <= p2 <= 20.05
    assert not [1 for t, e in log if e.startswith("sweep") and t < p2]      # none in phase 1


#Damage / phases
def test_damage_phases_stagger():
    c = to_fight(BossController(random.Random(2)), 1)
    b = c.boss
    assert c.damage(0) == 0 and c.damage(-5) == 0 and c.damage(float("nan")) == 0 and b.hp == b.max_hp
    assert approx(c.damage(10, "ball"), 10) and approx(b.hp, 90) and b.hit_flash == 1.0 and b.phase == 1
    # hit_flash fades out in ~0.18 s
    for _ in range(int(0.1 / DT)):
        c.update(DT, 270)
    assert 0.2 < b.hit_flash < 0.8
    for _ in range(int(0.1 / DT)):
        c.update(DT, 270)
    assert b.hit_flash == 0.0
    # phase 2 at <= 66%
    c.damage(23)
    assert approx(b.hp_frac, 0.67) and b.phase == 1
    c.damage(1)
    assert b.phase == 2 and b.hp_frac <= 0.66 + 1e-9
    tick = c.update(DT, 270)
    assert tick.events == ["phase2"]
    # stagger: no charge / volley / shots for BOSS_STAGGER_TIME, boss stands still and charge is 0
    ev, shots, xs = [], 0, []
    for _ in range(int((config.BOSS_STAGGER_TIME - 0.05) / DT)):
        tk = c.update(DT, 270)
        ev += tk.events
        shots += len(tk.shots)
        xs.append(b.pos.x)
        assert b.charge == 0.0
    assert "charge" not in ev and "volley" not in ev and shots == 0
    assert xs[-1] == xs[len(xs) // 2]                       # it brakes to a halt and stays put
    # firing resumes afterwards
    ev = run(c, 3.0, px=270)
    assert "charge" in ev and "volley" in ev
    # phase 3 at <= 33%
    c.damage(b.hp - 0.30 * b.max_hp)
    assert b.phase == 3 and c.update(DT, 270).events == ["phase3"]
    # a big hit can skip a phase: both events, in order
    c2 = to_fight(BossController(random.Random(3)), 1)
    c2.damage(70)
    assert c2.boss.phase == 3
    assert c2.update(DT, 270).events == ["phase2", "phase3"]
    # damage never drives hp negative and reports what it removed
    c3 = to_fight(BossController(random.Random(4)), 1)
    c3.damage(95)
    assert approx(c3.damage(50), 5) and c3.boss.hp == 0 and c3.state == "victory"
    # existing sweeps survive a phase change (the player was already warned)
    c4 = to_fight(BossController(random.Random(6)), 1)
    c4.damage(35)
    seen = {"ok": False}

    def hook(ctrl, tick, t):
        if ctrl.sweeps and not seen["ok"]:
            seen["ok"] = True
            n = len(ctrl.sweeps)
            ctrl.damage(35)                 # phase 3 while a sweep is up
            assert len(ctrl.sweeps) == n
    run(c4, 12, px=270, on_tick=hook)
    assert seen["ok"]


def test_enrage_rates():
    """Enraged: attacks come more often, bullets are faster; the cycle speeds both up too."""
    def gaps(enraged, cycle):
        c = fight_ctrl(0, 1, seed=8, cycle=cycle, enraged=enraged)
        c.boss.phase = 1
        times = []

        def hook(ctrl, tick, t):
            if "volley" in tick.events:
                times.append(t)
        run(c, 60, px=270, on_tick=hook)
        return [b - a for a, b in zip(times, times[1:])]
    calm, rage = gaps(False, 0), gaps(True, 0)
    fast = gaps(False, 2)
    mean = lambda xs: sum(xs) / len(xs)
    assert len(calm) > 10 and len(rage) > 10
    assert mean(rage) < mean(calm) / 1.35, (mean(rage), mean(calm))
    assert mean(fast) < mean(calm) / 1.2, (mean(fast), mean(calm))
    assert min(calm) >= boss_mod.MIN_IDLE + 0.5
    # shot speed: x BOSS_ENRAGE_SPEED, and x(1 + growth * cycle)
    for name in ("aimed", "fan", "row"):
        base = fight_ctrl(0, 1, 1)
        rage = fight_ctrl(0, 1, 1, enraged=True)
        cyc = fight_ctrl(0, 1, 1, cycle=2)
        v0 = max(speed_of(s) for _, s in base.plan_attack(name, 200))
        v1 = max(speed_of(s) for _, s in rage.plan_attack(name, 200))
        v2 = max(speed_of(s) for _, s in cyc.plan_attack(name, 200))
        assert approx(v1 / v0, config.BOSS_ENRAGE_SPEED, 1e-6), (name, v1 / v0)
        assert approx(v2 / v0, 1 + config.BOSS_SPEED_GROWTH * 2, 1e-6), (name, v2 / v0)
    # enraged bullets are red
    assert {s.color for _, s in fight_ctrl(1, 2, 1, enraged=True).plan_attack("row", 100)} == {"red"}


#Patrol
def test_patrol():
    for w in WIDTHS:
        with width(w):
            for kind in range(3):
                c = BossController(random.Random(20 + kind))
                to_fight(c, kind + 1)
                b = c.boss
                lo = b.half_w + config.BOSS_MARGIN
                hi = config.LOGICAL_W - lo
                top = max(140.0, boss_mod.SWEEP_SLIDE) * config.field_scale() ** 0.5
                acc = max(boss_mod.PATROL_ACCEL, boss_mod.PATROL_BRAKE, boss_mod.SWEEP_SLIDE_ACCEL) * config.field_scale() ** 0.5
                prev_x, prev_v = b.pos.x, 0.0
                xs, still_checked, moved = [], 0, 0.0
                for i in range(int(40 / DT)):
                    c.update(DT, 270 + 100 * math.sin(i * DT))
                    if i == int(15 / DT):
                        c.damage(40)                 # also covers the phase change standstill
                    x = b.pos.x
                    v = (x - prev_x) / DT
                    assert lo - 1e-6 <= x <= hi + 1e-6, (w, kind, x)
                    assert abs(v) <= top * 1.001, (w, kind, v)
                    assert abs(v - prev_v) <= acc * DT * 1.05 + 1e-6, (w, kind, v, prev_v)     # smooth: no jerks
                    if b.charge > 0 or (c.sweeps and not c._aiming()):
                        assert x == prev_x, (w, kind, "moved while charging / locked / firing")
                        still_checked += 1
                    moved += abs(x - prev_x)
                    prev_x, prev_v = x, v
                    xs.append(x)
                assert still_checked > 100
                assert max(xs) - min(xs) > 0.3 * (hi - lo), (w, kind, max(xs) - min(xs))
                assert moved / 40 > 15, (w, kind, moved / 40)          # it does patrol (not parked)


#Sweep objects
def test_sweep_object_and_hits():
    sw = Sweep(x_from=100, x_to=300, width=100, warn_time=1.2, fire_time=0.6)
    assert sw.phase == "warn" and sw.zone == (50, 350) and sw.beam_x == 100 and sw.k_warn == 0 and sw.k_fire == 0
    rect = pg.Rect(0, 700, 110, 22)
    assert not sw.hits(rect)                                  # not firing yet
    sw.update(0.6)
    assert sw.phase == "warn" and approx(sw.k_warn, 0.5) and sw.k_fire == 0 and sw.beam_x == 100
    sw.update(0.6 + 0.3)
    assert sw.phase == "fire" and approx(sw.k_fire, 0.5, 1e-9) and approx(sw.beam_x, 200, 1e-6) and sw.k_warn == 1
    assert sw.hits(pg.Rect(150, 700, 110, 22)) and sw.hits(pg.Rect(140, 700, 20, 22))
    assert not sw.hits(pg.Rect(0, 700, 100, 22))              # right edge at 100: beam spans 150..250
    assert not sw.hits(pg.Rect(252, 700, 100, 22))            # beam spans 150..250: just outside
    assert sw.hits(pg.Rect(248, 700, 100, 22))
    sw.consumed = True
    assert not sw.hits(pg.Rect(150, 700, 110, 22))
    sw.consumed = False
    sw.update(0.5)
    assert sw.phase == "done" and approx(sw.beam_x, 300) and sw.k_fire == 1 and not sw.hits(pg.Rect(250, 700, 110, 22))
    # static sweep: zone is just the beam
    st = Sweep(200, 200, 90, 1.2, 0.5)
    assert st.zone == (155, 245)
    # controller: hits are single-shot and flag consumed
    c = to_fight(BossController(random.Random(1)), 1)
    c.sweeps = [Sweep(200, 200, 100, 0.1, 0.5)]
    r = pg.Rect(180, 700, 40, 22)
    assert not c.sweep_hits(r)
    for _ in range(int(0.12 / DT)):
        c.update(DT, 270)
    assert c.sweeps and c.sweeps[0].phase == "fire"
    assert c.sweep_hits(r) and c.sweeps[0].consumed
    assert not c.sweep_hits(r)                                # one hit per sweep
    assert not c.sweep_hits(pg.Rect(0, 700, 40, 22))


def test_sweeps_fair_and_spaced():
    """Warning >= 1.1 s, zone <= 55% of the width, and the real paddle can always leave the zone in time."""
    worst = {}
    for w in WIDTHS:
        with width(w):
            pw, W = config.player_w(), config.LOGICAL_W
            for kind in range(3):
                for phase in (2, 3):
                    for cycle, enraged in ((0, False), (2, True)):
                        c = fight_ctrl(kind, phase, seed=100 + kind * 7 + phase, cycle=cycle, enraged=enraged)
                        rng = random.Random(w + kind * 31 + phase)
                        for _ in range(14):
                            px = rng.uniform(pw / 2, W - pw / 2)
                            lo = c.boss.half_w + config.BOSS_MARGIN
                            c.boss.pos.x = rng.uniform(lo, W - lo)
                            sweeps = c.plan_sweeps(px)
                            assert len(sweeps) == 1 and sweeps[0].x_from == sweeps[0].x_to == c.boss.pos.x
                            zones = []
                            for sw in sweeps:
                                assert sw.warn_time >= 1.1 and 0.45 <= sw.fire_time <= 0.9
                                assert boss_mod.SWEEP_LOCK_SLIDE_MIN - 1e-9 <= sw.lock_start and 0.5 <= sw.lock_time <= sw.warn_time
                                assert 90 <= sw.width <= 150
                                z0, z1 = sw.zone
                                assert z1 - z0 <= 0.55 * W + 1e-6, (w, kind, phase, z1 - z0)
                                assert z0 >= -1e-6 and z1 <= W + 1e-6
                                assert sw.age == 0 and not sw.consumed and sw.phase == "warn"
                                zones.append((z0, z1))
                            # complement of the zones (paddle rect clear of every zone) is where the paddle is safe
                            cs = np.arange(pw / 2, W - pw / 2 + 1e-9, 2.0)
                            hit = np.zeros(len(cs), dtype=bool)
                            for z0, z1 in zones:
                                hit |= (cs + pw / 2 > z0) & (cs - pw / 2 < z1)
                            spans = free_spans(cs, hit, COMFORT_TEST * pw)
                            assert spans, (w, kind, phase, zones)
                            for x in np.arange(pw / 2, W - pw / 2 + 1e-9, 12.0):
                                t = arrive(float(x), spans, sweeps[0].lock_time, REACT_SWEEP)
                                assert t <= sweeps[0].lock_time, (w, kind, phase, cycle, enraged, x, zones, t)
                                worst[w] = max(worst.get(w, 0.0), t / sweeps[0].lock_time)
    print("  worst sweep escape / lock time: " + ", ".join(f"{w}px: {worst[w]:.2f}" for w in WIDTHS))
    # Pacing over a whole fight: >= 6 s between starts, none overlapping, calm before and after
    for kind in range(3):
        c = to_fight(BossController(random.Random(40 + kind)), kind + 1)
        c.damage(35)                                                   # phase 2
        starts, ends, volley_t, charge_t, shots_t = [], [], [], [], []

        def hook(ctrl, tick, t):
            if "sweep_warn" in tick.events:
                starts.append(t)
                assert len({round(s.age, 6) for s in ctrl.sweeps}) == 1     # a double sweep fires together
            if "charge" in tick.events:
                charge_t.append(t)
            if "volley" in tick.events:
                volley_t.append(t)
            if tick.shots:
                shots_t.append(t)
            if t > 0 and not ctrl.sweeps and ctrl.fighting and getattr(hook, "had", False):
                ends.append(t)
            hook.had = bool(ctrl.sweeps)
        run(c, 60, px=lambda t: 270 + 120 * math.sin(t * 0.7), on_tick=hook)
        assert len(starts) >= 4, (kind, starts)
        assert all(b - a >= 6.0 - 1e-6 for a, b in zip(starts, starts[1:])), (kind, starts)
        assert len(ends) >= 3
        for s, e in zip(starts, ends):
            assert e - s >= 1.1 + 0.45 - 0.02, (kind, s, e)
            # nothing new starts between the start of the warning and 0.6 s after the beam ends
            for series in (charge_t, volley_t, shots_t):
                assert not [t for t in series if s - 1e-9 <= t < e + 0.6 - 0.03], (kind, s, e)
    c = to_fight(BossController(random.Random(77)), 3)
    c.damage(70)
    doubles = []

    def hook3(ctrl, tick, t):
        if "sweep_warn" in tick.events:
            doubles.append(len(ctrl.sweeps))
    run(c, 60, px=270, on_tick=hook3)
    assert doubles and all(n == 1 for n in doubles), doubles          # one column under the boss, even for the Void Eye
    for kind in (0, 1):
        c = fight_ctrl(kind, 3, seed=5)
        assert all(len(c.plan_sweeps(270)) == 1 for _ in range(5))


#Attack patterns
def pattern_cases():
    for kind in range(3):
        for phase in (1, 2, 3):
            for name in fight_ctrl(kind, phase).attack_pool():
                yield kind, phase, name


def test_sweep_slides_locks_and_fires_under_the_boss():
    """The laser only ever comes from where the boss stands: it slides to the player's x, freezes, then fires straight down."""
    for w in WIDTHS:
        with width(w):
            W = config.LOGICAL_W
            for kind in range(3):
                for phase in (2, 3):
                    c = fight_ctrl(kind, phase, seed=7 + kind)
                    lo, hi = c._x_range()
                    c.boss.pos.x = lo if kind % 2 else hi            # start at a wall, the player is on the other side
                    px = hi if kind % 2 else lo
                    c._sweep_pending = True
                    stages, xs, fired = [], [], False
                    for i in range(int(4.0 / DT)):
                        tick = c.update(DT, px, 0)
                        for s in c.sweeps:
                            if not fired and s.phase == "fire":
                                fired = True
                                assert approx(s.x_from, c.boss.pos.x, 1e-9) and s.x_from == s.x_to
                                assert approx(s.zone[0], c.boss.pos.x - s.width / 2, 1e-9)
                        if c.sweeps:
                            stages.append(c.boss.laser)
                            xs.append((c.boss.pos.x, c.sweeps[0].x_from, c.sweeps[0].frozen))
                            assert c.boss.pos.x >= lo - 1e-6 and c.boss.pos.x <= hi + 1e-6
                            assert approx(c.sweeps[0].x_from, c.boss.pos.x, 1e-9), "the column is always under the boss"
                    assert fired and c.boss.laser == "" and c.boss.laser_open < 1.0
                    order = [k for k, _ in itertools.groupby(stages)]
                    assert order == ["aim", "lock", "fire"], order
                    frozen_x = [x for x, _, fz in xs if fz]
                    assert len(frozen_x) > 0.5 / DT and max(frozen_x) == min(frozen_x), "no movement from the lock on"
                    assert abs(frozen_x[0] - px) <= 0.7 * abs(xs[0][0] - px), (w, kind, phase, frozen_x[0], px)   # it closed in on the player
                    assert abs(xs[0][0] - frozen_x[0]) > 0.15 * (hi - lo), "the boss really slid"


def test_sweep_laser_stage_and_open_amount():
    c = fight_ctrl(0, 2, seed=3)
    b = c.boss
    assert b.laser == "" and b.laser_k == 0.0 and b.laser_open == 0.0
    c._sweep_pending = True
    seen, last_open, opened = set(), 0.0, False
    for i in range(int(4.0 / DT)):
        c.update(DT, 270, 0)
        seen.add(b.laser)
        assert 0.0 <= b.laser_k <= 1.0 and 0.0 <= b.laser_open <= 1.0
        if b.laser in ("lock", "fire"):
            assert b.laser_open > 0.0
        opened = opened or b.laser_open >= 1.0 - 1e-9
        if not c.sweeps and b.laser == "" and opened:
            assert b.laser_open <= last_open + 1e-9, "closes again after the shot"
        last_open = b.laser_open
    assert {"aim", "lock", "fire", ""} <= seen and opened and b.laser_open == 0.0
    # a phase change or the death clears the pose
    c._sweep_pending = True
    for _ in range(int(8.0 / DT)):
        c.update(DT, 270, 0)
        if c.sweeps:
            break
    run(c, 0.9, px=270)
    assert c.boss.laser in ("aim", "lock")
    c.damage(c.boss.max_hp)
    assert c.boss.laser == "" and c.boss.laser_open == 0.0


def test_sweep_locked_flag_and_legacy_static():
    sw = Sweep(200, 200, 100, warn_time=1.5, fire_time=0.5, lock_time=0.7)
    assert not sw.locked and approx(sw.lock_start, 0.8) and sw.k_lock == 0 and sw.k_aim == 0
    sw.update(0.4)
    assert not sw.locked and approx(sw.k_aim, 0.5)
    sw.update(0.5)
    assert sw.locked and sw.k_aim == 1 and 0 < sw.k_lock < 1
    sw.update(0.7)
    assert sw.phase == "fire" and not sw.locked
    # a sweep without a lock (old style) stays where it was put: the boss does not drag it around
    c = to_fight(BossController(random.Random(1)), 1)
    c.sweeps = [Sweep(100, 100, 100, 0.8, 0.5)]
    c.boss.pos.x = 400.0
    run(c, 0.5, px=450)
    assert c.sweeps[0].x_from == 100 and not c._aiming()


def test_pool_design():
    """Each kind has its own signature attacks; sweeps start in phase 2; pools grow with the phase."""
    pools = {(k, p): set(fight_ctrl(k, p).attack_pool()) for k in range(3) for p in (1, 2, 3)}
    assert len({frozenset(pools[(k, 3)]) for k in range(3)}) == 3
    assert {"aimed", "fan"} <= pools[(0, 1)] and {"row", "fan"} <= pools[(1, 1)] and {"aimed", "row"} <= pools[(2, 1)]
    assert "row2" in pools[(1, 3)] and "spin" in pools[(0, 3)] and "trident" in pools[(2, 3)]
    for k in range(3):
        assert len(pools[(k, 3)]) >= len(pools[(k, 1)])
    for names in pools.values():
        assert names <= set(boss_mod.BUILDERS)


def test_shot_basics_and_speed_range():
    """Fields are sane, speeds sit in 220..520 px/s at speed 1, nothing is NaN, colours are danger colours."""
    seen = {}
    for w in WIDTHS:
        with width(w):
            pw, W = config.player_w(), config.LOGICAL_W
            for kind, phase, name in pattern_cases():
                c = fight_ctrl(kind, phase, seed=3)
                rng = random.Random(w + kind + phase)
                for _ in range(8):
                    c.boss.pos.x = rng.uniform(120, W - 120)
                    plan = c.plan_attack(name, rng.uniform(pw / 2, W - pw / 2))
                    assert plan, (kind, phase, name)
                    for delay, s in plan:
                        assert isinstance(s, Shot) and 0 <= delay <= 1.0
                        assert all(math.isfinite(v) for v in (s.x, s.y, s.vx, s.vy, s.radius))
                        assert 220.0 <= speed_of(s) <= 520.0, (kind, phase, name, speed_of(s))
                        assert s.vy > 0 and s.radius > 0
                        assert s.color in SHOT_COLORS and s.shape in SHAPES
                        assert c.boss.pos.y < s.y < config.PLAYER_Y - 250, s.y
                    seen.setdefault((kind, phase), []).append(len(plan))
    print("  bullets per volley (min / mean / max):")
    for kind in range(3):
        print("    kind %d: " % kind + "   ".join(
            f"P{p} {min(seen[(kind, p)])}/{sum(seen[(kind, p)]) / len(seen[(kind, p)]):.1f}/{max(seen[(kind, p)])}"
            for p in (1, 2, 3)))
    for kind in range(3):                                       # quantity ramps up with the phase
        means = [sum(seen[(kind, p)]) / len(seen[(kind, p)]) for p in (1, 2, 3)]
        assert means[0] < means[2], (kind, means)


def test_pattern_geometry():
    """fan: within +-40 deg; row: one wide gap and no passable holes; aimed: locked on the player's x."""
    for w in WIDTHS:
        with width(w):
            pw, W = config.player_w(), config.LOGICAL_W
            for kind, phase, name in pattern_cases():
                c = fight_ctrl(kind, phase, seed=9)
                rng = random.Random(w * 3 + kind * 5 + phase)
                for _ in range(PAIRS // 2):
                    c.boss.pos.x = rng.uniform(120, W - 120)
                    px = rng.uniform(pw / 2, W - pw / 2)
                    plan = c.plan_attack(name, px)
                    if name in ("fan", "spin", "prism"):
                        for _, s in plan:
                            ang = math.degrees(math.atan2(s.vx, s.vy))
                            assert abs(ang) <= 40.0 + 1e-6, (name, ang)
                            assert approx(s.x, c.boss.pos.x)
                    elif name in ("aimed", "trident"):
                        lanes = [s.x + s.vx * (config.PLAYER_Y - s.y) / s.vy for _, s in plan]
                        assert any(abs(x - px) < 3 for x in lanes), (name, px, lanes)
                        if name == "aimed":
                            assert all(abs(x - px) < 3 for x in lanes), (name, px, lanes)
                    else:                                      # row family
                        layers = {0: [], 1: []}
                        for d, s in plan:
                            layers[1 if d >= boss_mod.ROW2_GAP - 1e-9 else 0].append(s)
                            assert s.vx == 0 and s.y > c.boss.pos.y + c.boss.half_h
                        assert layers[0] and (name == "row2") == bool(layers[1])
                        for shots in (layers[0], layers[1]):
                            if not shots:
                                continue
                            xs = sorted(s.x for s in shots)
                            r = shots[0].radius
                            need = pw * 1.6 + 2 * r
                            gaps = [b - a for a, b in zip(xs, xs[1:])]
                            assert max(gaps) >= need - 1e-6, (w, name, max(gaps), need)
                            # every other hole is too small for the paddle (rows are never "swiss cheese")
                            big = [g for g in gaps if g >= need - 1e-6]
                            assert len(big) == 1, (w, name, gaps)
                            small = [g for g in gaps if g < need - 1e-6]
                            assert all(g - 2 * r * 0.8 < pw for g in small), (w, name, small)
                            step = boss_mod.ROW_PACK * (pw + 2 * r)
                            assert xs[0] <= step and xs[-1] >= W - step      # the row spans the whole field


def test_aimed_telegraph():
    """Aimed attacks wind up for >= 0.5 s (also late cycles / enraged) and the charge event comes first."""
    for kind, phase, cycle, enraged in [(0, 1, 0, False), (0, 3, 0, False), (0, 3, 2, True), (2, 3, 3, True), (2, 2, 1, False)]:
        c = fight_ctrl(kind, phase, seed=30 + kind + phase, cycle=cycle, enraged=enraged)
        c._idle_t = 0.2
        got = {"aimed": [], "trident": [], "other": []}
        state = {"t": None, "name": None}

        def hook(ctrl, tick, t):
            if "charge" in tick.events:
                state["t"], state["name"] = t, ctrl.attack
                assert ctrl.boss.charge == 0.0 or ctrl.boss.charge < 0.05
            if "volley" in tick.events:
                assert state["t"] is not None
                key = state["name"] if state["name"] in ("aimed", "trident") else "other"
                got[key].append(t - state["t"])
                state["t"] = None
            if ctrl.boss.charge > 0:
                assert 0 < ctrl.boss.charge <= 1.0
        run(c, 90, px=lambda t: 200 + 100 * math.sin(t), on_tick=hook)
        for key in ("aimed", "trident"):
            assert all(x >= 0.5 for x in got[key]), (kind, phase, cycle, enraged, key, min(got[key]))
        assert sum(len(v) for v in got.values()) > 10


def fairness_run(kind, phase, name, w, pairs, seed, cycle=0, enraged=False, v0=0.0):
    """(fails, total, worst slack) over `pairs` random (boss x, player x) pairs for one pattern."""
    pw, W = config.player_w(), config.LOGICAL_W
    c = fight_ctrl(kind, phase, seed=seed, cycle=cycle, enraged=enraged)
    rng = random.Random(seed * 7919 + w + phase)
    lo = c.boss.half_w + config.BOSS_MARGIN
    fails = []
    for _ in range(pairs):
        c.boss.pos.x = rng.uniform(lo, W - lo)
        px = rng.uniform(pw / 2, W - pw / 2)
        plan = c.plan_attack(name, px)
        v = rng.choice((-1, 1)) * v0
        if not volley_is_fair(plan, px, v0=v):
            fails.append((round(c.boss.pos.x), round(px), round(v)))
    return fails


def test_pattern_fairness():
    """Every pattern, kind, phase and width: a safe spot the real paddle reaches (0.3 s reaction) in time."""
    t0 = time.time()
    n = 0
    for w in WIDTHS:
        with width(w):
            for kind, phase, name in pattern_cases():
                fails = fairness_run(kind, phase, name, w, PAIRS, seed=1000 + kind * 10 + phase)
                n += PAIRS
                assert not fails, (w, kind, phase, name, fails[:5])
    print(f"  {n} volleys fair at widths {WIDTHS} ({time.time() - t0:.1f}s)")


def test_pattern_fairness_late_cycles():
    """Faster late-game bosses (cycle 3, enraged) still leave a way out."""
    n = 0
    for w in WIDTHS:
        with width(w):
            for kind, phase, name in pattern_cases():
                for cycle, enraged in ((2, False), (3, True)):
                    fails = fairness_run(kind, phase, name, w, 10, seed=2000 + kind + phase, cycle=cycle, enraged=enraged)
                    n += 10
                    assert not fails, (w, kind, phase, name, cycle, enraged, fails[:5])
    print(f"  {n} late-cycle volleys fair")


def test_pattern_fairness_moving_paddle():
    """Stricter: the paddle may be flying away at full speed when the volley goes out. Report, require most."""
    bad = total = 0
    for w in WIDTHS:
        with width(w):
            for kind, phase, name in pattern_cases():
                fails = fairness_run(kind, phase, name, w, 6, seed=3000 + kind + phase, v0=config.player_max_speed())
                bad += len(fails)
                total += 6
    print(f"  full-speed-away start: {total - bad}/{total} volleys still dodgeable inside the first-hit time")
    assert bad <= 0.35 * total, (bad, total)


def test_wide_paddle_scale():
    """With the wide power-up the controller is told the paddle width: gaps grow with it and stay dodgeable."""
    for w in WIDTHS:
        with width(w):
            pw0, W = config.player_w(), config.LOGICAL_W
            scale = config.WIDE_FACTOR
            pw = pw0 * scale
            for kind, phase, name in pattern_cases():
                c = fight_ctrl(kind, phase, seed=61)
                c.paddle_scale = scale
                rng = random.Random(w + kind + phase)
                for _ in range(12):
                    c.boss.pos.x = rng.uniform(120, W - 120)
                    px = rng.uniform(pw / 2, W - pw / 2)
                    plan = c.plan_attack(name, px)
                    cs, hit, t_first = blocked_centres(plan, pw, W)
                    spans = free_spans(cs, hit, COMFORT_TEST * pw)
                    assert spans, (w, kind, phase, name)
                    assert arrive(px, spans, t_first, REACT_PATTERN, width_scale=scale) <= t_first, (w, kind, phase, name)
                    if name.startswith("row"):
                        xs = sorted(s.x for d, s in plan if d < boss_mod.ROW2_GAP - 1e-9)
                        assert max(b - a for a, b in zip(xs, xs[1:])) >= pw * 1.6 + 26 - 1e-6
            for sweep_phase in (2, 3):
                c = fight_ctrl(2, sweep_phase, seed=62)
                c.paddle_scale = scale
                for px in (pw / 2, W / 2, W - pw / 2):
                    zones = [sw.zone for sw in c.plan_sweeps(px)]
                    cs = np.arange(pw / 2, W - pw / 2 + 1e-9, 2.0)
                    hit = np.zeros(len(cs), dtype=bool)
                    for z0, z1 in zones:
                        hit |= (cs + pw / 2 > z0) & (cs - pw / 2 < z1)
                    spans = free_spans(cs, hit, 0.2 * pw)       # a wide paddle on a narrow field only fits beside the column
                    lock = c.plan_sweeps(px)[0].lock_time
                    assert spans and arrive(px, spans, lock, REACT_SWEEP, width_scale=scale) <= lock, (w, sweep_phase, px)


def test_planner_matches_ground_truth():
    """The planner's analytic safety check never calls a volley safe when brute force finds no free corridor."""
    for w in WIDTHS:
        with width(w):
            pw, W = config.player_w(), config.LOGICAL_W
            rng = random.Random(w)
            for kind, phase, name in pattern_cases():
                c = fight_ctrl(kind, phase, seed=4)
                for _ in range(10):
                    c.boss.pos.x = rng.uniform(120, W - 120)
                    px = rng.uniform(pw / 2, W - pw / 2)
                    plan = c.plan_attack(name, px)
                    cs, hit, _ = blocked_centres(plan, pw, W)
                    assert free_spans(cs, hit, COMFORT_TEST * pw), (w, kind, phase, name)
    # an unsafe volley is recognised as such: a solid wall of bullets
    with width(540):
        wall = [(0.0, Shot(x, 300.0, 0.0, 300.0, 13.0, "orb", "red")) for x in range(0, 560, 40)]
        cs, hit, _ = blocked_centres(wall, config.player_w(), 540)
        assert not free_spans(cs, hit, 1.0)
        planned = [boss_mod._Planned(d, s, 0, s.x) for d, s in wall]
        assert not boss_mod.plan_is_safe(planned, 270.0)
        gate = [p for p in planned if abs(p.lane_x - 270) > 140]
        assert boss_mod.plan_is_safe(gate, 270.0)
        assert boss_mod.plan_is_safe(gate, 60.0)                         # the gate is within reach of the left wall
        assert not boss_mod.plan_is_safe(gate, 60.0, free=10.0)          # ... unless earlier shots pin the paddle down
        assert approx(boss_mod.reach_distance(0), 0) and boss_mod.reach_distance(1.0) > boss_mod.reach_distance(0.5)


def test_volleys_in_sequence():
    """Overlapping volleys: a volley waits when earlier bullets leave the paddle too little time."""
    for w in WIDTHS:
        with width(w):
            for enraged in (False, True):
                c = fight_ctrl(0, 3, seed=14, cycle=2, enraged=enraged)
                c.boss.phase = 3
                gaps = []
                last = {"t": None}

                def hook(ctrl, tick, t):
                    if "volley" in tick.events:
                        if last["t"] is not None:
                            gaps.append(t - last["t"])
                        last["t"] = t
                run(c, 80, px=lambda t: 270 + 200 * math.sin(t), on_tick=hook)
                assert len(gaps) > 15 and min(gaps) > 0.6, (w, enraged, min(gaps))


#Helpers drop
def test_ball_lost_delays_next_ball():
    # Both balls were out, one is lost: the replacement must not come at once (a loss costs time, not a life)
    c = to_fight(BossController(random.Random(3)), 1)
    for _ in range(int(config.BOSS_FIRST_BALL / DT) + 5):               # run until the first ball timer expired
        c.update(DT, 270, config.BOSS_MAX_BALLS)
    c.ball_lost()
    t_first = None
    for i in range(int(2 * config.BOSS_BALL_INTERVAL / DT)):
        tick = c.update(DT, 270, config.BOSS_MAX_BALLS - 1)
        if any(d.kind == "ball" for d in tick.drops):
            t_first = i * DT
            break
    assert t_first is not None and t_first >= config.BOSS_BALL_RESPAWN - 0.05, t_first
    # A loss never speeds the schedule up: a later timer stays as it is
    c._ball_t = config.BOSS_BALL_RESPAWN + 2.0
    c.ball_lost()
    assert approx(c._ball_t, config.BOSS_BALL_RESPAWN + 2.0)


def test_drops():
    c = to_fight(BossController(random.Random(21)), 1)
    drops = []            # (t, kind, x)
    t_total = 300.0

    def hook(ctrl, tick, t):
        for d in tick.drops:
            assert isinstance(d, Drop) and d.kind == "ball"
            drops.append((t, d.kind, d.x))
    # Pretend balls die: balls_alive follows a script
    balls = {"n": 0}
    steps = int(t_total / DT)
    for i in range(steps):
        t = i * DT
        tick = c.update(DT, 270, balls["n"])
        hook(c, tick, t)
        if 100 <= t < 130:
            balls["n"] = config.BOSS_MAX_BALLS         # full: no ball may drop
        else:
            balls["n"] = 0
        if c.state == "enrage" and i % 1000 == 0:
            pass
    ba = [d for d in drops if d[1] == "ball"]
    assert approx(ba[0][0], config.BOSS_FIRST_BALL, 0.05)
    j = config.BOSS_HELPER_JITTER
    for kind, series, interval in (("ball", ba, config.BOSS_BALL_INTERVAL),):
        gaps = [b[0] - a[0] for a, b in zip(series, series[1:]) if not (95 <= a[0] <= 135)]
        assert all(interval * (1 - j) - 0.03 <= g <= interval * (1 + j) + 0.03 for g in gaps), (kind, min(gaps), max(gaps))
        assert abs(sum(gaps) / len(gaps) - interval) < 0.25 * interval * j + 0.1
    assert all(boss_mod.DROP_WALL_MARGIN <= d[2] <= config.LOGICAL_W - boss_mod.DROP_WALL_MARGIN for d in drops)
    assert not [d for d in ba if 100 + 0.01 < d[0] < 130]            # MAX_BALLS respected
    first_after = min(d[0] for d in ba if d[0] >= 130)
    assert first_after < 131.0                                       # retried within ~0.5 s once a ball is free
    assert len({round(d[2]) for d in ba}) > len(ba) * 0.8            # spread out, not a fixed x
    # not aimed at the player: x is independent of the player's x
    for px in (60.0, 480.0):
        c2 = to_fight(BossController(random.Random(5)), 1, px=px)
        xs = []
        for i in range(int(120 / DT)):
            tick = c2.update(DT, px, 0)
            xs += [d.x for d in tick.drops]
        assert 40 <= min(xs) and max(xs) <= 500 and (max(xs) - min(xs)) > 250
        assert sum(1 for x in xs if abs(x - px) < 60) < 0.35 * len(xs)
    # none during intro / victory
    c3 = BossController(random.Random(6))
    c3.start(1)
    for _ in range(int(config.BOSS_INTRO_TIME / DT) - 5):
        assert c3.update(DT, 270, 0).drops == []
    c3.state = "fight"
    c3.damage(1000)
    for _ in range(int((config.BOSS_VICTORY_TIME + 1) / DT)):
        assert c3.update(DT, 270, 0).drops == []


#Resize
def test_on_resize():
    c = to_fight(BossController(random.Random(9)), 1)
    c.damage(35)
    run(c, 2.0, px=270)
    for _ in range(int(8 / DT)):
        c.update(DT, 270)
        if c.sweeps:
            break
    assert c.sweeps
    base = config.LOGICAL_W
    try:
        old = config.LOGICAL_W
        x0 = c.boss.pos.x
        sw = [(s.x_from, s.x_to) for s in c.sweeps]
        config.set_logical_width(1960)
        c.on_resize(old)
        k = 1960 / old
        lo = c.boss.half_w + config.BOSS_MARGIN
        assert approx(c.boss.pos.x, min(max(x0 * k, lo), 1960 - lo), 1e-6)
        for s, (a, b) in zip(c.sweeps, sw):
            assert approx(s.x_from, a * k, 1e-6) and approx(s.x_to, b * k, 1e-6)
            z0, z1 = s.zone
            assert z0 >= -1 and z1 <= 1960 + 1
        run(c, 3.0, px=900)                                   # keeps running, boss stays in range
        assert lo - 1e-6 <= c.boss.pos.x <= 1960 - lo + 1e-6
        old = config.LOGICAL_W
        config.set_logical_width(540)
        c.on_resize(old)
        lo = c.boss.half_w + config.BOSS_MARGIN
        assert lo - 1e-6 <= c.boss.pos.x <= 540 - lo + 1e-6
        for s in c.sweeps:
            z0, z1 = s.zone
            assert z1 - z0 <= 0.55 * 540 + 1e-6
        c.on_resize(540)                                      # same width: no-op
        c2 = BossController()
        c2.on_resize(960)                                     # no boss: no-op
        run(c, 4.0, px=270)
    finally:
        config.set_logical_width(base)


#Determinism, soak
def transcript(seed, seconds=40.0, kind_number=1):
    c = BossController(random.Random(seed))
    c.start(kind_number)
    out = []
    for i in range(int(seconds / DT)):
        tick = c.update(DT, 270 + 160 * math.sin(i * DT * 0.9), 0)
        if i == int(15 / DT):
            c.damage(36)
        if i == int(28 / DT):
            c.damage(35)
        out.append((tuple((round(s.x, 6), round(s.y, 6), round(s.vx, 6), round(s.vy, 6), s.shape, s.color) for s in tick.shots),
                    tuple((d.kind, round(d.x, 6)) for d in tick.drops), tuple(tick.events),
                    round(c.boss.pos.x, 6), tuple((round(s.x_from, 6), round(s.x_to, 6)) for s in c.sweeps)))
    return out


def test_determinism():
    a, b, c = transcript(123), transcript(123), transcript(124)
    assert a == b
    assert a != c
    assert sum(1 for t in a if t[0]) > 5
    assert transcript(5, kind_number=2) == transcript(5, kind_number=2)


def test_soak():
    """Thousands of steps in every kind / width with random damage and a wandering player: no NaN, no crash."""
    shapes, colors, total = set(), set(), 0
    for w in WIDTHS:
        with width(w):
            for number in (1, 2, 3, 4, 5, 6, 7):
                rng = random.Random(w + number)
                c = BossController(random.Random(rng.random()))
                c.start(number)
                px = config.LOGICAL_W / 2
                for i in range(5000):
                    px = min(max(px + rng.uniform(-14, 14), 0), config.LOGICAL_W)
                    tick = c.update(DT, px, rng.randint(0, 3))
                    for s in tick.shots:
                        total += 1
                        assert all(math.isfinite(v) for v in (s.x, s.y, s.vx, s.vy, s.radius)), s
                        assert s.radius > 0 and s.vy > 0
                        shapes.add(s.shape)
                        colors.add(s.color)
                    b = c.boss
                    assert math.isfinite(b.pos.x) and math.isfinite(b.pos.y) and math.isfinite(b.hp)
                    assert 0 <= b.hp <= b.max_hp and 0 <= b.hit_flash <= 1 and 0 <= b.charge <= 1 and 0 <= b.death_t <= 1
                    if i % 97 == 0 and c.damageable and rng.random() < 0.5:
                        c.damage(rng.uniform(0.5, 3.0))
                    if i % 40 == 0:
                        c.sweep_hits(pg.Rect(int(px - 50), config.PLAYER_Y - 11, 100, 22))
                    for sw in c.sweeps:
                        assert math.isfinite(sw.beam_x) and sw.warn_time >= 1.1
    assert shapes <= SHAPES and colors <= SHOT_COLORS and total > 500, (shapes, colors, total)
    # a long fight (>100 s) that reaches enrage and victory with a 1/60 step too
    c = to_fight(BossController(random.Random(1)), 1)
    for i in range(int(120 * 120)):
        c.update(1 / 60 if i % 2 else DT, 200)
    assert c.state == "enrage"
    c.damage(1e9)
    for _ in range(int(4 / DT)):
        c.update(DT, 200)
    assert c.state == "done"


#End to end: a dodging bot with the real Player against real bullets, whole fights
class _Bullet:
    __slots__ = ("x", "y", "vx", "vy", "r", "name", "t0", "ph")

    def __init__(self, s, name="", t0=0.0, ph=1):
        self.x, self.y, self.vx, self.vy, self.r = s.x, s.y, s.vx, s.vy, s.radius
        self.name, self.t0, self.ph = name, t0, ph


BOT_DT = 1 / 60                     # step of the bot's own paddle model
BOT_MOVE_STEPS = 90                 # the paddle model runs 1.5 s, then it is assumed to stand still
BOT_TK = np.concatenate((np.arange(1, BOT_MOVE_STEPS + 1) * BOT_DT, 1.5 + np.arange(1, 101) / 20.0))   # look-ahead grid, 6.5 s
BOT_STEPS = len(BOT_TK)             # bullets can need 4+ s to cross a wide field: the bot watches their whole flight
BOT_MARGIN = 5.0                    # px of clearance the bot insists on


def bot_drive(pl, target, brake):
    """One physics step steering the real Player to `target` (bang-bang with braking)."""
    v = pl.vel.x
    stop = v * abs(v) / (2 * brake)
    err = target - pl.pos.x
    if v * err < 0:
        d = 1 if err > 0 else -1
    elif abs(stop) >= abs(err) - 1.0 and v != 0:
        d = -1 if v > 0 else 1
    else:
        d = 0 if abs(err) < 2.0 else (1 if err > 0 else -1)
    pl.update(DT, d)


def bot_path(x0, v0, target, pw):
    """Where the paddle will be on the look-ahead grid when steered to `target` (mirrors Player + bot_drive)."""
    a, vmax = config.player_accel(), config.player_max_speed()
    fric, boost = config.player_friction(), config.PLAYER_TURN_BOOST
    brake = a * boost
    lo, hi = pw / 2, config.LOGICAL_W - pw / 2
    xs = np.empty(BOT_STEPS)
    x, v = x0, v0
    for k in range(BOT_MOVE_STEPS):
        err = target - x
        stop = v * abs(v) / (2 * brake)
        if v * err < 0:
            d = 1 if err > 0 else -1
        elif abs(stop) >= abs(err) - 1.0 and v != 0:
            d = -1 if v > 0 else 1
        else:
            d = 0 if abs(err) < 2.0 else (1 if err > 0 else -1)
        if d:
            acc = a * (boost if v * d < 0 else 1.0)
            v = max(-vmax, min(vmax, v + acc * d * BOT_DT))
        else:
            drop = fric * BOT_DT
            v = 0.0 if abs(v) <= drop else v - math.copysign(drop, v)
        x += v * BOT_DT
        if x < lo or x > hi:
            x = min(max(x, lo), hi)
            v = 0.0
        xs[k] = x
    xs[BOT_MOVE_STEPS:] = x
    return xs


def bot_first_hit(xs, pw, bullets, sweeps, margin=BOT_MARGIN):
    """Index of the first look-ahead step at which the path is hit (BOT_STEPS if never)."""
    top = config.PLAYER_Y - config.PLAYER_H / 2 - boss_mod.BAND_PAD
    bottom = config.PLAYER_Y + config.PLAYER_H / 2
    tk = BOT_TK
    first = BOT_STEPS
    if len(bullets):
        bx = bullets[:, 0:1] + bullets[:, 2:3] * tk[None, :]
        by = bullets[:, 1:2] + bullets[:, 3:4] * tk[None, :]
        rad = 0.8 * bullets[:, 4:5] + margin
        dx = np.maximum(xs[None, :] - pw / 2 - bx, 0.0) + np.maximum(bx - (xs[None, :] + pw / 2), 0.0)
        dy = np.maximum(top - by, 0.0) + np.maximum(by - bottom, 0.0)
        hit = (dx ** 2 + dy ** 2) <= rad ** 2
        idx = np.nonzero(hit.any(axis=0))[0]
        if len(idx):
            first = min(first, int(idx[0]))
    for z0, z1, t_on, t_off in sweeps:
        on = (tk >= t_on - 0.05) & (tk <= t_off + 0.05)
        over = on & (xs + pw / 2 + margin > z0) & (xs - pw / 2 - margin < z1)
        idx = np.nonzero(over)[0]
        if len(idx):
            first = min(first, int(idx[0]))
    return first


def bot_choose(pl, snap, react):
    """Pick the nearest paddle centre whose approach path the look-ahead says is clean.

    `snap` is the world as it was `react` s ago: bullets are extrapolated to now, newer shots are unseen.
    """
    bullets, sweeps = snap
    pw, W = pl.width, config.LOGICAL_W
    rows = [(x + vx * react, y + vy * react, vx, vy, r) for x, y, vx, vy, r in bullets
            if y + vy * react < config.LOGICAL_H + 40]
    arr = np.array(rows) if rows else np.empty((0, 5))
    sw = []
    for z0, z1, age, warn, fire in sweeps:
        now = age + react
        if now < warn + fire:
            sw.append((z0, z1, max(0.0, warn - now), warn + fire - now))
    x0, v0 = pl.pos.x, pl.vel.x
    cands = sorted([x0] + [float(c) for c in np.arange(pw / 2, W - pw / 2 + 1e-9, max(8.0, pw / 3))],
                   key=lambda c: abs(c - x0))
    paths = {}
    best, best_key = x0, None
    for margin in (0.35 * pw, 0.12 * pw, BOT_MARGIN):          # prefer roomy spots, settle for tight ones
        for c in cands:
            xs = paths.get(c)
            if xs is None:
                xs = paths[c] = bot_path(x0, v0, c, pw)
            first = bot_first_hit(xs, pw, arr, sw, margin)
            if first >= BOT_STEPS:
                return c                        # candidates are sorted by distance: the first clean one wins
            if margin == BOT_MARGIN and (best_key is None or first > best_key):
                best, best_key = c, first       # nothing is clean: delay the hit as long as possible
    return best


def bot_fight(w, number, seed, seconds=95.0, react=0.25, kill_at=80.0, p2_at=45.0):
    """Fight against the bot. Phases advance on a schedule. Returns (bullet hits, sweep hits, seconds, log)."""
    with width(w):
        c = BossController(random.Random(seed))
        c.start(number)
        pl = Player()
        bullets, history, hits_log = [], [], []
        hits_s = 0
        target = pl.pos.x
        brake = config.player_accel() * config.PLAYER_TURN_BOOST
        t = 0.0
        for i in range(int(seconds / DT)):
            t = i * DT
            tick = c.update(DT, pl.pos.x, 0)
            for s in tick.shots:
                bullets.append(_Bullet(s, c.attack, t, c.boss.phase))
            if c.state == "fight":
                if c.boss.phase == 1 and t > 15:
                    c.damage(34.5)
                elif c.boss.phase == 2 and t > p2_at:
                    c.damage(32)
            if c.state in ("fight", "enrage") and c.boss.phase == 3 and t > kill_at:
                c.damage(1e9)
            if c.state == "done":
                break
            for b in bullets:
                b.x += b.vx * DT
                b.y += b.vy * DT
            bullets = [b for b in bullets if b.y < config.LOGICAL_H + 40]
            rect = pl.rect
            for b in bullets:
                dx = max(rect.left - b.x, 0.0, b.x - rect.right)
                dy = max(rect.top - 6 - b.y, 0.0, b.y - rect.bottom)
                if dx * dx + dy * dy <= (0.8 * b.r) ** 2:
                    hits_log.append((round(t, 2), b.name, b.ph, round(pl.pos.x), round(pl.vel.x)))
                    b.y = 1e9
            if c.sweep_hits(rect):
                hits_s += 1
            history.append(([(b.x, b.y, b.vx, b.vy, b.r) for b in bullets],
                            [(s.zone[0], s.zone[1], s.age, s.warn_time, s.fire_time) for s in c.sweeps]))
            if len(history) > int(react / DT) + 1:
                history.pop(0)
            if i % 4 == 0:
                target = bot_choose(pl, history[0], react)
            bot_drive(pl, target, brake)
        return len(hits_log), hits_s, t, hits_log


def test_bot_survives_whole_fights():
    """A bot that sees the world 0.25 s late and plans paths with the real paddle takes (almost) no hits."""
    total_b = total_s = 0
    t0 = time.time()
    # (width, boss number, kill_at, seconds): even bosses run into the enrage phase (after ~93 s)
    for w, number, kill_at, secs in ((540, 1, 80, 95), (540, 6, 125, 128), (960, 2, 125, 128), (960, 4, 80, 95),
                                      (1960, 3, 80, 95), (1960, 5, 125, 128), (540, 7, 80, 95)):
        hb, hs, took, log = bot_fight(w, number, seed=500 + number + w, seconds=secs, kill_at=kill_at, p2_at=40.0)
        total_b += hb
        total_s += hs
        print(f"    width {w:4d} boss {number}: bullet hits {hb}, sweep hits {hs}, {took:.0f}s  {log[:3] if log else ''}")
    print(f"  bot fights took {time.time() - t0:.1f}s")
    assert total_s == 0, total_s
    assert total_b == 0, total_b


TESTS = [
    test_design_and_boss_data,
    test_state_machine,
    test_enrage_on_time,
    test_event_order_full_fight,
    test_damage_phases_stagger,
    test_enrage_rates,
    test_patrol,
    test_sweep_object_and_hits,
    test_sweeps_fair_and_spaced,
    test_sweep_slides_locks_and_fires_under_the_boss,
    test_sweep_laser_stage_and_open_amount,
    test_sweep_locked_flag_and_legacy_static,
    test_pool_design,
    test_shot_basics_and_speed_range,
    test_pattern_geometry,
    test_aimed_telegraph,
    test_pattern_fairness,
    test_pattern_fairness_late_cycles,
    test_pattern_fairness_moving_paddle,
    test_wide_paddle_scale,
    test_planner_matches_ground_truth,
    test_volleys_in_sequence,
    test_drops,
    test_ball_lost_delays_next_ball,
    test_on_resize,
    test_determinism,
    test_soak,
    test_bot_survives_whole_fights,
]


def main() -> int:
    failed = 0
    for test in TESTS:
        t0 = time.time()
        base = config.LOGICAL_W
        real_max_hp = config.boss_max_hp
        if test is not test_design_and_boss_data:       # the other tests think in percent: damage(35) = 35% of any boss
            config.boss_max_hp = lambda number: 100.0 * (1.0 + config.BOSS_HP_GROWTH * ((max(1, number) - 1) // config.BOSS_KINDS))
        try:
            test()
            print(f"PASS {test.__name__} ({time.time() - t0:.1f}s)")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {test.__name__}: {e!r}")
            import traceback
            traceback.print_exc()
        finally:
            config.boss_max_hp = real_max_hp
            config.set_logical_width(base)
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
