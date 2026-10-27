"""Ball speed tiers and boss damage formulas (plain asserts, no pytest).

Run from the repo root:   python -m tests.test_ball_tiers
"""
import math
import random
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg  # noqa: E402

from game import config  # noqa: E402
from game.entities.boss_items import HelperBall, tier_speed  # noqa: E402
from game.systems.boss import BossController  # noqa: E402

DT = config.PHYSICS_DT
SPEEDS = (620.0, 800.0, 1000.0)


def approx(a, b, eps=1e-6):
    return abs(a - b) <= eps


def floor_paddle() -> pg.Rect:
    """A full-width paddle: the ball can never be lost."""
    h = config.PLAYER_H
    return pg.Rect(0, config.PLAYER_Y - h // 2, config.LOGICAL_W, h)


def make_boss_rect() -> pg.Rect:
    return pg.Rect(config.LOGICAL_W // 2 - 80, 175, 160, 150)


def flying(x, y, vx, vy) -> HelperBall:
    ball = HelperBall(x, y)
    ball.state = "flying"
    ball.vel.update(vx, vy)
    return ball


def speed_of(ball) -> float:
    return math.hypot(ball.vel.x, ball.vel.y)


def test_config_formulas():
    assert config.BALL_TIER_SPEEDS == SPEEDS and config.BALL_TIER_DAMAGE == (1.0, 2.0, 3.0)
    assert config.BOSS_BALL_SPEED == SPEEDS[0]
    assert [tier_speed(t) for t in (1, 2, 3)] == list(SPEEDS)
    assert tier_speed(0) == SPEEDS[0] and tier_speed(9) == SPEEDS[-1]           # clamped
    # Boss 1: 2000 hp, ball 50, beam 17% = 340, one tier-1 ball hit = 50 points
    assert approx(config.boss_max_hp(1), 2000.0) and approx(config.ball_base_damage(1), 50.0)
    assert approx(config.beam_damage(1), 340.0) and config.boss_points(config.ball_base_damage(1), 1) == 50
    for n in range(1, 8):
        cycle = (n - 1) // config.BOSS_KINDS
        assert approx(config.ball_base_damage(n), 50.0 * n)
        assert approx(config.boss_max_hp(n), 2000.0 * n * (1 + config.BOSS_HP_GROWTH * cycle))
        assert approx(config.beam_damage(n), config.boss_max_hp(n) * config.BOSS_BEAM_FRAC)
        assert BossController(random.Random(1)).start(n).max_hp == config.boss_max_hp(n)
        # Tier-1 hits needed stay about the same for every boss in the first cycle
        if cycle == 0:
            assert approx(config.boss_max_hp(n) / config.ball_base_damage(n), 40.0)
        for tier in (1, 2, 3):
            assert approx(config.ball_base_damage(n) * config.BALL_TIER_DAMAGE[tier - 1], 50.0 * n * tier)
    # A boss's total pool of points does not grow with its hp: boss n gives 1/n per hp
    assert config.boss_points(config.boss_max_hp(1), 1) == 2000
    assert config.boss_points(config.boss_max_hp(2), 2) == 2000
    assert config.boss_points(config.ball_base_damage(3), 3) == 50


def test_new_ball_is_tier_one():
    ball = HelperBall(100)
    assert ball.tier == 1 and ball.speed == SPEEDS[0] and ball.damage_mult == 1.0 and ball.tier_up == 0
    # Being caught does not change the tier and the ball leaves at the tier-1 speed
    paddle = pg.Rect(0, config.PLAYER_Y - config.PLAYER_H // 2, config.LOGICAL_W, config.PLAYER_H)
    ball = HelperBall(paddle.centerx + 30, paddle.top - 40)
    for _ in range(200):
        if "caught" in ball.update(DT, 1.0, None, paddle, None):
            break
    assert ball.state == "flying" and ball.tier == 1 and ball.tier_up == 0
    assert approx(speed_of(ball), SPEEDS[0])
    assert approx(HelperBall.launched(100, 300, 0.0).speed, SPEEDS[0]) and HelperBall.launched(100, 300, 0.0).tier == 1


def test_tier_rises_on_each_paddle_bounce():
    paddle = floor_paddle()
    ball = flying(config.LOGICAL_W / 2 + 20, paddle.top - 60, 0.0, SPEEDS[0])
    seen = []                                       # (tier after, tier_up flag, speed) per paddle bounce
    for _ in range(int(40 * config.PHYSICS_HZ)):
        ev = ball.update(DT, 1.0, None, paddle, None)
        if "paddle" in ev:
            seen.append((ball.tier, ball.tier_up, speed_of(ball)))
        else:
            assert ball.tier_up == 0                # the flag is only set by the update() that raised the tier
        if len(seen) >= 5:
            break
    assert len(seen) == 5, seen
    # Tier goes up BEFORE the ball leaves: the first bounce already flies at the tier-2 speed
    assert [(t, up) for t, up, _ in seen] == [(2, 2), (3, 3), (3, 0), (3, 0), (3, 0)], seen
    assert [round(s, 3) for _, _, s in seen] == [800.0, 1000.0, 1000.0, 1000.0, 1000.0], seen
    assert ball.tier == 3 and approx(ball.damage_mult, 3.0) and approx(speed_of(ball), 1000.0)


def test_tier_unchanged_by_walls_ceiling_and_boss():
    W = config.LOGICAL_W
    boss = make_boss_rect()
    for tier in (1, 2, 3):
        sp = tier_speed(tier)
        # Walls and ceiling
        for x, y, vx, vy, want in ((8, 400, -0.8 * sp, -0.6 * sp, "wall"), (W - 8, 400, 0.8 * sp, -0.6 * sp, "wall"),
                                   (W / 2, 8, 0.6 * sp, -0.8 * sp, "ceiling")):
            ball = flying(x, y, vx, vy)
            ball.tier = tier
            got = []
            for _ in range(30):
                got += ball.update(DT, 1.0, None, None, None)
            assert got == [want], (tier, got)
            assert ball.tier == tier and ball.tier_up == 0 and approx(speed_of(ball), sp)
        # Boss
        ball = flying(boss.centerx, boss.bottom + 80, 0.0, -sp)
        ball.tier = tier
        got = []
        for _ in range(60):
            got += ball.update(DT, 1.0, None, None, boss)
        assert got == ["boss"], (tier, got)
        assert ball.tier == tier and ball.tier_up == 0 and approx(speed_of(ball), sp)
        assert approx(ball.damage_mult, config.BALL_TIER_DAMAGE[tier - 1])


def test_balls_have_independent_tiers():
    paddle = floor_paddle()
    a = flying(100, paddle.top - 50, 0.0, SPEEDS[0])
    b = flying(config.LOGICAL_W - 100, paddle.top - 50, 0.0, SPEEDS[0])
    # a bounces once, b keeps flying up the field and only meets the ceiling
    b.vel.update(0.0, -SPEEDS[0])
    for _ in range(40):
        a.update(DT, 1.0, None, paddle, None)
        b.update(DT, 1.0, None, None, None)
    assert a.tier == 2 and b.tier == 1
    assert approx(speed_of(a), SPEEDS[1]) and approx(speed_of(b), SPEEDS[0])
    assert a.damage_mult == 2.0 and b.damage_mult == 1.0
    # A ball that is lost just dies; a fresh one starts again at tier 1
    gone = flying(40, config.PLAYER_Y + 40, 0.0, SPEEDS[2])
    gone.tier = 3
    small = pg.Rect(300, config.PLAYER_Y - config.PLAYER_H // 2, 80, config.PLAYER_H)
    ev = []
    for _ in range(300):
        ev += gone.update(DT, 1.0, None, small, None)
    assert ev == ["lost"] and not gone.alive
    assert HelperBall(100).tier == 1


def test_damage_on_boss_n():
    for n in range(1, 8):
        for tier in (1, 2, 3):
            ball = HelperBall(100)
            ball.tier = tier
            assert approx(config.ball_base_damage(n) * ball.damage_mult, 50.0 * n * tier)
    # The scene computes exactly this on a "boss" event
    from game.scenes.play import PlayScene
    import inspect
    src = inspect.getsource(PlayScene._ball_hit_boss)
    assert "ball_base_damage" in src and "damage_mult" in src


TESTS = [test_config_formulas, test_new_ball_is_tier_one, test_tier_rises_on_each_paddle_bounce,
         test_tier_unchanged_by_walls_ceiling_and_boss, test_balls_have_independent_tiers, test_damage_on_boss_n]


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
