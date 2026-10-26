"""Procedural neon/synth sound generator (fallback for missing audio assets).

Every SFX name used by the game has a small recipe built from oscillators,
envelopes, noise and echo. A simple 16-bar synth loop can be rendered for
missing music. Output is 16-bit mono WAV, peak-normalised to about -1 dBFS.

Usage (from repo root):
    python hungdo_v2/tools/synth_sfx.py                 # only names with no file yet
    python hungdo_v2/tools/synth_sfx.py catch go        # these names (overwrite)
    python hungdo_v2/tools/synth_sfx.py --all           # every sfx (overwrite)
    python hungdo_v2/tools/synth_sfx.py --music menu    # music_menu.wav (also: game)
    python hungdo_v2/tools/synth_sfx.py --out some/dir ...
"""
import argparse
import os
import sys
import wave

import numpy as np

SR = 44100
PEAK_DBFS = -1.0
HERE = os.path.dirname(os.path.abspath(__file__))
SOUND_DIR = os.path.join(os.path.dirname(HERE), "assets", "sound")

SFX_NAMES = ["catch", "catch_rare", "catch_epic", "miss", "bomb", "powerup", "shield_break",
             "heart", "combo_up", "level_up", "countdown", "go", "ui_move", "ui_select",
             "ui_back", "game_over", "new_record",
             "boss_intro", "boss_hit", "beam_charge", "beam_fire", "boss_defeat", "warning"]

rng = np.random.default_rng(1234)   # fixed seed -> reproducible noise


#Building blocks
def midi(n: float) -> float:
    """MIDI note number -> frequency in Hz."""
    return 440.0 * 2 ** ((n - 69) / 12)


def n_samples(dur: float) -> int:
    return max(1, int(dur * SR))


def osc(freq, dur: float, wave_: str = "sine") -> np.ndarray:
    """Oscillator; freq may be a number or a per-sample array (for sweeps)."""
    n = n_samples(dur)
    f = np.broadcast_to(np.asarray(freq, dtype=np.float64), (n,))
    phase = np.cumsum(f) / SR          # in cycles
    frac = phase % 1.0
    if wave_ == "sine":
        return np.sin(2 * np.pi * phase)
    if wave_ == "square":
        return np.where(frac < 0.5, 1.0, -1.0)
    if wave_ == "saw":
        return 2.0 * frac - 1.0
    if wave_ == "tri":
        return 4.0 * np.abs(frac - 0.5) - 1.0
    raise ValueError(wave_)


def supersaw(freq, dur: float, detune: float = 0.012, voices: int = 3) -> np.ndarray:
    """A few detuned saws: the classic synthwave lead/pad."""
    out = np.zeros(n_samples(dur))
    for i in range(voices):
        k = 1 + detune * (i - (voices - 1) / 2)
        out += osc(np.asarray(freq) * k, dur, "saw")
    return out / voices


def sweep(f0: float, f1: float, dur: float, curve: str = "exp") -> np.ndarray:
    """Per-sample frequency glide from f0 to f1."""
    x = np.linspace(0, 1, n_samples(dur))
    if curve == "exp":
        return f0 * (f1 / f0) ** x
    return f0 + (f1 - f0) * x


def env(dur: float, attack: float = 0.004, decay: float = 0.15, sustain: float = 0.0,
        release: float = 0.02) -> np.ndarray:
    """Attack -> exponential decay towards sustain -> short linear release at the end."""
    n = n_samples(dur)
    t = np.arange(n) / SR
    e = sustain + (1 - sustain) * np.exp(-np.maximum(t - attack, 0) / max(decay, 1e-4))
    a = n_samples(attack)
    e[:a] *= np.linspace(0, 1, a)
    r = min(n, n_samples(release))
    e[n - r:] *= np.linspace(1, 0, r)
    return e


def noise(dur: float) -> np.ndarray:
    return rng.uniform(-1, 1, n_samples(dur))


