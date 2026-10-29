# AutoHSR 0.1 验证记录

## 2026-10-29：就地调整挑战设置并保留副本上下文

在`feee947`、独立配置与假后端下核对：打开“挑战设置”会隐藏整张副本列表，预算区与次数区之间留下大片空白，Esc不能返回；未加入时还重复显示“副本挑战未启用”。原图及状态为`runs/challenge-inline-before.png/json`。只读参考AutoZZZ本地`338951d`的直接操作、草稿与显式保存边界，未修改其工作区。

现在预算、支援和次数预设在列表下方展开；分类切换、搜索及选用副本保留展开状态，目标、费用和列表同时可见。“收起设置”与Esc返回原入口；打开设置选中预算，手动填写选中副本名，方便直接替换。搜索有内容时Esc先清空，手动下拉框先收起；运行期间返回不解锁编辑，焦点移至可用导航。“读取游戏目录”移到手动填写，只有显式点击才采集。移除未加入的重复警告，保留未加入状态、本次不刷本、支援关闭、沉浸器和已有资源边界。与原始相同未加入配置的对照为`runs/challenge-inline-after-matched.png/json`；最小1100×800窗口的已加入场景仍完整可见两条副本，见`runs/challenge-inline-minimum.png/json`。

**667项离线检查通过**：84项就地设置、272项生存索引、64项未加入配置保存与重开、55项输入纠错、108项缩放、84项GUI。新检查覆盖100%、125%、150%、200%，核对单次选择形成含目标、预算、次数与支援的运行快照，搜索和菜单的Esc层级、错误字段定位、窗口缩放及缓存复用、运行锁定与配置未写入；目录按钮仅截获派发，不运行采集。汇总`runs/challenge-inline-verification-summary.json`，逐项结果与日志为`challenge-inline-final-*`和`challenge-inline-verified-*`。

首轮输入纠错在`stamina_limit_focus_abc`出现一次焦点断言失败，保留`runs/challenge-inline-final-input_feedback_smoke.log`。加入诊断的独立复现、原脚本复跑及后续整合均通过55项（`challenge-inline-focus-probe.log`、`challenge-inline-focus-recheck.log`、`challenge-inline-verified-input_feedback_smoke.log`），没有为通过该断言修改生产逻辑或放宽检查；瞬态原因尚未核实。全程未操作游戏；整体逐像素一致性、玩家体验及日常周常组合实机仍未验收。

源码`357da46`已构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/challenge-inline-build.log`。使用独立配置、`--no-admin-launch`从首页“更换副本”进入，打开挑战设置后直接输入`abc`替换240；点击保存被整数校验阻止，字段重新选中，接着直接输入120即可纠正。切到侵蚀隧洞并选密伶之径／生研院，设置保持展开；点击填满预算得到3次／预计120开拓力，关闭支援后显示对应提示。Esc收起后，空格从返回的焦点重新打开，保留目标、次数、预算与支援；关闭时选择不保存。未点击任务执行或目录读取入口。原生截图`runs/challenge-inline-package-{opened,error,corrected,ready,collapsed,reopened,close-prompt}.png`保留各阶段。

窗口退出码0，独立配置与原有239份用户文件哈希不变；147项素材、5份清单及23份上游文件一致。EXE SHA-256为`ecba831018e5acee3f3af14fa00e936622449aab50e8b542e637b3e614f12358`，用户文件恢复副本为`build/userdata-challenge-inline-20261029_172228/`；详见`runs/challenge-inline-package-verification.json`。本轮全部证据归档至正式项目`runs/challenge-inline-*`，索引`runs/challenge-inline-evidence-archive.json`。关闭草稿的确认框仍为系统样式，是后续视觉一致性待处理项；本轮未将它算作已对齐。

## 2026-10-29：生存索引双行分类卡与游戏顺序

继续只读对照AutoZZZ本地`338951d`的导航、运行锁定与显式保存交互，未修改其工作区。界面依据既有4.6生存索引参考`runs/survival-layout-reference.png`及2026-10-20目录采集的分类OCR，恢复“分类名＋材料类型”、深底金色选中态、侧边标记和淡色徽记。六类按饰品提取、拟造花萼（金）、拟造花萼（赤）、凝滞虚影、侵蚀隧洞、历战余响排列；只调整显示顺序，不改工作流扫描顺序。复用已署名字体与水印，没有新增游戏截图或素材。

与`53c6f04`在相同1920×1080、125%界面比例下对比，分类卡从385×71变为386×102，六张等高并占用原来的空白区域；右侧列表仍高442、完整可见3行。分类标题与材料名分层显示，保留原生鼠标、空格、焦点和禁用反馈。浏览不改计划目标，只有列表选用才更换或加入任务。前后截图及尺寸记录为`runs/survival-categories-before.png/json`、`survival-categories-after.png/json`。

**611项离线检查通过**：272项生存索引、108项缩放、24项布局复用、123项缩放过渡、84项GUI。分类卡检查覆盖100%、125%、150%、200%，包含原生点击及空格切换、唯一选中态、运行禁用与恢复、最小窗口六类完整可见、草稿不变和配置未写入；沿用同名副本地点、半露行、次数限制和费用反例。最终生存索引结果位于`runs/survival-categories-ui-final/`，其余结果与日志为`survival-categories-final-*`，汇总`runs/survival-categories-regressions.json`。最后字号调整后重跑生存索引，不重复计算检查数。全程使用假后端，不启动游戏。整体逐像素一致性、玩家体验及日常周常组合实机仍未验收。

源码`35b248b`经`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，构建日志`runs/survival-categories-build.log`。原生窗口使用独立配置与`--no-admin-launch`，核对六类完整显示、点击饰品提取与历战余响、打开设置后Esc返回保留分类；目标仍为原来未加入的回忆之蕾／城郊雪原，未点击任务执行入口。正常关闭退出码0，独立配置及原有239份用户文件哈希不变。截图为`runs/survival-categories-package-browser.png`、`package-planar.png`、`package-returned.png`、`package-echo.png`（后三项同`survival-categories-`前缀），记录`runs/survival-categories-package-verification.json`。

147项素材、5份清单和23份上游文件与源码一致；用户文件恢复副本位于`build/userdata-survival-categories-20261029_165309/`。EXE SHA-256为`78ab73bb3a3d2416b833efeeae683f1970c1d4658c483c663b8b74e144932223`。本轮对照、离线与原生核验证据归档至正式项目`runs/survival-categories-*`，索引为`runs/survival-categories-evidence-archive.json`。

## 2026-10-29：保存与重开保留未加入的副本设置

只读核对AutoZZZ本地`338951d`的草稿与显式保存流程，未修改其工作区。在AutoHSR `ea08b1b`用假后端复现：选“侵蚀隧洞／密伶之径／生研院”、3次、120开拓力、关闭支援后取消加入，点击保存会还原成回忆之蕾／城郊雪原及240预算，界面却标记已保存；类别和次数仍留在新值，磁盘则保留旧类别、次数与支援选项。原始记录`runs/excluded-draft-before.json`，未启动游戏。

显式保存现在收集已授权副本的全部设置，与是否加入任务分别保存。空闲时未加入的副本也可修改次数、预算、手动目标和支援，预设仅填写表单；保存后重新打开仍保持目标与关闭状态。无效值按既有校验定位可修改字段，不替用户开启任务。运行、检测、仅补领奖保持快照与不保存约定，未启用副本的未完成输入不阻塞无关操作；运行中或未授权时仍锁定编辑与加入。

新增64项保存与重开检查通过，覆盖100%、125%、150%、200%：完整目标与支援持久化、重开前后关闭状态、非法次数／超预算／非法预算纠错、预设不加入、显式重新加入、运行及授权反例。结果与截图为`runs/excluded-draft-ui/`，日志`runs/excluded-draft-verified.log`。初次测试在清理窗口时统一取消了其他控件拥有的回调，导致销毁时重复删除Tcl命令；清理现只取消根窗口自己的队列轮询，其余控件自行销毁，原日志`runs/excluded-draft-initial.log`保留，没有为此修改生产界面。

另有228项生存索引、42项原生表单、225项设置、55项输入纠错、108项缩放、24项计划、84项GUI检查通过，合计**830项界面检查通过**。各脚本独立进程顺序运行，日志为`runs/excluded-draft-final-*.log`，汇总`runs/excluded-draft-regressions.json`。生存索引原有禁用状态断言改为对应“空闲未加入仍可编辑”的交互；运行锁定和未授权反例保留。

本轮未新增界面解释段落，没有启动、检测或操作游戏。整体视觉一致性、玩家体验与日常周常组合实机仍未验收。

源码`c9d17ce`经`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/excluded-draft-build.log`。使用独立配置和`--no-admin-launch`，通过原生鼠标与键盘选定密伶之径／生研院，取消加入，再改为3次、120开拓力上限、关闭支援并点击保存。窗口显示“已保存”且目标不变；磁盘全字段与预期一致。正常关闭、重新启动同一配置后，首页显示该副本未加入，生存索引与挑战设置保留上述值；再次关闭，两次退出码均为0，重开阶段配置哈希不变。截图为`runs/excluded-draft-package-count.png`、`package-before-save.png`、`package-saved.png`、`package-reopened-home.png`、`package-reopened-browser.png`、`package-reopened-settings.png`（后五项同`excluded-draft-`前缀）。

239份原有用户文件哈希不变，147项素材、5份清单和23份上游文件与源码一致；记录`runs/excluded-draft-package-verification.json`，备份`build/userdata-excluded-draft-20261029_162044/`。最终EXE SHA-256为`789386f23c21cb837cbd54c40a730853524527e6d78fa40da8bc146389cd6cfc`。本轮原始与最终证据归档至正式项目`runs/excluded-draft-*`；保存操作仅作用于独立核验配置。

## 2026-10-29：浏览副本后一键加入计划

继续只读参考AutoZZZ本地`b197004`的导航和直接动作入口，未修改其工作区。在AutoHSR `b714457`、独立配置和假后端下复现：关闭副本任务后，分类、搜索和列表一起锁定，但费用仍显示预计240开拓力；证据为`runs/dungeon-join-before.json/png`，配置字节未变，未启动游戏。

现在已授权、空闲的用户可先浏览六类副本；分类、搜索、方向键不修改草稿。未加入时每行显示“加入计划”，完整行点击或Enter同时选定分类、名称、地点并加入副本；次数按目标类别限制，首页与费用同步更新。半露行第一次点击只展开。取消加入后保留当前草稿目标、显示“本次不刷本”，重新勾选可恢复；手动字段和次数仍需加入后才能编辑。运行中与未授权时保持锁定，不隐式保存、启动或扩大资源授权。

**871项界面检查通过**：212项生存索引、42项原生表单、225项设置、121项任务入口、55项输入纠错、108项缩放、24项计划、84项GUI。新增检查覆盖100%、125%、150%、200%，验证六类浏览、同名地点、半露行、Enter加入历战余响后的3次／90开拓力限制、重新勾选、运行锁定和授权反例。日志为`runs/dungeon-join-ui-verified.log`与`dungeon-join-final-*.log`，汇总`runs/dungeon-join-regressions.json`；截图及逐项结果位于`runs/dungeon-join-ui/`及各`dungeon-join-final-*`目录，各脚本独立进程顺序运行。

初次新增检查把“未启用副本的运行快照”与当前未保存目标混为一谈，触发断言；既有读取逻辑只在副本启用时复制目标。检查现分别核对当前草稿保留目标、运行快照不含副本和显示不刷本，原失败`runs/dungeon-join-ui-initial.log`保留，没有改变配置读取或保存逻辑。原生表单禁用检查也改为核对实际点击的副本开关，不再误比邮件开关。

本轮未增加解释段落，没有启动、检测或操作游戏。整屏视觉一致性、玩家体验与日常周常组合实机仍未验收。

源码`c546ebf`经`tools/build.ps1`构建并更新正式目录，使用独立的副本未启用配置和`--no-admin-launch`核验：分类、搜索不加入任务；点击“加入计划”后显示回忆之蕾／城郊雪原、24次、预计240开拓力，首页同步为3项；取消后恢复2项、不刷本。未点击开始、检测或保存，正常关闭退出码0；239份用户文件及独立配置哈希未变，147项素材、5份清单与23份上游文件一致。证据为`runs/dungeon-join-package-*.png`、`dungeon-join-package-verification.json`、`dungeon-join-build.log`；备份`build/userdata-dungeon-join-20261029_155458/`。该次EXE SHA-256为`4ca3f73c06e6ca1fce7ce2f3d277f32a344916be72cf6261295630348c0ce5fb`。

上述实际窗口发现另一个显示问题：以副本未加入的配置首次打开时，次数框为24，滑块仍在最小位置，加入后也未同步。独立诊断`runs/dungeon-join-slider-before.json`确认滑块实际值为0，取消加入后才更新为24；原截图保留。原因是禁用的`ttk.Scale.set`忽略赋值，刷新发生在启用控件之前。现在通过控件配置同步显示值，不触发选择动作或改动草稿；首次打开、加入和返回页面增加数值与滑块实际位置检查。

滑块修正后，228项生存索引检查通过；针对受影响的原生控件、输入纠错、缩放与计划又分别运行42、55、108、24项，合计457项通过。新增16项为四种比例下的首次禁用显示、实际滑块位置、首次加入和返回，原有212项选择检查一并通过。结果为`runs/dungeon-join-slider-ui/result.json`和`dungeon-join-slider-regressions.json`，日志`dungeon-join-slider-ui.log`及`dungeon-join-slider-final-*.log`；没有重复运行不受此次显示修正影响的其他项目。

