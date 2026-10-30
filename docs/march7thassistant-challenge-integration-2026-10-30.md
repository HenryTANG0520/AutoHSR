# 三月七挑战与外部引擎接入研究

研究日期：2026-10-30。固定上游为March7thAssistant `7cf6c6bed474539485d3b1504077ac352866829f`，作者为moesnow及其贡献者，源码受[GPL v3](../assets/upstream/March7thAssistant/LICENSE)约束。本报告只读既有研究缓存及AutoHSR源码，没有运行上游／外部引擎、读取游戏进程、操作游戏或新增实机截图；没有迁入挑战实现。当前实现进度仍见[开发清单](development-roadmap.md)。同轮兑换码`auto`服务器解析另见[兑换码说明](redemption-codes.md)，与本报告的未实现挑战分开。

## 三种原生高难与两套外部引擎

上游[ChallengeManager](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/__init__.py#L9)直接创建三种高难模式，传入两队、层数、秘技热键及自动战斗检测配置。注册表另含日常`memoryone`辅助，不将它混作第四种本轮高难目标。

| 能力 | 固定上游执行方式 | AutoHSR接入前仍需核实 |
| --- | --- | --- |
| `forgottenhall`／混沌回忆 | 原生`MemoryOfChaos`：选层、两队、上下半、失败后交换队伍的两次尝试及领奖 | 当前页面、同层两半与星数／胜负的独立结果；明确两队名单与选角来源 |
| `purefiction`／虚构叙事 | 原生`PureFiction`：两队、层数及每半增益选择 | 增益关系、两半分数／星数、失败／退出与完整结算 |
| `apocalyptic`／末日幻影 | 原生`Apocalyptic`：两队、节点定位、增益、下一节点及挑战结束 | 当前节点归属、两节点结果及分数／星数，不能把下一节点按钮当整层成功 |
| `universe`及上游`divergent` | 外部Auto_Simulated_Universe：`simul.exe`／`simul.py`或`diver.exe`／`diver.py` | 固定引擎版本与来源、暂停／停止实际生效、结构化游戏结果、原生账号／预算门禁 |
| `fight`／锄大地 | 外部Fhoe-Rail：`Fhoe-Rail.exe`或`fhoe.py` | 路线与资源范围、完整子进程生命周期、结构化完成／失败及输入释放 |

三种高难的层数选择、星数初读及特定页面识别可作行为参考；它们不是只安装一个外部EXE即可完成的接口。上游[BaseChallenge.select_characters](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/basechallenge.py#L70)及[末日专用选角](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/apocalyptic.py#L193)直接按角色模板名单选角并滚动列表；固定screens中的`prepare_fight`和`configure_team`只声明退出动作，没有高难命名预设／快捷编队的可用导航证据。2026-10-30用户已明确允许仅高难模式按明确角色名单编队，该例外记入[开发约定](../AGENTS.md)，日常／差分等既有预设规则继续保留。

AutoHSR现有[差分预设](../autohsr/du_team.py)及[饰品预设](../autohsr/planar_team.py)分别受本模式标题／页锚约束，不能外推到高难。后续高难配置应冻结用户明确提供的两份完整角色名单，核对各队四人、两队无重复及实际选中结果；当前未提供实际名单，不能从“哈哈哈哈”推导两队或默认选择角色。名单编队已获授权，当前页面来源与原生选择反馈仍需适配及验证。

## 退出0与游戏成功的断层

上游三种挑战的`run()`在`prepare()`为假时仍可正常返回；[ChallengeManager.run／start](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/__init__.py#L18)对三种高难没有向外返回游戏结果。[main.run_sub_task](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/main.py#L264)调用任务后，只要未抛异常便记录完成遥测，并不检查其返回值；主入口仅在`main()`明确返回`False`时退出1。因此正常退出0最多证明这条调用链没有对外报告异常，不能直接写成层数、星数、分数、奖励或整批挑战成功。

例如[混沌check_fight](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/memoryofchaos.py#L176)以另一半准备图或返回按钮配合失败／暂停排除判断结束，每半等待上限30分钟；这些布尔结果没有携带本次最终星数与原图来源。当前层数的星数读取和战斗返回布尔是不同证据，不能把前者当作后者的已核实收据。虚构的[增益选择](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/purefiction.py#L153)、末日的[节点／结算分支](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/challenge/apocalyptic.py#L268)也应分别适配观察、输入和反馈，不复制固定点击后就记完成的边界。

外部引擎路径更明确地依赖[utils.command.subprocess_with_timeout](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/utils/command.py#L5)：只有`returncode == 0`便返回真，超时只`terminate()`当前子进程。Universe据此[执行后续领奖](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/universe.py#L170)，Fight据此[保存时间戳并通知](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/daily/fight.py#L104)。这证明包装器采取了哪些后续动作，不能证明外部引擎已经提供可核验的游戏结果。

GUI的[进程树强制结束](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/app/log_interface.py#L1469)与父任务的[协作暂停检查点](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/utils/pause.py#L1)同样不能直接证明外部引擎已经停发输入。接入前要区分请求停止、子进程退出、其后代退出、输入释放和结果保存；当前AutoHSR的[独立停止意图协议](task-workflows.md)并不自动为未知外部程序补齐这些回执。

## 外部版本与后续实现边界

固定上游tree记录的子模块指针为`3rdparty/Auto_Simulated_Universe = f3c58ffac1687029e0d3126322c87be62855154f`及`3rdparty/Fhoe-Rail = c37db20ab8d4c5f6601a21dcf53eab62099fb824`，仓库映射见固定[.gitmodules](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/.gitmodules)。但[Universe.update](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/universe.py#L20)的EXE更新使用moesnow fork发布或MirrorChyan latest，源码更新指向CHNZYX仓库`main.zip`；[Fight.update](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/daily/fight.py#L17)也使用发布资源或`master.zip`。子模块指针、下载渠道和实际运行文件版本不是同一证据。若以后接入，需另冻实际引擎／依赖／模型与资源哈希及许可，不能将March7thAssistant的固定提交等同于所有运行时依赖已固定。

本轮未核读这两个外部固定提交的完整内部实现，也未运行其输入／停止协议；不据包装器缺少回执推断外部引擎必然没有该能力。AutoHSR现有原生差分路径与验收保持，不因上游也包装`diver`就替换。

建议的后续交付顺序是先为混沌入口建立原生Context观察及配置，核对当前周期、层数、已获星数和明确两队来源；再分别实现准备、明确名单选角、出战、上下半与最终结果，每步保留当前账号、输入代次、动作意图和反馈。已完成半场不能被后半失败抹掉，未知提交／动画不重放，也不照搬上游交换队伍重试或按黄色C提示开自动的行为。完整原生结果协议成立后，再扩展虚构增益与末日节点；外部引擎接入另行验证版本、资源范围与生命周期。研究后已另接[明确计划与有限混沌备战](challenges.md)，仅至首个目标层准备页；上述完整选角、出战与结果仍待编码，不作为完整高难执行入口。

仍缺当前客户端的脱敏入口、两队选角、上下半准备、胜利／失败／主动退出、星数／分数结果及加载遮挡反例；没有真实留出或完整实机挑战验收。只读缓存核对不计作单元测试或玩法成功。

## 固定源码核对

下列11份缓存原件均已重新计算`SHA1("blob N\0" + bytes)`并与固定tree的Git blob及大小核对，另记录SHA-256。没有把这些原件分发入AutoHSR或署为已移植；已有来源记录继续保留。

| 上游路径 | Git blob | SHA-256 |
| --- | --- | --- |
| `main.py` | `feab0b158e1f80c2b7a0c85c6cc276479d710bf4` | `790391e9552763e1568c2c3165447d1c237a5ba4acabb0eff0fc2a04ff333211` |
| `tasks/challenge/__init__.py` | `233e9da7b23c2acbe7762ebdbe57bc61ba50d9c9` | `f2498a176b2b24a3fea36b6f601564ee482b7d8a095c21db59c0640987a89c7d` |
| `tasks/challenge/basechallenge.py` | `5d7f4b7ff1a73ee40db16225fa3d2286c06f1ae9` | `4bf7a5855682af3aa36c1719968b937148884189e143342f50249cd34ebb1706` |
| `tasks/challenge/memoryofchaos.py` | `6d84252e7ff255dff63ce2efc73a8332a2019977` | `831ee7dc4467a8bf6138a26146f2bff27b6c1602e9fcc811d4a94267d26adafb` |
| `tasks/challenge/purefiction.py` | `42715d66274e18d3e8f6976bbc3b0ade67059fde` | `632d72eec31a2153f90b4438c5664a4149f648c35ad102b4c47aa0dd3d018429` |
| `tasks/challenge/apocalyptic.py` | `41ac3d50243786543c646deda1e285af0dfd2f6d` | `782b942eca36cc3b752a5ea4baf6f58028b48b829029831651d50e3c3acbd05c` |
| `tasks/weekly/universe.py` | `3b2e46a027e8aa051957e43c03def08500a17571` | `70842317ab9c9202d774ac6de81a1b32cdb13334959ea20f311c2449a46b3a4a` |
| `tasks/daily/fight.py` | `02346a64b3fde092d2da0e28722e30298e1ab40b` | `0e100e428721748c9b74cd93ade13c32a194bd2b4252dc6c17ce09164ae1053a` |
| `utils/command.py` | `12c0462c4a74cfd7c5c5fb1d787fbd3d674af047` | `24b96704c33753c5674f3287fefa96e9efd137199ccc78532661890dda60ef40` |
| `utils/pause.py` | `85e66626af3b6f626c652de9a50b2d12cf86b7bc` | `d252c2667ea203c1135fac1517f46879dab31f372094e2120267a6d311629086` |
| `app/log_interface.py` | `e228fe2719060366615b0adbd8bfbe0616dc1310` | `8dec5a09d7427ce2a3c4670bab48292ae44979ba04df281164ea586b95141de5` |
