"""Read a station-card instruction independently of its numeric level bonus."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .models import Scene, Token, normalize

REGIONS = ('战斗', '精英', '首领', '财富', '异常', '事件', '冒险', '铸造', '商店', '休整', '奖励', '空白')
INSTRUCTION_ROI = (.03, .10, .70, .18)
_REGION = '(?:' + '|'.join(REGIONS) + ')'
_REGION_LIST = rf'【{_REGION}】(?:或【{_REGION}】)*'
_NUMBER = r'(?:[1-9][0-9]*|一)'
_BEACON = (rf'为其附加(?:({_NUMBER})个)?'
           r'(【[\u3400-\u9fff]{1,12}】(?:或【[\u3400-\u9fff]{1,12}】)*|随机(?:正面|负面)?)信标')


@dataclass(frozen=True)
class CardEffect:
    kind: str
    count: int
    source_regions: tuple[str, ...] = ()
    level_delta: int = 0
    output_regions: tuple[str, ...] = ()
    beacons: tuple[str, ...] = ()
    removed_region: str = ''
    beacon_polarity: str = ''
    reward_kind: str = ''
    reward_count: int = 0
    reward_star_range: tuple[int, ...] = ()
    copies: int = 0
    growth_threshold: int = 0
    growth_name: str = ''

    @property
    def target_labels(self) -> tuple[str, ...]:
        if self.source_regions:
            return self.source_regions
        if self.kind=='growing_beacon':
            return REGIONS
        if self.kind == 'delete':
            return ('冒险','商店','财富','事件','异常','空白','休整','奖励','铸造','战斗','精英','首领')
        if self.kind == 'randomize':
            return ('冒险', '财富', '事件', '异常', '商店', '空白', '休整', '奖励', '铸造', '战斗', '精英', '首领')
        if self.kind in ('upgrade','copy') or (self.kind == 'beacon' and self.beacons != ('随机',)):
            return ('战斗', '精英', '首领', '事件', '异常', '财富', '冒险', '奖励', '空白', '休整', '铸造', '商店')
        return ('事件', '冒险', '异常', '财富')


def _number(value: str) -> int:
    return 1 if value == '一' else int(value)


def _regions(value: str) -> tuple[str, ...]:
    return tuple(re.findall(r'【([^【】]+)】', value))


def _beacon_details(quantity: str | None, names: str) -> dict | None:
    if _number(quantity or '1') != 1:
        return None
    return {'beacons': _regions(names) or ('随机',),
            'beacon_polarity': names[2:] if names.startswith('随机') else ''}


def _instruction(scene: Scene) -> str:
    # Join only the instruction strip, in reading order. Do not discard a
    # prefix/suffix: it may specify a cost or a second, unsupported effect.
    rows: list[list[Token]] = []
    for token in sorted((t for t in scene.tokens if t.within(INSTRUCTION_ROI)), key=lambda t: t.center[1]):
        if rows and abs(rows[-1][0].center[1] - token.center[1]) <= .012:
            rows[-1].append(token)
        else:
            rows.append([token])
    text = ''.join(t.text for row in rows for t in sorted(row, key=lambda t: t.box[0]))
    return normalize(unicodedata.normalize('NFKC', text))


def station_card_effect(scene: Scene) -> CardEffect | None:
    """Parse supported free effects; counts describe UI flow, bonuses are data.

    Only the observed single-target and two sequential conversion flows are
    executable. No level cap is inferred from the unrelated three-beacon cap.
    """
    if not scene.has('选择站点卡', (0, 0, .32, .13), exact=True) or not scene.has('抽牌区', exact=True):
        return None
    text = _instruction(scene)
    growth=re.fullmatch(rf'立即获得({_NUMBER})个随机信标进入区域后若持有的信标数量大于等于({_NUMBER})'
                        r'则升级为【([\u3400-\u9fff·]{1,24}高级)】',text)
    if growth:
        return CardEffect('growing_beacon',1,beacons=('随机',),reward_kind='beacons',
            reward_count=_number(growth[1]),growth_threshold=_number(growth[2]),growth_name=growth[3])
    deletion=re.fullmatch(rf'立即删除({_NUMBER})个指定区域',text)
    if deletion:
        return CardEffect('delete',_number(deletion[1]))
    if text=='优化阶段请删除1个指定区域':
        return CardEffect('delete',1)
    head = re.fullmatch(rf'指定({_NUMBER})个({_REGION_LIST})?区域(.+)', text)
    if head is None:
        return None
    count = _number(head[1])
    sources = _regions(head[2] or '')
    body = head[3]
    if not sources and count in (1,2) and body == '使其变为同等级的随机区域':
        return CardEffect('randomize', count)
    if count != 1:
        return None
    copies = re.fullmatch(rf'获得({_NUMBER})个该区域的复制',body)
    if copies:
        return CardEffect('copy',count,sources,copies=_number(copies[1]))
    upgrade = re.fullmatch(rf'使其等级\+({_NUMBER})(?:(?:但|并|然后){_BEACON})?', body)
    if upgrade:
        details = _beacon_details(upgrade[2],upgrade[3]) if upgrade[3] else {}
        if details is not None:
            return CardEffect('upgrade', count, sources, _number(upgrade[1]), **details)
        return None
    transform = re.fullmatch(rf'使其变为\+({_NUMBER})等级的({_REGION_LIST})区域', body)
    if transform and sources:
        return CardEffect('transform', count, sources, _number(transform[1]), _regions(transform[2]))
    beacon = re.fullmatch(
        _BEACON +
        rf'(?:然后移除1个等级最低的【({_REGION})】区域)?', body)
    if beacon:
        details = _beacon_details(beacon[1],beacon[2])
        if details is not None:
            return CardEffect('beacon', count, sources, removed_region=beacon[3] or '', **details)
    beacon_after = re.fullmatch(r'为其附加信标(【[\u3400-\u9fff]{1,12}】)',body)
    if beacon_after:
        return CardEffect('beacon', count, sources, beacons=_regions(beacon_after[1]))
    blank = re.fullmatch(r'使其变为【空白】区域然后获得(.+)',body)
    if not sources and blank:
        reward=blank[1]
        currency=re.fullmatch(rf'({_NUMBER})宇宙碎片',reward)
        random_blessings=re.fullmatch(rf'({_NUMBER})个随机([1-3])-([1-3])星祝福',reward)
        equation_blessings=re.fullmatch(rf'({_NUMBER})个方程所需的祝福',reward)
        if currency:
            return CardEffect('transform',count,output_regions=('空白',),
                              reward_kind='cosmic_fragments',reward_count=_number(currency[1]))
        if random_blessings and int(random_blessings[2])<=int(random_blessings[3]):
            return CardEffect('transform',count,output_regions=('空白',),
                              reward_kind='random_blessings',reward_count=_number(random_blessings[1]),
                              reward_star_range=(int(random_blessings[2]),int(random_blessings[3])))
        if equation_blessings:
            return CardEffect('transform',count,output_regions=('空白',),
                              reward_kind='equation_blessings',reward_count=_number(equation_blessings[1]))
    if not sources and body == '使其变为空白':
        return CardEffect('transform', count, output_regions=('空白',))
    return None