最终源码`cfa522d`再次构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`。独立配置下，实际窗口首次打开未加入副本、点击加入、从首页“更换副本”返回时，24次与最右端滑块均一致；取消后显示本次不刷本，未保存或执行任务，正常关闭退出码0。239份用户文件及独立配置哈希仍不变，147项素材、5份清单、23份上游文件复核一致；记录`runs/dungeon-join-slider-package-verification.json`，截图`dungeon-join-slider-package-browser.png`、`package-selected.png`、`package-home-selected.png`、`package-return.png`、`package-removed.png`（后四项同`dungeon-join-slider-`前缀），构建日志`dungeon-join-slider-build.log`。备份`build/userdata-dungeon-join-slider-20261029_160411/`，最终EXE SHA-256为`5b9c9e60bf72c6af73ee9634c9eaf13b089ff12fefa451f94c01a412dddbab97`。本轮原始与最终证据归档至正式项目`runs/dungeon-join-*`，未替换失败记录。

## 2026-10-29：玩法设置与结果返回原入口

继续按AutoZZZ的明确动作与原操作保留方式核对，阅读基线为本地`b197004`的桌面与详情代码，未修改其工作区。在AutoHSR `bcdf9a1`、临时配置和假后端中复现：差分／货币战争两种玩法进入设置或结果时，焦点留在已隐藏入口，Esc不返回；鼠标返回后焦点也留在隐藏的返回按钮。四条路径的原始结果见`runs/mode-navigation-before.json`，配置未变，后端调用为0。

现在用户打开演算设置后直接聚焦局数，开发工具聚焦分类栏，结果页聚焦可翻阅的记录；点击返回或按Esc回到原入口按钮。下拉菜单与独立详情窗口先处理自己的Esc；从通用设置返回玩法编辑页后，再按一次Esc才回玩法入口。草稿、文本选择、开发分类和结果滚动位置保持，执行中返回不停止或解锁。只有用户导航请求安排默认焦点，自动结果更新、错误定位和缩放恢复不额外抢焦点；快速切换页面后取消旧目标的聚焦。

新增**156项导航检查通过**，覆盖100%、125%、150%、200%，包括鼠标返回、连续Esc、下拉菜单、PageDown、错误字段、独立窗口、快速切页和执行锁定。日志`runs/mode-navigation-verified.log`，结果与截图位于`runs/mode-navigation-ui/`。初次检查直接给尚未映射的隐藏字段设置焦点，Windows未接受该焦点；`runs/mode-navigation-focus-timing.json`记录映射前仍在入口按钮，映射后转至默认局数。专项改用真实`_input_failed`字段定位流程及映射后的导航回调核验，原失败`runs/mode-navigation-initial.log`保留，没有为此改变生产焦点逻辑或放宽最终焦点断言。

既有112项玩法入口、225项设置、55项输入纠错、108项缩放、24项计划和84项GUI检查通过，本轮合计**764项界面检查通过**，各脚本独立进程顺序执行。日志为`runs/mode-navigation-final-*.log`及`mode-navigation-verified-ux_smoke.log`，各输出目录保留截图与结果。批次包装器首次为GUI脚本指定新截图目录时漏建目录，原`mode-navigation-final-ux_smoke.log`保留；创建专用输出目录后单独重跑该脚本通过，没有修改生产代码或重复已通过项目。

本轮没有新增界面提示段落，没有改变开始、保存、暂停、停止或资源授权。未启动、检测或操作游戏；整屏一致性、玩家体验与日常周常组合实机仍未验收。

源码`42c37ab`经`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/mode-navigation-build.log`。独立配置、`--no-admin-launch`下，原生鼠标打开演算设置后不按Tab，直接按Down即可展开局数；第一次Esc收起下拉框、保持原3局，第二次Esc返回玩法入口。再打开结果，Esc同样返回。没有选择新值、保存、检测或执行任务；标题栏关闭后退出码0。截图为`runs/mode-navigation-package-home.png`、`package-editor.png`、`package-choice.png`、`package-choice-closed.png`、`package-return.png`、`package-result.png`与`package-result-return.png`（后六项均同`mode-navigation-`前缀）。239份用户文件及独立配置哈希不变，147项UI素材、5份清单及23个上游文件与源码一致；记录`runs/mode-navigation-package-verification.json`，备份`build/userdata-mode-navigation-20261029_152908/`。EXE SHA-256为`47e3f04f6393f76783f5c867496e7eae88a98f18d63b4a5ab46024779a3cf2b9`；本轮证据归档在正式项目`runs/mode-navigation-*`。

## 2026-10-29：生存索引按游戏分组浏览

只读对照AutoZZZ本地`51f236e`的页面与明确选择入口，以及2026-10-20既有CN 4.6.0生存索引采集帧。移除副本列表下方重复的委托、实训、邮件和勋礼开关，这些任务继续通过首页卡片与“每日任务”设置调整；副本自己的“加入计划”与已选目标放在同一行，原次数、费用、预算、授权与显式保存约定不变。

金色花萼按5个地区、赤色花萼按9个命途、凝滞虚影按7个属性显示灰底标题及原图标，共21组、64条已有副本归属。依据同屏标题与连续滚动帧中的重叠行核对，不按名称猜地区；本地新增条目没有分组证据时显示“其他副本”。其余40条目录仍按原列表显示。搜索可匹配分组、名称、地点，标题不承担选择动作；方向键和浏览不改计划，完整行点击或Enter才选用，半露行先完整展开。没有修改游戏执行目录或识别阈值。

从`a58b4cf`原模块和本轮源码分别运行相同假后端窗口，1920×1080、比例1.25、同一目录起点，列表宽均为911像素，高度由320增至442，完整可见副本由2条增至3条；原图与数值分别为`runs/survival-groups-before.png/json`、`survival-groups-after.png/json`。临时配置字节均未变，未调用游戏后端。这是特定窗口的前后对照，不外推为用户测试结果。

**803项界面检查通过**：144项生存索引、42项原生表单、225项设置、121项任务入口、108项缩放、55项输入纠错、24项计划、84项GUI。生存索引覆盖100%、125%、150%、200%，其他项目按各自既有比例核验；包括分组搜索、同名地点、标题非动作、半露行、未知归属、费用限制、禁用开关、手动配置、缩放恢复和原报告保留。日志为`runs/survival-groups-ui-initial.log`、`survival-groups-form_feedback_smoke.log`、`survival-groups-settings_ui_smoke.log`、`survival-groups-entry_clarity_smoke.log`及`survival-groups-final-*.log`，各脚本独立进程运行。GUI结果另归档到`runs/survival-groups-final-gui_smoke/`。

初次离线提取因部分标题OCR框包含图标而漏项，覆盖断言中止；按实际标题区域校正后完成64条映射，原日志`runs/survival-groups-preparation.log`与成功日志`survival-groups-preparation-verified.log`保留。缩放检查最初在设置页尚未显示时模拟编辑，默认入口聚焦随后把模拟焦点移到周常开关；诊断证明缩放前焦点已不在编辑框，光标与文本选择仍被保留。测试现先显示页面再模拟编辑，并新增缩放前焦点断言；原失败、诊断和trace为`runs/survival-groups-responsive_ui_smoke.log`、`survival-groups-resize-diagnostic.log`和`survival-groups-resize-trace.json`，未为此修改生产焦点逻辑或放宽恢复断言。

21幅图标已逐一查看；`runs/survival-groups-asset-verification.json`核对原图、OCR及输出哈希，分组清单SHA-256为`1359589505826ac653567b90ec856c8eed0deb75a25269e334bc06623d813532`。新增素材及复现脚本见`assets/ui/survival/groups.json`、`tools/prepare_survival_groups.py`及署名文件；原始截图与账号区域不分发。未启动、检测或操作游戏，未扩大资源授权；整屏一致性、最终玩家体验与组合计划实机尚未验收。

源码`e063dde`经`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/survival-groups-build.log`。独立配置、`--no-admin-launch`下，原生鼠标点击“更换副本”直接显示已选“回忆之蕾／城郊雪原”和雅利洛-VI分组；输入“匹诺康尼”后显示该地区三条金色花萼，原选中目标、24次和240开拓力预算不变。Esc清除搜索，再返回每日实训，原计划仍保持三项，未出现未保存改动。截图为`runs/survival-groups-package-home.png`、`survival-groups-package-selected.png`、`survival-groups-package-search.png`与`survival-groups-package-return.png`。全程未保存、检测或运行游戏。

监督脚本在界面核对期间达到360秒等待上限，原记录`runs/survival-groups-package-verification.json`保留；随后通过原生标题栏关闭助手，另确认进程已退出，但未取得助手退出码，不记录为0。补充核验`runs/survival-groups-package-final-verification.json`确认239份用户文件与独立配置哈希不变、1727个包文件与构建产物一致；其中147项UI素材、5份清单及23个上游文件与源码一致。备份`build/userdata-survival-groups-20261029_145943/`，EXE SHA-256为`14ef1584c2753c4f2748af733199e32b30fb68c56f944b9297a57039b50f13a8`。本轮失败记录、前后对照、检查与原生截图均归档到正式项目`runs/survival-groups-*`。

## 2026-10-29：启动路径错误直接定位到设置

沿用当前AutoZZZ的明确动作入口和显式保存约定，继续处理首次配置路径。原实现只在表单中检查文件名格式：路径以StarRail.exe结尾但文件不存在时，后端会报告一般失败，用户需自行找到设置。现在启动文件检查返回带字段的SettingsError，直接启动事件、普通Runner和日常／周常合并报告保留`input_error_field`；桌面在工作线程结束后打开游戏连接、选中路径，并显示必要原因。没有增加重复教程或自动打开文件选择器。

错误跳转仅接受已知字段与非空原因；未标字段、未知字段或内容恰好提到StarRail.exe的一般失败均不猜测跳转。错误处于报告中，已完成日常、费用、待核对消耗和报告保存失败继续可见；编辑只清除当前输入提示，不改写原报告、自动重试或保存配置。已有游戏窗口仍先复用，配置保存仍只检查格式，不额外检查安装文件；权限错误仍是运行错误。

新增7项后端机制回归，覆盖缺失文件、同名目录、配置可保存、已运行窗口复用、普通日常、组合计划、仅周常与权限反例。与既有启动、计划和输入结果检查合计**32项通过**，日志`runs/startup-feedback-unit-initial.log`。**27项假后端GUI检查通过**，日志`runs/startup-feedback-ui-initial.log`，截图与结果位于`runs/startup-feedback-ui/`；覆盖进入游戏、首次计划失败、日常已完成后失败、修改和返回、错误原因与原报告保留、未知字段反例，以及不额外运行或保存。

既有**55项输入纠错、225项设置、24项计划与84项GUI检查通过**，日志依次为`runs/startup-feedback-input_feedback_smoke.log`、`startup-feedback-settings_ui_smoke.log`、`startup-feedback-plan_ui_smoke.log`、`startup-feedback-gui_smoke.log`，各脚本独立进程运行。本轮界面检查合计415项，未出现回调错误。

报告字段影响普通Runner与计划，另执行1199项后端全量检查：1198项首次通过，一项旧生命周期测试的SimpleNamespace夹具缺少此前新增的周常摘要刷新方法。原失败见`runs/startup-feedback-full-unit.log`；该调用来自已有`6b56d521`，本轮未更改它。补齐夹具方法后，原“线程结束前不处理终止事件”断言保持不变，该项复查通过，见`runs/startup-feedback-lifecycle-fixed.log`。没有为此改动生产逻辑或重复其他已通过项目。

本轮不启动、检测或操作游戏；原日常周常组合实机、货币战争周常和积分奖励边界不变。玩家体验按用户安排留待开发完成后反馈，离线检查不代替体验验收。

源码`b9b8682`经`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/startup-feedback-build.log`。独立配置指向专门核实为不存在的StarRail.exe，用`--no-admin-launch`启动助手，原生鼠标打开设置、点击“进入游戏”：文件检查即阻止启动，路径自动全选，错误只在底栏显示一处；Tab到“浏览”，Esc返回首页后错误仍保留。没有执行游戏窗口检测、游戏进程启动、保存或重试；正常关闭退出码0。截图为`runs/startup-feedback-package-home.png`、`startup-feedback-package-settings.png`、`startup-feedback-package-error.png`、`startup-feedback-package-browse-focus.png`与`startup-feedback-package-return.png`。239份用户文件及独立配置哈希不变，126项UI素材、4份清单、23个上游文件与源码一致；记录`runs/startup-feedback-package-verification.json`，备份`build/userdata-startup-feedback-20261029_141933/`。EXE SHA-256为`a97bb0220e4e0167843b66d7fd416fa17a9e482227005edd9b5e56bc593a644a`，本轮证据归档在正式项目`runs/startup-feedback-*`。

## 2026-10-29：设置入口直接聚焦当前选项

以`9731bf0`为基线，用临时配置和假后端重现：从首页打开周常或设置，焦点仍在已隐藏的首页按钮；第一次Tab转到分类栏的第一个入口，而非正在显示的周常选项。记录`runs/settings-entry-focus-before.json`，两条路径的焦点`visible=false`，未修改配置、未运行游戏。

现在用户打开设置、周常或切换设置分类时，焦点进入当前分类首个可用控件；任务卡指定项、错误字段、文本选择、分类键盘导航和其他详情窗口优先保留。以控件的布局归属处理Windows延后映射，不通过强行抢前台或增加按钮说明解决。只有用户导航请求安排默认焦点，单纯的Notebook页面变化不覆盖错误定位。下拉框沿用原生下方向键展开与Esc收起，随后Esc返回原入口；任务、保存和启动逻辑不变。

初期实现确实遇到控件映射时机和通用页面事件覆盖错误焦点的问题，原失败与诊断保存在`runs/settings-entry-focus-initial.log`、`settings-entry-focus-verified.log`、`settings-entry-focus-final.log`、`settings-entry-focus-regressions.log`及对应trace文件。错误焦点检查在关闭新增导航回调时通过，之后将自动聚焦限定到用户导航请求，未放宽既有检查。 另一次检查误用了原生只读组合框未绑定的Space，已按实际绑定改用Down，没有新增或改变产品键位。 同进程串联两个旧GUI脚本时还出现前一脚本销毁窗口后遗留的`_drain`计时器警告，最终检查改为各脚本独立进程运行；未因此改写业务循环或游戏输入。

**225项设置、55项输入纠错、121项任务入口、84项GUI检查通过**，最终日志为`runs/settings-focus-clean-settings_ui_smoke.log`、`settings-focus-clean-input_feedback_smoke.log`、`settings-focus-clean-entry_clarity_smoke.log`、`settings-focus-clean-gui_smoke.log`。设置专项覆盖100%、150%、200%，入口专项另含125%；普通／最小窗口、当前字段变禁用、快速返回、详情焦点、原生下拉、指定任务与错误字段均已核对。最终独立进程日志无回调错误或计时器警告，配置写入只发生在临时配置的显式保存检查中，游戏调用为0。

本轮不新增提示文案、控件或键位，不改变日常与周常的执行、资源或保存约定；只修复导航后的焦点。真人体验反馈仍按用户安排留待开发完成后，不能以这些离线检查证明学习与注意力成本接近零。

源码`3ab3e16`经`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/settings-focus-build.log`。独立配置、`--no-admin-launch`下，鼠标打开周常后不按Tab，直接按Down即展开“开启／关闭”；Esc收起，下次Esc回到首页周常入口。再从齿轮打开设置，保留周常分类，同样直接按Down展开选择。全程未选择新值、保存、检测或启动任务，正常关闭退出码0。截图`runs/settings-focus-package-weekly.png`、`settings-focus-package-choice-screenshot-0.png`、`settings-focus-package-return.png`与`settings-focus-package-gear-choice-screenshot-0.png`保留完整原生路径。239份用户文件与独立配置哈希不变；126项UI素材、4份清单及23个上游文件与源码一致。记录`runs/settings-focus-package-verification.json`，备份`build/userdata-settings-focus-20261029_140018/`，EXE SHA-256为`30199af8941ea202c73497fe37a8ccbcf3f0b4b4e4f35813ca3fee10f302f76f`。本轮证据归档于正式项目`runs/settings-focus-*`及`runs/settings-entry-focus-*`。

## 2026-10-29：任务卡使用原纸面纹样与边框

保留当前任务卡、设置入口与开始计划的交互。只读对照AutoZZZ本地`8511c1b`的`interface.py`、`desktop.py`、`game_widgets.py`和`gui.py`，继续采用整卡点击、鼠标与键盘同一动作、切页保留状态及单独保存设置的原则；没有操作AutoZZZ窗口或迁入其源码。

从既有CN 4.6.0每日实训源图提取288×372静态纸面边框，替换原近似斜线和手绘点线，保留真实地图纹样与底部撕口。原状态栏、任务、数值、奖励区域的RGB及透明度整块清零，运行时绘制本次内容；费用底色收进点线内部。源码、素材清单、署名和复现脚本同步更新，没有使用旧任务完成状态。

**128项参考几何与121项入口检查通过**，日志`runs/card-paper-verified-ui.log`，截图和结果位于`runs/card-paper-reference-ui/`与`runs/card-paper-entry-ui/`。覆盖100%、125%、150%、200%的普通／最小窗口、半露卡片、加入草稿、任务调整、设置返回、运行锁定与费用授权。初次替换遗漏原纸面顶部1逻辑像素偏移，在125%下超出既有位置容差；已恢复原起点后通过，原失败日志`runs/card-paper-reference-initial.log`保留，没有放宽检查容差。

**169项任务状态检查通过**，日志`runs/card-paper-task-state.log`与结果`runs/card-paper-task-state-ui/`，覆盖停止、失败和异常后的未执行原因、实际消耗、原始报告及草稿不被修改；启动均为假后端，实际游戏调用为0。

`runs/card-paper-material-verification.json`核对四边金色点线、不透明像素与源图一致、透明区域RGB亦清零，以及18项根素材清单的输出哈希。源图、参考裁图均沿用此前记录；新的纸面素材SHA-256为`bcb327404434c124170b195456fd4e179ee01d02be30d011bd6f901e5432e8ff`。已查看最终普通窗口截图，实时费用和动作文字可见。

本轮只核对桌面素材与交互，不启动、检测或操作游戏。边缘透明度仍是提取结果，背景遮挡重建和应用专属内容也与游戏有差异；不宣称整屏逐像素相同。真人体验反馈按用户安排留待开发完成后，日常周常组合实机及未接入模式的既有边界不变。

源码`41bd40a`经`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/card-paper-build.log`。独立配置、`--no-admin-launch`下，核对任务卡新纹样与边框；一击“更换副本”打开当前已选“回忆之蕾／城郊雪原”，打开设置后按Esc回到原副本页，再返回首页仍保留副本卡选择。没有修改选项、保存、检测或启动任务，正常关闭退出码0。239份用户文件与独立配置哈希不变，126项UI素材、4份清单及23个上游文件与源码一致。记录`runs/card-paper-package-verification.json`，备份`build/userdata-card-paper-20261029_133008/`；EXE SHA-256为`9a61b78f18abbcfa0e0751cc1242b4ed117925a4b419f5f9c83895b2976a147c`。原生截图为`runs/card-paper-package-home.png`、`card-paper-package-dungeon.png`、`card-paper-package-settings.png`、`card-paper-package-return.png`及`card-paper-package-final-home.png`；本轮证据已归档到正式项目`runs/card-paper-*`。

## 2026-10-29：按任务卡与设置入口的用户反馈调整交互

用户指出首页的任务卡和设置入口仍需要停下来辨认。本次将“设置”从左侧玩法页签移至指南右侧，用齿轮与文字共同标识，保留原指南印章；各玩法及记录页位置一致，返回保留原页面和入口。任务卡标题简化为任务名，副本卡直接显示当前名称、地点及预计费用；未加入的标签和标题改用灰色。按钮按动作显示“加入计划／调整任务／更换副本／查看安排／查看进度／查看结果”。加入只修改当前草稿，保存仍需显式操作；运行中不能加入，没有开拓力授权时只查看限制。边缘仅部分可见的卡片首次点击先展开，不在动作名称不可见时修改计划。

详情样式同时对照已保存的4.6提示框`autohsr/tests/fixtures/du_runtime/last_area_confirm.png`：居中标题、圆点分隔线、浅色正文、深色底栏、单个右上圆角和关闭胶囊，素材说明见`assets/ATTRIBUTION.md`。标题不在正文重复，短提示居中，长记录完整可选、复制和滚动；原错误、费用和JSON内容不改。无系统标题栏，Esc、Alt+F4和关闭按钮通过同一退出路径恢复入口；主窗口最小化时同步隐藏。没有模态抓取，暂停／停止保持可操作。

- **121项入口专项、128项参考几何与页签检查通过**，分别为`runs/entry-clarity-final-verified-entry_clarity_smoke.log`、`entry-clarity-checks-reference_ui_smoke.log`。覆盖100%、125%、150%、200%的普通／最小窗口、五个页面的一击设置与返回、加入草稿、运行锁定、资源授权、半露卡片先展开、原始结果与配置不变。参考使用既有无账号全宽裁图`runs/reference-daily-inspection.png`，SHA-256为`ed431d67e4af97330cde6864fb23c530b58f0e3b2f576a3785d548e0d6f9c6f3`。
- **101项详情检查通过**，`runs/game-dialog-reference-final.log`与`runs/game-dialog-ui/`。四种缩放下核对参考纸色、底栏分界和按钮尺寸，以及长记录、短提示、最小化／还原、Esc／Alt+F4、窗口边缘和模拟620×360工作区。初期确实发现无边框窗口返回焦点、按钮图片纵向重复及设置按钮继承白色底的问题，已修复；原失败及中间截图日志保留。采样检查按明暗分界定位抗锯齿边缘，尺寸允许整数像素舍入。
- **169项任务结果、192项设置、60项首页反馈、24项计划、84项GUI检查通过**。日志分别为`entry-clarity-release-task_card_state_smoke.log`、`entry-clarity-verified-settings_ui_smoke.log`、`entry-clarity-checks-home_feedback_smoke.log`、`entry-clarity-final-verified-plan_ui_smoke.log`、`entry-clarity-final-verified-gui_smoke.log`。旧测试中“未加入卡片直接打开设置”、设置与文字居中等预期已同步新交互；计划测试改经真实关闭协议退出详情，不直接销毁窗口绕过返回流程。返回入口检查保留应用内焦点目标，不把其他桌面应用短暂取得前台当成丢失返回位置。中间失败和漏传参考参数的记录均保留，未重跑后端全量测试。

原生源码核验使用明确标注“离线入口核验”的假后端窗口与独立临时配置，记录`runs/entry-clarity-native-verification.json`：详情中心误差0，一次开启／关闭后返回原任务卡，退出码0、配置字节未变。截图为`entry-clarity-native-open-screenshot-0.png`等。截图工具在关闭后曾返回其他前台窗口像素，已停止依赖旧画面并重新绑定核验窗口；原生观察只确认记录中的一次返回，不将后续缓存截图当作Enter再次开启或Alt+F4成功的证据，这两项仍以专项事件检查为准。没有启动、检测或操作游戏。

旧正式版首页截图保存在`runs/entry-clarity-before-home.png`，来源提交和哈希见`entry-clarity-baseline.json`；新版普通／最小窗口见`runs/entry-clarity-ui/`。这些检查验证入口、反馈和局部参考样式，不能证明真实玩家的学习／注意力成本接近零，也不证明整屏逐像素一致。日常周常组合实机、货币战争周常与积分奖励的原有边界不变。

源码`eb92eff`经`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/entry-clarity-build.log`。独立配置、`--no-admin-launch`下，原生鼠标一击齿轮打开设置，Esc返回后入口仍高亮；一击邮件卡“加入计划”使日常从3项变4项并出现保存入口，再点“调整任务”直接聚焦邮件选项。将该独立草稿恢复关闭后返回，原卡位置保留、保存入口消失，正常退出码0。没有保存、检测或执行任务；239份用户文件及独立配置哈希不变。125项UI素材、4份清单、23个上游文件与源码一致，记录`runs/entry-clarity-package-verification.json`，备份`build/userdata-entry-clarity-20261029_130545/`。EXE SHA-256为`c9bd3c62a6a4db205e02d017a0a99c030d391cb8e21f48cd131037e0f11cf870`。原生截图为`runs/entry-clarity-package-home.png`、`package-settings.png`、`package-return.png`、`package-joined.png`、`package-task-settings.png`与`package-restored.png`（后五项均同`entry-clarity-`前缀）；相关证据已归档到正式项目`runs/entry-clarity-*`与`runs/game-dialog-*`。

## 2026-10-29：详情在当前窗口中央打开并返回原入口

从`3cc4e2c`提取原`_show_summary`方法，在相同临时配置和窗口位置离线重放：主窗口客户区`[611,445,1651,1201]`，详情客户区`[11,45,1021,510]`，中心相差`[-915,-746]`像素。新实现对应`[926,790,1021,510]`，中心误差为0；坐标、版本及截图见`runs/summary-placement-before-replay.json`与`summary-placement-after.json`及同名PNG。初次探针重复运行时复用了文件名，旧`summary-placement-baseline.json`和`summary-placement-before.png`已被修后输出覆盖，不能作为修前证据；上述基线是从原提交重新取得的方法重放的结果。

现在先隐藏详情窗，测量原生边框后按助手客户区居中，并通过当前显示器工作区限制位置和大小；不以主显示器原点代替当前窗口位置。关闭按钮、Esc和标题栏关闭恢复原入口焦点；替换详情仍保留原入口，原入口隐藏时不强行把焦点送回隐藏控件。正文使用可伸缩网格，长文本保留滚动、选择和只读状态，底部关闭按钮优先保留。没有增加模态输入抓取，没有改写结果、配置、任务启动或游戏输入。

**69项专项检查通过**，`runs/summary-dialog-release-smoke.log`与`runs/summary-dialog-ui/`。覆盖100%、125%、150%、200%，偏离原点的主窗口、实际工作区边缘、模拟620×360小工作区、长文本末尾、三种关闭方式、替换窗口、隐藏原入口及差分／货币战争的独立详细记录。最初两次检查错误地将独立Toplevel当成受主窗口客户区裁切的子控件，日志`runs/summary-dialog-smoke.log`与`summary-dialog-smoke-v2.log`保留；改为核对原生窗口工作区和其自身子控件后通过。

**169项任务卡、60项首页反馈、24项计划、84项GUI检查通过**，日志为`runs/summary-dialog-task_card_state_smoke.log`、`summary-dialog-home_feedback_smoke.log`、`summary-dialog-plan_ui_smoke.log`与`summary-dialog-gui_smoke.log`。相关配置和原始结果未变，没有重跑后端全量单元测试。

另以独立临时配置打开明确标注“离线详情核验”的源码窗口，使用原生键盘按Esc关闭、Enter再次打开同一结果，再用标题栏关闭。两次客户区中心误差均为0，两次关闭均返回原任务卡，正常退出码0，配置字节未变；记录`runs/summary-dialog-native-verification.json`，画面为`summary-dialog-native-open-screenshot-0.png`及`summary-dialog-native-reopened-screenshot-0.png`。第一次按缓存AX索引关闭遇到工具索引失效，刷新AX后正常关闭，没有重发任何游戏输入。

这次修复详情位置及返回路径；原生标题栏和详情样式仍与游戏不同，不证明整屏复刻或真实玩家学习／注意力成本已经验收。未启动、检测或操作游戏。

源码`e425c11`通过`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，最终日志`runs/summary-dialog-build-final.log`。独立配置下使用`--no-admin-launch`核对正式版正常启动、主入口显示及正常关闭，退出码0；截图`runs/summary-dialog-package-home.png`。详情操作由上述源码离线原生窗口与专项检查验证，正式版未启动任务来制造结果。239份用户文件和独立配置哈希未变，125项UI素材、4份清单及23个上游文件与源码一致。记录`runs/summary-dialog-package-verification.json`，备份`build/userdata-summary-dialog-20261029_121716/`，EXE SHA-256为`95f981afdd035bcf07e22e7f10fd1a00dc3ef93b1e0306c0c25f76b6b79229f1`。专项、任务卡、计划与首页证据均已归档到正式项目`runs/summary-dialog-*`目录，基线重放与修后位置保留在`runs/summary-placement-*`。

