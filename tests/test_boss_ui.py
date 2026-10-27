"""Boss UI tests (plain asserts, no pytest): i18n keys, HUD with boss, banners, reward scene, how-to layout.

Run from the repo root:   python -m tests.test_boss_ui [--shots]
--shots also saves screenshots of the boss HUD / reward scene / banners into tools/_out/ (git-ignored).
"""
import json
import logging
import os
import re
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame as pg  # noqa: E402

from game import config, i18n  # noqa: E402
from game.assets import Assets  # noqa: E402
from game.ui import boss_ui, hud as hud_mod  # noqa: E402

PAL = config.PALETTE
WIDTHS = (540, 960, 1960)
BASE_W = config.LOGICAL_W
H = config.LOGICAL_H
DT = 1 / 60
BG = PAL["bg_top"]

REQUIRED_KEYS = [
    "boss.warning", "boss.number", "boss.kind.0.name", "boss.kind.1.name", "boss.kind.2.name", "boss.defeated",
    "boss.bonus", "boss.phase", "boss.enraged", "boss.beam_ready", "boss.energy", "boss.ball_lost",
    "boss.reward.title", "boss.reward.sub", "boss.reward.lives", "boss.reward.owned", "boss.reward.hint",
    "upgrade.wide.name", "upgrade.wide.desc", "upgrade.magnet.name", "upgrade.magnet.desc",
    "upgrade.life.name", "upgrade.life.desc", "upgrade.power.name", "upgrade.power.desc",
    "upgrade.speed.name", "upgrade.speed.desc", "howto.fire", "howto.boss_tip",
]


#Fakes and helpers
class FakeScenes:
    def __init__(self, names=("play", "boss_reward")):
        self.stack_names = list(names)
        self.pops = 0

    def pop(self):
        self.pops += 1


class FakeAudio:
    def __init__(self):
        self.played = []

    def play(self, name, volume=1.0):
        self.played.append(name)

    def pause_music(self):
        pass

    def resume_music(self):
        pass


class FakeApp:
    def __init__(self, assets):
        self.assets = assets
        self.audio = FakeAudio()
        self.scenes = FakeScenes()
        self.autoplay = False
        self.time = 0.0

    def mouse_pos(self):
        return None


_assets = None


def assets() -> Assets:
    global _assets
    if _assets is None:
        pg.display.init()
        pg.font.init()
        pg.display.set_mode((config.BASE_W, config.LOGICAL_H))
        _assets = Assets()
    return _assets


def set_width(w: int) -> None:
    config.set_logical_width(w)


def blank(w: int = None) -> pg.Surface:
    surf = pg.Surface((w or config.LOGICAL_W, H))
    surf.fill(BG)
    return surf


def same_pixels(a: pg.Surface, b: pg.Surface) -> bool:
    return a.get_size() == b.get_size() and pg.image.tobytes(a, "RGB") == pg.image.tobytes(b, "RGB")


def is_blank(surf: pg.Surface, rect: pg.Rect, color=BG) -> bool:
    for y in range(rect.top, rect.bottom, 2):
        for x in range(rect.left, rect.right, 2):
            if surf.get_at((x, y))[:3] != tuple(color):
                return False
    return True


def lum(surf: pg.Surface, x: int, y: int) -> int:
    r, g, b = surf.get_at((x, y))[:3]
    return r + g + b


def boss_state(**kw) -> dict:
    b = {"name_key": "boss.kind.0.name", "number": 1, "kind": 0, "state": "fight", "hp_frac": 1.0, "phase": 1,
         "time_left": 65.0, "enraged": False, "colors": ("orange", "yellow"), "energy": 0, "energy_need": 3,
         "energy_cap": 6, "balls": 0, "player_x": 200.0, "boss_x": 270.0, "boss_half_w": 80.0}
    b.update(kw)
    return b


def hud_state(boss=False, **kw) -> dict:
    s = {"score": 12345, "best": 20000, "lives": 3, "max_lives": 5, "level": 10, "level_progress": 0.4,
         "combo": 12, "multiplier": 3, "powerups": [("magnet", 5.0, 8), ("wide", 1.0, 10)], "shield": 1}
    if boss is not False:
        s["boss"] = boss
    s.update(kw)
    return s


