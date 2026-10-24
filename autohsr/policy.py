"""Permanent exclusions requested by the user, applied before every click."""
from __future__ import annotations

import re

from .models import AutomationError, Scene, Token, normalize
from .du_card_effects import station_card_effect,preview_beacons

FORBIDDEN = ("跃迁", "抽卡", "商店", "合成", "充值", "购买", "续购", "续费", "订购", "兑换", "强化", "升级", "突破", "晋阶", "叠影", "培养", "养成", "角色", "光锥", "遗器", "背包")
PHONE_ALLOWED = ("委托", "指南", "星际和平指南", "邮件", "无名勋礼")
FORBIDDEN_ACTIONS = ("抽卡", "购买", "续购", "续费", "订购", "支付", "付款", "充值", "兑换", "强化", "升级", "突破", "晋阶", "叠影", "培养", "养成", "合成", "使用燃料", "使用星琼")


def du_last_area_confirm(scene: Scene) -> Token | None:
    """Identify the final route warning independently of the cards behind it."""
    body = ''.join(t.text for t in scene.tokens if t.within((.26,.43,.74,.55)))
    expected = '本次为最后一次区域选择阶段，之后将无法再进入储蓄间，是否继续？'
    modal = ''.join(t.text for t in scene.tokens if t.within((.23,.30,.77,.69)))
    if (not scene.has('提示',(.42,.34,.58,.42),exact=True)
            or normalize(body) != normalize(expected)
            or not scene.has('取消',(.29,.58,.49,.67),exact=True)
            or any(word in normalize(modal) for word in ('花费','消耗','支付','购买','星琼','燃料'))):
        return None
    return scene.find('确认',(.51,.58,.71,.67),exact=True)


def du_guide_details(scene):
    if not (scene.has('星际和平指南',(0,0,.32,.13))
            and scene.has('乐园漫记',(.36,.26,.88,.80))):
        return False
    if scene.has('拟合等级',(.36,.26,.88,.80)):
        return True
    levels=[t for t in scene.tokens if t.within((.41,.42,.53,.55))
            and re.fullmatch(r'[1-9]\d{0,2}',normalize(t.text))]
    return (len(levels)==1 and scene.has('已满级',(.39,.56,.56,.65),exact=True)
            and scene.has('奖励预览',(.55,.57,.68,.67),exact=True))


def has_du_field_plane_marker(text: str) -> bool:
    """Accept a known plane label or a narrowly corroborated OCR omission.

    Periodic-run HUD OCR occasionally drops the Chinese ordinal in ``第一位面``.
    Accept ``第位面`` only alongside the distinct first-plane ``1/13`` progress
    counter; a lone truncated label is not enough to authorize field actions.
    """
    context = normalize(text)
    if re.search(r"第[一二三四五六1-6]位面", context):
        return True
    return "第位面" in context and "1/13" in context


def du_encounter_field(scene: Scene) -> bool:
    header=normalize(''.join(t.text for t in scene.tokens if t.within((0,0,.32,.065))))
    return (has_du_field_plane_marker(header)
            and re.search(r'位面[-—]?奇遇[-—]?奇物合成',header) is not None)


def du_recruitment_candidates(scene: Scene) -> list[Token]:
    """Snow-owl recruitment uses bare region names on three fixed cards."""
    if not (scene.has('差分宇宙',(0,0,.32,.08),exact=True)
            and scene.has('人才管理阶段',(0,.04,.32,.11),exact=True)
            and scene.has('招聘阶段，请选择一个区域',(.23,.10,.77,.17),exact=True)):
        return []
    labels={'战斗','精英','首领','奖励','空白','休整','异常','事件','财富','冒险','铸造','商店'}
    result=[]
    for left,right in ((.14,.35),(.39,.60),(.65,.86)):
        found=[t for t in scene.tokens if normalize(t.text) in labels
               and t.within((left,.49,right,.55))]
        if len(found)!=1:
            return []
        result.append(found[0])
    return result


def replenishment_dialog(scene: Scene) -> bool:
    terms = ("星琼不足", "补充开拓力", "兑换开拓力", "使用燃料", "使用星琼", "开拓力补充", "开拓力不足", "购买开拓力")
    for token in scene.tokens:
        if not token.within((0.1, 0.1, 0.94, 0.95)) or normalize(token.text) == "快捷补充开拓力":
            continue
        if any(normalize(term) in normalize(token.text) for term in terms):
            return True
    return False


