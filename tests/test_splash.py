"""Splash screen tests (plain asserts, no pytest): timeline, fades, skipping, start-up routing, i18n, logo files.

Run from the repo root:   python -m tests.test_splash [--shots]
--shots also saves screenshots of both cards at full opacity and mid-fade into tools/_out/ (git-ignored).
"""
import json
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
from game.scenes import splash  # noqa: E402

DT = 1 / 60
OUT = os.path.join(ROOT, "tools", "_out")


def approx(a, b, eps=1e-6):
    return abs(a - b) <= eps


def new_app(tmp, *args):
    return App(["--data-dir", tmp, *args])


def run_for(app, seconds):
    for _ in range(int(seconds / DT)):
        app.step(DT)


#Tests
def test_timeline():
    s = splash.splash_state
    assert s(0.0) == (0, 0.0), "starts black"
    card, a = s(splash.FADE_IN / 2)
    assert card == 0 and 0.0 < a < 1.0, "first card fades in"
    assert s(splash.FADE_IN + splash.HOLD / 2) == (0, 1.0), "first card holds"
    card, a = s(splash.CARD_TIME - splash.FADE_OUT / 2)
    assert card == 0 and 0.0 < a < 1.0, "first card fades out"
    assert s(splash.CARD_TIME + splash.GAP / 2) == (None, 0.0), "black between the cards"
    second = splash.CARD_TIME + splash.GAP
    card, a = s(second + splash.FADE_IN / 2)
    assert card == 1 and 0.0 < a < 1.0, "second card fades in"
    assert s(second + splash.FADE_IN + splash.HOLD / 2) == (1, 1.0), "second card holds"
    card, a = s(second + splash.CARD_TIME - splash.FADE_OUT / 2)
    assert card == 1 and 0.0 < a < 1.0, "second card fades out"
    assert s(splash.TOTAL_TIME) == (None, 0.0) and s(splash.TOTAL_TIME + 5) == (None, 0.0), "finished"
    assert approx(splash.TOTAL_TIME, 2 * splash.CARD_TIME + splash.GAP)
    prev = -1.0                                                     # opacity never jumps, never leaves 0..1
    for i in range(int(splash.TOTAL_TIME / 0.005)):
        _, a = s(i * 0.005)
        assert 0.0 <= a <= 1.0, (i, a)
        assert prev < 0 or abs(a - prev) < 0.06, (i, a, prev)
        prev = a


def test_assets_and_strings():
    for name in ("python", "claude"):
        assert os.path.isfile(os.path.join(ROOT, splash.LOGO_DIR, name + ".png")), f"logo {name}.png missing"
    assert os.path.isfile(os.path.join(ROOT, "assets", "icon.png"))
    for code in config.LANGUAGES:
        with open(os.path.join(ROOT, "lang", f"{code}.json"), encoding="utf-8-sig") as f:
            data = json.load(f)
        for _, key, _, _ in splash.TOOLS:
            assert key in data, f"{code}: missing {key}"
    # the logos really are coloured (Claude's once came out grey)
    surf = pg.image.load(os.path.join(ROOT, splash.LOGO_DIR, "claude.png"))
    r, g, b, _ = surf.get_at((surf.get_width() // 2, surf.get_height() // 2))
    assert r > g + 40 and r > b + 60, (r, g, b)


def test_startup_routing():
    tmp = tempfile.mkdtemp()
    try:
        for args, want in (((), "splash"), (("--autoplay",), "menu"), (("--start-boss", "1"), "menu"),
                           (("--start-scene", "menu"), "menu")):
            app = new_app(tmp, *args)
            try:
                assert app.scenes.stack_names == [want], (args, app.scenes.stack_names)
                assert "splash" not in app.placeholders
            finally:
                app.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_runs_to_menu_and_skips():
    tmp = tempfile.mkdtemp()
    try:
        app = new_app(tmp)
        try:
            run_for(app, splash.TOTAL_TIME / 2)
            assert app.scenes.stack_names == ["splash"], "still showing"
            run_for(app, splash.TOTAL_TIME / 2 + 0.5)
            assert app.scenes.stack_names == ["menu"], app.scenes.stack_names
        finally:
            app.close()
        for ev in (pg.event.Event(pg.KEYDOWN, key=pg.K_SPACE, mod=0, unicode=" ", scancode=0),
                   pg.event.Event(pg.MOUSEBUTTONDOWN, pos=(10, 10), button=1)):
            app = new_app(tmp)
            try:
                run_for(app, 0.8)
                pg.event.post(ev)
                run_for(app, 0.1)
                assert app.scenes.stack_names == ["menu"], f"skipped by {pg.event.event_name(ev.type)}"
            finally:
                app.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_draw_fades():
    tmp = tempfile.mkdtemp()
    shots = "--shots" in sys.argv
    try:
        app = new_app(tmp)
        try:
            sc = app.scenes.top
            assert isinstance(sc, splash.SplashScene)
            surf = app.display.surface

            def brightness():
                return sum(pg.transform.average_color(surf)[:3])

            def at(tm):
                sc.timer = tm
                sc.draw(surf)
                return brightness()

            second = splash.CARD_TIME + splash.GAP
            for card, start in ((0, 0.0), (1, second)):
                dark = at(start)
                mid_in = at(start + splash.FADE_IN / 2)
                full = at(start + splash.FADE_IN + 0.2)
                mid_out = at(start + splash.CARD_TIME - splash.FADE_OUT / 2)
                assert dark == 0, f"card {card} starts black"
                assert dark < mid_in < full, f"card {card} fades in ({dark} {mid_in} {full})"
                assert dark < mid_out < full, f"card {card} fades out ({mid_out} {full})"
                if shots:
                    os.makedirs(OUT, exist_ok=True)
                    at(start + splash.FADE_IN + 0.2)
                    pg.image.save(surf, os.path.join(OUT, f"splash_card{card}.png"))
                    at(start + splash.FADE_IN / 2)
                    pg.image.save(surf, os.path.join(OUT, f"splash_card{card}_fade.png"))
            assert at(splash.CARD_TIME + splash.GAP / 2) == 0, "black in the gap"
            for w in (config.BASE_W, 960, config.max_logical_width()):         # any canvas width
                config.set_logical_width(w)
                app.display.apply(app.settings)
                app.scenes.relayout(w)
                sc.timer = splash.FADE_IN + 0.3
                sc.draw(app.display.surface)
        finally:
            config.set_logical_width(config.BASE_W)
            app.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


TESTS = [test_timeline, test_assets_and_strings, test_startup_routing, test_runs_to_menu_and_skips, test_draw_fades]


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
