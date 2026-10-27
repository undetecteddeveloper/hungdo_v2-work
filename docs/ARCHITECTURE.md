# Hứng Đồ v2 — Architecture & Module Contract

This document is the single source of truth for interfaces. Every module must follow it.
If you need something not listed, add it **inside a file you own** and note it in your report;
never change another module's public signature.

v1 lives in a separate repo (`E:\pygame projects\HungDo_project`) and stays untouched.

## Run / tooling
- Python: `.venv/Scripts/python.exe` at repo root (`E:\pygame projects\hungdo_v2-work\.venv`). Library: **pygame-ce 2.5.x** (`import pygame as pg`), numpy available.
- Run game: `.venv/Scripts/python.exe main.py`
- Headless: set env `SDL_VIDEODRIVER=dummy`, `SDL_AUDIODRIVER=dummy`.
- Code comments in English, concise, matching v1 style. No type-checker required, but use type hints on public functions.
- Never `print` in hot loops. Use `logging` (logger name `hungdo`).

## Visual direction
Neon abstract + flat vector: dark background (near-black navy), clean geometric shapes (circles, rounded
rects, diamonds, hexagons), bright saturated outlines/fills with additive glow, smooth easing animations.
No photo-realistic or pixel-art assets. Everything readable at 360x560 window.

## Directory layout
```
./                          # repo root
  main.py                    # entry: from game.app import App; App().run()
  game/
    __init__.py
    config.py                # constants + tunables (CORE)
    paths.py                 # resource_path(), user_data_dir() (CORE)
    settings.py              # Settings load/save (CORE)
    i18n.py                  # t(), set_language() (CORE)
    assets.py                # Assets: fonts, images, text cache (CORE)
    audio.py                 # AudioManager (CORE)
    display.py               # Display: window, logical surface, scaling (CORE)
    scene.py                 # Scene, SceneManager (CORE)
    app.py                   # App main loop (CORE)
    render/  neon.py background.py                      (EFFECTS)
    systems/ particles.py floating_text.py shake.py     (EFFECTS)
    entities/ player.py items.py                        (GAMEPLAY)
    systems/ difficulty.py spawner.py powerups.py combo.py highscore.py  (GAMEPLAY)
    ui/      widgets.py hud.py                          (UI)
    scenes/  menu.py settings_scene.py pause.py gameover.py howto.py  (UI)
    scenes/  play.py                                    (INTEGRATION)
    BOSS:    systems/boss.py systems/boss_bot.py entities/boss_items.py render/boss_draw.py
             ui/boss_ui.py scenes/boss_reward.py        (see "Boss fights" below)
  lang/ vi.json en.json      # (UI owns keys; CORE creates initial files with core keys)
  assets/
    font/                    # copied Barlow Condensed (+ optional display font)
    sound/                   # sfx + music (ASSETS-AUDIO)
    images/icons/            # white/monochrome PNG glyphs, tinted at runtime (ASSETS-IMAGE)
    icon.ico                 # window/exe icon
  tools/                     # dev scripts: smoke_test.py, synth_sfx.py, make_icon.py ...
  tests/                     # pytest-free plain asserts runnable with python -m
  build.py                   # PyInstaller build -> dist/HungDo_v2.exe
  CREDITS.md                 # every downloaded asset: name, author, source URL, license
```
All packages have `__init__.py`.

## Coordinate system & timing
- Logical canvas: always `config.LOGICAL_H = 840` tall; its width `config.LOGICAL_W` follows the window aspect, between
  `config.BASE_W = 540` (the original portrait width) and 21:9 (`config.MAX_ASPECT`). `Display.apply()` resizes it and calls
  `config.set_logical_width()`; code must read `config.LOGICAL_W` / `config.LOGICAL_SIZE` at use time, never cache them at import.
  After a change `SceneManager.relayout(old_w)` calls `Scene.on_resize(old_w)` on every created scene. All gameplay/UI
  coordinates are logical pixels. Menu-style scenes stay centred; the Play field uses the full width.
