# 应用内定时与有限重复

更新日期：2026-10-30。本文记录应用内调度的实现范围与接口。默认关闭；保存计划不等于启用，启用也不登记Windows系统任务。当前GUI尚未接入，不把后端开发视为桌面设置、系统自启或真实无人值守验收。

## 时间、资源和执行边界

调度使用固定北京时间（UTC+8），星期一至日为1～7。只考虑当前分钟的计划点，启用／启动所在分钟跳过；程序未运行、系统睡眠或暂停期间错过的计划不补跑。系统恢复后的自然开拓力增加不构成新的预算授权。

每次触发均调用原生任务入口，保留现有体力／沉浸器预算、账号连续性、UID门禁、未知交易、旧报告和恢复要求。定时或重复次数不能清理未知账本，也不能隐式添加`--new-battle-run`、重开货币战争或接续旧开发局。首版dispatcher拒绝任何含游戏任务目标的`repeat.count > 1`，也拒绝自动接续参数；已有差分／CW任务内部的明确局数仍由其原生批次协议核对。有限重复仅在不涉及游戏的本地任务中开放，不根据体力自然恢复无限运行；失败或未知停止后续重复。

调度只可取消自己持有的子Runner及待启动任务，不强杀其他进程、不抢占其他窗口，也不同时启动第二套游戏输入。游戏任务的暂停／停止和输入释放继续由原生Runner完成；应用内等待与游戏输入状态分别记录。

| 能力 | 本轮边界 |
| --- | --- |
| 应用内定时 | 显式启用的计划由正在运行的应用内时钟检查，不负责启动已退出的助手 |
| 有限重复 | 本次计划内冻结次数和间隔；每次仍检查原生账号／预算／旧账本 |
| Windows登录／开机自启 | 独立能力，本轮未实现；不创建登录触发器、开机触发器或后台服务 |
| 管理员固定GUI入口 | 现有`admin_launch.py`仅打开当前目录的固定GUI、无触发器、不接受任务参数；本轮不扩展这个授权桥 |
| 系统唤醒和补漏跑 | 未实现，不唤醒机器、不追补错过的分钟或跨日预算 |
| 任意程序、脚本和完成后系统操作 | 未实现，不用定时入口执行任意shell、关机、重启或用户脚本 |

## 计划JSON

计划定义是UTF-8 JSON对象，最大64 KiB；接受UTF-8 BOM，拒绝重复字段、NaN／无穷、未知字段及错误类型。保存的是静态定义，启用状态由独立的明确操作控制，不能在JSON里塞入`enabled=true`绕过。

```json
{
  "version": 1,
  "id": "example-daily",
  "name": "示例日常计划",
  "time": "04:05",
  "weekdays": [1, 2, 3, 4, 5, 6, 7],
  "target": {"type": "task", "task": "daily", "params": {}},
  "repeat": {"count": 1, "interval_seconds": 0},
  "conflict": "skip",
  "timeout_seconds": 0
}
```

此示例不在开发过程中导入或启用；实际目标仍须经过dispatcher的任务白名单与参数检查。

| 字段 | 默认／约束 |
| --- | --- |
| `version` | 必填，整数1 |
| `id` | 必填；小写字母开头的1～64位小写字母、数字、下划线或连字符 |
| `name` | 必填；非空单行文字，最多80字符 |
| `time` | 必填；严格`HH:MM`，北京时间24小时制 |
| `weekdays` | 默认1～7每天；非空、不重复的1～7整数列表 |
| `target` | 必填；`type=task`时需`task`及可选`params={}`；`type=workflow`时需`path`及可选`step_path`，路径序号从0开始，如`0/1` |
| `repeat.count` | 默认1，结构允许1～1000整数；含游戏任务的目标首版必须为1；失败／未知不自动补足次数 |
| `repeat.interval_seconds` | 默认0，0～86400整数；有限重复之间的等待，不是系统唤醒或错过补跑 |
| `conflict` | 默认`skip`；仅允许`skip / stop_owned`，后者只处理本调度器拥有的子Runner |
| `timeout_seconds` | 默认0（不设置任务超时），0～604800整数；超时仅请求原生停止，不强杀 |

预览只计算未来的日历计划点，不创建运行、不读取当前游戏、不消耗资源，也不把重复间隔当作新的每日计划点。结构检查不会读取目标文件或当前配置，因此不证明所选目标在启用时可执行；启用前还要完成dispatcher的冻结检查。

## CLI：检查、保存、预览与显式计时

下列入口互斥，不能混用游戏、记录、通知或管理员命令。`--config`只允许与`--schedule-run`一起使用；检查／保存／列举／预览不加载游戏配置，也不访问游戏。

