"""Boss drawing + boss sound tests (plain asserts, no pytest).

Boss / Sweep / Beam come from other modules, so they are faked with SimpleNamespace carrying exactly the
fields listed in docs/ARCHITECTURE.md "Boss fights".

Run from the repo root:   python -m tests.test_boss_draw
"""
import math
import os
import random
import sys
import time
import wave
from types import SimpleNamespace as NS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg  # noqa: E402

from game import config  # noqa: E402
from game.assets import Assets  # noqa: E402
from game.render import boss_draw, neon  # noqa: E402
from game.systems.particles import ParticleSystem, prewarm  # noqa: E402

pg.init()
pg.display.set_mode((64, 64))

WIDTHS = (540, 960, 1960)
H = 840
BOSS_Y = config.BOSS_Y
COLORS = (("orange", "yellow"), ("magenta", "cyan"), ("purple", "green"))
SIZES = ((100, 70), (92, 74), (96, 68))                 # inside the contract ranges [60,100] x [50,75]
SOUND_DIR = os.path.join(ROOT, "assets", "sound")
WAVS = {"boss_intro": (1.8, 2.8), "boss_hit": (0.08, 0.35), "beam_charge": (0.3, 0.9),
        "beam_fire": (0.3, 0.7), "boss_defeat": (1.8, 3.0), "warning": (0.5, 1.0)}

_surfs = {}


#Helpers
def surface(w: int) -> pg.Surface:
    """A cleared canvas; the last 4 per width stay valid so a test can compare a few pictures."""
    pool = _surfs.setdefault(w, [[pg.Surface((w, H)) for _ in range(4)], 0])
    pool[1] = (pool[1] + 1) % 4
    s = pool[0][pool[1]]
    s.fill((0, 0, 0))
    return s


def mk_boss(kind: int, w: int = 540, **kw) -> NS:
    hw, hh = SIZES[kind]
    d = dict(kind=kind, number=kind + 1, colors=COLORS[kind], pos=pg.Vector2(w / 2, BOSS_Y), half_w=hw, half_h=hh,
             hp_frac=1.0, phase=1, hit_flash=0.0, charge=0.0, enraged=False, anim_t=1.3, death_t=0.0)
    d.update(kw)
    return NS(**d)


def boss_rect(b: NS) -> pg.Rect:
    return pg.Rect(int(b.pos.x - b.half_w), int(b.pos.y - b.half_h), b.half_w * 2, b.half_h * 2)


def lit(surf: pg.Surface, rect: pg.Rect, thr: int = 12) -> int:
    """Pixels in `rect` that are not (near) black."""
    rect = rect.clip(surf.get_rect())
    if rect.w <= 0 or rect.h <= 0:
        return 0
    sub = surf.subsurface(rect)
    near_black = pg.mask.from_threshold(sub, (0, 0, 0), (thr, thr, thr, 255)).count()
    return rect.w * rect.h - near_black


def bbox_lit(surf: pg.Surface, thr: int = 60):
    """Bounding rect of pixels brighter than thr (any channel), or None."""
    mask = pg.mask.from_threshold(surf, (0, 0, 0), (thr, thr, thr, 255))
    mask.invert()
    rects = mask.get_bounding_rects()
    if not rects:
        return None
    out = rects[0].copy()
    for r in rects[1:]:
        out.union_ip(r)
    return out


def brightness(surf: pg.Surface, rect: pg.Rect) -> float:
    c = pg.transform.average_color(surf.subsurface(rect.clip(surf.get_rect())))
    return float(c[0] + c[1] + c[2])


def crop_bytes(surf: pg.Surface, rect: pg.Rect) -> bytes:
    return pg.image.tobytes(surf.subsurface(rect.clip(surf.get_rect())), "RGB")


def diff_frac(a: bytes, b: bytes) -> float:
    assert len(a) == len(b)
    return sum(1 for x, y in zip(a, b) if abs(x - y) > 8) / len(a)


def render(kind: int, w: int = 540, t: float = 0.0, **kw) -> tuple:
    boss = mk_boss(kind, w, **kw)
    s = surface(w)
    boss_draw.draw_boss(s, boss, t)
    return s, boss


