"""In-game HUD: score, best, level bar, lives, shield, combo badge, power-up timers.

Hud(app).draw(surf, state) with state = {
    "score", "best", "lives", "max_lives", "level", "level_progress" (0..1),
    "combo", "multiplier", "powerups": [(name, remaining, duration)], "shield": int,
    "boss": None | {...} }          # boss fight data, see section 5.1
With a boss the level bar, best line and combo badge give way to the boss header (name, clock, hp bar)
plus the energy meter and the beam aim hint. State without "boss" draws exactly as before.
Text surfaces are re-rendered only when the shown value changes.
"""
import math

import pygame as pg

from .. import config, i18n
from ..i18n import t
from .widgets import (POWER_COLORS, approach, clamp, dimmed, draw_glow, draw_heart, ease_out_back,
                      glow_circle, glow_rect, lerp_color, neon_text, scale_color, shape_points,
                      translucent_panel)

PAL = config.PALETTE

MARGIN = 18
FPS_AREA_H = 22                 # app draws the FPS counter in the top-right 20px
HEART_SIZE = 28
HEART_GAP = 32
POWER_R = 21                    # power-up timer radius
MULT_COLORS = {1: PAL["white"], 2: PAL["cyan"], 3: PAL["green"], 4: PAL["magenta"], 5: PAL["yellow"]}

