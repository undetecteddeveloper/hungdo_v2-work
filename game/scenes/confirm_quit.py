"""Quit confirmation overlay: Stay / Quit. Esc stays; the default focus is Stay."""
import math

from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import Button, Menu, dim_backdrop, make_background, neon_text, translucent_panel

import pygame as pg

PAL = config.PALETTE

PANEL_SIZE = (420, 330)


def _panel() -> pg.Rect:
    r = pg.Rect(0, 0, *PANEL_SIZE)
    r.center = (config.LOGICAL_W // 2, config.LOGICAL_H // 2)
    return r


class ConfirmQuitScene(Scene):
    is_overlay = True

    def __init__(self, app):
        super().__init__(app)
        self.panel = _panel()
        self._bg = None
        self.timer = 0.0
        self.menu = Menu([
            Button("quit.no", self._stay),
            Button("quit.yes", self.app.quit, sound="ui_back", color=PAL["magenta"]),
        ], self.panel.centerx, self.panel.y + 150, 72, app=app, width=300, row_height=56, font_size=30,
            on_back=self._stay)

    def _stay(self):
        if len(self.app.scenes.stack_names) > 1:
            self.app.scenes.pop()
        else:                               # opened standalone (e.g. --start-scene confirm_quit)
            self.app.scenes.switch("menu")

    #Scene hooks
    def on_resize(self, old_w):
        self.panel = _panel()
        self.menu.center_x = self.panel.centerx
        self.menu.layout()
        self._bg = None

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
        surf.blit(translucent_panel(self.panel.w, self.panel.h, (8, 10, 30), 215, 24), self.panel)
        pg.draw.rect(surf, (48, 54, 100), self.panel, 2, border_radius=24)
        title = neon_text(a, t("quit.title"), 52, PAL["magenta"], "display")
        bob = int(round(math.sin(self.timer * 2.2) * 3))
        surf.blit(title, title.get_rect(center=(self.panel.centerx, self.panel.y + 66 + bob)))
        self.menu.draw(surf)
        hint = a.text(t("quit.hint"), 22, PAL["dim"], "regular")
        surf.blit(hint, hint.get_rect(midbottom=(self.panel.centerx, self.panel.bottom - 16)))
