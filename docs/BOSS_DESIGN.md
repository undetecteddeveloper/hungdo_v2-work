# Hứng Đồ v2 — Thiết kế BOSS (tài liệu TẠM, xoá sau khi tính năng xong)

Đây là hợp đồng giữa 4 agent thi công song song (A, B, C, D) và điều phối viên (viết `scenes/play.py`).
Đọc kèm `docs/ARCHITECTURE.md` (toạ độ, timing, quy tắc hiệu năng). Chữ ký hàm dưới đây là CHỐT: không đổi
tên, không đổi thứ tự tham số. Thiếu gì thì thêm BÊN TRONG file của mình và ghi vào báo cáo.

## 0. Quy ước chung

- Python: `E:/pygame projects/HungDo_project/.venv/Scripts/python.exe` (3.13, pygame-ce 2.5.8, numpy). Code ở
  `E:\pygame projects\hungdo_v2-work\hungdo_v2\` (nhánh `v2-boss`). Chạy từ thư mục `hungdo_v2/`.
- Headless: đặt `SDL_VIDEODRIVER=dummy SDL_AUDIODRIVER=dummy`. Test: `python -m tests.<tên>` (assert thường, có `main()`
  trả 0/1 như `tests/test_gameplay.py`, in `PASS/FAIL`). Mỗi agent phải chạy test của mình VÀ `python -m tests.test_gameplay`
  (đang 14/14, không được hỏng).
- Comment code bằng tiếng Anh, ngắn, đúng giọng các module cũ; type hint cho hàm public; không `print` trong vòng lặp nóng;
  dùng `logging.getLogger(config.LOGGER_NAME)`.
- Sân chơi cao 840, rộng `config.LOGICAL_W` (540..1960). ĐỌC `config.LOGICAL_W` TẠI LÚC DÙNG, không cache lúc import.
  Mọi mẫu đòn/vị trí phải đúng ở 540, ~960 và 1960 rộng. Tham số tốc độ thanh hứng dùng `config.player_w()`,
  `player_max_speed()`, `player_accel()`, `player_friction()` (không dùng thẳng `PLAYER_*`).
- Mọi hằng số cân bằng đã nằm ở khối `#Boss fights` cuối `game/config.py` (điều phối viên đã thêm; agent chỉ ĐỌC, không sửa
  config.py/app.py). Cần số mới thì đặt hằng số ở đầu file của mình.
- Màu: dùng khoá của `config.PALETTE` (chuỗi) hoặc RGB tuple; chuyển khoá → RGB bằng `config.PALETTE[key]`.
- KHÔNG chạy `git commit/checkout/stash/reset`, KHÔNG chạy `build.py`, KHÔNG chạy `tools/smoke_test.py` (điều phối viên làm).
- Mỗi agent chỉ sửa file của mình (bảng dưới). Thấy lỗi ở file người khác: ghi vào báo cáo, đừng sửa.

| Agent | File được sở hữu (tạo/sửa) |
|---|---|
| A — logic boss | `game/systems/boss.py`, `tests/test_boss.py` |
| B — vật thể | `game/entities/boss_items.py`, `tests/test_boss_items.py` |
| C — giao diện | `game/ui/hud.py`, `game/ui/boss_ui.py`, `game/scenes/boss_reward.py`, `game/scenes/howto.py`, `lang/vi.json`, `lang/en.json`, `tests/test_boss_ui.py` |
| D — hình + âm | `game/render/boss_draw.py`, `tools/synth_sfx.py`, `assets/sound/*.wav` (6 file boss), `tests/test_boss_draw.py` |
| Điều phối | `scenes/play.py`, `entities/player.py`, `config.py`, `app.py`, `tools/smoke_test.py`, `docs/*`, `build.py` |

## 1. Luật chơi tóm tắt (đã chốt với người dùng)

- Level đạt bội số của 10 (`config.BOSS_EVERY`) → vào trận boss. Boss thứ `n` (n=1 ở level 10) dùng kiểu `kind = (n-1) % 3`
  (3 kiểu: hình neon, màu, bộ đòn riêng), `cycle = (n-1) // 3`. Từ boss 4 lặp lại kiểu 0 với máu ×`(1 + 0.35*cycle)` và đòn
  nhanh ×`(1 + 0.20*cycle)`.
- Trong trận: vật thường (điểm/bom/power-up) dừng hẳn và bị dọn khi vào trận; level đứng yên; điểm chỉ từ sát thương
  (`dealt * BOSS_POINTS_PER_HP`) và thưởng hạ boss. Power-up đang chạy (nam châm, chậm, rộng, khiên) vẫn còn hiệu lực.
- Vật hại của boss (Projectile) và đòn quét chạm thanh hứng: khiên hấp thụ 1 lần, không có khiên thì mất 1 mạng, rồi bất tử
  `BOSS_HIT_IFRAMES` giây (điều phối viên xử lý).