def guard_click(scene: Scene, target: Token | tuple[float, float], *, allow_differential_universe=False) -> None:
    point = target.center if isinstance(target, Token) else target
    if isinstance(target, Token):
        text = normalize(target.text)
        if scene.has('无名勋礼',(0,0,.32,.13),exact=True) and text.startswith('解锁无名客'):
            raise AutomationError('无名勋礼只允许领取已有免费奖励。')
        if any(text == normalize(word) or text.startswith(normalize(word)) for word in FORBIDDEN) or any(normalize(word) in text for word in FORBIDDEN_ACTIONS):
            raise AutomationError(f"用户禁项：禁止操作“{target.text}”。")
    phone = scene.has("开拓等级", (0.55, 0.05, 0.99, 0.35))
    if phone:
        # Menu icons sit above their labels. Require a permitted label in the
        # same column, so a coordinate cannot enter the gacha or training icons.
        matches = [t for t in scene.tokens if t.within((0.55, 0.25, 1, 1))
                   and (normalize(t.text) in map(normalize, PHONE_ALLOWED) or
                        (allow_differential_universe and normalize(t.text) == normalize("差分宇宙")))
                   and abs(t.center[0] - point[0]) < 0.035
                   and -0.09 < point[1] - t.center[1] < 0.025]
        from .free_rewards import mail_entry
        envelope=mail_entry(scene)
        verified_mail=(envelope is not None and isinstance(target,Token)
                       and target==envelope)
        if not matches and not verified_mail:
            raise AutomationError("手机菜单只允许进入委托、指南、邮件和无名勋礼。")
    # A forbidden page can be closed, but never operated. This also protects
    # runs started while the user happens to have a training screen open.
    danger = scene.find(FORBIDDEN, (0, 0, 0.32, 0.13), exact=True)
    if danger and not (isinstance(target, Token) and normalize(target.text) == "取消"):
        raise AutomationError(f"当前处于禁项页面“{danger.text}”，已停止点击。")


DU_SAFE_LABELS = (
    "指南", "星际和平指南",
    "差分宇宙", "开始游戏", "常规演算", "进入星阶模式", "拓星模式", "启动差分宇宙", "启动「差分宇宙」",
    "启动差分宇宙演算", "继续", "下一步", "进入下一位面", "继续探索", "继续演算", "开始演算",
    "开始挑战", "开始模拟", "开始探索", "进入战斗", "领取奖励", "选择祝福", "选择方程",
    "确认", "确认选择", "确认出战", "点击空白处关闭", "返回差分宇宙", "返回界面", "确定", "自动战斗",
    "离开", "离开商店", "返回", "关闭", "跳过", "进入区域",
)


def du_tutorial_close_prompt(scene: Scene) -> Token | None:
    exact=scene.find('点击空白处关闭',exact=True)
    if exact is not None:
        return exact
    # The deployed-beacon overlay can read 白 as 日 after its fade-in.
    # Keep this OCR exception tied to that heading and the bottom prompt.
    if not scene.has('信标已部署',(.25,.05,.75,.25),exact=True):
        return None
    return scene.find('点击空日处关闭',(.30,.85,.70,.98),exact=True)


def guard_differential_universe_field_input(scene: Scene, *, action: str) -> None:
    """Permit bounded movement or camera input only in the observed live field."""
    context = normalize(scene.text)
    truncated_battle_hud = (has_du_field_plane_marker(context) and re.search(r"位面[-—]?战", context)
                            and re.search(r"lv\s*\d+\s*/\s*20", context))
    if (not has_du_field_plane_marker(context)
            or not (any(s in context for s in ("战斗","精英","首领","异常","休整","奖励","事件","商店","财富","空白","铸造","冒险")) or truncated_battle_hud or du_encounter_field(scene))
            or any(normalize(term) in context for term in ("位面地图", "探索进度", "区域待选择"))):
        raise AutomationError(f"差分宇宙{action}输入只允许在已识别的位面现场场景中发送。")
    if any(normalize(term) in context for term in ("战斗失败", "模拟失败", "挑战成功", "模拟宇宙通关")):
        raise AutomationError(f"差分宇宙{action}输入遇到战斗结算页面，已停止。")


DU_CHEST_INTERACTIONS=('战利品','丰厚战利品','贵重战利品')
DU_NAMED_FIELD_INTERACTIONS=('造物调试台','维护市容（区域）',*DU_CHEST_INTERACTIONS)