- Wide-canvas balance (`config.field_scale() = LOGICAL_W / BASE_W`): paddle speed/accel/friction scale with `SPEED_EXP`,
  paddle width and magnet radius with `WIDTH_EXP`, spawn rate with `RATE_EXP`. Use `config.player_w()`, `player_max_speed()`,
  `player_accel()`, `player_friction()`, `magnet_radius()`, `spawn_rate_mult()` instead of the raw `PLAYER_*` constants.
- Fixed physics step: `config.PHYSICS_HZ = 120` → `update(dt)` always receives `dt = 1/120`.
  `App` accumulates real time, runs at most `config.MAX_STEPS_PER_FRAME = 6` updates per frame, then one `draw`.
- `App.time` = total unpaused seconds since start (float), handy for animations.

## CORE contracts

### config.py
```python
TITLE = "Hứng Đồ v2"
LOGICAL_SIZE = (540, 840); LOGICAL_W, LOGICAL_H
PHYSICS_HZ = 120; PHYSICS_DT = 1 / PHYSICS_HZ; MAX_STEPS_PER_FRAME = 6
WINDOW_HEIGHT_FRACTIONS = (0.55, 0.7, 0.85, 1.0)   # windowed sizes = these shares of the usable desktop height, at the desktop aspect
FPS_OPTIONS = [30, 60, 120, 144, 0]   # 0 = unlimited
LANGUAGES = ["vi", "en"]
PALETTE = { "bg_top", "bg_bottom", "cyan", "magenta", "yellow", "green", "red", "orange", "purple", "white", "dim" }  # RGB tuples
LEVEL_HUES = [...]  # list of RGB accent colours cycling per level
FONT_FILES = {"light": ..., "regular": ..., "bold": ..., "black": ...}   # relative asset paths
DISPLAY_FONT_FILE = None or relative path   # optional title font (must support Vietnamese)
SOUND_FILES = {name: relative_path}  # names listed in audio section
MUSIC_FILES = {"menu": rel_path, "game": rel_path}
ICON_FILES = {"magnet","slow","wide","shield","heart","bomb","star"}: rel_path  # may be missing on disk → procedural fallback
# Gameplay tunables live in a dataclass-free plain-constant block at the bottom (GAMEPLAY owns their values,
# CORE creates the block with the defaults from the Gameplay section below).
```

### paths.py
- `resource_path(rel: str) -> str` — base = `sys._MEIPASS` when frozen, else the repo root directory (dir of `main.py`), **not** cwd.
- `user_data_dir() -> str` — `%APPDATA%/HungDo` on Windows (fallback `~/.hungdo`), created on demand.

### settings.py
```python
@dataclass
class Settings:
    language: str = "vi"; resolution: tuple = (540, 840); fullscreen: bool = False
    fps_cap: int = 60; show_fps: bool = False
    music_volume: float = 0.6; sfx_volume: float = 0.8; screen_shake: bool = True
    @classmethod
    def load(cls) -> "Settings"      # from user_data_dir()/settings.json; invalid/missing fields -> defaults
    def save(self) -> None           # atomic write (tmp + os.replace)
```

### i18n.py
- `set_language(code)`, `get_language()`, `t(key: str, **fmt) -> str` (missing key → returns key and logs once).
- Loads `lang/<code>.json` (flat `{key: string}`) via `resource_path`. Font must render Vietnamese.

### assets.py — `Assets` (one instance at `app.assets`)
- `font(size: int, weight: str = "regular") -> pg.font.Font` (cached; weight in FONT_FILES keys or `"display"`).
- `text(s: str, size: int, color, weight="regular") -> pg.Surface` — LRU-cached rendered text (cache by all args; cap ~512 entries).
- `image(rel_path: str, tint=None, size=None) -> pg.Surface | None` — cached, `convert_alpha()`, tint by multiplying white glyph with colour; returns `None` if file missing (caller draws fallback).
- `icon(name: str, color, size: int) -> pg.Surface | None` — shortcut via `config.ICON_FILES`.

