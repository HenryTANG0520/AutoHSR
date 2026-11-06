"""Open a requested challenge lobby from the current Interastral Guide."""
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import time

from . import challenge_pages as pages
from .challenge_account import verified_account
from .currency_wars_identity import AccountNotObserved
from .currency_wars_prepare import trusted
from .models import AutomationError, EmptyCapture, InputInterrupted, Stopped, TaskResult, Token, normalize
from .storage import hold_read_sources, replace_file
from .workflows import TITLE


OPERATION = 'challenge_lobby'
SAFE_NEXT = '查看当前高难页面与导航记录，未知动作留待核对。'
GUIDE_TITLE = '星际和平指南'
SURVIVAL = '生存索引'
HIGH_GUIDE = '逐光捡金'
MODES = {
    pages.MODE: ('忘却之庭', '混沌回忆'),
    pages.FICTION: ('虚构叙事', '虚构叙事'),
    pages.APOCALYPTIC: ('末日幻影', '末日幻影'),
}
MODE_CARDS = (.14, .50, .32, .83)
MODE_DETAIL = (.46, .30, .59, .36)
TELEPORT = (.72, .57, .88, .67)
HIGH_TAB = (.349, .154, .405, .235)
BLOCKERS = ('获得物品', '确认购买', '使用燃料', '验证码', '开始挑战', '挑战结束', '确认', '取消',
            '选择最高解锁关卡', '退出挑战', '是否消耗', '账号登录', '扫码登录', '用户协议', '更新游戏')


@dataclass(frozen=True)
class LobbyState:
    page: str
    mode: str | None = None
    variant: str | None = None


@dataclass(frozen=True)
class LobbyAction:
    intent: str
    target: Token


def _exact(scene, view, label, region):
    x1, y1, x2, y2 = region
    matches = [t for t in scene.tokens if normalize(t.text) == label and t.within(region)]
    if len(matches) != 1 or matches[0] not in view.tokens:
        return None
    token = matches[0]
    a, b, c, d = token.box
    return token if x1 <= a < c <= x2 and y1 <= b < d <= y2 else None


def _apocalyptic_stellar_home(scene, view):
    fields = (
        ('末日幻影', TITLE),
        ('支配遗忘', (.40, .48, .60, .57)),
        ('星启模式', (.45, .65, .56, .72)),
        ('更换编队', (.85, .64, .95, .72)),
        ('节点一', (.24, .73, .32, .80)),
        ('节点二', (.44, .73, .52, .80)),
        ('节点三', (.64, .73, .72, .80)),
    )
    return (not view.has(('常规模式', '当期记录', '重新编队'), exact=True)
            and all(_exact(scene, view, label, box) is not None for label, box in fields))


def observe(scene, confidence=.85):
    view = trusted(scene, max(.85, confidence))
    if scene.has(BLOCKERS, exact=True):
        return None
    if scene.has(GUIDE_TITLE, TITLE, exact=True):
        if not _exact(scene, view, GUIDE_TITLE, TITLE):
            return None
        if scene.has(SURVIVAL, TITLE, exact=True):
            if _exact(scene, view, SURVIVAL, TITLE) and not scene.has(HIGH_GUIDE, TITLE, exact=True):
                return LobbyState('survival_guide')
            return None
        if (not _exact(scene, view, HIGH_GUIDE, TITLE)
                or not all(_exact(scene, view, label, MODE_CARDS) for label, _ in MODES.values())):
            return None
        selected = [(mode, label) for mode, (_, label) in MODES.items() if scene.has(label, MODE_DETAIL, exact=True)]
        if len(selected) > 1 or (selected and not _exact(scene, view, selected[0][1], MODE_DETAIL)):
            return None
        return LobbyState('difficulty_guide', selected[0][0] if selected else None)
    if _apocalyptic_stellar_home(scene, view):
        return LobbyState('lobby', pages.APOCALYPTIC, 'stellar')
    previous = pages.observe(scene, confidence)
    if previous.kind == 'lobby' and previous.mode in MODES:
        return LobbyState('lobby', previous.mode)
    return None