```powershell
# 只读检查JSON和目标结构，不读目标文件、不保存、不启用
.\.venv\Scripts\python.exe -m autohsr --schedule-check .\example-schedule.json
# 显式保存本地版本，保留输入原件，不启用
.\.venv\Scripts\python.exe -m autohsr --schedule-save .\example-schedule.json
# 同名修改必须明确替换，旧版本与旧回执保留
.\.venv\Scripts\python.exe -m autohsr --schedule-save .\example-schedule.json --schedule-replace
# 只读列出本地定义，不启用
.\.venv\Scripts\python.exe -m autohsr --schedule-list
# 只读预览未来五次日历时刻；参考时间必须带时区
.\.venv\Scripts\python.exe -m autohsr --schedule-preview example-daily --schedule-from "2026-11-02T03:59:00+08:00"
```

默认存储根为当前运行版的`ROOT/schedules.local/`，源码版在项目根，打包版在EXE旁；目录整体忽略，不提交。`--schedule-store-dir <目录>`可明确替换独立工具及本次控制器的定义／回执目录。`--schedule-expected-revision <旧SHA-256>`仅配合`--schedule-save ... --schedule-replace`使用，使用列表／预览返回的规范计划revision核对旧版本后才替换，不是输入JSON原始字节的哈希；不凭空把未知旧回执改成已核实。

实际计时必须明确选择1～32个不重复的已保存id；控制器持续运行到停止或期限到达。以下是实际启用入口示例，只有明确选择该入口后，到期目标才可能操作游戏，原任务授权与预算仍须成立：

```powershell
# 本进程启用所选计划并计时，退出不保留启用状态
.\.venv\Scripts\python.exe -m autohsr --schedule-run example-daily --config .\example-config.json
# 可选多份计划；期限到达只请求协作停止并等待，0秒表示立即结束本次计时
.\.venv\Scripts\python.exe -m autohsr --schedule-run example-daily --schedule-run example-analysis --schedule-limit-seconds 3600
```

`--schedule-limit-seconds`接受0～86400的有限数值，只用于控制器；省略即不设置本次计时期限。它与计划里的每次子任务`timeout_seconds`分开，不是杀进程时限。CLI持续提供tick；F10、Ctrl+C或期限到达后请求停止本控制器的任务，并等待实际释放。控制器正常退出返回status=stopped及snapshot，退出码0；键盘中断130，定义／配置／执行未核实错误2。子任务失败在调度事件／回执中单独保留，不能只凭控制器退出码0判断游戏成功。

## 目标、冻结与原生门禁

`target.type=task`仅支持任务树已注册的正式任务：`daily`、`plan`、`differential_universe`、`currency_wars_loop`、`currency_wars_points`、`currency_wars_rewards`、`warp_analysis`及`warp_export`。`params`使用同一任务树协议，不接受任意CLI字符串；组合、条件、有限循环与选中子树通过`target.type=workflow`引用正式任务树JSON，参数详见[任务流程](task-workflows.md)。不接受上游`program / args / trigger_mode / post_action`配置。

启用时冻结完整设置、计划修订、工作流原件哈希、所选子树及预算预留、本地导入依赖哈希、已选通知配置版本；本地路径及完整清单保存在私有回执。CLI工作流目标的相对路径以当前运行版ROOT为基准，工作流内部的相对导入仍以工作流所在目录解析，不随`--schedule-store-dir`移动。

每次创建子Runner前重新核对工作流与依赖原件、通知凭据版本及冻结清单哈希；有变化就停止该时隙，不悄悄采用新文件、新地址或新设置。运行期间修改普通配置文件不会替换已冻结设置；需要停止、核对后重新明确启用。通知只包装最外层任务树，原游戏输入释放后才发送，通知结果不改变原游戏报告，详见[通知说明](notifications.md)。

含游戏任务的目标仅允许一次调度执行；其内部局数、日常与周常组合仍受任务树静态预留、原生资源账本及跨步骤账号协议约束。`resume / resume_active / resume_weekly_currency=true`首版均拒绝自动接续，旧局须回到手动原生入口核对。结构检查与只读预览不读取这些来源，不能替代启用时的完整冻结检查。

## 本地版本与触发回执

计划保存为不可变版本及当前版本指针。显式替换保留旧版本；可提供`expected_revision`防止覆盖其他保存结果。损坏指针、内容与版本哈希不符或写盘失败均拒绝执行，不用空计划覆盖。保存后的返回值和本地定义列表中的`enabled=false`只说明定义本身没有执行授权，实际运行状态须查看对应Scheduler实例。

