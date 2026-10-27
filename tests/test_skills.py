"""Boss skill item tests (plain asserts, no pytest): drop rules, multi-ball, reflect shield, reset, i18n, sounds.

Run from the repo root:   python -m tests.test_skills
or from anywhere:      python tests/test_skills.py
"""
import json
import math
import os
import random
import shutil
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg  # noqa: E402

from game import config  # noqa: E402
from game.app import App  # noqa: E402
from game.entities.boss_items import HelperBall, Projectile, SkillItem  # noqa: E402
from game.render import boss_draw  # noqa: E402
from game.systems.boss import BossTick  # noqa: E402
from game.systems.skills import ReflectShield, SkillDrops, reflect_projectile  # noqa: E402

DT = config.PHYSICS_DT


#Helpers
class FixedRng:
    """random() always returns `value`; choice() returns the first option."""

    def __init__(self, value: float = 0.0):
        self.value = value
        self.calls = 0

    def random(self):
        self.calls += 1
        return self.value

    def choice(self, seq):
        return seq[0]

    def uniform(self, a, b):
        return (a + b) / 2


class RecAudio:
    """Stands in for AudioManager: records every play() call."""

    def __init__(self):
        self.calls = []             # (name, volume, min_interval)
        self.enabled = False

    def play(self, name, volume=1.0, min_interval=None):
        self.calls.append((name, volume, min_interval))

    def names(self):
        return [c[0] for c in self.calls]

    def __getattr__(self, name):    # play_music, stop_music, ... are no-ops
        return lambda *a, **k: None


class Fight:
    """A real PlayScene in the middle of a boss fight; the boss controller is frozen (no new shots or balls)."""

    def __init__(self):
        self.tmp = tempfile.mkdtemp()
        self.app = App(["--data-dir", self.tmp, "--start-scene", "menu"])
        self.scene = self.app.scenes.get("play")
        self.audio = self.app.audio = RecAudio()
        s = self.scene
        s.on_enter()
        s.state = "playing"
        s.lives = s.max_lives = 5
        s._start_boss()
        for _ in range(int((config.BOSS_INTRO_TIME + 0.5) / DT)):
            s.boss.update(DT, s.player.pos.x, 0)                    # run the intro only; the scene is not stepped
            if s.boss.fighting:
                break
        assert s.boss.fighting, s.boss.state
        s.projectiles.clear()
        s.helpers.clear()
        s.boss.update = self._frozen_update
        self.balls_arg = []
        s.rng = s.skill_drops.rng = FixedRng(0.99)                  # nothing drops unless a test says so
        s.player.pos.x = s.boss.boss.pos.x                           # paddle right under the boss
        s.hurt_timer = 0.0
        self.hp0 = s.boss.boss.hp

    def _frozen_update(self, dt, px, balls):
        self.balls_arg.append(balls)
        return BossTick()

    def step(self, seconds: float = DT, playing: bool = True) -> None:
        for _ in range(max(1, int(round(seconds / DT)))):
            self.scene._step_boss(DT, 1.0, None, playing)

    def shot(self, x=None, y=None, vx=0.0, vy=300.0, shape="orb") -> Projectile:
        s = self.scene
        p = Projectile(s.player.pos.x if x is None else x, s.player.rect.top - 2 if y is None else y, vx, vy, 13, shape)
        s.projectiles.append(p)
        return p

    def close(self) -> None:
        self.app.close()
        shutil.rmtree(self.tmp, ignore_errors=True)


def with_fight(test):
    def wrapper():
        f = Fight()
        try:
            test(f)
        finally:
            f.close()
    wrapper.__name__ = test.__name__
    return wrapper


def skill_items(f) -> list:
    return [h for h in f.scene.helpers if isinstance(h, SkillItem) and h.alive]


def bonus_balls(f) -> list:
    return [h for h in f.scene.helpers if isinstance(h, HelperBall) and h.bonus and h.alive]


def drop_item(f, skill: str) -> None:
    """A skill item right on the paddle: the next step catches it."""
    f.scene.helpers.append(SkillItem(skill, f.scene.player.pos.x, f.scene.player.pos.y - 5))
    f.step()


#Drop rules (pure logic)
def test_drop_chance():
    rng = random.Random(1234)
    d = SkillDrops(rng)
    n = 20000
    hits = 0
    for _ in range(n):
        d.cooldown = 0.0
        hits += d.roll(False) is not None
    assert abs(hits / n - config.SKILL_DROP_CHANCE) < 0.012, hits / n


