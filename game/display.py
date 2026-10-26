"""Display: OS window + fixed logical canvas, letterboxed scaling."""
import logging
import math
import os

import pygame as pg

from . import config
from .paths import resource_path

log = logging.getLogger(config.LOGGER_NAME)


def _desktop_size() -> tuple:
    try:
        sizes = pg.display.get_desktop_sizes()
        if sizes:
            return tuple(sizes[0])
    except pg.error:
        pass
    info = pg.display.Info()
    return (info.current_w, info.current_h)


def _make_fallback_icon() -> pg.Surface:
    """Procedural neon icon: catcher bar under a falling orb."""
    icon = pg.Surface((64, 64), pg.SRCALPHA)
    cyan, magenta = config.PALETTE["cyan"], config.PALETTE["magenta"]
    pg.draw.rect(icon, config.PALETTE["bg_top"], (0, 0, 64, 64), border_radius=14)
    pg.draw.circle(icon, magenta, (32, 24), 12)
    pg.draw.rect(icon, cyan, (12, 44, 40, 9), border_radius=4)
    return icon


class Display:
    """One instance lives at app.display. Everything draws onto `surface` (LOGICAL_SIZE)."""

    def __init__(self):
        os.environ.setdefault("SDL_VIDEO_CENTERED", "1")
        self.surface = pg.Surface(config.LOGICAL_SIZE)
        self.window = None
        self.fullscreen = False
        self.resolution = config.LOGICAL_SIZE   # effective windowed size
        self._mode = None                       # (fullscreen, size) last applied
        self._icon_set = False
        self._converted = False
        # Layout (recomputed when the window size changes)
        self._win_size = None
        self.scale = 1.0
        self.offset = (0, 0)
        self._dest_size = config.LOGICAL_SIZE
        self._scaled = None
        self._bars = []
        self._smooth_ok = True

    #Window setup
    def available_resolutions(self) -> list:
        """RESOLUTIONS that fit the desktop height (minus a margin); never empty."""
        dw, dh = _desktop_size()
        fit = [r for r in config.RESOLUTIONS
               if r[1] <= dh - config.DESKTOP_MARGIN_Y and r[0] <= dw]
        return fit or [config.RESOLUTIONS[0]]

    def _clamp_resolution(self, res) -> tuple:
        avail = self.available_resolutions()
        res = tuple(res)
        if res in avail:
            return res
        # Largest available that is not taller than the request, else the smallest
        smaller = [r for r in avail if r[1] <= res[1]]
        return smaller[-1] if smaller else avail[0]

    def _set_icon(self) -> None:
        if self._icon_set:
            return
        icon = None
        for rel in config.WINDOW_ICON_FILES:
            path = resource_path(rel)
            if os.path.isfile(path):
                try:
                    icon = pg.image.load(path)
                    break
                except (pg.error, OSError):
                    icon = None
        pg.display.set_icon(icon or _make_fallback_icon())
        self._icon_set = True

    def apply(self, settings) -> None:
        """(Re)create the window from settings; no-op when the mode is unchanged."""
        self.resolution = self._clamp_resolution(settings.resolution)
        if tuple(settings.resolution) != self.resolution:
            log.info("Resolution %s does not fit, using %s", settings.resolution, self.resolution)
            settings.resolution = self.resolution
        # A fullscreen window ignores the windowed size, so resizing must not rebuild it
        mode = (True, None) if settings.fullscreen else (False, self.resolution)
        if mode == self._mode and pg.display.get_surface() is not None:
            return

        self._set_icon()
        pg.display.set_caption(config.TITLE)
        try:
            if settings.fullscreen:
                self.window = pg.display.set_mode((0, 0), pg.FULLSCREEN)
            else:
                self.window = pg.display.set_mode(self.resolution)
        except pg.error as e:
            log.warning("Display mode failed (%s), falling back to windowed %s", e, self.resolution)
            settings.fullscreen = False
            self.window = pg.display.set_mode(self.resolution)
        self.fullscreen = bool(settings.fullscreen)
        self._mode = (True, None) if self.fullscreen else (False, self.resolution)

        if not self._converted:
            self.surface = self.surface.convert()
            self._converted = True
        self._win_size = None                   # force relayout
        self._layout()

    #Scaling
    def _layout(self) -> None:
        win = pg.display.get_surface()
        if win is None:
            return
        self.window = win
        size = win.get_size()
        if size == self._win_size:
            return
        self._win_size = size
        ww, wh = size
        lw, lh = config.LOGICAL_SIZE
        self.scale = min(ww / lw, wh / lh)
        dw, dh = max(1, round(lw * self.scale)), max(1, round(lh * self.scale))
        ox, oy = (ww - dw) // 2, (wh - dh) // 2
        self.offset = (ox, oy)
        self._dest_size = (dw, dh)
        # Reusable scaled target
        self._scaled = None if (dw, dh) == (lw, lh) else pg.Surface((dw, dh)).convert(self.surface)
        # Letterbox bars (filled every frame: buffer contents are undefined after a flip)
        self._bars = [r for r in (
            pg.Rect(0, 0, ww, oy), pg.Rect(0, oy + dh, ww, wh - oy - dh),
            pg.Rect(0, oy, ox, dh), pg.Rect(ox + dw, oy, ww - ox - dw, dh),
        ) if r.w > 0 and r.h > 0]

    def present(self) -> None:
        """Scale the logical canvas into the window (letterboxed) and flip."""
        self._layout()
        win = self.window
        if win is None:
            return
        for bar in self._bars:
            win.fill(config.LETTERBOX_COLOR, bar)
        if self._scaled is None:
            win.blit(self.surface, self.offset)
        else:
            if self._smooth_ok:
                try:
                    pg.transform.smoothscale(self.surface, self._dest_size, self._scaled)
                except ValueError:
                    self._smooth_ok = False     # unsupported pixel format
            if not self._smooth_ok:
                pg.transform.scale(self.surface, self._dest_size, self._scaled)
            win.blit(self._scaled, self.offset)
        pg.display.flip()

    #Coordinates
    def to_logical(self, window_pos):
        """Window pixel -> logical pixel, or None when outside the canvas (letterbox bars)."""
        self._layout()
        x = (window_pos[0] - self.offset[0]) / self.scale
        y = (window_pos[1] - self.offset[1]) / self.scale
        if 0 <= x < config.LOGICAL_W and 0 <= y < config.LOGICAL_H:
            return (int(x), int(y))
        return None

    def to_logical_clamped(self, window_pos) -> tuple:
        """Like to_logical but clamps to the canvas edge instead of returning None."""
        self._layout()
        x = (window_pos[0] - self.offset[0]) / self.scale
        y = (window_pos[1] - self.offset[1]) / self.scale
        x = min(max(x, 0), config.LOGICAL_W - 1)
        y = min(max(y, 0), config.LOGICAL_H - 1)
        return (int(x), int(y))

    def to_window(self, logical_pos) -> tuple:
        self._layout()
        return (math.floor(logical_pos[0] * self.scale + self.offset[0]),
                math.floor(logical_pos[1] * self.scale + self.offset[1]))

    def mouse_pos(self):
        """Current mouse position in logical pixels, or None if outside the canvas."""
        return self.to_logical(pg.mouse.get_pos())
