"""Bounded approach to the boss after a verified planar-extraction start."""
import re
from .models import AutomationError, normalize


def incomplete_team(scene):
    return (scene.has('提示',(.25,.30,.75,.45),exact=True) and
            scene.has('当前编队中仍有角色位空缺，是否继续出战？',(.25,.43,.75,.55),exact=True) and
            scene.has('取消',(.28,.58,.49,.67),exact=True) and
            scene.has('确认',(.51,.58,.72,.67),exact=True))


def field_ready(scene):
    return (scene.has("差分宇宙",(0,.0,.25,.10))
            and scene.has("状态效果",(.85,.17,1,.30),exact=True)
            and any(t.within((.38,0,.64,.10)) and re.match(r"等级\d{1,3}.+",normalize(t.text)) for t in scene.tokens)
            and not scene.has(("第1位面","第一位面","位面地图","开始挑战","挑战成功","战斗失败")))


def require_field(scene):
    if not field_ready(scene):
        raise AutomationError("未核实饰品提取首领现场与敌方等级标签，未移动或攻击。")
