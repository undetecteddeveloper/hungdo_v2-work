"""Catch streak and score multiplier."""
from .. import config


class Combo:
    def __init__(self):
        self.best = 0
        self.count = 0

    @property
    def multiplier(self) -> int:
        return min(1 + self.count // config.COMBO_STEP, config.COMBO_MAX_MULT)

    @property
    def progress(self) -> float:
        """0..1 progress toward the next multiplier step (1.0 when maxed)."""
        if self.multiplier >= config.COMBO_MAX_MULT:
            return 1.0
        return (self.count % config.COMBO_STEP) / config.COMBO_STEP

    def hit(self) -> bool:
        """Count a catch; True if the multiplier just went up."""
        before = self.multiplier
        self.count += 1
        self.best = max(self.best, self.count)
        return self.multiplier > before

    def break_(self) -> None:
        self.count = 0

    def reset(self) -> None:
        """New round: clears the streak and the round's best."""
        self.count = 0
        self.best = 0
