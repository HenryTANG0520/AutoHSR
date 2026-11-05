# 固定挑战局部图与有限准备观察

参考版本为 March7thAssistant `7cf6c6bed474539485d3b1504077ac352866829f`，作者为 moesnow 及其贡献者。19 幅页面局部图与 4 幅结算反馈局部图逐份核对固定提交的 Git blob、字节数、尺寸与 SHA-256，均保留原始字节。游戏美术归 HoYoverse 及相应权利人。[原路径、哈希和用途](sources.json) · [GPL v3 原许可](../LICENSE)

## 原件实际能证明什么

- `forgottenhall/team1.png`／`team2.png`只是带链纹的数字1／2，不含角色已选、禁用或四人完整反馈。
- `forgottenhall/start.png`只是`「混沌回忆」`文字，`start2.png`为`「回忆」`，不是完整按钮可用态。
- `forgottenhall/prepare_fight.png`是“剩余轮”文字，`purefiction/prepare_fight.png`是灯泡图形，不能单独证明战斗、上下半或完成。
- `back`／`again`为对应返回／再次挑战文字；`pause`呈交叉兵刃图形。文件名不构成当前页面或动作语义授权。
- `star.png`是17×17黑白星形；源`MemoryOfChaos.judge_stars`另按金色像素筛选并在层号起点的120×120范围数星。没有独立零星、空槽、锁定、选中和完整结果原件。
- `screen/forgottenhall/memory_of_chaos.png`是完整模式局部标识，仍需当前OCR及其它页内关系补证，标题单独不能授权输入。
- `screen/purefiction/purefiction.png`含蓝色菱形及「虚构叙事」文字。`purefiction/star.png`为 13×13 的亮点轮廓，按上游颜色过滤并绑定独立层号，用于证明历史正星。
- `purefiction/start.png`是「进入故事」局部图，用于备战页互证。`purefiction/start_story.png`是周期弹窗的「开启故事」局部图，仅用于阻止自动选层。
- `screen/apocalyptic/apocalyptic.png`含沙漏和「末日幻影」标题，只作末日主页与已挑战关卡详情互证。
- `purefiction/back.png`显示「返回虚构叙事」，`apocalyptic/back.png`显示「返回末日幻影」，`apocalyptic/next_node.png`显示「前往节点二」。三个原件只支持各自的可见控件，后者记录文字所指去向。`purefiction/fail.png`只裁红色「败」字，虚构与末日可在模式已核实的画面中独立记录此标记。当前缺完整结算、分数或星数来源。[结算观察](../../../../docs/challenges.md#独立结算观察)

## 本轮模块与API

`observe(scene, confidence=.65)`读取新鲜 Scene 并返回`Observation(kind, mode, level, half, stars, targets, basis)`。`target(scene, "select_level", confidence=.65, level=N)`重推混沌或虚构的唯一层号 Token。末日主页、详情、双节点备战都只观察，目标列表为空。[页面实现](../../../../autohsr/challenge_pages.py)

混沌主页用完整图文、独立`N/36`与关卡组互证，虚构主页用完整图文与互不重叠的`01`～`04`关卡组互证。两者分别使用自己的源星形与固定金色规则。正星与目标层号独立绑定，未读星数及当前可用性保持未知。模态、锁定、加载或其它玩法冲突优先阻断选层。[高难说明](../../../../docs/challenges.md)

主页列表中的第一项不等于当前选中层。`Observation.level`只来自独立完整“第N层”字段；`basis.levels`分别保存列表层号与星形来源。没有当前层证明时`level=None`，没有正星来源时该行`stars=None`。`half`始终未知，不能从数字队伍标识推断上下半。匿名basis只记录原件SHA-256、匹配范围／分数、字段范围及有限关系，不包含UID、原始日志、私人截图或账号值。

混沌与虚构备战用各自的文字图、两队编号和对应控件互证。`team_setup`的`team_feedback`始终为`unknown`。虚构缺少独立层标题时仍可观察备战页，原生任务需在同账号连续两帧各自核实计划目标层。末日的节点名称与重置只支持节点布局，当前节点与槽位仍待校准。[高难说明](../../../../docs/challenges.md)

## 角色参考与验证限制

已有[105幅支援头像](../support/sources.json)来自同一固定`share/character/`原件；逐条Git blob与现有文件SHA已复核，另实际查看黄泉／黑塔原件作图形核对。它们可作为以后候选身份参考，本轮没有复制该素材或调用支援好友行定位，也没有把头像命中当角色可用、选中或已加入本队。完整两队名单编队虽已获用户允许，但其当前页面与选中反馈尚缺来源，本模块不提供选角闭环。

[首轮13项纯Scene／合成图检查](../../../../autohsr/tests/test_challenge_pages.py)通过（4.783秒）；审查后纠正原件父标题／引号识别，区分冲突与缺失层标题，且采集到的锁定／模态提示先于严格正锚筛选，18项检查通过`runs/challenge-pages-reviewed.log`（9.093秒）。夹具`lobby_scene(levels=(1,2), stars=..., total=..., selected=...)`及`setup_scene(level=...)`使用上述原始局部图和人为构造的OCR／布局，只验证关联、未知门禁与源哈希，不是真实页面样本或独立留出。素材／纯观察专项没有运行Runner、项目CLI或游戏；整合检查另见[高难说明](../../../../docs/challenges.md)。

虚构与末日专项的正例使用原件拼图及合成 OCR，历史脱敏饰品编队只作反例。三种模式仍缺完整实机备战正例，虚构缺实际层标题和空队、禁用态，末日缺首次详情、当前关卡与选中节点。选角槽位、角色可用、上下半和结果各自需要独立校准。[专项测试](../../../../autohsr/tests/test_challenge_modes.py)
