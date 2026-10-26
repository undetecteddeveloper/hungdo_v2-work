"""Gameplay tests (plain asserts, no pytest).

Run from hungdo_v2/:   python -m tests.test_gameplay
or from anywhere:      python hungdo_v2/tests/test_gameplay.py
"""
import dataclasses
import json
import math
import os
import random
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg  # noqa: E402

from game import config, paths  # noqa: E402
from game.entities.items import Item, catch_y  # noqa: E402
from game.entities.player import Player  # noqa: E402
from game.systems import difficulty, spawner as spawner_mod  # noqa: E402
from game.systems.combo import Combo  # noqa: E402
from game.systems.highscore import HighScore  # noqa: E402
from game.systems.powerups import PowerUps  # noqa: E402
from game.systems.spawner import Spawner  # noqa: E402

DT = config.PHYSICS_DT
LEVELS = range(1, config.DIFFICULTY_MAX_LEVEL + 1)
GOOD = config.GOOD_KINDS
REACTION = 0.25         # s a human keeps doing the wrong thing before reacting
FAIR_SLACK = 0.9        # worst-case reach must fit in 90% of the fastest fall


#Helpers
def approx(a, b, eps=1e-6):
    return abs(a - b) <= eps


def fall_time(kind: str, level: int, vy0: float = None) -> float:
    """Seconds from spawn (just above the top) until the item touches the paddle top."""
    p = difficulty.params_for_level(level)
    if vy0 is None:     # fastest possible spawn speed = worst case
        vy0 = spawner_mod.SPAWN_VY[1] * p.max_fall_speed_mult
    item = Item(kind, config.LOGICAL_W / 2, None, 0.0, vy0, terminal_mult=p.max_fall_speed_mult)
    t = 0.0
    target = catch_y(item.radius)
    while item.pos.y < target:
        item.update(DT, p.gravity, 1.0, None)
        t += DT
    return t


def reach_time(start_x: float, start_v: float, target_x: float, tol: float) -> float:
    """Simulate the real Player: keep the old input for REACTION s, then steer to target_x."""
    pl = Player(start_x)
    pl.vel.x = start_v
    keep = (start_v > 0) - (start_v < 0)
    t = 0.0
    while t < 5.0:
        if abs(pl.pos.x - target_x) <= tol:
            return t
        if t < REACTION:
            d = keep
        else:
            d = 1 if target_x > pl.pos.x else -1
        pl.update(DT, d)
        t += DT
    return math.inf


def worst_reach_time() -> float:
    """Worst case over paddle start positions/velocities and every landing x an item can have."""
    half = config.PLAYER_W / 2
    tol = config.PLAYER_W / 2           # ignores the item radius: conservative
    r_min = min(config.ITEM_RADIUS[k] for k in GOOD)
    targets = [r_min, config.LOGICAL_W - r_min]     # extreme landing x (diagonal items reach the walls)
    worst = 0.0
    x = half
    while x <= config.LOGICAL_W - half + 1e-9:
        for v in (-config.PLAYER_MAX_SPEED, 0.0, config.PLAYER_MAX_SPEED):
            for tx in targets:
                worst = max(worst, reach_time(x, v, tx, tol))
        x += 10
    return worst


def player_travel_table():
    """Real-Player time to cover d px from rest, sampled per pixel (for the pair check)."""
    pl = Player(config.PLAYER_W / 2)
    start = pl.pos.x
    table = [0.0]
    t = 0.0
    while len(table) < config.LOGICAL_W + 2:
        pl.update(DT, 1)
        t += DT
        while len(table) <= pl.pos.x - start and len(table) < config.LOGICAL_W + 2:
            table.append(t)
        if pl.pos.x >= config.LOGICAL_W - pl.half_width:
            break
    while len(table) < config.LOGICAL_W + 2:   # beyond the wall: extrapolate at max speed
        table.append(table[-1] + 1 / config.PLAYER_MAX_SPEED)
    return table


