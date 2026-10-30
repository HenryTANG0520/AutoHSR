# 兑换码后端与逐码回执

更新日期：2026-10-30。本轮将固定March7thAssistant兑换流程适配到AutoHSR原生Flow／Context、配置与CLI，完成离线整合及全量检查。没有进行真实兑换或实时码表请求，完整表单／结果布局与实际游戏组合仍待验收。

## 固定来源与离线码表

参考版本为March7thAssistant提交`7cf6c6bed474539485d3b1504077ac352866829f`，作者为moesnow及其贡献者，保留[GNU GPL v3许可](../assets/upstream/March7thAssistant/LICENSE)。[原始兑换任务](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/daily/redemption.py)包含在线获取／本地回退、服务器与有效期筛选、手动批次、逐码输入／确认／结果以及成功后的邮件和通知行为。参考行为不代表已将上游输入框架、全局配置或GUI迁入。

[原样离线码表](../assets/upstream/March7thAssistant/redemption_codes.json)来自同提交的[码表文件](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/redemption_codes.json)，保留17条原始记录及`server`、`expires_at`、`code`字段；其中包含历史过期项。固定快照及远期到期日期均不证明游戏当前接受该码，是否成功须逐码读取实际反馈。后续筛选不能把`cn`与`global`混用，也不能把无可用码当作兑换成功。

| 固定文件 | Git blob | SHA-256 | 字节 |
| --- | --- | --- | --- |
| `tasks/daily/redemption.py` | `91668a3b8392223ee7136e64a543f632afc44dec` | `242c6ba6eacf129524013a0b5adc23b16c2e1c7b04e1c62480d864b476007eae` | 9131 |
| `assets/config/redemption_codes.json` | `038bb6a48fe050a185bd80a203ceae7b175c6a2d` | `9d5bbfd367f435338b7d9522545ac2f0c7f9878e1f0cbe874df6409107e37c65` | 2054 |

两份原件已在既有研究缓存中按固定Git tree核对Git blob、字节数和SHA-256，公开码表与缓存字节一致；Git文件属性保留码表原始字节，避免Windows换行转换改变固定来源哈希。机器可读记录见[source.json](../assets/upstream/March7thAssistant/source.json)，整体范围见[开发进度](development-roadmap.md)。码表仅作数据回退，不含账号凭据。

上游四个在线来源依次写在`valid_codes_for_server`中，实际抓取并发竞争首个有效列表：`m7a.top`、`github.kotori.top`代理、jsDelivr固定仓库的`main`路径和GitHub raw的`main`路径；全失败时读取本地表。它们与本轮下载的固定提交原件不同，本轮没有访问这些实时码表来测试可用性。

页面来源另参考固定[导航配置](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json)与[Screen实现](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/screen/screen.py)。五幅原始局部图保留在[redemption-ui](../assets/upstream/March7thAssistant/redemption-ui/)；原路径、公开路径及哈希已在同一清单登记：

| 公开文件 | 上游路径（相对`assets/images/`） | 原始尺寸 |
| --- | --- | --- |
| `title.png` | `screen/redemption.png` | 107×48 |
| `more.png` | `share/menu/more.png` | 35×15 |
| `paste.png` | `share/redemption/paste.png` | 18×22 |
| `clear.png` | `share/redemption/clear.png` | 16×22 |
| `confirm.png` | `zh_CN/base/confirm.png` | 91×29 |

五图均原样复制，逐张查看仅标题或控件局部，不含UID、账号内容或整图；它们不证明完整表单／结果布局已实机校准。游戏美术归HoYoverse及相应权利人，GPL许可不转移其权利，见[素材署名](../assets/ATTRIBUTION.md)。

## 配置与批次解析

当前配置字段见[Settings](../autohsr/config.py)与[兑换配置解析](../autohsr/redemption_settings.py)。保存配置与实际运行分开；禁用兑换时默认日常不因此获取码表或兑换，显式兑换入口另行校验本次所选来源。

| 字段 | 默认 | 含义 |
| --- | --- | --- |
| `redemption_enabled` | `false` | 是否将兑换加入启用它的运行流程 |
| `redemption_source` | `"online"` | `online`在线码表并允许固定离线回退；`manual`手动列表；`file`本地JSON码表 |
| `redemption_server` | `"cn"` | 明确选择`cn`或`global`；不通过账号凭据自动查询服务器 |
| `redemption_codes` | `[]` | 手动字符串列表，仅`manual`运行使用 |
| `redemption_catalog` | `""` | 本地JSON路径，仅`file`运行使用 |
| `redemption_claim_mail` | `true` | 兑换成功后的邮件阶段开关；不单独启用兑换 |

