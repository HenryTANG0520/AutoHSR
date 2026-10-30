# 运行结束文字通知

更新日期：2026-10-30。通知后端和CLI已接通，默认关闭；当前GUI尚无通知设置或状态呈现。固定参考March7thAssistant提交`7cf6c6bed474539485d3b1504077ac352866829f`的23个渠道，只适配文字发送路径，不能称为23个渠道的全部功能复现。所有真实远端渠道及本机Toast均未验收，本轮开发没有实际发送通知或操作游戏。

## 启用范围

当前正式CLI的日常、计划、差分、货币战争各Runner、目录采集及任务树可使用运行结束通知；`--check`、`--launch`、离线回放、记录工具等独立入口不通过此包装。通知在最外层Runner返回、原游戏输入释放后顺序执行，不在子任务之间发送。任务树只对父流程发一次结束通知；失败的子步骤不能被包装为父流程成功。

通知依据原报告的`success / partial / failed / stopped`过滤，默认不通知`stopped`。它不改变游戏报告、已验证的每日／胜利、游戏退出码或验收计数。通知失败、取消或未知单独报告。原Runner抛出普通异常时可尝试一条“失败／报告未保存”的摘要，随后继续抛出原异常；键盘中断保留中断语义。

当前是运行结束摘要，不推送逐条日志或每个战斗结果。摘要只从允许字段生成：任务类型、原结果、报告是否保存、每日核实、副本完成和已记账／待核对体力、差分请求／完成局数，以及已有的货币战争胜负／积分／领奖结论。缺失数字显示“未核实”，不补零。自动摘要不含UID、账号指纹、安装路径、原始异常、截图、OCR或原始日志；自定义模板和接收地址由用户自行明确配置。

## CLI：本地管理与实际发送

以下只列示用法，本轮没有执行`--notify-test`。通知工具是互斥的独立入口，不能与游戏、记录、管理员或运行覆盖选项混用；无需加载游戏配置、聚焦窗口或接触游戏。

```powershell
# 只列固定23个渠道，不读取凭据、不联网
.\.venv\Scripts\python.exe -m autohsr --notify-providers
# 只列本地配置的名称、渠道和可读性，不输出params、不联网
.\.venv\Scripts\python.exe -m autohsr --notify-profile-list
# 只读解密、格式与本地参数检查；不验证远端凭据有效性、不联网
.\.venv\Scripts\python.exe -m autohsr --notify-profile-check example-hook
# 显式导入并加密保存；本地写入，保留输入JSON原件，不联网、不发送
.\.venv\Scripts\python.exe -m autohsr --notify-profile-import .\example-notify.json
# 明确覆盖同名配置；先保留旧加密备份，不联网、不发送
.\.venv\Scripts\python.exe -m autohsr --notify-profile-import .\example-notify.json --notify-replace-profile
# 实际向所选渠道发送一条测试消息；每次显式调用是新的测试
.\.venv\Scripts\python.exe -m autohsr --notify-test example-hook
```

`--notify-store-dir <目录>`仅可用于上述独立通知工具，替换工具的本地存储根目录；正式游戏／任务树运行始终使用当前运行版的`ROOT/notifications.local/`。因此在自定义目录导入的配置不会自动被正常运行选中。源码版ROOT在项目根目录，打包版在EXE旁，两者独立。

成功的本地管理返回`status=success`、`network_accessed=false`。检查另返回`remote_credentials_verified=false`。实际测试返回通知结果，不以导入成功证明服务端可用：`accepted`退出码0，其他发送结果退出码1；参数／本地配置等错误为2，键盘中断130。测试文字固定为“AutoHSR 通知测试”和明确的测试说明，不表示执行过游戏任务。

运行时覆盖示例会执行所选真实任务，须按该任务原有授权与预算使用：

