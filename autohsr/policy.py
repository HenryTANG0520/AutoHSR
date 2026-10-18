"""Permanent exclusions requested by the user, applied before every click."""
from __future__ import annotations

import re

from .models import AutomationError, Scene, Token, normalize

FORBIDDEN = ("跃迁", "抽卡", "商店", "合成", "充值", "购买", "续购", "续费", "订购", "兑换", "强化", "升级", "突破", "晋阶", "叠影", "培养", "养成", "角色", "光锥", "遗器", "背包")
PHONE_ALLOWED = ("委托", "指南", "星际和平指南", "邮件", "无名勋礼")
FORBIDDEN_ACTIONS = ("抽卡", "购买", "续购", "续费", "订购", "支付", "付款", "充值", "兑换", "强化", "升级", "突破", "晋阶", "叠影", "培养", "养成", "合成", "使用燃料", "使用星琼")


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
        if not matches:
            raise AutomationError("手机菜单只允许进入委托、指南、邮件和无名勋礼。")
    # A forbidden page can be closed, but never operated. This also protects
    # runs started while the user happens to have a training screen open.
    danger = scene.find(FORBIDDEN, (0, 0, 0.32, 0.13), exact=True)
    if danger and not (isinstance(target, Token) and normalize(target.text) == "取消"):
        raise AutomationError(f"当前处于禁项页面“{danger.text}”，已停止点击。")


DU_SAFE_LABELS = (
    "差分宇宙", "开始游戏", "常规演算", "进入星阶模式", "拓星模式", "启动差分宇宙", "启动「差分宇宙」",
    "启动差分宇宙演算", "继续", "下一步", "进入下一位面", "继续探索", "继续演算", "开始演算",
    "开始挑战", "开始模拟", "开始探索", "进入战斗", "领取奖励", "选择祝福", "选择方程",
    "确认", "确认选择", "确认出战", "点击空白处关闭", "返回差分宇宙", "返回界面", "确定", "自动战斗",
    "离开", "离开商店", "返回", "关闭", "跳过", "进入区域",
)


def guard_differential_universe_field_input(scene: Scene, *, action: str) -> None:
    """Permit bounded movement or camera input only in the observed live field."""
    context = normalize(scene.text)
    truncated_battle_hud = (re.search(r"第[一二三四五六1-6]位面[-—]?战", context)
                            and re.search(r"lv\s*\d+\s*/\s*20", context))
    if (not has_du_field_plane_marker(context)
            or not ("战斗" in context or "异常" in context or truncated_battle_hud)
            or any(normalize(term) in context for term in ("位面地图", "探索进度", "区域待选择"))):
        raise AutomationError(f"差分宇宙{action}输入只允许在已识别的位面现场场景中发送。")
    if any(normalize(term) in context for term in ("战斗失败", "模拟失败", "挑战成功", "模拟宇宙通关")):
        raise AutomationError(f"差分宇宙{action}输入遇到战斗结算页面，已停止。")


def guard_differential_universe_field_interact(scene: Scene, target: Token) -> None:
    """Allow F only for a visible, non-spending anomaly interaction prompt."""
    context = normalize(scene.text)
    label = normalize(target.text)
    safe_prompts = tuple(map(normalize, ("交互", "调查", "触碰", "阅读", "对话", "启动", "开启", "拾取", "领取",
                                        "卡牌", "区域卡", "查看卡牌", "交互卡牌", "卡牌交互")))
    if (not has_du_field_plane_marker(context) or "异常" not in context
            or not any(prompt == label or label.endswith(prompt) for prompt in safe_prompts)
            or not target.within((0.18, 0.18, 0.86, 0.86))
            or any(normalize(term) in label for term in ("购买", "兑换", "消耗", "碎片", "燃料", "星琼"))):
        raise AutomationError("异常区域的免费交互提示或目标位置未确认，未按 F。")
    if any(normalize(term) in context for term in ("位面地图", "探索进度", "区域待选择",
                                                    "补充开拓力", "使用燃料", "使用星琼")):
        raise AutomationError("异常区域交互遇到地图或禁用资源页面，未按 F。")


