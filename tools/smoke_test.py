"""End-to-end smoke test for Hứng Đồ v2 (headless). Exit code 0 = pass, 1 = failure.

Drives the real App through every scene with posted input events, forces gameplay events
(catches, misses, bombs, power-ups, level-up, game over), runs the autoplay bot for 90
simulated seconds and saves screenshots to tools/_out/smoke_*.png.
All files are written to a temporary user data dir; the real profile is never touched.

Run: .venv/Scripts/python.exe tools/smoke_test.py [--autoplay-seconds N] [--keep-data]
"""
import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import traceback

os.environ["SDL_VIDEODRIVER"] = "dummy"
os.environ["SDL_AUDIODRIVER"] = "dummy"
TEMP_DATA = tempfile.mkdtemp(prefix="hungdo_smoke_")
os.environ["HUNGDO_DATA_DIR"] = TEMP_DATA

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "tools", "_out")
sys.path.insert(0, ROOT)

import pygame as pg  # noqa: E402

from game import app as app_mod, config, i18n, paths, settings as settings_mod  # noqa: E402


def _temp_data_dir() -> str:
    os.makedirs(TEMP_DATA, exist_ok=True)
    return TEMP_DATA


# Monkeypatch every user_data_dir reference (env var above is the first line of defence)
_real_data_dir = paths.user_data_dir
paths.user_data_dir = _temp_data_dir
settings_mod.user_data_dir = _temp_data_dir
app_mod.user_data_dir = _temp_data_dir

from game.app import App  # noqa: E402
from game.entities.items import Item, catch_y  # noqa: E402

DT = 1 / 60
CHECKS = []


def check(cond, msg) -> None:
    CHECKS.append(msg)
    if not cond:
        raise AssertionError(msg)


def real_profile_snapshot() -> dict:
    """mtimes of the real profile's files (must not change during the test)."""
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return {}
    d = os.path.join(appdata, config.DATA_DIR_NAME)
    out = {}
    for name in ("settings.json", "save.json"):
        p = os.path.join(d, name)
        out[name] = os.path.getmtime(p) if os.path.exists(p) else None
    return out


