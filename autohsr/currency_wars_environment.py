"""Choose only environment effects read completely from local captures."""
import time
import re
from dataclasses import dataclass

import numpy as np

from .currency_wars import CurrencyWarsWorkflow,observe
from .currency_wars_deployment import _crop
from .currency_wars_match import read_match
from .models import AutomationError, EmptyCapture, Scene, normalize


CENTERS=(.229,.50,.771)

ENVIRONMENT_POLICY = 'initial-strength-v1'
ENVIRONMENT_SELECT = 'select_standard_environment_'
ENVIRONMENT_SELECTED = 'environment_selected_'
ENVIRONMENT_CONFIRM = 'confirm_standard_environment_'
ENVIRONMENT_CONFLICTS = 'currency.initial_environment.conflicts'


@dataclass(frozen=True)
class EnvironmentOption:
    slot: int
    name: object
    effect: str
    kind: str | None
    parameters: tuple[tuple[str, int], ...] = ()
    score: int | None = None
    reason: str = ''

    @property
    def details(self):
        return (self.name.text, self.kind, self.effect, self.parameters, self.score, self.reason, ENVIRONMENT_POLICY)


def environment_decision(details):
    name, kind, effect, parameters, score, reason, policy = details
    return dict(name=name, kind=kind, effect=effect, parameters=dict(parameters), score=score, reason=reason, policy=policy)


def environment_decision_matches(recorded, details):
    if type(recorded) is not dict:
        return False
    name, kind, effect, parameters, score, _, policy = details
    original_name, original_effect = recorded.get('name'), recorded.get('effect')
    original_parameters, original_score = recorded.get('parameters'), recorded.get('score')
    return (isinstance(original_name, str) and normalize(original_name) == normalize(name)
            and isinstance(original_effect, str) and normalize(original_effect) == normalize(effect)
            and recorded.get('kind') == kind and recorded.get('policy') == policy
            and type(original_parameters) is dict and original_parameters == dict(parameters)
            and all(type(value) is int for value in original_parameters.values())
            and type(original_score) in (int, float) and original_score == score)


def environment_selection_slot(intent, expected):
    return next((slot for slot in range(len(CENTERS))
                 if intent == ENVIRONMENT_SELECT+str(slot) and expected == ENVIRONMENT_SELECTED+str(slot)), None)


def parse_environment_effect(effect, *, name=None):
    """Exact effect grammar; title, tier, star, count and gold stay separate."""
    value = normalize(effect)
    if match := re.fullmatch(r'获得([1-9])个随机([1-4])星([1-5])费角色进入新节点时这位角色永久获得随机属性加成', value):
        count, star, tier = map(int, match.groups())
        return 'growing_unit', (('count', count), ('star', star), ('tier', tier)), 16+4*(star-1)+2*tier+2*(count-1), '优先首战即有的高星角色与后续成长；分数为待校准基线'
    if match := re.fullmatch(r'本局在固定节点进行投资策略选择时左、中、右的选项分别为银金彩品质并且投资策略刷新次数\+([1-9])', value):
        refreshes = int(match[1])
        return 'fixed_investment_tiers', (('extra_refreshes', refreshes),), 12+2*refreshes, '固定品质与更多投资候选；尚不推算随机策略收益'
    if match := re.fullmatch(r'进入到一个随机投资环境中开局额外获得([1-9][0-9]?)金币', value):
        gold = int(match[1])
        return 'random_environment_gold', (('gold', gold),), gold//2-4, '额外金币已读，但随机环境结果未知，保守排序'
    if value == '所有首领节点前都加入一个额外补给阶段':
        return 'boss_supply', (('extra_stages_per_boss', 1),), 18, '增加首领前补给；不把未来随机物品视作已持有'
    if (isinstance(name, str) and normalize(name) == '过剩经费'
            and re.fullmatch(r'补给阶段中角色会携带[两2２]件装备', value)):
        return 'double_supply_equipment', (('equipment_per_role', 2),), -5, '已读后续双件补给效果，优先保留现有可选策略'
    return None, (), None, '效果未完整匹配已核验语法，不生成可执行候选'


def _standard_card_text(tokens, left, right):
    return [t for t in tokens if t is not None and normalize(t.text) and t.box[0] < right and t.box[2] > left
            and (.34 <= t.center[1] <= .38 or (t.box[1] < .79 and t.box[3] > .38))]


