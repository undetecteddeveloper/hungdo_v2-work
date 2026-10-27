"""Boss bullet sound tests (plain asserts, no pytest): one blip per bullet, spacing, volume, voice cap, PlayScene wiring.

Run from the repo root:   python -m tests.test_boss_sfx
"""
import os
import shutil
import sys
import tempfile
import wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

from game import config  # noqa: E402
from game.app import App  # noqa: E402
from game.systems import shot_sfx  # noqa: E402
from game.systems.boss import BossTick, Shot  # noqa: E402
from game.systems.shot_sfx import ShotSfx  # noqa: E402

DT = config.PHYSICS_DT


def drain(sfx: ShotSfx, seconds: float = 5.0) -> list:
    """(time, volume) of every blip until the queue is empty, stepping by DT."""
    out, t = [], 0.0
    for _ in range(int(seconds / DT)):
        t += DT
        out += [(t, v) for v in sfx.update(DT)]
        if not sfx.pending:
            break
    return out


class RecAudio:
    """Stands in for AudioManager: records every play() call."""

    def __init__(self):
        self.calls = []             # (name, volume, min_interval)
        self.enabled = False

    def play(self, name, volume=1.0, min_interval=None):
        self.calls.append((name, volume, min_interval))

    def __getattr__(self, name):    # play_music, stop_music, ... are no-ops
        return lambda *a, **k: None


#Tests
def test_one_blip_per_bullet():
    for n in (1, 2, 3, 6, 9, 12, 18, 30):
        sfx = ShotSfx()
        sfx.add(n)
        assert sfx.pending == n
        blips = drain(sfx)
        assert len(blips) == n, (n, len(blips))
        assert not sfx.pending
    sfx = ShotSfx()
    sfx.add(0)
    sfx.add(-3)
    assert sfx.pending == 0 and drain(sfx) == []


def test_lone_bullet_is_immediate_and_full_volume():
    sfx = ShotSfx()
    sfx.add(1)
    out = sfx.update(DT)
    assert out == [shot_sfx.VOLUME], out


def test_blips_are_spaced_and_voices_capped():
    for n in (2, 6, 12, 18, 40):
        sfx = ShotSfx()
        sfx.add(n)
        times = [t for t, _ in drain(sfx)]
        gaps = [b - a for a, b in zip(times, times[1:])]
        # blips stay apart (a bit of slack: times are quantised to the physics step)
        assert all(g >= shot_sfx.MIN_SPACING - DT for g in gaps), (n, min(gaps))
        # sounds alive at once never exceed the cap
        alive = max(sum(1 for u in times if t <= u < t + shot_sfx.SOUND_LEN) for t in times)
        assert alive <= shot_sfx.MAX_VOICES + 1, (n, alive)
        if n <= 12:                                             # a normal volley is over quickly
            assert times[-1] <= shot_sfx.TARGET_SPAN + 2 * shot_sfx.MAX_SPACING, (n, times[-1])
    # the blip is no longer than the length the spacing was designed for
    with wave.open(os.path.join(ROOT, "assets", "sound", "boss_shot.wav")) as w:
        assert w.getnframes() / w.getframerate() <= shot_sfx.SOUND_LEN + 1e-3


def test_crowded_volley_is_quieter_per_blip():
    mean = {}
    for n in (1, 3, 8, 12):
        sfx = ShotSfx()
        sfx.add(n)
        vols = [v for _, v in drain(sfx)]
        assert all(shot_sfx.MIN_VOLUME * shot_sfx.ALTERNATE - 1e-9 <= v <= shot_sfx.VOLUME + 1e-9 for v in vols), (n, vols)
        mean[n] = sum(vols) / n
    assert mean[1] > mean[3] > mean[8], mean
    assert mean[12] <= mean[8] + 1e-9, mean
    sfx = ShotSfx()                         # neighbouring blips differ a little, so they can be told apart
    sfx.add(4)
    vols = [v for _, v in drain(sfx)]
    assert vols[0] > vols[1] and vols[2] > vols[3], vols


def test_later_bullets_queue_behind_earlier_ones():
    sfx = ShotSfx()
    sfx.add(10)
    sfx.update(0.05)                                    # some already played, the rest are still pending
    left = sfx.pending
    assert 0 < left < 10
    sfx.add(5)
    assert sfx.pending == left + 5
    blips = drain(sfx)
    assert len(blips) == left + 5
    times = [t for t, _ in blips]
    assert all(b - a >= shot_sfx.MIN_SPACING - DT for a, b in zip(times, times[1:])), "no two blips on top of each other"
    sfx.add(7)
    sfx.clear()
    assert sfx.pending == 0 and drain(sfx) == []