def run_hud(hud, app, surf, state, frames: int = 1) -> None:
    for _ in range(frames):
        app.time += DT
        surf.fill(BG)
        hud.draw(surf, state)


#i18n
def test_lang_keys():
    root = os.path.join(ROOT, "lang")
    data = {}
    for code in ("vi", "en"):
        with open(os.path.join(root, f"{code}.json"), "rb") as f:
            raw = f.read()
        assert not raw.startswith(b"\xef\xbb\xbf"), "no BOM"
        data[code] = json.loads(raw.decode("utf-8"))
    vi, en = data["vi"], data["en"]
    assert list(vi) == list(en), "same keys in the same order"
    for key in REQUIRED_KEYS:
        assert key in vi and key in en, f"missing {key}"
        assert vi[key].strip() and en[key].strip(), f"empty {key}"
    for key in vi:
        assert set(re.findall(r"\{(\w+)\}", vi[key])) == set(re.findall(r"\{(\w+)\}", en[key])), f"placeholders {key}"
    # Vietnamese keeps its diacritics
    assert vi["boss.warning"] == "CẢNH BÁO!" and vi["boss.kind.2.name"] == "MẮT HƯ KHÔNG"
    assert vi["boss.phase"] == "GIAI ĐOẠN {n}" and vi["boss.enraged"] == "NỔI GIẬN!"
    assert all(any(ord(c) > 127 for c in vi[k]) for k in ("boss.reward.title", "boss.reward.sub", "boss.reward.lives",
                                                          "upgrade.wide.name", "upgrade.life.desc", "howto.fire"))
    for code in ("vi", "en"):
        i18n.set_language(code)
        assert i18n.t("boss.number", n=3) == "BOSS 3"
        assert "1000" in i18n.t("boss.bonus", points=1000)
        assert i18n.t("boss.reward.owned", n=2).endswith("2")
        for key in REQUIRED_KEYS:
            assert i18n.has(key)
    i18n.set_language("vi")


#HUD
class _HudApp(FakeApp):
    pass


def test_hud_backward_compatible():
    """State without 'boss' (or boss=None) draws the same pixels, whichever way it is passed."""
    a = assets()
    for w in WIDTHS:
        set_width(w)
        results = []
        for state in (hud_state(), hud_state(boss=None), hud_state(boss={})):
            app = _HudApp(a)
            hud = hud_mod.Hud(app)
            surf = blank()
            run_hud(hud, app, surf, state, 5)
            results.append(surf)
        assert same_pixels(results[0], results[1]), f"boss=None differs at {w}"
        assert same_pixels(results[0], results[2]), f"boss={{}} differs at {w}"
        # ...and it really is the level HUD: the level label region is not blank
        assert not is_blank(results[0], pg.Rect(18, 62, 120, 24))
    set_width(BASE_W)


def test_hud_boss_draws_every_state():
    a = assets()
    for w in WIDTHS:
        set_width(w)
        app = _HudApp(a)
        hud = hud_mod.Hud(app)
        surf = blank()
        for state in ("intro", "fight", "enrage", "victory"):
            for kind, cols in enumerate((("orange", "yellow"), ("magenta", "cyan"), ("purple", "green"))):
                for energy in (0, 2, 3, 5, 6):
                    for px in (0.0, w * 0.25, w / 2, float(w)):
                        boss = boss_state(state=state, kind=kind, name_key=f"boss.kind.{kind}.name", colors=cols,
                                          energy=energy, player_x=px, boss_x=w / 2, enraged=state == "enrage",
                                          hp_frac=0.0 if state == "victory" else 0.7, phase=1 + kind,
                                          time_left=0.0 if state == "enrage" else 12.5)
                        run_hud(hud, app, surf, hud_state(boss=boss), 2)
        # Boss goes away: the level HUD returns and a fresh boss refills the bar from empty
        run_hud(hud, app, surf, hud_state(boss=None), 2)
        assert not is_blank(surf, pg.Rect(18, 62, 120, 24))
        run_hud(hud, app, surf, hud_state(boss=boss_state(hp_frac=1.0)), 1)
        assert hud.boss_hp < 0.5, "bar refills after a new boss appears"
        # RGB colours and missing optional keys are tolerated
        run_hud(hud, app, surf, hud_state(boss={"colors": ((255, 0, 0), (0, 255, 0)), "state": "fight"}), 2)
        # Language switch is live
        i18n.set_language("en")
        run_hud(hud, app, surf, hud_state(boss=boss_state(energy=4)), 2)
        i18n.set_language("vi")
    set_width(BASE_W)


