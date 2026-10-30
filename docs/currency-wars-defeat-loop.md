# 货币战争整局失败与循环接续

更新日期：2026-10-30。当前为原生标准A8-40开发后端与CLI能力，尚未实机验收失败结算或连续整局，GUI开关待现有界面工作接入。旧十场目标没有恢复，独立通关仍为0/10。

## 节点失败和整局失败

参考固定三月七启动器提交`7cf6c6bed474539485d3b1504077ac352866829f`的[`_check_battle_result`](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/currency_wars.py#L2644-L2674)：普通节点“挑战结束／继续挑战”不能当作整局失败；“挑战结束／前往结算”才提供终局来源。上游另有“对局未完成”结果文字。本项目按行为适配，未迁入上游输入框架、缓存结果或自动放弃旧局。

[原生失败协议](../autohsr/currency_wars_defeat.py)要求本局已核实开局、最近一次已核实出战、相同节点和两帧独立终局来源，再分别执行四步：

| 当前页面 | 唯一控件 | 下一步独立反馈 |
| --- | --- | --- |
| 挑战结束／挑战失败，含同节点与挑战进度 | 前往结算 | 零小队生命值与对局评价 |
| 零生命值评价 | 下一步 | 对局失败／对局未完成，含原节点、阵容与投资信息 |
| 失败阵容总览 | 下一页 | 对局统计 |
| 对局统计 | 返回货币战争 | 主页 |

每步由原生Context提交一次，反馈须有两帧。胜利文字、继续挑战、其他完整弹窗、节点不符、缺原出战、未知支付或未完成专项协议均不能推进；未知点击不重发。单独看到失败文字、零生命或主页不构成完整结算来源。

结算会话为`status='settled'`、`match_outcome='defeat'`、`defeat_settlement_verified=true`和`settlement_verified=true`，但`completion_verified=false`、`node_verified=false`。单局报告保持`partial`，不改成胜利或独立通关。

## 循环设置与原局数

新增`Settings.currency_continue_after_defeat=false`。它只决定已核实整局失败留档后是否自动进入下一局，开始时冻结；旧配置和旧循环缺字段时均按关闭处理。运行和CLI覆盖不保存设置。

以下只说明入口，没有在本轮执行游戏操作：

```powershell
# 最多两局，已核实失败也占一局；失败结算后允许自动继续
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --currency-runs 2 --currency-continue-after-defeat
# 本次明确关闭自动继续，失败留档后停止
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --currency-runs 2 --no-currency-continue-after-defeat
# 明确接续原目标剩余局数，不重建预算，也不改变冻结的自动继续偏好
.\.venv\Scripts\python.exe -m autohsr --currency-wars-loop --resume-currency-loop
# 周常原目标明确接续，复用原日常报告与消耗
.\.venv\Scripts\python.exe -m autohsr --plan --resume-weekly-currency
```

未启用自动继续时，失败归档后将循环标为`defeated`并报告`partial`。明确接续核对该次原回执，仅确认越过这一次失败停止；若之后再次失败，还会再次停止。改为99局或改变自动继续偏好不能覆盖原冻结目标。若最后一局已消耗原局数，循环为`complete`但报告仍为`partial`，接续不再开局。普通循环停在`defeated`时，新周常计划也在日常开始前拒绝，不先刷日常再发现旧目标；原周常重复点击新开始则复用原日常和胜负摘要，仍要求明确接续。

例如请求3局，第一局失败后默认停止，明确接续最多再运行2局；不是额外再打3局，也不是直到凑满3场胜利。`currency-runs=0`仍表示直到停止，没有局数上限，但未知、技术异常或写盘失败照常停止。普通节点失败尚不属于本协议，不借此重发出战。

积分目标开启时，每局胜利或失败留档都消耗原上限。允许继续或明确接续后重新核实当前积分：满分可结束，未满且额度用尽则`exhausted`，不追加对局。周常保留原日常、积分、逐局与领奖结果；默认失败停止不会自行进入领奖阶段。

## 计数、原报告与恢复

循环报告将以下字段分开，周常及父计划保留对应汇总：

| 字段 | 含义 |
| --- | --- |
| `completed`、`settled_games` | 已核实结算且留档的结束局数，包含已核实失败 |
| `defeats` | 已核实整局失败数 |
| `victories` | 已结束局数减失败数，不将结束等同胜利 |
| `acceptance_runs=0` | 本轮都是开发机制，不增加历史独立验收 |

失败局沿用[循环原件归档](currency-wars-loop.md)：原会话、原`partial`报告、开局／节点出战／两帧终局／四步结算证据共同核对，逐局回执另记`outcome='defeat'`及`defeats_before/after`。前序哈希与累计失败数须连续；旧胜利回执缺这些字段时保持原义。仅修改胜负字段或完成标志不能通过归档。

归档中断可只读补齐同一次原件，不重复结算或新开局。原报告未保存时，当前运行先停止；明确接续可依据完整原始证据另存`partial`只读审计报告，保留原失败／缺失路径，不伪造或重写旧报告。停止发生在归档之后时，已核实计数保留，下一次接续仍先处理默认失败停止规则。

## 证据与限制

[专项检查](../autohsr/tests/test_currency_wars_defeat.py)使用正式Runner／Context与假窗口，涵盖同源终局、四步输入、文字与弹窗冲突、两种失败总览文字、胜负计数、默认停止与一次明确接续、局数耗尽、积分及周常组合、原日常复用、未知交易不清账、未知输入不重放、证据损坏、写盘及归档中断恢复。

失败页面的位置是已有4.6胜利几何的合成变体；本轮没有真实失败截图，不把它们称为已校准实机页面。参考上游文字不证明本地每一屏布局相同，实际不同布局仍会停止留证。正向失败、零生命、四步结算、连续胜负与周常组合都仍待真实验证，未训练模型、未取得独立留出，也没有游戏操作、资源消耗或EXE构建。最终检查结果见[开发记录](currency-wars-development.md)，来源见[清单](../assets/upstream/March7thAssistant/source.json)。