def view_rect(boss: NS) -> pg.Rect:
    return pg.Rect(int(boss.pos.x - 170), int(boss.pos.y - 130), 340, 260)


#Boss
def test_draw_boss_matrix():
    """Every kind x phase x state x canvas width: no error, pixels drawn on the body, nothing far away."""
    states = {"calm": {}, "flash": dict(hit_flash=1.0), "charge": dict(charge=1.0), "enraged": dict(enraged=True),
              "rage+charge": dict(enraged=True, charge=0.6, hit_flash=0.5),
              "dying_a": dict(death_t=0.3), "dying_b": dict(death_t=0.75), "dead": dict(death_t=1.0)}
    for w in WIDTHS:
        for kind in range(3):
            for phase in (1, 2, 3):
                for name, kw in states.items():
                    s, b = render(kind, w, phase=phase, **kw)
                    rect = boss_rect(b)
                    n = lit(s, rect)
                    if name != "dead":
                        assert n > rect.w * rect.h * 0.08, (w, kind, phase, name, n)
                    # Bright pixels (the body, not the faint halo) stay near the hitbox
                    bb = bbox_lit(s, 60)
                    if bb is not None:
                        assert rect.inflate(260, 220).contains(bb), (w, kind, phase, name, bb, rect)


def test_boss_edge_positions():
    """Intro (above the screen) and wall-hugging positions clip quietly."""
    for w in WIDTHS:
        for kind in range(3):
            for pos in ((30, BOSS_Y), (w - 30, BOSS_Y), (w / 2, -120), (w / 2, H + 100)):
                s = surface(w)
                boss_draw.draw_boss(s, mk_boss(kind, w, pos=pg.Vector2(pos)), 0.0)
                boss_draw.draw_boss(s, mk_boss(kind, w, pos=pg.Vector2(pos), death_t=0.5), 0.0)


def test_kinds_look_different():
    shots = []
    for kind in range(3):
        s, b = render(kind)
        shots.append(crop_bytes(s, view_rect(b)))
    for i in range(3):
        for j in range(i + 1, 3):
            f = diff_frac(shots[i], shots[j])
            assert f > 0.12, (i, j, f)
    # Colour identity: orange/yellow is warm, the other two lean blue/violet
    warm = pg.transform.average_color(render(0)[0].subsurface(view_rect(mk_boss(0))))
    assert warm[0] > warm[2] * 1.5, warm
    for kind in (1, 2):
        c = pg.transform.average_color(render(kind)[0].subsurface(view_rect(mk_boss(kind))))
        assert c[2] > c[0] * 0.9, (kind, c)


def test_boss_states_change_the_picture():
    for kind in range(3):
        base_s, b = render(kind)
        base = crop_bytes(base_s, view_rect(b))
        base_light = brightness(base_s, view_rect(b))
        # Phases add decoration
        for phase in (2, 3):
            s, b = render(kind, phase=phase)
            assert diff_frac(base, crop_bytes(s, view_rect(b))) > 0.002, (kind, "phase", phase)
        # Flash lights the body up; charge adds energy rings and glow
        s, b = render(kind, hit_flash=1.0)
        assert brightness(s, view_rect(b)) > base_light * 1.15, (kind, "flash")
        s, b = render(kind, charge=1.0)
        assert brightness(s, view_rect(b)) > base_light * 1.05, (kind, "charge")
        assert diff_frac(base, crop_bytes(s, view_rect(b))) > 0.01, (kind, "charge picture")
        # Enraged turns red: the red share of the colour rises
        s, b = render(kind, enraged=True)
        c0 = pg.transform.average_color(base_s.subsurface(view_rect(b)))
        c1 = pg.transform.average_color(s.subsurface(view_rect(b)))
        assert c1[0] / (sum(c1[:3]) + 1) > c0[0] / (sum(c0[:3]) + 1), (kind, c0, c1)


def test_boss_animates_and_is_deterministic():
    for kind in range(3):
        s, b = render(kind, anim_t=1.0)
        a1 = crop_bytes(s, view_rect(b))
        s, b = render(kind, anim_t=1.0)
        assert crop_bytes(s, view_rect(b)) == a1, "same input must give the same picture"
        s, b = render(kind, anim_t=2.1)
        assert diff_frac(a1, crop_bytes(s, view_rect(b))) > 0.003, (kind, "anim_t has no visible effect")
        # `t` (app time) must not matter: the boss animates from its own anim_t
        s = surface(540)
        boss_draw.draw_boss(s, mk_boss(kind, anim_t=1.0), 99.0)
        assert crop_bytes(s, view_rect(b)) == a1


