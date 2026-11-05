"""Use one observed investment quota and keep the resulting candidate chain."""
from functools import lru_cache
import hashlib
import json
import math
import re

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .currency_wars_investment_policy import PREFERRED, digest, option_digest, options, parse_effect, selected_slot
from .currency_wars_navigation import unique
from .currency_wars_prepare import trusted
from .currency_wars_standard import NAVIGATION_BLOCKERS
from .models import AutomationError, Token, normalize
from .policy import replenishment_dialog


ACTION = 'refresh_standard_investment'
EXPECTED = 'standard_investment_refreshed'
BINDING = 'investment_refresh_binding'
MAX_REFRESHES = 30  # Three columns, each with one base use and up to nine extra uses.
CENTERS = (.24, .50, .76)
COUNTER = re.compile(r'刷新次数([0-9]{1,2})')
CONFIRM_REGION = (.47, .89, .53, .93)
_LABELS = frozenset(('确认', '确定', '取消', '继续', '需', '需要', '须', '所需', '每次', '单次'))
_PROMPT_QUOTES = str.maketrans('', '', "「」『』【】[]“”\"'")
_SENTENCE_END = re.compile(r'[。；;！!？?]|(?<!\d)[.．]|[.．](?!\d)')
_PAY = r'(?:消耗|花费|耗费|扣除|扣费|扣减|扣款|扣掉|支付|付款|收取|收费)'
_AMOUNT = r'(?:\d+(?:[.．]\d+)?|[零〇一二两三四五六七八九十百千万]+)(?:枚|点|个|份|件)?'
_UNIT = r'(?:金币|代币|星琼|古老梦华|开拓力|燃料|信用点)'
_PROMPT = re.compile(rf'{_PAY}|刷新|重抽|重置候选|费用|价格|报价|单价|成本|金额|购买|付费|充值|是否|确认|取消'
                     rf'|(?:本列|该列|当前列)(?=需要?|须|{_AMOUNT}|{_UNIT}|\||$)|(?:扣|付|收)(?={_AMOUNT}(?:\||$))')
_RISK = re.compile(rf'{_PROMPT.pattern}|{_UNIT}')
_QUOTE = re.compile(rf'(?:{_AMOUNT}{_UNIT}|{_UNIT}(?:x|×)?{_AMOUNT})')
_BARE_AMOUNT = re.compile(rf'(?:需(?:要)?|须|每次|单次)?[+−-]?{_AMOUNT}(?:金|币|星|琼|元)?(?:[%％]|[/／](?:次|刷新))?')
_GOLD = rf'(?:{_AMOUNT}金币|金币(?:x|×)?{_AMOUNT})'
_GIFT_EFFECT = re.compile(rf'(?:每次|继续|开局时)?(?:额外)?(?:获得|赠送|奖励|返还){_GOLD}')
_SHOP = (r'(?:商店(?:的)?(?:每次|单次|本次|此次|下次|下一次|再次)?(?:手动|自动|免费|付费)?刷新'
         r'|刷新(?:一次|当前|本次|该|了)?商店)')
_SHOP_SPEND = rf'{_PAY}(?:{_GOLD}|金币)'
_SHOP_EFFECT = re.compile(rf'(?:你)?(?:每次|下次|下一次|当|在)?'
                          rf'(?:{_SHOP}(?:时|后|将|会){{0,3}}(?:(?:需要?|须)?{_SHOP_SPEND})?|{_SHOP_SPEND}(?:后|再|来|以)?{_SHOP})'
                          rf'(?:后|时|则|便|并|将|会|都会|可|可以|就能){{0,4}}(?:额外)?(?:获得|奖励|增加|提高)'
                          rf'{_AMOUNT}(?:经验(?:值)?|金币|(?:进阶|简易)武装箱)')
