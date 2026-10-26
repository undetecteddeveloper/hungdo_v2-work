"""Dev tool: unpack downloaded audio packs and turn picked clips into game SFX.

Downloaded archives are untrusted data, so this script never executes anything
from them: it only copies media files out, rejects unsafe member paths and caps
sizes. Run it isolated, passing every path as an argument:

    python -I tools/extract_audio.py extract <archive.zip> <out_dir>
    python -I tools/extract_audio.py curate <kenney_extract_root> <sound_dir>

`curate` reads the clips listed in PICKS (relative to the folder that holds the
extracted Kenney packs), trims leading/trailing silence, optionally shortens or
re-pitches them, peak-normalises to -1 dBFS and writes 16-bit mono WAVs named
after the game's SFX (`assets/sound/<name>.wav`).
"""
import os
import sys
import wave
import zipfile

#Only these file types ever leave an archive
MEDIA_EXTS = {".ogg", ".wav", ".mp3"}
MAX_MEMBER_BYTES = 20 * 1024 * 1024   # refuse anything bigger than 20 MB
MAX_TOTAL_BYTES = 200 * 1024 * 1024   # and stop past 200 MB total (zip-bomb guard)

SR = 44100
PEAK_DBFS = -1.0

#name -> (source clip, options). Sources: Kenney CC0 packs (see CREDITS.md).
#  max: cut length in seconds (with fade-out), rate: playback-rate factor (>1 = higher/shorter)
#  layer: (clip, gain) mixed under the main clip, drive: tanh saturation amount (lifts quiet, spiky clips)
PICKS = {
    "catch":        ("kenney_digital-audio/Audio/powerUp2.ogg", {}),
    "catch_rare":   ("kenney_digital-audio/Audio/powerUp7.ogg", {}),
    "catch_epic":   ("kenney_digital-audio/Audio/powerUp9.ogg", {}),
    "miss":         ("kenney_digital-audio/Audio/phaserDown3.ogg", {}),
    "bomb":         ("kenney_sci-fi-sounds/Audio/explosionCrunch_000.ogg", {}),
    "powerup":      ("kenney_digital-audio/Audio/powerUp11.ogg", {}),
    "shield_break": ("kenney_impact-sounds/Audio/impactGlass_heavy_001.ogg",
                     {"layer": ("kenney_sci-fi-sounds/Audio/forceField_002.ogg", 0.35), "drive": 2.5, "max": 0.6}),
    "heart":        ("kenney_interface-sounds/Audio/confirmation_001.ogg", {}),
    "combo_up":     ("kenney_digital-audio/Audio/phaserUp7.ogg", {}),
    "level_up":     ("kenney_music-jingles/Audio/8-Bit jingles/jingles_NES12.ogg", {}),
    "countdown":    ("kenney_interface-sounds/Audio/toggle_001.ogg", {}),
    "go":           ("kenney_interface-sounds/Audio/confirmation_002.ogg", {}),
    "ui_move":      ("kenney_interface-sounds/Audio/select_001.ogg", {}),
    "ui_select":    ("kenney_interface-sounds/Audio/select_005.ogg", {}),
    "ui_back":      ("kenney_interface-sounds/Audio/back_004.ogg", {}),
    "game_over":    ("kenney_music-jingles/Audio/8-Bit jingles/jingles_NES00.ogg", {}),
    # new_record: no fitting celebratory stinger in the packs -> tools/synth_sfx.py
}


#Extraction
def safe_target(out_dir: str, member: str) -> str | None:
    """Map an archive member name to a path inside out_dir, or None if unsafe."""
    name = member.replace("\\", "/")
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or any(p == ".." or ":" in p for p in parts):
        return None
    target = os.path.realpath(os.path.join(out_dir, *parts))
    root = os.path.realpath(out_dir)
    if os.path.commonpath([root, target]) != root:
        return None
    return target


