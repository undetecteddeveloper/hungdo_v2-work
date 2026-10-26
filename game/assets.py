"""Asset cache: fonts, rendered text and (tinted) images."""
import logging
import os
from collections import OrderedDict

import pygame as pg

from . import config
from .paths import resource_path

log = logging.getLogger(config.LOGGER_NAME)


def _color_key(color) -> tuple:
    """Normalise a colour (tuple, list, pg.Color) into a hashable RGBA tuple."""
    c = pg.Color(color)
    return (c.r, c.g, c.b, c.a)


def _size_key(size):
    """None | int | (w, h) -> None | (w, h)."""
    if size is None:
        return None
    if isinstance(size, (int, float)):
        n = max(1, int(size))
        return (n, n)
    return (max(1, int(size[0])), max(1, int(size[1])))


def _display_ready() -> bool:
    return pg.display.get_init() and pg.display.get_surface() is not None


class Assets:
    """One instance lives at app.assets. Returned surfaces are shared: never draw onto them."""

    def __init__(self):
        if not pg.font.get_init():
            pg.font.init()
        self._fonts = {}
        self._text = OrderedDict()
        self._images = {}           # (rel, tint, size) -> Surface | None
        self._raw = {}              # rel -> Surface | None (unscaled, untinted)
        self._missing_logged = set()

    #Fonts
    def _font_file(self, weight: str):
        if weight == "display":
            if config.DISPLAY_FONT_FILE:
                path = resource_path(config.DISPLAY_FONT_FILE)
                if os.path.isfile(path):
                    return path
            weight = "black"
        rel = config.FONT_FILES.get(weight)
        if rel is None:
            self._warn_once(f"weight:{weight}", "Unknown font weight '%s', using regular", weight)
            rel = config.FONT_FILES["regular"]
        path = resource_path(rel)
        if os.path.isfile(path):
            return path
        self._warn_once(rel, "Font file missing: %s (using pygame default)", rel)
        return None

    def font(self, size: int, weight: str = "regular") -> pg.font.Font:
        size = max(1, int(size))
        key = (size, weight)
        f = self._fonts.get(key)
        if f is None:
            f = pg.font.Font(self._font_file(weight), size)
            self._fonts[key] = f
        return f

    #Text
    def text(self, s: str, size: int, color, weight: str = "regular") -> pg.Surface:
        """Rendered antialiased text, LRU-cached by all arguments."""
        key = (s, int(size), _color_key(color), weight)
        surf = self._text.get(key)
        if surf is not None:
            self._text.move_to_end(key)
            return surf
        surf = self.font(size, weight).render(str(s), True, key[2][:3])
        if key[2][3] != 255:
            surf.set_alpha(key[2][3])
        if _display_ready():
            surf = surf.convert_alpha()
        self._text[key] = surf
        if len(self._text) > config.TEXT_CACHE_SIZE:
            self._text.popitem(last=False)
        return surf

    def clear_text_cache(self) -> None:
        self._text.clear()

    #Images
    def _load_raw(self, rel: str):
        if rel in self._raw:
            return self._raw[rel]
        path = resource_path(rel)
        surf = None
        if os.path.isfile(path):
            try:
                surf = pg.image.load(path)
                if _display_ready():
                    surf = surf.convert_alpha()
            except (pg.error, OSError) as e:
                log.warning("Could not load image %s: %s", rel, e)
                surf = None
        else:
            self._warn_once(rel, "Image missing: %s", rel)
        self._raw[rel] = surf
        return surf

    def image(self, rel_path: str, tint=None, size=None):
        """Cached image, optionally scaled and tinted (multiplies a white glyph). None if missing."""
        tint_key = _color_key(tint) if tint is not None else None
        size_key = _size_key(size)
        key = (rel_path, tint_key, size_key)
        if key in self._images:
            return self._images[key]

        base = self._load_raw(rel_path)
        surf = None
        if base is not None:
            surf = base
            if size_key and size_key != base.get_size():
                try:
                    surf = pg.transform.smoothscale(base, size_key)
                except ValueError:
                    surf = pg.transform.scale(base, size_key)
            if tint_key is not None:
                surf = surf.copy()
                surf.fill(tint_key, special_flags=pg.BLEND_RGBA_MULT)
        self._images[key] = surf
        return surf

    def icon(self, name: str, color, size: int):
        """Power-up/item glyph from config.ICON_FILES, or None (caller draws a fallback)."""
        rel = config.ICON_FILES.get(name)
        if rel is None:
            return None
        return self.image(rel, tint=color, size=size)

    def _warn_once(self, key, msg, *args):
        if key not in self._missing_logged:
            self._missing_logged.add(key)
            log.warning(msg, *args)
