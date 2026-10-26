"""How to play: every item (drawn with the real Item code) + effect, and the controls."""
import logging

import pygame as pg

from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import (KIND_COLORS, POWER_COLORS, Button, Menu, draw_item_shape, draw_keycap,
                          make_background, neon_text, translucent_panel)

log = logging.getLogger(config.LOGGER_NAME)
PAL = config.PALETTE

# (kind, power) rows in display order
ROWS = [("common", None), ("rare", None), ("epic", None), ("bomb", None),
        ("powerup", "magnet"), ("powerup", "slow"), ("powerup", "wide"),
        ("powerup", "shield"), ("powerup", "heart")]

ROW_TOP = 128
ROW_H = 53
ICON_X = 62
TEXT_X = 104
CANVAS = 76             # each item is drawn into its own canvas, then soft-masked


def _radial_mask(size: int) -> pg.Surface:
    """White centre fading to black at the edge (BLEND_MULT) so item glows stay in their row."""
    m = pg.Surface((size, size))
    m.fill((0, 0, 0))
    c = size // 2
    inner = size * 0.3
    for r in range(c, 0, -1):
        v = int(255 * min(1.0, (c - r) / (c - inner)) ** 1.6)
        pg.draw.circle(m, (v, v, v), (c, c), r)
    return m.convert() if pg.display.get_surface() is not None else m


def _make_item(kind: str, power, pos):
    """Real entities.items.Item at pos, or None (fallback drawing)."""
    try:
        from ..entities.items import Item
        return Item(kind, pos[0], pos[1], power=power)
    except Exception as e:      # module missing or tunables not in config yet
        log.info("HowTo: real Item unavailable for %s (%s); using fallback shape", kind, e)
        return None


class HowToScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.bg = make_background(app)
        self.items = None           # built lazily (needs the display for convert())
        self.canvas = None
        self.mask = None
        self.menu = Menu([Button("ui.back", self._back, sound="ui_back")],
                         config.LOGICAL_W // 2, config.LOGICAL_H - 74, 60, app=app, width=240,
                         row_height=50, font_size=28, on_back=self._back)

    def on_resize(self, old_w):
        self.bg = make_background(self.app)
        self.menu.center_x = config.LOGICAL_W // 2
        self.menu.layout()

    def _back(self):
        if len(self.app.scenes.stack_names) > 1:
            self.app.scenes.pop()
        else:
            self.app.scenes.switch("menu")

    def _build_items(self):
        c = CANVAS // 2
        self.items = [_make_item(kind, power, (c, c)) for kind, power in ROWS]
        self.canvas = pg.Surface((CANVAS, CANVAS))
        self.mask = _radial_mask(CANVAS)

    #Scene hooks
    def on_enter(self, **kwargs):
        self.menu.reset(0)
        self.bg.set_accent(PAL["purple"])

    def handle_event(self, event):
        self.menu.handle_event(event)

    def update(self, dt):
        self.bg.update(dt)
        self.menu.update(dt)
        for item in self.items or ():
            if item is not None:      # spin/pulse in place, no falling
                item.spin = getattr(item, "spin", 0.0) + getattr(item, "spin_speed", 0.0) * dt
                if hasattr(item, "age"):
                    item.age += dt

    #Drawing
    def _desc(self, kind, power) -> tuple:
        key = power or kind
        fmt = {}
        if kind in config.POINTS:
            fmt["points"] = config.POINTS[kind]
        if power in config.POWERUP_DURATION:
            fmt["s"] = config.POWERUP_DURATION[power]
        if power == "heart":
            fmt["max"] = config.MAX_LIVES
        return t(f"howto.{key}.name"), t(f"howto.{key}.desc", **fmt)

    def draw(self, surf):
        if self.items is None:
            self._build_items()
        a = self.app.assets
        tm = self.app.time
        cx = config.LOGICAL_W // 2
        dx = (config.LOGICAL_W - config.BASE_W) // 2     # the content column is BASE_W wide
        self.bg.draw(surf)

        title = neon_text(a, t("howto.title"), 50, PAL["purple"], "display")
        surf.blit(title, title.get_rect(center=(cx, 46)))

        # Items panel
        panel = pg.Rect(14 + dx, ROW_TOP - 34, config.BASE_W - 28, ROW_H * len(ROWS) + 42)
        surf.blit(translucent_panel(panel.w, panel.h, (8, 10, 30), 200, 18), panel)
        pg.draw.rect(surf, (48, 54, 100), panel, 2, border_radius=18)
        head = a.text(t("howto.items"), 20, PAL["dim"], "bold")
        surf.blit(head, (panel.x + 18, panel.y + 8))

        for i, (kind, power) in enumerate(ROWS):
            cy = ROW_TOP + i * ROW_H + ROW_H // 2
            item = self.items[i]
            if item is not None:
                # Real Item draw code into a soft-masked canvas, added onto the panel
                self.canvas.fill((0, 0, 0))
                item.draw(self.canvas, tm, a)
                self.canvas.blit(self.mask, (0, 0), special_flags=pg.BLEND_MULT)
                surf.blit(self.canvas, self.canvas.get_rect(center=(ICON_X + dx, cy)), special_flags=pg.BLEND_ADD)
            else:
                r = 11 if kind == "epic" else 16
                draw_item_shape(surf, kind, (ICON_X + dx, cy), r, tm, 0.0, power, a)
            color = POWER_COLORS.get(power, PAL["green"]) if power else KIND_COLORS[kind]
            name, desc = self._desc(kind, power)
            nt = a.text(name, 25, color, "bold")
            dt_ = a.text(desc, 22, (200, 206, 232), "regular")
            surf.blit(nt, nt.get_rect(bottomleft=(TEXT_X + dx, cy + 2)))
            surf.blit(dt_, dt_.get_rect(topleft=(TEXT_X + dx, cy + 1)))

        # Controls
        y = panel.bottom + 12
        head = a.text(t("howto.controls"), 20, PAL["dim"], "bold")
        surf.blit(head, (panel.x + 18, y))
        y += 28
        controls = ((("A", "D", "←", "→"), "howto.move"), (("P", "Esc"), "howto.pause"), (("F11",), "howto.fullscreen"))
        col_x = (panel.x + 18, panel.x + 18, panel.x + 280)
        rows_y = (y, y + 40, y + 40)
        for (keys, key), x, ry in zip(controls, col_x, rows_y):
            for k in keys:
                r = draw_keycap(surf, a, k, (x, ry), 20)
                x = r.right + 6
            lbl = a.text(t(key), 22, PAL["white"], "regular")
            surf.blit(lbl, lbl.get_rect(midleft=(x + 6, ry + 15)))
        # Tip (shrunk if a translation is too long for one line)
        tip_y = rows_y[-1] + 52
        size = 21
        tip = a.text(t("howto.tip"), size, PAL["yellow"], "regular")
        while tip.get_width() > config.BASE_W - 32 and size > 15:
            size -= 1
            tip = a.text(t("howto.tip"), size, PAL["yellow"], "regular")
        surf.blit(tip, tip.get_rect(center=(cx, tip_y)))
        self.menu.draw(surf)
