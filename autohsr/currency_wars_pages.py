"""Currency Wars screens calibrated from the local 4.6.0 captures.

These labels describe visible UI only. They never authorize a gameplay action
or imply that the tutorial, economy, or a match has been verified.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ROI, Token, normalize


PAGE_LABELS = {
    "world_entry": "朝露公馆交互入口，尚未打开玩法",
    "lobby": "货币战争主页",
    "guide_list": "热门攻略列表",
    "guide_detail": "攻略阵容与运营详情",
    "saved_teams": "已保存阵容列表",
    "team_save": "保存阵容槽位选择",
    "guide_legend": "攻略图例",
    "mode_select": "博弈模式选择",
    "difficulty_select": "超频难度选择",
    "boss_preview": "开局首领预览",
    "standard_rules": "标准博弈规则说明",
    "overclock_rules": "超频博弈规则说明",
    "tutorial": "玩法教学",
    "environment": "投资环境选择",
    "guide_applied": "局内已应用攻略",
    "preparation": "备战阶段",
    "shop": "备战商店",
    "character": "角色信息面板",
    "node_result": "节点挑战结算（非整局通关）",
    "gemi_info": "Gemi 狸信息说明",
    "star_selection": "盛会之星强化角色选择",
    "equipment_info": "简易装备信息与可合成列表",
    "battle": "货币战争节点战斗",
    "supply_selection": "补给角色与装备选择",
    "equipment_selection": "简易武装箱装备选择",
    "advanced_equipment_selection": "进阶武装箱装备选择",
    "expert_selection": "专家邀请函选择",
    "hiring_selection": "聘用书选择",
    "token_selection": "好运令牌装备选择",
    "bench_full": "备战席已满，等待整理",
    "plane_map": "位面进度地图",
    "investment_selection": "投资策略选择",
    "boss_intro": "强敌来袭介绍",
    "final_victory": "最终首领胜利，等待结算",
    "match_rating": "整局挑战评价",
    "match_summary": "整局胜利阵容总览",
    "match_statistics": "整局伤害统计与返回",
}


def _text(value: str) -> str:
    return normalize(value).translate(str.maketrans("", "", "「」『』【】"))


@dataclass(frozen=True)
class _Anchor:
    label: str | re.Pattern
    roi: ROI

    def matches(self, token: Token) -> bool:
        if not token.within(self.roi):
            return False
        value = _text(token.text)
        return value == _text(self.label) if isinstance(self.label, str) else bool(self.label.fullmatch(value))


# Modals take precedence over any background text still visible through them.
_MODALS = {
    "boss_intro": (
        _Anchor("强敌来袭", (.47,.34,.62,.40)),
        _Anchor(re.compile(r"等级[1-9][0-9]{0,2}.{2,40}"), (.45,.43,.85,.51)),
        _Anchor("点击空白处继续", (.43,.70,.57,.77)),
    ),
    "investment_selection": (
        _Anchor("请选择投资策略", (.44,.07,.56,.11)),
        _Anchor("返回备战界面", (.85,.02,1,.08)),
        _Anchor("图例", (.09,.07,.14,.11)),
        _Anchor(re.compile(r"刷新次数[0-9]{1,2}"), (.1,.76,.9,.84)),
        _Anchor("确认", (.47,.89,.53,.93)),
    ),
    "equipment_selection": (
        _Anchor("简易武装箱", (.53, .03, .65, .08)),
        _Anchor("请选择1个", (.53, .07, .65, .11)),
        _Anchor("查看详情", (.45, .29, .55, .34)),
        _Anchor("查看详情", (.60, .29, .70, .34)),
    ),
    "advanced_equipment_selection": (
        _Anchor("进阶武装箱", (.53, .03, .65, .08)),
        _Anchor("请选择1个", (.53, .07, .65, .11)),
        _Anchor("查看详情", (.45, .29, .55, .34)),
        _Anchor("查看详情", (.60, .29, .70, .34)),
    ),
    "expert_selection": (
        _Anchor("专家邀请函", (.49, .03, .59, .08)),
        _Anchor("请选择1个专家顾问，该角色在选择后同步加入商店", (.40, .07, .68, .11)),
        _Anchor("现金为王", (.14, .33, .9, .39)),
    ),
    "hiring_selection": (
        _Anchor(re.compile(r'(?:[1-5]费)?聘用书'), (.3,.02,.7,.10)),
        _Anchor(re.compile(r'请选择1(?:个|名)(?:角色)?'), (.3,.06,.75,.13)),
    ),
    "token_selection": (
        _Anchor("好运令牌",(.3,.02,.75,.10)),
        _Anchor("请选择1个",(.3,.06,.8,.14)),
        _Anchor("查看详情",(.35,.27,.6,.36)),
        _Anchor("查看详情",(.6,.27,.85,.36)),
    ),
    "equipment_info": (
        _Anchor("简易装备", (.75, .15, .9, .21)),
        _Anchor("可合成列表", (.77, .27, .90, .33)),
    ),
    "star_selection": (
        _Anchor("盛会之星", (.45, .04, .65, .10)),
        _Anchor("请选择1名角色成为巨星", (.45, .10, .65, .15)),
        _Anchor("请选择强化角色", (.65, .44, .88, .50)),
        _Anchor("确认选择", (.68, .49, .87, .56)),
    ),
    "gemi_info": (
        _Anchor("Gemi狸", (.77, .43, .87, .49)),
        _Anchor("后台", (.78, .47, .86, .52)),
        _Anchor(re.compile(r"gemi狸-货币战争专属模型2\.0已发布全自动"), (.72, .53, .98, .59)),
        _Anchor("商店刷新、角色购买、还有战斗就都交给它", (.72, .57, .98, .62)),
    ),
    "tutorial": (
        _Anchor("教学目录", (0, 0, .25, .14)),
        _Anchor("搜索教学", (0, .08, .3, .25)),
        _Anchor("上一页", (.45, .82, .8, .97)),
    ),
    "overclock_rules": (
        _Anchor("超频博弈规则", (.2, .25, .5, .36)),
        _Anchor("超频博弈", (.2, .33, .45, .43)),
        _Anchor(re.compile(r"超频博弈不会影响当前职级"), (.2, .5, .85, .8)),
    ),
    "character": (
        _Anchor(re.compile(r"前后台|前台|日?后台"), (.78, .22, .9, .28)),
        _Anchor("装备推荐", (.72, .7, .85, .8)),
        _Anchor("详情", (.72, .8, .84, .88)),
        _Anchor("出售", (.88, .8, .98, .88)),
        _Anchor("购买经验", (.1, .75, .2, .85)),
    ),
    "shop": (
        _Anchor("备战阶段", (.1, .02, .2, .09)),
        _Anchor("刷新", (.8, .4, .89, .49)),
        _Anchor(re.compile(r"[■□]?[0-9]{1,3}%"), (.49, .33, .55, .39)),
        _Anchor(re.compile(r"[■□]?[0-9]{1,3}%"), (.55, .33, .6, .39)),
        _Anchor(re.compile(r"[■□]?[0-9]{1,3}%"), (.6, .33, .64, .39)),
        _Anchor(re.compile(r"[■□]?[0-9]{1,3}%"), (.65, .33, .69, .39)),
        _Anchor(re.compile(r"[■□]?[0-9]{1,3}%"), (.7, .33, .74, .39)),
        _Anchor("购买经验", (.1, .75, .2, .85)),
    ),
    "team_save": (
        _Anchor(re.compile(r"保存阵容(?:10|[0-9])/10"), (.15, .14, .4, .24)),
        _Anchor("存为新阵容", (.4, .3, .6, .8)),
        _Anchor("保存并收藏", (.7, .75, .85, .86)),
    ),
    "guide_legend": (
        _Anchor("图例", (.45, .27, .55, .35)),
        _Anchor("在备战席", (.39, .42, .5, .49)),
        _Anchor("在场上", (.39, .48, .5, .54)),
        _Anchor("核心角色", (.39, .52, .5, .58)),
        _Anchor("专家顾问", (.39, .65, .5, .72)),
        _Anchor("点击空白处关闭", (.35, .88, .65, .96)),
    ),
    "standard_rules": (
        _Anchor("标准博弈规则", (.22, .27, .43, .35)),
        _Anchor("标准博弈", (.22, .35, .4, .4)),
        _Anchor("低当前职级。", (.21, .6, .4, .66)),
    ),
}
_PAGES = {
    "difficulty_select": (
        _Anchor("当前职级难度效果*效果叠加生效中",(.36,.27,.64,.33)),
        _Anchor("超频博弈",(.02,.78,.16,.85)),
        _Anchor("开始对局",(.80,.85,.97,.94)),
        _Anchor("敌人难度",(.24,.90,.33,.96)),
    ),
    "boss_preview": (
        _Anchor("本场对局首领",(.72,.66,.85,.74)),
        _Anchor(re.compile(r"敌人难度[1-9][0-9]{0,2}"),(.02,.87,.15,.95)),
        _Anchor("阵营",(.10,.58,.16,.65)),
        _Anchor("阵营",(.26,.58,.32,.65)),
        _Anchor("阵营",(.42,.58,.48,.65)),
        _Anchor("下一步",(.74,.87,.84,.95)),
    ),
    "final_victory": (
        _Anchor("挑战成功",(.42,.17,.58,.26)),
        _Anchor(re.compile(r"3-[1-9][0-9]?首领"),(.40,.24,.50,.29)),
        _Anchor("挑战进度",(.46,.33,.55,.39)),
        _Anchor(re.compile(r"[1-9][0-9]?|100"),(.46,.64,.54,.73)),
        _Anchor("前往结算",(.46,.80,.55,.86)),
    ),
    "match_rating": (
        _Anchor("挑战成功",(.42,.17,.58,.26)),
        _Anchor(re.compile(r"小队生命值.?[0-9]{1,3}"),(.44,.25,.56,.30)),
        _Anchor("对局评价",(.46,.32,.54,.38)),
        _Anchor("下一步",(.46,.80,.55,.86)),
    ),
    "match_summary": (
        _Anchor("对局胜利",(.23,.18,.31,.23)),
        _Anchor(re.compile(r"3-[1-9][0-9]?首领"),(.40,.16,.50,.21)),
        _Anchor("我的阵容",(.40,.34,.46,.40)),
        _Anchor("投资环境",(.40,.65,.46,.70)),
        _Anchor("投资策略",(.58,.65,.64,.70)),
        _Anchor(re.compile(r"下一页|下顶"),(.46,.80,.55,.86)),
    ),
    "match_statistics": (
        _Anchor("小队生命值",(.16,.16,.24,.22)),
        _Anchor("总经济",(.39,.16,.44,.22)),
        _Anchor("阵容价值",(.62,.16,.68,.22)),
        _Anchor(re.compile(r"■?伤害统计"),(.78,.22,.85,.27)),
        _Anchor(re.compile(r"返回货[币百]战争"),(.45,.80,.55,.86)),
    ),
    "plane_map": (
        _Anchor("位面", (.20,.29,.27,.38)),
        _Anchor("位面", (.46,.27,.55,.38)),
        _Anchor("位面", (.73,.29,.81,.38)),
        _Anchor("1", (.20,.38,.27,.49)),
        _Anchor("2", (.46,.38,.55,.49)),
        _Anchor("3", (.73,.38,.81,.49)),
        _Anchor("点击空白处继续", (.43,.86,.57,.93)),
    ),
    "battle": (
        _Anchor(re.compile(r"[1-3]-[1-9][0-9]?(?:(?:100|[0-9]{1,2})%)?"), (.28, 0, .43, .05)),
        _Anchor("羁绊", (.85, .18, .9, .22)),
        _Anchor("伤害", (.92, .18, .97, .22)),
    ),
    "supply_selection": (
        _Anchor("补给阶段", (.45, .12, .56, .17)),
        _Anchor("返回备战界面", (.85, 0, 1, .08)),
        _Anchor(re.compile(r"已选择[01]/1"), (.83, .82, .94, .88)),
        _Anchor("确认", (.85, .87, .95, .94)),
    ),
    "node_result": (
        _Anchor("挑战成功", (.4, .17, .6, .25)),
        _Anchor(re.compile(r"小队生命值[0-9]{1,3}"), (.3, .43, .5, .5)),
        _Anchor("获得金币总览", (.25, .5, .42, .55)),
        _Anchor("基础奖励", (.25, .55, .42, .6)),
        _Anchor("继续挑战", (.4, .79, .6, .86)),
    ),
    "preparation": (
        _Anchor("备战阶段", (.2, .01, .3, .07)),
        _Anchor(re.compile(r".?前台区域"), (.45, .25, .56, .32)),
        _Anchor(re.compile(r".?后台区域"), (.45, .5, .56, .57)),
        _Anchor("购买经验", (.1, .75, .2, .85)),
        _Anchor("出战", (.9, .65, 1, .75)),
    ),
    "environment": (
        _Anchor("投资环境", (.4, .01, .6, .12)),
        _Anchor("确认", (.5, .75, .65, .98)),
        _Anchor(re.compile(r"剩余次数[0-9]+"), (.3, .7, .8, .95)),
    ),
    "guide_applied": (
        _Anchor("货币战争", (0, 0, .15, .08)),
        _Anchor("攻略", (0, .06, .15, .1)),
        _Anchor("我的阵容", (.5, .08, .7, .15)),
        _Anchor("应用中", (.9, .15, .98, .35)),
        _Anchor("取消应用", (.8, .2, .98, .45)),
    ),
    "lobby": (
        _Anchor("货币战争", (0, .04, .15, .12)),
        _Anchor("零和博弈", (0, .1, .2, .18)),
        _Anchor("创业指南", (0, .22, .2, .3)),
        _Anchor("优势布局", (0, .3, .2, .38)),
        _Anchor("攻略大全", (0, .38, .2, .45)),
        _Anchor("开始货币战争", (.65, .84, .99, .96)),
    ),
    "guide_list": (
        _Anchor("货币战争", (0, 0, .15, .08)),
        _Anchor("攻略", (0, .06, .15, .1)),
        _Anchor("热门攻略", (.3, .08, .5, .15)),
        _Anchor("我的阵容", (.5, .08, .7, .15)),
        _Anchor("保存阵容", (.8, .3, .98, .8)),
        _Anchor("输入攻略码", (.7, .87, .85, .95)),
    ),
    "guide_detail": (
        _Anchor("货币战争", (0, 0, .15, .08)),
        _Anchor("攻略详情", (0, .06, .15, .1)),
        _Anchor("阵容详情", (.4, .19, .6, .27)),
        _Anchor("前台区域", (.15, .25, .3, .32)),
        _Anchor("后台区域", (.15, .48, .3, .55)),
        _Anchor("运营思路", (.4, .69, .6, .77)),
    ),
    "saved_teams": (
        _Anchor("货币战争", (0, 0, .15, .08)),
        _Anchor("攻略", (0, .06, .15, .1)),
        _Anchor("我的阵容", (.5, .08, .7, .15)),
        _Anchor("查看阵容", (.8, .24, .98, .4)),
        _Anchor("输入阵容码", (.6, .87, .8, .95)),
    ),
    "mode_select": (
        _Anchor("货币战争", (0, 0, .15, .08)),
        _Anchor("标准博弈", (0, .16, .2, .25)),
        _Anchor("超频博弈", (0, .33, .2, .43)),
        _Anchor("通关可获得积分", (.28, .4, .5, .47)),
        _Anchor("对局记录", (0, .84, .2, .94)),
    ),
    "world_entry": (
        _Anchor("朝露公馆", (0, 0, .25, .09)),
        _Anchor("状态效果", (.85, .1, 1, .3)),
        _Anchor("货币战争", (.55, .4, .85, .7)),
    ),
}


def classify_page(trusted_tokens: list[Token]) -> str:
    for definitions in (_MODALS, _PAGES):
        if definitions is _PAGES and any(
            _Anchor('请选择投资策略',(.4,.04,.6,.50)).matches(t) for t in trusted_tokens
        ):
            return 'unknown'
        if definitions is _PAGES and any(is_bench_full_notice(t) for t in trusted_tokens):
            return "bench_full"
        found = [kind for kind, anchors in definitions.items()
                 if all(any(anchor.matches(token) for token in trusted_tokens) for anchor in anchors)
                 and (kind!='investment_selection' or _investment_layout(trusted_tokens))]
        if found:
            return found[0] if len(found) == 1 else "unknown"
    return "unknown"


def _investment_layout(tokens):
    names=sorted((t for t in tokens if t.within((.1,.43,.9,.48))),key=lambda t:t.center[0])
    counters=[t for t in tokens if t.within((.1,.76,.9,.84)) and normalize(t.text).startswith('刷新次数')]
    return bool(1<=len(names)<=3 and len({normalize(t.text) for t in names})==len(names)
        and len(counters)==len(names) and all(names[i].center[0]-names[i-1].center[0]>=.2 for i in range(1,len(names)))
        and all(sum(t.within((name.center[0]-.12,.76,name.center[0]+.12,.84))
            and re.fullmatch('刷新次数[0-9]{1,2}',normalize(t.text)) is not None for t in counters)==1 for name in names))


def is_bench_full_notice(token):
    return _Anchor(re.compile(r"备战席已满(?:请出售角色或提升等级|需要售卖备战区角色才可开启晶矿)"),
                   (.24,.24,.76,.52)).matches(token)
