"""A read-only, same-day reason to borrow support for an existing battle batch."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import re
from time import monotonic

from .currency_wars_identity import account_key
from .du_daily import CHINA, game_day
from .models import AutomationError, Stopped, normalize


TASK = '使用支援角色并获得战斗胜利1次'
TITLE = (0, 0, .23, .13)
ACTIVITY = (.15, .30, .205, .36)
COLUMNS = (.15, .325, .50, .675)
FULL = '本日活跃度已满'


def complete_uid_label(scene):
    """Read one complete label, checking competing OCR before confidence filtering."""
    fragments = [token for token in scene.tokens if token.within((0,.94,.35,1))
                 and normalize(token.text).startswith('uid')]
    if len(fragments) == 1 and re.fullmatch(r'uid[0-9]{8,10}', normalize(fragments[0].text)):
        return fragments[0]
    return None


def _account(scene, confidence):
    if complete_uid_label(scene) is None:
        raise AutomationError('每日实训支援当前账号未核实，未发送输入。')
    try:
        return account_key(scene, confidence)
    except AutomationError:
        raise AutomationError('每日实训支援当前账号未核实，未发送输入。') from None


def _read_card(scene, confidence):
    matched = []
    for left in COLUMNS:
        right = left+.15
        titles = [token for token in scene.tokens if token.within((left,.435,right,.535))
                  and re.search(r'[\u3400-\u9fff]', token.text)]
        titles.sort(key=lambda token: (round(token.center[1], 2), token.center[0]))
        if ''.join(normalize(token.text) for token in titles) == TASK:
            matched.append((left, right, titles))
    if len(matched) != 1:
        return 'unknown'
    left, right, titles = matched[0]

    def trusted(tokens):
        return all(confidence <= token.score <= 1 and left <= token.box[0] < token.box[2] <= right
                   for token in tokens)

    progress = [token for token in scene.tokens if token.within((left,.375,right,.428))
                and normalize(token.text).startswith('进度')]
    points = [token for token in scene.tokens if token.within((left,.61,right,.70))
              and normalize(token.text).startswith('+')]
    states = [token for token in scene.tokens if token.within((left,.73,right,.81))
              and re.search(r'[\u3400-\u9fff]', token.text)]
    if (len(progress) != 1 or len(points) != 1 or len(states) != 1
            or not trusted(titles+progress+points+states) or normalize(points[0].text) != '+200'):
        return 'unknown'
    status = normalize(states[0].text)
    count = normalize(progress[0].text).replace('／', '/')
    if count == '进度0/1' and status == '进行中':
        return 'needed'
    if count == '进度1/1' and status in ('领取', '已领取', '已完成'):
        return 'completed'
    return 'unknown'


def read_state(scene, *, badge_verified=False, confidence=.85):
    """Read the observed four-column layout. A hidden card stays unknown."""
    for name in ('星际和平指南', '每日实训'):
        headers = [token for token in scene.tokens if token.within(TITLE) and normalize(token.text) == name]
        if len(headers) != 1 or not confidence <= headers[0].score <= 1:
            return 'unknown', None
    if scene.has(('点击空白处关闭', '点击任意位置关闭'), exact=True):
        return 'unknown', None
    numbers = [token for token in scene.tokens if token.within(ACTIVITY) and re.fullmatch(r'\d{1,3}', token.text.strip())]
    if len(numbers) != 1 or not confidence <= numbers[0].score <= 1:
        return 'unknown', None
    activity = int(numbers[0].text.strip())
    full = [token for token in scene.tokens if token.within((.14,.73,.89,.81)) and normalize(token.text) == FULL]
    if activity == 500 and (badge_verified or any(confidence <= token.score <= 1 for token in full)):
        return 'activity_full', activity
    if not 0 <= activity < 500 or full or not badge_verified:
        return 'unknown', None
    return _read_card(scene, confidence), activity


@dataclass(frozen=True)
class Decision:
    state: str
    day: str
    _account: str = field(repr=False)
    _epoch: int = field(repr=False)
    _confidence: float = field(repr=False)

    def require(self, ctx, scene):
        ctx.checkpoint()
        self.require_current(ctx, scene)

    def require_current(self, ctx, scene):
        if (scene is None or scene is not ctx.last_scene or ctx.scene_epoch != self._epoch
                or ctx.runner.input_epoch != self._epoch or scene.captured_at <= 0
                or not 0 <= monotonic()-scene.captured_at <= 8):
            raise AutomationError('实训支援核验后输入代次或画面已变化，未发送输入。')
        if _account(scene, self._confidence) != self._account:
            raise AutomationError('实训支援核验后账号已变化，未发送输入。')
        if game_day(datetime.now(CHINA)) != self.day:
            raise AutomationError('实训支援核验后已跨游戏日，未发送输入。')

    @contextmanager
    def inputs(self, ctx, *, scene=None):
        """Keep Context's policy and its outer account proxy in the send path."""
        window = ctx.window
        ctx.window = _Window(ctx, window, self, scene)
        try:
            yield
        finally:
            ctx.window = window