[码表解析](../autohsr/redemption_codes.py)最多读取256 KiB、2000行。JSON数组每项须有`server`、`expires_at`、`code`；重复字段、非法JSON及非有限数值拒绝整表。行级错误分别记录`invalid_row`、`invalid_server`、`invalid_code`、`invalid_expiry`，不据错误内容生成输入；其余服务器为`other_server`，到期时刻小于等于本次核对时刻为`expired`，同批相同原码为`duplicate`。

码必须为1至64个ASCII字母、数字或中文字符，不能含空白、控制符或标点。解析保留原字符串，不裁空格、不自动转大写、不做Unicode归一化；因此大小写不同的输入不被私自合并。手动列表也只采用合法且首次出现的原码，全部无效时不能启动手动兑换。以下均为虚构示例：

```json
[
  {"server": "cn", "expires_at": "2099-01-01T00:00:00+08:00", "code": "EXAMPLEONLY001"},
  {"server": "global", "expires_at": null, "code": "EXAMPLEONLY002"}
]
```

有效期为ISO时刻或`null`；`null`仅表示码表未声明到期。无时区的兼容值按UTC解释，并在诊断中计入`naive_expiry_assumed_utc`，不按本机时区猜测。在线解析按四个固定HTTPS来源依次尝试；响应有大小限制，不跟随重定向，不接受任意用户URL。在线失败后才读取随包固定回退表；取消／停止不作为下载失败继续回退。成功解析的空表或筛选后无有效码可以得到空批次，不表示任何一次兑换成功。

`CodeBatch`保存原码、所选服务器、来源摘要及逐行跳过原因；`public_summary()`仅给出数量、原因计数、来源种类和无时区日期计数，不包含原码。此解析阶段不读取游戏账号、不发送游戏输入，也不保存兑换成功回执。

## CLI：预览、保存与运行

[兑换CLI](../autohsr/redemption_cli.py)将预览工具放在加载运行配置和创建Runner之前。两个预览入口均须显式指定`--redemption-server cn|global`，只接受对应来源和服务器参数，不混入`--config`、通知或运行选项。

| 入口 | 实际行为 |
| --- | --- |
| `--redemption-check PATH` | 仅本地读取所选JSON、筛选及输出原码／跳过原因；不联网、不访问游戏、不写配置或回执 |
| `--redemption-fetch` | 显式联网预览四固定来源；不兑换、不访问游戏、不写配置或回执。失败返回错误，不冒充本地回退成功 |
| `--redeem-codes` | 实际启动原生独立兑换Runner，仅覆盖本次设置，不刷本、不保存配置 |
| `--run --with-redemption`或`--plan --with-redemption` | 将兑换加入本次日常；`--no-with-redemption`关闭本次日常兑换 |

以下是用法示例，本轮文档工作没有执行这些命令。前两条为预览；后两条会访问游戏并尝试真实兑换，示例码为虚构值：

```powershell
python -m autohsr --redemption-check .\examples\codes.json --redemption-server cn
python -m autohsr --redemption-fetch --redemption-server global
python -m autohsr --redeem-codes --redemption-server cn --redemption-code EXAMPLEONLY001 --redemption-code EXAMPLEONLY002 --no-redemption-mail
python -m autohsr --run --with-redemption --redemption-source file --redemption-catalog .\examples\codes.json --redemption-server cn
```

`--redemption-source online|manual|file`、`--redemption-server`、可重复的`--redemption-code`、`--redemption-catalog`及`--redemption-mail`／`--no-redemption-mail`均是本次覆盖。提供手动码会选择`manual`，提供本地表会选择`file`；两者不能同用，显式来源冲突会拒绝。运行参数仅允许独立兑换或普通`--run`／`--plan`日常；仅补领奖、周常接续、其他玩法和无运行入口不接受它们。`reward_only`排除兑换。

仅保存设置才持久化配置；预览、运行、日常CLI覆盖及邮件结果不自动把本次开关／码列表保存为未来默认。当前GUI编辑与新入口由现有界面工作另行接入，本后端说明不把这些字段视为已交付界面控件。

任务树的`daily`步骤可在`tasks`中显式选择`"redemption"`，并在该步骤参数中提供来源／服务器／码列表／码表／邮件选项；显式任务列表未选兑换时，不继承设置中隐藏启用的兑换。步骤内码表路径相对工作流文件夹解析。应用内定时若使用已启用本地码表的日常／计划，启用时冻结该文件的有界指纹并在执行前重核；这不登记系统任务，不绕过账号与未知回执门禁，也不把游戏目标的重复次数限制放开。详见既有[任务树](task-workflows.md)及[定时边界](schedules.md)。

