# 差分站点偏好参考

参考仓库：[March7thAssistant](https://github.com/moesnow/March7thAssistant)，固定提交`7cf6c6bed474539485d3b1504077ac352866829f`。

- [process_next_station](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/divergent_universe.py)：启用开关、名称到优先级的映射、禁用项，以及首领／休整／转化前置。
- [默认配置](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/config.example.yaml)：九类可选站点的默认自定义映射。
- 原GPL v3许可保留于[LICENSE](../LICENSE)。两个原源码的Git blob与许可哈希见[source.json](source.json)。

本次按行为适配为[原生冻结偏好](../../../../autohsr/du_station_policy.py)，接入已有差分流程及输入门禁；没有复制上游坐标、重抽循环或重抽耗尽后选择禁用项的兜底。AutoHSR默认关闭自定义，沿用既有已验收选择顺序；开启后的默认自定义映射参考上游，缺项按100排序，数值相同按当前卡片从左到右选择。必经站点固定前置且不可禁用；全部已识别候选被禁用时停留待核对，有界重抽另待适配。

已有战斗图标识别仍需独立模板及页面门禁。自定义时，低优先级图标不能覆盖更优文本，不能回选禁用战斗，也不能与同一卡列的已读非战斗名称冲突。危险信标检查及替代站点共同遵守冻结偏好。14类名称是可识别候选标签，不代表每种后续区域均完成实机验收。

本轮没有新增或复制图片、模型。正向流程采用模拟卡片与已有脱敏回放，真实通关计数保持10次独立周期和28次分段／接续；不新增实机验收。用法及边界见[差分说明](../../../../docs/differential-universe.md)和[逐局记录](../../../../docs/du-validation.md)。
