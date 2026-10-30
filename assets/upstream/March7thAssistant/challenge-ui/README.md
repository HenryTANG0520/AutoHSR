# 固定挑战局部图与有限准备观察

参考版本：March7thAssistant `7cf6c6bed474539485d3b1504077ac352866829f`，作者为moesnow及其贡献者，保留[GPL v3原许可](../LICENSE)。14幅原始最小局部图按固定tree重新核对Git blob／字节数及SHA-256，并逐张查看后原样复制；原路径、公开相对路径、尺寸、哈希和用途见[sources.json](sources.json)。没有重编码、派生完整页面、真实账号内容或新实机截图。游戏美术归HoYoverse及相应权利人，源码许可不授予额外美术权利。

## 原件实际能证明什么

- `forgottenhall/team1.png`／`team2.png`只是带链纹的数字1／2，不含角色已选、禁用或四人完整反馈。
- `forgottenhall/start.png`只是`「混沌回忆」`文字，`start2.png`为`「回忆」`，不是完整按钮可用态。
- `forgottenhall/prepare_fight.png`是“剩余轮”文字，`purefiction/prepare_fight.png`是灯泡图形，不能单独证明战斗、上下半或完成。
- `back`／`again`为对应返回／再次挑战文字；`pause`呈交叉兵刃图形。文件名不构成当前页面或动作语义授权。
- `star.png`是17×17黑白星形；源`MemoryOfChaos.judge_stars`另按金色像素筛选并在层号起点的120×120范围数星。没有独立零星、空槽、锁定、选中和完整结果原件。
- `screen/forgottenhall/memory_of_chaos.png`是完整模式局部标识，仍需当前OCR及其它页内关系补证，标题单独不能授权输入。

## 本轮模块与API

[challenge_pages.py](../../../../autohsr/challenge_pages.py)只读取新鲜Scene；`observe(scene, confidence=.65)`返回冻结`Observation(kind, mode, level, half, stars, targets, basis)`，`target(scene, "select_level", confidence=.65, level=N)`重新推导唯一层号Token或返回`None`。模式采用`memory_of_chaos`／`pure_fiction`／`apocalyptic_shadow`命名，本轮只有第一种有限观察；另两种及未知页面均不生成目标。

主页须同时有原完整模式局部图与一致OCR、独立`N/36`字段及至少两份不重复的两位层号，且层号在上游关卡区域内。逐层星形从该层号单独限定范围读取；只采用原始星形与原固定金色规则的正匹配，不把未见星形补为0。只有独立正星条的层号可能成为选层导航目标，不能据此授权开战；`available`仍为未知。重复、重叠、裁边、总星数冲突、暗淡、锁定、支付／退出／加载或其它玩法冲突均阻止相应观察或目标。

主页列表中的第一项不等于当前选中层。`Observation.level`只来自独立完整“第N层”字段；`basis.levels`分别保存列表层号与星形来源。没有当前层证明时`level=None`，没有正星来源时该行`stars=None`。`half`始终未知，不能从数字队伍标识推断上下半。匿名basis只记录原件SHA-256、匹配范围／分数、字段范围及有限关系，不包含UID、原始日志、私人截图或账号值。

备战观察须有当前独立层号、对应模式文字／原件，以及相互关联的两队数字、重置／交换图形组；它只返回`team_setup`，`team_feedback="unknown"`且`execution_supported=false`。没有任何重置、交换、角色、秘技、攻击、开战、返回、领奖或结果确认目标。原件与完整页锚不够时返回`unknown`，不借用差分或通用页面授权。

## 角色参考与验证限制

已有[105幅支援头像](../support/sources.json)来自同一固定`share/character/`原件；逐条Git blob与现有文件SHA已复核，另实际查看黄泉／黑塔原件作图形核对。它们可作为以后候选身份参考，本轮没有复制该素材或调用支援好友行定位，也没有把头像命中当角色可用、选中或已加入本队。完整两队名单编队虽已获用户允许，但其当前页面与选中反馈尚缺来源，本模块不提供选角闭环。

[首轮13项纯Scene／合成图检查](../../../../autohsr/tests/test_challenge_pages.py)通过（4.783秒）；审查后纠正原件父标题／引号识别，区分冲突与缺失层标题，且采集到的锁定／模态提示先于严格正锚筛选，18项检查通过`runs/challenge-pages-reviewed.log`（9.093秒）。夹具`lobby_scene(levels=(1,2), stars=..., total=..., selected=...)`及`setup_scene(level=...)`使用上述原始局部图和人为构造的OCR／布局，只验证关联、未知门禁与源哈希，不是真实页面样本或独立留出。素材／纯观察专项没有运行Runner、项目CLI或游戏；整合检查另见[高难说明](../../../../docs/challenges.md)。

仍缺完整真实混沌主页与备战页、当前层数显示、零星／锁定、选中／已选四人／角色禁用、上下半、战斗及胜负结果的独立校准。保守规则可能无法识别当前客户端；本轮只能声明有限观察机制与来源记录，不能声明真实准备路径或完整挑战已验收。