### audio.py — `AudioManager` (at `app.audio`)
- `play(name: str, volume: float = 1.0)` — no-op + one warning if missing. Max simultaneous channels 24.
- `play_music(track: str, fade_ms=800)` / `stop_music(fade_ms=500)`; `set_volumes(music, sfx)`.
- SFX names (all must exist in `assets/sound` after ASSETS-AUDIO): `catch`, `catch_rare`, `catch_epic`, `miss`,
  `bomb`, `powerup`, `shield_break`, `heart`, `combo_up`, `level_up`, `countdown`, `go`, `ui_move`, `ui_select`, `ui_back`, `game_over`, `new_record`.
- Mixer init must not crash when no audio device (catch `pg.error`, run silent).

### display.py — `Display` (at `app.display`)
- `apply(settings)` — (re)create window: windowed at `settings.resolution` (clamped to the largest available) or fullscreen at desktop size; sets caption + icon.
- `surface` — logical `pg.Surface(LOGICAL_SIZE)` everything draws onto.
- `present()` — scale logical surface into the window letterboxed (black bars), `pg.transform.smoothscale` unless scale is exactly 1, then `pg.display.flip()`. Reuse the scaled target surface when size unchanged (no per-frame allocation where avoidable).
- `to_logical(window_pos) -> (x, y) | None`.
- `available_resolutions() -> list[tuple]` — windowed sizes from `WINDOW_HEIGHT_FRACTIONS` of (desktop height − ~80px) at the desktop aspect (never empty).
- `take_resize() -> int | None` — previous canvas width if the last `apply()` changed it (App then relayouts the scenes).

### scene.py
```python
class Scene:
    is_overlay = False            # True → scene below is drawn (not updated) first
    def __init__(self, app): self.app = app
    def on_enter(self, **kwargs): ...
    def on_exit(self): ...
    def handle_event(self, event): ...   # mouse events already carry LOGICAL pos (or are dropped if outside)
    def update(self, dt): ...            # fixed dt
    def draw(self, surf): ...
class SceneManager:
    def register(self, name, factory)    # factory(app) -> Scene; scenes created lazily, cached
    def switch(self, name, **kw)         # replace whole stack
    def push(self, name, **kw); def pop(self)
    @property top
```
Scene names: `"splash"`, `"menu"`, `"play"`, `"pause"`, `"settings"`, `"gameover"`, `"howto"`, `"confirm_quit"`, `"boss_reward"`.
Switch/push/pop requested during update/handle_event are applied at end of frame (deferred) to avoid mutation mid-iteration.

### app.py — `App`
Attributes: `settings, display, assets, audio, scenes, clock, time, fps (float, smoothed)`.
Methods: `run()`, `quit()`, `apply_settings()` (display.apply, audio.set_volumes, i18n.set_language, then save).
Draws FPS counter top-right when `settings.show_fps` (after scene draw). Global: window close → quit; F11 toggles fullscreen.
Registers all scenes; scenes that fail to import (module not written yet) are replaced by a placeholder scene so CORE runs standalone.
Starts in `"menu"`.

Automation hooks (needed by tools/smoke_test.py and the exe self-test):
- `App(argv=None)` parses: `--autoplay` (sets `app.autoplay = True`; play scene then drives the player with a simple bot and
  the menu auto-starts a game), `--smoke-seconds N` (quit cleanly with exit code 0 after N seconds of wall time),
  `--start-scene NAME` (default `splash`: title card, then the "Python / Claude Code" card, whose logos and text fade in and out over a constant neon background, any key or click
  skips to the menu; `--autoplay` and `--start-boss` start at `menu` instead), `--data-dir PATH`, `--start-boss N` (`app.start_boss`: practice, every round starts at boss N right after
  the countdown, level 10*N; the high score is not saved).