def lowpass(x: np.ndarray, cutoff) -> np.ndarray:
    """One-pole low-pass; cutoff may be a number or per-sample array."""
    c = np.broadcast_to(np.asarray(cutoff, dtype=np.float64), x.shape)
    a = 1 - np.exp(-2 * np.pi * c / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):     # short buffers only; fine for offline tools
        acc += a[i] * (x[i] - acc)
        y[i] = acc
    return y


def highpass(x: np.ndarray, cutoff: float) -> np.ndarray:
    return x - lowpass(x, cutoff)


def echo(x: np.ndarray, delay: float = 0.09, feedback: float = 0.35, repeats: int = 4) -> np.ndarray:
    """Feed-forward echo taps with a decaying tail (the 'neon shimmer')."""
    d = n_samples(delay)
    out = np.zeros(len(x) + d * repeats)
    out[:len(x)] += x
    g = 1.0
    for k in range(1, repeats + 1):
        g *= feedback
        out[k * d:k * d + len(x)] += x * g
    return out


def mix(*parts) -> np.ndarray:
    """Sum (signal, offset_seconds) pairs into one buffer."""
    end = max(n_samples(off) + len(sig) for sig, off in parts)
    out = np.zeros(end)
    for sig, off in parts:
        s = n_samples(off) if off > 0 else 0
        out[s:s + len(sig)] += sig
    return out


def tone(note: float, dur: float, wave_: str = "square", decay: float = 0.12,
         sustain: float = 0.0, cutoff: float | None = None) -> np.ndarray:
    """One enveloped note, optionally low-passed to tame harsh waves."""
    sig = osc(midi(note), dur, wave_) if wave_ != "supersaw" else supersaw(midi(note), dur)
    if cutoff:
        sig = lowpass(sig, cutoff)
    return sig * env(dur, decay=decay, sustain=sustain)


def arpeggio(notes, step: float, note_dur: float, **kw) -> np.ndarray:
    return mix(*[(tone(n, note_dur, **kw), i * step) for i, n in enumerate(notes)])


#SFX recipes (each returns a float mono buffer)
def sfx_catch():
    f = sweep(midi(81), midi(88), 0.09)
    return osc(f, 0.09, "square") * env(0.09, decay=0.04) * 0.6 + osc(f * 2, 0.09) * env(0.09, decay=0.03) * 0.3


def sfx_catch_rare():
    return echo(arpeggio([84, 91], 0.06, 0.12, wave_="square", decay=0.06), 0.07, 0.3, 2)


def sfx_catch_epic():
    sig = arpeggio([84, 88, 91, 96], 0.045, 0.16, wave_="square", decay=0.07)
    sparkle = osc(midi(108), 0.25) * env(0.25, decay=0.08) * 0.25
    return echo(mix((sig, 0), (sparkle, 0.15)), 0.08, 0.35, 3)


def sfx_miss():
    f = sweep(520, 110, 0.32)
    sig = lowpass(osc(f, 0.32, "saw"), 1800) * env(0.32, decay=0.2, release=0.06)
    return sig + osc(f * 0.5, 0.32) * env(0.32, decay=0.15) * 0.5


def sfx_bomb():
    thump = osc(sweep(150, 38, 0.6), 0.6) * env(0.6, attack=0.002, decay=0.18)
    crack = lowpass(noise(0.9), sweep(6000, 300, 0.9)) * env(0.9, attack=0.001, decay=0.25)
    return mix((thump * 0.9, 0), (crack * 1.2, 0))


def sfx_powerup():
    f = sweep(330, 1320, 0.45) * (1 + 0.03 * np.sin(2 * np.pi * 18 * np.arange(n_samples(0.45)) / SR))
    sig = lowpass(osc(f, 0.45, "square"), 4000) * env(0.45, decay=0.5, sustain=0.3, release=0.08)
    return echo(sig, 0.06, 0.3, 2)


