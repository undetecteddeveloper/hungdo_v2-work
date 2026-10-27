"""Global constants and tunables for Hứng Đồ v2.

All paths are relative to the game root (resolve them with paths.resource_path).
"""

#Window & timing
TITLE = "Hứng Đồ v2"
LOGGER_NAME = "hungdo"
DATA_DIR_NAME = "HungDo"            # %APPDATA%/HungDo

# The canvas is always LOGICAL_H tall; its width follows the screen/window aspect between the
# original portrait width (BASE_W) and MAX_ASPECT. Display.apply() calls set_logical_width().
BASE_W = 540
LOGICAL_H = 840
MAX_ASPECT = 21 / 9
LOGICAL_W = BASE_W
LOGICAL_SIZE = (LOGICAL_W, LOGICAL_H)


def max_logical_width() -> int:
    return round(LOGICAL_H * MAX_ASPECT)


def logical_width_for(aspect: float) -> int:
    """Canvas width for a window of width/height `aspect`, clamped to the supported range."""
    return max(BASE_W, min(max_logical_width(), round(LOGICAL_H * aspect)))


def set_logical_width(w: int) -> None:
    global LOGICAL_W, LOGICAL_SIZE
    LOGICAL_W = int(w)
    LOGICAL_SIZE = (LOGICAL_W, LOGICAL_H)


def field_scale() -> float:
    """Playfield width relative to the original portrait canvas (1.0 on a 540 wide canvas)."""
    return LOGICAL_W / BASE_W


PHYSICS_HZ = 120
PHYSICS_DT = 1 / PHYSICS_HZ
MAX_STEPS_PER_FRAME = 6

WINDOW_HEIGHT_FRACTIONS = (0.55, 0.7, 0.85, 1.0)   # windowed sizes: share of the usable desktop height
MIN_WINDOW_H = 360
DESKTOP_MARGIN_Y = 80               # taskbar + title bar room when sizing windows
FPS_OPTIONS = [30, 60, 120, 144, 0]  # 0 = unlimited
LANGUAGES = ["vi", "en"]
DEFAULT_LANGUAGE = "vi"

LETTERBOX_COLOR = (0, 0, 0)

#Colours (neon on dark navy)
PALETTE = {
    "bg_top": (6, 8, 24),
    "bg_bottom": (22, 10, 44),
    "cyan": (0, 234, 255),
    "magenta": (255, 46, 196),
    "yellow": (255, 222, 60),
    "green": (60, 255, 140),
    "red": (255, 56, 88),
    "orange": (255, 140, 36),
    "purple": (156, 92, 255),
    "white": (238, 242, 255),
    "dim": (106, 114, 156),
    # Extras (not required by the contract, handy for UI)
    "panel": (16, 18, 44),
    "black": (0, 0, 0),
}

# Accent colour per level (cycles when level > len)
LEVEL_HUES = [
    PALETTE["cyan"],
    PALETTE["purple"],
    PALETTE["magenta"],
    PALETTE["green"],
    PALETTE["orange"],
    PALETTE["yellow"],
    PALETTE["red"],
    (70, 150, 255),                 # electric blue
]

#Asset files
FONT_DIR = "assets/font"
FONT_FILES = {
    "light": "assets/font/BarlowCondensed-Light.ttf",
    "regular": "assets/font/BarlowCondensed-Regular.ttf",
    "bold": "assets/font/BarlowCondensed-Bold.ttf",
    "black": "assets/font/BarlowCondensed-Black.ttf",
}
DISPLAY_FONT_FILE = "assets/font/display.ttf"   # optional title font; falls back to FONT_FILES["black"]

SFX_NAMES = [
    "catch", "catch_rare", "catch_epic", "miss",
    "bomb", "powerup", "shield_break", "heart",
    "combo_up", "level_up", "countdown", "go",
    "ui_move", "ui_select", "ui_back", "game_over", "new_record",
    # boss fights (docs/ARCHITECTURE.md "Boss fights")
    "boss_intro", "boss_hit", "beam_charge", "beam_fire", "boss_defeat", "warning",
    "boss_shot", "boss_sweep",                      # boss attacks: one blip per bullet / sweep beam
]
# Shipped as .wav (no Vorbis encoder was available); AudioManager also tries .ogg with the same stem
SOUND_FILES = {name: f"assets/sound/{name}.wav" for name in SFX_NAMES}