## 2026-10-29：区分任务安排与未执行结果

在`5d0d73e`上用假后端复现：计划在委托阶段停止后，副本卡显示“未执行”，按钮仍是“副本设置”，点击会进入生存索引，无法直接查看这项为何未执行。运行前未启用的任务也显示“跳过”，与实际执行结果混淆。原记录`runs/task-card-state-baseline.json`、`task-card-state-before-home.png`和`task-card-state-before-stopped.png`保留。同次检查确认最小窗口的每日设置选项均在完整祖先可见范围内，没有据此改动布局。

现在运行前显示“待执行／未加入”；后端实际报告的“跳过”不变。已结束流程中尚未开始的任务成为本次结果，按钮显示“查看结果”；一击打开该项原因，包含原报告提供的错误、未保存和资源待核对提示，不再跳到设置。状态已写“未执行”时，详情不再重复“此项未执行”。正在执行的任务若意外中断，也保留具体原因及“未确认完成”，不再要求另找日志。修改下一次每日计划后恢复设置入口，原报告、总摘要与已核实结果不被单项查看覆盖。没有改变后端任务、默认选择或主按钮。

- **169项专项检查通过**，`runs/task-card-state-release-task_card_state_smoke.log`与`runs/task-card-state-ui/`。覆盖100%、125%、150%、200%最小窗口、停止、启动失败和运行异常、鼠标一击打开副本及实训的本次详情、真实跳过与未加入区分、费用与错误保留、设置入口可见性、显示偏好不清结果、下一次计划恢复设置入口；12次启动均为显式调用主按钮产生的假后端，没有游戏调用，配置和原始报告未变。
- **186项设置、24项计划、60项首页反馈、84项GUI检查通过**。日志为`runs/task-card-state-settings_ui_smoke.log`、`task-card-state-final-plan_ui_smoke.log`、`task-card-state-home_feedback_smoke.log`与`task-card-state-release-gui_smoke.log`；补充错误原因后重跑了专项、计划与GUI检查，扩展运行异常时再次核对专项与GUI。没有改后端或重跑全量后端单元测试。

专项脚本前三次分别误将规范化运行配置与未展开默认值整体比较、未进入ScrolledText的外层容器、在尚有重绘回调时用根窗口取消子控件回调，日志`runs/task-card-state-smoke.log`、`task-card-state-smoke-final.log`和`task-card-state-smoke-final-v2.log`保留。修正测试方法后通过；`task-card-state-smoke-final-v3.log`为精简重复详情前的105项通过记录。已查看最终预览、停止及失败详情截图。这些检查证明状态与按钮去向一致，不代替真实玩家使用测试或整屏复刻验收；未启动、检测或操作游戏。

源码`d0f9558`通过`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/task-card-state-build.log`。用独立配置和`--no-admin-launch`打开，核对“待执行／未加入”、邮件卡一击进入对应设置及返回后的原卡片位置；没有修改选项、保存、检测或运行任务，正常关闭退出码0。截图`runs/task-card-state-package-home.png`、`task-card-state-package-settings.png`和`task-card-state-package-return.png`保留；提前结束和异常详情由上述假后端专项验证。239份正式用户文件与独立配置哈希未变，125项UI素材、4份清单和23个上游文件一致。记录`runs/task-card-state-package-verification.json`，备份`build/userdata-task-card-state-20261029_114913/`，EXE SHA-256为`b1cad3671689e6caab5019ccee9141e0d5729eadc6fb6a76480295f1a3de5145`。设置、计划与首页结果归档为`runs/task-card-state-settings-ui/`、`task-card-state-plan-ui/`和`task-card-state-home-feedback-ui/`。

## 2026-10-29：周常提示随计划时间与游戏周刷新

在`62b4ec8`上用临时配置和假时钟复现：助手从周四10:59:59保持打开至11:00，后端资格已到期，首页却仍显示“周四11:00后”，直到修改表单才更新。原记录`runs/weekly-preview-baseline.json`、`weekly-preview-before-due.png`和`weekly-preview-after-due-baseline.png`保留，配置字节未变，没有调用游戏后端。

现在复用已有界面事件轮询，空闲时按分钟核对预览，内容没变就不写变量或触发重绘。运行／暂停保持冻结快照及进度；同周已完成／已跳过结果保留，跨周后恢复本周资格预览。原结果仍在，属于该结果的摘要标为“上次计划”，周常详情使用冻结游戏周日期；不会改写原报告，也不重新标记较新的独立玩法结果。待核对、停止、无游戏周或报告未保存的结果不因时钟变化消失。未增加定时任务、启动动作、账号推断或配置写入。

- **35项假后端专项检查通过**，`runs/weekly-preview-smoke-final.log`和`runs/weekly-preview-ui/`。覆盖到期、时钟回退、周一02:00与04:00、无效草稿、关闭周常、同周保留／跨周切换、待核对与报告失败、独立结果、还原窗口、无重复重绘，以及一次点击后的运行／暂停跨周快照。全部时间变化只触发显示；唯一启动来自显式调用主按钮，实际游戏后端调用为0，配置与原始报告未改。
- **20项周计划单元测试、24项计划编排GUI、60项首页反馈、84项GUI检查通过**，`runs/weekly-preview-unit.log`、`weekly-preview-plan-ui.log`、`weekly-preview-home-feedback.log`与`weekly-preview-gui.log`。保留日常后接周常、账号周记录去重、原始结果、暂停停止、单一主按钮和保存语义。本轮未修改后端或重跑全量单元测试。

已查看到期及跨周后的截图，首页继续显示计划与真实状态，没有添加提示段落或新的启动入口。这次修复时间提示过期，不证明真实玩家的学习／注意力成本或整屏游戏复刻已经验收；日常周常组合实机、货币战争周常与积分奖励的既有边界不变。未启动、检测或操作游戏。

源码`6b56d52`通过`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，构建日志`runs/weekly-preview-build.log`。使用独立临时配置和`--no-admin-launch`，11:27打开窗口并保持首页不动；实际跨过11:29后，提示从“差分宇宙 · 1 局 · 周四 11:29 后”自动变为“差分宇宙 · 1 局 · 到期，运行时核对”。没有修改系统时间、点击运行／保存、切页或操作游戏。截图`runs/weekly-preview-package-before-due.png`与`weekly-preview-package-after-due.png`、观察记录`runs/weekly-preview-native-observation.json`保留。正常关闭退出码0，239份正式用户文件和独立配置哈希未变；125项UI素材、4份清单、23个上游文件与源码一致。发布记录`runs/weekly-preview-package-verification.json`，备份`build/userdata-weekly-preview-20261029_112657/`，EXE SHA-256为`27112aa12e1c2e309acd7781c209da4402f1699efebdea925313363dd7fa95a5`。本轮计划与首页结果分别归档为`runs/weekly-preview-plan-ui/`和`weekly-preview-home-feedback-ui/`。

## 2026-10-29：校正指南图标与任务卡静态素材

以`1d3bc55`为修改前基线，对照同一批已保存的CN 4.6.0画面，发现每日实训图标混入原指针，活跃标记含放射纹且失去渐变，任务水印被拉伸并叠在偏黄的内页上。此次重提取五项既有素材：三个页签改取未选中且无遮挡的区域，连续计算透明度并保持原比例；活跃标记改取任务卡区域，保留金色渐变、白色内环和抗锯齿；水印保留原色及比例，内页改为白色。源图、裁切、方法和输出哈希见`assets/ui/sources.json`，未新增素材数量或分发整图。

页签选中底色与悬停／键盘焦点分开；光晕只模糊透明度，避免透明像素的黑色RGB混入边缘。125%缩放对照同时发现副本列表边缘的不足一像素区域会产生空裁切异常，现跳过该区域并始终恢复外层画布；原绘制异常不被吞掉。没有改变任务名称、计划默认值、费用说明、主按钮或后端流程。

- **3项绘制回归通过**，`runs/guide-artwork-painter.log`。将同三项检查作用于基线`Painter`时复现5个空裁切错误（含四种缩放子项）及1个光晕发黑失败，原记录`runs/guide-artwork-painter-before.log`保留。
- **124项参考与页签检查通过**，`runs/guide-artwork-reference-final.log`。覆盖100%、125%、150%、200%的正常／最小窗口、参考纸面比例与位置，以及三个页签真实截图中的悬停、离开、键盘焦点和空格导航；没有绘制回调异常，配置字节不变。首次扩展脚本误用导航别名导致`KeyError: universe`，保留`runs/guide-artwork-reference.log`；改用实际页签控件后通过。
- **84项GUI、105项缩放交互、99项周常入口还原检查通过**，`runs/guide-artwork-gui.log`、`guide-artwork-responsive.log`与`guide-artwork-header.log`。假后端覆盖运行锁定、暂停停止、草稿、返回焦点、缓存布局、最大化／还原后的按钮可见性；未重跑后端全量单元测试。

已查看同尺寸1920×1080的修改前后首页，以及更新后的生存索引和旷宇纷争截图（`runs/guide-artwork-before-*.png`、`guide-artwork-final-*.png`）与`runs/guide-artwork-card-comparison.png`。对照图单独标明游戏参考、修改前和修改后，任务文本及状态各自独立。这些证据证明局部素材及交互改进，不代表整屏像素一致或真实玩家学习／注意力成本已经验收。原水印上端被标题遮挡的部分尚未恢复，纸面边饰等重绘部分仍有差异；日常周常组合实机、货币战争周常和周积分奖励的既有边界不变。未启动、检测或操作游戏。

源码`861df90`通过`tools/build.ps1`构建并更新正式版`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，构建日志`runs/guide-artwork-build.log`。用`--no-admin-launch`打开，按当前画面依次进入生存索引、旷宇纷争并返回每日实训；核对新的图标、焦点、任务卡和计划入口后正常关闭，退出码0。未点击保存、检测或运行。239份用户文件哈希未变，125项UI素材、4份清单及23个上游文件与源码一致；记录`runs/guide-artwork-package-verification.json`，备份`build/userdata-guide-artwork-20261029_105058/`，EXE SHA-256为`69d9c28c0aa55ada8947834f7abafb1a4b475894b45677197dca503b1f972e4c`。正式截图为`runs/guide-artwork-package-home.png`、`guide-artwork-package-tasks.png`、`guide-artwork-package-universe.png`及`guide-artwork-package-return.png`。参考、缩放和还原结果分别归档为`runs/guide-artwork-reference-ui/`、`guide-artwork-responsive-ui/`及`guide-artwork-header-ui/`。

## 2026-10-29：还原窗口后保持周常入口可见

上一轮正式截图记录了还原后周常按钮未出现、切页后恢复。本轮在`d3b8d01`上使用假后端复现：不切换页面，直接最大化再还原缓存布局，周常按钮落到可见范围之外；原失败`runs/header-restore-before.log`与截图`runs/header-restore-before.png`保留。原来的调用按钮测试仍能打开设置，不能证明玩家看得到或点得到按钮。

原因是顶部计划容器的宽度依赖`Header.paint()`更新，复用画面时该次重绘可能被跳过。现将位置计算接到标题区域的实际尺寸变化；背景绘制只负责画面，页面切换仍主动更新计划容器。没有改变文案、按钮样式、点击动作、配置或后端流程。

**99项专项检查通过**，`runs/header-restore-after.log`与`runs/header-restore-ui/`。覆盖100%、150%、200%，每日实训与生存索引，最大化／还原各重复两次；核对“周常计划”和“开始计划”在全部祖先容器及窗口内完整可见、还原复用原布局、周常打开正确分类、返回恢复焦点，配置字节不变。已查看同一普通窗口修复前后截图，按钮由缺失恢复到顶部右侧。

**63项背景、24项布局缓存、123项过渡、105项缩放交互、84项GUI检查通过**，日志`runs/header-restore-*_smoke.log`；过渡、缩放及缓存截图另存为`runs/header-restore-transition-ui/`、`runs/header-restore-responsive-ui/`及`runs/header-restore-cache-ui/`。覆盖场景衔接、空闲无重绘循环、草稿、动态候选与范围、运行锁定、暂停停止和布局失败恢复。本轮未修改后端或重跑全量单元测试。

早期探针漏考虑尚未绘制的控件没有`_photo`，原日志`runs/cached-paint-probe.log`保留，修正后的几何记录为`runs/cached-paint-probe-v2.log`。扩展背景检查的首次指针命中断言失败记录为`runs/header-position-before.log`，该路径此前已淘汰待验证的缓存；未以该断言推断按钮缺失，后续用直接缓存还原及完整祖先边界检查复现。

源码`359c6d2`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/header-restore-build.log`。以`--no-admin-launch`核对首页最大化、直接还原且不切页，周常入口完整显示；按当前画面点击按钮进入周常计划，再以Esc返回原入口，正常关闭退出码0。未点击保存、检测或运行，239份用户文件哈希未变；125个UI素材、4份清单、23个上游文件一致。核对记录`runs/header-restore-package-verification.json`，备份`build/userdata-header-restore-20261029_101316/`；EXE SHA-256为`81c7921c5b9ff97db93654a8ecc138df15daed85817abbae8b3b775c5afce333`。正式截图为`runs/header-restore-package-home.png`、`header-restore-package-maximized.png`、`header-restore-package-restored.png`、`header-restore-package-weekly.png`及`header-restore-package-return.png`。

这次修复稳定后的周常入口缺失，不代表已消除整个缩放过渡的裁切或闪烁。未启动、检测或操作游戏；整屏与游戏完全一致、真实玩家学习／注意力成本、日常周常组合实机仍未验收，货币战争周常与周积分领奖尚未接入。

## 2026-10-29：复用最近窗口布局并保持动态控件状态

在`0e26d57`基础上，窗口切换最多保留当前和前一个尺寸的布局。返回相同尺寸与比例时复用控件、主题图片；准备第三种布局前释放较早的控件与图片。隐藏画面记录内容变化，恢复时只重绘内容或位置变化的部分；任务、队列、草稿变量及运行对象仍共用当前状态。新布局准备失败时恢复原界面，错误继续报告。未修改游戏后端、CLI、默认配置、图标、字体或颜色。

专项检查发现：改选历战余响后，缓存布局可能仍显示旧的副本下拉选项与次数上限。原失败保留于`runs/resize-cache-dynamic-before.log`。现同时转移下拉候选、数值范围、滑块位置及当前文字选区，不在窗口切换时规范化尚未填完的输入。

- **24项专项检查通过**，`runs/resize-cache-dynamic-after.log`与`runs/resize-cache-lifecycle-ui/`。通过实际选项操作覆盖3次与24次上限切换、滑块取值、无效草稿、取消选区、任务结果像素、日志标签、运行锁定、暂停／停止、两个布局上限、第三种尺寸释放旧控件，以及完整构建后模拟失败的恢复。配置字节未变，假后端拒绝游戏运行。
- **123项过渡、105项缩放交互、123项设置绘制检查通过**，最终日志`runs/resize-cache-verified-*_smoke.log`；截图与结果归档于`runs/resize-cache-transition-ui/`、`runs/resize-cache-responsive-ui/`与`runs/resize-cache-paint-ui/`。覆盖100%、150%、200%缩放、普通／最大化／还原、草稿与焦点、下拉菜单、运行对象、主题图片与回调数量。设置绘制逐像素比较的是复用后画面与应用自身完整重绘结果，不代表与游戏整屏一致。
- **186项设置、63项背景、165个布局场景与15项布局交互、84项GUI、60项首页反馈、55项输入反馈检查通过**，`runs/resize-cache-final-*_smoke.log`。这批在最终补齐动态控件转移之前完成；补齐后重测上述专项、过渡、缩放与设置绘制。未修改后端，未重跑全量单元测试。

原过渡脚本的绘制钩子跨复用残留、截图变量重名，以及专项脚本在字段映射前设置焦点、绕过任务事件直接改卡片的失败均已保留为`runs/resize-cache-resize_transition_smoke.log`、`resize-cache-v2-resize_transition_smoke.log`、`resize-cache-v3-transition.log`及`resize-cache-lifecycle*.log`；修正测试方式后通过，未把这些脚本问题写成游戏或实机验收失败。

最终使用同一`profile_layout_transition.py`脚本、150%系统缩放和相同页面顺序复测，见`runs/resize-cache-final-profile.json`及对应调用分析。下表为本机单样本、含性能分析开销；首页第一次最大化仍需创建布局，随后切换复用已准备的两个尺寸。不代表所有设备或正式EXE的性能保证。

| 页面／操作 | 上一版 | 本次 |
| --- | ---: | ---: |
| 首页最大化 | 1684毫秒 | 1536毫秒 |
| 首页还原 | 1202毫秒 | 537毫秒 |
| 每日设置最大化 | 1115毫秒 | 462毫秒 |
| 每日设置还原 | 834毫秒 | 264毫秒 |

源码`f1ea1e6`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/resize-cache-build.log`。以`--no-admin-launch`核对最大化、邮件卡直达每日设置、关闭邮件后的4项草稿、还原后的值与焦点、恢复原开关、Esc返回原卡及5项计划，正常关闭退出码0。未点击保存、检测或运行，239份用户文件哈希未变；125个UI素材、4份清单、23个上游文件一致。核对记录`runs/resize-cache-package-verification.json`，备份`build/userdata-resize-cache-20261029_094719/`；EXE SHA-256为`83f33b217b06ed23e9a0ca89d7da1a80d0feb19877f0baf6c060f187e47796ed`。正式截图为`runs/resize-cache-package-maximized.png`、`resize-cache-package-settings.png`、`resize-cache-package-draft.png`、`resize-cache-package-restored.png`及`resize-cache-package-return.png`。