def sfx_shield_break():
    ring = sum(osc(sweep(f, f * 0.7, 0.45), 0.45) for f in (1230, 1870, 2650, 3410)) / 4
    crack = highpass(noise(0.3), 2500) * env(0.3, attack=0.001, decay=0.05)
    return mix((ring * env(0.45, attack=0.001, decay=0.12), 0), (crack * 0.9, 0))


def sfx_heart():
    return echo(arpeggio([76, 83], 0.09, 0.22, wave_="tri", decay=0.12), 0.1, 0.3, 2)


def sfx_combo_up():
    return arpeggio([79, 83, 86, 91], 0.035, 0.1, wave_="square", decay=0.05, cutoff=5000)


def sfx_level_up():
    sig = arpeggio([72, 76, 79, 84, 88, 91], 0.07, 0.25, wave_="supersaw", decay=0.15, cutoff=6000)
    chord = sum(tone(n, 0.7, "supersaw", decay=0.35, cutoff=4000) for n in (84, 88, 91)) / 3
    return echo(mix((sig, 0), (chord, 0.42)), 0.12, 0.3, 3)


def sfx_countdown():
    return osc(midi(81), 0.12, "square") * env(0.12, decay=0.06, release=0.01) * 0.6 + \
        osc(midi(81), 0.12) * env(0.12, decay=0.08) * 0.4


def sfx_go():
    chord = sum(tone(n, 0.45, "supersaw", decay=0.2, sustain=0.2, cutoff=6000) for n in (81, 85, 88, 93)) / 4
    return echo(chord, 0.09, 0.3, 2)


def sfx_ui_move():
    return osc(midi(91), 0.035, "tri") * env(0.035, attack=0.001, decay=0.012)


def sfx_ui_select():
    return arpeggio([84, 91], 0.045, 0.07, wave_="square", decay=0.03, cutoff=5000)


def sfx_ui_back():
    return arpeggio([86, 79], 0.045, 0.07, wave_="square", decay=0.03, cutoff=4000)


def sfx_game_over():
    notes = [69, 68, 67, 66]
    parts = [(tone(n, 0.42 if i < 3 else 1.1, "supersaw", decay=0.3 if i < 3 else 0.6,
                   sustain=0.2, cutoff=2500), i * 0.38) for i, n in enumerate(notes)]
    bass = tone(42, 1.3, "saw", decay=0.7, cutoff=600) * 0.6
    return echo(mix(*parts, (bass, 1.14)), 0.16, 0.25, 2)


def sfx_new_record():
    run = arpeggio([72, 76, 79, 84, 79, 84, 88, 91], 0.075, 0.18, wave_="square", decay=0.08, cutoff=6000)
    chord = sum(tone(n, 1.3, "supersaw", decay=0.6, sustain=0.15, cutoff=5000) for n in (84, 88, 91, 96)) / 4
    sparkle = arpeggio([108, 103, 108, 112], 0.09, 0.12, wave_="sine", decay=0.05) * 0.35
    return echo(mix((run, 0), (chord, 0.6), (sparkle, 0.7)), 0.13, 0.3, 3)


#Boss fight SFX (docs/BOSS_DESIGN.md section 6)
def _ramp(n: int, start: float, end: float, power: float = 1.0) -> np.ndarray:
    """0 before `start` s, rising 0..1 (to `power`) until `end` s, then 1."""
    t = np.arange(n) / SR
    return np.clip((t - start) / max(end - start, 1e-6), 0, 1) ** power


def _boom(dur: float, f0: float = 110, f1: float = 28, grit: float = 0.8) -> np.ndarray:
    """Explosion: pitch-dropping sine thump + a low-passed noise blast that closes down."""
    thump = osc(sweep(f0, f1, dur), dur) * env(dur, attack=0.002, decay=dur * 0.28)
    blast = lowpass(noise(dur), sweep(7000, 160, dur)) * env(dur, attack=0.001, decay=dur * 0.3)
    return thump + blast * grit


