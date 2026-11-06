"""Observe the current calibrated daily page and publish only anonymous facts."""

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
    'assignments': '委托', 'mail': '邮件', 'battlepass': '无名勋礼',
}


def initial_record():
    return dict(schema=1, page='unknown', page_verified=False, account_verified=False, input_sent=False)


def _verified_page(value):
    if (not isinstance(value, dict) or type(value.get('schema')) is not int or value['schema'] != 1
            or value.get('page_verified') is not True or value.get('account_verified') is not True
            or value.get('input_sent') is not False):
        return None
    page = value.get('page')
    return page if isinstance(page, str) and page in _PAGE_NAMES else None


def desktop_result(value, status):
    page = _verified_page(value) if status == 'success' else None
    if page is None:
        return '当前页面待核对', SAFE_NEXT
    return f'当前页面已核实 · {_PAGE_NAMES[page]}', '同一账号的连续两帧一致。'


class ScreenTestObserver:
    def __init__(self, context):
        self.context = context
        self.record = initial_record()
        self.result = None
        self._reader = self._pair = self._page = None
        self._daily = DailyWorkflow(context)
        self._confidence = max(.85, context.settings.ocr_confidence)

    def _read_pair(self, pair):
        first, second = (classify_page(frame.scene, self._confidence, self._daily) for frame in pair)
        self._reader.verify_pair(*pair)
        return first if first == second and first in _PAGE_NAMES else None

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
            page = self._read_pair(pair)
        except Stopped:
            self.invalidate('stopped', _STOPPED)
            raise Stopped(_STOPPED) from None
        except AutomationError:
            return self._result('partial', _UNVERIFIED)
        if page is None:
            return self._result('partial', _UNVERIFIED)
        self._pair, self._page = pair, page
        self.record.update(page=page, page_verified=True, account_verified=True)
        return self._result('ok', f'已双帧核实当前页面为{_PAGE_NAMES[page]}。')

    def invalidate(self, status, detail):
        self._pair = self._page = None
        self.record.clear()
        self.record.update(initial_record())
        if self.result is not None:
            self.result.status, self.result.detail = status, detail

    def _check_record(self):
        context = self.context
        if (self._pair is None or self._page is None or context.report.operation != OPERATION
                or context.report.status != 'success' or self.result is None or self.result.status != 'ok'
                or getattr(context, 'screen_test_observer', None) is not self
                or getattr(context.report, OPERATION, None) is not self.record
                or self.record.keys() != initial_record().keys() or _verified_page(self.record) != self._page):
            raise AutomationError(_PUBLICATION_FAILED)

    def guard_publication(self):
        self._check_record()
        if self._read_pair(self._pair) != self._page:
            raise AutomationError(_PUBLICATION_FAILED)
        self._check_record()

    def save_verified_report(self, temporary, write_report):
        report = self.context.report
        destination = temporary.with_name('report.json')

        def verify_attempt():
            try:
                with hold_read_sources((temporary,)):
                    if type(payload) is not str or temporary.read_text(encoding='utf8') != payload:
                        raise AutomationError(_PUBLICATION_FAILED)
                    self.guard_publication()
            except (OSError, UnicodeError):
                raise AutomationError(_PUBLICATION_FAILED) from None

        try:
            self._check_record()
            payload = write_report()
            replace_file(temporary, destination, before_replace=verify_attempt)
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
