"""Credits scene, tilted paddle glow, Void Eye shot colour (small polish features).

Run from the repo root:   python -m tests.test_credits
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
from game.scenes import credits  # noqa: E402

DT = 1 / 60


def key(app, k, up=True):
    pg.event.post(pg.event.Event(pg.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
    if up:
        pg.event.post(pg.event.Event(pg.KEYUP, key=k, mod=0, unicode="", scancode=0))
    app.step(DT)


def with_app(fn):
    tmp = tempfile.mkdtemp()
    try:
        app = App(["--data-dir", tmp, "--start-scene", "menu"])
        try:
            fn(app)
        finally:
            config.set_logical_width(config.BASE_W)
            app.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def open_credits(app):
    menu = app.scenes.top.menu
    idx = [w.label_key for w in menu.widgets].index("menu.credits")
    assert idx == 2, "Credit sits right under How to play"
    menu.set_focus(idx, sound=False)
    key(app, pg.K_RETURN)
    app.step(DT)
    assert app.scenes.stack_names == ["menu", "credits"], app.scenes.stack_names
    return app.scenes.top


def test_strings_and_content():
    for code in config.LANGUAGES:
        with open(os.path.join(ROOT, "lang", f"{code}.json"), encoding="utf-8-sig") as f:
            data = json.load(f)
        for k in ("menu.credits", "credits.made_by", "credits.tools", "credits.thanks", "credits.thanks_text", "credits.hint"):
            assert k in data and data[k], (code, k)
    texts = [x[1] for x in credits.build_lines()]
    assert credits.AUTHOR == "Smith Nguyễn" and credits.AUTHOR in texts
    for name in ("Python", "pygame-ce", "Claude Code"):
        assert name in texts, name


def test_scroll_and_back():
    def run(app):
        sc = open_credits(app)
        assert sc.rows and sc.block_h > 300
        start = sc.offset
        for _ in range(60):
            app.step(DT)
        slow = sc.offset - start
        assert slow > 0
        key(app, pg.K_SPACE, up=False)                       # hold: fast
        before = sc.offset
        for _ in range(60):
            app.step(DT)
        assert sc.offset - before > 3 * slow, (slow, sc.offset - before)
        pg.event.post(pg.event.Event(pg.KEYUP, key=pg.K_SPACE, mod=0, unicode="", scancode=0))
        app.step(DT)
        assert app.scenes.stack_names == ["menu", "credits"], "Space only speeds up"
        key(app, pg.K_ESCAPE)
        app.step(DT)
        assert app.scenes.stack_names == ["menu"], app.scenes.stack_names
    with_app(run)


def test_ends_by_itself_and_draws_at_all_widths():
    def run(app):
        sc = open_credits(app)
        for w in (config.BASE_W, 960, 1960):
            config.set_logical_width(w)
            app.scenes.relayout(w) if hasattr(app.scenes, "relayout") else None
            for off in (-50.0, 200.0, sc.total_travel * 0.5, sc.total_travel):
                sc.offset = off
                sc.draw(app.display.surface)
        config.set_logical_width(config.BASE_W)
        sc.offset = sc.total_travel + credits.SCROLL_SPEED * credits.END_HOLD + 1
        app.step(DT)
        app.step(DT)
        assert app.scenes.stack_names == ["menu"], app.scenes.stack_names
    with_app(run)


def test_paddle_glow_follows_tilt():
    from game.entities.player import Player
    from game.entities import items
    pg.display.init()
    surf = pg.Surface((540, 840))

    def glow_bytes(tilt):
        p = Player(270)
        p.tilt = tilt
        surf.fill((0, 0, 0))
        p.draw(surf, 0.0)
        return pg.image.tobytes(surf.subsurface(pg.Rect(120, p.pos.y - 60, 300, 120)), "RGB")
    flat, left, right = glow_bytes(0.0), glow_bytes(-6.0), glow_bytes(6.0)
    assert flat != left and left != right and flat != right, "the halo changes with the tilt"
    for _ in range(3):                                      # cache stays small and drawing is repeatable
        assert glow_bytes(6.0) == right
    assert len(items._tilted_glows) <= 400


def test_void_eye_shots_are_purple():
    import random
    from game.systems.boss import BossController, KIND_DEFS
    assert [d["shot"] for d in KIND_DEFS] == ["orange", "magenta", "purple"]
    c = BossController(random.Random(1))
    c.start(3)
    c.state = "fight"
    c.boss.pos.y = float(config.BOSS_Y)
    c.boss.phase = 2
    names = c.attack_pool()
    cols = {s.color for n in names for _, s in c.plan_attack(n, 270)}
    assert cols == {"purple"}, cols
    c.boss.enraged = True
    assert {s.color for n in names for _, s in c.plan_attack(n, 270)} == {"red"}


TESTS = [test_strings_and_content, test_scroll_and_back, test_ends_by_itself_and_draws_at_all_widths,
         test_paddle_glow_follows_tilt, test_void_eye_shots_are_purple]


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