class Driver:
    def __init__(self, app):
        self.app = app

    def steps(self, n: int = 1, dt: float = DT) -> None:
        for _ in range(n):
            self.app.step(dt)

    def key(self, k, hold: bool = False) -> None:
        pg.event.post(pg.event.Event(pg.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
        if not hold:
            pg.event.post(pg.event.Event(pg.KEYUP, key=k, mod=0, unicode="", scancode=0))
        self.app.step(DT)

    def release(self, k) -> None:
        pg.event.post(pg.event.Event(pg.KEYUP, key=k, mod=0, unicode="", scancode=0))
        self.app.step(DT)

    def click(self, logical) -> None:
        wp = self.app.display.to_window(logical)
        pg.event.post(pg.event.Event(pg.MOUSEMOTION, pos=wp, rel=(0, 0), buttons=(0, 0, 0)))
        pg.event.post(pg.event.Event(pg.MOUSEBUTTONDOWN, pos=wp, button=1))
        pg.event.post(pg.event.Event(pg.MOUSEBUTTONUP, pos=wp, button=1))
        self.app.step(DT)

    @property
    def top(self):
        return self.app.scenes.top

    @property
    def stack(self):
        return self.app.scenes.stack_names

    def focus_to(self, menu, i: int) -> None:
        for _ in range(len(menu.widgets) * 2):
            if menu.focus == i:
                return
            self.key(pg.K_s if menu.focus < i else pg.K_w)
        check(menu.focus == i, f"menu focus reached row {i}")

    def shot(self, name: str) -> None:
        os.makedirs(OUT, exist_ok=True)
        pg.image.save(self.app.display.surface, os.path.join(OUT, f"smoke_{name}.png"))


#(a) scripted walkthrough

def walk_menus(d: Driver) -> None:
    app = d.app
    d.steps(40)
    check(d.stack == ["menu"], f"starts in menu (stack {d.stack})")
    check(not app.placeholders, f"no placeholder scenes ({sorted(app.placeholders)})")
    # Regression: the mixer once claimed to be enabled while the device never opened (no sound at all)
    check(app.audio.enabled == bool(pg.mixer.get_init()), "audio.enabled matches the real mixer state")
    if app.audio.enabled:
        check(app.audio.has("catch") and app.audio.has("ui_move"), "sound effects loaded")
    d.shot("menu")

    # How to play and back
    menu = d.top.menu
    d.focus_to(menu, 1)
    d.key(pg.K_RETURN)
    d.steps(20)
    check(d.stack == ["menu", "howto"], f"howto pushed ({d.stack})")
    d.shot("howto")
    d.key(pg.K_ESCAPE)
    check(d.stack == ["menu"], f"Esc returns from howto ({d.stack})")

    # Settings: change every row
    d.focus_to(menu, 2)
    d.key(pg.K_RETURN)
    d.steps(10)
    check(d.stack == ["menu", "settings"], f"settings pushed ({d.stack})")
    sm = d.top.menu
    s = app.settings

    d.focus_to(sm, 0)                                   # Language
    d.key(pg.K_d)
    check(s.language == "en" and i18n.get_language() == "en", "language switched to en")
    d.steps(10)
    d.shot("settings_en")
    d.key(pg.K_a)
    check(s.language == "vi" and i18n.get_language() == "vi", "language back to vi")

    d.focus_to(sm, 1)                                   # Resolution
    avail = [tuple(r) for r in app.display.available_resolutions()]
    d.key(pg.K_d)
    d.key(pg.K_a)
    check(tuple(s.resolution) in avail, f"resolution {s.resolution} valid ({avail})")

    d.focus_to(sm, 2)                                   # Fullscreen on/off
    d.key(pg.K_RETURN)
    check(s.fullscreen, "fullscreen on")
    d.steps(5)
    d.shot("settings_fullscreen")
    d.key(pg.K_RETURN)
    check(not s.fullscreen, "fullscreen off")
    check(pg.display.get_surface() is not None, "window exists after fullscreen toggle")

    d.focus_to(sm, 3)                                   # FPS cap: visit every option
    seen = {s.fps_cap}
    for _ in range(len(config.FPS_OPTIONS)):
        d.key(pg.K_d)
        seen.add(s.fps_cap)
    check(seen == set(config.FPS_OPTIONS), f"FPS cap cycled through {sorted(seen)}")
    while s.fps_cap != 60:
        d.key(pg.K_d)

    d.focus_to(sm, 4)                                   # Show FPS
    d.key(pg.K_RETURN)
    check(s.show_fps, "show FPS on")

    d.focus_to(sm, 5)                                   # Music volume
    mv = s.music_volume
    d.key(pg.K_a)
    check(s.music_volume < mv, "music volume lowered")
    check(abs(app.audio.music_volume - s.music_volume) < 1e-6, "audio got the music volume")

    d.focus_to(sm, 6)                                   # SFX volume
    sv = s.sfx_volume
    d.key(pg.K_a)
    check(s.sfx_volume < sv, "sfx volume lowered")

    d.focus_to(sm, 7)                                   # Screen shake off/on
    d.key(pg.K_RETURN)
    check(not s.screen_shake, "screen shake off")
    d.key(pg.K_RETURN)
    check(s.screen_shake, "screen shake on")
    d.shot("settings")

    d.focus_to(sm, 8)                                   # Back
    d.key(pg.K_RETURN)
    check(d.stack == ["menu"], f"Back returns to menu ({d.stack})")

    with open(os.path.join(TEMP_DATA, "settings.json"), encoding="utf-8") as f:
        saved = json.load(f)
    check(saved.get("show_fps") is True and abs(saved.get("music_volume", 0) - s.music_volume) < 1e-6,
          "settings.json reflects the changes")

    # Quit asks for confirmation; Esc / Stay keeps the game running
    d.focus_to(menu, 3)
    d.key(pg.K_RETURN)
    check(d.stack == ["menu", "confirm_quit"], f"Quit opens confirmation ({d.stack})")
    check(app.running, "game still running while asked")
    d.shot("confirm_quit")
    d.key(pg.K_ESCAPE)
    check(d.stack == ["menu"] and app.running, f"Esc on confirmation stays ({d.stack})")
    d.focus_to(menu, 0)
    d.key(pg.K_ESCAPE)                                  # Esc in menu jumps to Quit...
    d.key(pg.K_ESCAPE)                                  # ...and Esc on Quit asks
    check(d.stack == ["menu", "confirm_quit"], f"Esc on Quit asks too ({d.stack})")
    d.key(pg.K_ESCAPE)
    check(d.stack == ["menu"] and app.running, "stayed in game again")


def play_scene(d: Driver):
    play = d.top
    check(d.stack == ["play"] and type(play).__name__ == "PlayScene", f"real play scene ({d.stack})")
    return play


def wait_for(d: Driver, cond, max_steps: int, msg: str) -> None:
    for _ in range(max_steps):
        if cond():
            return
        d.steps(1)
    check(cond(), msg)


def drop_on_player(d: Driver, play, kind: str, power=None) -> None:
    """Place an item just above the paddle and step until it is caught."""
    x = play.player.pos.x
    it = Item(kind, x, catch_y(config.ITEM_RADIUS[kind]) - 30, vy=300, power=power)
    play.items.append(it)
    wait_for(d, lambda: not it.alive, 60, f"{kind}/{power} caught")
    check(not it.fell, f"{kind}/{power} was caught, not dropped")


def drop_miss(d: Driver, play) -> None:
    """Good item far from the paddle, already below its top: it falls off screen."""
    x = 40 if play.player.pos.x > config.LOGICAL_W / 2 else config.LOGICAL_W - 40
    it = Item("common", x, config.PLAYER_Y + 10, vy=400)
    play.items.append(it)
    wait_for(d, lambda: not it.alive, 120, "missed item left the screen")


def walk_resize(d: Driver) -> None:
    """The canvas follows the window aspect; toggling fullscreen mid-round keeps the round."""
    app = d.app
    s = app.settings
    opts = app.display.available_resolutions()
    check(len(opts) >= 3, f"several window sizes offered ({opts})")
    check(all(o[0] > o[1] for o in opts) or app.display.available_resolutions()[0][0] >= config.BASE_W * 0.6,
          "window sizes follow the desktop aspect")
    win = pg.display.get_surface().get_size()
    check(config.LOGICAL_W == config.logical_width_for(win[0] / win[1]), "canvas width matches the window aspect")
    check(app.display.surface.get_size() == config.LOGICAL_SIZE, "canvas surface matches config size")
    check(d.stack == ["menu"], f"back at the menu ({d.stack})")
    d.focus_to(d.top.menu, 0)
    d.key(pg.K_RETURN)
    play = play_scene(d)
    d.steps(60 * 4)
    old_w = config.LOGICAL_W
    sizes = {old_w}
    for fs in (True, False, True, False):
        s.fullscreen = fs
        app.apply_settings()
        d.steps(20)
        sizes.add(config.LOGICAL_W)
        check(app.display.surface.get_size() == config.LOGICAL_SIZE, "canvas resized with the window")
        check(d.stack == ["play"], f"round survives the resize ({d.stack})")
        check(0 <= play.player.pos.x <= config.LOGICAL_W, "paddle stays inside the new canvas")
        check(all(-50 <= it.pos.x <= config.LOGICAL_W + 50 for it in play.items), "items stay inside the new canvas")
        check(play.bg.W == config.LOGICAL_W, "background rebuilt for the new width")
    d.shot("resized_play")
    d.key(pg.K_ESCAPE)                                  # pause, then back to the menu for the next walk
    d.focus_to(d.top.menu, 2)
    d.key(pg.K_RETURN)
    check(d.stack == ["menu"], f"main menu again ({d.stack})")
    check(d.top.menu.center_x == config.LOGICAL_W // 2, "menu re-centred for the canvas")


def walk_game(d: Driver) -> None:
    app = d.app
    menu = d.top.menu
    d.focus_to(menu, 0)
    d.key(pg.K_RETURN)
    play = play_scene(d)
    check(play.state == "countdown" and play.score == 0 and play.lives == config.START_LIVES, "round starts fresh")
    d.steps(30)
    d.shot("play_countdown")

    # Movement allowed during the countdown, no spawns
    x0 = play.player.pos.x
    d.key(pg.K_d, hold=True)
    d.steps(20)
    d.release(pg.K_d)
    check(play.player.pos.x > x0 + 20, "D moves the paddle during the countdown")
    check(not play.items, "no spawns during the countdown")
    # From here on only items placed by the test exist (stub removed after the round)
    play.spawner.update = lambda dt, params: []
    wait_for(d, lambda: play.state == "playing", 4 * 60, "countdown ends")

    # Pause -> settings -> back -> resume
    d.key(pg.K_ESCAPE)
    check(d.stack == ["play", "pause"], f"Esc pauses ({d.stack})")
    d.steps(10)
    d.shot("pause")
    t_before = play.round_time
    pm = d.top.menu
    d.focus_to(pm, 1)
    d.key(pg.K_RETURN)
    check(d.stack == ["play", "pause", "settings"], f"settings over pause ({d.stack})")
    d.steps(10)
    d.shot("settings_over_pause")
    d.key(pg.K_ESCAPE)
    check(d.stack == ["play", "pause"], f"Esc back to pause ({d.stack})")
    d.key(pg.K_ESCAPE)
    check(d.stack == ["play"], f"Esc resumes ({d.stack})")
    check(abs(play.round_time - t_before) < 0.05, "game frozen while paused")

    # Focus loss pauses, P resumes
    pg.event.post(pg.event.Event(pg.WINDOWFOCUSLOST))
    d.steps(1)
    check(d.stack == ["play", "pause"], f"focus loss pauses ({d.stack})")
    d.key(pg.K_p)
    check(d.stack == ["play"], f"P resumes ({d.stack})")

    play.items.clear()

    # Catches + combo multiplier
    for i in range(5):
        drop_on_player(d, play, "common")
    check(play.score == 50 and play.combo.count == 5 and play.combo.multiplier == 2, "5 catches -> combo x2")
    check(play._multiplier() == 1, "level 1 keeps scoring at x1")
    drop_on_player(d, play, "rare")
    check(play.score == 50 + 25, f"rare scored with x1 on level 1 ({play.score})")
    drop_on_player(d, play, "epic")
    check(play.score == 75 + 50, f"epic scored with x1 on level 1 ({play.score})")
    check(play.level == 2, f"level up at 120+ ({play.level})")
    check(play._multiplier() == 2, "combo multiplier applies from level 2")
    check(play.banner > 0, "level-up banner shown")
    d.steps(12)
    d.shot("play_levelup")

    # Power-ups
    drop_on_player(d, play, "powerup", "magnet")
    drop_on_player(d, play, "powerup", "slow")
    drop_on_player(d, play, "powerup", "wide")
    check(all(play.powerups.is_active(n) for n in ("magnet", "slow", "wide")), "timed power-ups active")
    drop_on_player(d, play, "powerup", "shield")
    check(play.player.shield == 1, "shield on")
    lives = play.lives
    drop_on_player(d, play, "powerup", "heart")
    check(play.lives == lives + 1, "heart adds a life")
    d.steps(30)
    check(play.player.width > config.PLAYER_W * 1.3, "wide power-up widens the paddle")
    drop_on_player(d, play, "common")
    d.steps(6)
    d.shot("play")

    # Bombs: shield absorbs the first one
    lives, combo = play.lives, play.combo.count
    drop_on_player(d, play, "bomb")
    check(play.player.shield == 0 and play.lives == lives and play.combo.count == 0,
          f"shield absorbs a bomb (lives {play.lives}, combo was {combo})")
    drop_on_player(d, play, "bomb")
    check(play.lives == lives - 1 and play.flash > 0, "bomb without shield costs a life")
    d.steps(4)
    d.shot("play_bomb")

    # Miss
    lives = play.lives
    drop_miss(d, play)
    check(play.lives == lives - 1 and play.combo.count == 0, "a missed good item costs a life")

    # Game over
    score, level = play.score, play.level
    best_combo = play.combo.best
    while play.lives > 0:
        drop_miss(d, play)
    check(play.state == "dying", "slow-mo before game over")
    d.steps(10)
    d.shot("play_dying")
    wait_for(d, lambda: d.stack == ["gameover"], 120, "game over scene after slow-mo")
    go = d.top
    check((go.score, go.level, go.best_combo, go.is_new_record) == (score, level, best_combo, True),
          f"gameover kwargs ({go.score}, {go.level}, {go.best_combo}, {go.is_new_record})")
    with open(os.path.join(TEMP_DATA, "save.json"), encoding="utf-8") as f:
        save = json.load(f)
    check(save["best_score"] == score and save["games_played"] == 1, f"save.json written ({save})")
    d.steps(150)
    d.shot("gameover")

    # Retry -> new round, then back to the menu through pause
    d.key(pg.K_RETURN)
    play = play_scene(d)
    check(play.state == "countdown" and play.score == 0 and play.lives == config.START_LIVES
          and not play.items and play.best == score, "retry starts a fresh round with the new best")
    vars(play.spawner).pop("update", None)          # remove the test stub again
    d.key(pg.K_ESCAPE)
    pm = d.top.menu
    d.focus_to(pm, 2)
    d.key(pg.K_RETURN)
    check(d.stack == ["menu"], f"pause -> main menu ({d.stack})")
    d.steps(30)
    d.shot("menu_after")


#(a2) boss fight walkthrough

def start_practice_boss(d: Driver, number: int):
    """From the menu into a practice round that starts at boss `number`."""
    app = d.app
    check(d.stack == ["menu"], f"at the menu before boss {number} ({d.stack})")
    app.start_boss = number
    d.focus_to(d.top.menu, 0)
    d.key(pg.K_RETURN)
    play = play_scene(d)
    check(play.practice and play.level == config.BOSS_EVERY * number, f"practice round starts at level {play.level}")
    return play


def walk_boss(d: Driver) -> None:
    """Boss 1 through the real scenes: intro, damage, beam, ball, hurt, resize, pause, reward, resume; then boss 2 game over."""
    from game.entities.boss_items import EnergyItem, HelperBall, Projectile
    app = d.app
    app.autoplay = False
    check(app_mod.parse_args(["--start-boss", "2"]).start_boss == 2, "--start-boss flag parsed")
    save_before = json.load(open(os.path.join(TEMP_DATA, "save.json"), encoding="utf-8"))
    play = start_practice_boss(d, 1)
    ctrl = play.boss
    wait_for(d, lambda: play.boss_mode, 6 * 60, "boss fight starts right after the countdown")
    play.hurt_timer = 1e6                               # scripted part: shots cannot hurt unless a check asks them to
    check(ctrl.state == "intro" and ctrl.boss.number == 1 and ctrl.boss.kind == 0, f"boss 1 intro ({ctrl.state})")
    check(not play.items and play.next_boss_level == config.BOSS_EVERY, "ordinary items are gone, level frozen at 10")
    hud = play._boss_hud()
    check(hud is not None and hud["state"] == "intro" and hud["hp_frac"] == 1.0, f"HUD boss state in the intro ({hud})")
    d.steps(40)
    d.shot("boss_intro")
    wait_for(d, lambda: ctrl.state == "fight", 6 * 60, "intro ends and the fight begins")
    check(ctrl.damageable and ctrl.time_left > config.BOSS_TIME_LIMIT - 5, "fight clock running")
    d.shot("boss_fight")

    # Balls fall from the sky on their own, energy does not; ordinary spawns stay off
    wait_for(d, lambda: any(isinstance(h, HelperBall) for h in play.helpers), 10 * 60, "a helper ball falls")
    check(not any(isinstance(h, EnergyItem) for h in play.helpers), "no energy item without a ball hit")
    check(not play.items, "no ordinary items during the fight")

    # The beam needs energy and a target
    play.beams.clear()
    play.energy = config.BOSS_ENERGY_NEED - 1
    d.key(pg.K_SPACE)
    check(not play.beams and play.energy == config.BOSS_ENERGY_NEED - 1, "Space without enough energy does nothing")
    play.energy = config.BOSS_ENERGY_NEED
    play.player.pos.x = 30 if ctrl.boss.pos.x > config.LOGICAL_W / 2 else config.LOGICAL_W - 30
    hp, score = ctrl.boss.hp, play.score
    d.key(pg.K_SPACE)
    check(play.beams and not play.beams[-1].hit and ctrl.boss.hp == hp, "a beam that misses does no damage")
    check(play.energy == 0, "the shot used up the energy")
    play.energy = config.BOSS_ENERGY_NEED
    play.player.pos.x = ctrl.boss.pos.x
    d.key(pg.K_SPACE)
    check(play.beams[-1].hit and abs((hp - ctrl.boss.hp) - config.beam_damage(1)) < 1e-6,
          f"beam took {hp - ctrl.boss.hp:.2f} hp")
    check(play.score > score, "damage scores points")
    d.steps(4)
    d.shot("boss_beam")

    # Ball: caught -> flies -> hits the boss for ball_base_damage(1)
    play.helpers.clear()
    x = play.player.pos.x
    ball = HelperBall(x, catch_y(config.BOSS_BALL_RADIUS) - 30)
    ball.vel.y = 300
    play.helpers.append(ball)
    wait_for(d, lambda: ball.state == "flying", 60, "paddle catches the falling ball")
    check(ball.vel.y < 0, "a caught ball launches upwards")
    hp = ctrl.boss.hp
    b = ctrl.boss
    ball.pos.update(b.pos.x, b.pos.y + b.half_h + 60)
    ball.vel.update(0, -config.BOSS_BALL_SPEED)
    wait_for(d, lambda: ctrl.boss.hp < hp, 60, "the ball hits the boss")
    check(abs((hp - ctrl.boss.hp) - config.ball_base_damage(1)) < 1e-6, f"ball took {hp - ctrl.boss.hp:.2f} hp")
    check(play.ball_hits == 1 and not any(isinstance(h, EnergyItem) for h in play.helpers), "one ball hit: no energy yet")
    ball.pos.update(b.pos.x, b.pos.y + b.half_h + 60)           # second hit: an energy item falls from the boss
    ball.vel.update(0, -config.BOSS_BALL_SPEED)
    d.steps(30)
    wait_for(d, lambda: any(isinstance(h, EnergyItem) for h in play.helpers), 60, "every 2nd ball hit drops an energy item")
    item = next(h for h in play.helpers if isinstance(h, EnergyItem))
    check(abs(item.pos.y - (b.pos.y + b.half_h)) < 120 or item.pos.y > b.pos.y, "the energy item comes from the boss")
    play.player.pos.x = item.pos.x
    energy = play.energy
    wait_for(d, lambda: play.energy == energy + 1, 5 * 60, "the paddle collects the falling energy item")
    play.helpers.clear()

    # Losing the ball costs no life, only time: the next ball is held back for BOSS_BALL_RESPAWN
    lives = play.lives
    ball = HelperBall(60, config.PLAYER_Y + 40)
    ball.state = "flying"
    ball.vel.update(0, config.BOSS_BALL_SPEED)
    play.helpers.append(ball)
    wait_for(d, lambda: play.stats.get("balls_lost", 0) == 1, 120, "a lost ball is counted")
    check(play.lives == lives, f"a lost ball costs no life ({lives} -> {play.lives})")
    check(ctrl._ball_t >= config.BOSS_BALL_RESPAWN - 0.1, "the next ball waits after a loss")
    play.lives = config.START_LIVES

    # A shot costs a life, then a second of invulnerability
    play.projectiles.clear()
    play.hurt_timer = 0.0
    lives = play.lives
    play.player.shield = 0
    pr = Projectile(play.player.pos.x, play.player.pos.y - 30, 0, 200)
    play.projectiles.append(pr)
    d.steps(6)
    check(play.lives == lives - 1 and play.hurt_timer > 0.5, f"a boss shot costs a life ({lives} -> {play.lives})")
    pr = Projectile(play.player.pos.x, play.player.pos.y - 30, 0, 200)
    play.projectiles.append(pr)
    d.steps(6)
    check(play.lives == lives - 1, "no second hit while invulnerable")
    play.player.shield = 1
    play.hurt_timer = 0.0
    pr = Projectile(play.player.pos.x, play.player.pos.y - 30, 0, 200)
    play.projectiles.append(pr)
    d.steps(6)
    check(play.player.shield == 0 and play.lives == lives - 1, "a shield soaks a boss shot")
    play.hurt_timer = 1e6
    d.shot("boss_hurt")

    # Resize and pause in the middle of the fight
    for fs in (True, False):
        app.settings.fullscreen = fs
        app.apply_settings()
        d.steps(20)
        b = ctrl.boss
        check(d.stack == ["play"] and b.half_w <= b.pos.x <= config.LOGICAL_W - b.half_w,
              f"boss stays inside the resized canvas (x={b.pos.x:.0f}, w={config.LOGICAL_W})")
        check(all(0 <= p.pos.x <= config.LOGICAL_W for p in play.helpers), "helpers stay inside the resized canvas")
    left = ctrl.time_left
    d.key(pg.K_ESCAPE)
    check(d.stack == ["play", "pause"], f"Esc pauses the boss fight ({d.stack})")
    d.steps(30)
    check(ctrl.time_left == left, "boss clock frozen while paused")
    d.key(pg.K_ESCAPE)
    check(d.stack == ["play"], "resumed")

    # Defeat: wipe the field, bonus, lives, reward scene
    play.lives = 2
    score = play.score
    ctrl.damage(1e9)
    wait_for(d, lambda: ctrl.state == "victory" and play.bosses_defeated == 1 and not play.projectiles and not play.helpers,
             30, "victory pays the bonus and clears the field")
    check(play.score - score >= config.BOSS_CLEAR_BONUS and play.lives == play.max_lives,
          f"victory bonus and full lives (score +{play.score - score}, lives {play.lives})")
    d.steps(30)
    d.shot("boss_victory")
    wait_for(d, lambda: d.stack == ["play", "boss_reward"], int((config.BOSS_VICTORY_TIME + 1) * 60), "reward scene opens")
    check(type(d.top).__name__ == "BossRewardScene" and "boss_reward" not in app.placeholders, "real reward scene")
    d.steps(60)
    d.shot("boss_reward")
    d.key(pg.K_ESCAPE)
    check(d.stack == ["play", "boss_reward"], "Esc cannot skip the reward")
    d.key(pg.K_d)
    d.key(pg.K_RETURN)
    check(d.stack == ["play"], f"picking an upgrade returns to the round ({d.stack})")
    check(not play.boss_mode and ctrl.state == "idle" and play.next_boss_level == 2 * config.BOSS_EVERY
          and sum(play.upgrades.values()) == 1 and play.level == config.BOSS_EVERY,
          f"back to normal play (boss_mode={play.boss_mode}, upgrades={play.upgrades}, next={play.next_boss_level})")
    wait_for(d, lambda: play.items, 6 * 60, "ordinary items come back after the reward")
    check(play.bosses_defeated == 1, "one boss defeated")

    # Boss 2 through the normal level trigger; losing there ends the round without a high score
    from game.systems import difficulty
    play.score = difficulty.score_for_level(2 * config.BOSS_EVERY)
    play._check_level()
    check(play.boss_mode and ctrl.boss.number == 2 and ctrl.boss.kind == 1, "level 20 starts boss 2 (second design)")
    wait_for(d, lambda: ctrl.state == "fight", 6 * 60, "boss 2 fight begins")
    d.shot("boss_2")
    play.projectiles.clear()
    play.player.shield = 0
    play.hurt_timer = 0.0
    play.lives = 1
    play.projectiles.append(Projectile(play.player.pos.x, play.player.pos.y - 30, 0, 200))
    d.steps(4)
    check(play.state == "dying", "the last life lost in a boss fight starts the death slow-mo")
    wait_for(d, lambda: d.stack == ["gameover"], 120, "game over after the boss fight")
    save_after = json.load(open(os.path.join(TEMP_DATA, "save.json"), encoding="utf-8"))
    check(save_after == save_before, "practice rounds do not touch the high score file")
    d.steps(30)
    d.key(pg.K_ESCAPE)
    check(d.stack == ["menu"], f"back at the menu ({d.stack})")
    app.start_boss = 0
    check(all(v == 1.0 for v in config.UPGRADE_MULT.values()), "upgrades reset when leaving the round")


#(b) autoplay soak

def autoplay_boss(d: Driver, number: int, max_seconds: float) -> dict:
    """The bot plays a practice round that starts at boss `number` (reward auto-picked). Winning is not required:
    energy only comes from ball hits now and the bot is weak at juggling a ball while dodging."""
    app = d.app
    app.autoplay = True
    app.start_boss = number
    app.settings.fps_cap = 0
    play = app.scenes.get("play")
    play.rng.seed(7000 + number)                        # reproducible fights (the bot itself is deterministic)
    app.scenes.switch("play")
    app.scenes.apply_pending()
    out = {"won": False, "seconds": 0.0, "lives_left": 0, "max_phase": 1}
    for i in range(int(max_seconds / DT)):
        app.step(DT)
        top = app.scenes.top_name
        if top == "play" and play.boss_mode and play.boss.boss is not None:
            out["max_phase"] = max(out["max_phase"], play.boss.boss.phase)
        if top == "gameover":
            break
        if top == "play" and play.bosses_defeated >= number and not play.boss_mode:
            out["won"] = True
            break
    out["seconds"] = (i + 1) * DT
    out["lives_left"] = play.lives
    app.start_boss = 0
    return out


def autoplay(d: Driver, seconds: float) -> dict:
    app = d.app
    app.start_boss = 0
    app.autoplay = True
    app.settings.fps_cap = 0
    app.scenes.switch("play")
    app.scenes.apply_pending()
    frames = int(seconds / DT)
    times = []
    max_level, best_score, rounds, last = 1, 0, 1, None
    play = app.scenes.get("play")
    shot_taken = False
    for i in range(frames):
        t0 = time.perf_counter()
        app.step(DT)
        times.append(time.perf_counter() - t0)
        top = app.scenes.top_name
        if top == "play":
            max_level = max(max_level, play.level)
            best_score = max(best_score, play.score)
            if not shot_taken and play.level >= 3 and len(play.items) >= 4:
                d.shot("autoplay")
                shot_taken = True
        if top == "play" and last == "gameover":
            rounds += 1
        last = top
    if not shot_taken:
        d.shot("autoplay")
    times.sort()
    return {
        "sim_seconds": seconds,
        "rounds": rounds,
        "max_level": max_level,
        "best_score": best_score,
        "avg_ms": 1000 * sum(times) / len(times),
        "p95_ms": 1000 * times[int(len(times) * 0.95)],
        "max_ms": 1000 * times[-1],
    }


#Main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--autoplay-seconds", type=float, default=90.0)
    ap.add_argument("--boss-seconds", type=float, default=240.0, help="simulated time allowed per boss for the bot")
    ap.add_argument("--keep-data", action="store_true", help="do not delete the temp data dir")
    args = ap.parse_args()

    before = real_profile_snapshot()
    app = None
    code = 0
    try:
        app = App(["--start-scene", "menu"])
        d = Driver(app)
        check(os.path.normcase(paths.user_data_dir()) == os.path.normcase(TEMP_DATA), "user data dir is the temp dir")
        walk_menus(d)
        walk_game(d)
        walk_resize(d)
        walk_boss(d)
        for number in (1, 2, 3):                        # the bot plays every boss design without crashing or hanging
            r = autoplay_boss(d, number, args.boss_seconds)
            print("BOSS {n}: bot {res} in {seconds:.0f}s simulated, phase {max_phase}, lives left {lives_left}".format(
                n=number, res="won" if r["won"] else "lost", **r))
            check(r["seconds"] > 10, f"autoplay bot plays boss {number} through without a crash or hang ({r})")
            if app.scenes.top_name != "play":
                d.steps(5)
        stats = autoplay(d, args.autoplay_seconds)
        print("AUTOPLAY: {sim_seconds:.0f}s simulated, rounds={rounds}, max level={max_level}, "
              "best score={best_score}, update+draw avg={avg_ms:.2f} ms p95={p95_ms:.2f} ms "
              "max={max_ms:.1f} ms".format(**stats))
        if args.autoplay_seconds >= 60:            # level 3 needs about a minute of play
            check(stats["max_level"] >= 3, f"autoplay bot reaches level 3+ ({stats['max_level']})")
        for name in ("settings.json", "save.json"):
            check(os.path.isfile(os.path.join(TEMP_DATA, name)), f"{name} written to temp data dir")
        check(real_profile_snapshot() == before, "real profile untouched")
        print(f"SMOKE TEST PASSED ({len([c for c in CHECKS if c])} checks); screenshots in {OUT}")
    except Exception:
        traceback.print_exc()
        print("SMOKE TEST FAILED")
        code = 1
    finally:
        if app is not None:
            app.close()
        paths.user_data_dir = _real_data_dir
        if not args.keep_data:
            shutil.rmtree(TEMP_DATA, ignore_errors=True)
        else:
            print("data kept in", TEMP_DATA)
    return code


if __name__ == "__main__":
    sys.exit(main())
