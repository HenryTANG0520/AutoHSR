# March7thAssistant 参考来源与适配

来源：[moesnow/March7thAssistant](https://github.com/moesnow/March7thAssistant)，维护者moesnow及其贡献者。核对日期2026-10-28，固定提交`7cf6c6bed474539485d3b1504077ac352866829f`。

上游使用GNU GPL v3；保留的原许可见[LICENSE](LICENSE)，具体源文件的Git blob及许可文件SHA-256见[source.json](source.json)。AutoHSR本身也使用GPL v3。游戏角色名及相关游戏内容仍归各自权利人所有。

本轮将上游`tasks/weekly/currency_wars.py`中的核心角色优先、取得核心后切换成长阶段、按完整一级经验判断余额、购买后更新角色信息等思路，改写为本项目的`currency_wars_standard_policy.py`与`currency_wars_standard_trading.py`。阿格莱雅／希儿的角色偏好和成长阶段来自这份固定源码；实际售价、星级、费用、位置适配、余额、经验及阵容来自AutoHSR当前画面和本局记录。

没有复制上游固定角色费用表或输入实现。输入继续经过本项目Context、UID核验、落盘意图和逐次反馈；上游连续按键购买被适配为每次购买后重新观察。原始上游执行框架、GUI、模型和图片未在本轮迁入。本目录只保存许可及来源清单，不包含账户配置或上游安装目录数据。

这些策略目前是购买、成长和已有角色补空位的工程基线。上游完整阵容替换、装备、刷新及所有节点尚未全部复现，离线测试不代表实机胜率或整局通过。实现与验证见[开发记录](../../../docs/currency-wars-development.md)。