_BATTLE_EFFECT = re.compile(rf'(?:需要?|须)?{_PAY}{_GOLD}(?:后|之后)(?:在)?(?:(?:下一场|下场|下次|下一次)战斗|进入战斗)(?:开始时|中|时)?'
                            rf'(?:(?:我方(?:小队)?|全队|队伍|角色|自身)?(?:伤害(?:增幅)?|攻击力?|防御力?|速度|生命值?|强度)'
                            rf'(?:提高|提升|增加|降低|减少){_AMOUNT}[%％]?|(?:额外)?(?:获得|提供){_AMOUNT}[%％]?'
                            rf'(?:伤害|防御|攻击|护盾|减伤|强度|增益|加成|金币|经验(?:值)?))')


def _words(text):
    return normalize(_SENTENCE_END.sub('|', text)).translate(_PROMPT_QUOTES)


def _same_line(left, right):
    return (abs(left.center[1]-right.center[1]) <= .012 and left.center[0] < right.center[0]
            and -.012 <= right.box[0]-left.box[2] <= .045)


def _unattributed_amount(text):
    return any(_BARE_AMOUNT.fullmatch(clause) for clause in text.split('|') if clause)


def _card_description(fields, choice, confidence):
    x = choice.name.center[0]
    parts = sorted(((t, text) for t, text in fields if t.within((x-.125, .48, x+.125, .74))),
                   key=lambda part: (round(part[0].center[1], 2), part[0].center[0]))
    if (not parts or parts[0][0].center[1] > .55
            or any(t.score < max(.85, confidence) or not x-.125 <= t.box[0] < t.box[2] <= x+.125 for t, _ in parts)
            or normalize(''.join(t.text for t, _ in parts)) != normalize(choice.effect)):
        raise AutomationError('投资刷新缺少能归入本列的完整候选说明。')
    line_left = parts[0][0].box[0]
    for (before, first_text), (after, second_text) in zip(parts, parts[1:]):
        if _same_line(before, after):
            if _unattributed_amount(first_text) and _unattributed_amount(second_text):
                raise AutomationError('投资候选的相邻金额无法独立归属。')
            continue
        if not (.012 < after.center[1]-before.center[1] <= .05 and abs(after.box[0]-line_left) <= .09):
            raise AutomationError('投资候选正文与额外文字未能分开。')
        line_left = after.box[0]
    return parts


def _unattributed_effect(parts, choice):
    # Exempt only the matched words in a coherent card, leaving any extra quote visible.
    remainder = ''.join(text for _, text in parts)
    for effect in (_SHOP_EFFECT, _BATTLE_EFFECT, _GIFT_EFFECT):
        remainder = effect.sub(lambda match: '|'*len(match[0]), remainder)
    if _RISK.search(remainder):
        return True
    # The existing exact parser can own numerical fields in this whole effect.
    typed = parse_effect(choice.effect)[0] is not None
    if not typed and _unattributed_amount(remainder):
        return True
    offset = 0
    for _, text in parts:
        end = offset+len(text)
        fragment = remainder[offset:end]
        if fragment.strip('|') in _LABELS or not typed and _unattributed_amount(fragment):
            return True
        offset = end
    return False


def _has_unattributed_prompt(fields, choices, confidence):
    owners = {}
    titles = {id(choice.name) for choice in choices}
    for choice in choices:
        parts = _card_description(fields, choice, confidence)
        if any(id(t) in owners for t, _ in parts):
            raise AutomationError('投资候选文字无法唯一归入一列。')
        if _unattributed_effect(parts, choice):
            return True
        owners.update((id(t), choice.slot) for t, _ in parts)
    for token, text in fields:
        if id(token) in owners:
            continue
        if text.strip('|') in _LABELS:
            return True
        if id(token) in titles:
            if _PROMPT.search(text) or _QUOTE.search(text) or re.fullmatch(_UNIT, text) or _unattributed_amount(text):
                return True
        elif _RISK.search(text) or _unattributed_amount(text):
            return True
    # A split word may cross the card gap. Only use that adjacency to block.
    for left, prefix in fields:
        owner = owners.get(id(left))
        for right, suffix in fields:
            if (owner is not None and owner == owners.get(id(right))) or not _same_line(left, right):
                continue
            if any(match.start() < len(prefix) < match.end() for match in _RISK.finditer(prefix+suffix)):
                return True
    return False


