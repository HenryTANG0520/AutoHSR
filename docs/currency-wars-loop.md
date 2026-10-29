# 货币战争连续运行

更新日期：2026-10-29。本入口复用原生标准A8-40开发流程，尚未通过真实整局或连续多局验收，历史独立通关仍为0/10。GUI入口由当前界面工作整合。

## 使用

后端入口为`CurrencyLoopRunner(settings, emit, runs=None, resume=False, ...)`。默认读取`Settings.currency_runs=1`；正整数表示请求的胜利结算局数，0表示直到停止。每局仍由普通`Runner(operation='currency_wars_standard')`执行，沿用窗口、账号、资源、落盘意图及反馈协议。

以下仅为用法说明，本轮没有执行游戏操作：

```powershell
# 两局，每局核实胜利、四步结算及证据后才进入下一局
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --currency-runs 2
# 持续运行；失败、未知或写盘异常仍会停止
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --currency-runs 0
# 接续同一循环的剩余目标及冻结设置
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --resume-currency-loop
```

`--currency-strategy`、`--currency-remembrance-name`及双向`--currency-fast-mode`可用于单局或循环。循环开始前冻结局数和这三项设置，修改已保存偏好不改变剩余目标；显式不同覆盖在访问游戏前拒绝。本次CLI覆盖不保存配置。`--resume-active-currency`仍只用于原单局入口，不能与循环入口混用。

F10与界面停止覆盖对局及归档间隙；F9在子Runner运行时沿用其原控制，间隙仅在最后的游戏窗口仍在前台时处理。暂停不创建下一局，停止保留原循环；继续须明确接续，不能重新点击新循环覆盖目标。

目前只支持已有标准A8-40能力。标准／超频自选、周积分达标停止、失败结算后继续、自动放弃旧局、周积分领奖和随后饰品任务仍待适配。循环不扩大资源授权，不恢复旧十场验收目标。

## 逐局记录

源码数据位于根目录`runs/`，打包版位于EXE旁，两者独立：

| 路径 | 用途 |
| --- | --- |
| `currency-loop-current.json` | 当前循环ID |
| `currency-loops/<循环ID>/loop.json` | 冻结设置、账号、当前预约、已完成数和末次回执哈希 |
| `currency-standard-session.json` | 正在执行的原生单局；原单局入口仍使用此路径 |
| `currency-loops/<循环ID>/<局号>.session.json` | 已核验单局，通过重命名归档，保留原内容 |
| `currency-loops/<循环ID>/<局号>.session.receipt.json` | 会话、报告及结算证据哈希，关联前序回执 |
| 各自运行目录的`report.json` | 原单局报告与独立循环汇总 |

先写当前局号和随机预约ID，原生会话在首个输入前写入`loop_owner`并绑定本局ID；每次正式输入回读核对归属。循环账号在首次正式标准输入前持久化，下一局必须一致。本地账号指纹和目录不加入模型局面。

完成计数要求已核实开局、第三位面最终节点出战和胜利来源、连续四步结算返回、清晰账本与专项核验、成功保存的原报告，以及存在的出战／结算证据。只改`completion_verified`或报告成功字样不能归档。

归档顺序为“写意图→原文件重命名→不可覆盖回执→更新计数”。若中间中断，明确接续只读核对原意图、文件、报告和证据，再补齐归档，不重发结算或开局。当前和归档同时存在、源或哈希缺失、目的地或局号改变时，停止并保留双方。下一局前复查上一局归档、回执及原始报告／证据。

以前由单局入口完成且证据完整的会话，可先以`prior-<本局ID>`归档，不增加新循环完成数。外部未完成、未知或属于其他循环的记录不自动接管。当前循环自己的单局仍可用原显式接续入口；循环随后核对同局归属及最新原生接续报告，只计一次。

## 中断和汇总

单局失败、partial、停止、未知输入或报告未保存时，循环保留原记录并停止。原有开店只读核对继续沿用，其他未知输入不能借循环重发。

若原生四步结算已经核实，但原报告写盘失败，当前运行仍停止。明确接续可依据完整动作、账本及文件证据另存只读审计报告，记录原报告路径和存在时的哈希；旧失败报告不改为成功。审计通过才归档，缺证据或待核对支付不能绕过。

循环报告的`currency_wars.mode`为`standard_loop`，含`requested_runs`、`completed`、`active`及`loop_record`，0局表示直到停止；每局仍为`currency_wars_standard`并保留完整原会话。循环只发一次`finished`，子日志及任务事件附带`loop_slot`，另提供`currency_loop_phase`和`currency_loop_progress`。

`completed`只表示本循环结算留档的开发局数，不是历史胜率、周积分或独立验收；`acceptance_runs=0`，`development_only=true`。后续失败保留已完成数，当前未完成局不计成功。

## 来源与验证边界

参考固定March7thAssistant提交`7cf6c6bed474539485d3b1504077ac352866829f`的[循环任务入口](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/main.py#L208-L245)。上游重复调用`CurrencyWars.start`，正常返回false后仍继续，异常退出。AutoHSR保留“直到停止”并增加指定局数与逐局证据；尚无可核实的失败结算继续协议，因此失败或未知会停止。这不表示全部模式、周目标及领奖已经等价。

22项[专项检查](../autohsr/tests/test_currency_wars_loop.py)使用合成最终节点、假窗口和正式Context的四步结算，覆盖连续两局、停止续跑、冻结设置、账号／写盘门禁、归档中断、来源篡改、原报告保留、CLI与热键。它们没有覆盖完整整局策略或访问真实游戏；全量检查见[开发记录](currency-wars-development.md)。