```powershell
# 明确选择一个或多个已保存配置，同时启用本次结束通知，不保存设置
.\.venv\Scripts\python.exe -m autohsr --run --notify-profile example-hook
.\.venv\Scripts\python.exe -m autohsr --plan --notify-profile example-hook --notify-profile example-mail
# 仅切换本次总开关；--notify要求设置中已经有配置列表
.\.venv\Scripts\python.exe -m autohsr --run --notify
.\.venv\Scripts\python.exe -m autohsr --run --no-notify
# 任务树只包装整个父流程；只读--task-workflow-check不接受通知覆盖
.\.venv\Scripts\python.exe -m autohsr --task-workflow .\example-workflow.json --notify-profile example-hook
```

`--notify-profile`可重复，名称不得重复；不能同时与`--no-notify`使用。不带任务而只传这些运行覆盖参数会报错。导入不自动启用总开关，也不自动把该配置加入运行列表。

## 配置、凭据与模板

普通设置只保存非敏感偏好；仅显式保存设置时持久化，运行覆盖不写回。

| 设置字段 | 默认值 | 约束 |
| --- | --- | --- |
| `notification_enabled` | `false` | 布尔；启用时须明确选择配置 |
| `notification_profiles` | `[]` | 最多32个不重复名称，按列表顺序发送 |
| `notification_statuses` | `["success", "partial", "failed"]` | 非空、不重复，仅允许四种原游戏结果，可显式加入`stopped` |
| `notification_title` | `AutoHSR · {operation} · {status}` | 最多4096字符的合法模板 |
| `notification_body` | `{summary}` | 同上；默认使用允许字段摘要 |

模板仅支持`{operation}`、`{status}`、`{summary}`，不执行表达式、属性访问、转换或格式指令；字面花括号使用`{{`、`}}`。格式化后标题最多160个UTF-16代码单元、正文最多4096个UTF-16代码单元，超限拒绝发送，不静默截断为“完整结果”。渠道自身可能有更小的远端限制，尚须真实验证。

导入JSON必须恰有`id`、`provider`、`params`三项。文件为UTF-8（可有BOM），最大64 KiB；拒绝重复字段、NaN／无穷、未知参数及无效类型，不忽略尚未实现的图片／加密字段。`id`为小写字母开头的1～64位小写字母、数字、下划线或连字符。

```json
{
  "id": "example-hook",
  "provider": "webhook",
  "params": {
    "url": "https://example.test/notify",
    "headers": {"Authorization": "Bearer FICTIONAL_TOKEN"},
    "body": {"title": "{title}", "content": "{content}"}
  }
}
```

这只是不可用的虚构示例。`webhook.body`和`custom.data`的字符串叶节点支持`{title}`、`{content}`和合并二者的`{message}`替换，嵌套深度最多8；`{image}`明确拒绝。它们与普通设置的摘要模板是两套字段规则。

凭据只由当前Windows用户DPAPI保护，保存为`notifications.local/profiles/<id>.dpapi`；无机器级共享或明文凭据副本。该目录整体忽略，不提交。显式替换先保存同目录唯一名`.dpapi.bak`再原子替换；失败不静默覆盖。导入文件原件仍由用户保管，导入不会删除或自动加密原件。更换Windows用户或无法解密时报告不可读，不能视为已配置可用；当前没有明文导出、自动迁移或远端凭据发现功能。

运行开始时冻结配置和加密凭据版本；每次授权、检查及发送前核对版本。运行期间同名配置被改动、删除或损坏，会停止该配置的发送，不改发到新地址。公开列表、事件及稳定错误不输出凭据或服务端响应原文。

## 23个文字渠道及参数

下表字段大小写敏感，列出当前允许参数；未列字段会被拒绝。每行另可带布尔`allow_insecure=false`。默认要求HTTPS，回环地址允许HTTP；其他HTTP需明确设为`true`。URL不接受内嵌用户名／密码、fragment或空白。`headers`最多32项，禁止Host、Content-Length、Transfer-Encoding、Proxy-Authorization及换行。高级代理／PAC参数尚未适配；传输可能沿用Python标准库的环境代理行为，不提供专用代理设置或保证。