- `App.step(frame_dt: float | None = None)` runs exactly one frame (events → fixed updates → draw → present); `run()` loops it.
  Tests call `step(1/60)` repeatedly and inject input via `pg.event.post(...)`.
- Any uncaught exception in `run()` is logged with traceback to `user_data_dir()/crash.log` and re-raised (exit code ≠ 0).

## EFFECTS contracts
- `render/neon.py`:
  `glow_circle(radius, color, intensity=1.0) -> Surface` (cached), `glow_rect(w, h, color, radius=8, thickness=0) -> Surface` (cached),
  `glow_polygon(points_key: str, size, color) -> Surface` for shapes `"diamond"`, `"hexagon"`, `"star"`, `"triangle"` (cached),
  `draw_glow(surf, glow_surf, center)` blits with `BLEND_ADD`. Glow built once via downscale-blur-upscale (smoothscale), never per frame.
  `neon_text(assets, s, size, color, weight="bold") -> Surface` (text + glow halo, cached).
- `render/background.py`: `Background(app)` with `update(dt)`, `draw(surf)`, `set_accent(rgb)` (smooth lerp over ~1.5 s). Dark vertical gradient + scrolling perspective synthwave grid near the bottom + slow drifting star dots. Pre-render static layers.
- `systems/particles.py`: `ParticleSystem(max_particles=600)`: `burst(pos, color, count=20, speed=(80, 360), life=(0.3, 0.8), size=(2, 5), gravity=300)`, `ring(pos, color, radius=60)` (expanding shockwave), `update(dt)`, `draw(surf)`, `clear()`. Preallocated/pooled, cheap additive dots.
- `systems/floating_text.py`: `FloatingTexts(assets)`: `spawn(text, pos, color, size=28)` rises + fades in 0.9 s; `update`, `draw`, `clear`.
- `systems/shake.py`: `ScreenShake`: `add(trauma: float)` (0..1), `update(dt)`, `offset -> (dx, dy)`; disabled when `app.settings.screen_shake` is False (caller passes flag).

## GAMEPLAY contracts (pure logic, no drawing except `draw` methods that use render/neon helpers)
Default tunables (go in config.py bottom block):
```
START_LIVES = 3; MAX_LIVES = 5
PLAYER_Y = LOGICAL_H - 120; PLAYER_W = 110; PLAYER_H = 22
PLAYER_ACCEL = 4200; PLAYER_MAX_SPEED = 780; PLAYER_FRICTION = 5600; PLAYER_TURN_BOOST = 1.8
WALL_BOUNCE = 0.25
GRAVITY = 520                     # px/s², multiplied by level gravity_mult
ITEM_RESTITUTION = 0.85           # wall bounce for items with vx
POINTS = {"common": 10, "rare": 25, "epic": 50}
POWERUP_DURATION = {"magnet": 8, "slow": 6, "wide": 10}
MAGNET_RADIUS = 240; MAGNET_PULL = 900; SLOW_FACTOR = 0.5; WIDE_FACTOR = 1.6
COMBO_STEP = 5; COMBO_MAX_MULT = 5      # mult = min(1 + combo // COMBO_STEP, COMBO_MAX_MULT)
COUNTDOWN_SECONDS = 3
```
- `entities/player.py` `Player`: `pos: Vector2` (center), `vel: Vector2`, `width` (animated toward target width), `rect` property,
  `update(dt, direction: int)` (direction −1/0/1 from A/D), `set_wide(active: bool)`, `shield: int` (0/1), `draw(surf, t)`.
  Physics: accelerate toward direction; when direction opposes velocity apply `PLAYER_TURN_BOOST`; no input → friction to 0;
  clamp to screen with `WALL_BOUNCE`. Visual squash/stretch & tilt from velocity; shield ring when shield>0.