# v1 sounds used only when the v2 file is missing
LEGACY_COIN = "assets/sound/v1/mixkit-winning-a-coin-video-game-2069.wav"
LEGACY_LOSE = "assets/sound/v1/drummusiclooper5000-lose-sfx-365579.mp3"
LEGACY_SOUND_FILES = {
    "catch": LEGACY_COIN, "catch_rare": LEGACY_COIN, "catch_epic": LEGACY_COIN,
    "powerup": LEGACY_COIN, "heart": LEGACY_COIN, "new_record": LEGACY_COIN,
    "miss": LEGACY_LOSE, "bomb": LEGACY_LOSE, "shield_break": LEGACY_LOSE, "game_over": LEGACY_LOSE,
}

MUSIC_FILES = {
    "menu": "assets/sound/music_menu.wav",
    "game": "assets/sound/music_game.ogg",
}

ICON_NAMES = ["magnet", "slow", "wide", "shield", "heart", "bomb", "star"]
ICON_FILES = {name: f"assets/images/icons/{name}.png" for name in ICON_NAMES}

WINDOW_ICON_FILES = ["assets/icon.png", "assets/icon.ico"]  # first one that loads wins

#Audio
MIXER_FREQUENCY = 44100
MIXER_BUFFER = 512
MIXER_CHANNELS = 24
SFX_MIN_INTERVAL = 0.03             # seconds; same sfx is not re-triggered faster than this

#Caches
TEXT_CACHE_SIZE = 512

#Gameplay tunables (values owned by GAMEPLAY)
START_LIVES = 3; MAX_LIVES = 5
PLAYER_Y = LOGICAL_H - 120; PLAYER_W = 110; PLAYER_H = 22
PLAYER_ACCEL = 4200; PLAYER_MAX_SPEED = 780; PLAYER_FRICTION = 5600; PLAYER_TURN_BOOST = 1.8
WALL_BOUNCE = 0.25
GRAVITY = 520                       # px/s², multiplied by level gravity_mult
ITEM_RESTITUTION = 0.85             # wall bounce for items with vx
POINTS = {"common": 10, "rare": 25, "epic": 50}
POWERUP_DURATION = {"magnet": 8, "slow": 6, "wide": 10}
MAGNET_RADIUS = 260; MAGNET_PULL = 2000; SLOW_FACTOR = 0.5; WIDE_FACTOR = 1.6
COMBO_STEP = 5; COMBO_MAX_MULT = 5  # mult = min(1 + combo // COMBO_STEP, COMBO_MAX_MULT)
COUNTDOWN_SECONDS = 3
# Extra gameplay tunables (GAMEPLAY additions)
PLAYER_WIDTH_RATE = 10.0            # 1/s, how fast width eases toward its target (wide power-up)
ITEM_RADIUS = {"common": 16, "rare": 16, "epic": 13, "bomb": 18, "powerup": 18}
ITEM_TERMINAL_SPEED = {"common": 470, "rare": 530, "epic": 580, "bomb": 500, "powerup": 330}  # px/s at level 1
ITEM_GRAVITY_SCALE = {"common": 1.0, "rare": 1.05, "epic": 1.08, "bomb": 1.0, "powerup": 0.8}
GOOD_KINDS = ("common", "rare", "epic")
POWERUP_NAMES = ["magnet", "slow", "wide", "shield", "heart"]
TIMED_POWERUPS = ("magnet", "slow", "wide")
DIFFICULTY_MAX_LEVEL = 15           # difficulty params stop scaling here

# A wider canvas (see field_scale) keeps the feel of the 540 wide original: the paddle gets
# faster and wider, and items spawn more often, but all less than proportionally so the
# opening stays easy. Tune the exponents here.
SPEED_EXP = 0.75                    # paddle speed / acceleration / friction ~ field_scale ** SPEED_EXP
WIDTH_EXP = 0.5                     # paddle width and magnet radius
RATE_EXP = 0.6                      # spawn rate