#Difficulty
def test_level_thresholds():
    assert difficulty.score_for_level(1) == 0
    assert difficulty.score_for_level(2) == 120
    assert difficulty.score_for_level(3) == 290
    assert difficulty.score_for_level(4) == 540
    prev_step = None
    for lv in range(2, 30):
        lo, hi = difficulty.score_for_level(lv), difficulty.score_for_level(lv + 1)
        assert hi > lo
        assert difficulty.level_for_score(lo) == lv
        assert difficulty.level_for_score(lo - 1) == lv - 1
        step = hi - lo
        if prev_step:
            assert 1.3 < step / prev_step < 1.6, (lv, step / prev_step)
        prev_step = step
    assert difficulty.level_for_score(0) == 1
    assert difficulty.level_for_score(-50) == 1
    assert 0.0 <= difficulty.level_progress(200) <= 1.0


def test_difficulty_monotonic():
    ps = [difficulty.params_for_level(lv) for lv in LEVELS]
    first, last = ps[0], ps[-1]
    assert first.bomb_chance == 0.0 and first.diagonal_chance == 0.0 and first.burst_chance == 0.0
    assert 0.9 <= first.spawn_interval <= 1.1
    for a, b in zip(ps, ps[1:]):
        assert b.spawn_interval < a.spawn_interval
        assert b.gravity_mult > a.gravity_mult
        assert b.max_fall_speed_mult > a.max_fall_speed_mult
        assert b.bomb_chance >= a.bomb_chance
        assert b.diagonal_chance >= a.diagonal_chance
        assert b.burst_chance >= a.burst_chance
        assert b.powerup_interval <= a.powerup_interval
        share = lambda p, k: p.weights[k] / sum(p.weights.values())
        assert share(b, "epic") > share(a, "epic")
        assert share(b, "common") < share(a, "common")
    # Values clamp past the top level and below 1
    assert difficulty.params_for_level(99) == last
    assert difficulty.params_for_level(0) == first
    for p in ps:
        assert 0 <= p.bomb_chance <= 0.3 and 0 <= p.burst_chance <= 0.25 and p.spawn_interval >= 0.35
        assert set(p.weights) == set(GOOD)


#Fairness
def test_reachability():
    """Any single good item is catchable at every level from the worst paddle state."""
    worst = worst_reach_time()
    print(f"  worst-case reach (react {REACTION}s, wrong way at max speed, wall to wall): {worst:.3f}s")
    for lv in LEVELS:
        fastest = min(fall_time(k, lv) for k in GOOD)
        assert worst <= fastest * FAIR_SLACK, (lv, worst, fastest)
        if lv in (1, 5, 10, 15):
            print(f"  level {lv:2d}: fastest good fall {fastest:.3f}s  (reach/fall = {worst / fastest:.2f})")
    # Level 1 is relaxed: the slowest common item takes well over a second and a half
    assert fall_time("common", 1) > 1.6


def simulate_spawns(level: int, seconds: float, seed: int):
    """Run the spawner + real items; returns ([(t, x, kind) good landings], [(t_spawn, x) bombs], items)."""
    p = difficulty.params_for_level(level)
    sp = Spawner(random.Random(seed))
    items, landings, bombs = [], [], []
    t = 0.0
    while t < seconds or items:
        if t < seconds:
            for it in sp.update(DT, p):
                items.append(it)
                if it.kind == "bomb":
                    bombs.append((t, it.pos.x))
        t += DT
        for it in items:
            before = it.pos.y
            it.update(DT, p.gravity, 1.0, None)
            target = catch_y(it.radius)
            if it.is_good and before < target <= it.pos.y:
                landings.append((t, it.pos.x, it.kind))
        items = [it for it in items if it.alive]
    return landings, bombs


def test_spawner_fairness():
    """Consecutive good landings are always reachable with the real paddle and the rate stays sane."""
    table = player_travel_table()
    tol = config.PLAYER_W / 2
    for lv in LEVELS:
        landings, _ = simulate_spawns(lv, 60.0, seed=1000 + lv)
        landings.sort()
        assert len(landings) > 30, (lv, len(landings))
        for (t1, x1, _), (t2, x2, _) in zip(landings, landings[1:]):
            need = max(0.0, abs(x2 - x1) - tol)
            travel = table[min(len(table) - 1, int(math.ceil(need)))]
            assert travel <= (t2 - t1) + 1e-9, (lv, t1, x1, t2, x2, travel)
        # No more than 5 good catches in any 1 s window
        j = 0
        peak = 0
        for i in range(len(landings)):
            while landings[i][0] - landings[j][0] > 1.0:
                j += 1
            peak = max(peak, i - j + 1)
        assert peak <= 5, (lv, peak)
        if lv in (1, 5, 10, 15):
            rate = len(landings) / 60.0
            print(f"  level {lv:2d}: {rate:.2f} good items/s, peak {peak} in 1s")


