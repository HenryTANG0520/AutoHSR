# 初始环境接受与确认后现状

更新日期：2026-10-30。标准A8财富造物主40已接环境选择接受、`post_choice`现状与初始自动商店免费收起的后端及正式Context门禁，通过假IO机制检查；环境赠品实际归因仍未接通。GUI、真实路径及独立整局尚未验收，历史0/10不变，旧十场目标未恢复。

## 四类事实分别记录

| 事实 | 含义与边界 |
| --- | --- |
| `initial_environment.selection_accepted` | 原确认动作verified、两份独立到达及after像素来源一致，只证明选择被接受 |
| 确认后现状：`post_choice_observation` | 实际字段名不是`current_state_observed`。`roster_complete=true`证明当前十九格与逐角色来源完整；十四格库存原样记录，`inventory_complete`可为false，此时观察`status=partial`；`baseline_scope=post_choice`不证明初始交付 |
| `declared_obligations` | 按已读完整声明保留kind／parameters；每项始终`status=unattributed, delivery_verified=false`，不从现状反推收入 |
| `post_choice_observation.delivery_verified` | 当前固定false；后续需要可归因的本次前后来源与实际变化，不能由选择接受或现状观察补为true |

环境声明、界面接受、现状观察和实际交付不能互相代替；确认成功不清除未知交付，`post_choice`也不追认之前是哪种来源增加了角色或物品。

## 初始确认与现状接口

实现位于[currency_wars_initial.py](../autohsr/currency_wars_initial.py)，`policy=initial-environment-v1`，记录在本局session的`initial_environment`，不新增设置或实际游戏授权。

| 接口 | 前置条件与结果 |
| --- | --- |
| `begin(session, action_id, run_dir=..., epoch=...)` | 只绑定本次新pending的`confirm_standard_environment_0/1/2`；此前为已核实start→preview→plane，可夹环境选择动作。目标固定1-1，核对本局／账号／4.6版本与本次确认run／epoch，冻结原动作、前缀摘要和before证据；已有来源不覆盖 |
| `record_arrival(session, scene, evidence=..., run_dir=..., epoch=...)` | 在原确认后、无中间动作时记录两份新鲜capture及不同证据路径。允许preparation／shop动画，只比较双方已读HUD，node／gold／level必须可读；重复capture不凑第二帧 |
| `accepted(session, action_id)` | 必须原确认动作verified，两帧齐全，action.after与第二帧像素／shape一致后，才记selection_accepted |
| `capture_current(session, scene, evidence=..., run_dir=..., epoch=...)` | 依原生完整采集，在确认后的实际inspect／close来源成立后冻结首次`post_choice_observation`；非备战、roster不完整返回None，不表示完成。无新记录的旧局不补建初始来源 |
| `validate_origin(session, require_accepted=...)` | 复核原动作／前缀／声明、证据文件与既存观察；这是历史来源校验，不代替Context的当前画面、账号和代次检查 |

文件引用须位于对应run内，PNG最多32 MiB、像素最多16,777,216，核对原字节SHA-256、像素和shape。原确认before还须与输入前Scene像素一致；缺失、越界、改变或不符停止，不能换一张近似图补来源。证据路径与账号指纹只留本地，不进入模型输入。

现状使用原生`roster_cells`、`collected_snapshot(..., allow_reward_items=True)`及14格`stock`。未开箱槽可以作为reward保留，不能先开箱才能构造前态；持有角色须有确认后的实际查看／关闭及当前来源，旧cache或名字／星级恰好匹配不够。库存未读格和数量unknown原样保留，不能把空Counter或后续识别补成初始空库存。

首次有效roster观察会冻结；库存unknown时保持partial，不用后续重读覆盖或升级这份历史记录。再次取得已有记录只是返回原观察，不能把它当作新的现场前态。记录整体按JSON语义规范化，tuple／list存读等价仍比完整内容，不删掉未知字段或落盘核对。

## 已有证据不支持初始零基线

原`StandardSession.begin`只保存开局entry；环境确认前没有完整角色与库存来源。既有[环境匿名字段](../autohsr/tests/fixtures/currency_wars_standard_environment.json)只证明当前4.6卡片中的数量／星级／费用文本，不证明实际交付。79份既有教程的安全字段扫描未找到初始角色数或零库存声明；42号说明补给／晶矿，93号说明专家解锁，均不构成零基线。

[旧开发记录](../CURRENCY_WARS.md)记载环境选择后又领取两个开场掉落，金币3→5后才看到五卡，且当时未读全部姓名／星级、未发布完整阵容。不能凭其中一个二星二费角色归因环境，也不能用奖励后的现状倒推领取前阵容。位面投资赠角所要求的末节点出战、胜利继续和下一位面直接相邻来源，不能用于开局阶段。

库存必须保留各格实际观察与unknown，缺完整库存来源时的空Counter不能证明初始库存为空。后续晶矿或箱子可在取得当前完整前态后独立核对变化，但这种变化仍不能补证环境确认前的赠品来源。

## 初始自动商店的独立免费收起

