"""Main menu: pulsing neon title, falling demo shapes, best score, buttons."""
import logging
import math
import random


from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import (Button, Menu, dimmed, draw_glow, draw_item_shape, make_background, neon_text,
                          scale_color, text_glow_layer)

log = logging.getLogger(config.LOGGER_NAME)
PAL = config.PALETTE

TITLE_SIZE = 104
AUTOPLAY_DELAY = 0.5
DEMO_COUNT = 14
DEMO_KINDS = ["common"] * 6 + ["rare"] * 3 + ["epic"] * 2 + ["bomb", "powerup"]
DEMO_POWERS = ["magnet", "slow", "wide", "shield", "heart"]


def load_best():
    """(best_score, best_level) from systems.highscore, or None if unavailable."""
    try:
        from ..systems.highscore import HighScore
        hs = HighScore()
        hs.load()
        return int(hs.best_score), int(getattr(hs, "best_level", 0) or 0)
    except Exception as e:      # module not written yet / corrupt save handled there
        log.debug("Highscore unavailable: %s", e)
        return None


class _DemoShape:
    """A dim item-like shape drifting down behind the menu (parallax by depth)."""

    def __init__(self, rng: random.Random, initial: bool):
        self.rng = rng
        self.reset(initial)

    def reset(self, initial: bool = False):
        rng = self.rng
        self.kind = rng.choice(DEMO_KINDS)
        self.power = rng.choice(DEMO_POWERS) if self.kind == "powerup" else None
        self.depth = rng.uniform(0.35, 1.0)                 # 1 = near
        self.r = (10 if self.kind == "epic" else 16) * (0.6 + 0.6 * self.depth)
        self.x = rng.uniform(30, config.LOGICAL_W - 30)
        self.y = rng.uniform(-60, config.LOGICAL_H) if initial else rng.uniform(-160, -40)
        self.vy = rng.uniform(40, 90) * (0.5 + self.depth)
        self.vx = rng.uniform(-12, 12)
        self.angle = rng.uniform(0, math.tau)
        self.spin = rng.uniform(-1.2, 1.2)

    def update(self, dt):
        self.y += self.vy * dt
        self.x += self.vx * dt
        self.angle += self.spin * dt
        if self.y > config.LOGICAL_H + 40:
            self.reset()


class MenuScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.bg = make_background(app)
        self.rng = random.Random()
        self.shapes = [_DemoShape(self.rng, True) for _ in range(DEMO_COUNT)]
        self.timer = 0.0
        self.best = None
        cx = config.LOGICAL_W // 2
        self.menu = Menu([
            Button("menu.play", self._play),
            Button("menu.howto", lambda: self.app.scenes.push("howto")),
            Button("menu.credits", lambda: self.app.scenes.push("credits")),
            Button("menu.settings", lambda: self.app.scenes.push("settings")),
            Button("menu.quit", self._ask_quit, sound="ui_back", color=PAL["magenta"]),
        ], cx, 420, 66, app=app, width=300, row_height=56, font_size=32, on_back=self._on_escape)

    #Scene hooks
    def on_enter(self, **kwargs):
        self.timer = 0.0
        self.menu.reset(0)
        self.best = load_best()
        self.bg.set_accent(PAL["cyan"])
        self.app.audio.play_music("menu")

    def on_resume(self):
        self.best = load_best()
        self.menu.dragging = None

    def on_resize(self, old_w):
        self.bg = make_background(self.app)
        self.bg.set_accent(PAL["cyan"], instant=True)
        self.shapes = [_DemoShape(self.rng, True) for _ in range(DEMO_COUNT)]
        self.menu.center_x = config.LOGICAL_W // 2
        self.menu.layout()

    def _play(self):
        self.app.scenes.switch("play")

    def _ask_quit(self):
        self.app.scenes.push("confirm_quit")

    def _on_escape(self):
        # First Esc jumps to Quit; Esc on Quit asks for confirmation
        quit_i = len(self.menu.widgets) - 1
        if self.menu.focus == quit_i:
            self._ask_quit()
        else:
            self.menu.set_focus(quit_i, sound=False)

    def handle_event(self, event):
        self.menu.handle_event(event)

    def update(self, dt):
        self.timer += dt
        self.bg.update(dt)
        for s in self.shapes:
            s.update(dt)
        self.menu.update(dt)
        if self.app.autoplay and self.timer >= AUTOPLAY_DELAY:
            self.timer = -1e9           # only once per visit
            self._play()

    #Drawing
    def draw(self, surf):
        tm = self.app.time
        self.bg.draw(surf)
        for s in sorted(self.shapes, key=lambda s: s.depth):
            draw_item_shape(surf, s.kind, (s.x, s.y), s.r, tm, s.angle, s.power, self.app.assets,
                            brightness=0.25 + 0.35 * s.depth, glow=s.depth > 0.7)
        self._draw_title(surf, tm)
        self._draw_best(surf)
        self.menu.draw(surf)
        hint = self.app.assets.text(t("menu.hint"), 22, PAL["dim"], "regular")
        surf.blit(hint, hint.get_rect(midbottom=(config.LOGICAL_W // 2, config.LOGICAL_H - 22)))

    def _draw_title(self, surf, tm):
        a = self.app.assets
        cx = config.LOGICAL_W // 2
        cy = 205 + int(math.sin(tm * 1.6) * 4)
        title = t("menu.title")
        pulse = 0.5 + 0.5 * math.sin(tm * 2.4)
        # Magenta outer haze + cyan inner glow, both pulsing, then the crisp core
        haze = text_glow_layer(a, title, TITLE_SIZE, PAL["magenta"], "display", spread=6)
        draw_glow(surf, dimmed(haze, 0.55 + 0.35 * pulse), (cx + 3, cy + 2))
        glow = text_glow_layer(a, title, TITLE_SIZE, PAL["cyan"], "display", spread=3)
        draw_glow(surf, dimmed(glow, 0.6 + 0.4 * (1 - pulse)), (cx, cy))
        shadow = a.text(title, TITLE_SIZE, scale_color(PAL["magenta"], 0.9), "display")
        surf.blit(shadow, shadow.get_rect(center=(cx + 3, cy + 3)))
        core = a.text(title, TITLE_SIZE, (205, 250, 255), "display")
        surf.blit(core, core.get_rect(center=(cx, cy)))
        # "v2" tag + subtitle
        tag = neon_text(a, "v2", 28, PAL["yellow"], "black")
        tr = tag.get_rect(center=(cx + core.get_width() // 2 + 6, cy + 46))
        tr.right = min(tr.right, config.LOGICAL_W - 2)
        surf.blit(tag, tr)
        sub = a.text(t("menu.subtitle"), 26, PAL["white"], "regular")
        surf.blit(sub, sub.get_rect(center=(cx, cy + 82)))

    def _draw_best(self, surf):
        a = self.app.assets
        if self.best and self.best[0] > 0:
            s = t("menu.best", score=self.best[0], level=max(1, self.best[1]))
            col = PAL["yellow"]
        else:
            s, col = t("menu.no_best"), PAL["dim"]
        txt = a.text(s, 24, col, "bold")
        surf.blit(txt, txt.get_rect(center=(config.LOGICAL_W // 2, 362)))
