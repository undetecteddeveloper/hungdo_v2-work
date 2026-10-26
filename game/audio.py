"""AudioManager: sound effects + streamed music. Runs silent if no audio device."""
import logging
import os
import sys

import pygame as pg

from . import config
from .paths import resource_path

log = logging.getLogger(config.LOGGER_NAME)


def _candidates(rel: str) -> list:
    """rel itself, then a .wav (or .ogg) with the same stem."""
    stem, ext = os.path.splitext(rel)
    alts = [rel]
    for alt_ext in (".ogg", ".wav"):
        if ext.lower() != alt_ext:
            alts.append(stem + alt_ext)
    return alts


def _find_file(rel: str):
    for cand in _candidates(rel):
        path = resource_path(cand)
        if os.path.isfile(path):
            return path
    return None


def _no_output_device() -> bool:
    """Fast probe: True only when SDL positively reports zero playback devices.

    Opening the default WASAPI endpoint with no device blocks ~8 s before failing,
    so on Windows we enumerate first (cheap) and skip the doomed attempt.
    """
    if not sys.platform.startswith("win"):
        return False
    if os.environ.get("SDL_AUDIODRIVER", "").lower() not in ("", "wasapi"):
        return False
    try:
        from pygame._sdl2 import audio as sdl_audio, sdl2
        sdl2.init_subsystem(sdl2.INIT_AUDIO)
        return len(sdl_audio.get_audio_device_names(False)) == 0
    except Exception:       # private API: any failure -> just try the normal init
        return False


def init_mixer() -> bool:
    """Initialise the mixer if needed; False when there is no usable audio device."""
    if pg.mixer.get_init():
        return True
    if _no_output_device():
        log.warning("Audio disabled: no playback device found")
        return False
    try:
        pg.mixer.init(config.MIXER_FREQUENCY, -16, 2, config.MIXER_BUFFER)
        return True
    except pg.error as e:
        log.warning("Audio disabled (mixer init failed): %s", e)
        return False


class AudioManager:
    """One instance lives at app.audio."""

    def __init__(self, music_volume: float = 0.6, sfx_volume: float = 0.8):
        self.enabled = init_mixer()
        self.music_volume = music_volume
        self.sfx_volume = sfx_volume
        self._sounds = {}           # name -> Sound | None
        self._warned = set()
        self._last_played = {}      # name -> ticks (ms)
        self.current_music = None   # track name currently playing (or fading in)

        if self.enabled:
            pg.mixer.set_num_channels(config.MIXER_CHANNELS)
            for name in config.SOUND_FILES:
                self._sounds[name] = self._load(name)

    #Loading
    def _load(self, name: str):
        path = _find_file(config.SOUND_FILES[name])
        if path is None and name in config.LEGACY_SOUND_FILES:
            path = _find_file(config.LEGACY_SOUND_FILES[name])
        if path is None:
            return None
        try:
            return pg.mixer.Sound(path)
        except (pg.error, OSError) as e:
            log.warning("Could not load sound %s: %s", path, e)
            return None

    def _warn_once(self, key, msg, *args):
        if key not in self._warned:
            self._warned.add(key)
            log.warning(msg, *args)

    #Sound effects
    def play(self, name: str, volume: float = 1.0) -> None:
        """Play a sfx by name; missing sounds are a silent no-op (warned once)."""
        if not self.enabled:
            return
        sound = self._sounds.get(name)
        if sound is None:
            if name not in self._sounds and name in config.SOUND_FILES:
                sound = self._sounds[name] = self._load(name)
            if sound is None:
                self._warn_once(name, "Sound '%s' unavailable", name)
                return

        # Avoid stacking the same sfx many times in one instant
        now = pg.time.get_ticks()
        last = self._last_played.get(name)
        if last is not None and now - last < config.SFX_MIN_INTERVAL * 1000:
            return
        self._last_played[name] = now

        vol = max(0.0, min(1.0, volume * self.sfx_volume))
        if vol <= 0:
            return
        channel = pg.mixer.find_channel(True)
        if channel is None:
            return
        channel.play(sound)
        channel.set_volume(vol)     # play() resets channel volume, so set it after

    #Music
    def play_music(self, track: str, fade_ms: int = 800) -> None:
        """Loop a music track; no-op if it is already playing."""
        if not self.enabled:
            return
        if track == self.current_music and pg.mixer.music.get_busy():
            return
        rel = config.MUSIC_FILES.get(track)
        path = _find_file(rel) if rel else None
        if path is None:
            self._warn_once(f"music:{track}", "Music '%s' unavailable", track)
            self.stop_music(fade_ms=300)
            return
        try:
            pg.mixer.music.load(path)
            pg.mixer.music.set_volume(self.music_volume)
            pg.mixer.music.play(-1, fade_ms=fade_ms)
            self.current_music = track
        except pg.error as e:
            log.warning("Could not play music %s: %s", path, e)
            self.current_music = None

    def stop_music(self, fade_ms: int = 500) -> None:
        if not self.enabled:
            return
        self.current_music = None
        try:
            if fade_ms > 0:
                pg.mixer.music.fadeout(fade_ms)
            else:
                pg.mixer.music.stop()
        except pg.error:
            pass

    def pause_music(self) -> None:
        if self.enabled:
            pg.mixer.music.pause()

    def resume_music(self) -> None:
        if self.enabled:
            pg.mixer.music.unpause()

    #Volumes
    def set_volumes(self, music: float, sfx: float) -> None:
        self.music_volume = max(0.0, min(1.0, float(music)))
        self.sfx_volume = max(0.0, min(1.0, float(sfx)))
        if self.enabled:
            pg.mixer.music.set_volume(self.music_volume)

    def has(self, name: str) -> bool:
        """True if the sfx is loaded (useful for tests)."""
        return self._sounds.get(name) is not None
