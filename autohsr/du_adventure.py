"""Observed adventure mini-game lifecycle; waiting never sends gameplay input."""
from .models import Scene, Token, normalize


def hanu_result_exit(scene: Scene) -> Token | None:
    goals=''.join(t.text for t in scene.tokens if t.within((.68,.40,.99,.58)))
    if (not scene.has('拍摄结束',(.68,.30,.98,.48),exact=True)
            or '目标1完成1个波次的挑战' not in normalize(goals)
            or '目标2完成2个波次的挑战' not in normalize(goals)
            or any(word in normalize(scene.text) for word in ('支付','购买','星琼','燃料'))):
        return None
    return scene.find('退出',(.70,.85,.99,.98),exact=True)


def hanu_challenge(scene: Scene) -> bool:
    return (scene.has('即将开拍',(.39,0,.61,.13),exact=True)
            or (scene.has('观众评分',(0,0,.35,.18),exact=True)
                and scene.has('目标评分',(.02,.15,.30,.25),exact=True)
                and scene.has('达到目标评分',(.02,.20,.30,.33))))