- Bóng bật (HelperBall): rơi từ trời; thanh hứng chạm thì bật lên ngay (kiểu Brick Breaker), góc theo chỗ chạm; trúng boss
  gây `BOSS_BALL_DAMAGE`; bật tường/trần; rơi xuống thanh thì bật lại; lọt qua thanh → mất bóng + mất 1 mạng.
- Năng lượng (EnergyItem): rơi từ trời, một loại duy nhất (giả định d: "cùng loại" = cùng là item năng lượng). Hứng đủ
  `BOSS_ENERGY_NEED`=3 thì bấm Space bắn tia thẳng lên từ x thanh hứng lúc đó; tia trúng boss khi x nằm trong thân boss
  (cộng nửa bề rộng tia) → `BOSS_BEAM_DAMAGE`. Giữ tối đa `BOSS_ENERGY_CAP`=6. Rơi mất item hỗ trợ không bị phạt.
- Boss có đồng hồ `BOSS_TIME_LIMIT`=90 s; hết giờ thì "nổi giận" (bắn dày ×1.7, đạn nhanh ×1.15), KHÔNG thua ngay.
- 3 giai đoạn: đổi mẫu đòn khi còn ≤66% và ≤33% máu (có `BOSS_STAGGER_TIME` ngừng bắn khi đổi).
- Đòn đặc biệt DUY NHẤT: quét ngang có báo trước (dải cảnh báo → tia quét → phải chạy ra khỏi dải). KHÔNG đảo phím, tối
  màn hình, mưa đạn.
- Hạ boss: điểm thưởng `BOSS_CLEAR_BONUS * số boss đã hạ`, hồi đầy mạng, màn chọn 1 trong 3 nâng cấp tạm (`BOSS_UPGRADES`:
  `wide`, `magnet`, `life`, `power`, `speed`), rồi ván chơi tiếp bình thường.

## 2. Máy trạng thái trận boss (`BossController.state`)

```
idle ──start(n)──▶ intro ──(BOSS_INTRO_TIME)──▶ fight ──(time_left <= 0)──▶ enrage
                                                  │                            │
                                                  └──────── hp <= 0 ───────────┘
                                                                 ▼
                                                              victory ──(BOSS_VICTORY_TIME)──▶ done ──stop()──▶ idle
```
- `intro`: boss hạ từ trên xuống (ease-out) tới `config.BOSS_Y`, KHÔNG bắn, KHÔNG nhận sát thương, không rơi item hỗ trợ.
- `fight`: bắn theo giai đoạn, rơi item hỗ trợ, nhận sát thương. `time_left` đếm lùi từ `BOSS_TIME_LIMIT`.
- `enrage`: như `fight` nhưng `boss.enraged = True` (bắn dày hơn). Một chiều: không quay lại `fight`.
- `victory`: hp = 0, không bắn, không item, `boss.death_t` chạy 0→1 trong `BOSS_VICTORY_TIME`; phát event `"done"` khi hết.
- Phát sự kiện (chuỗi) trong `BossTick.events`: `"intro_end"`, `"charge"` (boss bắt đầu dồn lực trước đợt bắn),
  `"volley"` (một đợt bắn vừa ra), `"sweep_warn"`, `"sweep_fire"`, `"phase2"`, `"phase3"`, `"enrage"`, `"dead"` (hp vừa về 0),
  `"done"` (hết thời gian victory).

Luồng PlayScene (điều phối viên làm, để các agent biết ai gọi mình thế nào):
`normal` → (level đạt `next_boss_level`) dọn item + `warning`/`boss_intro` + `controller.start(n)` → mỗi bước
`tick = controller.update(dt, player.pos.x, balls_alive)` rồi spawn `tick.shots` → `Projectile`, `tick.drops` →
`HelperBall`/`EnergyItem`; cập nhật vật thể, va chạm; → `"dead"` → dọn vật hại/bóng/năng lượng, cộng thưởng → `"done"` →
`push("boss_reward", ...)` → chọn xong `pop` → `normal`.

## 3. Agent A — `game/systems/boss.py` (logic thuần, không vẽ)