| provider | 必填或接收对象要求 | 其他允许参数与默认行为 |
| --- | --- | --- |
| `telegram` | `token`、`userid` | `api_url`（默认Telegram官方API主机，支持主机名或URL）、整数`thread_id`；`sendMessage`文字 |
| `matrix` | `homeserver`、`access_token`、`room_id` | `device_id`、`user_id`仅接受配置，未实现设备／E2EE流程；发送前必须取得未加密房间检查的404及`M_NOT_FOUND` |
| `onebot` | `endpoint`，`user_id / group_id`至少一个 | `token`可选Bearer；`/send_msg`文字段，两目标依次发送 |
| `smtp` | `host`；发件`From`或`user`，收件`To`或`user` | `user`、`password`、`From`、`To`（地址字符串或最多50项列表）、`port`、`ssl=true`、`starttls=false`；STARTTLS优先，端口未设时分别587／SSL 465／明文25；认证需密码 |
| `gocqhttp` | `endpoint`，`user_id / group_id`至少一个 | `path=/send_msg`、`token`、`auto_escape=true`；GET文字请求；可用`message_type=private / group`明确只发对应目标（须有该ID），省略则依次处理所有已填目标；endpoint可省HTTP方案，非回环仍需显式允许HTTP |
| `wechatworkapp` | `corpid`、`corpsecret`、`agentid`、`touser` | `base_url`默认企业微信官方API；先独立取token再文字发送，不持久化临时token |
| `wechatworkbot` | `key / webhook_url`至少一个 | `webhook_url`优先，否则由key构造官方机器人地址；文字 |
| `custom` | `url` | `method=POST`、`datatype=data`（`data / json / params`）、`data`默认标题／正文对象；不支持自定义headers（使用webhook） |
| `lark` | `webhook` | `sign`、`keyword`；文本post，支持时间戳HMAC签名及关键词前置 |
| `serverchan3` | `sendkey` | `sctp`凭据按声明的数字子域路由，其他使用兼容地址；文字标题／正文 |
| `serverchanturbo` | `sctkey` | `channel`、`openid`；表单标题／正文 |
| `kook` | `token`、`target_id` | `chat_type="1"`，仅字符串`"1" / "9"`；沿用上游配置含义，1为私聊（direct-message/create、文字），9为频道（message/create、Markdown）；API的type另表示内容格式 |
| `webhook` | `url` | `method=POST`、`headers={}`、`body`默认标题／正文JSON；body字符串原样UTF-8发送；GET／POST／PUT／PATCH／DELETE可选 |
| `meow` | `nickname` | 官方MeoW端点，文字标题／正文 |
| `bark` | `key / device_key`至少一个 | `base_url`默认官方push地址、`group`、`icon`、整数`isarchive`、`sound`、`url`（点击链接）、`copy`、整数`autocopy`；明文JSON，不支持密文 |
| `dingtalk` | `token`（令牌或完整机器人URL） | `secret`支持时间戳HMAC签名、`markdown=false` |
| `discord` | `webhook` | `username`、`avatar_url`、整数`color=16478873`；文字embed，未适配图片或附件上传 |
| `gotify` | `url`、`token` | 整数`priority=0`；`/message`文字 |
| `pushdeer` | `token / pushkey`至少一个 | `type=markdown`、`url`默认官方消息接口；文字 |
| `pushplus` | `token` | `markdown=false`（默认html模板）、`topic`、`channel`、`webhook`（服务路由名称）、`callbackUrl` |
| `qmsg` | `key` | `mode=send`（`send / group`）、`qq`可选；文字表单 |
| `qqbot` | `appid`、`client_secret`，`openid / group_openid`至少一个 | 先取官方token，再向明确目标依次发文字；不监听事件、不发现ID |
| `winotify` | 无必填params | `app_id=AutoHSR`；Windows原生Toast文本，通过隐藏PowerShell提交；无图片、按钮、声音选项 |