def test_hud_boss_layout():
    """Header at the top, nothing over the boss body, energy meter bottom-left, paddle row clear."""
    a = assets()
    for w in WIDTHS:
        set_width(w)
        app = _HudApp(a)
        hud = hud_mod.Hud(app)
        surf = blank()
        state = hud_state(boss=boss_state(energy=2, boss_x=w / 2, player_x=w / 2), powerups=[], shield=0)
        run_hud(hud, app, surf, state, 120)
        # hp bar visible (full) and the boss body zone (y 160..310) untouched by the HUD
        bar_y = hud_mod.BOSS_BAR_Y + hud_mod.BOSS_BAR_H // 2
        assert lum(surf, 18 + 40, bar_y) > 250, "hp bar filled"
        assert is_blank(surf, pg.Rect(0, 160, w, 150)), "HUD leaves the boss area alone"
        assert is_blank(surf, pg.Rect(0, 690, w, 70)), "HUD leaves the paddle row alone (no beam shot ready)"
        # energy meter: 2 lit cells and the label are in the bottom-left corner
        corner = pg.Rect(0, H - 60, 200, 60)
        assert not is_blank(surf, corner), "energy meter drawn"
        assert is_blank(surf, pg.Rect(300, H - 60, max(10, w - 300), 60)), "nothing else down there"
        # more energy -> more lit pixels
        counts = []
        for energy in (0, 1, 3, 6):
            run_hud(hud, app, surf, hud_state(boss=boss_state(energy=energy, state="intro"), powerups=[], shield=0), 40)
            counts.append(sum(lum(surf, x, y) > 200 for y in range(H - 50, H - 10) for x in range(0, 200)))
        assert counts[0] < counts[1] < counts[2] < counts[3], f"energy cells light up: {counts}"
    set_width(BASE_W)


def test_hud_boss_bar():
    a = assets()
    set_width(540)
    app = _HudApp(a)
    hud = hud_mod.Hud(app)
    surf = blank()
    bar_y = hud_mod.BOSS_BAR_Y + hud_mod.BOSS_BAR_H // 2
    xs = {f: 18 + int((540 - 36) * f) for f in (0.2, 0.5, 0.8)}
    run_hud(hud, app, surf, hud_state(boss=boss_state(hp_frac=1.0)), 240)
    assert all(lum(surf, x, bar_y) > 250 for x in xs.values()), "full bar"
    run_hud(hud, app, surf, hud_state(boss=boss_state(hp_frac=0.5)), 240)
    assert lum(surf, xs[0.2], bar_y) > 250 and lum(surf, xs[0.8], bar_y) < 200, "half bar after settling"
    assert abs(hud.boss_hp - 0.5) < 0.01
    # A hit flashes the bar and trails a lost chunk behind the new value
    run_hud(hud, app, surf, hud_state(boss=boss_state(hp_frac=0.3)), 1)
    assert hud.boss_flash > 0.5 and hud.boss_hp > 0.3
    # Phase thresholds are drawn on the bar
    run_hud(hud, app, surf, hud_state(boss=boss_state(hp_frac=1.0)), 240)
    for frac in config.BOSS_PHASE_AT:
        px = 18 + int((540 - 36) * frac)
        assert lum(surf, px, hud_mod.BOSS_BAR_Y - 2) > 450, f"phase mark at {frac}"
    # Clock: m:ss while fighting, ENRAGED text instead when enraged (some frames blink off)
    clock = pg.Rect(150, 62, 250, 26)
    run_hud(hud, app, surf, hud_state(boss=boss_state(time_left=65.0)), 2)
    assert not is_blank(surf, clock)
    seen = False
    for _ in range(60):
        run_hud(hud, app, surf, hud_state(boss=boss_state(state="enrage", enraged=True, time_left=0.0)), 1)
        seen = seen or not is_blank(surf, pg.Rect(200, 62, 160, 26))
    assert seen
    set_width(BASE_W)


