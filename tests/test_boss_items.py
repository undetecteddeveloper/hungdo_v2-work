"""Boss item tests (plain asserts, no pytest).

Run from the repo root:   python -m tests.test_boss_items
or from anywhere:      python tests/test_boss_items.py
"""
import contextlib
import functools
import logging
import math
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg  # noqa: E402

from game import config  # noqa: E402
from game.entities import boss_items as bi  # noqa: E402
from game.entities.boss_items import (Beam, EnergyItem, HelperBall, Projectile,  # noqa: E402
                                      ball_catch_rect, launch_velocity)
from game.entities.items import catch_y, step_fall  # noqa: E402

DT = config.PHYSICS_DT
WIDTHS = (540, 960, 1960)
SPEED = lambda: config.BOSS_BALL_SPEED          # noqa: E731  (read at use time)


#Helpers
def approx(a, b, eps=1e-6):
    return abs(a - b) <= eps


@contextlib.contextmanager
def width(w: int):
    base = config.LOGICAL_W
    config.set_logical_width(w)
    try:
        yield w
    finally:
        config.set_logical_width(base)


def at_widths(test):
    """Run a test at every canvas width; the width is restored even when it fails."""
    @functools.wraps(test)
    def wrapper():
        for w in WIDTHS:
            with width(w):
                try:
                    test()
                except AssertionError as e:
                    raise AssertionError(f"[width {w}] {e}") from e
    return wrapper


def make_paddle(cx: float = None, full: bool = False) -> pg.Rect:
    """Paddle rect like Player.rect (a full-width 'floor' when full=True)."""
    h = config.PLAYER_H
    top = config.PLAYER_Y - h // 2
    if full:
        return pg.Rect(0, top, config.LOGICAL_W, h)
    w = round(config.player_w())
    if cx is None:
        cx = config.LOGICAL_W / 2
    return pg.Rect(round(cx - w / 2), top, w, h)