## 账号、服务器与逐码回执

[RedemptionStore](../autohsr/redemption_store.py)使用本地账号标识、所选`server`和原码字符串三者共同定位记录。不同账号或不同服务器不互相继承结果；同一scope已有记录时不创建重复提交。原上游的全局`already_used_codes`列表不直接导入为已验证账号回执，也不根据当前表中删除某码就清除旧结果。

| 逐码状态 | 含义与后续行为 |
| --- | --- |
| `pending` | 提交前意图已经保存，尚无终态；不能按新码重发 |
| `redeemed` | 明确兑换成功；跨运行跳过，不等同邮件附件已领取 |
| `already_used` | 明确已使用；保留该原因，不增加本次成功数 |
| `expired` | 明确已过期；与码表筛选时的`expired`分别记录 |
| `invalid` | 明确无效；不与已使用或过期合并为成功 |
| `unknown` | 输入后结果／证据未核实；保留原意图，不自动重放或改成失败终态 |

意图包含本次运行目录内的PNG、账号／服务器／原码、本次输入代次及页面来源。`claim()`原子写盘后，输入前须由`require_pending()`重新读取实际落盘记录及原证据；写入失败不能授权提交。`finish()`须有本次运行中的两份不同路径PNG才能记已核实终态；未知可保留一份。记录保存原图字节／像素哈希、来源摘要和内容摘要，读取相应记录时重新核对，不因内存仍有旧对象就绕过磁盘损坏或证据变化。

账本为有界严格JSON，最多8 MiB／10000项，单份页面来源最多64 KiB；独占锁和原子替换保护实际提交归属。旧终态及未知结果不可被新结果覆盖；相同终态、证据和来源的重复保存只读复用。损坏文件、来源丢失、旧锁或待核对状态均保留，不新建空账掩盖问题。`public_summary()`只返回服务器和状态计数，不公开账号标识、原码、路径或证据摘要；完整回执属于本地私人运行数据。

## 原生执行与结果边界

[RedemptionWorkflow](../autohsr/redemption_run.py)由[DailyWorkflow.redemption](../autohsr/workflows.py)和独立`operation="redemption"`原生Runner调用。启用日常兑换时，它位于每日实训之后、原邮件与勋礼之前；默认关闭。独立兑换不建立刷本预算，也不因当前日常勾选项去刷本。非空批次先核实当前入口，必要时沿原生导航到手机菜单，以同输入代次的两份新鲜画面绑定账号，随后每次观察继续核对当前账号；服务器来自本次配置／覆盖，不把UID识别当作已核实服务器归属。

起点可为已核实手机菜单、已展开更多菜单或完整表单，复用当前阶段，不重复切换已有入口。每码按当前页面定位完整表单；输入框焦点、输入、确认、结果关闭与返回手机菜单分开记录。输入通过专用Context授权，重新推导当前目标、核对实际落盘意图与窗口，不调用上游通用点击或剪贴板。原生输入只在已核实表单中全选后以Unicode键盘事件输入有限原码；释放按键并逐字符检查停止／暂停。完整原码须在两份不同capture中精确读回，确认时再核对当前字段与原码一致，才保存逐码提交意图并点击一次。提交授权还核对当前RGB像素哈希／shape与意图原证据、表单摘要、本次run及动作ID，不只比较目标框。

提交后有限等待同一明确终态的两份独立capture，先保存回执，再关闭本次结果。旧结果弹窗不能借给新码；没有唯一目标、遮挡、动画、文本冲突、失焦、账号／输入代次变化或超时均停止该批，不重复提交确认，不自动跳过未知项继续输入。F9／失焦后原目标失效，兑换步骤不会由通用恢复逻辑重启整批；F10沿原生停止协议释放输入。已经落盘的逐码结果、旧失败和已核实每日奖励继续保留。

私人逐批文件为本次运行目录下的`redemption-session.json`，跨运行账本为`ROOT/runs/redemption-ledger.json`；源码版`ROOT`为项目根目录，打包版为EXE旁，二者独立。逐批记录含本次冻结码表来源／批次摘要、原码、账号来源、动作与逐码结果；不应作为匿名日志或公开素材发布。`report.redemption`保留该批数据，正常公共任务事件只给处理数量和结果说明。

本次新`redeemed`才触发可选邮件处理。日常本来已启用`mail`时，兑换记录为`deferred_to_daily_mail`并交给原邮件阶段，避免重复领取；其余情况调用原生邮件核验。邮件未完整核实可使兑换任务`partial`，不改已核实逐码成功。通知沿用独立、默认关闭的最外层运行结束通知，不照搬上游每批成功直接通知原码的方式；真实通知状态不能作为游戏兑换证据。

