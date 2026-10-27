"""CHEAT (temporary, F9 in a round): pick which boss to fight. Overlay on top of the play scene.

on_enter(on_pick, current): `on_pick(number)` is called once with the chosen boss number (1..MAX_START_BOSS), then the
scene pops itself. Esc / F9 close it without a choice.
"""
import pygame as pg

from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import Button, Menu, dim_backdrop, neon_text, translucent_panel

PAL = config.PALETTE

PANEL_W = 400
ROW_SPACING = 48
HEADER_H = 96


class _BossButton(Button):
    """A row labelled "Boss 3 - lv 30" (the label depends on the number, not on a fixed i18n key)."""

    def __init__(self, number: int, on_click):
        super().__init__("cheat.boss", on_click)
        self.number = number

    @property
    def label(self) -> str:
        return t("cheat.boss", n=self.number, lv=self.number * config.BOSS_EVERY)


class CheatBossScene(Scene):
    is_overlay = True

    def __init__(self, app):
        super().__init__(app)
        self.on_pick = None
        self.panel = pg.Rect(0, 0, PANEL_W, 0)
        self.menu = None
        self._build(1)

    def _build(self, focus: int) -> None:
        rows = config.MAX_START_BOSS + 1                       # every boss + "back"
        self.panel.size = (PANEL_W, HEADER_H + rows * ROW_SPACING + 28)
        self.panel.center = (config.LOGICAL_W // 2, config.LOGICAL_H // 2)
        widgets = [_BossButton(n, lambda n=n: self._pick(n)) for n in range(1, config.MAX_START_BOSS + 1)]
        widgets.append(Button("cheat.back", self._close, sound="ui_back", color=PAL["magenta"]))
        self.menu = Menu(widgets, self.panel.centerx, self.panel.y + HEADER_H, ROW_SPACING, app=self.app, width=300,
                         row_height=40, font_size=26, on_back=self._close)
        self.menu.reset(max(0, min(len(widgets) - 1, focus - 1)))

    #Actions
    def _close(self) -> None:
        self.app.scenes.pop()

    def _pick(self, number: int) -> None:
        cb, self.on_pick = self.on_pick, None
        self.app.scenes.pop()
        if cb is not None:
            cb(number)

    #Scene hooks
    def on_enter(self, on_pick=None, current: int = 1, **kwargs):
        self.on_pick = on_pick
        self._build(current)

    def on_resize(self, old_w):
        self._build(self.menu.focus + 1 if self.menu is not None else 1)

    def on_resume(self):
        self.menu.dragging = None

    def handle_event(self, event):
        if event.type == pg.KEYDOWN and event.key == pg.K_F9:
            self._close()
            return
        self.menu.handle_event(event)

    def update(self, dt):
        self.menu.update(dt)

    def draw(self, surf):
        a = self.app.assets
        surf.blit(dim_backdrop(165), (0, 0))
        surf.blit(translucent_panel(self.panel.w, self.panel.h, (8, 10, 30), 215, 24), self.panel)
        pg.draw.rect(surf, (48, 54, 100), self.panel, 2, border_radius=24)
        title = neon_text(a, t("cheat.title"), 40, PAL["yellow"], "display")
        surf.blit(title, title.get_rect(center=(self.panel.centerx, self.panel.y + 42)))
        hint = a.text(t("cheat.hint"), 18, PAL["dim"], "regular")
        surf.blit(hint, hint.get_rect(center=(self.panel.centerx, self.panel.y + 76)))
        self.menu.draw(surf)
