# 普通队伍页局部图

原图来自 moesnow 及其贡献者维护的 March7thAssistant 固定提交 `7cf6c6bed474539485d3b1504077ac352866829f`，保留原始 PNG 字节。游戏美术归 HoYoverse 及相应权利人。[原图路径、哈希和用途](sources.json) · [上游 GPL v3 许可](../LICENSE)

`configure_team.png` 为 36×39 的金色三人剪影，带深蓝星空背景。上游把它登记为「队伍」页识别图，入口来自手机菜单。同样的队伍标志也出现在其它编队页，须配合独立字段判断。上游未声明此金图的单独搜索区。[上游页面配置](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json#L993)

固定上游 `Team.change_to` 在 1920×1080 参考尺寸的 `[311, 15, 1687, 115)` 区域读取顶部两位队伍编号。在右下 `[1507, 955, 1843, 1013)` 核对「已启用」或「启用队伍」。编号位置与启用状态各自提供证据。固定上游未给出手机派生预设列表或预设成员的可见锚。[上游队伍切换](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/base/team.py#L18-L44)