| 存储根下的文件 | 用途 |
| --- | --- |
| `plans/<id>.json` | 当前版本指针，不保存enabled授权 |
| `definitions/<id>/<revision>.json` | 不可变规范计划，旧版保留，最多64 KiB |
| `slots/<key>.json` | 私有冻结清单、认领及逐次意图／结果，回执最多1 MiB，冻结清单最多256 KiB |
| `store.lock` | 本地并发写保护；不是Windows定时任务或执行授权 |

`enable(id)`在当前进程内冻结计划、修订和dispatcher清单，不持久化启用状态，不启动时钟或Runner。重新启动进程后须重新明确启用；运行过程中改变计划，不自动使用新定义替换已启用的版本，下次时隙检查会禁用旧修订，下一次重复前发现变化也会停止。

触发键由计划id、修订及北京时间分钟共同生成，认领意图须先落盘才能构造子Runner。每次重复另写`pending`，取得原生报告后再记结果。相同键的旧回执只读复用：`claimed / running`对外视为unknown，终态保留，不恢复未完成执行或自动重试；损坏回执不重建。进程退出或未知输入后，不能靠删除计划回执重跑旧目标。

计划回执与原游戏报告分别保存；正式adapter在返回后有界读取原`report.json`（最多64 MiB），核对保存内容与Runner返回的完整dict一致，再记录原路径、SHA-256、字节数及operation。核心再核对来源结构与operation，把来源写入私有`attempt.result.source`；缺失、损坏或不一致时记unknown，不重写原报告或重跑。纯注入fake的契约不等于正式adapter可省去原件核验。

只有原生报告状态有效、`report_saved=true`且来源核验通过，才能成为已核实结果。原报告缺保存证明时，调度层记unknown并保留原`game_status`，不把游戏状态改成失败或删除已确认的每日／胜利。回执结果只存必要的任务状态与原报告来源；完整冻结清单、本地路径和原报告来源哈希不放入公开snapshot或调度事件。

## 控制器与UI接口

核心为[schedule_runtime.Scheduler](../autohsr/schedule_runtime.py)，注入`store`、`executor`、`clock`、`emit`及可选`monotonic`。executor提供`freeze(plan)`、`revalidate(manifest)`、`create(target, manifest, emit)`和`busy()`。构造、保存和启用均不暗中创建定时线程；调用方明确`start()`并持续提供`tick()`才检查到期时隙，执行工作使用受控子Runner。

| 接口 | 行为 |
| --- | --- |
| `enable(id)` | 在本实例启用并冻结版本；启用所在分钟不触发 |
| `disable(id)` | 禁止该计划的未来触发，取消尚未开始的同计划pending；不冒充已停止正在执行的子Runner |
| `start()` | 开始接受tick，跳过本次启动分钟；不读取错过的历史计划点 |
| `tick(now=None)` | 只检查当前分钟，并检查当前子Runner超时；调用方停止tick后不会在后台自动扫描 |
| `pause() / resume()` | 同时控制本调度器及其当前子Runner；实际暂停状态须核实，暂停期间不触发新计划，恢复不补漏 |
| `stop(wait=False, timeout=None)` | 关闭本实例调度、取消pending、请求停止自己持有的子Runner；wait参数只等待，不强杀 |
| `wait_idle(timeout=None)` | 等待实际子Runner和pending退出，以返回值区分已空闲与仍在停止 |
| `snapshot()` | 返回`running / started / stopping / state / paused`、已启用计划、`enabled_ids / next_times`、active／runner_active／pending／last及北京时间信息，不包含完整目标或冻结设置 |

冲突默认`skip`。`stop_owned`只在本实例当前有子Runner、尚无pending且控制器可用时，保留一个新目标并请求当前子Runner停止；必须等其run实际返回后才尝试新目标。其他AutoHSR进程或原生任务持有执行权时，两种策略都不会强停它；相同时刻的计划按id顺序检查，没有无限队列。

`timeout_seconds`对每次实际子Runner分别计时，从run开始到返回；它依赖调用方持续tick检查，暂停期间仍观察超时，不是强制终止时限。有限重复之间的等待可暂停；暂停时当前子Runner的F9实际状态也会同步到调度器，避免新计划打断暂停。只有前次已核实success才创建下一次Runner，partial、failed、stopped、unknown均停止本时隙剩余次数。