- `entities/items.py` `Item`: fields `kind` (`"common" | "rare" | "epic" | "bomb" | "powerup"`), `power` (powerup name or None),
  `pos`, `vel`, `radius`, `alive`, `spin`; `update(dt, gravity, time_scale, magnet_target_x | None)`; `draw(surf, t, assets)`;
  `rect` property. Shapes: common = cyan circle, rare = magenta diamond, epic = yellow star (smaller, faster), bomb = red/orange
  spiky hexagon with pulsing core (+ optional icon `bomb`), powerup = rounded square with icon from `assets.icon(power, ...)` (fallback letter).
  Items fall with gravity, have a per-kind terminal velocity, side-wall bounce with ITEM_RESTITUTION, short trail.
- `systems/difficulty.py`: `level_for_score(score) -> int` (level 1 at 0, thresholds grow ~1.45× each: 120, 290, 540, ...),
  `score_for_level(level) -> int`, `params_for_level(level) -> LevelParams` (dataclass: `spawn_interval`, `gravity_mult`,
  `max_fall_speed_mult`, `weights: dict kind->weight`, `bomb_chance`, `diagonal_chance`, `burst_chance`, `powerup_interval`).
  Level 1 must feel easy (no bombs, interval ≈1.0 s), level 5+ demanding, level 10+ near-chaotic but fair; values clamp.
- `systems/spawner.py` `Spawner(rng)`: `update(dt, level_params) -> list[Item]` new items (random x within margins; diagonal items get vx;
  bursts spawn 2–3 items; never spawn a bomb directly above another bomb within 0.4 s; powerups on their own timer), `reset()`.
- `systems/powerups.py` `PowerUps`: `activate(name)`, `update(dt)`, `is_active(name)`, `remaining(name) -> float`,
  `active() -> list[(name, remaining, duration)]`, `reset()`. Names: `magnet`, `slow`, `wide` (timed); `shield`, `heart` are instant
  (handled by play scene: shield → player.shield = 1; heart → +1 life capped MAX_LIVES).
- `systems/combo.py` `Combo`: `hit() -> bool` (True if multiplier increased), `break_()`, `count`, `multiplier`, `best`, `reset()`.
- `systems/highscore.py` `HighScore`: `load()`, `submit(score, level) -> bool` (True if new best; saves), `best_score`, `best_level`, `games_played`. File `user_data_dir()/save.json`, atomic write, corrupt file → defaults.

### Rules (implemented by INTEGRATION in scenes/play.py)
- Catch common/rare/epic → `POINTS[kind] * combo.multiplier`, combo.hit(), particles + floating text, sfx.
- Miss (good item falls below screen) → lose 1 life, combo breaks, red flash + shake, sfx `miss`. Bombs/powerups falling off = no penalty.
- Catch bomb → if shield: consume shield (`shield_break`) else lose 1 life + big shake + explosion; combo breaks.
- Catch powerup → apply; sfx `powerup`.
- Level up when `level_for_score(score)` increases → banner "LEVEL N", sfx, background accent from `LEVEL_HUES`.
- Lives 0 → short slow-mo (0.6 s) → `gameover` with `score, level, best_combo, is_new_record`.
- Start of round: countdown 3‑2‑1‑GO (no spawns), A/D movement allowed.
- `Esc` or `P` → push `pause`. Window focus lost → auto pause.

## UI contracts
- `ui/widgets.py`: focusable list-based menus usable by keyboard (W/S or ↑/↓ move, A/D or ←/→ change, Enter/Space activate, Esc back)
  AND mouse (hover focuses, click activates, drag sliders). Widgets: `Button(label_key, on_click)`, `Toggle(label_key, get, set)`,
  `Selector(label_key, options: list[(value, label_str)], get, set)`, `Slider(label_key, get, set, step=0.1)`, `Menu(widgets, center_x, top_y, spacing)`
  with `handle_event`, `update(dt)`, `draw(surf)`. Labels resolve via `t()` at draw time (language switch is live). Plays `ui_move/ui_select/ui_back`.
  Neon styling: focused item glows/scales with easing.
