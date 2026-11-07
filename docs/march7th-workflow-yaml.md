# 三月七任务流 YAML 草稿转换

`autohsr.workflow_yaml.load_march7th_yaml(path)` 读取显式选择的一份 UTF-8 `.yaml` 或 `.yml`，返回未保存的 `WorkflowDraft`。原路径见 `draft.original_source`。上游作者、版本和描述保存在只读 `draft.metadata` 中，正式 JSON 仍使用 AutoHSR 的 `version: 1` 格式。步骤 ID 由原来的零起始树路径生成，便于定位和单步预览。

`draft.validate()` 使用正式编译器，`draft.save_as(path)` 排他写入已存在本地目录下的新 `.json` 并回读验证。`convert_march7th_yaml(source, destination)` 连续执行这两步。导入不运行任务，不加载配置，不读取或复制 YAML 引用的素材。源 YAML、旁边的模板以及已有输出保留原样。桌面从「打开任务流」选择 YAML，CLI 使用 `--task-workflow-convert-yaml` 和 `--workflow-json-destination`。[桌面和 CLI 用法](task-workflows.md)

| 上游步骤 | 转换条件 |
| --- | --- |
| `wait` | 秒数可为 0～3600 的有限数字，支持小数秒，缺省 1 秒 |
| `for` | 1～1000 次、非空 `children`，子步骤全部可转换。缺省 1 次 |
| `break`、`continue` | 在可转换的循环体中 |
| `stop_workflow` | 转为原生 `stop` |
| `switch_screen` | `main` 转为 `world`，`menu` 转为手机。`guide2`、`guide3`、`guide4`、`guide5` 分别转为每日实训、生存索引、逐光捡金、旷宇纷争。支持委托 `dispatch`、邮件 `mail`、奖励指南 `reward_guide`、新消息通知 `incoming_message`、成就 `achievement` 和兑换表单 `redemption`。`pass1`、`pass2` 分别转为 `battlepass_rewards`、`battlepass_tasks`。 `visa` 转为 `visa_collection` |
| `play_audio` | 显式填写普通相对路径或本地绝对路径，扩展名为 `.wav`。转为原生 `workflow_audio` |
| `send_message` | 调用方显式绑定一个原生方案名称。纯文本转为 `workflow_notify` |

识别固定提交的上游步骤字段。上游编辑器在节点里同时写入其他步骤类型的默认字段，转换只取当前动作实际使用的字段。非循环节点携带非空子步骤、任何未知字段或动作，都会拒绝整份转换。错误给出出问题的步骤路径。

普通相对音频路径（例如 `clips/beep.wav`）以原 YAML 所在目录为基准。本地绝对路径沿用指定位置。两者均以绝对引用写入草稿及另存文件，目标目录的同名 WAV 不会改变引用。以 `./` 或 `../` 开头的路径在三月七里取决于其进程工作目录，因此拒绝。省略路径、默认 MP3、其他扩展名、UNC、网络映射盘和设备路径也会拒绝。导入阶段只检查路径，文件是否存在和能否按 PCM WAV 播放由正式音频步骤核验。播放失败会记录在任务流报告中，后续步骤沿用上游行为继续。