首次桌面采集得到目标窗口外画面，保留为本地`runs/resize-cache-package-initial-capture-mismatch.png`，不作为界面证据或打包素材。前置后普通窗口首帧`resize-cache-package-home.png`尚未显示周常按钮，随后稳定的最大化和返回首页截图均显示入口；未将单帧检查当作连续过渡验收。

已查看失败恢复后的首页和替换前的设置画面。还原时旧大布局仍可能短暂裁切，不能称为即时或无闪烁。未启动、检测或操作游戏；真实玩家学习／注意力成本、与游戏整屏逐像素一致、日常周常组合实机仍未验收，货币战争周常与周积分领奖尚未接入。

## 2026-10-29：减少窗口缩放的重复绘制

在`f7c2291`上使用假后端与临时配置分析首页、每日设置的最大化和还原；本机150%缩放下四次切换为2337、2507、2784、1424毫秒。主要耗时来自旧布局在替换前重绘，以及设置页将整块纯色背景按双倍尺寸绘制后缩小。原计时、调用分析与诊断脚本保留为`runs/resize-performance-before.json`、`resize-performance-before-*.txt`／`.prof`及`profile_layout_transition.py`。

现直接准备新布局，保留旧画面至替换；设置页只生成顶部装饰图片，其余区域使用同色画布背景。设置页完全遮住的场景暂停显示，返回指南后恢复。未改变绘制倍率、图标、字体、颜色、原生控件或点击区域。

- **84项绘制检查通过**，`runs/resize-performance-paint.log`与`runs/resize-performance-paint-ui/`。三档系统缩放、普通／最大化窗口、全部六个设置分类，含实际消耗和计时文字；将新装饰图片铺回完整背景后，与原整页绘制逐像素一致。此处仅证明优化前后设置画面一致，不证明与游戏整屏相同。
- **123项过渡检查通过**，`runs/resize-performance-transition.log`与`runs/resize-performance-transition-ui/`。旧画面不再在待替换尺寸上重绘，旧控件与原字号保留到新画面准备完成，替换后旧控件释放；三档缩放下首页和每日设置均覆盖，配置未写入。
- **102项缩放交互、186项设置、63项背景衔接、165个布局场景与15项布局交互、84项GUI检查通过**，日志为`runs/resize-performance-*_smoke.log`。覆盖草稿、焦点、下拉菜单、运行锁定、暂停停止、页面返回及场景恢复。未修改后端，未重跑全量单元测试。

最终代码使用同一分析脚本与窗口顺序复测，见`runs/resize-performance-final.json`及对应调用分析。下表是本机四次单样本、带性能分析开销的对照，不代表其他设备或正式EXE的性能保证。

| 页面／操作 | 修改前 | 修改后 |
| --- | ---: | ---: |
| 首页最大化 | 2337毫秒 | 1684毫秒 |
| 首页还原 | 2507毫秒 | 1202毫秒 |
| 每日设置最大化 | 2784毫秒 | 1115毫秒 |
| 每日设置还原 | 1424毫秒 | 834毫秒 |

源码`094d0e2`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/resize-performance-build.log`。以`--no-admin-launch`核对首页、最大化、邮件卡直达每日设置、还原、Esc返回原卡片及正常关闭，退出码0；所捕获的各帧画面完整，邮件焦点与返回位置保持、指南背景恢复。未点击保存、检测或运行，239份用户文件哈希未变；125个UI素材、4份清单、23个上游文件一致。核对记录为`runs/resize-performance-package-verification.json`，备份`build/userdata-resize-performance-20261029_085056/`；EXE SHA-256为`1c1ba831f2e0437b390f33d7abe11c070aec2206bf83d6589cdd3c1bad944022`。正式截图为`runs/resize-performance-package-home.png`、`resize-performance-package-maximized.png`、`resize-performance-package-settings.png`、`resize-performance-package-restored.png`及`resize-performance-package-return.png`。

已查看切换前与稳定画面。还原时旧的大布局仍会暂时裁切，缩放等待尚未消除，不能称为即时或无闪烁。检查使用假后端，未启动、检测或操作游戏；真实玩家学习／注意力成本、整屏逐像素一致、日常周常组合实机仍未验收，货币战争周常与周积分领奖尚未接入。

## 2026-10-29：首页任务直达每日设置

诊断复现：首页邮件卡的“邮件设置”进入生存索引，页面主体仍是副本目录，仅把焦点移到下方勾选框。原记录保留为`runs/task-settings-before.log`、`runs/task-settings-before-mail.png`。现将委托、实训、邮件和勋礼卡片接到独立“每日任务”分类，直接聚焦对应开关；返回恢复原卡片和浏览位置。实训合成移到实训奖励下一行，保留数量、材料和适用条件。副本卡保留原生存索引捷径：关闭时定位启用开关，开启时定位所选副本，避免启用后再绕回设置。

新开关与生存索引勾选共用原变量，保持草稿、显式保存、运行锁定及开拓力授权限制。每日任务分类使用现有星铁设置行、原字体和既有图标；未新增第三方素材或修改游戏执行、默认配置和CLI。卡片已有结果时仍打开详情。

- **最终186项设置检查、84项GUI检查通过**，`runs/task-settings-battle-route-settings.log`、`runs/task-settings-battle-route-gui.log`。覆盖四张卡片的实际点击、对应焦点、原卡片返回、计划状态同步、两个副本入口状态、开拓力授权、运行锁定、草稿和显式保存，以及100%、150%、200%的默认／最小窗口。已查看每日任务页实际Tk截图，最终截图和结果归档为`runs/task-settings-ui/`。
- **99项缩放检查、165个布局场景与15项布局交互、54项参考检查通过**，`runs/task-settings-final-responsive_ui_smoke.log`、`task-settings-final-ui_layout_smoke.log`、`task-settings-final-reference.log`。包括新分类与开关焦点在最大化、还原后保留，返回首页仍定位原卡片；原任务比例和结果详情入口保持。这批检查在最终保留关闭状态副本捷径之前完成，该分支调整后已重测上述186项设置及84项GUI。缩放截图和结果归档为`runs/task-settings-responsive-ui/`。

首次正式源码`ab83691`通过`tools/build.ps1`构建，实查邮件卡直达、关闭任务后的4项计划、Esc返回原卡片、还原开关后的5项计划及正常退出，退出码0。239份用户文件哈希未变，125个素材、4份清单与23个上游文件一致；核对记录`runs/task-settings-package-verification.json`，备份`build/userdata-task-settings-20261029_080957/`，EXE SHA-256为`fcc1d7f92283be2ae3713940efb8f6445111d03d744f52a222b88b4c7363954e`。截图为`runs/task-settings-package-home.png`、`task-settings-package-mail.png`、`task-settings-package-draft.png`、`task-settings-package-draft-home.png`及`task-settings-package-return.png`。未点击保存、检测或运行。

该构建最大化时仍捕获到文字交叠的中间帧，`runs/task-settings-package-maximized.png`保留；同一窗口随后恢复完整，见`task-settings-package-maximized-settled.png`。诊断确认Tk切换全局主题时，仍可见的旧按钮文字宽度从88变成140像素，见`runs/task-settings-theme-before.log`。现为旧控件保留原主题的字体、边距、状态和图形元素，再创建新布局；诊断恢复为88→88，见`task-settings-theme-after-v2.log`。旧布局释放前的**111项过渡检查通过**，覆盖首页与每日设置、三档缩放、最大化和还原，日志`runs/task-settings-theme-transition-v2.log`。原失败诊断保留，未删改。

已查看旧布局释放前的截图：文字交叠消失，但还原过程中旧大布局仍会暂时裁切；新布局完成后恢复全部行。截图检查不是连续视频验收，本机该轮过渡测量1.5～4.6秒，不能称为即时或无闪烁切换。

主题修复后的**102项缩放、186项设置、165个布局场景与15项布局交互再次通过**，日志为`runs/task-settings-theme-responsive_ui_smoke.log`、`task-settings-theme-settings_ui_smoke.log`、`task-settings-theme-ui_layout_smoke.log`。反复缩放复用旧主题元素，图片与回调数量有界；草稿、焦点、运行锁定、暂停停止和结果保持。最终离线证据另存于`runs/task-settings-theme-transition-ui/`、`runs/task-settings-theme-ui/`和`runs/task-settings-theme-responsive-ui/`。

最终源码`383e99b`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/task-settings-theme-final-build.log`。以`--no-admin-launch`实查邮件卡直达对应开关、最大化、还原、Esc返回原卡片和正常关闭，退出码0。放大与还原后首次返回的截图均显示完整行、正常字号及邮件开关焦点；这两帧不替代连续过渡验收。未点击保存、检测或运行，239份用户文件哈希未变；125个UI素材、4份清单、23个上游文件一致。核对记录`runs/task-settings-theme-final-package-verification.json`，备份`build/userdata-task-settings-theme-final-20261029_083010/`；EXE SHA-256为`18f28d0a60fa85319b97e0f0cda128ef97fd0830a24fe3cfc54a34f015286441`。正式截图为`runs/task-settings-theme-final-package-home.png`、`task-settings-theme-final-package-mail.png`、`task-settings-theme-final-package-maximized.png`、`task-settings-theme-final-package-restored.png`及`task-settings-theme-final-package-return.png`。

离线回归使用假后端，正式版检查仅操作助手界面；未启动、检测或操作游戏。上述结果证明入口与状态行为，不证明真实玩家学习／注意力成本，也不代表整屏与游戏逐像素一致；日常周常组合实机、货币战争周常和周积分领奖仍未验收或接入。

## 2026-10-29：缩放切换时保留旧控件

最大化、还原和调整比例时，新界面在旧界面下面完成布局与绘制，再释放旧控件和图片。旧主按钮不再先销毁；后台线程、计划和状态继续复用。场景背景直接使用已缓存的目标尺寸图片，移除二次放大缩小和重复书页绘制；更新画布图片时先关联新图片，再释放上一张。搜索框销毁时清理自身变量上的回调，避免新旧控件短暂共存时清理错变量。

- **45项过渡检查通过**，`runs/transition-swap-ui.log`。100%、150%、200%下自动响应最大化和还原；在旧控件即将释放的时刻，检查旧主按钮仍完整映射、旧主题图片仍存在、旧界面仍在最上层、新主按钮与书页绘制已就绪，切换后旧控件释放且配置未写入。
- **93项缩放交互检查通过**，`runs/transition-responsive-ui-retry.log`。草稿、当前设置页、编辑位置、搜索、结果、日志、队列、暂停停止、下拉菜单及对话框归属保持，反复切换后图片和根窗口回调数量有界。首次回归暴露的搜索回调清理错误保留在`runs/transition-responsive-ui.log`，修复后重测通过。
- **156个布局场景、15项布局交互、84项GUI、63项背景和54项参考检查通过**，`runs/transition-ui_layout_smoke.log`、`transition-stage-gui.log`、`transition-guide_backdrop_smoke.log`、`transition-reference.log`。使用假后端与临时配置；本轮未启动、检测或操作游戏。

首次正式构建`30732df`核对首页与最大化时发现：旧控件保留期间，Tk会复用缓存的点数字体，按钮与部分输入文字没有随新界面放大。原截图保留为`runs/transition-package-maximized.png`及`transition-package-maximized-settled.png`；此构建正常关闭，239份用户文件哈希未变。已改为按当前比例提供明确的像素字号，覆盖按钮、设置值、日志、下拉列表与键盘提示。原测试新建Font对象测量，绕过了已有字体缓存；现直接测量控件使用的字体，新回归在恢复旧点数字体时确实失败，见`runs/transition-point-font-regression.log`。修正后的**51项切换与字号检查通过**，`runs/transition-font-swap.log`。

字号修正后，**93项缩放交互、156个布局场景与15项布局交互、123项设置及54项参考检查再次通过**，最终日志为`runs/transition-final-responsive_ui_smoke.log`、`transition-final-ui_layout_smoke.log`、`transition-final-settings_ui_smoke.log`及`transition-final-reference.log`。已查看最终假后端最大化画面，主按钮、周常入口与文字比例完整。

最终源码`56d7d2e`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/transition-final-build.log`。以`--no-admin-launch`检查首页、最大化、周常设置、还原保留设置分类、Esc返回和正常关闭，退出码0；所查看的最大化画面中主按钮、导航及原生文字比例完整。未点击保存、检测或运行；239份配置及运行证据哈希未变，125个UI素材、4份清单、23个上游文件一致。核对记录`runs/transition-final-package-verification.json`，备份`build/userdata-transition-final-20261029_074758/`；EXE SHA-256为`5233ad2ede4d22132fa6240aa9f2df08679337ffa70f070807172126f650f179`。正式截图为`runs/transition-final-package-home.png`、`transition-final-package-maximized.png`、`transition-final-package-weekly.png`、`transition-final-package-restored.png`及`transition-final-package-return.png`，最终离线切换结果与截图归档为`runs/transition-final-resize-ui/`、`runs/transition-final-responsive-ui/`。

先前停绘／画面缓存试验在慢速模拟中仍出现黑边或缺失控件，未采用；原中间帧继续保留。最终实现保留实际控件，不截取桌面或缓存窗口截图。字号修正后的离线自动切换本机计时为1.9～3.2秒，不能宣称即时缩放；上述结构与布局检查也不等于连续画面的无闪烁验收。整屏逐像素一致、真实玩家学习／注意力成本和日常周常组合实机仍未验收，货币战争周常与周积分领奖尚未接入。

## 2026-10-29：随窗口等比放大并保留操作位置

更大窗口和最大化窗口按可用宽高放大整套指南、字体、设置行和按钮，不再维持小窗口书页尺寸。小窗口保留原系统缩放下的可读尺寸；还原时保留当前页面、设置分类、输入光标与选区、未保存计划、副本搜索、结果页、任务记录及日志。运行线程、事件队列和计时器不重建，暂停／停止继续作用于同一次运行。原生下拉菜单、对话框与按住的按钮先完成当前交互，再调整布局；键盘名称提示不阻止缩放。主题切换释放旧图片，重复调整不累积根窗口事件处理器。

- **90项响应式交互检查及3项键盘提示补查通过**，`runs/responsive-ui-final.log`、`responsive-tooltip-final.log`。覆盖100%、150%、200%缩放下的最大化、还原、更大的普通窗口、编辑焦点、草稿、结果、搜索、日志、运行锁定、暂停停止、菜单／对话框归属，以及图片与事件处理器的数量边界。截图和结果为`runs/responsive-ui/`，假后端与临时配置，无游戏输入。
- **156个布局场景、15项布局交互、84项GUI、63项背景、123项设置、42项表单及24项计划检查通过**，`runs/responsive-*_smoke.log`。布局新增最大化窗口下的全部主页面、设置分类及玩法子页；原默认／最小窗口继续覆盖。
- **54项参考几何与入口检查通过**，`runs/responsive-reference.log`。默认窗口与原游戏参考的局部位置、尺寸和比例保持；不证明整屏逐像素相同。
- **1189项全量单元测试通过**，`runs/responsive-ui-unit.log`，139.514秒；在最终原生菜单焦点修正前完成，后续改动由上述界面回归核对。未改Runner、CLI、周常到期规则或资源门禁。

菜单补查实际重现状态条重绘的`KeyError: popdown`：Tk原生下拉列表没有Python控件包装。已改为直接比较原生焦点路径，并在恢复输入位置时定位其Python所属控件；生存索引同步处理同类焦点。原诊断保留为`runs/responsive-ui-dropdown-diagnostic.log`，未通过的初期测试日志继续保留。

本轮还核对源码启动的DPI：实际客户区2305×1297、系统DPI适配已生效，同一窗口经桌面截图工具返回1539×896（含标题栏）。证据`runs/guide-dpi-source.json`、`guide-dpi-source-cua.png`说明该截图经过缩小，不能仅据截图判定程序DPI失效；本次未修改DPI入口。

源码`855dbac`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/responsive-build.log`。以`--no-admin-launch`核对首页、最大化、周常设置、还原保留设置分类、Esc返回及正常关闭，退出码0；未点击保存、检测或运行。239份配置及运行证据哈希未变，125个UI素材、4份清单、23个上游文件一致。核对记录`runs/responsive-package-verification.json`，备份`build/userdata-responsive-20261029_065718/`，EXE SHA-256为`e87cf8e772cf235d729b20ec57f09a21a1bd62fdfff70a1d07ef0b286d980a58`。正式截图为`runs/responsive-package-home.png`、`responsive-package-maximized-settled.png`、`responsive-package-weekly.png`、`responsive-package-restored.png`和`responsive-package-return.png`。

首次最大化捕获了重绘中间帧：页签与主按钮暂未绘出，辅助功能树暂不可用；没有重新发出最大化操作，再次读取同一窗口后全部入口完整。中间帧保留为`runs/responsive-package-maximized.png`，不能用稳定帧宣称无闪烁过渡；缩放过渡仍待优化。