def test_drop_cooldown():
    d = SkillDrops(FixedRng(0.0))                               # every roll would succeed
    assert d.roll(False) in config.SKILL_KINDS
    assert d.roll(False) is None, "cooldown starts with the drop"
    d.update(config.SKILL_DROP_COOLDOWN - 0.01)
    assert d.roll(False) is None
    d.update(0.02)
    assert d.roll(False) in config.SKILL_KINDS
    assert d.cooldown == config.SKILL_DROP_COOLDOWN
    blocked = FixedRng(0.0)
    d2 = SkillDrops(blocked)
    d2.cooldown = 3.0
    d2.roll(False)
    assert blocked.calls == 0, "no random number is used while blocked"
    d2.reset()
    assert d2.cooldown == 0.0


def test_one_item_on_field():
    d = SkillDrops(FixedRng(0.0))
    assert d.roll(True) is None and d.cooldown == 0.0, "an item already lies on the field: no roll, no cooldown"
    assert d.roll(False) is not None


def test_kinds_are_even():
    d = SkillDrops(random.Random(7))
    d.rng.random = lambda: 0.0                                  # chance always hits; kinds come from the seeded choice()
    counts = {k: 0 for k in config.SKILL_KINDS}
    for _ in range(4000):
        d.cooldown = 0.0
        counts[d.roll(False)] += 1
    assert set(counts) == {"multiball", "reflect"}, counts
    assert all(0.47 <= c / 4000 <= 0.53 for c in counts.values()), counts


def test_shield_timer():
    sh = ReflectShield()
    assert not sh.active and sh.frac == 0.0 and not sh.blinking
    sh.activate()
    assert sh.active and sh.time_left == config.REFLECT_TIME == 5.0 and sh.frac == 1.0
    sh.update(2.0)
    assert abs(sh.time_left - 3.0) < 1e-9 and abs(sh.frac - 0.6) < 1e-9
    sh.activate()                                               # picking it up again refreshes, never adds
    assert sh.time_left == config.REFLECT_TIME
    sh.update(config.REFLECT_TIME - config.REFLECT_BLINK_TIME + 0.01)
    assert sh.active and sh.blinking
    sh.update(10.0)
    assert not sh.active and sh.time_left == 0.0 and not sh.blinking
    sh.activate()
    sh.clear()
    assert not sh.active


def test_reflect_projectile_rule():
    paddle = pg.Rect(200, 700, 110, 22)
    p = Projectile(250, 698, 40.0, 300.0, 13, "bolt")
    reflect_projectile(p, paddle)
    assert p.reflected and p.vel.y == -300.0 and p.vel.x == 40.0
    assert not p.hits(paddle), "pushed clear of the paddle"
    assert p.pos.y < paddle.top


#Scene wiring
@with_fight
def test_drop_in_scene(f):
    s = f.scene
    s.rng = s.skill_drops.rng = FixedRng(0.0)
    s._damage_boss(10, (s.boss.boss.pos.x, 300), False)
    items = skill_items(f)
    assert len(items) == 1 and items[0].skill in config.SKILL_KINDS
    b = s.boss.boss
    assert abs(items[0].pos.y - (b.pos.y + b.half_h)) < 1 and abs(items[0].pos.x - b.pos.x) <= 0.4 * b.half_w + 1
    s._damage_boss(10, (200, 300), False)
    assert len(skill_items(f)) == 1, "cooldown and the item on the field: no second one"
    s.skill_drops.update(config.SKILL_DROP_COOLDOWN)
    s._damage_boss(10, (200, 300), False)
    assert len(skill_items(f)) == 1, "cooldown over, but one still lies on the field"
    s.helpers.clear()
    s._damage_boss(10, (200, 300), False)
    assert len(skill_items(f)) == 1, "field empty again: a new one may drop"
    # no damage dealt = no roll
    s.helpers.clear()
    s.skill_drops.reset()
    s.boss.state = "intro"
    s._damage_boss(10, (200, 300), False)
    assert not skill_items(f)


@with_fight
def test_drop_cooldown_runs_only_while_fighting(f):
    s = f.scene
    s.skill_drops.cooldown = config.SKILL_DROP_COOLDOWN
    f.step(1.0, playing=False)
    assert s.skill_drops.cooldown == config.SKILL_DROP_COOLDOWN, "no time passes while not playing"
    f.step(1.0)
    assert abs(s.skill_drops.cooldown - (config.SKILL_DROP_COOLDOWN - 1.0)) < 0.02
    s.boss.state = "intro"
    f.step(1.0)
    assert abs(s.skill_drops.cooldown - (config.SKILL_DROP_COOLDOWN - 1.0)) < 0.02, "intro does not count"


