# 货币战争装备识别参考图

来源：[March7thAssistant](https://github.com/moesnow/March7thAssistant/tree/7cf6c6bed474539485d3b1504077ac352866829f/assets/images/share/aglaea)，作者moesnow及其贡献者。固定提交`7cf6c6bed474539485d3b1504077ac352866829f`，2026-10-29取得；18幅PNG为原始字节，没有裁切、缩放或重编码。

每幅图的原路径、Git blob、SHA-256、字节数和变换记录见[sources.json](sources.json)。上游采用GNU GPL v3，完整许可见[LICENSE](../LICENSE)，适配范围见[上级来源说明](../README.md)。游戏装备美术及名称仍归游戏权利人所有，上游代码许可不表示取得这些游戏素材的所有权。

| 文件 | 本地识别标识／含义 |
| --- | --- |
| e1.png | star／幸运星 |
| e2.png | life_flower／生命之花 |
| e3.png | pistol／和平手枪 |
| e4.png | battery／光能电池 |
| e5.png | drill／以太钻头 |
| e6.png | armor／量产型装甲 |
| e7.png | knife／折叠小刀 |
| shoe.png | shoe／轮滑鞋 |
| boots.png | boots／反重力皮靴 |
| firestorm.png | firestorm／火力风暴潮 |
| chainsaw.png | chainsaw／高周波电锯 |
| propeller.png | propeller／光速螺旋桨 |
| projector.png、projector2.png | 员工投影仪、完美投影仪，尚未接入使用 |
| token.png、stove.png | 好运令牌、冶金炉，尚未接入使用 |
| wrench.png、wrench2.png | 上游两种拆装扳手参考，尚未接入使用 |

识别另复用已有原生[很硬的甲](../../../templates/currency_hard_armor_4_6.png)、[蓄能帆](../../../templates/currency_energy_sail_4_6.png)，以及电池和装甲的旧校准变体；原始采集与哈希继续保留在[素材署名](../../../ATTRIBUTION.md)。这些已有文件未在本轮改写。

仓库、已穿戴槽位和推荐图分别识别，不以图标出现代替输入许可。匹配至少0.92且最佳候选与次优候选至少相差0.025；无法区分保持未知。配方材料分别识别并保留重复项，例如两件装甲仍是两个材料，不能去重成一件。默认合成依赖当前展开的推荐面板；上游源码明示的两条希儿配方单独保留，未知配方不猜测。

12格仓库扫描只覆盖已校准的可穿戴装备区域；顶部消耗品、任意未知装备和所有配方并未因此获得执行资格。现有两份旧画面用于字段校准和回放，不是独立实机验收、模型训练集或新留出集。完整机制验证见[开发记录](../../../../docs/currency-wars-development.md)。
