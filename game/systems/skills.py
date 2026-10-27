"""Boss skill items, pure logic (no pygame window needed): when one drops, which kind, the reflect shield.

`SkillDrops` decides drops: every damaging hit on the boss rolls SKILL_DROP_CHANCE, at most one item lies on the
field and two drops are at least SKILL_DROP_COOLDOWN seconds of fighting apart. `ReflectShield` is the 5 s timer
of the reflect skill. `reflect_projectile` bounces a boss shot like a mirror. PlayScene wires them to the game.
"""
from .. import config


class SkillDrops:
    """Rolls the skill item drops. `rng` is any object with random() and choice() (the scene's random.Random)."""

    def __init__(self, rng):
        self.rng = rng
        self.cooldown = 0.0             # s of fighting left before the next roll is allowed

    def reset(self) -> None:
        self.cooldown = 0.0

    def update(self, dt: float) -> None:
        """Count the cooldown down; call only with fighting time (not intro, not pause)."""
        self.cooldown = max(0.0, self.cooldown - dt)

    def roll(self, item_on_field: bool = False):
        """One damaging hit on the boss: returns the kind of the item that drops, or None.
        Nothing is rolled (and no random number is used) while the cooldown runs or an item still lies on the field."""
        if item_on_field or self.cooldown > 0.0:
            return None
        if self.rng.random() >= config.SKILL_DROP_CHANCE:
            return None
        self.cooldown = config.SKILL_DROP_COOLDOWN
        return self.rng.choice(config.SKILL_KINDS)


class ReflectShield:
    """Timer of the reflect shield: picking it up again refreshes the time, it never stacks."""

    def __init__(self):
        self.time_left = 0.0

    @property
    def active(self) -> bool:
        return self.time_left > 0.0

    @property
    def frac(self) -> float:
        """Time left as 0..1 of REFLECT_TIME (for the timer bar)."""
        return max(0.0, min(1.0, self.time_left / config.REFLECT_TIME))

    @property
    def blinking(self) -> bool:
        return 0.0 < self.time_left <= config.REFLECT_BLINK_TIME

    def activate(self) -> None:
        self.time_left = config.REFLECT_TIME

    def update(self, dt: float) -> None:
        if self.time_left > 0.0:
            self.time_left = max(0.0, self.time_left - dt)

    def clear(self) -> None:
        self.time_left = 0.0


def reflect_projectile(p, paddle) -> None:
    """Bounce boss shot `p` off the paddle like a mirror: vertical speed flips, horizontal stays. The shot is marked
    `reflected` (harmless to the player from now on) and moved just above the paddle so it cannot touch it again."""
    p.vel.y = -p.vel.y
    p.reflected = True
    p.color = config.PALETTE["green"]               # friendly colour: it now flies for the player
    p.pos.y = min(p.pos.y, paddle.top - p.hit_radius - config.REFLECT_PUSH_OUT)