def du_adventure_field(scene: Scene) -> bool:
    header=''.join(t.text for t in scene.tokens if t.within((0,0,.32,.065)))
    return has_du_field_plane_marker(header) and bool(re.search(r'位面[-—]?冒险',normalize(header)))


def du_hanu_adventure(scene: Scene) -> bool:
    return du_adventure_field(scene) and scene.has('哈努兄弟',(.24,.07,.80,.55),exact=True)


def du_named_field_interaction(scene: Scene) -> Token | None:
    names=DU_NAMED_FIELD_INTERACTIONS+(('开始挑战',) if du_hanu_adventure(scene) else ())
    target=scene.find(names,(.60,.45,.85,.70),exact=True)
    if target is not None and scene.image is not None:
        from .du_navigation import interaction_hint
        if interaction_hint(scene.image,threshold=.85):
            return target
    return None


def du_forge_console_menu(scene: Scene) -> bool:
    return (scene.has('造物调试台',(0,0,.32,.13),exact=True)
            and scene.has('选择加权奇物',(.58,.40,.95,.65),exact=True)
            and scene.has('装配或调整加权奇物',(.58,.43,.95,.70),exact=True))


def guard_differential_universe_field_interact(scene: Scene, target: Token) -> None:
    """Allow F only for a visible, non-spending anomaly interaction prompt."""
    context = normalize(scene.text)
    label = normalize(target.text)
    safe_prompts = tuple(map(normalize, ("交互", "调查", "触碰", "阅读", "对话", "启动", "开启", "拾取", "领取",
                                        "卡牌", "区域卡", "查看卡牌", "交互卡牌", "卡牌交互", "事件",*DU_NAMED_FIELD_INTERACTIONS,
                                        *(('开始挑战',) if du_hanu_adventure(scene) else ()))))
    combat_chest=('战斗' in context and label in DU_CHEST_INTERACTIONS
                  and target==du_named_field_interaction(scene))
    if (not has_du_field_plane_marker(context) or not (any(s in context for s in ('异常','奖励','事件','铸造','商店','财富','冒险')) or du_encounter_field(scene) or combat_chest)
            or not any(prompt == label or label.endswith(prompt) for prompt in safe_prompts)
            or not target.within((0.18, 0.18, 0.86, 0.86))
            or any(normalize(term) in label for term in ("购买", "兑换", "消耗", "碎片", "燃料", "星琼"))):
        raise AutomationError("异常区域的免费交互提示或目标位置未确认，未按 F。")
    if label in tuple(map(normalize,(*DU_NAMED_FIELD_INTERACTIONS,'开始挑战'))) and target!=du_named_field_interaction(scene):
        raise AutomationError('未核实名称交互的实时F提示，未交互。')
    if any(normalize(term) in context for term in ("位面地图", "探索进度", "区域待选择",
                                                    "补充开拓力", "使用燃料", "使用星琼")):
        raise AutomationError("异常区域交互遇到地图或禁用资源页面，未按 F。")


def guard_differential_universe_portal(scene: Scene, target: Token) -> None:
    """Only use the explicit F prompt for the requested random gate."""
    context = normalize(scene.text)
    if (normalize(target.text) != normalize("随意门") or
            not has_du_field_plane_marker(context) or not (any(s in context for s in ("战斗","精英","首领","异常","休整","奖励","事件","商店","财富","空白","铸造","冒险")) or du_encounter_field(scene)) or
            any(normalize(term) in context for term in ("位面地图", "探索进度", "区域待选择")) or
            not target.within((0.25, 0.30, 0.78, 0.75))):
        raise AutomationError("差分宇宙未确认位面战斗中的随意门交互提示，未按 F。")
    if any(normalize(term) in context for term in ("补充开拓力", "使用燃料", "星琼不足", "开拓力不足")):
        raise AutomationError("检测到禁用资源提示，未进入随意门。")


def du_station_hazard(scene: Scene) -> str | None:
    text=normalize(''.join(t.text for t in scene.tokens if t.within((.08,.14,.92,.33))))
    if ('跟你爆了' in text or
            all(term in text for term in ('敌人被消灭时自爆','我方全体','伤害'))):
        return 'enemy_death_party_explosion'
    return None


def du_miracle_randomize_two(scene: Scene) -> bool:
    """The observed free effect applies one conversion, then asks again."""
    effect = station_card_effect(scene)
    return effect is not None and effect.kind == 'randomize' and effect.count == 2


