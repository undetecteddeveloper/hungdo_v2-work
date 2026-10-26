"""Quit confirmation overlay: Stay / Quit. Esc stays; the default focus is Stay."""
import math

from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import Button, Menu, dim_backdrop, make_background, neon_text, translucent_panel

import pygame as pg

PAL = config.PALETTE

PANEL = pg.Rect(0, 0, 420, 330)
PANEL.center = (config.LOGICAL_W // 2, config.LOGICAL_H // 2)


class ConfirmQuitScene(Scene):
    is_overlay = True

    def __init__(self, app):
        super().__init__(app)
        self._bg = None
        self.timer = 0.0
        self.menu = Menu([
            Button("quit.no", self._stay),
            Button("quit.yes", self.app.quit, sound="ui_back", color=PAL["magenta"]),
        ], PANEL.centerx, PANEL.y + 150, 72, app=app, width=300, row_height=56, font_size=30,
            on_back=self._stay)

    def _stay(self):
        if len(self.app.scenes.stack_names) > 1:
            self.app.scenes.pop()
        else:                               # opened standalone (e.g. --start-scene confirm_quit)
            self.app.scenes.switch("menu")

    #Scene hooks
    def on_enter(self, **kwargs):
        self.timer = 0.0
        self.menu.reset(0)

    def on_resume(self):
        self.menu.dragging = None

    def handle_event(self, event):
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
        title = neon_text(a, t("quit.title"), 52, PAL["magenta"], "display")
        bob = int(round(math.sin(self.timer * 2.2) * 3))
        surf.blit(title, title.get_rect(center=(PANEL.centerx, PANEL.y + 66 + bob)))
        self.menu.draw(surf)
        hint = a.text(t("quit.hint"), 22, PAL["dim"], "regular")
        surf.blit(hint, hint.get_rect(midbottom=(PANEL.centerx, PANEL.bottom - 16)))
