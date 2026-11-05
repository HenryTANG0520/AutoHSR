# 高难计划与备战

2026-11-05 更新。三种高难都可离线核对明确双队计划。混沌回忆和虚构叙事接入首个目标层的有限原生备战，末日幻影目前只提供页面观察。备战成功只记本次同层页面核实。完整选角、通关与结果仍在开发。[上游接入研究](march7thassistant-challenge-integration-2026-10-30.md) · [开发清单](development-roadmap.md)

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

[独立CLI](../autohsr/challenge_cli.py)提供两个入口。以下是用法示例，本轮没有执行访问游戏的命令：

```powershell
python -m autohsr --challenge-check .\my-challenge.json
python -m autohsr --challenge-prepare --challenge-plan .\my-challenge.json
```

`--challenge-check PATH`只读取所选UTF-8 JSON，最多64 KiB，拒绝重复键与非有限数；先于运行配置加载和Runner创建分流，不联网、不访问游戏、不保存配置。不能与`--config`、通知或运行选项混用。它输出规范计划与摘要，不证明账号角色或页面可识别。

`--challenge-prepare`要求游戏已打开在计划对应的混沌或虚构主页，也可停在本次首个目标层的备战页。流程复用当前窗口、前台及原 F9／F10 控制，范围限于高难备战。`--challenge-plan PATH`只覆盖本次，也可使用已明确保存的非空计划。独立备战排斥刷本、资源、新预算、其他玩法和接续参数，继续检查未完成的货币战争周常与领奖记录。[独立 CLI](../autohsr/challenge_cli.py)

本轮只处理`levels`起层，完整范围仍保留在冻结计划中供后续开发，不运行后续层。先取得当前账号与同一目标的两份新鲜画面；当前原件／页锚支持时只点击该层一次，随后取得两份同模式、同层的备战反馈。已有同层备战页只观察，不重新选层。每次输入在专用[Context入口](../autohsr/app.py)重新推导当前目标，核对账号、输入代次、冻结计划和本次落盘意图；原PNG字节／像素／shape、capture及run归属同时核对。通用点击和按键不能绕过此入口。

窗口检查结束后，点击前再核对目标、落盘意图与原截图，并在读盘后检查画面是否超龄。其间目标、原件或记录失效时停止，保留本次待核对意图。

反馈在 30 秒活动时限和 100 次采集上限内观察。加载帧暂缺完整账号、空帧及重复或倒序时间戳会打断连续计数。核实成功需要同一账号、同一输入代次的连续两张当前层备战画面。已有备战和刚选层两路均在第二张证据写盘后复核当前状态，最终记录在每次实际替换前再次核对窗口、页面、账号、画面时效、输入代次和原活动时限。共享锁重试期间失效会保留观察，已提交的选层保持待核对。明确换号、多个完整账号候选、模式冲突、暂停或计划变化会中止原选择的核验。[实现](../autohsr/challenge_prepare.py)

未知、动画、重复capture、失焦、账号／计划／代次变化、写盘失败或超时不重发选择。私人`run_dir/challenge-preparation.json`及`RunReport.challenge`保存原意图、页面来源和反馈；旧文件不覆盖，未核实选择保留`unknown`。最外层运行结束通知只沿用明确启用的通知配置，将任务标为“高难备战”，不公开名单、账号摘要或截图；本轮没有实际发送。

## 页面与证据

[challenge_pages](../autohsr/challenge_pages.py)的`observe()`返回`Observation(kind, mode, level, half, stars, targets, basis)`；`target(scene, "select_level", level=N)`从当前完整观察返回唯一导航Token或`None`。完整当前层标题与列表中的某个层号是不同来源，第一项不能充当当前选中层。

### 混沌回忆

主页需要固定模式局部图与对应 OCR、独立`N/36`字段和关卡区域内至少两份不同层号。每个层号独立核对金色星形，只有绑定正星来源的层号才可作为选层目标。没有正星匹配时，该行星数与可用态保持未知。备战用独立当前层、固定模式文字图及两队数字、重置、交换的相互关系补证。[局部图与来源](../assets/upstream/March7thAssistant/challenge-ui/README.md)

### 虚构叙事

