"""App: owns the window, services and the fixed-timestep main loop."""
import argparse
import datetime
import importlib
import logging
import os
import sys
import time as _time
import traceback

import pygame as pg

from . import config, i18n
from .paths import user_data_dir

log = logging.getLogger(config.LOGGER_NAME)

# Scene name -> (module, preferred class names). Missing modules become placeholders.
SCENE_MODULES = {
    "menu": (".scenes.menu", ("MenuScene",)),
    "play": (".scenes.play", ("PlayScene",)),
    "pause": (".scenes.pause", ("PauseScene",)),
    "settings": (".scenes.settings_scene", ("SettingsScene",)),
    "gameover": (".scenes.gameover", ("GameOverScene", "GameoverScene")),
    "howto": (".scenes.howto", ("HowToScene", "HowtoScene")),
    "confirm_quit": (".scenes.confirm_quit", ("ConfirmQuitScene",)),
    "boss_reward": (".scenes.boss_reward", ("BossRewardScene",)),
}
OVERLAY_PLACEHOLDERS = {"pause", "settings", "confirm_quit", "boss_reward"}
SETTINGS_SAVE_DELAY = 0.4     # seconds to wait after the last change before writing settings.json

MOUSE_EVENTS = (pg.MOUSEMOTION, pg.MOUSEBUTTONDOWN, pg.MOUSEBUTTONUP)
FPS_REFRESH = 0.25            # seconds between FPS counter text refreshes


#Logging & crash reporting

def setup_logging() -> None:
    """Configure the 'hungdo' logger once: stderr (if any) + user_data_dir()/hungdo.log."""
    logger = logging.getLogger(config.LOGGER_NAME)
    if getattr(logger, "_hungdo_configured", False):
        return
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S")
    if sys.stderr is not None:          # windowed exe has no stderr
        h = logging.StreamHandler()
        h.setFormatter(fmt)
        logger.addHandler(h)
    try:
        fh = logging.FileHandler(os.path.join(user_data_dir(), "hungdo.log"), mode="w", encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    except OSError:
        pass
    logger.propagate = False
    logger._hungdo_configured = True


def write_crash_log(exc: BaseException) -> str:
    """Append a timestamped traceback to user_data_dir()/crash.log; returns the path."""
    path = os.path.join(user_data_dir(), "crash.log")
    text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"=== {datetime.datetime.now().isoformat(timespec='seconds')} {config.TITLE} ===\n")
            f.write(text + "\n")
    except OSError:
        pass
    log.error("Unhandled exception (see %s):\n%s", path, text)
    return path


def parse_args(argv) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="hungdo_v2", add_help=True)
    p.add_argument("--autoplay", action="store_true", help="bot plays; menu auto-starts a game")
    p.add_argument("--smoke-seconds", type=float, default=None, help="quit with code 0 after N wall seconds")
    p.add_argument("--start-scene", default="menu", help="initial scene name")
    p.add_argument("--data-dir", default=None, help="override user data directory")
    p.add_argument("--start-boss", type=int, default=0, metavar="N",
                   help="practice: every round starts at boss N (level 10*N); high scores are not saved")
    args, unknown = p.parse_known_args(argv)
    if unknown:
        log.warning("Ignoring unknown arguments: %s", unknown)
    return args


#Placeholder for scenes whose module is not written yet

def _make_placeholder_factory(name: str):
    """Minimal stand-in scene so CORE runs before the real scene module exists."""
    from .scene import Scene

    class _Placeholder(Scene):
        is_overlay = name in OVERLAY_PLACEHOLDERS
        is_placeholder = True

        def __init__(self, app):
            super().__init__(app)
            self.name = name
            self.timer = 0.0

        def on_enter(self, **kwargs):
            self.timer = 0.0
            self.kwargs = kwargs

        def _back(self):
            if len(self.app.scenes.stack_names) > 1:
                self.app.scenes.pop()
            else:
                self.app.scenes.switch("menu")

        def handle_event(self, event):
            if event.type != pg.KEYDOWN:
                return
            if self.name == "menu":
                if event.key in (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE):
                    self.app.scenes.switch("play")
                elif event.key == pg.K_ESCAPE:
                    self.app.quit()
            elif event.key in (pg.K_ESCAPE, pg.K_RETURN, pg.K_KP_ENTER):
                self._back()

        def update(self, dt):
            self.timer += dt
            if self.name == "menu" and self.app.autoplay and self.timer >= 0.5:
                self.timer = -1e9           # only once per visit
                self.app.scenes.switch("play")

        def draw(self, surf):
            pal = config.PALETTE
            if self.is_overlay:
                surf.fill((40, 40, 60), special_flags=pg.BLEND_RGB_MULT)
            else:
                surf.fill(pal["bg_top"])
            a = self.app.assets
            cx, cy = config.LOGICAL_W // 2, config.LOGICAL_H // 2
            accent = config.LEVEL_HUES[int(self.app.time) % len(config.LEVEL_HUES)]
            title = a.text(config.TITLE if self.name == "menu" else self.name.upper(), 64, accent, "display")
            surf.blit(title, title.get_rect(center=(cx, cy - 80)))
            msg = a.text(i18n.t("placeholder.missing", name=self.name), 26, pal["white"], "regular")
            surf.blit(msg, msg.get_rect(center=(cx, cy)))
            hint_key = "placeholder.hint_menu" if self.name == "menu" else "placeholder.hint"
            hint = a.text(i18n.t(hint_key), 22, pal["dim"], "light")
            surf.blit(hint, hint.get_rect(center=(cx, cy + 50)))

    _Placeholder.__name__ = f"Placeholder_{name}"
    return _Placeholder


