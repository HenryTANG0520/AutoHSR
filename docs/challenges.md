# 高难计划与备战

2026-11-06 更新。三种高难都可离线核对明确双队计划。混沌回忆和虚构叙事接入首个目标层的有限原生备战，末日幻影可只读观察关卡详情和节点备战。独立结算入口可核对虚构与末日的部分可见反馈。完整选角、通关与结算校准仍在开发。[上游接入研究](march7thassistant-challenge-integration-2026-10-30.md) · [开发清单](development-roadmap.md)

用户已明确允许仅这三种高难按明确角色名单编双队，见[开发约定](../AGENTS.md)。日常、差分和饰品等既有预设规则继续保留。配置中的明确名单不证明角色已拥有、解锁、可用或实际入队；本轮原生流程尚不选择角色。

2026-11-01用户提供队伍预设名及强度顺序：“哈哈哈哈 → 记忆 → 组一辈子列车 → 神主日”，越左越强。此处记录为后续选队偏好，不把预设名当成四名角色或猜测成员；当前`ChallengePlan`仍要求两队各四名明确角色。尚待核实这些预设的实际成员、形态、两队是否重复、可用及完整入队反馈，再接入高难执行。没有据此改写已保存配置或启动游戏。

2026-10-23 的脱敏饰品回放可核实历史「哈哈哈哈」已启用，四人为火花、爻光、银狼LV.999、真珠。「记忆」也有四个可见头像，目前只达到遐蝶与缇宝两名历史候选的模板门槛。四队当前成员、实际可用状态和高难入队仍需在本次校准中核对。[历史启用画面](../autohsr/tests/fixtures/du_runtime/planar_preset_enabled.png) · [预设历史记录](differential-universe.md)

## 明确计划

[ChallengePlan](../autohsr/challenge_plan.py)只接受四个JSON字段：

| 字段 | 要求 |
| --- | --- |
| `mode` | `memory_of_chaos`、`pure_fiction`或`apocalyptic_shadow` |
| `levels` | 包含起止层的两个整数；混沌1～12，虚构／末日1～4，起层不大于终层 |
| `team1`、`team2` | 每队明确四个固定角色ID或唯一完整中文名，不猜别名、不自动补队 |

未知字段、缺少字段、布尔／字符串层数、空或带控制字符的名字、未知／不唯一名称、同队与跨队重复的规范ID均拒绝。另拒绝下述5组已核实皮肤与本体重复；精确皮肤ID仍保留在不可变元组及`to_dict()`中，`digest`仍为具体计划的SHA-256，不把皮肤替换成本体。已有[105幅头像目录](../assets/upstream/March7thAssistant/support/sources.json)只提供固定ID和完整名字，不证明账号拥有、可用或实际入队。没有秘技、失败重试、购买或领奖授权字段。

[单位去重](../autohsr/challenge_identities.py)只采用有限显式对应关系，三种模式的同队与跨队检查一致。官方正文分别明确这些外观所属角色；2026-11-05读取官方CMS完整`sContent`，文章编号及内容SHA-256记在该模块，不依据相似名字或头像猜测：