def du_miracle_target_labels(scene: Scene) -> tuple[str, ...]:
    """Supported free card effects, bound to their observed instruction."""
    effect = station_card_effect(scene)
    return effect.target_labels if effect is not None else ()


def du_event_free_leave(text: str) -> bool:
    label=normalize(text)
    prefixes=("离开","离去","算了","不感兴趣","拒绝","不拿")
    if label.startswith("米") and label[1:].startswith(prefixes):
        label=label[1:]  # Observed gold option star read as 米 by OCR.
    return (label.startswith(prefixes)
        and not any(word in label for word in ("消耗","失去","花费","购买","支付","扣除")))


def du_event_free_choice(scene: Scene,target: Token) -> bool:
    if du_event_free_leave(target.text):
        return True
    label=normalize(target.text).lstrip('★☆米*')
    if (target.within((.68,.18,.99,.90)) and label not in ('确定','确认')
            and not label.startswith(('与','和'))):
        body=normalize(''.join(t.text for t in scene.tokens if t.within((.68,.18,.99,.90))
                       and .015<t.center[1]-target.center[1]<.15
                       and normalize(t.text) not in ('确定','确认')))
        if (scene.has('商店街一番战',(.02,.70,.50,1),exact=True)
                and label=='叽里咕噜无语水果糖'
                and body=='获得300宇宙碎片获得1个和宇宙碎片相关的奇物'):
            return True
        if re.fullmatch(r'(?:与|和)[\u3400-\u9fff]{1,20}战斗胜利后获得[1-9]\d?个[1-3]星(?:祝福|奇物)和[1-9]\d{1,4}宇宙碎片',body):
            return True
        if re.fullmatch(r'(?:放弃战斗直接)?获得(?:[1-9]\d{1,4}宇宙碎片|[1-9]\d?个(?:随机)?(?:[1-3](?:-[1-3])?星)?(?:祝福|奇物))|有概率获得[1-3]星(?:祝福|奇物)',body):
            return True
    if (label!='触摸帝国的遗产' or not scene.has('帝国遗产',(.02,.70,.5,1),exact=True)
            or not target.within((.68,.18,.99,.90))):
        return False
    body=normalize(''.join(t.text for t in scene.tokens if t.within((.68,.18,.99,.90))
                   and .015<t.center[1]-target.center[1]<.15))
    return ('有极低的概率' in body and '获得300宇宙碎片' in body
            and not any(word in body for word in ('花费','消耗','扣除','支付')))


def du_flea_market_choice(scene: Scene,target: Token) -> bool:
    """A bounded in-run blessing trade, separate from free event choices."""
    if (not scene.has('事件',(0,0,.32,.13),exact=True)
            or not scene.has('跳蚤市场',(.02,.70,.50,1),exact=True)
            or not target.within((.68,.18,.99,.90))):
        return False
    label=normalize(target.text).lstrip('★☆米*')
    body=normalize(''.join(t.text for t in scene.tokens if t.within((.68,.18,.99,.90))
                   and .015<t.center[1]-target.center[1]<.15
                   and normalize(t.text) not in ('确定','确认')))
    return ((label=='讲述多彩的旅途' and body=='提交祝福')
            or (label=='雪原的赏金猎人' and body=='失去1个1星祝福获得3个2-3星祝福'))


def du_blessing_discard_prompt(scene: Scene) -> str | None:
    if (not scene.has('取消',(.29,.58,.49,.67),exact=True)
            or not scene.has('确认',(.51,.58,.71,.67),exact=True)):
        return None
    for token in scene.tokens:
        if token.within((.27,.43,.73,.54)):
            match=re.fullmatch('确认丢弃祝福「(.{1,40})」',normalize(token.text))
            if match:
                return match.group(1)
    return None


