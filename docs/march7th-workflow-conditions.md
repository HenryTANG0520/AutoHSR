# 三月七图文检测与条件的迁移边界

核对固定上游 `7cf6c6bed474539485d3b1504077ac352866829f`，并对照 AutoHSR 的原生实时图文实现 `c60bcdd`。转换器为选区及条件提供节点级诊断。遇到仍无等价契约的图文或控制节点时，整份转换失败，YAML 和模板保留原样。

## 选区

`parse_march7th_crop(value)` 将上游 `[x, y, width, height]` 转为原生 `[left, top, right, bottom]`。缺省、空字符串和空序列表示整幅画面。支持四项十进制数及上游截图工具生成的单项分式。表达式可以有一对外层圆括号。数组元素只接受数字或十进制字符串。解析先以有理数核对相加后的边界及面积，再转换成原生 JSON 数值。除零、非有限数、空项、越界、过长、任意运算符和代码表达式均会拒绝。

该转换保留归一化几何。上游截图分别截断位置和宽高，原生将终点各自四舍五入。例如宽 100、起点 0.125、宽度 0.25 时，上游右边界是 37，原生右边界是 38。上游还可能在裁剪后缩放到 1920×1080 基准。成功解析选区无法证明两种识别得到同一个像素区域。 [固定上游选区及截图实现](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/automation/screenshot.py)

## 检测与条件

| 上游行为 | 原生可表达范围 |
| --- | --- |
| `find_image` 默认一次检测，`max_retries` 大于 1 时可间隔重取并在任一次命中后返回。透明掩码用平方差上界，普通图用相关性下界 | `workflow_game_image` 要求同窗口、同账号、同一代次的新鲜双帧一致。原生模板还要求可区分细节及像素差检查。上游阈值直接抄入会改变语义，诊断过程也不读取模板来猜测类型 |
| `find_text` 对 OCR 输出做字面精确或包含匹配，可用分号列出多个候选。YAML 的图像阈值字段不参与文字匹配 | `workflow_game_text` 只接收一个目标，应用文本规范化、OCR 分数与框检查。候选组合、分数和文本处理有差异 |
| `if` 的图文条件在进入时检测。否定条件可把上游缺少模板、匹配错误或 OCR 错误产生的失败值反转 | 原生 `screen_condition` 在进入时重采。双帧冲突、遮挡、识别异常或缺少原回执时没有布尔事实，条件停止。`false` 表示两帧按所选规则均未匹配 |
| `last_result` 初值为 `False`，每个执行步骤都会更新。等待、控制节点返回以及被捕获的异常也会改变它 | `@last` 指最近一次实际执行的原生任务。原生 `status=success` 表示观察已验证，可以同时带 `found=false`。将上游上一动作布尔值映射到这两个字段中的任意一个会丢失信息。只有明确绑定同一次执行的具体事实才可比较 |
| `while` 每轮在进入循环体前重新检测或读取当时的 `last_result`。上限为 0 表示无限。达到正上限时直接离开，未额外观察 | 原生 `screen_condition` 每轮前及耗尽上限后重新观察。普通 `condition` 仍比较步骤事实。两者均受静态执行上限约束 |

[固定上游流程执行](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/workflow/__init__.py) · [元素检测与重试](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/module/automation/automation.py) · [模板算法](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/utils/image_utils.py)

## 原生实时条件

AutoHSR 已为 `if` 和有界 `while` 接入与 `condition` 互斥的 `screen_condition`。它调用现有只读图文入口，保存本次同账号、同输入代次的原始回执。未知立即停止，两个分支都不进入。[原生配置与操作](task-workflows.md#实时画面条件)

上游 YAML 的默认转换仍按原始语义检查。坐标算式诊断不会执行表达式，也不会读取模板。出现匹配算法、重试、否定结果或循环上限差异时，默认转换指出步骤位置并保留原件。

显式采用原生规则时，可转换单次单目标查找和有界图文条件。它们使用 AutoHSR 的匹配与停止规则。[选择方式与支持范围](march7th-workflow-native-vision.md)

95 项相关回归通过，覆盖归一化边界、无效算式、条件和重试诊断，以及转换期间不访问模板和不发布部分流程。
