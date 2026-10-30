# 货币战争连续运行

更新日期：2026-10-30。本入口复用原生标准A8-40开发流程，尚未通过真实整局或连续多局验收，历史独立通关仍为0/10。GUI入口由当前界面工作整合。现已接入默认关闭的[已核实失败后继续](currency-wars-defeat-loop.md)，失败布局仍为合成变体。

## 使用

后端入口为`CurrencyLoopRunner(settings, emit, runs=None, resume=False, until_points=None, continue_after_defeat=None, ...)`。默认读取`Settings.currency_runs=1`、`currency_until_points=False`与`currency_continue_after_defeat=False`；积分目标关闭时，正整数表示请求的结束局数，胜利和已核实失败都占局数，0表示直到停止。每局仍由普通`Runner(operation='currency_wars_standard')`执行，沿用窗口、账号、资源、落盘意图及反馈协议。

以下仅为用法说明，本轮没有执行游戏操作：

```powershell
# 两局，每局核实结算及证据；默认遇已核实失败留档后停止
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --currency-runs 2
# 持续运行；默认失败停止，未知或写盘异常始终停止
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --currency-runs 0
# 本周积分满后停止，最多完成五局新开发局；默认不开启积分目标
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --currency-until-points --currency-runs 5
# 本次关闭积分目标，按局数运行；不保存配置
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --no-currency-until-points --currency-runs 2
# 接续同一循环的剩余目标及冻结设置
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --resume-currency-loop
```

`--currency-strategy`、`--currency-remembrance-name`及双向`--currency-fast-mode`可用于单局或循环。循环开始前冻结局数、积分目标开关和这三项设置，修改已保存偏好不改变剩余目标；显式不同覆盖在访问游戏前拒绝。本次CLI覆盖不保存配置。`--resume-active-currency`仍只用于原单局入口，不能与循环入口混用。旧循环没有积分开关时按关闭接续，不因新保存偏好改成积分循环。

F10与界面停止覆盖对局及归档间隙；F9在子Runner运行时沿用其原控制，间隙仅在最后的游戏窗口仍在前台时处理。暂停不创建下一局，停止保留原循环；继续须明确接续，不能重新点击新循环覆盖目标。

`--currency-continue-after-defeat`及`--no-currency-continue-after-defeat`仅用于循环，并在开始时冻结。关闭时已核实失败留档后标为`defeated`；明确接续仅确认这一次失败并使用原剩余局数，下次失败仍停止。设置与命令不会将失败算成胜利，局数耗尽不会自动补局。

目前只支持已有标准A8-40能力。标准／超频自选、自动放弃旧局和随后饰品任务仍待适配；独立周积分领奖与周常编排已另有后端，见[周常说明](weekly-plan.md)。循环不扩大资源授权，不恢复旧十场验收目标。

## 本周积分目标

`--currency-until-points`仅用于循环，也可从显式保存的设置读取。开启后，首次新局前及每局完成留档后分别调用[独立积分Runner](currency-wars-weekly-notes.md)，核对当前账号、积分及游戏周倒计时；已有满分时可零局结束。`--currency-runs N`此时表示本循环最多结束的新开发局数，已核实失败也占上限，0表示没有局数上限，仍受停止、默认失败停止及未知门禁约束。

创建循环时冻结北京时间周一04:00游戏周，首次有效积分观察绑定账号；每次正式标准输入继续检查当前UID。开局前要求本循环、该游戏周、该已完成数对应的有效原始积分回执，且观察不超过120秒、未来偏差不超过5秒；画面本期倒计时必须一致且积分尚未满。原生流程在写开局意图前和正式输入前各查一次，仍须新鲜画面、代次、难度及完整目标核验。历史latest指针不授权开局。

| 循环终态 | 汇总结果 | 含义 |
| --- | --- | --- |
| `complete` | success | 本周积分与倒计时已核实达标，可少于请求局数甚至0局 |
| `exhausted` | partial | 局数上限已用完且已核实积分未满；不再追加预算 |
| `expired` | partial | 冻结目标已跨游戏周；保留旧目标，不自动改到新周 |
| `defeated` | partial | 已核实失败留档，默认停止；明确接续仅使用原剩余额度 |
| `active` | partial／stopped／failed | 积分、周期、报告或本局未完成，保留目标，须明确接续 |

接续已有开局先完成原局，不为查积分离开对局；跨周后仍可接续该局，留档后终止旧周目标。外部或未知开局仍拒绝。只有同循环、从未提交任何开局动作的`start_pending`空记录，才可经“意图→原件重命名→不可覆盖回执”保留归档并释放预约，随后重新查积分；pending或unknown开局不适用。空预约也留独立记录，不计完成局数，归档中断只读恢复。

积分缺失、倒计时未知、换号、证据改变或写盘失败均不开始下一局，也不把周常设为完成。达到局数上限且重读积分仍未满时循环结束；如需更多局，须显式新建目标，旧目录保留。循环自身不领取积分奖励，`rewards_verified=false`；周常组合另由独立Runner处理。

## 逐局记录

源码数据位于根目录`runs/`，打包版位于EXE旁，两者独立：