def guard_differential_universe_click(scene: Scene, target: Token | tuple[float, float], *, intent="navigation") -> None:
    """Only allow observed DU controls and narrowly defined in-run choices."""
    if not isinstance(target, Token):
        raise AutomationError("差分宇宙只允许点击 OCR 明确识别的按钮；坐标点击未授权。")
    if replenishment_dialog(scene):
        raise AutomationError("检测到开拓力补充界面，差分宇宙流程已停止。")
    if intent=='last_area_confirm':
        if target != du_last_area_confirm(scene):
            raise AutomationError('未核实最后一次区域选择提示及确认按钮，未点击。')
        return
    if intent=='adventure_result_exit':
        from .du_adventure import hanu_result_exit
        if target != hanu_result_exit(scene):
            raise AutomationError('未核实哈努冒险的拍摄结束及退出按钮，未点击。')
        return
    if intent=='du_tutorial_close':
        if target!=du_tutorial_close_prompt(scene):
            raise AutomationError('未核实说明页的当前关闭提示，未点击。')
        return
    if intent in ('du_supply_claim', 'du_supply_close'):
        from .workflows import DailyWorkflow
        claim = DailyWorkflow._supply_claim(scene)
        revealed = DailyWorkflow._supply_revealed(scene)
        central_content = any(t.within((.40,.45,.60,.68))
            and (normalize(t.text) in ('星琼','90°','90x')
                 or re.fullmatch(r'\d{1,4}', normalize(t.text))) for t in scene.tokens)
        if (claim is None or target != claim
                or (intent == 'du_supply_close' and not revealed)
                or (intent == 'du_supply_claim' and (revealed or central_content))):
            raise AutomationError('未核实已拥有的列车补给或90星琼展示，未点击。')
        return
    if intent.startswith('du_team_'):
        from .du_team import guard_click as guard_team_click
        # The requested name is checked by Context against its settings.
        guard_team_click(scene,target,intent,target.text)
        return
    if intent=='du_mode_select':
        if (not scene.has('模式选择',(0,0,.32,.13)) or scene.has('继续进度',exact=True)
                or normalize(target.text) not in ('周期演算','常规演算')
                or not target.within((.03,.23,.38,.70))):
            raise AutomationError('未核实演算模式入口，未启动。')
        return
    if intent.startswith('du_save_'):
        from .du_saves import guard_save_click
        guard_save_click(scene,target,intent)
        return
    if intent.startswith('du_reward_'):
        from .du_rewards import guard_click as guard_reward_click
        guard_reward_click(scene,target,intent)
        return
    text = normalize(target.text)
    if intent=='blessing_discard_prompt_confirm':
        if (du_blessing_discard_prompt(scene) is None or text!='确认'
                or not target.within((.51,.58,.71,.67))):
            raise AutomationError('祝福舍弃确认框未核实，未确认。')
        return
    if intent in ('blessing_discard_select','blessing_discard_confirm'):
        from .du_strategy import rarity
        valid=(scene.has('丢弃祝福',(0,0,.32,.13),exact=True) and scene.has('请舍弃祝福')
               and all(rarity(scene,x)==1 for x in (.25,.5,.75)))
        if intent=='blessing_discard_select':
            valid=valid and text=='祝福候选卡片' and target.within((.14,.28,.87,.36))
        else:
            valid=valid and text=='丢弃' and target.within((.56,.78,.99,.98))
        if not valid:
            raise AutomationError('未核实一星祝福舍弃页面、星级或按钮，未丢弃。')
        return
    if intent in ('event_flea_select','event_flea_confirm'):
        permitted=[t for t in scene.tokens if du_flea_market_choice(scene,t)]
        valid=(target in permitted if intent=='event_flea_select' else
            text in ('确定','确认') and target.within((.75,.18,.99,.94))
            and any(.02<target.center[1]-t.center[1]<.16 for t in permitted))
        if not valid:
            raise AutomationError('未核实跳蚤市场的一星祝福换高星祝福路径，未提交。')
        return
    if intent in ('event_star_select','event_star_confirm'):
        from .du_events import guard as guard_event_star
        guard_event_star(scene,target,intent)
        return
    if intent in ("event_advance","event_leave","event_open_selection","event_confirm"):
        if not scene.has("事件",(0,0,.32,.13),exact=True):
            raise AutomationError("未核实差分宇宙事件页面。")
        if intent=="event_advance":
            valid=(text=="事件对话继续" and target.score>=.88
                and target.within((.75,.55,.90,.84)))
        elif intent=="event_open_selection":
            valid=text=="选择" and target.within((.70,.58,.99,.84))
        elif intent=="event_confirm":
            valid=(text in ("确定","确认") and target.within((.75,.18,.99,.94))
                and any(du_event_free_choice(scene,t) and t.within((.68,.18,.99,.90))
                    and .02<target.center[1]-t.center[1]<.16 for t in scene.tokens))
        else:
            valid=du_event_free_choice(scene,target) and target.within((.68,.18,.99,.90))
        if not valid:
            raise AutomationError("事件继续箭头或免费离开选项未核实。")
        return
    if intent=="station_icon_select":
        if (text!="差分宇宙战斗站点卡图标" or target.score<.90
                or not target.within((.20,.32,.73,.73))
                or not scene.has("选择下一站",(0,0,.32,.13))
                or not scene.has("选择一张站点卡",(.2,.15,.8,.36))):
            raise AutomationError("战斗站点卡图标或当前选择页未核实。")
        return
    if intent in ("curio_discard_select","curio_discard_confirm"):
        context=normalize(scene.text)
        if (not scene.has("丢弃奇物",(0,0,.32,.13))
                or not re.search(r"(?:需|须)舍弃1次奇物",context)):
            raise AutomationError("未核实当前局内强制舍弃奇物页面。")
        if intent == "curio_discard_select":
            valid=bool(re.search(r"[\u3400-\u9fff]{2}",target.text)) and target.within((.14,.35,.87,.54))
        else:
            valid=text in ("丢弃","丢弃·") and target.within((.78,.85,.99,.96))
        if not valid:
            raise AutomationError("强制舍弃奇物候选或确认按钮未核实。")
        return
    if intent in ("miracle_target","miracle_target_confirm"):
        labels=du_miracle_target_labels(scene)
        if not labels:
            raise AutomationError("未核实奇迹的站点卡目标页。")
        if intent == "miracle_target":
            valid=text in labels and target.within((.03,.24,.64,.78))
        else:
            valid=text in ("确定","确认") and target.within((.72,.82,.99,.96))
            effect=station_card_effect(scene)
            if effect.kind=='reroll_beacons' and not preview_beacons(scene):
                raise AutomationError('重置信标前未在当前卡片详情中核实已有信标。')
        if not valid:
            raise AutomationError("奇迹站点卡目标或确认按钮未核实。")
        return
    if intent == "du_resume_menu":
        if (not scene.has("模式选择",(0,0,.32,.13)) or not scene.has("进行中")
                or text!=normalize("继续进度") or not target.within((.18,.64,.42,.76))):
            raise AutomationError("未核实模式页已有进度与继续按钮，未接续。")
        return
    if intent == "du_resume_confirm":
        if (not all(term in normalize(scene.text) for term in ("当前存档非本周演算进度","确定继续进度吗"))
                or text!=normalize("确认") or not target.within((.51,.58,.71,.67))):
            raise AutomationError("未核实过期演算接续提示，未确认。")
        return
    if intent in ("du_guide_tab","du_guide_select","du_guide_enter"):
        if not scene.has("星际和平指南",(0,0,.32,.13)):
            raise AutomationError("未核实星际和平指南，未进入差分宇宙。")
        if intent == "du_guide_tab":
            valid=text==normalize("差分宇宙指南页签") and target.within((.28,.15,.35,.24))
        elif intent == "du_guide_select":
            valid=(text==normalize("差分宇宙") and target.within((.14,.26,.35,.82))
                   and scene.has(("旷宇纷争","寰宇纷争"),(0,0,.32,.13)))
        else:
            valid=(text==normalize("前往参与") and target.within((.70,.75,.88,.87))
                   and du_guide_details(scene))
        if not valid:
            raise AutomationError("差分宇宙指南入口的类别、位置或详情未核实。")
        return
    if intent == 'du_low_rank_confirm':
        if (text!=normalize('确认') or not target.within((.51,.58,.71,.66))
                or not scene.has('均衡等级大幅超过当前难度，无法获得解锁材料、拟合值和积分',(.27,.44,.73,.53))
                or not scene.has('取消',(.29,.58,.49,.66),exact=True)):
            raise AutomationError('未核实最低难度的无奖励提示，未确认。')
        return
    if intent == "periodic_start":
        context = normalize(scene.text)
        if (text not in {normalize("启动「差分宇宙」"), normalize("启动差分宇宙")}
                or not all(term in context for term in map(normalize, ("差分宇宙", "周期演算", "难度")))
                or not target.within((0.72, 0.82, 1, 0.98))):
            raise AutomationError("周期演算页或启动按钮未核实，未启动。")
        if any(normalize(term) in context for term in ("补充开拓力", "使用燃料", "使用星琼", "星琼不足")):
            raise AutomationError("检测到禁用资源提示，未启动周期演算。")
        return
    if intent == "difficulty_selection":
        if (text != normalize("差分宇宙难度I") or not target.within((0.015, 0.08, 0.12, 0.23))
                or not all(term in normalize(scene.text) for term in map(normalize, ("差分宇宙", "乐园漫记", "难度")))):
            raise AutomationError("差分宇宙最低难度选择器或配置页未核实，未点击。")
        if any(normalize(term) in normalize(scene.text) for term in ("星琼不足", "补充开拓力", "使用燃料")):
            raise AutomationError("检测到体力或星琼提示，未选择难度。")
        return
    if intent == "area_select":
        recruitment=du_recruitment_candidates(scene)
        if recruitment and target in recruitment:
            return
        safe_area = re.fullmatch(r"区域[-— ]?(?:战斗|随机|休整|商店|合成|冒险|事件|奖励|首领)|(?:战斗|随机|休整|商店|合成|冒险|事件|奖励|首领)区域", text)
        if (not safe_area or not any(normalize(term) in normalize(scene.text) for term in
                                     ("选择区域", "区域选择", "抽取区域", "选择一个区域", "区域待选择"))
                or not target.within((0.12, 0.16, 0.98, 0.88))):
            raise AutomationError("差分宇宙区域候选或选择页未核实，未点击。")
        if any(normalize(term) in normalize(target.text) for term in ("充值", "燃料", "星琼", "开拓力", "购买")):
            raise AutomationError("区域候选包含禁用资源操作，未点击。")
        return
    if intent == 'area_recruit_confirm':
        if (not du_recruitment_candidates(scene) or target not in scene.tokens
                or text!='确认' or not target.within((.38,.86,.62,.95))):
            raise AutomationError('未核实人才招聘区域与确认按钮，未确认。')
        return
    if intent == "leave_area":
        if (text not in map(normalize, ("离开", "离开商店", "返回", "返回差分宇宙", "返回差分宇宙主界面",
                                        "关闭", "跳过", "继续"))
                or not any(normalize(term) in normalize(scene.text) for term in ("商店", "合成", "休整", "事件"))):
            raise AutomationError("差分宇宙区域离开按钮或当前页面未核实，未点击。")
        if any(normalize(term) in normalize(scene.text) for term in ("星琼不足", "补充开拓力", "使用燃料")):
            raise AutomationError("检测到禁用资源提示，未离开页面。")
        return
    if intent in ("station_select","station_confirm"):
        # A station named 商店 is a route choice; it does not purchase an item.
        context=normalize(scene.text)
        labels={"战斗","精英","首领","奖励","空白","休整","异常","事件","财富","冒险","铸造","商店"}
        if "选择下一站" not in context:
            raise AutomationError("未核实差分宇宙下一站选择页，未点击。")
        if intent=="station_select":
            valid=text in labels and target.within((.20,.54,.73,.82))
        else:
            valid=(any(label in context for label in labels)
                   and text in ("确认","确定","进入区域","进入下一站")
                   and target.within((.48,.78,.98,.99))
                   and du_station_hazard(scene) is None)
        if not valid:
            raise AutomationError("差分宇宙站点卡或确认按钮未核实，未点击。")
        return
    if intent == "dismiss_mask_reward":
        if (text != normalize("点击空白处关闭") or
                not all(normalize(term) in normalize(scene.text) for term in ("敷衍面具", "获得愿力")) or
                not target.within((0.42, 0.74, 0.62, 0.94))):
            raise AutomationError("差分宇宙面具升级奖励或空白关闭位置未核实，未点击。")
        return
    if (intent=='choice' and text=='跃迁复眼' and target in scene.tokens
            and scene.has('差分宇宙',(0,0,.32,.13))
            and scene.has('选择奇物',(0,0,.32,.13),exact=True)
            and scene.has('请选择奇物',(.30,.10,.70,.20),exact=True)
            and target.within((.14,.43,.87,.53))):
        # This is a named free curio on the reward card grid, not the Warp UI.
        return
    if any(normalize(word) in text for word in FORBIDDEN_ACTIONS + FORBIDDEN):
        raise AutomationError(f"用户禁项：差分宇宙禁止操作“{target.text}”。")
    if replenishment_dialog(scene):
        raise AutomationError("检测到开拓力补充界面，差分宇宙流程已停止。")
    if scene.has("开拓等级", (0.55, 0.05, 0.99, 0.35)):
        guard_click(scene, target, allow_differential_universe=True)
    danger = scene.find(FORBIDDEN, (0, 0, 0.32, 0.13), exact=True)
    if danger:
        raise AutomationError(f"当前处于禁项页面“{danger.text}”，差分宇宙流程已停止。")
    allowed_navigation = any(text == normalize(label) or text.startswith(normalize(label)) for label in DU_SAFE_LABELS)
    if intent == 'field_forward_attack':
        header=''.join(token.text for token in scene.tokens if token.within((0,0,.32,.065)))
        if (text!=normalize('差分宇宙直行接战') or not has_du_field_plane_marker(header)
                or not re.search(r'位面[-—]?(?:战斗|精英|首领)',normalize(header))
                or not target.within((.45,.40,.55,.55))):
            raise AutomationError('未核实直行后的战斗位面现场，未发送基础攻击。')
    elif intent == 'field_ring_attack':
        from .du_navigation import attack_reticle
        ring=attack_reticle(scene)
        if (ring is None or target!=ring or not has_du_field_plane_marker(scene.text)
                or not scene.has('等级',(.38,.01,.64,.10))
                or not any(s in normalize(scene.text) for s in ('战斗','精英','首领'))):
            raise AutomationError('未核实当前战斗位面的敌人信息条与实时攻击圆环，未攻击。')
    elif intent == "field_attack":
        context = normalize(scene.text)
        truncated_battle_hud = (has_du_field_plane_marker(context) and re.search(r"位面[-—]?战", context)
                                and re.search(r"lv\s*\d+\s*/\s*20", context))
        if (text != normalize("差分宇宙基础攻击") or not has_du_field_plane_marker(context)
                or not (any(s in context for s in ("战斗","精英","首领")) or truncated_battle_hud)
                or not target.within((0.82, 0.75, 0.94, 0.95))):
            raise AutomationError("差分宇宙基础攻击图标或第一位面战斗画面未确认，未点击。")
    elif intent == "field_target_attack":
        context = normalize(scene.text)
        truncated_battle_hud = (re.search(r"第[一二三四五六1-6]位面[-—]?战", context)
                                and re.search(r"lv\s*\d+\s*/\s*20", context))
        if (text != normalize("差分宇宙已锁定敌方目标") or not has_du_field_plane_marker(context)
                or not ("战斗" in context or truncated_battle_hud)
                or not target.within((0.08, 0.15, 0.80, 0.82))):
            raise AutomationError("差分宇宙锁定目标或第一位面战斗画面未确认，未点击。")
    elif intent == "field_enemy_attack":
        context = normalize(scene.text)
        truncated_battle_hud = (re.search(r"第[一二三四五六1-6]位面[-—]?战", context)
                                and re.search(r"lv\s*\d+\s*/\s*20", context))
        enemy_label = "等级" in context and any(name in context for name in map(normalize,
            ("惊梦剧团", "幻造生物")))
        if (text != normalize("差分宇宙可见敌方目标") or not enemy_label
                or not has_du_field_plane_marker(context)
                or not ("战斗" in context or truncated_battle_hud)
                or not target.within((0.06, 0.25, 0.82, 0.90))):
            raise AutomationError("差分宇宙位面战斗页面、敌人标签或目标模板位置未核实，未点击。")
    elif intent == "choice":
        du_context = normalize(scene.text)
        field_header=''.join(token.text for token in scene.tokens if token.within((0,0,.32,.065)))
        if has_du_field_plane_marker(field_header):
            raise AutomationError("位面现场交互提示不是选项页，未点击场景 HUD。")
        known_choice_page = any(term in du_context for term in map(normalize,
            ("祝福", "方程", "奇物", "面具", "奇迹", "选择区域", "区域选择", "抽取区域", "位面地图",
             "休整区", "休息区", "事件", "遭遇", "模拟宇宙通关")))
        if not known_choice_page or not target.within((0.16, 0.18, 0.96, 0.84)):
            raise AutomationError("差分宇宙选择页或候选位置未能确认，已停止点击。")
    elif intent == "choice_confirm":
        du_context = normalize(scene.text)
        known_choice_page = any(term in du_context for term in map(normalize,
            ("祝福", "方程", "奇物", "面具效果", "奇迹")))
        if (not known_choice_page
                or text not in {normalize("确认选择"), normalize("确认"), normalize("确定")}
                or not target.within((0.56, 0.78, 0.99, 0.98))):
            raise AutomationError("差分宇宙奖励确认页或按钮位置未确认，未点击。")
    elif intent != "navigation" or not allowed_navigation:
        raise AutomationError(f"差分宇宙按钮“{target.text}”不在安全白名单中，已停止并留证。")
