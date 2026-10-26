"""Play scene: the actual game round (countdown, spawning, catching, effects, HUD, bot)."""
import logging
import math
import random

import pygame as pg

from .. import config
from ..entities.boss_items import Beam, EnergyItem, HelperBall, Projectile
from ..entities.items import Item, catch_y
from ..entities.player import Player
from ..i18n import t
from ..render import boss_draw
from ..scene import Scene
from ..systems import difficulty
from ..systems import boss_bot
from ..systems.boss import BossController
from ..systems.combo import Combo
from ..systems.floating_text import FloatingTexts
from ..systems.highscore import HighScore
from ..systems.powerups import PowerUps
from ..systems.shake import ScreenShake
from ..systems.spawner import Spawner
from ..ui import boss_ui
from ..ui.hud import Hud
from ..ui.widgets import ease_out_back, make_background, make_particles, neon_text

log = logging.getLogger(config.LOGGER_NAME)
PAL = config.PALETTE

LEFT_KEYS = (pg.K_a, pg.K_LEFT)
RIGHT_KEYS = (pg.K_d, pg.K_RIGHT)
FIRE_KEYS = (pg.K_SPACE,)
PAUSE_KEYS = (pg.K_ESCAPE, pg.K_p)

CALLOUT_TIME = boss_ui.CALLOUT_TIME  # boss callout ("PHASE 2", "ENRAGED") duration
RESUME_GRACE = 1.6                  # no spawns for this long after the boss reward

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
        self.boss = BossController(self.rng)
        self.bot_balls = True                   # autoplay: go for helper balls (they are the only source of energy)
        self.items = []
        self._flash_surf = None
        self._prewarmed = False
        self.reset_round()

    #Round state
    def reset_round(self) -> None:
        """Fresh round: every system reset, countdown armed."""
        config.set_upgrade_mults()              # boss upgrades last for one round only
        self.score = 0
        self.level = 1
        self.max_lives = config.MAX_LIVES
        self.lives = config.START_LIVES
        # Boss fight state (see docs/ARCHITECTURE.md "Boss fights")
        self.boss.stop()
        self.boss_mode = False
        self.next_boss_level = config.BOSS_EVERY
        self.bosses_defeated = 0
        self.upgrades = {k: 0 for k in config.BOSS_UPGRADES}
        self.projectiles = []
        self.helpers = []                       # EnergyItem + HelperBall
        self.beams = []
        self.energy = 0
        self.ball_hits = 0                      # ball hits on the boss since the last energy item
        self.hurt_timer = 0.0                   # invulnerability after a boss hit
        self.callout = None                     # [text, colour, age]
        self.victory_bonus = 0
        self._bot_tick = 0
        self._bot_goal = None                   # autoplay: cached steering target in boss fights
        self._glow_warm = None                  # generator that pre-renders the boss glows during the intro
        self._warm_tick = 0
        self._death_fx_t = 0.0
        self.grace = 0.0                        # spawn pause after the reward scene
        self.reward_open = False
        start_boss = int(getattr(self.app, "start_boss", 0) or 0)
        self.practice = start_boss > 0          # --start-boss N: no high score, boss N right after the countdown
        self._practice_pending = self.practice
        if self.practice:
            self.level = config.BOSS_EVERY * start_boss
            self.next_boss_level = self.level
            self.bosses_defeated = start_boss - 1
            self.score = difficulty.score_for_level(self.level)
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
        self.player.color = level_hue(self.level)
        self.spawner.reset()
        self.powerups.reset()
        self.combo.reset()
        self.shake.reset()
        self.texts.clear()
        if self.particles is not None:
            self.particles.clear()
        self.hud.reset()
        self.bg.set_accent(level_hue(self.level))
        if hasattr(self.bg, "speed"):
            self.bg.speed = min(2.2, 1.0 + 0.08 * (self.level - 1))
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

    def on_exit(self):
        config.set_upgrade_mults()              # nothing outside a round keeps the boss upgrades

    def on_resize(self, old_w: int) -> None:
        """Canvas width changed mid-round (F11 / window size): keep the round going."""
        k = config.LOGICAL_W / old_w
        self.player.refit(old_w)
        for it in self.items:
            it.pos.x *= k
            it.vel.x *= k
            it.trail.clear()
        for obj in self.projectiles + self.helpers + self.beams:
            obj.on_resize(old_w)                # scales x (and trails) by LOGICAL_W / old_w
        self.boss.on_resize(old_w)
        if config.LOGICAL_W < old_w:
            self.projectiles.clear()            # a narrowed row of shots could leave a gap smaller than the paddle
        self._flash_surf = None                 # the red vignette is sized to the canvas
        self.spawner.clear_pending()            # landing predictions were for the old width
        self.texts.clear()
        if self.particles is not None:
            self.particles.clear()
        speed = getattr(self.bg, "speed", 1.0)
        self.bg = make_background(self.app)
        self.bg.set_accent(level_hue(self.level), instant=True)
        if hasattr(self.bg, "speed"):
            self.bg.speed = speed

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
            prewarm(PREWARM_COLORS + list(boss_draw.prewarm_colors()))
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
            elif event.key in FIRE_KEYS:
                self._fire_beam()
            elif event.key == pg.K_F9:                      # CHEAT (temporary): jump straight to the next boss
                self._cheat_boss()
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
        self.hurt_timer = max(0.0, self.hurt_timer - world_dt)
        if self.callout is not None:
            self.callout[2] += world_dt
            if self.callout[2] >= CALLOUT_TIME:
                self.callout = None

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
            self.app.audio.play("go")
            if self._practice_pending:              # --start-boss: straight into the fight
                self._practice_pending = False
                self._start_boss()
            else:
                self.go_timer = GO_TIME

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

        if playing and not self.boss_mode:
            self.spawner.allow_heart = self.lives < self.max_lives
            if self.grace > 0:
                self.grace = max(0.0, self.grace - dt)      # breather after a boss
            else:
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
        if self.boss_mode:
            self._step_boss(dt, ts, magnet_x, playing)

    #Boss fight
    def _boss_color(self) -> tuple:
        b = self.boss.boss
        return PAL[b.colors[0]] if b is not None else PAL["red"]

    def _poof(self, pos, color, count: int = 14) -> None:
        if self.particles is not None:
            self.particles.burst(pos, color, count=count, speed=(60, 300), life=(0.25, 0.6), size=(2, 4), gravity=200)

    def _callout(self, text: str, color) -> None:
        self.callout = [text, color, 0.0]

    def _power_mult(self) -> float:
        return 1.0 + config.UPGRADE_POWER_STEP * self.upgrades["power"]

    def _start_boss(self) -> None:
        """Level hit a multiple of BOSS_EVERY: ordinary items vanish and the boss comes down."""
        number = max(1, self.next_boss_level // config.BOSS_EVERY)
        self.boss_mode = True
        self.level = self.next_boss_level
        self.banner = 0.0
        for it in self.items:
            if it.alive:
                self._poof(it.pos, it.color, 10)        # no penalty for what disappears
        self.items.clear()
        self.spawner.clear_pending()
        self.combo.break_()
        self.energy = 0
        self.ball_hits = 0
        self.hurt_timer = 0.0
        self._death_fx_t = 0.0
        self.projectiles.clear()
        self.helpers.clear()
        self.beams.clear()
        boss = self.boss.start(number)
        self._glow_warm = boss_draw.prewarm_glows_iter(boss)    # first draws cost ms: spread them over the intro
        self._warm_tick = 0
        hue = PAL[boss.colors[0]]
        self.bg.set_accent(hue)
        self.bg.pulse(1.0)
        self.shake.add(0.5)
        self.app.audio.play("warning", 0.7)
        self.app.audio.play("boss_intro")
        log.info("Boss %d (design %d, cycle %d) at level %d", number, boss.kind, boss.cycle, self.level)

    def _step_boss(self, dt: float, ts: float, magnet_x, playing: bool) -> None:
        ctrl = self.boss
        if playing and self.app.autoplay:
            self._bot_fire()
        balls = sum(1 for h in self.helpers if isinstance(h, HelperBall) and h.alive)
        ctrl.paddle_scale = self.player.width / config.player_w()      # wide power-up: planner opens bigger gaps
        tick = ctrl.update(dt, self.player.pos.x, balls)
        if self._glow_warm is not None:
            self._warm_tick += 1
            if self._warm_tick % 3 == 0 and next(self._glow_warm, None) is None:
                self._glow_warm = None
        for s in tick.shots:
            self.projectiles.append(Projectile(s.x, s.y, s.vx, s.vy, s.radius, s.shape, s.color))
        for d in tick.drops:
            self.helpers.append(EnergyItem(d.x) if d.kind == "energy" else HelperBall(d.x))
        if tick.events:
            self._on_boss_events(tick.events)
        if ctrl.state == "victory" and self.particles is not None:
            self._death_fx_t -= dt
            if self._death_fx_t <= 0:
                self._death_fx_t = 0.08
                boss_draw.boss_death_fx(self.particles, ctrl.boss, self.rng)

        paddle = self.player.rect                   # HelperBall wants the real paddle, not the taller catch_rect
        for p in self.projectiles:
            p.update(dt, ts)
        for h in self.helpers:
            if isinstance(h, HelperBall):
                for ev in h.update(dt, ts, magnet_x, paddle, ctrl.hit_rect):
                    if playing:
                        self._on_ball_event(h, ev)
            else:
                h.update(dt, ts, magnet_x)
                if playing and h.alive and self.player.catch_rect.colliderect(h.rect):
                    h.alive = False
                    self._collect_energy(h)
        for bm in self.beams:
            bm.update(dt)

        if playing and ctrl.fighting and self.hurt_timer <= 0:
            body = self.player.rect
            for p in self.projectiles:
                if p.alive and p.hits(body):
                    p.alive = False
                    self._boss_hit((p.pos.x, min(p.pos.y, self.player.pos.y - 10)))
                    break
            else:
                if ctrl.sweep_hits(body):
                    self._boss_hit((self.player.pos.x, self.player.pos.y - 20))
        self.projectiles = [p for p in self.projectiles if p.alive]
        self.helpers = [h for h in self.helpers if h.alive]
        self.beams = [b for b in self.beams if b.alive]

    def _on_boss_events(self, events) -> None:
        color = self._boss_color()
        for ev in events:
            if ev == "sweep_warn":
                self.app.audio.play("warning", 0.8)
            elif ev == "sweep_fire":
                self.shake.add(0.4)
            elif ev in ("phase2", "phase3"):
                n = int(ev[-1])
                self._callout(t("boss.phase", n=n), color)
                self.app.audio.play("warning", 0.7)
                self.shake.add(0.5)
                self.bg.pulse(0.8)
                if self.particles is not None:
                    self.particles.ring(self.boss.boss.pos, color, radius=170, duration=0.6, width=6)
            elif ev == "enrage":
                self._callout(t("boss.enraged"), PAL["red"])
                self.app.audio.play("warning", 0.7)
                self.shake.add(0.5)
                self.bg.pulse(1.0)
            elif ev == "dead":
                self._on_boss_dead()
            elif ev == "done":
                self._open_reward()

    def _on_boss_dead(self) -> None:
        if self.state != "playing":
            return                                  # the last life went in the same step: no reward for the dead
        self.stats["bosses"] = self.stats.get("bosses", 0) + 1
        self.bosses_defeated += 1
        self.victory_bonus = config.BOSS_CLEAR_BONUS * self.bosses_defeated
        self.score += self.victory_bonus
        self.lives = self.max_lives
        self.hurt_timer = 0.0
        self.energy = 0
        for obj in self.projectiles + self.helpers:
            self._poof(obj.pos, getattr(obj, "color", PAL["white"]), 8)
        self.projectiles.clear()
        self.helpers.clear()
        self.app.audio.play("boss_defeat")
        self.shake.add(0.9)
        self.bg.pulse(1.0)
        log.info("Boss %d defeated: score=%d lives=%d", self.bosses_defeated, self.score, self.lives)

    def _open_reward(self) -> None:
        if self.reward_open or self.state != "playing":
            return
        self.reward_open = True
        pool = [k for k in config.BOSS_UPGRADES if self.upgrades[k] < config.UPGRADE_MAX_STACK
                and not (k == "life" and self.max_lives >= config.MAX_LIVES_CAP)]
        options = self.rng.sample(pool, min(3, len(pool)))
        if not options:                                 # everything maxed: nothing to offer
            self._end_boss()
            return
        self.app.scenes.push("boss_reward", options=options, number=self.boss.boss.number,
                             bonus=self.victory_bonus, owned=dict(self.upgrades), on_pick=self._on_upgrade_picked)

    def _on_upgrade_picked(self, key: str) -> None:
        if key in self.upgrades and self.upgrades[key] < config.UPGRADE_MAX_STACK:
            self.upgrades[key] += 1
            self._apply_upgrades(key)
        self._end_boss()

    def _apply_upgrades(self, just: str = None) -> None:
        u = self.upgrades
        config.set_upgrade_mults(wide=1.0 + config.UPGRADE_WIDE_STEP * u["wide"],
                                 magnet=1.0 + config.UPGRADE_MAGNET_STEP * u["magnet"],
                                 speed=1.0 + config.UPGRADE_SPEED_STEP * u["speed"])
        self.max_lives = min(config.MAX_LIVES_CAP, config.MAX_LIVES + u["life"])
        if just == "life":
            self.lives = min(self.max_lives, self.lives + 1)

    def _end_boss(self) -> None:
        """Reward taken: back to the ordinary game with a short breather."""
        self.boss.stop()
        self.boss_mode = False
        self.reward_open = False
        self.next_boss_level += config.BOSS_EVERY
        self.items.clear()
        self.projectiles.clear()
        self.helpers.clear()
        self.beams.clear()
        self.spawner.reset()
        self.grace = RESUME_GRACE
        self.combo.reset()
        self.callout = None
        self.bg.set_accent(level_hue(self.level))
        self._check_level()

    def _cheat_boss(self) -> None:                          # CHEAT (temporary, remove after testing)
        """F9: skip to the next boss fight. The round no longer counts for the high score."""
        if self.state != "playing" or self.boss_mode:
            return
        self.practice = True
        self.score = max(self.score, difficulty.score_for_level(self.next_boss_level))
        self._check_level()

    def _fire_beam(self) -> bool:
        """Space: spend the energy and shoot straight up from the paddle."""
        if not (self.boss_mode and self.state == "playing" and self.boss.fighting):
            return False
        if self.energy < config.BOSS_ENERGY_NEED:
            return False
        self.energy -= config.BOSS_ENERGY_NEED
        x, y = self.player.pos.x, self.player.rect.top
        beam = Beam(x, y, self.boss.hit_rect)
        self.beams.append(beam)
        self.app.audio.play("beam_fire")
        self.shake.add(0.2)
        self.player.bump(0.8)
        if beam.hit:
            self._damage_boss(config.BOSS_BEAM_DAMAGE, (x, beam.y_to), True)
        return True

    def _damage_boss(self, amount: float, pos, heavy: bool) -> float:
        dealt = self.boss.damage(amount * self._power_mult(), "beam" if heavy else "ball")
        if dealt <= 0:
            return 0.0
        pts = int(round(dealt * config.BOSS_POINTS_PER_HP))
        self.score += pts
        self.stats["boss_damage"] = self.stats.get("boss_damage", 0.0) + dealt
        self.app.audio.play("boss_hit", 0.6 if heavy else 0.5)
        self.shake.add(0.3 if heavy else 0.1)
        if self.particles is not None:
            boss_draw.boss_hit_fx(self.particles, pos, self._boss_color(), heavy)
        b = self.boss.boss
        self._popup(f"+{pts}", (pos[0], b.pos.y + b.half_h + 24), PAL["white"], 30 if heavy else 24)
        return dealt

    def _ball_hit_boss(self, pos) -> None:
        """A ball hit counts towards the next energy item, which falls from the boss (beam hits do not count)."""
        if self._damage_boss(config.BOSS_BALL_DAMAGE, pos, False) <= 0:
            return
        self.ball_hits += 1
        if self.ball_hits % config.BOSS_HITS_PER_ENERGY == 0 and self.boss.fighting:
            b = self.boss.boss
            x = min(max(b.pos.x + self.rng.uniform(-0.4, 0.4) * b.half_w, 30), config.LOGICAL_W - 30)
            self.helpers.append(EnergyItem(x, b.pos.y + b.half_h))
            self._popup(t("boss.energy"), (x, b.pos.y + b.half_h + 52), PAL["yellow"], 24)

    def _collect_energy(self, h) -> None:
        before = self.energy
        self.energy = min(config.BOSS_ENERGY_CAP, self.energy + 1)
        self.stats["powerups"] += 1
        self.player.bump(0.4)
        pos = (h.pos.x, min(h.pos.y, self.player.pos.y - 14))
        if before < config.BOSS_ENERGY_NEED <= self.energy:
            self.app.audio.play("beam_charge")                  # a shot is ready
        else:
            self.app.audio.play("catch_rare", 0.8)
        if self.particles is not None:
            self.particles.burst(pos, PAL["yellow"], count=16, speed=(60, 300), life=(0.25, 0.6), gravity=300)
        self._popup("+1", (pos[0], pos[1] - 26), PAL["yellow"], 26)

    def _on_ball_event(self, ball, ev: str) -> None:
        pos = (ball.pos.x, min(ball.pos.y, self.player.pos.y - 14))
        if ev == "caught":
            self.app.audio.play("catch", CATCH_VOLUME)
            self.player.bump(0.5)
            self._poof(pos, PAL["white"], 12)
        elif ev == "paddle":
            self.app.audio.play("catch", 0.55)
            self.player.bump(0.3)
        elif ev == "boss":
            self._ball_hit_boss(ball.pos)
        elif ev == "lost":
            self._on_miss(ball, t("boss.ball_lost"))

    def _boss_hit(self, pos) -> None:
        """A boss shot or sweep touched the paddle: like a bomb, then a second of invulnerability."""
        self.stats["bombs"] += 1
        self._hurt(pos)
        self.hurt_timer = config.BOSS_HIT_IFRAMES

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
        self._hurt(pos)

    def _hurt(self, pos) -> None:
        """Something deadly touched the paddle (bomb, boss shot, sweep): a shield soaks it, else -1 life."""
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
            if self.lives < self.max_lives:
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

    def _on_miss(self, it, label: str = None) -> None:
        """A good item (or, in a boss fight, the ball) fell past the paddle."""
        self.stats["missed"] += 1
        self.combo.break_()
        self.app.audio.play("miss")
        self.shake.add(0.45)
        self.flash = max(self.flash, 0.8)
        x = min(max(it.pos.x, 20), config.LOGICAL_W - 20)
        if self.particles is not None:
            self.particles.burst((x, config.LOGICAL_H - 6), PAL["red"], count=24, speed=(100, 380),
                                 life=(0.3, 0.7), angle=-math.pi / 2, spread=math.pi * 0.8)
        self._popup(label or t("play.miss"), (x, config.LOGICAL_H - 70), PAL["red"], 28)
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
        if self.boss_mode:
            return                                  # the level stands still during a boss fight
        new = difficulty.level_for_score(self.score)
        if new >= self.next_boss_level:
            self._start_boss()
            return
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
        if self.practice:
            log.info("Practice round (--start-boss): high score not saved")
        else:
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
        a, v = config.player_accel(), config.player_max_speed()
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

    #Boss fight bot: keep the ball alive, dodge shots and sweeps, line up under the boss and fire
    @staticmethod
    def _ball_flight(x: float, y: float, vx: float, vy: float, r: float, boss_rect):
        """(seconds, x, hit_boss) until a ball next comes down to the paddle line (walls, ceiling and boss folded)."""
        width = config.LOGICAL_W
        y_line = config.PLAYER_Y - config.PLAYER_H / 2 - r
        box = boss_rect.inflate(2 * r, 2 * r) if boss_rect is not None else None
        step, tm, cool, hit = 1 / 120, 0.0, 0.0, False
        while tm < 6.0:
            x += vx * step
            y += vy * step
            tm += step
            cool -= step
            if x < r:
                x, vx = r, abs(vx)
            elif x > width - r:
                x, vx = width - r, -abs(vx)
            if y < r:
                y, vy = r, abs(vy)
            if box is not None and cool <= 0 and box.collidepoint(x, y):
                # Same rule as HelperBall: leave through the side with the least penetration
                pen = {"l": x - box.left, "r": box.right - x, "t": y - box.top, "b": box.bottom - y}
                side = min(pen, key=pen.get)
                if side == "t":
                    vy = -abs(vy)
                elif side == "b":
                    vy = abs(vy)
                elif side == "l":
                    vx = -abs(vx)
                else:
                    vx = abs(vx)
                cool, hit = 0.1, True
            if vy > 0 and y >= y_line:
                break
        return tm, x, hit

    def _boss_goal(self):
        """(x, until, tol): where the paddle should be, how soon, and how far off it may be (None = no rush)."""
        ctrl, half = self.boss, self.player.width / 2
        b = ctrl.boss
        if b is None:
            return config.LOGICAL_W / 2, None, None, False, None
        flying = [h for h in self.helpers if isinstance(h, HelperBall) and h.alive and h.state == "flying"]
        if flying:
            # A ball coming down is worth a life: be under it. Hit it so that it comes back near the boss
            # to where it was caught (a ball sent across the field is lost), preferring returns that touch the boss.
            tm, lx, _ = min((self._ball_flight(h.pos.x, h.pos.y, h.vel.x, h.vel.y, h.radius, ctrl.hit_rect)
                             for h in flying), key=lambda f: f[0])
            y_line = config.PLAYER_Y - config.PLAYER_H / 2 - config.BOSS_BALL_RADIUS
            sp, best = config.BOSS_BALL_SPEED, None
            for o in (-0.5, -0.25, 0.0, 0.25, 0.5):
                ang = o * math.radians(config.BOSS_BALL_MAX_ANGLE)
                _, rx, hit = self._ball_flight(lx, y_line, sp * math.sin(ang), -sp * math.cos(ang),
                                               config.BOSS_BALL_RADIUS, ctrl.hit_rect)
                cost = abs(rx - lx) - (150.0 if hit else 0.0) + 15.0 * abs(o)     # back where it was caught = no running
                if best is None or cost < best[0]:
                    best = (cost, o)
            return lx - best[1] * half, tm + 0.15, 0.5 * half, False, tm
        if ctrl.fighting and self.energy >= config.BOSS_ENERGY_NEED:
            return b.pos.x, 1.0, 0.6 * half, False, None
        ts = max(self.powerups.time_scale, 0.05)
        px = self.player.pos.x
        pick = None
        for h in self.helpers:
            if not h.alive or h.pos.y > config.PLAYER_Y:
                continue
            if isinstance(h, HelperBall) and (h.state != "falling" or not self.bot_balls):
                continue
            eta = max(0.0, config.PLAYER_Y - h.pos.y) / max(h.vel.y, 150.0) / ts
            if abs(h.pos.x - px) - half * 0.6 <= self._reach(eta) and (pick is None or eta < pick[0]):
                pick = (eta, h.pos.x)
        if pick is not None:
            return pick[1], pick[0] + 0.15, 0.6 * half, False, pick[0]
        return b.pos.x, None, 0.6 * half, False, None

    def _boss_bot_target(self) -> float:
        """Spot nearest to the goal whose approach path the planner finds clean of shots and sweeps."""
        ts = self.powerups.time_scale
        shots = [(p.pos.x, p.pos.y, p.vel.x * ts, p.vel.y * ts, p.radius) for p in self.projectiles if p.alive]
        if not self.bot_balls:      # a ball caught by accident has to be kept alive: steer clear of falling ones
            shots += [(h.pos.x, h.pos.y, h.vel.x, max(h.vel.y, 260.0) * ts, h.radius + 6)
                      for h in self.helpers if isinstance(h, HelperBall) and h.alive and h.state == "falling"]
        sweeps = [(sw.zone[0], sw.zone[1], max(0.0, sw.warn_time - sw.age), sw.warn_time + sw.fire_time - sw.age)
                  for sw in self.boss.sweeps if sw.phase != "done" and not sw.consumed]
        goal, until, tol, commit, arrive = self._boss_goal()
        return boss_bot.choose(self.player.pos.x, self.player.vel.x, self.player.width, goal, shots, sweeps, until, tol,
                               commit, arrive)

    def _bot_fire(self) -> None:
        ctrl = self.boss
        b = ctrl.boss
        if b is None or not ctrl.fighting or self.energy < config.BOSS_ENERGY_NEED:
            return
        if abs(self.player.pos.x - b.pos.x) <= b.half_w * 0.6 and abs(self.player.vel.x) < 350:
            self._fire_beam()

    def _bot_direction(self) -> int:
        x, v = self.player.pos.x, self.player.vel.x
        if self.boss_mode:
            self._bot_tick += 1
            if self._bot_tick % 4 == 1 or self._bot_goal is None:      # planning is costly: every 4th step is plenty
                self._bot_goal = self._boss_bot_target()
            return boss_bot.drive(x, v, self._bot_goal, config.player_accel() * config.PLAYER_TURN_BOOST)
        target = self._bot_target()
        stop_x = x + v * abs(v) / (2 * config.player_friction())    # where friction alone would stop us
        err = target - stop_x
        return _sign(err) if abs(err) > 5 else 0

    #Drawing
    def hud_state(self) -> dict:
        return {
            "score": self.score,
            "best": max(self.best, self.score),
            "lives": self.lives,
            "max_lives": self.max_lives,
            "level": self.level,
            "level_progress": difficulty.level_progress(self.score),
            "combo": self.combo.count,
            "multiplier": self._multiplier(),
            "powerups": self.powerups.active(),
            "shield": self.player.shield,
            "boss": self._boss_hud(),
        }

    def _boss_hud(self):
        """The HUD's view of the fight (see 5.1), None outside a boss fight."""
        b = self.boss.boss
        if not self.boss_mode or b is None:
            return None
        return {
            "name_key": b.name_key, "number": b.number, "kind": b.kind,
            "state": "victory" if self.boss.state == "done" else self.boss.state,
            "hp_frac": b.hp_frac, "phase": b.phase,
            "time_left": self.boss.time_left, "enraged": b.enraged, "colors": b.colors,
            "energy": self.energy, "energy_need": config.BOSS_ENERGY_NEED, "energy_cap": config.BOSS_ENERGY_CAP,
            "balls": sum(1 for h in self.helpers if isinstance(h, HelperBall) and h.alive),
            "player_x": self.player.pos.x, "boss_x": b.pos.x, "boss_half_w": b.half_w,
        }

    def draw(self, surf):
        tm = self.app.time
        self.bg.draw(surf)
        assets = self.app.assets
        if self.boss_mode and self.boss.boss is not None:
            b = self.boss.boss
            for sw in self.boss.sweeps:
                boss_draw.draw_sweep(surf, sw, b.pos.y + b.half_h, tm)
            boss_draw.draw_boss(surf, b, tm, assets)
        for it in self.items:
            it.draw(surf, tm, assets)
        for obj in self.projectiles:
            obj.draw(surf, tm, assets)
        for obj in self.helpers:
            obj.draw(surf, tm, assets)
        if not (self.hurt_timer > 0 and int(self.hurt_timer * 16) % 2 == 0):    # blink while invulnerable
            self.player.draw(surf, tm)
        for bm in self.beams:
            boss_draw.draw_beam(surf, bm, tm)
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
        if self.boss_mode:
            self._draw_boss_banners(surf)

    def _draw_boss_banners(self, surf) -> None:
        b = self.boss.boss
        if b is None:
            return
        assets = self.app.assets
        state = self.boss.state
        if state == "intro":
            boss_ui.draw_boss_banner(surf, assets, self._boss_hud(), min(1.0, b.anim_t / config.BOSS_INTRO_TIME))
        elif state == "victory":
            boss_ui.draw_victory_banner(surf, assets, self.victory_bonus, min(1.0, b.death_t))
        if self.callout is not None:
            text, color, age = self.callout
            boss_ui.draw_callout(surf, assets, text, color, min(1.0, age / CALLOUT_TIME))

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