def sfx_boss_intro():
    """Low drone climbing in pitch + a rising noise swell, two tritone horn blasts, landing boom (~2.3 s)."""
    dur, hit = 2.3, 1.8
    n = n_samples(dur)
    t = np.arange(n) / SR
    f = sweep(55, 130, hit)
    f = np.concatenate([f, np.full(n - len(f), f[-1])])
    saws = lowpass(osc(f, dur, "saw") + osc(f * 1.007, dur, "saw"), np.linspace(160, 1100, n))
    drone = saws * 0.45 + osc(f * 0.5, dur) * 0.5 + osc(f * 2, dur, "tri") * 0.25
    drone *= (0.15 + 0.85 * _ramp(n, 0, hit, 1.5)) * np.where(t < hit, 1.0, np.exp(-(t - hit) / 0.12))
    swell = lowpass(noise(dur), np.linspace(300, 5200, n)) * _ramp(n, 0.2, hit, 2.2) * 0.35 * (t < hit)

    def horn(root, dur_, bend):
        fr = sweep(midi(root), midi(root) * bend, dur_, "lin")
        sig = sum(osc(fr * r, dur_, "saw") for r in (1.0, 2 ** (6 / 12), 2.0)) / 3        # root + tritone + octave
        vib = 1 + 0.012 * np.sin(2 * np.pi * 5.5 * np.arange(len(sig)) / SR)
        sig = lowpass(sig * vib, 1400)
        return sig * env(dur_, attack=0.04, decay=1.0, sustain=1.0, release=0.12)

    horns = mix((horn(46, 0.6, 1.0), 0.5), (horn(46, 0.55, 1.06), 1.15))
    boom = _boom(0.55, 95, 30) * 1.1
    sig = mix((drone[:n] + swell[:n], 0), (echo(horns, 0.13, 0.3, 2) * 0.55, 0), (boom, hit))
    return sig[:n_samples(2.4)]


def sfx_boss_hit():
    """Short metallic clang: inharmonic partials + a click and a small thump (~0.16 s)."""
    dur = 0.16
    base = 740.0
    ring = sum(osc(base * r, dur) * env(dur, attack=0.0005, decay=0.05 / (1 + 0.5 * i)) / (1 + 0.3 * i)
               for i, r in enumerate((1.0, 1.59, 2.14, 2.30, 2.65, 3.2)))
    click = highpass(noise(0.025), 2500) * env(0.025, attack=0.0003, decay=0.007)
    thump = osc(sweep(190, 70, 0.07), 0.07) * env(0.07, attack=0.0005, decay=0.025)
    return mix((ring, 0), (click * 0.9, 0), (thump * 0.8, 0))


def sfx_beam_charge():
    """Rising whine that tremolos faster and peaks into a bright two-note chime = 'energy ready' (~0.6 s)."""
    dur = 0.32
    n = n_samples(dur)
    t = np.arange(n) / SR
    x = np.linspace(0, 1, n)
    f = sweep(280, 2300, dur)
    whine = osc(f, dur, "tri") * 0.7 + osc(f * 2.01, dur) * 0.3
    trem = 1 + 0.3 * np.sin(2 * np.pi * np.cumsum(14 + 40 * x) / SR)
    whine = whine * trem * (0.2 + 0.8 * x ** 1.3) * env(dur, attack=0.01, decay=1.0, sustain=1.0, release=0.02)
    chime = mix((arpeggio([91, 98], 0.07, 0.2, wave_="tri", decay=0.1), 0),
                (arpeggio([103, 110], 0.07, 0.15, wave_="sine", decay=0.07) * 0.35, 0))
    return echo(mix((whine * 0.8, 0), (chime, dur - 0.04)), 0.05, 0.3, 2)