```python
@dataclass
class Shot:                 # yêu cầu sinh 1 vật hại; play.py đổi thành entities.boss_items.Projectile
    x: float; y: float; vx: float; vy: float
    radius: float = 13.0
    shape: str = "orb"      # "orb" | "bolt" | "shard"
    color: str = "red"      # khoá PALETTE, CHỈ "red" | "orange" | "magenta" (màu = nguy hiểm, người chơi học được)

@dataclass
class Drop:                 # yêu cầu sinh 1 item hỗ trợ ở đỉnh màn hình
    kind: str               # "ball" | "energy"
    x: float

@dataclass
class BossTick:
    shots: list             # list[Shot] mới trong bước này (thường rỗng)
    drops: list             # list[Drop]
    events: list            # list[str] (xem mục 2)

class Boss:                 # trạng thái thuần; BossController sửa, D vẽ, C đọc
    kind: int               # 0..2  (kiểu hình/đòn)
    number: int             # 1-based, boss thứ mấy trong ván
    cycle: int              # (number-1)//3
    name_key: str           # "boss.kind.{kind}.name"
    colors: tuple           # (khoá PALETTE chính, khoá phụ), vd ("orange", "yellow")
    pos: pg.Vector2         # tâm; x do đi tuần, y = BOSS_Y (trong intro y chạy từ trên màn hình xuống)
    half_w: float; half_h: float   # nửa kích thước hitbox, trong khoảng [60,100] x [50,75]
    max_hp: float; hp: float
    phase: int              # 1..3
    hit_flash: float        # 0..1, giảm về 0 trong ~0.18 s sau mỗi cú trúng
    charge: float           # 0..1, dồn lực trước đợt bắn (D vẽ báo hiệu); 0 khi rảnh
    enraged: bool
    anim_t: float           # giây từ start() (gồm intro), để D làm hoạt ảnh
    death_t: float          # 0..1 tiến độ nổ (0 khi còn sống)
    @property hp_frac -> float          # 0..1
    @property rect -> pg.Rect           # hitbox: (pos.x-half_w, pos.y-half_h, 2*half_w, 2*half_h)

class Sweep:                # đòn quét: dải cảnh báo → tia quét. Một cột dọc từ đáy boss xuống hết màn hình.
    x_from: float; x_to: float      # tâm tia lúc bắt đầu / kết thúc pha bắn (khác nhau = tia quét ngang)
    width: float                    # bề rộng tia (90..150)
    warn_time: float                # >= 1.1 s
    fire_time: float                # 0.45..0.9 s
    age: float
    consumed: bool                  # True sau khi đã gây sát thương người chơi (mỗi đòn chỉ gây 1 lần)
    @property phase -> str          # "warn" | "fire" | "done"
    @property zone -> tuple         # (x0, x1) dải cảnh báo = hợp của mọi chỗ tia đi qua
    @property beam_x -> float       # tâm tia hiện tại (= x_from khi đang warn)
    @property k_warn -> float       # 0..1 trong pha warn
    @property k_fire -> float       # 0..1 trong pha fire
    def hits(self, rect: pg.Rect) -> bool   # chỉ khi phase == "fire" và chưa consumed; rect cắt [beam_x±width/2]

class BossController:
    def __init__(self, rng: random.Random = None)
    state: str                      # "idle"|"intro"|"fight"|"enrage"|"victory"|"done"
    boss: Boss | None
    sweeps: list                    # list[Sweep] đang sống (cả warn lẫn fire)
    time_left: float                # giây tới nổi giận (0 khi đã nổi giận)
    def start(self, number: int) -> Boss
    def stop(self) -> None          # về idle, xoá hết
    def update(self, dt: float, player_x: float, balls_alive: int = 0) -> BossTick
    def damage(self, amount: float, source: str = "beam") -> float   # trả hp thực trừ; 0 nếu không nhận sát thương
    def sweep_hits(self, rect: pg.Rect) -> bool                      # có Sweep nào vừa trúng rect (đánh dấu consumed)
    def on_resize(self, old_w: int) -> None   # nhân x boss/sweep với LOGICAL_W/old_w rồi kẹp lại
    @property active -> bool        # state không phải idle/done
    @property fighting -> bool      # state in ("fight","enrage")
    @property damageable -> bool    # = fighting
    @property hit_rect -> pg.Rect | None   # boss.rect khi damageable, ngược lại None (dùng cho bóng/tia)
    @staticmethod
    def design(number: int) -> tuple        # (kind, cycle)
```

Yêu cầu hành vi:
1. Máu `max_hp = BOSS_BASE_HP * (1 + BOSS_HP_GROWTH * cycle)`. `damage()` bị bỏ qua (trả 0) ngoài fight/enrage; đặt
   `hit_flash = 1`; hp về 0 → `state = "victory"`, sự kiện `"dead"` đi vào `events` của lần `update` kế tiếp (hàng đợi).
   Đổi giai đoạn khi `hp_frac` ≤ `BOSS_PHASE_AT[0]`/`[1]` (có thể nhảy 2 bậc nếu sát thương lớn): sự kiện `"phase2"`/`"phase3"`,
   ngừng bắn `BOSS_STAGGER_TIME`, KHÔNG huỷ vật hại đang bay (đó là việc của play.py nếu cần).
2. Tốc độ đòn `speed = 1 + BOSS_SPEED_GROWTH * cycle` (nhân vận tốc đạn và chia khoảng cách giữa các đòn). Khi `enrage`:
   khoảng cách giữa các đòn chia `BOSS_ENRAGE_RATE`, vận tốc đạn nhân `BOSS_ENRAGE_SPEED`.
3. Boss đi tuần ngang trong `[half_w + BOSS_MARGIN, LOGICAL_W - half_w - BOSS_MARGIN]`, mượt (không giật đột ngột), tốc độ
   ~60..140 px/s tuỳ kiểu và nhân `config.field_scale() ** 0.5`; ĐỨNG YÊN khi `charge > 0` và khi sweep đang warn/fire. Phải
   canh tia trúng được: người chơi nhắm vào boss đang đi chậm, không phải mục tiêu bay.
