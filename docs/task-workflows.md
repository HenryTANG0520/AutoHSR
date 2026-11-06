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
| `workflow_notify` | 已保存通知方案 | 必填 `profile`、`message`。只在明确授权的手动运行中发送文本，同一运行出现待核对的提交后停止后续主动通知 |

记录任务目前只接显式本地JSON；真实缓存／链接获取继续使用[独立工具入口](warp-records.md)，没有在流程中隐式扫描。XLSX仍使用已固定的可选加载引擎，见[统计与Excel](warp-statistics-xlsx.md)。

图文判断的 `region` 是相对整张图片的 `[左, 上, 右, 下]`，缺省为整张图。已完成分析但未匹配时，回执明确给出 `image_found=false` 或 `text_found=false`，可以用于后续条件。文件、范围或识别失败时没有匹配事实。音频及图片路径相对流程文件，应用内定时冻结这些来源的文件指纹。

游戏图文步骤读取已经登录且处于前台的游戏客户区。两张连续新画面都必须核实同一窗口、账号、输入代次及一致的识别结果。登录、遮挡、失焦、账号变化或两次识别不一致时，匹配字段留空。步骤占用正式执行权，只观察画面，回执只写布尔结果，账号证据仍按原规则留在本机。定时触发时也需要游戏已在前台，并受含游戏任务的单次重复限制。

页面切换与实时图文共享前台及账号门禁。目标为 `phone` 手机、`guide` 指南、`daily_training` 每日实训、`survival_index` 生存索引、`assignments` 委托、`mail` 邮件、`battlepass` 无名勋礼。泛指南目标保留当前指南子页。已经在目标页时零输入。每次点击或返回都要求当前页面和可用入口有证据，再双帧核对新页面。遇到登录、弹窗、战斗、失焦或不认识的页面时保留已有动作回执。只有已核实到达的结果才提供 `page_verified=true`。导航不领取奖励、不开战，也不建立资源预算。

音频支持 1 或 2 声道、8 或 16 位、8～48 kHz，文件最多 32 MiB、时长最多 120 秒。播放完成来自 Windows 驱动反馈。主动通知在桌面运行时显示本次最多步骤数和方案别名，授权后沿用冻结的方案版本。CLI 显式使用 `--workflow-allow-notify`。每次流程最多 20 个主动通知步骤。应用内定时暂未开放这项授权。通知正文留在流程文件及明确发往的渠道，运行回执只记结果及必要的匿名事实。[通知设置](notifications.md)