def sfx_beam_fire():
    """Laser zap: bright saw sweeping down 3.4 kHz -> 160 Hz with FM wobble, crackle and thump (~0.45 s)."""
    dur = 0.45
    n = n_samples(dur)
    t = np.arange(n) / SR
    f = sweep(3400, 160, dur) * (1 + 0.035 * np.sin(2 * np.pi * 38 * t))
    body = lowpass(osc(f, dur, "saw"), 7000) * 0.55 + osc(f * 0.5, dur, "square") * 0.3 + osc(f, dur) * 0.4
    body = body * env(dur, attack=0.002, decay=0.3, release=0.08)
    zap = highpass(noise(0.14), 3000) * env(0.14, attack=0.001, decay=0.045)
    hiss = lowpass(noise(dur), sweep(5000, 400, dur)) * env(dur, attack=0.005, decay=0.18) * 0.3
    thump = osc(sweep(130, 45, 0.25), 0.25) * env(0.25, attack=0.001, decay=0.08)
    return mix((body, 0), (zap * 0.4, 0), (hiss * 0.6, 0), (thump * 0.8, 0))


def sfx_boss_defeat():
    """Big blast + staggered smaller blasts, long rumble, then a falling arpeggio over the wreckage (~2.4 s)."""
    dur = 2.5
    n = n_samples(dur)
    t = np.arange(n) / SR
    blasts = mix((_boom(1.5, 120, 26), 0), (_boom(0.7, 150, 40) * 0.6, 0.28), (_boom(0.6, 170, 50) * 0.5, 0.55),
                 (_boom(0.5, 190, 60) * 0.4, 0.8))
    blasts = np.tanh(1.5 * blasts)                                  # saturate: fat, not just loud
    rumble = lowpass(noise(2.2), 120) * (0.6 + 0.4 * np.sin(2 * np.pi * 9 * np.arange(n_samples(2.2)) / SR))
    rumble *= env(2.2, attack=0.03, decay=0.9, release=0.4) * 1.6
    notes = [96, 91, 88, 84, 79, 76, 72, 67]
    arp = arpeggio(notes, 0.12, 0.4, wave_="supersaw", decay=0.2, cutoff=4500)
    arp = echo(arp, 0.15, 0.4, 3) * 0.55
    sig = mix((blasts, 0), (rumble, 0), (arp, 0.9))[:n]
    sig = np.pad(sig, (0, n - len(sig)))
    return sig * np.clip((dur - t) / 0.2, 0, 1)                      # fade the echo tail out


def sfx_warning():
    """Two gated alarm beeps with a tritone edge (~0.7 s)."""
    def beep():
        d = 0.2
        sig = lowpass(osc(880, d, "square"), 2400) * 0.7 + osc(1245, d, "tri") * 0.25 + osc(440, d) * 0.3
        return sig * env(d, attack=0.004, decay=1.0, sustain=1.0, release=0.025)
    return echo(mix((beep(), 0), (beep(), 0.29)), 0.11, 0.3, 2)


RECIPES = {name: globals()[f"sfx_{name}"] for name in SFX_NAMES}


#Music loop
def kick(dur=0.3):
    return osc(sweep(140, 45, dur), dur) * env(dur, attack=0.001, decay=0.09)


def hat(dur=0.05):
    return highpass(noise(dur), 7000) * env(dur, attack=0.001, decay=0.015)


def snare(dur=0.18):
    return (highpass(noise(dur), 1500) * 0.8 + osc(190, dur, "tri") * 0.4) * env(dur, attack=0.001, decay=0.05)


