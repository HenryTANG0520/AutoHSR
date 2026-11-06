"""Bind the 4.6 event readout to a current native window and two fresh frames."""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path

from .currency_wars_identity import installed_client
from .daily_event_pages import _VERSION, phone_journey_event_entry, read_gift_of_odyssey
from .models import AutomationError, Stopped, TaskResult
from .storage import file_revision, hold_read_sources, replace_file
from .workflow_screen import _CurrentFrames


OPERATION = 'daily_event_observe'
SAFE_NEXT = '请手动打开游戏手机或巡星之礼页面，再执行只读核对。'
COLLECTION_FLOOR = .65
_STOPPED = '活动观察已停止。'
_UNVERIFIED = '当前游戏安装版本、窗口或连续双帧待核实。'
_PUBLICATION_FAILED = '报告提交前的游戏版本、窗口或活动读数待核实。'


def initial_record():
    return dict(schema=1, client_version=None, page='unknown', page_verified=False,
                account_verified=False, claimable_state='not_observed',
                claimable_days=[], claimed_days=[], unknown_days=[])


@dataclass(frozen=True)
class _Installation:
    version: str
    executable: Path
    source: Path
    sha256: str
    revision: tuple[int, int, int, int, int]


def read_event_installation(window):
    try:
        executable = Path(window.current_executable()).resolve(strict=True)
        source = executable.with_name('config.ini')
        with hold_read_sources((source,)):
            client = installed_client(executable)
            revision = file_revision(source)
        if Path(client['executable']) != executable or Path(client['source']) != source:
            raise ValueError()
        return _Installation(client['full_version'], executable, source, client['sha256'], revision)
    except Stopped:
        raise
    except (OSError, RuntimeError, ValueError, TypeError, KeyError):
        raise AutomationError('当前游戏进程的安装版本待核实。') from None


def _read_page(scene, version, confidence):
    entry = phone_journey_event_entry(scene, client_version=version, confidence=confidence)
    odyssey = read_gift_of_odyssey(scene, client_version=version, confidence=confidence)
    if entry is not None and odyssey is None:
        return 'phone_entry', tuple(entry.box)
    if entry is None and odyssey is not None:
        return 'gift_of_odyssey', odyssey
    return 'unknown', None


def _project(version, first, second):
    record = initial_record()
    record['client_version'] = version
    page, first_value = first
    second_page, second_value = second
    if page != second_page or page == 'unknown':
        return record
    if page == 'phone_entry':
        if any(abs(a - b) > .006 for a, b in zip(first_value, second_value)):
            return record
    else:
        claimable = sorted(set(first_value.claimable_days).intersection(second_value.claimable_days))
        claimed = sorted(set(first_value.claimed_days).intersection(second_value.claimed_days))
        unknown = sorted(set(range(1, 8)).difference(claimable, claimed))
        state = 'available' if claimable else 'unknown' if unknown else 'none'
        record.update(claimable_state=state, claimable_days=claimable, claimed_days=claimed, unknown_days=unknown)
    record.update(page=page, page_verified=True, account_verified=True)
    return record