class _Window:
    def __init__(self, ctx, window, decision, scene):
        self.ctx, self.window, self.decision, self.scene = ctx, window, decision, scene

    def __getattr__(self, name):
        method = getattr(self.window, name)
        if name not in ('click', 'key'):
            return method

        def checked(*args, **kwargs):
            from .windows import GameWindow
            from .workflow_identity import _Window as AccountWindow

            scene = self.scene if self.scene is not None else self.ctx.last_scene
            self.decision.require(self.ctx, scene)
            native = self.window._raw if isinstance(self.window, AccountWindow) else self.window
            if isinstance(native, GameWindow):
                geometry = scene.geometry
                if geometry is None:
                    raise AutomationError('实训支援当前窗口位置未核实，未发送输入。')
                if name == 'key' and kwargs.setdefault('expected', geometry) != geometry:
                    raise AutomationError('实训支援按键窗口与当前画面不符，未发送输入。')
                finish = kwargs.get('before_submit')

                def before_submit():
                    native.guard(geometry)
                    if native.emergency_pressed():
                        raise Stopped('F10 紧急停止。')
                    if getattr(self.ctx.runner, 'stop_requested', False) is True:
                        raise Stopped('任务已停止。')
                    if scene.geometry != geometry:
                        raise AutomationError('实训支援当前窗口位置已变化，未发送输入。')
                    self.decision.require_current(self.ctx, scene)
                    # A planned payment marks its native attempt only after this gate.
                    if finish is not None:
                        finish()

                kwargs['before_submit'] = before_submit
            return method(*args, **kwargs)
        return checked


def observe(workflow):
    ctx = workflow.ctx
    scene = workflow._open_guide('每日实训')
    confidence = max(.85, workflow.settings.ocr_confidence)
    now = datetime.now(CHINA)
    age = monotonic()-scene.captured_at
    day = game_day(now)
    if scene.captured_at <= 0 or not 0 <= age <= 8 or game_day(now-timedelta(seconds=age)) != day:
        raise AutomationError('每日实训支援页面已失效或跨游戏日，未开始挑战。')
    badge = workflow._icon(scene, 'daily_activity_badge', (.13,.23,.225,.37), threshold=.85)
    state, activity = read_state(scene, confidence=confidence, badge_verified=badge is not None)
    decision = Decision(state, day, _account(scene, confidence), ctx.scene_epoch, confidence)
    decision.require(ctx, scene)
    ctx.report.support_selections.append(dict(mode='daily_training', state=state, activity=activity, game_day=day))
    if state == 'unknown':
        raise AutomationError('每日实训支援需求未核实，未借用或开始挑战。')
    return decision


def _support_controls(scene):
    from .workflows import BOTTOM
    return [token for token in scene.tokens if token.within(BOTTOM)
            and normalize(token.text) in ('支援', '解除支援')]


def reject_existing_planar_support(workflow, scene):
    from .planar_team import preparation, selection
    if not preparation(scene) or selection(scene):
        return
    confidence = max(.85, workflow.settings.ocr_confidence)
    if (workflow._planar_marker(scene)
            or any(normalize(token.text) == '解除支援' and confidence <= token.score <= 1
                   for token in _support_controls(scene))):
        raise AutomationError('本批实训无需借用，但饰品备战页仍有旧支援，未操作预设。')


def require_unborrowed(workflow, scene, *, planar):
    marker = workflow._planar_marker(scene) if planar else workflow._support_marker(scene)
    controls = _support_controls(scene)
    if (marker or len(controls) != 1 or normalize(controls[0].text) != '支援'
            or not max(.85, workflow.settings.ocr_confidence) <= controls[0].score <= 1):
        raise AutomationError('本批实训无需借用，但当前队伍的支援状态未核实，未开始挑战。')
