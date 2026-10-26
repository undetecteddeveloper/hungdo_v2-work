"""Floating score popups: neon text that pops, rises and fades."""
import pygame as pg

from ..render import neon

DURATION = 0.9                      # seconds on screen
RISE = 70                           # px travelled upward (ease-out)
FADE_START = 0.45                   # fraction of life before fading begins
POP_STEPS = ((0.05, 1.35), (0.10, 1.15))   # (age, scale) used right after spawn, then 1.0
MAX_TEXTS = 32
STACK_DIST = 34                     # popups spawned close to a young one stack upward


class _Popup:
    __slots__ = ("frames", "x", "y", "age")

    def __init__(self, frames, x, y):
        self.frames = frames        # [(max_age, surface)], last one is the 1:1 surface
        self.x, self.y = x, y
        self.age = 0.0


class FloatingTexts:
    def __init__(self, assets):
        self.assets = assets
        self.items = []

    def __len__(self) -> int:
        return len(self.items)

    def spawn(self, text, pos, color, size: int = 28) -> None:
        """Pop `text` centred at `pos`; it rises and fades out in DURATION seconds."""
        base = neon.neon_text(self.assets, str(text), size, color)
        # Private copy: per-popup alpha must not touch the shared cached surface
        main = base.copy()
        frames = []
        w, h = main.get_size()
        for age, k in POP_STEPS:
            frames.append((age, pg.transform.smoothscale(main, (int(w * k), int(h * k)))))
        frames.append((DURATION, main))

        x, y = float(pos[0]), float(pos[1])
        # Avoid exact overlap with popups spawned a moment ago at the same spot
        for p in self.items:
            if p.age < 0.25 and abs(p.x - x) < STACK_DIST and abs(p.y - y) < STACK_DIST:
                y = min(y, p.y - STACK_DIST)
        if len(self.items) >= MAX_TEXTS:
            self.items.pop(0)
        self.items.append(_Popup(frames, x, y))

    def update(self, dt: float) -> None:
        expired = False
        for p in self.items:
            p.age += dt
            if p.age >= DURATION:
                expired = True
        if expired:
            self.items = [p for p in self.items if p.age < DURATION]

    def draw(self, surf: pg.Surface) -> None:
        for p in self.items:
            f = p.age / DURATION
            if f >= 1.0:
                continue
            ease = 1.0 - (1.0 - f) ** 3
            y = p.y - RISE * ease
            alpha = 255 if f < FADE_START else int(255 * (1.0 - (f - FADE_START) / (1.0 - FADE_START)))
            img = p.frames[-1][1]
            for max_age, frame in p.frames:
                if p.age < max_age:
                    img = frame
                    break
            img.set_alpha(alpha)
            w, h = img.get_size()
            surf.blit(img, (int(p.x - w / 2), int(y - h / 2)))

    def clear(self) -> None:
        self.items.clear()
