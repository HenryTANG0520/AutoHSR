# March7thAssistant 参考来源与适配

来源：[moesnow/March7thAssistant](https://github.com/moesnow/March7thAssistant)，维护者moesnow及其贡献者。核对日期2026-10-28，固定提交`7cf6c6bed474539485d3b1504077ac352866829f`。

上游使用GNU GPL v3；保留的原许可见[LICENSE](LICENSE)，具体源文件的Git blob及许可文件SHA-256见[source.json](source.json)。AutoHSR本身也使用GPL v3。游戏角色名及相关游戏内容仍归各自权利人所有。

本轮将上游`tasks/weekly/currency_wars.py`中的核心角色优先、取得核心后切换成长阶段、按完整一级经验判断余额、购买后更新角色信息等思路，改写为本项目的`currency_wars_standard_policy.py`与`currency_wars_standard_trading.py`。阿格莱雅／希儿的角色偏好和成长阶段来自这份固定源码；实际售价、星级、费用、位置适配、余额、经验及阵容来自AutoHSR当前画面和本局记录。

没有复制上游固定角色费用表或输入实现。输入继续经过本项目Context、UID核验、落盘意图和逐次反馈；上游连续按键购买被适配为每次购买后重新观察。原始上游执行框架、GUI和模型未迁入；装备阶段另引入18幅[固定装备参考图](equipment/README.md)，其字节、Git blob、哈希和许可另行记录。本目录不包含账户配置或上游安装目录数据。

2026-10-29另将`deploy_and_optimize`、`move_character`中的已持有角色成对交换思路适配到`currency_wars_standard_exchange.py`。本项目在拖动后另行打开两个位置的角色面板，核实名字、星级、费用及位置，返回同一备战页后才确认移动；不直接把内存中的角色列表交换当作游戏已完成。

2026-10-29另将`buy_aglaea`、`buy_seele`中按核心星级和等级阶段刷新的机制适配到`currency_wars_standard_refresh.py`与`standard-native-v2`。当前按钮显示的费用是唯一扣款来源；每节点最多六次、合计十二金币，优先保留完整一级经验预算和现有利息底线。刷新后读取五个报价及精确余额，核对备战席未变，逐笔记录再决策；未沿用上游循环按D和缓存扣除两金币的实现。

2026-10-29另将三种整理方法和`_sell_single_character`适配到`currency_wars_standard_sale.py`。本项目先保留有用部署／交换与空装备证据，逐个查看九个备战格中的候选，读取当前返还，再核对金币到账、来源槽清空及其余槽未变；不以缓存列表删除或点击“出售”作为完成。`standard-native-v3`同时停止命名策略对非核心已持有角色的无用重复购买，同节点淘汰的名字暂不买回。

2026-10-29另将`equip_aglaea`、`equip_seele`、`equip_weapons`及`_equip_single_character`的核心优先和推荐合成适配到`currency_wars_equipment_catalog.py`、`currency_wars_standard_equipment.py`。识别14种可穿戴装备；按当前角色推荐及两件材料图读取配方，保留相同材料的两份数量。每次只拖一件，核对仓库少一件后另开角色面板确认实际穿戴与合成结果，返回备战页才完成，不沿用上游尝试后直接增加鞋数／装备数的计数方式。

2026-10-29另将`check_box`、`_check_equipment_box`、`_check_expert_invitation`和`check_supply_phase`适配到`currency_wars_standard_rewards.py`。开启来源、冻结的核心偏好、四／五组角色与装备配对、选择和确认分别核实；普通／高级武装箱只选已识别的装备，邀请函现金按当前0～99读数核对到账，不沿用旧固定4金币。补给返回后先核对仓库恰好增加所选装备，再重新查看完整持有角色；实际角色增加／升星及其他角色不变后才完成领取，不通过点击或缓存追加认定到账。

2026-10-29另将`check_investment_environment`中的命名策略偏好与排除列表适配到`currency_wars_investment_policy.py`、`currency_wars_standard_investment.py`。支持完整文本的斩杀、延迟伤害增幅、减伤／附赠武装箱、临时升星及收费刷新赠经验语法；先核实胜利和位面来源，再分开选择、确认，赠品由已有武装箱协议逐箱核实到账。没有移植未知候选、图鉴标记或固定第一项的兜底，也不自动重开。刷新赠经验从已核实策略回执推导，读取实际经验及余量；免费刷新不套用收费收益，赠经验后收店重采，不沿用旧容量。

2026-10-29另将`_check_hiring_book`、`_check_expert_invitation`的角色偏好适配到`currency_wars_character_rewards.py`及原奖励流程。聘用书按当前OCR名字与羁绊关联一至五个候选，费用、领取数量和实际星级分别处理；命名策略按完整持有阵容选择，默认邀请函仍选择已读现金。角色选择返回后逐个重采，核实新增／升星、费用及原装备保留，再结束领取。没有移植固定坐标或首项兜底；上游也将聘用书坐标注明为未测试，本项目目前没有真实聘用书画面，只验证合成变体。

顾问解锁与商店购买是不同事实，参见[官方V4.0机制说明](https://sr.mihoyo.com/news/162649?nav=home&type=news_all)及本地既有4.6教程回放。当前选项只记录`advisor_unlock_declared`；必须后续在商店看到该名字的带价格报价，才另记`advisor_shop_observations`，不构造购买记录。角色未实际新增／升星时原领取保持未核实，单纯解锁但不交付角色的分支尚未接通；旧公告的角色费用和职级上限不迁入4.6规则。

这些策略目前覆盖购买、成长、受限刷新、备战整理、已有角色补空位、合法满员交换、有界装备穿戴／合成、部分奖励和投资策略，以及聘用书／邀请函角色的离线选择与到账核验机制。任意全局重排、直接出售在场角色、记忆开拓者自定义名称配置、拆装／投影仪／令牌／冶金炉、补给刷新和所有节点尚未全部复现；聘用书真实布局、顾问仅解锁分支、未识别装备和配方、星徽／投资策略角色赠送及改造型策略、多个赠经验规则的叠加、其他额外金币／经验、额外多件补给、自动填入刚释放槽位的奖励等效果仍需专门契约，当前保持未知。离线测试不代表实机胜率或整局通过。实现与验证见[开发记录](../../../docs/currency-wars-development.md)。