# Run upgrades won as boss rewards (see BOSS_UPGRADES). PlayScene sets them, resets them every round.
UPGRADE_MULT = {"wide": 1.0, "magnet": 1.0, "speed": 1.0}


def set_upgrade_mults(wide: float = 1.0, magnet: float = 1.0, speed: float = 1.0) -> None:
    UPGRADE_MULT["wide"], UPGRADE_MULT["magnet"], UPGRADE_MULT["speed"] = wide, magnet, speed


def player_w() -> float:
    return PLAYER_W * field_scale() ** WIDTH_EXP * UPGRADE_MULT["wide"]


def player_speed_mult() -> float:
    return field_scale() ** SPEED_EXP * UPGRADE_MULT["speed"]


def player_max_speed() -> float:
    return PLAYER_MAX_SPEED * player_speed_mult()


def player_accel() -> float:
    return PLAYER_ACCEL * player_speed_mult()


def player_friction() -> float:
    return PLAYER_FRICTION * player_speed_mult()


def magnet_radius() -> float:
    return MAGNET_RADIUS * field_scale() ** WIDTH_EXP * UPGRADE_MULT["magnet"]


def spawn_rate_mult() -> float:
    return field_scale() ** RATE_EXP


#Boss fights (owns the meaning of every value; tune them here only)
BOSS_EVERY = 10                     # a boss fight starts when the level reaches a multiple of this
BOSS_KINDS = 3                      # distinct boss designs; boss number n uses design (n - 1) % 3
BOSS_Y = 250                        # boss centre line (logical px); the paddle is at PLAYER_Y
BOSS_MARGIN = 24                    # min gap between the boss body and a side wall
BOSS_INTRO_TIME = 2.8               # s: warning banner + boss descends, nothing hurts yet
BOSS_VICTORY_TIME = 2.6             # s: death explosion before the reward scene
BOSS_TIME_LIMIT = 90.0              # s of fight until the boss enrages (no instant loss)
BOSS_PHASE_AT = (0.66, 0.33)        # hp fractions where phase 2 and phase 3 start
BOSS_BASE_HP = 2000.0               # "hp points" of boss 1; see boss_max_hp(). 2000 = 40 hits of the 50 hp tier-1 ball
BOSS_HP_GROWTH = 0.35               # hp x (1 + growth * cycle); cycle = (n - 1) // BOSS_KINDS
BOSS_SPEED_GROWTH = 0.20            # attack speed x (1 + growth * cycle)
BOSS_ENRAGE_RATE = 1.7              # enraged: time between attacks is divided by this
BOSS_ENRAGE_SPEED = 1.15            # enraged: projectile speed multiplier
BOSS_STAGGER_TIME = 1.0             # s without attacks right after a phase change
BOSS_BEAM_FRAC = 0.17               # one beam shot = this fraction of THAT boss's max hp, see beam_damage()
BOSS_BALL_MIN_DAMAGE = 50.0         # tier-1 ball hit on boss 1; boss n deals n times this, see ball_base_damage()
BOSS_POINTS_PER_HP = 1.0            # score per hp of damage on boss 1; boss n gives 1/n of it (hp is n times bigger), see boss_points()
BOSS_CLEAR_BONUS = 1000             # x number of bosses defeated so far (including this one)
BOSS_ENERGY_NEED = 2                # energy items per beam shot
BOSS_ENERGY_CAP = 4                 # items you can hold (two shots); more are wasted
BALL_TIER_SPEEDS = (620.0, 800.0, 1000.0)   # px/s of a flying ball per tier (tier 1 = a fresh ball)
BALL_TIER_DAMAGE = (1.0, 2.0, 3.0)          # damage factor per tier; a ball goes up one tier at every paddle bounce
BOSS_BALL_SPEED = BALL_TIER_SPEEDS[0]       # px/s of a tier-1 ball (kept as the base speed for tests / bots)
BOSS_BALL_RADIUS = 11
BOSS_BALL_MAX_ANGLE = 60.0          # degrees from vertical for a hit on the paddle edge
BOSS_BALL_MIN_VY = 0.30             # |vy| / speed never drops below this (no endless sideways rally)
BOSS_MAX_BALLS = 2                  # balls alive at once; the boss controller stops dropping more
BOSS_BALL_INTERVAL = 5.0            # s between helper-ball drops (the ball is the only source of energy)
BOSS_BALL_RESPAWN = 3.0             # s: after a ball is lost the next helper ball waits at least this long (losing one costs no life)
BOSS_HITS_PER_ENERGY = 2           # ball hits on the boss that make it drop one energy item (beam hits do not count)
BOSS_FIRST_BALL = 3.0
BOSS_HELPER_JITTER = 0.25           # +-fraction of the interval, random
BOSS_HELPER_TERMINAL = 300          # px/s: falling speed cap of helper items
BOSS_BEAM_LIFE = 0.35               # s the player's beam stays visible
BOSS_BEAM_WIDTH = 36                # px, full width of the player's beam
BOSS_HIT_IFRAMES = 1.0              # s of invulnerability after a boss hit
# Skill items (a boss drops them after damage; caught = used at once)
SKILL_DROP_CHANCE = 0.20            # per damaging hit on the boss
SKILL_DROP_COOLDOWN = 7.0           # s: minimum gap between two drops; only one skill item lies on the field
SKILL_KINDS = ("multiball", "reflect")      # picked 50/50
MULTIBALL_ANGLES = (-25.0, 0.0, 25.0)       # degrees from vertical; the bonus balls ignore BOSS_MAX_BALLS
REFLECT_TIME = 5.0                  # s a reflect shield lasts (a second pick-up refreshes it, no stacking)
REFLECT_SHAPE_DAMAGE = {"orb": 1.0, "bolt": 1.5, "shard": 2.0}   # x ball_base_damage(n) when a reflected shot hits the boss
MAX_START_BOSS = 9                  # --start-boss cap: level 90 is the last level difficulty.MAX_LEVEL (99) can reach
BOSS_UPGRADES = ("wide", "magnet", "life", "power", "speed")   # reward choices (3 of these are offered)
UPGRADE_MAX_STACK = 3               # times one upgrade can be taken in a run
UPGRADE_WIDE_STEP = 0.20            # paddle width +20% per stack
UPGRADE_MAGNET_STEP = 0.40          # magnet radius +40% per stack
UPGRADE_SPEED_STEP = 0.10           # paddle speed +10% per stack
UPGRADE_POWER_STEP = 0.25           # ball and beam damage +25% per stack
MAX_LIVES_CAP = 8                   # MAX_LIVES + "life" upgrades never exceed this


