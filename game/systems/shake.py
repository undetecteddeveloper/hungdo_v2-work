"""Trauma-based screen shake (shake = trauma^2, smooth pseudo-noise, decays over time).

The caller applies `offset` when blitting the world, and passes the settings flag:
    shake.update(dt, app.settings.screen_shake)
"""
import math
import random


class ScreenShake:
    def __init__(self, max_offset: float = 14.0, decay: float = 1.6, frequency: float = 18.0,
                 enabled: bool = True):
        self.max_offset = max_offset    # px at trauma 1
        self.decay = decay              # trauma lost per second
        self.frequency = frequency      # Hz of the wobble
        self.enabled = enabled
        self.trauma = 0.0
        self._t = 0.0
        self._offset = (0, 0)
        rnd = random.Random()
        self._phase = [rnd.uniform(0, math.tau) for _ in range(4)]

    def add(self, trauma: float) -> None:
        """Add trauma (0..1); repeated hits stack up to 1."""
        if self.enabled:
            self.trauma = min(1.0, self.trauma + max(0.0, trauma))

    def update(self, dt: float, enabled: bool = None) -> None:
        if enabled is not None:
            self.enabled = bool(enabled)
        if not self.enabled:
            self.trauma = 0.0
            self._offset = (0, 0)
            return
        self._t += dt
        self.trauma = max(0.0, self.trauma - self.decay * dt)
        if self.trauma <= 0.0:
            self._offset = (0, 0)
            return
        amount = self.max_offset * self.trauma * self.trauma
        w = math.tau * self.frequency * self._t
        ph = self._phase
        # Two incommensurate sines per axis: smooth, never visibly periodic
        nx = 0.65 * math.sin(w + ph[0]) + 0.35 * math.sin(w * 2.31 + ph[1])
        ny = 0.65 * math.sin(w * 1.13 + ph[2]) + 0.35 * math.sin(w * 2.67 + ph[3])
        self._offset = (int(round(nx * amount)), int(round(ny * amount)))

    @property
    def offset(self) -> tuple:
        """(dx, dy) in logical px; (0, 0) when disabled or calm."""
        return self._offset

    def reset(self) -> None:
        self.trauma = 0.0
        self._offset = (0, 0)