def _resolve_scene_class(name: str, module_name: str, class_names):
    """Import a scene module and find its Scene class; None if not available yet."""
    from .scene import Scene
    try:
        module = importlib.import_module(module_name, __package__)
    except ImportError as e:
        log.warning("Scene '%s' unavailable (%s); using placeholder", name, e)
        return None
    factory = getattr(module, "create_scene", None)
    if callable(factory):
        return factory
    for cls_name in class_names:
        cls = getattr(module, cls_name, None)
        if isinstance(cls, type) and issubclass(cls, Scene):
            return cls
    # Fallback: first Scene subclass defined in that module
    for obj in vars(module).values():
        if isinstance(obj, type) and issubclass(obj, Scene) and obj is not Scene \
                and obj.__module__ == module.__name__:
            return obj
    log.warning("Scene module %s has no Scene class; using placeholder", module_name)
    return None


#Application

class App:
    def __init__(self, argv=None):
        args = parse_args(sys.argv[1:] if argv is None else list(argv))
        if args.data_dir:
            os.environ["HUNGDO_DATA_DIR"] = os.path.abspath(args.data_dir)
        setup_logging()
        self.autoplay = bool(args.autoplay)
        self.start_boss = max(0, int(args.start_boss))      # 0 = normal game
        self.smoke_seconds = args.smoke_seconds
        self.exit_code = 0
        self.running = True

        #Initializing pygame & services
        # Not pg.init(): it would also try the mixer, which can block for seconds
        # without an audio device. AudioManager initialises the mixer exactly once.
        pg.display.init()
        pg.font.init()
        # Late imports keep `import game.app` cheap and avoid cycles
        from .assets import Assets
        from .audio import AudioManager
        from .display import Display
        from .scene import SceneManager
        from .settings import Settings

        self.settings = Settings.load()
        i18n.set_language(self.settings.language)
        self.display = Display()
        self.display.apply(self.settings)
        self.display.take_resize()              # no scenes exist yet: nothing to relayout
        self.assets = Assets()
        self.audio = AudioManager(self.settings.music_volume, self.settings.sfx_volume)
        self.scenes = SceneManager(self)
        self.clock = pg.time.Clock()

        #Timing state
        self.time = 0.0             # simulated seconds (advances PHYSICS_DT per fixed update)
        self.real_time = 0.0        # wall seconds of frames processed
        self.fps = 0.0              # smoothed
        self.frame = 0
        self._accum = 0.0
        self._fps_shown = 0
        self._fps_timer = 0.0
        self._closed = False
        self._save_due = None       # real_time at which pending settings get written

        self._register_scenes()
        start = args.start_scene
        if not self.scenes.has(start):
            log.warning("Unknown --start-scene '%s', using menu", start)
            start = "menu"
        self.scenes.switch(start)
        self.scenes.apply_pending()

    def _register_scenes(self) -> None:
        self.placeholders = set()
        for name, (module_name, class_names) in SCENE_MODULES.items():
            factory = _resolve_scene_class(name, module_name, class_names)
            if factory is None:
                factory = _make_placeholder_factory(name)
                self.placeholders.add(name)
            self.scenes.register(name, factory)

    #Public API
    def quit(self) -> None:
        self.running = False

    def apply_settings(self) -> None:
        """Push current settings into display/audio/i18n, then save them."""
        self.display.apply(self.settings)
        old_w = self.display.take_resize()
        if old_w is not None:
            self.scenes.relayout(old_w)         # the canvas got wider/narrower (fullscreen, window size)
        self.audio.set_volumes(self.settings.music_volume, self.settings.sfx_volume)
        i18n.set_language(self.settings.language)
        # Sliders and held keys call this many times a second: write once things settle
        self._save_due = self.real_time + SETTINGS_SAVE_DELAY

    def flush_settings(self) -> None:
        if self._save_due is not None:
            self._save_due = None
            self.settings.save()

    def toggle_fullscreen(self) -> None:
        self.settings.fullscreen = not self.settings.fullscreen
        self.apply_settings()

    def mouse_pos(self):
        """Logical mouse position or None (outside the canvas)."""
        return self.display.mouse_pos()

    #Events
    def _remap_mouse(self, event):
        """Window coords -> logical coords; returns None to drop the event."""
        d = dict(event.dict)
        dragging = event.type == pg.MOUSEMOTION and bool(event.buttons[0])
        if event.type == pg.MOUSEBUTTONUP or dragging:
            # Never drop a release, and keep drags alive outside the canvas (sliders must reach 0%/100%)
            d["pos"] = self.display.to_logical_clamped(event.pos)
            if dragging and "rel" in d:
                s = self.display.scale or 1.0
                d["rel"] = (round(d["rel"][0] / s), round(d["rel"][1] / s))
        else:
            pos = self.display.to_logical(event.pos)
            if pos is None:
                return None
            d["pos"] = pos
            if event.type == pg.MOUSEMOTION and "rel" in d:
                s = self.display.scale or 1.0
                d["rel"] = (round(d["rel"][0] / s), round(d["rel"][1] / s))
        return pg.event.Event(event.type, d)

    def _process_events(self) -> None:
        for event in pg.event.get():
            if event.type == pg.QUIT:
                self.quit()
                continue
            if event.type == pg.KEYDOWN:
                alt_enter = event.key in (pg.K_RETURN, pg.K_KP_ENTER) and (event.mod & pg.KMOD_ALT)
                if event.key == pg.K_F11 or alt_enter:
                    self.toggle_fullscreen()
                    continue
            if event.type in MOUSE_EVENTS:
                event = self._remap_mouse(event)
                if event is None:
                    continue
            self.scenes.handle_event(event)
            # Transitions requested by this event apply before the next event
            self.scenes.apply_pending()

    #Frame
    def step(self, frame_dt=None) -> None:
        """One frame: events -> fixed updates -> draw -> present."""
        cap = self.settings.fps_cap
        if frame_dt is None and cap:
            self._limit_frame(cap)
        ms = self.clock.tick()
        if frame_dt is None:
            frame_dt = ms / 1000.0
        frame_dt = max(0.0, float(frame_dt))
        self.real_time += frame_dt
        self.frame += 1

        self._process_events()
        if not self.running:
            return

        #Fixed-timestep updates
        dt = config.PHYSICS_DT
        self._accum += frame_dt
        steps = 0
        while self._accum >= dt and steps < config.MAX_STEPS_PER_FRAME:
            self.scenes.update(dt)
            self.time += dt
            self._accum -= dt
            steps += 1
            if self.scenes.pending:
                break                   # let the transition happen before more updates
        if steps >= config.MAX_STEPS_PER_FRAME:
            self._accum = min(self._accum, dt)  # drop backlog (avoid spiral of death)
        self.scenes.apply_pending()
        if self._save_due is not None and self.real_time >= self._save_due:
            self.flush_settings()

        #Drawing
        surf = self.display.surface
        self.scenes.draw(surf)
        self._update_fps(frame_dt)
        if self.settings.show_fps:
            self._draw_fps(surf)
        self.display.present()

    def _limit_frame(self, cap: int) -> None:
        """Wait until the next frame slot. Clock.tick(cap) relies on SDL_Delay, which on
        Windows rounds up to ~15.6 ms and turned a 60 FPS cap into ~35-45 FPS; Python's
        time.sleep uses a high-resolution timer, plus a short spin for the last ~1 ms."""
        period = 1.0 / cap
        now = _time.perf_counter()
        target = getattr(self, "_next_frame", now) + period
        if target < now - period:           # fell far behind (hitch): do not try to catch up
            target = now
        remaining = target - now
        if remaining > 0.0015:
            _time.sleep(remaining - 0.001)
        while _time.perf_counter() < target:
            pass
        self._next_frame = target

    def _update_fps(self, frame_dt) -> None:
        measured = self.clock.get_fps()
        if measured > 0:
            self.fps = measured if self.fps <= 0 else self.fps + (measured - self.fps) * 0.1
        self._fps_timer -= frame_dt
        if self._fps_timer <= 0:
            self._fps_timer = FPS_REFRESH
            self._fps_shown = int(round(self.fps))

    def _draw_fps(self, surf) -> None:
        txt = self.assets.text(i18n.t("fps", fps=self._fps_shown), 18, config.PALETTE["green"], "bold")
        surf.blit(txt, txt.get_rect(topright=(config.LOGICAL_W - 6, 1)))

    def run(self) -> int:
        """Main loop; returns the process exit code. Crashes go to crash.log and re-raise."""
        start = _time.perf_counter()
        try:
            while self.running:
                self.step()
                if self.smoke_seconds is not None and _time.perf_counter() - start >= self.smoke_seconds:
                    log.info("Smoke run finished after %.1fs (%d frames)", self.smoke_seconds, self.frame)
                    self.quit()
        except Exception as e:
            write_crash_log(e)
            self.exit_code = 1
            raise
        finally:
            self.close()
        return self.exit_code

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.flush_settings()
        except Exception as e:                  # never let a failed save block shutdown
            log.warning("Could not save settings on exit: %s", e)
        pg.quit()