@with_fight
def test_skill_item_falls_and_vanishes(f):
    s = f.scene
    item = SkillItem("reflect", 30, 400)                        # far from the paddle
    s.player.pos.x = config.LOGICAL_W - 80
    s.helpers.append(item)
    lives = s.lives
    f.step(4.0)
    assert not item.alive and item.fell and not s.reflect.active and s.lives == lives
    assert "miss" not in f.audio.names() and not s.skill_drops.cooldown < 0


@with_fight
def test_multiball(f):
    s = f.scene
    drop_item(f, "multiball")
    balls = bonus_balls(f)
    assert len(balls) == 3 and all(b.flying and b.tier == 1 for b in balls), balls
    angles = sorted(round(math.degrees(math.atan2(b.vel.x, -b.vel.y))) for b in balls)
    assert angles == sorted(round(a) for a in config.MULTIBALL_ANGLES), angles
    top = s.player.rect.top - config.BOSS_BALL_RADIUS
    assert all(top - 20 <= b.pos.y <= top + 1 and abs(b.pos.x - s.player.pos.x) < 20 for b in balls), \
        [(b.pos.x, b.pos.y) for b in balls]
    assert "skill_pick" in f.audio.names()
    assert not skill_items(f)
    # outside BOSS_MAX_BALLS: not counted by the scene, the controller or the HUD
    assert s._normal_balls() == 0 and s.hud_state()["boss"]["balls"] == 0
    s.helpers.extend(HelperBall(60 + 80 * i, 300) for i in range(config.BOSS_MAX_BALLS))
    f.balls_arg.clear()
    f.step()
    assert f.balls_arg[-1] == config.BOSS_MAX_BALLS, f.balls_arg
    assert s.hud_state()["boss"]["balls"] == config.BOSS_MAX_BALLS
    assert len(bonus_balls(f)) == 3


@with_fight
def test_bonus_ball_lost_costs_nothing(f):
    s = f.scene
    lost = []
    s.boss.ball_lost = lambda: lost.append(1)
    ball = HelperBall.launched(30, config.LOGICAL_H + 5, 0.0, bonus=True)
    ball.vel.update(0, 300)
    s.helpers.append(ball)
    lives = s.lives
    f.step(0.2)
    assert not ball.alive and not bonus_balls(f)
    assert s.lives == lives and not lost and s.stats.get("balls_lost", 0) == 0
    assert "miss" not in f.audio.names() and s.flash == 0.0
    # a normal ball is still a (free) loss with the old bookkeeping
    normal = HelperBall.launched(30, config.LOGICAL_H + 5, 0.0, bonus=False)
    normal.vel.update(0, 300)
    s.helpers.append(normal)
    f.step(0.2)
    assert lost == [1] and s.stats.get("balls_lost") == 1 and s.lives == lives and "miss" in f.audio.names()


@with_fight
def test_bonus_ball_damages_but_earns_no_energy(f):
    s = f.scene
    n = s.boss.boss.number
    bonus = HelperBall.launched(200, 300, 0.0, bonus=True)
    before = s.boss.boss.hp
    s._on_ball_event(bonus, "boss")
    dealt = before - s.boss.boss.hp
    assert abs(dealt - config.ball_base_damage(n) * bonus.damage_mult) < 1e-6, dealt
    assert s.score > 0
    for _ in range(config.BOSS_HITS_PER_ENERGY * 3):
        s._on_ball_event(bonus, "boss")
    assert s.ball_hits == 0 and not [h for h in s.helpers if h.kind == "energy"], "bonus hits never count for energy"
    normal = HelperBall.launched(200, 300, 0.0, bonus=False)
    for _ in range(config.BOSS_HITS_PER_ENERGY):
        s._on_ball_event(normal, "boss")
    assert s.ball_hits == config.BOSS_HITS_PER_ENERGY and [h for h in s.helpers if h.kind == "energy"]


@with_fight
def test_bonus_ball_hits_boss_in_flight(f):
    s = f.scene
    b = s.boss.boss
    ball = HelperBall.launched(b.pos.x, b.pos.y + b.half_h + 40, 0.0, bonus=True)
    s.helpers.append(ball)
    f.step(0.3)
    assert s.boss.boss.hp < f.hp0 and s.ball_hits == 0