def _current_table(scene, choices, node, confidence):
    clean = trusted(scene, min(.65, confidence))
    observed = trusted(scene, 0)
    if observed.has((*NAVIGATION_BLOCKERS, '账号验证', '登录验证', '实名认证', '游戏更新')) or replenishment_dialog(observed):
        raise AutomationError('投资页出现账号认证、更新或外部资源提示，未操作。')
    confirm = unique(clean, '确认', CONFIRM_REGION)
    counters = sorted((t for t in clean.tokens if t.within((.13, .75, .87, .84))), key=lambda t: t.center[0])
    if (len(choices) != len(counters) or len(choices) != len(CENTERS)
            or option_digest(choices) != option_digest(options(scene, max(.85, confidence)))):
        raise AutomationError('投资刷新需要三列可核实的完整候选和独立次数。')
    for center, choice, token in zip(CENTERS, choices, counters):
        value = COUNTER.fullmatch(normalize(token.text))
        if (value is None or not max(.90, confidence) <= token.score <= 1 or int(value[1]) != choice.refreshes
                or abs(choice.name.center[0] - center) > .035 or abs(token.box[0] - choice.name.center[0] + .021) > .018
                or abs(token.center[1] - .792) > .020):
            raise AutomationError('投资刷新次数与当前列不唯一对应。')
    known_controls = {id(confirm), *(id(token) for token in counters)}
    fields = [(token, _words(token.text)) for token in observed.tokens if id(token) not in known_controls]
    if _has_unattributed_prompt(fields, choices, confidence):
        raise AutomationError('投资页的报价、刷新字样或金额无法归入完整候选说明，未操作。')
    for token, text in fields:
        if token.within((.10, .04, .29, .13)) and re.fullmatch(r'[1-3]-[1-9][0-9]?', text) and text != node:
            raise AutomationError('当前投资页节点与已核实位面来源不同。')
    rows = [[c.slot, normalize(c.name.text), normalize(c.effect), c.refreshes] for c in choices]
    if not _valid_table(rows):
        raise AutomationError('投资刷新前的完整候选描述未核实。')
    return rows, counters


@lru_cache(maxsize=1)
def _icon_template():
    root = RESOURCE_ROOT/'assets/currency-investment'
    try:
        entry = json.loads((root/'sources.json').read_text(encoding='utf-8'))['refresh_control']
        raw = (root/entry['template']).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['template_sha256']:
            raise ValueError('hash')
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape != (68, 68, 3):
            raise ValueError('shape')
        return image
    except (OSError, ValueError, KeyError, TypeError, cv2.error) as exc:
        raise AutomationError('投资刷新控件参考无法核实，未发送输入。') from exc


def _control(scene, counter):
    if scene.image is None:
        raise AutomationError('投资刷新缺少当前控件图像。')
    ref = _icon_template()
    image = scene.image if scene.image.shape[:2] == (1440, 2560) else cv2.resize(scene.image, (2560, 1440))
    x, y = round((counter.box[0]-.017)*2560)-47, round(counter.center[1]*1440)-48
    patch = image[y:y+96, x:x+94]
    scores = cv2.matchTemplate(patch, ref, cv2.TM_CCOEFF_NORMED)
    _, score, _, (dx, dy) = cv2.minMaxLoc(scores)
    matched = patch[dy:dy+68, dx:dx+68]
    bright = cv2.cvtColor(matched, cv2.COLOR_BGR2GRAY) >= 200
    if not math.isfinite(score) or score < .92 or np.mean(bright) < .43:
        raise AutomationError('对应投资列的刷新箭头未核实启用，未发送输入。')
    left, top = x+dx, y+dy
    return Token('刷新投资策略', min(score, counter.score), (left/2560, top/1440, (left+68)/2560, (top+68)/1440))


