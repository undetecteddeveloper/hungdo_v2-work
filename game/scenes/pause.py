"""Pause overlay: Resume / Settings / Main menu. Esc or P resumes."""
import math

import pygame as pg

from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import Button, Menu, dim_backdrop, make_background, neon_text, translucent_panel

PAL = config.PALETTE

PANEL = pg.Rect(0, 0, 420, 420)
PANEL.center = (config.LOGICAL_W // 2, config.LOGICAL_H // 2 - 10)


class PauseScene(Scene):
    is_overlay = True

    def __init__(self, app):
        super().__init__(app)
        self._bg = None
        self.timer = 0.0
        self.menu = Menu([
            Button("pause.resume", self._resume),
            Button("pause.settings", lambda: self.app.scenes.push("settings")),
            Button("pause.menu", self._main_menu, sound="ui_back", color=PAL["magenta"]),
        ], PANEL.centerx, PANEL.y + 132, 72, app=app, width=300, row_height=56, font_size=30,
            on_back=self._resume)

    #Actions
    def _resume(self):
        if len(self.app.scenes.stack_names) > 1:
            self.app.scenes.pop()
        else:                               # opened standalone (e.g. --start-scene pause)
            self.app.scenes.switch("play")

    def _main_menu(self):
        self.app.scenes.switch("menu")

    #Scene hooks
    def on_enter(self, **kwargs):
        self.timer = 0.0
        self.menu.reset(0)
        self.app.audio.pause_music()

    def on_exit(self):
        self.app.audio.resume_music()

    def on_resume(self):
        self.menu.dragging = None

    def handle_event(self, event):
        if event.type == pg.KEYDOWN and event.key == pg.K_p:
            self.app.audio.play("ui_back")
            self._resume()
            return
        self.menu.handle_event(event)

    def update(self, dt):
        self.timer += dt
        self.menu.update(dt)

    #Drawing
    def draw(self, surf):
        a = self.app.assets
        if len(self.app.scenes.stack_names) <= 1:
            if self._bg is None:
                self._bg = make_background(self.app)
            self._bg.draw(surf)
        surf.blit(dim_backdrop(165), (0, 0))
        surf.blit(translucent_panel(PANEL.w, PANEL.h, (8, 10, 30), 215, 24), PANEL)
        pg.draw.rect(surf, (48, 54, 100), PANEL, 2, border_radius=24)
        # Title gently bobbing
        title = neon_text(a, t("pause.title"), 56, PAL["cyan"], "display")
        bob = int(round(math.sin(self.timer * 2.2) * 3))
        surf.blit(title, title.get_rect(center=(PANEL.centerx, PANEL.y + 66 + bob)))
        self.menu.draw(surf)
        hint = a.text(t("pause.hint"), 22, PAL["dim"], "regular")
        surf.blit(hint, hint.get_rect(midbottom=(PANEL.centerx, PANEL.bottom - 16)))
