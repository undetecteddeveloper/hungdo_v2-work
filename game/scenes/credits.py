"""Credits: neon text scrolling up over the animated background, like the end of a film.

Esc / Enter / click go back to the menu; hold Space or Down to scroll faster. When the last line has gone past the
top the scene returns to the menu by itself.
"""
import pygame as pg

from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import make_background, neon_text, scale_color

PAL = config.PALETTE

AUTHOR = "Smith Nguyễn"
LOGO_DIR = "assets/images/logos"
TOOLS = (("Python", "python", (255, 212, 59)), ("pygame-ce", None, PAL["green"]), ("Claude Code", "claude", (217, 119, 87)))

SCROLL_SPEED = 62.0                 # px/s
FAST_MULT = 4.0
START_GAP = 0.8                     # s of empty screen before the first line rises
END_HOLD = 0.6                      # s after the last line has left before returning to the menu
FADE_ZONE = 120                     # px at the top and bottom of the screen in which lines fade
LOGO_SIZE = 84
FAST_KEYS = (pg.K_SPACE, pg.K_DOWN, pg.K_s)
BACK_KEYS = (pg.K_ESCAPE, pg.K_BACKSPACE, pg.K_RETURN, pg.K_KP_ENTER)


def build_lines() -> list:
    """[(kind, text, extra)] in reading order; kind is title | head | name | text | logo."""
    lines = [("title", t("menu.title"), None), ("gap", "", 30),
             ("head", t("credits.made_by"), None), ("name", AUTHOR, None), ("gap", "", 70),
             ("head", t("credits.tools"), None)]
    for name, logo, color in TOOLS:
        if logo:
            lines.append(("logo", logo, None))
        lines.append(("tool", name, color))
        lines.append(("gap", "", 26))
    lines += [("gap", "", 44), ("head", t("credits.thanks"), None), ("text", t("credits.thanks_text"), None)]
    return lines


class CreditsScene(Scene):
    def __init__(self, app):
        super().__init__(app)
        self.bg = make_background(app)
        self.offset = 0.0               # px the text block has risen
        self.timer = 0.0
        self.fast = False
        self.rows = []                  # [(y_from_block_top, kind, surface)]
        self.block_h = 0
        self._done = False

    #Layout
    def _build(self) -> None:
        a = self.app.assets
        rows, y = [], 0
        for kind, text, extra in build_lines():
            if kind == "gap":
                y += int(extra)
                continue
            if kind == "title":
                img, gap = neon_text(a, text, 84, PAL["cyan"], "display"), 24
            elif kind == "head":
                img, gap = neon_text(a, text.upper(), 28, PAL["magenta"], "display"), 22
            elif kind == "name":
                img, gap = neon_text(a, text, 50, PAL["yellow"], "display"), 0
            elif kind == "tool":
                img, gap = neon_text(a, text, 38, extra, "display"), 0
            elif kind == "logo":
                img, gap = a.image(f"{LOGO_DIR}/{text}.png", size=LOGO_SIZE), 12
            else:
                img, gap = a.text(text, 30, PAL["white"], "regular"), 0
            if img is None:
                continue
            rows.append((y, kind, img))
            y += img.get_height() + gap
        self.rows = rows
        self.block_h = y

    @property
    def total_travel(self) -> float:
        """Distance the block travels from just below the screen until its last pixel is above the top."""
        return config.LOGICAL_H + self.block_h

    #Scene hooks
    def on_enter(self, **kwargs):
        self.offset = -SCROLL_SPEED * START_GAP
        self.timer = 0.0
        self.fast = False
        self._done = False
        self._build()
        self.bg.set_accent(PAL["magenta"], instant=True)

    def on_resize(self, old_w):
        self.bg = make_background(self.app)
        self.bg.set_accent(PAL["magenta"], instant=True)

    def _back(self) -> None:
        if self._done:
            return
        self._done = True
        self.app.audio.play("ui_back")
        if len(self.app.scenes.stack_names) > 1:
            self.app.scenes.pop()
        else:
            self.app.scenes.switch("menu")

    def handle_event(self, event):
        if event.type == pg.KEYDOWN:
            if event.key in BACK_KEYS:
                self._back()
            elif event.key in FAST_KEYS:
                self.fast = True
        elif event.type == pg.KEYUP:
            if event.key in FAST_KEYS:
                self.fast = False
        elif event.type == pg.MOUSEBUTTONDOWN:
            self._back()

    def update(self, dt):
        self.timer += dt
        self.bg.update(dt)
        self.offset += SCROLL_SPEED * (FAST_MULT if self.fast else 1.0) * dt
        if self.offset >= self.total_travel + SCROLL_SPEED * END_HOLD:
            self._back()

    #Drawing
    def draw(self, surf):
        self.bg.draw(surf)
        H, cx = config.LOGICAL_H, config.LOGICAL_W // 2
        top0 = H - self.offset                       # y of the block's first pixel
        for y, _, img in self.rows:
            ry = top0 + y
            if ry > H or ry + img.get_height() < 0:
                continue
            mid = ry + img.get_height() / 2
            fade = min(1.0, mid / FADE_ZONE, (H - mid) / FADE_ZONE)
            if fade <= 0.02:
                continue
            if fade < 0.98:
                img.set_alpha(int(255 * fade))
            surf.blit(img, img.get_rect(midtop=(cx, int(ry))))
            if fade < 0.98:
                img.set_alpha(255)
        hint = self.app.assets.text(t("credits.hint"), 20, scale_color(PAL["dim"], 1.0), "regular")
        surf.blit(hint, hint.get_rect(midbottom=(cx, H - 14)))
