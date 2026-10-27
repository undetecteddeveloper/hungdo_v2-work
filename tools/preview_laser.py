"""Prototype viewer for the boss laser firing animation (Hex Core, boss of level 10). Nothing here is part of the game.

    python tools/preview_laser.py                 # window: the real BossController + the real drawing code
    python tools/preview_laser.py --sheet         # no window: writes tools/_out/laser_sheet.png (frames of A / B / C)

Keys in the window:
    1 2 3      animation variant A / B / C        Tab   boss phase 2 <-> 3
    A D / < >  move the paddle (the boss slides to it)   Space  fire the laser now
    S          slow motion on / off                Esc   quit
The laser repeats on its own. The red strip under the boss is the real warning column; the paddle flashes red when it is hit.
"""
import argparse
import os
import random
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import pygame as pg  # noqa: E402

from game import config  # noqa: E402
from game.render import boss_draw, boss_laser  # noqa: E402
from game.systems.boss import BossController  # noqa: E402

W, H = config.LOGICAL_W, config.LOGICAL_H
DT = 1 / 120
NAMES = {"A": "A  Nòng lõi", "B": "B  Lăng kính hội tụ", "C": "C  Pháo cánh kép"}
OUT = os.path.join(ROOT, "tools", "_out")


class Rig:
    """One boss + one paddle position, stepped like the game does (volleys switched off, laser repeating)."""

    def __init__(self, phase: int = 2, seed: int = 5):
        self.ctrl = BossController(random.Random(seed))
        self.boss = self.ctrl.start(1)
        self.px = W / 2
        self.t = 0.0
        self.hit_flash = 0.0
        self.rest = 1.2                                     # s of calm before the next laser
        for _ in range(int(4.0 / DT)):
            self.ctrl.update(DT, self.px, 0)
            if self.ctrl.state == "fight":
                break
        self.set_phase(phase)

    def set_phase(self, phase: int) -> None:
        c = self.ctrl
        frac = {1: 0.0, 2: 0.4, 3: 0.7}[phase]
        c.boss.hp = c.boss.max_hp * (1.0 - frac)
        c.boss.phase = phase
        c._sweep_t = 1e9

    def fire_now(self) -> None:
        if not self.ctrl.sweeps:
            self.ctrl._sweep_pending = True

    def step(self, dt: float, auto: bool = True) -> None:
        c = self.ctrl
        c._idle_t = 99.0                                    # no bullet volleys, only the laser
        c._stagger_t = 0.0
        if auto and not c.sweeps and not c._sweep_pending:
            self.rest -= dt
            if self.rest <= 0.0:
                c._sweep_pending = True
        if c.sweeps:
            self.rest = 1.4
        c.update(dt, self.px, 0)
        self.t += dt
        self.hit_flash = max(0.0, self.hit_flash - dt)
        if c.sweep_hits(pg.Rect(int(self.px - 55), config.PLAYER_Y - 11, 110, 22)):
            self.hit_flash = 0.5


def draw_world(surf: pg.Surface, rig: Rig, t: float) -> None:
    surf.fill((7, 8, 24))
    for gy in range(0, H, 60):
        pg.draw.line(surf, (14, 18, 44), (0, gy), (W, gy))
    for gx in range(0, W, 60):
        pg.draw.line(surf, (14, 18, 44), (gx, 0), (gx, H))
    b = rig.ctrl.boss
    for sw in rig.ctrl.sweeps:
        boss_draw.draw_sweep(surf, sw, b.pos.y + b.half_h, t)
    boss_draw.draw_boss(surf, b, t)
    col = (255, 90, 90) if rig.hit_flash > 0 else (60, 235, 255)
    pr = pg.Rect(int(rig.px - 55), config.PLAYER_Y - 11, 110, 22)
    pg.draw.rect(surf, col, pr, border_radius=8)
    pg.draw.rect(surf, (230, 255, 255), pr.inflate(-30, -14), border_radius=4)