@with_fight
def test_skill_drop_from_bonus_ball_hit(f):
    s = f.scene
    s.rng = s.skill_drops.rng = FixedRng(0.0)
    s._on_ball_event(HelperBall.launched(200, 300, 0.0, bonus=True), "boss")
    assert len(skill_items(f)) == 1, "a bonus ball hit rolls a drop like any damage"


@with_fight
def test_reflect_bounces_and_hits_boss_once(f):
    s = f.scene
    n = s.boss.boss.number
    for shape in ("orb", "bolt", "shard"):
        s.helpers.clear()
        s.projectiles.clear()
        s.boss.boss.hp = f.hp0
        s.score = 0
        drop_item(f, "reflect")
        assert s.reflect.active and abs(s.reflect.time_left - config.REFLECT_TIME) < 0.05
        lives = s.lives
        p = f.shot(vx=0.0, vy=300.0, shape=shape)
        f.step()
        assert s.lives == lives and s.hurt_timer == 0.0, "shield: no life lost, no invulnerability"
        assert p.reflected and p.alive and p.vel.y < 0 and p.vel.x == 0.0
        assert not p.hits(s.player.rect)
        f.step(0.1)
        assert s.lives == lives and s.hurt_timer == 0.0 and p.reflected
        f.step(2.0)                                             # flies up into the boss
        assert not p.alive
        dealt = f.hp0 - s.boss.boss.hp
        assert abs(dealt - config.reflect_damage(n, shape)) < 1e-6, (shape, dealt)
        f.step(1.0)
        assert abs((f.hp0 - s.boss.boss.hp) - dealt) < 1e-9, "hits exactly once"
        assert "skill_reflect" in f.audio.names() and "boss_hit" in f.audio.names()
        assert s.score > 0 and s.ball_hits == 0
    ratios = [config.reflect_damage(n, k) / config.ball_base_damage(n) for k in ("orb", "bolt", "shard")]
    assert ratios == [1.0, 1.5, 2.0], ratios


@with_fight
def test_reflect_keeps_horizontal_speed(f):
    s = f.scene
    drop_item(f, "reflect")
    p = f.shot(vx=90.0, vy=250.0)
    f.step()
    assert p.reflected and abs(p.vel.x - 90.0) < 1e-9 and abs(p.vel.y + 250.0) < 1e-9, p.vel


@with_fight
def test_reflect_works_during_invulnerability(f):
    s = f.scene
    drop_item(f, "reflect")
    s.hurt_timer = 0.8
    p = f.shot()
    f.step()
    assert p.reflected and s.hurt_timer == 0.8 and s.lives == 5


@with_fight
def test_reflected_shot_flies_off_screen(f):
    s = f.scene
    drop_item(f, "reflect")
    s.player.pos.x = 40                                         # far from the boss: the bounced shot misses it
    s.boss.boss.pos.x = config.LOGICAL_W - 100
    p = f.shot(x=40)
    f.step(0.05)
    assert p.reflected
    f.step(4.0)
    assert not p.alive and s.boss.boss.hp == f.hp0 and p not in s.projectiles


@with_fight
def test_reflected_shot_passes_when_boss_not_hittable(f):
    s = f.scene
    drop_item(f, "reflect")
    p = f.shot()
    f.step(0.05)
    assert p.reflected
    s.boss.state = "intro"                                      # hit_rect is None: it flies through
    f.step(4.0)
    assert not p.alive and s.boss.boss.hp == f.hp0


@with_fight
def test_reflected_shot_never_hurts_player(f):
    s = f.scene
    p = f.shot()
    p.reflected = True                                          # shield long gone, shot already bounced
    f.step()
    assert s.lives == 5 and s.hurt_timer == 0.0 and p.alive


@with_fight
def test_shot_hurts_without_shield(f):
    s = f.scene
    s.helpers.clear()
    f.shot()
    f.step()
    assert s.lives == 4 and s.hurt_timer == config.BOSS_HIT_IFRAMES


@with_fight
def test_sweep_still_hurts_with_shield(f):
    s = f.scene
    drop_item(f, "reflect")
    s.boss.sweep_hits = lambda rect: True                       # a firing sweep over the paddle
    f.step()
    assert s.lives == 4 and s.hurt_timer == config.BOSS_HIT_IFRAMES and s.reflect.active


