"""Global constants and tunables for Hứng Đồ v2.

All paths are relative to the game root (resolve them with paths.resource_path).
"""

#Window & timing
TITLE = "Hứng Đồ v2"
LOGGER_NAME = "hungdo"
DATA_DIR_NAME = "HungDo"            # %APPDATA%/HungDo

LOGICAL_SIZE = (540, 840)
LOGICAL_W, LOGICAL_H = LOGICAL_SIZE

PHYSICS_HZ = 120
PHYSICS_DT = 1 / PHYSICS_HZ
MAX_STEPS_PER_FRAME = 6

RESOLUTIONS = [(360, 560), (450, 700), (540, 840), (630, 980), (720, 1120)]  # filtered at runtime to fit desktop
DESKTOP_MARGIN_Y = 80               # taskbar + title bar room when filtering resolutions
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