def _standard_card_name(tokens, left, right, confidence):
    names = [t for t in tokens if .34 <= t.center[1] <= .38]
    if len(names) == 1 and names[0].score >= confidence and left <= names[0].box[0] < names[0].box[2] <= right:
        return names[0]
    return None


def preserve_environment_conflicts(scene, weak_tokens, confidence):
    """Keep at most one negative OCR witness per located card."""
    if observe(scene, confidence).page_kind != 'environment':
        return
    from .currency_wars_prepare import trusted
    strong = trusted(scene, confidence).tokens
    weak = trusted(Scene(list(weak_tokens)), 0).tokens
    conflicts = []
    for center in CENTERS:
        left, right = center - .115, center + .115
        title = _standard_card_name(_standard_card_text(strong, left, right), left, right, confidence)
        if title is not None:
            conflict = next(iter(_standard_card_text(weak, left, right)), None)
            if conflict is not None and conflict not in conflicts:
                conflicts.append(conflict)
    if conflicts:
        scene.field_reads[ENVIRONMENT_CONFLICTS] = tuple(conflicts)


def _standard_card_body(tokens, name, left, right, confidence):
    # Include weak or overlapping text in the column so it cannot hide a
    # trailing condition after the part that happens to match a known effect.
    parts = [t for t in tokens if t is not name and t.box[1] < .79 and t.box[3] > .38]
    if not parts or any(t.score < confidence or not left <= t.box[0] < t.box[2] <= right
                        or t.box[1] < .368 or t.box[3] > .79 for t in parts):
        return None

    rows = []
    for token in sorted(parts, key=lambda t: t.center[1]):
        if not rows or token.center[1] - rows[-1][0].center[1] > .012:
            rows.append([])
        rows[-1].append(token)

    previous = None
    for row in rows:
        y = row[0].center[1]
        row.sort(key=lambda t: t.box[0])
        start = row[0].box[0]
        top = min(t.box[1] for t in row)
        bottom = max(t.box[3] for t in row)
        if previous is None:
            if not -.008 <= top - name.box[3] <= .045:
                return None
        else:
            last_start, last_y, last_top, last_bottom = previous
            overlap = min(bottom, last_bottom) - max(top, last_top)
            if (y - last_y > .05 or top - last_bottom > .022 or abs(start - last_start) > .06
                    or overlap > min(bottom - top, last_bottom - last_top) / 3):
                return None
        for before, after in zip(row, row[1:]):
            ax1, ay1, ax2, ay2 = before.box
            bx1, by1, bx2, by2 = after.box
            allowed_overlap = min(.012, (ax2 - ax1) / 3, (bx2 - bx1) / 3)
            overlap = min(ay2, by2) - max(ay1, by1)
            if (not -allowed_overlap <= bx1 - ax2 <= .035
                    or overlap < min(ay2 - ay1, by2 - by1) / 3):
                return None
        previous = start, y, top, bottom
    return ''.join(t.text for row in rows for t in row)


def standard_environment_options(scene, confidence=.65):
    from .currency_wars_prepare import trusted
    clean = trusted(scene, confidence)
    if observe(clean, confidence).page_kind != 'environment':
        raise AutomationError('当前不是投资环境选择页。')
    tokens = trusted(scene, 0).tokens
    conflicts = scene.field_reads.get(ENVIRONMENT_CONFLICTS, ())
    options = []
    for slot, cx in enumerate(CENTERS):
        left, right = cx - .115, cx + .115
        column = _standard_card_text(tokens, left, right)
        name = _standard_card_name(column, left, right, confidence)
        if name is None:
            continue
        effect = None if _standard_card_text(conflicts, left, right) else _standard_card_body(column, name, left, right, confidence)
        if effect is None:
            options.append(EnvironmentOption(slot, name, '', None, reason='环境正文的同列、相邻行或清晰度未核实'))
            continue
        kind, parameters, score, reason = parse_environment_effect(effect, name=name.text)
        options.append(EnvironmentOption(slot, name, effect, kind, parameters, score, reason))
    if not options:
        raise AutomationError('未完整定位投资环境卡片。')
    return tuple(options)


def standard_environment_choice(scene, confidence=.65, *, slot=None):
    choices = [choice for choice in standard_environment_options(scene, confidence)
               if choice.score is not None and (slot is None or choice.slot == slot)]
    if not choices:
        raise AutomationError('没有效果已核实的环境候选，未选择或刷新。')
    # Semantic tie-break, independent of left/middle/right placement.
    return min(choices, key=lambda choice:(-choice.score, choice.kind, normalize(choice.name.text)))