未启动、检测或操作真实游戏。真实玩家的学习／注意力成本、整屏逐像素一致和日常周常组合实机仍未验收；货币战争周常与周积分领奖尚未接入。

## 2026-10-29：指南比例与可见入口名称

按原每日实训画面校准默认窗口的书页位置、页签间距、纸面内边距及卡片起点和大小，纸面底纹恢复参考比例。画布为挂饰预留外缘，默认窗口的右侧挂饰不再缩小或被任务内容遮挡；小窗口保持内容可达，大窗口继续保留阅读尺寸。应用入口“记录”“设置”直接显示名称，前三个游戏入口保留原图标，避免把游戏其他玩法的图标重新解释为日志或设置。按钮外形、选中底色、键盘操作和主动作语义保留。

- **54项参考与入口检查通过**，`runs/guide-proportions-final-reference.log`。新增整宽、无账号区域的参考裁图（SHA-256 `ed431d67e4af97330cde6864fb23c530b58f0e3b2f576a3785d548e0d6f9c6f3`），独立提取纸面起点、宽度和四张卡片的位置／尺寸，100%、150%、200%默认窗口按参考宽度缩放后误差均不超过4逻辑像素；最小窗口继续校验卡片比例。另核对两个文字入口无需悬停、没有重复名称浮窗、键盘进入对应页且保留“开始计划”。截图和原始量测见`runs/guide-proportions-ui/`，仅为局部几何与交互证据。
- **最终108个布局场景、63项场景背景、123项设置及84项GUI检查通过**，`runs/guide-proportions-final-*_smoke.log`。覆盖三档缩放、默认／最小／更宽／最大化、挂饰画布扩展后的背景衔接、设置返回、暂停停止、错误和保存；假后端运行，无真实游戏输入。
- **60项首页反馈、55项输入反馈、24项计划及1189项全量单测通过**，`runs/guide-proportions-*_smoke.log`及`guide-proportions-unit.log`（148.041秒）。这批检查在最终挂饰画布扩展之前完成；最终绘制变更由上一项界面检查再次核对。素材未新增，沿用原来源、版本及哈希；配置、资源门禁、Runner、CLI和周常执行规则未改。

首次正式构建`2945e4d`已核对首页、记录和设置，发现可见文字入口仍弹出同名提示，现移除这两条重复提示，保留三个图标入口的名称提示；最终54项参考与入口检查再次通过。首次截图和构建记录以`guide-proportions-package-initial-*`保留，239份配置及运行证据哈希未变。

最终源码`d73b44d`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/guide-proportions-build.log`。以`--no-admin-launch`核对首页、记录、设置及Esc返回原页面，两个文字入口不再出现重复名称浮窗，未点击保存、检测或运行。正常关闭退出码0；239份配置及运行证据哈希未变，125个UI素材、4份清单、23个上游文件逐项一致。截图为`runs/guide-proportions-package-home.png`、`guide-proportions-package-records.png`、`guide-proportions-package-settings.png`、`guide-proportions-package-return.png`；核对记录`runs/guide-proportions-package-verification.json`，备份`build/userdata-guide-proportions-20261029_061945/`。EXE SHA-256为`69d7b7d3d4e5441432508f025a2b4ac2cb0bdce8d9e958b21d6f7f2e1daa63fa`。

未启动、检测或操作真实游戏。整屏逐像素一致、全屏随分辨率等比放大、真实玩家学习／注意力成本，以及日常周常组合实机仍未完成；货币战争周常与周积分领奖的未接入边界保留。

## 2026-10-29：指南场景与活跃徽章

标题栏、指南外缘和周常按钮改用同一窗口坐标的静态模糊场景，窗口缩放后重新裁切，运行计时更新复用缓存；周常按钮圆角外不再出现纯色方块，保留原生点击、键盘、禁用和返回焦点。关闭符号来自既有参考，设置页仍执行返回，指南页仍执行关闭。活跃圆章按参考补上四向尖角、点状边缘及内部放射纹，未核实的活跃值继续显示“—”，不复用截图中的500或领取状态。

新增两幅静态素材及来源清单，移除整本指南、文字和整个底部HUD区域；被遮挡场景采用邻近颜色插值，不能称为原始景物或整屏像素复现。原图哈希与已有指南素材一致，完整帧不提交，详见[UI素材说明](assets/ui/README.md)。底栏和设置页保留深色，主操作、费用、错误提示与周常启动规则未改。

- **63项场景与交互检查通过**，`runs/guide-backdrop-resize-guide_backdrop_smoke.log`及`runs/guide-backdrop-ui/result.json`。覆盖100%、150%、200%、默认／最小／更宽／最大化窗口、跨组件背景坐标、书页高度与垂直居中、周常原生键盘进入、禁用、返回焦点、实时计时复用缓存及空闲不循环重绘。仅使用临时配置，禁止启动Runner。
- **84项GUI、60项首页反馈、72项底栏和123项设置检查通过**，`runs/guide-backdrop-*_smoke.log`及`guide-backdrop-settings.log`。运行、暂停、停止、保存、错误定位、结果状态与隐藏页面恢复均保持。
- **30项参考几何与交互、108个布局场景及15项布局交互检查通过**，`runs/guide-backdrop-final-reference.log`及`runs/guide-backdrop-ui_layout_smoke.log`。已查看真实GUI生成的`runs/guide-backdrop-ui/home.png`，背景与圆角连续、徽章状态正确；这些证据不证明整个游戏界面的像素相同。
- **1189项全量单元测试通过**，`runs/guide-backdrop-unit.log`，141.584秒；素材输出哈希、文档链接与`git diff --check`通过。初次空闲重绘检查直接写计时文本，与真实时钟字段冲突而失败；改用正式计时字段后通过，原日志`runs/guide-backdrop-smoke.log`及`guide-backdrop-smoke-diagnostic.log`保留，未修改运行时钟以掩盖测试问题。

首次正式构建`d0dbddf`在最大化时暴露旧布局问题：书页受最大宽度约束，高度却随窗口拉长。现为书页设置默认阅读高度并垂直居中，小窗口仍随可用空间收缩；背景继续铺满窗口。修正后63项场景、108个布局、123项设置、84项GUI及30项参考检查再次通过，日志为`runs/guide-backdrop-resize-*.log`。首次检查记录为`runs/guide-backdrop-package-initial-verification.json`，截图`guide-backdrop-package-initial-maximized.png`保留；原配置和239份运行证据哈希未变。这是离线界面修正，不是新游戏验证。

最终源码`a475edf`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/guide-backdrop-build.log`。以`--no-admin-launch`核对首页、最大化／还原、周常入口与右上返回，未点击保存、检测或运行。正常关闭退出码0；239份配置及运行证据哈希未变，125个UI素材、4份清单、23个上游文件逐项一致。截图为`runs/guide-backdrop-package-home.png`、`guide-backdrop-package-maximized.png`、`guide-backdrop-package-weekly.png`、`guide-backdrop-package-return.png`；核对记录`runs/guide-backdrop-package-verification.json`，备份`build/userdata-guide-backdrop-20261029_054410/`。EXE SHA-256为`52ac6592af7b675cb3b621a044ffc64825daef03550d8ef6752977f5076dc42b`。

本次未启动、检测或操作游戏。日常与周常组合实机、周积分奖励、货币战争周常和真实玩家学习／注意力成本仍未验收；历史资源、失败记录和通关计数不变。

## 2026-10-29：底栏按当前操作显示

未修改的已保存计划收起保存按钮及“已保存”“准备就绪”常驻文案；有草稿、首次使用或配置读取失败时保留显式保存入口。保存成功后在左侧操作区确认，继续编辑或切页后收起；磁盘写入失败明确显示“保存失败”，保留原文件、草稿、保存入口与具体错误。读取损坏配置后使用默认表单，不再误称已保存；仅明确保存才替换配置。补领奖只在每日实训、生存索引出现；运行时收起空闲操作，阶段、暂停、停止、错误、资源和恢复信息继续显示。主按钮位置和日常后接到期周常的执行规则不变。

- **72项底栏交互检查通过**，`runs/footer-attention-final-ui.log`与`runs/footer-attention-ui/result.json`。覆盖100%、150%、200%、默认／最小窗口、草稿恢复、无写入导航、无效输入定位、显式保存、模拟磁盘失败、损坏配置恢复、首次默认配置、运行锁定、停止状态和错误优先。已查看`home.png`、`draft.png`、`saved.png`；使用临时配置并禁止启动Runner。
- **84项GUI、60项首页反馈、55项输入反馈、24项计划、123项设置及42项表单检查通过**，`runs/footer-attention-*_smoke.log`。补充配置读取失败分支后，底栏72项及GUI84项再次通过，后者为`runs/footer-attention-final-gui.log`；随后仅改正磁盘失败的标题与底栏文字，底栏72项再次通过。
- **108个布局场景、30项指南参考检查通过**，`runs/footer-attention-ui_layout_smoke.log`、`footer-attention-reference.log`。卡片比例、全部入口、设置和结果可达；仅为局部布局及交互证据，不代表整屏与游戏逐像素相同。
- **1189项全量单元测试通过**，`runs/footer-attention-unit.log`，140.382秒；在补充配置读取失败的界面分支之前完成，后续改动由上述底栏和GUI回归核对。未修改游戏流程、资源门禁或报告格式。

源码`663a17c`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/footer-attention-build.log`。以`--no-admin-launch`实际检查首页、周常页、运行偏好草稿和还原：保存入口随修改出现、还原后收起，未点击保存、检测或运行。正常关闭退出码0，239份配置及运行证据哈希未变，123个UI素材、3份清单和23个上游文件一致。截图为`runs/footer-attention-package-home.png`、`footer-attention-package-weekly.png`、`footer-attention-package-draft.png`、`footer-attention-package-reverted.png`；核对记录`runs/footer-attention-package-verification.json`，备份`build/userdata-footer-attention-20261029_051005/`。EXE SHA-256为`51eed346ba7f6278382838afd99211eca1154f2489c989ab18ef604b37ffe521`。文档链接和`git diff --check`通过。

本次未启动、检测或操作真实游戏。真实玩家的学习／注意力成本、整屏逐像素一致和日常周常组合实机仍未验收；货币战争周常及周积分奖励尚未接入，历史计数及失败记录不变。

## 2026-10-29：独立设置页与返回操作

设置从指南书框中移出，采用顶部分类、整行选项与右上返回。右上“×”和Esc返回进入前的页面及键盘焦点；从周常计划返回每日实训，下拉菜单打开时Esc仅收起菜单。窗口标题栏关闭继续走停止、等待后台和未保存确认。设置内保留当前操作，日常计划摘要在下方显示，始终只有一个可见主按钮；返回不保存配置、不停止正在运行的任务。游戏设置参考来源见[素材署名](assets/ATTRIBUTION.md)，分类仍使用既有指南图标、应用名称与深色背景，未达到整屏逐像素一致。

- **120项设置界面检查通过**，`runs/settings-shell-settings_ui_smoke.log`。覆盖100%、150%、200%缩放、正常／最小尺寸、五个分类、值区域与键盘操作、两层Esc、各页返回、恢复焦点、周常默认返回日常、隐藏页面恢复、已用开拓力与计时、运行中返回保持锁定，以及只在显式保存时写配置。已查看实际Tk截图`runs/settings-shell-ui/weekly-default.png`；截图使用测试数据。
- **84项GUI、55项输入反馈、24项计划、42项表单、60项首页反馈检查通过**，`runs/settings-shell-*_smoke.log`；执行使用假后端，未启动游戏。
- **108个布局场景与30项指南参考检查通过**，`runs/settings-shell-ui_layout_smoke.log`、`settings-shell-reference.log`。参考检查只证明原有指南卡片几何及交互，不能用于证明新设置页像素一致。
- **1189项全量单元测试通过**，`runs/settings-shell-final-unit.log`，140.503秒；新增3项时钟检查覆盖空闲重复轮询、跨秒／小时更新和冻结结果时间。

首次GUI回归在“货币战争 → 运行记录 → 设置”后持续绘制，进程CPU增长且后续截图未生成。保留有界复现`runs/settings-shell-repro-before.log`：计时器每100毫秒重复写同一个字符串，触发新全屏背景及隐藏页重绘。修复为显示值变化时才更新时间、隐藏Surface不绘制、重新映射时绘制最新状态；修复后同路径复现退出码0，日志`runs/settings-shell-repro.log`，以上最终回归全部通过。初期测试焦点时序错误与返回按钮宽度不足记录分别保存在`settings-shell-initial-ui.log`、`settings-shell-close-layout.log`，未覆盖原失败。

首版`fb57818`构建并打开正式EXE，发现首次进入设置时选中圆环显示、下划线缺失。补充真实画布像素检查后重现失败，日志`runs/settings-shell-first-entry-before.log`；新增分类按钮映射与导航布局事件触发重绘，最终**123项设置检查通过**，`runs/settings-shell-first-entry-final.log`，覆盖三档缩放首次进入后的下划线及原有全部设置路径。首版EXE的配置和运行记录239份哈希未变，已正常关闭；首版核对记录、构建日志及截图保留为`settings-shell-package-initial-verification.json`、`settings-shell-initial-build.log`、`settings-shell-package-initial-weekly.png`，不混作最终版本。

最终源码`e782372`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/settings-shell-build.log`。以`--no-admin-launch`打开正式程序，核对首次进入周常设置的完整选中标记、管理员按钮列及右上返回每日实训，正常关闭退出码0。实际截图为`runs/settings-shell-package-weekly.png`、`settings-shell-package-admin.png`、`settings-shell-package-return.png`；最终模拟截图另存`runs/settings-shell-final-ui/`。239份配置及运行证据哈希未变，123个UI素材、3份清单、23个上游文件一致；记录`runs/settings-shell-package-verification.json`，备份`build/userdata-settings-shell-20261029_045325/`。EXE SHA-256为`5b4a919adfdb870a69e5f33e9e4a859e25f63597cf3862a0e61f073e98d6211e`。文档相对链接和`git diff --check`通过，7处历史忽略报告链接在原工作区核对。

本次未启动、检测或操作真实游戏。日常周常组合实机、周积分奖励、货币战争周常和真实玩家学习／注意力成本仍未验收；历史资源、失败记录和通关计数不变。

## 2026-10-29：设置行布局与明确开关状态

设置页从左上角紧凑表单改为游戏式整行浅灰选项，名称在左、当前值统一在右；周常、游戏内字幕和实训合成使用“开启／关闭”下拉选择。时间格式、北京时间、数值范围和合成费用放在对应字段附近，配置路径移至游戏连接页，管理员授权边界继续显示。周常选择货币战争时整体隐藏差分局数及编队行，隐藏字段不进入键盘焦点顺序；错误定位、草稿、显式保存和运行锁定规则不变。

参考图来源、响应格式、哈希与未标明版本的限制见[素材署名](assets/ATTRIBUTION.md)。本次只以代码重绘设置行，未把公开截图打包成素材；外围仍为指南页，尚未达到游戏设置整屏逐像素一致。

- **81项新增设置界面检查通过**，`runs/settings-settings_ui_smoke.log`及`runs/settings-ui/result.json`。覆盖100%、150%、200%、默认／最小窗口、五个分类、值区域打开选择、键盘改变周常及两个运行偏好、外部布尔值同步、忙碌锁定、差分字段显隐、长状态提示、只显式保存时落盘。假后端拒绝启动Runner。
- **108个既有布局场景通过**，`runs/settings-layout.log`。初版已检查全部页面与子页，最终设置检查再次覆盖修改后的五个设置分类、三档缩放与两个尺寸；已查看`runs/settings-ui/weekly-default.png`、`weekly-minimum.png`和`run-minimum.png`。
- **42项表单、55项输入反馈、24项计划和84项GUI检查通过**，`runs/settings-*_smoke.log`。错误字段仍自动展开并选中，周常交接与显式保存逻辑保持；所有执行使用假后端。
- **1186项全量单元测试通过**，`runs/settings-unit.log`，137.540秒；文档链接与`git diff --check`通过。7处历史忽略报告链接在原工作区核对，未为新工作树改写或删除原记录。

新增检查的首次脚本误用Home键选择列表首项，改为原生上下键后修正；测试结束时批量取消所有组件回调造成重复清理，改为完成待绘制内容并只取消根窗口轮询。两份原失败日志为`runs/settings-ui-initial.log`、`settings-ui-cleanup.log`，未改运行代码以掩盖错误。

初次打包检查了首页、五个设置分类和下拉打开／Escape收起，配置未改；截图发现管理员页双按钮撑宽值列，已缩小设置专用按钮内边距。最终**81项设置检查再次通过**，`runs/settings-final-ui.log`，已查看管理员最小窗口，未改游戏输入或流程代码。

最终源码`5987f74`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志`runs/settings-build.log`。以`--no-admin-launch`打开正式程序，复核周常入口和管理员按钮列后正常关闭，退出码0；截图为`runs/settings-package-weekly.png`和`settings-package-admin.png`。239份配置及运行证据哈希未变，123个UI素材、3份清单、23个上游文件一致；核对记录`runs/settings-package-verification.json`，备份`build/userdata-settings-20261029_041708/`。EXE SHA-256为`0fb7259cc63b9d8376dc8df44949cf977cd28586a2c9724808a040479d6179ab`。初次构建、核对与截图以`settings-initial-build`、`settings-package-initial-*`保留，未混作最终版本。

本次未启动、检测或操作真实游戏。日常周常组合实机、周积分奖励、货币战争周常和真实玩家学习／注意力成本仍未验收；历史资源、失败记录和通关计数不变。

## 2026-10-29：首页费用语义与结果去重

首页删除委托、邮件、勋礼卡片的重复“0 开拓力”，跳过和未执行的副本不显示费用；只保留副本预算与实训目标等影响判断的信息。普通副本标注预计费用，饰品提取标注最多开拓力及已有沉浸器优先，首页与生存索引使用一致语义；无效次数不生成负数或超范围费用。副本运行后的卡片读取报告中的次数和两种资源消耗，缺失与待核对数据单独显示。初次打开隐藏未发生的消耗与计时，运行后右上角明确为“已用开拓力”；缺少新消耗字段不会把已确认值覆盖成0。

空闲底栏合并结果与状态，不再出现两个重复行。当前差分或货币结果页已展示完整结果时，底栏收起相同反馈；离开结果页立即恢复。判断同时核对页面、结果内容、警告和运行状态，新输入错误、新报告、其他任务错误及运行中步骤仍然显示。完整费用、原因、报告未保存与下一步继续保留。两个资源的文字改为卡片内独立行距，最小窗口不碰到底部点线。