class DailyEventObserver:
    def __init__(self, context):
        self.context = context
        self.record = initial_record()
        self.result = None
        self._reader = self._install = self._pair = self._reads = None
        self._started = False

    def _read_installation(self):
        reader = self._reader
        reader.guard()
        install = read_event_installation(reader.window)
        reader.guard()
        return install

    def _require_installation(self):
        if self._read_installation() != self._install:
            raise AutomationError('当前游戏的安装来源或版本已变化。')

    def _result(self, status, detail):
        self.result = TaskResult(OPERATION, status, detail)
        return self.result

    def run(self):
        context = self.context
        if (self._started or context.report.operation != OPERATION
                or getattr(context.runner, '_foreground_only', False) is not True
                or getattr(context, 'daily_event_observer', None) is not None):
            raise AutomationError('活动观察需要独立的前台只读运行入口。')
        floor = getattr(context.vision, 'confidence', None)
        if type(floor) not in (int, float) or not 0 <= floor <= COLLECTION_FLOOR:
            raise AutomationError('活动观察须保留当前账号和遮挡的采集反证。')
        self._started = True
        context.daily_event_observer = self
        context.report.daily_event_observe = self.record
        try:
            self._reader = _CurrentFrames(context)
            self._install = self._read_installation()
            version = self._install.version
            self.record['client_version'] = version
            if version != _VERSION:
                return self._result('failed', '当前游戏版本尚无活动界面校准。')
            first = self._reader.capture()
            first_read = _read_page(first.scene, version, context.settings.ocr_confidence)
            context.sleep(.15)
            self._require_installation()
            second = self._reader.capture()
            self._reader.verify_pair(first, second)
            second_read = _read_page(second.scene, version, context.settings.ocr_confidence)
            self._require_installation()
            self._reader.verify_pair(first, second)
        except Stopped:
            self.invalidate('stopped', _STOPPED)
            raise Stopped(_STOPPED) from None
        except AutomationError:
            return self._result('failed', _UNVERIFIED)

        self._pair, self._reads = (first, second), (first_read, second_read)
        self.record.update(_project(version, *self._reads))
        if self.record['page'] == 'phone_entry':
            return self._result('ok', '已双帧核实当前手机的旅情事记入口。')
        if self.record['page'] == 'unknown':
            return self._result('partial', '手机入口或巡星之礼页面待同账号双帧核实。')
        if self.record['unknown_days']:
            return self._result('partial', '已双帧核实巡星之礼，部分日卡待核对。')
        if self.record['claimable_state'] == 'none':
            return self._result('ok', '已双帧核实巡星之礼七张日卡均已领取。')
        return self._result('ok', '已双帧核实巡星之礼日卡状态。')

    def invalidate(self, status, detail):
        version = self._install.version if self._install is not None else None
        self._pair = self._reads = None
        self.record.clear()
        self.record.update(initial_record(), client_version=version)
        if self.result is not None:
            self.result.status, self.result.detail = status, detail

    def _check_record(self):
        if (self._install is None or self._pair is None or self._reads is None
                or self.context.report.operation != OPERATION
                or getattr(self.context.report, OPERATION, None) is not self.record
                or not self.record.get('page_verified')
                or self.record != _project(self._install.version, *self._reads)):
            raise AutomationError('活动观察报告来源未核实。')

    def guard_publication(self):
        try:
            self._check_record()
            self._require_installation()
            self._reader.verify_pair(*self._pair)
            current = tuple(_read_page(frame.scene, self._install.version, self.context.settings.ocr_confidence)
                            for frame in self._pair)
            if current != self._reads:
                raise AutomationError('活动观察的原始读数已变化。')
            self._reader.verify_pair(*self._pair)
            self._check_record()
        except AutomationError as error:
            stopped = isinstance(error, Stopped)
            self.invalidate('stopped' if stopped else 'failed', _STOPPED if stopped else _PUBLICATION_FAILED)
            raise

    def save_verified_report(self, temporary, write_report):
        report = self.context.report
        destination = temporary.with_name('report.json')
        try:
            self._check_record()
            payload = write_report()

            @contextmanager
            def verified_attempt():
                with ExitStack() as sources:
                    try:
                        sources.enter_context(hold_read_sources((self._install.source,)))
                    except (OSError, RuntimeError):
                        raise AutomationError('活动观察的安装来源在报告提交前待核实。') from None
                    with hold_read_sources((temporary,)):
                        try:
                            staged = temporary.read_text(encoding='utf8')
                        except UnicodeError:
                            staged = None
                        if type(payload) is not str or staged != payload:
                            raise AutomationError('活动观察的暂存报告已变化。')
                        self.guard_publication()
                    yield

            replace_file(temporary, destination, attempt_scope=verified_attempt)
        except AutomationError as error:
            stopped = isinstance(error, Stopped)
            if stopped:
                self.context.runner.stop()
            status = 'stopped' if stopped else 'failed'
            detail = _STOPPED if stopped else _PUBLICATION_FAILED
            self.invalidate(status, detail)
            report.daily_event_observe = self.record
            report.status, report.error, report.failure_task = status, detail, OPERATION
            write_report()
            replace_file(temporary, destination)