4. Bộ đòn theo kiểu và giai đoạn (A thiết kế chi tiết, mỗi kiểu có "chữ ký" riêng). Các mẫu cơ bản: `fan` (quạt N viên từ
   thân boss), `row` (hàng ngang cả bề rộng sân với MỘT khoảng hở), `aimed` (1-3 viên nhắm vào x người chơi, khoá hướng lúc
   bắn, KHÔNG dự đoán), thêm biến thể riêng từng kiểu (vd quạt xoay, hàng so le). Gợi ý: kiểu 0 "Lõi Hex" (cam/vàng, hình lục giác):
   aimed + fan; kiểu 1 "Lăng Kính" (magenta/cyan, nhiều hình thoi): row + fan có khe di chuyển; kiểu 2 "Mắt Hư Không" (tím/xanh lá,
   con mắt): aimed + row, quét đôi ở giai đoạn 3. Đòn quét (Sweep) xuất hiện từ giai đoạn 2 (hoặc 1 với kiểu nào A muốn), cách
   nhau >= 6 s, KHÔNG chồng nhau; trong lúc warn/fire và 0.6 s sau không bắt đầu đợt bắn mới.
5. Công bằng (có test): vận tốc đạn trong 220..520 px/s ở speed=1 (trước nổi giận); `aimed` dồn lực `charge` >= 0.5 s trước
   khi bắn; khoảng hở của `row` >= `config.player_w() * 1.6 + 2*radius`; `fan` rải trong ±40° và khoảng cách thanh hứng-đạn
   gần nhất vẫn cho phép chạy thoát; sweep: `warn_time >= 1.1`, `zone` rộng <= `0.55 * LOGICAL_W`, và với MỌI x người chơi
   trong zone, thanh hứng thật (`entities.player.Player`, phản xạ 0.25 s) thoát khỏi zone trước khi tia bắn (rộng 540, 960, 1960).
   Với mỗi mẫu đòn, kiểm bằng "bộ kiểm tra bảo thủ" trong test: từ 40 cặp (x boss, x người chơi) ngẫu nhiên luôn tồn tại một
   x an toàn người chơi chạy tới kịp trước viên đạn đầu tiên chạm đường thanh hứng (phản xạ 0.3 s).
6. Item hỗ trợ: `drops` theo nhịp đều `BOSS_ENERGY_INTERVAL`/`BOSS_BALL_INTERVAL` ± `BOSS_HELPER_JITTER`, lần đầu sau
   `BOSS_FIRST_ENERGY`/`BOSS_FIRST_BALL` giây kể từ đầu fight. Bóng chỉ rơi khi `balls_alive < BOSS_MAX_BALLS` (thiếu thì dời
   ~0.5 s rồi thử lại). x ngẫu nhiên cách tường >= 40 px, KHÔNG nhắm thẳng chỗ người chơi. Không drop trong intro/victory.
7. `update()` ở idle/done/victory chỉ chạy hoạt ảnh (`death_t`, `hit_flash`) và trả `BossTick` rỗng (trừ event `"done"`).
8. Test (`tests/test_boss.py`): máy trạng thái và thứ tự sự kiện; hp/phase/stagger; nổi giận đúng giờ; thiết kế `design(n)`
   (n=1..7); công bằng (mục 5) cho cả 3 kiểu x 3 giai đoạn x bề rộng 540/960/1960; độ lặp lại với seed cố định; drops đều và
   tôn trọng `BOSS_MAX_BALLS`; `on_resize`; `Sweep.hits` và `consumed`; mô phỏng 5.000 bước không lỗi/không đạn NaN.

## 4. Agent B — `game/entities/boss_items.py` (vật thể + va chạm + vẽ chính chúng)

Dùng lại helper của `entities/items.py` (`glow_circle_at`, `glow_rect_at`, `add_dot`, `scale_color`, `mix_color`,
`regular_polygon`, `outline`, `step_fall`). Mọi class có `draw(surf, t, assets=None)` theo giọng của `Item.draw`.

