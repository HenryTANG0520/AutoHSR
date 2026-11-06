"""Dedicated one-click SMS input and anonymous receipt publication."""
from contextlib import ExitStack, contextmanager
from pathlib import Path

from .daily_message_reply import OPERATION, REPLY_SELECTIONS, reply_once
from .daily_message_reply_store import ReplyStore
from .models import AutomationError, Stopped, TaskResult
from .storage import replace_file
from .windows import GameWindow
from .workflow_identity import active as active_account_scope
from .workflow_lease import sequence_lease


SAFE_NEXT = '请核对当前选中会话。已有待核对或确认记录时保留原记录，避免重复发送。'


def supported_selection(selection):
    return type(selection) is tuple and all(type(value) is str for value in selection) and selection in REPLY_SELECTIONS


def initial_record(selection):
    node, choice = selection
    return dict(schema=1, node=node, choice=choice, client_version=None,
                input_status='not_sent', feedback_status='unknown', ledger_status='none')


def _ledger_directory(root):
    directory = Path(root).resolve(strict=True)
    for name in ('runs', 'daily-message-reply'):
        directory = directory / name
        directory.mkdir(exist_ok=True)
        if not directory.is_dir() or directory.resolve(strict=True) != directory:
            raise AutomationError('短信回复本地回执目录来源已变化。')
    return directory


class DailyMessageReply:
    def __init__(self, context, *, root, selection):
        if not supported_selection(selection):
            raise AutomationError('请明确选择受支持的短信节点和回复。')
        self.context = context
        self.record = initial_record(selection)
        self._item = REPLY_SELECTIONS[selection]
        self._root = root
        self._window, self._runner, self._vision = context.window, context.runner, context.vision
        self._started = False
        self._intent = self._feedback = self._confirmed_ledger = None

    def _guard_context(self):
        context = self.context
        if (context.window is not self._window or context.runner is not self._runner
                or context.vision is not self._vision or context.report.operation != OPERATION
                or getattr(context, 'daily_message_reply', None) is not self
                or context.report.daily_message_reply is not self.record
                or getattr(self._runner, '_foreground_only', False) is not True or active_account_scope()):
            raise AutomationError('短信回复需要独立的已核实前台运行来源。')
        if self._runner.stop_requested or self._window.emergency_pressed():
            raise Stopped('短信回复已停止。')

    def _submit(self, scene, point, *, before_submit):
        self._intent = (scene, point, before_submit)
        try:
            self.context.daily_message_reply_input(self, scene)
        finally:
            self._intent = None

    def dispatch(self, scene):
        self._guard_context()
        intent = self._intent
        if intent is None or scene is not intent[0] or scene is not self.context.last_scene:
            raise AutomationError('缺少本次短信回复的一次性意图。')
        _, point, reserve_and_verify = intent

        def before_submit():
            if self._intent is not intent:
                raise AutomationError('短信回复的一次性意图已消费。')
            reserve_and_verify()
            self._guard_context()
            self._intent = None
            self.record['input_status'] = 'unconfirmed'
            self.context.last_scene = self.context._scroll_anchor = None

        self._window.click(*point, scene.geometry, before_submit=before_submit)
        if self.record['input_status'] != 'unconfirmed':
            raise AutomationError('缺少本次短信回复的原生提交标记。')
        self.record['input_status'] = 'sent'

    def run(self):
        self._guard_context()
        if self._started or type(self._window) is not GameWindow:
            raise AutomationError('短信回复需要独立的原生前台入口。')
        self._started = True
        with sequence_lease():
            store = ReplyStore(_ledger_directory(self._root))
            self._feedback, self._confirmed_ledger = reply_once(
                self.context, store, item_id=self._item, submit=self._submit, record=self.record)
        return TaskResult(OPERATION, 'ok', '已核实同一会话中的新发出回复。')

    def invalidate_feedback(self):
        self._feedback = None
        self.record['feedback_status'] = 'unknown'

    def save_verified_report(self, temporary, write_report):
        """Hold the original confirmation through each report publication attempt."""
        report = self.context.report
        destination = temporary.with_name('report.json')
        feedback_detail = '报告发布前的短信反馈待核对，保留已保存的回复记录。'
        ledger_detail = '报告发布前的短信确认记录来源或内容已变化，保留待核对。'
        payload = write_report()
        check_feedback = True

        @contextmanager
        def verify_attempt():
            nonlocal check_feedback, payload
            with ExitStack() as holds:
                ledger_changed = False
                if self.record['ledger_status'] == 'confirmed':
                    try:
                        if self._confirmed_ledger is None:
                            raise AutomationError(ledger_detail)
                        holds.enter_context(self._confirmed_ledger())
                    except (AutomationError, OSError):
                        self.record['ledger_status'] = 'pending'
                        ledger_changed = True

                try:
                    if check_feedback:
                        self._guard_context()
                    if ledger_changed or temporary.read_text(encoding='utf8') != payload:
                        raise AutomationError(feedback_detail)
                    if check_feedback:
                        if (self._feedback is None or self.record['feedback_status'] != 'confirmed'
                                or self.record['ledger_status'] != 'confirmed'):
                            raise AutomationError(feedback_detail)
                        holds.enter_context(self._feedback())
                except (AutomationError, OSError, UnicodeError) as error:
                    detail = feedback_detail if check_feedback else report.error
                    if ledger_changed:
                        detail = ledger_detail
                    check_feedback = False
                    self.invalidate_feedback()
                    if isinstance(error, Stopped):
                        self._runner.stop()
                        report.status = 'stopped'
                    elif report.status != 'stopped':
                        report.status = 'partial'
                    report.error = detail
                    report.failure_task = OPERATION
                    report.results[-1] = TaskResult(OPERATION, report.status, detail)
                    payload = write_report()
                yield

        replace_file(temporary, destination, attempt_scope=verify_attempt)
