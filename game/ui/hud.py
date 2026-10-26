"""In-game HUD: score, best, level bar, lives, shield, combo badge, power-up timers.

Hud(app).draw(surf, state) with state = {
    "score", "best", "lives", "max_lives", "level", "level_progress" (0..1),
    "combo", "multiplier", "powerups": [(name, remaining, duration)], "shield": int }
Text surfaces are re-rendered only when the shown value changes.
"""
import math

import pygame as pg

from .. import config, i18n
from ..i18n import t
from .widgets import (POWER_COLORS, approach, clamp, dimmed, draw_glow, draw_heart, ease_out_back,
                      glow_circle, glow_rect, lerp_color, scale_color, translucent_panel)

PAL = config.PALETTE

MARGIN = 18
FPS_AREA_H = 22                 # app draws the FPS counter in the top-right 20px
HEART_SIZE = 28
HEART_GAP = 32
POWER_R = 21                    # power-up timer radius
MULT_COLORS = {1: PAL["white"], 2: PAL["cyan"], 3: PAL["green"], 4: PAL["magenta"], 5: PAL["yellow"]}


def level_color(level: int) -> tuple:
    hues = config.LEVEL_HUES
    return hues[(max(1, int(level)) - 1) % len(hues)]


class Hud:
    def __init__(self, app):
        self.app = app
        self.assets = app.assets
        self._text = {}             # slot -> (key, surface)
        self._last_time = None
        # Animation state
        self.score_pop = 0.0
        self.mult_pop = 0.0
        self.life_flash = 0.0
        self.shown_progress = 0.0
        self._prev = {}
        self._arc_cache = {}

    def reset(self) -> None:
        """Forget previous values (call at round start so nothing 'pops')."""
        self._prev = {}
        self.score_pop = self.mult_pop = self.life_flash = 0.0
        self.shown_progress = 0.0

    #Cached text
    def _txt(self, slot: str, s: str, size: int, color, weight: str = "bold") -> pg.Surface:
        key = (s, size, tuple(color), weight, i18n.get_language())
        hit = self._text.get(slot)
        if hit is not None and hit[0] == key:
            return hit[1]
        surf = self.assets.font(size, weight).render(s, True, color)
        surf = surf.convert_alpha() if pg.display.get_surface() is not None else surf
        self._text[slot] = (key, surf)
        return surf

    #Animation bookkeeping
    def _tick(self, state: dict) -> float:
        now = self.app.time
        dt = 0.0 if self._last_time is None else max(0.0, min(0.1, now - self._last_time))
        self._last_time = now
        prev = self._prev
        if prev:
            if state.get("score", 0) > prev.get("score", 0):
                self.score_pop = 1.0
            if state.get("multiplier", 1) > prev.get("multiplier", 1):
                self.mult_pop = 1.0
            if state.get("lives", 0) != prev.get("lives", 0):
                self.life_flash = 1.0
        self._prev = {k: state.get(k) for k in ("score", "multiplier", "lives")}
        self.score_pop = max(0.0, self.score_pop - dt * 5.0)
        self.mult_pop = max(0.0, self.mult_pop - dt * 2.5)
        self.life_flash = max(0.0, self.life_flash - dt * 2.0)
        target = clamp(float(state.get("level_progress", 0.0)))
        if target < self.shown_progress - 0.5:      # level up: bar wraps to 0
            self.shown_progress = 0.0
        self.shown_progress = approach(self.shown_progress, target, 8, dt)
        return dt

    #Drawing
    def draw(self, surf: pg.Surface, state: dict) -> None:
        self._tick(state)
        level = int(state.get("level", 1))
        accent = level_color(level)
        self._draw_score(surf, state, accent)
        self._draw_level(surf, state, level, accent)
        self._draw_powerups(surf, state.get("powerups") or [])
        self._draw_lives(surf, state)
        self._draw_combo(surf, state)

    def _draw_score(self, surf, state, accent):
        score = int(state.get("score", 0))
        txt = self._txt("score", f"{score:,}".replace(",", " "), 48, PAL["white"], "black")
        pos = (MARGIN, 4)
        if self.score_pop > 0:
            k = 1.0 + 0.14 * self.score_pop
            big = pg.transform.smoothscale_by(txt, k)
            # Grow from the left-middle so the number does not jump
            surf.blit(big, big.get_rect(midleft=(pos[0], pos[1] + txt.get_height() // 2)))
        else:
            surf.blit(txt, pos)

    def _draw_level(self, surf, state, level, accent):
        y = 62
        lv = self._txt("level", t("hud.level", n=level), 22, accent, "bold")
        surf.blit(lv, (MARGIN, y))
        bar = pg.Rect(MARGIN + max(lv.get_width(), 52) + 10, y + lv.get_height() // 2 - 4, 150, 8)
        pg.draw.rect(surf, (34, 38, 72), bar, border_radius=4)
        fill = bar.copy()
        fill.w = int(bar.w * clamp(self.shown_progress))
        if fill.w > 2:
            pg.draw.rect(surf, accent, fill, border_radius=4)
            draw_glow(surf, dimmed(glow_circle(7, accent), 0.8), (fill.right, fill.centery))
        pg.draw.rect(surf, scale_color(accent, 0.55), bar, 1, border_radius=4)
        best = int(state.get("best", 0))
        bt = self._txt("best", t("hud.best", score=f"{best:,}".replace(",", " ")), 20, PAL["dim"], "bold")
        surf.blit(bt, (MARGIN, y + 28))

    def _arc_ring(self, color, frac: float) -> pg.Surface:
        """Cached ring arc for power-up timers (quantised to 48 steps)."""
        step = int(round(clamp(frac) * 48))
        key = (tuple(color), step)
        surf = self._arc_cache.get(key)
        if surf is None:
            size = POWER_R * 2 + 6
            surf = pg.Surface((size, size), pg.SRCALPHA)
            rect = pg.Rect(3, 3, POWER_R * 2, POWER_R * 2)
            pg.draw.circle(surf, (40, 44, 80), rect.center, POWER_R, 3)
            if step > 0:
                end = math.pi / 2
                start = end - 2 * math.pi * step / 48
                # Thick arc: several 1px arcs (pygame arcs have gaps when wide)
                for i in range(4):
                    pg.draw.arc(surf, color, rect.inflate(-i, -i), start, end, 2)
            if len(self._arc_cache) > 400:
                self._arc_cache.clear()
            self._arc_cache[key] = surf
        return surf

    def _draw_powerups(self, surf, powerups):
        x, y = MARGIN + POWER_R, 140
        for name, remaining, duration in powerups:
            color = POWER_COLORS.get(name, PAL["green"])
            frac = remaining / duration if duration else 0.0
            low = remaining < 2.0
            blink = low and int(self.app.time * 6) % 2 == 0
            draw_glow(surf, dimmed(glow_circle(POWER_R, color), 0.35 if not blink else 0.7), (x, y))
            pg.draw.circle(surf, scale_color(color, 0.18), (x, y), POWER_R - 2)
            ring = self._arc_ring(color, frac)
            surf.blit(ring, ring.get_rect(center=(x, y)))
            icon = self.assets.icon(name, PAL["white"] if not blink else color, 24)
            if icon is not None:
                surf.blit(icon, icon.get_rect(center=(x, y)))
            else:
                letter = self.assets.text(name[:1].upper(), 24, PAL["white"], "black")
                surf.blit(letter, letter.get_rect(center=(x, y)))
            secs = self.assets.text(str(int(math.ceil(remaining))), 18, color, "bold")
            surf.blit(secs, secs.get_rect(midtop=(x, y + POWER_R + 2)))
            x += POWER_R * 2 + 14

    def _draw_lives(self, surf, state):
        lives = int(state.get("lives", 0))
        max_lives = max(lives, int(state.get("max_lives", config.MAX_LIVES)))
        cy = FPS_AREA_H + 6 + HEART_SIZE // 2
        x = config.LOGICAL_W - MARGIN - HEART_SIZE // 2
        red = PAL["red"]
        full = self.assets.icon("heart", red, HEART_SIZE)
        empty = self.assets.icon("heart", (60, 40, 72), HEART_SIZE)
        flash = self.life_flash
        for i in range(max_lives - 1, -1, -1):
            filled = i < lives
            cx = x - (max_lives - 1 - i) * HEART_GAP
            if filled and flash > 0 and i == lives - 1:
                draw_glow(surf, dimmed(glow_circle(14, red), flash), (cx, cy))
            if full is not None:
                img = full if filled else empty
                surf.blit(img, img.get_rect(center=(cx, cy)))
            else:
                draw_heart(surf, (cx, cy), HEART_SIZE, red if filled else (60, 40, 72), True)
        # Shield to the left of the hearts
        if int(state.get("shield", 0)) > 0:
            sx = x - max_lives * HEART_GAP - 4
            col = POWER_COLORS["shield"]
            pulse = 0.6 + 0.4 * math.sin(self.app.time * 5)
            draw_glow(surf, dimmed(glow_circle(14, col), pulse), (sx, cy))
            icon = self.assets.icon("shield", col, HEART_SIZE)
            if icon is not None:
                surf.blit(icon, icon.get_rect(center=(sx, cy)))
            else:
                pg.draw.circle(surf, col, (sx, cy), HEART_SIZE // 2, 3)

    def _draw_combo(self, surf, state):
        combo = int(state.get("combo", 0))
        mult = int(state.get("multiplier", 1))
        if combo <= 0 and mult <= 1:
            return
        color = MULT_COLORS.get(min(mult, 5), PAL["yellow"])
        right = config.LOGICAL_W - MARGIN
        top = FPS_AREA_H + HEART_SIZE + 20
        mt = self._txt("mult", f"x{mult}", 34, color, "black")
        ct = self._txt("combo", t("hud.combo", n=combo), 20, PAL["white"], "bold")
        w = mt.get_width() + ct.get_width() + 40
        h = 44
        rect = pg.Rect(right - w, top, w, h)
        pop = self.mult_pop
        if pop > 0:
            draw_glow(surf, dimmed(glow_rect(w, h, color, 14, 2), pop), rect.center)
        surf.blit(translucent_panel(w, h, PAL["panel"], 170, 14), rect)
        pg.draw.rect(surf, lerp_color(scale_color(color, 0.6), PAL["white"], pop * 0.6), rect, 2, border_radius=14)
        slot = (rect.x + 12 + mt.get_width() // 2, rect.centery)
        if pop > 0:     # scale around its own centre so it never covers the combo text
            k = 1.0 + 0.25 * pop + 0.3 * (ease_out_back(1 - pop) - (1 - pop))
            mt = pg.transform.smoothscale_by(mt, max(1.0, min(1.25, k)))
        surf.blit(mt, mt.get_rect(center=slot))
        surf.blit(ct, ct.get_rect(midright=(rect.right - 12, rect.centery + 2)))