```python
class Projectile:                   # vật hại; bay thẳng đều, KHÔNG có trọng lực, KHÔNG nảy tường
    def __init__(self, x, y, vx, vy, radius=13.0, shape="orb", color="red")   # color: khoá PALETTE hoặc RGB
    pos: pg.Vector2; vel: pg.Vector2; radius: float; shape: str; color: tuple   # RGB đã phân giải
    alive: bool; age: float
    @property hit_radius -> float   # radius * 0.8 (khoan dung)
    @property rect -> pg.Rect
    def update(self, dt, time_scale=1.0) -> None   # alive=False khi ra khỏi màn hình (x ngoài [-r*3, W+r*3], y > H + r*3)
    def hits(self, rect: pg.Rect) -> bool          # đường tròn hit_radius cắt hình chữ nhật (chính xác, không dùng bbox)
    def draw(self, surf, t, assets=None) -> None   # "orb" tròn lõi tối, "bolt" thoi dài xoay theo hướng bay, "shard" mảnh gai

class EnergyItem:                   # item năng lượng rơi từ trời
    kind = "energy"
    def __init__(self, x, y=None)   # y=None: ngay trên mép trên màn hình
    pos; vel; radius = 15; alive; fell (rơi khỏi đáy); magnetized; age
    @property rect -> pg.Rect
    def update(self, dt, time_scale=1.0, magnet_x=None) -> None   # rơi bằng items.step_fall (gravity=GRAVITY*0.8, terminal=BOSS_HELPER_TERMINAL); magnet_x kéo ngang như Item (tầm config.magnet_radius())
    def draw(...)                   # màu vàng PAL["yellow"], hình lục giác + tia sét, khác hẳn đạn đỏ

class HelperBall:                   # quả bóng bật
    def __init__(self, x, y=None)
    state: str                      # "falling" (chưa hứng) | "flying" (đang bật)
    pos; vel; radius = BOSS_BALL_RADIUS; alive; fell; magnetized; age; hit_cd
    @property rect -> pg.Rect
    def update(self, dt, time_scale, magnet_x, paddle: pg.Rect, boss_rect: pg.Rect | None) -> tuple   # tuple[str,...] sự kiện
    def draw(...)                   # lõi trắng, vầng cyan, vệt đuôi; bay nhanh thì đuôi dài
```
Sự kiện của `HelperBall.update` (tuple chuỗi; trả hằng `()` khi không có): `"caught"` (bóng đang rơi chạm `paddle` → chuyển
sang flying), `"paddle"` (bóng đang bay bật lại ở thanh), `"wall"`, `"ceiling"`, `"boss"` (trúng boss: play.py gây sát thương),
`"lost"` (bóng ĐANG BAY lọt qua đáy → `alive=False`, `fell=True`: play.py trừ 1 mạng). Bóng chưa hứng mà rơi khỏi đáy:
`alive=False`, `fell=True`, KHÔNG có sự kiện (không phạt).
Vật lý bóng:
- `falling`: rơi bằng `items.step_fall` (không vx; `time_scale` và `magnet_x` áp dụng như item rơi); hứng bằng
  `paddle.colliderect(self.rect)`.
- `flying`: vận tốc độ lớn CỐ ĐỊNH `BOSS_BALL_SPEED` (không trọng lực, `time_scale` KHÔNG áp dụng). Khi chạm thanh (bóng đi
  xuống, tâm bóng nằm trên đường giữa thanh): `offset = clamp((x - paddle.centerx) / (paddle.w/2), -1, 1)`,
  góc `a = offset * radians(BOSS_BALL_MAX_ANGLE)` tính từ phương thẳng đứng, `vel = speed * (sin a, -cos a)`, đặt bóng ngay
  trên mặt thanh. Bật tường trái/phải và trần (y=radius) có phản xạ; sau mỗi lần phản xạ ép `|vy| >= BOSS_BALL_MIN_VY*speed`
  rồi chuẩn hoá lại về `speed`. Trúng `boss_rect` (nếu không phải None): đẩy bóng ra ngoài theo trục xuyên ít nhất, đảo
  thành phần tương ứng, `hit_cd = 0.1 s` (trong thời gian này không tính trúng lần nữa), trả `"boss"`.
- Chia nhỏ bước nội bộ (<= 1/120 s) để không xuyên vật khi `dt` lớn.
- Hàm tự do: `launch_velocity(ball_x: float, paddle: pg.Rect) -> tuple[float, float]` (dùng cho bot) và
  `ball_catch_rect(paddle: pg.Rect) -> pg.Rect` nếu B cần.

```python
class Beam:                         # tia của người chơi; trúng/trượt được phân giải NGAY khi tạo (hitscan)
    def __init__(self, x: float, y_from: float, boss_rect: pg.Rect | None)
    x: float; y_from: float; y_to: float     # y_to = boss_rect.bottom nếu trúng, ngược lại 0 (tia bay ra khỏi màn hình)
    width: float = config.BOSS_BEAM_WIDTH
    life: float = config.BOSS_BEAM_LIFE; age: float; alive: bool
    hit: bool                        # True nếu boss_rect không None và boss_rect.left - width/2 <= x <= boss_rect.right + width/2
    @property progress -> float      # age/life, 0..1
    def update(self, dt: float) -> None   # alive=False khi age >= life
```
(Beam KHÔNG tự vẽ: D vẽ qua `render.boss_draw.draw_beam`.)

