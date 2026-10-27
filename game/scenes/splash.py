"""Splash screen: two cards one after the other (the game title, then the tools it was made with).

The neon background stays on the whole time; the content of each card (logos and text) fades in, holds and
fades out on top of it. Any key or click skips to the menu.
"""
import math

import pygame as pg

from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import dimmed, draw_glow, make_background, neon_text, scale_color, text_glow_layer

PAL = config.PALETTE

FADE_IN = 0.6                       # s
HOLD = 1.3                          # s fully visible
FADE_OUT = 0.6                      # s
GAP = 0.25                          # s of empty background between the two cards
CARD_TIME = FADE_IN + HOLD + FADE_OUT
CARDS = 2
TOTAL_TIME = CARDS * CARD_TIME + (CARDS - 1) * GAP

TITLE_SIZE = 104
ICON_SIZE = 150
LOGO_SIZE = 130
LINE_SIZE = 40
LOGO_DIR = "assets/images/logos"
PYTHON_COLOR = (255, 212, 59)       # python.org yellow
CLAUDE_COLOR = (217, 119, 87)       # Claude orange (same as the logo)
TOOLS = (                           # (logo file, i18n key of the lead-in, tool name, name colour)
    ("python", "splash.written_with", "Python", PYTHON_COLOR),
    ("claude", "splash.made_with", "Claude Code", CLAUDE_COLOR),
)


def _smooth(x: float) -> float:
    x = min(1.0, max(0.0, x))
    return x * x * (3.0 - 2.0 * x)


def splash_state(tm: float):
    """(card index, opacity of that card's content 0..1) at `tm` seconds since the start; (None, 0.0) in a gap or once finished."""
    for i in range(CARDS):
        start = i * (CARD_TIME + GAP)
        local = tm - start
        if 0.0 <= local < CARD_TIME:
            if local < FADE_IN:
                return i, _smooth(local / FADE_IN)
            if local > CARD_TIME - FADE_OUT:
                return i, _smooth((CARD_TIME - local) / FADE_OUT)
            return i, 1.0
    return None, 0.0


class SplashScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.bg = make_background(app)
        self.timer = 0.0
        self._buf = None
        self._done = False

    def on_enter(self, **kwargs):
        self.timer = 0.0
        self._done = False
        self.bg.set_accent(PAL["cyan"], instant=True)

    def on_resize(self, old_w):
        self.bg = make_background(self.app)
        self.bg.set_accent(PAL["cyan"], instant=True)
        self._buf = None

    def _finish(self) -> None:
        if not self._done:
            self._done = True
            self.app.scenes.switch("menu")

    def handle_event(self, event):
        if event.type in (pg.KEYDOWN, pg.MOUSEBUTTONDOWN):
            self._finish()

    def update(self, dt):
        self.timer += dt
        self.bg.update(dt)
        if self.timer >= TOTAL_TIME:
            self._finish()

    #Drawing
    def draw(self, surf):
        self.bg.draw(surf)
        card, alpha = splash_state(self.timer)
        if card is None or alpha <= 0.0:
            return
        draw = self._draw_title if card == 0 else self._draw_tools
        if alpha >= 1.0:
            draw(surf)
            return
        # Draw the card on a copy of the background, then fade that copy in: background + alpha * content
        if self._buf is None or self._buf.get_size() != surf.get_size():
            self._buf = pg.Surface(surf.get_size(), 0, surf)
        buf = self._buf
        buf.blit(surf, (0, 0))
        draw(buf)
        buf.set_alpha(int(round(alpha * 255)))
        surf.blit(buf, (0, 0))

    def _draw_title(self, surf) -> None:
        a = self.app.assets
        tm = self.app.time
        cx, cy = config.LOGICAL_W // 2, config.LOGICAL_H // 2
        icon = a.image("assets/icon.png", size=ICON_SIZE)
        if icon is not None:
            surf.blit(icon, icon.get_rect(center=(cx, cy - 150)))
        title = t("menu.title")
        pulse = 0.5 + 0.5 * math.sin(tm * 2.4)
        # Same look as the menu title: magenta haze, cyan inner glow, crisp core
        haze = text_glow_layer(a, title, TITLE_SIZE, PAL["magenta"], "display", spread=6)
        draw_glow(surf, dimmed(haze, 0.55 + 0.35 * pulse), (cx + 3, cy + 2))
        glow = text_glow_layer(a, title, TITLE_SIZE, PAL["cyan"], "display", spread=3)
        draw_glow(surf, dimmed(glow, 0.6 + 0.4 * (1 - pulse)), (cx, cy))
        shadow = a.text(title, TITLE_SIZE, scale_color(PAL["magenta"], 0.9), "display")
        surf.blit(shadow, shadow.get_rect(center=(cx + 3, cy + 3)))
        core = a.text(title, TITLE_SIZE, (205, 250, 255), "display")
        surf.blit(core, core.get_rect(center=(cx, cy)))
        tag = neon_text(a, "v2", 28, PAL["yellow"], "black")
        tr = tag.get_rect(center=(cx + core.get_width() // 2 + 6, cy + 46))
        tr.right = min(tr.right, config.LOGICAL_W - 2)
        surf.blit(tag, tr)

    def _draw_tools(self, surf) -> None:
        a = self.app.assets
        cx = config.LOGICAL_W // 2
        block = LOGO_SIZE + 14 + 46         # logo, gap, one text line
        total = len(TOOLS) * block + (len(TOOLS) - 1) * 70
        y = (config.LOGICAL_H - total) // 2
        for logo, lead_key, name, color in TOOLS:
            img = a.image(f"{LOGO_DIR}/{logo}.png", size=LOGO_SIZE)
            if img is not None:
                surf.blit(img, img.get_rect(midtop=(cx, y)))
            lead = a.text(t(lead_key) + " ", LINE_SIZE, PAL["white"], "regular")
            tool = a.text(name, LINE_SIZE + 4, color, "display")
            w = lead.get_width() + tool.get_width()
            x = cx - w // 2
            ly = y + LOGO_SIZE + 14 + 23
            surf.blit(lead, lead.get_rect(midleft=(x, ly)))
            surf.blit(tool, tool.get_rect(midleft=(x + lead.get_width(), ly)))
            y += block + 70
