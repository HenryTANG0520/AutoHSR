# AutoHSR resource attribution

AutoHSR is distributed under the GNU General Public License version 3. The full
license is in [../LICENSE](../LICENSE). The resources below retain their upstream
license and contributor attribution. They are used as UI recognition references
and, where stated below, desktop UI materials.
Honkai: Star Rail artwork and names belong to their respective rights holders;
the upstream software licenses do not grant ownership of those game assets.

## 2026-10-29 指南底纹

更新既有指南的`ui/paper-pattern.png`：仍取自已登记4.6每日实训原图（SHA-256 `6ba21f7ad3417d8bebb0224849221b59b674030e1e964c49e34f676176d28e11`），范围扩为`[236,892,1694,964]`，以连续暖色透明度提取静态底边星图，清除倒计时与挂饰遮挡区，不补全未知像素。处理与输出哈希见`ui/sources.json`；游戏美术权利归原权利人，不纳入代码GPL许可。

## 2026-10-29 设置页布局参考

设置行的左右分区、细分隔线和下拉箭头参考 [GameWith 发布的游戏「其他」设置截图](https://img.gamewith.jp/img/original_ff63c82b79444430e3f32cae5029b920.png)，所在[原文](https://gamewith.jp/houkaistarrail/article/show/447025)。本次读取的原始响应为1200×630 JPEG，SHA-256为`8e6c0f13f458454da06a14570c37e8decec5c764eaa543f288da1846b0894d0f`；原截图游戏版本未标明，不能视作当前客户端逐像素验收。图片只用于本地视觉对照，未作为分发素材；界面以代码绘制，沿用下文已登记的字体。未复制博主的标记箭头、教程或截图像素，也未取得该图片的再分发许可。

## Honkai Star Rail - One Dragon

Source: [OneDragon-Anything/StarRailOneDragon](https://github.com/OneDragon-Anything/StarRailOneDragon)
and its contributors. License: GPL-3.0; the unmodified upstream license is saved
as [upstream/OneDragon-LICENSE](upstream/OneDragon-LICENSE).

Retrieved 2026-10-11 from `main`, whose head at retrieval was
`1ffd7e082c38bcdb559d2c0a194191ae21514ef0`. The following files are unmodified
copies of upstream `raw.png` assets. Their coordinates and scale use the upstream
1920×1080 game-client baseline.

| AutoHSR file in `templates/` | Upstream file under `assets/template/` |
| --- | --- |
| `daily_reward.png` | [phone_menu/training_reward_gift/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/training_reward_gift/raw.png) |
| `daily_completed.png` | [phone_menu/training_reward_completed/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/training_reward_completed/raw.png) |
| `daily_tab.png` | [guide/daily_training/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/guide/daily_training/raw.png) |
| `survival_tab.png` | [guide/survival_index/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/guide/survival_index/raw.png) |
| `world_character.png` | [normal_world/ui_icon_01/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/normal_world/ui_icon_01/raw.png) |
| `count_minus.png` | [challenge_mission/battle_times_minus/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/challenge_mission/battle_times_minus/raw.png) |
| `phone_guide.png` | [phone_menu/phone_menu_item_11_interastral_guide/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/phone_menu_item_11_interastral_guide/raw.png) |
| `phone_mail.png` | [phone_menu/phone_menu_item_24_email/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/phone_menu_item_24_email/raw.png) |
| `phone_assignments.png` | [phone_menu/phone_menu_item_03_assignments/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/phone_menu_item_03_assignments/raw.png) |
| `phone_battlepass.png` | [phone_menu/phone_menu_item_08_nameless_honor/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/phone_menu_item_08_nameless_honor/raw.png) |

`templates/survival_tab_base.png` is a 2026-10-24 derivative of the above
`survival_tab.png`, cropped at `(5, 30, 65, 66)` (right/bottom exclusive).
It excludes the upper notification badge while retaining the original 1920px
baseline. Source hash and crop are recorded in `survival_tab_base.json`.

## StarRailCopilot

Source: [LmeSzinc/StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot)
and its contributors. License: GPL-3.0; the unmodified upstream license is saved
as [upstream/StarRailCopilot-LICENSE](upstream/StarRailCopilot-LICENSE).

Retrieved 2026-10-11 from `master`, whose head at retrieval was
`e2c7f0894fdea737805becbe02809ff01f47068e`. Original source PNGs and the coordinate
declarations are retained under `upstream/`. The following derivatives were
modified by AutoHSR on 2026-10-11: crop the declared `area` from the 1280×720
source, then resize by 1.5 using Pillow bicubic interpolation to the 1920×1080
baseline. Rectangle bounds are `(left, top, right, bottom)`, with right/bottom
exclusive; output dimensions are rounded to integers.

| AutoHSR file in `templates/` | Original source | Crop area | Result |
| --- | --- | --- | --- |
| `auto_anchor.png` | [COMBAT_AUTO.png](https://github.com/LmeSzinc/StarRailCopilot/blob/e2c7f0894fdea737805becbe02809ff01f47068e/assets/share/combat/state/COMBAT_AUTO.png) | `(1113, 22, 1183, 58)` | 105×54 |
| `battle_pause.png` | [COMBAT_PAUSE.png](https://github.com/LmeSzinc/StarRailCopilot/blob/e2c7f0894fdea737805becbe02809ff01f47068e/assets/share/combat/state/COMBAT_PAUSE.png) | `(1218, 27, 1245, 53)` | 40×39 |

Crop declarations are from
[tasks/combat/assets/assets_combat_state.py](https://github.com/LmeSzinc/StarRailCopilot/blob/e2c7f0894fdea737805becbe02809ff01f47068e/tasks/combat/assets/assets_combat_state.py),
saved locally as [upstream/assets_combat_state.py](upstream/assets_combat_state.py).
The full 1280×720 source canvases are kept for reproduction and are not used as
matching templates. The automatic-battle template locates the control; the
workflow checks its visible border independently before deciding its state.

## OCR and design reference

`templates/daily_activity_badge.png` was sampled locally on 2026-10-11
from the game's daily training page. The captured 3840×2160 image was resized
to 1920×1080, then cropped at `(302, 268, 353, 326)`. It includes only the
activity emblem and no account identifier. It is used to locate the current
activity value independently of the milestone labels. Game artwork belongs
to its respective rights holder.

OCR models can be read from the user's existing BetterGI installation. The
PaddleOCR models there originate from
[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), converted using
[Paddle2ONNX](https://github.com/PaddlePaddle/Paddle2ONNX); both upstream projects
use Apache-2.0. Those external model files are not bundled here. Preserve their
upstream notices when redistributing models.

[BetterGI](https://github.com/babalae/better-genshin-impact) is the design
reference for the screenshot, recognition, and simulated-input architecture.
No BetterGI game-specific templates or trained game-specific models are copied
into this resource directory.

The foreground log layout introduced on 2026-10-25 also references BetterGI's
[`MaskWindowConfig.cs`](https://github.com/babalae/better-genshin-impact/blob/4d42b8bac7f7665254593f70b97b19a9e09b8586/BetterGenshinImpact/Core/Config/MaskWindowConfig.cs)
and [`MaskWindow.xaml`](https://github.com/babalae/better-genshin-impact/blob/4d42b8bac7f7665254593f70b97b19a9e09b8586/BetterGenshinImpact/View/MaskWindow.xaml):
transparent lower-left status/log regions at the 1920×1080 baseline, timestamps,
severity labels, light gray text and a dark shadow. Rendering and game-capture
exclusion are implemented locally in `autohsr/overlay_native.py`.
The display-event queue and acceptance harness were adapted from Henry's
AutoZZZ project, also GPL-3.0-only; no BetterGI executable, artwork or model is
bundled for this display.

`templates/daily_synthesis_snack.png` was cropped on 2026-10-25 from the user's
clean snack-icon screenshot at `(25, 28, 196, 202)` and resized to 86×87 for recipe
selection. It excludes inventory counts and account identifiers. The source
hash and transform are in `daily_synthesis_snack.json`; game artwork belongs
to its rights holder. Recipe text, single-item quantity, ingredient balances,
daily task and post-craft inventory are checked independently of this image.

## Differential Universe local samples

The following recognition templates were cropped locally on 2026-10-18 from
the Simplified Chinese Star Rail client during Differential Universe development:
`templates/du_difficulty_i.png`, `templates/du_enemy_target.png`,
`templates/du_field_enemy.png`, and `templates/du_field_enemy_2.png` through
`templates/du_field_enemy_5.png`. They contain the difficulty-I control, an
enemy target indicator, or visible enemy artwork at sampled poses and views.
Original gameplay evidence remains in the ignored local `runs/` directory;
these recognition crops do not include account identifiers. Game artwork and
interface elements belong to their respective rights holders. These are local
gameplay samples, not copies of the upstream template libraries listed above.
Their presence does not establish successful combat entry or a completed run;
development is paused pending the user's guide.

## Daily dungeon catalogue and local recognition samples

`dungeons.json` records mission labels and map labels observed in the Simplified
Chinese 4.6.0 client on 2026-10-20. The 104 entries were bound to visible entry
buttons in locally captured Survival Index pages, with native-resolution OCR
and a small set of exact, sample-backed OCR aliases. No upstream mission data
file was copied. Account identifiers and player nicknames are not included.

`autohsr/tests/fixtures/dungeons/guide_rows.json` preserves list-region OCR and
source-image hashes for 63 local observations. `cavern_refill_off.png` contains
only the observed refill-switch region from a local cavern challenge page.
Original screenshots remain in ignored local `runs/` directories. Game labels
and interface pixels belong to their respective rights holders. Catalogue
coverage is separate from actual combat validation recorded in `VALIDATION.md`.

`planar_support_badge.png` and `planar_friend_slot4.png` are tiny native-resolution
crops of the support badge and numbered selected-slot flag from the same local
client. Their source hash and crop rectangles are in `planar_support.json`;
these crops contain no account identifiers or player nicknames.

`templates/planar_attack_mouse.png` is a local 2026-10-20 crop of the mouse-left
hint beside the field normal-attack control, resized to the 1920px template
baseline. Its JSON sidecar records the source hash and rectangle. It is used
only after this run has started planar extraction and reserved its cost; it
does not enable general Differential Universe movement or gameplay.

`du_guide_tab.png` is a crop of the 4.6 guide's 旷宇纷争 tab from the local
2026-10-20 catalogue capture. `du_attack_mouse.png` derives from the existing
mouse-hint crop with an alpha mask excluding the changing 3-D background;
its JSON sidecar records that derivation. `autohsr/tests/fixtures/du_runtime/`
contains four tiny mouse-hint crops and source hashes, without account data.

`du_random_gate.png` contains the eyes and nose of the pink 随意门 observed
in the same local client. Its source hash and crop rectangle are recorded in
the adjacent JSON. The `du_runtime/gate_*.png` fixtures preserve distant and
near views plus a neon-building negative, resized and blanked outside their
field regions to exclude account identifiers. Their provenance is recorded
in `gate_samples.json`. These landmarks authorize bounded navigation only;
interaction still requires the live OCR 随意门 prompt.

`du_battle_pause.png` and `du_auto_anchor.png` are tightly bounded control
glyphs from the local 4.6 Differential Universe battle. Their sidecars record
source hashes and rectangles. `du_runtime/battle_controls_*.png` contains only
the corresponding toolbar region; `battle_controls.json` records provenance.
The grayscale off-state test is a derived color-classification test, not a
claim that an actual off-state was captured.

`du_difficulty_i_idle.png` isolates the difficulty I glyph from a local setup
page. `du_event_next.png` is the small gold dialogue continuation arrow
from the event page. Their JSON sidecars record source hashes and crop rectangles.
`du_runtime/event_next_*.png` preserves normal and hover states; its JSON manifest
records provenance. Matching excludes the cursor-covered bottom-right quadrant. `du_runtime/header_*.png` contains only the top-left field HUD
strip or the corresponding reward-page region; `field_headers.json` records
provenance. These crops contain no account identifiers or player names.


`du_station_combat.png` is the battle station's sword glyph from the local
4.6 client; its JSON sidecar records the source hash and crop rectangle.
`du_runtime/attack_ring_*.png` keeps only the world region needed to distinguish
an attack-range reticle from open gate eyes and the character's floating emoji.
All HUD/account regions are blanked; `attack_rings.json` records source hashes.

`models/du_target.onnx` is a locally trained YOLO11n derivative from the official
Ultralytics pretrained asset. It is distributed under AGPL-3.0 with its license,
hash, evaluation limits and training provenance in `models/`. Training imagery
remains local under ignored `runs/`; training images have identifiers masked.

The 2026-10-24 gate fit retains the preceding split and negative examples and
adds three reviewed night exits with avatar occlusion plus 36 brightness
variants, all in training. The three masked `du_runtime/night_exit_*.png`
fixtures retain source hashes, reviewed boxes, and non-identifier OCR. They
are training replays, not held-out accuracy or independent-run evidence.
The runtime threshold remains 0.55; metadata records the selected checkpoint
and unchanged held-out CPU evaluation. The model remains AGPL-3.0.

`du_interaction_f.png`, `du_card_crest.png` and `du_boss_head.png` are local
2026-10-21 crops of the F interaction hint, world event-card ornament, and visible
boss upper body. Their JSON sidecars identify source hashes and crop rectangles.
They supply stop signals or bearings; they never establish a cleared room or
authorize an attack without its actual range reticle. `visual_targets.json`
records the masked card, interaction and detector regression fixtures.

`du_runtime/rewards_*.png` are local 2026-10-21 reward-page regression frames,
scaled with the bottom account identifier strip blanked. `reward_pages.json`
records source hashes and OCR metadata. The unearned-avatar negative fixture
ensures future red artwork is not treated as a notification or a received reward.
`du_cassette_zero.png` and `du_runtime/moon_balance_zero.png` preserve only the
numeric cassette-balance region; their sidecars record crop provenance. The zero
glyph is a fallback when OCR omits zero and never authorizes a paid unlock.

`du_runtime/blessing_missing_title.png` is a native-resolution title-strip crop
for a two-character blessing missed by full-screen OCR. Its JSON sidecar records
the source hash and crop. No account or player identifiers are included.

`du_runtime/card_distant.png` is a masked 960px world-card frame from the local
2026-10-21 client. Its provenance sidecar records the source hash; the sample
regresses a distant 70px-high card excluded by the former strict size threshold.

`du_runtime/card_avatar_occlusion.png` preserves the partial purple card frame,
pale face and nearby pink gate used to distinguish the card from the gate while
it overlaps the avatar. Its provenance sidecar records the local source hash;
account and player-name regions are masked.

`du_runtime/gate_sleep_far.png` and `gate_sleep_near.png` are masked local
2026-10-21 frames. `sleep_gate_states.json` records source hashes. They regress
the closed-eye/front-versus-back ambiguity at far and near distances; far
anti-aliased eyelids require native-resolution inspection before back matching.

`du_runtime/card_cyan_frame.png` is the masked local abnormal-event card
「归来的岁阳」 with its bright cyan frame, pale eye and purple ornament.
Its sidecar records the source hash. This card does not have dark frame rails.

`du_runtime/cards_reward_gold.png` is a masked local reward-region scene with a
warm purple/gold card, a gold card and a locked pink gate. The sidecar records
the source hash and positive centers; the pink gate is a negative target.

`models/du_cards.onnx` is a locally trained YOLO11n Card-only derivative, under
the same included AGPL-3.0 terms. `models/du_cards.json` and the model README record
its hash, training provenance and limited native evaluation. Its raw training
captures and generated scenes remain under ignored runs/ with identifiers masked.
`du_runtime/cards_poster_negative.png` is a masked held-out facade-view regression;
its sidecar records provenance. The learned card model must reject that artwork.

`du_runtime/attack_ring_5.png` through `attack_ring_8.png` are masked, resized
local 2026-10-21 field captures. Their source hashes are in `attack_rings.json`.
They distinguish a real attack glow from blonde hair and orange shop numerals.
`attack_ring_9.png` and `attack_ring_10.png` also reject sleeping-door gold trim.

`templates/du_aurumaton_roof.png` is an observed boss-roof crop used only for a
coarse approach bearing. Its sidecar and `du_runtime/boss_aurumaton.json` record
source hashes. Two masked field frames test the bearing at different headings;
the roof never establishes attack range.

`templates/du_aurumaton_side.png` adds an observed side chest crop with a source
hash in its sidecar. `du_runtime/boss_aurumaton_2.png` is a masked native frame.
`models/du_enemies.onnx` is a locally trained, Enemy-only YOLO11n derivative
under the included AGPL-3.0 terms. Its sidecar records the small local dataset,
CPU checkpoint selection, missed occlusion sample and scope limitation.

`du_runtime/preset_list.png`, `preset_enabled.png` and `periodic_setup.png`
are masked, resized local 2026-10-21 client captures. Their JSON sidecars retain
OCR boxes and source hashes to verify named preset activation and mode isolation.

The 2026-10-22 `du_enemies.onnx` update adds the observed Senior Staff: Team
Leader family, retaining Aurumaton training examples. Its sidecar records the
combined fit and strict CPU evaluation. `du_runtime/boss_ipc_front.png`,
`boss_ipc_clear.png` and `boss_ipc_occluded.png` are masked local field frames;
their sidecars contain reviewed boxes and source hashes. The included AGPL-3.0
terms also apply to the updated Ultralytics derivative.

`du_runtime/blessing_discard.png` is a masked 2026-10-22 native one-star
blessing trade page. The sidecar preserves its source hash and OCR boxes.

The further 2026-10-22 enemy model update adds the observed 正阳狮鹫 appearance.
`du_runtime/boss_griffin_clear.png`, `boss_griffin_center.png` and
`boss_griffin_occluded.png` are masked local field captures. Their sidecars
preserve source hashes and reviewed bounding boxes. Training and calibration
remain local; included AGPL-3.0 terms apply to this derivative.

`du_runtime/attack_ring_11.png` preserves a genuine, dimly filled range ring
near the left edge after a party switch. `attack_rings.json` records provenance.
`du_runtime/enemy_avatar_negative.png` preserves a central avatar in front of a
wall; the sidecar records its source hash. Identifiers are masked in both.

`du_runtime/gate_rest_distant.png` is a masked local rest-area capture where
the learned door score dips below its normal threshold. Its source hash is in
the sidecar; a spatially matching eye feature corroborates the lower-score box.

The fourth enemy model fit adds 金血忆灵·裁定 and retains earlier families.
`du_runtime/boss_arbiter_clear.png`, `boss_arbiter_center.png` and
`boss_arbiter_occluded.png` are masked local captures with reviewed-box sidecars
and source hashes. The progress-banner sample checks bearing only; its imperfect
full-body box remains a strict evaluation miss. Included AGPL-3.0 terms apply.

The fifth enemy fit adds 乐变化天人. Masked local `du_runtime/enemy_celestial_clear.png`,
`enemy_celestial_center.png` and `enemy_celestial_spawn.png` have reviewed-box
sidecars with source hashes. The bright spawn frame remains a known detector
miss; it is not counted as a successful localization. AGPL-3.0 terms apply.

The sixth enemy fit adds 承露天人. Masked local `du_runtime/enemy_dew_clear.png`,
`enemy_dew_center.png` and `enemy_dew_front.png` have reviewed-box sidecars and
source hashes. `models/du_enemies_fallback.onnx` retains the preceding five-
appearance fit solely for missing primary bearings. Both model sidecars retain
their hashes, provenance, limitations and included AGPL-3.0 terms.

`du_runtime/gate_awake_ornament.png` is a masked local capture of a cleared
boss room, with an awake exit and distant scenery that the enemy model can
misidentify. Its sidecar records the source hash. It tests exit-state priority.

`du_runtime/attack_ring_mouse_animation.png` is a masked local field capture
with a genuine attack ring and enemy information bar while the mouse-hint
template is changing. The sidecar preserves source hash and masked OCR tokens.

`du_runtime/attack_ring_12.png` through `attack_ring_14.png` preserve three
masked native frames of the 乐变化天人 range ring with weak circle-edge votes.
Their source hashes are recorded in `attack_rings.json`.

`du_runtime/blessing_title_variant_0.png` and `blessing_title_variant_1.png`
are masked local captures of unchanged blessing cards during reversible previews.
They exercise a two-character title whose first character varies in OCR.

`du_runtime/gallery_home.png`, `gallery_category.png` and `gallery_milestones.png`
are masked local captures of earned gallery reward navigation. Their sidecars
retain source hashes and OCR tokens.

`du_runtime/companion_ring_candidate.png` is a masked native entrance frame.
Its companion's expression meets the low-level circle appearance checks but
lacks an enemy information bar, so it must not suppress the forward approach.
Its sidecar records the source hash and OCR tokens.

The seventh enemy fit adds the observed winged elite 波涛夫人, subsequently
identified from the native enemy bar. `du_runtime/enemy_winged_front.png`, `enemy_winged_center.png`,
`enemy_winged_side.png` and `enemy_winged_hud.png` are masked local captures with
reviewed boxes and source hashes. Nearby samples only establish local calibration;
the included AGPL-3.0 terms apply to the model.

`du_runtime/world_card_title_130.png` and `world_card_title_131.png` are masked
native reward-room entrance frames. Their OCR sidecars retain source hashes.
They distinguish the fixed 奖励 progress header from the world-card title
商店街一番战, which also supplies a coarse approach bearing.

`templates/du_event_option_star.png` is a local native crop of the selectable
event-row star at a 1920x1080 baseline. Its sidecar records the source hash and
crop. `du_runtime/event_star_choices.png` is a masked native 神秘链接 choice
screen with three stars and OCR tokens; its sidecar records the source hash.

`du_runtime/attack_ring_15.png` through `attack_ring_17.png` are masked native
波涛夫人 frames where the attack ring lies inside a larger bright eye rim.
Their source hashes and expected presence are recorded in `attack_rings.json`.

`du_runtime/beacon_close_variant.png` is a masked native deployed-beacon
overlay where OCR reads 白 as 日 in the bottom close hint. Its sidecar
retains the source hash and OCR tokens for the observed regression.

`du_runtime/station_transform.png` is a masked native station-card target
selector for the observed combat-to-event/anomaly transformation. Its sidecar
records the source hash and OCR tokens.

`templates/du_range_ring.png` is a local crop of the native hollow attack
marker, represented as red excess for shape matching. Its sidecar records the
source hash, baseline crop and calibration limit. Masked native nearby views
`du_runtime/attack_ring_18.png` through `attack_ring_20.png` retain source
hashes in `attack_rings.json`.

`du_runtime/blessing_title_glow_0.png` and `blessing_title_glow_1.png`
are masked native previews of unchanged blessing titles with different card
glow and short-name OCR. Their sidecars record the source hashes.

`du_runtime/attack_ring_21.png` is a masked native negative containing an
orange numeral balloon and a real distant enemy bar. Its source hash and
negative expectation are recorded in `attack_rings.json`.

`du_runtime/station_beacon_target.png` is a masked native single-card beacon
selector. Its sidecar records the source hash and OCR tokens; the instruction
also names an automatically removed region that is not the selected target.

`du_runtime/gate_awake_partial_hud.png` and `gate_awake_partial_side.png`
are masked native awake doors with one complete eye visible. The masked
`gate_banner_negative.png` is the nearby blue banner used as a negative.
Their sidecars record source hashes.

`du_runtime/gate_back_near_clipped.png` is a masked native near-door back
view, with its upper panel clipped by the screen. Its sidecar records the
source hash.

`du_runtime/forge_interaction.png` and `forge_console_menu.png` are masked
native views of the named F prompt and weighted-curio assembly menu. Their
sidecars record source hashes and OCR tokens.

`du_runtime/card_blue_forge_distant.png` and `card_blue_forge_close.png`
are masked maintenance-card calibration views. `card_blue_banner_negative.png`
and `card_boss_console_negative.png` are masked non-card views. Their sidecars
record source hashes and the local calibration limit. The card model was
incrementally fitted on separately grouped training views and train-only
composites; raw images and PyTorch checkpoints remain under ignored `runs/`.

`templates/du_guide_tab.png` retains the stable planet glyph, excluding its
notification badge and the lower edge covered by the guide's content panel.
Its sidecar records the source and derived crop. The masked native
`du_runtime/guide_universe_tab_clear.png` verifies entry with no notification.

`du_runtime/card_edge_world_title.png` is a masked native edge-on card with
a readable floating region qualifier. Its sidecar retains OCR and source hashes;
the caption supplies a bearing and does not authorize F.

`du_runtime/curio_plane_description.png` is a masked native curio selection
whose descriptive prose mentions planes. Its sidecar retains OCR and source
hashes; only the actual field progress header blocks reward selection.

`du_runtime/equation_queue_24.png` and `equation_queue_27.png` are masked
consecutive equation-expansion overlays. Their distinct names identify progress
even when the shared overlay heading stays unchanged; sidecars retain source
hashes and OCR tokens.

`du_runtime/attack_ring_22.png` through `attack_ring_25.png` are masked native
door-link streaks, companion hats and a genuine attack UI ring. Their source
hashes and positive/negative labels are recorded in `attack_rings.json`.

`du_runtime/attack_ring_26.png` is a masked native genuine range marker near
the party sidebar. Its source hash and positive label are in the same manifest.

`du_runtime/reward_chest_interaction.png` is a masked native free rich-loot
chest F prompt. Its sidecar records OCR and source hashes.

`du_runtime/random_two_{target,remaining,loss,gain}.png` are masked native
screens from the free two-card same-level random conversion. They document
the unchanged second instruction and separate one-card loss/gain receipts.
Sidecars retain OCR tokens and source hashes.

`du_blessing_recommended.png` is cropped from the user's supplied green
blessing recommendation icon. Its metadata retains the source hash and crop.
`du_runtime/blessing_recommended_{right,two,none}.png` are masked native
three-card selections with one, two and zero marked cards, covering gray,
blue and gold cards. Sidecars record marked columns, OCR and source hashes.

`du_runtime/late_gate_interaction.png` is a masked native awake-gate F prompt
which appeared on the last observation of a timed navigation attempt. Its
sidecar retains OCR and source hashes.

`du_runtime/any_region_beacon.png` is a masked native free single-beacon
selector using the written quantity “一个” and no source-region restriction.
Its sidecar records OCR and source hashes.

`du_runtime/forge_plus_three.png` is a masked native free single-card forge
upgrade selector with a +3 level effect. Its sidecar retains OCR and source
hashes.

`du_runtime/awake_gate_with_poster.png` is a masked native reward-room capture
resized to 1920×1080. The distant street poster is a known false Card detection;
the awake gate must retain navigation priority. Its sidecar records source and
fixture hashes and dimensions. Game artwork remains the property of HoYoverse.

`du_runtime/any_region_upgrade.png` is a masked native single-card +2 upgrade
selector without a source-region restriction. Its sidecar retains native OCR
and source/fixture hashes; the right-hand card preview is level 3.

`du_runtime/upgrade_negative_beacon.png` is a masked native single-card upgrade
selector combining a +2 level bonus with a random negative beacon. Its sidecar
retains native OCR and source/fixture hashes.

`du_runtime/pink_brush_false_gate.png`, `brush_and_cafe_sign.png`, and
`card_with_advertisement.png` are masked native cafeteria captures used to
regress decorative brushes, wall advertisements, and the actual TV event card.
Their sidecars retain hashes. They are from the incremental training episode
and are calibration/regression examples, not held-out accuracy evidence.
# Additional local calibration, 2026-10-23

The existing AGPL-3.0 YOLO11n door derivative was fine-tuned on three locally
reviewed console-occluded door screenshots and 36 brightness variants. Raw
captures, labels and checkpoints remain local under ignored `runs/`. The
packaged model retains the license and upstream provenance in its metadata.

`two_cards_at_entry.png`, `card_green_edge_on.png`, and
`card_green_edge_on_pitched.png` are masked local native room captures.
The green event card remains an interaction target when viewed edge-on;
sidecars record reviewed boxes and hashes. These are incremental training and
regression samples, not independent held-out evaluation images.

The card derivative was incrementally fine-tuned on these four native views
and 48 brightness variants, retaining the earlier training corpus and original
held-out split. The packaged last checkpoint retains AGPL-3.0 licensing;
model hashes and CPU ONNX evaluation are recorded in `assets/models/du_cards.json`.

`du_runtime/snow_owl_recruitment.png` is a masked native Snow Owl mask
recruitment screen. Its sidecar retains observed OCR and source/fixture hashes.

`du_runtime/snow_owl_optimization.png` is a masked native Snow Owl station-card
optimization selector, with the same observed OCR/hash provenance convention.

`du_runtime/snow_owl_recruitment_loading.png` captures the native recruitment
animation before the three region titles appear, with identifiers masked.

## Planar preparation and gallery controls, 2026-10-23

`planar_preparation`, `planar_preset_list`, `planar_preset_enabled`,
`planar_mixed_payment`, `planar_disabled_auto`, and `planar_disabled_stage`
under `autohsr/tests/fixtures/du_runtime/` are masked native client captures
for named presets, separate stamina/immersifier prices, and disabled battle
controls. Their JSON sidecars retain source/fixture hashes and observed OCR.

The `gallery_*` fixtures added with this update cover the offscreen reward
pointer, five reward-category views, the collection-only weighted-curio view,
and five corresponding milestone dialogs, including icon-only claimed rows.
Account identifiers are masked and omitted from sidecar OCR. These captures
are regression examples, not independent completion evidence.

`count_plus`, `planar_stamina_cost`, `planar_stamina_cost_single`,
`planar_immersifier_cost`, `planar_auto_dim`, `planar_auto_dim_transition`,
`planar_auto_dim_stage`, and `du_gallery_claimed` in `assets/templates/`
are small native UI crops. Their sidecars retain source hashes, original
dimensions, normalized crop bounds, and the 1920-pixel matching baseline.
Raw captures stay in ignored local `runs/`. All game artwork belongs to
HoYoverse and is included solely for client UI recognition and regression.

`du_runtime/helper_occluded_blessing.png` is a native client capture occluded
by a closing AutoHSR inspection window. The fixture masks account identifiers
and local configuration paths; its sidecar omits those OCR tokens and retains
source/fixture hashes. It tests rejecting helper UI content before game-option
recognition. It is not independent completion evidence.

`du_runtime/optional_device_blocks_gate.png` is a native wealth-room capture
with account identifiers masked. Its sidecar retains source/fixture hashes
and observed OCR excluding identifiers. It tests recognizing a live optional
machine prompt for bounded avoidance, without authorizing game interaction
or spending. Game artwork remains the property of HoYoverse.

`du_runtime/chaos_box_blocks_combat.png` is a native combat-room capture of
an optional chaos medicine box obstructing the entrance path. Identifiers are
masked; the sidecar retains source/fixture hashes and non-identifier OCR. It
tests shared bounded avoidance and early re-reading of unknown F prompts,
without authorizing the box's negative-curio exchange. Artwork is HoYoverse's.

`du_runtime/rest_entry_fade.png` and `rest_entry_ready.png` are masked native
rest-room entrance captures before and after the same fade. They test waiting
for the fixed HUD to recover without rejecting a fully loaded night scene.
`du_runtime/rewards_home_intro.png` is a masked native home entrance frame
whose reward panels are still sliding in from offscreen. It tests withholding
the no-rewards conclusion until all four anchors are complete and stable.
Their sidecars retain hashes and non-identifier OCR; these are local
regression examples, not independent completion evidence. Artwork is HoYoverse's.

`du_runtime/card_unqualified_caption.png` is a masked native edge-on world
event card with a bare floating Chinese title. The sidecar retains source and
fixture hashes and non-identifier OCR. It tests matching a weak learned card
body to the title above it without lowering the normal detector threshold or
authorizing F from a title. It is a local regression example, not independent
completion evidence. Game artwork remains HoYoverse's.

`du_runtime/growing_beacon_target.png` is a masked native station-card
selector opened by a growing curio. Its sidecar preserves source/fixture
hashes and OCR excluding account identifiers. It tests the complete immediate
random-beacon reward and later count-based upgrade instruction. It is local
regression evidence, not an independent completion. Artwork is HoYoverse's.

`du_enemies_recovery.onnx` is a YOLO11n fit derived from the existing
seven-appearance checkpoint, adding three reviewed positive frames, three
negative frames, and 240 generated training scenes from the same local trial.
The existing validation/test split is retained. It is limited to recovery
after an initial missed attack or explicit resumed-field recovery; the
existing runtime models remain unchanged.
Training uses the existing isolated PyTorch/Ultralytics environment and the
same AGPL-3.0 model license. `enemy_pair_front.png`, `enemy_yellow_side.png`,
and `enemy_corner_negative.png` are masked training-frame replays with source
hashes and reviewed boxes in sidecars, not independent accuracy samples.
Game artwork remains the property of HoYoverse.

`du_runtime/event_f_blue_background` is a locally observed field interaction
with a blue event card. Its 1920-pixel copy masks the identifier strip and
retains source hashes and non-identifier OCR. It verifies the circular F key
independently of the scenery outside the button. Game artwork remains the
property of HoYoverse.

`du_runtime/red_tinted_attack_circle` is a locally observed attack-range UI
phase with a red centre and no white core. The 1920-pixel copy masks bottom
identifiers; its sidecar retains source hashes and non-identifier OCR. Game
artwork remains the property of HoYoverse.

`du_runtime/rest_revival_awake_exit` and `rest_forge_awake_exit` are locally
observed rest-room prompts with a visibly awake exit. Their 1920-pixel copies
mask identifiers and retain source hashes and non-identifier OCR. They verify
bounded travel past optional devices, never device use. Game artwork remains
the property of HoYoverse.

`du_runtime/coin_counter_prompt` and `coin_counter_menu` are locally observed
4.6 wealth-room frames. The menu was opened manually for inspection without
executing a trade. The 1920-pixel copies mask bottom identifiers; sidecars
retain source hashes and non-identifier OCR. They verify an optional-device
detour and an Escape-only menu close, not transaction behavior or independent
completion. Game artwork remains the property of HoYoverse.

`du_runtime/entry_trigger_target.png` is a masked native station-card selector
for an enter-region curio with a finite activation lifetime. Source/fixture
hashes and non-identifier OCR are retained in its sidecar. It tests separating
the current target count from the later destruction counter, and is a local
regression sample rather than independent completion evidence.

`du_runtime/side_attack_ring.png` is a masked native combat-room frame with
a genuine range marker on a side enemy while the avatar faces the locked
gate. Its sidecar preserves source/fixture hashes and non-identifier OCR.
It tests corrective aiming after a missed initial click and the bounded use
of a range bearing just verified by the held-input watcher. It is local
regression evidence, not an independent completion. Artwork is HoYoverse's.

`du_runtime/beacon_reroll_target.png` is a masked native station-card selector
requiring a card with existing beacons. Its sidecar retains source/fixture
hashes and OCR excluding the account identifier. It tests the full reroll
instruction and named beacon descriptions in the selected-card panel. It is
local regression evidence, not an independent completion.

`du_runtime/supply_room_banner_overlap.png` is a masked native daily-reset
login-supply popup over an active room-entry banner. Source/fixture hashes
and non-identifier OCR are preserved in its sidecar. It tests bounded
observation retries while the remaining-day text is obscured, retaining the
same owned-supply and free-claim checks. Game artwork belongs to HoYoverse.

`gate_tracking_reference.png`, `gate_tracking_occluded.png`, and
`gate_tracking_wrong_view.png` are masked native nearby frames used to test
optical-flow continuity of an already detected gate through avatar occlusion.
Their sidecars retain source/fixture hashes and the original detected box.
They are local regression views, not independent accuracy or completion
evidence. Game artwork remains the property of HoYoverse.

`phone_mail_body.png`, `mail_disabled_arrow.png`, `bp_tasks_tab.png`, and
`bp_rewards_tab.png` are narrow crops of locally observed 4.6 UI frames.
Their sidecars record source hashes, exact crops, and the 1920-pixel baseline;
notification badges are excluded from navigation glyphs. The masked native
`du_runtime/phone_mail_icon`, `mail_claimable`, `mail_claimed`, and `bp_*`
fixtures test free-claim controls, tabs, XP feedback, and notification state.
Account identifiers, phone profile details, and unnecessary mail content are
masked; sidecars retain hashes and non-identifier OCR. These are local
regression samples, not independent automation-success evidence. Game artwork
remains the property of HoYoverse.

`du_runtime/last_area_confirm` is a locally captured final-route warning from
the 4.6 client, resized to the 1920-pixel baseline with the bottom identifier
strip masked. Its sidecar records the source hash and non-identifier OCR.
It verifies modal priority and one-shot confirmation feedback; it is not
independent completion evidence. Game artwork remains the property of HoYoverse.

The same `du_runtime/last_area_confirm.png` is also a layout/color reference for
the code-drawn desktop detail and unsaved-settings panels in `autohsr/desktop_dialogs.py`
(2026-10-29): 960×360 plate, 8px offset frame, 96px footer at the 1920px baseline.
The masked fixture SHA-256 is
`961eefc1aaf95bb3c501bb23df9e519e97e6431abd2e4ff68b92714e3cdc7dab`.
No new bitmap is extracted or bundled for this panel; the existing game font
retains its attribution above. This reference does not prove whole-screen parity.
The unsaved-settings panel has three explicit application choices; narrow work
areas stack them vertically. These are application adaptations of the reference,
not claims that the game's original two-button interaction is identical.

`du_runtime/adventure_hanu_*` are locally captured 4.6 adventure-room frames
with the bottom identifier strip masked at the 1920-pixel baseline. Their
source hashes and non-identifier OCR verify the floating NPC name separately
from the live interaction prompt, countdown, score HUD, and result exit.
These are regression samples, not independent completion evidence. Game
artwork remains the property of HoYoverse.

`du_runtime/event_five_reward_confirm` and `reward_items_fifty` /
`reward_items_twenty` are locally observed 4.6 event and item-receipt frames.
The 1920-pixel copies mask bottom identifiers; sidecars retain source hashes
and non-identifier OCR. They verify an observed reward-count bound and
receipt-content changes, not the number of independently earned rewards.
Game artwork remains the property of HoYoverse.

`du_runtime/two_random_beacons` is a locally captured 4.6 station-card
instruction, resized to 1920 pixels with the bottom identifier strip masked.
Its sidecar retains the source hash and non-identifier OCR. It verifies one
target card with two automatically attached beacons, not two selections.
Game artwork remains the property of HoYoverse.
# 2026-10-26 货币战争导航OCR回归

`autohsr/tests/fixtures/currency_wars_navigation.json`仅提取用户授权本地开发截图的固定导航文字、置信度与归一化框；元数据保留原样本相对标识与图像SHA-256以便本地核对。字段采用明确白名单，排除UID、昵称、资源库存和原始图像；文本事实用于界面回归。来源客户端4.6.0，日期2026-10-26；没有新增分发游戏图像，旧`du_guide_tab`与`du_interaction_f`继续使用各自既有来源记录。

`autohsr/tests/fixtures/currency_wars_standard_environment.json`来自同日用户授权开发的标准A8-40环境选择页，仅保存卡片与固定UI OCR，排除UID、账号和原始图像。来源相对标识、客户端4.6.0与原图SHA-256保存在元数据；用于完整效果、数值与卡片顺序回归，不将回放当成实时输入授权。

`autohsr/tests/fixtures/currency_wars_standard_shop.json`来自2026-10-26标准商店记录，仅保存商店标题、候选、标价与固定导航OCR，排除UID、玩家头像、余额区域及原始图像。元数据保留本地来源相对标识、日期和原图哈希；藿藿与单数字价采用已核实的局部识别，原始截图保持忽略，不分发游戏整图。

# 2026-10-28 桌面指南界面（首版）

AutoHSR桌面参考《崩坏：星穹铁道》“星际和平指南／每日实训”的信息层次和视觉语言（深色外框、浅色内容、金色菱形里程碑、任务条目），以及[AutoZZZ快捷手册界面](https://github.com/HenryTANG0520/AutoZZZ/tree/a137c1eee44ea7429d06d018bd60d47c34bed41a/autozzz)的游戏化任务组织与常驻控制思路。星铁界面的公开参考可见[HoYoLAB社区截图](https://www.hoyolab.com/article/24934874)与[每日实训截图](https://www.pushsquare.com/guides/honkai-star-rail-beginners-tips-tricks-and-how-to-play)。参考日期2026-10-28；仅作设计参考，不代表相应旧版截图中的游戏任务仍是当前规则。

首版提交`468dffe`没有下载、裁切或分发上述截图，没有新增第三方位图、游戏字体或模型。其图形由程序绘制，中文使用Windows系统字体Microsoft YaHei UI。该说明仅对应首版历史状态；后续用户要求按实际游戏素材复刻，见下节。

## 2026-10-28 指南实际素材与字体

新增`assets/ui/`中的16个静态图像与1个字体文件，用于桌面指南复刻。源画面为既有简体中文4.6.0实机截图，分别对应每日实训、生存索引与旷宇纷争；没有重新启动游戏取材。源图SHA-256、各静态裁切坐标、透明蒙版变换和输出哈希均记录于[UI sources.json](ui/sources.json)。原始整图、UID和账号信息不随素材提交。两个图标复用既有模板，原来源与许可记录继续保留。

字体为本地客户端附带的`SDK_SC_Web`，原文件名`zh-cn.ttf`，按原始字节复制；保留汉仪版权和许可元数据，不纳入原创代码GPL声明。游戏图像同样归相应游戏权利人；来源事实与署名不构成再许可授权。详情及复现脚本见[UI素材说明](ui/README.md)。代码重绘指南外框、纹样、卡片、进度与按钮，没有迁入AutoZZZ或March7thAssistant的GUI源码。

2026-10-29重制其中三个页签图标、活跃标记与任务卡水印。仍使用既有每日实训、旷宇纷争两张原图，避开指针与放射纹背景，保留连续透明度、图标渐变及原比例；五项来源、裁切与输出哈希更新在同一清单中。没有新增来源或素材文件数，未分发原始画面；游戏美术的权利归属和许可边界不变。

同日新增`card-frame.png`，从同一每日实训源图提取纸面地图纹样、金色点线与底部撕口。原状态栏、任务、数值和奖励区域的RGB及透明度一并清零，外缘按亮度提取透明度；没有保留藏在透明通道下的原任务文字。清单记录288×372裁切、蒙版与哈希；不透明静态区域保留源像素。未采集新游戏画面，权利归属仍同上。

## 2026-10-28 March7thAssistant货币战争策略适配

标准模式“默认／阿格莱雅／希儿”的购买、成长和补空位偏好参考March7thAssistant固定提交`7cf6c6bed474539485d3b1504077ac352866829f`，作者moesnow及其贡献者，上游GPL v3。完整许可、Git blob与哈希清单及改写范围见[来源说明](upstream/March7thAssistant/README.md)。本次界面只接入对应的本次新局策略选择，接续继续使用已记录策略；没有迁入上游GUI、固定输入或图片，未将离线通过写作实机通过。

## 2026-10-29 生存索引列表素材

新增`assets/ui/survival/`的104幅静态图像，从2026-10-20既有CN 4.6.0生存索引目录采集画面裁出对应掉落图标或首领徽章。分类、名称和地点与现有104条目录逐项绑定；[来源清单](ui/survival/sources.json)记录原图相对标识、SHA-256、1920×1080坐标、裁切变换及输出哈希。排除完整画面、UID、玩家头像、余额和无关个人信息，没有启动游戏取新图。游戏美术归HoYoverse及相应权利人，不纳入原创代码GPL声明；来源记录不代表额外再许可。仅用于桌面目录展示，不能作为当前账号已解锁或已通关的证据。

同日从同批归档画面补入21个地区、命途、属性标题图标。对应64条副本的分组按同屏标题及相邻滚动画面的重叠条目核对；[分组清单](ui/survival/groups.json)保留每组图标的裁切、原图与OCR记录哈希、输出哈希，以及条目归属的原始帧标识。没有采集新画面、复制账号状态或变更执行目录；图像的权利归属与上述许可边界相同。

## 2026-10-29 March7thAssistant装备识别参考

后端装备阶段从同一固定提交引入18幅`assets/images/share/aglaea/`原始PNG，作者moesnow及其贡献者，遵循所附上游GPL v3；游戏美术与名称仍归其权利人。文件未经裁切、缩放或重编码，逐项原路径、Git blob、SHA-256和字节数见[装备来源清单](upstream/March7thAssistant/equipment/sources.json)，本地标识、用途及原生变体见[装备参考说明](upstream/March7thAssistant/equipment/README.md)。完整上游许可继续保留于[LICENSE](upstream/March7thAssistant/LICENSE)。

这些图用于仓库、角色槽和当前推荐配方的本地识别。已校准14种可穿戴装备；参考图包含的投影仪、令牌、冶金炉和两种扳手尚未接入使用。没有复制上游输入实现，也没有将界面打开、材料消失、合成测试或离线模板回放写作实机穿戴成功；现有UI素材署名和原生4.6装备参考保持不变。

## 2026-10-29 旷宇纷争入口插图

新增`assets/ui/universe/`两幅入口插图，来源为2026-10-24和26日已保存的CN 4.6.0指南画面。只保留静态插图，原等级、赛季倒计时、奖励预览和动作区域移除，局部颜色延展补充背景；原区域不再代表账号或当前版本状态。来源SHA-256、裁切、移除蒙版、处理方法与输出SHA-256见[来源清单](ui/universe/sources.json)。未启动游戏采集，不包含完整帧、UID或账号指纹；游戏美术归HoYoverse及相应权利人，继续排除在原创代码GPL许可之外。

## 2026-10-29 指南场景与关闭符号

新增`assets/ui/guide/`两幅图像，复用既有CN 4.6.0每日实训源图，原图SHA-256与首批指南素材一致。背景移除标题、整本指南、关闭符号及整个底部HUD区，遮挡区域用低分辨率邻近颜色插值、放大并在蒙版内侧羽化；这些区域不代表原始景物。关闭符号单独裁出静态白色图形。来源哈希、1920×1080坐标、蒙版、变换及输出哈希见[来源清单](ui/guide/sources.json)，未分发原始整图、UID或安装路径，未启动游戏取材。游戏美术归HoYoverse及相应权利人，不纳入原创代码GPL许可，署名不构成额外再许可。
