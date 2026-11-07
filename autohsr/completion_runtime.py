"""Post-run actions that preserve the original durable task report."""

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
import os
from pathlib import Path
import threading

from .models import AutomationError, RunReport, TaskResult
from .run_control import stop_requested
from .storage import replace_file
from .workflow_lease import native_idle_lease


_active = ContextVar('autohsr_completion_target', default=None)


def bind_window(window):
    scope = _active.get()
    if scope is not None:
        scope.bind(window)


class _Binding:
    target = None
    invalid = False

    def bind(self, window):
        if self.invalid:
            return
        try:
            if self.target is None:
                from .completion_window import CloseTarget
                self.target = CloseTarget(window)
            elif not self.target.matches(window):
                self.invalid = True
        except (OSError, ValueError, RuntimeError, AutomationError):
            self.invalid = True


def _play():
    import winsound
    winsound.PlaySound('SystemAsterisk', winsound.SND_ALIAS | winsound.SND_NODEFAULT)


def _receipt(path, receipt, *, create):
    temporary = path if create else path.with_suffix('.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    if not create:
        replace_file(temporary, path)


def _eligible(report, operations):
    return (isinstance(report, RunReport) and report.status == 'success' and report.report_saved is True
            and report.operation in operations and report.run_dir and report.finished_at
            and not (report.stamina_pending or report.immersifiers_pending)
            and all(result.status in ('ok', 'skipped') for result in report.results)
            and any(result.status == 'ok' for result in report.results))


def _require_saved_report(path, report, digest):
    with path.open('rb') as stream:
        raw = stream.read(64 * 1024 * 1024 + 1)
    if len(raw) > 64 * 1024 * 1024:
        raise ValueError('run report too large')
    if digest is not None and sha256(raw).hexdigest() != digest:
        raise ValueError('run report changed after verification')
    saved = json.loads(raw)
    if (not isinstance(saved, dict) or saved.get('report_saved') is not True
            or any(saved.get(key) != getattr(report, key)
                   for key in ('operation', 'run_dir', 'finished_at', 'status'))):
        raise ValueError('run report identity changed')


class CompletionActions:
    def __init__(self, *, sound, close_game, emit):
        self.sound, self.close_game, self.emit = sound, close_game, emit
        self.binding = _Binding()

    @contextmanager
    def capture(self):
        token = _active.set(self.binding if self.close_game else None)
        try:
            yield
        finally:
            _active.reset(token)

    def release(self):
        if self.binding.target is not None:
            self.binding.target.release()
            self.binding.target = None

    def skipped(self, detail):
        return dict(sound='skipped' if self.sound else 'not_requested',
                    close_game='skipped' if self.close_game else 'not_requested', close_detail=detail)

    def finish(self, report, *, stopped, operations, report_digest=None):
        if not _eligible(report, operations) or stopped():
            return self.skipped('本次运行未完整核实或已停止。')
        path = Path(report.run_dir) / 'completion.json'
        saved_report = path.with_name('report.json')
        receipt = dict(operation=report.operation, finished_at=report.finished_at,
                       sound='pending' if self.sound else 'not_requested',
                       close_game='pending' if self.close_game else 'not_requested')
        try:
            _require_saved_report(saved_report, report, report_digest)
            _receipt(path, receipt, create=True)
        except (OSError, ValueError, RecursionError):
            self._log('结束操作回执未建立，本次未执行。', 'warning')
            return self.skipped('结束操作回执未建立。')
        if self.close_game:
            status, detail = self._close(stopped)
            receipt.update(close_game=status, close_detail=detail)
        if self.sound:
            receipt['sound'] = 'skipped'
            if not stopped():
                try:
                    _play()
                    receipt['sound'] = 'requested'
                except (OSError, RuntimeError):
                    receipt['sound'] = 'failed'
                    self._log('完成提示音未能播放。', 'warning')
        try:
            _receipt(path, receipt, create=False)
        except OSError:
            self._log('结束操作结果未保存，保留原运行报告。', 'warning')
            return dict(sound='unknown' if self.sound else 'not_requested',
                        close_game='partial' if self.close_game else 'not_requested',
                        close_detail='结束操作结果保存失败，请核对原进程和回执。')
        return {key: value for key, value in receipt.items() if key in ('sound', 'close_game', 'close_detail')}

    def _close(self, stopped):
        target = self.binding.target
        if self.binding.invalid or target is None:
            return 'skipped', '无法持续核实本次游戏窗口。'
        try:
            with native_idle_lease():
                return target.request(stopped)
        except (AutomationError, OSError):
            return 'skipped', '已有其他任务运行或退出请求未核实。'

    def _log(self, message, level):
        self.emit(dict(type='log', level=level, phase='completion', message=message))


class _CompletionRunner:
    def __init__(self, runner, settings, emit):
        self.runner, self.emit = runner, emit
        self.actions = CompletionActions(sound=settings.finish_sound, close_game=settings.finish_close_game, emit=emit)
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._started = False

    def __getattr__(self, name):
        return getattr(self.runner, name)

    @property
    def stop_requested(self):
        return self._stop.is_set() or stop_requested(self.runner)

    def stop(self):
        self._stop.set()
        self.runner.stop()

    def run(self):
        with self._lock:
            if self._started:
                raise AutomationError('本次运行的结束操作已处理。')
            self._started = True
        try:
            with self.actions.capture():
                report = self.runner.run()
            if isinstance(report, RunReport):
                result = self.actions.finish(report, stopped=lambda: self.stop_requested, operations=('daily', 'plan'))
                if self.actions.close_game:
                    report.exit_status = result['close_game']
                    report.results.append(TaskResult('close_game', result['close_game'], result['close_detail']))
            self.emit(dict(type='finished', report=report.to_dict() if hasattr(report, 'to_dict') else report))
            return report
        finally:
            self.actions.release()


def hooks(settings, emit):
    if not (settings.finish_sound or settings.finish_close_game):
        return emit, lambda runner: runner

    def events(event):
        if event.get('type') != 'finished':
            emit(event)

    return events, lambda runner: _CompletionRunner(runner, settings, emit)