def _plane_digest(actions, index, node):
    from .currency_wars_standard_investment import _origin
    if _origin(actions, index) != node:
        raise AutomationError('投资刷新来源与原位面不同。')
    parent = actions[index]
    fields = ('id', 'action', 'status', 'input_epoch', 'before', 'after', 'target', 'feedback', 'reward_basis')
    return digest([[action.get(key) for key in fields] for action in (actions[parent['target'][1]], actions[index-1], parent)])


def _slot(rows):
    # max keeps the first column when several have the same quota.
    return max(range(len(rows)), key=lambda i: rows[i][3])


def _intent(scene, session, choices, confidence):
    from .currency_wars_standard_flow import StandardAction
    data, actions = session['investment'], session['actions']
    node, index = data['expected_node'], data['origin_action_id']
    if (session.get('expected_board') != node or session.get('strategy', 'default') not in PREFERRED
            or not 1 <= len(actions)-index <= MAX_REFRESHES
            or len(actions) != index+1 and actions[-1].get('action') != ACTION
            or selected_slot(scene, choices) is not None):
        raise AutomationError('投资刷新超过本位面额度、已有选择或来源待核对。')
    rows, counters = _current_table(scene, choices, node, confidence)
    slot = _slot(rows)
    quota = rows[slot][3]
    if quota == 0:
        raise AutomationError('本位面投资刷新次数已用完，未继续。')
    control = _control(scene, counters[slot])
    scope = session['collection']
    origin = dict(plane=_plane_digest(actions, index, node), candidates_before=rows,
                  run_dir=scope['run_dir'], input_epoch=scope['input_epoch'], strategy=session.get('strategy', 'default'),
                  client_version=session['client']['version'], captured_at=scene.captured_at, control=list(control.box))
    choice = StandardAction(ACTION, EXPECTED, control, payload=(node, index, slot, quota, digest(rows), digest(origin)))
    return choice, origin


def proposal(scene, session, choices, confidence):
    choice, origin = _intent(scene, session, choices, confidence)
    pending = session.get('rederiving_action')
    if pending and pending.get('action') == ACTION and pending.get('investment_refresh_origin') != origin:
        raise AutomationError('当前投资刷新控件、候选或位面与落盘意图不同。')
    return choice


def bind_intent(session, choice, scene, confidence):
    from .currency_wars_standard_trading import _prior
    current, origin = _intent(scene, _prior(session, ACTION), options(scene, confidence), confidence)
    action = session['actions'][-1]
    if (current != choice or action.get('action') != ACTION or action.get('status') != 'pending'
            or action.get('expected') != EXPECTED or action.get('target') != list(choice.payload)
            or action.get('input_epoch') != origin['input_epoch']):
        raise AutomationError('投资刷新意图与当前列或代次不符，未发送输入。')
    action['investment_refresh_origin'] = origin


def _receipt(before, after, slot):
    if (after[slot][3] != before[slot][3]-1
            or any(old != new for i, (old, new) in enumerate(zip(before, after)) if i != slot)):
        return None
    return dict(slot=slot, quota_used=1, remaining_before=before[slot][3], remaining_after=after[slot][3],
                candidates_after=after, candidates_digest=digest(after), card_changed=before[slot][1:3] != after[slot][1:3])


def feedback(choice, before, after, session, confidence=.65):
    try:
        action = session['actions'][-1]
        origin = action['investment_refresh_origin']
        if (choice.intent != ACTION or action.get('status') != 'pending' or action.get('action') != ACTION
                or action.get('target') != list(choice.payload) or before.captured_at != origin['captured_at']
                or choice.payload[4] != option_digest(options(before, confidence)) or choice.payload[5] != digest(origin)):
            return None
        choices = options(after, confidence)
        if selected_slot(after, choices) is not None:
            return None
        rows, _ = _current_table(after, choices, choice.payload[0], confidence)
        return _receipt(origin['candidates_before'], rows, choice.payload[2])
    except (AutomationError, AttributeError, IndexError, KeyError, TypeError, ValueError):
        return None