- **1186项全量单元测试通过**，`runs/home-feedback-unit.log`；新增9项普通／饰品费用、无效次数、未知与0、待核对及双资源结果检查。
- **60项首页与反馈界面检查通过**，`runs/home-feedback-ui.log`及`runs/home-feedback-ui/result.json`。覆盖三档缩放、正常／最小尺寸、真实绘制文案、单一主按钮、详情可达、跨页面与跨操作错误不隐藏、执行阶段保留及配置不写入。已查看`home.png`、`partial-daily.png`、`partial-daily-minimum.png`和`result.png`，全部为假数据、假后端或拒绝启动Runner的测试。
- **84项既有GUI、55项输入反馈、45项货币结果、24项计划检查通过**，前三项日志为`runs/home-feedback-*_smoke.log`，计划日志为`runs/quiet-home-plan-ui.log`。运行、保存与日常周常交接逻辑未改。
- **30项参考几何与交互、108个布局场景通过**，`runs/home-feedback-reference_ui_smoke.log`、`runs/home-feedback-ui_layout_smoke.log`。参考裁图仍为既有无账号图片，SHA-256为`a3e584b01eb5103c1f1ed72585d862ebcd1cce1d251b89351008c0696c380bb7`；初次调用漏传参考路径，补齐参数后通过，调用记录保存在`runs/home-feedback-reference-invocation.log`。

源码`7b7f53e`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，日志为`runs/home-feedback-build.log`。使用`--no-admin-launch`检查正式首页和一键进入周常设置，未点击运行或检测，正常关闭退出码0；实际截图为`runs/home-feedback-package-home.png`和`home-feedback-package-weekly.png`。239份配置及运行证据哈希未变，123个UI素材、3份来源清单及23个上游文件一致；核对记录`runs/home-feedback-package-verification.json`，备份`build/userdata-home-feedback-20261029_035244/`。EXE SHA-256为`df58e84dbcb1e4eec564aa6206f57e52ae22756a20a190188ac067ab46ed38cb`。

未操作真实游戏，未改变历史资源、通关或失败记录。逐像素一致与真实玩家注意力／学习成本尚未验证，货币战争周常及周积分领奖的未接入边界保留。

## 2026-10-29：货币战争结果简化与交付状态核对

货币战争结果改为具体的中文结果标题、必要原因和下一步；动作状态码、截图路径和原始字段收进“详细记录”。已结束但尚待核实的步骤不继续显示运行时动词，准备与只读识别不重复“玩法未完成”；单个节点和开发步骤仍明确整局未完成。识别不到的金币、等级保持“未识别”，与实际读到的0区分。对应原始报告保存独立快照，之后执行日常不会覆盖；缺失观察或运行失败不会遗留旧结果。

整合已提交后端`f7a2909`，补给页面转换、仓库反馈和角色交付分开显示：两笔关联动作与仓库核验均完成，有角色时还须核实新增／升星及其他阵容不变，才显示“奖励交付已核实”。奖励局部完成不等于整局完成；失败、停止、报告未保存及后续错误中的既有结算证据继续保留。未纳入另一工作区当前尚未提交的投资实现。

- **1177项全量单元测试通过**，`runs/currency-feedback-unit.log`，包含12项新的结果语义与交付证据检查。
- **45项结果界面检查通过**，`runs/currency-feedback-currency_feedback_smoke.log`及`runs/currency-feedback-ui/result.json`。覆盖三档缩放、等待／失败／只读结果、原始记录不随外部对象或后续日常改变、未知与0、入口／设置／结果的主按钮、配置未写入。实际Tk模拟截图`runs/currency-feedback-ui/pending-delivery.png`和`readonly-result.png`已查看。
- **84项既有GUI、55项输入反馈、24项计划检查通过**，`runs/currency-feedback-*_smoke.log`。首次GUI检查仍要求旧重复文案而失败；改为核对具体结果、未开局或整局未完成及未保存设置，不放宽运行门禁。
- **108个布局场景通过**，`runs/currency-feedback-ui_layout_smoke.log`，覆盖100%、150%、200%、默认和最小尺寸及全部入口、设置、结果、开发分页。

源码`f38a3c9`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，构建日志`runs/currency-feedback-build.log`。以`--no-admin-launch`打开正式桌面，检查首页、旷宇纷争、货币入口和空结果页，确认“详细记录”初始禁用、单一主操作与保存状态，正常关闭退出码0。239份配置及运行证据哈希未变，123个UI素材、3份UI来源清单、23个上游文件匹配；核对记录`runs/currency-feedback-package-verification.json`，备份`build/userdata-currency-feedback-20261029_033526/`。EXE SHA-256为`afeea11d07c8539e7f4426973788678088b1e1fe2a4679d4937eb8a9571b9407`；实际打包窗口截图`runs/currency-feedback-package-result.png`，补给等待截图使用离线模拟报告，二者不混作真实游戏结果。

本轮只使用假后端与助手桌面，没有启动、检测或操作真实游戏。新交付路径、日常周常组合与货币战争完整对局未实机验收；周常及积分奖励的未接入边界、独立通关计数与历史失败记录保持不变。界面仍不能称为整屏逐像素一致，也没有实际玩家学习成本测试。

## 2026-10-29：旷宇纷争入口与单一主操作

差分宇宙和货币战争改为左侧玩法选择、右侧游戏入口插图。右下原“前往参与”的位置放当前实际动作；设置及结果按需打开，同一动作在这些页面移至底栏，避免同时出现两个启动按钮。差分入口实时显示计划局数、编队、新开／接续和通关后选项；费用提示随卡带、通关后每日开关保留。周期接续局数不符时直接展开并聚焦局数字段，不再额外弹出提示框。货币战争主操作保持只读，开发操作收在“开发工具”；整局未验收和周常未接入边界保留。

两幅静态插图来自既有CN 4.6指南参考，源图哈希、裁切和去除区域见[来源清单](assets/ui/universe/sources.json)。旧等级、倒计时、赛季与奖励状态全部移除，中央数字仅清除封闭字形，保留徽章轮廓；背景缺失部分以局部颜色延展补足。补足纹理、应用文案和响应布局仍有区别，不能称为整屏逐像素相同。没有启动游戏采集素材。

- **112项入口交互检查通过**，`runs/universe-ui/result.json`：鼠标进入设置、键盘返回、单击分别启动差分／货币只读假后端、单一可见主按钮、切页不改计划、编队缺失及周期接续错误定位、运行锁定、暂停停止、停止后不冒充完整通关、配置字节未变化。
- **108个布局场景通过**，`runs/ui-layout/result.json`：100%、150%、200%，默认及最小窗口；新增入口、设置、结果和全部货币开发分页均实际展开检查。32字编队、全部通关后选项与费用提示的画面见`runs/universe-ui/long-team-options.png`。
- **84项既有GUI、55项输入反馈、42项表单反馈、24项计划检查通过**，日志在`runs/universe-*_smoke.log`。真实Runner均替换为假后端，表单结果检查同步打开新的结果页。
- **1151项全量单元测试通过**，`runs/universe-unit.log`，未启动真实游戏；文档相对链接及`git diff --check`通过。

源码`66f88a8`通过`tools/build.ps1`构建，日志`runs/universe-build.log`。已更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，以`--no-admin-launch`实际打开首页、差分入口、演算设置、结果与货币入口，确认启动动作位置和配置状态，正常关闭退出码0。239份配置及运行证据哈希未变，123个UI素材、3份UI清单、23个上游文件均匹配；核对记录`runs/universe-package-verification.json`，备份`build/userdata-universe-20261029_031334/`。EXE SHA-256为`31ca4fca66eef5c2c970f6e817eeac22462b8c47b9d8ba085e9befaf0f6c4cd9`；实际窗口截图为`runs/universe-package-du.png`、`runs/universe-package-cw.png`和`runs/universe-package-settings.png`。打包未纳入另一任务尚未提交的补给后端改动，未点击运行、检测或开发操作。

正常开始仍自动最小化以让游戏获得前台；假后端运行态检查恢复助手后再验证暂停和停止显示。旧布局检查曾把独立提示窗的屏幕坐标当作按钮内部坐标；已将独立窗口排除在父控件边界检查之外，不放宽正常控件裁切约束。日常周常组合、周积分奖励、货币战争整局和真实玩家学习成本未由这些桌面回归证明，历史实机计数不变。

## 2026-10-29：生存索引行式选择与计划草稿隔离

生存索引从副本、地点两个下拉框改为游戏式行列表，展示对应掉落图标或首领徽章、名称、地点、单次费用及选中态。左侧分类、搜索、滚轮与键盘定位只改变浏览位置；点击行／“选用”或Enter才更新当前计划。同名副本保留不同地点，已选目标、次数、预计费用与预算上限常驻下方。预算、支援、快捷填写与目录刷新进入“挑战设置”；“手动填写”保留未知旧配置及新副本输入，错误直接打开对应字段。选择不保存，不启动Runner，不改变资源或实时页面门禁。

104幅静态素材来自已有2026-10-20目录采集记录，逐条记录源图哈希、坐标与输出哈希，见[素材清单](assets/ui/survival/sources.json)。裁切范围不含UID、玩家头像、余额或整图；已查看拼图核对图标与首领徽章边界。初版曾出现已选行被视口上沿截住、最小窗口展开表单溢出，分别通过跟随键盘／选中行的尺寸变化和共用编辑区域修正。

- **1137项单元测试通过**，`runs/survival-unit.log`。
- **86项新增离线检查通过**，`tools/survival_ui_smoke.py`、`runs/survival-ui/result.json`。覆盖104条图标键和哈希、六类浏览不改计划、同名地点、键盘定位／确认、空搜索、鼠标选择、周次数限制、沉浸器费用提示、忙碌锁定、自定义目标、错误展开、三种编辑视图及三档缩放和两种窗口尺寸；配置字节不变，假后端拒绝任何Runner启动。
- **84项既有GUI、24项计划、55项输入定位、42项控件检查通过**，日志为`runs/survival-*_smoke.log`。计划检查改为核对任务卡打开列表并定位已选目标；没有放宽启动、持久化与资源断言。
- **84个全界面布局场景通过**，`runs/survival-ui_layout_smoke.log`。覆盖100%、150%、200%、默认／最小窗口、全部页面、运行和暂停。预览为`runs/survival-ui/survival-index.png`，仅使用测试配置。

随后合入主分支装备更新`9a38fa9`，保留两边新增的素材署名；界面区分仓库变化后的“核验角色装备”、实际穿戴与返回均确认后的“装备已核实”及“角色装备不符”，不能把这些状态当作整局完成。同步现有局内交易和装备合成的必要提示。集成后**1151项单元测试、84项假后端GUI及84个布局场景通过**，见`runs/survival-integrated-unit.log`、`runs/survival-integrated-gui.log`、`runs/survival-integrated-layout.log`。

源码`dffe0bb`已通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`。以`--no-admin-launch`打开正式打包入口，用Computer Use检查生存索引和分类切换，已选目标、次数、费用与“已保存”状态保持不变，随后正常关闭，退出码0。**239份既有配置与运行证据哈希不变**；121个UI图像／字体、2份UI来源清单、23个上游素材与许可文件均与源码一致。记录为`runs/survival-package-verification.json`，预览为`runs/survival-package.png`、`runs/survival-package-browsing.png`，构建日志为`runs/survival-integrated-build.log`；数据备份位于`build/userdata-survival-20261029_023101/`。EXE SHA-256：`7d1f34c2d955b84758c919a5e0bb3c399fffdad1e323197204dcce90f1830470`。

本轮没有启动、检测或操作真实游戏；完整游戏画面的逐像素一致、实际玩家学习成本、日常与周常组合实机、货币战争周常及周积分领奖仍未证明完成。历史失败、账单和通关计数保持原样。

## 2026-10-29：按实机指南校准首页比例与横向任务提示

直接对照已有的无账号信息指南裁图，修正卡片被说明区挤短的问题：日常费用、目标与周常摘要移至顶部空白处，周常设置仍一键可达；费用置于可能截短的副本名之前。独立玩法隐藏该日常摘要，进入周常设置恢复“开始计划”。空结果栏收起，有错误或运行结果时自动展开，仍保留完整提示与详情。卡片按约290×480、纸面372高与45间距的参考比例缩放，右侧露出下一张，点击露出的部分可直接进入对应设置。活跃圆章、分段进度线、页签边线与选中光晕同步校准。

- **1137项全量单元测试通过**，`runs/reference-unit.log`；基于已提交的标准出售实现`850b898`，没有修改游戏输入或资源流程。
- **84项既有假后端GUI、24项计划检查通过**，`runs/reference-gui.log`、`runs/reference-plan-ui.log`，主操作、运行锁定、日常周常交接与只保存设置时落盘保持不变。
- **30项参考几何和交互检查通过**，`runs/reference-ui.log`、`runs/reference-ui/result.json`。从参考与真实Tk截图独立按像素提取四张完整卡片纸面；参考宽高比中位数0.776，三种缩放及默认/最小尺寸实测约0.78。检查露出的下一张可点击、页头随运行模式变化、费用位置、空提示收起及错误重现、配置不变。首轮检查发现小窗口实际卡数与分页阈值不一致，已修正；多窗口测试须先给当前测试窗焦点，再模拟点击。
- **84个布局场景通过**，`runs/reference-layout.log`，覆盖100%、150%、200%、默认/最小窗口、页面与运行/暂停。预览`runs/reference-ui/home.png`已查看。

源码`6a28a89`通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，只以`--no-admin-launch`打开桌面并正常关闭，退出码0；打包预览`runs/reference-package.png`已查看。239份配置和运行证据哈希不变，17个界面素材及3个上游来源文件一致；核对记录`runs/reference-package-verification.json`，构建日志`runs/reference-build.log`，备份`build/userdata-reference-20261029_015209/`。EXE SHA-256为`fad874044795d96fd193d41983e112b3377f5800205dac03e09cca47dc1c693b`。

参考裁图SHA-256为`a3e584b01eb5103c1f1ed72585d862ebcd1cce1d251b89351008c0696c380bb7`，沿用既有游戏素材的来源与权利说明，没有新增分发图片。局部比例测量不代表全界面逐像素一致，也不是玩家学习成本测试。只运行桌面与假后端，没有启动、检测或操作真实游戏；完整周常组合、货币战争周常与积分领奖的未验证边界继续保留。标准开发风险提示同步当前已合入的刷新与备战出售行为。

## 2026-10-29：统一表单控件与差分结果

将系统默认的细小勾选框、下拉箭头、次数微调和滑条改为指南配色的代码绘制控件，输入与下拉列表统一使用已随包提供的游戏字体。保留原生Tk输入、选择和快捷键，选中、禁用与焦点各有可见状态；修正按钮边角与所在纸面背景不一致。首轮小窗口检查发现图像边框被再次计入内容边距，修正后既有最小窗口内控件完整可见，没有提高最小尺寸来绕过检查。

差分结果区改为完成局数与实际结果摘要，原始JSON仅在“详细记录”及运行报告内查看。失败与停止分开；通关后的领奖失败保留已完成局数，缺失计数不从当前设置补成目标，未知消耗不变成0。保存、满槽跳过、红点领奖、卡带消耗、接续计数、通关后日常分别读取报告事实，后续运行不会替换该差分详情的快照。没有改动游戏操作或结果计数流程。

- **1123项全量单元测试通过**，`runs/form-feedback-unit.log`；完成/领奖标题细化后，6项结果语义检查另行通过，`runs/form-feedback-result-unit.log`。
- **42项控件与结果GUI检查通过**，`runs/form-feedback-ui.log`及`runs/form-feedback-ui/result.json`。三种缩放下实际触发勾选框图形、文字和空格，微调上下箭头、滑条拖动、下拉弹出与键盘选项、输入选择、禁用锁定；核对简明结果、原始详情独立保留及配置未写入。测试只注入Tk事件，游戏Runner被替换为拒绝执行的假对象。
- **84项既有假后端GUI检查通过**，`runs/form-feedback-gui.log`。首次失败是旧断言仍要求无依据的“每日刷本预算未使用”文案，现检查原始差分报告、计数、结果分离及配置不落盘；没有放宽资源门禁。
- **55项输入定位、24项一键计划检查通过**，`runs/form-feedback-input-ui.log`、`runs/form-feedback-plan-ui.log`，确认新控件仍支持错误选中、配置草稿、日常周常交接与忙碌锁定。
- **84个布局场景通过**，`runs/form-feedback-layout.log`，覆盖100%、150%、200%、默认及最小尺寸、页面与运行状态。已查看生存索引、周常设置和差分部分完成画面，`runs/form-feedback-ui/`保留预览。

源码`a127380`已通过`tools/build.ps1`构建并更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`。仅以`--no-admin-launch`打开助手桌面后正常关闭，退出码0；239份配置及运行证据的哈希保持不变，17个UI素材、3个上游来源及许可文件一致。记录为`runs/form-feedback-package-verification.json`，构建日志为`runs/form-feedback-build.log`，数据备份为`build/userdata-form-20261029_012556/`。EXE SHA-256：`0987f82af8a463adbcd0db40f2725fbf2681a75f522b63263706d2203c423cd4`。

本轮基于已提交的`789a3ea`，README同步逐笔刷新的实际离线实现；未纳入另一工作区尚未提交的出售等改动。只验证桌面，没有启动、检测或操作真实游戏。整套UI逐像素一致、实际玩家学习成本、日常周常组合实机、货币战争周常及周积分领奖仍未证明完成；不能用本轮回归代替这些验收。

## 2026-10-29：输入错误直接定位与失败原因前置

为“看一眼找到下一步”修正两处操作断点：配置校验携带字段标识，时间、次数、预算、地点和识别参数等错误直接打开相应页并聚焦字段，不再要求先关闭输入错误弹窗。错误消息置于底栏，修改该字段后清除；历史总结果保留，定位设置不会把日常主按钮切成独立玩法。数值解析使用中文字段名，不暴露Python转换异常。周常页补充共用的预设编队；未启用周常时忽略未填完的周常草稿，显式保存仍完整校验。

失败原因、待核对消耗及报告未保存状态优先显示，完整费用、下一步和原始报告保留在详情。摘要支持键盘进入与焦点标记；任务卡与已验证实训结果继续保留，不通过简短文案掩盖部分完成。重新检测或启动游戏时清除旧提示，避免新检测状态与上次错误同时出现；原报告和日志保留。

合入主分支`65e08e9`后，标准开发反馈区分“核验换人角色”“换人角色不符”“换人已核实”，不把动作阶段的verified视作换人完成。开发局胜利与结算均核实后保留实际结果，明确未计独立验收；未通过两项核验时继续显示未完成。README同步当前已接入的离线能力与未实机边界。

- **1102项集成单元测试通过**，`runs/input-feedback-integrated-unit.log`，包括字段归属、无效数值与范围、未保存报告、待核对资源、附加任务失败，以及换人和结算核实状态的提示检查。整合前1090项记录保留于`runs/input-feedback-unit.log`。
- **55项输入/错误反馈、24项计划、84项既有假后端GUI检查通过**，日志分别为`runs/input-feedback-ui.log`、`runs/input-feedback-plan-ui.log`、`runs/input-feedback-integrated-gui.log`。检查定位、选中、修正后保留启动操作、共用编队、禁用周常草稿、显式保存、配置未写入、旧错误清除及开发结果保留；没有使用游戏输入后端。
- **84个布局场景通过**，`runs/input-feedback-layout.log`，覆盖100%、150%、200%及默认/最小窗口。已查看输入错误与部分完成画面，归档于`runs/input-feedback-ui/`。

