"""Best score / level / games played, persisted to user_data_dir()/save.json."""
import json
import logging
import os

from .. import config, paths

log = logging.getLogger(config.LOGGER_NAME)

SAVE_FILE = "save.json"
SAVE_VERSION = 1


def _as_count(v) -> int:
    """Non-negative int from JSON, else 0."""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != v:
        return 0
    return max(0, int(v))


class HighScore:
    def __init__(self, autoload: bool = True):
        self._defaults()
        if autoload:
            self.load()

    def _defaults(self) -> None:
        self.best_score = 0
        self.best_level = 1
        self.best_combo = 0
        self.games_played = 0

    @staticmethod
    def path() -> str:
        # paths.user_data_dir is looked up at call time (tests monkeypatch it)
        return os.path.join(paths.user_data_dir(), SAVE_FILE)

    def load(self) -> None:
        """Read save.json; missing or corrupt file -> defaults (corrupt one is kept as .bad)."""
        self._defaults()
        path = self.path()
        try:
            with open(path, "r", encoding="utf-8-sig") as f:
                data = json.load(f)
        except FileNotFoundError:
            return
        except (OSError, ValueError) as e:
            log.warning("Save file unreadable, starting fresh: %s", e)
            self._quarantine(path)
            return
        if not isinstance(data, dict):
            log.warning("Save file has unexpected format, starting fresh")
            self._quarantine(path)
            return
        self.best_score = _as_count(data.get("best_score"))
        self.best_level = max(1, _as_count(data.get("best_level")))
        self.best_combo = _as_count(data.get("best_combo"))
        self.games_played = _as_count(data.get("games_played"))

    @staticmethod
    def _quarantine(path: str) -> None:
        try:
            os.replace(path, path + ".bad")
        except OSError:
            pass

    def submit(self, score: int, level: int, combo: int = 0) -> bool:
        """Record a finished game; True if it is a new best score. Always saves."""
        score, level, combo = _as_count(score), max(1, _as_count(level)), _as_count(combo)
        self.games_played += 1
        is_new = score > self.best_score
        if is_new:
            self.best_score = score
        self.best_level = max(self.best_level, level)
        self.best_combo = max(self.best_combo, combo)
        self.save()
        return is_new

    def to_dict(self) -> dict:
        return {
            "version": SAVE_VERSION,
            "best_score": self.best_score,
            "best_level": self.best_level,
            "best_combo": self.best_combo,
            "games_played": self.games_played,
        }

    def save(self) -> bool:
        """Atomic write (tmp file + os.replace); failures are logged, never raised."""
        path = self.path()
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
            return True
        except OSError as e:
            log.warning("Could not save high score: %s", e)
            try:
                os.remove(tmp)
            except OSError:
                pass
            return False