Test (`tests/test_boss_items.py`): Projectile bay thẳng/rời màn hình/`hits` chính xác (biên, góc hình chữ nhật);
EnergyItem rơi đúng tốc độ, bị nam châm kéo; HelperBall: rơi → `"caught"` → bay lên với góc đúng theo chỗ chạm (trái/giữa/phải),
tốc độ giữ nguyên sau 1.000 bước, bật tường/trần, không bị kẹt ngang, trúng boss gây đúng 1 sự kiện mỗi lần (hit_cd), lọt
đáy → `"lost"` đúng 1 lần, bóng chưa hứng rơi khỏi đáy → không sự kiện; `dt` lớn (1/20) không xuyên thanh/boss; Beam hit/miss ở
biên; mọi `draw` chạy được ở 540/960/1960 rộng, có và không có `assets`.

## 5. Agent C — giao diện (`ui/hud.py`, `ui/boss_ui.py`, `scenes/boss_reward.py`, `howto.py`, lang)

### 5.1 HUD
`Hud.draw(surf, state)`: `state` giữ nguyên khoá cũ, thêm khoá `"boss"` (None khi không có boss). Khi khác None, `state["boss"]`:
```python
{"name_key": "boss.kind.0.name", "number": 1, "kind": 0,
 "state": "intro" | "fight" | "enrage" | "victory",
 "hp_frac": 0..1, "phase": 1..3, "time_left": float, "enraged": bool,
 "colors": ("orange", "yellow"),          # khoá PALETTE
 "energy": int, "energy_need": 3, "energy_cap": 6, "balls": int,
 "player_x": float, "boss_x": float, "boss_half_w": float}
```
Khi có boss, HUD: giữ điểm (trái trên) và hearts (phải trên); ẨN thanh cấp + dòng kỷ lục + huy hiệu combo; vẽ dòng
"BOSS n · TÊN" bằng màu boss ở chỗ nhãn cấp, đồng hồ đếm lùi `m:ss` (hoặc "NỔI GIẬN!" nhấp nháy khi enraged) bên phải nhãn,
thanh máu boss ngang cả bề rộng (cách mép MARGIN, cao ~14 px, glow, hiển thị mượt tới `hp_frac` bằng `approach`, có 2 vạch
66%/33% đánh dấu giai đoạn, nháy trắng ngắn khi máu giảm). KHÔNG che vùng boss (y từ ~170 trở xuống; thân boss ở y=250±75).
Thanh năng lượng ở góc dưới-trái (`energy` ô tròn nhỏ tới `energy_cap`, ô thứ `energy_need` có vạch chia; khi
`energy >= energy_need` sáng + nhấp nháy). Khi `energy >= energy_need`: chữ `t("boss.beam_ready")` nhấp nháy phía trên thanh hứng
(dùng `player_x`, y ≈ `config.PLAYER_Y - 80`) và đường ngắm mờ từ thanh hứng lên đáy boss (`config.BOSS_Y + 80`), SÁNG LÊN khi
`|player_x - boss_x| <= boss_half_w` (đang trúng). Power-up timer giữ nguyên vị trí. Mọi chữ cache như HUD cũ, không cấp phát
Surface lớn mỗi khung.

### 5.2 `ui/boss_ui.py` (hàm vẽ thuần, `k` ∈ [0,1] là tiến độ thời gian; hàm tự lo vào/ra, ease)
```python
def draw_boss_banner(surf, assets, boss: dict, k: float) -> None     # intro: "CẢNH BÁO!" nhấp nháy đỏ, rồi "BOSS n" + tên boss lớn màu boss
def draw_victory_banner(surf, assets, bonus: int, k: float) -> None  # "BOSS BỊ HẠ!" + "THƯỞNG +bonus"
def draw_callout(surf, assets, text: str, color, k: float, cy: int = None) -> None   # dòng ngắn giữa-trên: "GIAI ĐOẠN 2", "NỔI GIẬN!", "MẤT BÓNG!"
```
### 5.3 `scenes/boss_reward.py` — `class BossRewardScene(Scene)`, `is_overlay = True`
- `on_enter(self, options: list, number: int, bonus: int, owned: dict, on_pick, **kw)`: `options` = 3 khoá trong
  `config.BOSS_UPGRADES`, `owned` = {khoá: số lần đã nhận}, `on_pick(key: str)` gọi MỘT lần khi chọn xong, sau đó scene tự
  `self.app.scenes.pop()`.
- 3 thẻ neon cạnh nhau (xếp dọc nếu `LOGICAL_W < 700`): icon (dùng `assets.icon`: wide→"wide", magnet→"magnet", life→"heart",
  power→"star", speed→ hình mũi tên/chevron tự vẽ), tên `t("upgrade.<key>.name")`, mô tả `t("upgrade.<key>.desc")`, "Đã có: n" nếu n>0.
- Điều khiển: A/D hoặc ←/→ đổi thẻ, Enter/Space chọn, phím 1/2/3 chọn nhanh, chuột hover/click. Esc/P KHÔNG làm gì (không bỏ qua
  được). Chặn input 0.6 s đầu (người chơi đang mash Space để bắn tia). Âm `ui_move`/`ui_select`. Autoplay (`app.autoplay`):
  tự chọn thẻ giữa sau 1.0 s. Tiêu đề `boss.reward.title`, phụ đề `boss.reward.sub`, dòng `boss.reward.lives`, hint `boss.reward.hint`.
