"""Settings: overlay-capable list of options; every change applies live."""
import pygame as pg

from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import (Button, Menu, Selector, Slider, Toggle, dim_backdrop, make_background, neon_text,
                          translucent_panel)

PAL = config.PALETTE

TOP_Y = 150
SPACING = 62
ROW_H = 52


def back_or_menu(app) -> None:
    """Pop when something is below, else go to the main menu."""
    if len(app.scenes.stack_names) > 1:
        app.scenes.pop()
    else:
        app.scenes.switch("menu")


class SettingsScene(Scene):
    is_overlay = True               # pushed over menu or pause; dims what is below

    def __init__(self, app):
        super().__init__(app)
        self._bg = None             # only needed when nothing is drawn below
        s = app.settings
        self.menu = Menu([
            Selector("settings.language",
                     [(code, (lambda c=code: t(f"lang.{c}"))) for code in config.LANGUAGES],
                     lambda: s.language, lambda v: self._set("language", v)),
            Selector("settings.resolution", self._resolution_options,
                     lambda: tuple(s.resolution), lambda v: self._set("resolution", tuple(v)), wrap=False),
            Toggle("settings.fullscreen", lambda: s.fullscreen, lambda v: self._set("fullscreen", bool(v))),
            Selector("settings.fps_cap",
                     [(n, (str(n) if n else (lambda: t("settings.unlimited")))) for n in config.FPS_OPTIONS],
                     lambda: s.fps_cap, lambda v: self._set("fps_cap", int(v))),
            Toggle("settings.show_fps", lambda: s.show_fps, lambda v: self._set("show_fps", bool(v))),
            Slider("settings.music", lambda: s.music_volume, lambda v: self._set("music_volume", float(v))),
            Slider("settings.sfx", lambda: s.sfx_volume, lambda v: self._set("sfx_volume", float(v))),
            Toggle("settings.shake", lambda: s.screen_shake, lambda v: self._set("screen_shake", bool(v))),
            Button("settings.back", self._back, sound="ui_back"),
        ], config.LOGICAL_W // 2, TOP_Y, SPACING, app=app, width=480, row_height=ROW_H,
            font_size=27, value_size=24, style="row", on_back=self._back, control_w=230)

    #Options
    def _resolution_options(self) -> list:
        avail = [tuple(r) for r in self.app.display.available_resolutions()]
        cur = tuple(self.app.settings.resolution)
        if cur not in avail:
            avail = sorted(avail + [cur], key=lambda r: r[1])
        return [(r, f"{r[0]} × {r[1]}") for r in avail]

    def _set(self, name: str, value) -> None:
        if getattr(self.app.settings, name) == value:
            return
        setattr(self.app.settings, name, value)
        self.app.apply_settings()

    def _back(self) -> None:
        back_or_menu(self.app)

    #Scene hooks
    def on_enter(self, **kwargs):
        self.menu.reset(0)

    def on_exit(self):
        self.app.flush_settings()           # changes are saved lazily while sliders move

    def on_resume(self):
        self.menu.dragging = None

    def on_resize(self, old_w):
        self._bg = None
        self.menu.center_x = config.LOGICAL_W // 2
        self.menu.layout()

    def handle_event(self, event):
        self.menu.handle_event(event)

    def update(self, dt):
        self.menu.update(dt)
        if self._standalone() and self._bg is not None:
            self._bg.update(dt)

    #Drawing
    def _standalone(self) -> bool:
        return len(self.app.scenes.stack_names) <= 1

    def draw(self, surf):
        a = self.app.assets
        cx = config.LOGICAL_W // 2
        if self._standalone():
            if self._bg is None:
                self._bg = make_background(self.app)
            self._bg.draw(surf)
        else:
            surf.blit(dim_backdrop(185), (0, 0))
        # Panel behind the rows
        panel = pg.Rect(0, 0, 516, self.menu.bottom - TOP_Y + 180)
        panel.midtop = (cx, TOP_Y - 104)
        surf.blit(translucent_panel(panel.w, panel.h, (8, 10, 30), 200, 22), panel)
        pg.draw.rect(surf, (48, 54, 100), panel, 2, border_radius=22)

        title = neon_text(a, t("settings.title"), 54, PAL["cyan"], "display")
        surf.blit(title, title.get_rect(center=(cx, TOP_Y - 52)))
        self.menu.draw(surf)

        y = self.menu.bottom + 10
        if self.app.settings.fullscreen:
            note = a.text(t("settings.res_note"), 21, PAL["yellow"], "regular")
            surf.blit(note, note.get_rect(midtop=(cx, y)))
        hint = a.text(t("settings.hint"), 22, PAL["dim"], "regular")
        surf.blit(hint, hint.get_rect(midbottom=(cx, panel.bottom - 10)))