def _valid_table(rows):
    return (isinstance(rows, list) and len(rows) == len(CENTERS)
            and all(isinstance(row, list) and len(row) == 4 and type(row[0]) is int and row[0] == i
                    and all(isinstance(value, str) and 0 < len(value) <= bound and value == normalize(value)
                            for value, bound in zip(row[1:3], (80, 1000)))
                    and type(row[3]) is int and 0 <= row[3] <= 99 for i, row in enumerate(rows))
            and len({row[1] for row in rows}) == len(rows))


def _not_older_than(previous, scope, captured_at):
    origin = previous['investment_refresh_origin']
    return (origin['run_dir'] != scope['run_dir'] or origin['input_epoch'] != scope['input_epoch']
            or previous['progress_frames'][-1]['captured_at'] <= captured_at)


def valid_receipt(action, actions):
    from .currency_wars_standard_progress import _paired_progress_evidence
    from .currency_wars_standard_sale import same_target
    try:
        index, target = action['id'], action['target']
        origin, receipt = action['investment_refresh_origin'], action['investment_refresh_receipt']
        node, parent, slot, quota, table_hash, origin_hash = target
        rows, after = origin['candidates_before'], receipt['candidates_after']
        before_time, control = origin['captured_at'], origin['control']
        frames = action['progress_frames']
        if (action.get('action') != ACTION or action.get('status') != 'verified' or action.get('expected') != EXPECTED
                or type(index) is not int or type(parent) is not int or not 0 <= parent < index < len(actions)
                or actions[index] != action or not 1 <= index-parent <= MAX_REFRESHES
                or not isinstance(action.get('before'), str) or not action['before'] or not _paired_progress_evidence(action)
                or type(before_time) not in (int, float) or not 0 <= before_time < frames[0]['captured_at']
                or any(frame['evidence'] == action['before'] for frame in frames)
                or type(action.get('input_epoch')) is not int or not 0 <= action['input_epoch'] == origin['input_epoch']
                or not isinstance(origin.get('run_dir'), str) or not origin['run_dir'] or origin.get('strategy') not in PREFERRED
                or origin.get('client_version') != '4.6' or origin['plane'] != _plane_digest(actions, parent, node)
                or not isinstance(control, list) or len(control) != 4
                or any(type(v) not in (int, float) or not 0 <= v <= 1 for v in control)
                or not (control[0] < control[2] and control[1] < control[3])
                or not _valid_table(rows) or not _valid_table(after) or type(slot) is not int or slot != _slot(rows)
                or type(quota) is not int or not 1 <= quota == rows[slot][3]
                or table_hash != digest(rows) or origin_hash != digest(origin)
                or not same_target(receipt, _receipt(rows, after, slot))
                or any(frame.get('candidates_digest') != receipt['candidates_digest'] for frame in frames)
                or action.get('investment_refresh_digest') != digest([action['before'], receipt, frames])):
            return False
        if index == parent+1:
            return True
        previous = actions[index-1]
        prior = previous.get('investment_refresh_origin', {})
        return (previous.get('action') == ACTION and previous.get('status') == 'verified'
                and previous['target'][:2] == target[:2]
                and prior.get('strategy') == origin['strategy']
                and _not_older_than(previous, origin, before_time)
                and previous['investment_refresh_receipt']['candidates_after'] == rows)
    except (AutomationError, AttributeError, IndexError, KeyError, TypeError, ValueError):
        return False


