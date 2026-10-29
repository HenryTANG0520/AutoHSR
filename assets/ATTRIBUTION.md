# AutoHSR resource attribution

2026-10-29差分站点偏好参考固定March7thAssistant `process_next_station`及默认配置，按行为适配为[原生冻结偏好](../autohsr/du_station_policy.py)。保留本项目默认顺序、输入门禁及危险信标检查，没有复制坐标、重抽循环或禁用项兜底。两个原源码blob、GPL v3许可哈希及范围见[站点来源说明](upstream/March7thAssistant/du/README.md)和[清单](upstream/March7thAssistant/du/source.json)；未新增图像、模型或游戏采集，检查使用模拟卡片及已有脱敏回放。

## 2026-10-29 货币战争周常编排

参考固定March7thAssistant的日常`Daily.start`与`CurrencyWars.start`／`check_currency_wars_score`，将积分、原生有限循环及独立领奖接入[周常归属](../autohsr/currency_wars_weekly.py)与[顺序Runner](../autohsr/currency_wars_weekly_run.py)。每账号／游戏周索引、固定对局上限、原日常报告复用、逐局来源审计和只读恢复为AutoHSR适配；没有迁入上游定时器、全局时间戳、遥测或输入框架。源文件blob与GPL v3见[source.json](upstream/March7thAssistant/source.json)。本次没有新增素材或真实采集，检查使用假窗口与合成最终节点。

## 2026-10-29 独立积分领奖

参考固定March7thAssistant的`get_reward`、`_fuel_ticket_limit_visible`及`wait_for_weekly_reward`，改写为[原生积分领奖控件](../autohsr/currency_wars_weekly_rewards.py)、独立Runner与意图／回执存储。沿用AutoHSR当前页面、账号、客户端、代次及输入门禁，另核对两帧奖励展示、数量字段、禁用状态、原图及原报告；满额只记录拒绝结果，不清理或重发。来源blob和GPL v3见[source.json](upstream/March7thAssistant/source.json)。本次未导入上游领取按钮图、GUI或输入框架，未新增真实采集、公开图片或模型；正向领取检查使用合成文字／按钮图像及假窗口，不作为真实领取样本。

## 2026-10-29 本周积分循环目标

在固定上游`check_currency_wars_score`及循环入口参考上，将[独立积分观察](../autohsr/currency_wars_points_run.py)接入[原生循环目标](../autohsr/currency_wars_points_goal.py)。冻结周／账号、局数上限、精确回执、开局前双重门禁与空记录归档为AutoHSR适配；没有迁入全局时间戳、未知失败后重开或领奖实现。函数、blob及GPL v3见[source.json](upstream/March7thAssistant/source.json)。本轮未新增素材、真实采集或模型，检查采用模拟窗口与既有原生报告协议。

## 2026-10-29 积分核对与旧OCR白名单

参考固定March7thAssistant的`check_currency_wars_score`，将积分当前值／上限判断改写为[原生解析](../autohsr/currency_wars_points.py)及账号／游戏周观察回执；函数、Git blob和GPL v3见[source.json](upstream/March7thAssistant/source.json)。未迁入全局时间戳或领取实现，未新增图像或模型。[文字夹具](../autohsr/tests/fixtures/currency_wars_points.json)由三份既有游戏截图的原OCR筛选，仅保留22条菜单、积分与倒计时字段及来源哈希，不带UID、图像和无关余额；它们是旧校准材料，不是新实机留出。游戏界面及文字归HoYoverse和相应权利人所有。

## 2026-10-29 逐局连续运行

参考固定March7thAssistant的`main.py`中`run_sub_task`及其局部循环／货币战争调用，将连续运行改写为[原生组合Runner](../autohsr/currency_wars_loop.py)。逐局归属、冻结目标、账号输入门禁、原报告核验和可恢复归档属于AutoHSR原生适配；失败／未知停止，不迁入上游false返回后继续或遥测实现。Git blob及GPL v3许可见[source.json](upstream/March7thAssistant/source.json)。未新增公开图像、模型或真实采集；检查使用合成最终节点、假窗口与既有原生结算协议。

AutoHSR is distributed under the GNU General Public License version 3. The full
license is in [../LICENSE](../LICENSE). The resources below retain their upstream
license and contributor attribution. They are used as UI recognition references
and, where stated below, desktop UI materials.
Honkai: Star Rail artwork and names belong to their respective rights holders;
the upstream software licenses do not grant ownership of those game assets.

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

