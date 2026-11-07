# AutoHSR resource attribution

## 2026-11-07 巡星之礼活动导航

三个模板来自星阳希公开 4.6 活动实录 P5 的 108.0 秒，640×360 原解码 BGR SHA-256 为 `868522d5495e8531dc7b84c40545efa12d5fca141afa1547bd039da2de5f8f55`。PNG 直接编码裁片，无缩放。三份回放分别取 122.5、90.0、127.9 秒，仅保留 `[104,8,177,36]` 和 `[15,62,82,329]` 两块，其余像素清零。模板和回放均不含 UID。游戏美术权利归 HoYoverse 及相应权利人，原视频归上传者及相应权利人。[P5 原片](https://www.bilibili.com/video/BV1JZaV6XEH3/?p=5) · [回放文件](../autohsr/tests/fixtures/daily_event_navigation)

| 文件 | 源裁剪 `x1,y1,x2,y2` | 文件 SHA-256 |
| --- | --- | --- |
| `event_rewards_badge.png` | `112,14,128,29` | `4c41740310a2e63fc68fc2402e855edc7b84ea6d1171632f61223d0ad61d5055` |
| `event_rewards_caption.png` | `131,19,170,25` | `e3dfe277a3dba477a2c7026ea55a3bc0fc3d40bda80996612d243c667d5e597c` |
| `event_odyssey_row.png` | `24,98,76,113` | `25e3299b542a3f89157bec390fe3519a1267538ec3c826c377c79d7611d48a9d` |
| `activity-list.png` | 两块保留区域 | `9c6713edc1cce5f35320dd358d667a30cfb074e89ea42376a62c60c5e3dbc65f` |
| `activity-list-scrolled.png` | 两块保留区域 | `b3ae44449fab612b2a77d4416f597b246c2f003f100bed47ee319d4d772c194c` |
| `claim-popup.png` | 两块保留区域 | `a0ada14aeaefc54e866172d87993ae8f84d27eece99f0edff12461c7d3c11970` |

巡星之礼手动回页复放仍用同一 P5 640×360 原视频。23 份 PNG 各仅保留标题、侧栏、日卡分隔线、物品标记、票面及数标的六个像素框，边缘留 3 像素，其余清零。回放不含 UID 或账号信息。帧索引、原始与脱敏哈希、像素框及来源许可记在[淡出回放清单](../autohsr/tests/fixtures/daily_event_claim_fade/manifest.json)。

## 2026-11-07 奖励指南旅程热点

素材取自星阳希公开的国服简中 4.6 活动实录 P5。使用上节同一 640×360、约 30 fps 播放源，视频 SHA-256 为 `8b81a95fa3f001175c3ff7d6193016824810c41ae9f058499d81ade79d3fb480`。两个模板从 233.8 秒的原解码 BGR 帧直接裁剪并编码 PNG，该帧 SHA-256 为 `fa2659fd95539d063169da8cc4c7eafa533a7bcdc69aef6df3b4ef8aa317287b`。裁剪为左闭右开像素框。游戏美术权利归 HoYoverse 及相应权利人，原视频归上传者及相应权利人。[P5 原片](https://www.bilibili.com/video/BV1JZaV6XEH3/?p=5)

| 模板 | 裁剪 `x1,y1,x2,y2` | PNG SHA-256 |
| --- | --- | --- |
| `reward_guide_title.png` | `12,12,70,31` | `c4907e1520335449211026214fabde2e53a917e692ec8bf3cb52b3d962f35b94` |
| `reward_guide_highlights_banner.png` | `174,61,274,78` | `7062c6a9c8e58ec379cfdfcf47933a7934a66af35fd4bc60a6650d0d5562a890` |

回放只保留左侧标题与页签 `[4,6,105,109]`、青色标题条 `[121,44,452,94]` 和浅色列表中段 `[355,110,455,320]`，其余像素清零。裁片不含 UID、账号信息、奖励数字或活动条目文字。原帧索引按视频秒数乘 30 取整。234.8 秒的退场帧仍可由 RapidOCR 读出「旅程热点」，亮色布局已消失。[回放文件](../autohsr/tests/fixtures/daily_reward_guide) · [识别回归](../autohsr/tests/test_daily_reward_guide_pages.py)

| 回放 | 秒数／帧索引 | 原解码 BGR SHA-256 | PNG SHA-256 |
| --- | --- | --- | --- |
| `highlights-2328.png` | 232.8／6984 | `6151b79b13e81da8fd0998dd91a7cf4460e89741fc0e1cb3e06f0b83ba96aa7f` | `86379d16bab052c8c2dc662a8f96e0a62cfa42f5db8793732c6f7dee96b906a0` |
| `highlights-2346.png` | 234.6／7038 | `f1c088ed4fedf40ee39464bac71ef9c7cf5c5d2db0c3aa6e665dcd9afda92604` | `8b61ef13f4759fc037aa5ece39e490358d6d516654aa9f67cff8453f951b6d28` |
| `fade-2348.png` | 234.8／7044 | `5b0f276b12191e7bb6b426f178b47b9311076fcb7f4dfce5ffce5f7356331c43` | `6314a3e5ad4023f99e51c7620a0d4cc40419348e3b20131270f1e558baa129b4` |

P5 的 234.6 秒鼠标位于首行「前往」按钮，235.2 秒开始显示活动列表，236.0 秒可见选中的星际幻宠乐园。这段录像只提供页面去向旁证。固定上游的页面映射另将奖励指南的 Esc 去向列为活动列表，仍待本机原生回退核验。[P5 原片](https://www.bilibili.com/video/BV1JZaV6XEH3/?p=5&t=234) · [三月七页面映射](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/screens.json)

列表视野回放沿用同一 P5 原始 BGR，保留 `[4,6,105,109]`、`[121,44,452,94]` 和 `[121,97,469,318]`，其余像素清零。内容包括活动名称、缩略图和计时，排除账号信息、右侧奖励数字及操作列。两个时点的可见列表保持静止。分组标题模板直接裁自 233.8 秒的 `[122,98,159,112]`。[P5 原片](https://www.bilibili.com/video/BV1JZaV6XEH3/?p=5&t=233)

| 文件 | 秒数／帧索引 | 原解码 BGR SHA-256 | PNG SHA-256 |
| --- | --- | --- | --- |
| `reward_guide_ongoing.png` | 233.8／7014 | `fa2659fd95539d063169da8cc4c7eafa533a7bcdc69aef6df3b4ef8aa317287b` | `f5a19224be6248b4305d2d1e8753b682139c573bc1093a088a1c2fa3486bd225` |
| `viewport-7014.png` | 233.8／7014 | `fa2659fd95539d063169da8cc4c7eafa533a7bcdc69aef6df3b4ef8aa317287b` | `1bba52447a1a30884021e67bc0e24f5ca968841db399393dff6cbd80397248f9` |
| `viewport-7026.png` | 234.2／7026 | `eb41f63ee98aa5b48e4bc9c8d956f3066b99d29c7819c7152356c2bd5f224a1b` | `1097742b1529474aea35c547931d6fe90d633594ed5ab3ad583fbfc723b25703` |
| `viewport-fade-7041.png` | 234.7／7041 | `85806472525bfce44b2b70468c5883ab7960b76ddcb7284dc293714c11f0b7e3` | `348c396b40733b6ae1f28d1ebeb2e5c2bc86125652b8a96b0e844a80b83577b1` |

7041 淡出反例保留 `[4,6,105,109]`、`[121,44,452,94]`、`[118,95,452,114]` 与 `[355,110,455,320]`，原尺寸直接编码，其余像素清零。指南页名在这一帧仍能核实。仅在内容框读取中，两个橙带各自以红通道至少 218 核对原有的 75% 色块覆盖。用 6978–7040 的 63 张亮态原帧（含 7014、7026）在 640×360 原尺寸及放大到 960×540、1920×1080 后归一复核，亮态每带至少 91.2% 命中，7041 每带最多 0.62%。正式内容框仍要求画面至少 960×540。[P5 原片](https://www.bilibili.com/video/BV1JZaV6XEH3/?p=5&t=234) · [回归](../autohsr/tests/test_reward_guide_viewport.py)

## 2026-11-07 漫游签证选中页签

三张国服 4.6 时期玩家公开静态截图用于核对收集展示、角色展示和战绩展示。夹具保留最小页签裁片与白名单界面文字、坐标及分数。原图、UID 和账号信息未入库。游戏界面权利归 HoYoverse 及相应权利人，原截图归上传者及相应权利人。[公开原帖](https://www.miyoushe.com/sr/article/79174169) · [来源、裁剪与哈希](../autohsr/tests/fixtures/daily_visa/sources.json)

## 2026-11-07 培养材料槽取证

银河沙盘两个正向槽及星系框架反例取自公开国服 4.6 视频，仅保留物品图案及槽位数字。游戏美术权利归相关权利人。使用既有海原电视塔目录小图作识别参考，样本来源、裁剪与 SHA-256 见[素材清单](../autohsr/tests/fixtures/dungeons/build_target_slots/sources.json)。

## 2026-11-06 逐光捡金页签图标

保留固定 March7thAssistant 逐光捡金未选中图标的原始字节，用于识别生存索引上的相邻页签。上游作者为 moesnow 及其贡献者，游戏美术权利归 HoYoverse 及相应权利人。[来源与哈希](templates/high_guide_tab.json) · [GPL v3](upstream/March7thAssistant/LICENSE)

任务流的 `workflow_guides` 夹具复用历史逐光捡金和旷宇纷争画面。保留指南页签和有限版式文字裁片，账号与其余区域遮盖。源文件、裁片、缩放方法和哈希见清单。游戏美术权利归 HoYoverse 及相应权利人。[夹具清单](../autohsr/tests/fixtures/workflow_guides/sources.json)

## 2026-11-06 差分周期结算 OCR 字段

本地历史原图与国服 4.6 日期范围内的公开周期演算录像用于结算字段及相邻页面回归。仓库保存筛选后的 OCR 文字、归一化坐标与原件或解码帧 SHA-256。游戏界面权利归 HoYoverse 及相应权利人，录像权利归各上传者及相应权利人。[字段与来源](../autohsr/tests/fixtures/du_runtime/periodic_settlement_fields.json) · [原片对照](../docs/du-validation.md#2026-11-06-周期积分实增与差分领奖原片)

## 2026-11-06 普通末日终局 OCR 字段

4.6 常规末日及星启的公开原片用作布局正反例。仓库保存 RapidOCR 文字、原画面归一化坐标、原件时间和最小去 UID 裁片 SHA-256。游戏美术归 HoYoverse 及相应权利人，原片归各上传者及相应权利人。[字段与来源清单](../autohsr/tests/fixtures/challenge_apocalyptic_result_4_6.json)

## 2026-11-06 常规混沌层图与备战 OCR 字段

4.6.0 本机授权校准用于对照灰星、锁定、亮圆环及第十层双队备战。仓库保存筛选后的界面字段、归一化坐标及去 UID 裁片摘要。星形继续使用已有 March7thAssistant 原件，游戏界面权利归 HoYoverse 及相应权利人。[字段与来源清单](../autohsr/tests/fixtures/challenge_chaos_map_4_6.json) · [已有星形来源](upstream/March7thAssistant/challenge-ui/sources.json)

## 2026-11-06 高难结算反馈局部图

新增固定 March7thAssistant 的两幅模式返回图、一幅节点去向图和一幅红色「败」字图。四幅原件保留原始字节，作者为 moesnow 及其贡献者，游戏美术权利归 HoYoverse 及相应权利人。原路径、尺寸、Git blob、SHA-256 和观察用途记入来源清单。[局部图说明](upstream/March7thAssistant/challenge-ui/README.md) · [原图清单](upstream/March7thAssistant/challenge-ui/sources.json) · [GPL v3](upstream/March7thAssistant/LICENSE)

## 2026-11-05 货币战争满席历史裁片

新增三张历史超频 A0 的地面晶矿裁片，仅保留晶矿区域。三帧为同一历史事件的前后观察，原件留在本地。标准局回归将裁片与合成备战、提示和假窗口组合。游戏美术归 HoYoverse 及相应权利人。原件 SHA-256、变换、游戏版本和裁片哈希见[来源清单](../autohsr/tests/fixtures/currency_crystals/sources.json)。

## 2026-11-05 货币战争桌面执行入口

循环、积分核对和普通领奖沿用已适配的固定March7thAssistant流程；新增[桌面控件](../autohsr/currency_controls_ui.py)及[结果投影](../autohsr/currency_controls_feedback.py)为AutoHSR编写，复用既有指南、开发工具和结果页。新循环与原目标接续、积分与奖励、开发胜败与独立验收分别呈现；没有新增图像、模型、账号截图或上游输入框架。关联原生文件及检查记入[source.json](upstream/March7thAssistant/source.json)，原作者、GPL v3和素材权利说明保持。

## 2026-11-05 差分独立红点领奖

[独立领奖](../autohsr/du_rewards_only.py)与[领取记录](../autohsr/du_reward_store.py)为AutoHSR原生扩展，复用既有[奖励页面](../autohsr/du_rewards.py)及脱敏的拟合／稳态／月下／画廊素材；没有新增图片、模型或原始账号截图。各原素材来源及游戏美术权利说明保持，新增文件／测试及范围记入[source.json](upstream/March7thAssistant/source.json)。

同日桌面接线复用现有差分插图、控件和结果页；独立模式的范围、卡带选项及[结果投影](../autohsr/du_rewards_feedback.py)为AutoHSR编写，没有新增上游图像、截图或输入框架。

固定March7thAssistant的`check_divergent_universe_score`与`get_reward`另有周期积分／邮件发放语义，本次没有移植其盲点或把原生右侧红点当成周积分奖励。已有作者moesnow及贡献者与[GPL许可](upstream/March7thAssistant/LICENSE)保持；接口、请求范围和未实机边界见[独立领奖说明](../docs/du-rewards-only.md)。

## 2026-11-05 高难单位与列表候选

[列表候选观察](../autohsr/challenge_roster.py)为AutoHSR原生实现，参考固定March7thAssistant `7cf6c6bed474539485d3b1504077ac352866829f`的`BaseChallenge.select_characters`及`Apocalyptic.select_characters`列表裁剪关系，继续使用既有105幅[原始头像及来源清单](upstream/March7thAssistant/support/sources.json)。作者moesnow及贡献者、[GPL v3](upstream/March7thAssistant/LICENSE)与游戏美术权利说明保持；没有新增图片、模型、上游输入框架或账号整图，候选、歧义与完整入队分开，接线范围记在[source.json](upstream/March7thAssistant/source.json)。

5组有限皮肤去重为原生配置规则，另依据官方文章全文核实外观所属角色；[身份模块](../autohsr/challenge_identities.py)保留4篇官方页面URL、CMS编号及读取正文SHA-256，没有分发文章全文或将其当成完整形态／单位表。具体对应关系、来源链接及未覆盖范围见[高难说明](../docs/challenges.md)。

## 2026-11-05 虚构备战与末日观察

沿用固定 March7thAssistant 提交，增加虚构标题、金色星点形状、「进入故事」、「开启故事」和末日标题共 5 幅原始局部图。选层与页面观察使用原件哈希和源裁剪关系，原生输入继续经过 AutoHSR 的账号、窗口及持久意图门禁。原件未经变换，保留作者 moesnow 及贡献者、GPL v3 和游戏美术权利说明。[原图清单](upstream/March7thAssistant/challenge-ui/sources.json) · [适配记录](upstream/March7thAssistant/source.json) · [GPL v3](upstream/March7thAssistant/LICENSE)

## 2026-11-05 周目标与首次收店执行来源

差分周常的当前周门禁及货币初始商店的当前执行证明均为AutoHSR原生协议，继续使用既有[来源清单](upstream/March7thAssistant/source.json)与[GPL许可](upstream/March7thAssistant/LICENSE)，没有新增上游截图、模型或输入框架。周目标保持冻结，历史确认与重新观察分开；新的只读双帧证明不授权交易或重放未知输入。边界及验证见[周常说明](../docs/weekly-plan.md)、[初始环境说明](../docs/currency-wars-initial-environment.md)及[验证记录](../VALIDATION.md)。

## 2026-11-05 补给装备列表协议

继续参考固定March7thAssistant `7cf6c6bed474539485d3b1504077ac352866829f`的`check_supply_phase`及“过剩经费”双装备机制，补齐AutoHSR原生候选、策略、确认与交付的装备列表契约。固定[来源清单](upstream/March7thAssistant/source.json)、作者moesnow及贡献者与[GPL许可](upstream/March7thAssistant/LICENSE)保留，没有新增上游源码、图片或模型。双件字段与交付变体为合成机制检查，不称真实布局或独立留出；既有单件校准及未完成项见[补给说明](currency-supply/README.md)。

## 2026-11-01 本地核心序列协作

执行权及账号连续性为AutoHSR原生协议，现由任务树扩展到独立日常／周常计划和货币战争循环／周常。没有迁入新上游源码、截图、输入框架或增加模型素材；已有固定[来源清单](upstream/March7thAssistant/source.json)及GPL许可保持。控制器同线程加入既有作用域，不替换外层账号或发布器，跨线程与嵌套任务树仍拒绝；实现与证据边界见[账号连续性](../docs/workflow-account-continuity.md)。

## 2026-10-30 高难计划与有限混沌备战

固定March7thAssistant `7cf6c6bed474539485d3b1504077ac352866829f`的挑战源码作为模式／层数、名单及局部页面关系参考，作者moesnow及其贡献者与[GPL v3](upstream/March7thAssistant/LICENSE)保持，原件哈希与原生适配范围记入[source.json](upstream/March7thAssistant/source.json)。14幅最小原图逐份查看并按固定tree／Git blob／SHA-256／大小核对，原样分发于[challenge-ui](upstream/March7thAssistant/challenge-ui/README.md)；没有重编码或发布游戏整图／账号内容。游戏美术权利归HoYoverse及相应权利人。

新双队计划及准备意图／反馈协议为AutoHSR原生实现；现有105头像只作已知标识目录，不沿用好友列表几何或宣称已选。只接有限正星关联选层与备战观察，没有导入上游选角点击、重置／交换重试、固定直行／秘技／攻击、开战或领奖，实际API及检查见[高难说明](../docs/challenges.md)。完整高难和真实页面仍未完成验收。

## 2026-10-30 兑换服务器自动解析参考

固定March7thAssistant `utils/registry/star_rail_setting.py`已原样缓存在既有研究目录，Git blob为`156538a8313020a4bd9aedfd780d9025a820a736`、SHA-256为`84d6a44693888b610cd65476a5c1093b36626cad403ca52b2301f9c7298184a2`，11538字节，已核对固定tree。作者与[GPL v3许可](upstream/March7thAssistant/LICENSE)保持，来源加入[source.json](upstream/March7thAssistant/source.json)。本轮只参考`get_game_path`的两份HYP包名及`GameInstallPath`字段，原生实现／验证状态见[兑换说明](../docs/redemption-codes.md)；没有分发原模块或导入其模块级探测、FPS／分辨率／自动战斗读写功能，没有读取真实用户注册表或进程。

## 2026-10-30 March7thAssistant兑换码参考与离线表

固定参考版本为March7thAssistant `7cf6c6bed474539485d3b1504077ac352866829f`，作者为moesnow及其贡献者，保留[GPL v3原许可](upstream/March7thAssistant/LICENSE)。`tasks/daily/redemption.py`与`assets/config/redemption_codes.json`已按固定Git tree核对Git blob、字节数与SHA-256，见[source.json](upstream/March7thAssistant/source.json)。[离线码表](upstream/March7thAssistant/redemption_codes.json)原样保留2054字节，没有重排、筛选或改写原码；它是固定版本回退数据，含历史到期记录，不证明当前有效。

页面参考另含固定`assets/config/screens.json`与`module/screen/screen.py`；[redemption-ui](upstream/March7thAssistant/redemption-ui/)原样保存五幅最小标题／控件图，分别来自`screen/redemption.png`、`share/menu/more.png`、`share/redemption/paste.png`、`share/redemption/clear.png`及`zh_CN/base/confirm.png`。没有裁改、放大或重编码；各原路径、公开路径、尺寸、Git blob、SHA-256和字节数均在同一清单。逐张查看仅含标题／图形，无UID、账号内容或整图；这些局部模板不证明完整表单或结果布局已实机校准。

在线获取／回退、精确服务器与到期筛选、逐码输入及反馈分别改写为[码表解析](../autohsr/redemption_codes.py)、[只读页面](../autohsr/redemption_pages.py)和[原生流程](../autohsr/redemption_run.py)，函数及范围记在adaptations。账号＋服务器＋原码意图／回执、严格JSON与锁、当前Context目标重核、精确双capture读回／反馈、无剪贴板Unicode输入及配置／CLI分离属于AutoHSR原生扩展，另记native_extensions；没有迁入上游全局已用列表、注册表服务器推断、通用输入／页面路由或GUI。实际接口与验证状态见[兑换码说明](../docs/redemption-codes.md)。

本轮固定原件下载不请求实时码表、账号API或真实兑换；未新增实机截图或模型。游戏界面与图形权利仍归HoYoverse及相应权利人，GPL源码许可不授予额外游戏美术权利。

## 2026-10-30 初始环境接受与确认后现状

[初始来源](../autohsr/currency_wars_initial.py)、[专用免费收店](../autohsr/currency_wars_initial_shop.py)及正式Flow／Context接线为AutoHSR原生扩展。固定上游`check_investment_environment`的效果解析参考及GPL v3署名继续保留，未迁入其缓存增角色计数，也不把上游列表清空当作初始零基线；文件和范围记在[source.json](upstream/March7thAssistant/source.json)的native_extensions。

沿用既有4.6环境匿名文字夹具、当前十九格与14格库存读取，没有新增公开素材、模型或真实采集。原动作／PNG／像素来源、两次独立capture、选择接受、首次post_choice现状及unattributed声明分别记录；库存unknown保留partial，delivery_verified始终false。原失败与旧格式不补成功，未知不重放；实际API、兼容和验证边界见[说明](../docs/currency-wars-initial-environment.md)。

## 2026-10-30 货币战争自动状态只读观察

[CW状态检测](../autohsr/currency_wars_auto.py)及[标准节点观察接线](../autohsr/currency_wars_standard_node.py)为AutoHSR原生实现。新公开范围仅为[最小控制组说明](currency-auto/README.md)、[来源清单](currency-auto/sources.json)、12份右上局部裁片及2幅CW控件图形；没有重新采集游戏、分发原始整图或公开调查临时目录。清单保留匿名样本ID、原图／裁片SHA-256、裁剪坐标、版本或unverified、变换及分组，不含UID、账号指纹、原始文件名或安装路径。游戏美术归HoYoverse及相应权利人，不授予额外游戏素材许可。

状态还与本仓库已有真实DU开启图形、暂停控件及饰品禁用图形交叉核对，旧素材署名保持。1份4.6.0完整CW组用于on校准，两份10月18日斜杠组用于disabled校准／历史回放，其余未知及同局邻近遮挡分别保留；未知版本不补为当前版本，合成缩放／遮挡／灰度不当作真实off或独立留出。上游固定`check_auto_battle`及黄色C图片仅作区别研究，blob／SHA-256记在清单的`upstream_research_only`，未移植其图像、搜索位置或热键。来源总表另记[原生扩展](upstream/March7thAssistant/source.json)。当前仅on／disabled／unknown只读观察，无off、开启动作、真实切换或整局验收，范围见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-30 March7thAssistant应用内定时参考

固定March7thAssistant提交`7cf6c6bed474539485d3b1504077ac352866829f`，作者moesnow及其贡献者，GPL v3。`app/common/schedule.py`的分钟时隙／下次时刻与`app/log_interface.py`的启动分钟、定时检查和冲突生命周期，改写为[原生计划](../autohsr/schedule_plan.py)及[调度控制器](../autohsr/schedule_runtime.py)。两份源码的Git blob、SHA-256及字节数、具体参考函数见[source.json](upstream/March7thAssistant/source.json)，完整原许可继续保留于[LICENSE](upstream/March7thAssistant/LICENSE)。不迁入上游Qt／QProcess GUI、任意程序参数、默认失败续链或完成后系统操作。

[本地版本与时隙回执](../autohsr/schedule_store.py)、固定北京时间、显式当前进程启用、原生Runner与预算／账号门禁、唯一执行权和公共事件允许字段是AutoHSR实现。[共享只读控制意图](../autohsr/run_control.py)及原生／计划／CW循环／任务树／通知wrapper的`stop_requested`也是本项目原生扩展；它跨报告保存错误传播停止，控制器／slot／原游戏／通知分别保留结果，不迁入上游输入或控制框架。`utils/schedule.py`及`tasks/game/__init__.py::after_finish_is_loop`只作区别研究，在清单中明确标记`research_only_not_ported`；系统自启、无限体力循环及管理员任意参数桥没有迁入。没有新增游戏素材、模型或真实采集，没有登记真实系统任务或启用真实计划；当前范围及后续实际验证见[定时说明](../docs/schedules.md)。

## 2026-10-30 March7thAssistant文字通知适配

固定March7thAssistant提交`7cf6c6bed474539485d3b1504077ac352866829f`，作者moesnow及其贡献者，GPL v3。`module/notification/__init__.py`、`notification.py`、`notifier.py`及23个渠道源文件的文字参数、端点／请求结构、合并文字、钉钉／飞书签名及自定义替换改写为[原生文字适配](../autohsr/notify_providers.py)和[SMTP／本机传输](../autohsr/notify_local.py)。共26份实际参考源码的Git blob、SHA-256及字节数见[source.json](upstream/March7thAssistant/source.json)，完整原许可继续保留于[LICENSE](upstream/March7thAssistant/LICENSE)。没有迁入`pac.py`、上游GUI、全局配置或输入框架，也未引入上游通知依赖。

当前用户DPAPI凭据、显式导入与加密覆盖备份、运行版本冻结、摘要允许字段、独立有界HTTP、意图／回执去重及游戏报告隔离是AutoHSR原生实现；Toast为本项目隐藏PowerShell／WinRT实现。当前仅23渠道的文字路径，图片／截图、Bark密文、Matrix E2EE、QQ接收ID发现和PAC／代理高级项尚未接入。没有新增游戏图像、玩家数据、模型或真实采集，检查使用虚构配置、假传输和本地机制；真实渠道和本机Toast尚未验收，详见[通知说明](../docs/notifications.md)。

## 2026-10-30 任务流程账号连续性

[账号作用域](../autohsr/workflow_identity.py)是AutoHSR原生扩展，复用本仓库`currency_wars_identity.account_key`的严格解析，不新增第三方素材或模型。两帧当前捕获、输入代次、跨步骤绑定、原生输入代理、预算延后建立、私人UID区域证据及来源完整性检查为本项目实现；旧DU与CW账本键不重写。依赖仅用已有OpenCV／NumPy，未新增运行包、真实账号或图像采集。测试图片和UID均为临时虚构输入，不作为真实校准或训练数据；私人运行裁剪继续忽略，范围见[账号连续性](../docs/workflow-account-continuity.md)，原生扩展记录见[清单](upstream/March7thAssistant/source.json)。

## 2026-10-30 正式任务流程编排

参考固定March7thAssistant的`module/workflow/__init__.py`及`assets/docs/Workflow.md`，在[任务树](../autohsr/task_workflow.py)、[执行器](../autohsr/task_workflow_run.py)和[独立CLI](../autohsr/task_workflow_cli.py)中适配步骤树、条件、有界循环与选中子步骤的概念。任务级Runner组合、单预算静态预留、已保存原报告核对、Windows跨进程执行归属、先写意图、未知停止和游戏失败后仅本地继续为AutoHSR实现。没有迁入Qt编辑器、坐标／键鼠／模板动作、上游YAML解析、消息推送或官方示例养成流程；详细差距见[任务流程](../docs/task-workflows.md)。两份固定源码／教程的blob和SHA-256及函数记录在[原清单](upstream/March7thAssistant/source.json)，GPL v3原件保留。没有新增玩家样本、图像素材、模型或运行时依赖。

## 2026-10-30 记录窗口统计与Excel

参考固定March7thAssistant的`WarpExport.data_to_html`与`WarpInterface.__onExportExcelBtnClicked`，新增[本地窗口统计](../autohsr/warp_statistics.py)和[Excel序列化](../autohsr/warp_xlsx.py)。保留分池星级和高星着色，同时将首段不完整、缺失星级及物品数量与记录数分开；未知间隔不构造均值，全部统计仍为已导入窗口。UID／ID按文本、显示文字原样保存，按账号分表，停止和错误清理自有临时文件，经原服务发布新文件。源码／函数与适配边界见[原清单](upstream/March7thAssistant/source.json)，没有新增游戏素材、模型或玩家记录。

Excel采用延迟加载的openpyxl 3.1.5与et_xmlfile 2.0.0，均按包声明保留MIT许可；et_xmlfile随附的Python许可文本亦原样保留。[依赖清单](upstream/openpyxl-source.json)记录PyPI固定版本、wheel与许可SHA-256，对应原件为[openpyxl许可](upstream/openpyxl-LICENSE)、[et_xmlfile许可](upstream/et_xmlfile-LICENSE)、[随附Python许可](upstream/et_xmlfile-PYTHON-LICENSE)。新依赖用于Excel序列化，JSON与只分析不加载引擎；未迁入上游Qt界面，实际Excel桌面和GUI图表仍待验收，见[范围与检查](../docs/warp-statistics-xlsx.md)。

## 2026-10-30 跃迁记录获取与交换格式

参考固定March7thAssistant的`app/tools/warp_export.py`和`app/warp_interface.py`，将缓存／链接读取、六类卡池分页、导入及SRGF／UIGF转换改写为[原生记录模块](../autohsr/warp_records.py)、[只读获取](../autohsr/warp_fetch.py)及[独立工具服务](../autohsr/warp_service.py)。多账号显式选择、字符串ID数字排序、跨时区合并、冲突拒绝、原件保留、取消及新文件原子发布属于AutoHSR适配。没有复制Qt控件、自动扫描本机用户目录、上传统计、明文链接输出或覆盖式修复。三份上游源码／测试的固定Git blob及SHA-256、GPL v3和函数范围见[source.json](upstream/March7thAssistant/source.json)。

格式按[UIGF组织](https://uigf.org/)的[UIGF](https://uigf.org/zh/standards/uigf.html)与[SRGF](https://uigf.org/zh/standards/srgf.html)规范实现星铁数据读取和导出；旧SRGF中的联动扩展另作提示，严格旧格式输出拒绝联动记录。官方验证Schema的版本和哈希仅作为本地检查来源，不分发原Schema或第三方验证器包，也不声明认证；本仓库仅提供使用指定离线文件及虚构数据的QA脚本。没有新增游戏图像、模型或玩家记录，所有示例及网络检查为虚构，详见[功能与验证](../docs/warp-records.md)。

## 2026-10-30 整局失败结算与有界循环

参考固定March7thAssistant的`_check_battle_result`与`main.py`循环入口，将普通节点继续与终局失败分开，改写为[原生失败协议](../autohsr/currency_wars_defeat.py)。同局出战、两帧终局、零生命与失败总览、四步独立反馈、原partial报告、逐局胜负计数和原局数上限属于AutoHSR适配；默认失败停止，明确接续只确认该次原回执，自动继续须在循环开始时冻结。未迁入上游输入框架、遥测、放弃旧局或未知失败后重开。源文件blob与GPL v3见[source.json](upstream/March7thAssistant/source.json)。未新增图像、模型或真实采集；失败页面使用已有胜利几何的合成变体，未声称真实布局已校准或失败结算已实机验收，见[范围](../docs/currency-wars-defeat-loop.md)。

2026-10-29差分站点偏好参考固定March7thAssistant `process_next_station`及默认配置，按行为适配为[原生冻结偏好](../autohsr/du_station_policy.py)。保留本项目默认顺序、输入门禁及危险信标检查，没有复制坐标、重抽循环或禁用项兜底。两个原源码blob、GPL v3许可哈希及范围见[站点来源说明](upstream/March7thAssistant/du/README.md)和[清单](upstream/March7thAssistant/du/source.json)；未新增图像、模型或游戏采集，检查使用模拟卡片及已有脱敏回放。

2026-11-06选站只读观察复用同一固定源码的控件分区和已有[脱敏四卡图](../autohsr/tests/fixtures/du_runtime/station_explosion_beacon.png)。[重抽字段夹具](../autohsr/tests/fixtures/du_runtime/station_reroll_fields.json)记录三张简中 4.6 历史画面的原图哈希、局部 OCR 变换和控件文字框。只保留「重抽」及其同行数字。游戏图像归 HoYoverse 和相应权利人，原图保存在本地忽略目录。

2026-11-06 周期三卡重抽以公开简中 4.6 原片核对实际弹窗、暗态零次和同局候选变化，按该证据独立实现一次请求与一次确认。公开画面仅在本地去 UID 后用于离线复放，15 张必要裁片的清单记录时间、范围与 SHA-256。图像版权归相应权利人。[公开原片](https://www.bilibili.com/video/BV1nPSoBDEZn/?p=26&t=1918) · [验证记录](../docs/du-validation.md#2026-11-06-周期三卡重抽回放)

2026-11-06 周期四卡重抽采用同一公开系列两集的简中 4.6 画面。只保留去 UID 的关键帧及来源清单用于本地离线复放，记录卡名、数字、相邻时点及 SHA-256。图像版权归相应权利人。[四卡直接翻牌](https://www.bilibili.com/video/BV1nPSoBDEZn/?p=28&t=120) · [次数先扣对照](https://www.bilibili.com/video/BV1nPSoBDEZn/?p=27&t=2747) · [验证记录](../docs/du-validation.md#2026-11-06-周期四卡直接重抽回放)

同日新增三张简中 4.6 周期选站裁片，依次保留未选、左侧战斗和右侧铸造。各清单记录原报告页号、原图与输出 SHA-256、缩放与保留区。仅保留页标题、预览、卡身和确认控件的像素及相关 OCR。游戏图像归 HoYoverse 和相应权利人，原图保存在本地忽略目录。[未选](../autohsr/tests/fixtures/du_runtime/station_preview_three_447.json) · [战斗](../autohsr/tests/fixtures/du_runtime/station_preview_three_450.json) · [铸造](../autohsr/tests/fixtures/du_runtime/station_preview_three_451.json)

三卡改选的「暂无信标」模板取自同局第 84 页，仅保留 71 × 27 的二值字形。回放夹具保留同一报告两段连续选站与进场标题，原图、变换、遮罩与输出 SHA-256 均随清单记录。游戏图像归 HoYoverse 和相应权利人。[模板](templates/du_station_empty_beacon_ink.png) · [回放来源清单](../autohsr/tests/fixtures/du_runtime/station_empty_beacon_replay.json)

## 2026-10-29 货币战争周常编排

参考固定March7thAssistant的日常`Daily.start`与`CurrencyWars.start`／`check_currency_wars_score`，将积分、原生有限循环及独立领奖接入[周常归属](../autohsr/currency_wars_weekly.py)与[顺序Runner](../autohsr/currency_wars_weekly_run.py)。每账号／游戏周索引、固定对局上限、原日常报告复用、逐局来源审计和只读恢复为AutoHSR适配；没有迁入上游定时器、全局时间戳、遥测或输入框架。源文件blob与GPL v3见[source.json](upstream/March7thAssistant/source.json)。本次没有新增素材或真实采集，检查使用假窗口与合成最终节点。

## 2026-10-29 独立积分领奖

参考固定March7thAssistant的`get_reward`、`_fuel_ticket_limit_visible`及`wait_for_weekly_reward`，改写为[原生积分领奖控件](../autohsr/currency_wars_weekly_rewards.py)、独立Runner与意图／回执存储。沿用AutoHSR当前页面、账号、客户端、代次及输入门禁，另核对两帧奖励展示、数量字段、禁用状态、原图及原报告；满额只记录拒绝结果，不清理或重发。来源blob和GPL v3见[source.json](upstream/March7thAssistant/source.json)。本次未导入上游领取按钮图、GUI或输入框架，未新增真实采集、公开图片或模型；正向领取检查使用合成文字／按钮图像及假窗口，不作为真实领取样本。

## 2026-10-29 本周积分循环目标

在固定上游`check_currency_wars_score`及循环入口参考上，将[独立积分观察](../autohsr/currency_wars_points_run.py)接入[原生循环目标](../autohsr/currency_wars_points_goal.py)。冻结周／账号、局数上限、精确回执、开局前双重门禁与空记录归档为AutoHSR适配；没有迁入全局时间戳、未知失败后重开或领奖实现。函数、blob及GPL v3见[source.json](upstream/March7thAssistant/source.json)。本轮未新增素材、真实采集或模型，检查采用模拟窗口与既有原生报告协议。

## 2026-10-29 积分核对与旧OCR白名单

参考固定March7thAssistant的`check_currency_wars_score`，将积分当前值／上限判断改写为[原生解析](../autohsr/currency_wars_points.py)及账号／游戏周观察回执；函数、Git blob和GPL v3见[source.json](upstream/March7thAssistant/source.json)。未迁入全局时间戳或领取实现，未新增图像或模型。[文字夹具](../autohsr/tests/fixtures/currency_wars_points.json)由三份既有游戏截图的原OCR筛选，仅保留22条菜单、积分与倒计时字段及来源哈希，不带UID、图像和无关余额；它们是旧校准材料，不是新实机留出。游戏界面及文字归HoYoverse和相应权利人所有。

## 2026-10-29 逐局连续运行

参考固定March7thAssistant的`main.py`中`run_sub_task`及其局部循环／货币战争调用，将连续运行改写为[原生组合Runner](../autohsr/currency_wars_loop.py)。逐局归属、冻结目标、账号输入门禁、原报告核验和可恢复归档属于AutoHSR原生适配；最初失败／未知停止，10月30日另接同源已核实失败的可选继续，技术异常／未知仍停止，不按任意false结果重开，也不迁入遥测实现。Git blob及GPL v3许可见[source.json](upstream/March7thAssistant/source.json)。未新增公开图像、模型或真实采集；检查使用合成最终节点、假窗口与既有原生结算协议。

AutoHSR is distributed under the GNU General Public License version 3. The full
license is in [../LICENSE](../LICENSE). The resources below retain their upstream
license and contributor attribution. They are used as UI recognition references
and, where stated below, desktop UI materials.
Honkai: Star Rail artwork and names belong to their respective rights holders;
the upstream software licenses do not grant ownership of those game assets.

## 2026-10-29 指南底纹

更新既有指南的`ui/paper-pattern.png`：仍取自已登记4.6每日实训原图（SHA-256 `6ba21f7ad3417d8bebb0224849221b59b674030e1e964c49e34f676176d28e11`），范围扩为`[236,892,1694,964]`，以连续暖色透明度提取静态底边星图，清除倒计时与挂饰遮挡区，不补全未知像素。处理与输出哈希见`ui/sources.json`；游戏美术权利归原权利人，不纳入代码GPL许可。

## 2026-10-29 设置页布局参考

设置行的左右分区、细分隔线和下拉箭头参考 [GameWith 发布的游戏「其他」设置截图](https://img.gamewith.jp/img/original_ff63c82b79444430e3f32cae5029b920.png)，所在[原文](https://gamewith.jp/houkaistarrail/article/show/447025)。本次读取的原始响应为1200×630 JPEG，SHA-256为`8e6c0f13f458454da06a14570c37e8decec5c764eaa543f288da1846b0894d0f`；原截图游戏版本未标明，不能视作当前客户端逐像素验收。图片只用于本地视觉对照，未作为分发素材；界面以代码绘制，沿用下文已登记的字体。未复制博主的标记箭头、教程或截图像素，也未取得该图片的再分发许可。

展开列表的行高、分隔线和右侧选中圆点另参考[MobileMatters的PC帧率选项截图](https://prod.assets.earlygamecdn.com/images/Honkai_-Star-Rail-PC-FPS-modes.png)，所在[原文](https://mobilematters.gg/gaming/enable-120-fps-honkai-star-rail)标记于2023-07-13更新。读取的1920×1080 PNG SHA-256为`2882740221aaa7033f6cf0d23f9b37dee7227ed270d61a1524cffc7b767c8df6`；本地对照区域`[1406,418,1834,567]`只含两行选项，排除UID和无关内容。`autohsr/setting_choices.py`使用代码和既有字体绘制，没有分发截图像素或新增位图素材。原图游戏版本未知，仅为该静态列表的视觉参考；未取得额外再分发许可。橙点保留已确认值、待确认行焦点框及工作区限高是应用交互适配，不作为游戏键盘行为或当前版本的证据。

## Honkai Star Rail - One Dragon

Source: [OneDragon-Anything/StarRailOneDragon](https://github.com/OneDragon-Anything/StarRailOneDragon)
and its contributors. License: GPL-3.0; the unmodified upstream license is saved
as [upstream/OneDragon-LICENSE](upstream/OneDragon-LICENSE).

Retrieved 2026-10-11 from `main`, whose head at retrieval was
`1ffd7e082c38bcdb559d2c0a194191ae21514ef0`. The following files are unmodified
copies of upstream `raw.png` assets. Their coordinates and scale use the upstream
1920×1080 game-client baseline.

| AutoHSR file in `templates/` | Upstream file under `assets/template/` |
| --- | --- |
| `daily_reward.png` | [phone_menu/training_reward_gift/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/training_reward_gift/raw.png) |
| `daily_completed.png` | [phone_menu/training_reward_completed/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/training_reward_completed/raw.png) |
| `daily_tab.png` | [guide/daily_training/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/guide/daily_training/raw.png) |
| `survival_tab.png` | [guide/survival_index/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/guide/survival_index/raw.png) |
| `world_character.png` | [normal_world/ui_icon_01/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/normal_world/ui_icon_01/raw.png) |
| `count_minus.png` | [challenge_mission/battle_times_minus/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/challenge_mission/battle_times_minus/raw.png) |
| `phone_guide.png` | [phone_menu/phone_menu_item_11_interastral_guide/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/phone_menu_item_11_interastral_guide/raw.png) |
| `phone_mail.png` | [phone_menu/phone_menu_item_24_email/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/phone_menu_item_24_email/raw.png) |
| `phone_assignments.png` | [phone_menu/phone_menu_item_03_assignments/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/phone_menu_item_03_assignments/raw.png) |
| `phone_battlepass.png` | [phone_menu/phone_menu_item_08_nameless_honor/raw.png](https://github.com/OneDragon-Anything/StarRailOneDragon/blob/1ffd7e082c38bcdb559d2c0a194191ae21514ef0/assets/template/phone_menu/phone_menu_item_08_nameless_honor/raw.png) |

`templates/survival_tab_base.png` is a 2026-10-24 derivative of the above
`survival_tab.png`, cropped at `(5, 30, 65, 66)` (right/bottom exclusive).
It excludes the upper notification badge while retaining the original 1920px
baseline. Source hash and crop are recorded in `survival_tab_base.json`.

## StarRailCopilot

Source: [LmeSzinc/StarRailCopilot](https://github.com/LmeSzinc/StarRailCopilot)
and its contributors. License: GPL-3.0; the unmodified upstream license is saved
as [upstream/StarRailCopilot-LICENSE](upstream/StarRailCopilot-LICENSE).

Retrieved 2026-10-11 from `master`, whose head at retrieval was
`e2c7f0894fdea737805becbe02809ff01f47068e`. Original source PNGs and the coordinate
declarations are retained under `upstream/`. The following derivatives were
modified by AutoHSR on 2026-10-11: crop the declared `area` from the 1280×720
source, then resize by 1.5 using Pillow bicubic interpolation to the 1920×1080
baseline. Rectangle bounds are `(left, top, right, bottom)`, with right/bottom
exclusive; output dimensions are rounded to integers.

| AutoHSR file in `templates/` | Original source | Crop area | Result |
| --- | --- | --- | --- |
| `auto_anchor.png` | [COMBAT_AUTO.png](https://github.com/LmeSzinc/StarRailCopilot/blob/e2c7f0894fdea737805becbe02809ff01f47068e/assets/share/combat/state/COMBAT_AUTO.png) | `(1113, 22, 1183, 58)` | 105×54 |
| `battle_pause.png` | [COMBAT_PAUSE.png](https://github.com/LmeSzinc/StarRailCopilot/blob/e2c7f0894fdea737805becbe02809ff01f47068e/assets/share/combat/state/COMBAT_PAUSE.png) | `(1218, 27, 1245, 53)` | 40×39 |

Crop declarations are from
[tasks/combat/assets/assets_combat_state.py](https://github.com/LmeSzinc/StarRailCopilot/blob/e2c7f0894fdea737805becbe02809ff01f47068e/tasks/combat/assets/assets_combat_state.py),
saved locally as [upstream/assets_combat_state.py](upstream/assets_combat_state.py).
The full 1280×720 source canvases are kept for reproduction and are not used as
matching templates. The automatic-battle template locates the control; the
workflow checks its visible border independently before deciding its state.

## OCR and design reference

`templates/daily_activity_badge.png` was sampled locally on 2026-10-11
from the game's daily training page. The captured 3840×2160 image was resized
to 1920×1080, then cropped at `(302, 268, 353, 326)`. It includes only the
activity emblem and no account identifier. It is used to locate the current
activity value independently of the milestone labels. Game artwork belongs
to its respective rights holder.

OCR models can be read from the user's existing BetterGI installation. The
PaddleOCR models there originate from
[PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR), converted using
[Paddle2ONNX](https://github.com/PaddlePaddle/Paddle2ONNX); both upstream projects
use Apache-2.0. Those external model files are not bundled here. Preserve their
upstream notices when redistributing models.

[BetterGI](https://github.com/babalae/better-genshin-impact) is the design
reference for the screenshot, recognition, and simulated-input architecture.
No BetterGI game-specific templates or trained game-specific models are copied
into this resource directory.

The foreground log layout introduced on 2026-10-25 also references BetterGI's
[`MaskWindowConfig.cs`](https://github.com/babalae/better-genshin-impact/blob/4d42b8bac7f7665254593f70b97b19a9e09b8586/BetterGenshinImpact/Core/Config/MaskWindowConfig.cs)
and [`MaskWindow.xaml`](https://github.com/babalae/better-genshin-impact/blob/4d42b8bac7f7665254593f70b97b19a9e09b8586/BetterGenshinImpact/View/MaskWindow.xaml):
transparent lower-left status/log regions at the 1920×1080 baseline, timestamps,
severity labels, light gray text and a dark shadow. Rendering and game-capture
exclusion are implemented locally in `autohsr/overlay_native.py`.
The display-event queue and acceptance harness were adapted from Henry's
AutoZZZ project, also GPL-3.0-only; no BetterGI executable, artwork or model is
bundled for this display.

`templates/daily_synthesis_snack.png` was cropped on 2026-10-25 from the user's
clean snack-icon screenshot at `(25, 28, 196, 202)` and resized to 86×87 for recipe
selection. It excludes inventory counts and account identifiers. The source
hash and transform are in `daily_synthesis_snack.json`; game artwork belongs
to its rights holder. Recipe text, single-item quantity, ingredient balances,
daily task and post-craft inventory are checked independently of this image.

## Differential Universe local samples

The following recognition templates were cropped locally on 2026-10-18 from
the Simplified Chinese Star Rail client during Differential Universe development:
`templates/du_difficulty_i.png`, `templates/du_enemy_target.png`,
`templates/du_field_enemy.png`, and `templates/du_field_enemy_2.png` through
`templates/du_field_enemy_5.png`. They contain the difficulty-I control, an
enemy target indicator, or visible enemy artwork at sampled poses and views.
Original gameplay evidence remains in the ignored local `runs/` directory;
these recognition crops do not include account identifiers. Game artwork and
interface elements belong to their respective rights holders. These are local
gameplay samples, not copies of the upstream template libraries listed above.
Their presence does not establish successful combat entry or a completed run;
development is paused pending the user's guide.

## Daily dungeon catalogue and local recognition samples

`dungeons.json` records mission labels and map labels observed in the Simplified
Chinese 4.6.0 client on 2026-10-20. The 104 entries were bound to visible entry
buttons in locally captured Survival Index pages, with native-resolution OCR
and a small set of exact, sample-backed OCR aliases. No upstream mission data
file was copied. Account identifiers and player nicknames are not included.

`autohsr/tests/fixtures/dungeons/guide_rows.json` preserves list-region OCR and
source-image hashes for 63 local observations. `cavern_refill_off.png` contains
only the observed refill-switch region from a local cavern challenge page.
Original screenshots remain in ignored local `runs/` directories. Game labels
and interface pixels belong to their respective rights holders. Catalogue
coverage is separate from actual combat validation recorded in `VALIDATION.md`.

`planar_support_badge.png` and `planar_friend_slot4.png` are tiny native-resolution
crops of the support badge and numbered selected-slot flag from the same local
client. Their source hash and crop rectangles are in `planar_support.json`;
these crops contain no account identifiers or player nicknames.

`templates/planar_attack_mouse.png` is a local 2026-10-20 crop of the mouse-left
hint beside the field normal-attack control, resized to the 1920px template
baseline. Its JSON sidecar records the source hash and rectangle. It is used
only after this run has started planar extraction and reserved its cost; it
does not enable general Differential Universe movement or gameplay.

`du_guide_tab.png` is a crop of the 4.6 guide's 旷宇纷争 tab from the local
2026-10-20 catalogue capture. `du_attack_mouse.png` derives from the existing
mouse-hint crop with an alpha mask excluding the changing 3-D background;
its JSON sidecar records that derivation. `autohsr/tests/fixtures/du_runtime/`
contains four tiny mouse-hint crops and source hashes, without account data.

`du_random_gate.png` contains the eyes and nose of the pink 随意门 observed
in the same local client. Its source hash and crop rectangle are recorded in
the adjacent JSON. The `du_runtime/gate_*.png` fixtures preserve distant and
near views plus a neon-building negative, resized and blanked outside their
field regions to exclude account identifiers. Their provenance is recorded
in `gate_samples.json`. These landmarks authorize bounded navigation only;
interaction still requires the live OCR 随意门 prompt.

`du_battle_pause.png` and `du_auto_anchor.png` are tightly bounded control
glyphs from the local 4.6 Differential Universe battle. Their sidecars record
source hashes and rectangles. `du_runtime/battle_controls_*.png` contains only
the corresponding toolbar region; `battle_controls.json` records provenance.
The grayscale off-state test is a derived color-classification test, not a
claim that an actual off-state was captured.

`du_difficulty_i_idle.png` isolates the difficulty I glyph from a local setup
page. `du_event_next.png` is the small gold dialogue continuation arrow
from the event page. Their JSON sidecars record source hashes and crop rectangles.
`du_runtime/event_next_*.png` preserves normal and hover states; its JSON manifest
records provenance. Matching excludes the cursor-covered bottom-right quadrant. `du_runtime/header_*.png` contains only the top-left field HUD
strip or the corresponding reward-page region; `field_headers.json` records
provenance. These crops contain no account identifiers or player names.


`du_station_combat.png` is the battle station's sword glyph from the local
4.6 client; its JSON sidecar records the source hash and crop rectangle.
`du_runtime/attack_ring_*.png` keeps only the world region needed to distinguish
an attack-range reticle from open gate eyes and the character's floating emoji.
All HUD/account regions are blanked; `attack_rings.json` records source hashes.

`models/du_target.onnx` is a locally trained YOLO11n derivative from the official
Ultralytics pretrained asset. It is distributed under AGPL-3.0 with its license,
hash, evaluation limits and training provenance in `models/`. Training imagery
remains local under ignored `runs/`; training images have identifiers masked.

The 2026-10-24 gate fit retains the preceding split and negative examples and
adds three reviewed night exits with avatar occlusion plus 36 brightness
variants, all in training. The three masked `du_runtime/night_exit_*.png`
fixtures retain source hashes, reviewed boxes, and non-identifier OCR. They
are training replays, not held-out accuracy or independent-run evidence.
The runtime threshold remains 0.55; metadata records the selected checkpoint
and unchanged held-out CPU evaluation. The model remains AGPL-3.0.

`du_interaction_f.png`, `du_card_crest.png` and `du_boss_head.png` are local
2026-10-21 crops of the F interaction hint, world event-card ornament, and visible
boss upper body. Their JSON sidecars identify source hashes and crop rectangles.
They supply stop signals or bearings; they never establish a cleared room or
authorize an attack without its actual range reticle. `visual_targets.json`
records the masked card, interaction and detector regression fixtures.

`du_runtime/rewards_*.png` are local 2026-10-21 reward-page regression frames,
scaled with the bottom account identifier strip blanked. `reward_pages.json`
records source hashes and OCR metadata. The unearned-avatar negative fixture
ensures future red artwork is not treated as a notification or a received reward.
`du_cassette_zero.png` and `du_runtime/moon_balance_zero.png` preserve only the
numeric cassette-balance region; their sidecars record crop provenance. The zero
glyph is a fallback when OCR omits zero and never authorizes a paid unlock.

`du_runtime/blessing_missing_title.png` is a native-resolution title-strip crop
for a two-character blessing missed by full-screen OCR. Its JSON sidecar records
the source hash and crop. No account or player identifiers are included.

`du_runtime/card_distant.png` is a masked 960px world-card frame from the local
2026-10-21 client. Its provenance sidecar records the source hash; the sample
regresses a distant 70px-high card excluded by the former strict size threshold.

`du_runtime/card_avatar_occlusion.png` preserves the partial purple card frame,
pale face and nearby pink gate used to distinguish the card from the gate while
it overlaps the avatar. Its provenance sidecar records the local source hash;
account and player-name regions are masked.

`du_runtime/gate_sleep_far.png` and `gate_sleep_near.png` are masked local
2026-10-21 frames. `sleep_gate_states.json` records source hashes. They regress
the closed-eye/front-versus-back ambiguity at far and near distances; far
anti-aliased eyelids require native-resolution inspection before back matching.

`du_runtime/card_cyan_frame.png` is the masked local abnormal-event card
「归来的岁阳」 with its bright cyan frame, pale eye and purple ornament.
Its sidecar records the source hash. This card does not have dark frame rails.

`du_runtime/cards_reward_gold.png` is a masked local reward-region scene with a
warm purple/gold card, a gold card and a locked pink gate. The sidecar records
the source hash and positive centers; the pink gate is a negative target.

`models/du_cards.onnx` is a locally trained YOLO11n Card-only derivative, under
the same included AGPL-3.0 terms. `models/du_cards.json` and the model README record
its hash, training provenance and limited native evaluation. Its raw training
captures and generated scenes remain under ignored runs/ with identifiers masked.
`du_runtime/cards_poster_negative.png` is a masked held-out facade-view regression;
its sidecar records provenance. The learned card model must reject that artwork.

`du_runtime/attack_ring_5.png` through `attack_ring_8.png` are masked, resized
local 2026-10-21 field captures. Their source hashes are in `attack_rings.json`.
They distinguish a real attack glow from blonde hair and orange shop numerals.
`attack_ring_9.png` and `attack_ring_10.png` also reject sleeping-door gold trim.

`templates/du_aurumaton_roof.png` is an observed boss-roof crop used only for a
coarse approach bearing. Its sidecar and `du_runtime/boss_aurumaton.json` record
source hashes. Two masked field frames test the bearing at different headings;
the roof never establishes attack range.

`templates/du_aurumaton_side.png` adds an observed side chest crop with a source
hash in its sidecar. `du_runtime/boss_aurumaton_2.png` is a masked native frame.
`models/du_enemies.onnx` is a locally trained, Enemy-only YOLO11n derivative
under the included AGPL-3.0 terms. Its sidecar records the small local dataset,
CPU checkpoint selection, missed occlusion sample and scope limitation.

`du_runtime/preset_list.png`, `preset_enabled.png` and `periodic_setup.png`
are masked, resized local 2026-10-21 client captures. Their JSON sidecars retain
OCR boxes and source hashes to verify named preset activation and mode isolation.

The 2026-10-22 `du_enemies.onnx` update adds the observed Senior Staff: Team
Leader family, retaining Aurumaton training examples. Its sidecar records the
combined fit and strict CPU evaluation. `du_runtime/boss_ipc_front.png`,
`boss_ipc_clear.png` and `boss_ipc_occluded.png` are masked local field frames;
their sidecars contain reviewed boxes and source hashes. The included AGPL-3.0
terms also apply to the updated Ultralytics derivative.

`du_runtime/blessing_discard.png` is a masked 2026-10-22 native one-star
blessing trade page. The sidecar preserves its source hash and OCR boxes.

The further 2026-10-22 enemy model update adds the observed 正阳狮鹫 appearance.
`du_runtime/boss_griffin_clear.png`, `boss_griffin_center.png` and
`boss_griffin_occluded.png` are masked local field captures. Their sidecars
preserve source hashes and reviewed bounding boxes. Training and calibration
remain local; included AGPL-3.0 terms apply to this derivative.

`du_runtime/attack_ring_11.png` preserves a genuine, dimly filled range ring
near the left edge after a party switch. `attack_rings.json` records provenance.
`du_runtime/enemy_avatar_negative.png` preserves a central avatar in front of a
wall; the sidecar records its source hash. Identifiers are masked in both.

`du_runtime/gate_rest_distant.png` is a masked local rest-area capture where
the learned door score dips below its normal threshold. Its source hash is in
the sidecar; a spatially matching eye feature corroborates the lower-score box.

The fourth enemy model fit adds 金血忆灵·裁定 and retains earlier families.
`du_runtime/boss_arbiter_clear.png`, `boss_arbiter_center.png` and
`boss_arbiter_occluded.png` are masked local captures with reviewed-box sidecars
and source hashes. The progress-banner sample checks bearing only; its imperfect
full-body box remains a strict evaluation miss. Included AGPL-3.0 terms apply.

The fifth enemy fit adds 乐变化天人. Masked local `du_runtime/enemy_celestial_clear.png`,
`enemy_celestial_center.png` and `enemy_celestial_spawn.png` have reviewed-box
sidecars with source hashes. The bright spawn frame remains a known detector
miss; it is not counted as a successful localization. AGPL-3.0 terms apply.

The sixth enemy fit adds 承露天人. Masked local `du_runtime/enemy_dew_clear.png`,
`enemy_dew_center.png` and `enemy_dew_front.png` have reviewed-box sidecars and
source hashes. `models/du_enemies_fallback.onnx` retains the preceding five-
appearance fit solely for missing primary bearings. Both model sidecars retain
their hashes, provenance, limitations and included AGPL-3.0 terms.

`du_runtime/gate_awake_ornament.png` is a masked local capture of a cleared
boss room, with an awake exit and distant scenery that the enemy model can
misidentify. Its sidecar records the source hash. It tests exit-state priority.

`du_runtime/attack_ring_mouse_animation.png` is a masked local field capture
with a genuine attack ring and enemy information bar while the mouse-hint
template is changing. The sidecar preserves source hash and masked OCR tokens.

`du_runtime/attack_ring_12.png` through `attack_ring_14.png` preserve three
masked native frames of the 乐变化天人 range ring with weak circle-edge votes.
Their source hashes are recorded in `attack_rings.json`.

`du_runtime/blessing_title_variant_0.png` and `blessing_title_variant_1.png`
are masked local captures of unchanged blessing cards during reversible previews.
They exercise a two-character title whose first character varies in OCR.

`du_runtime/gallery_home.png`, `gallery_category.png` and `gallery_milestones.png`
are masked local captures of earned gallery reward navigation. Their sidecars
retain source hashes and OCR tokens.

`du_runtime/companion_ring_candidate.png` is a masked native entrance frame.
Its companion's expression meets the low-level circle appearance checks but
lacks an enemy information bar, so it must not suppress the forward approach.
Its sidecar records the source hash and OCR tokens.

The seventh enemy fit adds the observed winged elite 波涛夫人, subsequently
identified from the native enemy bar. `du_runtime/enemy_winged_front.png`, `enemy_winged_center.png`,
`enemy_winged_side.png` and `enemy_winged_hud.png` are masked local captures with
reviewed boxes and source hashes. Nearby samples only establish local calibration;
the included AGPL-3.0 terms apply to the model.

`du_runtime/world_card_title_130.png` and `world_card_title_131.png` are masked
native reward-room entrance frames. Their OCR sidecars retain source hashes.
They distinguish the fixed 奖励 progress header from the world-card title
商店街一番战, which also supplies a coarse approach bearing.

`templates/du_event_option_star.png` is a local native crop of the selectable
event-row star at a 1920x1080 baseline. Its sidecar records the source hash and
crop. `du_runtime/event_star_choices.png` is a masked native 神秘链接 choice
screen with three stars and OCR tokens; its sidecar records the source hash.

`du_runtime/attack_ring_15.png` through `attack_ring_17.png` are masked native
波涛夫人 frames where the attack ring lies inside a larger bright eye rim.
Their source hashes and expected presence are recorded in `attack_rings.json`.

`du_runtime/beacon_close_variant.png` is a masked native deployed-beacon
overlay where OCR reads 白 as 日 in the bottom close hint. Its sidecar
retains the source hash and OCR tokens for the observed regression.

`du_runtime/station_transform.png` is a masked native station-card target
selector for the observed combat-to-event/anomaly transformation. Its sidecar
records the source hash and OCR tokens.

`templates/du_range_ring.png` is a local crop of the native hollow attack
marker, represented as red excess for shape matching. Its sidecar records the
source hash, baseline crop and calibration limit. Masked native nearby views
`du_runtime/attack_ring_18.png` through `attack_ring_20.png` retain source
hashes in `attack_rings.json`.

`du_runtime/blessing_title_glow_0.png` and `blessing_title_glow_1.png`
are masked native previews of unchanged blessing titles with different card
glow and short-name OCR. Their sidecars record the source hashes.

`du_runtime/attack_ring_21.png` is a masked native negative containing an
orange numeral balloon and a real distant enemy bar. Its source hash and
negative expectation are recorded in `attack_rings.json`.

`du_runtime/station_beacon_target.png` is a masked native single-card beacon
selector. Its sidecar records the source hash and OCR tokens; the instruction
also names an automatically removed region that is not the selected target.

`du_runtime/gate_awake_partial_hud.png` and `gate_awake_partial_side.png`
are masked native awake doors with one complete eye visible. The masked
`gate_banner_negative.png` is the nearby blue banner used as a negative.
Their sidecars record source hashes.

`du_runtime/gate_back_near_clipped.png` is a masked native near-door back
view, with its upper panel clipped by the screen. Its sidecar records the
source hash.

`du_runtime/forge_interaction.png` and `forge_console_menu.png` are masked
native views of the named F prompt and weighted-curio assembly menu. Their
sidecars record source hashes and OCR tokens.

`du_runtime/card_blue_forge_distant.png` and `card_blue_forge_close.png`
are masked maintenance-card calibration views. `card_blue_banner_negative.png`
and `card_boss_console_negative.png` are masked non-card views. Their sidecars
record source hashes and the local calibration limit. The card model was
incrementally fitted on separately grouped training views and train-only
composites; raw images and PyTorch checkpoints remain under ignored `runs/`.

`templates/du_guide_tab.png` retains the stable planet glyph, excluding its
notification badge and the lower edge covered by the guide's content panel.
Its sidecar records the source and derived crop. The masked native
`du_runtime/guide_universe_tab_clear.png` verifies entry with no notification.

`du_runtime/card_edge_world_title.png` is a masked native edge-on card with
a readable floating region qualifier. Its sidecar retains OCR and source hashes;
the caption supplies a bearing and does not authorize F.

`du_runtime/curio_plane_description.png` is a masked native curio selection
whose descriptive prose mentions planes. Its sidecar retains OCR and source
hashes; only the actual field progress header blocks reward selection.

`du_runtime/equation_queue_24.png` and `equation_queue_27.png` are masked
consecutive equation-expansion overlays. Their distinct names identify progress
even when the shared overlay heading stays unchanged; sidecars retain source
hashes and OCR tokens.

`du_runtime/attack_ring_22.png` through `attack_ring_25.png` are masked native
door-link streaks, companion hats and a genuine attack UI ring. Their source
hashes and positive/negative labels are recorded in `attack_rings.json`.

`du_runtime/attack_ring_26.png` is a masked native genuine range marker near
the party sidebar. Its source hash and positive label are in the same manifest.

`du_runtime/reward_chest_interaction.png` is a masked native free rich-loot
chest F prompt. Its sidecar records OCR and source hashes.

`du_runtime/random_two_{target,remaining,loss,gain}.png` are masked native
screens from the free two-card same-level random conversion. They document
the unchanged second instruction and separate one-card loss/gain receipts.
Sidecars retain OCR tokens and source hashes.

`du_blessing_recommended.png` is cropped from the user's supplied green
blessing recommendation icon. Its metadata retains the source hash and crop.
`du_runtime/blessing_recommended_{right,two,none}.png` are masked native
three-card selections with one, two and zero marked cards, covering gray,
blue and gold cards. Sidecars record marked columns, OCR and source hashes.

`du_runtime/late_gate_interaction.png` is a masked native awake-gate F prompt
which appeared on the last observation of a timed navigation attempt. Its
sidecar retains OCR and source hashes.

`du_runtime/any_region_beacon.png` is a masked native free single-beacon
selector using the written quantity “一个” and no source-region restriction.
Its sidecar records OCR and source hashes.

`du_runtime/forge_plus_three.png` is a masked native free single-card forge
upgrade selector with a +3 level effect. Its sidecar retains OCR and source
hashes.

`du_runtime/awake_gate_with_poster.png` is a masked native reward-room capture
resized to 1920×1080. The distant street poster is a known false Card detection;
the awake gate must retain navigation priority. Its sidecar records source and
fixture hashes and dimensions. Game artwork remains the property of HoYoverse.

`du_runtime/any_region_upgrade.png` is a masked native single-card +2 upgrade
selector without a source-region restriction. Its sidecar retains native OCR
and source/fixture hashes; the right-hand card preview is level 3.

`du_runtime/upgrade_negative_beacon.png` is a masked native single-card upgrade
selector combining a +2 level bonus with a random negative beacon. Its sidecar
retains native OCR and source/fixture hashes.

`du_runtime/pink_brush_false_gate.png`, `brush_and_cafe_sign.png`, and
`card_with_advertisement.png` are masked native cafeteria captures used to
regress decorative brushes, wall advertisements, and the actual TV event card.
Their sidecars retain hashes. They are from the incremental training episode
and are calibration/regression examples, not held-out accuracy evidence.
# Additional local calibration, 2026-10-23

The existing AGPL-3.0 YOLO11n door derivative was fine-tuned on three locally
reviewed console-occluded door screenshots and 36 brightness variants. Raw
captures, labels and checkpoints remain local under ignored `runs/`. The
packaged model retains the license and upstream provenance in its metadata.

`two_cards_at_entry.png`, `card_green_edge_on.png`, and
`card_green_edge_on_pitched.png` are masked local native room captures.
The green event card remains an interaction target when viewed edge-on;
sidecars record reviewed boxes and hashes. These are incremental training and
regression samples, not independent held-out evaluation images.

The card derivative was incrementally fine-tuned on these four native views
and 48 brightness variants, retaining the earlier training corpus and original
held-out split. The packaged last checkpoint retains AGPL-3.0 licensing;
model hashes and CPU ONNX evaluation are recorded in `assets/models/du_cards.json`.

`du_runtime/snow_owl_recruitment.png` is a masked native Snow Owl mask
recruitment screen. Its sidecar retains observed OCR and source/fixture hashes.

`du_runtime/snow_owl_optimization.png` is a masked native Snow Owl station-card
optimization selector, with the same observed OCR/hash provenance convention.

`du_runtime/snow_owl_recruitment_loading.png` captures the native recruitment
animation before the three region titles appear, with identifiers masked.

## Planar preparation and gallery controls, 2026-10-23

`planar_preparation`, `planar_preset_list`, `planar_preset_enabled`,
`planar_mixed_payment`, `planar_disabled_auto`, and `planar_disabled_stage`
under `autohsr/tests/fixtures/du_runtime/` are masked native client captures
for named presets, separate stamina/immersifier prices, and disabled battle
controls. Their JSON sidecars retain source/fixture hashes and observed OCR.

The `gallery_*` fixtures added with this update cover the offscreen reward
pointer, five reward-category views, the collection-only weighted-curio view,
and five corresponding milestone dialogs, including icon-only claimed rows.
Account identifiers are masked and omitted from sidecar OCR. These captures
are regression examples, not independent completion evidence.

`count_plus`, `planar_stamina_cost`, `planar_stamina_cost_single`,
`planar_immersifier_cost`, `planar_auto_dim`, `planar_auto_dim_transition`,
`planar_auto_dim_stage`, and `du_gallery_claimed` in `assets/templates/`
are small native UI crops. Their sidecars retain source hashes, original
dimensions, normalized crop bounds, and the 1920-pixel matching baseline.
Raw captures stay in ignored local `runs/`. All game artwork belongs to
HoYoverse and is included solely for client UI recognition and regression.

`du_runtime/helper_occluded_blessing.png` is a native client capture occluded
by a closing AutoHSR inspection window. The fixture masks account identifiers
and local configuration paths; its sidecar omits those OCR tokens and retains
source/fixture hashes. It tests rejecting helper UI content before game-option
recognition. It is not independent completion evidence.

`du_runtime/optional_device_blocks_gate.png` is a native wealth-room capture
with account identifiers masked. Its sidecar retains source/fixture hashes
and observed OCR excluding identifiers. It tests recognizing a live optional
machine prompt for bounded avoidance, without authorizing game interaction
or spending. Game artwork remains the property of HoYoverse.

`du_runtime/chaos_box_blocks_combat.png` is a native combat-room capture of
an optional chaos medicine box obstructing the entrance path. Identifiers are
masked; the sidecar retains source/fixture hashes and non-identifier OCR. It
tests shared bounded avoidance and early re-reading of unknown F prompts,
without authorizing the box's negative-curio exchange. Artwork is HoYoverse's.

`du_runtime/rest_entry_fade.png` and `rest_entry_ready.png` are masked native
rest-room entrance captures before and after the same fade. They test waiting
for the fixed HUD to recover without rejecting a fully loaded night scene.
`du_runtime/rewards_home_intro.png` is a masked native home entrance frame
whose reward panels are still sliding in from offscreen. It tests withholding
the no-rewards conclusion until all four anchors are complete and stable.
Their sidecars retain hashes and non-identifier OCR; these are local
regression examples, not independent completion evidence. Artwork is HoYoverse's.

`du_runtime/card_unqualified_caption.png` is a masked native edge-on world
event card with a bare floating Chinese title. The sidecar retains source and
fixture hashes and non-identifier OCR. It tests matching a weak learned card
body to the title above it without lowering the normal detector threshold or
authorizing F from a title. It is a local regression example, not independent
completion evidence. Game artwork remains HoYoverse's.

`du_runtime/growing_beacon_target.png` is a masked native station-card
selector opened by a growing curio. Its sidecar preserves source/fixture
hashes and OCR excluding account identifiers. It tests the complete immediate
random-beacon reward and later count-based upgrade instruction. It is local
regression evidence, not an independent completion. Artwork is HoYoverse's.

`du_enemies_recovery.onnx` is a YOLO11n fit derived from the existing
seven-appearance checkpoint, adding three reviewed positive frames, three
negative frames, and 240 generated training scenes from the same local trial.
The existing validation/test split is retained. It is limited to recovery
after an initial missed attack or explicit resumed-field recovery; the
existing runtime models remain unchanged.
Training uses the existing isolated PyTorch/Ultralytics environment and the
same AGPL-3.0 model license. `enemy_pair_front.png`, `enemy_yellow_side.png`,
and `enemy_corner_negative.png` are masked training-frame replays with source
hashes and reviewed boxes in sidecars, not independent accuracy samples.
Game artwork remains the property of HoYoverse.

`du_runtime/event_f_blue_background` is a locally observed field interaction
with a blue event card. Its 1920-pixel copy masks the identifier strip and
retains source hashes and non-identifier OCR. It verifies the circular F key
independently of the scenery outside the button. Game artwork remains the
property of HoYoverse.

`du_runtime/red_tinted_attack_circle` is a locally observed attack-range UI
phase with a red centre and no white core. The 1920-pixel copy masks bottom
identifiers; its sidecar retains source hashes and non-identifier OCR. Game
artwork remains the property of HoYoverse.

`du_runtime/rest_revival_awake_exit` and `rest_forge_awake_exit` are locally
observed rest-room prompts with a visibly awake exit. Their 1920-pixel copies
mask identifiers and retain source hashes and non-identifier OCR. They verify
bounded travel past optional devices, never device use. Game artwork remains
the property of HoYoverse.

`du_runtime/coin_counter_prompt` and `coin_counter_menu` are locally observed
4.6 wealth-room frames. The menu was opened manually for inspection without
executing a trade. The 1920-pixel copies mask bottom identifiers; sidecars
retain source hashes and non-identifier OCR. They verify an optional-device
detour and an Escape-only menu close, not transaction behavior or independent
completion. Game artwork remains the property of HoYoverse.

`du_runtime/entry_trigger_target.png` is a masked native station-card selector
for an enter-region curio with a finite activation lifetime. Source/fixture
hashes and non-identifier OCR are retained in its sidecar. It tests separating
the current target count from the later destruction counter, and is a local
regression sample rather than independent completion evidence.

`du_runtime/side_attack_ring.png` is a masked native combat-room frame with
a genuine range marker on a side enemy while the avatar faces the locked
gate. Its sidecar preserves source/fixture hashes and non-identifier OCR.
It tests corrective aiming after a missed initial click and the bounded use
of a range bearing just verified by the held-input watcher. It is local
regression evidence, not an independent completion. Artwork is HoYoverse's.

`du_runtime/beacon_reroll_target.png` is a masked native station-card selector
requiring a card with existing beacons. Its sidecar retains source/fixture
hashes and OCR excluding the account identifier. It tests the full reroll
instruction and named beacon descriptions in the selected-card panel. It is
local regression evidence, not an independent completion.

`du_runtime/supply_room_banner_overlap.png` is a masked native daily-reset
login-supply popup over an active room-entry banner. Source/fixture hashes
and non-identifier OCR are preserved in its sidecar. It tests bounded
observation retries while the remaining-day text is obscured, retaining the
same owned-supply and free-claim checks. Game artwork belongs to HoYoverse.

`gate_tracking_reference.png`, `gate_tracking_occluded.png`, and
`gate_tracking_wrong_view.png` are masked native nearby frames used to test
optical-flow continuity of an already detected gate through avatar occlusion.
Their sidecars retain source/fixture hashes and the original detected box.
They are local regression views, not independent accuracy or completion
evidence. Game artwork remains the property of HoYoverse.

`phone_mail_body.png`, `mail_disabled_arrow.png`, `bp_tasks_tab.png`, and
`bp_rewards_tab.png` are narrow crops of locally observed 4.6 UI frames.
Their sidecars record source hashes, exact crops, and the 1920-pixel baseline;
notification badges are excluded from navigation glyphs. The masked native
`du_runtime/phone_mail_icon`, `mail_claimable`, `mail_claimed`, and `bp_*`
fixtures test free-claim controls, tabs, XP feedback, and notification state.
Account identifiers, phone profile details, and unnecessary mail content are
masked; sidecars retain hashes and non-identifier OCR. These are local
regression samples, not independent automation-success evidence. Game artwork
remains the property of HoYoverse.

`templates/workflow_world_phone.png` preserves the unchanged 32×29 RGBA
main-screen phone glyph from the pinned March7thAssistant source. Its SHA-256
is `39a79cc4318447516ee504e6ebb49cd335481cf6ad64ea644826fae4bb00b80e`.
The two `workflow_world` regression fixtures retain only the two HUD search
regions from historical local frames on a neutral canvas. Their manifest
records the source, transform and hashes. Game artwork belongs to HoYoverse
and its respective rights holders. [Fixed upstream glyph](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/images/screen/main.png) · [Masked fixtures](../autohsr/tests/fixtures/workflow_world/sources.json)

`upstream/March7thAssistant/daily-message/incoming_message.png` preserves the
original 154×40 title crop from moesnow and contributors at
`7cf6c6bed474539485d3b1504077ac352866829f`, upstream path
`assets/images/screen/incoming_message.png`. The 4026-byte file is unchanged.
Git blob is `c838cc3d8d39d142737f58fcfefb9fdd89a75329` and SHA-256 is
`fa493d9797805cfa4cdcb6158c19a07407777363fa7161366d567de60f04729d`.
It supports read-only message panel recognition. The upstream GPL v3 and
HoYoverse game artwork attribution apply.
[Pinned original](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/images/screen/incoming_message.png)
· [Upstream license](upstream/March7thAssistant/LICENSE)

`upstream/March7thAssistant/daily-message/unread_badge.png` preserves the
original 17×17, 1002-byte `assets/images/share/base/RedExclamationMark.png`
from the same upstream commit and contributors. Git blob is
`d7d6e225847c7a1471203b763f71d05aa1ecbc1a` and SHA-256 is
`0321342e46d3b048872733c632a6971aede10da29aea8416ef678749cb4f45f4`.
The same GPL v3 and HoYoverse attribution apply.
[Pinned original](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/images/share/base/RedExclamationMark.png)

`autohsr/tests/fixtures/daily_message_state` contains reduced evidence from
the public PC gameplay video by 绘希推_书记. The source MP4 and fixture
hashes, frame times and reductions are in the manifest. The title and badge
are the only retained original patches. Other observations are reduced to
luminance summaries and anonymous header ink counts. Game artwork remains
with HoYoverse and the footage with its respective rights holders.
[Source video](https://www.bilibili.com/video/BV1Pj421X7r1/)
· [Fixture manifest](../autohsr/tests/fixtures/daily_message_state/manifest.json)

亮背景双栏回归另从两段 4.6 时期公开 PC 录像各取五帧。夹具缩至 480×270，仅保留静态标题和 HUD 图块、匿名亮度统计与图形特征。来源、时间、转换范围、原解码帧和脱敏 PNG 的 SHA-256 见清单。视频及游戏界面归原作者、HoYoverse 和相应权利人。[亮背景夹具清单](../autohsr/tests/fixtures/daily_message_bright/manifest.json)

世界短信定位的 25×22 灰度透明气泡模板来自 4.6 时期公开 PC 录像，沿用上文来源表中的右上世界锚图标。定位夹具仅保留必要静态 HUD 和匿名统计；外来红标移入短信位置的测试为合成摆放。来源、裁剪范围、脱敏方式、哈希和权利说明见[世界短信夹具清单](../autohsr/tests/fixtures/daily_message_world/manifest.json)。

回复条淡出样本来自同一公开 P179 录像，沿用短信状态样本的 480×270 匿名亮度和静态标题转换。来源、时间、原解码帧及脱敏 PNG 的 SHA-256 和权利说明见[回复条夹具清单](../autohsr/tests/fixtures/daily_message_reply_targets/manifest.json)。

单次短信候选引用公开 P178 录像的前后帧及固定 4.6 简中数据。仅收录静态页标题、匿名几何与亮度、固定游戏字段指纹和原件哈希。固定源提交、表文件及脱敏方式见[单次回复夹具清单](../autohsr/tests/fixtures/daily_message_reply/manifest.json)。

另补同一录像系列 P179 后段的三选项、无气泡过渡和新发出气泡。沿用匿名标题和亮度转换，并记录第一条整帧漏标点与局部严格读数。来源、固定字段指纹、转换和逐帧哈希见[P179 夹具清单](../autohsr/tests/fixtures/daily_message_reply_p179/manifest.json)。

`upstream/March7thAssistant/team-calibration/configure_team.png` preserves a
single original crop from moesnow and contributors at
`7cf6c6bed474539485d3b1504077ac352866829f`. It supports read-only normal team
page identification alongside separate OCR fields. Source path, Git blob,
SHA-256, and upstream GPL v3 attribution are recorded in the
[team calibration source notes](upstream/March7thAssistant/team-calibration/README.md).
The game artwork remains the property of HoYoverse.

`du_runtime/last_area_confirm` is a locally captured final-route warning from
the 4.6 client, resized to the 1920-pixel baseline with the bottom identifier
strip masked. Its sidecar records the source hash and non-identifier OCR.
It verifies modal priority and one-shot confirmation feedback; it is not
independent completion evidence. Game artwork remains the property of HoYoverse.

The same `du_runtime/last_area_confirm.png` is also a layout/color reference for
the code-drawn desktop detail and unsaved-settings panels in `autohsr/desktop_dialogs.py`
(2026-10-29): 960×360 plate, 8px offset frame, 96px footer at the 1920px baseline.
The masked fixture SHA-256 is
`961eefc1aaf95bb3c501bb23df9e519e97e6431abd2e4ff68b92714e3cdc7dab`.
No new bitmap is extracted or bundled for this panel; the existing game font
retains its attribution above. This reference does not prove whole-screen parity.
The unsaved-settings panel has three explicit application choices; narrow work
areas stack them vertically. These are application adaptations of the reference,
not claims that the game's original two-button interaction is identical.

`du_runtime/adventure_hanu_*` are locally captured 4.6 adventure-room frames
with the bottom identifier strip masked at the 1920-pixel baseline. Their
source hashes and non-identifier OCR verify the floating NPC name separately
from the live interaction prompt, countdown, score HUD, and result exit.
These are regression samples, not independent completion evidence. Game
artwork remains the property of HoYoverse.

`du_runtime/event_five_reward_confirm` and `reward_items_fifty` /
`reward_items_twenty` are locally observed 4.6 event and item-receipt frames.
The 1920-pixel copies mask bottom identifiers; sidecars retain source hashes
and non-identifier OCR. They verify an observed reward-count bound and
receipt-content changes, not the number of independently earned rewards.
Game artwork remains the property of HoYoverse.

`du_runtime/two_random_beacons` is a locally captured 4.6 station-card
instruction, resized to 1920 pixels with the bottom identifier strip masked.
Its sidecar retains the source hash and non-identifier OCR. It verifies one
target card with two automatically attached beacons, not two selections.
Game artwork remains the property of HoYoverse.
## 2026-11-05 差分存档持久提交

参考固定March7thAssistant的`process_save_management`、`_save_completed_run`及本轮尝试状态，保留上游作者与GPL v3说明，Git blob及SHA-256见[来源清单](upstream/March7thAssistant/source.json)。[保存工作流](../autohsr/du_archive_workflow.py)与[持久记录](../autohsr/du_archive_store.py)由AutoHSR编写，继续使用既有空槽及递增命名规则，另增加当前来源核验、逐次意图、返回核实与跨运行防重复。没有移入上游坐标、默认名称、重试或输入框架。

本次没有新增或变换游戏素材、模型或真实采集；假窗口与合成页面只验证机制，自动命名及完整保存页面仍需实机验收。旧保存记录不扫描或自动迁移，范围见[说明](../docs/du-archives.md)。

# 2026-10-26 货币战争导航OCR回归

`autohsr/tests/fixtures/currency_wars_navigation.json`仅提取用户授权本地开发截图的固定导航文字、置信度与归一化框；元数据保留原样本相对标识与图像SHA-256以便本地核对。字段采用明确白名单，排除UID、昵称、资源库存和原始图像；文本事实用于界面回归。来源客户端4.6.0，日期2026-10-26；没有新增分发游戏图像，旧`du_guide_tab`与`du_interaction_f`继续使用各自既有来源记录。

`autohsr/tests/fixtures/currency_wars_standard_environment.json`来自同日用户授权开发的标准A8-40环境选择页，仅保存卡片与固定UI OCR，排除UID、账号和原始图像。来源相对标识、客户端4.6.0与原图SHA-256保存在元数据；用于完整效果、数值与卡片顺序回归，不将回放当成实时输入授权。

`autohsr/tests/fixtures/currency_wars_standard_shop.json`来自2026-10-26标准商店记录，仅保存商店标题、候选、标价与固定导航OCR，排除UID、玩家头像、余额区域及原始图像。元数据保留本地来源相对标识、日期和原图哈希；藿藿与单数字价采用已核实的局部识别，原始截图保持忽略，不分发游戏整图。

# 2026-10-28 桌面指南界面（首版）

AutoHSR桌面参考《崩坏：星穹铁道》“星际和平指南／每日实训”的信息层次和视觉语言（深色外框、浅色内容、金色菱形里程碑、任务条目），以及[AutoZZZ快捷手册界面](https://github.com/HenryTANG0520/AutoZZZ/tree/a137c1eee44ea7429d06d018bd60d47c34bed41a/autozzz)的游戏化任务组织与常驻控制思路。星铁界面的公开参考可见[HoYoLAB社区截图](https://www.hoyolab.com/article/24934874)与[每日实训截图](https://www.pushsquare.com/guides/honkai-star-rail-beginners-tips-tricks-and-how-to-play)。参考日期2026-10-28；仅作设计参考，不代表相应旧版截图中的游戏任务仍是当前规则。

首版提交`468dffe`没有下载、裁切或分发上述截图，没有新增第三方位图、游戏字体或模型。其图形由程序绘制，中文使用Windows系统字体Microsoft YaHei UI。该说明仅对应首版历史状态；后续用户要求按实际游戏素材复刻，见下节。

## 2026-10-28 指南实际素材与字体

新增`assets/ui/`中的16个静态图像与1个字体文件，用于桌面指南复刻。源画面为既有简体中文4.6.0实机截图，分别对应每日实训、生存索引与旷宇纷争；没有重新启动游戏取材。源图SHA-256、各静态裁切坐标、透明蒙版变换和输出哈希均记录于[UI sources.json](ui/sources.json)。原始整图、UID和账号信息不随素材提交。两个图标复用既有模板，原来源与许可记录继续保留。

字体为本地客户端附带的`SDK_SC_Web`，原文件名`zh-cn.ttf`，按原始字节复制；保留汉仪版权和许可元数据，不纳入原创代码GPL声明。游戏图像同样归相应游戏权利人；来源事实与署名不构成再许可授权。详情及复现脚本见[UI素材说明](ui/README.md)。代码重绘指南外框、纹样、卡片、进度与按钮，没有迁入AutoZZZ或March7thAssistant的GUI源码。

2026-10-29重制其中三个页签图标、活跃标记与任务卡水印。仍使用既有每日实训、旷宇纷争两张原图，避开指针与放射纹背景，保留连续透明度、图标渐变及原比例；五项来源、裁切与输出哈希更新在同一清单中。没有新增来源或素材文件数，未分发原始画面；游戏美术的权利归属和许可边界不变。

同日新增`card-frame.png`，从同一每日实训源图提取纸面地图纹样、金色点线与底部撕口。原状态栏、任务、数值和奖励区域的RGB及透明度一并清零，外缘按亮度提取透明度；没有保留藏在透明通道下的原任务文字。清单记录288×372裁切、蒙版与哈希；不透明静态区域保留源像素。未采集新游戏画面，权利归属仍同上。

## 2026-10-28 March7thAssistant货币战争策略适配

标准模式“默认／阿格莱雅／希儿”的购买、成长和补空位偏好参考March7thAssistant固定提交`7cf6c6bed474539485d3b1504077ac352866829f`，作者moesnow及其贡献者，上游GPL v3。完整许可、Git blob与哈希清单及改写范围见[来源说明](upstream/March7thAssistant/README.md)。本次界面只接入对应的本次新局策略选择，接续继续使用已记录策略；没有迁入上游GUI、固定输入或图片，未将离线通过写作实机通过。

## 2026-10-29 生存索引列表素材

新增`assets/ui/survival/`的104幅静态图像，从2026-10-20既有CN 4.6.0生存索引目录采集画面裁出对应掉落图标或首领徽章。分类、名称和地点与现有104条目录逐项绑定；[来源清单](ui/survival/sources.json)记录原图相对标识、SHA-256、1920×1080坐标、裁切变换及输出哈希。排除完整画面、UID、玩家头像、余额和无关个人信息，没有启动游戏取新图。游戏美术归HoYoverse及相应权利人，不纳入原创代码GPL声明；来源记录不代表额外再许可。仅用于桌面目录展示，不能作为当前账号已解锁或已通关的证据。

同日从同批归档画面补入21个地区、命途、属性标题图标。对应64条副本的分组按同屏标题及相邻滚动画面的重叠条目核对；[分组清单](ui/survival/groups.json)保留每组图标的裁切、原图与OCR记录哈希、输出哈希，以及条目归属的原始帧标识。没有采集新画面、复制账号状态或变更执行目录；图像的权利归属与上述许可边界相同。

## 2026-10-29 March7thAssistant装备识别参考

后端装备阶段从同一固定提交引入18幅`assets/images/share/aglaea/`原始PNG，作者moesnow及其贡献者，遵循所附上游GPL v3；游戏美术与名称仍归其权利人。文件未经裁切、缩放或重编码，逐项原路径、Git blob、SHA-256和字节数见[装备来源清单](upstream/March7thAssistant/equipment/sources.json)，本地标识、用途及原生变体见[装备参考说明](upstream/March7thAssistant/equipment/README.md)。完整上游许可继续保留于[LICENSE](upstream/March7thAssistant/LICENSE)。

这些图用于仓库、角色槽和当前推荐配方的本地识别。已校准14种可穿戴装备；六种工具另经专用数量识别与实际效果协议适配，范围见下节。没有复制上游输入实现，也没有将界面打开、材料消失、合成测试或离线模板回放写作实机穿戴成功；现有UI素材署名和原生4.6装备参考保持不变。

## 2026-10-29 货币战争工具原生变体与次数校准

`assets/templates/currency_wrench2_native_4_6.png`从既有本地4.6画面`146-boss-ready-loot-cleared.png`静态裁出75×70金色扳手图标，裁切坐标、原图及原清单SHA-256、输出哈希记录在[消耗品来源清单](currency-consumables/sources.json)。图标排除次数、UID、账号和完整画面；原始截图保持忽略，没有启动游戏取新图。游戏美术归HoYoverse及相应权利人，不纳入原创代码GPL声明，来源不授予额外再许可。

工具初始参考继续使用上一节固定提交的18幅上游原PNG及完整GPL v3许可，没有改写这些字节。六种工具的命名核心优先思路改写为本项目Context、账号／输入代次、库存及完整角色效果核验；上游来源与具体适配文件继续记录于[source.json](upstream/March7thAssistant/source.json)。三份既有画面及五份工具教程仅记录脱离账号的局部事实、原哈希与本地标识；没有分发整图、更新模型或建立独立实机验收集。识别与执行边界见[工具说明](currency-consumables/README.md)。

## 2026-10-29 货币战争补给刷新控件

`assets/templates/currency_supply_refresh_4_6.png`从既有4.6补给画面静态裁出72×71的Q控件，排除次数、UID与完整画面；原图、原清单、坐标、变换、SHA-256及三份旧补给控件校准记录见[补给来源清单](currency-supply/sources.json)。游戏美术归HoYoverse及相应权利人，不纳入原创代码GPL声明，来源不授予额外再许可。没有启动游戏取材、公开整图或训练模型。

命名策略的补给偏好和有界刷新参考同一March7thAssistant固定提交的`check_supply_phase`，经原生Context、独立次数回执、完整候选链和原奖励到账核验改写；保留上游署名与GPL v3许可。旧图缺失名字保留未知列，不从视觉人工读数伪造OCR通过；没有将局部校准或合成场景写成实机刷新成功。范围见[补给说明](currency-supply/README.md)。

## 2026-10-29 记忆开拓者配置名策略适配

同一March7thAssistant固定提交的`get_remembrance_trailblazer_name`及购买、保留、聘用书、顾问和补给调用，改写为AutoHSR的本局名称协议、原生策略偏好和一致身份核验。保留上游署名、固定源码Git blob及完整GPL v3许可，具体文件见[source.json](upstream/March7thAssistant/source.json)。名称配置不作图像素材，不引入上游固定费用或输入代码；本地实读名不发送给模型。本轮没有新增游戏素材或模型，真实字体及游戏路径尚未验收，见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-29 标准盛会之星弹窗与文字校准

固定March7thAssistant提交的`move_character`、`check_festival_star_popup`改写为原生部署／换人后的弹窗来源、一次选择／确认及完整角色交付协议，保留上游署名和GPL v3许可，见[source.json](upstream/March7thAssistant/source.json)。AutoHSR原有花火偏好继续保留，没有复制固定首项或上游输入代码。

[两卡文字夹具](../autohsr/tests/fixtures/currency_wars_star_two.json)来自既有4.6画面119／121，仅保留弹窗区域原OCR、原图及清单SHA-256，不修改识别文字，不含UID、账号或完整图像。游戏UI文字与角色内容归HoYoverse及相应权利人；来源记录不授予额外再许可。本轮未新增公开游戏图像或模型，119／121／169原图与清单保持本地忽略；用于查看的裁图和运行时局部图像来源不进入模型请求。布局、选中反例与未验收范围见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-29 普通角色采集局部图像校准

复用既有CN 4.6画面115／116，比较原角色槽位的微小像素变化，核对原图与原清单哈希；没有获取新游戏截图、发布原图或新增模型。两份旧图属于相邻校准样本，不是独立留出或新实机验收。原素材权利仍归HoYoverse及相应权利人，来源记录不授予额外再许可。

原弹窗协议的32×48灰度来源与有界比较移至[本地局部图像模块](../autohsr/currency_wars_appearance.py)，新增普通采集使用由本项目原生编写。运行时只裁已定位的角色槽位，图像来源保存在本地对局记录；不含UID或账号区域，不进入模型请求。公开新增测试仅生成合成槽位与面板；原图、清单、局部比较输出保持忽略，具体证据与边界见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-29 希儿场上整理与信用回执

参考固定March7thAssistant的`check_main_screen`、`sell_characters_seele_strategy`和`_sell_single_character`，将取得希儿后的场上非策略角色整理改写为AutoHSR前台／后台的独立查看与信用回执。来源函数、固定Git blob及GPL v3许可继续记在[source.json](upstream/March7thAssistant/source.json)，没有移植上游输入代码或缓存删除即成功的判定。

复用既有2026-10-26三份角色面板的当前`+5／+1／+2`返还文字与原图／清单哈希，未修改原图、重新取得游戏画面或公开账号区域；这些画面只校准返还字段，不能证明新增场上出售动作已通过实机。游戏素材权利仍归HoYoverse及相应权利人，来源记录不授予额外再许可。新增公开检查只生成合成槽位，使用既有署名图标构造空装备面板；场上来源及有界局部图像只保存到本地对局记录，不进入模型。验证与未实现的携装返回效果见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-29 原生全身重铸扩展

[全身重铸协议](../autohsr/currency_wars_worn_reforge.py)由AutoHSR根据既有CN 4.6游戏教程67／68号原生编写，原图及清单哈希仍见[消耗品来源](currency-consumables/sources.json)。67号说明冶金炉的同品质重铸，68号明确对角色全部穿戴装备重新随机；已查看排除账号区域的旧教程裁图，其中示意角色前后三个装备格均保留。此为规则校准，不是新实机动作或独立留出。

上游`equip_aglaea`、`equip_seele`提供仓库重铸及命名工具策略参考，全身目标及结果核验属于本项目新增扩展，分别记在[source.json](upstream/March7thAssistant/source.json)。没有添加新公开游戏图像或模型，测试使用既有署名图标与合成槽位。旧教程、离线QA裁图、角色有界来源与新回放保持本地忽略，QA查看排除账号区域，对局图像来源不加入策略模型载荷；游戏内容权利归HoYoverse及相应权利人，来源记录不授予额外再许可。

## 2026-10-29 全局阵容整理与空位移动

参考固定March7thAssistant的`deploy_and_optimize`及`move_character`，将全体持有角色的区域规划改写为[原生全局整理](../autohsr/currency_wars_standard_reorder.py)。保留本项目评分，固定与位置无关的目标，逐步核验真实身份和资源；新增另一侧空位移动，并处理其盛会之星接续。来源函数、固定Git blob与GPL v3许可见[source.json](upstream/March7thAssistant/source.json)，未直接移植上游金额排序、输入框架或缓存即成功的判定。没有新增公开图像、模型或游戏采集；测试沿用既有署名图标和合成棋盘，局部外观证明仅保存到忽略的本地记录，不加入模型载荷。

## 2026-10-29 整局执行与有界存档

参考固定March7thAssistant的`start_war`及`identify_current_stage`的整局执行与阶段监测，将本项目总512步实验循环改写为[原生分段执行上限](../autohsr/currency_wars_standard_budget.py)。计数刷新依赖本项目的胜利继续／补给交付来源，原未知输入保护继续使用；不迁入自动放弃与重开，也不以OCR变化作为额度刷新。64 MiB有界存档、写入前容量检查及总4096动作限制属于AutoHSR原生设计。源码blob、引用函数和GPL v3继续记在[source.json](upstream/March7thAssistant/source.json)；没有新增公开素材、模型或游戏采集，检查使用合成记录与已有署名素材。

## 2026-10-29 速通装备选项

参考固定March7thAssistant的`equip_weapons`、`check_main_screen`及`equip_aglaea`／`equip_seele`调用关系，将普通装备的首领节点限制改写为[原生装备模式](../autohsr/currency_wars_equipment_mode.py)。命名核心分配独立，保留本项目默认、设置保存语义及逐件装备回执；标准首领节点采用固定源码中的1-9、2-7、3-7，不将其他模式写成已接入。来源函数、Git blob及GPL v3许可见[source.json](upstream/March7thAssistant/source.json)。没有新增公开游戏素材、模型或实机采集；检查沿用既有署名图标与合成状态。

## 2026-10-29 旷宇纷争入口插图

新增`assets/ui/universe/`两幅入口插图，来源为2026-10-24和26日已保存的CN 4.6.0指南画面。只保留静态插图，原等级、赛季倒计时、奖励预览和动作区域移除，局部颜色延展补充背景；原区域不再代表账号或当前版本状态。来源SHA-256、裁切、移除蒙版、处理方法与输出SHA-256见[来源清单](ui/universe/sources.json)。未启动游戏采集，不包含完整帧、UID或账号指纹；游戏美术归HoYoverse及相应权利人，继续排除在原创代码GPL许可之外。

## 2026-10-29 指南场景与关闭符号

新增`assets/ui/guide/`两幅图像，复用既有CN 4.6.0每日实训源图，原图SHA-256与首批指南素材一致。背景移除标题、整本指南、关闭符号及整个底部HUD区，遮挡区域用低分辨率邻近颜色插值、放大并在蒙版内侧羽化；这些区域不代表原始景物。关闭符号单独裁出静态白色图形。来源哈希、1920×1080坐标、蒙版、变换及输出哈希见[来源清单](ui/guide/sources.json)，未分发原始整图、UID或安装路径，未启动游戏取材。游戏美术归HoYoverse及相应权利人，不纳入原创代码GPL许可，署名不构成额外再许可。

## 2026-10-29 携装角色出售与装备返还

参考固定March7thAssistant的`_sell_single_character`及三种出售调用关系，将携装角色处理适配为[原生库存返还协议](../autohsr/currency_wars_sale_equipment.py)。保留本项目已校准图标和角色面板，增加版本化目标、完整库存来源、逐项返还及售后完整重采，未移植点击成功即完成的判断。来源函数、Git blob及GPL v3许可继续记录于[source.json](upstream/March7thAssistant/source.json)。本轮没有新增图像、模型或游戏采集；正向售出及返还均为合成画面机制检查，来源及边界见[开发记录](../docs/currency-wars-development.md)。

## 2026-10-30 多副本体力计划

参考固定March7thAssistant的`Power.run`、`Power.execute_power_plan`、`Power.process`及副本执行结构，将有序条目、剩余次数、固定重复和默认副本补刷适配为[AutoHSR原生计划](../autohsr/power_plan_run.py)。源码的Git blob、SHA-256、固定提交及GPL v3许可记在[source.json](upstream/March7thAssistant/source.json)，已与此前取得的固定目录树核对。没有复制上游GUI、输入框架或配置自动扣减写回行为；本项目仍只在保存设置时写配置，运行进度使用独立本地账本。

一份已有资源预算、同账号新鲜画面、原生逐批支付核验、原子计数及不可覆盖归档属于AutoHSR实现。没有新增公开游戏素材、训练模型或采集画面；新增检查使用合成窗口与场景，账号数字为虚构测试值。培养目标、资源补充及遗器清理均未在本轮接入，界面与实机边界见[计划说明](../docs/power-plan.md)。

## 2026-10-30 历战优先周计划

参考固定March7thAssistant的`Echoofwar.start`及`Daily.prepare_daily`，将当前0～3次周额度与清体力前的优先执行适配为[原生历战周计划](../autohsr/echo_weekly.py)。源码Git blob、SHA-256、固定提交和GPL v3来源见[清单](upstream/March7thAssistant/source.json)。本项目使用日常开始时间、04:00游戏周和单份冻结预算，独立核实周额度、可见结算与本次实际完成，不迁入上游配置时间戳写回、输入或定时器。

没有新增图像、模型或游戏采集，检查沿用合成窗口与场景。缩短新归档目录键并保留完整账本摘要是本项目对Windows路径长度的修复，既有目录不迁移或覆盖。培养目标和支援角色偏好仅完成源码核对，尚未适配，不在本轮署为已实现；交互、运行证据及实机边界见[说明](../docs/echo-of-war-plan.md)。

## 2026-10-30 支援角色与好友偏好

参考固定March7thAssistant的`Character.borrow`及角色／好友查找、角标遮罩检查，适配为[原生支援选择](../autohsr/support_selection.py)。固定代码、角色名称来源的Git blob及SHA-256见[父清单](upstream/March7thAssistant/source.json)，上游代码使用GPL v3。另引入105幅未改变字节的角色头像，逐幅路径、尺寸、哈希和原Git blob见[头像清单](upstream/March7thAssistant/support/sources.json)，[说明](upstream/March7thAssistant/support/README.md)区分源码许可与HoYoverse等原权利人的游戏美术权利。

有界逐页查找、精确好友名、角色形态分差、左侧星魂遮罩、明确回退和原生逐次反馈属于本项目适配。没有迁入上游输入框架、满员移除自身角色或借用即完成实训的行为；没有训练模型或新增游戏采集。合成变体与两份既有列表仅用于机制／局部校准，不代表独立真实留出或实机通过，见[功能与验证边界](../docs/support-preferences.md)。

## 2026-10-30 投资策略角色赠送

继续参考固定March7thAssistant的`check_investment_environment`和`check_special_characters`，将角色赠送接入[原生核验](../autohsr/currency_wars_investment_units.py)。固定源码及GPL v3署名保留在[上游清单](upstream/March7thAssistant/source.json)。原末节点完整阵容、直接位面来源、确认后全部重采、显式数量／星级／费用、装备守恒与逐角色关闭回执是AutoHSR实现，没有迁入上游缓存加计数或默认首项的行为。

效果文本来自既有4.6的150号匿名字段样本，记录“黑塔、缇宝、0.15%”，未由标题猜测星级。原样本和PNG的SHA-256、校准范围及权利说明见[机制清单](currency-investment/sources.json)与[README](currency-investment/README.md)。没有新增、复制或公开原游戏画面，没有训练模型或独立真实留出；其他变体和输入链为合成检查，真实赠送尚未验收，见[说明](../docs/currency-wars-investment-units.md)。

2026-11-05 另从既有 150 号画面裁出 68×68 投资刷新图标，并核对同局 164 号画面和两图的其他列。原图未发布，图标仅用于技术识别。来源、坐标、转换和哈希见[投资素材记录](currency-investment/sources.json)。

## 2026-10-30 支援偏好桌面展示

中文候选列表复用上述105幅既有[支援头像清单](upstream/March7thAssistant/support/sources.json)与明确名称，仅在内存中将已选头像缩放至38个逻辑像素供界面显示；原PNG及哈希不变，没有增加游戏画面或训练素材。美术权利与上游源码GPL边界继续见[原说明](upstream/March7thAssistant/support/README.md)。编辑与快照接线由本项目实现，应用／保存不读账号、好友名单或游戏画面，不把参考头像视为可用支援的观察证据；验证与实机边界见[支援说明](../docs/support-preferences.md)。

## 2026-11-05 培养材料来源预览

预览参考固定三月七提交的紧凑材料标题框、花萼来源区域和掉落表中的四组材料。只复用指定材料与副本的名称事实，按 AutoHSR 已有目录映射候选。固定源码及数据表哈希、GPL v3 来源见清单，游戏画面位置与材料来源的证据分别见体力计划说明。新增测试采用合成 OCR 布局与原有脱敏目录字段。[上游来源清单](upstream/March7thAssistant/source.json) [材料预览说明](../docs/power-plan.md#材料来源与体力计划预览)

2026-11-06 补充国服 4.6 时期玩家公开的材料合成页及两类确认弹层。夹具仅收录限定 OCR 文字、数值与坐标，出处、原件与脱敏哈希及配方数量栏放大方式见数据清单。公开原图、视频及游戏界面归原作者、HoYoverse 和相应权利人。仓库只分发脱敏字段。[数据清单](../autohsr/tests/fixtures/dungeons/build_target_synthesis.json)
