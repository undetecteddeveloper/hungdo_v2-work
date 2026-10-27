"""F9 cheat picker (temporary feature): the panel opens over a paused round and starts the chosen boss.

Run from the repo root:   python -m tests.test_cheat_boss
"""
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg  # noqa: E402

from game import config  # noqa: E402
from game.app import App  # noqa: E402

DT = 1 / 60


def key(app, k):
    pg.event.post(pg.event.Event(pg.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
    pg.event.post(pg.event.Event(pg.KEYUP, key=k, mod=0, unicode="", scancode=0))
    app.step(DT)


def start_round(tmp):
    app = App(["--data-dir", tmp, "--start-scene", "menu"])
    key(app, pg.K_RETURN)                                   # "Play"
    for _ in range(int(4.5 / DT)):                          # countdown
        app.step(DT)
    play = app.scenes.top
    assert app.scenes.stack_names == ["play"] and play.state == "playing", app.scenes.stack_names
    return app, play


def test_pick_any_boss():
    tmp = tempfile.mkdtemp()
    try:
        app, play = start_round(tmp)
        try:
            key(app, pg.K_F9)
            app.step(DT)
            assert app.scenes.stack_names == ["play", "cheat_boss"], app.scenes.stack_names
            t0 = play.round_time
            for _ in range(30):
                app.step(DT)
            assert play.round_time == t0, "the round is paused under the picker"
            key(app, pg.K_F9)                               # closes without a choice
            app.step(DT)
            assert app.scenes.stack_names == ["play"] and not play.boss_mode and not play.practice
            key(app, pg.K_F9)
            app.step(DT)
            for _ in range(2):
                key(app, pg.K_s)                            # Boss 1 -> Boss 3
            key(app, pg.K_RETURN)
            app.step(DT)
            assert app.scenes.stack_names == ["play"], app.scenes.stack_names
            assert play.boss_mode and play.boss.boss.number == 3 and play.level == 3 * config.BOSS_EVERY
            assert play.practice and play.bosses_defeated == 2
            assert play.boss.boss.max_hp == config.boss_max_hp(3)
        finally:
            app.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_picker_not_during_boss_or_countdown():
    tmp = tempfile.mkdtemp()
    try:
        app, play = start_round(tmp)
        try:
            play._cheat_boss(1)
            assert play.boss_mode
            key(app, pg.K_F9)
            app.step(DT)
            assert app.scenes.stack_names == ["play"], "no picker in the middle of a boss fight"
        finally:
            app.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


TESTS = [test_pick_any_boss, test_picker_not_during_boss_or_countdown]


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