## 2026-10-28 March7thAssistant货币战争策略适配

标准模式“默认／阿格莱雅／希儿”的购买、成长和补空位偏好参考March7thAssistant固定提交`7cf6c6bed474539485d3b1504077ac352866829f`，作者moesnow及其贡献者，上游GPL v3。完整许可、Git blob与哈希清单及改写范围见[来源说明](upstream/March7thAssistant/README.md)。本次界面只接入对应的本次新局策略选择，接续继续使用已记录策略；没有迁入上游GUI、固定输入或图片，未将离线通过写作实机通过。

## 2026-10-29 生存索引列表素材

新增`assets/ui/survival/`的104幅静态图像，从2026-10-20既有CN 4.6.0生存索引目录采集画面裁出对应掉落图标或首领徽章。分类、名称和地点与现有104条目录逐项绑定；[来源清单](ui/survival/sources.json)记录原图相对标识、SHA-256、1920×1080坐标、裁切变换及输出哈希。排除完整画面、UID、玩家头像、余额和无关个人信息，没有启动游戏取新图。游戏美术归HoYoverse及相应权利人，不纳入原创代码GPL声明；来源记录不代表额外再许可。仅用于桌面目录展示，不能作为当前账号已解锁或已通关的证据。

## 2026-10-29 March7thAssistant装备识别参考

后端装备阶段从同一固定提交引入18幅`assets/images/share/aglaea/`原始PNG，作者moesnow及其贡献者，遵循所附上游GPL v3；游戏美术与名称仍归其权利人。文件未经裁切、缩放或重编码，逐项原路径、Git blob、SHA-256和字节数见[装备来源清单](upstream/March7thAssistant/equipment/sources.json)，本地标识、用途及原生变体见[装备参考说明](upstream/March7thAssistant/equipment/README.md)。完整上游许可继续保留于[LICENSE](upstream/March7thAssistant/LICENSE)。

这些图用于仓库、角色槽和当前推荐配方的本地识别。已校准14种可穿戴装备；六种工具另经专用数量识别与实际效果协议适配，范围见下节。没有复制上游输入实现，也没有将界面打开、材料消失、合成测试或离线模板回放写作实机穿戴成功；现有UI素材署名和原生4.6装备参考保持不变。

## 2026-10-29 货币战争工具原生变体与次数校准

`assets/templates/currency_wrench2_native_4_6.png`从既有本地4.6画面`146-boss-ready-loot-cleared.png`静态裁出75×70金色扳手图标，裁切坐标、原图及原清单SHA-256、输出哈希记录在[消耗品来源清单](currency-consumables/sources.json)。图标排除次数、UID、账号和完整画面；原始截图保持忽略，没有启动游戏取新图。游戏美术归HoYoverse及相应权利人，不纳入原创代码GPL声明，来源不授予额外再许可。

工具初始参考继续使用上一节固定提交的18幅上游原PNG及完整GPL v3许可，没有改写这些字节。六种工具的命名核心优先思路改写为本项目Context、账号／输入代次、库存及完整角色效果核验；上游来源与具体适配文件继续记录于[source.json](upstream/March7thAssistant/source.json)。三份既有画面及五份工具教程仅记录脱离账号的局部事实、原哈希与本地标识；没有分发整图、更新模型或建立独立实机验收集。识别与执行边界见[工具说明](currency-consumables/README.md)。

## 2026-10-29 货币战争补给刷新控件

`assets/templates/currency_supply_refresh_4_6.png`从既有4.6补给画面静态裁出72×71的Q控件，排除次数、UID与完整画面；原图、原清单、坐标、变换、SHA-256及三份旧补给控件校准记录见[补给来源清单](currency-supply/sources.json)。游戏美术归HoYoverse及相应权利人，不纳入原创代码GPL声明，来源不授予额外再许可。没有启动游戏取材、公开整图或训练模型。

命名策略的补给偏好和有界刷新参考同一March7thAssistant固定提交的`check_supply_phase`，经原生Context、独立次数回执、完整候选链和原奖励到账核验改写；保留上游署名与GPL v3许可。旧图缺失名字保留未知列，不从视觉人工读数伪造OCR通过；没有将局部校准或合成场景写成实机刷新成功。范围见[补给说明](currency-supply/README.md)。

## 2026-10-29 记忆开拓者配置名策略适配

