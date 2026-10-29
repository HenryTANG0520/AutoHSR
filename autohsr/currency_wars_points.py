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
from .models import AutomationError, normalize
from .weekly_plan import CHINA

LIMIT = 18000
NUMBER = r'(?:0|[1-9][0-9]{0,4}|[1-9][0-9]{0,2},[0-9]{3})'
SCORE_ROIS = dict(lobby=(.025,.895,.25,.945), points_rewards=(.06,.67,.25,.725))
TIMER_ROI = (.02,.825,.35,.875)
LOBBY_ANCHORS = {
    '货币战争':(0,.04,.15,.12), '零和博弈':(0,.10,.20,.18),
    '创业指南':(0,.22,.20,.30), '优势布局':(0,.30,.20,.38),
    '攻略大全':(0,.38,.20,.45), '开始货币战争':(.65,.84,.99,.96), '积分':(.16,.86,.25,.91),
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


def read_points(scene, confidence=.85):
    confidence=max(.85,confidence)
    kind=page_kind(scene,confidence)
    if kind not in SCORE_ROIS:
        raise AutomationError('当前不是完整货币战争主页或积分面板。')
    if kind=='lobby':
        labels=[t for t in scene.tokens if t.within(LOBBY_ANCHORS['积分']) and normalize(t.text)=='积分'
                and math.isfinite(t.score) and confidence<=t.score<=1]
        if len(labels)!=1:raise AutomationError('主页积分标签缺失或不唯一。')
    roi=SCORE_ROIS[kind]
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
    return Points(current,limit,kind)


def period_evidence(scene, now, confidence=.85):
    """Compare the visible countdown with the local Monday-04:00 boundary."""
    row=[t for t in scene.tokens if t.within(TIMER_ROI)]
    text=normalize(''.join(compact(t.text) for t in sorted(row,key=lambda t:t.box[0])))
    if not text.startswith('本期剩余时间') or text.count('本期剩余时间')!=1:
        return dict(verified=False,reason='period_countdown_missing_or_ambiguous')
    try:row=_field(row,TIMER_ROI,max(.85,confidence),max_parts=6)
    except AutomationError:return dict(verified=False,reason='period_countdown_unreadable')
    text=normalize(''.join(compact(t.text) for t in row))
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
            any(anchor_text(t.text)==label and t.within(box) for label,box in anchors.items())
            or t.within(roi) and re.search(r'[0-9０-９/／]',t.text)
            or page=='lobby' and t.within(TIMER_ROI))]