def record_feedback(action, session, receipt):
    action['investment_refresh_receipt'] = receipt
    frames = action['progress_frames']
    for frame in frames:
        frame['candidates_digest'] = receipt['candidates_digest']
    action['investment_refresh_digest'] = digest([action['before'], receipt, frames])
    if not valid_receipt(action, session['actions']):
        raise AutomationError('投资刷新回执缺少本次连续候选和扣次证据，保留待核对。')
    session['action_status'] = 'investment_refreshed'


def _latest(actions, index):
    from .currency_wars_standard_investment import SELECT
    tail = actions[index+1:]
    selection = tail.pop() if tail and tail[-1].get('action') == SELECT else None
    if not any(action.get('action') == ACTION for action in tail):
        return None, selection
    if len(tail) > MAX_REFRESHES or not all(valid_receipt(action, actions) for action in tail):
        raise AutomationError('投资刷新来源存在未核实动作或候选链断开。')
    return tail[-1], selection


def _binding(action):
    return dict(refresh_action_id=action['id'], origin_action_id=action['target'][1],
                receipt_digest=action['investment_refresh_digest'])


def current_binding(scene, session, choices, confidence):
    from .currency_wars_standard_investment import CONFIRM, SELECT
    data = session['investment']
    last, selection = _latest(session['actions'], data['origin_action_id'])
    binding = None
    if last is not None:
        rows, _ = _current_table(scene, choices, data['expected_node'], confidence)
        binding = _binding(last)
        if (session.get('expected_board') != data['expected_node']
                or rows != last['investment_refresh_receipt']['candidates_after']
                or session.get('strategy', 'default') != last['investment_refresh_origin']['strategy']
                or not _not_older_than(last, session['collection'], scene.captured_at)
                or selection is not None and selection.get(BINDING) != binding):
            raise AutomationError('当前投资候选或选中来源与最近刷新回执不同。')
    pending = session.get('rederiving_action')
    if pending and pending.get('action') in (SELECT, CONFIRM) and pending.get(BINDING) != binding:
        raise AutomationError('本次投资选择缺少最近刷新回执的落盘绑定。')
    return binding


def bind_choice(session, choice, scene, confidence):
    from .currency_wars_standard_trading import _prior
    prior = _prior(session, choice.intent)
    last, _ = _latest(prior['actions'], prior['investment']['origin_action_id'])
    if last is None:
        return
    choices = options(scene, confidence)
    binding = current_binding(scene, prior, choices, confidence)
    if choice.payload[6] != option_digest(choices):
        raise AutomationError('投资选择与当前已核实刷新候选不同。')
    session['actions'][-1][BINDING] = binding


def valid_selection(action, actions):
    try:
        index, target = action['id'], action['target']
        if type(index) is not int or not 0 <= index < len(actions) or actions[index] != action:
            return False
        parent, slot = target[1:3]
        if type(parent) is not int or not 0 <= parent < index:
            return False
        last, selection = _latest(actions[:index], parent)
        if last is None:
            return action.get(BINDING) is None
        rows = last['investment_refresh_receipt']['candidates_after']
        return (selection is None and action.get(BINDING) == _binding(last) and target[0] == last['target'][0]
                and type(slot) is int and 0 <= slot < len(rows) and rows[slot][1:3] == [target[3], target[5]]
                and target[6] == last['investment_refresh_receipt']['candidates_digest'])
    except (AutomationError, AttributeError, IndexError, KeyError, TypeError, ValueError):
        return False


def input_scope(intent, current, saved):
    from .currency_wars_standard_investment import CONFIRM, SELECT
    from .currency_wars_standard_sale import same_target
    if intent not in (ACTION, SELECT, CONFIRM):
        return False
    fields = ('investment', 'actions', 'collection', 'client', 'account_key', 'rules_version', 'strategy',
              'account_verified_run', 'account_verified_epoch', 'expected_board')
    if not same_target([current.get(key) for key in fields], [saved.get(key) for key in fields]):
        raise AutomationError('投资的位面、候选与意图未与落盘记录一致，未发送输入。')
    return True
