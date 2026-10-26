"""Game over: animated counters, NEW RECORD flash, Retry (Enter/Space) / Menu (Esc)."""
import math

import pygame as pg

from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import (Button, Menu, dimmed, draw_glow, ease_out_back, ease_out_cubic, glow_rect, lerp_color,
                          make_background, make_particles, neon_text, translucent_panel)
from .menu import load_best

PAL = config.PALETTE

INPUT_GUARD = 0.4           # ignore keys briefly (avoid skipping with gameplay key presses)
SCORE_TIME = 1.2            # score counter duration
STAT_DELAY = 0.5            # level/combo counters start after this
STAT_TIME = 0.7
RECORD_AT = SCORE_TIME + 0.1
AUTOPLAY_RETRY = 2.5

RETRY_KEYS = (pg.K_RETURN, pg.K_KP_ENTER, pg.K_SPACE)


def _fmt(n: int) -> str:
    return f"{int(n):,}".replace(",", " ")


class GameOverScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.bg = make_background(app)
        self.particles = make_particles(500)
        self.timer = 0.0
        self.score = self.level = self.best_combo = 0
        self.is_new_record = False
        self.record_fired = False
        self.best = None
        cx = config.LOGICAL_W // 2
        self.menu = Menu([
            Button("gameover.retry", self._retry),
            Button("gameover.menu", self._menu, sound="ui_back", color=PAL["magenta"]),
        ], cx, 642, 70, app=app, width=280, row_height=54, font_size=30)

    #Scene hooks
    def on_enter(self, score=0, level=1, best_combo=0, is_new_record=False, **kwargs):
        self.score = int(score)
        self.level = max(1, int(level))
        self.best_combo = int(best_combo)
        self.is_new_record = bool(is_new_record)
        self.timer = 0.0
        self.record_fired = False
        self.best = load_best()
        self.menu.reset(0)
        if self.particles is not None:
            self.particles.clear()
        self.bg.set_accent(PAL["magenta"] if self.is_new_record else PAL["red"])
        self.app.audio.stop_music(800)
        self.app.audio.play("game_over")

    def _retry(self):
        self.app.scenes.switch("play")

    def _menu(self):
        self.app.scenes.switch("menu")

    def handle_event(self, event):
        if event.type == pg.KEYDOWN:
            if self.timer < INPUT_GUARD:
                return
            if event.key in RETRY_KEYS:
                self.app.audio.play("ui_select")
                self._retry()
            elif event.key == pg.K_ESCAPE:
                self.app.audio.play("ui_back")
                self._menu()
            return                       # keyboard focus is not used here
        if self.timer >= INPUT_GUARD:
            self.menu.handle_event(event)

    def update(self, dt):
        self.timer += dt
        self.bg.update(dt)
        self.menu.update(dt)
        if self.particles is not None:
            self.particles.update(dt)
        if self.is_new_record and not self.record_fired and self.timer >= RECORD_AT:
            self.record_fired = True
            self.app.audio.play("new_record")
            if self.particles is not None:
                c = (config.LOGICAL_W // 2, 236)
                for col in (PAL["yellow"], PAL["magenta"], PAL["cyan"]):
                    self.particles.burst(c, col, count=40, speed=(120, 520), life=(0.5, 1.2), gravity=380)
                self.particles.ring(c, PAL["yellow"], radius=160)
        if self.app.autoplay and self.timer >= AUTOPLAY_RETRY:
            self.timer = -1e9
            self._retry()

    #Drawing
    def _count(self, value: int, start: float, duration: float) -> int:
        k = ease_out_cubic((self.timer - start) / duration) if self.timer > start else 0.0
        return int(round(value * k))

    def draw(self, surf):
        a = self.app.assets
        cx = config.LOGICAL_W // 2
        self.bg.draw(surf)

        # Title drops in
        k = ease_out_back(min(1.0, self.timer / 0.5))
        title = neon_text(a, t("gameover.title"), 70, PAL["red"], "display")
        surf.blit(title, title.get_rect(center=(cx, int(-40 + 190 * k))))

        if self.is_new_record and self.timer >= RECORD_AT:
            self._draw_record_badge(surf, cx, 236)

        # Score panel
        panel = pg.Rect(0, 0, 440, 300)
        panel.midtop = (cx, 284)
        surf.blit(translucent_panel(panel.w, panel.h, (8, 10, 30), 190, 22), panel)
        pg.draw.rect(surf, (48, 54, 100), panel, 2, border_radius=22)
        lbl = a.text(t("gameover.score"), 24, PAL["dim"], "bold")
        surf.blit(lbl, lbl.get_rect(center=(cx, panel.y + 32)))
        score_col = PAL["yellow"] if self.is_new_record else PAL["white"]
        num = a.text(_fmt(self._count(self.score, 0.15, SCORE_TIME)), 88, score_col, "display")
        surf.blit(num, num.get_rect(center=(cx, panel.y + 100)))

        # Two stat boxes
        bw, gap = 196, 16
        for i, (key, val, col) in enumerate((("gameover.level", self.level, PAL["cyan"]),
                                             ("gameover.best_combo", self.best_combo, PAL["green"]))):
            box = pg.Rect(0, 0, bw, 104)
            box.topleft = (cx - bw - gap // 2 + i * (bw + gap), panel.y + 168)
            pg.draw.rect(surf, (52, 58, 104), box, 2, border_radius=16)
            cap = a.text(t(key), 20, PAL["dim"], "bold")
            surf.blit(cap, cap.get_rect(center=(box.centerx, box.y + 24)))
            shown = self._count(val, STAT_DELAY + i * 0.15, STAT_TIME)
            v = a.text(_fmt(shown), 48, col, "black")
            surf.blit(v, v.get_rect(center=(box.centerx, box.y + 66)))

        # Best line
        if self.best is not None and self.best[0] > 0 and not self.is_new_record:
            bt = a.text(t("gameover.best", score=_fmt(self.best[0])), 24, PAL["dim"], "bold")
            surf.blit(bt, bt.get_rect(center=(cx, panel.bottom + 26)))

        if self.particles is not None:
            self.particles.draw(surf)
        self.menu.draw(surf)
        hint = a.text(t("gameover.hint"), 22, PAL["dim"], "regular")
        surf.blit(hint, hint.get_rect(midbottom=(cx, config.LOGICAL_H - 22)))

    def _draw_record_badge(self, surf, cx, cy):
        a = self.app.assets
        age = self.timer - RECORD_AT
        pop = ease_out_back(min(1.0, age / 0.45), 2.4)
        flash = 0.5 + 0.5 * math.sin(age * 9)
        col = lerp_color(PAL["yellow"], PAL["magenta"], flash)
        txt = neon_text(a, t("gameover.new_record"), 40, PAL["yellow"], "display")
        w, h = txt.get_width() + 16, 58
        draw_glow(surf, dimmed(glow_rect(w, h, col, 18, 2), 0.5 + 0.5 * flash), (cx, cy))
        rect = pg.Rect(0, 0, w, h)
        rect.center = (cx, cy)
        surf.blit(translucent_panel(w, h, (30, 14, 40), 220, 18), rect)
        pg.draw.rect(surf, col, rect, 3, border_radius=18)
        if pop < 0.999:
            txt = pg.transform.smoothscale_by(txt, max(0.05, pop))
        surf.blit(txt, txt.get_rect(center=(cx, cy)))
