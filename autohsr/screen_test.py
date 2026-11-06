"""Observe the current calibrated daily page and publish only anonymous facts."""

from contextlib import ExitStack, contextmanager

from .achievement_pages import (ACHIEVEMENT_CATEGORIES, achievement_reward_panel_started,
                                observe_achievement_screen)
from .daily_event_observe import read_event_installation
from .daily_event_pages import _VERSION
from .daily_reward_guide_pages import reward_guide_page
from .models import AutomationError, Stopped, TaskResult
from .storage import hold_read_sources, replace_file
from .workflow_navigation import COLLECTION_FLOOR, classify_page
from .workflow_screen import _CurrentFrames
from .workflows import DailyWorkflow


OPERATION = 'screen_test'
SAFE_NEXT = '请手动打开已登录的日常页面并保持游戏窗口在前台，再核对当前页面。'
_STOPPED = '当前页面核对已停止。'
_UNVERIFIED = '当前日常页面或同账号连续双帧待核实。'
_PUBLICATION_FAILED = '报告提交前的前台窗口或页面证据待核实。'
_PAGE_NAMES = {
    'phone': '手机', 'guide': '星际和平指南', 'daily_training': '每日实训', 'survival_index': '生存索引',
    'assignments': '委托', 'mail': '邮件', 'battlepass': '无名勋礼', 'reward_guide': '奖励指南',
}
_ACHIEVEMENT_NAMES = {
    'achievement_overview': '成就总览', 'achievement_list': '成就分类', 'achievement_receipt': '成就奖励面板',
}
_NAMES = _PAGE_NAMES | _ACHIEVEMENT_NAMES
_CLAIM_CONTROLS = {'achievement_overview': 'bulk', 'achievement_list': 'single'}


def initial_record():
    return dict(schema=1, page='unknown', page_verified=False, account_verified=False, input_sent=False)


def _verified_page(value):
    if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
            or value.get('page_verified') is not True or value.get('account_verified') is not True
            or value.get('input_sent') is not False):
        return None
    page = value.get('page')
    if not isinstance(page, str) or page not in _NAMES:
        return None
    if page in _PAGE_NAMES:
        return page if 'achievement' not in value else None
    achievement = value.get('achievement')
    if not isinstance(achievement, dict) or achievement.keys() != {'category', 'visible_claim'}:
        return None
    category, claim = achievement['category'], achievement['visible_claim']
    if page == 'achievement_list':
        if not isinstance(category, str) or category not in ACHIEVEMENT_CATEGORIES:
            return None
    elif category is not None:
        return None
    return page if claim is None or claim == _CLAIM_CONTROLS.get(page) else None


def _observed_record(observation):
    page, category, claim = observation
    record = dict(initial_record(), page=page, page_verified=True, account_verified=True)
    if page in _ACHIEVEMENT_NAMES:
        record['achievement'] = dict(category=category, visible_claim=claim)
    return record


def desktop_result(value, status):
    page = _verified_page(value) if status == 'success' else None
    if page is None:
        return '当前页面待核对', SAFE_NEXT
    title = f'当前页面已核实 · {_NAMES[page]}'
    if page not in _ACHIEVEMENT_NAMES:
        return title, '同一账号的连续两帧一致。'
    if page == 'achievement_receipt':
        return title, '成就奖励面板可见，实际到账待核对。'
    state = value['achievement']
    category = state['category']
    claim = {'bulk': '两帧均看到「一键领取奖励」。', 'single': '两帧均看到可用的领取按钮。'}
    detail = claim.get(state['visible_claim'], '奖励可领状态待核对。')
    return title, (f'{category}。{detail}' if category is not None else detail)