子原生任务主动返回stopped（例如F10）且不是内部替换／超时／控制器停止导致时，整个调度器停止计时并清pending，保留本进程enabled定义；只有显式再次`start()`才恢复未来计划，恢复所在分钟仍跳过。共享`run_control.stop_requested(runner, report)`读取严格的只读bool或原stopped报告；run返回／异常后在清Runner引用、源验证和结果落盘前锁存，tick也在认领下一due前观察当前自有Runner的该bool。后续核验或回执写入失败仍停止未来计时，结果保持unknown／pending，不能改成已核实stopped。

原生Runner、计划、CW循环、任务树及通知wrapper均公开只读`stop_requested`，父级合并当前child并在清理前传递。NotificationRunner合并自身通知stop和child意图，通知阶段F10可在原游戏仍success、网络尚未返回时停未来计划；不能撤回已提交的通知。原child停止被来源错误或保存失败表现为partial时，该控制意图仍保留。它不授权后续动作、不改变原报告，内部stop_owned替换也不误当作用户全局停止；具体区别见[任务流程停止说明](task-workflows.md#停止意图与未保存报告)。

| 分列的结果 | 解释与停止时行为 |
| --- | --- |
| 控制器 | `state / running / stopping / pending`说明是否继续计时及是否仍等自有Runner退出；F10停止未来，不代表原任务失败 |
| slot／attempt | 已完整核实count1时保留success，可另记`reason=controller_stopped`；内部替换若原slot已完整完成可为success＋`replaced_by_schedule`。有限repeat尚有未执行次数则partial并保留completed；真实stopped／unknown不伪造为成功 |
| 原游戏／父流程报告 | 原status、每日／胜利、消耗、错误和保存状态保持；控制意图不把success改stopped，也不把partial／unknown改成已核实停止 |
| 通知 | accepted／cancelled／unknown等独立保存；“游戏success、通知cancelled、slot success、controller stopped”可以同时成立 |

| 事件 | 状态含义 |
| --- | --- |
| `schedule_enabled / schedule_disabled` | 本实例启用／禁用，含id；启用另有修订及当前running状态 |
| `schedule_started / schedule_paused / schedule_stopped` | 控制器状态；stopped的`waiting_for_owned_runner`表示原有子Runner可能尚未退出 |
| `schedule_claimed / schedule_running` | 时隙意图已落盘／某次重复开始；包含id、revision、slot和requested，running另含从0开始的index |
| `schedule_waiting` | 因`stop_owned`正在等待本实例原有子Runner退出，不表示新目标已经开始 |
| `schedule_reused` | 已有同键回执，无新执行；旧claimed／running显示unknown |
| `schedule_skipped` | 当前修订变化或时隙未核实等原因；冲突跳过由`schedule_finished, status=skipped`报告，均非任务成功 |
| `schedule_result / schedule_finished` | 单次结果／本时隙终态，status与原游戏结果分开；含completed和requested，finished可另含稳定reason |
| `schedule_child` | 只保留白名单child_type、布尔paused、允许的status／game_status及完成／当前／请求／通知受理计数，并附本时隙id／revision／slot；未知事件类型直接丢弃 |

子finished不重复当作控制器结束；原始子事件须经允许字段投影，原日志、完整报告、UID、通知profile／provider、路径、来源哈希和manifest均不过公共事件。`child_type`可区分游戏进展和notification_phase／result／summary；通知的accepted／rejected／unknown／cancelled／filtered／partial单独呈现，`game_status`只允许原四种游戏结果，计数须为0～1000000的整数。调度器本身可以继续等待下一个时刻，UI须区分本时隙完成、当前已空闲与整个调度器已停止。当前GUI控件尚未接入，不能把这些API表述为已有设置页或按钮。

## 固定上游参考与区别

参考提交为March7thAssistant的`7cf6c6bed474539485d3b1504077ac352866829f`，作者moesnow及其贡献者，GPL v3；完整许可见[上游LICENSE](../assets/upstream/March7thAssistant/LICENSE)。本轮读取的公开源码均按原始字节计算SHA-256及Git blob，并与该提交的固定目录树核对。

| 上游文件／函数 | 研究事实与本轮范围 |
| --- | --- |
| `app/common/schedule.py`：`scheduled_task_slot`、`next_scheduled_datetime`、`milliseconds_to_next_minute`、`scheduled_task_chain` | 当前分钟匹配、下次时间、分钟边界与任务链的参考；本项目改用原生计划与Runner，不迁入Qt时间对象和命令解析 |
| `app/log_interface.py`：`_startScheduleTimer`、`_checkScheduledTime`、`runScheduledTask` | 上游跳过启动分钟，以Qt计时器调度，冲突可skip／stop，默认允许失败后继续链式任务；本项目使用独立持久回执和原生执行权，未知／失败不自动继续 |
| `utils/schedule.py`：`create_task`、`apply_task_settings` | **仅作区别研究，未移植。** 上游创建Windows登录触发任务并配置运行设置；本轮应用内调度不调用这些函数，也不创建此类系统任务 |
| `tasks/game/__init__.py`：`after_finish_is_loop` | **仅作区别研究，未移植。** 上游CLI可按体力或等待时间再次运行，GUI分支明确拒绝该Loop；本项目不据自然恢复推导额外消耗授权 |

原生存储、调度时隙去重、配置冻结、唯一执行权、预算／账号门禁和逐次报告核验须分别记录，不能因为借鉴时间匹配就称为完整移植上游调度器。上游任务配置、Qt GUI、任意程序参数、默认失败续链、自启、关机及无限循环均不自动成为本项目可用能力。

## 验证记录与剩余边界

2026-10-30统一控制链最终冻结源码的相关244项通过（`runs/schedules-control-complete-related.log`，10.469秒）：14项共享控制协议、46项核心、16项dispatcher／CLI、33项原生CW、11项CV、9项节点、32项任务树、23项账号、9项计划、31项通知、12项渠道合同及8项CLI。另核对正式Graph在fake通知网络held期间公开stop，再tick不认领下一due，原success报告字节不变，完整slot成功与controller停止分别保留。没有真实通知或游戏输入。

统一控制链初次211项中有1项测试断言错误，原`runs/schedules-unified-stop-related.log`保留：默认失败策略下应保留原partial及独立`stop_requested=true`，不能断言所有报告变stopped。修正断言并增加原error、原child partial／report_saved=false均保留的反例后，211项通过`runs/schedules-unified-stop-related-final.log`（10.318秒）；随后又完成上述244项最终相关。原故障注入`runs/schedules-stop-receipt-reproduction.json`也保留，复现修复前回执写入失败可能丢失停止提示的问题。

更早186项相关通过（`runs/schedules-cw-auto-related.log`，9.858秒），当时为40项核心／14项dispatcher；停止报告／落盘顺序加固的191项通过`runs/schedules-cw-auto-related-final.log`（9.707秒）。1857项全量通过`runs/schedules-cw-auto-all.log`（817.511秒），当次305份源文件前后哈希一致；1862项快照通过`runs/schedules-cw-auto-all-final.log`（787.210秒，驱动787.907秒、305份源文件一致），仍早于通知阶段及跨wrapper统一控制意图修复。上述结果保留为更早快照，不署为最终源码全量通过。

阶段72项通过记录`runs/schedules-cw-auto-reviewed.log`（2.494秒）保留。首轮70项中1个假窗口夹具失败，原`runs/schedules-cw-auto-first.log`保留：Windows monotonic分辨率使未实际推进时间的两份capture同时间；修正夹具时间递增，并增加重复capture不能凑两帧的反例，没有放宽运行来源门禁。具体CW局部校准和限制见[开发记录](currency-wars-development.md)。

独立真实CLI进程的5项check／save／list／preview／run期限0核对通过，并以正式NativeScheduleExecutor→TaskWorkflowRunner执行临时wait(0)流程，记录在`runs/schedules-cli-verification.json`。检查实际使用跨进程执行标记，核对同分钟只执行一次、原父报告与SHA引用一致、公开／私有字段分开，以及原配置／工作流文件不变；没有游戏、键鼠、网络、通知或系统任务登记。临时无游戏目标的核验不代表实际资源计划已通过。

统一控制链最终源码的**1883项全量通过**（`runs/schedules-control-all.log`，813.843秒）；驱动总耗时814.594秒、退出码0，见`runs/schedules-control-full-result.json`。`runs/schedules-control-full-snapshot.json`记录307个Python／requirements文件；检查后动态重新枚举完整文件清单并核对哈希，清单及内容均一致，`snapshot_unchanged=true`。这是本轮最终全量，先前1857／1862结果仅保留为历史快照；本地日志、snapshot及回执继续忽略，不随文档提交。

文档／来源只读核对确认8份说明327处本地链接均存在、17份CW公开资产／参考SHA-256匹配、4份固定上游研究源码Git blob／字节与固定目录树一致且SHA-256已记录、GPL原件哈希匹配。

本轮没有启动、检测或操控真实游戏，没有启用真实账号资源计划、登记真实系统任务、发送通知、新游戏采集或EXE构建。GUI、真实调度与游戏组合、系统睡眠恢复和用户机器上的长期常驻仍未验收；含游戏目标的跨重复整批预算、自动接续、系统自启及完成后操作仍有明确缺口。