# Boss layout (logical px; the boss body spans y ~175..325, so everything stays above 170 or below 330)
BOSS_ROW_Y = 62                 # name + clock row, where the level label normally sits
BOSS_BAR_Y = 94                 # top of the hp bar
BOSS_BAR_H = 14
ENERGY_R = 10                   # energy cell (hexagon) radius
ENERGY_GAP = 9
ENERGY_BOTTOM = 30              # cell centre distance from the canvas bottom
BEAM_TEXT_DY = 80               # "fire beam" text sits this far above the paddle line
AIM_PERIOD = 26                 # aim line dash period / dash length
AIM_DASH = 13


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
        # Boss animation state
        self.boss_hp = 1.0              # smoothed hp fraction actually drawn
        self.boss_flash = 0.0           # white flash after the hp dropped
        self.energy_pop = 0.0           # glow on the newest energy cell
        self._boss_seen = False
        self._boss_prev_hp = 1.0
        self._prev_energy = 0
        self._aim_cache = {}

    def reset(self) -> None:
        """Forget previous values (call at round start so nothing 'pops')."""
        self._prev = {}
        self.score_pop = self.mult_pop = self.life_flash = 0.0
        self.shown_progress = 0.0
        self.boss_hp = 1.0
        self.boss_flash = self.energy_pop = 0.0
        self._boss_seen = False

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
        dt = self._tick(state)
        boss = state.get("boss")
        self._tick_boss(boss, dt)
        level = int(state.get("level", 1))
        accent = level_color(level)
        self._draw_score(surf, state, accent)
        if boss:
            self._draw_boss_header(surf, boss)
        else:
            self._draw_level(surf, state, level, accent)
        self._draw_powerups(surf, state.get("powerups") or [])
        self._draw_lives(surf, state)
        if boss:
            self._draw_beam_hint(surf, boss)
            self._draw_energy(surf, boss)
        else:
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

    #Boss
    @staticmethod
    def _boss_color(c) -> tuple:
        """PALETTE key or RGB tuple -> RGB."""
        if isinstance(c, str):
            return PAL.get(c, PAL["white"])
        return tuple(c[:3])

    def _boss_colors(self, boss: dict) -> tuple:
        cols = boss.get("colors") or ("orange", "yellow")
        c1 = self._boss_color(cols[0])
        c2 = self._boss_color(cols[1] if len(cols) > 1 else cols[0])
        return c1, c2

    def _tick_boss(self, boss, dt: float) -> None:
        """Smooth hp bar, hp-loss flash and energy pop; a fresh boss makes the bar fill up from empty."""
        if not boss:
            self._boss_seen = False
            return
        target = clamp(float(boss.get("hp_frac", 1.0)))
        energy = int(boss.get("energy", 0))
        if not self._boss_seen:
            self._boss_seen = True
            self.boss_hp = 0.0
            self.boss_flash = self.energy_pop = 0.0
        else:
            if target < self._boss_prev_hp - 1e-4:
                self.boss_flash = 1.0
            if energy > self._prev_energy:
                self.energy_pop = 1.0
        self._boss_prev_hp = target
        self._prev_energy = energy
        self.boss_flash = max(0.0, self.boss_flash - dt * 5.0)
        self.energy_pop = max(0.0, self.energy_pop - dt * 3.0)
        self.boss_hp = approach(self.boss_hp, target, 10 if target < self.boss_hp else 3, dt)

    def _draw_boss_header(self, surf, boss: dict) -> None:
        """'BOSS n · NAME', clock (or ENRAGED!), phase tag and the hp bar."""
        c1, c2 = self._boss_colors(boss)
        state = boss.get("state", "fight")
        enraged = bool(boss.get("enraged")) or state == "enrage"
        now = self.app.time
        pulse = 0.5 + 0.5 * math.sin(now * 9)
        # Enraged: tint toward red in 4 steps (keeps the cached name text and glow from being rebuilt every frame)
        main = lerp_color(c1, PAL["red"], 0.35 + 0.1 * round(pulse * 3)) if enraged else c1
        W = config.LOGICAL_W

        # Name row
        name_key = boss.get("name_key") or f"boss.kind.{int(boss.get('kind', 0))}.name"
        label = f"{t('boss.number', n=int(boss.get('number', 1)))} · {t(name_key)}"
        lt = self._txt("boss_label", label, 22, main, "bold")
        surf.blit(lt, (MARGIN, BOSS_ROW_Y))
        x = MARGIN + lt.get_width() + 16
        cy = BOSS_ROW_Y + lt.get_height() // 2 + 1
        if state != "victory":
            if enraged:
                if pulse > 0.25:
                    et = self._txt("boss_enraged", t("boss.enraged"), 22, PAL["red"], "black")
                    surf.blit(et, et.get_rect(midleft=(x, cy)))
            else:
                left = max(0.0, float(boss.get("time_left", 0.0)))
                secs = int(math.ceil(left))
                col = PAL["orange"] if secs <= 10 else (200, 206, 232)
                self._draw_clock(surf, (x + 8, cy), col)
                tt = self._txt("boss_time", f"{secs // 60}:{secs % 60:02d}", 22, col, "bold")
                surf.blit(tt, tt.get_rect(midleft=(x + 22, cy)))
        pt = self._txt("boss_phase", t("boss.phase", n=int(boss.get("phase", 1))), 18, PAL["dim"], "bold")
        surf.blit(pt, pt.get_rect(midright=(W - MARGIN, cy)))

        self._draw_boss_bar(surf, c1, c2, main, PAL["red"] if enraged else c1, enraged, pulse)

    @staticmethod
    def _draw_clock(surf, center, color) -> None:
        cx, cy = center
        pg.draw.circle(surf, color, (cx, cy), 8, 2)
        pg.draw.line(surf, color, (cx, cy), (cx, cy - 5), 2)
        pg.draw.line(surf, color, (cx, cy), (cx + 3, cy + 2), 2)

    def _draw_boss_bar(self, surf, c1, c2, main, glow_color, enraged: bool, pulse: float) -> None:
        bar = pg.Rect(MARGIN, BOSS_BAR_Y, config.LOGICAL_W - 2 * MARGIN, BOSS_BAR_H)
        r = BOSS_BAR_H // 2
        flash = self.boss_flash
        shown = clamp(self.boss_hp)
        target = clamp(self._boss_prev_hp)
        # Fixed-size glow around the whole bar (cached once per width), brighter on a hit / when enraged
        glow = glow_rect(bar.w, bar.h, glow_color, r, 2)
        draw_glow(surf, dimmed(glow, 0.4 + 0.35 * flash + (0.2 * pulse if enraged else 0.0)), bar.center)
        pg.draw.rect(surf, (22, 24, 54), bar, border_radius=r)

        # Lost chunk (white) trails behind the real value, then the real fill on top
        if shown > target + 0.002:
            ch = pg.Rect(bar.x, bar.y, int(bar.w * shown), bar.h)
            pg.draw.rect(surf, lerp_color(c1, PAL["white"], 0.85), ch, border_radius=min(r, max(1, ch.w // 2)))
        fill = pg.Rect(bar.x, bar.y, int(bar.w * min(shown, target)), bar.h)
        if fill.w > 1:
            body = lerp_color(main, PAL["white"], 0.75 * flash)
            pg.draw.rect(surf, body, fill, border_radius=min(r, max(1, fill.w // 2)))
            if fill.w > 8:      # lighter strip on top: neon-tube look
                hl = pg.Rect(fill.x + 3, fill.y + 2, fill.w - 6, 3)
                pg.draw.rect(surf, lerp_color(body, PAL["white"], 0.45), hl, border_radius=2)
            if fill.w > 6:
                draw_glow(surf, dimmed(glow_circle(9, c2), 0.8), (fill.right, fill.centery))
        # Phase thresholds
        for frac in config.BOSS_PHASE_AT:
            px = bar.x + int(bar.w * frac)
            col = (92, 98, 140) if shown <= frac else (214, 220, 244)
            pg.draw.line(surf, col, (px, bar.y - 3), (px, bar.bottom + 2), 2)
        pg.draw.rect(surf, scale_color(main, 0.6), bar, 2, border_radius=r)

    def _draw_energy(self, surf, boss: dict) -> None:
        """Energy meter, bottom-left: hexagon cells, a divider after the cells needed for one beam shot."""
        if boss.get("state") == "victory":
            return
        need = max(1, int(boss.get("energy_need", config.BOSS_ENERGY_NEED)))
        cap = max(need, int(boss.get("energy_cap", config.BOSS_ENERGY_CAP)))
        energy = max(0, min(cap, int(boss.get("energy", 0))))
        ready = energy >= need
        yel = PAL["yellow"]
        now = self.app.time
        blink = 0.65 + 0.35 * math.sin(now * 9) if ready else 1.0
        cy = config.LOGICAL_H - ENERGY_BOTTOM
        step = ENERGY_R * 2 + ENERGY_GAP
        div_gap = 8                                  # extra space after the first `need` cells
        x0 = MARGIN + ENERGY_R
        lab = self._txt("boss_energy", t("boss.energy"), 16, yel if ready else PAL["dim"], "bold")
        surf.blit(lab, lab.get_rect(bottomleft=(MARGIN, cy - ENERGY_R - 6)))
        for i in range(cap):
            cx = x0 + i * step + (div_gap if i >= need else 0)
            full = i < energy
            if i == need and need < cap:             # divider between the first shot and the spare cells
                dx = cx - step // 2 - div_gap // 2 + 2
                pg.draw.line(surf, (70, 76, 120), (dx, cy - ENERGY_R), (dx, cy + ENERGY_R), 2)
            pts = shape_points("hexagon", (cx, cy), ENERGY_R, math.pi / 6)
            if full:
                lit = ready and i < need
                k = blink if lit else 0.75
                pop = self.energy_pop if i == energy - 1 else 0.0
                glow_k = min(1.0, 0.45 * k + 0.8 * pop + (0.3 if lit else 0.0))
                draw_glow(surf, dimmed(glow_circle(ENERGY_R + 4, yel), glow_k), (cx, cy))
                pg.draw.polygon(surf, scale_color(yel, 0.28 + 0.3 * k), pts)
                pg.draw.polygon(surf, lerp_color(yel, PAL["white"], 0.5 * pop + (0.25 if lit else 0.0)), pts, 3)
            else:
                pg.draw.polygon(surf, (22, 24, 50), pts)
                pg.draw.polygon(surf, (62, 68, 108), pts, 2)

    def _aim_surface(self, length: int, color, lit: bool) -> pg.Surface:
        """Cached dashed aim line (additive; black background), scrolled with `area` when blitted."""
        key = (length, tuple(color), lit)
        surf = self._aim_cache.get(key)
        if surf is None:
            w = 7 if lit else 5
            surf = pg.Surface((w, length + AIM_PERIOD))
            surf.fill((0, 0, 0))
            core = lerp_color(color, PAL["white"], 0.65 if lit else 0.25)
            core = core if lit else scale_color(core, 0.5)
            lw = 3 if lit else 2
            for y in range(0, length + AIM_PERIOD, AIM_PERIOD):
                pg.draw.rect(surf, core, ((w - lw) // 2, y, lw, AIM_DASH))
            if pg.display.get_surface() is not None:
                surf = surf.convert()
            if len(self._aim_cache) > 16:
                self._aim_cache.clear()
            self._aim_cache[key] = surf
        return surf

    def _draw_beam_hint(self, surf, boss: dict) -> None:
        """When a beam shot is ready: blinking text above the paddle and an aim line up to the boss."""
        if boss.get("state") not in ("fight", "enrage"):
            return
        need = max(1, int(boss.get("energy_need", config.BOSS_ENERGY_NEED)))
        if int(boss.get("energy", 0)) < need:
            return
        W = config.LOGICAL_W
        now = self.app.time
        px = clamp(float(boss.get("player_x", W / 2)), 0.0, float(W))
        bx = float(boss.get("boss_x", W / 2))
        half = float(boss.get("boss_half_w", 80.0)) + config.BOSS_BEAM_WIDTH / 2    # same rule as Beam.hit
        on_target = abs(px - bx) <= half
        yel = PAL["yellow"]
        top = config.BOSS_Y + 80
        length = (config.PLAYER_Y - 18) - top
        ix = int(round(px))
        aim = self._aim_surface(length, yel, on_target)
        off = int(now * 90) % AIM_PERIOD
        if on_target:
            beam_glow = glow_rect(config.BOSS_BEAM_WIDTH, length, yel, 12, 0)
            draw_glow(surf, dimmed(beam_glow, 0.3 + 0.1 * math.sin(now * 10)), (ix, top + length // 2))
        surf.blit(aim, (ix - aim.get_width() // 2, top), area=pg.Rect(0, off, aim.get_width(), length),
                  special_flags=pg.BLEND_ADD)
        if on_target:       # reticle on the boss
            rr = 12 + int(2 * math.sin(now * 10))
            pg.draw.circle(surf, PAL["white"], (ix, top), rr, 2)
            pg.draw.line(surf, yel, (ix - rr - 6, top), (ix - rr + 4, top), 2)
            pg.draw.line(surf, yel, (ix + rr - 4, top), (ix + rr + 6, top), 2)
        col = yel if int(now * 6) % 2 == 0 else PAL["white"]
        img = neon_text(self.assets, t("boss.beam_ready"), 26, col, "bold")
        rect = img.get_rect(center=(ix, config.PLAYER_Y - BEAM_TEXT_DY + int(3 * math.sin(now * 6))))
        rect.clamp_ip(pg.Rect(4, 0, max(1, W - 8), config.LOGICAL_H))
        surf.blit(img, rect)