主页需要左上固定标题图和完整 OCR，以及关卡区域内至少两个不同且互不重叠的`01`～`04`标签。每层从该标签起点的 120×120 区域核对原始圆点和上游金色规则。与其它层搜索带共享的星点不计入。只有目标层自己的正星证据才开放一次选层。快速解锁、周期「开启故事」、已读的锁定和冲突页面都会阻止导航。开启故事原图可在文字漏读时阻断导航。正星来自历史分数，角色可用与当前层仍各自核实。[固定上游选层源码](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/purefiction.py#L85)

备战由右下「进入故事」图文、同列上下两个队伍数字和上游范围内唯一的重置或交换原图共同支持。层数只接受角色列表右侧、编队控件上方的唯一完整「第 N 层」字段。同一行相邻的分词可合读，采用片段最低置信度。采集阈值内的第二个完整字段即使数值一致，也会使层数保持未核实。上游没有给出虚构备战标题的实机字段位置，当前限定区按角色列表和编队控件的分区设置。缺少完整层号时只能观察`team_setup`且`level=None`。已打开的同层备战可走原生只读核验，两帧都须独立读出计划首层。[固定上游备战源码](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/purefiction.py#L134)

### 末日幻影

`observe()`可从固定标题图、完整 OCR 和不同层号识别`lobby`。完整标题与右下独立「更换编队」可辅助识别已挑战关卡的`level_detail`。首次引导与开战都出现「前往挑战」。该文案单独出现，或在同一按钮区与「更换编队」并存时保留未知，含同一行的相邻拆词。[固定上游页面配置](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json#L980) · [固定上游关卡流程](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/apocalyptic.py#L130)

双节点备战`node_setup`需要两个不同的节点标题和上游限定范围内的重置图。它只记录可见节点标题，关卡、当前节点、角色可用与槽位状态仍未知。末日观察均无输入目标，`--challenge-prepare`会在创建 Runner 前拒绝末日计划。[固定上游节点准备](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/apocalyptic.py#L166)

### 候选与结果

成功备战仅记`preparation_page_verified=true`；`team_verified`、`battle_started`、`completion_verified`仍为false，半场和完整挑战结果未知。`TaskResult("challenge_prepare", "ok", ...)`和父报告success只说明这个有限准备任务完成，不增加战斗完成、挑战星数或奖励计数。

2026-11-05新增[列表候选观察](../autohsr/challenge_roster.py)。原生准备流程仅在保存已核实同模式备战页时，将`candidate_list`附入来源`basis`；主页、未知页和目标推导不扫描。105幅既有完整头像逐份核对固定manifest、SHA-256、Git blob和尺寸，使用固定上游列表裁剪范围，保留身份、完整框与模板来源。边缘残缺、遮挡及过期画面不作为正候选，跨素材重叠匹配完整保留歧义；没有支援列表行假设或徽章遮罩，也不产出点击目标。

输出的`ownership`、`availability`、`selected`、`complete`均为`unknown`，`execution_supported=false`。混沌与虚构的备战候选使用上游`BaseChallenge.select_characters`的 1920×1080、xywh`(30,115,530,810)`。末日另有候选工具的裁剪参考`(30,110,550,850)`，目前未接入正式任务。名单结构、候选身份、可用性、槽位与实际双队完成各自独立。[列表候选实现](../autohsr/challenge_roster.py)

19 幅局部原件均固定到上游`7cf6c6bed474539485d3b1504077ac352866829f`，保留作者 moesnow 及其贡献者、GPL v3 与游戏美术权利说明。来源清单记录原路径、尺寸和哈希。[素材说明](../assets/upstream/March7thAssistant/challenge-ui/README.md) · [来源清单](../assets/upstream/March7thAssistant/challenge-ui/sources.json) · [GPL v3](../assets/upstream/March7thAssistant/LICENSE)

## 验证与未完成项

### 2026-11-05 虚构备战与末日观察

正例使用固定上游局部原图拼图、合成 OCR 和假窗口。既有脱敏饰品预设整图只作邻近玩法反例。当前仍缺虚构主页至备战的真实连续正帧、备战层标题及空队或禁用态，以及末日首次关卡详情与双节点备战的真实正帧。角色可用性、八个实际槽位、双队归属、增益和分数仍须另行校准。[专项测试](../autohsr/tests/test_challenge_modes.py)

独立工作树的 100 项高难定向回归通过，覆盖三种模式的页面观察、计划、CLI、同账号新帧、持久意图及列表候选。最后复核的 39 项页面与 CLI 检查通过，与定向回归范围重叠。运行日志为`runs/high-challenge-qa/related.log`和`runs/high-challenge-qa/final-pages-cli.log`，CLI 帮助与 19 幅固定原图来源均核对通过。实机正例和主线全量验收待中央整合。

独立复测发现最终备战记录可能在共享锁重试期间换代，虚构的拆词层号可能与完整层号并存，末日的相邻按钮文字也可能冲突。修复后在高难工作树复跑原 8 项独立探针和 112 项高难及原子写盘定向回归，均通过。新增检查覆盖正常重试、原活动时限、不同分词边界和末日按钮局部冲突。冻结后的独立验收及当前客户端验证仍待完成。

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