class ScreenTestObserver:
    def __init__(self, context):
        self.context = context
        self.record = initial_record()
        self.result = None
        self._reader = self._pair = self._observation = self._guide_installation = None
        self._daily = DailyWorkflow(context)
        self._confidence = max(.85, context.settings.ocr_confidence)

    def _read_scene(self, scene):
        page = classify_page(scene, self._confidence, self._daily)
        achievement = observe_achievement_screen(scene, self._confidence)
        reward_guide = reward_guide_page(scene, client_version=_VERSION, confidence=self._confidence)
        if reward_guide:
            if page is not None or achievement is not None or achievement_reward_panel_started(scene):
                return None
            installation = read_event_installation(self.context.window)
            if installation.version != _VERSION:
                return None
            if self._guide_installation is not None and installation != self._guide_installation:
                raise AutomationError('奖励指南的客户端安装来源已变化。')
            self._guide_installation = installation
            return 'reward_guide', None, None
        if page is None:
            return achievement
        if achievement is None and page in _PAGE_NAMES and not achievement_reward_panel_started(scene):
            return page, None, None
        return None

    def _read_pair(self, pair):
        first, second = (self._read_scene(frame.scene) for frame in pair)
        self._reader.verify_pair(*pair)
        if first is None or second is None or first[:2] != second[:2]:
            return None
        if first[0] == 'reward_guide':
            if read_event_installation(self.context.window) != self._guide_installation:
                raise AutomationError('奖励指南的客户端安装来源已变化。')
            self._reader.guard()
        return (*first[:2], first[2] if first[2] == second[2] else None)

    def _result(self, status, detail):
        self.result = TaskResult(OPERATION, status, detail)
        return self.result

    def run(self):
        context = self.context
        if (context.report.operation != OPERATION or getattr(context.runner, '_foreground_only', False) is not True
                or getattr(context, 'screen_test_observer', None) is not None):
            raise AutomationError('当前页面核对需要独立的前台只读运行入口。')
        floor = getattr(context.vision, 'confidence', None)
        if type(floor) not in (int, float) or not 0 <= floor <= COLLECTION_FLOOR:
            raise AutomationError('当前页面核对须保留账号及遮挡的采集反证。')
        context.screen_test_observer = self
        context.report.screen_test = self.record
        try:
            self._reader = _CurrentFrames(context)
            first = self._reader.capture()
            context.sleep(.15)
            pair = first, self._reader.capture()
            observation = self._read_pair(pair)
        except Stopped:
            self.invalidate('stopped', _STOPPED)
            raise Stopped(_STOPPED) from None
        except AutomationError:
            return self._result('partial', _UNVERIFIED)
        if observation is None:
            return self._result('partial', _UNVERIFIED)
        self._pair, self._observation = pair, observation
        self.record.update(_observed_record(observation))
        return self._result('ok', f'已双帧核实当前页面为{_NAMES[observation[0]]}。')

    def invalidate(self, status, detail):
        self._pair = self._observation = self._guide_installation = None
        self.record.clear()
        self.record.update(initial_record())
        if self.result is not None:
            self.result.status, self.result.detail = status, detail

    def _check_record(self):
        context = self.context
        if (self._pair is None or self._observation is None or context.report.operation != OPERATION
                or context.report.status != 'success' or self.result is None or self.result.status != 'ok'
                or getattr(context, 'screen_test_observer', None) is not self
                or getattr(context.report, OPERATION, None) is not self.record
                or self.record != _observed_record(self._observation)
                or _verified_page(self.record) != self._observation[0]):
            raise AutomationError(_PUBLICATION_FAILED)

    def guard_publication(self):
        self._check_record()
        if self._read_pair(self._pair) != self._observation:
            raise AutomationError(_PUBLICATION_FAILED)
        self._check_record()

    def save_verified_report(self, temporary, write_report):
        report = self.context.report
        destination = temporary.with_name('report.json')

        @contextmanager
        def verify_attempt():
            with ExitStack() as locks:
                try:
                    if self._guide_installation is not None:
                        locks.enter_context(hold_read_sources((self._guide_installation.source,)))
                    with hold_read_sources((temporary,)):
                        if type(payload) is not str or temporary.read_text(encoding='utf8') != payload:
                            raise AutomationError(_PUBLICATION_FAILED)
                        self.guard_publication()
                except (OSError, UnicodeError):
                    raise AutomationError(_PUBLICATION_FAILED) from None
                yield

        try:
            self._check_record()
            payload = write_report()
            replace_file(temporary, destination, attempt_scope=verify_attempt)
        except AutomationError as error:
            stopped = isinstance(error, Stopped)
            if stopped:
                self.context.runner.stop()
            status, detail = ('stopped', _STOPPED) if stopped else ('partial', _PUBLICATION_FAILED)
            self.invalidate(status, detail)
            report.screen_test = self.record
            report.status, report.error, report.failure_task = status, detail, OPERATION
            write_report()
            replace_file(temporary, destination)
