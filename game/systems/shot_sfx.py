"""Sound of the boss's bullets: one short blip per bullet, spread over a few milliseconds so a crowd still sounds like n shots.

Pure logic (no pygame): PlayScene calls `add(n)` when n bullets are fired and `update(dt)` every step, and plays
`SFX` once at every volume `update` returns.
"""
import math

SFX = "boss_shot"
VOLUME = 0.55                       # a lone bullet
MIN_VOLUME = 0.2                    # floor for the louder blips of a crowded volley (the softer ones are ALTERNATE x this)
ALTERNATE = 0.85                    # every other blip is this much softer, so neighbours stay distinguishable
SOUND_LEN = 0.12                    # s: length of the blip (assets/sound/boss_shot.wav)
MAX_VOICES = 5                      # blips sounding at the same moment, at most
MIN_SPACING = SOUND_LEN / MAX_VOICES    # s between blips: this alone bounds the voices (and mixer channels) in use
MAX_SPACING = 0.04
TARGET_SPAN = 0.3                   # s a big volley should take to sound out (spacing shrinks towards MIN_SPACING)


class ShotSfx:
    def __init__(self):
        self.clear()

    def clear(self) -> None:
        self._clock = 0.0
        self._due = []              # [time, volume] of blips not played yet, in time order
        self._free = 0.0            # earliest time the next blip may start

    @property
    def pending(self) -> int:
        return len(self._due)

    def add(self, n: int) -> None:
        """n bullets left the boss now: queue one blip each. Bigger crowds are spaced tighter and sound softer."""
        if n <= 0:
            return
        crowd = len(self._due) + n
        spacing = min(MAX_SPACING, max(MIN_SPACING, TARGET_SPAN / crowd))
        volume = max(MIN_VOLUME, VOLUME / math.sqrt(crowd))
        for i in range(n):
            at = max(self._clock, self._free)
            self._free = at + spacing
            self._due.append([at, volume * (ALTERNATE if i % 2 else 1.0)])

    def update(self, dt: float) -> list:
        """Advance by dt seconds; returns the volumes of the blips that are due now."""
        self._clock += dt
        out = []
        while self._due and self._due[0][0] <= self._clock:
            out.append(self._due.pop(0)[1])
        return out