- `ui/hud.py` `Hud(app)`: `draw(surf, state)` where `state` is a dict:
  `{"score", "best", "lives", "max_lives", "level", "level_progress" (0..1), "combo", "multiplier", "powerups": [(name, remaining, duration)], "shield": int}`.
  Re-renders text only when values change. Score top-left, hearts top-right (below FPS area, FPS uses top-right 20px), level bar under score,
  combo multiplier badge, power-up timers as small radial/linear bars with icons.
- Scenes: `menu` (animated neon title "HỨNG ĐỒ", buttons Play / How to play / Settings / Quit, best score line, background), `settings`
  (overlay-capable; rows: Language, Resolution, Fullscreen, FPS cap, Show FPS, Music volume, SFX volume, Screen shake, Back — changes
  apply live via `app.apply_settings()`; resolution change applies immediately), `pause` (overlay: Resume / Settings / Main menu),
  `gameover` (score, level, best combo, NEW RECORD animation, Retry (Enter) / Menu (Esc)), `howto` (shows each item shape + effect, controls).
- `lang/vi.json` and `lang/en.json` must have identical key sets. Vietnamese strings with full diacritics.

## Boss fights
Every `config.BOSS_EVERY` (10) levels the ordinary game stops and a boss fight starts. All tunables are in the `#Boss fights`
block at the bottom of `config.py` (hp, damage, timings, upgrade steps); `set_upgrade_mults()` / `UPGRADE_MULT` carry the
boss-reward upgrades into `player_w()`, `player_*speed*()` and `magnet_radius()` (reset every round).

Boss number `n` (n=1 at level 10) uses design `kind = (n-1) % 3` and repeats with `cycle = (n-1)//3`: hp x(1 + 0.35 cycle), attacks
x(1 + 0.20 cycle). Three designs: 0 Hex Core (orange), 1 Prism (magenta), 2 Void Eye (purple); each has its own attack pool per phase.

### State machine (`systems/boss.py`, `BossController.state`)
`idle -> intro (BOSS_INTRO_TIME, no shots, not damageable) -> fight -> enrage (after BOSS_TIME_LIMIT, one way) -> victory
(hp 0, BOSS_VICTORY_TIME of explosion) -> done -> stop() -> idle`. Phases change at hp 66% and 33% (`BOSS_STAGGER_TIME` calm).
```python
c = BossController(rng)
boss = c.start(number)                       # Boss: kind, number, cycle, name_key, colors, pos, half_w, half_h, hp, max_hp,
                                             #       phase, hit_flash, charge, enraged, anim_t, death_t, hp_frac, rect
tick = c.update(dt, player_x, balls_alive)   # BossTick: shots [Shot], drops [Drop], events [str]
c.damage(amount, source)  -> hp removed (0 unless fighting)       c.sweep_hits(rect) -> bool (marks the Sweep consumed)
c.hit_rect (None unless damageable)   c.sweeps [Sweep]   c.time_left   c.paddle_scale   c.on_resize(old_w)
```
Events: `intro_end charge volley sweep_warn sweep_fire phase2 phase3 enrage dead done`. `Shot(x, y, vx, vy, radius, shape, color)`
becomes an `entities.boss_items.Projectile`; `Drop(kind="ball", x)` becomes a `HelperBall`; energy items are created by play.py (`EnergyItem(x, y)`). The only special
attack is the `Sweep`: a vertical danger band (warning, then a beam that may glide across `zone`), hits once, always escapable.
Fairness (tests): every volley leaves a reachable safe spot for the real `Player` with 0.3 s reaction at widths 540, 960, 1960.