| 路径 | 用途 |
| --- | --- |
| `currency-loop-current.json` | 当前循环ID |
| `currency-loops/<循环ID>/loop.json` | 冻结设置、账号、当前预约、已完成数和末次回执哈希 |
| `currency-standard-session.json` | 正在执行的原生单局；原单局入口仍使用此路径 |
| `currency-loops/<循环ID>/<局号>.session.json` | 已核验单局，通过重命名归档，保留原内容 |
| `currency-loops/<循环ID>/<局号>.session.receipt.json` | 会话、报告及结算证据哈希，关联前序回执 |
| `currency-loops/<循环ID>/unstarted-*.session.json`及回执 | 从未提交开局输入的本循环空记录原件，不计局数 |
| 各自运行目录的`report.json` | 原单局报告与独立循环汇总 |

先写当前局号和随机预约ID，原生会话在首个输入前写入`loop_owner`并绑定本局ID；每次正式输入回读核对归属。按局数循环的账号在首次正式标准输入前持久化，积分循环在首次有效积分观察时绑定，下一局必须一致。本地账号指纹和目录不加入模型局面。

胜利计数要求已核实开局、第三位面最终节点出战和胜利来源、连续四步结算返回、清晰账本与专项核验、成功保存的原报告，以及存在的出战／结算证据。失败计数另须同局出战、同节点两帧终局、零生命与失败总览、独立四步返回和原partial报告，不能借胜利标志清账。只改完成标志或报告字样不能归档。

归档顺序为“写意图→原文件重命名→不可覆盖回执→更新计数”。若中间中断，明确接续只读核对原意图、文件、报告和证据，再补齐归档，不重发结算或开局。当前和归档同时存在、源或哈希缺失、目的地或局号改变时，停止并保留双方。下一局前复查上一局归档、回执及原始报告／证据。

以前由单局入口完成且证据完整的会话，可先以`prior-<本局ID>`归档，不增加新循环完成数。外部未完成、未知或属于其他循环的记录不自动接管。当前循环自己的单局仍可用原显式接续入口；循环随后核对同局归属及最新原生接续报告，只计一次。

## 中断和汇总

技术失败、一般partial、停止、未知输入或报告未保存时，循环保留原记录并停止。唯一可继续的partial是完整失败结算并有原报告／证据的已核实整局，且须冻结设置允许或本次明确接续；原有开店只读核对继续沿用，其他未知输入不能借循环重发。

若原生四步结算已经核实，但原报告写盘失败，当前运行仍停止。明确接续可依据完整动作、账本及文件证据另存只读审计报告，记录原报告路径和存在时的哈希；旧失败报告不改为成功。审计通过才归档，缺证据或待核对支付不能绕过。

循环报告的`currency_wars.mode`为`standard_loop`，含`requested_runs`、`completed`、`active`及`loop_record`；积分循环另含`until_points`、`points_goal`与`rewards_verified=false`，保留末次标准／积分子报告目录。`points_goal`保存冻结周、末次积分摘要、对应已完成数及精确回执／原报告哈希，不依赖可被下一次观察替换的latest。每局仍为`currency_wars_standard`并保留完整原会话。循环只发一次`finished`，子日志及任务事件附带`loop_slot`，另提供`currency_loop_phase`、`currency_loop_progress`及`currency_loop_points`。

`completed`及同义`settled_games`表示本循环结算留档的开发结束局数，另列`defeats`与`victories`，不是历史胜率、周积分或独立验收；`acceptance_runs=0`，`development_only=true`。按局数完成但包含失败时汇总仍为partial，积分已实际达标可为success，均不把败局改成胜利。后续异常保留已有计数，未核实局不计完成。

## 来源与验证边界

参考固定March7thAssistant提交`7cf6c6bed474539485d3b1504077ac352866829f`的[循环任务入口](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/main.py#L208-L245)。上游重复调用`CurrencyWars.start`，正常返回false后仍继续，异常退出。AutoHSR保留“直到停止”并增加指定局数与逐局证据，另将已核实失败与未知／技术异常分开，默认停止，选择继续时仍消耗原局数。这不表示全部模式、周目标及领奖已经等价，失败几何仍待实机校准。

25项[专项检查](../autohsr/tests/test_currency_wars_loop.py)使用合成最终节点和假窗口，覆盖正式Runner.run、四步Context输入、原报告写入、连续两局归档，以及原报告失败后的明确接续、剩余局执行、停止、冻结设置、账号／写盘门禁、归档中断、来源篡改、CLI与热键。最初22项的成功夹具绕过了Runner报告状态赋值，随后正式链路检查发现并修复报告被固定写为partial的问题；夹具现已调用真实结果分派，不手动赋成功。检查不覆盖完整整局策略，也没有访问真实游戏；详情见[开发记录](currency-wars-development.md)。

积分目标另有27项[专项检查](../autohsr/tests/test_currency_wars_points_goal.py)，使用正式积分Runner及标准结算生命周期配合模拟窗口／起始最终节点，覆盖零局达标、提前完成、局数耗尽、原目标接续、旧循环兼容、跨周已有局、空记录中断归档、pending／unknown不重放、原证据变化、过期／未来观察、开局前双重检查、停止及CLI。96项积分／循环／标准流程／装备模式相关回归、1461项全量与84项假后端GUI通过；真实整局、积分循环和GUI接入仍未验收。