`initial_board`允许到达shop或preparation。普通`close_standard_shop`要求已核实的`open_standard_shop`／交易链及`pre_shop_snapshot`；节点到达收店又要求`continue_standard_node`来源。环境确认自动打开的商店没有这两种来源，不能伪造普通开店前快照或借用跨节点记录。

实现位于[currency_wars_initial_shop.py](../autohsr/currency_wars_initial_shop.py)，`policy=initial-free-shop-return-v1`。动作`close_standard_initial_shop → standard_initial_shop_closed`只接受原确认的直接延续：同局／账号／run／epoch，尾动作是原confirm、没有中间交易或其他动作，当前为新鲜shop且有唯一可用“收起”。到达可为prep→shop，也可prep→prep后无输入的freshshop延续；不要求被面板遮挡的HP／xp／部署数强行可读。

`proposal`冻结原确认id／摘要、当前HUD、来源帧／图像／OCR摘要、收起控件与当前商店信息；当前node／gold／level必读，隐藏字段保留None。Root先写新pending及target，再`bind_intent`并持久化独立`initial_shop_return`，Context重新推导目标并核对落盘同一性后才一次点击。

`feedback`只认返回preparation、同节点／账号及双方已知HUD守恒；Root收集两份不同capture与不同证据路径后，把原动作verified，再调用`closed(session, choice, before, frames, evidence_paths, confidence)`核对原after为最后一帧，写独立收据。收据保留`free_view_only=true, trade_authorized=false, delivery_attributed=false`，并写`action.initial_shop_return_receipt`；不制造`open_standard_shop`、`pre_shop_snapshot`或跨节点arrival来源。

接受或返回专用核验失败时，原动作保留unknown、独立来源／pending不清除，不能看见当前备战页就补成成功或重发点击。合法的后续普通商店仍走原合同：已核实原post_choice来源后，此专用proposal返回None，不长期劫持以后开店。整个协议不购买、不刷新、不补资源，也不开放通用确认或交易。

## 正式流程顺序

共享[标准流程](../autohsr/currency_wars_standard_flow.py)先处理专用初始shop，再进入普通商店／交易。若初始来源已接受而首次观察尚缺，preparation阶段只推进角色查看与关闭；完整采集后先持久化post_choice，再处理开箱、晶矿、消耗品或原决策，不能把奖励后状态倒填为前态。

[Context](../autohsr/app.py)在内存或磁盘任一存在初始字段时，都以严格JSON内容核对落盘记录，检查当前窗口／Scene／账号／epoch及原确认before，再重新推导动作；只删内存字段也不能绕过。`close_standard_initial_shop`单列为免费动作，不改变原支付意图／收据。暂停、失焦、换代次或证据缺失时丢弃旧目标，不能以旧帧拼接新的接受／返回证明。

## 旧记录与验证边界

无`initial_environment`的旧记录继续保留旧格式，`capture_current`不补建新来源；`begin`也不接纳旧verified确认来反写新接受。已存在的新元数据损坏、与磁盘不符、来源改变或旧动作unknown时停止，不删除字段冒充legacy，不重放确认／收店。原报告、失败、账单及待核对状态不改。

新观察只证明当前roster来源及库存识别程度，不是金币收入、角色赠送或环境交付收据，不增加节点／整局成功计数。当前只覆盖初始1-1；后续位面、纯赠箱、双装备补给及可归因的环境交付仍有各自缺口。

2026-10-30阶段38项专项通过`runs/cw-initial-related-first.log`（33.908秒）：12项初始来源、18项免费收店、8项实际run_standard／Context假IO整合。覆盖两不同capture、混合页面动画、未知HUD／库存、JSON存读、旧cache拒绝、内存来源删除、写盘失败和返回核验失败后不重放；没有游戏、真实marker、实际CLI或GUI。首轮Root17项中的2失败1错误保留于`runs/cw-initial-flow-first.log`，原因是夹具停止边界和旧cache发布预期不符，修正为真实下一checkpoint停止及旧cache不得发布，没有放宽运行来源门禁。

最终**1921项全量通过**`runs/cw-initial-all.log`（813.028秒），驱动813.782秒、退出0；`runs/cw-initial-full-result.json`及`runs/cw-initial-full-snapshot.json`核对312份Python／requirements源文件与重新枚举的完整清单，前后哈希一致、`snapshot_unchanged=true`。前轮1883项属于旧快照，本轮另留原日志，不相互替代。

提交前6份说明的326处本地链接、45份固定上游源码的Git blob及其中41份已声明SHA-256、GPL许可哈希和8组原生扩展的51处文件引用核对通过，见`runs/cw-initial-final-verification.json`。同时将来源清单原有的过期通知测试路径修正为实际的`test_notify_provider_contract.py`，没有改动通知代码或测试内容；私人运行、配置、凭据和调查目录未纳入版本控制。

本轮没有启动、检测或操作游戏，没有新实机截图、模型、真实外部通知、系统任务或EXE构建；真实初始布局、页面动画、查看／收店组合、初始礼物归因及独立整局仍未验收。