def test_bomb_spacing():
    """Never a bomb directly above another bomb spawned within 0.4 s (also under bomb-only stress)."""
    base = difficulty.params_for_level(config.DIFFICULTY_MAX_LEVEL)
    stress = dataclasses.replace(base, bomb_chance=1.0, spawn_interval=0.05, burst_chance=0.0)
    for params in (base, stress):
        sp = Spawner(random.Random(7))
        bombs = []
        t = 0.0
        while t < 120.0:
            for it in sp.update(DT, params):
                if it.kind == "bomb":
                    bombs.append((t, it.pos.x))
            t += DT
        assert len(bombs) > 30, len(bombs)
        for i, (t1, x1) in enumerate(bombs):
            for t2, x2 in bombs[i + 1:]:
                if t2 - t1 >= spawner_mod.BOMB_REPEAT_TIME:
                    break
                assert abs(x2 - x1) >= spawner_mod.BOMB_MIN_DX, (t1, x1, t2, x2)
    # Level 1 never spawns bombs
    landings, bombs = simulate_spawns(1, 60.0, seed=3)
    assert not bombs


def test_spawner_items():
    sp = Spawner(random.Random(11))
    p = difficulty.params_for_level(10)
    kinds, powers = set(), set()
    t = 0.0
    while t < 600:
        for it in sp.update(DT, p):
            kinds.add(it.kind)
            if it.power:
                powers.add(it.power)
            assert it.radius <= it.pos.x <= config.LOGICAL_W - it.radius
            assert it.pos.y < 0                         # spawned above the screen
        t += DT
    assert kinds == {"common", "rare", "epic", "bomb", "powerup"}, kinds
    assert powers == set(config.POWERUP_NAMES), powers
    sp.allow_heart = False
    sp.reset()
    t = 0.0
    while t < 300:
        for it in sp.update(DT, p):
            assert it.power != "heart"
        t += DT


#Player
def test_player_walls():
    pl = Player()
    half = pl.half_width
    # Hold left into the wall: flush, no jitter
    xs = []
    for i in range(240):
        pl.update(DT, -1)
        if i >= 180:
            xs.append(pl.pos.x)
    assert all(x == half for x in xs), set(xs)
    assert pl.vel.x == 0
    # Coast into the right wall at full speed: small bounce, then rest inside
    pl.reset(config.LOGICAL_W - half - 20)
    pl.vel.x = config.PLAYER_MAX_SPEED
    bounced = False
    for _ in range(240):
        pl.update(DT, 0)
        assert half - 1e-9 <= pl.pos.x <= config.LOGICAL_W - half + 1e-9
        bounced |= pl.vel.x < 0
    assert bounced and pl.vel.x == 0
    # Growing wider next to a wall never pokes outside
    pl.reset(config.LOGICAL_W - half)
    pl.set_wide(True)
    for _ in range(240):
        pl.update(DT, 1)
        assert pl.rect.right <= config.LOGICAL_W and pl.rect.left >= 0
    assert approx(pl.width, config.PLAYER_W * config.WIDE_FACTOR, 0.5)
    pl.set_wide(False)
    for _ in range(240):
        pl.update(DT, 0)
    assert approx(pl.width, config.PLAYER_W, 0.5)


def test_player_physics():
    pl = Player(config.PLAYER_W / 2)                           # start at the left wall
    for _ in range(30):
        pl.update(DT, 1)
    assert approx(pl.vel.x, config.PLAYER_MAX_SPEED)          # capped
    assert pl.pos.x < config.LOGICAL_W - pl.half_width        # still short of the right wall
    # Friction brings it to rest without overshooting backwards
    for _ in range(60):
        pl.update(DT, 0)
        assert pl.vel.x >= 0
    assert pl.vel.x == 0
    # Turn boost: reversing from full speed is quicker than plain acceleration would be
    pl.reset()
    pl.vel.x = config.PLAYER_MAX_SPEED
    steps = 0
    while pl.vel.x > 0:
        pl.update(DT, -1)
        steps += 1
    plain = config.PLAYER_MAX_SPEED / config.PLAYER_ACCEL / DT
    assert steps < plain * 0.7, (steps, plain)
    assert pl.rect.height == config.PLAYER_H and pl.rect.centery == config.PLAYER_Y