数字型接收ID只在`userid / user_id / group_id / agentid / appid / qq / target_id`字段接受JSON整数并转成文字。其余连接参数为单行字符串；布尔字段不能用`"true"`替代。整数校验及最终请求以[当前适配源码](../autohsr/notify_providers.py)为准，SMTP端口额外限制1～65535。

尚未实现：截图／图片发送与上传、Bark密文、Matrix E2EE和设备会话、QQ机器人事件／接收ID发现、上游PAC与代理高级项、上游通知等级／图片开关和整套自动合并机制、任务树内任意通知步骤、GUI配置与结果呈现。部分文本可采用Markdown／HTML承载，不表示图片或富媒体功能已完成。

## 一次提交、意图与回执

每份原报告按本地来源标识生成键，再与配置名称组合成通知键；原始run路径只参与本地哈希，不进入发送文本。`notifications.local/attempts/<键>.json`记录版本、消息哈希、动作及结果，`.lock`保护同键并发。此目录与凭据一起忽略，不改写原游戏报告。

授权取token、Matrix房间检查和每个实际发送动作都先写`pending`意图，落盘成功后才调用传输；动作回执及最终结果分别持久化。同报告同配置再次出现时复用原结果，`pending`返回`unknown`，不重发；版本改变返回`unknown / profile_changed`。旧回执损坏／缺字段不重建发送记录，已失败、取消和未知也不自动重试。最终回执写入失败返回`unknown / receipt_write_failed`，保留原意图。显式`--notify-test`每次生成独立测试键，因此再次执行本身就是另一次真实发送请求。

HTTP每次调用单次提交，不跟随重定向；socket操作timeout为15秒，分块读取循环检查从请求开始计时的30秒观察截止，响应最大1 MiB，请求体最大64 KiB。30秒不是整个调用的硬性总时限，DNS解析或最后一次阻塞读取可能使实际返回更晚。多目标按顺序发送，遇首个非`accepted`停止该配置后续目标；一个配置出错后仍可继续其他已选配置。SMTP为每个socket操作15秒超时，不是整个邮件会话总限；Toast子进程timeout为15秒。暂停／停止仅在动作边界检查，不重发或强行撤销已提交请求。

| 结果 | 精确含义 |
| --- | --- |
| `accepted` | 服务端字段／HTTP、SMTP或Toast调用返回符合当前受理规则；不证明用户已收到、阅读或Toast实际可见 |
| `partial` | 某些目标已受理、其他目标未完整受理；或企业微信／SMTP明确返回部分接收方问题 |
| `rejected` | 明确的协议拒绝、本地Toast进程失败，或冻结配置不可读；不代表游戏失败 |
| `unknown` | 超时、响应缺失／冲突、5xx、3xx、旧pending、凭据版本改变、回执异常等无法核实；不自动重试 |
| `cancelled` | 在尚无未确认发送动作的边界收到停止；若已有发送pending则该配置结果保持unknown |
| `reused=true` | 本次只读复用已有回执，没有新提交；可与上述结果组合 |

一般HTTP 4xx为`rejected`，3xx／5xx为`unknown`；2xx仍按各渠道业务字段核对。OneBot／GoCQHTTP仅`status=ok, retcode=0`视为accepted，async或矛盾字段保持unknown。通用Webhook和Discord等仅证明HTTP受理，不等待接收端的人工交付。Matrix未核实无加密就不发明文；授权失败不提交后续消息，但其通知总体可能保持unknown，不能据此推断凭据有效。

## UI与Runner接口

入口为[notify_runtime.hooks](../autohsr/notify_runtime.py)：`child_emit, wrap_runner = hooks(settings, emit)`。关闭时原样透传，启用时冻结设置与配置。创建最外层原生Runner时使用`child_emit`，再调用一次`runner = wrap_runner(runner)`；不能在子Runner重复包装。正常返回时先完成通知阶段，再以原报告发一次`finished`并原样返回report。异常仍按原Runner异常处理，不伪造成功报告。

