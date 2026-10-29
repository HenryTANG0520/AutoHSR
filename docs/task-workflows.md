# 可编辑任务流程后端

更新：2026-10-30。此项接通正式任务级的树形编排、独立CLI和结果协议，供现有AutoHSR界面接入。GUI编辑器、实机组合及三月七的底层图文／鼠标／键盘流程尚未交付。没有操作游戏、读取真实账号记录、消耗资源或构建EXE。

## 与三月七的关系

参考固定March7thAssistant提交`7cf6c6bed474539485d3b1504077ac352866829f`的[流程教程](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/docs/Workflow.md)及[执行模块](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/workflow/__init__.py)。借鉴步骤树、条件、循环、循环控制及选中步骤执行，采用AutoHSR自己的JSON与正式Runner。

上游的图片／文字查找、坐标点击、拖动、按键、界面切换、音频、消息推送、模板采集、YAML导入和可视化编辑仍须分别适配。本次没有将这些能力换算成已完成，也不能直接运行上游YAML。流程不会生成绕过Context和玩法门禁的通用点击器。固定来源、函数与SHA-256见[来源清单](../assets/upstream/March7thAssistant/source.json)，原GPL v3保留。

## 当前任务与设置

流程的`task`步骤调用下表正式入口。每次执行先冻结独立设置副本；不保存用户配置。相对记录路径以流程文件所在目录为准，API调用可明确传入`base_dir`。

| task | 正式实现 | params与默认行为 |
| --- | --- | --- |
| `daily` | `Runner(operation='daily')` | 不填`tasks`时沿用当前五项日常开关；可明确指定`assignments/battle/daily/mail/battlepass`子集。可覆盖`stamina_limit/rounds/target_name/target_location/dungeon_category/challenge_count/use_support`；`use_power_plan`默认false |
| `plan` | `PlanRunner` | 沿用现有日常→到期周常；`use_power_plan`、`resume_weekly_currency`默认false。原周目标及接续规则保持 |
| `differential_universe` | `Runner(operation='differential_universe')` | `runs`默认1、范围1～10；`mode`默认periodic，可选normal；`team`默认沿用当前预设；`save/rewards/resume_active`默认false；`periodic_rank`仅用于明确接续；通关后日常固定关闭 |
| `currency_wars_loop` | `CurrencyLoopRunner` | `runs`默认1、范围1～10，不接受0／无限批次；`resume`默认false；可选`strategy/until_points/continue_after_defeat`。未指定的后三项沿用原生默认及冻结设置；接续仍须核对原局数和原账本 |
| `currency_wars_points` | 原生积分Runner | 无参数；仍会导航和核对当前账号／游戏周，属于游戏输入任务 |
| `currency_wars_rewards` | 原生积分领奖Runner | `resume`默认false；不开始对局，不清理满额资源，未知领取不重放 |
| `warp_analysis` | `warp_service.run(analysis_only=True)` | 必填`imports`，1～32份明确的本地SRGF／UIGF文件；只分析不创建导出 |
| `warp_export` | 原记录导出服务 | 必填`imports/output`，`format`默认uigf，可选srgf/xlsx；可选`selected_uid`，原件及已有输出不覆盖 |

记录任务目前只接显式本地JSON；真实缓存／链接获取继续使用[独立工具入口](warp-records.md)，没有在流程中隐式扫描。XLSX仍使用已固定的可选加载引擎，见[统计与Excel](warp-statistics-xlsx.md)。

货币战争仍为标准A8财富造物主40开发流程，没有扩大超频、其他模式、资源授权或独立整局计数；历史0/10保持。流程中的差分仍由原生页面、预设与账本核验，不能因为任务树完成就宣称所有模式验收。

## 文件与控制步骤

UTF-8 JSON顶层为`version:1`、`name`、`steps`；不接受重复JSON键、NaN、未知字段、脚本或任意命令。每步有唯一`id`，由英文字母开头、后接字母／数字／下划线／连字符，最多64字符。可选`name`为显示名，`enabled`默认true。禁用步骤保留skipped结果。

| type | 专用字段 | 行为 |
| --- | --- | --- |
| `task` | `task`、可选`params/on_failure` | 顺序执行一次正式任务；失败策略默认stop，可选continue；不重试 |
| `wait` | `seconds`，0～3600的整数 | 可暂停／停止的主动等待；暂停期间不消耗所请求等待时间 |
| `if` | `condition/steps`、可选`else_steps` | 按已知结果执行一个分支；未知条件停止 |
| `for` | `count/steps`，1～1000 | 固定有界次数；不接受上游0表示无限的行为 |
| `while` | `condition/max_iterations/steps`，上限1～1000 | 每次重新比较当前结果；到上限后仍为真则partial，不宣称条件已结束 |
| `break/continue` | 无 | 仅用于循环内，分别结束当前循环／进入下一轮 |
| `stop` | 无 | 明确停止流程，整体stopped |

条件形如`{"step":"daily","field":"daily_verified","op":"eq","value":true}`。只能引用树中前面出现的步骤结果；所引用分支本次没执行、步骤被禁用而字段未知、类型不一致时停止，不将缺值视作false。`step:"@last"`表示最近一次实际执行的task结果，可用于有界观察循环；普通控制步骤不会替换它。