#Items
def test_item_physics():
    p = difficulty.params_for_level(15)
    for kind in ("common", "rare", "epic", "bomb", "powerup"):
        it = Item(kind, 100, -20, 0, 0, terminal_mult=p.max_fall_speed_mult)
        for _ in range(600):
            it.update(DT, p.gravity, 1.0, None)
            assert it.vel.y <= config.ITEM_TERMINAL_SPEED[kind] * p.max_fall_speed_mult + 1e-6
        assert it.fell and not it.alive
    # Diagonal: bounces off both walls, stays inside, loses speed by ITEM_RESTITUTION
    it = Item("rare", 60, -20, -300, 0)
    hits = 0
    last_sign = -1
    for _ in range(240):
        it.update(DT, 100, 1.0, None)
        assert it.radius <= it.pos.x <= config.LOGICAL_W - it.radius
        sign = 1 if it.vel.x > 0 else -1
        if sign != last_sign:
            hits += 1
            last_sign = sign
    assert hits >= 1 and abs(it.vel.x) < 300
    # Slow power-up: half the time scale -> about half the distance
    a, b = Item("common", 200, 0), Item("common", 200, 0)
    for _ in range(60):
        a.update(DT, 520, 1.0, None)
        b.update(DT, 520, config.SLOW_FACTOR, None)
    assert b.pos.y < a.pos.y * 0.6
    # Magnet: bends good items toward the paddle smoothly, ignores bombs
    good = Item("common", 150, config.PLAYER_Y - 300)
    bomb = Item("bomb", 150, config.PLAYER_Y - 300)
    max_jump = 0.0
    for _ in range(60):
        x0 = good.pos.x
        good.update(DT, 520, 1.0, 350)
        bomb.update(DT, 520, 1.0, 350)
        max_jump = max(max_jump, abs(good.pos.x - x0))
    assert good.pos.x > 160 and good.vel.x > 0 and good.magnetized
    assert bomb.pos.x == 150
    assert max_jump < 10            # smooth: no snapping
    # An item that would miss by 200 px lands on the paddle with the magnet on
    it = Item("common", 200, None, 0, 50)
    while it.pos.y < catch_y(it.radius):
        it.update(DT, config.GRAVITY, 1.0, 400)
    assert abs(it.pos.x - 400) < config.PLAYER_W / 2, it.pos.x
    # ... but nothing happens outside the magnet radius
    far = Item("common", 400 - config.MAGNET_RADIUS - 20, None, 0, 50)
    while far.pos.y < catch_y(far.radius):
        far.update(DT, config.GRAVITY, 1.0, 400)
    assert far.pos.x == 400 - config.MAGNET_RADIUS - 20
    # Prediction matches the live item exactly
    it = Item("epic", 80, None, 200, 60)
    t_pred, x_pred = it.predict_landing(700)
    t = 0.0
    target = catch_y(it.radius)
    while it.pos.y < target:
        it.update(DT, 700, 1.0, None)
        t += DT
    assert approx(t, t_pred, 1e-9) and approx(it.pos.x, x_pred, 1e-6)