#Boss balance (one place: play.py, the HUD, the bot and the tests all go through these)
def _boss_cycle(number: int) -> int:
    return (max(1, number) - 1) // BOSS_KINDS


def ball_base_damage(number: int) -> float:
    """Tier-1 ball hit on boss `number` (1-based): 50 on boss 1, 100 on boss 2, 150 on boss 3 ... Real damage = this x BALL_TIER_DAMAGE[tier-1]."""
    return BOSS_BALL_MIN_DAMAGE * max(1, number)


def boss_max_hp(number: int) -> float:
    """Max hp of boss `number`: scales with the ball damage, so tier-1 hits needed stay ~40 (x(1 + growth * cycle))."""
    return BOSS_BASE_HP * max(1, number) * (1.0 + BOSS_HP_GROWTH * _boss_cycle(number))


def beam_damage(number: int) -> float:
    """One beam shot: BOSS_BEAM_FRAC of that boss's max hp."""
    return boss_max_hp(number) * BOSS_BEAM_FRAC


def reflect_damage(number: int, shape: str) -> float:
    """A reflected enemy shot hitting the boss: the tier-1 ball damage times the shape factor."""
    return ball_base_damage(number) * REFLECT_SHAPE_DAMAGE.get(shape, 1.0)


def boss_points(dealt_hp: float, number: int) -> int:
    """Score for `dealt_hp` of damage on boss `number` (a boss's total pool of points does not grow with its hp)."""
    return int(round(dealt_hp * BOSS_POINTS_PER_HP / max(1, number)))