上游的 `pass1` 与 `pass2` 分别指向勋礼奖励页和任务页。转换后使用对应的正式到页目标，从已核实的手机或勋礼页开始，在前台连续核对同账号和实际到页。导航待核对时挡住后续游戏输入。[固定上游页面定义](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json#L801-L837) · [勋礼到页边界](task-workflows.md#无名勋礼页签)

上游的 `main` 指大世界主界面，手机菜单经 Esc 返回该页。转换后的 `world` 只使用现有安全返回路径，每一步均核对实际落页。[固定上游主界面与手机定义](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json#L1-L45) · [大世界到页边界](task-workflows.md#返回大世界)

`guide4` 与 `guide5` 各核对明确页签，停在指南内。`incoming_message` 复用新消息通知双栏，须从带可见未读角标的大世界或已打开的通知双栏开始。[上游指南页签](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json#L407-L490) · [上游新消息通知](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json#L1122-L1135) · [明确指南页签](task-workflows.md#明确指南页签)

`achievement` 沿用从手机进入成就的路线，转换为明确的 `achievement_overview`。总览必须有分类卡与底部成就进度证据。仅有标题、分类页和奖励面板均保留待核对。[固定上游手机入口](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json#L181-L186) · [成就总览导航](task-workflows.md#成就总览导航)

`redemption` 转为 `redemption_form`，沿用手机「更多」的两段核对，止于兑换表单。[固定上游路线](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json#L97-L103) · [兑换码表单导航](task-workflows.md#兑换码表单导航)

上游的 `visa` 从手机「更多」打开漫游签证，页面定义未区分页签。转换后的 `visa_collection` 要求核实收集展示，从前台手机主菜单或已打开的收集展示开始。需要角色展示时，可另设原生 `visa_characters` 步骤。[固定上游手机路径](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json#L89-L95) · [固定上游签证定义](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json#L536-L547) · [收集展示导航](task-workflows.md#漫游签证收集展示)

| 待核对目标 | 补映射所需的最小证据 |
| --- | --- |
| 行动摘要 | 固定上游只列 `guide2` 至 `guide5`。先确认对应上游页面 ID，再核对 4.6.0 未选中入口与选中标题、独立正文标记，并用相邻指南页作反例 |
| `activity`、`configure_team` | 需区分通用活动与具体横幅、普通编队与玩法备战。各需安全入口、到页双帧和相邻误页 |
| 地图、相机、背包及玩法子页 | 需实际入口与到页标记，以及无消耗的独立动作回执。当前各玩法的正式命令有各自的停止条件 |

坐标、图文点击、滑动、按键、其余页面和无限循环均会拒绝。模板查找、文字查找及条件的默认转换会检查选区和上游语义差异，并给出节点路径。桌面「导入 YAML 图文…」可为受支持的步骤显式采用原生实时识别。上游官方示例索引只用于定位具体示例，不会触发目录扫描或自动选取。该接口接收单份 YAML。素材包格式与导入另有入口。[原生图文适配](march7th-workflow-native-vision.md) · [图文条件与迁移边界](march7th-workflow-conditions.md)

定义最多 1 MiB，YAML 解析最多 27 层和 16,416 个解析节点。拒绝锚点、别名、合并键、重复键、非文字键、自定义标签和多文档输入。文件需为普通本地文件，来源与目标父目录不经过重解析点。正式编译器仍独立限制 256 个任务步骤、12 层步骤和 10,000 次展开。

## 纯文本通知

桌面从「设置 → 工具 → 任务流」选择「导入 YAML 图文…」。选定 YAML 后，可为其中的纯文本通知明确选一个已有方案，默认不绑定。普通「打开任务流」保留严格导入。也可在 Python API 中传入 `notify_profile='my-profile'`，或使用转换专用 CLI 参数。方案名称写入通知步骤的 `params.profile`。桌面选择和 CLI 转换都只生成草稿或新 JSON。手动运行时由原入口核实方案及其版本，CLI 需要另外明确给出 `--workflow-allow-notify`。[原生任务流](task-workflows.md) · [通知方案](notifications.md)

```powershell
.\.venv\Scripts\python.exe -m autohsr --task-workflow-convert-yaml workflow.yaml --workflow-json-destination migrated.json --workflow-yaml-notify-profile my-profile
```

`text` 须为非空字符串，最多 1800 个字符。支持原样保留内部空格和换行。三月七发送前会裁去首尾空白，这类正文会拒绝转换。多行正文可用 `|-` 省去 YAML 默认追加的末尾换行。「7 次完成」等普通正文可直接写入。纯数字、日期及其他会被上游解析为非文本的标量，须用引号或文本块明确表示文字。`with_screenshot` 可省略或显式填布尔 `false`，截图及节点自带的方案、标题和渠道字段均不支持。[上游通知步骤](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/workflow/__init__.py#L1203-L1232) · [上游 YAML 版本](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/requirements.txt#L1)

上游 `with_screenshot: true` 在步骤执行时获取当前游戏画面。原生 JSON 可另行明确选择本地 PNG 和 SMTP 方案，并在命令行授权这次运行。[原生任务流](task-workflows.md)

迁移只保留正文的发送意图。三月七的全局标题、渠道、通知级别、合并发送及布尔成功结果没有逐节点等价项。原生使用选定方案、固定任务流标题和独立提交回执。通知失败后可继续流程，提交待核对时会阻止后续主动通知。原生每次运行最多 20 个通知步骤的限制仍适用。[上游全局通知器](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/notification/notification.py#L271-L318)

## 固定上游核对

编解码、步骤默认值、运行逻辑和教程固定在 `7cf6c6bed474539485d3b1504077ac352866829f`。未引入上游代码或素材。 [上游编解码和执行](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/workflow/__init__.py) · [流程教程](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/docs/Workflow.md)

| 上游文件 | SHA-256 | 核对结果 |
| --- | --- | --- |
| [官方示例索引](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/workflows/official_workflows.yaml) | `76396e7ce2cdfd2c9332499ae58952339a4ee1d1eade09560dd9e2b008b820d9` | 识别为索引 |
| [自动升级示例](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/workflows/sample_auto_upgrade/workflow.yaml) | `40a71ff6d1fa9e2d93060092a44f4e080dd59439d13e16ec50e180a552d9523c` | 步骤 0 的文字点击阻止转换 |
| [银河信号漫游示例](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/workflows/cosmic_data_roaming/workflow.yaml) | `a3c78c29758073993c3c61a59634b5563069a12298dadda6b7d96ea31c1f0f6c` | 步骤 0 的无限循环阻止转换 |
| [银河信号漫游模板](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/workflows/cosmic_data_roaming/templates/receive.png) | `9636dfa91dd6a5a10d253c07bffb56af0c2f7af569b5fa4733e6326fefd3c40a` | 源 YAML 的模板点击位于 0/4，导入不读取模板 |

YAML 专项和原生任务流、草稿及音频相关回归共 90 项通过。跨目录另存测试同时放置同名 WAV，核对正式任务仍解析到原位置。转换期间禁止查询 WAV 元数据、打开文件或调用播放。另用上表三个原始 YAML 文件核对索引和拒绝原因，确认未生成输出，原文件及模板的哈希一致。
