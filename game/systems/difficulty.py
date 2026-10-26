"""Level thresholds and per-level spawn/physics parameters.

Level 1 is relaxed (no bombs, ~1 item/s, slow fall). Everything ramps smoothly up to
config.DIFFICULTY_MAX_LEVEL and then stays put; tests/test_gameplay.py proves every
level keeps single items reachable.
"""
from dataclasses import dataclass, field
from functools import lru_cache

from .. import config

LEVEL_BASE = 120                    # score needed for level 2
LEVEL_GROWTH = 1.45                 # each next step costs ~1.45x the previous one
MAX_LEVEL = 99                      # level number cap (difficulty itself caps earlier)


@dataclass(frozen=True)
class LevelParams:
    level: int
    spawn_interval: float           # seconds between spawn events (before jitter)
    gravity_mult: float             # x config.GRAVITY
    max_fall_speed_mult: float      # x per-kind terminal speed
    weights: dict = field(default_factory=dict)   # good kind -> relative weight
    bomb_chance: float = 0.0        # chance a spawn event is a bomb
    diagonal_chance: float = 0.0    # chance an item gets sideways speed (bounces off walls)
    burst_chance: float = 0.0       # chance a spawn event is a 2-3 item line
    powerup_interval: float = 12.0  # seconds between power-up drops

    @property
    def gravity(self) -> float:
        """Absolute level gravity (px/s²) to pass to Item.update."""
        return config.GRAVITY * self.gravity_mult


def score_for_level(level: int) -> int:
    """Minimum score for `level` (level 1 -> 0, 2 -> 120, 3 -> 290, 4 -> 540, ...)."""
    level = max(1, int(level))
    if level == 1:
        return 0
    total = LEVEL_BASE * (LEVEL_GROWTH ** (level - 1) - 1) / (LEVEL_GROWTH - 1)
    return int(total // 10 * 10)


def level_for_score(score: int) -> int:
    level = 1
    while level < MAX_LEVEL and score >= score_for_level(level + 1):
        level += 1
    return level


def level_progress(score: int) -> float:
    """0..1 progress from the current level threshold to the next (for the HUD bar)."""
    level = level_for_score(score)
    lo, hi = score_for_level(level), score_for_level(level + 1)
    if hi <= lo:
        return 1.0
    return max(0.0, min(1.0, (score - lo) / (hi - lo)))


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


@lru_cache(maxsize=None)
def params_for_level(level: int) -> LevelParams:
    """Spawn/physics parameters; values clamp at config.DIFFICULTY_MAX_LEVEL."""
    top = config.DIFFICULTY_MAX_LEVEL
    level = max(1, min(int(level), top))
    t = (level - 1) / (top - 1)                     # 0 at level 1 .. 1 at the top level

    return LevelParams(
        level=level,
        spawn_interval=round(1.0 * 0.38 ** t, 4),   # 1.0 s -> 0.38 s (geometric)
        gravity_mult=round(_lerp(1.0, 1.85, t), 4),
        max_fall_speed_mult=round(_lerp(1.0, 1.6, t), 4),
        weights={
            "common": round(_lerp(80, 42, t), 2),
            "rare": round(_lerp(17, 34, t), 2),
            "epic": round(_lerp(3, 24, t), 2),
        },
        bomb_chance=0.0 if level < 2 else round(_lerp(0.06, 0.28, (level - 2) / (top - 2)), 4),
        diagonal_chance=0.0 if level < 3 else round(_lerp(0.08, 0.38, (level - 3) / (top - 3)), 4),
        burst_chance=0.0 if level < 4 else round(_lerp(0.05, 0.20, (level - 4) / (top - 4)), 4),
        powerup_interval=round(_lerp(13.0, 9.0, t), 3),
    )