def extract(archive: str, out_dir: str) -> int:
    """Extract media members of archive into out_dir. Returns file count."""
    os.makedirs(out_dir, exist_ok=True)
    count = total = 0
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            if info.is_dir() or os.path.splitext(info.filename)[1].lower() not in MEDIA_EXTS:
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                print(f"skip (too big): {info.filename}")
                continue
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                print("stop: total size limit reached")
                break
            target = safe_target(out_dir, info.filename)
            if target is None:
                print(f"skip (unsafe path): {info.filename}")
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            # Stream copy with a hard cap (do not trust the header size)
            written = 0
            with zf.open(info) as src, open(target, "wb") as dst:
                while chunk := src.read(65536):
                    written += len(chunk)
                    if written > MAX_MEMBER_BYTES:
                        break
                    dst.write(chunk)
            if written > MAX_MEMBER_BYTES:
                os.remove(target)
                print(f"skip (grew too big): {info.filename}")
                continue
            count += 1
    return count


#Curation
def load_mono(path: str):
    """Decode any format SDL_mixer understands into a float mono numpy array."""
    import numpy as np
    import pygame as pg
    if not pg.mixer.get_init():
        pg.mixer.init(SR, -16, 2)
    a = pg.sndarray.array(pg.mixer.Sound(path)).astype(np.float64) / 32768
    return a.mean(axis=1) if a.ndim == 2 else a


def trim(x):
    """Remove DC and leading (-40 dB, 2 ms pre-roll) / trailing (-50 dB) silence."""
    import numpy as np
    x = x - x.mean()
    peak = np.abs(x).max() or 1.0
    # Leading: first sample above -40 dB of peak (keep 2 ms pre-roll)
    loud = np.nonzero(np.abs(x) > peak * 0.01)[0]
    start = max(0, loud[0] - int(0.002 * SR))
    # Trailing: last sample above -50 dB of peak
    quiet = np.nonzero(np.abs(x) > peak * 0.003)[0]
    return x[start:quiet[-1] + 1] / peak


def process(x, max_dur: float | None = None, rate: float = 1.0, layer=None, drive: float = 0.0):
    """Trim silence, optional layer / drive / re-pitch / shorten, normalise to PEAK_DBFS."""
    import numpy as np
    x = trim(x)
    if drive:
        x = np.tanh(drive * x) / np.tanh(drive)
    if layer is not None:
        under, gain = layer
        under = trim(under)
        n = max(len(x), len(under))
        x = np.pad(x, (0, n - len(x))) + np.pad(under, (0, n - len(under))) * gain
    if rate != 1.0:
        idx = np.arange(0, len(x) - 1, rate)
        x = np.interp(idx, np.arange(len(x)), x)
    if max_dur and len(x) > max_dur * SR:
        x = x[:int(max_dur * SR)]
        f = int(0.06 * SR)
        x[-f:] *= np.linspace(1, 0, f)
    # Tiny fades so the cut points never click
    fi, fo = int(0.001 * SR), int(0.004 * SR)
    x[:fi] *= np.linspace(0, 1, fi)
    x[-fo:] *= np.linspace(1, 0, fo)
    return x * (10 ** (PEAK_DBFS / 20) / (np.abs(x).max() or 1.0))


def write_wav(path: str, x) -> None:
    import numpy as np
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def curate(src_root: str, sound_dir: str) -> int:
    os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
    os.makedirs(sound_dir, exist_ok=True)
    for name, (rel, opts) in PICKS.items():
        src = os.path.join(src_root, *rel.split("/"))
        layer = None
        if "layer" in opts:
            lrel, gain = opts["layer"]
            layer = (load_mono(os.path.join(src_root, *lrel.split("/"))), gain)
        x = process(load_mono(src), opts.get("max"), opts.get("rate", 1.0), layer, opts.get("drive", 0.0))
        dst = os.path.join(sound_dir, f"{name}.wav")
        write_wav(dst, x)
        extra = f" + {opts['layer'][0]}" if "layer" in opts else ""
        print(f"{name:13s} <- {rel}{extra}  ({len(x) / SR:.2f}s)")
    return len(PICKS)


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[1] == "extract":
        n = extract(argv[2], argv[3])
        print(f"extracted {n} media files from {os.path.basename(argv[2])}")
        return 0
    if len(argv) == 4 and argv[1] == "curate":
        curate(argv[2], argv[3])
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