def standard_environment_confirm(scene, choice, confidence=.65):
    if scene.image is None or standard_environment_choice(scene, confidence, slot=choice.slot) != choice:
        raise AutomationError('当前环境选择与本次候选不一致。')
    chosen = []
    for slot, center in enumerate(CENTERS):
        border = _crop(scene.image, (center-.123,.20,center-.121,.79))
        if border.size and np.mean(np.min(border,axis=2)>200) >= .5:
            chosen.append(slot)
    button = _crop(scene.image, (.50,.895,.62,.925))
    if chosen != [choice.slot] or not button.size or np.mean(np.min(button,axis=2)>180) < .5:
        raise AutomationError('环境选中边框或确认按钮未核实。')
    from .currency_wars_navigation import unique
    from .currency_wars_prepare import trusted
    return unique(trusted(scene, confidence), '确认', (.50,.87,.65,.95))


def environment_choice(scene,confidence=.65):
    if observe(scene,confidence).page_kind!='environment':
        raise AutomationError('投资环境页未核实。')
    for cx in CENTERS:
        names=[t for t in scene.tokens if confidence<=t.score<=1 and
               t.within((cx-.11,.34,cx+.11,.38)) and normalize(t.text)=='人身意外险']
        effect=sorted((t for t in scene.tokens if confidence<=t.score<=1 and
                       t.within((cx-.11,.38,cx+.11,.47))),key=lambda t:(round(t.center[1],2),t.center[0]))
        if len(names)==1 and ''.join(normalize(t.text) for t in effect)=='所有首领节点前都加入一个额外补给阶段':
            return names[0],cx
    raise AutomationError('没有完整核实效果的投资环境，未刷新或选择。')


def environment_confirm(scene,confidence=.65):
    _,cx=environment_choice(scene,confidence)
    if scene.image is None:
        raise AutomationError('环境选择缺少选中反馈图像。')
    chosen=[]
    for center in CENTERS:
        border=_crop(scene.image,(center-.123,.20,center-.121,.79))
        if border.size and np.mean(np.min(border,axis=2)>200)>=.5:
            chosen.append(center)
    button=_crop(scene.image,(.50,.895,.62,.925))
    if chosen!=[cx] or button.size==0 or np.mean(np.min(button,axis=2)>180)<.5:
        raise AutomationError('环境卡片边框或确认按钮与本次选择不符。')
    targets=[t for t in scene.tokens if confidence<=t.score<=1 and normalize(t.text)=='确认' and
             t.within((.50,.87,.65,.95))]
    if len(targets)!=1:
        raise AutomationError('投资环境确认按钮不唯一。')
    return targets[0]


def choose_environment(c,scene,data,persist):
    name,_=environment_choice(scene,c.settings.ocr_confidence)
    guard=CurrencyWarsWorkflow(c)
    try:
        environment_confirm(scene,c.settings.ocr_confidence)
        phases=('confirm',)
    except AutomationError:
        phases=('select','confirm')
    for phase in phases:
        guard._require_current_scene(scene)
        action=dict(action=phase+'_environment',name=name.text,status='pending',
                    before=str(c.evidence(scene,'currency_environment_'+phase)))
        data['actions'].append(action)
        data.update(action_status='pending',screenshot=action['before'])
        persist()
        c.currency_select_environment(scene,confirm=phase=='confirm')
        elapsed=0.
        while elapsed<20:
            started=time.monotonic()
            inactive=c.runner.inactive_duration
            try:
                after=c.snapshot()
            except EmptyCapture:
                after=None
            if after is not None:
                guard._require_current_scene(after)
                current=read_match(after,c.settings.ocr_confidence)
                ready=bool(current and current.page in ('shop','preparation') and current.node=='1-1') if phase=='confirm' else False
                if phase=='select':
                    try:
                        environment_confirm(after,c.settings.ocr_confidence)
                        ready=True
                    except AutomationError:
                        pass
                if ready:
                    action.update(status='verified',after=str(c.evidence(after,'currency_environment_after_'+phase)))
                    data.update(action_status='environment_verified',screenshot=action['after'])
                    if phase=='confirm':
                        data['environment']='人身意外险'
                    persist()
                    scene=after
                    break
            c.sleep(1)
            elapsed+=max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
        else:
            action['status']='unknown'
            if c.last_scene is not None:
                action['after']=str(c.evidence(c.last_scene,'currency_environment_unknown'))
                data['screenshot']=action['after']
            data['action_status']='unknown'
            persist()
            return False
    return True