def guard_differential_universe_portal(scene: Scene, target: Token) -> None:
    """Only use the explicit F prompt for the requested random gate."""
    context = normalize(scene.text)
    if (normalize(target.text) != normalize("随意门") or
            not has_du_field_plane_marker(context) or "战斗" not in context or
            any(normalize(term) in context for term in ("位面地图", "探索进度", "区域待选择")) or
            not target.within((0.25, 0.30, 0.78, 0.75))):
        raise AutomationError("差分宇宙未确认位面战斗中的随意门交互提示，未按 F。")
    if any(normalize(term) in context for term in ("补充开拓力", "使用燃料", "星琼不足", "开拓力不足")):
        raise AutomationError("检测到禁用资源提示，未进入随意门。")


def guard_differential_universe_click(scene: Scene, target: Token | tuple[float, float], *, intent="navigation") -> None:
    """Only allow explicit, non-spending controls on observed DU pages."""
    if not isinstance(target, Token):
        raise AutomationError("差分宇宙只允许点击 OCR 明确识别的按钮；坐标点击未授权。")
    text = normalize(target.text)
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
        safe_area = re.fullmatch(r"区域[-— ]?(?:战斗|随机|休整|商店|合成|冒险|事件|奖励|首领)|(?:战斗|随机|休整|商店|合成|冒险|事件|奖励|首领)区域", text)
        if (not safe_area or not any(normalize(term) in normalize(scene.text) for term in
                                     ("选择区域", "区域选择", "抽取区域", "选择一个区域", "区域待选择"))
                or not target.within((0.12, 0.16, 0.98, 0.88))):
            raise AutomationError("差分宇宙区域候选或选择页未核实，未点击。")
        if any(normalize(term) in normalize(target.text) for term in ("充值", "燃料", "星琼", "开拓力", "购买")):
            raise AutomationError("区域候选包含禁用资源操作，未点击。")
        return
    if intent == "leave_area":
        if (text not in map(normalize, ("离开", "离开商店", "返回", "返回差分宇宙", "返回差分宇宙主界面",
                                        "关闭", "跳过", "继续"))
                or not any(normalize(term) in normalize(scene.text) for term in ("商店", "合成", "休整", "事件"))):
            raise AutomationError("差分宇宙区域离开按钮或当前页面未核实，未点击。")
        if any(normalize(term) in normalize(scene.text) for term in ("星琼不足", "补充开拓力", "使用燃料")):
            raise AutomationError("检测到禁用资源提示，未离开页面。")
        return
    if intent == "dismiss_mask_reward":
        if (text != normalize("点击空白处关闭") or
                not all(normalize(term) in normalize(scene.text) for term in ("敷衍面具", "获得愿力")) or
                not target.within((0.42, 0.74, 0.62, 0.94))):
            raise AutomationError("差分宇宙面具升级奖励或空白关闭位置未核实，未点击。")
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
    if intent == "field_attack":
        context = normalize(scene.text)
        truncated_battle_hud = (re.search(r"第[一二三四五六1-6]位面[-—]?战", context)
                                and re.search(r"lv\s*\d+\s*/\s*20", context))
        if (text != normalize("差分宇宙基础攻击") or not has_du_field_plane_marker(context)
                or not ("战斗" in context or truncated_battle_hud)
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
    elif intent == "station_select":
        du_context = normalize(scene.text)
        if ("选择下一站" not in du_context
                or not any(term in du_context for term in map(normalize, ("战斗", "异常", "铸造")))
                or text not in {normalize("战斗"), normalize("异常")}
                or not target.within((0.20, 0.54, 0.65, 0.82))):
            raise AutomationError("差分宇宙站点卡或战斗/异常区域候选位置未确认，未点击。")
    elif intent == "station_confirm":
        du_context = normalize(scene.text)
        if ("选择下一站" not in du_context
                or not any(term in du_context for term in map(normalize, ("战斗", "异常", "铸造")))
                or text not in {normalize("确认"), normalize("确定"), normalize("进入区域"), normalize("进入下一站")}
                or not target.within((0.48, 0.78, 0.98, 0.99))):
            raise AutomationError("差分宇宙站点卡确认按钮未确认，未点击。")
    elif intent != "navigation" or not allowed_navigation:
        raise AutomationError(f"差分宇宙按钮“{target.text}”不在安全白名单中，已停止并留证。")