def test_death_fades_out():
    for kind in range(3):
        levels = []
        for d in (0.0, 0.5, 0.7, 0.85, 1.0):
            s, b = render(kind, death_t=d)
            levels.append(brightness(s, view_rect(b)))
        assert levels[2] > levels[3] > levels[4], (kind, levels)
        assert levels[4] < levels[0] * 0.03, (kind, levels)
        # Cracks appear while the body is still there
        a, b = render(kind, death_t=0.05)
        c, _ = render(kind, death_t=0.5)
        f = diff_frac(crop_bytes(a, view_rect(b)), crop_bytes(c, view_rect(b)))
        assert f > 0.01, (kind, f)


def test_boss_duck_typing():
    """Colours as keys or RGB, missing optional fields, assets passed or not."""
    assets = Assets()
    s = surface(540)
    b = NS(kind=1, pos=pg.Vector2(270, 250), half_w=80, half_h=60)
    boss_draw.draw_boss(s, b, 0.5)
    b.colors = ((255, 140, 36), (255, 222, 60))
    boss_draw.draw_boss(s, b, 0.5, assets)
    b.kind = 5                                           # out of range: wraps instead of crashing
    boss_draw.draw_boss(s, b, 0.5)
    b.phase, b.hit_flash, b.charge, b.death_t = 9, 7.0, -3.0, 2.0   # garbage is clamped
    boss_draw.draw_boss(s, b, 0.5)


def test_glow_cache_stays_small():
    """A long fight (all phases, rage, charges, flashes) must not flood the shared neon cache."""
    for kind in range(3):
        neon.clear_cache()
        s = surface(540)
        for i in range(900):
            boss = mk_boss(kind, anim_t=i * 0.0167, phase=1 + i // 300, enraged=(i // 150) % 2 == 1,
                           charge=(0.0 if i % 120 < 60 else (i % 120 - 60) / 60), hit_flash=max(0.0, 1.0 - (i % 40) / 10))
            boss_draw.draw_boss(s, boss, i * 0.0167)
        n = len(neon._glows.data)
        assert n <= 110, (kind, n)