@with_fight
def test_reflect_refresh_and_expiry(f):
    s = f.scene
    drop_item(f, "reflect")
    f.step(2.0)
    assert 2.9 < s.reflect.time_left < 3.1
    drop_item(f, "reflect")
    assert abs(s.reflect.time_left - config.REFLECT_TIME) < 0.05, "second pick-up refreshes to 5 s, no stacking"
    f.step(config.REFLECT_TIME + 0.1)
    assert not s.reflect.active
    p = f.shot()
    f.step()
    assert not p.reflected and s.lives == 4 and s.hurt_timer == config.BOSS_HIT_IFRAMES, "back to normal after 5 s"


@with_fight
def test_reset_clears_skills(f):
    s = f.scene

    def load():
        s.reflect.activate()
        s.skill_drops.cooldown = 5.0
        s.helpers.append(SkillItem("multiball", 100, 100))
        s.helpers.append(HelperBall.launched(100, 500, 0.0, bonus=True))

    def clean():
        assert not s.reflect.active and s.skill_drops.cooldown == 0.0 and not skill_items(f) and not bonus_balls(f)

    load()
    s._on_boss_dead()                                           # boss beaten
    clean()
    load()
    s._end_boss()                                               # reward taken
    clean()
    load()
    s._start_boss()                                             # next fight
    clean()
    load()
    s.reset_round()                                             # new round
    clean()


@with_fight
def test_hud_reflect_keys(f):
    s = f.scene
    assert s.hud_state()["boss"]["reflect_left"] == 0.0 and s.hud_state()["boss"]["reflect_frac"] == 0.0
    s.reflect.activate()
    s.reflect.update(1.0)
    h = s.hud_state()["boss"]
    assert abs(h["reflect_left"] - 4.0) < 1e-9 and abs(h["reflect_frac"] - 0.8) < 1e-9


@with_fight
def test_bot_ignores_bonus_balls(f):
    s = f.scene
    s.helpers.append(HelperBall.launched(100, 600, -10.0, bonus=False))
    before = s._boss_goal()
    s.helpers.append(HelperBall.launched(400, 650, 20.0, bonus=True))
    s.helpers.append(HelperBall.launched(300, 500, -20.0, bonus=True))
    assert s._boss_goal() == before
    s.helpers.clear()
    s.helpers.append(HelperBall.launched(400, 650, 20.0, bonus=True))
    assert s._boss_goal()[2] is not None or s._boss_goal()[0] == s.boss.boss.pos.x       # does not chase a bonus ball
    s.app.autoplay = True
    assert s._bot_direction() in (-1, 0, 1)


def test_autoplay_with_many_skills():
    """The bot plays a whole real fight while items drop all the time: no crash, no stray objects."""
    f = Fight()
    old = config.SKILL_DROP_CHANCE, config.SKILL_DROP_COOLDOWN
    try:
        config.SKILL_DROP_CHANCE, config.SKILL_DROP_COOLDOWN = 1.0, 1.0
        s = f.scene
        del s.boss.update                                       # back to the real controller
        s.rng = random.Random(5)
        s.skill_drops.rng = s.rng
        s.app.autoplay = True
        s.lives = s.max_lives = 999
        seen = set()
        for _ in range(int(60.0 / DT)):
            s.update(DT)
            seen.update(h.kind if not isinstance(h, HelperBall) else "ball" for h in s.helpers)
            assert all(isinstance(h, (HelperBall, SkillItem)) or h.kind == "energy" for h in s.helpers)
            if s.state != "playing" or not s.boss_mode:
                break
        assert "skill" in seen, seen
        assert s.lives >= 1
    finally:
        config.SKILL_DROP_CHANCE, config.SKILL_DROP_COOLDOWN = old
        f.close()


