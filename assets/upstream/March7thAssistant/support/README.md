# 支援角色参考头像

来源：[moesnow/March7thAssistant](https://github.com/moesnow/March7thAssistant)，维护者moesnow及其贡献者；固定提交`7cf6c6bed474539485d3b1504077ac352866829f`，取回日期2026-10-30。

本目录包含上游`assets/images/share/character/`中的105幅PNG，字节保持原样；逐幅原路径、Git blob、SHA-256、尺寸及明确角色标识见[sources.json](sources.json)。名称来自同一提交的`assets/config/character_names.json`；无唯一中文名的两项保留英文标识，不猜测别名。没有训练模型，也没有新增或公开玩家画面。

参考代码为`tasks/power/character.py`和`tests/test_tasks/test_support_character.py`，具体源码哈希见[父清单](../source.json)。上游代码使用GNU GPL v3，保留[原许可](../LICENSE)；角色头像及相关游戏内容仍归HoYoverse等各自权利人所有。源码许可与署名不额外授予游戏美术的权利。

AutoHSR使用这些图像提供[支援偏好](../../../../docs/support-preferences.md)的局部候选证据。运行时按1920宽归一化并尝试0.90／0.95／1.00／1.05／1.10有限模板尺度，保留0.90匹配阈值；原图匹配未核实时尝试右上角26%遮罩，再尝试左侧星魂数字遮罩。遮罩只在内存中处理，原PNG与清单不改变。另与其他角色参考图比较至少0.025分差；完整好友卡片、当前画面、输入门禁和实际入队反馈仍须分别核实。

左侧遮罩及候选分差属于AutoHSR基于既有4.6列表回放补充的机制。合成尺度／遮挡检查和两份相邻旧列表校准不代表独立真实留出测试或偏好借用实机验收；相关记录保留本地忽略目录，公开素材清单不含UID、好友昵称或玩家配置。