`daily` 节点显式填写 `"params": {"tasks": ["assignments"]}` 时，只处理已有的持续委托奖励。列车补给和登录附加奖励会阻止本步继续。核实当前账号和可用按钮后，最多尝试一次领取。领取反馈中断或账号改变时，保留原证据待核对。回到委托页后，在两张新画面上复核同账号的原委托状态。详见[每日流程](../DAILY_FLOW.md#执行顺序)。

`daily` 和 `plan` 的 `params.support_daily_only` 只接受布尔值。省略沿用当前设置，显式 `false` 仅关闭本次按需判断。显式 `true` 要求本次选中刷本、允许使用已有资源，且 `plan` 执行范围包含日常。实际借用仍由 `use_support` 决定。冻结参数不保存设置，借用与支付继续由原生日常核实。[按需支援](support-preferences.md#按实训需求借用)

差分节点设置 `"params": {"until_points": true, "runs": 3}` 后，`runs` 是本次新开局上限。该选项需要显式填写 `runs`，只适用于新开周期演算。积分满额可零局完成。达到上限仍未满时保留已核实胜利，任务返回部分完成并遵守原失败策略。附加红点领取仍由 `rewards` 单独指定，周期积分奖励保持独立。[差分积分目标](differential-universe.md)

原生周期积分运行写胜利与返回截图时，同时把原图摘要和本局标识写入局记录。任务树对照原报告、账本、证据清单和原图摘要，核对积分双帧及每局的胜利与返回。条件 `completed_runs` 只读取核实过的实际局数。证据缺失或不一致时，本步为部分完成，局数待核对，后续游戏步骤暂停。

任务树在接收积分结果、判断条件及进入后续游戏步骤时核对游戏周。接续满额结果的游戏任务沿用原游戏周，在原生检查点和发送输入前复核。父流程每次尝试提交最终报告也核对游戏周。跨周时将 `periodic_points_goal` 标为待核对，停止后续游戏输入，保留原报告、原周观察、已核实胜利以及已发生的后续操作及其回执。固定局数仍沿用原流程。

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

条件字段包括 `status`、`daily_verified`、`completed_runs`、`victories`、`defeats`、`points_verified`、`rewards_verified`、`du_rewards_verified`、`image_found`、`text_found` 和 `page_verified`。`du_rewards_verified` 对应本次明确请求的红点。图文及页面字段对应已成功核实的观察或切换步骤。只有对应子报告确实存在且含该字段时才可比较，日常实训也须有执行证据。计数支持 `eq/ne/lt/le/gt/ge`，状态和布尔值支持 `eq/ne`。`completed_runs` 对应差分已完成数或货币战争已结束数，货币战争胜负另有 `victories` 和 `defeats`。

上限为1 MiB定义、256个节点、12层、最多10000次展开执行；禁用节点也计执行数量。每个可能路径最多一份日常预算、一个差分批次、一个CW批次；循环乘算，互斥分支取最大值。不能用两个daily步骤或for循环重复创建240预算。`plan`保守预留日常、差分与CW各一个所有者，不能再叠加独立同类任务；其10局预留值仅为静态最大值，不是实际请求或完成数。

## 桌面操作

「新建草稿」在内存中准备一条默认关闭的持续委托步骤。勾选或取消「启用持续委托」会更新草稿的 `enabled` 并刷新 JSON 排版，可在文本区撤销。已显示的预算和单步校验随编辑失效。勾选后校验可见一份日常调用预算，该步骤的开拓力上限为 0。选择新路径并核实另存结果后，才可使用「运行已保存流程」。

「打开任务流」选择现有 JSON。通过校验且仅含一条明确指定 `daily` / `tasks: ["assignments"]` 的流程也可使用持续委托开关。其他流程可用「可视编辑…」或直接编辑文本。用「另存为」校验整棵树并保存到新路径，成功回读后切换到新文件。重名、校验失败或回读异常保留草稿。原件外部变化时可保留编辑另存，也可重新加载。

「打开任务流」也可选择三月七的 `.yaml` 或 `.yml`。支持的文件会转换成未保存草稿，另存为 JSON 并重新校验后才可运行。未适配的步骤会给出具体节点路径并保留当前草稿。格式、支持范围和上游实测见[三月七 YAML 转换](march7th-workflow-yaml.md)。

可视编辑显示步骤、启用状态和执行路径。选中流程根、条件成立、否则或循环体可向对应分支添加步骤。选中步骤可编辑属性、添加同级步骤、调整同级顺序或移除。步骤类型包括正式任务、等待、条件、固定循环、条件循环、跳出循环、继续循环和停止。条件字段、比较和值分别填写，正式任务的高级参数可用 JSON。新添加的正式任务默认禁用。

「切换到游戏页面」的目标可以在属性面板中直接选择。两个图像判断节点可点「采集模板…」，打开本地磁盘上的普通 PNG／JPEG，或在提示后手动将已启动的游戏切到前台。框选后在当前流程目录内另存新的 PNG。程序校验裁片并回读摘要，再把相对路径填入当前节点。新草稿需先选定未占用的本地 JSON 另存位置。采集后仍需应用属性和草稿。当前编辑会话会记住采集来源，同一 JSON 重新加载后仍保留。要在本会话换目录另存，需为相关节点重新采集或明确编辑路径。保存的 JSON 沿用相对路径格式，跨目录分享可使用 ZIP 素材包。

编辑弹窗允许暂留空分支和待修正的引用，整棵树通过原编译器才可「应用到草稿」。应用后可在文本区撤销。取消只关闭编辑弹窗。按「应用并选中步骤」可把当前步骤路径带回指定步骤范围，之后仍需独立校验和另存。原范围为指定步骤时，应用改动后须重新选择路径或明确切回整棵流程。

打开时默认范围为「整棵流程」。切换为「指定步骤」，填写从 0 开始的路径（例如 `1/0`），再点「校验草稿」查看步骤名称和该范围的预算。条件节点的子序号先列 `steps`，再列 `else_steps`。修改路径、范围或草稿后需要重新校验单步。范围切回「整棵流程」即可使用原来的整树入口。

「运行已保存单步」要求当前草稿与保存版本一致，沿用下述 CLI 的 `--workflow-step-path` 语义。运行前重新核实文件版本、步骤路径和解析目录。选择其他目录作为另存位置时，显示该目录的预算预览，保存后须按新来源重新校验所选步骤。另存始终校验整棵树。定时的任务流目标也可填写步骤路径。

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

## 执行权、停止与报告

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
