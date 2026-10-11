"""Permanent exclusions requested by the user, applied before every click."""
from __future__ import annotations

from .models import AutomationError, Scene, Token, normalize

FORBIDDEN = ("跃迁", "抽卡", "商店", "合成", "充值", "购买", "续购", "续费", "订购", "兑换", "强化", "升级", "突破", "晋阶", "叠影", "培养", "养成", "角色", "光锥", "遗器", "背包")
PHONE_ALLOWED = ("委托", "指南", "星际和平指南", "邮件", "无名勋礼")
FORBIDDEN_ACTIONS = ("抽卡", "购买", "续购", "续费", "订购", "支付", "付款", "充值", "兑换", "强化", "升级", "突破", "晋阶", "叠影", "培养", "养成", "合成", "使用燃料", "使用星琼")


def replenishment_dialog(scene: Scene) -> bool:
    terms = ("星琼不足", "补充开拓力", "兑换开拓力", "使用燃料", "使用星琼", "开拓力补充", "开拓力不足", "购买开拓力")
    for token in scene.tokens:
        if not token.within((0.1, 0.1, 0.94, 0.95)) or normalize(token.text) == "快捷补充开拓力":
            continue
        if any(normalize(term) in normalize(token.text) for term in terms):
            return True
    return False


def guard_click(scene: Scene, target: Token | tuple[float, float]) -> None:
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
                   and normalize(t.text) in map(normalize, PHONE_ALLOWED)
                   and abs(t.center[0] - point[0]) < 0.035
                   and -0.09 < point[1] - t.center[1] < 0.025]
        if not matches:
            raise AutomationError("手机菜单只允许进入委托、指南、邮件和无名勋礼。")
    # A forbidden page can be closed, but never operated. This also protects
    # runs started while the user happens to have a training screen open.
    danger = scene.find(FORBIDDEN, (0, 0, 0.32, 0.13), exact=True)
    if danger and not (isinstance(target, Token) and normalize(target.text) == "取消"):
        raise AutomationError(f"当前处于禁项页面“{danger.text}”，已停止点击。")
