"""Timed power-ups (magnet, slow, wide). Shield/heart are instant and handled by the play scene."""
import math

from .. import config

SLOW_EASE_RATE = 6.0                # 1/s, time_scale eases in/out instead of snapping
EXPIRING_SECONDS = 2.0              # HUD may blink icons in the last seconds


class PowerUps:
    ORDER = tuple(config.TIMED_POWERUPS)

    def __init__(self):
        self._remaining = {}
        self._time_scale = 1.0

    def reset(self) -> None:
        self._remaining.clear()
        self._time_scale = 1.0

    def activate(self, name: str) -> bool:
        """Start (or refresh to full) a timed power-up. False for unknown/instant names."""
        duration = config.POWERUP_DURATION.get(name)
        if duration is None:
            return False
        self._remaining[name] = float(duration)
        return True

    def update(self, dt: float) -> list:
        """Advance real (unscaled) time; returns the names that just expired."""
        expired = []
        for name in list(self._remaining):
            left = self._remaining[name] - dt
            if left <= 0:
                del self._remaining[name]
                expired.append(name)
            else:
                self._remaining[name] = left
        target = config.SLOW_FACTOR if "slow" in self._remaining else 1.0
        self._time_scale += (target - self._time_scale) * (1.0 - math.exp(-SLOW_EASE_RATE * dt))
        if abs(self._time_scale - target) < 1e-3:
            self._time_scale = target
        return expired

    def is_active(self, name: str) -> bool:
        return name in self._remaining

    def remaining(self, name: str) -> float:
        return self._remaining.get(name, 0.0)

    def duration(self, name: str) -> float:
        return float(config.POWERUP_DURATION.get(name, 0.0))

    def expiring(self, name: str) -> bool:
        return 0.0 < self.remaining(name) <= EXPIRING_SECONDS

    def active(self) -> list:
        """[(name, remaining, duration)] in a stable order (for the HUD)."""
        return [(n, self._remaining[n], self.duration(n)) for n in self.ORDER if n in self._remaining]

    @property
    def time_scale(self) -> float:
        """Item time multiplier: eases toward SLOW_FACTOR while slow is active, back to 1 after."""
        return self._time_scale