def make_boss() -> pg.Rect:
    return pg.Rect(config.LOGICAL_W // 2 - 80, 175, 160, 150)


def flying_ball(x, y, vx, vy) -> HelperBall:
    ball = HelperBall(x, y)
    ball.state = "flying"
    ball.vel.update(vx, vy)
    return ball


def speed_of(ball) -> float:
    return math.hypot(ball.vel.x, ball.vel.y)


def run_ball(ball, steps, dt=DT, paddle=None, boss=None, time_scale=1.0, magnet_x=None, stop=()):
    """Update up to `steps` times; returns the flat list of all events.

    Stops early when the ball dies or (right after the step that produced) any event listed in `stop`.
    """
    events = []
    for _ in range(steps):
        ev = ball.update(dt, time_scale, magnet_x, paddle, boss)
        assert isinstance(ev, tuple), ev
        events.extend(ev)
        if not ball.alive or any(e in stop for e in ev):
            break
    return events


#Projectile
def test_projectile_basics():
    p = Projectile(100, 50, 120, 240)
    assert p.radius == 13.0 and p.shape == "orb" and p.alive and p.age == 0
    assert p.color == config.PALETTE["red"]
    assert approx(p.hit_radius, 13.0 * 0.8)
    for _ in range(120):
        p.update(DT)
    assert approx(p.pos.x, 220, 1e-6) and approx(p.pos.y, 290, 1e-6)      # straight line, no gravity
    assert (p.vel.x, p.vel.y) == (120, 240) and approx(p.age, 1.0, 1e-6)
    # Slow power-up halves the distance and the age
    q = Projectile(100, 50, 0, 200)
    q.update(0.5, 0.5)
    assert approx(q.pos.y, 100) and approx(q.age, 0.25)
    # No wall bounce: flies on through the side wall until it is dropped
    w = Projectile(20, 100, -300, 0)
    for _ in range(240):
        w.update(DT)
    assert not w.alive and w.vel.x == -300
    # Colours: palette key, RGB tuple, unknown key falls back to red, unknown shape to orb
    assert Projectile(0, 0, 0, 0, color="magenta").color == config.PALETTE["magenta"]
    assert Projectile(0, 0, 0, 0, color=(10, 20, 300)).color == (10, 20, 255)
    logging.disable(logging.WARNING)            # the fallbacks log a warning on purpose
    try:
        assert Projectile(0, 0, 0, 0, color="nope").color == config.PALETTE["red"]
        assert Projectile(0, 0, 0, 0, shape="nope").shape == "orb"
    finally:
        logging.disable(logging.NOTSET)
    for shape in bi.SHAPES:
        assert Projectile(0, 0, 0, 0, shape=shape).shape == shape


@at_widths
def test_projectile_offscreen():
    W, H = config.LOGICAL_W, config.LOGICAL_H
    r = 13.0
    m = r * 3

    def alive_at(x, y, vx=0.0, vy=0.0):
        p = Projectile(x, y, vx, vy, radius=r)
        p.update(0.0)
        return p.alive

    assert alive_at(-m + 0.5, 100) and not alive_at(-m - 0.5, 100)
    assert alive_at(W + m - 0.5, 100) and not alive_at(W + m + 0.5, 100)
    assert alive_at(100, H + m - 0.5) and not alive_at(100, H + m + 0.5)
    # Above the top edge it only dies when it is flying away from the screen
    assert alive_at(100, -m - 5, 0, 200) and not alive_at(100, -m - 5, 0, -200)
    # A shot fired down leaves through the bottom in bounded time
    p = Projectile(W / 2, 250, 0, 400)
    t = 0.0
    while p.alive and t < 5:
        p.update(DT)
        t += DT
    assert not p.alive and approx(t, (H + m - 250) / 400, 0.02)
    p.update(1.0)                       # dead shots stay dead and still
    assert not p.alive


def test_projectile_hits():
    rect = pg.Rect(100, 100, 80, 40)            # x 100..180, y 100..140
    p = Projectile(0, 0, 0, 0, radius=10)       # hit radius 8
    assert approx(p.hit_radius, 8.0)

    def at(x, y):
        p.pos.update(x, y)
        return p.hits(rect)

    # Each side: touching counts, a hair further does not
    assert at(92, 120) and not at(91.99, 120)
    assert at(188, 120) and not at(188.01, 120)
    assert at(140, 92) and not at(140, 91.99)
    assert at(140, 148) and not at(140, 148.01)
    # Corner: the bounding box overlaps but the circle does not (distance 8.49 > 8) ...
    assert not at(100 - 6, 100 - 6) and not at(180 + 6, 140 + 6)
    # ... and just inside the corner arc it does (distance 7.92 < 8)
    assert at(100 - 5.6, 100 - 5.6) and at(180 + 5.6, 140 + 5.6)
    assert at(100 - 5.6, 140 + 5.6) and at(180 + 5.6, 100 - 5.6)
    # Inside, on an edge, far away
    assert at(140, 120) and at(100, 100) and not at(400, 400) and not at(140, 0)
    # A rect fully inside the circle's reach
    p.radius = 100.0
    assert at(140, 120)
    # rect property: a square of the hit radius around the centre
    p.radius = 10.0
    p.pos.update(50.4, 60.6)
    r = p.rect
    assert r.size == (16, 16) and abs(r.centerx - 50.4) <= 1 and abs(r.centery - 60.6) <= 1


#EnergyItem
@at_widths
def test_energy_fall():
    W = config.LOGICAL_W
    e = EnergyItem(W / 2)
    assert e.kind == "energy" and e.radius == 15 and e.alive and not e.fell and not e.magnetized
    assert e.pos.y == -e.radius and e.pos.x == W / 2                    # just above the top edge
    assert EnergyItem(100, 222).pos.y == 222
    g, term = config.GRAVITY * 0.8, config.BOSS_HELPER_TERMINAL
    x, y, vx, vy = e.pos.x, e.pos.y, e.vel.x, e.vel.y
    for i in range(400):
        if not e.alive:
            break
        e.update(DT)
        x, y, vx, vy = step_fall(x, y, vx, vy, DT, g, term, 15)
        assert approx(e.pos.y, y, 1e-9) and approx(e.vel.y, vy, 1e-9), i
        assert e.vel.y <= term + 1e-9
    # Reaches the terminal speed, then leaves through the bottom: fell, no longer alive
    e2 = EnergyItem(W / 2)
    top_speed = 0.0
    for _ in range(1000):
        e2.update(DT)
        top_speed = max(top_speed, e2.vel.y)
        if not e2.alive:
            break
    assert approx(top_speed, term) and e2.fell and not e2.alive
    e2.update(DT)
    assert e2.fell
    # Slow time: half the speed of the clock -> clearly less distance
    a, b = EnergyItem(100, 0), EnergyItem(100, 0)
    for _ in range(60):
        a.update(DT, 1.0)
        b.update(DT, 0.5)
    assert b.pos.y < a.pos.y * 0.65
    # A long frame equals the same time in fixed steps (sub-stepping)
    big, small = EnergyItem(100, 0), EnergyItem(100, 0)
    for _ in range(10):
        big.update(1 / 20)
        for _ in range(6):
            small.update(DT)
    assert approx(big.pos.y, small.pos.y, 1e-6) and approx(big.vel.y, small.vel.y, 1e-6)
    # Hitbox is generous and centred
    e3 = EnergyItem(200, 300)
    assert e3.rect.collidepoint(200, 300) and e3.rect.w >= 2 * 15


@at_widths
def test_energy_magnet():
    W = config.LOGICAL_W
    x0 = W / 2 - 100
    mx = W / 2 + 50
    e = EnergyItem(x0, config.PLAYER_Y - 300)
    max_jump = 0.0
    for _ in range(60):
        before = e.pos.x
        e.update(DT, 1.0, mx)
        max_jump = max(max_jump, abs(e.pos.x - before))
    assert e.pos.x > x0 + 5 and e.vel.x > 0 and e.magnetized
    assert max_jump < 10                        # smooth bend, no snapping
    # An item that would miss by 150 px lands on the paddle with the magnet on
    e = EnergyItem(W / 2 - 150)
    target = catch_y(e.radius)
    for _ in range(2000):
        if e.pos.y >= target:
            break
        e.update(DT, 1.0, W / 2)
    assert abs(e.pos.x - W / 2) < config.player_w() / 2, e.pos.x
    # Outside the magnet radius: nothing happens
    far = EnergyItem(W / 2 - config.magnet_radius() - 60, config.PLAYER_Y - 100)
    far.update(DT, 1.0, W / 2)
    assert far.vel.x == 0 and not far.magnetized
    # Without the magnet there is no drift, and leftover sideways speed fades away
    plain = EnergyItem(200, 100)
    for _ in range(60):
        plain.update(DT)
    assert plain.pos.x == 200
    e.alive = True
    e.vel.x = 200.0
    e.pos.update(W / 2, 100)
    for _ in range(240):
        e.update(DT)
    assert abs(e.vel.x) < 1.0
    # Side walls keep it on the screen
    wall = EnergyItem(config.LOGICAL_W - 5, 100)
    wall.vel.x = 400.0
    for _ in range(20):
        wall.update(DT)
        assert wall.radius <= wall.pos.x <= config.LOGICAL_W - wall.radius


#HelperBall
def test_launch_velocity():
    for w in WIDTHS:
        with width(w):
            p = make_paddle()
            sp = SPEED()
            cases = {-1.0: -config.BOSS_BALL_MAX_ANGLE, 0.0: 0.0, 1.0: config.BOSS_BALL_MAX_ANGLE,
                     -0.5: -config.BOSS_BALL_MAX_ANGLE / 2, 0.25: config.BOSS_BALL_MAX_ANGLE / 4}
            for off, deg in cases.items():
                vx, vy = launch_velocity(p.centerx + off * p.w / 2, p)
                assert approx(vx, sp * math.sin(math.radians(deg)), 1e-6), (off, vx)
                assert approx(vy, -sp * math.cos(math.radians(deg)), 1e-6), (off, vy)
                assert approx(math.hypot(vx, vy), sp, 1e-6)
                assert -vy >= config.BOSS_BALL_MIN_VY * sp        # always clearly upward
            # Off the paddle the offset clamps to the edge angle; left/right are mirror images
            lx, ly = launch_velocity(p.left - 500, p)
            rx, ry = launch_velocity(p.right + 500, p)
            assert approx(lx, -rx) and approx(ly, ry) and lx < 0 < rx
            assert launch_velocity(p.centerx, p)[0] == 0.0
            # Degenerate paddle does not divide by zero
            assert launch_velocity(10, pg.Rect(10, 700, 0, 22))[0] == 0.0
            # Catch rect: paddle widened by the ball radius, reaching up one radius
            c = ball_catch_rect(p)
            assert c.left == p.left - config.BOSS_BALL_RADIUS and c.top == p.top - config.BOSS_BALL_RADIUS
            assert c.w == p.w + 2 * config.BOSS_BALL_RADIUS and c.bottom == p.bottom


@at_widths
def test_ball_catch_angles():
    W = config.LOGICAL_W
    paddle = make_paddle(W / 2)
    sp = SPEED()
    for off in (-1.0, -0.6, 0.0, 0.35, 1.0):
        x = paddle.centerx + off * paddle.w / 2
        ball = HelperBall(x, paddle.top - 60)
        assert ball.state == "falling" and ball.alive and not ball.fell
        events = run_ball(ball, 600, paddle=paddle, stop=("caught",))
        assert events == ["caught"], (off, events)
        assert ball.state == "flying" and not ball.magnetized
        a = math.radians(off * config.BOSS_BALL_MAX_ANGLE)
        assert approx(ball.vel.x, sp * math.sin(a), 1e-6) and approx(ball.vel.y, -sp * math.cos(a), 1e-6)
        assert approx(speed_of(ball), sp, 1e-6)
        assert ball.pos.y <= paddle.top - ball.radius + 1e-9
        assert ball.vel.y < 0
    # An exactly left / middle / right catch leaves the paddle leaning left / straight / right
    vl = HelperBall(paddle.left, paddle.top - 30)
    vm = HelperBall(paddle.centerx, paddle.top - 30)
    vr = HelperBall(paddle.right, paddle.top - 30)
    for b in (vl, vm, vr):
        run_ball(b, 600, paddle=paddle, stop=("caught",))
    assert vl.vel.x < 0 and vm.vel.x == 0 and vr.vel.x > 0
    # "caught" appears exactly once: later steps are about flying, not catching
    ball = HelperBall(paddle.centerx, paddle.top - 5)
    ev1 = ball.update(DT, 1.0, None, paddle, None)
    assert ev1 == ("caught",)
    ev2 = ball.update(DT, 1.0, None, paddle, None)
    assert "caught" not in ev2 and ball.pos.y < paddle.top - ball.radius + 1e-9
    # No events at all while the ball is just falling, and the constant () is returned
    ball = HelperBall(paddle.centerx, 100)
    assert ball.update(DT, 1.0, None, paddle, None) == ()
    # Touching the paddle rect counts (colliderect)
    ball = HelperBall(paddle.centerx, paddle.top - ball.radius + 1)
    assert "caught" in ball.update(DT, 1.0, None, paddle, None)


@at_widths
def test_ball_flight_1000():
    W, H = config.LOGICAL_W, config.LOGICAL_H
    floor = make_paddle(full=True)
    boss = make_boss()
    sp = SPEED()
    seen = set()
    for use_boss in (False, True):
        ball = flying_ball(W * 0.1, floor.top - 11, *launch_velocity(W * 0.1, floor))
        for i in range(1000):
            ev = ball.update(DT, 1.0, None, floor, boss if use_boss else None)
            seen.update(ev)
            assert approx(speed_of(ball), sp, 1e-6), (i, speed_of(ball))
            r = ball.radius
            assert r - 1e-9 <= ball.pos.x <= W - r + 1e-9 and ball.pos.y >= r - 1e-9
            assert ball.alive and ball.state == "flying" and "lost" not in ev
    assert {"wall", "ceiling", "paddle"} <= seen, seen
    # Flying ignores the time scale and the magnet
    a = flying_ball(W * 0.3, 500, 300, -400)
    b = flying_ball(W * 0.3, 500, 300, -400)
    for _ in range(500):
        a.update(DT, 1.0, None, floor, None)
        b.update(DT, 0.25, W / 2, floor, None)
    assert approx(a.pos.x, b.pos.x) and approx(a.pos.y, b.pos.y) and not b.magnetized
    # Long run in every direction: never leaves the playfield, never loses speed
    rng = random.Random(5)
    for _ in range(12):
        ang = rng.uniform(0, math.tau)
        ball = flying_ball(rng.uniform(50, W - 50), rng.uniform(300, 600), sp * math.cos(ang), sp * math.sin(ang))
        for _ in range(2500):
            ball.update(DT, 1.0, None, floor, boss)
            assert approx(speed_of(ball), sp, 1e-6) and ball.alive
            assert ball.radius - 1e-9 <= ball.pos.x <= W - ball.radius + 1e-9
            assert ball.pos.y <= floor.top + 1e-9 and ball.pos.y >= ball.radius - 1e-9
    assert H > 0


@at_widths
def test_ball_walls_ceiling():
    W = config.LOGICAL_W
    sp = SPEED()
    r = config.BOSS_BALL_RADIUS
    # Left wall
    ball = flying_ball(r + 3, 400, -sp * 0.8, -sp * 0.6)
    events = run_ball(ball, 30)
    assert events == ["wall"], events
    assert ball.vel.x > 0 and ball.vel.y < 0 and ball.pos.x >= r and approx(speed_of(ball), sp)
    # Right wall
    ball = flying_ball(W - r - 3, 400, sp * 0.8, -sp * 0.6)
    events = run_ball(ball, 30)
    assert events == ["wall"] and ball.vel.x < 0 and ball.pos.x <= W - r
    # Ceiling
    ball = flying_ball(W / 2, r + 3, sp * 0.6, -sp * 0.8)
    events = run_ball(ball, 30)
    assert events == ["ceiling"] and ball.vel.y > 0 and ball.pos.y >= r and approx(speed_of(ball), sp)
    # Corner: both reflect, each reported once
    ball = flying_ball(r + 2, r + 2, -sp * 0.6, -sp * 0.8)
    events = run_ball(ball, 30)
    assert sorted(events) == ["ceiling", "wall"] and ball.vel.x > 0 and ball.vel.y > 0
    # A shallow angle is straightened after the bounce: |vy| >= MIN_VY * speed, speed unchanged
    vy = -sp * 0.14
    ball = flying_ball(W - r - 2, 400, math.sqrt(sp * sp - vy * vy), vy)
    events = run_ball(ball, 30)
    assert events == ["wall"]
    assert abs(ball.vel.y) >= config.BOSS_BALL_MIN_VY * sp - 1e-9 and ball.vel.y < 0 and ball.vel.x < 0
    assert approx(speed_of(ball), sp, 1e-6)
    # Moving away from a wall while touching it (e.g. after a resize) is clamped without a bounce event
    ball = flying_ball(W + 40, 400, -sp * 0.6, -sp * 0.8)
    ev = ball.update(DT, 1.0, None, None, None)
    assert ev == () and ball.pos.x <= W - r + 1e-9 and ball.vel.x < 0


@at_widths
def test_ball_not_trapped():
    """A ball that starts perfectly horizontal can never rally sideways forever."""
    W = config.LOGICAL_W
    floor = make_paddle(full=True)
    sp = SPEED()
    ball = flying_ball(W / 2, 400, sp, 0.0)
    min_vy = config.BOSS_BALL_MIN_VY * sp
    reflected = False
    seen = set()
    for _ in range(int(60 * config.PHYSICS_HZ)):
        ev = ball.update(DT, 1.0, None, floor, None)
        seen.update(ev)
        if ev:
            reflected = True
        if reflected:
            assert abs(ball.vel.y) >= min_vy - 1e-6
    assert {"wall", "paddle", "ceiling"} <= seen, seen
    # Near-horizontal launches from random heights always come back to the paddle within 20 s
    rng = random.Random(9)
    for _ in range(20):
        ang = math.radians(rng.choice((-1, 1)) * rng.uniform(0, 4)) + rng.choice((0.0, math.pi))
        ball = flying_ball(rng.uniform(30, W - 30), rng.uniform(200, 600), sp * math.cos(ang), sp * math.sin(ang))
        got = run_ball(ball, 20 * config.PHYSICS_HZ, paddle=floor)
        assert "paddle" in got or "ceiling" in got, got


@at_widths
def test_ball_paddle_bounce():
    W = config.LOGICAL_W
    paddle = make_paddle(W / 2)
    sp = SPEED()
    r = config.BOSS_BALL_RADIUS
    for off in (-0.8, 0.0, 0.8):
        x = paddle.centerx + off * paddle.w / 2
        ball = flying_ball(x, paddle.top - 50, 0.0, sp)
        events = run_ball(ball, 120, paddle=paddle, stop=("paddle",))
        assert events == ["paddle"], events
        a = math.radians(off * config.BOSS_BALL_MAX_ANGLE)
        assert approx(ball.vel.x, sp * math.sin(a), 1e-6) and ball.vel.y < 0
        assert approx(speed_of(ball), sp, 1e-6)
    # Right after the bounce the ball sits on top of the paddle and is not stuck in it
    ball = flying_ball(paddle.centerx, paddle.top - 3, 0.0, sp)
    ev = ball.update(DT, 1.0, None, paddle, None)
    assert ev == ("paddle",) and approx(ball.pos.y, paddle.top - r) and not paddle.colliderect(ball.rect)
    assert ball.update(DT, 1.0, None, paddle, None) == ()
    # Going UP through the paddle does nothing
    ball = flying_ball(paddle.centerx, paddle.centery, 0.0, -sp)
    assert ball.update(DT, 1.0, None, paddle, None) == ()
    # A ball already below the paddle's middle line is missed (no bounce) and ends up lost
    ball = flying_ball(paddle.centerx, paddle.centery + 4, 0.0, sp)
    events = run_ball(ball, 600, paddle=paddle)
    assert events == ["lost"], events
    # Ball skimming the paddle edge with its side still bounces (full edge angle)
    ball = flying_ball(paddle.right + r - 2, paddle.top - 8, 0.0, sp)
    events = run_ball(ball, 60, paddle=paddle, stop=("paddle",))
    assert events == ["paddle"] and ball.vel.x > 0


@at_widths
def test_ball_boss():
    W = config.LOGICAL_W
    boss = make_boss()
    sp = SPEED()
    r = config.BOSS_BALL_RADIUS

    # From below, straight up: exactly one "boss", bounces down, pushed out of the boss
    ball = flying_ball(boss.centerx, boss.bottom + 80, 0.0, -sp)
    events = []
    first_seen = None
    for i in range(60):
        ev = ball.update(DT, 1.0, None, None, boss)
        events += ev
        if "boss" in ev and first_seen is None:
            first_seen = i
            assert ball.vel.y > 0 and not boss.colliderect(ball.rect)
            assert approx(ball.pos.y, boss.bottom + r)
            assert approx(ball.hit_cd, bi.BALL_HIT_CD, 1e-9)
    assert first_seen is not None and events == ["boss"], events
    assert approx(speed_of(ball), sp, 1e-6)
    # Cooldown: inside the boss with hit_cd running, no event; once it ends, the next contact counts
    ball = flying_ball(boss.centerx, boss.centery, sp * 0.5, -sp * math.sqrt(0.75))
    ball.hit_cd = 0.05
    assert ball.update(0.02, 1.0, None, None, boss) == () and ball.hit_cd > 0.02
    ev = ball.update(0.05, 1.0, None, None, boss)
    assert ev == ("boss",), ev
    # Side hits flip vx, top hits flip vy
    ball = flying_ball(boss.left - 30, boss.centery, sp * 0.8, -sp * 0.6)
    events = run_ball(ball, 60, boss=boss, stop=("boss", "wall"))
    assert events == ["boss"] and ball.vel.x < 0 and ball.vel.y < 0 and approx(ball.pos.x, boss.left - r)
    ball = flying_ball(boss.right + 30, boss.centery, -sp * 0.8, -sp * 0.6)
    events = run_ball(ball, 60, boss=boss, stop=("boss", "wall"))
    assert events == ["boss"] and ball.vel.x > 0 and approx(ball.pos.x, boss.right + r)
    ball = flying_ball(boss.centerx, boss.top - 40, 0.0, sp)
    events = run_ball(ball, 60, boss=boss, stop=("boss", "wall"))
    assert events == ["boss"] and ball.vel.y < 0 and approx(ball.pos.y, boss.top - r)
    # Boss not hurtable (rect None): the ball flies straight through
    ball = flying_ball(boss.centerx, boss.bottom + 80, 0.0, -sp)
    events = run_ball(ball, 60, boss=None)
    assert events == [] and ball.pos.y < boss.top
    # A falling (not yet caught) ball is not part of the fight
    ball = HelperBall(boss.centerx, boss.top - 40)
    events = run_ball(ball, 120, boss=boss, paddle=make_paddle(40))
    assert events == [] and ball.state == "falling" and ball.pos.y > boss.bottom
    # Rally under a wide, moving boss: every contact is a single event and the speed never changes
    wide = pg.Rect(round(W * 0.1), 175, round(W * 0.8), 150)
    ball = flying_ball(W / 2, 600, sp * 0.5, -sp * math.sqrt(0.75))
    floor = make_paddle(full=True)
    hits = 0
    for i in range(3000):
        b = wide.move(int(60 * math.sin(i / 90)), 0)
        ev = ball.update(DT, 1.0, None, floor, b)
        hits += ev.count("boss")
        assert ev.count("boss") <= 1
        assert approx(speed_of(ball), sp, 1e-6)
    assert hits >= 10, hits


@at_widths
def test_ball_lost_and_fell():
    W, H = config.LOGICAL_W, config.LOGICAL_H
    sp = SPEED()
    paddle = make_paddle(40)                    # far to the left: the ball goes past it
    # A flying ball that gets past the paddle: one "lost", then dead
    ball = flying_ball(W - 100, H - 80, sp * 0.3, sp * 0.95)
    events = run_ball(ball, 600, paddle=paddle)
    assert events == ["lost"], events
    assert not ball.alive and ball.fell
    assert ball.update(DT, 1.0, None, paddle, None) == () and ball.pos.y > H
    # An uncaught falling ball just drops out: fell, dead, NO event
    ball = HelperBall(W - 100)
    events = run_ball(ball, 3000, paddle=paddle)
    assert events == [] and ball.fell and not ball.alive
    assert ball.update(DT, 1.0, None, paddle, None) == ()
    # Same without any paddle given
    ball = HelperBall(W / 2)
    assert run_ball(ball, 3000) == [] and ball.fell and not ball.alive
    # A caught ball that is then missed pays once
    paddle = make_paddle(W / 2)
    ball = HelperBall(paddle.centerx, paddle.top - 20)
    events = run_ball(ball, 120, paddle=paddle, stop=("caught",))
    assert events == ["caught"]
    ball.vel.update(0.0, sp)                    # force it back down, paddle moved away
    ball.pos.update(W - 60 if paddle.centerx < W / 2 else 60, paddle.top - 100)
    events = run_ball(ball, 2000, paddle=paddle)
    assert events == ["lost"], events


@at_widths
def test_ball_large_dt():
    W = config.LOGICAL_W
    sp = SPEED()
    paddle = make_paddle(W / 2)
    boss = make_boss()
    # Sub-stepping: one 1/20 s frame equals six fixed steps (positions and events)
    rng = random.Random(3)
    for _ in range(8):
        ang = rng.uniform(-1.2, 1.2)
        x0, y0 = rng.uniform(80, W - 80), rng.uniform(380, 650)
        a = flying_ball(x0, y0, sp * math.sin(ang), -sp * math.cos(ang))
        b = flying_ball(x0, y0, sp * math.sin(ang), -sp * math.cos(ang))
        fa, fb = [], []
        for _ in range(40):
            fa += a.update(1 / 20, 1.0, None, paddle, boss)
            for _ in range(6):
                fb += b.update(DT, 1.0, None, paddle, boss)
        assert fa == fb, (fa, fb)
        assert approx(a.pos.x, b.pos.x, 1e-3) and approx(a.pos.y, b.pos.y, 1e-3)
    # Falling ball at 1/20: still caught by the paddle, no tunnelling
    for off in (-0.9, 0.0, 0.9):
        ball = HelperBall(paddle.centerx + off * paddle.w / 2, 600)
        events = run_ball(ball, 200, dt=1 / 20, paddle=paddle, stop=("caught",))
        assert events == ["caught"], events
    # Flying ball at 1/20 never gets below the paddle line when it is over the paddle
    for dt in (1 / 20, 1 / 10, 0.25):
        ball = flying_ball(paddle.centerx + 10, paddle.top - 70, 0.0, sp)
        events = run_ball(ball, 10, dt=dt, paddle=paddle, stop=("paddle", "lost"))
        assert events == ["paddle"] and ball.vel.y < 0 and ball.pos.y <= paddle.top, (dt, events)
    # Flying ball at big dt does not pass through the boss
    for dt in (1 / 20, 1 / 10, 0.25):
        ball = flying_ball(boss.centerx, boss.bottom + 30, 0.0, -sp)
        events = ball.update(dt, 1.0, None, None, boss)
        assert events == ("boss",) and ball.vel.y > 0, (dt, events)
    # A frame longer than MAX_DT is cut instead of freezing the game
    ball = flying_ball(W / 2, 600, 0.0, -sp)
    ball.update(10.0, 1.0, None, None, None)
    assert approx(ball.pos.y, 600 - sp * bi.MAX_DT, 1e-6)
    assert ball.update(0.0) == () and ball.update(-1.0) == ()


@at_widths
def test_ball_falling_physics():
    W = config.LOGICAL_W
    # Falls like the energy cell: same gravity, terminal and magnet; time scale applies
    ball = HelperBall(W / 2)
    assert ball.radius == config.BOSS_BALL_RADIUS and ball.pos.y == -ball.radius
    assert ball.state == "falling" and ball.hit_cd == 0.0 and not ball.magnetized
    e = EnergyItem(W / 2, ball.pos.y)
    for _ in range(100):
        ball.update(DT)
        e.update(DT)
    assert approx(ball.pos.y, e.pos.y, 1e-9)
    slow = HelperBall(W / 2, 0)
    norm = HelperBall(W / 2, 0)
    for _ in range(60):
        slow.update(DT, 0.5)
        norm.update(DT, 1.0)
    assert slow.pos.y < norm.pos.y * 0.65
    # Magnet bends a falling ball toward the paddle
    ball = HelperBall(W / 2 - 100, config.PLAYER_Y - 300)
    for _ in range(60):
        ball.update(DT, 1.0, W / 2 + 40)
    assert ball.magnetized and ball.vel.x > 0 and ball.pos.x > W / 2 - 100
    # Caught under magnet: lands over the paddle
    paddle = make_paddle(W / 2)
    ball = HelperBall(W / 2 - 140)
    events = run_ball(ball, 3000, paddle=paddle, magnet_x=W / 2, stop=("caught",))
    assert events == ["caught"] and abs(ball.pos.x - W / 2) < paddle.w / 2 + ball.radius
    # Rect is the ball's bounding square around its centre
    ball = HelperBall(123, 456)
    assert ball.rect.center == (123, 456) and ball.rect.w == 2 * ball.radius


def test_beam():
    boss = pg.Rect(300, 175, 160, 150)          # x 300..460, bottom 325
    half = config.BOSS_BEAM_WIDTH / 2
    b = Beam(380, 700, boss)
    assert b.hit and b.y_to == 325 and b.y_from == 700 and b.x == 380
    assert b.width == config.BOSS_BEAM_WIDTH and b.life == config.BOSS_BEAM_LIFE
    assert b.alive and b.age == 0 and b.progress == 0
    # Edges: width/2 of slack on each side, inclusive
    assert Beam(boss.left - half, 700, boss).hit
    assert not Beam(boss.left - half - 0.01, 700, boss).hit
    assert Beam(boss.right + half, 700, boss).hit
    assert not Beam(boss.right + half + 0.01, 700, boss).hit
    assert Beam(boss.left, 700, boss).hit and Beam(boss.right, 700, boss).hit
    # Miss: flies off the top of the screen
    miss = Beam(50, 700, boss)
    assert not miss.hit and miss.y_to == 0
    none = Beam(380, 700, None)
    assert not none.hit and none.y_to == 0
    # Life: ages out, progress rises to 1 and stays there
    b = Beam(380, 700, boss)
    last = 0.0
    steps = 0
    while b.alive:
        b.update(DT)
        assert b.progress >= last and 0.0 <= b.progress <= 1.0
        last = b.progress
        steps += 1
        assert steps < 1000
    assert approx(steps * DT, config.BOSS_BEAM_LIFE, DT + 1e-9) and b.progress == 1.0
    b.update(1.0)
    assert not b.alive and b.progress == 1.0
    # Width follows the canvas-independent config at creation time
    for w in WIDTHS:
        with width(w):
            assert Beam(100, 700, pg.Rect(50, 100, 200, 100)).width == config.BOSS_BEAM_WIDTH


def test_resize():
    base = config.LOGICAL_W
    try:
        config.set_logical_width(540)
        objs = [Projectile(270, 100, 0, 100), EnergyItem(270, 100), HelperBall(270, 100), Beam(270, 700, None)]
        for o in objs:
            if hasattr(o, "trail"):
                o.trail.append((270, 90))
        config.set_logical_width(1080)
        for o in objs:
            o.on_resize(540)
            x = o.pos.x if hasattr(o, "pos") else o.x
            assert approx(x, 540), (type(o).__name__, x)
        assert approx(objs[1].trail[0][0], 540)
    finally:
        config.set_logical_width(base)


#Drawing
def bright(color) -> int:
    return color[0] + color[1] + color[2]


def painted(surf, cx, cy, rad, bg) -> bool:
    """True when something other than the background colour is within `rad` of (cx, cy)."""
    rect = pg.Rect(int(cx - rad), int(cy - rad), int(rad * 2), int(rad * 2)).clip(surf.get_rect())
    if rect.w == 0 or rect.h == 0:
        return False
    avg = pg.transform.average_color(surf, rect)
    return any(abs(avg[i] - bg[i]) > 2 for i in range(3))


def test_draw_smoke():
    """Every draw runs at every width, with and without assets, on and off screen, alive or dead."""
    pg.display.init()
    pg.font.init()
    pg.display.set_mode((config.LOGICAL_W, config.LOGICAL_H))
    from game.assets import Assets
    assets = Assets()
    bg = (10, 8, 30)
    for w in WIDTHS:
        with width(w):
            W, H = config.LOGICAL_W, config.LOGICAL_H
            surf = pg.Surface((W, H))
            objs = []
            i = 0
            for shape in bi.SHAPES:
                for color in ("red", "orange", "magenta", (200, 30, 90)):
                    objs.append(Projectile(40 + 38 * i, 80 + 20 * (i % 5), 40 * (i % 3 - 1), 220, 13.0 + i % 3, shape, color))
                    i += 1
            objs += [Projectile(-5, 10, 0, 0), Projectile(W + 5, H + 5, 0, 0), Projectile(W / 2, 100, 0, 0, shape="bolt")]
            objs += [EnergyItem(W * 0.2, 300), EnergyItem(W * 0.3, 500), EnergyItem(W * 0.4, -10)]
            fall = HelperBall(W * 0.5, 300)
            fly = flying_ball(W * 0.6, 500, 300, -500)
            near = HelperBall(W * 0.7, 400)
            near.pos.x = W * 0.7
            objs += [fall, fly, near]
            floor = make_paddle(full=True)
            for frame in range(60):
                for o in objs:
                    if isinstance(o, HelperBall):
                        o.update(DT, 1.0, W / 2 if frame > 20 else None, floor, make_boss())
                    elif isinstance(o, EnergyItem):
                        o.update(DT, 1.0, W / 2 if frame > 20 else None)
                    else:
                        o.update(DT)
                    o.draw(surf, frame * DT, assets if frame % 2 else None)
            # Dead objects draw nothing
            surf.fill(bg)
            dead = [Projectile(W / 2, 400, 0, 0), EnergyItem(W / 2, 400), HelperBall(W / 2, 400)]
            for d in dead:
                d.alive = False
                d.draw(surf, 0.3, assets)
            assert not painted(surf, W / 2, 400, 60, bg)
            # Alive ones do paint, in the right place
            for o in (Projectile(W / 2, 400, 0, 100), EnergyItem(W / 2, 400), HelperBall(W / 2, 400)):
                surf.fill(bg)
                o.draw(surf, 0.3, assets)
                assert painted(surf, W / 2, 400, 24, bg), type(o).__name__
            for shape in bi.SHAPES:
                surf.fill(bg)
                Projectile(W / 2, 400, 50, 150, 13, shape, "red").draw(surf, 0.3)
                assert painted(surf, W / 2, 400, 24, bg), shape


def test_draw_looks_distinct():
    """Hostile shots have a dark core, the ball is white: catch-or-dodge must read at a glance."""
    pg.display.init()
    pg.font.init()
    pg.display.set_mode((config.LOGICAL_W, config.LOGICAL_H))
    W = config.LOGICAL_W
    surf = pg.Surface((W, config.LOGICAL_H))
    bg = (0, 0, 0)
    cx, cy = 200, 300
    # Hostile orb: dark body around a small ember
    surf.fill(bg)
    orb = Projectile(cx, cy, 0, 100, 13.0, "orb", "red")
    orb.draw(surf, 0.5)
    r = orb.radius
    body = surf.get_at((cx + int(r * 0.45), cy))[:3]
    assert bright(body) < 120, body                      # dark core
    # Ball: bright white middle
    surf.fill(bg)
    ball = HelperBall(cx, cy)
    ball.draw(surf, 0.5)
    mid = surf.get_at((cx, cy))[:3]
    assert min(mid) >= 190, mid
    # Energy cell: bright pale bolt on a yellow hexagon (no red)
    surf.fill(bg)
    e = EnergyItem(cx, cy)
    e.draw(surf, 0.5)
    ring = surf.get_at((cx, cy - 14))[:3]
    assert ring[0] > 150 and ring[1] > 120 and ring[2] < 200, ring
    # Hostile colours are in the red/orange/magenta family: red channel dominates the others' blue/green mix
    for color in ("red", "orange", "magenta"):
        p = Projectile(cx, cy, 0, 100, 13.0, "orb", color)
        assert p.color[0] >= 200 and not (p.color[1] > 200 and p.color[2] > 200)


def test_draw_cache_bounded():
    """Pulsing glows are quantised: hundreds of frames add only a handful of cache entries."""
    pg.display.init()
    pg.font.init()
    pg.display.set_mode((config.LOGICAL_W, config.LOGICAL_H))
    from game.render import neon
    cache = getattr(neon, "_glows", None)
    surf = pg.Surface(config.LOGICAL_SIZE)
    objs = [Projectile(100 + 40 * i, 100 + 30 * i, 20 * i - 40, 200, 13.0, shape, color)
            for i, (shape, color) in enumerate((s, c) for s in bi.SHAPES for c in ("red", "orange", "magenta"))]
    objs += [EnergyItem(100, 400), HelperBall(200, 400), HelperBall(300, 400)]
    objs[-1].state = "flying"
    objs[-1].vel.update(100, -500)
    # warm the cache over one pulse period first, then measure growth
    for frame in range(400):
        t = frame / 60.0
        for o in objs:
            o.draw(surf, t)
    before = len(cache.data) if cache is not None else 0
    for frame in range(400, 1600):
        t = frame / 60.0
        for o in objs:
            if isinstance(o, (EnergyItem, HelperBall)):
                o.age += 1 / 60
            o.draw(surf, t)
    after = len(cache.data) if cache is not None else 0
    assert after - before <= 6, (before, after)
    assert after < 150, after


TESTS = [
    test_projectile_basics, test_projectile_offscreen, test_projectile_hits,
    test_energy_fall, test_energy_magnet,
    test_launch_velocity, test_ball_catch_angles, test_ball_flight_1000, test_ball_walls_ceiling,
    test_ball_not_trapped, test_ball_paddle_bounce, test_ball_boss, test_ball_lost_and_fell,
    test_ball_large_dt, test_ball_falling_physics,
    test_beam, test_resize,
    test_draw_smoke, test_draw_looks_distinct, test_draw_cache_bounded,
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