def synth_music(kind: str) -> np.ndarray:
    """Render a seamless 16-bar loop. 'menu' = calm pad + arp, 'game' = driving synthwave."""
    bpm = 96 if kind == "menu" else 124
    beat = 60 / bpm
    bars = 16
    total = n_samples(bars * 4 * beat)
    out = np.zeros(total + n_samples(2.0))           # spill-over wraps to the start
    chords = [(57, 60, 64), (53, 57, 60), (48, 52, 55), (55, 59, 62)]   # Am F C G

    def put(sig, t, gain=1.0):
        s = n_samples(t)
        out[s:s + len(sig)] += sig * gain

    for bar in range(bars):
        root = chords[bar % 4]
        t0 = bar * 4 * beat
        # Pad: detuned saws, low-passed
        pad = sum(supersaw(midi(n), 4 * beat) for n in root) / 3
        pad = lowpass(pad, 900 if kind == "menu" else 1400) * env(4 * beat, attack=0.3, decay=9, sustain=1, release=0.3)
        put(pad, t0, 0.35)
        # Arp: 8ths (menu) or 16ths (game) over the chord, one octave up
        step = beat / 2 if kind == "menu" else beat / 4
        arp_notes = [root[0] + 12, root[1] + 12, root[2] + 12, root[1] + 12]
        for i in range(int(4 * beat / step)):
            n = arp_notes[i % 4] + (12 if kind == "game" and i % 8 == 7 else 0)
            put(tone(n, step * 1.6, "square" if kind == "game" else "tri", decay=step * 0.6, cutoff=3500), t0 + i * step, 0.16)
        # Bass
        if kind == "game":
            for i in range(8):
                put(tone(root[0] - 12, beat / 2, "saw", decay=0.12, cutoff=700), t0 + i * beat / 2, 0.45)
        else:
            put(tone(root[0] - 12, 4 * beat, "tri", decay=1.5, sustain=0.3), t0, 0.35)
        # Drums
        for b in range(4):
            tb = t0 + b * beat
            if kind == "game":
                put(kick(), tb, 0.9)
                if b in (1, 3):
                    put(snare(), tb, 0.5)
                put(hat(), tb + beat / 2, 0.25)
            elif bar >= 4:
                put(hat(), tb + beat / 2, 0.12)
                if b == 0:
                    put(kick(), tb, 0.45)

    # Wrap the tail into the head so the loop is seamless
    tail = out[total:]
    out = out[:total]
    out[:len(tail)] += tail
    return out


#Output
def normalise(x: np.ndarray, peak_db: float = PEAK_DBFS) -> np.ndarray:
    x = x - np.mean(x)                               # remove DC
    peak = np.max(np.abs(x)) or 1.0
    return x * (10 ** (peak_db / 20) / peak)


def write_wav(path: str, x: np.ndarray, fade_ms: float = 4.0) -> None:
    """Write a float buffer as 16-bit mono WAV (peak -1 dBFS, tiny fade-out)."""
    x = normalise(np.asarray(x, dtype=np.float64))
    f = min(len(x), n_samples(fade_ms / 1000))
    if f > 1:
        x[-f:] *= np.linspace(1, 0, f)
    pcm = np.clip(np.round(x * 32767), -32768, 32767).astype("<i2")
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


def exists_any(out_dir: str, stem: str) -> bool:
    return any(os.path.isfile(os.path.join(out_dir, stem + ext)) for ext in (".ogg", ".wav", ".mp3"))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help="sfx names to (re)generate")
    ap.add_argument("--all", action="store_true", help="generate every sfx")
    ap.add_argument("--music", choices=["menu", "game"], action="append", default=[],
                    help="render music_<kind>.wav")
    ap.add_argument("--out", default=SOUND_DIR, help="output directory")
    args = ap.parse_args(argv)

    unknown = [n for n in args.names if n not in RECIPES]
    if unknown:
        ap.error(f"unknown sfx: {', '.join(unknown)}")
    if args.all:
        names = SFX_NAMES
    elif args.names or args.music:
        names = args.names
    else:
        names = [n for n in SFX_NAMES if not exists_any(args.out, n)]

    for name in names:
        path = os.path.join(args.out, f"{name}.wav")
        write_wav(path, RECIPES[name]())
        print(f"wrote {path}")
    for kind in args.music:
        path = os.path.join(args.out, f"music_{kind}.wav")
        write_wav(path, synth_music(kind), fade_ms=0)
        print(f"wrote {path}")
    if not names and not args.music:
        print("nothing missing")
    return 0


if __name__ == "__main__":
    sys.exit(main())
