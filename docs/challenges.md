# 高难计划与混沌备战

更新日期：2026-11-05。完整混沌回忆、虚构叙事、末日幻影自动执行仍在开发。已有明确双队计划、离线计划核对，以及从已打开的混沌主页核实首个目标层并进入备战页的有限原生流程；本次补充有依据的皮肤单位去重及列表候选观察。不把备战任务成功写成通关、星数提升或奖励已领取。上游实现与缺口见[接入研究](march7thassistant-challenge-integration-2026-10-30.md)，全部功能范围见[开发清单](development-roadmap.md)。

用户已明确允许仅这三种高难按明确角色名单编双队，见[开发约定](../AGENTS.md)。日常、差分和饰品等既有预设规则继续保留。配置中的明确名单不证明角色已拥有、解锁、可用或实际入队；本轮原生流程尚不选择角色。

2026-11-01用户提供队伍预设名及强度顺序：“哈哈哈哈 → 记忆 → 组一辈子列车 → 神主日”，越左越强。此处记录为后续选队偏好，不把预设名当成四名角色或猜测成员；当前`ChallengePlan`仍要求两队各四名明确角色。尚待核实这些预设的实际成员、形态、两队是否重复、可用及完整入队反馈，再接入高难执行。没有据此改写已保存配置或启动游戏。

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

[Settings](../autohsr/config.py)新增`challenge_plan={}`，空对象表示未配置；仅保存设置才持久化。保存非空计划会校验三种模式的结构，独立备战入口还要求`memory_of_chaos`。目前没有日常自动启用开关、周常组合、任务树、定时或GUI执行入口。当前GUI仍由既有“UX/UI”工作接入，不能从一个新Settings字段推导界面已交付。

## CLI与原生范围

[独立CLI](../autohsr/challenge_cli.py)提供两个入口。以下是用法示例，本轮没有执行访问游戏的命令：

```powershell
python -m autohsr --challenge-check .\my-challenge.json
python -m autohsr --challenge-prepare --challenge-plan .\my-challenge.json
```

`--challenge-check PATH`只读取所选UTF-8 JSON，最多64 KiB，拒绝重复键与非有限数；先于运行配置加载和Runner创建分流，不联网、不访问游戏、不保存配置。不能与`--config`、通知或运行选项混用。它输出规范计划与摘要，不证明账号角色或页面可识别。

`--challenge-prepare`是实际原生任务，要求游戏已经打开在可核实的混沌主页或本次首个目标层备战页；复用当前窗口、前台及原F9／F10控制。不调用日常启动／登录／指南导航，不创建日常开拓力或沉浸器预算。`--challenge-plan PATH`只覆盖本次，不写回配置；也可使用已明确保存的非空计划。不能混入刷本、资源、新预算、其他玩法或接续参数。读取现有未完成货币战争周常／领奖门禁的行为保留。

本轮只处理`levels`起层，完整范围仍保留在冻结计划中供后续开发，不运行后续层。先取得当前账号与同一目标的两份新鲜画面；当前原件／页锚支持时只点击该层一次，随后取得两份同模式、同层的备战反馈。已有同层备战页只观察，不重新选层。每次输入在专用[Context入口](../autohsr/app.py)重新推导当前目标，核对账号、输入代次、冻结计划和本次落盘意图；原PNG字节／像素／shape、capture及run归属同时核对。通用点击和按键不能绕过此入口。

提交后的反馈在 30 秒活动时限和 100 次采集上限内观察。加载帧暂缺完整账号、空帧及重复或倒序时间戳会打断连续计数。核实成功需要同一账号、同一输入代次的连续两张当前层备战画面。明确换号、多个完整账号候选、模式冲突、暂停或计划变化会中止原选择的核验。[实现](../autohsr/challenge_prepare.py)

未知、动画、重复capture、失焦、账号／计划／代次变化、写盘失败或超时不重发选择。私人`run_dir/challenge-preparation.json`及`RunReport.challenge`保存原意图、页面来源和反馈；旧文件不覆盖，未核实选择保留`unknown`。最外层运行结束通知只沿用明确启用的通知配置，将任务标为“高难备战”，不公开名单、账号摘要或截图；本轮没有实际发送。

## 页面与证据

[challenge_pages](../autohsr/challenge_pages.py)的`observe()`返回`Observation(kind, mode, level, half, stars, targets, basis)`；`target(scene, "select_level", level=N)`从当前完整观察返回唯一导航Token或`None`。完整当前层标题与列表中的某个层号是不同来源，第一项不能充当当前选中层。

主页需要固定模式局部图与对应OCR、独立`N/36`字段及关卡区域内至少两份不同层号。星形分别绑定当前层号的局部区域，遵循固定原星形与金色规则；只给有独立正星来源的层号导航目标，零星／无星条仍为未知，`available`也保持未知。不据标题、金色、过去星数或层号单独授权开战。当前客户端的完整主页、零星与锁定状态未校准，保守规则可能拒绝真实页面。

备战观察只由独立当前层、模式文字／原件和相互关联的队伍数字／重置／交换图形组补证。数字1／2不代表四名角色已入队，模式文字小图不是完整开战按钮，剩余轮文字／灯泡也不能证明战斗、上下半或胜利。没有重置、交换、选角、秘技、攻击、开战、返回、领奖或结果确认目标。

成功备战仅记`preparation_page_verified=true`；`team_verified`、`battle_started`、`completion_verified`仍为false，半场和完整挑战结果未知。`TaskResult("challenge_prepare", "ok", ...)`和父报告success只说明这个有限准备任务完成，不增加战斗完成、挑战星数或奖励计数。

2026-11-05新增[列表候选观察](../autohsr/challenge_roster.py)。原生准备流程仅在保存已核实同模式备战页时，将`candidate_list`附入来源`basis`；主页、未知页和目标推导不扫描。105幅既有完整头像逐份核对固定manifest、SHA-256、Git blob和尺寸，使用固定上游列表裁剪范围，保留身份、完整框与模板来源。边缘残缺、遮挡及过期画面不作为正候选，跨素材重叠匹配完整保留歧义；没有支援列表行假设或徽章遮罩，也不产出点击目标。

输出的`ownership`、`availability`、`selected`、`complete`全部为`unknown`，`execution_supported=false`。候选未知不改变“只完成备战页核实”的结果。混沌／虚构的列表参考为上游`BaseChallenge.select_characters`的1920×1080、xywh`(30,115,530,810)`；末日工具参考为`Apocalyptic.select_characters`的`(30,110,550,850)`。当前实际接线仍仅混沌备战，其他裁剪参考不表示两种模式主页或完整执行已支持。拼图、尺寸量化及遮挡检查也不是真实全页校准。

14幅原件、实际可见内容、哈希与许可见[素材说明](../assets/upstream/March7thAssistant/challenge-ui/README.md)及[来源清单](../assets/upstream/March7thAssistant/challenge-ui/sources.json)。固定上游为`7cf6c6bed474539485d3b1504077ac352866829f`，作者moesnow及其贡献者、[GPL v3](../assets/upstream/March7thAssistant/LICENSE)与游戏美术权利说明保留，没有移入上游输入框架或公开账号整图。

## 验证与未完成项

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
