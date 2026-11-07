# 可编辑任务流程

开发版的「设置 → 工具 → 任务流」支持可视编辑、本地 JSON 草稿与 ZIP 素材包。正式任务级树形编排也可通过独立 CLI 使用，并支持独立差分红点领奖。真实跨玩法组合、游戏画面识别及鼠标／键盘底层步骤分别验收。[独立差分红点领奖](du-rewards-only.md)

## 与三月七的关系

参考固定March7thAssistant提交`7cf6c6bed474539485d3b1504077ac352866829f`的[流程教程](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/docs/Workflow.md)及[执行模块](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/workflow/__init__.py)。借鉴步骤树、条件、循环、循环控制及选中步骤执行，采用AutoHSR自己的JSON与正式Runner。

可视编辑覆盖 AutoHSR 的正式步骤类型。图文判断可选本地图片或当前游戏画面。AutoHSR 素材包关联本流程使用的图像与音频。页面切换沿用已经核实的日常入口，三月七 YAML 可转换其中已有对应实现的步骤。坐标点击、拖动、通用按键及其他页面继续分别适配。固定来源、函数与 SHA-256 见[来源清单](../assets/upstream/March7thAssistant/source.json)，原 GPL v3 保留。

## 当前任务与设置

流程的`task`步骤调用下表正式入口。每次执行先冻结独立设置副本；不保存用户配置。相对记录路径以流程文件所在目录为准，API调用可明确传入`base_dir`。

| task | 正式实现 | params与默认行为 |
| --- | --- | --- |
| `daily` | `Runner(operation='daily')` | 不填`tasks`时沿用当前日常开关；可明确指定`assignments/battle/daily/redemption/mail/battlepass`子集。可覆盖`stamina_limit/rounds/target_name/target_location/dungeon_category/challenge_count/use_support/support_daily_only`；`use_power_plan`默认false |
| `daily_training_rewards` | `Runner(operation='reward_only')` | 无参数，仅补领已完成的每日实训点数与已达档位。材料、开拓力、沉浸器预算均为零 |
| `daily_free_attachment` | 日常 Runner 的独立领奖范围 | 必填 `target`，选择 `mail`（邮件附件）或 `battlepass`（勋礼经验与免费等级奖励） |
| `plan` | `PlanRunner` | 沿用现有日常→到期周常。`use_power_plan`、`resume_weekly_currency`默认false，`support_daily_only`可覆盖本次日常。原周目标及接续规则保持 |
| `differential_universe` | `Runner(operation='differential_universe')` | `runs`默认1、范围1～10；`mode`默认periodic，可选normal；`team`默认沿用当前预设；`save/rewards/resume_active/until_points`默认false；`periodic_rank`仅用于明确接续；通关后日常固定关闭 |
| `du_rewards` | `Runner(operation='du_rewards')` | 已打开差分主页，独立处理三类免费已有红点；`use_cassettes`默认false，明确true才加入月下；不演算，不改变保存设置，不等于周积分领奖 |
| `currency_wars_loop` | `CurrencyLoopRunner` | `runs`默认1、范围1～10，不接受0／无限批次；`resume`默认false；可选`strategy/until_points/continue_after_defeat`。未指定的后三项沿用原生默认及冻结设置；接续仍须核对原局数和原账本 |
| `currency_wars_points` | 原生积分Runner | 无参数；仍会导航和核对当前账号／游戏周，属于游戏输入任务 |
| `currency_wars_rewards` | 原生积分领奖Runner | `resume`默认false；不开始对局，不清理满额资源，未知领取不重放 |
| `warp_analysis` | `warp_service.run(analysis_only=True)` | 必填`imports`，1～32份明确的本地SRGF／UIGF文件；只分析不创建导出 |
| `warp_export` | 原记录导出服务 | 必填`imports/output`，`format`默认uigf，可选srgf/xlsx；可选`selected_uid`，原件及已有输出不覆盖 |
| `workflow_audio` | Windows 本地音频 | 必填 `path`，支持明确选定的 PCM WAV。暂停后从当前位置继续，停止时清空本步骤队列 |
| `workflow_image` | 本地模板判断 | 必填 `image`、`template`，使用明确的 PNG／JPEG。可选 `region`、`threshold`，默认阈值 0.88 |
| `workflow_text` | 本地 OCR 判断 | 必填 `image`、`text`，可选 `region`、`threshold`、`contains`。默认精确匹配，阈值 0.65 |
| `workflow_game_image` | 当前游戏画面模板判断 | 必填 `template`，可选 `region`、`threshold`。默认阈值 0.88 |
| `workflow_game_text` | 当前游戏画面 OCR 判断 | 必填 `text`，可选 `region`、`threshold`、`contains`。默认精确匹配，阈值 0.65 |
| `workflow_open_page` | 已知日常页面切换 | 必填 `target`，可选值见下方。只切换页面并核实到达 |
| `workflow_notify` | 已保存通知方案 | 必填 `profile`、`message`。可选 `png`，显式绑定本地 PNG 和 SMTP 方案时仅通过命令行手动运行。同一运行出现待核对的提交后停止后续主动通知 |

记录任务目前只接显式本地JSON；真实缓存／链接获取继续使用[独立工具入口](warp-records.md)，没有在流程中隐式扫描。XLSX仍使用已固定的可选加载引擎，见[统计与Excel](warp-statistics-xlsx.md)。

图文判断的 `region` 是相对整张图片的 `[左, 上, 右, 下]`，缺省为整张图。已完成分析但未匹配时，回执明确给出 `image_found=false` 或 `text_found=false`，可以用于后续条件。文件、范围或识别失败时没有匹配事实。音频及图片路径相对流程文件，应用内定时冻结这些来源的文件指纹。

游戏图文步骤读取已经登录且处于前台的游戏客户区。两张连续新画面都必须核实同一窗口、账号、输入代次及一致的识别结果。登录、遮挡、失焦、账号变化或两次识别不一致时，匹配字段留空。步骤占用正式执行权，只观察画面，回执只写布尔结果，账号证据仍按原规则留在本机。定时触发时也需要游戏已在前台，并受含游戏任务的单次重复限制。