def test_hud_beam_hint():
    a = assets()
    for w in WIDTHS:
        set_width(w)
        app = _HudApp(a)
        px = w * 0.4
        text_zone = pg.Rect(int(px) - 90, config.PLAYER_Y - 100, 180, 40)

        def frame(frames=30, **kw):
            args = dict(player_x=px, boss_x=w / 2)
            args.update(kw)
            hud = hud_mod.Hud(app)
            surf = blank()
            run_hud(hud, app, surf, hud_state(boss=boss_state(**args), powerups=[], shield=0), frames)
            return surf

        def column(surf, x):
            return sum(lum(surf, xx, y) for y in range(400, 650, 2) for xx in range(int(x) - 3, int(x) + 4))

        assert is_blank(frame(energy=2), text_zone), "no text without enough energy"
        assert column(frame(energy=2), px) == column(blank(), px), "no aim line without enough energy"
        # Ready -> blinking text above the paddle (sample a whole blink cycle) and an aim line
        seen = False
        for _ in range(20):
            seen = seen or not is_blank(frame(1, energy=3), text_zone)
        assert seen, "beam ready text shows"
        assert column(frame(energy=3), px) > column(blank(), px), "aim line drawn"
        # States that cannot fire show no hint
        for st in ("intro", "victory"):
            s2 = frame(energy=6, state=st)
            assert is_blank(s2, text_zone) and column(s2, px) == column(blank(), px), st
        # Aim line is brighter when the paddle is under the boss than when it is off to the side
        half = 60.0
        far = w / 2 + half + config.BOSS_BEAM_WIDTH / 2 + 80
        on = frame(energy=3, player_x=w / 2, boss_half_w=half)
        off = frame(energy=3, player_x=far, boss_half_w=half)
        assert column(on, w / 2) > column(off, far) * 1.5, "aim line brighter when on target"
        # The boundary follows the beam hit rule (half width + half beam width)
        edge_in = frame(energy=3, player_x=w / 2 + half + config.BOSS_BEAM_WIDTH / 2 - 2, boss_half_w=half)
        edge_out = frame(energy=3, player_x=w / 2 + half + config.BOSS_BEAM_WIDTH / 2 + 4, boss_half_w=half)
        assert column(edge_in, w / 2 + half + config.BOSS_BEAM_WIDTH / 2 - 2) >             column(edge_out, w / 2 + half + config.BOSS_BEAM_WIDTH / 2 + 4) * 1.3
    set_width(BASE_W)


