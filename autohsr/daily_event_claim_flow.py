"""Coordinate one explicitly selected Odyssey card on an already open page."""
from contextlib import ExitStack, contextmanager
from pathlib import Path
import time

from .currency_wars_identity import AccountNotObserved
from .daily_event_claim import (ACTIVITY, OPERATION, _QUANTITY_BY_DAY, _VERSION, _pair, _require_fresh,
                                _supported_day, bind_current_claim_frame, prepare_claim)
from .models import AutomationError, Stopped, TaskResult
from .storage import hold_read_sources, replace_file
from .windows import GameWindow
from .workflow_identity import active as active_account_scope
from .workflow_lease import sequence_lease


_FRAME_DELAY = .15
_POPUP_DELAY = .75
_LEDGER_DIRECTORY = 'daily-event-claim'
SAFE_NEXT = '请在游戏内核对所选签到日。已有待核对记录时保留原记录，避免重复领取。'


def initial_record(day):
    return dict(schema=1, activity=ACTIVITY, day=day, client_version=None, state='not_sent',
                stage='source', submission='not_sent', popup='not_observed', quantity=None)


def _ledger(root):
    directory = Path(root).resolve(strict=True)
    if not directory.is_dir():
        raise AutomationError('巡星之礼缺少固定的用户数据目录。')
    for name in ('runs', _LEDGER_DIRECTORY):
        directory = directory / name
        directory.mkdir(exist_ok=True)
        if not directory.is_dir() or directory.resolve(strict=True) != directory:
            raise AutomationError('巡星之礼本地回执目录来源已变化。')
    return directory