#Drawing, i18n, sound files
def test_draw_smoke():
    app = App(["--data-dir", tempfile.mkdtemp(), "--start-scene", "menu"])
    try:
        surf = pg.Surface(config.LOGICAL_SIZE)
        for skill in config.SKILL_KINDS:
            item = SkillItem(skill, 100, 100)
            for i in range(30):
                item.update(1 / 60)
                item.magnetized = i % 2 == 0
                item.draw(surf, i / 60.0, app.assets)
        a = SkillItem("multiball", 100, 100)
        b = SkillItem("reflect", 100, 100)
        s1, s2 = pg.Surface((80, 80)), pg.Surface((80, 80))
        for s, it in ((s1, a), (s2, b)):
            s.fill((0, 0, 0))
            it.pos.update(40, 40)
            it.draw(s, 0.3)
        assert pg.image.tobytes(s1, "RGB") != pg.image.tobytes(s2, "RGB"), "the two icons look different"
        assert pg.transform.average_color(s1)[:3] != (0, 0, 0)
        for w in (110, 220):
            for frac in (1.0, 0.5, 0.0):
                for blink in (False, True):
                    boss_draw.draw_reflect_shield(surf, 270, 720, w, 22, frac, blink, 0.37)
        surf.fill((0, 0, 0))
        boss_draw.draw_reflect_shield(surf, 270, 720, 110, 22, 1.0, False, 0.0)
        assert surf.get_bounding_rect().height > 30 and surf.get_bounding_rect().top < 700
        # the shield is part of the scene's draw too
        sc = app.scenes.get("play")
        sc.on_enter()
        sc.state = "playing"
        sc.reflect.activate()
        sc.draw(surf)
        sc.reflect.update(4.5)
        sc.draw(surf)
    finally:
        app.close()


def test_i18n_keys():
    langs = {}
    for lang in ("vi", "en"):
        with open(os.path.join(ROOT, "lang", f"{lang}.json"), encoding="utf-8") as fh:
            langs[lang] = json.load(fh)
    assert set(langs["vi"]) == set(langs["en"]), set(langs["vi"]) ^ set(langs["en"])
    for kind in config.SKILL_KINDS:
        for lang, d in langs.items():
            assert d.get(f"boss.skill.{kind}", "").strip(), (lang, kind)
    assert langs["vi"]["boss.skill.reflect"] == "PHẢN ĐẠN!" and langs["en"]["boss.skill.multiball"] == "TRIPLE BALL!"
    assert "kỹ năng" in langs["vi"]["howto.boss_tip"] and "skill" in langs["en"]["howto.boss_tip"]


def test_sound_files():
    sys.path.insert(0, os.path.join(ROOT, "tools"))
    import synth_sfx
    for name, (lo, hi) in {"skill_pick": (0.2, 0.9), "skill_reflect": (0.08, 0.35)}.items():
        assert name in config.SFX_NAMES and name in synth_sfx.SFX_NAMES and name in synth_sfx.RECIPES, name
        with wave.open(os.path.join(ROOT, "assets", "sound", name + ".wav")) as w:
            dur = w.getnframes() / w.getframerate()
            data = w.readframes(w.getnframes())
        assert lo <= dur <= hi, (name, dur)
        samples = [int.from_bytes(data[i:i + 2], "little", signed=True) for i in range(0, len(data), 2)]
        peak = max(abs(v) for v in samples) / 32768
        assert 0.8 < peak < 1.0, (name, peak)
        assert abs(samples[0]) / 32768 < 0.05 and abs(samples[-1]) / 32768 < 0.05, name
    assert set(synth_sfx.SFX_NAMES) == set(config.SFX_NAMES)


@with_fight
def test_reflect_sound_is_throttled(f):
    drop_item(f, "reflect")
    f.shot()
    f.step()
    calls = [c for c in f.audio.calls if c[0] == "skill_reflect"]
    assert calls and all(c[2] is not None and c[2] <= 0.1 for c in calls), calls


TESTS = [
    test_drop_chance, test_drop_cooldown, test_one_item_on_field, test_kinds_are_even, test_shield_timer,
    test_reflect_projectile_rule,
    test_drop_in_scene, test_drop_cooldown_runs_only_while_fighting, test_skill_item_falls_and_vanishes,
    test_multiball, test_bonus_ball_lost_costs_nothing, test_bonus_ball_damages_but_earns_no_energy,
    test_bonus_ball_hits_boss_in_flight, test_skill_drop_from_bonus_ball_hit,
    test_reflect_bounces_and_hits_boss_once, test_reflect_keeps_horizontal_speed,
    test_reflect_works_during_invulnerability, test_reflected_shot_flies_off_screen,
    test_reflected_shot_passes_when_boss_not_hittable, test_reflected_shot_never_hurts_player,
    test_shot_hurts_without_shield, test_sweep_still_hurts_with_shield, test_reflect_refresh_and_expiry,
    test_reset_clears_skills, test_hud_reflect_keys, test_bot_ignores_bonus_balls, test_autoplay_with_many_skills,
    test_draw_smoke, test_i18n_keys, test_sound_files, test_reflect_sound_is_throttled,
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