#Banners
def test_banners():
    a = assets()
    boss = {"name_key": "boss.kind.2.name", "number": 12, "kind": 2, "colors": ("purple", "green")}
    for lang in ("vi", "en"):
        i18n.set_language(lang)
        for w in WIDTHS:
            set_width(w)
            for fn in (lambda s, k: boss_ui.draw_boss_banner(s, a, boss, k),
                       lambda s, k: boss_ui.draw_victory_banner(s, a, 12000, k),
                       lambda s, k: boss_ui.draw_callout(s, a, i18n.t("boss.phase", n=2), "orange", k),
                       lambda s, k: boss_ui.draw_callout(s, a, i18n.t("boss.ball_lost"), (255, 56, 88), k, cy=500)):
                for k in (-1.0, 0.0, 0.03, 0.1, 0.25, 0.45, 0.5, 0.55, 0.7, 0.9, 0.97, 1.0, 1.7):
                    surf = blank()
                    fn(surf, k)
                    if k <= 0.0 or k >= 1.0:
                        assert is_blank(surf, surf.get_rect()), f"nothing drawn at k={k}"
            # Each phase draws something
            for k in (0.25, 0.7):
                surf = blank()
                boss_ui.draw_boss_banner(surf, a, boss, k)
                assert not is_blank(surf, pg.Rect(0, H // 2 - 80, w, 160)), f"intro k={k} at {w}"
            surf = blank()
            boss_ui.draw_victory_banner(surf, a, 5000, 0.5)
            assert not is_blank(surf, pg.Rect(0, H // 2 - 80, w, 160))
            surf = blank()
            boss_ui.draw_callout(surf, a, i18n.t("boss.enraged"), "red", 0.3)
            assert not is_blank(surf, pg.Rect(0, 100, w, 130))
    i18n.set_language("vi")
    # Names and titles are shrunk to fit a 540 canvas
    set_width(540)
    for lang in ("vi", "en"):
        i18n.set_language(lang)
        for key in ("boss.kind.0.name", "boss.kind.1.name", "boss.kind.2.name", "boss.warning", "boss.defeated"):
            s = i18n.t(key)
            size = boss_ui._fit_size(a, s, 76, "display", 540 - 2 * boss_ui.SIDE_PAD)
            assert a.font(size, "display").size(s)[0] <= 540 - 2 * boss_ui.SIDE_PAD, key
    # The shared cached panels/text keep full alpha after fades
    surf = blank()
    boss_ui.draw_boss_banner(surf, a, boss, 0.05)
    surf2 = blank()
    boss_ui.draw_boss_banner(surf2, a, boss, 0.05)
    assert same_pixels(surf, surf2), "banner is deterministic (no alpha leak into caches)"
    i18n.set_language("vi")
    set_width(BASE_W)


#Reward scene
OPTIONS = ["wide", "life", "speed"]


def make_scene(app=None, options=OPTIONS, owned=None, on_pick=None):
    from game.scenes.boss_reward import BossRewardScene
    app = app or FakeApp(assets())
    sc = BossRewardScene(app)
    picks = []
    sc.on_enter(options=list(options), number=2, bonus=2000, owned=owned if owned is not None else {"life": 1},
                on_pick=on_pick if on_pick is not None else picks.append)
    sc.picks = picks
    return sc


def key(k):
    return pg.event.Event(pg.KEYDOWN, key=k, mod=0, unicode="", scancode=0)


def step(sc, seconds):
    n = int(round(seconds / config.PHYSICS_DT))
    for _ in range(n):
        sc.update(config.PHYSICS_DT)


def test_reward_layout():
    from game.scenes import boss_reward as br
    for w, stacked in ((540, True), (699, True), (700, False), (960, False), (1960, False)):
        set_width(w)
        sc = make_scene()
        assert sc.stacked == stacked, w
        assert len(sc.rects) == 3
        screen = pg.Rect(0, 0, w, H)
        for i, r in enumerate(sc.rects):
            assert screen.contains(r), f"card {i} inside the canvas at {w}: {r}"
            assert r.top >= br.HEADER_H and r.bottom <= H - br.FOOTER_H + 1, f"card {i} vertical bounds at {w}"
            for other in sc.rects[i + 1:]:
                assert not r.colliderect(other), f"cards overlap at {w}"
        # Row of cards (or column) is centred
        assert abs(sum(r.centerx for r in sc.rects) / 3 - w / 2) < 2
        if stacked:
            assert sc.rects[0].top < sc.rects[1].top < sc.rects[2].top
        else:
            assert sc.rects[0].left < sc.rects[1].left < sc.rects[2].left and sc.rects[0].w <= 340
    # Resize rebuilds the layout
    set_width(540)
    sc = make_scene()
    set_width(1260)
    sc.on_resize(540)
    assert not sc.stacked and sc.rects[0].top == sc.rects[2].top
    set_width(540)
    sc.on_resize(1260)
    assert sc.stacked
    # Fewer options still lay out
    for n in (1, 2):
        sc = make_scene(options=OPTIONS[:n])
        assert len(sc.rects) == n
        assert pg.Rect(0, 0, 540, H).contains(sc.rects[0])
    set_width(BASE_W)


def test_reward_input():
    set_width(540)
    app = FakeApp(assets())
    sc = make_scene(app)
    assert sc.focus == 1                                    # middle card is the default
    # Input guard: nothing counts during the first 0.6 s
    step(sc, 0.3)
    sc.handle_event(key(pg.K_RETURN))
    sc.handle_event(key(pg.K_SPACE))
    sc.handle_event(key(pg.K_1))
    sc.handle_event(pg.event.Event(pg.MOUSEBUTTONDOWN, pos=sc.rects[0].center, button=1))
    assert not sc.picks and app.scenes.pops == 0
    step(sc, 0.35)
    # Esc / P do nothing
    sc.handle_event(key(pg.K_ESCAPE))
    sc.handle_event(key(pg.K_p))
    assert not sc.picks and app.scenes.pops == 0 and sc.focus == 1
    # A/D and arrows move the focus (wrapping); movement sounds play
    sc.handle_event(key(pg.K_a))
    assert sc.focus == 0
    sc.handle_event(key(pg.K_LEFT))
    assert sc.focus == 2
    sc.handle_event(key(pg.K_d))
    assert sc.focus == 0
    sc.handle_event(key(pg.K_RIGHT))
    sc.handle_event(key(pg.K_RIGHT))
    assert sc.focus == 2
    assert app.audio.played.count("ui_move") == 5
    # Enter takes the focused card exactly once
    sc.handle_event(key(pg.K_RETURN))
    sc.handle_event(key(pg.K_RETURN))
    sc.handle_event(key(pg.K_1))
    assert sc.picks == ["speed"] and app.scenes.pops == 1
    assert "ui_select" in app.audio.played

    # Quick pick keys (main row and keypad)
    for k, idx in ((pg.K_1, 0), (pg.K_2, 1), (pg.K_3, 2), (pg.K_KP1, 0), (pg.K_KP3, 2)):
        app = FakeApp(assets())
        sc = make_scene(app)
        step(sc, 0.7)
        sc.handle_event(key(k))
        assert sc.picks == [OPTIONS[idx]] and app.scenes.pops == 1, k
    # Space takes as well; a quick pick beyond the option count is ignored
    app = FakeApp(assets())
    sc = make_scene(app)
    step(sc, 0.7)
    sc.handle_event(key(pg.K_4))
    assert not sc.picks
    sc.handle_event(key(pg.K_SPACE))
    assert sc.picks == [OPTIONS[1]]

    # Mouse: hover focuses, click takes
    app = FakeApp(assets())
    sc = make_scene(app)
    step(sc, 0.7)
    sc.handle_event(pg.event.Event(pg.MOUSEMOTION, pos=sc.rects[2].center, rel=(0, 0), buttons=(0, 0, 0)))
    assert sc.focus == 2
    sc.handle_event(pg.event.Event(pg.MOUSEBUTTONDOWN, pos=(2, 2), button=1))      # miss: nothing
    sc.handle_event(pg.event.Event(pg.MOUSEBUTTONDOWN, pos=sc.rects[0].center, button=3))   # wrong button
    assert not sc.picks
    sc.handle_event(pg.event.Event(pg.MOUSEBUTTONDOWN, pos=sc.rects[0].center, button=1))
    assert sc.picks == ["wide"] and app.scenes.pops == 1

    # on_pick raising does not trap the player: still popped once
    app = FakeApp(assets())

    def boom(_):
        raise RuntimeError("boom")
    log = logging.getLogger(config.LOGGER_NAME)
    old_level = log.level
    log.setLevel(logging.CRITICAL)                          # the scene logs the error on purpose
    try:
        sc = make_scene(app, on_pick=boom)
        step(sc, 0.7)
        sc.handle_event(key(pg.K_RETURN))
        assert app.scenes.pops == 1
        sc.handle_event(key(pg.K_RETURN))
        assert app.scenes.pops == 1
    finally:
        log.setLevel(old_level)

    # Autoplay takes the middle card after 1 s
    app = FakeApp(assets())
    app.autoplay = True
    sc = make_scene(app)
    step(sc, 0.9)
    assert not sc.picks
    step(sc, 0.2)
    assert sc.picks == ["life"] and app.scenes.pops == 1
    step(sc, 1.0)
    assert app.scenes.pops == 1 and len(sc.picks) == 1

    # No options: the scene closes by itself, on_pick is never called
    app = FakeApp(assets())
    sc = make_scene(app, options=[])
    assert app.scenes.pops == 1 and not sc.picks
    # Re-entering the (cached) scene starts a fresh choice
    app = FakeApp(assets())
    sc = make_scene(app)
    step(sc, 0.7)
    sc.handle_event(key(pg.K_RETURN))
    got = []
    sc.on_enter(options=OPTIONS, number=3, bonus=3000, owned={}, on_pick=got.append)
    assert sc.timer == 0.0 and not sc.done
    step(sc, 0.7)
    sc.handle_event(key(pg.K_RETURN))
    assert got == ["life"] and app.scenes.pops == 2


def test_reward_draw():
    a = assets()
    for lang in ("vi", "en"):
        i18n.set_language(lang)
        for w in WIDTHS:
            set_width(w)
            for options, owned in ((OPTIONS, {}), (OPTIONS, {"wide": 2, "life": 3, "speed": 1}),
                                   (["power", "magnet", "life"], {"power": 1}), (["life"], {}), (["mystery"], {})):
                sc = make_scene(FakeApp(a), options=options, owned=owned)
                surf = blank()
                for _ in range(60):
                    sc.update(config.PHYSICS_DT * 4)
                    sc.draw(surf)
                assert not is_blank(surf, sc.rects[0]), "card drawn"
            # Standalone (only scene on the stack): it paints its own background
            app = FakeApp(a)
            app.scenes = FakeScenes(("boss_reward",))
            sc = make_scene(app)
            surf = blank()
            sc.update(1.0)
            sc.draw(surf)
    i18n.set_language("vi")
    set_width(BASE_W)


def test_reward_real_app():
    """The real App registers the scene (not a placeholder), pushes it on top of another scene and pops it."""
    tmp = tempfile.mkdtemp(prefix="hungdo_bossui_")
    set_width(BASE_W)
    from game.app import App
    app = App(["--data-dir", tmp, "--start-scene", "menu"])
    try:
        assert "boss_reward" not in app.placeholders, "boss_reward scene module loads"
        got = []
        for _ in range(3):
            app.step(DT)
        app.scenes.push("boss_reward", options=["magnet", "power", "speed"], number=1, bonus=1000, owned={},
                        on_pick=got.append)
        for _ in range(5):
            app.step(DT)
        assert app.scenes.top_name == "boss_reward" and app.scenes.stack_names == ["menu", "boss_reward"]

        def press(k):
            pg.event.post(pg.event.Event(pg.KEYDOWN, key=k, mod=0, unicode="", scancode=0))
            app.step(DT)
        press(pg.K_RETURN)                                  # inside the input guard
        press(pg.K_ESCAPE)
        assert app.scenes.top_name == "boss_reward" and not got
        for _ in range(45):
            app.step(DT)
        press(pg.K_RIGHT)
        press(pg.K_RETURN)
        for _ in range(3):
            app.step(DT)
        assert got == ["speed"], got
        assert app.scenes.stack_names == ["menu"], app.scenes.stack_names
        # Esc on the howto screen still works with the new rows
        app.scenes.push("howto")
        for _ in range(3):
            app.step(DT)
        press(pg.K_ESCAPE)
        assert app.scenes.stack_names == ["menu"]
    finally:
        app.close()
        shutil.rmtree(tmp, ignore_errors=True)


#How to play
def test_howto_layout():
    from game.scenes import howto
    a = assets()
    for lang in ("vi", "en"):
        i18n.set_language(lang)
        for w in (540, 1260):
            set_width(w)
            app = FakeApp(a)
            app.scenes = FakeScenes(("menu", "howto"))
            sc = howto.HowToScene(app)
            sc.on_enter()
            sc.update(DT)
            surf = blank()
            sc.draw(surf)
            # Everything fits above the Back button
            panel_bottom = howto.ROW_TOP - 34 + howto.ROW_H * len(howto.ROWS) + 42
            last_row = panel_bottom + 12 + 28 + howto.CTRL_ROW_H
            tip_y = last_row + 48
            lines, size = howto.HowToScene._wrap_tip(a, i18n.t("howto.boss_tip"), config.BASE_W - 40, 2)
            assert 1 <= len(lines) <= 2 and size >= 17, (lang, lines, size)
            for ln in lines:
                assert a.font(size, "regular").size(ln)[0] <= config.BASE_W - 40
            boss_bottom = tip_y + 25 + (len(lines) - 1) * (a.font(size, "regular").get_height() - 2) + size
            back = sc.menu.widgets[0].rect
            assert boss_bottom < back.top, f"boss tip clears the Back button ({boss_bottom} vs {back.top}) {lang}"
            assert back.bottom <= H - 8
            dx = (w - config.BASE_W) // 2
            # The Space keycap row and the boss tip rows have pixels
            assert not is_blank(surf, pg.Rect(dx + 30, last_row, 200, 30)), "Space row drawn"
            assert not is_blank(surf, pg.Rect(dx + 20, tip_y + 14, config.BASE_W - 40, 24)), "boss tip drawn"
    i18n.set_language("vi")
    set_width(BASE_W)


#Screenshots
def save_shots() -> None:
    from game.scenes.howto import HowToScene
    out = os.path.join(ROOT, "tools", "_out")
    os.makedirs(out, exist_ok=True)
    a = assets()
    from game.ui.widgets import FallbackBackground

    def field(w: int, boss_x: float, player_x: float, half_w: float = 80.0) -> pg.Surface:
        """Play-field stand-in: gradient, boss body box, paddle bar."""
        surf = FallbackBackground().base.copy() if w == 540 else pg.Surface((w, H))
        if w != 540:
            surf.fill(BG)
        pg.draw.rect(surf, (90, 60, 130), (boss_x - half_w, config.BOSS_Y - 70, half_w * 2, 140), 2, border_radius=18)
        pg.draw.rect(surf, PAL["cyan"], (player_x - 55, config.PLAYER_Y - 11, 110, 22), border_radius=8)
        return surf

    for w, name in ((540, "540"), (1260, "1260")):
        set_width(w)
        for label, kw in (("fight", dict(state="fight", energy=3, hp_frac=0.55, phase=2, time_left=47.0)),
                          ("enrage", dict(state="enrage", enraged=True, energy=5, hp_frac=0.2, phase=3, time_left=0.0)),
                          ("intro", dict(state="intro", energy=0, hp_frac=1.0))):
            app = _HudApp(a)
            hud = hud_mod.Hud(app)
            bx = w * 0.62
            boss = boss_state(kind=2, number=3, name_key="boss.kind.2.name", colors=("purple", "green"),
                              boss_x=bx, player_x=bx + 20, boss_half_w=90.0, **kw)
            state = hud_state(boss=boss, powerups=[("magnet", 5.0, 8)] if label == "fight" else [])
            surf = field(w, bx, bx + 20, 90.0)
            for _ in range(240):
                app.time += DT
                surf2 = surf.copy()
                hud.draw(surf2, state)
            pg.image.save(surf2, os.path.join(out, f"boss_hud_{name}_{label}.png"))
        # Banners over the field
        boss = {"name_key": "boss.kind.2.name", "number": 3, "kind": 2, "colors": ("purple", "green")}
        for label, fn in (("warn", lambda s: boss_ui.draw_boss_banner(s, a, boss, 0.25)),
                          ("name", lambda s: boss_ui.draw_boss_banner(s, a, boss, 0.72)),
                          ("victory", lambda s: boss_ui.draw_victory_banner(s, a, 3000, 0.6)),
                          ("callout", lambda s: boss_ui.draw_callout(s, a, i18n.t("boss.phase", n=2), "orange", 0.3))):
            surf = field(w, w * 0.5, w * 0.5)
            fn(surf)
            pg.image.save(surf, os.path.join(out, f"boss_banner_{name}_{label}.png"))
        # Reward scene
        app = FakeApp(a)
        app.scenes = FakeScenes(("boss_reward",))
        sc = make_scene(app, options=["wide", "life", "speed"], owned={"life": 2})
        surf = blank()
        for _ in range(180):
            sc.update(config.PHYSICS_DT)
        sc.draw(surf)
        pg.image.save(surf, os.path.join(out, f"boss_reward_{name}.png"))
        sc = make_scene(app, options=["power", "magnet", "life"], owned={})
        sc.focus = 0
        for _ in range(180):
            sc.update(config.PHYSICS_DT)
        surf = blank()
        sc.draw(surf)
        pg.image.save(surf, os.path.join(out, f"boss_reward_{name}_b.png"))
        # How to play
        app = FakeApp(a)
        app.scenes = FakeScenes(("menu", "howto"))
        sc = HowToScene(app)
        sc.on_enter()
        for _ in range(30):
            sc.update(DT)
        surf = blank()
        sc.draw(surf)
        pg.image.save(surf, os.path.join(out, f"howto_{name}.png"))
    set_width(BASE_W)


TESTS = [
    test_lang_keys, test_hud_backward_compatible, test_hud_boss_draws_every_state, test_hud_boss_layout,
    test_hud_boss_bar, test_hud_beam_hint, test_banners, test_reward_layout, test_reward_input, test_reward_draw,
    test_howto_layout, test_reward_real_app,
]


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    i18n.set_language("vi")
    if "--shots" in argv:
        save_shots()
        print("screenshots saved to tools/_out/")
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
        finally:
            set_width(BASE_W)
            i18n.set_language("vi")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