def run_window(args) -> None:
    pg.init()
    desk = pg.display.get_desktop_sizes()[0]
    scale = max(0.5, min(1.3, desk[1] * 0.88 / H)) if not args.scale else args.scale
    win = pg.display.set_mode((int(W * scale), int(H * scale)))
    pg.display.set_caption("Hứng Đồ - xem thử hoạt ảnh laser của boss")
    canvas = pg.Surface((W, H))
    font = pg.font.SysFont("segoeui,arial,tahoma", 20)
    small = pg.font.SysFont("segoeui,arial,tahoma", 16)
    rig = Rig(phase=2)
    boss_draw.LASER_VARIANT = "A"
    phase, slow = 2, False
    clock = pg.time.Clock()
    acc = 0.0
    running = True
    while running:
        real = min(0.05, clock.tick(120) / 1000.0)
        for ev in pg.event.get():
            if ev.type == pg.QUIT or (ev.type == pg.KEYDOWN and ev.key == pg.K_ESCAPE):
                running = False
            elif ev.type == pg.KEYDOWN:
                if ev.key in (pg.K_1, pg.K_2, pg.K_3):
                    boss_draw.LASER_VARIANT = "ABC"[ev.key - pg.K_1]
                elif ev.key == pg.K_TAB:
                    phase = 5 - phase
                    rig.set_phase(phase)
                elif ev.key == pg.K_SPACE:
                    rig.fire_now()
                elif ev.key == pg.K_s:
                    slow = not slow
        keys = pg.key.get_pressed()
        move = (keys[pg.K_d] or keys[pg.K_RIGHT]) - (keys[pg.K_a] or keys[pg.K_LEFT])
        rig.px = min(max(rig.px + move * 520 * real, 60), W - 60)
        acc += real * (0.3 if slow else 1.0)
        while acc >= DT:
            rig.step(DT)
            acc -= DT
        draw_world(canvas, rig, rig.t)
        b = rig.ctrl.boss
        info = [f"Kiểu: {NAMES[boss_draw.LASER_VARIANT]}   (phím 1 / 2 / 3)", f"Giai đoạn boss: {phase}   (Tab)",
                f"Tia: {b.laser or '-'}   {'chậm 0.3x' if slow else 'tốc độ thường'}   (S)"]
        for i, line in enumerate(info):
            canvas.blit(font.render(line, True, (200, 220, 255)), (12, 10 + i * 24))
        canvas.blit(small.render("A D / mũi tên: di chuyển thanh   Space: bắn laser ngay   Esc: thoát", True, (130, 150, 190)),
                    (12, H - 26))
        pg.transform.smoothscale(canvas, win.get_size(), win)
        pg.display.flip()
    pg.quit()


def make_sheet(args) -> None:
    """Frames of one laser shot per variant: columns are moments of the shot, rows are the variants."""
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    pg.init()
    pg.display.set_mode((16, 16))
    canvas = pg.Surface((W, H))
    moments = [("ngắm", "aim", 0.5), ("khoá 0.1", "lock", 0.1), ("khoá 0.5", "lock", 0.5), ("khoá 0.95", "lock", 0.95),
               ("bắn 0.05", "fire", 0.05), ("bắn 0.5", "fire", 0.5), ("đóng", "", 0.0)]
    crop = pg.Rect(0, 0, 300, 470)
    font = pg.font.SysFont("segoeui,arial,tahoma", 18)
    sheet = pg.Surface((crop.w * len(moments), (crop.h + 28) * 3))
    sheet.fill((0, 0, 0))
    for row, variant in enumerate("ABC"):
        boss_draw.LASER_VARIANT = variant
        rig = Rig(phase=args.phase)
        rig.px = W / 2 + 130
        rig.fire_now()
        got = {}
        for _ in range(int(9.0 / DT)):
            rig.step(DT, auto=False)
            b = rig.ctrl.boss
            for i, (_, stage, k) in enumerate(moments):
                if i in got:
                    continue
                if stage == "" and b.laser == "" and got.get(i - 1) is not None and rig.ctrl.boss.laser_open > 0.4 and not rig.ctrl.sweeps:
                    ok = True
                elif stage and b.laser == stage and b.laser_k >= k:
                    ok = True
                else:
                    ok = False
                if ok:
                    draw_world(canvas, rig, rig.t)
                    focus = pg.Rect(0, 0, crop.w, crop.h)
                    focus.midtop = (int(b.pos.x), 80)
                    focus.clamp_ip(canvas.get_rect())
                    got[i] = canvas.subsurface(focus).copy()
        for i, (label, _, _) in enumerate(moments):
            x, y = i * crop.w, row * (crop.h + 28)
            if i in got:
                sheet.blit(got[i], (x, y + 28))
            sheet.blit(font.render(f"{variant}  {label}", True, (255, 220, 140)), (x + 6, y + 4))
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, "laser_sheet.png")
    pg.image.save(sheet, path)
    print("saved", path)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sheet", action="store_true", help="write tools/_out/laser_sheet.png instead of opening a window")
    ap.add_argument("--phase", type=int, default=2, choices=(2, 3), help="boss phase for --sheet")
    ap.add_argument("--scale", type=float, default=0.0, help="window scale (default: fit the screen)")
    args = ap.parse_args()
    if args.sheet:
        make_sheet(args)
    else:
        run_window(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