class DailyEventClaim:
    """Run the independent submission and bounded popup observation for one day.

    The adapter supplies ``context.snapshot_foreground`` using the strict
    foreground branch of Context.snapshot. A lost window must raise promptly.
    """

    def __init__(self, context, *, root, day):
        if not _supported_day(day):
            raise AutomationError('巡星之礼只核对明确选择的第三至第七日。')
        self.context, self._root, self._day = context, root, day
        self._window, self._runner, self._vision = context.window, context.runner, context.vision
        self.record = initial_record(day)
        self._started = False
        self._intent = self._popup = None

    def _same_context(self):
        context = self.context
        return (context.window is self._window and context.runner is self._runner and context.vision is self._vision
                and context.report.operation == OPERATION and getattr(self._runner, '_foreground_only', False) is True
                and not active_account_scope())

    def _guard(self):
        if not self._same_context():
            raise AutomationError('巡星之礼领取的当前运行来源已变化。')
        if self._runner.stop_requested or self._window.emergency_pressed():
            raise Stopped('巡星之礼领取已停止。')
        self.context.checkpoint()
        self._window.guard()

    def _capture(self, snapshot, reader):
        self._guard()
        context, runner = self.context, self._runner
        previous, sequence = context.last_scene, context.capture_sequence
        epoch, occlusions = runner.input_epoch, context.capture_occlusion_count
        started = time.monotonic()
        scene = snapshot()
        stamp = getattr(scene, 'captured_at', None)
        if (scene is None or scene is previous or scene is not context.last_scene or not self._same_context()
                or context.capture_sequence != sequence + 1 or runner.input_epoch != epoch
                or context.capture_occlusion_count != occlusions or type(stamp) not in (int, float)
                or not started <= stamp <= time.monotonic()):
            raise AutomationError('巡星之礼需要本次同窗口一次采集的新鲜画面。')
        return bind_current_claim_frame(context, day=self._day, quantity_reader=reader, text_reader=reader)

    def _open_card(self, snapshot, reader):
        frame = self._capture(snapshot, reader)
        if frame.page is None or frame.button is None or frame.tickets is not None:
            raise AutomationError('请先打开巡星之礼，并核对指定日卡的可领取按钮。')
        return frame

    def _popup_frame(self, snapshot, reader, origin, previous):
        frame = self._capture(snapshot, reader)
        if (frame.scope != origin.scope or frame.context is not origin.context or frame.window is not origin.window
                or frame.sequence != previous.sequence + 1 or frame.captured_at <= previous.captured_at
                or frame.page is not None or frame.tickets != _QUANTITY_BY_DAY[self._day]):
            raise AutomationError('巡星之礼指定日的奖励弹窗待核对。')
        return frame

    def _observe_popup(self, before, snapshot, reader):
        self.record.update(stage='popup', popup='unknown')
        origin = before[-1]
        self._guard()
        self.context.sleep(_POPUP_DELAY)
        first = self._popup_frame(snapshot, reader, origin, origin)
        self._guard()
        self.context.sleep(_FRAME_DELAY)
        second = self._popup_frame(snapshot, reader, origin, first)
        popup = _pair((first, second), origin=origin)
        _require_fresh(before + popup)
        second.guard()
        self._popup = popup
        self.record.update(stage='return', popup='observed', quantity=second.tickets)

    def invalidate_popup(self):
        if self._popup is not None:
            self._popup = None
            self.record.update(stage='popup', popup='unknown', quantity=None)

    def save_verified_report(self, temporary, write_report):
        """Publish the observed popup without promoting the pending claim."""
        report = self.context.report
        destination = temporary.with_name('report.json')
        detail = '奖励弹窗在报告发布前失去核验证据，保留原领取意图。'

        @contextmanager
        def verify_attempt():
            with ExitStack() as locks:
                try:
                    origin = self._intent._before[-1]
                    before = self._intent._before
                    popup = _pair(self._popup, origin=origin)
                    locks.enter_context(hold_read_sources((origin.scope.executable.with_name('config.ini'),)))
                    with hold_read_sources((temporary,)):
                        if temporary.read_text(encoding='utf8') != payload:
                            raise AutomationError(detail)
                        _require_fresh(before + popup)
                        popup[-1].guard()
                except (OSError, UnicodeError):
                    raise AutomationError(detail) from None
                yield

        try:
            payload = write_report()
            replace_file(temporary, destination, attempt_scope=verify_attempt)
        except AutomationError as error:
            self.invalidate_popup()
            if isinstance(error, Stopped):
                self._runner.stop()
                report.status = 'stopped'
            else:
                report.status = 'partial'
            report.error = detail
            report.failure_task = OPERATION
            report.results[-1] = TaskResult(OPERATION, report.status, detail)
            write_report()
            replace_file(temporary, destination)

    def run(self):
        context = self.context
        snapshot = getattr(context, 'snapshot_foreground', None)
        submit = getattr(context, 'daily_event_claim_input', None)
        reader = getattr(self._vision, '_read_field', None)
        if (self._started or not self._same_context() or type(self._window) is not GameWindow
                or not callable(snapshot) or not callable(submit) or not callable(reader)):
            raise AutomationError('巡星之礼领取需要独立的严格前台采集入口。')
        self._started = True
        with sequence_lease():
            first = self._open_card(snapshot, reader)
            self._guard()
            context.sleep(_FRAME_DELAY)
            second = self._open_card(snapshot, reader)
            before = _pair((first, second))
            self.record.update(stage='intent', client_version=_VERSION)
            self._intent = prepare_claim(_ledger(self._root), before, day=self._day, checkpoint=context.checkpoint)
            self.record.update(state='pending', stage='submission', submission='unconfirmed')
            try:
                submit(self, self._intent)
            except Stopped:
                raise
            except (AutomationError, OSError):
                return TaskResult(OPERATION, 'partial', '本次提交待核对，已保留原领取意图。')
            self.record['submission'] = 'sent'
            try:
                self._observe_popup(before, snapshot, reader)
            except Stopped:
                raise
            except AccountNotObserved:
                self.record['popup'] = 'account_unverified'
                return TaskResult(OPERATION, 'partial', '提交后的画面缺少当前账号证据，已保留原领取意图。')
            except (AutomationError, OSError):
                return TaskResult(OPERATION, 'partial', '奖励弹窗待同账号连续核对，已保留原领取意图。')
            return TaskResult(OPERATION, 'partial', '已核实同账号奖励弹窗，领取仍待核对关闭后的同卡状态。')