源码`ed46417`通过`tools/build.ps1`构建，日志`runs/input-feedback-build.log`；已更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，以`--no-admin-launch`仅打开桌面并正常关闭，退出码0。239份配置与运行证据哈希不变，17个界面素材及3个上游来源/许可文件一致。核对记录`runs/input-feedback-package-verification.json`，备份`build/userdata-input-20261029_010023/`，EXE SHA-256为`81ee084372a9c12767c80244e2e3ca8e364b536f9368d2637fe281b9fe6ea5cd`；首次打包的记录另存`runs/input-feedback-initial-package-verification.json`。未打入另一任务尚未提交的后端改动。

本轮只验证桌面与配置反馈，没有启动或操作真实游戏。日常周常组合、周积分奖励及货币战争完整自动玩法的未验证边界继续保留，未改变历史通关计数。

## 2026-10-29：直接显示执行阶段并保留单项结果

运行栏增加当前任务和已核实演算局数，暂停后保留相同阶段。日常子流程返回后立即显示实训领取结果、实际副本次数与已确认消耗；周常尚在运行时设置继续锁定，周常自身的零消耗不会覆盖日常消耗。差分完成数只在演算账单成功落盘后通知界面，新开尝试不会增加完成数。

任务卡按自身状态显示具体设置、查看进度或查看结果；设置入口聚焦对应控件，详情不覆盖全局错误和总结果。独立玩法开始、结束或异常不再重置日常卡片。修改日常计划切回待执行预览，显示选项修改保留原结果，原始报告不变。普通日常不再被独立差分页未填完的字段阻止；已启用周常差分仍检查实际使用的预设名。删除运行栏重复的“当前表单未写入配置”说明，保留未保存状态、资源成本、输入错误和恢复提示。

整合主分支已提交的`acb12f8`接口，标准开发页新增“默认／阿格莱雅／希儿”新局策略选择，仅本次运行有效；接续传空策略，沿用本局记录，执行期间选择器锁定。更新README与上游来源入口；新增策略仍为购买、成长及补空位基线，未标成完整复现或整局通过。

- **1086项单元测试通过**，`runs/stage-progress-unit.log`；新增阶段交接先显示日常证据、已写入账单才发布完成数、写入失败与新尝试不误报进度检查。
- **83项既有假后端GUI检查、24项计划界面检查通过**，`runs/stage-progress-gui.log`、`runs/stage-progress-plan-ui.log`；涵盖三种新局策略及接续沿用、暂停/继续、消耗保留、独立玩法结果隔离、任务详情和计划变更。
- **84个布局场景通过**，`runs/stage-progress-layout.log`；覆盖100%、150%、200%、默认/最小窗口及运行/暂停状态。已查看并归档`runs/stage-progress-ui/weekly-running.png`与`runs/stage-progress-ui/paused.png`，核对阶段、真实次数、消耗、按钮和缩放排版。

