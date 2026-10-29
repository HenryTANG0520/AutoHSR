"""Complete visible investment effects, with March7th named-core preferences.

Source and license: assets/upstream/March7thAssistant/source.json.
Unknown effects stay unexecutable; titles alone never authorize a selection.
"""
from dataclasses import dataclass
import hashlib
import json
import re

import numpy as np

from .currency_wars import observe
from .currency_wars_deployment import _crop
from .currency_wars_prepare import trusted
from .models import AutomationError, normalize


POLICY = 'standard-investment-v2'
AVOID = frozenset(('深井角斗场','佩佩客串','钻石商人','现金为王','降本增效','大裁员','人力重组',
    '全员晋升','节省工位','奋斗协议','专家研讨会','快请专家','英雄登场','命运礼物','独家代言',
    '全都要','广聚天下英才','阿哈大悦','好运来'))
PREFERRED = {
    'default': (),
    'aglaea': ('昼之半神概念股','能量概念股','火药味','过剩经费','红钻贵族','蓝钻贵族','增发货币',
        '成功经验','二手市场','昼之半神邀请','量子同频邀请','能量邀请','特权阶级','公司军火更新',
        '超光速提拔','自由市场','优势火力论','淘金客'),
    'seele': ('量子同频契约','人才储备','量子同频邀请','贝洛伯格概念股','长线利好','增发货币',
        '经济过热','经济严重过热','钢铁美学','量子力学','枪在手'),
}


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


@dataclass(frozen=True)
class InvestmentOption:
    slot: int
    name: object
    effect: str
    kind: str | None
    parameters: tuple = ()
    score: float | None = None
    refreshes: int | None = None


def parse_effect(effect):
    value = normalize(effect)
    from .currency_wars_investment_units import parse as parse_units
    unit_kind,unit_parameters,unit_score=parse_units(value)
    if unit_kind:return unit_kind,unit_parameters,unit_score
    if m:=re.fullmatch(r'我方小队攻击敌方目标后若其生命值百分比少于([1-9][0-9]?|100)%将其【斩杀】',value):
        threshold=int(m[1])
        return 'execution',(('threshold',threshold),),100+threshold
    if m:=re.fullmatch(r'在战斗开始([1-9][0-9]{0,2})行动值后我方小队伤害增幅提高([1-9][0-9]{0,2})%',value):
        delay,damage=map(int,m.groups())
        return 'delayed_damage',(('delay',delay),('damage',damage)),70+damage*100/(100+delay)
    if m:=re.fullmatch(r'我方小队获得([1-9][0-9]?|100)%伤害减免进入战斗时生命上限最低的角色额外获得([1-9][0-9]?|100)%伤害减免(?:获得([一二三1-3])(?:件|个)【(进阶|简易)武装箱】)?',value):
        reduction,extra=int(m[1]),int(m[2])
        count=0 if m[3] is None else {'一':1,'二':2,'三':3}.get(m[3],int(m[3]) if m[3].isdigit() else 0)
        tier=2 if m[4]=='进阶' else 1 if m[4]=='简易' else 0
        return 'reduction',(('reduction',reduction),('extra_reduction',extra),('boxes',count),('box_tier',tier)),85+reduction+extra+count*tier*10
    if m:=re.fullmatch(r'战斗开始时([1-9])个随机的([1-5])费角色在这场战斗中升为([1-4])星并获得([0-9]{1,2}|100)%前/后台强度',value):
        count,tier,star,strength=map(int,m.groups())
        return 'temporary_upgrade',tuple(zip(('count','tier','star','strength'),(count,tier,star,strength))),60+count*(star*8+tier)+strength
    if m:=re.fullmatch(r'你每次消耗金币刷新商店都会获得([1-9][0-9]?)经验值',value):
        gain=int(m[1])
        return 'refresh_experience',(('experience',gain),),80+gain*5
    return None,(),None


def options(scene, confidence=.65):
    clean=trusted(scene,confidence)
    if observe(clean,confidence).page_kind!='investment_selection':
        raise AutomationError('当前不是投资策略候选页。')
    names=sorted((t for t in clean.tokens if t.within((.10,.43,.90,.48))),key=lambda t:t.center[0])
    if (not 1<=len(names)<=3 or len({normalize(t.text) for t in names})!=len(names)
            or any(names[i].center[0]-names[i-1].center[0]<.20 for i in range(1,len(names)))):
        raise AutomationError('投资策略一／二／三卡名称不完整或有歧义。')
    result=[]
    for slot,name in enumerate(names):
        x=name.center[0]
        parts=sorted((t for t in clean.tokens if t.within((x-.125,.48,x+.125,.85))
                      and not re.fullmatch(r'刷新次数[0-9]{1,2}',normalize(t.text))),
                     key=lambda t:(round(t.center[1],2),t.center[0]))
        effect=''.join(t.text for t in parts)
        if not effect:raise AutomationError('投资策略完整说明未读到。')
        kind,parameters,score=parse_effect(effect)
        if normalize(name.text) in AVOID:kind,parameters,score=None,(),None
        refreshes={int(m[1]) for t in clean.tokens if t.within((x-.12,.76,x+.12,.84))
                   and (m:=re.fullmatch(r'刷新次数([0-9]{1,2})',normalize(t.text)))}
        result.append(InvestmentOption(slot,name,effect,kind,parameters,score,
                                       next(iter(refreshes)) if len(refreshes)==1 else None))
    return tuple(result)


def option_digest(choices):
    return digest([[c.slot,normalize(c.name.text),normalize(c.effect),c.refreshes] for c in choices])


def choose(choices, strategy):
    if strategy not in PREFERRED:raise AutomationError('投资策略的本局偏好无效。')
    candidates=[c for c in choices if c.score is not None]
    if not candidates:raise AutomationError('没有完整效果及交付契约已支持的投资策略，未默认第一项或刷新。')
    preferred=PREFERRED[strategy]
    def rank(c):
        name=normalize(c.name.text)
        bonus=200-len(preferred[:preferred.index(name)]) if name in preferred else 0
        return (-bonus-c.score,c.kind,name)
    return min(candidates,key=rank)


def selected_slot(scene, choices):
    if scene.image is None:raise AutomationError('投资策略缺少当前选中反馈图像。')
    marked=[]
    for c in choices:
        x=c.name.center[0]
        border=_crop(scene.image,(x-.106,.198,x-.103,.722))
        if border.size and np.mean(np.min(border,axis=2)>200)>=.15:marked.append(c.slot)
    button=_crop(scene.image,(.43,.892,.57,.925))
    enabled=bool(button.size and np.mean(np.min(button,axis=2)>180)>=.6)
    if len(marked)>1 or enabled!=bool(marked):
        raise AutomationError('投资策略边框和确认按钮状态冲突。')
    return marked[0] if marked else None
