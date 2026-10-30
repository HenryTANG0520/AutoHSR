# 货币战争后端差距审查（2026-10-30）

## 核对范围与结论

核对日期为2026年10月30日，本地基线为`95a6691`及当时工作区的货币战争源码。目标继续是保留AutoHSR已有能力，逐项学习、适配三月七全部功能，特别完善货币战争；桌面交互由现有“UX/UI”工作负责，本审查不调整界面。

上游固定为March7thAssistant提交[`7cf6c6bed474539485d3b1504077ac352866829f`](https://github.com/moesnow/March7thAssistant/tree/7cf6c6bed474539485d3b1504077ac352866829f)，实际读取已有本地缓存的[`tasks/weekly/currency_wars.py`](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/currency_wars.py)。该文件的Git blob为`52507ccfa8bf7977f8a8be9eca24050a6c16990d`，SHA-256为`1a26a0339439204281e34a2fbc8cdec3aa46b61f0589f4ab1c5d377d0397ef54`；已核对缓存文件、固定树条目与[来源清单](../assets/upstream/March7thAssistant/source.json)一致。上游源码许可为GNU GPL v3，游戏画面及文本仍归各自权利人所有。

建议先补**初始环境的独立交付协议**，再扩展纯赠武装箱及双装备补给。它们可以拆成有界的离线机制工作，但现有证据不足以把新增效果、真实布局或实际到账一并验收。自动战斗开关也是明确缺口，需要单独校准CW控制，不能未经核实直接沿用日常或差分的状态授权。

原审查阶段仅记录差距，没有完成修复、OCR或模板校准、游戏输入、资源消耗、实机验收或EXE构建；同日后续的位置更正与CW只读状态观察另见下文，不把它们外推为自动开启动作或整局通过。没有新增游戏授权、接续旧开发局或恢复已终止的十场A8-40目标；历史独立整局验收仍为**0/10**。

## 已有能力与新增发现

当前已经接通标准节点识别与推进、分步终局结算、逐张购买、经验支付、受限刷新和出售收据、三种策略、满员交换与全局候选整理、14类装备及已读配方、六种工具的部分规则、命名核心全身重铸、奖励与补给选择、补给刷新、部分投资效果及赠角，以及失败结算、循环、积分、普通领奖和周常编排。这些能力的离线检查与各自实机边界见[开发记录](currency-wars-development.md)、[总体清单](development-roadmap.md)和[货币战争验收](../CURRENCY_WARS.md)，不能把历史条目中的“尚未接通”重新当作当前完整缺口。

本次补充指出以下源码边界；它们是审查发现，不是本轮新增能力：

| 未闭环点 | 具体源码事实 | 影响 |
| --- | --- | --- |
| 初始环境声明的赠品缺独立交付协议 | [环境解析](../autohsr/currency_wars_environment.py)能读出`growing_unit`的数量、星级与费用；[标准流程](../autohsr/currency_wars_standard_flow.py)的`transition_ready`对`initial_board`只核对目标节点和备战／商店页，确认后保存环境决定 | 页面转换通过不能进一步证明声明角色或物品到账；这里缺少类似位面投资赠角的独立完成回执 |
| 纯赠箱环境没有可执行语法和初始来源 | 同一环境解析未支持上游“火药味”的纯赠箱文本；[投资解析](../autohsr/currency_wars_investment_policy.py)当前支持的是减伤附赠箱等已定义效果 | 已有开箱能力不等于初始环境赠箱已经接通 |
| 补给候选与回执只表达一件装备 | [补给字段](../autohsr/currency_wars_supply_fields.py)的`_items`按每列一个装备词核对四／五卡；[奖励协议](../autohsr/currency_wars_standard_rewards.py)的`_options`保存单个物品，`feedback`只增加一件库存，`returned`也记录单个`item` | 不能覆盖上游明确提到的双装备补给，漏读第二件也不能当作单件已完整识别 |
| 标准节点没有开启自动战斗协议 | 原审查时[节点观察](../autohsr/currency_wars_standard_node.py)只识别战斗与结果；同日后续已补on／disabled／unknown只读检测及两帧观察，仍没有off或开启动作 | 只读on证据不等于本程序开启过开关；缺少真实关闭与切换反馈链，完整自动开启仍待交付 |

## 建议顺序与验证范围

### 1. 初始环境声明与交付分开核验

上游参考为[`check_investment_environment`](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/currency_wars.py#L2709)的环境选择与[`check_special_characters`](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/currency_wars.py#L2676)的特殊赠送处理；后者的缓存计数不直接移植。本地入口为`parse_environment_effect`、`standard_environment_choice`及标准流程的环境确认／`initial_board`分支。

已有[脱敏环境字段](../autohsr/tests/fixtures/currency_wars_standard_environment.json)记录4.6“战力飙升”的完整数量、星级和费用，另有[环境机制检查](../autohsr/tests/test_currency_wars_standard_environment.py)、[角色采集](../autohsr/currency_wars_collector.py)及[位面投资赠角协议](../autohsr/currency_wars_investment_units.py)可参考。可以离线设计确认后的`delivery_pending`、当前十九格／完整角色重读、独立查看与关闭来源，以及错误数量／星级／费用、旧面板、换代次和写盘失败的反例。环境确认只应完成页面转换，声明交付另记结果。

**不能复用位面赠角的旧基线。** `currency_wars_investment_units.baseline`要求本局末节点出战前的完整角色、装备和库存，且与胜利继续、下一位面来源直接相邻；`currency_wars_standard_investment._origin`也核对这条跨位面链。初始环境处于开局阶段，没有这条前置出战链，也没有现成确认前完整阵容。不能借用旧局、旧节点或不完整缓存补齐，更不能只因结果阵容出现一个匹配的二星二费角色就归因“赠品已到账”。

同日后续扫描79份既有教程的安全字段，未找到初始角色数或零库存声明；其中42号说明补给／晶矿，93号说明专家解锁，均不构成初始零基线。[旧开发记录](../CURRENCY_WARS.md)还表明：环境选择后领取两个开场掉落、金币3→5，随后才见五张角色卡，未读取全部姓名／星级，也未发布完整阵容。既有匿名环境字段只证明“获得1个随机2星2费角色”等声明，不能确定五卡中哪一张来自环境、开局原有角色或掉落，更不能用最后可见角色反推领取前库存。

`StandardSession.begin`只保存开局entry，`snapshot_from_scene`不补初始roster／inventory。后续基线应使用完整十九格与逐角色查看来源，以及[14格库存读取](../autohsr/currency_wars_consumables.py)保留的unknown；未取得完整库存来源时，`inventory_counts`返回空Counter不能证明初始库存为空。

后续编码建议分开表达以下状态，**尚未实现**：

| 建议状态 | 需要证明的事实 |
| --- | --- |
| `selection_accepted` | 环境选择／确认的独立页面反馈被接受；只完成选择转换 |
| `current_state_observed`，`baseline_scope=post_choice` | 确认后新鲜的角色／装备／库存现状已完整观察；只能作为之后晶矿／箱子等独立交付的当前前态，不能追认环境之前的来源 |
| `declared_obligations` | 按已读完整效果保留声明数量／星级／费用／箱种等待核实义务，未声明的字段不补造 |
| `delivery_verified` | 有本次专用前后来源及逐项实际变化，才能证明对应义务交付；现有post_choice阵容相符本身不够 |

还需环境确认专用的免费收店来源。[`initial_board`反馈](../autohsr/currency_wars_standard_flow.py)允许shop或preparation，而[普通收店](../autohsr/currency_wars_standard_market.py)经`shop_return_values`要求已核实`open_standard_shop`／交易链及`pre_shop_snapshot`；[节点到达收店](../autohsr/currency_wars_standard_progress.py)又只认`continue_standard_node`来源。不能伪造普通开店前快照或借跨节点到达记录。下一步应从本次已核实环境确认、同账号／节点／代次、新鲜可用收起控件建立独立无消耗意图和返回核验，再采集post_choice现状；这条专用协议仍待编码，不开放交易、不补环境交付成功。

因此首项工作必须先定义并证明初始专用来源：哪些是可核实的开局原有角色，哪些是声明新增，能证明数量、身份、装备与库存的哪些变化。缺少基线时只能保存当前观察和未核实义务，不能构造收入或完成回执。既有字段只是文本校准，不是这条来源及真实交付的证明；相应规则或真图缺口仍需补证。此项优先是因为后续初始赠箱、其他初始角色／物品效果都需要同一来源基础。

### 2. 纯赠武装箱环境的逐箱交付

固定上游[`check_investment_environment`中的环境说明](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/currency_wars.py#L2742)列出“火药味：开局时获得2个简易武装箱”，并将它列入阿格莱雅环境偏好。本地可扩展环境语法，并参考[投资赠箱协议](../autohsr/currency_wars_standard_investment.py)的`_reward_action`、`bind_reward`、`reward_completed`和`valid_effect`，由[标准奖励](../autohsr/currency_wars_standard_rewards.py)实际开箱与核对装备到账。

已有[普通奖励字段集合](../autohsr/tests/fixtures/currency_wars_pages.json)、[高级箱字段](../autohsr/tests/fixtures/currency_wars_advanced_box.json)及[奖励机制检查](../autohsr/tests/test_currency_wars_standard_rewards.py)可复用。范围宜限完整声明的一至三箱、已识别箱种和现有装备；箱数、来源槽、每箱选择／确认／库存交付分别核验，其他未开箱子保持原签名。未知箱种、空位不足和溢出停止，不重复领取。

当前缺“火药味”的4.6真实卡片文本与完整交付样本；固定上游说明证明参考思路，不能替代当前游戏校准。可以完成合成文本变体和逐箱来源机制，真实识别及实际到账仍须补证。初始来源依赖第1项，不能把初始环境伪装成`_origin`要求的跨位面投资。此项排第二，因为它不需要新增特殊物品图标，能够小范围复用已有逐箱交付机制。

### 3. 已识别双装备补给

固定上游[`check_investment_environment`的“过剩经费”说明](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/currency_wars.py#L2743)明确提到补给角色携带两件装备；策略选择参考[`check_supply_phase`](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/currency_wars.py#L2854)。本地入口为补给字段`rows`、奖励候选／摘要、刷新候选连续来源及最终库存／角色核验。

已有[补给来源说明](../assets/currency-supply/README.md)、[第三位面补给字段](../autohsr/tests/fixtures/currency_wars_supply_plane3.json)、[装备目录](../autohsr/currency_wars_equipment_catalog.py)和完整角色重采可复用。可离线把单个`item`扩为带数量的装备列表，保留旧单件格式，核对重复两件、不同两件、候选重排、缺读、错误增量和来源篡改；仅接受两件都属于现有14类目录且具有当前独立来源的候选。选择、确认、刷新摘要和实际交付必须使用同一列表，不能只扩解析器。

**当前没有真实双装备卡片布局。** 单件装备行不能证明第二件的位置、显示形式或最终进入仓库／穿戴的方式；不得按上游一句说明猜坐标、猜第二件或自动增加库存。可以先完成数据与合成机制，真正接通识别前须补双装备真图及交付结果。未知装备、额外奖励、自动穿戴和溢出应有专用契约，否则仍保持未核实。此项排第三，原因是它横跨候选、刷新、策略与交付，校准缺口比纯赠箱更大。

## 自动战斗及暂不宜扩大的范围

上游[`check_auto_battle`](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/weekly/currency_wars.py#L2558)在左下区域匹配`share/base/not_auto.png`后发送配置热键。该参考图实际只是黄色字母C提示，搜索ROI不能据此等同为CW自动开关的位置。当前[标准节点观察](../autohsr/currency_wars_standard_node.py)仍没有自动开启输入协议；[日常自动开关](../autohsr/workflows.py)的`_auto_state`主要读取右上区域，差分另有[自身图标及状态判断](../autohsr/du_navigation.py)。[Context](../autohsr/app.py)的`differential_universe_auto_click`也明确限差分入口。

**真实旧CW画面的右上也有自动／倍速／暂停控制，颜色本身不能证明状态。** 同日最初对10张既有CW战斗图作排除账号区域的局部核对，已确认右上的双三角自动图标与倍速、暂停同组，并有金／白／灰外观；后续仅对有独立CW图形与真实跨参考、暂停组共同证据的on／disabled作局部校准，其余仍unknown，不能直接套用DU金／白判断。存在同形图标不证明目标是可用且关闭的CW自动开关，标准战斗页已识别也不单独授权切换。

同日后续已将[原生检测器](../autohsr/currency_wars_auto.py)接入标准节点：CW战斗页、CW局部图形、独立真实on／disabled参考及暂停组共同成立后，只读返回on／disabled／unknown；同节点／账号／代次的两份新鲜on画面才记本节点曾核实on。当前状态与历史证据分开，unknown／disabled不抹掉已核实on或胜利，日志也不再在未核实时称“正在自动战斗”。局部校准、历史回放、邻近遮挡与合成检查见[素材说明](../assets/currency-auto/README.md)及[开发记录](currency-wars-development.md)。

后续仍缺真实off及关闭→开启的来源与反馈，完整输入协议还须绑定本次已核实出战、相同节点、新鲜画面、账号、输入代次和一次落盘动作；未知不得反复切换。当前检测不返回off或可点击点位，也不发送热键，不得将局部只读校准当作输入授权、实机切换或新增独立整局成功。

同日后续更正说明：本文最初把上游左下字符搜索误写成“CW左下角控制”，并据位置差异排除了右上参考；这是先前审查中的位置推断，不是当前结论。原审查提交保留，不改已推历史；当前正文已依据旧CW右上控制的实际观察收准。定位更正本身不完成状态或动作验收，后续局部只读实现单独记录，真实off、切换来源与动作协议仍待核实。

后台8／9格、星徽和其他特殊物品、满额助燃券清理、其他模式／难度仍需各自的布局、规则或资源反馈证据。不能通过增加枚举、照搬上游缓存计数、降低识别阈值或合成一张正例就写成已支持。已有6／7格检测及前六个可部署后台槽也不能外推为所有扩容布局。

## 本轮检查边界

原审查阶段只读核对上述源码、脱敏夹具、来源说明和固定上游缓存；没有读取或外发真实UID、账号私密记录。该阶段文档检查限两份文档的差异、相对链接、固定源码的Git blob／SHA-256及树归属，没有运行单元测试、项目CLI、GUI／字幕模拟或游戏。后续只读检测与标准节点的专项、夹具失败及修正记录另见[开发记录](currency-wars-development.md)，不以其他并行工作通过替代本功能证据。

本审查初版仅新增本文并在[开发记录](currency-wars-development.md)末尾追加入口。上列前三项交付方案仍未实现；同日后续只读CW状态观察没有新增off或切换动作，也没有新增实机、独立留出或成功整局。旧失败、旧账本与已终止目标保持原状，历史独立验收仍为0/10。