- `on_resize(old_w)` dựng lại layout; vẽ trên nền play (overlay) + `dim_backdrop`.
- Hộp lỗi: `on_pick` ném lỗi → bắt, log, vẫn `pop()`.
### 5.4 `howto.py`
Thêm một hàng điều khiển `Space` (`howto.fire`) và một dòng mẹo `howto.boss_tip` mà không làm vỡ bố cục ở 540 rộng.
### 5.5 Chuỗi i18n (cả `vi.json` và `en.json`, CÙNG bộ khoá, đủ dấu tiếng Việt; thêm đúng các khoá sau)
| Khoá | vi | en |
|---|---|---|
| `boss.warning` | CẢNH BÁO! | WARNING! |
| `boss.number` | BOSS {n} | BOSS {n} |
| `boss.kind.0.name` | LÕI HEX | HEX CORE |
| `boss.kind.1.name` | LĂNG KÍNH | PRISM |
| `boss.kind.2.name` | MẮT HƯ KHÔNG | VOID EYE |
| `boss.defeated` | BOSS BỊ HẠ! | BOSS DEFEATED! |
| `boss.bonus` | THƯỞNG +{points} | BONUS +{points} |
| `boss.phase` | GIAI ĐOẠN {n} | PHASE {n} |
| `boss.enraged` | NỔI GIẬN! | ENRAGED! |
| `boss.beam_ready` | SPACE: BẮN TIA! | SPACE: FIRE BEAM! |
| `boss.energy` | NĂNG LƯỢNG | ENERGY |
| `boss.ball_lost` | MẤT BÓNG! | BALL LOST! |
| `boss.reward.title` | CHỌN NÂNG CẤP | CHOOSE AN UPGRADE |
| `boss.reward.sub` | Có hiệu lực đến hết ván | Lasts until the end of the run |
| `boss.reward.lives` | Mạng đã được hồi đầy | Lives fully restored |
| `boss.reward.owned` | Đã có: {n} | Owned: {n} |
| `boss.reward.hint` | A/D: chọn  ·  Enter: nhận  ·  1/2/3: chọn nhanh | A/D: choose  ·  Enter: take  ·  1/2/3: quick pick |
| `upgrade.wide.name` | Thanh rộng | Wide paddle |
| `upgrade.wide.desc` | Thanh hứng rộng thêm 20% | Paddle 20% wider |
| `upgrade.magnet.name` | Nam châm xa | Long magnet |
| `upgrade.magnet.desc` | Tầm hút nam châm +40% | Magnet range +40% |
| `upgrade.life.name` | Thêm mạng | Extra life |
| `upgrade.life.desc` | +1 mạng tối đa và hồi 1 mạng | +1 max life and heal 1 |
| `upgrade.power.name` | Hoả lực | Firepower |
| `upgrade.power.desc` | Bóng và tia mạnh thêm 25% | Ball and beam 25% stronger |
| `upgrade.speed.name` | Thanh nhanh | Quick paddle |
| `upgrade.speed.desc` | Thanh hứng chạy nhanh hơn 10% | Paddle 10% faster |
| `howto.fire` | Bắn tia (khi đủ năng lượng) | Fire beam (when charged) |
| `howto.boss_tip` | Cứ 10 cấp có một boss: hứng bóng nảy để đánh, gom 3 năng lượng rồi nhấn Space để bắn tia! | Every 10 levels a boss appears: catch the bouncing ball to hit it, collect 3 energy and press Space to fire the beam! |

Test (`tests/test_boss_ui.py`): bộ khoá vi == en; HUD vẽ được mọi trạng thái boss ở 540/960/1960 rộng (cả `boss=None`); banner với
k = 0, 0.5, 1 và ngoài khoảng; màn thưởng: chọn bằng phím/chuột, chặn input đầu, `on_pick` gọi đúng 1 lần, `pop` được yêu cầu,
`on_resize`.

## 6. Agent D — `render/boss_draw.py` + âm thanh

```python
def draw_boss(surf, boss, t: float, assets=None) -> None
def draw_sweep(surf, sweep, boss_bottom: float, t: float) -> None
def draw_beam(surf, beam, t: float) -> None
def boss_hit_fx(particles, pos, color, heavy: bool = False) -> None      # tia-trúng = heavy, bóng-trúng = nhẹ
def boss_death_fx(particles, boss, rng) -> None                          # gọi ~mỗi 0.08 s trong victory; nổ rải trên thân boss
def prewarm_colors() -> list                                              # màu để particles.prewarm() chuẩn bị trước
```
- `boss` là đối tượng `Boss` của A (đọc các trường mục 3: `kind, colors, pos, half_w, half_h, hp_frac, phase, hit_flash, charge,
  enraged, anim_t, death_t`); `sweep` là `Sweep` của A (`x_from/x_to/width/phase/zone/beam_x/k_warn/k_fire`); `beam` là `Beam` của
  B (`x, y_from, y_to, width, hit, progress`). Lúc làm song song các file kia có thể chưa có: test bằng `types.SimpleNamespace`
  với đúng các trường đó; điều phối viên sẽ chạy thật khi ghép.
