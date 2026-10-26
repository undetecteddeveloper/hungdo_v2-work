"""Play scene: the actual game round (countdown, spawning, catching, effects, HUD, bot)."""
import logging
import math
import random

import pygame as pg

from .. import config
from ..entities.items import Item, catch_y
from ..entities.player import Player
from ..i18n import t
from ..scene import Scene
from ..systems import difficulty
from ..systems.combo import Combo
from ..systems.floating_text import FloatingTexts
from ..systems.highscore import HighScore
from ..systems.powerups import PowerUps
from ..systems.shake import ScreenShake
from ..systems.spawner import Spawner
from ..ui.hud import Hud
from ..ui.widgets import ease_out_back, make_background, make_particles, neon_text

log = logging.getLogger(config.LOGGER_NAME)
PAL = config.PALETTE

LEFT_KEYS = (pg.K_a, pg.K_LEFT)
RIGHT_KEYS = (pg.K_d, pg.K_RIGHT)
PAUSE_KEYS = (pg.K_ESCAPE, pg.K_p)

GO_TIME = 0.7                       # "GO!" stays on screen this long (spawning already runs)
DEATH_TIME = 0.6                    # slow-mo before game over (real seconds)
DEATH_SCALE = 0.25                  # world speed during the slow-mo
BANNER_TIME = 1.7                   # level-up banner duration
FLASH_DECAY = 2.6                   # red flash fade (1/s)
CATCH_VOLUME = 0.75                 # catch fires very often: keep it a bit quieter
PREWARM_COLORS = [PAL["cyan"], PAL["magenta"], PAL["yellow"], PAL["red"], PAL["orange"],
                  PAL["green"], PAL["purple"], PAL["white"], (70, 150, 255)]

CATCH_SFX = {"common": "catch", "rare": "catch_rare", "epic": "catch_epic"}


def level_hue(level: int) -> tuple:
    hues = config.LEVEL_HUES
    return hues[(max(1, level) - 1) % len(hues)]


def _sign(x: float) -> int:
    return (x > 0) - (x < 0)


class PlayScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.rng = random.Random()
        self.bg = make_background(app)
        self.particles = make_particles(600)
        self.texts = FloatingTexts(app.assets)
        self.shake = ScreenShake()
        self.hud = Hud(app)
        self.player = Player()
        self.spawner = Spawner(self.rng)
        self.powerups = PowerUps()
        self.combo = Combo()
        self.items = []
        self._flash_surf = None
        self._prewarmed = False
        self.reset_round()

    #Round state
    def reset_round(self) -> None:
        """Fresh round: every system reset, countdown armed."""
        self.score = 0
        self.level = 1
        self.lives = config.START_LIVES
        self.state = "countdown"            # countdown -> playing -> dying -> (gameover scene)
        self.countdown = float(config.COUNTDOWN_SECONDS)
        self._count_shown = None
        self.go_timer = 0.0
        self.death_timer = 0.0
        self.round_time = 0.0
        self.flash = 0.0
        self.banner = 0.0
        self.held = {-1: False, 1: False}
        self.items = []
        self.player.reset()
        self.player.color = level_hue(1)
        self.spawner.reset()
        self.powerups.reset()
        self.combo.reset()
        self.shake.reset()
        self.texts.clear()
        if self.particles is not None:
            self.particles.clear()
        self.hud.reset()
        self.bg.set_accent(level_hue(1))
        if hasattr(self.bg, "speed"):
            self.bg.speed = 1.0
        self.best = self._load_best()
        self.stats = {"caught": 0, "missed": 0, "bombs": 0, "powerups": 0}

    @staticmethod
    def _load_best() -> int:
        try:
            return int(HighScore().best_score)
        except Exception as e:              # never let a bad save block the game
            log.warning("Could not read best score: %s", e)
            return 0

    #Scene hooks
    def on_enter(self, **kwargs):
        self.reset_round()
        self._sync_keys()                   # Retry while still holding A/D must keep moving
        self._prewarm()
        self.app.audio.play_music("game")

    def on_resume(self):
        self._sync_keys()

    def _sync_keys(self) -> None:
        """Key events missed while another scene was on top: resync from the real keyboard."""
        keys = pg.key.get_pressed()
        self.held[-1] = any(keys[k] for k in LEFT_KEYS)
        self.held[1] = any(keys[k] for k in RIGHT_KEYS)

    def _prewarm(self) -> None:
        if self._prewarmed:
            return
        self._prewarmed = True
        try:
            from ..systems.particles import prewarm
            prewarm(PREWARM_COLORS)
        except Exception as e:
            log.debug("Particle prewarm skipped: %s", e)

    def pause(self) -> None:
        if self.state != "dying" and self.app.scenes.top is self and not self.app.scenes.pending:
            self.app.scenes.push("pause")

    #Input
    def handle_event(self, event):
        if event.type == pg.KEYDOWN:
            if event.key in PAUSE_KEYS:
                self.pause()
            elif event.key in LEFT_KEYS:
                self.held[-1] = True
            elif event.key in RIGHT_KEYS:
                self.held[1] = True
        elif event.type == pg.KEYUP:
            if event.key in LEFT_KEYS:
                self.held[-1] = False
            elif event.key in RIGHT_KEYS:
                self.held[1] = False
        elif event.type == pg.WINDOWFOCUSLOST:
            self.held[-1] = self.held[1] = False
            self.pause()

    def _direction(self) -> int:
        if self.app.autoplay and self.state != "dying":
            return self._bot_direction()
        d = int(self.held[1]) - int(self.held[-1])
        return d

    #Update
    def update(self, dt):
        world_dt = dt
        if self.state == "dying":
            world_dt = dt * DEATH_SCALE
            self.death_timer += dt
        self.bg.update(world_dt)
        if self.particles is not None:
            self.particles.update(world_dt)
        self.texts.update(world_dt)
        self.shake.update(dt, self.app.settings.screen_shake)
        self.flash = max(0.0, self.flash - FLASH_DECAY * dt)
        self.banner = max(0.0, self.banner - dt)
        self.go_timer = max(0.0, self.go_timer - dt)

        if self.state == "countdown":
            self._update_countdown(dt)
            self.player.update(dt, self._direction())   # movement allowed, no spawns
            return
        self._step_world(world_dt)
        if self.state == "dying" and self.death_timer >= DEATH_TIME:
            self._finish()

    def _update_countdown(self, dt) -> None:
        self.countdown -= dt
        n = math.ceil(self.countdown)
        if n != self._count_shown and n > 0:
            self._count_shown = n
            self.app.audio.play("countdown")
        if self.countdown <= 0:
            self.state = "playing"
            self.go_timer = GO_TIME
            self.app.audio.play("go")

    def _step_world(self, dt) -> None:
        params = difficulty.params_for_level(self.level)
        playing = self.state == "playing"
        if playing:
            self.round_time += dt
        ts = self.powerups.time_scale
        self.powerups.update(dt)                       # real (unscaled) time
        self.player.set_wide(self.powerups.is_active("wide"))
        self.player.update(dt, self._direction())
        if self.player.wall_hit:
            self.shake.add(0.12)

        if playing:
            self.spawner.allow_heart = self.lives < config.MAX_LIVES
            self.items.extend(self.spawner.update(dt * ts, params))

        magnet_x = self.player.pos.x if self.powerups.is_active("magnet") else None
        gravity = params.gravity
        for it in self.items:
            it.update(dt, gravity, ts, magnet_x)

        if playing:
            catch = self.player.catch_rect
            for it in self.items:
                if it.alive and catch.colliderect(it.rect):
                    it.alive = False
                    self._on_catch(it)
                    if self.state != "playing":
                        break
            for it in self.items:
                if it.fell and it.is_good and self.state == "playing":
                    it.fell = False                    # count each miss once
                    self._on_miss(it)
        self.items = [it for it in self.items if it.alive]

    #Rules
    def _on_catch(self, it: Item) -> None:
        pos = (it.pos.x, min(it.pos.y, self.player.pos.y - 14))
        if it.kind == "bomb":
            self._on_bomb(pos)
        elif it.kind == "powerup":
            self._on_powerup(it, pos)
        else:
            self._on_good(it, pos)

    def _multiplier(self) -> int:
        """Combo multiplier; level 1 stays at x1 so the easy opening lasts longer."""
        return self.combo.multiplier if self.level >= 2 else 1

    def _on_good(self, it: Item, pos) -> None:
        pts = it.value * self._multiplier()
        self.score += pts
        self.stats["caught"] += 1
        up = self.combo.hit()
        self.player.bump()
        self.app.audio.play(CATCH_SFX[it.kind], CATCH_VOLUME if it.kind == "common" else 1.0)
        big = it.kind != "common"
        if self.particles is not None:
            self.particles.burst(pos, it.color, count=26 if big else 16, speed=(80, 380 if big else 300),
                                 life=(0.25, 0.7), size=(2, 5), gravity=420, angle=-math.pi / 2, spread=math.pi * 1.3)
            if it.kind == "epic":
                self.particles.ring(pos, it.color, radius=70)
        self._popup(f"+{pts}", (pos[0], pos[1] - 26), it.color, 30 if big else 26)
        if up and self.level >= 2:
            m = self.combo.multiplier
            self.app.audio.play("combo_up")
            self._popup(f"x{m} COMBO", (self.player.pos.x, self.player.pos.y - 90), PAL["yellow"], 34)
            if self.particles is not None:
                self.particles.ring(self.player.pos, PAL["yellow"], radius=110)
            self.bg.pulse(0.4)
        self._check_level()

    def _on_bomb(self, pos) -> None:
        self.stats["bombs"] += 1
        self.combo.break_()
        if self.player.shield > 0:
            self.player.shield = 0
            self.app.audio.play("shield_break")
            self.shake.add(0.3)
            self._popup(t("play.shield_break"), (pos[0], pos[1] - 30), PAL["cyan"], 28)
            if self.particles is not None:
                self.particles.ring(self.player.pos, PAL["cyan"], radius=90)
                self.particles.burst(pos, PAL["cyan"], count=30, speed=(120, 420), life=(0.3, 0.7))
            return
        self.app.audio.play("bomb")
        self.shake.add(0.75)
        self.flash = 1.0
        if self.particles is not None:
            for col, n in ((PAL["red"], 40), (PAL["orange"], 30), (PAL["yellow"], 16)):
                self.particles.burst(pos, col, count=n, speed=(120, 560), life=(0.35, 1.0), size=(2, 6))
            self.particles.ring(pos, PAL["orange"], radius=130, duration=0.55, width=6)
        self._lose_life()

    def _on_powerup(self, it: Item, pos) -> None:
        name = it.power
        self.stats["powerups"] += 1
        self.app.audio.play("powerup")
        label = t(f"howto.{name}.name").upper()
        if name == "shield":
            self.player.shield = 1
            label = t("play.shield")
        elif name == "heart":
            if self.lives < config.MAX_LIVES:
                self.lives += 1
            self.app.audio.play("heart")
            label = t("play.life")
        else:
            self.powerups.activate(name)
        self.player.bump(0.4)
        self._popup(label, (pos[0], pos[1] - 30), it.color, 28)
        if self.particles is not None:
            self.particles.ring(pos, it.color, radius=80)
            self.particles.burst(pos, it.color, count=22, speed=(60, 300), life=(0.3, 0.8))

    def _on_miss(self, it: Item) -> None:
        self.stats["missed"] += 1
        self.combo.break_()
        self.app.audio.play("miss")
        self.shake.add(0.45)
        self.flash = max(self.flash, 0.8)
        x = min(max(it.pos.x, 20), config.LOGICAL_W - 20)
        if self.particles is not None:
            self.particles.burst((x, config.LOGICAL_H - 6), PAL["red"], count=24, speed=(100, 380),
                                 life=(0.3, 0.7), angle=-math.pi / 2, spread=math.pi * 0.8)
        self._popup(t("play.miss"), (x, config.LOGICAL_H - 70), PAL["red"], 28)
        self._lose_life()

    def _popup(self, text: str, pos, color, size: int = 28) -> None:
        """Floating text, nudged inward so it never leaves the screen."""
        half = self.app.assets.font(size, "bold").size(text)[0] / 2 + 12
        x = min(max(pos[0], half), config.LOGICAL_W - half)
        self.texts.spawn(text, (x, pos[1]), color, size)

    def _lose_life(self) -> None:
        self.lives = max(0, self.lives - 1)
        if self.lives <= 0 and self.state == "playing":
            self.state = "dying"
            self.death_timer = 0.0
            self.shake.add(0.5)
            self.app.audio.stop_music(600)

    def _check_level(self) -> None:
        new = difficulty.level_for_score(self.score)
        if new <= self.level:
            return
        self.level = new
        hue = level_hue(new)
        self.banner = BANNER_TIME
        self.app.audio.play("level_up")
        self.bg.set_accent(hue)
        self.bg.pulse(1.0)
        if hasattr(self.bg, "speed"):
            self.bg.speed = min(2.2, 1.0 + 0.08 * (new - 1))
        self.player.color = hue
        if self.particles is not None:
            self.particles.ring((config.LOGICAL_W / 2, config.LOGICAL_H * 0.4), hue, radius=220, duration=0.7, width=5)

    def _finish(self) -> None:
        """Submit the result, then hand over to the game-over scene (it plays the sound)."""
        is_new = False
        try:
            is_new = HighScore().submit(self.score, self.level, self.combo.best)
        except Exception as e:
            log.warning("Could not submit high score: %s", e)
        self.state = "over"
        log.info("Round over: score=%d level=%d best_combo=%d time=%.1fs %s", self.score, self.level,
                 self.combo.best, self.round_time, self.stats)
        self.app.scenes.switch("gameover", score=self.score, level=self.level,
                               best_combo=self.combo.best, is_new_record=is_new)

    #Autoplay bot
    def _eta(self, it: Item, gravity: float, ts: float):
        """(real seconds, x) until `it` reaches the paddle line; analytic, walls folded."""
        dy = catch_y(it.radius) - it.pos.y
        if dy <= 0:
            return 0.0, it.pos.x
        g = max(1.0, gravity * it.gravity_scale)
        v, vt = max(0.0, it.vel.y), it.terminal
        t_term = max(0.0, (vt - v) / g)
        d_term = v * t_term + 0.5 * g * t_term * t_term
        if dy <= d_term:
            tt = (-v + math.sqrt(v * v + 2 * g * dy)) / g
        else:
            tt = t_term + (dy - d_term) / vt
        # Sideways travel with wall reflections (restitution ignored: close enough for a bot)
        r = it.radius
        span = config.LOGICAL_W - 2 * r
        x = (it.pos.x - r + it.vel.x * tt) % (2 * span)
        x = (x if x <= span else 2 * span - x) + r
        return tt / max(ts, 0.05), x

    def _reach(self, t: float) -> float:
        """Distance the paddle can surely cover in t seconds (conservative)."""
        t = max(0.0, t - 0.05)
        a, v = config.PLAYER_ACCEL, config.PLAYER_MAX_SPEED
        ta = v / a
        return 0.5 * a * t * t if t <= ta else v * ta / 2 + v * (t - ta)

    def _bot_target(self):
        params = difficulty.params_for_level(self.level)
        ts = self.powerups.time_scale
        px, half = self.player.pos.x, self.player.width / 2
        cands, bombs = [], []
        for it in self.items:
            if not it.alive or it.pos.y > config.PLAYER_Y:
                continue
            eta, x = self._eta(it, params.gravity, ts)
            if it.kind == "bomb":
                bombs.append((eta, x, it.hit_radius))
            elif it.is_good or it.kind == "powerup":
                cands.append((eta, x, it))
        target = None
        cands.sort(key=lambda c: c[0])
        for eta, x, it in cands:
            # Powerups are optional: only chase them when nothing urgent is close in time
            if it.kind == "powerup" and any(c[0] < eta + 0.5 and c[2].is_good for c in cands):
                continue
            if abs(x - px) - half * 0.6 <= self._reach(eta):
                target = x
                break
        if target is None:
            target = cands[0][1] if cands else config.LOGICAL_W / 2
        # Dodge bombs landing soon: shift so the bomb misses the paddle but the target stays on it
        for eta, bx, br in bombs:
            if eta > 0.9:
                continue
            clear = half + br + 10
            if abs(target - bx) < clear:
                left, right = bx - clear, bx + clear
                opts = [o for o in (left, right) if half <= o <= config.LOGICAL_W - half]
                if opts:
                    target = min(opts, key=lambda o: abs(o - target))
        return target

    def _bot_direction(self) -> int:
        target = self._bot_target()
        x, v = self.player.pos.x, self.player.vel.x
        stop_x = x + v * abs(v) / (2 * config.PLAYER_FRICTION)    # where friction alone would stop us
        err = target - stop_x
        return _sign(err) if abs(err) > 5 else 0

    #Drawing
    def hud_state(self) -> dict:
        return {
            "score": self.score,
            "best": max(self.best, self.score),
            "lives": self.lives,
            "max_lives": config.MAX_LIVES,
            "level": self.level,
            "level_progress": difficulty.level_progress(self.score),
            "combo": self.combo.count,
            "multiplier": self._multiplier(),
            "powerups": self.powerups.active(),
            "shield": self.player.shield,
        }

    def draw(self, surf):
        tm = self.app.time
        self.bg.draw(surf)
        assets = self.app.assets
        for it in self.items:
            it.draw(surf, tm, assets)
        self.player.draw(surf, tm)
        if self.particles is not None:
            self.particles.draw(surf)
        self.texts.draw(surf)

        dx, dy = self.shake.offset
        if dx or dy:
            surf.scroll(dx, dy)                         # world shakes, HUD stays put

        if self.flash > 0:
            fl = self._flash()
            fl.set_alpha(int(255 * min(1.0, self.flash)))
            surf.blit(fl, (0, 0))
        if self.state == "dying":
            k = min(1.0, self.death_timer / DEATH_TIME)
            v = int(255 - 120 * k)
            surf.fill((v, v, v), special_flags=pg.BLEND_RGB_MULT)

        self.hud.draw(surf, self.hud_state())
        if self.state == "countdown":
            self._draw_countdown(surf)
        elif self.go_timer > 0:
            self._draw_go(surf)
        if self.banner > 0:
            self._draw_banner(surf)

    def _flash(self) -> pg.Surface:
        """Red edge vignette (built once), shown with surface alpha on misses/bombs."""
        if self._flash_surf is None:
            # Alpha from a smooth edge-distance falloff on a small grid, then upscaled (soft, no banding)
            w, h = config.LOGICAL_SIZE
            f = 10
            sw, sh = w // f, h // f
            small = pg.Surface((sw, sh), pg.SRCALPHA)
            depth = 110 / f
            for y in range(sh):
                for x in range(sw):
                    d = min(x + 0.5, sw - x - 0.5, y + 0.5, sh - y - 0.5)
                    k = max(0.0, 1.0 - d / depth)
                    small.set_at((x, y), (255, 40, 70, int(14 + 190 * k * k)))
            s = pg.transform.smoothscale(small, (w, h))
            self._flash_surf = s.convert_alpha() if pg.display.get_surface() is not None else s
        return self._flash_surf

    def _center_text(self, surf, s: str, size: int, color, scale: float, cy: int, alpha: int = 255) -> None:
        img = neon_text(self.app.assets, s, size, color, "display")
        if abs(scale - 1.0) > 0.01:
            img = pg.transform.smoothscale_by(img, max(0.05, scale))
        if alpha < 255:
            img = img.copy()
            img.set_alpha(alpha)
        surf.blit(img, img.get_rect(center=(config.LOGICAL_W // 2, cy)))

    def _draw_countdown(self, surf) -> None:
        n = max(1, math.ceil(self.countdown))
        frac = n - self.countdown                       # 0 -> 1 within the current number
        scale = 0.6 + 0.6 * ease_out_back(min(1.0, frac / 0.35))
        alpha = 255 if frac < 0.7 else int(255 * max(0.0, 1 - (frac - 0.7) / 0.3))
        color = (PAL["cyan"], PAL["magenta"], PAL["yellow"])[n % 3]
        self._center_text(surf, str(n), 140, color, scale, int(config.LOGICAL_H * 0.4), alpha)
        hint = self.app.assets.text(t("play.hint"), 22, PAL["dim"], "regular")
        surf.blit(hint, hint.get_rect(midbottom=(config.LOGICAL_W // 2, config.LOGICAL_H - 22)))

    def _draw_go(self, surf) -> None:
        k = 1 - self.go_timer / GO_TIME
        scale = 0.8 + 0.5 * ease_out_back(min(1.0, k / 0.3))
        alpha = int(255 * min(1.0, self.go_timer / (GO_TIME * 0.5)))
        self._center_text(surf, t("play.go"), 96, PAL["green"], scale, int(config.LOGICAL_H * 0.4), alpha)

    def _draw_banner(self, surf) -> None:
        age = BANNER_TIME - self.banner
        k_in = ease_out_back(min(1.0, age / 0.35))
        alpha = int(255 * min(1.0, self.banner / 0.4))
        cy = int(config.LOGICAL_H * 0.32)
        hue = level_hue(self.level)
        self._center_text(surf, t("play.level_up", n=self.level), 72, hue, 0.5 + 0.5 * k_in, cy, alpha)
        sub = neon_text(self.app.assets, t("play.level_sub"), 28, PAL["white"], "bold")
        if alpha < 255:
            sub = sub.copy()
            sub.set_alpha(alpha)
        surf.blit(sub, sub.get_rect(center=(config.LOGICAL_W // 2, cy + 62)))
