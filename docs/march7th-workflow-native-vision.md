# 三月七 YAML 的原生图文适配

默认导入仍拒绝三月七图文查找和条件。调用方明确选择 AutoHSR 的双帧识别后，可传入 `use_native_vision=True`。该选项只由调用方传入，YAML 内的字段无法启用它。

桌面使用「设置 → 工具 → 任务流 → 导入 YAML 图文…」。普通「打开任务流」保持严格模式。转换完成后可检查草稿，另存为 JSON 并校验，再单独启动。

独立 CLI 使用 `--workflow-yaml-native-vision`，须同时选择 `--task-workflow-convert-yaml` 并指定新的 JSON 输出。省略开关时沿用严格转换。开关与执行、校验、ZIP 素材包及其他命令的组合会在接触目标文件前拒绝。

```powershell
.\.venv\Scripts\python.exe -m autohsr --task-workflow-convert-yaml workflow.yaml --workflow-json-destination migrated.json --workflow-yaml-native-vision
```

```python
from autohsr.workflow_yaml import convert_march7th_yaml, load_march7th_yaml

draft = load_march7th_yaml("workflow.yaml", use_native_vision=True)
saved = convert_march7th_yaml("workflow.yaml", "new-workflow.json", use_native_vision=True)
```

支持单目标、单次检测的 `find_image` 和 `find_text`。图文 `if` 和有界 `while` 会转换为 `screen_condition`，保留条件正否、选区、子步骤顺序及循环上限。省略上限沿用上游默认 20，支持 1～1000。原生 `while` 在每轮前重新取样，次数耗尽后也会复测一次。上限复测仍满足条件时，以部分完成结束。

图片阈值只支持 0.50～1，省略时沿用上游默认数值 0.90。转换后该数值用于 AutoHSR 原生模板算法。上游的透明掩码和匹配算法可能给出不同结果。文字查找保留 `include` 对应的 `contains`。上游 YAML 的 `threshold` 字段不参与文字检测，转换后的文字步骤使用 AutoHSR 的 OCR 默认阈值 0.65 和文字规范化规则。检测失败或双帧冲突为未知，流程停止。

PNG、JPG 或 JPEG 的普通相对路径绑定到原 YAML 所在目录，本地绝对路径沿用原位置。另存时保留绝对引用。转换不检查模板内容或文件是否存在，正式运行仍核验模板。依赖三月七进程工作目录的 `./`、`../` 路径，以及 UNC、网络映射盘、设备路径均拒绝。多目标、重试、无限循环、`last_result` 和未知步骤也会拒绝整份转换。 [固定上游执行与路径规则](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/workflow/__init__.py)

## 转换示例

```yaml
name: 等待提示出现
steps:
- type: while
  condition_type: text_not_exists
  text: 继续
  include: true
  crop: (1 / 8, 0, 1 / 2, 1 / 2)
  max_retries: 1
  max_iterations: 3
  children:
  - type: wait
    seconds: 1
```

```json
{
  "version": 1,
  "name": "等待提示出现",
  "steps": [
    {
      "id": "m7-0",
      "type": "while",
      "screen_condition": {
        "task": "workflow_game_text",
        "params": {"text": "继续", "contains": true, "region": [0.125, 0, 0.625, 0.5]},
        "value": false
      },
      "max_iterations": 3,
      "steps": [{"id": "m7-0-0", "type": "wait", "seconds": 1}]
    }
  ]
}
```
