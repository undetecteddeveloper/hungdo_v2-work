"""Player settings persisted to user_data_dir()/settings.json."""
import json
import logging
import os
from dataclasses import asdict, dataclass, fields

from . import config
from .paths import user_data_dir

log = logging.getLogger(config.LOGGER_NAME)

SETTINGS_FILE = "settings.json"


def _is_bool(v) -> bool:
    return isinstance(v, bool)


def _is_volume(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _as_resolution(v):
    """[w, h] -> (w, h) if sane, else None."""
    if isinstance(v, (list, tuple)) and len(v) == 2 and all(isinstance(n, int) and not isinstance(n, bool) for n in v):
        if 100 <= v[0] <= 10000 and 100 <= v[1] <= 10000:
            return (v[0], v[1])
    return None


@dataclass
class Settings:
    language: str = config.DEFAULT_LANGUAGE
    resolution: tuple = (540, 840)
    fullscreen: bool = False
    fps_cap: int = 60
    show_fps: bool = False
    music_volume: float = 0.6
    sfx_volume: float = 0.8
    screen_shake: bool = True

    @staticmethod
    def path() -> str:
        return os.path.join(user_data_dir(), SETTINGS_FILE)

    @classmethod
    def load(cls) -> "Settings":
        """Load from disk; every missing or invalid field falls back to its default."""
        s = cls()
        try:
            with open(cls.path(), "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except FileNotFoundError:
            return s
        except (OSError, ValueError) as e:
            log.warning("Settings file unreadable, using defaults: %s", e)
            return s
        if not isinstance(data, dict):
            return s

        #Validating field by field
        v = data.get("language")
        if v in config.LANGUAGES:
            s.language = v
        res = _as_resolution(data.get("resolution"))
        if res:
            s.resolution = res
        if _is_bool(data.get("fullscreen")):
            s.fullscreen = data["fullscreen"]
        v = data.get("fps_cap")
        if isinstance(v, int) and not isinstance(v, bool) and v in config.FPS_OPTIONS:
            s.fps_cap = v
        if _is_bool(data.get("show_fps")):
            s.show_fps = data["show_fps"]
        for name in ("music_volume", "sfx_volume"):
            v = data.get(name)
            if _is_volume(v):
                setattr(s, name, max(0.0, min(1.0, float(v))))
        if _is_bool(data.get("screen_shake")):
            s.screen_shake = data["screen_shake"]
        return s

    def to_dict(self) -> dict:
        d = asdict(self)
        d["resolution"] = list(self.resolution)
        return d

    def save(self) -> None:
        """Atomic write (tmp file + os.replace); failures are logged, never raised."""
        path = self.path()
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except OSError as e:
            log.warning("Could not save settings: %s", e)

    def copy(self) -> "Settings":
        return Settings(**{f.name: getattr(self, f.name) for f in fields(self)})