字段为`status`、`daily_verified`、`completed_runs`、`victories`、`defeats`、`points_verified`、`rewards_verified`。只有对应子报告确实存在且含该字段时才可比较；其他玩法报告的默认实训false，以及未执行实训的日常默认false，都不是实训条件事实。计数支持`eq/ne/lt/le/gt/ge`，状态和布尔值只支持`eq/ne`。`completed_runs`分别指差分已完成数或CW已结束数，CW失败另见`defeats`，不等于胜利。

上限为1 MiB定义、256个节点、12层、最多10000次展开执行；禁用节点也计执行数量。每个可能路径最多一份日常预算、一个差分批次、一个CW批次；循环乘算，互斥分支取最大值。不能用两个daily步骤或for循环重复创建240预算。`plan`保守预留日常、差分与CW各一个所有者，不能再叠加独立同类任务；其10局预留值仅为静态最大值，不是实际请求或完成数。

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
```

序号从0开始，`/`与`\`等价；控制节点的子序号先为`steps`，再为`else_steps`。选中控制节点仍需本次前序结果，缺少时在输入前停止；选中叶子则按上游单步语义跳过父控制。整个文件仍做结构检查，但最大预算按选中子树计算。单独选中的break／continue无效，会在执行前拒绝。

`--task-workflow-check`只证明结构和静态预留合法，不读取实际设置或记录文件，不证明配置、页面或实际资源可用。执行入口额外检查本次配置，并在每个原生任务中重采当前画面、账号、窗口与玩法状态。

## 执行权、停止与报告

`TaskWorkflowRunner(settings, document, emit, selected_path=None, base_dir=None)`提供`run/stop/toggle_pause`。UI提交草稿副本即可，不调用Settings.save。流程只执行一次，同一Runner第二次run拒绝；一次点击不自动重放整个树。

流程持有Windows命名执行标记，覆盖任务间隙；所有原生Runner及单独启动游戏入口检查归属，其他进程／线程不能借间隙启动输入任务。子流程仍独立持有原输入互斥、Context和专用账本。运行中的F9由原子任务处理；间隙仅在已知控制窗口前台响应F9；F10和界面停止跨阶段传递。本地记录服务的取消回调同步响应暂停停止。快捷键监听故障请求停止。

每次步骤先fsync写`steps.jsonl`意图和总报告，再创建／运行子任务；写入失败不执行该步。子任务finished不会变成父流程finished；只有父流程最终报告保存尝试后发送一次。逐步反馈为`workflow_step`，含step、sequence、status；原子事件另带`workflow_step/workflow_task`。

父报告位于本次`runs/<时间>_workflow_<随机ID>/report.json`，同目录保留`workflow.json`定义快照及SHA-256。`workflow.steps`记录每次执行、分支、循环轨迹、状态、条件事实和原子报告路径／哈希；时间、局数、胜负及真实消耗分别保留，不改写原子报告。原子任务的返回结果须与对应已保存`report.json`一致，才能进入下一项。匿名记录工具另存本地子报告。

失败默认停止。`on_failure:"continue"`可用于后续本地分析、等待或分支；若失败来自游戏任务，后续任何游戏任务均被阻止，即使前者已核实部分实训。整体仍为partial，不用后续本地成功覆盖旧失败。未知报告、保存失败、停止、条件未知均不触发重试；已经保存的日常、消耗和CW胜负不会因后续失败丢失。

当前没有流程断点自动恢复、定时器或后台续跑。重新执行文件是一次新执行，不能当作旧预算的接续；应先查看原子报告，再使用原差分／CW／领奖接续入口核对未完成步骤。原生账号核验仍按各子流程执行，跨步骤统一账号约束和完整多账号配置切换未交付。

## 验证

最终新增29项[专项检查](../autohsr/tests/test_task_workflow.py)，与计划、正式日常恢复、CLI及记录功能合计84项最终相关检查通过`runs/task-workflow-final-scope-related.log`（1.715秒）。包括真实原生日常协调器＋假Context、跨线程／独立进程执行权、意图与报告失败、重复预算、未知条件、停止与暂停、while上限、单步执行及真实本地虚构记录分析／JSON导出。没有访问真实游戏、真实Player.log／缓存或账号接口。

28项专项时的1721项全量快照通过`runs/task-workflow-all-final.log`（802.487秒）；源文件哈希为`runs/task-workflow-full-snapshot.json`。随后收紧非对应任务／未执行实训的默认false条件，仅修改条件事实提取并新增1项检查；最终版本由上述29项专项所在的84项相关回归覆盖，未将1721写成最终1722项全量通过。

原GUI84项假后端检查通过`runs/task-workflow-gui.log`。独立进程运行正式CLI的本地“分析→分支→导出”及第二次已有输出拒绝通过`runs/task-workflow-cli-verification.json`：配置、输入和定义原件保持，长ID文本保留，匿名事件与父报告原件一致。固定来源、引用函数、许可、相对链接、文档JSON示例与CLI帮助核对见`runs/task-workflow-source-verification.json`。这些检查不代替真实GUI或游戏验收。

早期两版专项失败保留在`runs/task-workflow-first.log`、`runs/task-workflow-second.log`，跨线程测试夹具修正前的失败保留在`runs/task-workflow-scope.log`。首次全量在修正日常继承规则后主动终止，原`runs/task-workflow-all.log`为不完整记录，不作为全量通过证据。

尚未验证：新GUI操作、真实跨玩法组合、真实CW整局，以及上游底层流程功能。未新增游戏样本、图像模型或训练数据；没有重新开启旧十场目标。
