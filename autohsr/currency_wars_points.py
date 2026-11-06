"""Read the observed Currency Wars score; points never prove reward delivery.

Reference: March7thAssistant check_currency_wars_score, pinned 7cf6c6b.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import re
import unicodedata

from .currency_wars_navigation import page_kind
from .currency_wars_pages import LOBBY_GUIDE_ROI, LOBBY_START_CAPTIONS, LOBBY_START_ROI
from .currency_wars_prepare import trusted
from .models import AutomationError, normalize
from .weekly_plan import CHINA

LIMIT = 18000
NUMBER = r'(?:0|[1-9][0-9]{0,4}|[1-9][0-9]{0,2},[0-9]{3})'
# The 4.6 score is directly below the label and above the legacy score row.
SCORE_ROIS = dict(lobby=(.025,.895,.25,.945), points_rewards=(.06,.648,.25,.725))
TIMER_ROI = (.02,.825,.35,.875)
LOBBY_ANCHORS = {
    '货币战争':(0,.04,.15,.12), '零和博弈':(0,.10,.20,.18),
    '创业指南':(0,.22,.20,.30), '优势布局':(0,.30,.20,.38),
    '攻略大全':LOBBY_GUIDE_ROI, '开始货币战争':LOBBY_START_ROI, '积分':(.16,.86,.25,.91),
}
PANEL_ANCHORS = {'积分奖励':(.02,.28,.15,.35), '规则说明':(.78,.28,.90,.35), '当前积分':(.05,.63,.20,.67)}


def local_now():
    return datetime.now(CHINA)


def game_week(now):
    if now.tzinfo is None:
        raise ValueError('积分观察时间必须含时区。')
    day=(now.astimezone(CHINA)-timedelta(hours=4)).date()
    return (day-timedelta(days=day.weekday())).isoformat()


def compact(text):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', text)).replace('／','/')


def anchor_text(text):
    return normalize(text).translate(str.maketrans('', '', '「」『』'))


def _matches_anchor(token, label, roi):
    captions = LOBBY_START_CAPTIONS if label == '开始货币战争' else (label,)
    return token.within(roi) and anchor_text(token.text) in captions


def _lobby_anchors(scene, confidence, skip=None):
    for label, area in LOBBY_ANCHORS.items():
        if label == skip:
            continue
        matches = [t for t in scene.tokens if _matches_anchor(t, label, area)]
        if len(matches) != 1 or matches[0].score < confidence:
            return False
    return True


def lobby_mode_needs_crop(scene, confidence):
    mode = '零和博弈'
    return (not scene.has(('积分奖励', '获得物品', '常规挑战', '对局记录'), exact=True)
            and not any(_matches_anchor(t, mode, LOBBY_ANCHORS[mode]) for t in scene.tokens)
            and _lobby_anchors(trusted(scene, 0), confidence, skip=mode))


def _field(tokens, roi, confidence, max_parts=3):
    if not tokens or len(tokens)>max_parts:
        raise AutomationError('积分字段缺失、重复或拆框不完整。')
    tokens=sorted(tokens,key=lambda t:t.box[0])
    for token in tokens:
        if (type(token.score) not in (int,float) or not math.isfinite(token.score) or not confidence<=token.score<=1 or len(token.box)!=4
                or not all(math.isfinite(v) for v in token.box)
                or not roi[0]<=token.box[0]<token.box[2]<=roi[2]
                or not roi[1]<=token.box[1]<token.box[3]<=roi[3]):
            raise AutomationError('积分字段置信度、边界或完整性未核实。')
    if (max(t.center[1] for t in tokens)-min(t.center[1] for t in tokens)>.012
            or any(not 0<=b.box[0]-a.box[2]<=.025 for a,b in zip(tokens,tokens[1:]))):
        raise AutomationError('积分拆框不在同一行或关系不明确。')
    return tokens


@dataclass(frozen=True)
class Points:
    current: int
    limit: int
    page: str

    @property
    def complete(self):
        return self.current==self.limit


def _score_pair(scene, roi, confidence):
    # Keep suspicious low-confidence fragments too. Dropping one could turn
    # an ambiguous field into a plausible, but false, complete score.
    tokens=_field([t for t in scene.tokens if t.within(roi) and re.search(r'[0-9０-９/／]',t.text)],roi,confidence)
    parts=[compact(t.text) for t in tokens]
    if len(parts)==1:
        match=re.fullmatch('('+NUMBER+')/('+NUMBER+')',parts[0])
        pair=match.groups() if match else None
    elif len(parts)==2:
        a,b=parts
        pair=(a[:-1],b) if a.endswith('/') else (a,b[1:]) if b.startswith('/') else None
    else:
        pair=(parts[0],parts[2]) if parts[1]=='/' else None
    if pair is None or any(re.fullmatch(NUMBER,p) is None for p in pair):
        raise AutomationError('积分当前值／上限语法不完整或存在多份读数。')
    current,limit=(int(p.replace(',','')) for p in pair)
    if limit!=LIMIT or not 0<=current<=limit:
        raise AutomationError('积分上限或当前值不在已核对范围内。')
    return current, limit


def read_points(scene, confidence=.85):
    confidence=max(.85,confidence)
    kind=page_kind(scene,confidence)
    if kind not in SCORE_ROIS:
        raise AutomationError('当前不是完整货币战争主页或积分面板。')
    if kind=='lobby':
        labels=[t for t in scene.tokens if t.within(LOBBY_ANCHORS['积分']) and normalize(t.text)=='积分'
                and math.isfinite(t.score) and confidence<=t.score<=1]
        if len(labels)!=1:raise AutomationError('主页积分标签缺失或不唯一。')
    current, limit = _score_pair(scene, SCORE_ROIS[kind], confidence)
    return Points(current, limit, kind)


def read_points_observation(scene, confidence=.85):
    """Read the displayed total on the two calibrated read-only layouts."""
    confidence = max(.85, confidence)
    visible = trusted(scene, 0)
    if visible.has(('常规挑战', '获得物品', '点击空白处关闭', '对局未完成',
                    '对局失败', '对局胜利', '对局记录'), exact=True):
        return None
    kind = page_kind(scene, confidence)
    if kind == 'points_rewards':
        roi = SCORE_ROIS[kind]
    elif kind in ('lobby', 'unknown') and not visible.has('积分奖励', exact=True):
        if not _lobby_anchors(visible, confidence):
            return None
        kind, roi = 'lobby', SCORE_ROIS['lobby']
    else:
        return None
    try:
        current, limit = _score_pair(scene, roi, confidence)
    except AutomationError:
        return None
    return Points(current, limit, kind)


def _timer_text(row):
    # The leading clock icon can be read as a circled digit on this lobby.
    text = ''.join(t.text for t in sorted(row, key=lambda t: t.box[0]))
    return normalize(compact(text.lstrip().removeprefix('①')))


def period_evidence(scene, now, confidence=.85):
    """Compare the visible countdown with the local Monday-04:00 boundary."""
    row=[t for t in scene.tokens if t.within(TIMER_ROI)]
    text=_timer_text(row)
    if not text.startswith('本期剩余时间') or text.count('本期剩余时间')!=1:
        return dict(verified=False,reason='period_countdown_missing_or_ambiguous')
    try:row=_field(row,TIMER_ROI,max(.85,confidence),max_parts=6)
    except AutomationError:return dict(verified=False,reason='period_countdown_unreadable')
    text=_timer_text(row)
    match=re.fullmatch(r'本期剩余时间(?:(\d{1,2})天)?(?:(\d{1,3})小时)?(?:(\d{1,2})分钟)?',text)
    if not match or not any(v is not None for v in match.groups()):
        return dict(verified=False,reason='period_countdown_unreadable')
    days,hours,minutes=(int(v) if v is not None else 0 for v in match.groups())
    if (days>7 or days==7 and (hours or minutes) or hours>167
            or match[1] is not None and hours>23 or minutes>59):
        return dict(verified=False,reason='period_countdown_out_of_range')
    lower=days*86400+hours*3600+minutes*60
    precision=60 if match[3] is not None else 3600 if match[2] is not None else 86400
    monday=datetime.fromisoformat(game_week(now)).replace(tzinfo=CHINA,hour=4)
    remaining=(monday+timedelta(days=7)-now.astimezone(CHINA)).total_seconds()
    verified=lower-120<=remaining<lower+precision+120
    return dict(verified=verified,reason='countdown_matches_game_week' if verified else 'period_countdown_conflicts_with_clock',
                text=text,seconds_lower=lower,precision=precision)


def proof_tokens(scene, page):
    """Allowlist menu anchors, score fields and countdown; exclude account UI."""
    anchors=LOBBY_ANCHORS if page=='lobby' else PANEL_ANCHORS
    roi=SCORE_ROIS[page]
    return [dict(text=t.text,score=t.score,box=list(t.box)) for t in scene.tokens if 'uid' not in t.text.casefold() and (
            any(_matches_anchor(t,label,box) for label,box in anchors.items())
            or t.within(roi) and re.search(r'[0-9０-９/／]',t.text)
            or page=='lobby' and t.within(TIMER_ROI))]