### Objects (`entities/boss_items.py`)
`Projectile` (straight line, `hits(rect)` circle-vs-rect), `EnergyItem` (falls, magnet-able), `HelperBall` (`falling` until the paddle
touches it, then `flying` at constant `BOSS_BALL_SPEED`; paddle bounce angle follows the hit position, walls/ceiling reflect, boss hit
deals `BOSS_BALL_DAMAGE`; `update(dt, ts, magnet_x, paddle, boss_rect)` returns events `caught paddle wall ceiling boss lost`),
`Beam(x, y_from, boss_rect)` (hitscan resolved at creation). Every object has `on_resize(old_w)`.

### Rules in `scenes/play.py`
- Level reaches `next_boss_level` -> ordinary items vanish (no penalty), `warning` + `boss_intro`, `boss.start(n)`; level and ordinary
  spawns are frozen, score only comes from damage (`BOSS_POINTS_PER_HP` per hp) and the defeat bonus (`BOSS_CLEAR_BONUS * bosses`).
- A shot or sweep touching the paddle behaves like a bomb (shield soaks it, else -1 life) then `BOSS_HIT_IFRAMES` of invulnerability
  (the paddle blinks). A ball falling past the paddle costs nothing but time: `PlayScene._on_ball_lost` shows `MẤT BÓNG!`, counts `stats["balls_lost"]`
  and `BossController.ball_lost()` holds the next helper ball back for at least `BOSS_BALL_RESPAWN` (3 s). Helpers falling past cost nothing either.
- Energy items only come from the ball: every `BOSS_HITS_PER_ENERGY` (2) ball hits on the boss one falls from the boss (beam hits
  do not count). Catching `BOSS_ENERGY_NEED` (2) energy items (hold up to `BOSS_ENERGY_CAP` = 4, i.e. two shots) arms the beam: Space fires straight up from the paddle.
- Defeat: field cleared, lives refilled, bonus added, `push("boss_reward", options, number, bonus, owned, on_pick)`; the chosen
  upgrade (`wide magnet life power speed`, max `UPGRADE_MAX_STACK` each, until the round ends) is applied, then normal play resumes
  after `RESUME_GRACE` and `next_boss_level += BOSS_EVERY`.
- `slow` power-up scales falling things (projectiles, falling helpers), never boss timers, sweeps or flying balls.
- HUD gets `state["boss"]` (None outside a fight): name key, number, kind, state, hp_frac, phase, time_left, enraged, colors,
  energy / energy_need / energy_cap, balls, player_x, boss_x, boss_half_w. Banners: `ui/boss_ui.py` (`draw_boss_banner`,
  `draw_victory_banner`, `draw_callout`).
- Autoplay bot (`PlayScene._boss_*`, `systems/boss_bot.py`): plans the paddle path against every shot and sweep zone, aims at
  the goal (energy items, lining up under the boss) and fires the beam; it goes for the helper balls (the only source of energy) but is weak at juggling a ball while dodging: it often loses.
- Sounds (synthesised by `tools/synth_sfx.py`): `boss_intro boss_hit beam_charge beam_fire boss_defeat warning`, plus the boss's own attacks: `boss_shot` plays once per bullet fired
  (`systems/shot_sfx.py`: `ShotSfx` spaces the blips 24-40 ms apart, lowers each blip's volume with the crowd size and keeps at most 5
  sounding at once; the scene plays them with `AudioManager.play(..., min_interval=0.0)`), and `boss_sweep` on `sweep_fire`.

## Performance rules
- All loaded/created surfaces `convert()`/`convert_alpha()`; caches for glow, text, icons; no `pg.font.Font(...)` outside Assets.
- No per-frame allocation of large Surfaces; particles pooled; HUD text cached.
- Target: ≥ 200 FPS uncapped at 540x840 logical on a mid laptop with 300 particles; `present()` scaling cost measured.
