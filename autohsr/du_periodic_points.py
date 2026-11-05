"""Read the DU periodic score from its guide and home panels."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import math
import re
import time

from .currency_wars_identity import account_key
from .currency_wars_initial import evidence_ref
from .currency_wars_points import compact, game_week, local_now
from .currency_wars_prepare import trusted
from .models import AutomationError, EmptyCapture, Scene, Token, normalize
from .policy import du_guide_details
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
NUMBER = r'(?:0|[1-9][0-9]{0,8}|[1-9][0-9]{0,2}(?:,[0-9]{3}){1,2})'
RATIO = re.compile(rf'({NUMBER})/({NUMBER})')
COUNTDOWN = re.compile(r'(?:(\d{1,2})天)?(?:(\d{1,3})小时)?(?:(\d{1,2})分钟)?')


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


def _home_row(scene, bounds, confidence, reason):
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
    score = _home_row(scene,HOME_SCORE,confidence,'home_score_row_unverified')
    current,cap = _score(score)
    timer = _home_row(scene,HOME_TIME,confidence,'home_countdown_unverified')
    time_text = compact(''.join(token.text for token in timer).lstrip().removeprefix('①'))
    prefix = '本期剩余时间'
    if not time_text.startswith(prefix):
        raise GuidePointsUnverified('home_countdown_unverified')
    _require_countdown(time_text.removeprefix(prefix).removeprefix(':'),captured_at,week)
    return GuidePoints(current,cap,(*timer,*score))


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

    def _capture(self, scene):
        capture = _capture(self.context,scene,self.confidence)
        identity = (capture.account,capture.week,capture.window,capture.directory)
        if self.identity is None:
            self.identity = identity
        if identity != self.identity:
            raise GuidePointsUnverified('points_goal_scope_changed')
        return capture

    def require_current(self, scene, *, launch=False):
        try:
            self.context.checkpoint()
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
        except GuidePointsUnverified as error:
            self.result.update(status='unverified',reason=str(error))
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
