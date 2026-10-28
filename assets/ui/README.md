# 星际和平指南 UI 素材

2026-10-28，按用户要求使用游戏实际素材细化桌面界面。参考为本地保存的简体中文《崩坏：星穹铁道》4.6.0「每日实训」「生存索引」「旷宇纷争」实机画面；原始3840×2160帧先按1920×1080坐标面归一化。原始截图保持在忽略目录，不在本目录分发。

## 内容与复现

| 文件 | 来源与处理 |
| --- | --- |
| `guide-mark.png`、`guide-seal.png`、`tab-*.png` | 指南标记、封面星球徽记与五个页签图标，静态区域裁切并提取透明蒙版，运行时按选中状态着色 |
| `activity.png`、`reward-check.png` | 活跃标记、已领取勾选图标，排除数字和文字 |
| `card-watermark.png` | 任务卡淡色水印，亮度蒙版排除任务文字 |
| `card-footer.png`、`paper-pattern.png` | 卡片底纹与书页地图纹样；底纹的原按钮文字以颜色蒙版、膨胀和局部修补移除，由实时按钮文字替代 |
| `guide-charm-*.png` | 左侧花饰与右侧猫、菊花挂饰，沿轮廓制作蒙版 |
| `stamina.png` | 原样复用既有`templates/planar_stamina_cost_single.png`，来源记录仍保留 |
| `reward-gift.png` | 从既有`templates/daily_reward.png`裁出礼物，排除通知角标；上游来源见[总署名](../ATTRIBUTION.md) |
| `hsr-sc.ttf` | 客户端`StreamingAssets/MiHoYoSDKRes/HttpServerResources/font/zh-cn.ttf`原样复制，内部家族名`SDK_SC_Web` |

[sources.json](sources.json)逐项记录来源、源文件SHA-256、归一化坐标、变换、输出SHA-256及权利信息。没有包含UID、账号指纹、安装绝对路径或完整游戏画面。运行时只加载这些静态资源，不读取游戏安装目录。

可用[prepare_guide_assets.py](https://github.com/HenryTANG0520/AutoHSR/blob/main/tools/prepare_guide_assets.py)的`--daily`、`--guide`、`--universe`、`--font`参数提供对应本地原始文件，重新生成素材。字体采用进程私有注册，不安装到Windows字体目录；Pillow绘图也使用同一字体文件。

## 版权与许可

游戏美术、名称与商标归HoYoverse及其相应权利人所有。字体保留原始name/copyright/license表，版权字段为`(c) Copyright 2013-2022 Beijing Hanyi Innovation Technology Co.,Ltd`，许可相关字段指向`http://hanyi.com.cn/law.php`。未修改、重命名字体内部信息或将其声明为开源字体；随客户端提供这一来源事实不代表额外的再许可授权。

上述第三方美术与字体不适用AutoHSR原创代码的GPL-3.0-only声明。新绘图代码和素材准备脚本仍按仓库代码许可提供，来源署名不构成对第三方资产的所有权或额外使用许可。

## 交互与核对边界

指南外框、纸纹、卡片、胶囊按钮、文字和实时状态由代码重绘；图标与挂饰来自上述参考。默认窗口16:9，小窗口重新排布任务卡；工作流表单与底部运行控制对应AutoHSR功能。界面不会用参考截图中的已领取状态冒充当前结果，只有本次报告明确核实后才点亮五档奖励。

2026-10-29，输入框、勾选框、下拉箭头、次数微调和滑条改为指南配色的代码绘制控件，保留Tk的输入、选择与键盘操作；输入字体统一为同一私有字体。新增的是代码绘制状态，没有新增或替换来源清单中的第三方素材。禁用、勾选、鼠标悬停和键盘焦点分别显示，100%、150%、200%下核对控件操作与最小窗口布局。

已按静态参考逐项核对字体、标记、页签、挂饰与控件布局；重绘几何、窗口响应布局和应用专属表单不宣称与整个游戏画面逐像素完全一致。
