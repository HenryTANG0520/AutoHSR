# 旅情事记与巡星之礼观察

AutoHSR 的独立读取覆盖简中 4.6.0 手机里的「旅情事记」和其中「巡星之礼」的七日签到版式。可在桌面「设置 → 工具 → 日常页面核对」选择巡星之礼，或在游戏已处于前台时运行 `--daily-reward-observe odyssey`。任务流的 `workflow_open_page` 另提供 `target: odyssey`。当前账号实际到页、领取和到账仍待实机验证，领取尚无正式入口。

正式入口从当前 StarRail 进程的安装配置核对版本。连续两份独立新画面必须属于同一窗口、账号和输入代次。报告保留匿名页面和日期列表。缺读或冲突的日期归为未知，只有双帧都核实七张均已领取时才输出 `claimable_state=none`。共享锁重试会重新核实窗口和安装配置，发布前失焦、超时或停止会撤回观察结论。

## 固定上游范围

在 March7thAssistant 固定提交 `7cf6c6bed474539485d3b1504077ac352866829f` 中，活动任务通过 `activity` 页面查找活动列表。签到开关控制「巡星之礼」「巡光之礼」「庆典祝礼」，专用类在选中活动后查找三类领取图标。花藏繁生、异器盈界和位面分裂读取双倍次数并转入刷本，使用另一组开关。[活动任务](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/activity/__init__.py) · [签到类](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/activity/checkInactivity.py) · [配置](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/config.example.yaml#L175-L183)

活动日历提醒在「奖励指南」取图并拼接发送。普通奖励任务分别处理邮件附件和每日实训活跃。「银河信号漫游」作为自定义半自动流程示例发布，含无限循环、模板点击和人工提醒。[活动提醒](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/activity/journey_highlights_notification.py) · [邮件](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/reward/mail.py) · [实训](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/tasks/reward/quest.py) · [示例](https://github.com/moesnow/March7thAssistant/blob/7cf6c6bed474539485d3b1504077ac352866829f/assets/config/workflows/cosmic_data_roaming/workflow.yaml)

## 4.6 原始证据

官方版本公告将「巡星之礼」列为累计七天登录奖励，累计发放十张星轨专票；同版本「游园伴手礼」单列六张潮玩礼券。「镇伏『贪饕』，汇聚愿力」另有进度与奖励条件。[4.6 版本公告](https://hsr.hoyoverse.com/zh-cn/news/166468)

手机使用项目内已有 1920×1080 的 [4.6 脱敏夹具](../autohsr/tests/fixtures/du_runtime/phone_mail_icon.json)，PNG 的 SHA-256 为 `c4523eacc8d009fea596110d0da3fdcfac56c472d1b94d80537e6401c4af4517`。同帧可读「旅情事记」「商店」「合成」，并能独立核对整块手机图标布局。这里的手机帧和下面的签到帧来源不同。

签到使用星阳希公开的 [4.6 活动实录 P5](https://www.bilibili.com/video/BV1JZaV6XEH3/?p=5)。本次取用无需登录的 640×360、30 fps 播放版本，共 24,208,105 字节，SHA-256 为 `8b81a95fa3f001175c3ff7d6193016824810c41ae9f058499d81ade79d3fb480`。作者简介注明公开素材可取用，画面中的游戏美术归 HoYoverse。仓库记录时间、摘要和识别规则，测试使用已有脱敏夹具及合成对照。

| P5 时间 | 同帧所见 | 原解码 BGR SHA-256 |
| --- | --- | --- |
| 126.5 秒 | 「巡星之礼」面板。第一至三天暗卡带勾，第四至七天白色按钮 | `925b5124f7599bb6b91f7ced031ba12a6c7d1f51a7083ea7f65562b0e5111b8b` |
| 129.0 秒 | 第四天转为暗卡带勾，第五至七天可见领取按钮 | `d3824fd9398ce6e519067d4fce39eb9adc95e2fa89858904150f49a46fe8ecee` |
| 130.5 秒 | 第五天转为暗卡带勾，第六、七天仍可领取 | `c31423a6e6227081cdb37c63f109f5c9ba56e70b6c0d3d1125bac3fa4aea388a` |
| 133.0 秒 | 第七天仍可领取，其他卡已转暗 | `44440c423890c88923a00ae36537ac0f83bff700960a7f3e6afd1f237670ac3f` |
| 135.0 秒 | 独立「获得物品」弹窗显示三张星轨专票，背景模糊 | `a1799e8a4edb8cc591f84b2b961dd616f36e790834283b5a400c5d726ed67f05` |
| 136.5 秒 | 返回签到原页，七卡均暗且可见勾标 | `1b32581b42da2944728098f413508cb1a39e93f808040d433551aa7054f9f505` |
| 138.0 秒 | 切到星际幻宠乐园，同框出现独立「游园伴手礼」和「立刻领取赠礼」 | `75b1067591c58b81daf2d9cd14bda9c21def9841e31ecda88473bbb0b8e80e58` |

复放按上述时间乘 30 取帧索引，先计算原始 BGR 字节摘要，再遮盖底部 6%。分别在原图和以三次插值等比放大的 960×540 整帧运行正式 `Vision(.65)`。画面门禁使用 960×540 图。两种 OCR 输入都读到 126.5 秒可领第 4、6、7 天，128.5／129.0 秒可领第 5、6、7 天，130.5 秒可领第 6、7 天，133.0 秒可领第 7 天。126.5 秒画面上第 5 天可见，正式读数保留未知。136.5 和 137.0 秒没有可领读数，低清画面中仍有多卡未读全。108.0 秒的贪饕页、125.5／131.5／135.0 秒的奖励叠层和 138.0／139.0 秒的幻宠邻页均返回无该签到页。

## 读数接口

[识别模块](../autohsr/daily_event_pages.py) 的 `phone_journey_event_entry(scene, client_version='4.6.0')` 返回原始手机图标文字 Token。图标须处于完整手机布局的对应位置，同排合成和上方商店均有正向读数。版本不符、遮挡、移位或重复文字时返回 `None`。

`read_gift_of_odyssey(scene, client_version='4.6.0')` 核对右侧活动标题、活动说明、左上活动札记及卡片分隔线，再分别读取七个卡位。每个可领日需要本格的完整「领取」文字与浅色按钮一致。每个已领日需要本格的完整「已领取」文字与暗态一致。低清 OCR 对两个栏目文字的实际错字仅作为其固定位置的辅助读数。结果按 `claimable_days`、`claimed_days` 和 `unknown_days` 分列，空的可领列表只能表示本帧没有核实到可领卡。整个页面不明时返回 `None`。[正反例](../autohsr/tests/test_daily_event_pages.py)

当前证据只覆盖一次公开录屏的已解锁与已领取状态。尚需用本机同账号、同版本连续画面核实入口到页、未解锁卡、原生输入前后的来源和逐笔到账。邻页礼券、其他签到标题及双倍活动继续各自核实。

## 独立导航

在任务流的可视编辑中选择「切换到游戏页面 → 巡星之礼」。手机点击使用双帧一致的「旅情事记」图标文字。进入活动后，左栏必须找到唯一巡星之礼横幅，且顶部同时核实奖励指南徽章和文字条。横幅位置随列表滚动变化。已在巡星之礼时直接核实到页，找不到横幅时保留当前画面。流程不点奖励卡、不会自动滚动或重发原点击。

源客户端固定校准到 4.6.0。发送前、到页和提交报告均重核窗口、账号、输入代次、安装来源及版本。P5 的 108.0 秒取三个最小模板，122.5 秒和 90.0 秒是同次录屏不同列表位置的复放，127.9 秒是奖励叠层反例。到页与两次导航发送使用正式任务流 CLI 和假窗口核对。[素材裁剪与摘要](../assets/ATTRIBUTION.md#2026-11-07-巡星之礼活动导航)