逐码终态、批次处理、原生任务及邮件是不同结果。空批次或全部得到已使用／过期／无效时，批次可以处理完毕而新成功数为0；任务`ok`或原生报告`success`只表示本次选择的批次流程完成，不能据此宣称所有码有效或全部奖励已领取。逐批`submitted`仅计本次已核实的新提交终态，不计`pending`；`redeemed`仅计本批新成功，复用旧终态标为`reused=true`，不再次增加这两个计数。每次保存session重算计数，关页或后续session写入异常不抹掉已确认逐码结果。已有逐码结果后的原生父报告异常记为`partial`，停止另列，邮件异常同样保留原码结果。

## 页面与界面接入接口

[页面识别](../autohsr/redemption_pages.py)只读取当前Scene，不执行输入。`phone_more_target()`和`redemption_entry()`返回唯一当前目标或`None`；`field_region()`读取当前输入框范围，供局部OCR使用；`read_form()`返回`Form`或`None`，含输入目标、ROI、完整原码／空态、独立确认目标及来源摘要；`read_result()`返回`Result`，没有明确终态时为`status="unknown"`，不能拿它授权关闭或确认。`Form.basis`与`Result.basis`为匿名页面来源，实际账号归属与提交动作由原生流程核验。

表单必须同时有标题、取消／确认关系、原局部图形及从当前可见背景恢复的闭合输入框；精确原码由同一ROI的两种局部OCR读数一致后提供，再由执行层要求两份不同capture。占位文字才证明空输入，缺少局部读数不能补为空。仅标题、原图标、一个“确认”文字、截断码或泛用白框均不能授权提交；暗淡／冲突／付款、补体力或登录验证提示优先阻断。结果必须匹配明确文字及完整关联结构；独立成功还须邮件说明正文与可用关闭确认，裸“兑换成功”仍未知。内联错误只开放已核实表单的Esc路径，不将原提交确认按钮当作结果关闭按钮。

后端复用点为`resolve_batch(settings, cancel=...)`、`run_redemption(context, batch=..., store=...)`及`RunReport.redemption`；界面保存时只保存设置，开始时冻结本次Settings，线程内通过原生Runner执行。原始逐码／账号／证据数据留在私人报告，不直接放入公共事件或通知正文。独立本地预览只需`from_file`，显式在线预览才使用`fetch_catalog`；不要为编辑表单或刷新控件隐式联网、读账号或创建Runner。

## 验证记录与限制

阶段**134项相关检查通过**`runs/redemption-related-final.log`（95.483秒），覆盖码表／存储、页面、真实Flow／Context假IO、配置／CLI、任务树、账号连续性及定时依赖。此前24项码表／存储另见`runs/redemption-codes-store.log`（1.232秒）；本地实际CLI预览见`runs/redemption-cli-preview.json`，不读运行配置、不联网、不访问游戏。早期夹具时钟、异常断言及漏导入的故障保留在`redemption-flow-first.log`、`redemption-flow-reviewed.log`及`redemption-related.log`，没有放宽页面或来源门禁；阶段21项流程／CLI通过`redemption-flow-final.log`（56.025秒）仍属于后续补强前快照。

首轮全量`runs/redemption-all.log`在227.781秒主动中止，以补齐逐字符回调的输入代次检查；对应`redemption-full-result.json`退出4294967295，不能当作全量通过。F9恢复／失焦后剩余字符立即丢弃，修复后**3项专项通过**`runs/redemption-typing-generation.log`（6.189秒）。已保存结果后的session写失败、已有form／more复用及提交前PNG正反例分别保留专项日志，原始证据和失败记录未删除。

最新冻结源码的**1985项全量通过**`runs/redemption-reviewed-all.log`（901.970秒），驱动902.703秒、退出0；`redemption-reviewed-full-result.json`及`redemption-reviewed-full-snapshot.json`核对323份Python／requirements与6份引用资源，重新枚举的完整清单及前后哈希一致，`snapshot_unchanged=true`。

提交前4份说明223处本地链接、54份固定树源码的Git blob／其中50份已声明SHA-256、GPL许可、6份原样分发文件及65处原生文件引用核对通过，见`runs/redemption-final-verification.json`。3个历史私人样本标签保持来源说明，不按仓库公开文件读出或发布；源码与资产清单未改变，运行数据、配置及凭据未纳入版本控制。

完整form／结果组合目前只有合成机制检查，5幅原件仅证明局部标题／控件来源。没有新实机截图、真实兑换、真实外部通知或EXE构建；真实页面、账号／服务器组合及完整无人接管路径尚未验收，GUI及自动服务器检测仍待适配。