- 3 boss neon trừu tượng, mỗi con nhận ra ngay từ hình dáng: kiểu 0 "Lõi Hex" (lục giác lớn nhiều lớp quay ngược chiều, lõi
  sáng, cam/vàng), kiểu 1 "Lăng Kính" (cụm thoi/tam giác xếp thành lăng kính, magenta/cyan, các mảnh dao động), kiểu 2 "Mắt Hư
  Không" (vòng tròn đồng tâm + con ngươi đi theo `anim_t`, tím/xanh lá, mí mắt nháy). Kích thước tương ứng `half_w/half_h`.
  Hiệu ứng: đổi tông khi `phase` 2/3 (thêm vòng/viền), `enraged` đỏ rực + rung nhẹ, `hit_flash` loé trắng, `charge` (0..1) vòng
  năng lượng co vào + glow tăng, `death_t` rạn nứt/phình/mờ dần. Glow dùng `entities.items.glow_*_at`/`render.neon` (cache,
  lượng tử hoá kích thước), KHÔNG tạo Surface lớn mỗi khung, mọi `pg.font` qua `assets`.
- `draw_sweep`: pha `warn`: dải `zone` từ `boss_bottom` xuống đáy màn hình, vạch sọc chéo đỏ-cam nhấp nháy nhanh dần, viền sáng,
  dấu "!" lớn ở đầu dải; pha `fire`: tia trắng-đỏ rộng `width` chạy từ `x_from` tới `x_to` kèm vầng sáng, dải cảnh báo mờ dần.
- `draw_beam`: tia dọc `x` từ `y_from` lên `y_to`, rộng `width`, trắng lõi + vầng cyan/vàng, co nhỏ và mờ theo `progress`, thêm
  vòng loé ở điểm trúng (`y_to`) nếu `hit`.
- Âm thanh: viết thêm 6 công thức vào `tools/synth_sfx.py` (thêm tên vào `SFX_NAMES` của file đó) và chạy để sinh file WAV vào
  `assets/sound/`: `boss_intro` (drone trầm dâng cao + còi, ~2.2 s), `boss_hit` (cú va kim loại ngắn ~0.15 s, hơi nhỏ vì phát
  đều), `beam_charge` (tiếng rít dâng ~0.5 s, báo "đã đủ năng lượng"), `beam_fire` (tia laser quét xuống ~0.45 s),
  `boss_defeat` (nổ + rền + arpeggio đi xuống ~2.4 s), `warning` (hai tiếng bíp báo động ~0.7 s). Không tải gì từ internet.
  `config.SFX_NAMES` đã có sẵn 6 tên. Chuẩn hoá đỉnh như các âm khác. Kiểm: 6 file tồn tại, không im lặng, không quá to (đỉnh
  ≈ -1 dBFS), độ dài hợp lý.
- Test (`tests/test_boss_draw.py`): vẽ mọi kiểu boss x mọi phase x các trạng thái (hit_flash, charge, enraged, death_t) ở 540/960/
  1960 rộng không lỗi và có pixel được vẽ trong vùng boss; `draw_sweep` ở warn/fire; `draw_beam` hit/miss; fx không lỗi với
  `ParticleSystem`; 6 wav tồn tại, đọc được bằng `pg.mixer.Sound` (hoặc module `wave`).

## 7. Điều phối viên (play.py) — để các agent hiểu cách mình được gọi

- Trạng thái trận nằm ở `PlayScene.boss` (một `BossController`), `PlayScene.boss_mode` (bool), danh sách `projectiles`,
  `helpers` (EnergyItem + HelperBall), `beams`. Cờ dòng lệnh `--start-boss N` (đã có trong `app.py`: `app.start_boss`) là chế độ
  luyện tập: mỗi ván bắt đầu thẳng ở boss N, không ghi kỷ lục.
- Bot autoplay trong trận boss: bám item hỗ trợ/bóng, né đạn và vùng quét, đứng dưới boss khi đủ năng lượng rồi bắn.
- `ARCHITECTURE.md` và `tools/smoke_test.py` do điều phối viên cập nhật.

## 8. Báo cáo của agent (kết quả cuối, tiếng Việt, ngắn)

1. Dòng đầu: `XONG` hoặc `THIẾU: <mục> — <lý do>`.
2. File đã tạo/sửa (đường dẫn). 3. Kết quả chạy test của mình và `tests.test_gameplay` (số PASS).
4. Chỗ lệch hoặc bổ sung so với hợp đồng này (thêm trường/hàm nào bên trong file của mình). 5. Rủi ro điều phối viên cần biết khi ghép.
