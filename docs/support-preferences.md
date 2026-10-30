# 支援角色与好友偏好

更新日期：2026-10-30。参考[三月七启动器](https://github.com/moesnow/March7thAssistant)的多候选支援选择，将角色、可选好友与有界滚动接入AutoHSR原生日常Runner。当前提供后端配置及CLI，GUI编辑控件和真实偏好借用尚未验收；本轮只使用合成窗口、公开参考头像与既有本地证据，没有启动、检测或操作真实游戏。

## 设置与运行

| 设置 | 默认值 | 含义 |
| --- | --- | --- |
| `use_support` | `true` | 保留原借用支援开关 |
| `support_preferences` | `[]` | 有序偏好；为空时沿用原好友支援流程 |
| `support_scroll_pages` | `10` | 每轮最多查看1～20页，包含当前页 |
| `support_fallback` | `stop` | 本次未核实可用偏好时，停止、另借好友或明确不借支援 |

偏好是最多256项的JSON列表，每项只含字符串字段`character`和`friend`；至少填写一项。角色使用[参考清单](../assets/upstream/March7thAssistant/support/sources.json)中的明确标识或唯一中文名，允许只指定好友；相同中文名对应多个形态时须选择具体标识。好友昵称最多40字，除首尾空格与既有卡片装饰星号处理外保持原文，区分标点和大小写，不用模糊包含匹配。重复的规范化角色／好友组合会被拒绝。

例如，下面优先查找指定好友的青雀，再查找任意好友的符玄，最后查找另一名指定好友：

```json
[
  {"character": "Qingque", "friend": "示例好友甲"},
  {"character": "FuXuan", "friend": ""},
  {"character": "", "friend": "示例好友乙"}
]
```

以下仅为用法说明，本轮没有执行这些游戏命令：

```powershell
.\.venv\Scripts\python.exe -m autohsr --run --support-preferences-file support.json
.\.venv\Scripts\python.exe -m autohsr --plan --support-preferences-file support.json --support-scroll-pages 5 --support-fallback friend
.\.venv\Scripts\python.exe -m autohsr --run --support-preferences-file support.json --support-fallback skip
```

指定偏好文件会在本次快照启用`use_support`，不自动保存设置。已保存非空偏好则在借用支援开启时生效；设置、偏好列表与候选顺序在Runner创建时冻结。新参数仅用于`--run/--plan`的日常阶段，不能用于仅补领奖、仅接续货币战争周常或只读检测。三个回退值为：

- `stop`：默认行为；本次有界查找未核实可用候选时停止开战。
- `friend`：明确允许另借其他好友。回到列表顶部，再进行一次同样页数上限的好友查找；此前明确满员的同一卡片不会通过另一偏好再次尝试。
- `skip`：明确允许本次不借支援。返回准备页并核实没有借用标记后继续；仍须通过原费用、次数、已有资源及编队门禁，不能跳过付款核验。

回退只在已配置偏好时有效。识别不完整、反馈冲突和选择结果不明会停止，不能用回退把未知状态当作候选不存在。

## 查找和反馈

沿用上游逐页查找方式：**每页先按偏好顺序，再按可见好友卡片顺序**。较低偏好在当前页可用时，不会先遍历全列表寻找较高偏好；报告保留实际选择的偏好索引。连续三页昵称／等级签名相同时提前结束有界查找，不能据此证明所有好友都不存在。

候选须在同一完整卡片关联高置信度的好友标记、等级和昵称。指定角色时，另外在该卡片头像局部比较105幅固定参考图；按1920宽归一化、有限尺寸变体和0.90阈值识别。先尝试原图，再尝试右上角26%角标遮罩，最后处理旧图中头像左侧的星魂数字遮挡；参考图原始字节不变。与其他角色参考图的分差须至少0.025，重复形态、相近头像或空图保持未核实。头像匹配只提供候选证据，点击前重新取图、绑定当前卡片，再经原生Context检查画面和输入代次。

选择后区分绿色支援标记、明确满员及未知反馈。满员提示必须消失，才能尝试下一张；满员和绿色标记同时出现则停止。普通副本在同一卡片来源再次核实后点击实际确认，饰品提取按原流程返回，最后均核实准备页及真实绿色支援标记。借用成功不直接计为每日实训的支援任务完成，也不代表战斗已经成功。

本功能不移除自身预设中的角色。饰品流程只可按原协议解除已核实的旧借用支援；其余已有支援标记若无法归属本次选择则停止。既有未知支援的自动接续、更换自身满员编队，以及上游“仅实训需要时借用”的条件模式均未在本轮实现。

## 报告与界面接口

`report.support_selections`按每次查找保存记录；日常／周常父报告保留原日常记录，后续周常失败不抹掉已核实借用。主要字段如下：

| 字段 | 含义 |
| --- | --- |
| `state` | `searching`、`borrowed`、`skipped`或`unverified` |
| `mode`、`requested` | 普通／饰品模式及冻结的角色／好友偏好 |
| `maximum_pages`、`pages_seen` | 每轮页数上限及实际查看总页数；另借好友时总页数可能为上限的两倍 |
| `attempts` | 实际提交的好友选择次数，不等于借用成功或战斗次数 |
| `selected` | 实际偏好索引（0起）、角色、好友及可选头像分数／遮罩／检测框；另借好友时索引为null |
| `fallback`、`fallback_used` | 配置回退与实际是否执行；`skip`也明确记录 |
| `evidence`、`error` | 本地证据路径及未核实原因 |

昵称及原始证据仅保留本地报告，不送入货币战争决策模型。界面可使用这些结果解释实际角色、好友和回退；本轮没有更改当前桌面设计，也没有把尚未接入的字段视为GUI已经完成。运行和CLI覆盖仍只使用快照，只有保存设置才持久化。

## 来源与验证

固定上游提交`7cf6c6bed474539485d3b1504077ac352866829f`，参考[Character.borrow及其查找过程](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/power/character.py)、[角标变体检查](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tests/test_tasks/test_support_character.py)与角色名称清单。上游代码按GPL v3署名，105幅未改字节的角色头像分别记录Git blob、SHA-256、尺寸与来源；游戏画面权利仍归HoYoverse等原权利人，见[素材说明](../assets/upstream/March7thAssistant/support/README.md)。本项目没有迁入上游输入框架、满员移除自身槽位或借用后直接标记实训完成的行为。

[新增检查](../autohsr/tests/test_support_preferences.py)覆盖偏好顺序、精确昵称、非好友排除、形态区分、遮挡、960／1920／3840宽合成变体、相似候选拒绝、逐页／回退、满员提示消退、冲突和未知反馈、选中后头像变化、原饰品支援路径、正式Runner／Context与已有资源预算、饰品明确跳过及父报告保留。素材匹配变体使用固定参考图构造，是机制检查，不是独立真实留出集。

两份2026-10-20既有普通／饰品列表按匿名卡片位置只读回放，共10行，涉及Cyrene、SilverWolfLV999和Sparxie三种角色；匹配分数约0.927～0.949，原件SHA-256保持不变。它们用于布局和局部遮罩校准，未重新运行OCR、核实当前好友身份或重放点击；相邻列表不能当作独立整局验收。私有记录保存在`runs/support-preferences-qa/old-portrait-audit.json`，不公开原图、UID或好友昵称。

| 检查 | 结果与边界 |
| --- | --- |
| 最终相关回归 | 312项通过，14.374秒，`runs/support-preferences-related-final.log`，含29项新增 |
| 项目虚拟环境全量 | 1618项通过，731.163秒，`runs/support-preferences-all-tests.log`；覆盖本轮最终代码 |
| 原GUI假后端 | 84项通过，`runs/support-preferences-gui.log`，配置不被运行／检测写入；不包含尚未接入的新字段 |
| 固定来源 | 12份源码／名称文件和105幅头像的Git blob与SHA-256核对通过 |
| 说明与入口 | 相关说明相对链接、CLI帮助和`git diff --check`通过；没有执行示例中的游戏命令 |

没有重建EXE，没有新增资源消耗或实机通关计数。字幕自建窗口此前的焦点失败记录继续保留；本轮没有修改字幕或重复该检查。
