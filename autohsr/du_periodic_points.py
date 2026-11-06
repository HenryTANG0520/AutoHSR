"""Read DU weekly progress and independent periodic result fields."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import re
import time
import unicodedata

from .currency_wars_identity import account_key
from .currency_wars_initial import evidence_ref
from .currency_wars_points import anchor_text, compact, game_week, local_now
from .currency_wars_prepare import trusted
from .models import AutomationError, EmptyCapture, Scene, Token, normalize
from .policy import du_guide_details, replenishment_dialog
from .weekly_plan import CHINA, WeeklyGuard


# The two rows belong to the same lower-left panel of guide_du_capped.
SCORE_LABEL = (.137,.808,.209,.852)
SCORE_FIELD = (.216,.808,.346,.852)
SCORE_LANE = (.128,.808,.358,.858)
TIME_LABEL = (.137,.771,.209,.810)
TIME_FIELD = (.228,.771,.346,.810)
TIME_LANE = (.128,.771,.358,.810)
PANEL = (.128,.763,.356,.860)
HOME_SCORE = (.065,.892,.262,.958)
HOME_TIME = (.0,.848,.213,.891)
HOME_PANEL = (.0,.848,.262,.958)
# The 16:9 and wide analysis layouts keep the same columns but shift rows vertically.
SETTLEMENT_ANCHORS = (
    ('分析报告', (.774, .073, .875, .175)),
    ('差分宇宙构筑内容', (.337, .249, .478, .336)),
    ('返回主界面', (.34, .831, .56, .943)),
)
SETTLEMENT_OUTCOME = (.154, .328, .309, .418)
SETTLEMENT_OUTCOMES = ('探索成功', '探索中断')
SETTLEMENT_PROGRESS = (.158, .404, .298, .456)
SETTLEMENT_LIMIT = (.165, .668, .293, .716)
SETTLEMENT_AMOUNT_REGION = (.118, .653, .216, .808)
SETTLEMENT_AMOUNT_LABELS = ('获得积分', '获得解锁材料', '获得拟合值')
SETUP_HEADING = (0,0,.24,.13)
SETUP_RANK = (.54,.10,.86,.155)
SETUP_MODE = (.55,.23,.90,.30)
SETUP_BOSS = (.53,.51,.80,.59)
SETUP_START = (.72,.82,1,.98)
SETUP_START_LABELS = ('启动「差分宇宙」', '启动差分宇宙')
OTHER_START_LABELS = ('开始游戏', '开始演算', '开始挑战', '开始模拟', '开始探索', '确认出战')
SETUP_CONFLICTS = ('常规演算', '星阶模式', '拓星模式', '练习模式', '模式选择', '下载角色',
                   '继续进度', '结束并结算', '账号验证', '账号登录', '游戏更新')
ROMAN_RANKS = ('i', 'ii', 'iii', 'iv', 'v', 'vi', 'vii', 'viii', 'ix', 'x')
NUMBER = r'(?:0|[1-9][0-9]{0,8}|[1-9][0-9]{0,2}(?:,[0-9]{3}){1,2})'
RATIO = re.compile(rf'({NUMBER})/({NUMBER})')
COUNTDOWN = re.compile(r'(?:(\d{1,2})天)?(?:(\d{1,3})小时)?(?:(\d{1,2})分钟)?')
PERIODIC_PROGRESS = re.compile(r'周期演算\((0|[1-9][0-9]?)/(13|20)\)')
SETTLEMENT_NUMBER = re.compile(rf'({NUMBER})')
FITTING_EXPRESSION = re.compile(rf'({NUMBER})(?:\s*\+\s*({NUMBER}))?')


class GuidePointsUnverified(ValueError):
    """A fixed reason code without raw account data or OCR content."""


def _inside(token, roi, confidence):
    left,top,right,bottom = token.box
    return (math.isfinite(token.score) and confidence <= token.score <= 1
            and roi[0] <= left < right <= roi[2] and roi[1] <= top < bottom <= roi[3])


def _label(scene, text, roi, confidence, reason):
    labels = [token for token in scene.tokens if compact(token.text) == text]
    if len(labels) != 1 or not _inside(labels[0],roi,confidence):
        raise GuidePointsUnverified(reason)
    return labels[0]


def _row(scene, label, lane, bounds, confidence, reason):
    # Include suspicious fragments at their raw confidence. Filtering first
    # could turn an ambiguous read into a plausible score.
    parts = sorted((token for token in scene.tokens if token.within(lane)
                    and re.search(r'[0-9/]',compact(token.text))),key=lambda token:token.box[0])
    if (not 1 <= len(parts) <= 3
            or any(not _inside(token,bounds,confidence) or abs(token.center[1]-label.center[1]) > .014
                   for token in parts)
            or any(not -.002 <= right.box[0]-left.box[2] <= .021
                   or abs(left.center[1]-right.center[1]) > .012 for left,right in zip(parts,parts[1:]))):
        raise GuidePointsUnverified(reason)
    return tuple(parts)


def _guide_page(scene, confidence):
    clean = trusted(scene,confidence)
    return (du_guide_details(clean)
            and clean.has(('旷宇纷争','寰宇纷争'),(0,0,.32,.13),exact=True)
            and clean.has('差分宇宙',(.14,.39,.27,.49),exact=True)
            and clean.has('前往参与',(.70,.75,.88,.87),exact=True))


@dataclass(frozen=True)
class GuidePoints:
    current: int
    cap: int
    tokens: tuple[Token, ...]

    @property
    def capped(self):
        return self.current == self.cap


def _score(tokens):
    parts = [compact(token.text) for token in tokens]
    split_at_slash = (len(parts) == 1
                      or len(parts) == 2 and (parts[0].endswith('/') or parts[1].startswith('/'))
                      or len(parts) == 3 and parts[1] == '/')
    ratio = RATIO.fullmatch(''.join(parts)) if split_at_slash else None
    if ratio is None:
        raise GuidePointsUnverified('score_ratio_unverified')
    current,cap = (int(value.replace(',','')) for value in ratio.groups())
    if not 0 <= current <= cap or cap == 0:
        raise GuidePointsUnverified('score_out_of_range')
    return current,cap


def read_guide_points(scene, confidence=.85):
    confidence = max(.85,confidence)
    if not _guide_page(scene,confidence):
        raise GuidePointsUnverified('guide_details_unverified')
    label = _label(scene,'周期积分',SCORE_LABEL,confidence,'score_label_unverified')
    tokens = _row(scene,label,SCORE_LANE,SCORE_FIELD,confidence,'score_row_unverified')
    current,cap = _score(tokens)
    return GuidePoints(current,cap,(label,*tokens))


def _period_tokens(scene, captured_at, week, confidence):
    reason = 'week_countdown_unverified'
    label = _label(scene,'剩余时间',TIME_LABEL,confidence,reason)
    tokens = _row(scene,label,TIME_LANE,TIME_FIELD,confidence,reason)
    # On the known guide OCR the clock glyph may appear as a leading ①.
    text = compact(''.join(token.text for token in tokens).lstrip().removeprefix('①'))
    _require_countdown(text,captured_at,week)
    return (label,*tokens)


def _require_countdown(text, captured_at, week):
    reason = 'week_countdown_unverified'
    match = COUNTDOWN.fullmatch(text)
    if match is None or not any(match.groups()):
        raise GuidePointsUnverified(reason)
    days,hours,minutes = (int(value or 0) for value in match.groups())
    if (days > 7 or days == 7 and (hours or minutes) or hours > 167
            or match[1] is not None and hours > 23 or minutes > 59):
        raise GuidePointsUnverified(reason)
    lower = days*86400 + hours*3600 + minutes*60
    precision = 60 if match[3] is not None else 3600 if match[2] is not None else 86400
    reset = datetime.fromisoformat(week).replace(tzinfo=CHINA,hour=4) + timedelta(days=7)
    remaining = (reset-captured_at).total_seconds()
    if not lower-120 <= remaining < lower+precision+120:
        raise GuidePointsUnverified('week_countdown_conflict')


def _horizontal_row(scene, bounds, confidence, reason):
    parts = sorted((token for token in scene.tokens if token.within(bounds)),key=lambda token:token.box[0])
    if (not 1 <= len(parts) <= 4 or any(not _inside(token,bounds,confidence) for token in parts)
            or any(not -.003 <= right.box[0]-left.box[2] <= .025
                   or abs(left.center[1]-right.center[1]) > .014 for left,right in zip(parts,parts[1:]))):
        raise GuidePointsUnverified(reason)
    return tuple(parts)


def read_home_points(scene, captured_at, week, confidence=.85):
    from .du_rewards import home
    confidence = max(.85,confidence)
    clean = trusted(scene,confidence)
    if (not home(clean) or not clean.has('更新内容',(.84,.03,.96,.09),exact=True)
            or scene.has(('账号验证','账号登录','验证码','用户协议','资源下载','继续进度','结束并结算'))):
        raise GuidePointsUnverified('home_points_page_unverified')
    score = _horizontal_row(scene,HOME_SCORE,confidence,'home_score_row_unverified')
    current,cap = _score(score)
    timer = _horizontal_row(scene,HOME_TIME,confidence,'home_countdown_unverified')
    time_text = compact(''.join(token.text for token in timer).lstrip().removeprefix('①'))
    prefix = '本期剩余时间'
    if not time_text.startswith(prefix):
        raise GuidePointsUnverified('home_countdown_unverified')
    _require_countdown(time_text.removeprefix(prefix).removeprefix(':'),captured_at,week)
    return GuidePoints(current,cap,(*timer,*score))


def _settlement_amount(scene, name, expression, confidence):
    reason = 'settlement_amount_unverified'
    label = _label(scene, name, SETTLEMENT_AMOUNT_REGION, confidence, reason)
    # Reject labels that could share the same amount under the row alignment tolerance.
    if any(token is not label and token.within(SETTLEMENT_AMOUNT_REGION)
           and compact(token.text) in SETTLEMENT_AMOUNT_LABELS
           and abs(token.center[1] - label.center[1]) <= .028 for token in scene.tokens):
        raise GuidePointsUnverified(reason)
    lane = (.219, label.box[1] - .014, .334, label.box[3] + .014)
    parts = _horizontal_row(scene, lane, confidence, reason)
    texts = [unicodedata.normalize('NFKC', token.text).strip() for token in parts]
    match = expression.fullmatch(''.join(texts))
    if (match is None or any(abs(token.center[1] - label.center[1]) > .014 for token in parts)
            or any(not (left.endswith('+') or right.startswith('+'))
                   for left, right in zip(texts, texts[1:]))):
        raise GuidePointsUnverified(reason)
    return [int(value.replace(',', '')) for value in match.groups() if value is not None]


def periodic_settlement_observation(scene, confidence=.85):
    """Read a settled periodic report without using its values to advance play."""
    confidence = max(.85, confidence)
    reason = 'periodic_settlement_unverified'
    try:
        for text, region in SETTLEMENT_ANCHORS:
            _label(scene, text, region, confidence, reason)
        progress = _horizontal_row(scene, SETTLEMENT_PROGRESS, confidence, reason)
    except GuidePointsUnverified:
        return None
    outcomes = [token for token in scene.tokens if token.within(SETTLEMENT_OUTCOME)
                and compact(token.text) in SETTLEMENT_OUTCOMES]
    if len(outcomes) != 1 or not _inside(outcomes[0], SETTLEMENT_OUTCOME, confidence):
        return None
    outcome = compact(outcomes[0].text)
    stage = PERIODIC_PROGRESS.fullmatch(''.join(compact(token.text) for token in progress))
    if stage is None:
        return None
    area, total = map(int, stage.groups())
    if area > total or outcome == '探索成功' and area != total:
        return None
    observation = dict(outcome=outcome, area_index=area, area_total=total,
                       weekly_points_gained=None, unlock_materials_gained=None,
                       fitting_value_gained=None, fitting_value_terms=None)
    try:
        _label(scene, '奖励已到达上限', SETTLEMENT_LIMIT, confidence, reason)
    except GuidePointsUnverified:
        pass
    else:
        observation['reward_limit_message'] = True
        return observation
    for label, field in (('获得积分', 'weekly_points_gained'), ('获得解锁材料', 'unlock_materials_gained')):
        try:
            observation[field], = _settlement_amount(scene, label, SETTLEMENT_NUMBER, confidence)
        except GuidePointsUnverified:
            pass
    try:
        terms = _settlement_amount(scene, '获得拟合值', FITTING_EXPRESSION, confidence)
    except GuidePointsUnverified:
        pass
    else:
        observation.update(fitting_value_gained=sum(terms), fitting_value_terms=terms)
    return observation


def shared_periodic_rewards_observation(scene, confidence=.85):
    """Read the shared panel without inferring its entry or a claim receipt."""
    from .currency_wars_points import read_points
    from .currency_wars_weekly_rewards import kind, panel_control

    confidence = max(.85, confidence)
    if kind(scene, confidence) != 'points_rewards':
        return None
    try:
        points = read_points(scene, confidence)
    except AutomationError:
        return None
    observation = dict(current=points.current, cap=points.limit, claim_control='unverified')
    try:
        state, _ = panel_control(scene, confidence)
    except AutomationError:
        return observation
    if state == 'available' and points.current > 0:
        observation['claim_control'] = 'available'
    elif state == 'settled':
        observation['claim_control'] = 'unavailable'
    return observation


def _launch_label(text):
    return anchor_text(text).startswith('启动差分宇宙')


def is_setup_launch_click(scene, target):
    """Keep the launch area out of ordinary clicks even on conflicting setup frames."""
    if not isinstance(target, Token):
        return False
    if _launch_label(target.text):
        return True
    if not target.within(SETUP_START):
        return False
    from .differential_universe import classify_page
    if (any(t.within(SETUP_START) and _launch_label(t.text) for t in scene.tokens)
            or classify_page(scene) in ('periodic_setup', 'difficulty_setup', 'star_rank_setup')):
        return True
    return (anchor_text(target.text).startswith(OTHER_START_LABELS)
            and (scene.has('本周首领敌人', SETUP_BOSS, exact=True)
                 or scene.has('难度', SETUP_RANK) and scene.has('乐园漫记', SETUP_RANK)))


def read_periodic_setup(scene, confidence):
    from .currency_wars_standard import NAVIGATION_BLOCKERS
    from .differential_universe import classify_page

    reason = 'periodic_setup_unverified'
    observed = trusted(scene, 0)
    if (classify_page(observed) != 'periodic_setup' or observed.has((*SETUP_CONFLICTS, *NAVIGATION_BLOCKERS))
            or replenishment_dialog(observed)
            or not any(normalize(t.text) == '差分宇宙' and _inside(t, SETUP_HEADING, confidence)
                       for t in observed.tokens)):
        raise GuidePointsUnverified(reason)
    _label(observed, '本周首领敌人', SETUP_BOSS, confidence, reason)
    modes = [t for t in observed.tokens if t.within(SETUP_MODE)
             and (compact(t.text) == '周期演算' or compact(t.text).startswith('周期演算:'))]
    if len(modes) != 1 or not _inside(modes[0], SETUP_MODE, confidence):
        raise GuidePointsUnverified(reason)
    header = _horizontal_row(observed, SETUP_RANK, confidence, reason)
    text = normalize(compact(''.join(t.text for t in header)))
    match = re.fullmatch(r'差分宇宙乐园漫记[丨|/-]?难度([ivx]+|10|[1-9])', text)
    if match is None or not (match[1].isdigit() or match[1] in ROMAN_RANKS):
        raise GuidePointsUnverified(reason)
    rank = int(match[1]) if match[1].isdigit() else ROMAN_RANKS.index(match[1]) + 1
    starts = [t for t in observed.tokens if t.within(SETUP_START)
              and (_launch_label(t.text) or anchor_text(t.text).startswith(OTHER_START_LABELS))]
    if (len(starts) != 1 or normalize(starts[0].text) not in SETUP_START_LABELS
            or not _inside(starts[0], SETUP_START, confidence)):
        raise GuidePointsUnverified(reason)
    return rank, starts[0]


@dataclass(frozen=True)
class _Capture:
    epoch: int
    window: int
    geometry: object
    stamp: float
    captured_at: datetime
    week: str
    account: str | None
    directory: str


def _account_tokens(scene):
    return [token for token in scene.tokens if token.within((0,.94,.35,1))
            and (normalize(token.text).startswith(('uid','ui'))
                 or re.fullmatch(r'\d{8,10}',normalize(token.text)))]


def _account(scene, confidence, *, allow_hidden):
    candidates = _account_tokens(scene)
    if not candidates and allow_hidden:
        return None
    if len(candidates) == 1:
        try:
            return account_key(scene,confidence)
        except AutomationError:
            pass
    raise GuidePointsUnverified('account_unverified')


def _capture(context, scene, confidence, *, allow_hidden=False):
    epoch = context.scene_epoch
    window = getattr(context.window,'hwnd',None)
    stamp = scene.captured_at
    directory = context.report.run_dir
    if (context.report.operation != 'differential_universe' or scene is not context.last_scene
            or type(epoch) is not int or epoch < 0 or epoch != context.runner.input_epoch
            or type(window) is not int or window <= 0 or scene.geometry is None
            or not isinstance(directory,str) or not directory):
        raise GuidePointsUnverified('capture_scope_unverified')
    if type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp <= 0:
        raise GuidePointsUnverified('capture_not_fresh')
    age = time.monotonic()-stamp
    if not 0 <= age <= 8:
        raise GuidePointsUnverified('capture_not_fresh')
    now = local_now()
    captured_at = now-timedelta(seconds=age)
    week = game_week(captured_at)
    weekly = getattr(context.runner,'weekly_plan',None)
    if week != game_week(now) or isinstance(weekly,WeeklyGuard) and week != weekly.slot.week:
        raise GuidePointsUnverified('game_week_changed')
    account = _account(scene,confidence,allow_hidden=allow_hidden)
    return _Capture(epoch,window,scene.geometry,stamp,captured_at,week,account,directory)


def unverified(reason='guide_not_observed'):
    return dict(verified=False,current=None,cap=None,capped=None,reason=reason,source='guide_details',
                game_week=None,observed_at=None,input_epoch=None,evidence=None)


def is_current_game_week(observation, now=None):
    """A stored verified read is only evidence for its own observed game week."""
    if not isinstance(observation,dict) or observation.get('verified') is not True:
        return False
    try:
        now = local_now() if now is None else now
        observed_at = datetime.fromisoformat(observation['observed_at'])
        return observed_at <= now and game_week(observed_at) == observation.get('game_week') == game_week(now)
    except (KeyError,TypeError,ValueError):
        return False


def _panel(scene, tokens, roi=PANEL):
    import numpy as np

    image = scene.image
    if not isinstance(image,np.ndarray) or image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise GuidePointsUnverified('evidence_unverified')
    height,width = image.shape[:2]
    x1,y1,x2,y2 = (round(part*size) for part,size in zip(roi,(width,height,width,height)))
    if x2 <= x1 or y2 <= y1:
        raise GuidePointsUnverified('evidence_unverified')
    # The text sidecar is limited to the validated score and clock rows.
    return Scene(list(tokens),image[y1:y2,x1:x2].copy())


class PeriodicPointsGoal:
    """Require a current, same-account home read for each new periodic run."""

    def __init__(self, context, maximum):
        self.context = context
        self.confidence = max(.85,context.settings.ocr_confidence)
        self.result = dict(status='observing',source='du_home',maximum=maximum,observations=[])
        self.identity = None
        self.source = None

    def invalidate(self, reason):
        self.result.update(status='unverified', reason=self.result.get('reason') or reason)

    def expire_at_publication(self):
        if (self.source is None or self.result['status'] not in ('capped', 'exhausted')
                or game_week(local_now()) == self.source.week):
            return False
        self.invalidate('game_week_changed')
        return True

    def require_setup(self, scene, *, target=None, read_sources=None):
        try:
            setup = read_periodic_setup(scene, self.confidence)
            if target is not None and target is not setup[1]:
                raise GuidePointsUnverified('periodic_start_target_unverified')
        except GuidePointsUnverified as error:
            self.invalidate(str(error))
            raise AutomationError('差分周期积分目标的周期备战页或启动按钮未核实。') from error
        self.require_current(scene, launch=True, read_sources=read_sources)
        return setup

    def _capture(self, scene):
        capture = _capture(self.context,scene,self.confidence)
        weekly = getattr(self.context.runner, 'weekly_plan', None)
        if isinstance(weekly, WeeklyGuard):
            try:
                weekly.require_account(scene)
            except AutomationError as error:
                raise GuidePointsUnverified('weekly_account_unverified') from error
        identity = (capture.account,capture.week,capture.window,capture.directory)
        if self.identity is None:
            self.identity = identity
        if identity != self.identity:
            raise GuidePointsUnverified('points_goal_scope_changed')
        return capture

    def require_weekly_sources(self, *, read_sources=None):
        weekly = getattr(self.context.runner, 'weekly_plan', None)
        if isinstance(weekly, WeeklyGuard) and weekly.until_points:
            try:
                weekly.require_points_sources(self.context.report.differential_universe, read_sources=read_sources)
            except AutomationError:
                self.invalidate('weekly_sources_unverified')
                raise

    def require_current(self, scene, *, launch=False, read_sources=None):
        try:
            if launch:
                self.context.window.guard(scene.geometry)
            self.context.checkpoint()
            if not launch:
                self.context.window.guard(scene.geometry)
            current = self._capture(scene)
            source = self.source
            if (source is None or current.epoch != source.epoch or current.geometry != source.geometry
                    or current.stamp < source.stamp):
                raise GuidePointsUnverified('points_goal_scope_changed')
            if launch and (self.result['status'] != 'below_cap' or current.stamp-source.stamp > 60):
                raise GuidePointsUnverified('points_launch_unverified')
            if not launch and current.stamp != source.stamp:
                raise GuidePointsUnverified('capture_not_fresh')
            if launch:
                self.context.window.guard(scene.geometry)
                self.require_weekly_sources(read_sources=read_sources)
                if (scene is not self.context.last_scene or current.geometry != scene.geometry
                        or current.window != self.context.window.hwnd or current.directory != self.context.report.run_dir
                        or current.epoch != self.context.scene_epoch or current.epoch != self.context.runner.input_epoch):
                    raise GuidePointsUnverified('capture_scope_unverified')
                if not 0 <= time.monotonic() - current.stamp <= 8:
                    raise GuidePointsUnverified('capture_not_fresh')
                if game_week(local_now()) != current.week:
                    raise GuidePointsUnverified('game_week_changed')
        except GuidePointsUnverified as error:
            self.invalidate(str(error))
            raise AutomationError('差分周期积分目标的当前画面或账号未核实，停止启动。') from error

    def observe(self, scene, completed):
        previous = None
        self.source = None
        self.result.update(status='observing',reason=None)
        reason = 'home_points_pair_unverified'
        try:
            for attempt in range(6):
                if attempt:
                    self.context.sleep(.25)
                    sequence = self.context.capture_sequence
                    try:
                        scene = self.context.snapshot()
                    except EmptyCapture:
                        previous = None
                        continue
                    if self.context.capture_sequence != sequence+1:
                        previous = None
                try:
                    current = self._capture(scene)
                except GuidePointsUnverified as error:
                    if str(error) not in ('account_unverified','capture_not_fresh'):
                        raise
                    reason = str(error)
                    previous = None
                    continue
                try:
                    points = read_home_points(scene,current.captured_at,current.week,self.confidence)
                except GuidePointsUnverified as error:
                    reason = str(error)
                    previous = None
                    continue
                bottom = min(HOME_PANEL[3],_account_tokens(scene)[0].box[1])
                if any(token.box[3] > bottom for token in points.tokens):
                    raise GuidePointsUnverified('home_score_crop_unverified')
                panel = _panel(scene,points.tokens,(*HOME_PANEL[:3],bottom))
                if previous is not None:
                    prior_scene,prior,prior_points,prior_panel = previous
                    if current.epoch != prior.epoch or current.geometry != prior.geometry:
                        raise GuidePointsUnverified('points_goal_scope_changed')
                    if (scene is not prior_scene and current.stamp > prior.stamp
                            and abs(points.tokens[-1].box[2]-prior_points.tokens[-1].box[2]) <= .012
                            and (points.current,points.cap) == (prior_points.current,prior_points.cap)):
                        history = self.result['observations']
                        if history and (points.cap != history[-1]['cap'] or points.current < history[-1]['current']):
                            raise GuidePointsUnverified('points_goal_history_conflict')
                        self.source = current
                        evidence = []
                        for index,crop in enumerate((prior_panel,panel),1):
                            path = self.context.evidence(crop,f'du_points_after_{completed}_{index}')
                            evidence.append(evidence_ref(crop,path,current.directory))
                            self.require_current(scene)
                        history.append(dict(completed_runs=completed,current=points.current,
                            cap=points.cap,capped=points.capped,game_week=current.week,
                            observed_at=current.captured_at.isoformat(),evidence=evidence))
                        self.result['status'] = 'capped' if points.capped else 'below_cap'
                        return scene
                previous = scene,current,points,panel
            raise GuidePointsUnverified(reason)
        except (GuidePointsUnverified,OSError) as error:
            reason = str(error) if isinstance(error,GuidePointsUnverified) else 'evidence_unverified'
            self.result.update(status='unverified',reason=reason)
            raise AutomationError('差分主页周期积分未取得连续的当前读数，停止启动。') from error


class GuidePointsObservation:
    def __init__(self, context, scene):
        self.context = context
        self.result = unverified('guide_entry_incomplete')
        self.origin = self.previous = self.origin_scene = self.previous_scene = None
        self.account = self.source = self.panel = None
        try:
            self.confidence = max(.85,context.settings.ocr_confidence)
            self.origin = self.previous = _capture(context,scene,self.confidence,allow_hidden=True)
            self.origin_scene = self.previous_scene = scene
            self.account = self.origin.account
        except GuidePointsUnverified as error:
            self.result['reason'] = str(error)
        except (AttributeError, TypeError, ValueError):
            self.result['reason'] = 'capture_scope_unverified'

    def _followup(self, scene, *, allow_hidden=False):
        current = _capture(self.context,scene,self.confidence,allow_hidden=allow_hidden)
        if (current.epoch != self.origin.epoch or current.window != self.origin.window
                or current.geometry != self.origin.geometry or current.directory != self.origin.directory):
            raise GuidePointsUnverified('capture_scope_changed')
        # Distinct native captures can share a clock tick. They must still
        # follow the entry frame and cannot reuse an already observed Scene.
        if (current.stamp <= self.origin.stamp or current.stamp < self.previous.stamp
                or scene is self.origin_scene or scene is self.previous_scene):
            raise GuidePointsUnverified('capture_not_fresh')
        if current.week != self.origin.week:
            raise GuidePointsUnverified('game_week_changed')
        if current.account is not None:
            if self.account is not None and current.account != self.account:
                raise GuidePointsUnverified('account_changed')
            self.account = current.account
        self.previous, self.previous_scene = current, scene
        return current

    def after_input(self, scene):
        if self.previous is None:
            return
        try:
            self._followup(scene,allow_hidden=True)
            return
        except GuidePointsUnverified as error:
            self.result['reason'] = str(error)
        except (AttributeError, TypeError, ValueError):
            self.result['reason'] = 'capture_scope_unverified'
        self.previous = self.origin_scene = self.previous_scene = None

    def freeze(self, scene):
        if self.previous is None:
            return
        try:
            current = self._followup(scene)
            self.source = current
            self.result.update(game_week=current.week,observed_at=current.captured_at.isoformat(),input_epoch=current.epoch)
            # An intact guide still supplies a cropped review image when the
            # score or timer is ambiguous. No guessed text goes into its sidecar.
            if _guide_page(scene,self.confidence):
                self.panel = _panel(scene,())
            points = read_guide_points(scene,self.confidence)
            period = _period_tokens(scene,current.captured_at,current.week,self.confidence)
            self.panel.tokens.extend((*period,*points.tokens))
            self.result.update(verified=True,current=points.current,cap=points.cap,capped=points.capped,reason=None)
        except GuidePointsUnverified as error:
            self.result['reason'] = str(error)
        except (AttributeError, TypeError, ValueError):
            self.result['reason'] = 'guide_details_unverified'
        finally:
            self.origin_scene = self.previous_scene = None

    def _current_reason(self):
        now = local_now()
        if game_week(now) != self.source.week:
            return 'game_week_changed'
        if (self.result['verified'] and not is_current_game_week(self.result,now)
                or self.context.runner.input_epoch != self.source.epoch or self.context.window.hwnd != self.source.window
                or self.context.report.run_dir != self.source.directory):
            return 'capture_scope_changed'
        return None

    def invalidate(self, reason):
        self.result.update(verified=False,current=None,cap=None,capped=None,reason=reason)

    def invalidate_if_stale(self):
        if not self.result['verified']:
            return False
        reason = self._current_reason()
        if reason is None:
            return False
        self.invalidate(reason)
        return True

    def finish(self):
        """Publish after the workflow's input sequence has ended."""
        if self.panel is None:
            return self.result
        try:
            reason = self._current_reason()
            if reason is None:
                path = self.context.evidence(self.panel,'du_periodic_points')
                evidence = evidence_ref(self.panel,path,self.source.directory)
                self.result['evidence'] = dict(evidence,roi=list(PANEL))
                reason = self._current_reason()
        except Exception:
            reason = 'evidence_unverified'
        if reason is not None:
            self.invalidate(reason)
        return self.result
