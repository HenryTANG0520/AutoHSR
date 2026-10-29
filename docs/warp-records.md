# 跃迁记录读取、合并与导出

更新日期：2026-10-30。当前为独立工具后端与CLI，沿用AutoHSR“本次操作不保存游戏设置、分项报告真实结果”的语义。没有修改现有GUI；工具箱入口、统计展示和真实账号路径仍待界面接入与验证。本功能读取已有记录，不执行跃迁，不启动或控制游戏。

## 格式与合并

参考固定三月七启动器提交`7cf6c6bed474539485d3b1504077ac352866829f`的[记录读取及转换](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/app/tools/warp_export.py)与[导入导出界面](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/app/warp_interface.py)，适配为[记录协议](../autohsr/warp_records.py)、[只读获取](../autohsr/warp_fetch.py)、[独立服务](../autohsr/warp_service.py)和[CLI桥接](../autohsr/warp_cli.py)。没有迁入Qt界面、遥测、自动扫描用户目录或覆盖式修复。

格式依据为[UIGF组织](https://uigf.org/)的[UIGF v4.2规范](https://uigf.org/zh/standards/uigf.html)及[SRGF v1.0规范](https://uigf.org/zh/standards/srgf.html)。本项目没有取得格式认证，也不声明支持其他游戏。

| 格式 | 读取 | 导出与边界 |
| --- | --- | --- |
| UIGF v4.0 | 星铁`hkrpg`分组，四类旧卡池 | 统一导出v4.2；v4.0中出现21／22拒绝错误版本声明 |
| UIGF v4.1、v4.2 | 星铁分组，六类卡池、多账号 | 导出v4.2，账号、时区、可选语言和记录分开保留 |
| SRGF v1.0 | 单账号、四类旧卡池 | 单账号导出；多账号须明确选择UID，不能默取第一账号 |
| 上游扩展SRGF | 保留其中21／22，附`legacy_srgf_extended_pools`提示 | 应导出UIGF；旧SRGF导出拒绝联动池，不静默删记录 |

卡池1／2／11／12／21／22分别独立读取。记录ID始终为字符串，排序按大整数比较，不经过浮点，也不按字典序排列。相同账号和ID去重，缺失的可选字段可补齐；同ID的实际内容冲突则停止整次操作。记录级JSON扩展字段保留，不改写输入原件。

同账号跨时区导入会转换到第一份资料的时区，保持同一时刻；不会按本机时区猜测。SRGF的整数值浮点时区可无损转成整数；非整小时时区拒绝转换。语言缺失保持未知，星级、数量及显示名称不填造；同账号语言不一致时明确拒绝混合，原件可分别导出。其他游戏分组不导入，并记录`other_games_not_imported`提示；输出只含星铁，不能将其视为原多游戏档案的备份。

## CLI用法

以下仅为入口说明，本轮没有读取实际账号或调用其记录接口。推荐将私有记录放在已忽略的`runs/warp/`中。

```powershell
# 合并两份既有文件，导出新的UIGF；输入文件保留
.\.venv\Scripts\python.exe -m autohsr --warp-records --warp-import .\runs\warp\old.srgf.json --warp-import .\runs\warp\recent.json --warp-output .\runs\warp\combined.json
# 单账号导出旧SRGF；出现联动池会拒绝，改用UIGF可保留全部记录
.\.venv\Scripts\python.exe -m autohsr --warp-records --warp-import .\runs\warp\old.srgf.json --warp-format srgf --warp-output .\runs\warp\legacy-export.json
# 多账号文件明确选择一个UID；这里是虚构示例UID
.\.venv\Scripts\python.exe -m autohsr --warp-records --warp-import .\runs\warp\combined.json --warp-uid 100000000 --warp-output .\runs\warp\selected.json
# 读取用户明确指定的StarRail_Data目录，再导出接口当前可读取的记录
.\.venv\Scripts\python.exe -m autohsr --warp-records --warp-cache-dir 'D:\Game\StarRail_Data' --warp-output .\runs\warp\fetched.json
# 或使用本地UTF-8链接文件；不要将鉴权链接作为普通日志输出
.\.venv\Scripts\python.exe -m autohsr --warp-records --warp-url-file .\runs\warp\private-link.txt --warp-output .\runs\warp\fetched-from-link.json
```

`--warp-import`可以重复指定，并可与一种获取来源合并；`--warp-url-file`与`--warp-cache-dir`不能同时使用。`--warp-format`默认为`uigf`。`--warp-pools 11,12`只请求选定卡池，结果中保留本次范围；不选择时读取全部六类。`--warp-max-pages`为每池1～5000页，默认1000页。卡池与页数参数只用于获取来源，不用于纯文件转换。

此工具在加载游戏配置、GUI或Runner之前分派，不能混用游戏任务、管理员或配置参数。错误不会回退为启动GUI。CLI成功为0、失败为2，用户中断为130。完成指本次文件操作和请求范围核实结束，不证明账号终身历史完整。

## 读取与停止

缓存扫描仅位于明确目录的`webCaches/*/Cache/Cache_Data/data_2`，按修改时间及文件中最后的有效候选选择，不删除或修改缓存。库另提供`paths_from_player_log(path)`解析用户明确选择的日志路径；它不自动遍历本机用户目录，也不读取进程内存。缓存或链接过期时，由用户手动打开游戏的跃迁记录后再发起工具操作。

链接须有明确的星铁业务、语言、网页鉴权和官方域名。请求始终发往写死的国服／国际服记录域名；联动池使用独立接口，旧页码、条数及游标清除后重新读取。HTTP重定向关闭，3xx／4xx停止；网络或5xx最多三次，每次超时15秒。原始URL、鉴权及服务器原始错误文字不写入配置、事件、日志或导出文件，链接对象的repr也脱敏。

每页核对结构、账号、语言、时区、卡池及严格递减的数字ID。短页不等于末页，须取得空列表；重复、逆行游标、账号变化、错误响应、页数耗尽均不能报告为完整获取。所有池为空且没有账号来源时不猜UID。请求和原件合并完成前不发布导出文件，失败后可重新进行只读获取，不覆盖旧数据。

`cancel`回调在每次请求、重试等待、导入和发布前检查；停止时取消后续请求，清理本次尚未发布的临时文件。当前阻塞HTTP请求受15秒超时约束。本工具不登记全局游戏热键，不与玩法Runner争夺输入；GUI应使用其工具工作线程与取消事件。

## 文件与界面对接

`warp_service.run(imports=(), url_file=None, cache_dir=None, output=..., format='uigf', selected_uid=None, pools=..., max_pages=1000, cancel=None, emit=None)`是界面入口。完成后只创建用户指定的新JSON；既有目标拒绝覆盖。先写临时文件、flush／fsync，检查取消，再原子发布；Windows使用不替换既有目标的重命名，其他平台使用同目录排他硬链接。写盘或发布失败不改输入原件。

完成摘要含`status`、输出格式、账号数、记录数、各卡池的总记录／四星记录／五星记录／未知星级记录数、来源格式提示、获取范围与输出哈希；不把记录数当作物品`count`总和。`history_complete=false`始终保留，不能将观察窗口统计称为完整保底或终身抽数。标准导出文件按格式含UID；公共摘要和事件不带UID、角色名称、鉴权或本地输入路径。没有将记录传给决策模型。

事件分别为`warp_import_progress`（已读文件数与匿名摘要）、`warp_fetch_progress`（当前卡池、页码、已读数量）和`warp_finished`（完成摘要）。只有导出发布成功才发finished。界面应显示本次来源和卡池范围、冲突原因及新文件目标；多账号SRGF使用明确选择，不沿用上游取第一账号行为。

运行不新增第三方依赖。JSON输入／输出最多32 MiB、每账号最多500000条、一次最多1000文件；缓存总读取最多64 MiB、最多100个缓存文件及每文件10000个URL候选。GUI、Excel表格导出、图形统计、覆盖式纠错、更多语言兼容和真实客户端缓存／账号接口仍待完成。

## 来源和验证

上游两个源码与原测试文件的Git blob及SHA-256、GPL v3许可、具体适配范围见[来源清单](../assets/upstream/March7thAssistant/source.json)和[署名](../assets/ATTRIBUTION.md)。未新增游戏图片、模型或玩家资料。

- [22项专项](../autohsr/tests/test_warp_records.py)通过`runs/warp-records-final-scope.log`（0.104秒），覆盖往返、六池／多账号、超过JS安全整数的ID、时区、不完整字段、冲突、分页、重定向、缓存、真实服务组合、取消和原件保留。后续再补同一链接含多行的反例，单项通过`runs/warp-link-final.log`。
- 75项CLI、原计划、多副本正式入口和货币战争失败相关回归通过`runs/warp-records-related-final.log`（15.205秒）。首轮命令误写不存在的`test_config`，该命令日志`runs/warp-records-related.log`保留；实际配置入口检查使用既有`test_cli_contract`。
- 最终应用代码1679项全量通过`runs/warp-records-all.log`（778.884秒），84项原GUI假后端检查通过`runs/warp-records-gui.log`。真实CLI入口以虚构六池JSON导入／发布成功，日志为`runs/warp-records-cli.log`；没有访问实际缓存或账号接口。3份上游源码／测试、原许可及Schema来源、4份说明136条本地链接和CLI帮助通过`runs/warp-source-verification.json`，`git diff --check`通过。
- 独立`jsonschema 4.26.0`针对UIGF组织验证仓库提交`3f87dbfa4ae690b56237f867c13d4fcb0c4c4ac2`的原Schema，通过15语言×6时区×2格式的180组导出和2项拒绝反例，记录`runs/warp-schema-verification.json`。UIGF／SRGF Schema SHA-256分别为`4cfe8552707ba86fefc26daa79340d1067d63faa0a5ea69e5f34de9d1c17e134`、`53ae458aa3241f1f2ceb6776818141ef9bb7174e04f1bc3bb01840844833d5c8`。第三方验证器包和原Schema只在本地忽略目录，不加入运行依赖或分发包，也不是格式认证。

可复用的[离线校验脚本](../tools/warp_schema_check.py)以相同180组及2项拒绝反例再次通过，记录`runs/warp-schema-tool-verification.json`。从[固定来源的两个Schema](https://github.com/UIGF-org/UIGF-SchemaVerify/tree/3f87dbfa4ae690b56237f867c13d4fcb0c4c4ac2/src/source)取得原JSON后，可在单独的开发目录准备`jsonschema`并执行下列命令；脚本先核对来源哈希，不下载文件、不安装依赖、不读取玩家数据：

```powershell
.\.venv\Scripts\python.exe tools/warp_schema_check.py --schema-dir .\runs\warp-standard-source --validator-dir .\runs\warp-validator
```

脚本另已核对空Schema篡改会被来源哈希拒绝、无开发验证器时帮助仍可打开，记录`runs/warp-schema-tool-negative.json`；没有通过放宽Schema得到正向结果。第三方验证器包、Schema原件、虚构导出、原失败日志与辅助审计均保持忽略。

全部账号、鉴权、缓存、接口与时间样例均为虚构；没有读取实际Player.log或账号缓存，没有向实际账号接口发送鉴权、启动游戏、消耗资源或构建EXE。培养目标列表与材料详情缺少校准样本，未用本功能替代其读取，其他未完范围继续见[开发路线](development-roadmap.md)。
