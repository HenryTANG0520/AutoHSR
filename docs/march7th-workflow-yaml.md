# 三月七任务流 YAML 草稿转换

`autohsr.workflow_yaml.load_march7th_yaml(path)` 读取显式选择的一份 UTF-8 `.yaml` 或 `.yml`，返回未保存的 `WorkflowDraft`。原路径见 `draft.original_source`。上游作者、版本和描述保存在只读 `draft.metadata` 中，正式 JSON 仍使用 AutoHSR 的 `version: 1` 格式。步骤 ID 由原来的零起始树路径生成，便于定位和单步预览。

`draft.validate()` 使用正式编译器，`draft.save_as(path)` 排他写入已存在本地目录下的新 `.json` 并回读验证。`convert_march7th_yaml(source, destination)` 连续执行这两步。导入不运行任务，不加载配置，不读取或复制 YAML 引用的素材。源 YAML、旁边的模板以及已有输出保留原样。桌面从「打开任务流」选择 YAML，CLI 使用 `--task-workflow-convert-yaml` 和 `--workflow-json-destination`。[桌面和 CLI 用法](task-workflows.md)

| 上游步骤 | 转换条件 |
| --- | --- |
| `wait` | 秒数能无损表示为 0～3600 的整数，缺省 1 秒 |
| `for` | 1～1000 次、非空 `children`，子步骤全部可转换。缺省 1 次 |
| `break`、`continue` | 在可转换的循环体中 |
| `stop_workflow` | 转为原生 `stop` |
| `switch_screen` | `menu`、`guide2`、`guide3`、`dispatch`、`mail`、`reward_guide` 转为对应的手机、每日实训、生存索引、委托、邮件和奖励指南 |
| `play_audio` | 显式填写普通相对路径或本地绝对路径，扩展名为 `.wav`。转为原生 `workflow_audio` |

识别固定提交的上游步骤字段。上游编辑器在节点里同时写入其他步骤类型的默认字段，转换只取当前动作实际使用的字段。非循环节点携带非空子步骤、任何未知字段或动作，都会拒绝整份转换。错误给出出问题的步骤路径。

普通相对音频路径（例如 `clips/beep.wav`）以原 YAML 所在目录为基准。本地绝对路径沿用指定位置。两者均以绝对引用写入草稿及另存文件，目标目录的同名 WAV 不会改变引用。以 `./` 或 `../` 开头的路径在三月七里取决于其进程工作目录，因此拒绝。省略路径、默认 MP3、其他扩展名、UNC、网络映射盘和设备路径也会拒绝。导入阶段只检查路径，文件是否存在和能否按 PCM WAV 播放由正式音频步骤核验。播放失败会记录在任务流报告中，后续步骤沿用上游行为继续。

上游的 `pass1` 与 `pass2` 精确指向勋礼的奖励及任务页，当前泛勋礼目标不会替代它们。已映射的切换运行时沿用 AutoHSR 前台、同账号与到页门禁，未核实的导航会挡住后续游戏输入。[固定上游页面定义](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json)

坐标、图文点击、滑动、按键、其余页面和无限循环均会拒绝。模板查找、文字查找及条件的默认转换会检查选区和上游语义差异，并给出节点路径。桌面「导入 YAML 图文…」可为受支持的步骤显式采用原生实时识别。上游通知仍缺少明确的方案绑定。上游官方示例索引只用于定位具体示例，不会触发目录扫描或自动选取。该接口接收单份 YAML。素材包格式与导入另有入口。[原生图文适配](march7th-workflow-native-vision.md) · [图文条件与迁移边界](march7th-workflow-conditions.md)

定义最多 1 MiB，YAML 解析最多 27 层和 16,416 个解析节点。拒绝锚点、别名、合并键、重复键、非文字键、自定义标签和多文档输入。文件需为普通本地文件，来源与目标父目录不经过重解析点。正式编译器仍独立限制 256 个任务步骤、12 层步骤和 10,000 次展开。

## 固定上游核对

编解码、步骤默认值、运行逻辑和教程固定在 `7cf6c6bed474539485d3b1504077ac352866829f`。未引入上游代码或素材。 [上游编解码和执行](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/workflow/__init__.py) · [流程教程](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/docs/Workflow.md)

| 上游文件 | SHA-256 | 核对结果 |
| --- | --- | --- |
| [官方示例索引](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/workflows/official_workflows.yaml) | `76396e7ce2cdfd2c9332499ae58952339a4ee1d1eade09560dd9e2b008b820d9` | 识别为索引 |
| [自动升级示例](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/workflows/sample_auto_upgrade/workflow.yaml) | `40a71ff6d1fa9e2d93060092a44f4e080dd59439d13e16ec50e180a552d9523c` | 步骤 0 的文字点击阻止转换 |
| [银河信号漫游示例](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/workflows/cosmic_data_roaming/workflow.yaml) | `a3c78c29758073993c3c61a59634b5563069a12298dadda6b7d96ea31c1f0f6c` | 步骤 0 的无限循环阻止转换 |
| [银河信号漫游模板](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/workflows/cosmic_data_roaming/templates/receive.png) | `9636dfa91dd6a5a10d253c07bffb56af0c2f7af569b5fa4733e6326fefd3c40a` | 源 YAML 的模板点击位于 0/4，导入不读取模板 |

YAML 专项和原生任务流、草稿及音频相关回归共 90 项通过。跨目录另存测试同时放置同名 WAV，核对正式任务仍解析到原位置。转换期间禁止查询 WAV 元数据、打开文件或调用播放。另用上表三个原始 YAML 文件核对索引和拒绝原因，确认未生成输出，原文件及模板的哈希一致。
