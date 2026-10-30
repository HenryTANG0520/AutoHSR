# 跃迁记录窗口统计与Excel导出

更新日期：2026-10-30。新增独立分析入口和Excel阅读表，保留已有UIGF／SRGF交换、读取范围、原件保留及取消语义。GUI工具箱、图形呈现与真实账号路径仍待接入和验证；本轮只使用虚构资料，不控制游戏。

## 统计的是记录窗口

参考固定三月七启动器`7cf6c6bed474539485d3b1504077ac352866829f`的[`WarpExport.data_to_html`](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/app/tools/warp_export.py#L161-L214)，提供分池星级占比、已观察五星历史、尾段记录数与区间均值。改写为[原生统计](../autohsr/warp_statistics.py)，不把文件窗口当作账号完整历史，不把记录数与物品`count`混为一谈。

- 按账号及六类卡池分别计算，沿用已核实格式中的数字ID顺序。其他卡池的五星不会重置本池，同一账号的重复ID仍由原合并协议去重。
- 四／五星等占比以本池全部记录为分母，缺失星级单列为unknown；空列表占比为null。物品数量只有每条都明确含`count`时才给合计，缺失时为null，不默认补1。
- 首次观察到的五星之前是窗口前缀，不将其纳入“五星间平均记录数”。两个已观察五星之间若出现缺失星级，该段也不参与均值，因为中间可能还有五星。均值始终只描述可用记录段，记录遗漏和窗口外数据仍未证明完整，不能当成实际保底或真实平均出货抽数。
- `observed_tail_records`保留最近已观察五星之后、或无五星时整个前缀的记录数；`known_tail_records`只在已观察五星且之后星级均已知时给数值，其他情况为null。末条为已知五星时窗口尾段为0，不表示当前游戏账号此刻保底为0。
- 时间字段保持账号时区的原字符串。数值ID顺序下发现时间逆行会保留`time_order_consistent=false`，不擅自重排或改写原记录；时间范围与是否存在逆序分开。

例如同池星级为`3,5,4,3,5,未知,5,3,5,3`：首个五星前缀不计入均值，缺失星级后的下一段也不计入；剩下两段记录数为3和2，均值2.5，已知尾段为1。若第一条`count=3`、其余均为1，物品数量合计是12，记录数仍为10。这些都是虚构记录窗口的计算结果。

## CLI和保存

以下仅为入口说明，没有在本轮读取真实玩家资料：

```powershell
# 只输出匿名窗口统计，不生成文件，也不加载游戏设置
.\.venv\Scripts\python.exe -m autohsr --warp-analysis --warp-import .\runs\warp\combined.json
# Excel阅读表，全部账号分别成表；原JSON保留
.\.venv\Scripts\python.exe -m autohsr --warp-records --warp-import .\runs\warp\combined.json --warp-format xlsx --warp-output .\runs\warp\records.xlsx
# 只导出明确选择的账号；虚构UID示例
.\.venv\Scripts\python.exe -m autohsr --warp-records --warp-import .\runs\warp\combined.json --warp-uid 100000000 --warp-format xlsx --warp-output .\runs\warp\selected.xlsx
```

只分析可以使用同一套明确链接／缓存读取来源及卡池、页数范围；只分析不接受`--warp-output`或`--warp-format`，不落盘导出。`--warp-analysis`和`--warp-records`互斥，均在游戏配置、GUI和Runner之前分派。它们不会启动、检测或控制游戏，不新增定时任务。

Excel使用`.xlsx`新文件，拒绝覆盖。缺少或版本不符的Excel依赖会在读取来源及请求接口前停止，提示运行项目setup；JSON交换和只分析仍不加载Excel引擎。文件按原[导入／获取协议](warp-records.md)完成校验、合并及明确账号选择后发布。

## 工作簿内容

参考上游[`__onExportExcelBtnClicked`](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/app/warp_interface.py#L221-L323)的表格字段及四／五星着色，新增[原生Excel序列化](../autohsr/warp_xlsx.py)：

| 工作表 | 内容 |
| --- | --- |
| 分池统计 | 每账号六类卡池的记录数、星级计数与占比、观察尾段、可用区间数及均值、时间范围与逆序提示 |
| `记录-<UID>` | 原时间、名称、类别、星级、卡池、物品数量、账号／本池窗口序号、已知五星后记录数及计数范围，另保留记录／物品／卡池ID |

每账号单独成表，含空记录账号，不默取第一UID。分池页冻结账号／卡池列和表头，记录页冻结表头；两页均有筛选、列宽、范围说明和重复打印表头。四星为紫色、五星为金色。未知星级、物品数量及无法确定的间隔保持空单元格，时间无数据时不展示“已核实顺序”。

UID、记录ID等保持文本，避免Excel数字精度截断；显示名称等也以原文文本写入，不执行公式。Excel是阅读视图，不是可重新导入的交换档案：任意JSON扩展字段仍保留在输入及JSON交换文件中，表格仅展示列出的字段。文字包含XML无法表示的控制字符时拒绝Excel导出，原JSON不修改。

使用固定`openpyxl==3.1.5`及`et_xmlfile==2.0.0`流式写入，依赖在明确Excel操作时加载；版本加入[requirements](../requirements.txt)。临时工作簿完成、flush／fsync、哈希及取消检查后才原子发布新目标，JSON仍保留32 MiB上限，Excel为128 MiB。流式工作表的自有XML临时文件在完成、停止和错误时释放，不能因取消留下半份导出。共享发布逻辑在[服务](../autohsr/warp_service.py)中复用。

新包的PyPI来源、wheel及许可原件SHA-256见[依赖清单](../assets/upstream/openpyxl-source.json)。openpyxl与et_xmlfile的MIT许可、包内Python许可文本均原样保存，相关文件固定字节以避免换行转换；来源与适配范围见[总署名](../assets/ATTRIBUTION.md)。本轮没有构建EXE，旧包不因源码更新自动取得本功能。

## 界面对接

`warp_statistics.analyze(accounts, history=True, cancel=None)`为本地完整分析，返回每账号的UID、时区、语言及六池统计；`five_star_history`含已读名字、时间、记录ID、观察跨度、可用区间和窗口前缀／未知标记。它只供本地界面使用，不发给模型或日志。`positions(rows)`为已经格式核验且按数字ID排序的记录提供逐行注释。

`public_statistics()`通过白名单生成匿名快照，只保留账号序号、计数、占比、区间与时序布尔值，不带UID、姓名、记录ID、具体时间、路径或鉴权。GUI需将姓名当作普通文字显示，不能将其拼成可执行HTML。

原`warp_service.run`增加`analysis_only=False`与可选`output=None`。只分析必须不提供输出和导出格式，完成事件为`warp_analysis_finished`；导出完成事件仍为`warp_finished`且只在文件发布后发出。两者的公共结果均增加匿名`statistics`，原`accounts`数量、`records`及`pools`字段保留。格式新增`xlsx`，原UIGF／SRGF数据结构不变。只分析返回的`mode='analysis'`不得显示“文件已保存”，Excel也不能标为UIGF交换文件。

`scope='imported_record_window'`、`history_complete=false`在所有统计结果中保留。界面显示“记录窗口统计”“未知”“首段不完整”等对应状态，不将其改成实时账号保底、概率预测或完整历史完成。

## 验证边界

[14项专项](../autohsr/tests/test_warp_statistics_xlsx.py)通过`runs/warp-xlsx-final-scope.log`（0.226秒），覆盖首段／未知、空记录、两账号六池、数字排序与时间逆序、记录数／物品数量区分、匿名事件快照、Excel真实服务和CLI、源文字、ID精度、颜色／冻结／筛选、错误／中途取消／写盘失败的原件及临时文件保留契约。除openpyxl重新读取外，另直接核对OOXML类型、无公式节点及无外部链接／宏关系。

原22项记录回归通过`runs/warp-xlsx-legacy.log`（0.095秒）；新增13项阶段专项先通过`runs/warp-xlsx-first.log`，补依赖预检后53项记录／统计／CLI／原计划相关通过`runs/warp-xlsx-related-final.log`（0.415秒）。之后补同一专项的依赖版本和空时间显示反例，最终14项重新核实。检查均为虚构记录，不证明真实Excel桌面视觉、GUI图表、实际客户端缓存或完整历史已验收；旧货币战争独立0/10与资源记录不变。

最终代码1693项全量通过`runs/warp-xlsx-all.log`（795.453秒），84项原GUI假后端通过`runs/warp-xlsx-gui.log`。原JSON数据继续通过180组独立Schema及2项反例，`runs/warp-xlsx-json-schema.json`；固定两份上游源码／函数、原GPL许可、新依赖版本及三份原许可、5份说明158条本地链接和CLI帮助通过`runs/warp-xlsx-source-verification.json`，`git diff --check`通过。

另以20000条六池虚构记录执行真实服务的Excel发布及只分析CLI，再用流式读取核对20000行、21292物品数量、全部长ID文本及首末ID、源文件不变、导出哈希和临时文件释放，全部通过`runs/warp-xlsx-load-verification.json`。本机该次导出10.109秒、文件1134240字节；这是本地样例结果，不外推最大容量或其他设备耗时。检查脚本、输入／导出、独立验证器和日志均保持忽略，没有新游戏采集、资源消耗或EXE构建。