源码`67696ce`通过`tools/build.ps1`构建，日志`runs/stage-progress-build.log`，周常说明随包分发。新版已更新`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，以`--no-admin-launch`仅打开桌面并正常关闭，退出码0，截图`runs/stage-progress-package.png`。原239份配置与运行证据SHA-256不变，17个界面素材及3个上游许可/来源文件与源码一致，核对记录`runs/stage-progress-package-verification.json`，备份`build/userdata-stage-20261029_002340/`。EXE SHA-256为`a64afbdc37feaaa778813704883756f82174ee02dbe3dc341064b8ca6a32b2e9`。其他开发任务尚未提交的后端改动没有进入该包。

本次全部使用假后端及独立桌面界面，没有启动、检测或操作真实游戏，没有新增资源消耗或通关计数。日常到周常组合路径、周积分奖励和货币战争完整自动玩法仍未实机验收；这些检查不能替代真实玩家的学习成本与注意力测试。

## 2026-10-28：一键日常与周常计划

根据用户“按已有计划完成全部日常，并在周一或自定时间完成指定周常”的首页用途，将日常主按钮统一为“开始计划”。首页显示日常项目、预计开拓力与周常安排；周常设置一键可达，检测与进入游戏归入游戏连接，暂停和停止在执行中显示。保留实际指南素材与字体，删除闲置控制及重复说明；时间格式、成本、错误和当前能力边界继续显示。

参考三月七固定提交的全部任务与周常逻辑，增加独立计划编排：日常完整结束后才进入到期周常，每周一04:00刷新，可改星期和北京时间。差分按指定局数执行，默认1局；周计划关闭存档、红点领奖和通关后再次刷本。当前账号由新画面核实；本地记录开局意图、原始报告与证据哈希，已完成同周跳过，未知或损坏记录保留并阻止重开。停止、暂停和每日已验证结果跨阶段保留，运行不自动保存设置。

检查结果（UI分支，基于`0be48c9`）：

- **1043项单元测试通过**，`runs/weekly-plan-unit.log`，包含新增加的29项日历、持久化、账号核验、停止/暂停交接、原报告及证据核对、CLI契约检查。快速连续运行曾发现Windows时钟粒度导致目录重名，已加独立运行标识后回归通过。
- **78项既有假后端GUI检查通过**；增加**12项一键计划界面检查**，`runs/weekly-plan-ui.log`、`runs/plan-ui/result.json`。覆盖非法时间、表单快照、执行锁定、自动接到差分、同周跳过、每日结果保留、货币战争未接入状态和显式保存。新测试清理阶段曾用root取消子控件的Tk回调，已改为正常销毁控件后通过。
- **72个布局场景通过**，`runs/weekly-plan-layout.log`，覆盖100%、150%、200%与默认/最小窗口、全部页面及新增周常设置。界面截图在`runs/plan-ui/`和`runs/ui-layout/`。
- `tools/build.ps1`工作区构建通过，日志`runs/weekly-plan-build.log`；CLI帮助和`git diff --check`通过。

合入主分支节点修复`7fd5885`后，增加真实Runner调用周常门禁的离线检查，**1063项单元测试、78项假后端GUI检查通过**，见`runs/weekly-plan-integrated-unit.log`、`runs/weekly-plan-integrated-gui.log`。重新通过`tools/build.ps1`构建集成版本，`runs/weekly-plan-integrated-build.log`；已更新原`D:\Projects\AutoHSR\dist\AutoHSR\AutoHSR.exe`，只用`--no-admin-launch`打开桌面核实渲染并正常关闭，退出码0。原打包版**239份配置与运行证据SHA-256全部不变**，17个UI素材与源码一致，记录`runs/weekly-plan-package-verification.json`，备份为`build/userdata-weekly-20261028_234135/`，截图`runs/weekly-plan-package.png`。未把另一开发任务当前未提交的后端代码打入此版本。

本次没有启动、检测或操作真实游戏，没有消耗资源。组合路径未实机验收；差分“本周局数已完成”不代表周积分奖励完成。货币战争周积分与完整自动玩法尚未接入计划，选择它时仅执行日常并保留周常未完成状态。未新增定时器、系统唤醒或管理员任务；旧货币战争独立验收仍为0/10。

## 2026-10-28：按实际指南素材复刻并精简界面文案

用户对首版提出两项修正：按星铁实际界面继续复刻；删除依赖口号、需求原话和重复段落来解释操作的文案。当前版改用五个横向图标页签、黑色圆角指南书页、实机挂饰、封面徽记与任务纹样、竖向任务卡、活跃圆章和五档圆形奖励进度；生存索引改为六类副本侧栏，差分宇宙与货币战争共用「旷宇纷争」页签。字体为客户端附带的`SDK_SC_Web`，进程私有注册。16幅静态图像和1个字体的来源、变换、哈希与版权边界见[UI素材说明](assets/ui/README.md)。没有读取游戏内存、启动游戏取材或迁入上游GUI源码。

删除页首说明、重复操作教程、货币战争静态开发状态表；使用任务名、分组、选中态和按钮名称表达下一步。未运行时任务卡进入设置，运行后打开可滚动结果；底部长报告以单行摘要加详情呈现。保留预计开拓力、未知消耗恢复、输入格式、合成材料、卡带使用、局内交易与未验收提示。设置范围按配置校验值显示，只有显式保存才写入配置；原始报告和错误详情未删减。

本次检查：

- **1014项单元测试通过**：`runs/ui-native-unit-tests.log`。
- **78项假后端GUI检查通过**：`runs/ui-native-gui.log`。首轮因检查仍引用已移除的静态开发状态表而失败，改为核对真实结果摘要中的未完成状态及错误原因后通过，未放宽工作流或资源门禁。
- **66个布局场景通过**：`runs/ui-native-layout.log`、`runs/ui-layout/result.json`，覆盖100%、150%、200%缩放、默认16:9及最小窗口、六页和全部设置／货币战争子页。另核实实际字体注册、任务设置可达、分类切换的每周次数限制与运行锁定、旷宇纷争返回上次子页、详情实际含完整文本、长摘要不挤压底部操作，以及每日奖励证据保留。
- **字幕模拟窗检查通过**：`runs/ui-native-overlay.log`；焦点、穿透、截图排除与清理保持正常。
- 17个素材输出SHA-256与来源清单一致；`git diff --check`通过。原始游戏整图及本次界面截图均留在忽略目录。

已通过`tools/build.ps1`重建`dist/AutoHSR/AutoHSR.exe`，构建日志`runs/ui-native-build.log`。用`--no-admin-launch`启动打包版，核实指南窗口正常渲染后关闭，退出码0；17个打包素材与源码逐字节一致。构建、启动前后原有**239份配置及运行证据文件SHA-256全部一致**，见`runs/ui-native-package-verification.json`，恢复副本为`build/userdata-20261028_224449_4858/`。打包版预览为`runs/ui-native-package.png`；没有检测游戏、开始玩法或新增管理员授权。

截图与布局检查证明上述尺寸下的交互可达及静态细节核对，不代表整套应用与游戏全画面逐像素一致；助手专属表单、运行控制与响应布局仍由代码实现。本次没有游戏输入或资源消耗，历史玩法验收数、失败报告和账单不变。

## 2026-10-28：星穹铁道指南式桌面交互改版

按用户要求参考目前AutoZZZ的游戏化界面思路，重新设计AutoHSR桌面。参考本机AutoZZZ提交`a137c1eee44ea7429d06d018bd60d47c34bed41a`中的快捷手册、任务卡、分组设置与常驻控制；AutoHSR采用星铁指南的深色外框、暖白面板、金色菱形进度、任务卡与胶囊按钮。主题、绘图和玩法表单分别放在`theme.py`、`game_widgets.py`、`desktop_modes.py`，继续使用既有Tkinter与Runner，没有迁入March7thAssistant源码或改变玩法能力。

交互划分为每日实训、生存索引、差分宇宙、货币战争、运行记录、设置。生存索引集中任务开关、副本和资源计划；设置分游戏连接、运行偏好、识别与等待、管理员启动；货币战争按观察与准备、标准开发、单步调试分组，既有实验仍需显式操作。记录和设置保留之前选中的运行模式，避免查看报告后主按钮变成另一任务；暂停和停止常驻。五项任务卡支持左右切换、滚轮、Home/End、Enter和点击查看完整结果。

实训进度初始为未核实，仅由本次`daily_verified=true`报告点亮全部五档；不会从历史报告或任意数字推测奖励已领取。收尾失败保留已核实实训，独立玩法观察不会抹掉此前实训证据。每日重新开始时重置本次显示；差分存档、红点与通关后日常默认关闭的行为不变。

离线检查：

- **1014项单元测试通过**，`runs/ui-redesign-unit-tests.log`。
- **78项假后端GUI检查通过**，`runs/ui-redesign-gui.log`、`runs/ux-smoke/result.json`；包括配置不自动保存、资源授权锁定、运行快照、接续、暂停停止、后台线程退出及异常收尾。
- **66个布局场景通过**，`tools/ui_layout_smoke.py`、`runs/ui-layout/result.json`；覆盖100%、150%、200%缩放、默认及最小窗口、六个页面、四个设置子页、三个货币战争子页，逐级检查控件边界及文字尺寸。另在每种缩放下检查五项任务可达、完整结果可读、实训证据保留和切页后的模式；长观察记录在可滚动文本框中展示，不挤走运行控制。
- **字幕模拟窗检查通过**，`runs/ui-redesign-overlay.log`；不抢焦点、穿透、截图排除、切换、隐藏恢复及结束清理保持正常。

已通过`tools/build.ps1`重建`dist/AutoHSR/AutoHSR.exe`，构建日志`runs/ui-redesign-build.log`。新版用`--no-admin-launch`仅启动桌面，核实窗口标题为“AutoHSR · 开拓指南”，随后正常关闭，未进入游戏。构建与启动前后，原打包版**239份配置与运行证据文件SHA-256全部一致**，记录`runs/ui-package-verification.json`；恢复副本为`build/userdata-20261028_214855_8034/`。没有新增管理员授权或修改既有授权。

截图见`runs/ui-layout/`及`runs/ux-smoke/`，均为离线界面检查。此次没有启动、检测或操作真实游戏，没有新增游戏资源消耗、差分通关或货币战争验收。历史失败、账单与未完成实验保留。

## 2026-10-26：管理员免重复确认启动

用户要求将“一次授权、后续启动免重复确认”集成进助手。新增设置中的启用、移除、刷新状态，以及`--admin-launch status/enable/disable`、`--no-admin-launch`。系统任务仅按需打开固定默认GUI，绑定当前管理员账户和软件目录，无定时、登录、开机触发器，不存密码、不改UAC全局策略。任务状态由Windows重新读取验证，未收到管理员GUI就绪反馈不视为启动成功。旧管理员CMD仍保留单次授权用途。

离线检查：**903项单元测试、68项假后端GUI检查通过**，见`runs/admin-launch-unit-tests.log`、`runs/admin-launch-gui.log`及`runs/ux-smoke/result.json`。新增19项权限与启动测试、6项GUI检查，覆盖账户/目录隔离、固定参数、特殊字符路径编码、状态缺失及超时、取消授权、非管理员账户拒绝、操作后核验、重复移除、反馈事件寿命、已运行界面复用、CLI不加载游戏配置、任务参数不允许附加运行指令、授权期间不并发开始游戏任务。设置页面与最小窗口尺寸检查通过，截图`runs/ux-smoke/page-settings.png`。

Windows本机集成通过`tools/admin_launch_smoke.py`调用正式入口验证；从当前桌面Explorer的**普通权限令牌**创建启动进程，核实最终GUI进程的提升状态，而非仅检查计划任务显示“运行中”：

| 对象 | 授权生命周期 | 独立启动 | 已运行时再次打开 | 数据保留 |
| --- | --- | --- | --- | --- |
| 源码GUI | 启用→移除→再启用，逐次复读 | 2/2普通权限入口进入管理员GUI | 2/2复用原窗口 | 2109份既有JSON账单、报告及配置哈希一致 |
| 重建EXE | 启用→移除→再启用，逐次复读 | 2/2普通权限入口进入管理员GUI | 2/2复用原窗口 | 22份既有JSON报告及配置哈希一致 |

集成证据为`runs/admin-launch-source.json`、`runs/admin-launch-package.json`。源码测试授权已移除；按本次要求为`dist/AutoHSR/AutoHSR.exe`保留已核实的授权任务`AutoHSR-Admin-v1-f6e3aa56eb70e0d22b09`。以后使用普通`Start-AutoHSR.cmd`或EXE即可；任务不会自动开始每日或差分。两种入口本次均只打开助手，未启动游戏、检测窗口、执行玩法或消耗游戏资源。

已用`tools/build.ps1`重建EXE，构建日志`runs/admin-launch-build.log`，原打包版239份配置及证据文件在构建和启动验证后逐份哈希一致，核对见`runs/admin-launch-package-preservation.json`；恢复备份`build/userdata-20261026_004502_1899/`。配置、账单、原失败报告均未改写。

边界：执行环境开始时已提升，因此本次真实启用直接登记，没有让用户再点击一次UAC；取消弹窗路径为隔离回归验证。未执行重启验证、组织策略环境验证或其他Windows账户的授权验证。源码和EXE为独立目录授权，移动目录前可移除旧任务，新目录重新启用；自定义其他配置与游戏任务CLI不自动提权。普通账户不能借用另一管理员账户登记此入口。该任务授予固定路径中的软件管理员启动能力，路径内程序应保持可信。

## 2026-10-25：每日启动、前台日志与单件合成

本次按用户要求由 AutoHSR 执行每日，正常运行期间仅监看日志，识别停滞后才检查程序保存的失败画面。游戏已运行且停在差分宇宙菜单，程序将游戏置于前台，逐层 Esc 返回后执行；该实机路径不代表未运行游戏的启动分支也已实机通过，后者由离线测试覆盖。

- `runs/20261025_224808_077674/report.json`：持续委托奖励收取并复核4/4；从“哈哈哈哈”预设进入浴火钢心，自动完成6次饰品提取，确认消耗240开拓力、0个沉浸器、待核对消耗0。邮件和无名勋礼检查为ok；每日实训当时为400，原报告保留partial。
- 用户随后指定以万能合成机任务补足活跃，不再通过周期演算补任务。使用用户提供的干净零食图标建立配方模板；真实失败帧回放置信度0.9855，配方名称另行OCR核实。局部数字OCR解决数量“1”被全屏OCR遗漏的问题，已读取的2、3等数量不会被覆盖为1。
- `runs/20261025_233046_246924/`首次到达“确认合成”弹窗时停止；`runs/20261025_234018_463252/`由修改后的程序接续原弹窗、仅发送一次确认，获得奇巧零食后因关闭提示位置偏高而停止。两份失败报告保持原样，不计为完整自动通过。
- `runs/20261025_234254_304957/report.json`为success：程序接续原奖励弹窗，核实奇巧零食299→300，两种材料分别301→300、397→396，随后核实每日500活跃和五档奖励全部领取。本次接续没有新增刷本消耗。实际合成与确认均由程序执行，没有手动合成；这是分阶段修复后的实机闭环，尚非一次全程无人接续验收。

合成前按账号和04:00重置的游戏日保存单件记录；重启时先处理原确认或结果，不重放配方页的“合成”。已经发送过确认而反馈不明时停止，库存与两种材料同时符合变化后才将记录标为complete。“仅补领奖”关闭合成，普通每日可在设置中关闭这项补活跃步骤。

前台日志参考BetterGI的透明左下角状态栏和滚动日志，使用本地原生分层窗口实现。`runs/overlay-smoke/proof.json`在独立模拟窗口验证不抢焦点、鼠标穿透、失焦隐藏及截图排除；正常实机日志确认字幕服务启用。该检查未为了观察字幕而查看运行中的游戏。设置开关、事件队列拥塞及错误降级均有离线覆盖。

最终离线验证：**884项单元测试、62项假后端GUI检查通过**，见`runs/daily-final-tests-20261025.log`、`runs/daily-final-gui-20261025.log`。覆盖菜单与登录区分、已有窗口复用、缺失窗口启动、精确任务卡片绑定、数量识别、单件确认、结果核对及中断后不重复消耗。图标、数量和确认弹窗的真实图像回放记录分别为`runs/daily-synthesis-icon-replay-20261025.json`、`runs/daily-synthesis-quantity-replay-20261025.json`、`runs/daily-synthesis-confirmation-replay-20261025.json`。

已重建并打开`dist/AutoHSR/AutoHSR.exe`，核对新版自动启动说明及设置中的字幕、单件合成开关，没有点击开始或新增游戏消耗。首次发布因空闲旧版占用依赖文件停止，正常关闭旧版后发布成功；239份原配置和运行证据的文件哈希与备份一致，零食模板与源码一致，见`runs/daily-package-20261025.json`。旧版历史失败报告未被本日成功覆盖。

## 2026-10-20：六类日常副本与次数选择

简体中文4.6客户端，客户区3840×2160。按本次用户授权验证日常副本；只运行刷本任务，不将本次结果计为每日实训或其他玩法验收。为节省开拓力，采用**104个入口覆盖 + 六类各一个代表本实战 + 两次批量复测**，没有逐一通关104个关卡。

- 目录：金花萼15、赤花萼20、凝滞虚影29、侵蚀隧洞17、历战余响9、饰品提取14，共104个。63份真实指南行样本核对名称、地点与入口的绑定，样本和源图哈希见 `autohsr/tests/fixtures/dungeons/guide_rows.json`；原始采集在 `runs/20261020_173848_774067/`、`runs/20261020_174933_827826/`。目录采集不消耗资源。
- 以下7次最终验收运行均自动选择入口、借用好友、核对费用、开始挑战、核实成功并退出；`stamina_pending=0`，达到请求次数后停止。饰品使用已有差分存档，包含受限接近首领和普攻接战，没有新建或修改差分存档。

| 分类 / 目标 | 请求 / 完成 | 确认消耗 | 成功报告 |
| --- | ---: | ---: | --- |
| 侵蚀隧洞：霜风之径 / 收容舱段 | 1 / 1 | 40 | [175302](runs/20261020_175302_051771/report.json) |
| 金花萼：回忆之蕾 / 绘世学院 | 1 / 1 | 10 | [175533](runs/20261020_175533_216177/report.json) |
| 赤花萼：欢愉之蕾 / 「世界尽头」酒馆 | 1 / 1 | 10 | [175734](runs/20261020_175734_880952/report.json) |
| 凝滞虚影：霜晶之形 / 残响回廊 | 1 / 1 | 30 | [175911](runs/20261020_175911_006348/report.json) |
| 历战余响：毁灭的开端 / 支援舱段 | 1 / 1 | 30 | [180043](runs/20261020_180043_941625/report.json) |
| 饰品提取：百年冻土 | 1 / 1 | 40 | [182228](runs/20261020_182228_913407/report.json) |
| 金花萼：回忆之蕾 / 绘世学院，批量两次 | 2 / 2 | 20 | [182834](runs/20261020_182834_891221/report.json) |

上述最终自动验收共确认180开拓力。另有两次开发校准：饰品 `runs/20261020_181446_594099/` 手动校准接战后由程序结算40，不计作全自动通过；首轮两次花萼 `runs/20261020_182419_160744/` 在成功动画刚出现时因未读到波次安全停止，保留待核对20，没有重放挑战。随后完整结算页核对“上轮挑战波次：2”和85/300开拓力，证据为 `runs/check_20261020_182807/` 与 `runs/daily-dungeons-20261020/gold2-settlement-check.json`；人工退出后才明确开始新测试预算。原 partial 报告保持原样。**本次实际累计消耗240开拓力**，全部来自现有开拓力，未补充燃料、星琼或后备开拓力。其他导航、OCR与支援校准在开战前停止，未新增消耗。

修复覆盖：4K小字原图细读、长列表分帧滚动、同名副本地点绑定、历战本周剩余奖励、快捷补充开关的真实像素、饰品内嵌支援列表、受限首领接战、成功动画后等待波次显示。结算波次不匹配时保持待核对预算；暂停和失焦会先释放移动键。

离线验证：**438项单元测试、56项假后端GUI检查通过**，见 `runs/dungeon-final-unit-tests.log`、`runs/dungeon-final-gui.log`；GUI全部页面最小尺寸检查通过，次数界面见 `runs/ux-smoke/page-tasks.png`。覆盖全部104个入口样本回放、各分类费用与次数上限、固定单次/批量计数、达到次数即停止、延迟结算与次数不匹配保护。除金花萼两次外，其他分类的批量和跨批次数目前为离线回归验证；不能据此宣称每个关卡或每种批量均已实机通关。

PyInstaller已重建 `dist/AutoHSR/AutoHSR.exe`，实际打开EXE核对六类下拉项、次数控件，并通过窗口截图与OCR检测（`dist/AutoHSR/runs/check_20261020_183323/`）。42份资产哈希与源码一致，原打包版配置与221份历史证据文件核对一致；恢复备份在 `build/userdata-20261020_183118_9041/`。构建日志为 `runs/dungeon-final-build.log`，结构化验收与打包核对见 `runs/daily-dungeons-20261020/matrix.json`、`package-check.json`。

使用说明见 [日常副本与次数](docs/daily-dungeons.md)。本次不恢复货币战争或差分宇宙整局开发；下文保留此前的历史验证记录，其当次测试预算不作为本次新目标的累计限制。

## 历史记录

日期：2026-10-11，Asia/Shanghai。游戏已登录，简体中文，客户区 3840×2160。目标为回忆之蕾 / 绘世学院，好友支援开启，每次上限 10 开拓力、1 轮。本轮累计上限 50，达到后停止刷本。

原始日志、报告和截图仅保存在开发者本地，未随公开仓库发布；下列路径用于追溯本次开发验证。

2026-10-18 差分宇宙暂停归档：用户要求先保存并推送现有内容，等待其 Markdown 操作指南和界面介绍后再恢复。**完整自动通关仍为 0/3，功能仅部分实现**；保留同级 GUI 入口、独立操作与报告、周期演算和局部识别/导航原型，不将离线测试与局部接战计为整局成功。最新实机报告 `runs/20261018_195131_956224/report.json` 为 failed、completed_runs=0；实际源码 GUI 入口检查见 `runs/ui_refresh_20261018_190719/`。本次归档全量 415 项单元测试、53 项假后端 GUI 检查及差异格式检查通过，日志为 `runs/publish-differential-paused-20261018-tests.txt` 和 `runs/publish-differential-paused-20261018-gui.txt`。暂停归档期间不操作游戏、不继续实机调试、不重建 EXE，原始本机证据与配置保持忽略。当前限制和恢复接续点见 [差分宇宙记录](docs/differential-universe.md)。

2026-10-18 暂停开发归档：按用户要求保存并推送当前全部未忽略改动，货币战争暂停开发，等待明确恢复。发布前运行 `python -m unittest discover -s autohsr/tests -v`，**388项单元测试通过**，输出保存于本地 `runs/publish-paused-20261018-tests.txt`。本次未操作游戏、未新增实机验收、未重建EXE；当前实机边界、攻略跨版本限制与恢复接续点见 [CURRENCY_WARS.md](CURRENCY_WARS.md) 顶部。

2026-10-18 当前阶段验收：**实机观察与页面识别最小闭环通过**。复用91份真实截图样本、12类页面（含79页教学），图像哈希与保存OCR分类91/91符合预期，复用9份既有独立重OCR记录。本阶段未新采集、未点击游戏、未使用模拟样本替代实机证据；结果与识别锚点见`runs/currency-wars-live-20261018-rules/phase-observation-recognition.json`。未见战败、重连及特殊变体仍未验证。380项单测和48项假后端GUI检查已通过，未重复运行，源码未重建EXE。3个播放设备均静音，已只读复核。

本阶段结束后等待用户说“继续”。战斗使用游戏内自动战斗，后续工作重点为决策。普通商店评分/购买和自动经济策略已有代码及离线测试，尚无实机交易验收；最新1-1结算继续挑战的紧凑节点OCR修复也尚未实机验证。分阶段范围与接续点见[CURRENCY_WARS.md](CURRENCY_WARS.md)顶部。下列为此前完整功能开发的历史分步记录，不等于当前阶段需要继续自动通关。

最新完整运行`runs/20261018_111702_071013/`验证十笔4金币/4经验交易，Lv7 10/48→Lv8 2/60、金币58→18；程序自动读取符玄仅后台并部署到后台4，8/9→9/9、头像0.911、原格清空、金币不变。随后自动完成2-3出战、战斗、同节点胜利与继续挑战，抵达2-4奖励备战，HP100、金币31；整局报告仍partial。商店收起及武装箱/邀请函分支已补入代码与单测，实机证据后续追加。

`111400_937071`验证补给符玄+量产型装甲的选择和确认。`110930_866802`验证2-1继续挑战→补给。`110336_918720`验证4颗晶矿后实际2-1胜利，但结果节点OCR混入图标；原unknown不改，修复后独立重读记录为node-result-reocr.json。较早原unknown/failed报告及派生验证证据亦保留。Gemi自身的购买/合并与Computer Use手动动作，均不计作AutoHSR自动商店或整局闭环通过。

后续`112139_113068`验证商店收起与2-4奖励战胜利，`112400_774044`验证强敌介绍与商店关闭。后一次的旧晶矿反馈有一笔错误verified，独立审计loot-audit.json证实实体4→4，该笔不计通过。原报告保留；新检测以灰/蓝/金实体轮廓定位，要求数量减少1，已加入真实奖励区裁剪回归。当前2-5首领前备战席满，副本整理分支单测通过、实机进行中。

`113310_741397`验证大丽花备战副本出售（52→53、场上9/9不变），两颗蓝晶矿按实体数量2→1→0领取。武装箱标签抬升导致开启unknown，已改卡片中央点击；电池穿戴分支单测通过，尚待实机。

`114039_798485`实际验证保持按下的武装箱开启、光能电池选择，以及三月七、花火、阮梅穿戴。独立原生截图重OCR与视觉校验equipment-audit.json通过：电池3→2→1→0，每位一颗+两空槽，金币53、9/9不变。随后2-5首领胜利、继续和第三位面地图推进均verified，HP100、金币72、Lv8 30/60；在未支持的投资策略页停止。保守派完整效果已采集并加入精确匹配回归。

`114732_081962`验证保守派，`115056_016964`验证进阶箱很硬的甲与3-1胜利。`115549_263139`验证3-2符玄+蓄能帆、符玄量产型装甲（独立defensive-equipment-audit=true），3-3及3-4胜利，到3-5时HP100、金币124、Lv9 8/72。知更鸟部署触发强化弹窗并替换原角色，原unknown保留；已补绕行拖动与花火强化确认，待实机反馈。

`120554_153516`验证花火强化确认。`120959_509144`验证释放后等待的知更鸟后台5部署，9/10→10/10、原格空、金币124，目标头像0.813；后续多角色掉落溢出原unknown保留。已补满席副本整理、立即填槽反馈及红色斜纹布局回归，350项单测通过。

`121917_327452`验证满席副本整理（符玄124→128且等待奖励填槽、不死途128→130）、花火很硬的甲及蓄能帆穿戴；独立defensive-equipment-audit=true，保留电池、金币130、10/10不变。已进入3-5首领；原金晶矿半径62.024超过旧阈值而漏领，不能计为全部掉落通过。新半径范围与真实裁剪回归已补入，实机待下一局。

`121917_327452`实际赢得3-5最终首领，HP100、9连胜；独立final-boss-reocr.json核实，原unknown保留。手动查看终局SSS、阵容、统计页的转换不计入程序闭环。`124006_152268`仅验证程序从统计页返回主页，settlement_verified=true、completion_verified=false。四个终局页面已校准；新增超频A0开局分支及显式GUI按钮，实机验证进行中。

以下为10月11日每日任务验收历史，与当前货币战争开发状态分别记录。

## 最终结果

最新打包版执行委托核实、好友花萼单轮挑战和每日实训领取，报告 **success**；每日活跃度 **500/500**，五档奖励均有完成标记。最终画面同时显示累计消耗 **50/120**，与五次单轮挑战的报告计量一致。

- 最终报告（`dist/AutoHSR/runs/20261011_094940_235380/report.json`）
- 最终日志（`dist/AutoHSR/runs/20261011_094940_235380/run.log`）
- 500 活跃与五档奖励画面（`dist/AutoHSR/runs/20261011_094940_235380/095135_216667_daily_ok.png`）
- 对应 OCR 文本（`dist/AutoHSR/runs/20261011_094940_235380/095135_216667_daily_ok.txt`）

使用现有开拓力；未领取后备开拓力，未使用燃料或星琼补充，未执行抽卡、养成、商店、合成、购买或兑换。

## 实机计量

| 运行记录 | 程序 | 确认消耗 | 结果 |
| --- | --- | ---: | --- |
| 091708（`runs/20261011_091708_414479/report.json`） | 源码，早期校准 | 10 | 战斗成功；实训 400，partial |
| 093930（`runs/20261011_093930_028686/report.json`） | 源码，严格好友验证 | 10 | 战斗成功；实训 400，partial |
| 094224（`dist/AutoHSR/runs/20261011_094224_632929/report.json`） | 打包版 | 10 | 已确认战斗成功；退出按钮尚未出现而 failed，随后修复 |
| 094725（`dist/AutoHSR/runs/20261011_094725_638739/report.json`） | 修复后的打包版 | 10 | 清理旧结算且不重复计量；新战斗成功；实训 400，partial |
| 094940（`dist/AutoHSR/runs/20261011_094940_235380/report.json`） | 最终打包版 | 10 | 战斗成功；实训 500，五档奖励领取，success |
| 合计 | 五次单轮 | **50** | 不再追加刷本 |

其他校准运行在开战前安全停止，没有新增已确认消耗。旧报告保留原状态，不把后续修复改写为旧运行成功。

月卡按已拥有补给的领取与奖励展示两阶段关闭；持续委托领取后核实 4/4 进行中。好友选择先核实卡片的好友徽标、昵称和等级；仅明确满员反馈才尝试下一张卡，并分别核实选择页和队伍页绿色支援标记。快捷补充已复核关闭，开战前独立核实轮数、10 点费用和可用开拓力。

## 离线与打包检查

- 140 项单元测试通过，输出见 unit-tests.txt（`runs/unit-tests.txt`）。包含未知页拒绝、输入时效、资源禁项、好友选择反馈、结算时序和旧结算不重复计量。
- GUI 模拟检查通过：1100×760 / 1180×820、设置保存 / 校验、检测详情、暂停 / 恢复 / 停止、结果和报告入口。示例截图见 1180x820.png（`runs/gui-ui-smoke/1180x820.png`）。模拟检查不访问游戏。
- PyInstaller 构建成功。19 个资产和三个 OCR 模型与源码匹配；新 EXE 实机截图与 OCR 检测通过。
- 最后重建前后的 37 份配置与运行证据逐项 SHA256 一致，备份保存在 `build/userdata-20261011_094624_9629`。
- 打包配置保留测试 10 / 1、好友支援、绘世学院；预设按钮仅填写表单，不自动执行。

## 验证边界

完整 240 点、每批 6 轮的实机运行没有在本轮执行；其他副本、后备领取、可选邮件 / 勋礼页面及其他客户端版本或缩放组合没有获得本次端到端证据。标准每日上限 240 已写入配置与流程文档；当前自动流程仍拒绝开拓力补充弹窗，燃料始终禁止。


## 2026-10-16 UX 工程回归

本批变更只做离线回放、单元测试和假后端 GUI 验收；实际打包助手仅打开界面，不运行游戏。最终测试数量及 EXE 校验值记录在本机交付证据中。历史实机验证不代表新版战斗、暂停或游戏 UI 已重新实测。

## 2026-10-17 货币战争只读阶段

新增独立入口、只读观察和报告，自动玩法尚未开放。178 项单元测试及 32 项假后端 GUI 验收通过；包括输入拒绝、预算隔离、暂停后重新识别、停止、过期画面、OCR/证据保存失败与未完成展示。日志见 `runs/currency-wars-dev/unit-tests.txt`、`runs/ux-smoke/result.json`。界面截图已检查，详见 [CURRENCY_WARS.md](CURRENCY_WARS.md)。

本轮未进行实机观察或操作，缺少 Computer Use 所需的 node_repl 入口，CUA 原生桌面 API 禁用。攻略参考、问号教程、随机与存钱机制、真实页面转换、消费反馈、恢复及终局均未核实。只读采集和合成回放不代表自动玩法闭环或通关；EXE 未重建。平台 Goal 未启用，项目目标文件不等于 `/goal`。

同日质量复审最终结果：**189 项单元测试、40 项假后端 GUI 检查通过**，编译与差异格式检查通过。新增故障注入覆盖存图期间暂停/过期、最终报告写盘及原子替换失败、OCR 阻塞中停止、暂停中停止、失焦重采集、热键线程退出/启动失败、提前完成事件和线程退出、关闭运行/检测。写盘失败仍关闭日志并上报 `report_saved=false`，不会把旧画面或旧报告作为本次成功证据。日志在 `runs/currency-wars-review/`，最小实机证据清单及限制见 [CURRENCY_WARS.md](CURRENCY_WARS.md)。这些回归未调用真实游戏窗口；实机阻塞未解除。

后续 OCR 隔离/样本回放阶段更新为 **213 项单元测试、40 项 GUI 验收通过**。货币战争只读 OCR 使用实际独立进程，挂起、取消、暂停中停止、崩溃、坏结果与进程/临时目录回收均有回归；项目模型识别生成图片通过。新增版本化样本、PNG 哈希/尺寸/目录校验、未知状态停止决策及独立 CLI 回放。日志与合成样本位于 `runs/currency-wars-isolation/`；两种 CLI 回放均不访问游戏，真实模型复跑期望匹配。普通每日/窗口检测仍沿用同步 OCR，冻结 EXE 与实机识别尚未验证，未开放货币战争自动操作，Goal 延至用户计划的明天启用，不阻止现在开发。

用户随后授权先静音再启动：通过标准 Core Audio API 保存原状态并实际静音 3 个活动播放设备，启动前与事后独立复读均为静音。一次正常权限启动 StarRail.exe 返回 WinError 740（需要提升），StarRail 进程数为 0；未提权重试或更改安全权限，因此仍没有游戏内攻略/教程证据。原声音状态、静音复读和启动错误见 `runs/muted-launch-20261017_1/`；未解除静音。本阶段 5 项门禁测试使用假设备，全套 **218 项单元测试通过**，编译及差异格式检查通过；没有将模拟 GUI 验收计作游戏实机验证。

2026-10-18 接续用户进一步批准本次管理员启动：静音状态和同一 StarRail.exe 的有效签名/哈希核验后，正常 Windows `RunAs` 流程尝试一次，立即返回“拒绝访问”，事后 StarRail 进程数为 0。没有观察到 UAC 或游戏画面，没有再次尝试或修改安全权限。声音仍保持静音。证据在 `runs/admin-launch-20261018_1/`；本次仅保存记录，没有执行代码变更，最近代码回归仍为 218 项单测。启动与游戏内验证仍未完成，最小本机步骤见 [CURRENCY_WARS.md](CURRENCY_WARS.md)。
