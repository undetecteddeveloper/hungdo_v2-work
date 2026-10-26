"""Boss reward: pick 1 of 3 run-long upgrades after a boss falls (overlay on top of the play scene).

on_enter(options, number, bonus, owned, on_pick): `options` are keys of config.BOSS_UPGRADES, `owned` maps
key -> times already taken, `on_pick(key)` is called once, then the scene pops itself.
Keys: A/D or arrows move, Enter/Space take, 1/2/3 quick pick. Esc/P do nothing (the choice cannot be skipped).
"""
import logging
import math

import pygame as pg

from .. import config
from ..i18n import t
from ..scene import Scene
from ..ui.widgets import (ACTIVATE_KEYS, dim_backdrop, dimmed, draw_glow, draw_keycap, ease_out_back, ease_out_cubic,
                          glow_circle, glow_rect, lerp_color, make_background, make_particles, neon_text,
                          scale_color, translucent_panel, approach, clamp)

log = logging.getLogger(config.LOGGER_NAME)
PAL = config.PALETTE

INPUT_GUARD = 0.6               # s: the player is still mashing Space to fire the beam
AUTOPLAY_PICK = 1.0             # s before the bot takes the middle card
STACK_BELOW = 700               # canvases narrower than this stack the cards vertically
HEADER_H = 206                  # space used by the title block at the top
FOOTER_H = 64                   # space reserved for the hint line

UPGRADE_COLORS = {"wide": PAL["green"], "magnet": PAL["purple"], "life": PAL["red"],
                  "power": PAL["orange"], "speed": PAL["cyan"]}
UPGRADE_ICONS = {"wide": "wide", "magnet": "magnet", "life": "heart", "power": "star"}   # speed is drawn by hand
NUMBER_KEYS = {pg.K_1: 0, pg.K_2: 1, pg.K_3: 2, pg.K_4: 3, pg.K_5: 4,
               pg.K_KP1: 0, pg.K_KP2: 1, pg.K_KP3: 2, pg.K_KP4: 3, pg.K_KP5: 4}
PREV_KEYS = (pg.K_a, pg.K_LEFT, pg.K_w, pg.K_UP)
NEXT_KEYS = (pg.K_d, pg.K_RIGHT, pg.K_s, pg.K_DOWN)

_wrap_cache = {}


def _wrap(assets, text: str, size: int, weight: str, max_w: int, max_lines: int) -> tuple:
    """Greedy word wrap; shrinks the font until it fits max_lines. Returns (lines, size)."""
    key = (text, size, weight, max_w, max_lines)
    hit = _wrap_cache.get(key)
    if hit is not None:
        return hit
    cur = size
    while True:
        font = assets.font(cur, weight)
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if line and font.size(trial)[0] > max_w:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
        if len(lines) <= max_lines or cur <= 14:
            break
        cur -= 1
    if len(_wrap_cache) > 128:
        _wrap_cache.clear()
    _wrap_cache[key] = (lines, cur)
    return lines, cur


def _fit(assets, s: str, size: int, weight: str, max_w: int, min_size: int = 16) -> int:
    while size > min_size and assets.font(size, weight).size(s)[0] > max_w:
        size -= 1
    return size


def _blit_tinted(surf, panel: pg.Surface, alpha: float, rect) -> None:
    """Blit a shared cached panel at the given alpha (restored afterwards)."""
    a = int(clamp(alpha, 0, 255))
    if a <= 0:
        return
    panel.set_alpha(a)
    surf.blit(panel, rect)
    panel.set_alpha(255)