def next_action(context, scene, mode):
    confidence = max(.85, context.settings.ocr_confidence)
    state = observe(scene, confidence)
    if state is None or state.page == 'lobby':
        return None
    view = trusted(scene, confidence)
    if state.page == 'survival_guide':
        match = context.template(scene, 'high_guide_tab', HIGH_TAB, threshold=.94)
        if match is None:
            return None
        x, y, score = match
        if not (HIGH_TAB[0] < x < HIGH_TAB[2] and HIGH_TAB[1] < y < HIGH_TAB[3] and .94 <= score <= 1):
            return None
        return LobbyAction('open_difficulty_guide', Token('逐光捡金页签', score, (x-.005, y-.007, x+.005, y+.007)))
    if state.mode != mode:
        target = _exact(scene, view, MODES[mode][0], MODE_CARDS)
        return LobbyAction('open_mode_card', target) if target else None
    target = _exact(scene, view, '传送', TELEPORT)
    return LobbyAction('enter_lobby', target) if target else None


class ChallengeLobbyNavigation:
    def __init__(self, context, mode):
        if context.report.operation != OPERATION or mode not in MODES or context.report.challenge:
            raise AutomationError('高难主页导航需要独立入口和明确模式。')
        self.c = context
        self.mode = mode
        self.epoch = context.runner.input_epoch
        self.geometry = None
        self.account = None
        self.pending = None
        self.receipt = None
        self.path = Path(context.report.run_dir) / 'challenge-lobby.json'
        if self.path.exists():
            raise AutomationError('本次高难导航记录已存在。')
        self.data = dict(schema=1, operation=OPERATION, mode=mode, status='observing',
                         lobby_verified=False, actions=[], battle_started=False)
        context.report.challenge = self.data
        context.challenge_lobby_navigation = self
        context.report.safe_next = SAFE_NEXT
        context.vision.uid_counterevidence_floor = .65

    def _save(self, data=None, *, before_replace=None):
        payload = json.dumps(self.data if data is None else data,
                             ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(payload)
        replace_file(temporary, self.path, before_replace=before_replace)
        return payload

    def _current(self, scene):
        self.c.checkpoint()
        if self.c.scene_epoch != self.epoch or self.c.runner.input_epoch != self.epoch:
            raise InputInterrupted('高难导航输入代次已改变。')
        if (scene is not self.c.last_scene or scene.geometry is None or scene.captured_at <= 0
                or not 0 <= time.monotonic()-scene.captured_at <= 8):
            raise AutomationError('高难导航缺少当前新鲜画面。')
        if self.geometry is not None and self.geometry != scene.geometry:
            raise AutomationError('高难导航期间窗口位置或大小改变。')
        self.c.window.guard(scene.geometry)
        return verified_account(scene, self.c.settings.ocr_confidence, expected=self.account, veto_floor=.65)

    def _evidence(self, scene, label):
        path, digest = self.c.evidence(scene, label, with_sha256=True)
        self._current(scene)
        return dict(file=path.name, sha256=digest, capture_sequence=self.c.capture_sequence)

    def _source_path(self, source):
        return self.path.parent / source['file']

    def _check_sources(self, scene, sources):
        for source in sources:
            if sha256(self._source_path(source).read_bytes()).hexdigest() != source['sha256']:
                raise AutomationError('高难导航原始截图已变化。')
        if self.c.window.emergency_pressed() is True:
            raise Stopped('F10 紧急停止。')
        self._current(scene)

    def _pair(self, expected, label):
        previous = None
        for index in range(12):
            if index:
                self.c.sleep(.4)
            try:
                scene = self.c.snapshot()
                account = self._current(scene)
            except (AccountNotObserved, EmptyCapture):
                previous = None
                continue
            state = observe(scene, self.c.settings.ocr_confidence)
            if state is None or not expected(state):
                previous = None
                continue
            if self.account is None:
                self.account = account
                self.geometry = scene.geometry
            sequence = self.c.capture_sequence
            if previous and previous[0] == state and previous[1] + 1 == sequence and previous[2] < scene.captured_at:
                return scene, state, [previous[3], self._evidence(scene, label+'_2')]
            previous = (state, sequence, scene.captured_at, self._evidence(scene, label+'_1'))
        raise AutomationError('高难导航未取得两张相邻一致的新画面。')

    def authorize(self, scene, action):
        if self.pending is None or self.pending[0] is not scene or self.pending[1] != action:
            raise AutomationError('高难导航缺少本次待提交动作。')
        if self._current(scene) != self.account or next_action(self.c, scene, self.mode) != action:
            raise AutomationError('高难导航目标或账号已变化。')
        _, _, payload, sources = self.pending
        self._check_journal(payload)
        self._check_sources(scene, sources)

    def input_sources(self):
        if self.pending is None:
            raise AutomationError('高难导航没有待提交动作。')
        return self.path, *(self._source_path(source) for source in self.pending[3])

    def _check_journal(self, expected):
        if self.path.read_bytes() != expected:
            raise AutomationError('高难导航原始意图已变化，保留当前文件。')

    def save_report(self, temporary, write_report):
        destination = self.path.parent / 'report.json'
        if self.receipt is None:
            write_report()
            replace_file(temporary, destination)
            return
        scene, sources, journal = self.receipt
        report = self.c.report
        try:
            with hold_read_sources([self.path, *(self._source_path(source) for source in sources)]):
                payload = write_report()

                def recheck():
                    self._check_journal(journal)
                    if temporary.read_text(encoding='utf-8') != payload:
                        raise AutomationError('高难导航待发布报告已变化。')
                    self._check_sources(scene, sources)

                replace_file(temporary, destination, before_replace=recheck)
        except (AutomationError, OSError, UnicodeError) as error:
            report.status = 'stopped' if isinstance(error, Stopped) else 'partial'
            report.error = str(error)
            report.safe_next = SAFE_NEXT
            report.failure_task = OPERATION
            report.results[-1] = TaskResult(OPERATION, report.status, '高难主页最终报告未核实，保留原回执。')
            self.data.pop('lobby_evidence', None)
            self.data.pop('variant', None)
            self.data.update(status='unverified', lobby_verified=False)
            write_report()
            replace_file(temporary, destination)

    def run(self):
        self._save()
        scene, state, sources = self._pair(lambda current: True, 'challenge_lobby_initial')
        for _ in range(4):
            if state.page == 'lobby':
                if state.mode != self.mode:
                    raise AutomationError('当前高难主页与请求模式不同。')
                verified = dict(self.data, status='verified', lobby_verified=True,
                                variant=state.variant, lobby_evidence=sources)
                with hold_read_sources(self._source_path(source) for source in sources):
                    journal = self._save(verified, before_replace=lambda: self._check_sources(scene, sources))
                self.receipt = scene, sources, journal
                self.data.update(verified)
                self.c.report.safe_next = '指定高难主页已核实，可继续独立备战。'
                return TaskResult(OPERATION, 'ok', '已核实指定高难主页。')
            action = next_action(self.c, scene, self.mode)
            if action is None or any(row['intent'] == action.intent for row in self.data['actions']):
                raise AutomationError('高难导航控件未知或已提交，原记录保留。')
            row = dict(intent=action.intent, status='pending', before=sources)
            self.data['actions'].append(row)
            payload = self._save(before_replace=lambda: self._current(scene))
            self.pending = scene, action, payload, sources
            try:
                self.c.challenge_lobby_input(scene, action)
                if action.intent == 'open_difficulty_guide':
                    expected = lambda current: current.page == 'difficulty_guide'
                elif action.intent == 'open_mode_card':
                    expected = lambda current: current.page == 'difficulty_guide' and current.mode == self.mode
                else:
                    expected = lambda current: current.page == 'lobby' and current.mode == self.mode
                scene, state, sources = self._pair(expected, 'challenge_lobby_'+action.intent)

                def before_verify():
                    self._check_journal(payload)
                    self._check_sources(scene, sources)

                verified = dict(row, status='verified', after=sources)
                with hold_read_sources(self._source_path(source) for source in sources):
                    self._save(dict(self.data, actions=[*self.data['actions'][:-1], verified]), before_replace=before_verify)
                row.update(verified)
            except (AutomationError, OSError):
                row['status'] = 'unknown'
                self.data['status'] = 'unverified'
                if self.path.is_file() and self.path.read_bytes() == payload:
                    self._save(before_replace=lambda: self._check_journal(payload))
                raise
            finally:
                self.pending = None
        raise AutomationError('高难导航超出本次有界步骤。')
