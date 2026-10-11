# AutoHSR resource attribution

AutoHSR is distributed under the GNU General Public License version 3. The full
license is in [../LICENSE](../LICENSE). The resources below retain their upstream
license and contributor attribution. They are used as UI recognition references.
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