| 本体／外观ID | 依据 |
| --- | --- |
| `March7th`／`March7thNascentSpring` | [3.0更新说明](https://hsr.hoyoverse.com/en-us/news/127987?type=activity) |
| `Firefly`／`FireflySpringMissive` | [3.4更新说明](https://hsr.hoyoverse.com/en-us/news/157441) |
| `Castorice`／`CastoriceGossamerFlutter` | [4.2更新说明](https://hsr.hoyoverse.com/en-us/news/163625) |
| `Hyacine`／`HyacineWarmCottonSkies` | [4.6更新说明](https://hsr.hoyoverse.com/en-us/news/166468) |
| `Evanescia`／`EvanesciaLunarBlossoming` | [4.6更新说明](https://hsr.hoyoverse.com/en-us/news/166468) |

这不是完整单位关系表。开拓者／三月七的命途互斥及其他未核实外观继续保留缺项，不按前缀或剧情身份归并；丹恒／饮月、停云／忘归人、黑塔／大黑塔等不同目录项也不据叙事名称合并。未被此表拒绝，只说明计划结构可接受，仍须运行时核实实际单位与两队完整性。

以下八名角色只是说明格式的示例，不是本账号名单或默认编队：

```json
{
  "mode": "memory_of_chaos",
  "levels": [7, 12],
  "team1": ["Firefly", "RuanMei", "Fugue", "Lingsha"],
  "team2": ["Acheron", "Jiaoqiu", "Pela", "Aventurine"]
}
```

`challenge_plan={}`表示未配置，明确保存时才持久化。三种模式都接受非空计划校验，独立备战入口接受`memory_of_chaos`和`pure_fiction`。该入口目前经 CLI 执行。[Settings](../autohsr/config.py)

## CLI与原生范围

[独立 CLI](../autohsr/challenge_cli.py)提供计划预览、主页导航、有限备战和结算观察。

```powershell
python -m autohsr --challenge-check .\my-challenge.json
python -m autohsr --challenge-lobby apocalyptic_shadow
python -m autohsr --challenge-prepare --challenge-plan .\my-challenge.json
python -m autohsr --challenge-result
```

`--challenge-check PATH`只读取所选UTF-8 JSON，最多64 KiB，拒绝重复键与非有限数；先于运行配置加载和Runner创建分流，不联网、不访问游戏、不保存配置。不能与`--config`、通知或运行选项混用。它输出规范计划与摘要，不证明账号角色或页面可识别。

`--challenge-lobby MODE` 接受 `memory_of_chaos`、`pure_fiction` 和 `apocalyptic_shadow`。从已经在前台的生存索引、逐光捡金或同模式主页起步。生存索引使用局部图标，逐光捡金使用左侧模式项、右侧详情名和同区域的唯一传送。每步最多提交一次，必须在同账号、同窗口、同代次的相邻新帧核实到达。到页及最终报告均复核已保存的原证据；证据改变、错模式、遮挡或超时保留原记录。此入口的完成条件为指定主页。选层、备战、战斗与领奖各有独立边界。[实现](../autohsr/challenge_lobby.py) · [校准与验证](../VALIDATION.md#2026-11-06-高难指南与主页导航)

4.6.0 当前账号的末日幻影传送后进入「支配遗忘」星启主页。该布局用星启模式、更换编队及三个独立节点同时确认。主页上的历史击败标记仅属于页面观察。

`--challenge-prepare`要求游戏已打开在计划对应的高难页面。混沌回忆和虚构叙事可以从主页核实首个目标层，也可直接核对已打开的同层备战。末日幻影只观察已在前台的页面，沿用 F9／F10 控制。`--challenge-plan PATH`只覆盖本次，也可使用已明确保存的非空计划。独立备战排斥刷本、资源、新预算、其他玩法和接续参数，继续检查未完成的货币战争周常与领奖记录。[独立 CLI](../autohsr/challenge_cli.py)

本轮只核对`levels`起层，完整范围保留在冻结计划中。混沌与虚构先取得当前账号与同一目标的两份新鲜画面。当前原件和页锚支持时只点击该层一次，随后取得两份同模式、同层的备战反馈。已打开的同层备战页直接观察。每次输入在专用入口重新推导当前目标，核对账号、输入代次、冻结计划和本次落盘意图，同时复核原 PNG 字节、像素、尺寸、采集时刻及运行归属。[Context 入口](../autohsr/app.py)

窗口检查结束后，点击前再核对目标、落盘意图与原截图，并在读盘后检查画面是否超龄。其间目标、原件或记录失效时停止，保留本次待核对意图。

混沌与虚构的页面探测与选层反馈各自在 30 秒活动时限和 100 次采集上限内观察。两阶段遇到空帧都会核对运行状态和输入代次，随后从晚于该空帧的画面重新组成配对。选层反馈须晚于点击发送完成时刻，暂缺完整账号、重复或倒序时间戳会打断其连续计数。核实成功需要同一账号、同一输入代次的连续两张当前层备战画面。已有备战和刚选层两路均在第二张证据写盘后复核当前状态，最终记录在每次实际替换前再次核对窗口、页面、账号、画面时效、输入代次和原活动时限。共享锁重试期间失效会保留观察，已提交的选层保持待核对。明确换号、多个完整账号候选、模式冲突、暂停或计划变化会中止原选择的核验。[实现](../autohsr/challenge_prepare.py)

备战与槽位对照共用高难账号门禁。绑定账号仍须达到 `max(0.85, OCR 采集阈值)`。在原 UID 区域，达到采集阈值的完整字段会参与冲突判定，多条完整字段或与已绑定账号不同的完整字段均停止。初始观察、选层发送前和最终回执写入前都使用这条规则。异区文字、不完整字段及低于采集阈值的读数不参与。[账号门禁](../autohsr/challenge_account.py)

未知、动画、重复capture、失焦、账号／计划／代次变化、写盘失败或超时不重发选择。私人`run_dir/challenge-preparation.json`及`RunReport.challenge`保存原意图、页面来源和反馈；旧文件不覆盖，未核实选择保留`unknown`。最外层运行结束通知只沿用明确启用的通知配置，将任务标为“高难备战”，不公开名单、账号摘要或截图；本轮没有实际发送。

## 页面与证据

[challenge_pages](../autohsr/challenge_pages.py)的`observe()`返回`Observation(kind, mode, level, half, stars, targets, basis)`；`target(scene, "select_level", level=N)`从当前完整观察返回唯一导航Token或`None`。完整当前层标题与列表中的某个层号是不同来源，第一项不能充当当前选中层。

### 混沌回忆

主页需要固定模式局部图与对应 OCR、独立`N/36`字段和关卡区域内至少两份不同层号。每个层号独立核对金色星形，只有绑定正星来源的层号才可作为选层目标。没有正星匹配时，该行星数与可用态保持未知。备战用独立当前层、固定模式文字图及两队数字、重置、交换的相互关系补证。[局部图与来源](../assets/upstream/March7thAssistant/challenge-ui/README.md)

### 虚构叙事

主页需要左上固定标题图和完整 OCR，以及关卡区域内至少两个不同且互不重叠的`01`～`04`标签。每层从该标签起点的 120×120 区域核对原始圆点和上游金色规则。与其它层搜索带共享的星点不计入。只有目标层自己的正星证据才开放一次选层。快速解锁、周期「开启故事」、已读的锁定和冲突页面都会阻止导航。开启故事原图可在文字漏读时阻断导航。正星来自历史分数，角色可用与当前层仍各自核实。[固定上游选层源码](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/purefiction.py#L85)

备战由右下「进入故事」图文、同列上下两个队伍数字和上游范围内唯一的重置或交换原图共同支持。层数只接受角色列表右侧、编队控件上方的唯一完整「第 N 层」字段。半角与全角数字使用同一语法，同一行相邻的分词可合读，采用片段最低置信度。采集阈值内的第二个完整字段即使数值一致，也会使层数保持未核实。上游没有给出虚构备战标题的实机字段位置，当前限定区按角色列表和编队控件的分区设置。缺少完整层号时只能观察`team_setup`且`level=None`。已打开的同层备战可走原生只读核验，两帧都须独立读出计划首层。[固定上游备战源码](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/purefiction.py#L134)

### 末日幻影

计划模式为 `apocalyptic_shadow` 时，独立备战只读核对常规「支配遗忘」的当前页面。每次运行观察一个已打开的页面，前台失效即中止。页面字段取自对应区域，允许相邻分词和全角数字。正向 OCR 证据须达到 `max(0.85, OCR 采集阈值)`。末日备战单独保留达到 0.65 的较低置信度页面反证，以识别叠加的异模式、提示和冲突字段。[末日备战识别](../autohsr/challenge_apocalyptic_prepare.py)

| 页面 | 回执证据 |
| --- | --- |
| 主页 `lobby` | 左上模式、中央「支配遗忘」和「前往挑战」，以及按位置排列的 `01` 至 `04` 难度卡。「未解锁」仅在读全的对应卡内有效。原生选中态保持未知。 |
| 首领信息 `boss_info` | 左上模式和副标题、同列的数字与「难度」、完整的节点一或二及首领名、页尾「本期不再提示」。尾按钮文案单独核实，截断的「前编队」保持未核实。 |
| 已挑战总览 `played_overview` | 左上模式、中央「支配遗忘」、同排「常规模式」和右侧「更换编队」。两个节点各有标签和同排分数，分数和须等于唯一金色细线对应难度卡的旧分。常规 04 已用原片校准。 |
| 固定队伍节点详情 `locked_node_detail` | 独立的难度与完整首领行、「当前队伍」和「不可更换」、同排「角色详情」及右下「前往挑战」。回执保存可见节点及难度是否与计划首层相符。 |
| 双节点备战 `node_setup` | 左上「末日幻影／编队」、左侧「支配遗忘」、中上「角色编队」、同列上下两个节点及其首领名。难度从左侧徽标独立读取。缺读可保存页面，难度留空。若读到「角色详情」，须与页尾「前往挑战」同排。 |

解锁浮层、活动更新、星启标记和确认遮挡均保留为未核实。「快速通关」只接受底部难度卡的文字。「前往挑战」分别与当前页锚核对。现有入口只核实按钮文案，原生按钮可用性与输入目标待另行验收。既有固定模板的只读详情与槽位探针仍可单独调用。

固定队伍节点详情读取 `01` 至 `03` 的字段语法，真实素材校准在常规 03。该页的首领行位置与首次首领信息不同，低置信度、缺字、错位或冲突均保留为未核实。回执的期名留空，难度和首领行仍须独立核实。常规 04 原片可由前序总览追溯模式，单独打开的 04 固定队伍详情仍需能够区分星启的页内证据。[星启模式官方说明](https://www.taptap.cn/moment/809481781068696810)

固定上游的已挑战分支从层号和右侧「更换编队」进入共用的「下一步」及「前往编队」，并在编队页提交「前往挑战」后检查清空提示。4.6 常规 04 原片有一条直接进入同层备战的路径，后续提交出战才出现清空提示。[固定上游关卡流程](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/apocalyptic.py#L130-L152) · [固定上游出战分支](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/apocalyptic.py#L241-L256) · [常规 04 转场](#2026-11-06-末日常规-04-换队转场)

末日流程最多尝试 8 次页面观察，使用 30 秒活动时限。配对需要相邻的采集序号、严格递增的时间、独立图像缓冲和证据文件、同前台窗口几何、同账号与同输入代次。两帧各自读出的页面字段及位置须相符。空帧、UID 缺读、助手遮挡或页面变化均打断配对。达到 0.65 的完整 UID 候选可阻止回执发布，账号绑定仍需达到原正向阈值。回执及最终报告在替换时复核原 PNG 哈希、识别像素、窗口几何、字段与账号。最终报告核验失败时保留先前回执和原图，最终报告降级为待核实。

主页、首领信息、已挑战总览、固定队伍节点详情和未匹配首个目标难度的备战页记 `page_observed`，父报告为 `partial`。只有两帧独立读到计划首个难度的双节点备战页，才记 `preparation_page_verified=true`。`page_observation` 记录页面、难度、可见节点和两张带采集序号、窗口坐标、OCR 框及哈希的 PNG 引用。固定队伍节点详情另记 `team_editability=locked` 和 `matches_plan_level`。总览另记 `visible_selected_level`、`matches_plan_level`，逐帧保存选中线和历史节点分。末日只读运行的 `actions` 为空，执行层的 `selected_level` 留空，队伍成员和挑战进度待核实。[回执实现](../autohsr/challenge_prepare.py)

### 候选与结果

成功备战仅记`preparation_page_verified=true`；`team_verified`、`battle_started`、`completion_verified`仍为false，半场和完整挑战结果未知。`TaskResult("challenge_prepare", "ok", ...)`和父报告success只说明这个有限准备任务完成，不增加战斗完成、挑战星数或奖励计数。

2026-11-05新增列表候选观察。混沌和虚构的原生备战流程仅在保存已核实同模式备战页时，将`candidate_list`附入来源`basis`。105 幅既有完整头像逐份核对固定 manifest、SHA-256、Git blob 和尺寸，使用固定上游列表裁剪范围，保留身份、完整框与模板来源。残缺、遮挡及过期画面排除，跨素材重叠匹配保留歧义。[列表候选观察](../autohsr/challenge_roster.py)

列表候选的`ownership`、`availability`、`selected`、`complete`均为`unknown`。混沌与虚构使用上游`BaseChallenge.select_characters`的 1920×1080、xywh`(30,115,530,810)`。末日的独立候选探针采用`(30,110,550,850)`。常规 04 的正式回执以右侧圆槽核对占位，左侧名单另作候选证据。[列表候选实现](../autohsr/challenge_roster.py)

### 槽位与双队对照

`observe_setup_roster(scene)`先核实备战页，再分别读`candidate_list`和`team_slots`。混沌和虚构在保存备战帧时将两项附入回执。这一路的通用槽位布局待真实采样，缺布局时标为`missing_slot_calibration`。固定上游头像只证明所匹配的素材身份。角色可选性仍须独立状态证据。[槽位实现](../autohsr/challenge_slots.py) · [固定上游队伍列表](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/basechallenge.py#L70) · [固定上游末日控件](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/apocalyptic.py#L193)

末日常规 04 从正式 `--challenge-prepare` 的相邻两张原图核对槽位。两张都须读到计划首个难度 04 和两个节点标题。`page_observation.team_slots` 按 `node_order=[1,2]` 排列上下两队，每队从左到右四槽，交互焦点 `selected_node` 留空。圆槽须在两帧保持共同的几何位置。`occupied` 需要环缘和覆盖槽内主体的头像纹理，`empty` 需要环缘与暗底小人符号。裁切、遮挡或两帧不一致的槽为 `unknown`。候选角标、首领圆控件和编队预设各有独立区域。报告发布沿用两张原图的读锁、哈希、账号及前台复核。[常规 04 取证](#2026-11-06-末日常规-04-双队槽位)

`eight_slots_occupied` 只记物理占用。明确空槽可证实未满，缺读则保留未知。圆槽的角色身份、形态、可用性和名单匹配均需另外证明。完整占用时 `eight_identities_known` 留空，`team_verified` 保持 `false`。[只读回执](../autohsr/challenge_prepare.py)

常规 04 的 `page_observation.candidate_slot_transition` 需要同一次观察的六张相邻采集。先读到完整 04 备战，再采到名单中角标出现前、角标出现而槽仍空、同槽出现头像三帧，最后取得两个已关闭名单且难度可读的 04 画面。名单页有两个节点标题、独立的活动栏轮廓和已选「角色列表」；其中难度字段留空。开头已有两张稳定备战画面时，入口按原流程完成页面观察。任一阶段漏读、失焦、活动节点冲突或中断均不能形成时序回执。[时序实现](../autohsr/challenge_apocalyptic_transition.py)

左侧只核对停稳名单中同一完整卡片和唯一新增的「队伍1／2」角标。检查文字框、横贯卡片的白条及相邻卡片变化，另一白条即使漏读文字也可阻止发布。右侧须在对应活动节点唯一出现从空到占用，其他槽保持可核实的一致状态，返回两帧须与名单最后的同槽头像相符。六张来源均随报告复核。时序记 `badge_before_occupancy`、节点、槽序、返回头像及采集来源，身份与可用性留作独立证据。[原片和反例](#2026-11-06-末日常规-04-候选入槽时序)

合成校准将槽位绑定到当帧所属队伍或节点的标题。每队须有四个完整、互不重叠的槽框，并与候选列表分离。已占槽须有槽框内的完整头像匹配，明确空槽须有独立空位标记。缺读、裁切和冲突保留未知，多个身份同时命中时保留候选歧义。已占槽也不推导该角色当前可选。

`compare_roster_frames`用采集方提供的相邻序号、输入代次和冻结计划摘要绑定两帧，再分别核对首个目标层与同账号。末日还须明确请求的节点，并在两帧各自独立读到该节点。扫描结束复核像素、页面、锚点和账号。相同静态像素可来自两次独立采集，复用缓冲区或时间戳、序号间断、换号、错层和错节点均不能形成对照回执。返回值只含页面与槽位事实，账号核验在本地完成。

两帧分别核实的物理占用、精确身份、队伍成员和槽位顺序用不同字段记录。已确认空槽意味着八槽不完整，缺读保持未知。同队成员对调可使`team_members_match`为真而`slot_order_match`为假。身份按计划里的精确 ID 比对，已核实的同单位关系只用于拒绝重复。`duplicate_unit`的否定范围限于固定身份表。完整的合成比对结果仍为只读，备战回执中的`team_verified`保持未核实。[合成回归](../autohsr/tests/test_challenge_slots.py)

#### 实机最小补证

| 范围 | 需要保留的脱敏区域 |
| --- | --- |
| 混沌、虚构和末日 | 同层两张连续新帧，保留模式、当前层、两个队伍或节点标题与八个完整槽框。提供明确入槽头像及至少一个同类槽位的正向空位标记。 |
| 角色可选状态和形态 | 同一角色卡的可选与禁用对照，保留禁用标记或原因。皮肤、命途和同名形态需保留可区分的实际槽位样式或完整标识。 |
| 末日节点 | 分别在节点一、节点二激活时保留当前关卡、活动节点标记及其槽位归属。若节点切换改变可见槽框，保留切换前后对应区域。 |

当前公共裁片可能遮住上方层号、末日节点或虚构底部入口。采集时按覆盖诊断核对所需区域，同账号与采集连续性在本地验证。[采集说明](interface-calibration-2026-11-05.md)

19 幅页面局部原件和 4 幅结算反馈原件均固定到上游`7cf6c6bed474539485d3b1504077ac352866829f`，保留作者 moesnow 及其贡献者、GPL v3 与游戏美术权利说明。来源清单记录原路径、尺寸和哈希。[素材说明](../assets/upstream/March7thAssistant/challenge-ui/README.md) · [来源清单](../assets/upstream/March7thAssistant/challenge-ui/sources.json) · [GPL v3](../assets/upstream/March7thAssistant/LICENSE)

## 独立结算观察

`--challenge-result` 从已在前台打开的窗口只读采集，最多八次外层读取，失焦即结束。仅接受 `--config` 与 `--game-path` 覆盖。观察源为当前画面，局部回执独立保存到本次 `challenge-result.json` 及 `RunReport.challenge_result`。同账号、同窗口、同代次的相邻新帧需看到相同反馈，空帧、漏读和采集层丢弃的助手遮挡帧会断开配对。[实现](../autohsr/challenge_result.py)

Windows 发布回执时持有两张 PNG 的只读句柄，发布最终报告时同时持有回执和两张 PNG。每次共享锁重试都复核原文件、帧时效和输入代次，并在 OCR 和读盘之后查询实际前台。暂停与停止监视持续到最终报告发布结束。最终复核失败时报告与 CLI 保留 `unknown`，已写回执及原证据留存。普通 OCR 沿用配置阈值，账号正向确认仍要求至少 0.85。仅高难结果将配置阈值过滤掉但达到 0.65 的完整 UID 留作冲突反证。账号仅在本次内存核验中使用，公开裁片仍需去 UID。[复验记录](../VALIDATION.md#2026-11-06-高难结算来源复核)

一般控件反馈以「返回虚构叙事」「前往节点二」「返回末日幻影」的唯一局部原件及同位置完整 OCR 核对。普通混沌与普通末日终局还可使用下述完整布局核对。出现异模式结算原件或支付、确认领取等遮挡迹象时保留未核实。「前往节点二」只记文字所指去向，单独出现时模式也保持未知。红色「败」字是可见标记，需与模式专属返回控件同帧。固定上游的判断分支也在不同战况复用返回或节点去向控件。混沌与常驻回忆共享「返回忘却之庭」，需按本期混沌布局的同屏字段区分。[虚构结算判断](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/purefiction.py#L184-L204) · [末日结算判断](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/apocalyptic.py#L268-L294) · [混沌结算判断](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/memoryofchaos.py#L176-L203)

双帧核实模式反馈后 `challenge_result.status=feedback_verified`，只有去向文案时为 `caption_verified`，证据不足时为 `unknown`。成绩按下述已校准布局发布。实际半场、已到节点、胜负与最终结算分别留空或为 `unknown`，`completion_verified` 和 `rewards_verified` 为 `false`。运行状态为 `partial`，CLI 退出 1。已有主页星数仍属于主页历史观察，备战回执仍由 `--challenge-prepare` 独立记录。[反馈入口验证](../VALIDATION.md#2026-11-06-高难结算只读反馈)

### 本期虚构与混沌节点二入场

4.6 已校准的 16:9 入场画面有上中深色横幅「节点二」，以及左上场内 HUD 的当期期名和完整读数。横幅两翼须符合画面中的明暗边界，两个同账号相邻新帧须读到相同字段与对应位置。上中小字有完整的冲突读数时，场内 HUD 也保持未核实。核实后回执为 `entry_verified`，将横幅节点与 `displayed_current_score` 或 `displayed_remaining_rounds` 写入 `node_entry`。虚构可凭本期「取象为文其四」核实该字段内的第四层。混沌左上 OCR 会把十一层或十二层读成十，当前只核实「物竞天择」期名，层号留空。[脱敏字段、裁片位置与哈希](../autohsr/tests/fixtures/challenge_node_entry_4_6.json)

常规虚构原片上半末尾只有战场内的「剩余0轮」提示，随后直接切场。05:47.000 和 05:47.300 的节点二入场读到当前积分 25,840，横幅消失后同一积分仍留在 HUD。其真正终局另显示两个节点和总分 65,840。常规混沌 02:19.800 和 02:20.200 的节点二入场读到剩余 30 轮，终局也有 30 轮。两种读数分别属于入场 HUD 和终局结果。[虚构上半末尾](https://www.bilibili.com/video/BV1Qxnz6nEUB/?t=345) · [虚构节点二](https://www.bilibili.com/video/BV1Qxnz6nEUB/?t=347.3) · [虚构终局](https://www.bilibili.com/video/BV1Qxnz6nEUB/?t=912.2) · [混沌节点二](https://www.bilibili.com/video/BV1oG4h6UEVo/?t=139.8) · [混沌终局](https://www.bilibili.com/video/BV1oG4h6UEVo/?t=280)

星启同名节点二也用此横幅及场内 HUD。公开对照分别读到虚构 40,000 分、混沌 43 轮。当前回执核实现场的玩法、横幅和读数，常规或星启、前一侧胜负、实际出战、结算与领奖继续分别待核实。上游普通流程同样在前一间等待下一间准备画面，最后一间等独立返回反馈。[星启虚构节点二](https://www.bilibili.com/video/BV1g8nj6JEyi/?t=171) · [星启混沌节点二](https://www.bilibili.com/video/BV1Ht4F6MEG5/?t=272) · [上游普通虚构](https://github.com/moesnow/March7thAssistant/blob/26bee153544db44a882313f361b5ddbcefb001fa/tasks/challenge/purefiction.py#L202-L227) · [上游普通混沌](https://github.com/moesnow/March7thAssistant/blob/26bee153544db44a882313f361b5ddbcefb001fa/tasks/challenge/memoryofchaos.py#L207-L226)

### 战斗波次观察

4.6 已校准的画面同时显示上中「战斗开始」与形如 `1/3` 的完整波次、同屏「通关目标」或「特殊机制生效中」，以及底部同排至少两个队伍血条。相邻两张同账号新帧的波次和 HUD 文案须相同，且至少两个对应血条位置重叠。回执为 `wave_observed`，把 `current_wave` 和 `total_waves` 写入 `battle_wave`。缺少斜线、血条被特效遮挡、只有战斗 HUD、转场或终局均不能单独生成波次字段。[原片字段、HUD 裁片和哈希](../autohsr/tests/fixtures/challenge_battle_wave_4_6.json)

同一普通虚构录像的节点一和节点二均显示 1/3。普通混沌节点二显示 1/2。各自的节点归属可由录像中的先前入场画面回看，当前两张战斗帧只核实波次。玩法、节点、出战来源、秘技实际生效与最终战果分别保持待核实。出战归因需在同一运行中绑定账号、已核实节点、本次动作及动作后的新画面。[虚构节点一战斗](https://www.bilibili.com/video/BV1Qxnz6nEUB/?t=12.5) · [虚构节点二战斗](https://www.bilibili.com/video/BV1Qxnz6nEUB/?t=361) · [混沌节点二战斗](https://www.bilibili.com/video/BV1oG4h6UEVo/?t=161.4) · [虚构秘技画面](https://www.bilibili.com/video/BV1Qxnz6nEUB/?t=353) · [弱点转场](https://www.bilibili.com/video/BV1Qxnz6nEUB/?t=355)

### 本期常规混沌剩余轮

4.6 本期「物竞天择」的已校准 16:9 版式须同屏出现居中关卡标题、独立「挑战成功」、单列轮数和「剩余轮」、左侧三行普通星级目标、底部居中「返回忘却之庭」。相邻两张新帧须读到相同轮数和相互重叠的对应字段框。核实后回执记录 `remaining_rounds` 与返回控件。普通终局的奖励栏属于独立内容。识别到「节点二」交接、星启、历史详情、确认弹窗或冲突字段时保留未核实。[4.6 官方排期](https://www.taptap.cn/moment/853326330178046059)

十一层原片的 02:19.800 和 02:20.200 是第二队入场，04:40 与 04:47 的终局均为 30 轮。另一场十一层在 03:42.800 与 03:43.300 均为 29 轮，整屏 OCR 两次都漏掉标题末字「一」。常驻回忆终局也可同时显示「挑战成功」「剩余轮」「返回忘却之庭」。原片只在本地做去 UID 裁片校准，仓库记录字段、时间和哈希。[十一层交接](https://www.bilibili.com/video/BV1oG4h6UEVo/?t=139.8) · [十一层终局](https://www.bilibili.com/video/BV1oG4h6UEVo/?t=280) · [29 轮原片](https://www.bilibili.com/video/BV1AK4c6GExo/?t=222.8) · [常驻回忆终局](https://www.bilibili.com/video/BV1L7uG6QENm/?t=79.2) · [脱敏字段与哈希](../autohsr/tests/fixtures/challenge_chaos_result_4_6.json)

十、十一层的 `level` 和 `stars=3` 使用同一对新帧中的独立画面证据。层号逐字核对居中标题内「十」的交叉笔画与独立末字「一」。每一颗实得星须在对应星级目标左侧呈稳定金色，并匹配已校准的轮廓和位置。回执分别保存数字字形框与三项星标框。灰星、过曝闪光、标题缺笔或两帧字段冲突时，仍可发布已独立核实的剩余轮。稳定 0 至 2 星、其他层号及失败或重打版式继续留作待核实。[十层稳定三金](https://www.bilibili.com/video/BV1wT4c6rEyX/?t=257.9) · [十一层稳定三金](https://www.bilibili.com/video/BV1AK4c6GExo/?t=222.6) · [同场灰星与闪光](https://www.bilibili.com/video/BV1wT4c6rEyX/?t=257) · [主页历史星数](https://www.bilibili.com/video/BV1wT4c6rEyX/?t=266) · [视觉证据坐标与哈希](../autohsr/tests/fixtures/challenge_chaos_result_detail_4_6.json)

### 普通虚构总分

常规「取象为文其四」的结算页须同屏出现底部居中的模式返回锚、上方关卡标题和独立的「挑战成功」。再读标题下方的「积分」原数及同一横栏左右两列的「节点一」「节点二」。各列须由完整标签与相邻数值组成。各节点上限为 40,000，两个分项相加须等于原读总分。合并识别与同一行的 OCR 分片均可核实，数字分片须有规范千位逗号。星级目标和历史详情各自留在原页面范围。[4.6 积分修复公告](https://www.taptap.cn/moment/853651354927762083)

同一对相邻新帧须读到相同的两列分项和总分，且对应文字框重叠。只在本次回执和最终报告的现有证据核验内填入 `total_score`。数字漏读或歧义时，同一对新帧中已核实的控件反馈仍可发布，总分留空。发布重试发现来源已变时，最终报告回到未核实。[总分验证](../VALIDATION.md#2026-11-06-普通虚构本局总分)

公开校准源为 `BV1Qxnz6nEUB` P1，CID `42925294535`。05:47 的节点二入场显示累计 25,840。15:10 为积分动画，15:12.200 与 15:12.500 的完整结果显示节点一 25,840、节点二 40,000、积分 65,840。原片用于核对字段位置，仓库用合成布局与固定上游返回素材。末日星启 10:20 的「挑战结束」及累计分同「前往节点三」并存，属于中间结算。[节点交接](https://www.bilibili.com/video/BV1Qxnz6nEUB/?t=347) · [虚构终局](https://www.bilibili.com/video/BV1Qxnz6nEUB/?t=912) · [末日中间结算](https://www.bilibili.com/video/BV1pq4K6xEg7/?t=620)

### 普通末日双节点终局得分

4.6 常规「支配遗忘」终局在「挑战结束」下显示「积分」及两个节点的分数，底部同排显示「重新挑战」和「返回末日幻影」。两行节点各自核对左侧标签和右侧数值，两个分数相加须等于原读总分。普通节点交接、星启、历史详情和冲突字段会拦住分数发布。连续两张同账号新帧须读得相同的三个数值，且对应文字框重叠。

可复核结果写入 `node_one_score`、`node_two_score` 和 `total_score`。完整布局通过时，回执可用这两个当前 OCR 控件作来源，按实际来源标记。公开的 17:30.650 与 17:31.000 分别读到 3,223、3,505 和 6,728，07:41.600 的节点一结束、07:45 的节点二入场及星启画面作对照。层号、星数、胜负和领奖仍待实机核对。[常规终局](https://www.bilibili.com/video/BV1VxJ266ErP/?t=1050.65) · [节点交接](https://www.bilibili.com/video/BV1VxJ266ErP/?t=461.6) · [星启终局](https://www.bilibili.com/video/BV1pq4K6xEg7/?t=900) · [脱敏字段和原裁片哈希](../autohsr/tests/fixtures/challenge_apocalyptic_result_4_6.json)

### 4.6 星启终局显示

星启自 4.3 加在各玩法最高难度，可用三支队伍分别挑战节点，各节点可单独重打。三月七启动器固定提交 `26bee153` 的混沌、虚构、末日入口分别传最高关 12、4、4。共享流程先以常规处理范围内的较低关，范围包含最高关时进入星启与第三队。其模式选择逻辑区分同时显示两种选项的菜单和仅显示当前模式的画面。混沌与虚构的模式入口在右上区域，末日使用居中的下方入口，末日三队角色列表采用数字节点。上游首次开场和节点间点击各有独立流程。[官方星启说明](https://www.taptap.cn/moment/809481781068696810) · [共享星启流程](https://github.com/moesnow/March7thAssistant/blob/26bee153544db44a882313f361b5ddbcefb001fa/tasks/challenge/stellar.py) · [混沌入口](https://github.com/moesnow/March7thAssistant/blob/26bee153544db44a882313f361b5ddbcefb001fa/tasks/challenge/memoryofchaos.py) · [虚构入口](https://github.com/moesnow/March7thAssistant/blob/26bee153544db44a882313f361b5ddbcefb001fa/tasks/challenge/purefiction.py) · [末日入口](https://github.com/moesnow/March7thAssistant/blob/26bee153544db44a882313f361b5ddbcefb001fa/tasks/challenge/apocalyptic.py)

4.6 原片中，混沌十一层返回主页后显示十二层与星启已开启提示，随后备战列出三个节点。虚构主页的四层晶体下可见历史积分与星数。末日主页下方显示所选星启模式、三个节点和 04 的历史成绩，节点详情各有自己的节点号。这些页面各自作为结算错页对照。模式双选项菜单的当前原片、三队编队和出战流程仍待独立校准。[混沌星启提示](https://www.bilibili.com/video/BV1cg4c6zEsh/?t=205) · [混沌三节点](https://www.bilibili.com/video/BV1cg4c6zEsh/?t=214) · [虚构最高层主页](https://www.bilibili.com/video/BV1jEnE6vELU/?t=2) · [末日星启主页](https://www.bilibili.com/video/BV14QHH6YESx/?t=1098)

独立结果入口在当前已校准布局同屏核对星启标识、期名关卡、结果标题、三个节点字段及底部「重新挑战」和玩法返回文案。两个相邻新帧的数值和对应位置均一致时，独立写入 `stellar_result`。混沌十二层的剩余轮为 35，三节点耗轮分别为 2、1、7，核对合计 45。虚构四层为 104,960，三项为 39,560、40,000、25,400。末日难度 04 为 10,780，三项为 3,454、3,635、3,691。末日展开的伤害和剩余行动值属于节点分项的明细。普通结果沿用各自原有字段。[混沌终局](https://www.bilibili.com/video/BV1Ht4F6MEG5/?t=1187) · [虚构终局](https://www.bilibili.com/video/BV1uBx96ME2j/?t=548) · [末日终局](https://www.bilibili.com/video/BV1u8Hp6qE8f/?t=1054.1) · [脱敏字段、坐标与哈希](../autohsr/tests/fixtures/challenge_stellar_result_4_6.json)

虚构单节点重打后也可显示三项累计分。`stellar_result` 记录当前页面显示的挑战记录，遇到中间页、主页历史、少行、冲突与模式选择时留空。连续三队通关、棱彩星与领奖各需独立证据。[虚构单节点重打](https://www.bilibili.com/video/BV1uBx96ME2j/?t=239)

### 4.6 星启节点去向

同一对相邻新帧须核实星启标识、本期期名关卡、「挑战结束」、左侧三个节点标题，以及同排底部「退出」「重新挑战」「前往节点一／二／三」。回执在 `stellar_handoff.destination_node_in_caption` 记录右侧按钮文案所指节点，并保存各字段的画面位置。末日分项展开及混沌、虚构的中间页存在不同的滚动位置，按已校准布局核对。空帧、漏行、异模式、返回按钮、冲突文案及遮挡会使这一字段留空。常规的 `destination_node_in_caption` 和星启的 `stellar_result` 沿用各自的证据。[脱敏字段、坐标与哈希](../autohsr/tests/fixtures/challenge_stellar_handoff_4_6.json)

末日第三节点的录像在结束页只显示第三行的 4,000 分，底部写「前往节点一」。另一场录像中的两次交接分别写「前往节点二」与「前往节点三」，展开的分项对应不同的节点。单独重打一、二节点的终局仍显示另外两节点的已有分数，底部改为「重新挑战」「返回末日幻影」。分项和展开行可承载历史分数，正式入口保留刚完成与实际抵达的节点为未知，运行状态仍为 `partial`。[末日去往节点一](https://www.bilibili.com/video/BV1vDHt6tEEH/?p=3&t=191.2) · [末日去往节点二](https://www.bilibili.com/video/BV19Bpx6QEKX/?t=287) · [末日去往节点三](https://www.bilibili.com/video/BV19Bpx6QEKX/?t=630.8) · [重打节点一](https://www.bilibili.com/video/BV1vDHt6tEEH/?p=1&t=225.4) · [重打节点二](https://www.bilibili.com/video/BV1vDHt6tEEH/?p=2&t=328.4)

本期混沌十二层与虚构四层各有节点二和三的交接原片。上游共享流程从正在执行的节点序号指定预期按钮，并继续核实下一节点备战。此入口只观察当前结果页面，实际进场、出战、胜负、积分及领奖按各自门禁处理。[混沌去往节点二](https://www.bilibili.com/video/BV1Ht4F6MEG5/?t=265.4) · [混沌去往节点三](https://www.bilibili.com/video/BV1Ht4F6MEG5/?t=567.4) · [虚构去往节点二](https://www.bilibili.com/video/BV1g8nj6JEyi/?t=167.5) · [虚构去往节点三](https://www.bilibili.com/video/BV1g8nj6JEyi/?t=320.4) · [上游等待与交接](https://github.com/moesnow/March7thAssistant/blob/26bee153544db44a882313f361b5ddbcefb001fa/tasks/challenge/stellar.py#L210-L269)

下一次原生画面校准需要下列证据，保留模式、层号、分项标题及原相对位置，导出时遮盖 UID 与无关个人信息。每个用于核实的状态留同账号连续两帧。

| 模式 | 所需的最小页面证据 |
| --- | --- |
| 虚构叙事 | 同层上半结束、下半接续、最终总览。总览保留两半得分、总分、星数和结束标识。另留失败或主动退出对照 |
| 末日幻影 | 首节点成功与失败反馈、节点二实际到达、最终总览的两节点分、总分和星。已挑战详情单独留历史分字段作对照 |
| 混沌回忆 | 当前客户端的同层上下半交接、不同剩余轮和重打版式、失败结算。保留本次实得星和逐项目标 |

领奖可用与已领取状态各需独立页面证据。现有入口的边界为观察当前结果反馈。

## 验证与未完成项

### 2026-11-06 末日常规 04 候选入槽时序

`BV1P1Ho6sETd` P1 在 29:04.814／29:05.064 显示可读的常规 04 和节点二第 3 槽旧头像。29:06.668 出现下排活动轮廓，随后左侧角色名单盖住难度徽标。29:07.345 至 29:07.380 的相邻原帧中，旧头像移除，对应候选也失去「队伍2」。29:07.630 的同一位置空槽完整可见。[名单打开与卸下](https://www.bilibili.com/video/BV1P1Ho6sETd/?p=1&t=1744)

29:10.303 的可见候选卡还没有队伍条。29:10.338／29:10.374，左卡已出现「队伍2」，右侧节点二第 3 槽仍空。29:10.409 首次出现新头像，29:10.695 仍在同槽。29:11.194 已出现 04 文案，名单残影和下排轮廓尚未消退。29:11.372／29:11.550 独立读到 04，且保持名单内的同一圆槽头像。正式假窗口按阶段抽取六张原帧，来源索引保留完整秒值、有效客户区和哈希。[角标领先及返回](https://www.bilibili.com/video/BV1P1Ho6sETd/?p=1&t=1750) · [验证记录](../VALIDATION.md#2026-11-06-末日常规-04-候选入槽时序)

固定头像库的离线筛查中，这段录像的目标方卡和圆槽都最接近基础砂金 `Aventurine`，圆槽粗排为 0.849，同库次名 0.644，`AventurineWaveflair` 为 0.393。不同采样范围的方卡到圆槽排名会变化，附近画面仍缺能绑定该槽的姓名或命途。运行时回执将角色身份和形态保留为未知。许可待核的去 UID 画面、比较数据和相邻帧哈希仅保存在本地取证目录及 `runs/candidate-transition-qa/`。[固定素材来源](../assets/upstream/March7thAssistant/support/sources.json)

### 2026-11-06 末日常规 04 双队槽位

`BV1P1Ho6sETd` P1 的 09:59.995／10:00.173 首次进入 04，28:24.828／28:25.007 换队后进入同难度，均显示上下各四个圆槽。28:27.252 至 28:27.287，节点一第 4 槽从头像变为带灰白小人符号的暗圆，左侧对应卡片的「队伍1」同步消失。关闭名单后，28:28.606／28:29.212 保留该空槽及难度 04。28:30.317 至 28:30.602 另见节点二第 3 槽清空。[首次备战](https://www.bilibili.com/video/BV1P1Ho6sETd/?p=1&t=599) · [换队及移除槽位](https://www.bilibili.com/video/BV1P1Ho6sETd/?p=1&t=1704)

同片 29:10.338／29:10.374 已出现「队伍2」候选角标，节点二第 3 槽仍显示空位，29:10.409 才出现头像。选角名单打开后遮住难度徽标，这段用于区分候选和入槽。可选与禁用的实际拒绝反馈待采样。米游社另一视频的角色详情可读「巡猎／三月七」和「智识／姬子·启行」，详情到具体圆槽的对应关系待核实。现有方形头像模板在公开圆槽帧上未达到精确身份门槛。[候选转为实际入槽](https://www.bilibili.com/video/BV1P1Ho6sETd/?p=1&t=1750) · [单角色详情](https://www.miyoushe.com/sr/article/78807463)

主片去顶部 26 像素录屏边框后为 802×454，保留当前难度、两个节点标题及圆槽区域。米游社独立来源 5.000／5.033 秒用于验证不同横向偏移的八槽布局。其左上标题区遮去发布者水印，布局测试单独补合成标题，按布局留出记录。上排绿字遮挡、星启 04 三排和清空提示保留为对照。原片时点、变换和哈希保存在独立树本地 `runs/regular04-slot-qa/` 及取证目录，素材再利用许可待核。[独立布局](https://www.miyoushe.com/sr/article/78698476) · [字幕遮挡](https://www.miyoushe.com/sr/article/78807463) · [星启三排](https://www.bilibili.com/video/BV1quHC6rEmd/?p=1&t=8) · [离线验证](../VALIDATION.md#2026-11-06-末日常规-04-双队槽位)

### 2026-11-06 末日常规 04 换队转场

4.6「支配遗忘」连续原片为 `BV1P1Ho6sETd` P1，CID `42495905789`，2026-10-06 发布。28:06.012 显示双节点结算 3,830 分。返回后，常规 04 有金色选中线和 3,830 旧分，两个节点各显示 2,552 和 1,278，旁边的 03 另有 7,320 分。28:14 后先短暂打开节点二的固定队伍详情，画面显示「不可更换」。28:23.724 已回到同一个 04 总览，指针落在右侧「更换编队」，28:23.902 开始过渡，28:24.828 可读同难度双节点编队及底部两按钮。连续画面中直接进入备战。[常规 04 原片](https://www.bilibili.com/video/BV1P1Ho6sETd/?p=1&t=1686) · [换队时点](https://www.bilibili.com/video/BV1P1Ho6sETd/?p=1&t=1703) · [4.6 公告](https://www.taptap.cn/moment/853326330178046059)

同片 29:12.334 指针在备战页「前往挑战」，29:13.118 出现询问是否清空原队伍及节点积分的确认。录像随后回到编队，实际清空结果未知。另一个米游社原片在 15.500 秒同屏显示常规 04 选中、旧分 6,653 和「更换编队」。39.500 至 42.900 秒的剪辑保留总览、两页首领信息及 04 编队，可对照首领提示分支的页面顺序。[提交后的确认](https://www.bilibili.com/video/BV1P1Ho6sETd/?p=1&t=1752) · [独立常规 04 片段](https://www.miyoushe.com/sr/article/78807463)

正式入口分别复放总览的 28:23.403／28:23.724 和备战的 28:24.828／28:25.007。802×480 解码帧去除顶部 26 像素录屏边框，遮盖账号和无关区域，再按有效客户区缩放。去边框的未遮盖原帧也可识别总览。备战初段的难度徽标有低置信度，28:28.606 和 28:29.212 的完整客户区可读出难度 04。原片来源、时点及裁片哈希留在独立树本地 `runs/played-evidence-qa/`，素材许可待核。[定向用例](../autohsr/tests/test_challenge_apocalyptic_played.py)

错计划 03 的总览仍保留可见选中 04，并标记计划未匹配。跨页拼帧、清空提示、星启换队均无本次页面回执。01 至 03 的已挑战总览、当前账号的原生双帧、实际控件可用性、队伍与积分清空结果待实机取证。[离线验证](../VALIDATION.md#2026-11-06-末日常规-04-换队转场)

### 2026-11-06 末日常规固定队伍详情

4.6 常规 03 的节点一来自 P1 的 0.000／0.206 秒，节点二来自 P4 的 0.000／0.211 秒。P5 的 0.000／0.209 秒作邻近片段复放。公开 852×480 裁片保留难度、首领行、队伍锁定提示及底部两按钮，遮去其余区域后缩放到 1920×1080。实际 RapidOCR 经正式入口的假窗口生成固定队伍详情回执。P2 的难度标签置信不足，回执保持待核实。[常规双节点原片](https://www.bilibili.com/video/BV1MEJ164ELp/)

三份常规 03 终局回程的首个可辨认大厅分别在 04:25.367、07:05.600 和 06:41.002。它们都显示 03 的历史分和已选中的星启 04，常规 03 的选中及换队连续片段待补。4.6 公告另说明，重新登录后会默认选择当前已解锁的最高难度。[04:25 回程](https://www.bilibili.com/video/BV135xr6NEU6/) · [07:05 回程](https://www.bilibili.com/video/BV1Adno69EPD/) · [06:41 回程](https://www.bilibili.com/video/BV1E3Hp6SENy/?p=1&t=401) · [4.6 更新说明](https://www.taptap.cn/moment/853326330178046059)

星启 04 原片 P1 在 00:06.100 显示「更换编队」，随后在 00:07.900 进入三栏编队。另一原片 P5 的 00:48.000 显示提示，询问是否接受更换编队后重置对应关卡的成绩。两组均保留为错模式对照。[星启同名按钮原片](https://www.bilibili.com/video/BV1quHC6rEmd/?p=1&t=6.1) · [星启确认原片](https://www.bilibili.com/video/BV1E3Hp6SENy/?p=5&t=48)

### 2026-11-06 末日备战离线复放

4.6 常规 03 的连续素材取自同一视频 P1。主页用 20.500／21.000 秒，首领信息一用 22.400／22.800 秒，首领信息二用 27.500／28.000 秒，双节点备战用 30.267／31.000 秒。852×480 裁片遮去账号、水印及无关信息后缩放到 1920×1080，经实际 RapidOCR 和正式 CLI 的假窗口复放。四组均得到相应页面回执。首领信息二的两个尾按钮读数仍缺字。对照包括同源 18.500 秒解锁提示、14.000 秒更新页，以及另一视频 P1 开头的已挑战节点详情。三组在当时的识别版本均未发布页面回执。[常规 03 连续来源](https://www.bilibili.com/video/BV135xr6NEU6/) · [已挑战详情来源](https://www.bilibili.com/video/BV1MEJ164ELp/) · [活动公告](https://www.taptap.cn/moment/853326330178046059)

公开视频只作本地核对。仓库回归使用合成 OCR、合成账号和假窗口。本组覆盖常规 03 首次备战。当前客户端原生双帧、星启、实际可用目标和其他首次挑战难度待单独验收。[定向用例](../autohsr/tests/test_challenge_apocalyptic_prepare.py)

### 2026-11-06 备战账号冲突

在 `dc8b2cc` 用正式 CLI、Runner、Context 和假窗口复现四个反例。0.80 的第二个完整 UID 出现在已有备战首帧、次帧、选层前或选层后，四例均错误核实了备战，其中选层前一例还发出一次假点击。修复后初始冲突停止在选层前，发送前冲突保留已写入的选择意图和原图，反馈或最终回执冲突将已提交动作保留为 `unknown`。原基线日志留在本工作树的 `runs/high-roster-account-qa/`。[正式入口用例](../autohsr/tests/test_challenge_integration.py) [回执与发送前用例](../autohsr/tests/test_challenge_prepare.py)

**63 项定向回归通过**，其中正式备战与 CLI 39 项，槽位、虚构备战、候选证据和共享 UID 解析 24 项。账号专项 7 项为其中的子集，覆盖干净同号、单条 0.80 字段不足以绑定、明确换号、异区、截断及低于采集阈值的噪声。本批使用虚构标识、固定公开素材和假窗口。当前客户端的 UID 可读性、同层连续转场及真实双队槽位仍待实机核实。

### 2026-11-05 双队槽位对照

定向回归使用固定上游头像、合成槽位与空位标记、虚构账号和末日活动节点字段。公开脱敏的历史饰品预设只作错页反例。当前可在备战回执查看彼此独立的候选与槽位状态，实际高难八槽与角色可选性仍待上述最小样本校准。[定向用例](../autohsr/tests/test_challenge_slots.py)

阶段高难相关回归 123 项通过，日志为`runs/high-roster-qa/related.log`。最终加入按标题定位槽框后，槽位、候选、备战回执及 CLI 共 35 项定向通过，日志为`runs/high-roster-qa/final-focused.log`。两组范围重叠。

### 2026-11-05 虚构备战与末日观察

正例使用固定上游局部原图拼图、合成 OCR 和假窗口。既有脱敏饰品预设整图只作邻近玩法反例。当前仍缺虚构主页至备战的真实连续正帧、备战层标题及空队或禁用态，以及末日首次关卡详情与双节点备战的真实正帧。角色可用性、八个实际槽位、双队归属、增益和分数仍须另行校准。[专项测试](../autohsr/tests/test_challenge_modes.py)

独立工作树的 100 项高难定向回归通过，覆盖三种模式的页面观察、计划、CLI、同账号新帧、持久意图及列表候选。最后复核的 39 项页面与 CLI 检查通过，与定向回归范围重叠。运行日志为`runs/high-challenge-qa/related.log`和`runs/high-challenge-qa/final-pages-cli.log`，CLI 帮助与 19 幅固定原图来源均核对通过。实机正例和主线全量验收待中央整合。

独立复测发现最终备战记录可能在共享锁重试期间换代，虚构的拆词层号可能与完整层号并存，末日的相邻按钮文字也可能冲突。修复后在高难工作树复跑原 8 项独立探针和 112 项高难及原子写盘定向回归，均通过。新增检查覆盖正常重试、原活动时限、不同分词边界和末日按钮局部冲突。

下一轮独立复测发现首轮页面探测会跨空帧配对，也会漏掉全角数字的冲突层号。原样复跑两代探针共 12 项及本轮 76 项定向回归均通过，覆盖空帧后重新配对、旧帧重放、实际点击时间边界和混合宽度数字。当前冻结版的独立验收和真实客户端验证仍待完成。

### 既有混沌验证

19项计划纯检查通过；阶段25项配置／CLI／原生路由检查通过`runs/challenge-integration-first.log`（0.222秒）。首轮13项页面原件拼图通过后，审查发现原文父标题／引号、冲突层标题及低置信度阻断提示三个漏项，已分别补强固定原文组合、歧义与缺失分离、采集阈值阻断先于严格正锚筛选；18项页面检查通过`runs/challenge-pages-reviewed.log`（9.093秒）。不以最初合成夹具通过代替当前完整页面支持。

9项正式Flow／Context假IO检查通过`runs/challenge-prepare-first.log`（90.964秒），覆盖一次选层／同层两帧反馈、已有备战不输入、未知不重放、重复capture、错误层数／账号、epoch／失焦／计划变化、PNG被改及待提交写盘失败。阶段39项计划／页面／接线检查见`runs/challenge-boundaries.log`（5.623秒），在上述页面审查补强前；补强后的46项计划／页面／CLI／原生路由及两条正式Flow正向路径通过`runs/challenge-reviewed.log`（12.317秒）。这些分组有重叠，不累加独立用例数；最终全量结果以本轮结束日志为准。

随后核对发现角色目录工作区CRLF字节与Git索引LF字节不同；初版原始字节固定哈希会在不同检出方式下误拒目录。已将哈希统一为精确LF内容，分别测试LF／CRLF及内容被改的反例；27项计划与接线检查通过`runs/challenge-checkout-reviewed.log`（0.223秒）。为修复此问题主动中断首轮全量，原`challenge-all.log`、snapshot及`challenge-interruption.json`保留，916条完成记录不计全量通过；确认该轮测试子进程已退出后才启动最终轮。

实际CLI帮助及离线示例计划预览均退出0，分别为`runs/challenge-final-help.txt`、`runs/challenge-final-cli-preview.json`；后者输出`game_accessed=false`。没有执行实际`--challenge-prepare`命令。

最终**2071项全量通过**`runs/challenge-final-all.log`（1083.721秒），驱动退出0、总耗时1084.640秒；`challenge-final-full-result.json`及`challenge-final-full-snapshot.json`重新枚举334份Python／requirements与129份引用资源，完整清单与前后哈希一致，`snapshot_unchanged=true`。该轮覆盖上述页面补强及目录LF／CRLF修复，没有以中断轮或较早夹具结果充当最终快照。

提交前8份说明274处本地链接、60份固定树源码的Git blob／其中56份已声明SHA-256、GPL许可、14幅新增局部图及105幅既有头像、11份研究原件与85处原生文件引用核对通过，见`runs/challenge-final-verification.json`。角色目录的Git索引与工作区按LF内容一致，原始兑换码表字节保持；3个历史私人样本标签保留，不读取或公开原始样本，运行记录、用户配置和凭据未纳入版本控制。

完整角色列表与当前队归属、实际八人完整反馈、角色禁用／其余皮肤形态同单位、秘技与开怪、自动状态、上下半／节点转换、真实星数／分数与失败／退出／领奖，以及虚构增益和末日节点仍待实现。完整高难执行目标保持，不能因增加备战入口而改写为已完成。没有新实机截图、游戏输入、真实游戏进程／用户注册表访问、外部引擎运行、通知发送或EXE构建；原件拼图、模拟OCR和假IO都不是真实留出或完整无人接管验收。

## 后续无消耗采样的入口边界

`--check`只聚焦当前窗口并保存截图／OCR，现另从当前窗口的`current_executable()`读取安装配置`game_version`。`game_client`成功时仅增加`version`、`full_version`、`kind`、`sha256`及`status=verified`；缺失、歧义或不可读时为`unknown`，不回落到缓存路径或EXE的Unity版本。新游戏版本不阻断只读检测；其他游戏流程仍按自身版本规则处理。检测结果仍含完整OCR和私人证据路径，原件应留本地，模型只使用去UID裁片与必要非身份字段。

独立`--launch`仅启动／聚焦，不点击进入；`--currency-wars-prepare`及`--currency-wars-locate`包含登录月卡和登录奖励处理，不能直接当“不领奖”采样。`--challenge-prepare`必须先有明确八人计划，也不能填示例名单来解决四预设成员尚缺的前置采样。当前自动到全部目标页的无领奖导航仍缺，旧`live_probe`输入分支不经过Context，不作为替代入口。后续须先取得具体实机范围授权并与AutoZZZ交接；本次仅离线开发，没有执行这些访问游戏的命令。