同一March7thAssistant固定提交的`get_remembrance_trailblazer_name`及购买、保留、聘用书、顾问和补给调用，改写为AutoHSR的本局名称协议、原生策略偏好和一致身份核验。保留上游署名、固定源码Git blob及完整GPL v3许可，具体文件见[source.json](upstream/March7thAssistant/source.json)。名称配置不作图像素材，不引入上游固定费用或输入代码；本地实读名不发送给模型。本轮没有新增游戏素材或模型，真实字体及游戏路径尚未验收，见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-29 标准盛会之星弹窗与文字校准

固定March7thAssistant提交的`move_character`、`check_festival_star_popup`改写为原生部署／换人后的弹窗来源、一次选择／确认及完整角色交付协议，保留上游署名和GPL v3许可，见[source.json](upstream/March7thAssistant/source.json)。AutoHSR原有花火偏好继续保留，没有复制固定首项或上游输入代码。

[两卡文字夹具](../autohsr/tests/fixtures/currency_wars_star_two.json)来自既有4.6画面119／121，仅保留弹窗区域原OCR、原图及清单SHA-256，不修改识别文字，不含UID、账号或完整图像。游戏UI文字与角色内容归HoYoverse及相应权利人；来源记录不授予额外再许可。本轮未新增公开游戏图像或模型，119／121／169原图与清单保持本地忽略；用于查看的裁图和运行时局部图像来源不进入模型请求。布局、选中反例与未验收范围见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-29 普通角色采集局部图像校准

复用既有CN 4.6画面115／116，比较原角色槽位的微小像素变化，核对原图与原清单哈希；没有获取新游戏截图、发布原图或新增模型。两份旧图属于相邻校准样本，不是独立留出或新实机验收。原素材权利仍归HoYoverse及相应权利人，来源记录不授予额外再许可。

原弹窗协议的32×48灰度来源与有界比较移至[本地局部图像模块](../autohsr/currency_wars_appearance.py)，新增普通采集使用由本项目原生编写。运行时只裁已定位的角色槽位，图像来源保存在本地对局记录；不含UID或账号区域，不进入模型请求。公开新增测试仅生成合成槽位与面板；原图、清单、局部比较输出保持忽略，具体证据与边界见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-29 希儿场上整理与信用回执

参考固定March7thAssistant的`check_main_screen`、`sell_characters_seele_strategy`和`_sell_single_character`，将取得希儿后的场上非策略角色整理改写为AutoHSR前台／后台的独立查看与信用回执。来源函数、固定Git blob及GPL v3许可继续记在[source.json](upstream/March7thAssistant/source.json)，没有移植上游输入代码或缓存删除即成功的判定。

复用既有2026-10-26三份角色面板的当前`+5／+1／+2`返还文字与原图／清单哈希，未修改原图、重新取得游戏画面或公开账号区域；这些画面只校准返还字段，不能证明新增场上出售动作已通过实机。游戏素材权利仍归HoYoverse及相应权利人，来源记录不授予额外再许可。新增公开检查只生成合成槽位，使用既有署名图标构造空装备面板；场上来源及有界局部图像只保存到本地对局记录，不进入模型。验证与未实现的携装返回效果见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-29 原生全身重铸扩展

[全身重铸协议](../autohsr/currency_wars_worn_reforge.py)由AutoHSR根据既有CN 4.6游戏教程67／68号原生编写，原图及清单哈希仍见[消耗品来源](currency-consumables/sources.json)。67号说明冶金炉的同品质重铸，68号明确对角色全部穿戴装备重新随机；已查看排除账号区域的旧教程裁图，其中示意角色前后三个装备格均保留。此为规则校准，不是新实机动作或独立留出。

上游`equip_aglaea`、`equip_seele`提供仓库重铸及命名工具策略参考，全身目标及结果核验属于本项目新增扩展，分别记在[source.json](upstream/March7thAssistant/source.json)。没有添加新公开游戏图像或模型，测试使用既有署名图标与合成槽位。旧教程、离线QA裁图、角色有界来源与新回放保持本地忽略，QA查看排除账号区域，对局图像来源不加入策略模型载荷；游戏内容权利归HoYoverse及相应权利人，来源记录不授予额外再许可。

## 2026-10-29 全局阵容整理与空位移动