页面切换与实时图文共享前台及账号门禁。目标为 `phone` 手机、`guide` 指南、`daily_training` 每日实训、`survival_index` 生存索引、`assignments` 委托、`mail` 邮件、`battlepass` 无名勋礼、`odyssey` 巡星之礼、`reward_guide` 奖励指南和 `messages` 短信通知。泛指南目标保留当前指南子页。已经在目标页时零输入。每次点击或返回都要求当前页面和可用入口有证据，再双帧核对新页面。遇到登录、弹窗、战斗、失焦或不认识的页面时保留已有动作回执。只有已核实到达的结果才提供 `page_verified=true`。导航不领取奖励、不开战，也不建立资源预算。活动与短信通知目标目前支持已校准的 4.6.0 版式。短信从带可见未读角标的大世界或已打开的通知双栏开始，最多提交一次气泡点击。[活动页面导航](daily-event-observation.md#独立导航) · [短信导航](../DAILY_FLOW.md#短信只读校准)

### 仅补领每日实训

能力 ID 为 `daily_training_rewards`。任务流步骤接受省略的 `params` 或空对象 `{}`，其他字段均拒绝。普通 `daily` 节点的 `tasks: ["daily"]` 继续沿用保存的 `daily_synthesis`。独立领奖节点使用仅补领奖设置副本，关闭合成与已有资源消耗，跳过刷本、附加任务、合成恢复和旧账核销。它仍会发出导航和领奖输入，沿用原生仅补领奖的启动、页面和输入门禁，以及任务流的执行权与账号连续性。

P1 底栏「仅补领奖」和 `--run --reward-only` 继续直达同一原生入口。任务流和应用内定时的任务下拉框显示「仅补领每日实训」。定时可直接选此任务，也可选包含此节点的已保存任务流。两者使用同一参数校验和回执。此节点占用一次日常执行名额，因此同一路径只允许一个 `daily_training_rewards`、`daily` 或 `plan` 节点。定时的批内重复上限为一次，单任务预览的体力预算为零。现有父层结束通知仍按其独立设置生效。[应用内定时](schedules.md)

任务流保留子报告与账号核验状态。实训未到 500 时，即使已核实部分档位领取，状态仍为 `partial`。只有 500 活跃且五档均核实已领取时才给出 `daily_verified=true`。本能力可作为后续 P1 模块的执行落点。持久化模块开关及授权策略留待中央评审。

| 最小回归 | 核对项 |
| --- | --- |
| 普通实训与独立领奖的设置投影 | 同一份开启合成、刷本的配置。旧实训继承合成，新节点只保留领奖，输入扩展和同路径重复被拒绝 |
| 模拟窗口执行 | 400 活跃领取可见档位后报告部分完成，500 活跃五档已领取时零领奖点击。父子回执一致，材料流程及其恢复均未调用，资源账和配置不变 |
| 任务编辑与定时 | 下拉框保存空参数，预览与冻结保留游戏任务身份和零体力预算，批内重复两次被拒绝 |

### 明确指南页签

`difficulty_guide` 指逐光捡金，`universe_guide` 指旷宇纷争。简中 4.6.0 可从已核实的手机或指南页开始。手机打开指南后先核对实际落页，再按需切换。逐光捡金复用左侧三项高难布局。旷宇纷争核对左栏货币战争与差分宇宙，并核对其中一种已校准的详情布局。只有明确页签通过同账号双帧才算到页。已在目标页零输入。切换只点指南页签，模板匹配须唯一且位于对应页签。泛 `guide` 仍接受任一现有指南子页。

使用脱敏历史帧和假 Win32 验证从手机经生存索引到逐光捡金、从逐光捡金到旷宇纷争，以及双模板零输入。两张选中货币战争的历史帧缩至 960×540 后，在自定义 OCR 阈值 `0.91` 下「零和博弈」得分 `0.884`，回执保留待核对。原生小窗口与当前客户端切页待实机验证。[历史帧来源](../autohsr/tests/fixtures/workflow_guides/sources.json)

### 返回大世界

正式 `workflow_open_page` 可选择「大世界」`world`，用于简中 4.6.0 前台。已在普通大世界时，通过左上手机图标和右上世界 HUD 的同账号双帧确认，零输入结束。从已核实的手机提交一次 Esc，必须到达大世界。已核实的指南、每日实训、生存索引、委托、邮件或无名勋礼允许先返回一步，只有双帧核实落在手机后才允许再按一次 Esc。差分区域及指南内的「乐园漫记」详情、战斗、登录、剧情、付费和领奖弹窗、活动未知离页或其他未核实状态均停止。已发送但反馈不明时保留原动作回执。此目标用于正式任务流，批量页面核对维持原有目标清单与回执格式。

离线对照包括历史普通大世界、差分区域、手机和其他菜单。差分区域能匹配原右上锚点，左上布局和普通大世界不同。正式 CLI 用脱敏历史 HUD、手机和邮件帧在假 Win32 验证零输入、一次及两次 Esc，以及发布前失焦保留发送记录。当前客户端返回仍待实机验证。[历史帧来源](../autohsr/tests/fixtures/workflow_world/sources.json)

每次 Esc 的按下与松开均获 Windows 接受后，才核对下一页。若松开未获确认，程序只再尝试一次松键，保留本次动作待核对并结束步骤。

### 无名勋礼页签

任务流的「切换到游戏页面」可选「无名勋礼 · 奖励」`battlepass_rewards` 或「无名勋礼 · 任务」`battlepass_tasks`。泛目标 `battlepass` 仍接受已打开的任一页。两个明确目标支持简中 4.6.0，须从已核实的手机或勋礼页开始。从手机打开勋礼后先核对实际落在哪一页。只有需要切换时，才点两帧一致的目标页签一次。已在所选页时零输入。报告中的 `target`、`source_page`、`destination_page` 区分两页。

两个明确目标优先用标准模板寻找唯一页签。任一来源帧出现分离的多个合格匹配时停止切换，保留已经发送的动作。仅当标准模板没有合格匹配时，960×540 和 1280×720 才按基准图中的裁片位置将同一模板对齐缩小，再用原有 `0.94` 门限匹配。这两档尺寸还须核对当前页的白色选中线，并确认另一页签没有选中线。标题、版式、选中线或目标图标的证据冲突时停止导航。

离线复读了 10 月 24–25 日的 9 张勋礼历史帧和 2 张奖励弹窗，以两种插值缩到上述两档尺寸。36 组页签正例均通过，8 组弹窗均被拦截。遮挡、相邻图标和错选中线另作对照。正式 CLI 在两档尺寸以假 Win32 和合成账号各验证一批页签点击及双帧到达。历史帧缩放和原生小窗口的渲染条件有差异，当前客户端的实际小窗口切换仍待验证。[任务页样本](../autohsr/tests/fixtures/du_runtime/bp_tasks_claimable.json) · [本期任务样本](../autohsr/tests/fixtures/du_runtime/bp_period_settled.json) · [奖励页样本](../autohsr/tests/fixtures/du_runtime/bp_rewards_claimable.json) · [模板来源](../assets/ATTRIBUTION.md)

9 张历史原帧的标准模板匹配保持原位置和得分。两种页签分别用同一搜索区内的两个不重叠模板副本作为反例，正式 CLI 在假 Win32 中均停止于切页前，保留零输入记录。

### 漫游签证收集展示

在任务流编辑器选择「切换到游戏页面 → 漫游签证收集展示」，或将 `workflow_open_page` 的 `target` 设为 `"visa_collection"`。从 4.6.0 前台手机主菜单开始。已在收集展示时，同账号连续双帧核实后零输入完成。若手机「更多」已经展开，先手动回到手机主菜单再启动本步骤。

流程先点「更多」，确认同账号连续两帧均为展开后的菜单，才点其中的「漫游签证」。到页时核对标题、副标题、规则入口及收集页签的选中状态。原生报告的 `workflow_navigation.actions` 分别记录两段输入与到页结果。首段待核对时不会提交第二段。角色展示、领奖提示或异常弹窗会停止导航并保留已有回执。全程只操作这两个导航入口。

三月七 YAML 的 `switch_screen` 加 `target_screen: visa` 会导入这个目标。原生任务流已通过假 Win32 验证两段点击、零输入核对及异常停止。当前客户端的完整任务流路径仍待实机验收。[YAML 转换](march7th-workflow-yaml.md) · [签证版式来源](../autohsr/tests/fixtures/daily_visa/sources.json)

### 漫游签证角色展示

在任务流编辑器选择「切换到游戏页面 → 漫游签证角色展示」，或在 JSON 使用 `workflow_open_page` 的 `target: "visa_characters"`。保持简中 4.6.0 客户端前台。可从手机主菜单依次点击「更多」「漫游签证」和「角色展示」，每段输入和到页均独立核对。若签证直接打开角色展示，则在该页核实后结束。从收集展示开始只点一次页签，从角色展示开始零输入。

角色页签选中且同账号两帧均核实「支援角色」「星海同行」后才记到页。出现领奖提示、转到战绩或反馈待核对时，保留已发送的动作并停止。支援奖励领取与到账另行核验。

```json
{
  "version": 1,
  "name": "切换漫游签证角色展示",
  "steps": [
    {"id": "visa", "type": "task", "task": "workflow_open_page", "params": {"target": "visa_characters"}}
  ]
}
```

用 `python -m autohsr --task-workflow visa-characters.json` 运行上面保存的文件。只读支援观察继续使用 `--daily-reward-observe support`。

4.6 公开图在 1280×720 和 1920×1080 回放中通过版式识别。960×540 缩小图的整帧 OCR 会把左上标题读成「温游签证」。任务流仅在页签、所选副标题和规则入口完整时重读这处标题，角色页还须保留右侧双锚。两种缩小回放均通过默认阈值，配置 0.93 时线性样本保持待核对。连续切页目前用假窗口回放。实机最小采样为同一个已登录的 4.6.0 原生 960×540 窗口，分别采集收集与角色展示的两张稳定帧，再采一张标题或目标页签受遮挡的对照。[签证版式来源](../autohsr/tests/fixtures/daily_visa/sources.json)

### 成就总览导航

`workflow_open_page` 的「成就总览」对应 `achievement_overview`。简中 4.6.0 下，从已核实手机菜单最多点一次成就入口，再核对同账号两张总览新帧。已在总览时零输入。仅有标题、分类页和奖励面板都保留待核对。成就领取继续走独立入口。[原生观察与领取](../DAILY_FLOW.md#成就与漫游签证入口校准)

### 兑换码表单导航

`workflow_open_page` 的「兑换码表单」对应 `redemption_form`。简中 4.6.0 下，从已核实手机菜单先打开「更多」，再进入「兑换码」。每段核对新鲜同账号双帧；已展开菜单时只需要第二段，已在表单时零输入。停在表单，不填写兑换码、点击确认或读取原生兑换回执。兑换结果、购买提示及只见菜单残留文字均不算到页。[正式兑换入口](redemption-codes.md)

### 当前页面核对

「设置 → 工具 → 日常页面核对 → 当前页面」在用户手动切回前台后，只读核对当前页面。独立 CLI `python -m autohsr --screen-test` 要求游戏已在前台。手机、指南、每日实训、生存索引、委托、邮件、无名勋礼和奖励指南复用任务流的页面识别，成就总览、分类和奖励面板使用各自的布局证据。只有同一账号连续双帧一致并完成报告发布时的复核，才给出固定页名。报告不导出原图、OCR 内容或 UID。[成就领奖布局](../DAILY_FLOW.md#成就领奖布局核对)

### 核对所选页面

三月七的 `screen_test` 会实际切换多个页面并汇总结果。AutoHSR 的多页核对把用户选择编译为一次临时任务流，复用 `workflow_open_page` 的前台、账号和输入检查。桌面在日常页面核对中选择「核对所选页面」，先预览实际顺序，再启动并手动切回已登录游戏。CLI 可用以下独立命令。预览只编译，执行要求游戏已在前台。[三月七固定实现](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/base/screen_test.py)

```powershell
python -m autohsr --screen-check-plan phone mail odyssey reward_guide
python -m autohsr --screen-check-pages phone mail odyssey reward_guide
```

每页只选一次。活动页面放在末尾，两项都选时依次核对巡星之礼和奖励指南。奖励指南可从已核实的巡星之礼打开，两项的离页路线仍待校准。已在目标页时不发送输入。遇到首次待核对时，保留之前已核实的页面及已发送、发送不完整的动作计数，后续页面记为未执行。核对不会领取奖励、开战、建立资源预算或发送通知。

三月七在单页失败后尝试返回主界面，再核对余下页面。AutoHSR 中，若最后一步在写入启动意图时中断、父报告最终保存成功，先前核实页的回执仍可查看。本步到页和动作次数保留待核对，后续页标为未执行。人工恢复到已知页面后，可以显式选中仍需核对的页面另开一批，新一批按当次窗口和账号重新取证。[三月七失败处理](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/base/screen_test.py#L33-L42)

原页面核对保存为部分完成且还有未启动页面时，也可以使用 CLI 续查。选择本机 `runs` 中该批次的原 `report.json`，保留同目录的 `workflow.json`、`steps.jsonl` 和各子报告。程序交叉核对原顺序、已核实前缀和执行日志，只选尚无启动意图的后续页面。曾发生换号、主动停止、原报告和日志不一致时会拒绝续查。

```powershell
python -m autohsr --screen-check-resume-plan 'runs\原批次目录\report.json'
python -m autohsr --screen-check-resume 'runs\原批次目录\report.json'
```

预览只读本地文件。执行前先手动回到大世界并将游戏置于前台，程序用双帧零输入确认当前大世界，成功后才执行后续页面。续查生成独立报告，按本次账号重新绑定并在本批内保持一致，保留原批次的结果。

短信通知的入口来源与其他页面不同，桌面和 CLI 均需单独选择。CLI 可用 `--screen-check-plan messages` 预览，或用 `--screen-check-pages messages` 执行。

CLI 还可单独核对 `world`（大世界）、`visa_collection`（漫游签证收集展示）、`visa_characters`（角色展示）、`achievement_overview`（成就总览）、`battlepass_rewards`（勋礼奖励页）、`battlepass_tasks`（勋礼任务页）或 `redemption_form`（兑换码表单）。这些目标使用各自已校准的前台路线，暂不并入多页批次。兑换表单只核对到达，奖励页只核对页签。

```powershell
python -m autohsr --screen-check-plan visa_characters
python -m autohsr --screen-check-pages visa_characters
```

`--list-task-capabilities` 中的 `autohsr.screen_check_plan` 同步列出这些目标，使用相同的单页选择和预算检查。执行后只在匿名回执中显示目标、核对状态与动作计数。

音频支持 1 或 2 声道、8 或 16 位、8～48 kHz，文件最多 32 MiB、时长最多 120 秒。播放完成来自 Windows 驱动反馈。主动通知在桌面运行时显示本次最多步骤数和方案别名，授权后沿用冻结的方案版本。CLI 显式使用 `--workflow-allow-notify`。每次流程最多 20 个主动通知步骤。应用内定时暂未开放这项授权。通知正文留在流程文件及明确发往的渠道，运行回执只记结果及必要的匿名事实。[通知设置](notifications.md)

图片通知可在 `workflow_notify` 的 `params` 中填写 `{"profile":"my-smtp","message":"本次流程的图片","png":"selected.png"}`。JSON 中的相对路径以流程文件所在目录为准。运行时还须明确提供同一份 PNG 的路径和同一个已保存的 SMTP 方案。

```powershell
python -m autohsr --task-workflow 'D:\Workflows\demo.json' --workflow-allow-notify --workflow-notify-png 'D:\Workflows\selected.png' my-smtp
```

每次命令只能授权一个 PNG 与 SMTP 方案组合，以所选子树的启用步骤为准。命令行相对路径以当前目录为准。离线检查只解析字段和路径语法。执行时先核实启用 SSL 或 STARTTLS 的 SMTP 方案及普通本地 PNG，提交前再核对原配置版本和图片来源。所选图片步骤在桌面运行入口会提示改用命令行。[图片格式及去重规则](notifications.md#活动日历-smtp-附件) · [三月七通知步骤](march7th-workflow-yaml.md)

`daily` 节点显式填写 `"params": {"tasks": ["assignments"]}` 时，只处理已有的持续委托奖励。列车补给和登录附加奖励会阻止本步继续。核实当前账号、可用按钮和大于零的累积时长后，最多尝试一次领取。领取反馈中断或账号改变时，保留原证据待核对。回到委托页后，在两张新画面上复核同账号的原委托状态和累积时长归零。详见[每日流程](../DAILY_FLOW.md#执行顺序)。

`daily` 和 `plan` 的 `params.support_daily_only` 只接受布尔值。省略沿用当前设置，显式 `false` 仅关闭本次按需判断。显式 `true` 要求本次选中刷本、允许使用已有资源，且 `plan` 执行范围包含日常。实际借用仍由 `use_support` 决定。冻结参数不保存设置，借用与支付继续由原生日常核实。[按需支援](support-preferences.md#按实训需求借用)

差分节点设置 `"params": {"until_points": true, "runs": 3}` 后，`runs` 是本次新开局上限。该选项需要显式填写 `runs`，只适用于新开周期演算。积分满额可零局完成。达到上限仍未满时保留已核实胜利，任务返回部分完成并遵守原失败策略。附加红点领取仍由 `rewards` 单独指定，周期积分奖励保持独立。[差分积分目标](differential-universe.md)

原生周期积分运行写胜利与返回截图时，同时把原图摘要和本局标识写入局记录。任务树对照原报告、账本、证据清单和原图摘要，核对积分双帧及每局的胜利与返回。条件 `completed_runs` 只读取核实过的实际局数。证据缺失或不一致时，本步为部分完成，局数待核对，后续游戏步骤暂停。

任务树在接收积分结果、判断条件及进入后续游戏步骤时核对游戏周。接续满额结果的游戏任务沿用原游戏周，在原生检查点和发送输入前复核。父流程每次尝试提交最终报告也核对游戏周。跨周时将 `periodic_points_goal` 标为待核对，停止后续游戏输入，保留原报告、原周观察、已核实胜利以及已发生的后续操作及其回执。固定局数仍沿用原流程。

货币战争仍为标准A8财富造物主40开发流程，没有扩大超频、其他模式、资源授权或独立整局计数；历史0/10保持。流程中的差分仍由原生页面、预设与账本核验，不能因为任务树完成就宣称所有模式验收。

### 独立免费领奖

在现有任务树属性中选择「独立免费领奖」，再选择邮件附件或无名勋礼。也可在 JSON 中按需要排列两个步骤。

```json
{
  "version": 1,
  "name": "领取邮件和勋礼",
  "steps": [
    {"id": "mail", "type": "task", "task": "daily_free_attachment", "params": {"target": "mail"}},
    {"id": "pass", "type": "task", "task": "daily_free_attachment", "params": {"target": "battlepass"}}
  ]
}
```

预览把这两步计为两次独立免费领奖和零份日常预算。若同一路径中的普通日常或周常计划可能处理相同目标，编译会拦截。选择明确排除该目标的日常子集时可组合。两个独立步骤共享同一执行租约和账号核验，使用各自原生领取门禁。父报告在对应步骤的 `attachment` 字段记录目标、结果与已核实领取项目。

## 文件与控制步骤

UTF-8 JSON顶层为`version:1`、`name`、`steps`；不接受重复JSON键、NaN、未知字段、脚本或任意命令。每步有唯一`id`，由英文字母开头、后接字母／数字／下划线／连字符，最多64字符。可选`name`为显示名，`enabled`默认true。禁用步骤保留skipped结果。

| type | 专用字段 | 行为 |
| --- | --- | --- |
| `task` | `task`、可选`params/on_failure` | 顺序执行一次正式任务；失败策略默认stop，可选continue；不重试 |
| `wait` | `seconds`，0～3600 的有限数字，可用小数秒 | 可暂停／停止的主动等待；暂停期间不消耗所请求等待时间 |
| `if` | `condition` 或 `screen_condition`，`steps`，可选 `else_steps` | 按已知结果执行一个分支，未知条件停止 |
| `for` | `count/steps`，1～1000 | 固定有界次数；不接受上游0表示无限的行为 |
| `while` | `condition` 或 `screen_condition`，`max_iterations`，`steps`，上限 1～1000 | 每次重新核对条件。到上限后仍成立则为部分完成 |
| `break/continue` | 无 | 仅用于循环内，分别结束当前循环／进入下一轮 |
| `stop` | 无 | 明确停止流程，整体stopped |

条件形如`{"step":"daily","field":"daily_verified","op":"eq","value":true}`。只能引用树中前面出现的步骤结果；所引用分支本次没执行、步骤被禁用而字段未知、类型不一致时停止，不将缺值视作false。`step:"@last"`表示最近一次实际执行的task结果，可用于有界观察循环；普通控制步骤不会替换它。

条件字段包括 `status`、`daily_verified`、`completed_runs`、`victories`、`defeats`、`points_verified`、`rewards_verified`、`du_rewards_verified`、`image_found`、`text_found` 和 `page_verified`。`du_rewards_verified` 对应本次明确请求的红点。图文及页面字段对应已成功核实的观察或切换步骤。只有对应子报告确实存在且含该字段时才可比较，日常实训也须有执行证据。计数支持 `eq/ne/lt/le/gt/ge`，状态和布尔值支持 `eq/ne`。`completed_runs` 对应差分已完成数或货币战争已结束数，货币战争胜负另有 `victories` 和 `defeats`。

上限为1 MiB定义、256个节点、12层、最多10000次展开执行；禁用节点也计执行数量。每个可能路径最多一份日常预算、一个差分批次、一个CW批次；循环乘算，互斥分支取最大值。不能用两个daily步骤或for循环重复创建240预算。`plan`保守预留日常、差分与CW各一个所有者，不能再叠加独立同类任务；其10局预留值仅为静态最大值，不是实际请求或完成数。

## 实时画面条件

`if` 和 `while` 可以在每次求值时重新观察当前游戏客户区。将原来的 `condition` 换成 `screen_condition`，两者只能选一个。下面的条件在同账号新鲜双帧均匹配「继续」时成立。

```json
{
  "task": "workflow_game_text",
  "params": {"text": "继续", "region": [0.25, 0.35, 0.75, 0.85]},
  "value": true
}
```

可选 `workflow_game_text` 或 `workflow_game_image`，参数与正式图文步骤相同。`value: false` 只匹配已核实的未命中。出现遮挡、失焦、识别冲突或账号变化时没有布尔结果，两个分支都不进入。条件观察单独保存回执及来源摘要，记录阶段和循环序号，纳入静态执行上限。

`while` 每轮前重采，运行到上限后再独立检查一次。复核仍为真时记录 `limit_reached` 并结束为部分完成，已核实为假时自然结束。循环体明确 `break` 时直接退出。实时条件回执不替换 `@last` 的原生任务结果。应用内定时按游戏任务处理，启用时冻结图像条件使用的模板。ZIP 素材包同样包含实时图像条件引用的模板。

CLI 和定时要求游戏已经在前台。桌面手动运行时，如果第一个游戏步骤是页面切换或实时观察，会短时等待用户自行切回游戏。条件的窗口、几何、画面时效和输入代次一直核对到所选分支的首个启用步骤派发。之后各步骤沿用自己的门禁。

## 桌面操作

「新建草稿」在内存中准备一条默认关闭的持续委托步骤。勾选或取消「启用持续委托」会更新草稿的 `enabled` 并刷新 JSON 排版，可在文本区撤销。已显示的预算和单步校验随编辑失效。勾选后校验可见一份日常调用预算，该步骤的开拓力上限为 0。选择新路径并核实另存结果后，才可使用「运行已保存流程」。

「打开任务流」选择现有 JSON。通过校验且仅含一条明确指定 `daily` / `tasks: ["assignments"]` 的流程也可使用持续委托开关。其他流程可用「可视编辑…」或直接编辑文本。用「另存为」校验整棵树并保存到新路径，成功回读后切换到新文件。重名、校验失败或回读异常保留草稿。原件外部变化时可保留编辑另存，也可重新加载。

「打开任务流」也可选择三月七的 `.yaml` 或 `.yml`。支持的文件会转换成未保存草稿，另存为 JSON 并重新校验后才可运行。未适配的步骤会给出具体节点路径并保留当前草稿。格式、支持范围和上游实测见[三月七 YAML 转换](march7th-workflow-yaml.md)。

「导入 YAML 图文…」可明确选择 AutoHSR 的双帧图文语义，导入受支持的单目标查找与条件。可为纯文本通知另选一个已保存方案，默认不绑定。普通「打开任务流」仍按严格模式转换。两种入口均只生成草稿，运行通知需要另行授权。[原生图文适配](march7th-workflow-native-vision.md) · [通知迁移](march7th-workflow-yaml.md#纯文本通知)

可视编辑显示步骤、启用状态和执行路径。选中流程根、条件成立、否则或循环体可向对应分支添加步骤。选中步骤可编辑属性、添加同级步骤、调整同级顺序或移除。条件分支和条件循环可选前序步骤结果、实时图像或实时文字。前序结果分别填写字段、比较和值。实时条件在 JSON 中填写 `template` 或 `text`，并选择「已匹配」或「未匹配」。切换来源保留步骤编号及子分支。正式任务的高级参数也可用 JSON，新添加的正式任务默认禁用。

「切换到游戏页面」的目标可以在属性面板中直接选择。图像判断步骤和实时图像条件均可点「采集模板…」，打开本地磁盘上的普通 PNG／JPEG，或在提示后手动将已启动的游戏切到前台。框选后在当前流程目录内另存新的 PNG。程序校验裁片并回读摘要，再把相对路径填入当前节点。新草稿需先选定未占用的本地 JSON 另存位置。采集后仍需应用属性和草稿。当前编辑会话会记住采集来源，同一 JSON 重新加载后仍保留。要在本会话换目录另存，需为相关节点重新采集或明确编辑路径。保存的 JSON 沿用相对路径格式，跨目录分享可使用 ZIP 素材包。

编辑「每日任务」步骤时，可直接勾选持续委托、日常副本、每日实训、兑换码、邮件附件和无名勋礼。选择「使用配置中的每日任务」时，任务范围在运行时按当前配置确定。自选范围须勾选至少一项，日常副本旁标明会使用体力。勾选项和高级参数中的 `tasks` 同步，已有体力上限和支援偏好等字段随草稿保留。

编辑弹窗允许暂留空分支和待修正的引用，整棵树通过原编译器才可「应用到草稿」。应用后可在文本区撤销。取消只关闭编辑弹窗。按「应用并选中步骤」可把当前步骤路径带回指定步骤范围，之后仍需独立校验和另存。原范围为指定步骤时，应用改动后须重新选择路径或明确切回整棵流程。

打开时默认范围为「整棵流程」。切换为「指定步骤」，填写从 0 开始的路径（例如 `1/0`），再点「校验草稿」查看步骤名称和该范围的预算。条件节点的子序号先列 `steps`，再列 `else_steps`。修改路径、范围或草稿后需要重新校验单步。范围切回「整棵流程」即可使用原来的整树入口。

「运行已保存单步」要求当前草稿与保存版本一致，沿用下述 CLI 的 `--workflow-step-path` 语义。运行前重新核实文件版本、步骤路径和解析目录。选择其他目录作为另存位置时，显示该目录的预算预览，保存后须按新来源重新校验所选步骤。另存始终校验整棵树。定时的任务流目标也可填写步骤路径。

当前编辑会话采集并绑定的模板，在提交和工作线程启动前都核对文件身份与摘要。Windows 执行期间保持所选范围内的绑定模板只读。若同一路径的文件被替换，请重新采集或明确改选模板，再校验单步。

## 素材包

「导出素材包…」从已保存且与当前草稿一致的流程生成新的 ZIP。导出会遍历整棵任务树，包括禁用节点及条件的两侧，只收录节点明确引用的 PNG、JPEG 和 PCM WAV。包内用相对路径关联素材，并记录文件长度与 SHA-256。包含私有记录、通知配置依赖或其他非便携设置的流程会被拒绝。分享前可检查流程名称、文字条件和素材内容。

「导入素材包…」需要明确选择 ZIP 和一个新目录。导入校验归档成员、摘要与整棵任务树后发布目录，并打开其中的 `workflow.json` 草稿。运行仍由单独的操作触发。导入导出均保留已有目录和文件。

## 本地草稿接口

`WorkflowDraft.new()` 返回从禁用委托模板创建的独立草稿，初始 `source` 为 `None`。选择目标目录之前，校验预览以 AutoHSR 数据根目录为解析基准。

`WorkflowDraft.load(path)` 只打开用户明确选中的普通流程文件，用现有解析器和整树预算校验建立草稿。界面可修改 `draft.document`，再调用 `draft.validate()` 取得独立的 `Recipe` 和预算预留。选中步骤预览使用原 `selected_path` 语法。读取和校验只涉及定义及指定路径。[草稿后端](../autohsr/task_workflow_draft.py)

`draft.save_as(path)` 要求明确的新文件名和已存在的父目录。它重新校验完整树，沿用独占发布，确认磁盘回读字节后返回 `SavedWorkflow(path, sha256, recipe)`。保存结果与现有 `--task-workflow-check`、`--task-workflow` 使用相同的 JSON 格式。相对路径字符串保留，之后以新流程文件所在目录解析。界面可用 `draft.validate(destination=path)` 预览该目录下的解析基准。

已打开草稿的 `draft.source` 记录首次加载位置，`draft.dirty` 比较当前内容和打开时的内容或初始模板。成功另存后，界面如需切换当前文件，可按返回路径显式加载。来源发生外部变化时，可保留当前编辑并另选新文件。`source_is_current()` 同时比较原始字节与文件修订。

保存冲突由 `WorkflowSaveConflict.reason` 区分。原路径 `source_path` 提示另选名称，原路径已修改或丢失 `source_changed` 可引导重新加载或另存。已有目标及并发抢占为 `target_exists`。发布后回读无法核实为 `readback_changed`，此时保留草稿与目标现有内容。其他校验问题沿用 `WorkflowError`，磁盘故障按 `OSError` 提示。测试覆盖双进程竞争、外部晚创建、回读前变更及损坏原文件。[草稿验证](../autohsr/tests/test_task_workflow_draft.py)

## 用法示例

以下为说明，未执行游戏。保存为自己选择的UTF-8 JSON，例如`my-workflow.json`：

```json
{
  "version": 1,
  "name": "日常完成后周期演算",
  "steps": [
    {"id": "daily", "type": "task", "task": "daily"},
    {
      "id": "afterDaily",
      "type": "if",
      "condition": {"step": "daily", "field": "daily_verified", "op": "eq", "value": true},
      "steps": [
        {"id": "du", "type": "task", "task": "differential_universe", "params": {"runs": 1}}
      ]
    }
  ]
}
```

```powershell
# 只读流程定义，不加载config.json，不读取记录来源，不访问游戏
.\.venv\Scripts\python.exe -m autohsr --task-workflow-check my-workflow.json
# 显式执行，沿用当前设置，仍受原生账本和页面门禁约束
.\.venv\Scripts\python.exe -m autohsr --task-workflow my-workflow.json
# 仅执行第二个顶层节点里的第一个子步骤，不补做日常或父条件
.\.venv\Scripts\python.exe -m autohsr --task-workflow my-workflow.json --workflow-step-path 1/0
# 将已保存的流程和明确引用的素材打成新 ZIP
.\.venv\Scripts\python.exe -m autohsr --task-workflow-export my-workflow.json --workflow-bundle-destination my-workflow.zip
# 核实并解包到一个新目录
.\.venv\Scripts\python.exe -m autohsr --task-workflow-import my-workflow.zip --workflow-bundle-destination imported-workflow
# 将三月七 YAML 转成新的 AutoHSR JSON
.\.venv\Scripts\python.exe -m autohsr --task-workflow-convert-yaml workflow.yaml --workflow-json-destination migrated-workflow.json
```

序号从0开始，`/`与`\`等价；控制节点的子序号先为`steps`，再为`else_steps`。选中控制节点仍需本次前序结果，缺少时在输入前停止；选中叶子则按上游单步语义跳过父控制。整个文件仍做结构检查，但最大预算按选中子树计算。单独选中的break／continue无效，会在执行前拒绝。

`--task-workflow-check`只证明结构和静态预留合法，不读取实际设置或记录文件，不证明配置、页面或实际资源可用。执行入口额外检查本次配置，并在每个原生任务中重采当前画面、账号、窗口与玩法状态。

执行 `--task-workflow` 或 `--screen-check-pages` 时，若明确指定的 `--config` 文件不存在，命令以退出码 2 结束，未创建执行器或启动游戏。省略该参数时沿用默认配置。

### 只读能力目录

`python -m autohsr --list-task-capabilities` 输出当前内置的只读能力、各自版本、启用状态及参数和结果结构。目录包括所选页面预演 `autohsr.screen_check_plan` 和任务流校验 `autohsr.task_workflow_check`。CLI 与本地能力服务复用同一编译和预算规则。能力调用可传入结构化流程及所选步骤，校验过程不读取流程引用的素材、账号配置或游戏画面。宿主可单独停用任一能力，停用时调度会在编译前拒绝。

当前 CLI 默认启用这两项。目录与校验结果用于发现和预演，实际执行仍使用现有任务入口及其授权门禁。桌面持久化开关和 MCP 连接仍待接入。

## 执行权、停止与报告

最终报告写入失败时，桌面继续显示本次内存结果和运行目录，撤回「打开报告」链接。重启后若发现上次任务流只保存到运行中的快照，结果区标明「任务流仅有中间快照」，原文件可从运行目录另行查看。

`TaskWorkflowRunner(settings, document, emit, selected_path=None, base_dir=None)`提供`run/stop/toggle_pause`。UI提交草稿副本即可，不调用Settings.save。流程只执行一次，同一Runner第二次run拒绝；一次点击不自动重放整个树。

流程持有Windows命名执行标记，覆盖任务间隙；所有原生Runner及单独启动游戏入口检查归属，其他进程／线程不能借间隙启动输入任务。子流程仍独立持有原输入互斥、Context和专用账本。运行中的F9由原子任务处理；间隙仅在已知控制窗口前台响应F9；F10和界面停止跨阶段传递。本地记录服务的取消回调同步响应暂停停止。快捷键监听故障请求停止。

每次步骤先fsync写`steps.jsonl`意图和总报告，再创建／运行子任务；写入失败不执行该步。子任务finished不会变成父流程finished；只有父流程最终报告保存尝试后发送一次。逐步反馈为`workflow_step`，含step、sequence、status；原子事件另带`workflow_step/workflow_task`。

父报告位于本次`runs/<时间>_workflow_<随机ID>/report.json`，同目录保留`workflow.json`定义快照及SHA-256。`workflow.steps`记录每次执行、分支、循环轨迹、状态、条件事实和原子报告路径／哈希；时间、局数、胜负及真实消耗分别保留，不改写原子报告。原子任务的返回结果须与对应已保存`report.json`一致，才能进入下一项。匿名记录工具另存本地子报告。

失败默认停止。`on_failure:"continue"`可用于后续本地分析、等待或分支；若失败来自游戏任务，后续任何游戏任务均被阻止，即使前者已核实部分实训。整体仍为partial，不用后续本地成功覆盖旧失败。未知报告、保存失败、停止、条件未知均不触发重试；已经保存的日常、消耗和CW胜负不会因后续失败丢失。

### 停止意图与未保存报告

2026-10-30补统一的只读布尔`stop_requested`，由原生Runner、PlanRunner、CurrencyLoopRunner、TaskWorkflowRunner及NotificationRunner公开；它表示已经请求协作停止，独立于最终报告status。共享[run_control.stop_requested](../autohsr/run_control.py)只接受严格的runner `True`或原报告字符串`status=stopped`，不把`1`／`"true"`等真值近似当作证据，不修改报告，也不调用输入。

计划／循环／任务树合并当前子Runner的意图，并在返回边界或清理当前child前锁存；原生Runner、计划与CW循环捕获Stopped异常时也显式请求stop。任务树的`_notice_stopped`在原报告来源核验及后续落盘前先传递子任务的stopped／只读停止意图；即使子报告未保存、来源不符或父报告保存失败而使整体成为partial，这个控制意图仍保留。原来源错误、未核实状态和旧报告继续记录，不能为了传播停止把partial／unknown改成已核实stopped。

[应用内定时](schedules.md)的正式adapter保留该控制意图，兼容只读`schedule_stopped`来源提示；调度器在返回／异常后，以及tick认领下一due之前观察自有Runner的严格布尔，先停止未来计时并清pending，再核对来源或结果落盘。NotificationRunner还合并自身通知阶段stop，因此游戏报告仍success、通知cancelled时也能停止未来计划，不必等网络返回；实际run退出仍须等待。写回执失败保持unknown／pending，不再次触发。内部stop_owned替换已有job.cancel来源，不误当作用户全局停止。

控制器停止不改写已核实结果：完整count1的slot／attempt仍可为success，另记reason=controller_stopped；有限重复只完成一部分则为partial并保留completed计数，原子stopped仍stopped、unknown仍unknown。这个布尔不证明原游戏结果、资源或报告保存成功，界面须分别呈现控制器状态、slot／attempt、原游戏报告及通知结果，并等待原run实际退出再解锁。

此前两项任务树回归覆盖未保存child stopped不被来源错误盖掉停止意图，以及父报告保存失败仍保留停止标记，所在191项快照通过`runs/schedules-cw-auto-related-final.log`（9.707秒）。统一控制链的最终相关244项通过`runs/schedules-control-complete-related.log`（10.469秒），另核对正式通知Graph在fake网络held期间公开stop后，不认领下一due、原success报告字节不变及完整slot成功保留。旧故障注入复现`runs/schedules-stop-receipt-reproduction.json`保留，记录修复前“child已停止、slot unknown但controller仍运行”的问题；最终全量结果另见本轮[定时验证](schedules.md#验证记录与剩余边界)，不借用旧全量快照。

当前没有流程断点自动恢复或后台续跑，流程本体不自带定时器；可由默认关闭、明确启用的[应用内调度器](schedules.md)调用。重新执行文件是一次新执行，不能当作旧预算的接续；应先查看原子报告，再使用原差分／CW／领奖接续入口核对未完成步骤。跨步骤统一账号约束另已接通：两帧新鲜证明、暂停重核、原证据检查与日常预算延后建立，见[账号连续性](workflow-account-continuity.md)。现有各子流程核验仍保持，完整多账号配置切换尚未交付，真实组合仍待验收。

## 2026-11-06 持续委托可视开关

39 项相关测试和 10 项隐藏 Tk 检查通过。专项核对开关同步、文本撤销、缩放、原文件保留、取消与单步校验失效。保存后沿正式入口用假 Runner 核对任务范围，预算预览为 0 开拓力。实际桌面前台交互待验收。

## 首版验证（531da85）

后续账号连续性及当前版本检查见[账号连续性验证](workflow-account-continuity.md#验证与限制)；以下保留任务树首版记录。

最终新增29项[专项检查](../autohsr/tests/test_task_workflow.py)，与计划、正式日常恢复、CLI及记录功能合计84项最终相关检查通过`runs/task-workflow-final-scope-related.log`（1.715秒）。包括真实原生日常协调器＋假Context、跨线程／独立进程执行权、意图与报告失败、重复预算、未知条件、停止与暂停、while上限、单步执行及真实本地虚构记录分析／JSON导出。没有访问真实游戏、真实Player.log／缓存或账号接口。

28项专项时的1721项全量快照通过`runs/task-workflow-all-final.log`（802.487秒）；源文件哈希为`runs/task-workflow-full-snapshot.json`。随后收紧非对应任务／未执行实训的默认false条件，仅修改条件事实提取并新增1项检查；最终版本由上述29项专项所在的84项相关回归覆盖，未将1721写成最终1722项全量通过。

原GUI84项假后端检查通过`runs/task-workflow-gui.log`。独立进程运行正式CLI的本地“分析→分支→导出”及第二次已有输出拒绝通过`runs/task-workflow-cli-verification.json`：配置、输入和定义原件保持，长ID文本保留，匿名事件与父报告原件一致。固定来源、引用函数、许可、相对链接、文档JSON示例与CLI帮助核对见`runs/task-workflow-source-verification.json`。这些检查不代替真实GUI或游戏验收。

早期两版专项失败保留在`runs/task-workflow-first.log`、`runs/task-workflow-second.log`，跨线程测试夹具修正前的失败保留在`runs/task-workflow-scope.log`。首次全量在修正日常继承规则后主动终止，原`runs/task-workflow-all.log`为不完整记录，不作为全量通过证据。

尚未验证：新GUI操作、真实跨玩法组合、真实CW整局，以及上游底层流程功能。未新增游戏样本、图像模型或训练数据；没有重新开启旧十场目标。
