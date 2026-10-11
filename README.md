# AutoHSR

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)
[![Platform: Windows](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011-blue)](#使用范围)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue)](#从源码安装)

**通过屏幕识别与模拟输入完成《崩坏：星穹铁道》每日任务的 Windows 桌面助手。** 当前版本为 `0.1.0`。

| 功能 | 当前行为 |
| --- | --- |
| 持续委托 | 领取可领取奖励，核实持续进行 |
| 拟造花萼 | 按名称与地点定位、借用好友支援、自动战斗与结算 |
| 每日实训 | 领取奖励，核实活跃度与领取状态 |
| 已拥有月卡 | 识别今日免费补给并核实领取结果 |
| 邮件 / 无名勋礼 | 可选，默认关闭，尚未完成实机验证 |
| 运行控制 | F9 暂停 / 继续，F10 停止，保存报告与关键画面 |

项目为非官方社区工具，与游戏开发商、发行商无关联。使用前请了解游戏服务条款及自动化工具的使用限制，自行决定是否使用。

AutoHSR 是面向《崩坏：星穹铁道》的 Windows 每日助手初版。它参考 BetterGI 的屏幕截图、OCR / 图标识别、模拟鼠标键盘输入流程：识别当前页面，执行一个动作，再检查页面变化。遇到未知页面、窗口失焦或验证失败会停止，并保存日志与截图。

用户确定的标准每日路径是**指南 → 指定副本 → 借用好友支援 → 使用已有开拓力刷最多 240**。完整执行标准、永久禁项和小规模测试要求见 [DAILY_FLOW.md](DAILY_FLOW.md)。

本版已实现持续委托奖励领取、拟造花萼挑战、每日实训奖励领取。4.6 的持续委托只领取可领取奖励并核实持续进行，保留原委托，不重新派遣或变更选择。邮件和无名勋礼领取是可选项，默认关闭；当前客户端的全部页面与奖励状态仍需实机校准。软件不会把未确认的奖励或战斗标记为完成。

登录时可处理已拥有月卡的今日补给：核实剩余天数与免费领取提示，领取后核实 90 星琼展示，再关闭展示进入场景。遇到购买、续购、支付或无法确认的奖励卡会停止。

## 使用范围

- Windows 10 / 11，游戏语言为简体中文，游戏客户区为 16:9，至少 960×540；建议使用 1920×1080 窗口。
- 采用 Windows DPI 感知、客户区截图和按分辨率缩放的模板。4K 屏幕及系统缩放环境先使用“检测窗口”确认识别结果；运行期间保持窗口尺寸与位置不变。
- 提前完成账号登录、更新和验证码。已登录、停留在“点击进入”画面时，助手可以识别后尝试进入游戏；不会处理密码、扫码、验证码、协议确认或下载更新。
- 预先配置能完成目标花萼的队伍，并解锁自动战斗。默认目标是“回忆之蕾 / 城郊雪原”，可在界面修改名称与地点；地点用于区分同名花萼。留空时当前实现会选择首个完整可见的匹配候选，标准每日应填写明确地点。保持“借用好友支援角色”勾选，借用好友角色挑战。

标准每日仅消耗**已有开拓力**，每次运行上限默认 **240**。首次实机测试请设置**上限 10、每次 1 轮**，仅测试少量战斗，确认识别和结算正常后再调整。上限是一次运行的累计消耗限额，不会自动恢复或购买开拓力。现有量不足 240 时使用可支付的整轮挑战，随后停止并报告 `partial` 和实际消耗。

**永久禁止自动抽卡、角色 / 光锥 / 遗器养成、商店、合成、购买和兑换。** 不使用燃料或星琼补充开拓力。出现补充、购买、兑换或需要选择奖励的界面会停止相关操作。配置中的 `allow_stamina_spend=false` 会锁定刷本任务及相关设置；界面没有自授权开关。

## 运行打包版

如果已有 `dist\AutoHSR\AutoHSR.exe`，双击项目目录中的 `Start-AutoHSR.cmd`；也可直接运行该 EXE。保持整个 `AutoHSR` 文件夹完整，不要只复制 EXE。

如果游戏以管理员权限运行，使用 `Start-AutoHSR-Admin.cmd` 并确认 Windows 的管理员提示。它仅以管理员权限启动助手，隐藏启动器控制台，图形界面正常可见；不会更改系统执行策略或其他系统配置。

配置和运行记录保存在 EXE 所在目录的 `config.json` 与 `runs\`，因此请将程序放在可写目录。

源码缺少本地配置时使用 **240 开拓力 / 6 轮、回忆之蕾 / 城郊雪原、借用好友支援** 的默认值。首次运行请先选择“测试 10 / 1 轮”，核实目标地点后保存或开始；预设本身不会执行任务。仓库不包含打包产物，可按下方步骤自行构建。

## 从源码安装

需要 Python 3.10 或更新版本。`setup.ps1` 默认依次寻找系统的 `py`、`python`、`python3`，创建项目内的 `.venv` 并安装 `requirements.txt`，保留已有虚拟环境。

克隆仓库，然后在项目目录打开 PowerShell：

```powershell
git clone https://github.com/HenryTANG0520/AutoHSR.git
cd AutoHSR
```

安装依赖：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1
```

如果使用自选 Python 或应用附带的 Python runtime，显式指定解释器路径；无需修改脚本，也不依赖某个用户名或安装目录：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup.ps1 -PythonPath "C:\path\to\python.exe"
```

这里的 `ExecutionPolicy Bypass` 仅作用于这一次 PowerShell 进程。脚本不会修改机器或用户级执行策略，也不会安装系统级 Python。

安装后双击 `Start-AutoHSR.cmd`，或运行：

```powershell
.\.venv\Scripts\python.exe -m autohsr
```

启动器优先使用打包版 EXE，找不到时才使用 `.venv\Scripts\pythonw.exe` 启动源码界面。

源码更新后已有 EXE 不会自动更新。开发时使用上面的 `.venv\Scripts\python.exe -m autohsr` 明确运行源码，验证后重新构建打包版，再使用启动器。

## 每日执行

1. 启动游戏并完成登录。默认游戏路径为 `E:\miHoYo Launcher\games\Star Rail Game\StarRail.exe`，路径不同可在“游戏与设置”页选择。
2. 点击“检测窗口”。助手暂时最小化以让游戏聚焦，完成后恢复界面。“窗口检测”页显示窗口尺寸和助手权限；点击“识别详情”阅读完整 OCR 结果，或点击“查看截图”。
3. 在“每日配置”页勾选任务，填写副本名称与地点，标准每日勾选“借用好友支援角色”。“每日 240 / 6 轮”和“测试 10 / 1 轮”只填写开拓力上限与每次轮数，**不会保存或自动执行**。建议首次仅开启委托，或采用测试模式；当前小规模刷本测试地点为“绘世学院”，邮件和无名勋礼仍可保持关闭。
4. 点击“开始每日任务”。设置会保存，助手最小化，执行中不要移动游戏窗口或操作鼠标键盘。
5. 按 **F9** 暂停 / 继续；暂停时助手窗口会恢复。按 **F10** 紧急停止，也可使用界面的“停止”。关闭助手会先发送停止请求。
6. 结束后查看各项状态、已确认开拓力消耗和每日奖励验证，可点击任务行阅读说明，或打开“最后报告”和“运行目录”。每日实训只有在活跃度与全部奖励状态均获得画面证据后才标记完成。

界面底部会提示未保存的修改，“保存配置”可单独保存表单。未勾选花萼时副本设置会禁用；运行、检测或启动期间设置锁定。执行区显示当前任务、本次耗时和已确认消耗，暂停后可查看详情与记录；停止或异常结束会明确标注未完成、未执行的任务。关闭正在执行的助手会先停止并等待后台退出；关闭前有未保存修改时可选择保存或放弃。

首次 OCR 加载可能需要等待。游戏失焦、最小化、窗口移动、无法识别页面或战斗超时都会中止操作；恢复游戏主界面后再重新检测与开始。

## 命令行与记录

```powershell
# 检测与 OCR，只输出 JSON，不点击任务按钮
.\.venv\Scripts\python.exe -m autohsr --check

# 只启动游戏；登录和验证仍需手动完成
.\.venv\Scripts\python.exe -m autohsr --launch

# 按保存配置执行；当前小规模测试使用绘世学院、10 开拓力、1 轮
.\.venv\Scripts\python.exe -m autohsr --run --target "回忆之蕾" --location "绘世学院" --stamina 10 --rounds 1

# 离线单元测试，不启动或操作游戏
.\.venv\Scripts\python.exe -m autohsr --self-test
```

可用 `--config "路径\config.json"` 指定配置文件。源码 GUI 的配置和 `runs\` 在项目目录；打包 GUI 使用 EXE 同目录的配置和记录，两者独立。GUI 可显式保存配置，也会在点击检测、启动或开始时保存设置；命令行 `--target`、`--location`、`--stamina`、`--rounds` 覆盖仅作用于本次执行，不写回 GUI 配置。每次运行保存 `run.log`、`report.json` 及关键画面 PNG / OCR 文本，检测结果另存为 `check_...` 目录。首次排查优先查看最新报告中的失败原因和对应截图。

打包版是无控制台的图形程序。使用 EXE 的 `--check` 或 `--run` 时，请读取 EXE 同目录 `runs\` 下的 `check.json` 或 `report.json`；需要终端 JSON 输出时使用上面的源码命令。

## 构建

先完成源码安装，再执行：

构建会重新生成 `dist\AutoHSR` 输出目录。重建前关闭已有助手；脚本会把该目录中的 `config.json` 和 `runs\` 备份到 `build\userdata-时间戳` 并在构建结束后恢复，构建失败时也保留备份。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tools\build.ps1
```

脚本使用项目虚拟环境中的 PyInstaller；缺少时会安装该打包依赖。输出为 `dist\AutoHSR\AutoHSR.exe` 和配套文件夹，包含 RapidOCR、ONNX Runtime、识别模板与许可证，并复制本说明和 `DAILY_FLOW.md`。打包资源位于 `_internal\assets\`，来源说明为 `_internal\assets\ATTRIBUTION.md`。

## 验证状态

2026-10-11 已通过 **140 项离线测试**。GUI 已检查 1100×760 / 1180×820 布局，并用模拟后台验证模式切换、保存与校验、检测摘要、暂停 / 恢复 / 停止、结果收尾、报告入口和授权锁定；源码下可运行 `.venv\Scripts\python.exe tools\gui_smoke.py` 重现，它不会访问游戏或启动器。

在当前简体中文客户端、3840×2160 客户区实机验证了月卡补给关闭、持续委托领取 / 进行中核实、指定花萼、好友支援、自动战斗、结算退出，以及每日实训 **500 活跃、五档奖励均已领取**。本轮累计五次单轮挑战，消耗 **50 现有开拓力**；未使用后备开拓力、燃料或星琼补充。最新打包版端到端报告为 `success`。途中发现的好友选择与结算动画问题已修复，原始失败报告仍保留；详见 [VALIDATION.md](VALIDATION.md)。

本轮没有执行完整 240 开拓力 / 6 轮批次实测，也没有验证后备领取、其他副本、可选邮件 / 勋礼页面或不同版本与缩放组合。上述场景不能沿用本次实机成功结论；未知状态仍会停止并保存证据。

## 来源与许可

本项目以 **GPL-3.0-only** 发布，完整文本见 [LICENSE](LICENSE)，版权与适用范围见 [LICENSE_NOTICE.md](LICENSE_NOTICE.md)。发布修改版或二进制时，应按许可证要求保留声明并提供相应源码。架构参考 [BetterGI](https://github.com/babalae/better-genshin-impact)；部分识别模板来自 [StarRailOneDragon](https://github.com/OneDragon-Anything/StarRailOneDragon) 和 [StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot)。具体文件、来源版本、修改方式和上游许可保存在 [assets/ATTRIBUTION.md](assets/ATTRIBUTION.md) 及对应上游许可证中。游戏画面与名称仍属于相应权利人。


## 项目结构

```text
autohsr/                 界面、窗口控制、识别、策略与每日流程
  tests/                 离线测试
assets/                  识别模板、来源记录与上游许可证
tools/                   构建、GUI 检查和实机诊断工具
setup.ps1                创建虚拟环境并安装依赖
requirements.txt         直接依赖
requirements-lock.txt    当前开发环境依赖快照
DAILY_FLOW.md            每日流程与操作边界
VALIDATION.md            开发期间的验证记录
```

`config.json`、`runs/`、`.venv/`、`build/` 和 `dist/` 不纳入版本控制。验证记录中的本地报告或截图路径用于开发追溯，公开仓库不包含这些原始运行文件。

## 反馈与贡献

通过 [Issues](https://github.com/HenryTANG0520/AutoHSR/issues) 报告问题时，请附上 Windows / Python / 游戏版本、客户区分辨率、系统缩放、复现步骤及经过脱敏的日志。截图与 OCR 文本可能包含 UID、昵称、好友信息，请检查后再公开。

欢迎提交 Pull Request。修改识别或流程时，请同步维护离线测试和相关文档，并运行 `python -m autohsr --self-test`；涉及 GUI 时还应运行 `python tools/gui_smoke.py`。新增上游素材请在 `assets/ATTRIBUTION.md` 记录来源、版本、修改方式与许可证。未实机验证的场景应明确标注。