def test_prewarm_glows():
    for kind in range(3):
        boss = mk_boss(kind)
        steps = sum(1 for _ in boss_draw.prewarm_glows_iter(boss))
        assert steps == 72, steps
        neon.clear_cache()
        boss_draw.prewarm_glows(boss)
        warm = len(neon._glows.data)
        assert warm > 10
        # A warmed boss builds (almost) nothing new while fighting
        s = surface(540)
        for i in range(200):
            boss_draw.draw_boss(s, mk_boss(kind, anim_t=i * 0.0167, phase=1 + i // 70, charge=0.0 if i % 100 < 50 else 1.0), 0)
        assert len(neon._glows.data) - warm <= 8, (kind, warm, len(neon._glows.data))


def test_boss_draw_cost():
    """Mean cost per boss must stay well under the frame budget (target < 1 ms; asserted loosely)."""
    s = surface(540)
    for kind in range(3):
        for label, kw in (("calm", dict(phase=3)), ("rage+charge", dict(phase=3, enraged=True, charge=1.0, hit_flash=0.5))):
            b = mk_boss(kind, **kw)
            for i in range(40):
                b.anim_t = i * 0.0167
                boss_draw.draw_boss(s, b, 0.0)
            n = 300
            t0 = time.perf_counter()
            for i in range(n):
                b.anim_t = 1 + i * 0.0167
                boss_draw.draw_boss(s, b, 0.0)
            ms = (time.perf_counter() - t0) / n * 1000
            print(f"  boss {kind} {label}: {ms:.3f} ms")
            assert ms < 3.0, (kind, label, ms)


#Sweep
def mk_sweep(**kw) -> NS:
    d = dict(x_from=200.0, x_to=200.0, width=110.0, warn_time=1.3, fire_time=0.7, age=0.0, consumed=False,
             phase="warn", zone=(145.0, 255.0), beam_x=200.0, k_warn=0.5, k_fire=0.0)
    d.update(kw)
    return NS(**d)


def sweep_for(w: int, moving: bool) -> dict:
    """A sweep spanning up to 0.55 * W, centred on the playfield."""
    width = 110.0
    if moving:
        span = 0.55 * w - width
        x_from, x_to = w / 2 - span / 2, w / 2 + span / 2
        zone = (x_from - width / 2, x_to + width / 2)
    else:
        x_from = x_to = w / 2
        zone = (x_from - width / 2, x_to + width / 2)
    return dict(x_from=x_from, x_to=x_to, width=width, zone=zone, beam_x=x_from)


def test_draw_sweep():
    bottom = BOSS_Y + 70
    for w in WIDTHS:
        for moving in (False, True):
            geo = sweep_for(w, moving)
            x0, x1 = geo["zone"]
            # Warning: strip below the boss only, inside the zone (plus edge glow and the sign's halo)
            for k in (0.0, 0.3, 0.7, 1.0):
                s = surface(w)
                boss_draw.draw_sweep(s, mk_sweep(phase="warn", k_warn=k, **geo), bottom, 1.7 + k)
                strip = pg.Rect(int(x0), bottom, int(x1 - x0), H - bottom)
                assert lit(s, strip) > strip.w * strip.h * 0.5, (w, moving, k)
                assert lit(s, pg.Rect(0, 0, w, bottom - 1)) == 0, (w, "drew above the boss", k)
                assert lit(s, pg.Rect(0, bottom, max(0, int(x0) - 90), H - bottom)) == 0, (w, moving, k, "left spill")
                assert lit(s, pg.Rect(int(x1) + 90, bottom, max(0, w - int(x1) - 90), H - bottom)) == 0, (w, moving, k, "right spill")
            # Fire: white-hot core at beam_x, red haze fades with k_fire
            for k in (0.0, 0.2, 0.5, 0.95, 1.0):
                bx = geo["x_from"] + (geo["x_to"] - geo["x_from"]) * k
                s = surface(w)
                boss_draw.draw_sweep(s, mk_sweep(phase="fire", k_fire=k, beam_x=bx, **{kk: v for kk, v in geo.items()
                                                                                          if kk != "beam_x"}), bottom, 2.3)
                core = s.get_at((int(bx), (bottom + H) // 2))
                assert min(core[:3]) > 120 and core[0] > 200, (w, moving, k, core)
                # only the muzzle flare may spill above the boss' bottom edge, and only close to the beam
                for side in (pg.Rect(0, 0, max(0, int(bx) - 200), bottom - 1), pg.Rect(int(bx) + 200, 0, w, bottom - 1)):
                    assert lit(s, side) == 0, (w, "fire drew above the boss", k)
                # nothing beyond the beam's reach
                reach = max(abs(bx - x0), abs(x1 - bx), 0) + 80
                assert s.get_at((max(0, int(bx - reach - 40)), (bottom + H) // 2))[:3] == (0, 0, 0) or w < 700
            # Finished sweeps draw nothing
            s = surface(w)
            boss_draw.draw_sweep(s, mk_sweep(phase="done", **geo), bottom, 0.0)
            assert lit(s, s.get_rect()) == 0


def test_sweep_edge_cases():
    s = surface(540)
    bottom = BOSS_Y + 70
    boss_draw.draw_sweep(s, mk_sweep(zone=(-60.0, 80.0), x_from=10.0, x_to=10.0), bottom, 0.3)        # off the left wall
    boss_draw.draw_sweep(s, mk_sweep(zone=(480.0, 700.0), x_from=600.0, x_to=600.0), bottom, 0.3)     # off the right wall
    boss_draw.draw_sweep(s, mk_sweep(zone=(900.0, 950.0)), bottom, 0.3)                                # fully outside
    boss_draw.draw_sweep(s, mk_sweep(), 900.0, 0.3)                                                    # boss below the floor
    boss_draw.draw_sweep(s, mk_sweep(phase="fire", k_fire=0.5, zone=(-60.0, 80.0), beam_x=10.0, x_from=10.0), bottom, 0.3)
    # The warning flickers faster as it goes on
    def flips(k0, k1):
        cnt, prev = 0, None
        for i in range(200):
            k = k0 + (k1 - k0) * i / 199
            sv = surface(540)
            boss_draw.draw_sweep(sv, mk_sweep(k_warn=k), bottom, 0.0)
            lvl = brightness(sv, pg.Rect(150, bottom + 100, 100, 300)) > 70
            cnt += prev is not None and lvl != prev
            prev = lvl
        return cnt
    assert flips(0.7, 1.0) >= flips(0.0, 0.3), "flicker should accelerate"


#Beam
def mk_beam(**kw) -> NS:
    d = dict(x=270.0, y_from=709.0, y_to=330.0, width=float(config.BOSS_BEAM_WIDTH), hit=True, progress=0.0,
             life=config.BOSS_BEAM_LIFE, age=0.0, alive=True)
    d.update(kw)
    return NS(**d)


def test_laser_poses():
    """Every boss, every laser stage and animation variant draws without error, stays near the body, the variants differ for
    the Hex Core only, the closed cannon looks like the plain body, and the glow cache stays small."""
    from game.render import boss_laser
    stages = [("aim", 0.5, 0.4), ("lock", 0.1, 1.0), ("lock", 0.9, 1.0), ("fire", 0.05, 1.0), ("fire", 0.8, 1.0), ("", 0.0, 0.5)]
    try:
        for w in WIDTHS:
            for kind in range(3):
                pics = {}
                for variant in boss_laser.VARIANTS:
                    boss_draw.LASER_VARIANT = variant
                    for stage, k, op in stages:
                        s, b = render(kind, w, laser=stage, laser_k=k, laser_open=op, phase=2)
                        rect = boss_rect(b)
                        assert lit(s, rect) > rect.w * rect.h * 0.08, (w, kind, variant, stage)
                        bb = bbox_lit(s, 60)
                        assert bb is not None and rect.inflate(300, 360).contains(bb), (w, kind, variant, stage, bb, rect)
                        pics[(variant, stage, k)] = crop_bytes(s, view_rect(b).inflate(0, 120))
                key = ("lock", 0.9)
                d_ab = diff_frac(pics[("A",) + key], pics[("B",) + key])
                d_ac = diff_frac(pics[("A",) + key], pics[("C",) + key])
                if kind == 0:
                    assert d_ab > 0.01 and d_ac > 0.01, (w, d_ab, d_ac)
                else:
                    assert d_ab == 0.0 and d_ac == 0.0, (w, kind, "only the Hex Core has variants")
        # closed and idle: same picture as a boss that was never told about lasers
        boss_draw.LASER_VARIANT = "B"
        s1, b1 = render(0, 540, phase=2)
        s2, b2 = render(0, 540, phase=2, laser="", laser_k=0.0, laser_open=0.0)
        assert crop_bytes(s1, view_rect(b1)) == crop_bytes(s2, view_rect(b2))
        # a long shot sequence does not flood the shared neon cache
        for variant in boss_laser.VARIANTS:
            boss_draw.LASER_VARIANT = variant
            neon.clear_cache()
            s = surface(540)
            for i in range(600):
                st = ("aim", "lock", "fire")[min(2, i // 200)]
                boss = mk_boss(0, anim_t=i * 0.0167, phase=2, laser=st, laser_k=(i % 200) / 200, laser_open=min(1.0, i / 30))
                boss_draw.draw_boss(s, boss, i * 0.0167)
            assert len(neon._glows.data) <= 140, (variant, len(neon._glows.data))
    finally:
        boss_draw.LASER_VARIANT = "A"


def test_sweep_stages_with_real_sweep():
    """The warning column is a thin sight line while aiming and the full hazard column once locked."""
    from game.systems.boss import Sweep
    sw = Sweep(270, 270, 110, warn_time=1.6, fire_time=0.55, lock_time=0.85)
    bottom = BOSS_Y + 64
    col = pg.Rect(270 - 40, bottom + 120, 80, 200)
    shots = {}
    for name, age in (("aim", 0.4), ("lock", 1.2), ("fire", 1.8)):
        sw.age = age
        s = surface(540)
        boss_draw.draw_sweep(s, sw, bottom, 3.1)
        shots[name] = brightness(s, col)
    assert 0.0 < shots["aim"] < shots["lock"] < shots["fire"], shots
    sw.age = 2.5                                                  # done: nothing
    s = surface(540)
    boss_draw.draw_sweep(s, sw, bottom, 3.1)
    assert brightness(s, col) == 0.0


def test_draw_beam():
    for w in WIDTHS:
        for hit in (True, False):
            x = w / 2 + 37
            for p in (0.0, 0.1, 0.4, 0.8, 1.0):
                s = surface(w)
                boss_draw.draw_beam(s, mk_beam(x=x, hit=hit, y_to=330.0 if hit else 0.0, progress=p), 0.4)
                mid = s.get_at((int(x), 520))
                assert sum(mid[:3]) > 90 or p >= 1.0, (w, hit, p, mid)
                body = lit(s, pg.Rect(int(x) - 80, 340, 160, 360), 20)
                assert body > 0, (w, hit, p)
                assert lit(s, pg.Rect(0, 0, max(0, int(x) - 120), H)) == 0
                assert lit(s, pg.Rect(int(x) + 120, 0, max(0, w - int(x) - 120), H)) == 0
                above = lit(s, pg.Rect(int(x) - 12, 0, 24, 250), 40)
                if hit:
                    assert above == 0, (w, p, "hit beam must stop at the boss")
                elif p < 0.5:
                    assert above > 0, (w, p, "missed beam flies on to the top")
        # Fades and shrinks with progress; a hit adds a flash at the impact point
        x = w / 2
        s0 = surface(w)
        boss_draw.draw_beam(s0, mk_beam(x=x, progress=0.05), 0.0)
        b0 = brightness(s0, pg.Rect(int(x) - 90, 330, 180, 380))
        s1 = surface(w)
        boss_draw.draw_beam(s1, mk_beam(x=x, progress=0.9), 0.0)
        b1 = brightness(s1, pg.Rect(int(x) - 90, 330, 180, 380))
        assert b1 < b0 * 0.45, (b0, b1)
        sh = surface(w)
        boss_draw.draw_beam(sh, mk_beam(x=x, hit=True, progress=0.2), 0.0)
        sm = surface(w)
        boss_draw.draw_beam(sm, mk_beam(x=x, hit=False, y_to=330.0, progress=0.2), 0.0)
        spot = pg.Rect(int(x) - 90, 330 - 90, 180, 180)
        assert lit(sh, spot, 20) > lit(sm, spot, 20), "hit adds a flash at y_to"
    # Degenerate: paddle above the target -> nothing
    s = surface(540)
    boss_draw.draw_beam(s, mk_beam(y_from=300.0, y_to=330.0), 0.0)
    assert lit(s, s.get_rect()) == 0
    boss_draw.draw_beam(s, mk_beam(progress=7.0), 0.0)                    # out-of-range progress is clamped


#Particle effects
def test_fx():
    ps = ParticleSystem(600)
    pos = pg.Vector2(270, 330)
    boss_draw.boss_hit_fx(ps, pos, "orange")
    light = ps.count
    assert light > 0
    boss_draw.boss_hit_fx(ps, pos, (255, 46, 196), heavy=True)
    heavy = ps.count - light
    assert heavy > light, (light, heavy)
    assert len(ps._rings) == 3, len(ps._rings)
    ps.update(0.08)
    s = surface(540)
    ps.draw(s)
    assert lit(s, pg.Rect(0, 0, 540, 840)) > 50
    # Death: one pop per call, spread over the body, grows with death_t
    rng = random.Random(3)
    for kind in range(3):
        ps = ParticleSystem(600)
        b = mk_boss(kind)
        for i in range(40):
            b.death_t = i / 39
            before = ps.count
            boss_draw.boss_death_fx(ps, b, rng)
            assert ps.count > before or ps.count == ps.max_particles
            ps.update(0.08)
        s = surface(540)
        ps.draw(s)
        assert lit(s, pg.Rect(0, 0, 540, 840)) > 100
    assert ps.count <= 600
    # Colours to prewarm: plain RGB tuples that the particle system accepts
    cols = boss_draw.prewarm_colors()
    assert cols and all(len(c) == 3 and all(0 <= v <= 255 for v in c) for c in cols)
    prewarm(cols)
    pp = ParticleSystem(100)
    for key in ("orange", "yellow", "magenta", "cyan", "purple", "green", "red", "white"):
        boss_draw.boss_hit_fx(pp, (100, 100), key, heavy=True)


def test_death_fx_stays_on_the_body():
    ps = ParticleSystem(600)
    rng = random.Random(11)
    b = mk_boss(0, death_t=0.3)
    for _ in range(30):
        boss_draw.boss_death_fx(ps, b, rng)
    ps.update(0.02)                                      # barely any travel yet
    s = surface(540)
    ps.draw(s)
    bb = bbox_lit(s, 40)
    assert bb is not None and boss_rect(b).inflate(120, 120).contains(bb), (bb, boss_rect(b))


#Sounds
def read_wav(name: str):
    path = os.path.join(SOUND_DIR, name + ".wav")
    assert os.path.isfile(path), f"missing {path}"
    with wave.open(path, "rb") as w:
        n, sr, ch, sw = w.getnframes(), w.getframerate(), w.getnchannels(), w.getsampwidth()
        raw = w.readframes(n)
    return n, sr, ch, sw, raw


def test_boss_wavs():
    for name, (lo, hi) in WAVS.items():
        n, sr, ch, sw, raw = read_wav(name)
        assert sr == 44100 and ch == 1 and sw == 2, (name, sr, ch, sw)
        dur = n / sr
        assert lo <= dur <= hi, (name, dur)
        samples = [int.from_bytes(raw[i:i + 2], "little", signed=True) for i in range(0, len(raw), 2)]
        peak = max(abs(v) for v in samples)
        peak_db = 20 * math.log10(peak / 32768)
        assert -1.3 <= peak_db <= -0.7, (name, peak_db)
        rms_db = 20 * math.log10(math.sqrt(sum(v * v for v in samples) / len(samples)) / 32768 + 1e-9)
        assert -30 < rms_db < -5, (name, rms_db)                       # audible, not a wall of noise
        tail = max(abs(v) for v in samples[-int(0.004 * sr):]) / 32768
        assert tail < 0.05, (name, "ends abruptly", tail)             # no click at the end
        assert abs(samples[0]) / 32768 < 0.05, (name, "starts with a step", samples[0])
        print(f"  {name}: {dur:.2f}s peak {peak_db:.1f} dBFS rms {rms_db:.1f} dBFS")


def test_wavs_load_in_mixer():
    try:
        pg.mixer.init()
    except pg.error as e:                                # no audio device: the files were still validated above
        print(f"  (mixer unavailable: {e})")
        return
    for name, (lo, hi) in WAVS.items():
        snd = pg.mixer.Sound(os.path.join(SOUND_DIR, name + ".wav"))
        assert lo <= snd.get_length() <= hi, (name, snd.get_length())
    assert all(n in config.SFX_NAMES for n in WAVS), "config.SFX_NAMES lacks a boss sound"


def test_synth_recipes_registered():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import synth_sfx
    for name in WAVS:
        assert name in synth_sfx.SFX_NAMES and name in synth_sfx.RECIPES, name


TESTS = [
    test_draw_boss_matrix, test_boss_edge_positions, test_kinds_look_different, test_boss_states_change_the_picture,
    test_boss_animates_and_is_deterministic, test_death_fades_out, test_boss_duck_typing, test_glow_cache_stays_small,
    test_prewarm_glows, test_boss_draw_cost, test_draw_sweep, test_sweep_edge_cases, test_laser_poses,
    test_sweep_stages_with_real_sweep, test_draw_beam, test_fx,
    test_death_fx_stays_on_the_body, test_boss_wavs, test_wavs_load_in_mixer, test_synth_recipes_registered,
]


def main() -> int:
    failed = 0
    base_w = config.LOGICAL_W
    try:
        for test in TESTS:
            try:
                test()
                print(f"PASS {test.__name__}")
            except AssertionError as e:
                failed += 1
                print(f"FAIL {test.__name__}: {e!r}")
                import traceback
                traceback.print_exc()
    finally:
        config.set_logical_width(base_w)
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