#Systems
def test_combo():
    c = Combo()
    assert c.multiplier == 1
    ups = [c.hit() for _ in range(30)]
    assert [i + 1 for i, u in enumerate(ups) if u] == [5, 10, 15, 20]   # 2x..5x, then capped
    assert c.multiplier == config.COMBO_MAX_MULT and c.count == 30 and c.best == 30
    for n in range(40):
        c.count = n
        assert c.multiplier == min(1 + n // config.COMBO_STEP, config.COMBO_MAX_MULT)
    c.count = 7
    c.break_()
    assert c.count == 0 and c.multiplier == 1 and c.best == 30
    c.reset()
    assert c.best == 0


def test_powerups():
    pu = PowerUps()
    assert pu.activate("magnet") and pu.activate("slow")
    assert not pu.activate("shield") and not pu.activate("nope")
    assert pu.is_active("magnet") and approx(pu.remaining("magnet"), 8)
    expired = []
    for _ in range(int(3 * config.PHYSICS_HZ)):
        expired += pu.update(DT)
    assert approx(pu.remaining("magnet"), 5, 1e-6) and not expired
    assert approx(pu.time_scale, config.SLOW_FACTOR, 1e-3)
    assert [n for n, _, _ in pu.active()] == ["magnet", "slow"]
    assert all(d == config.POWERUP_DURATION[n] for n, _, d in pu.active())
    # Refresh to full duration (no stacking past it)
    pu.activate("magnet")
    assert approx(pu.remaining("magnet"), 8)
    for _ in range(int(7 * config.PHYSICS_HZ)):
        expired += pu.update(DT)
    assert "slow" in expired and not pu.is_active("slow") and pu.is_active("magnet")
    assert pu.expiring("magnet")
    assert approx(pu.time_scale, 1.0, 1e-3)          # eased back
    for _ in range(int(2 * config.PHYSICS_HZ)):
        pu.update(DT)
    assert pu.active() == [] and pu.remaining("magnet") == 0.0
    pu.activate("wide")
    pu.reset()
    assert pu.active() == [] and pu.time_scale == 1.0


def test_highscore():
    original = paths.user_data_dir
    with tempfile.TemporaryDirectory() as tmp:
        paths.user_data_dir = lambda: tmp
        try:
            save = os.path.join(tmp, "save.json")
            hs = HighScore()
            assert hs.best_score == 0 and hs.games_played == 0
            assert hs.submit(150, 3, combo=12)
            assert not hs.submit(100, 5)
            assert hs.submit(400, 4)
            assert not hs.submit(400, 2)                     # tie is not a new record
            assert not os.path.exists(save + ".tmp")
            hs2 = HighScore()
            assert (hs2.best_score, hs2.best_level, hs2.best_combo, hs2.games_played) == (400, 5, 12, 4)
            # Corrupt file -> defaults, bad file kept aside, next save works
            with open(save, "w", encoding="utf-8") as f:
                f.write("{not json")
            hs3 = HighScore()
            assert hs3.best_score == 0 and hs3.games_played == 0
            assert os.path.exists(save + ".bad")
            # Wrong types are ignored field by field
            with open(save, "w", encoding="utf-8") as f:
                json.dump({"best_score": "lots", "best_level": 7, "games_played": -3, "best_combo": True}, f)
            hs4 = HighScore()
            assert (hs4.best_score, hs4.best_level, hs4.games_played, hs4.best_combo) == (0, 7, 0, 0)
            # Atomic: a failing replace leaves the previous file untouched
            hs4.submit(50, 1)
            before = open(save, encoding="utf-8").read()
            real_replace = os.replace
            os.replace = lambda *a: (_ for _ in ()).throw(OSError("disk full"))
            try:
                assert hs4.submit(999, 9)                     # still reports the record
            finally:
                os.replace = real_replace
            assert open(save, encoding="utf-8").read() == before
            assert not os.path.exists(save + ".tmp")
        finally:
            paths.user_data_dir = original


def test_draw_smoke():
    """Drawing works with and without assets (neon module may or may not exist yet)."""
    pg.display.init()
    pg.font.init()
    pg.display.set_mode((config.LOGICAL_W, config.LOGICAL_H))
    surf = pg.Surface(config.LOGICAL_SIZE)
    from game.assets import Assets
    assets = Assets()
    pl = Player()
    pl.shield = 1
    pl.set_wide(True)
    items = [Item(k, 100 + 70 * i, 300, 120, 0, power="magnet" if k == "powerup" else None)
             for i, k in enumerate(("common", "rare", "epic", "bomb", "powerup"))]
    items.append(Item("powerup", 450, 500, power="heart"))
    for frame in range(30):
        pl.update(DT, 1 if frame < 15 else -1)
        pl.draw(surf, frame * DT)
        for it in items:
            it.update(DT, 520, 1.0, pl.pos.x)
            it.draw(surf, frame * DT, assets if frame % 2 else None)


TESTS = [
    test_level_thresholds, test_difficulty_monotonic, test_reachability, test_spawner_fairness,
    test_bomb_spacing, test_spawner_items, test_player_walls, test_player_physics, test_item_physics,
    test_combo, test_powerups, test_highscore, test_draw_smoke,
]


def main() -> int:
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {test.__name__}: {e!r}")
            import traceback
            traceback.print_exc()
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
