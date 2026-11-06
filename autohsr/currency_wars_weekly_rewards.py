"""Current controls for Currency Wars weekly rewards, separate from a match.

Reference: March7thAssistant.get_reward / wait_for_weekly_reward at 7cf6c6b.
No generic confirmation, purchase or full-inventory cleanup is authorized here.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import re

from .currency_wars_navigation import page_kind, unique
from .currency_wars_points import LIMIT, NUMBER, compact, lobby_mode_needs_crop, read_points
from .currency_wars_prepare import trusted
from .free_rewards import claim_enabled, gold_fraction
from .models import AutomationError, Token, normalize

OPERATION='currency_wars_rewards'
BUTTON=(.65,.58,.98,.80)
CLOSE=(.25,.65,.75,.90)
EMPTY=('暂无可领取奖励','无可领取奖励','奖励已全部领取')
CLAIM_CAPTION = '一键领取'
CLOSE_CAPTION = '点击空白处关闭'
CLAIM_FRAGMENTS = ('键领取', '0一键领取', '一键领', '一键')
CLAIM_CROP = (.835, .639, .898, .674)
CLOSE_CROP = (.448, .681, .554, .735)
LOBBY_MODE_CROP = (.026, .101, .139, .153)
COMPACT_LABEL = (.06, .620, .15, .659)
COMPACT_BUTTON = (.758, .631, .95, .687)
OVERLAY_TITLE = (.25, .04, .75, .25)
PANEL_BLOCKERS = ('确认购买', '支付', '购买', '是否消耗', '知道了')
PANEL_MODAL = (.20, .25, .80, .80)
TIER_LABELS = (.04, .51, .94, .573)
TIER_STEP = 1800


@dataclass(frozen=True)
class RewardAction:
    intent: str
    expected: str
    target: object = None
    key: str | None = None


def fuel_limit(scene,confidence=.85):
    clean=trusted(scene,confidence)
    rows=[]
    for token in sorted((t for t in clean.tokens if t.within((.20,.30,.80,.60))),key=lambda t:t.center[1]):
        if not rows or abs(token.center[1]-rows[-1][0].center[1])>.015:rows.append([])
        rows[-1].append(token)
    words=''.join(normalize(t.text) for row in rows for t in sorted(row,key=lambda t:t.box[0]))
    return '背包内助燃券持有数量已达上限' in words


def quantities(scene,confidence=.85):
    clean=trusted(scene,confidence)
    result=[]
    for token in clean.tokens:
        text=normalize(token.text).replace(',','').replace('，','')
        if token.within((.10,.24,.90,.64)) and re.fullmatch(r'[x×]?\d{1,7}',text):
            value=int(text.lstrip('x×'))
            if value>0:result.append(value)
    return result


def _overlay_items(scene, confidence):
    clean=trusted(scene,confidence)
    return (not fuel_limit(scene,confidence)
            and clean.has('获得物品',OVERLAY_TITLE,exact=True)
            and bool(quantities(scene,confidence)))


def overlay(scene,confidence=.85):
    return (_overlay_items(scene, confidence)
            and trusted(scene, confidence).has(CLOSE_CAPTION, CLOSE, exact=True))


def kind(scene,confidence=.85):
    if fuel_limit(scene,confidence):return 'fuel_ticket_limit'
    if overlay(scene,confidence):return 'reward_overlay'
    return page_kind(scene,confidence)


def _compact_panel(scene, confidence):
    labels = [t for t in scene.tokens if normalize(t.text) == '当前积分' and t.within((.05, .62, .20, .70))]
    if len(labels) != 1 or labels[0] not in trusted(scene, confidence).tokens:
        return False
    x1, y1, x2, y2 = labels[0].box
    return (COMPACT_LABEL[0] <= x1 and x2 <= COMPACT_LABEL[2]
            and COMPACT_LABEL[1] <= y1 and y2 <= COMPACT_LABEL[3])


def _crop(image, roi):
    h, w = image.shape[:2]
    x1, y1, x2, y2 = roi
    return image[round(y1*h):round(y2*h), round(x1*w):round(x2*w)]


def supplement_reward_controls(scene, reader, confidence=.85):
    """Recover an exact caption from its calibrated crop and two OCR views."""
    confidence = max(.85, confidence)
    if scene.image is None:
        return scene
    page = page_kind(scene, confidence)
    if _overlay_items(scene, confidence):
        caption, crop, area = CLOSE_CAPTION, CLOSE_CROP, CLOSE
    elif (page == 'points_rewards' and _compact_panel(scene, confidence)
          and not scene.has(PANEL_BLOCKERS, PANEL_MODAL, exact=True)
          and not scene.has('获得物品', OVERLAY_TITLE, exact=True)):
        caption, crop, area = CLAIM_CAPTION, CLAIM_CROP, BUTTON
        if claim_enabled(scene, Token(caption, 1, crop)) is not True:
            return scene
    elif page == 'unknown' and lobby_mode_needs_crop(scene, confidence):
        caption, crop, area = '零和博弈', LOBBY_MODE_CROP, (0, .10, .20, .18)
    else:
        return scene
    if any(t.within(area) and normalize(t.text) == caption for t in scene.tokens):
        return scene

    import cv2

    field = _crop(scene.image, crop)
    if field.size == 0:
        return scene
    # Normalize the field to twice its size on the calibrated source surface.
    # Upscaling the full client to another resolution must not stretch this OCR input.
    x1, y1, x2, y2 = crop
    dimensions = (round((x2-x1)*1536), round((y2-y1)*960))
    color = cv2.resize(field, dimensions, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(color, cv2.COLOR_BGR2GRAY)
    readings = [reader._read_field(image, caption) for image in (color, gray)]
    if all(t is not None and t.text == caption and t.score >= confidence for t in readings):
        return replace(scene, tokens=[*scene.tokens, Token(caption, min(t.score for t in readings), crop)])
    return scene


def panel_proof_token(token):
    text = normalize(token.text)
    return ((token.within(BUTTON) and text in (CLAIM_CAPTION, *CLAIM_FRAGMENTS, *EMPTY))
            or (token.within(TIER_LABELS) and bool(re.search(r'[0-9０-９]', token.text)))
            or (token.within(PANEL_MODAL) and text in PANEL_BLOCKERS)
            or (token.within(OVERLAY_TITLE) and text == '获得物品'))


def _checked_tiers(scene, current, confidence):
    """Every earned tier needs its ring and check. Later tiers retain their price in points."""
    gold = gold_fraction(scene, COMPACT_BUTTON)
    if (current < TIER_STEP or gold is None or gold >= .05
            or any(t.within(BUTTON) and normalize(t.text) in CLAIM_FRAGMENTS for t in scene.tokens)):
        return False

    import cv2
    import numpy as np

    mark = np.zeros((21, 22), np.uint8)
    cv2.ellipse(mark, (10, 10), (9, 9), 0, 0, 320, 255, 1, cv2.LINE_AA)
    cv2.polylines(mark, [np.array([(5, 9), (9, 13), (18, 4)], np.int32)], False, 255, 2, cv2.LINE_AA)
    trusted_tokens = trusted(scene, confidence).tokens
    for index, threshold in enumerate(range(TIER_STEP, LIMIT + 1, TIER_STEP)):
        x = .081 + index * .0906
        field = _crop(scene.image, (x-.0182, .451, x+.0182, .505))
        if field.size == 0:
            return False
        gray = cv2.cvtColor(cv2.resize(field, (27, 25)), cv2.COLOR_BGR2GRAY)
        correlation = cv2.matchTemplate(gray, mark, cv2.TM_CCOEFF_NORMED).max()
        brightness = np.median(gray)
        labels = [t for t in scene.tokens if t.within((x-.036, TIER_LABELS[1], x+.036, TIER_LABELS[3]))
                  and re.search(r'[0-9０-９]', t.text)]
        if current >= threshold:
            if labels or correlation < .58 or brightness > 85 or not .05 <= np.mean(gray >= 128) <= .30:
                return False
        else:
            if correlation >= .58 or brightness <= 85 or len(labels) != 1 or labels[0] not in trusted_tokens:
                return False
            value = compact(labels[0].text)
            if not re.fullmatch(NUMBER, value) or int(value.replace(',', '')) != threshold:
                return False
    return True


def panel_control(scene,confidence=.85):
    """Require an available control or positive proof that no earned tier remains."""
    confidence = max(.85, confidence)
    if kind(scene,confidence)!='points_rewards':
        raise AutomationError('当前不是已核实积分奖励面板。')
    points = read_points(scene,confidence)
    compact_panel = _compact_panel(scene, confidence)
    if (scene.has(PANEL_BLOCKERS, PANEL_MODAL, exact=True)
            or scene.has('获得物品', OVERLAY_TITLE, exact=True)):
        raise AutomationError('积分面板存在其他弹窗，未点击领取。')
    # Count even low-confidence duplicates, rather than dropping conflicts.
    candidates=[t for t in scene.tokens if t.within(BUTTON) and normalize(t.text)==CLAIM_CAPTION]
    empty=[t for t in scene.tokens if t.within(BUTTON) and normalize(t.text) in EMPTY]
    if len(candidates)>1 or len(empty)>1 or candidates and empty:
        raise AutomationError('积分领取控件冲突或不唯一。')
    if empty:
        if empty[0] in trusted(scene,confidence).tokens:return 'settled',None
        raise AutomationError('积分无可领取状态置信度不足。')
    if not candidates and compact_panel and _checked_tiers(scene, points.current, confidence):
        return 'settled', None
    if len(candidates)!=1 or candidates[0] not in trusted(scene,confidence).tokens:
        raise AutomationError('积分领取按钮缺失或尚未核实，不能推断奖励已领。')
    target = candidates[0]
    if compact_panel and not target.within(COMPACT_BUTTON):
        raise AutomationError('积分领取按钮不在此面板的已核实位置。')
    enabled = claim_enabled(scene,target)
    if enabled is True:return 'available',target
    if enabled is False and (not compact_panel or _checked_tiers(scene, points.current, confidence)):
        return 'settled',target
    raise AutomationError('积分领取按钮可用状态未知。')


def next_action(scene,data,confidence=.85):
    phase=data['phase'];page=kind(scene,confidence)
    if phase=='lobby' and page=='lobby':
        points=read_points(scene,confidence)
        if points.current!=data['current']:raise AutomationError('积分已改变，未使用旧领取目标。')
        return RewardAction('open_points_rewards','points_rewards',unique(trusted(scene,confidence),'积分',(.16,.86,.25,.91)))
    if phase=='panel' and page=='points_rewards':
        points=read_points(scene,confidence)
        if points.current!=data['current']:raise AutomationError('面板积分与本次主页观察不符。')
        state,target=panel_control(scene,confidence)
        if state=='available':
            if not points.current:raise AutomationError('零积分与可领取控件冲突，未领取。')
            return RewardAction('claim_weekly_rewards','reward_overlay',target)
        return None
    if phase=='overlay' and page=='reward_overlay':
        return RewardAction('dismiss_weekly_rewards','points_rewards',unique(trusted(scene,confidence),CLOSE_CAPTION,CLOSE))
    if phase=='panel_settled' and page=='points_rewards':
        if read_points(scene,confidence).current!=data['current'] or panel_control(scene,confidence)[0]!='settled':
            raise AutomationError('返回前积分或不可领取状态已改变。')
        return RewardAction('return_weekly_lobby','lobby',key='esc')
    raise AutomationError('积分奖励当前页面与已记录阶段不符：'+phase+'/'+page)