包装器保留其他Runner属性。游戏阶段`toggle_pause / stop`传给原Runner；通知阶段只暂停／停止通知，`paused`事件附`phase=notification`，不再次操作游戏输入。子Runner返回并结束原快捷键监听后，通知阶段另开F9／F10监听，完成时停止并join；F9只响应已知游戏控制窗口前台的按键上升沿，F10停止后续通知。监听故障也停止后续发送并发稳定错误日志。已进入socket／SMTP／PowerShell调用须等待返回或适用超时，不能承诺撤回已提交消息。现有GUI后续接线可继续使用包装器的`toggle_pause / stop`；配置管理可直接使用[ProfileStore](../autohsr/notify_profiles.py)的`list_public / save / load_version`，不能把私有params放入普通设置、公共事件、日志或报告。

| 公共事件 | 字段与UI含义 |
| --- | --- |
| `notification_phase` | `phase=notification`、`profile`、`status=running`、原`game_status`、`requested_profiles`；显示当前正在通知，保留已结束的游戏结果 |
| `notification_result` | `profile`、通知`status`；正常传输结果另含`provider`、`reused`，错误可能只有`reason`，这些字段均按可选处理 |
| `notification_summary` | 被原结果过滤时`status=filtered, profiles=0`；否则为`accepted / partial / cancelled`，含已处理`profiles`、`requested_profiles`、`accepted`计数；捕获阶段异常时可为`unknown, reason=notification_unverified`且不保证计数字段 |
| `finished` | 正常返回时最后发出一次，`report`仍是原游戏／父流程报告；通知状态另保留 |

summary只有全部已处理配置均为accepted且未停止才为accepted，其他非取消情况为partial；它不是逐配置unknown／rejected的替代。停止可令`profiles < requested_profiles`，未处理配置不能被UI显示成已发送。已受理的复用回执也计入accepted，UI应同时显示其reused标记，避免称为本次新发送。

## 验证记录与剩余事项

2026-10-30通知专项31项及渠道合同12项，共43项；与CLI、任务树、账号连续性、计划及记录工具相关合计148项通过（`runs/notifications-reviewed-related.log`，7.661秒）。检查覆盖23渠道的构造／回执、严格参数、受保护凭据／备份／冻结、未知不重发、损坏旧回执不重建、最外层事件、F9前台边沿与F10监听交接，以及GoCQ目标选择、KOOK端点、OneBot异步未知和Content-Type大小写等离线机制，远端传输与本机通知均由替身隔离。此前133项`runs/notifications-related-final.log`（6.654秒）及132项`runs/notifications-related.log`（6.988秒）保留。

假后端GUI84项通过（`runs/notifications-gui.log`）；独立真实CLI进程的6项核对通过（`runs/notifications-cli-verification.json`），范围为注册表、DPAPI导入／检查／列表、拒绝隐式覆盖、显式备份及帮助文本，不实际发送。这些检查不表示GUI已经有通知配置页。

本轮冻结源码后的全量1788项通过，单测耗时812.908秒，日志为`runs/notifications-all.log`；驱动总耗时813.797秒、退出码0，见`runs/notifications-full-result.json`。`runs/notifications-full-snapshot.json`保存296份Python／requirements文件的SHA-256，检查前后哈希一致，`snapshot_unchanged=true`。这些本地验证记录继续忽略，不随文档提交。

文档与来源只读核对另确认：23行渠道表与当前注册表一致，167处本地相对链接均存在；新增26份上游来源的SHA-256、Git blob及字节数与固定目录树／下载审计逐份匹配，GPL原件哈希一致。示例仅含虚构凭据和`example.test`，未导入真实接收配置。

本次没有真实推送、Toast可见性、真实邮箱、真实代理、实际服务凭据、GUI设置、游戏后通知组合或新EXE验收。离线通过不等于23渠道的真实交付成功，也不改变玩法验收或旧货币战争0/10。固定上游版权、26份实际参考源码的Git blob／SHA-256及原生扩展边界见[来源说明](../assets/upstream/March7thAssistant/README.md)和[清单](../assets/upstream/March7thAssistant/source.json)。