class BossRewardScene(Scene):
    is_overlay = True

    def __init__(self, app):
        super().__init__(app)
        self.options = []
        self.number = 1
        self.bonus = 0
        self.owned = {}
        self.on_pick = None
        self.timer = 0.0
        self.focus = 0
        self.focus_anim = []
        self.done = False
        self.celebrated = False
        self.rects = []
        self.stacked = True
        self._bg = None
        self.particles = make_particles(300)
        self._layout()

    #Layout
    def _layout(self) -> None:
        """Card rects for the current canvas: a column on narrow canvases, a row on wide ones."""
        W, H = config.LOGICAL_W, config.LOGICAL_H
        n = max(1, len(self.options))
        cx = W // 2
        self.stacked = W < STACK_BELOW
        self.rects = []
        if self.stacked:
            top, bottom, gap = HEADER_H + 10, H - FOOTER_H, 14
            avail = bottom - top
            card_h = max(110, min(176, (avail - gap * (n - 1)) // n))
            card_w = min(W - 48, 560)
            y0 = top + max(0, (avail - (n * card_h + gap * (n - 1))) // 2)
            for i in range(n):
                self.rects.append(pg.Rect(cx - card_w // 2, y0 + i * (card_h + gap), card_w, card_h))
        else:
            gap = 28
            card_w = max(160, min(340, (W - 80 - gap * (n - 1)) // n))
            card_h = 372
            x0 = cx - (n * card_w + gap * (n - 1)) // 2
            top = HEADER_H + 4
            y0 = top + max(0, (H - FOOTER_H - top - card_h) // 2)
            for i in range(n):
                self.rects.append(pg.Rect(x0 + i * (card_w + gap), y0, card_w, card_h))

    def on_resize(self, old_w):
        self._layout()
        self._bg = None
        if self.particles is not None:
            self.particles.clear()

    #Scene hooks
    def on_enter(self, options=(), number=1, bonus=0, owned=None, on_pick=None, **kwargs):
        self.options = [str(o) for o in options]
        self.number = int(number)
        self.bonus = int(bonus)
        self.owned = dict(owned or {})
        self.on_pick = on_pick
        self.timer = 0.0
        self.done = False
        self.celebrated = False
        self.focus = len(self.options) // 2
        self.focus_anim = [1.0 if i == self.focus else 0.0 for i in range(len(self.options))]
        self._layout()
        if self.particles is not None:
            self.particles.clear()
        if not self.options:                # nothing to choose from: do not trap the player
            log.warning("BossReward: no options, closing")
            self.done = True
            self.app.scenes.pop()

    #Actions
    def _sound(self, name: str) -> None:
        audio = getattr(self.app, "audio", None)
        if audio is not None:
            audio.play(name)

    def _set_focus(self, i: int, sound: bool = True) -> None:
        if 0 <= i < len(self.options) and i != self.focus:
            self.focus = i
            if sound:
                self._sound("ui_move")

    def _move(self, delta: int) -> None:
        if self.options:
            self._set_focus((self.focus + delta) % len(self.options))

    def _hit(self, pos):
        if pos is None:
            return None
        for i, r in enumerate(self.rects[:len(self.options)]):
            if r.collidepoint(pos):
                return i
        return None

    def _pick(self, i: int) -> None:
        if self.done or not (0 <= i < len(self.options)):
            return
        self.done = True
        self._sound("ui_select")
        if self.on_pick is not None:
            try:
                self.on_pick(self.options[i])
            except Exception:
                log.exception("BossReward: on_pick failed for '%s'", self.options[i])
        self.app.scenes.pop()

    def handle_event(self, event):
        if self.done or self.timer < INPUT_GUARD:
            return
        et = event.type
        if et == pg.KEYDOWN:
            k = event.key
            if k in PREV_KEYS:
                self._move(-1)
            elif k in NEXT_KEYS:
                self._move(1)
            elif k in ACTIVATE_KEYS:
                self._pick(self.focus)
            elif k in NUMBER_KEYS:
                self._pick(NUMBER_KEYS[k])
            # Esc / P: deliberately ignored
        elif et == pg.MOUSEMOTION:
            i = self._hit(event.pos)
            if i is not None:
                self._set_focus(i)
        elif et == pg.MOUSEBUTTONDOWN and event.button == 1:
            i = self._hit(event.pos)
            if i is not None:
                self._set_focus(i, sound=False)
                self._pick(i)

    def update(self, dt):
        self.timer += dt
        for i in range(len(self.focus_anim)):
            self.focus_anim[i] = approach(self.focus_anim[i], 1.0 if i == self.focus else 0.0, 14, dt)
        if self.particles is not None:
            self.particles.update(dt)
            if not self.celebrated and self.timer >= 0.05:
                self.celebrated = True
                c = (config.LOGICAL_W // 2, 108)
                for col in (PAL["yellow"], PAL["cyan"], PAL["magenta"]):
                    self.particles.burst(c, col, count=30, speed=(120, 480), life=(0.5, 1.1), gravity=380)
                self.particles.ring(c, PAL["yellow"], radius=150)
        if getattr(self.app, "autoplay", False) and not self.done and self.timer >= AUTOPLAY_PICK:
            self._pick(len(self.options) // 2)

    #Drawing
    def draw(self, surf):
        a = self.app.assets
        W, H = config.LOGICAL_W, config.LOGICAL_H
        cx = W // 2
        if len(self.app.scenes.stack_names) <= 1:           # opened standalone: draw our own background
            if self._bg is None:
                self._bg = make_background(self.app)
            self._bg.draw(surf)
        surf.blit(dim_backdrop(190), (0, 0))
        self._draw_header(surf, a, cx)
        tm = self.timer
        for i, key in enumerate(self.options):
            self._draw_card(surf, a, i, key, tm)
        if self.particles is not None:
            self.particles.draw(surf)
        hint = a.text(t("boss.reward.hint"), _fit(a, t("boss.reward.hint"), 22, "regular", W - 32), PAL["dim"], "regular")
        surf.blit(hint, hint.get_rect(midbottom=(cx, H - 22)))

    def _draw_header(self, surf, a, cx):
        W = config.LOGICAL_W
        # "BOSS DEFEATED!  BONUS +n"
        k = clamp(self.timer / 0.3)
        d = neon_text(a, t("boss.defeated"), 28, PAL["green"], "bold")
        b = neon_text(a, t("boss.bonus", points=f"{self.bonus:,}".replace(",", " ")), 28, PAL["yellow"], "bold")
        gap = 14
        total = d.get_width() + b.get_width() + gap
        x = cx - total // 2
        y = 40 + int(10 * (1 - ease_out_cubic(k)))
        surf.blit(d, d.get_rect(midleft=(x, y)))
        surf.blit(b, b.get_rect(midleft=(x + d.get_width() + gap, y)))
        # Title pops in
        title = t("boss.reward.title")
        img = neon_text(a, title, _fit(a, title, 52, "display", W - 48, 24), PAL["yellow"], "display")
        scale = 0.6 + 0.4 * ease_out_back(min(1.0, self.timer / 0.45))
        if abs(scale - 1.0) > 0.01:
            img = pg.transform.smoothscale_by(img, max(0.05, scale))
        surf.blit(img, img.get_rect(center=(cx, 108)))
        sub = a.text(t("boss.reward.sub"), 22, PAL["dim"], "bold")
        surf.blit(sub, sub.get_rect(center=(cx, 158)))
        # Lives restored line with a heart
        text = a.text(t("boss.reward.lives"), 22, PAL["green"], "bold")
        heart = a.icon("heart", PAL["red"], 22)
        hw = (heart.get_width() + 8) if heart is not None else 0
        lx = cx - (text.get_width() + hw) // 2
        if heart is not None:
            surf.blit(heart, heart.get_rect(midleft=(lx, 188)))
        surf.blit(text, text.get_rect(midleft=(lx + hw, 188)))

    def _draw_icon(self, surf, a, key, center, rad, color, f, tm):
        draw_glow(surf, dimmed(glow_circle(rad + 8, color), 0.45 + 0.45 * f), center)
        pg.draw.circle(surf, scale_color(color, 0.16), center, rad)
        pg.draw.circle(surf, lerp_color(scale_color(color, 0.7), color, f), center, rad, 3)
        size = int(rad * 1.15)
        cx, cy = center
        if key == "speed":                  # two chevrons sliding right
            s = rad * 0.42
            shift = 3 * math.sin(tm * 7)
            for ox in (-0.32 * rad, 0.14 * rad):
                x = cx + ox + shift
                pg.draw.lines(surf, PAL["white"], False,
                              [(x - s * 0.5, cy - s), (x + s * 0.5, cy), (x - s * 0.5, cy + s)], max(3, rad // 9))
            return
        icon = a.icon(UPGRADE_ICONS.get(key, ""), PAL["white"], size)
        if icon is not None:
            surf.blit(icon, icon.get_rect(center=center))
        else:
            letter = a.text(key[:1].upper(), size, PAL["white"], "black")
            surf.blit(letter, letter.get_rect(center=center))

    def _draw_card(self, surf, a, i, key, tm):
        appear = clamp((tm - 0.12 - i * 0.08) / 0.4)
        if appear <= 0:
            return
        f = ease_out_cubic(self.focus_anim[i]) if i < len(self.focus_anim) else 0.0
        color = UPGRADE_COLORS.get(key, PAL["cyan"])
        base = self.rects[i]
        r = base.move(0, int(round(-8 * f + 46 * (1 - ease_out_cubic(appear)))))
        radius = 22
        draw_glow(surf, dimmed(glow_rect(r.w, r.h, color, radius, 3), 0.18 + 0.72 * f), r.center)
        surf.blit(translucent_panel(r.w, r.h, (10, 12, 34), 228, radius), r)
        _blit_tinted(surf, translucent_panel(r.w, r.h, color, 54, radius), 255 * f, r)
        pg.draw.rect(surf, lerp_color((52, 58, 104), color, 0.3 + 0.7 * f), r, 3 if f > 0.5 else 2, border_radius=radius)

        name = t(f"upgrade.{key}.name")
        desc = t(f"upgrade.{key}.desc")
        n_owned = int(self.owned.get(key, 0))
        name_col = lerp_color((200, 206, 232), PAL["white"], f)
        desc_col = (190, 196, 224)
        owned_txt = t("boss.reward.owned", n=n_owned) if n_owned > 0 else None
        label = str(i + 1)

        if self.stacked:
            rad = min(46, r.h // 2 - 14)
            self._draw_icon(surf, a, key, (r.x + 34 + rad + 10, r.centery), rad, color, f, tm)
            draw_keycap(surf, a, label, (r.x + 14, r.y + 12), 20, color)
            tx = r.x + 34 + rad * 2 + 34
            max_w = r.right - 20 - tx
            name_img = a.text(name, _fit(a, name, 34, "bold", max_w, 20), name_col, "bold")
            lines, dsize = _wrap(a, desc, 22, "regular", max_w, 2)
            line_h = a.font(dsize, "regular").get_height()
            owned_img = a.text(owned_txt, 20, color, "bold") if owned_txt else None
            total = name_img.get_height() + 4 + line_h * len(lines) + (owned_img.get_height() + 4 if owned_img else 0)
            y = r.centery - total // 2
            surf.blit(name_img, (tx, y))
            y += name_img.get_height() + 4
            for ln in lines:
                surf.blit(a.text(ln, dsize, desc_col, "regular"), (tx, y))
                y += line_h
            if owned_img is not None:
                surf.blit(owned_img, (tx, y + 4))
        else:
            self._draw_icon(surf, a, key, (r.centerx, r.y + 116), 56, color, f, tm)
            draw_keycap(surf, a, label, (r.centerx - 15, r.y + 16), 20, color)
            max_w = r.w - 32
            name_img = a.text(name, _fit(a, name, 34, "bold", max_w, 20), name_col, "bold")
            surf.blit(name_img, name_img.get_rect(center=(r.centerx, r.y + 212)))
            lines, dsize = _wrap(a, desc, 22, "regular", max_w, 3)
            line_h = a.font(dsize, "regular").get_height()
            y = r.y + 248
            for ln in lines:
                img = a.text(ln, dsize, desc_col, "regular")
                surf.blit(img, img.get_rect(midtop=(r.centerx, y)))
                y += line_h
            if owned_txt:
                oi = a.text(owned_txt, 20, color, "bold")
                surf.blit(oi, oi.get_rect(center=(r.centerx, r.bottom - 28)))