def test_config_and_files():
    assert "boss_burst" not in config.SFX_NAMES and "boss_shot" in config.SFX_NAMES and "boss_sweep" in config.SFX_NAMES
    assert not os.path.exists(os.path.join(ROOT, "assets", "sound", "boss_burst.wav"))
    assert os.path.isfile(os.path.join(ROOT, "assets", "sound", "boss_shot.wav"))
    assert shot_sfx.SFX == "boss_shot"


def _play_scene(tmp):
    app = App(["--data-dir", tmp, "--start-scene", "menu"])
    scene = app.scenes.get("play")
    app.audio = RecAudio()
    scene.on_enter()
    scene.state = "playing"
    return app, scene


def test_playscene_plays_one_sound_per_shot():
    tmp = tempfile.mkdtemp()
    try:
        app, scene = _play_scene(tmp)
        try:
            ticks = {1: BossTick(shots=[Shot(270, 250, 0, 300) for _ in range(8)], events=["volley"]),
                     150: BossTick(shots=[Shot(100, 250, 0, 300)], events=["volley"]),      # long after the crowd has sounded
                     160: BossTick(shots=[], events=["sweep_fire"])}
            n = {"i": 0}

            def fake_update(dt, px, balls):
                n["i"] += 1
                return ticks.get(n["i"], BossTick())
            scene.boss.update = fake_update
            for _ in range(int(2.0 / DT)):
                scene._step_boss(DT, 1.0, None, True)
            names = [c[0] for c in app.audio.calls]
            assert names.count("boss_shot") == 9, names                 # 8 + 1 bullets: one blip each
            assert names.count("boss_sweep") == 1, names                # the sweep keeps its own sound
            assert "boss_burst" not in names and len(names) == 10, names
            # nothing is played for the "volley" event itself: only the bullets count
            assert all(c[2] == 0.0 for c in app.audio.calls if c[0] == "boss_shot"), "blips bypass the min interval"
            vols = [c[1] for c in app.audio.calls if c[0] == "boss_shot"]
            assert max(vols[:8]) < vols[8], "a crowded volley is softer per blip than a lone shot"
            assert scene.shot_sfx.pending == 0
            # a new round forgets blips that were still queued
            scene.shot_sfx.add(5)
            scene.reset_round()
            assert scene.shot_sfx.pending == 0
        finally:
            app.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_real_fight_blips_match_bullets():
    """A whole fight with the real controller: every bullet fired is a blip played or still queued, never a 'volley' sound."""
    tmp = tempfile.mkdtemp()
    try:
        app, scene = _play_scene(tmp)
        try:
            scene.lives = scene.max_lives = 999
            scene._start_boss()
            fired = {"n": 0, "volleys": 0}
            real_update = scene.boss.update

            def counting_update(dt, px, balls):
                tick = real_update(dt, px, balls)
                fired["n"] += len(tick.shots)
                fired["volleys"] += tick.events.count("volley")
                return tick
            scene.boss.update = counting_update
            for _ in range(int(60.0 / DT)):
                scene.update(DT)
                scene.hurt_timer = 1e6                      # stay alive: only the sound is under test
            assert fired["volleys"] >= 5 and fired["n"] > fired["volleys"], fired
            names = [c[0] for c in app.audio.calls]
            blips = names.count("boss_shot")
            assert blips + scene.shot_sfx.pending == fired["n"], (blips, scene.shot_sfx.pending, fired)
            assert set(names) <= {"boss_shot", "boss_sweep", "warning", "boss_intro", "boss_hit", "miss", "catch",
                                  "countdown", "go", "beam_charge", "beam_fire", "catch_rare", "boss_defeat"}, set(names)
        finally:
            app.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


TESTS = [test_one_blip_per_bullet, test_lone_bullet_is_immediate_and_full_volume,
         test_blips_are_spaced_and_voices_capped, test_crowded_volley_is_quieter_per_blip,
         test_later_bullets_queue_behind_earlier_ones, test_config_and_files,
         test_playscene_plays_one_sound_per_shot, test_real_fight_blips_match_bullets]


def main() -> int:
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {test.__name__}: {e!r}")
            import traceback
            traceback.print_exc()
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