参考固定March7thAssistant的`deploy_and_optimize`及`move_character`，将全体持有角色的区域规划改写为[原生全局整理](../autohsr/currency_wars_standard_reorder.py)。保留本项目评分，固定与位置无关的目标，逐步核验真实身份和资源；新增另一侧空位移动，并处理其盛会之星接续。来源函数、固定Git blob与GPL v3许可见[source.json](upstream/March7thAssistant/source.json)，未直接移植上游金额排序、输入框架或缓存即成功的判定。没有新增公开图像、模型或游戏采集；测试沿用既有署名图标和合成棋盘，局部外观证明仅保存到忽略的本地记录，不加入模型载荷。

## 2026-10-29 整局执行与有界存档

参考固定March7thAssistant的`start_war`及`identify_current_stage`的整局执行与阶段监测，将本项目总512步实验循环改写为[原生分段执行上限](../autohsr/currency_wars_standard_budget.py)。计数刷新依赖本项目的胜利继续／补给交付来源，原未知输入保护继续使用；不迁入自动放弃与重开，也不以OCR变化作为额度刷新。64 MiB有界存档、写入前容量检查及总4096动作限制属于AutoHSR原生设计。源码blob、引用函数和GPL v3继续记在[source.json](upstream/March7thAssistant/source.json)；没有新增公开素材、模型或游戏采集，检查使用合成记录与已有署名素材。

## 2026-10-29 速通装备选项

参考固定March7thAssistant的`equip_weapons`、`check_main_screen`及`equip_aglaea`／`equip_seele`调用关系，将普通装备的首领节点限制改写为[原生装备模式](../autohsr/currency_wars_equipment_mode.py)。命名核心分配独立，保留本项目默认、设置保存语义及逐件装备回执；标准首领节点采用固定源码中的1-9、2-7、3-7，不将其他模式写成已接入。来源函数、Git blob及GPL v3许可见[source.json](upstream/March7thAssistant/source.json)。没有新增公开游戏素材、模型或实机采集；检查沿用既有署名图标与合成状态。

## 2026-10-29 携装角色出售与装备返还

参考固定March7thAssistant的`_sell_single_character`及三种出售调用关系，将携装角色处理适配为[原生库存返还协议](../autohsr/currency_wars_sale_equipment.py)。保留本项目已校准图标和角色面板，增加版本化目标、完整库存来源、逐项返还及售后完整重采，未移植点击成功即完成的判断。来源函数、Git blob及GPL v3许可继续记录于[source.json](upstream/March7thAssistant/source.json)。本轮没有新增图像、模型或游戏采集；正向售出及返还均为合成画面机制检查，来源及边界见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-30 多副本体力计划

参考固定March7thAssistant的`Power.run`、`Power.execute_power_plan`、`Power.process`及副本执行结构，将有序条目、剩余次数、固定重复和默认副本补刷适配为[AutoHSR原生计划](../autohsr/power_plan_run.py)。源码的Git blob、SHA-256、固定提交及GPL v3许可记在[source.json](upstream/March7thAssistant/source.json)，已与此前取得的固定目录树核对。没有复制上游GUI、输入框架或配置自动扣减写回行为；本项目仍只在保存设置时写配置，运行进度使用独立本地账本。

一份已有资源预算、同账号新鲜画面、原生逐批支付核验、原子计数及不可覆盖归档属于AutoHSR实现。没有新增公开游戏素材、训练模型或采集画面；新增检查使用合成窗口与场景，账号数字为虚构测试值。培养目标、资源补充及遗器清理均未在本轮接入，界面与实机边界见[计划说明](../docs/power-plan.md)。

## 2026-10-30 历战优先周计划

参考固定March7thAssistant的`Echoofwar.start`及`Daily.prepare_daily`，将当前0～3次周额度与清体力前的优先执行适配为[原生历战周计划](../autohsr/echo_weekly.py)。源码Git blob、SHA-256、固定提交和GPL v3来源见[清单](upstream/March7thAssistant/source.json)。本项目使用日常开始时间、04:00游戏周和单份冻结预算，独立核实周额度、可见结算与本次实际完成，不迁入上游配置时间戳写回、输入或定时器。

没有新增图像、模型或游戏采集，检查沿用合成窗口与场景。缩短新归档目录键并保留完整账本摘要是本项目对Windows路径长度的修复，既有目录不迁移或覆盖。培养目标和支援角色偏好仅完成源码核对，尚未适配，不在本轮署为已实现；交互、运行证据及实机边界见[说明](../docs/echo-of-war-plan.md)。
