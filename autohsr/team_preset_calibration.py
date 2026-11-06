"""A single phone-to-team navigation attempt with local calibration evidence."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import time

import cv2
import numpy as np

from .challenge_account import verified_account
from .currency_wars_identity import AccountNotObserved, UID_VETO_FLOOR
from .models import AutomationError, EmptyCapture, InputInterrupted, Scene, Stopped, TaskResult, Token
from .storage import hold_read_sources, replace_file
from .team_calibration_destination import observe_team_page, same_team_page
from .team_calibration_pages import phone_team_target


OPERATION = 'team_preset_calibration'
SAFE_NEXT = '请核对本次入口与到页原图，按当前画面继续校准编队或预设。'
COLLECTION_FLOOR = .65
MAX_AGE = 8
MAX_CAPTURES = 6
MAX_PNG_BYTES = 64 * 1024 * 1024


def initial_record():
    return dict(schema=1, scope='open_team_from_phone', input_status='not_sent',
                destination_status='unknown', preset_members_verified=False,
                before_frames=[], after_frames=[])


def _pixel_sha(image):
    return hashlib.sha256(image.tobytes()).hexdigest()


@dataclass(frozen=True)
class _Frame:
    scene: Scene
    sequence: int
    captured_at: float
    target: Token | None
    team_page: dict | None
    pixel_sha256: str


class TeamPresetCalibration:
    def __init__(self, context):
        self.c = context
        self.window = context.window
        self.window_key = None
        self.epoch = context.runner.input_epoch
        self.confidence = context.settings.ocr_confidence
        self.account = None
        self.geometry = None
        self.directory = Path(context.report.run_dir).resolve()
        self.intent_path = self.directory / 'team-preset-entry-intent.json'
        self.intent_bytes = None
        self.before = ()
        self.submission = None
        self.arrival = ()
        self.record = initial_record()

    def _check_control(self):
        if self.c.runner.stop_requested:
            raise Stopped('编队入口校准已停止。')
        if self.c.runner.input_epoch != self.epoch:
            raise InputInterrupted('编队入口校准的输入代次已改变。')

    def guard_window(self):
        if self.window_key is None or self.window.current_window_key() != self.window_key:
            raise AutomationError('编队入口校准的前台窗口来源已改变。')
        self.window.guard(self.geometry)

    def _current(self, scene, sequence):
        self._check_control()
        if (self.c.report.operation != OPERATION or self.c.team_preset_reader is not self
                or self.c.report.team_preset_calibration is not self.record
                or self.c.scene_epoch != self.epoch or self.c.capture_sequence != sequence
                or self.c.last_scene is not scene or self.c.window is not self.window
                or scene.geometry is None or scene.geometry != self.geometry
                or not 0 <= time.monotonic() - scene.captured_at <= MAX_AGE):
            raise AutomationError('编队入口校准缺少同一窗口的当前新鲜画面。')
        image = scene.image
        if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
                or image.shape != (self.geometry.height, self.geometry.width, 3)):
            raise AutomationError('编队入口校准的采集尺寸与窗口不符。')

    def _read_account(self, scene):
        return verified_account(scene, self.confidence, expected=self.account, veto_floor=UID_VETO_FLOOR)

    def _observe(self, scene):
        target = phone_team_target(scene, self.confidence)
        return target, None if target is not None else observe_team_page(scene, self.confidence)

    def _capture(self):
        scene = self.c.snapshot()
        if self.geometry is None:
            self.geometry = scene.geometry
        sequence = self.c.capture_sequence
        self._current(scene, sequence)
        self.account = self._read_account(scene)
        target, page = self._observe(scene)
        return _Frame(scene, sequence, scene.captured_at, target, page, _pixel_sha(scene.image))

    @staticmethod
    def _adjacent(first, second):
        return (first.sequence + 1 == second.sequence and first.scene is not second.scene
                and first.captured_at < second.captured_at
                and 0 <= time.monotonic() - first.captured_at <= MAX_AGE
                and not np.may_share_memory(first.scene.image, second.scene.image))

    def _pair(self, *, after=None):
        previous = None
        pair = ()
        for attempt in range(MAX_CAPTURES):
            self._check_control()
            if attempt or after is not None:
                self.c.sleep(.30)
            try:
                frame = self._capture()
            except (EmptyCapture, AccountNotObserved):
                previous, pair = None, ()
                continue
            if (after is None and frame.target is None and frame.team_page is None
                    or after is not None and frame.captured_at <= after):
                previous, pair = None, ()
                continue
            if (previous is not None and self._adjacent(previous, frame)
                    and self._same_view(previous, frame)):
                pair = previous, frame
                if after is None or frame.team_page is not None:
                    return pair
            else:
                pair = ()
            previous = frame
        return pair

    @staticmethod
    def _agree(first, second):
        if first is None or second is None:
            return first is second
        return all(abs(a - b) <= .006 for a, b in zip(first.box, second.box))

    def _same_view(self, first, second):
        if first.team_page is not None or second.team_page is not None:
            return (first.team_page is not None and second.team_page is not None
                    and same_team_page(first.team_page, second.team_page))
        return self._agree(first.target, second.target)

    def _path(self, path):
        path = Path(path).absolute()
        if path.parent != self.directory or path.resolve(strict=True) != path or path.suffix != '.png':
            raise AutomationError('编队入口截图不在本次运行目录。')
        return path

    @staticmethod
    def _png(path):
        with path.open('rb') as stream:
            raw = stream.read(MAX_PNG_BYTES + 1)
        if not raw.startswith(b'\x89PNG\r\n\x1a\n') or len(raw) > MAX_PNG_BYTES:
            raise AutomationError('编队入口截图缺失或格式异常。')
        return raw

    def _check_frame(self, frame):
        scene = frame.scene
        if (scene.geometry != self.geometry or scene.captured_at != frame.captured_at
                or not 0 <= time.monotonic() - frame.captured_at <= MAX_AGE
                or _pixel_sha(scene.image) != frame.pixel_sha256
                or self._read_account(scene) != self.account
                or self._observe(scene) != (frame.target, frame.team_page)):
            raise AutomationError('编队入口采集的原画面、账号或控件已改变。')

    @staticmethod
    def _frame_data(frame):
        target = frame.target
        return dict(capture_sequence=frame.sequence, captured_at=frame.captured_at, pixel_sha256=frame.pixel_sha256,
                    phone_team_entry=dict(box=list(target.box), score=target.score) if target else None,
                    team_page=frame.team_page)

    def _save_frame(self, frame, label):
        self._check_frame(frame)
        path = self._path(self.c.evidence(frame.scene, 'team_preset_' + label))
        raw = self._png(path)
        decoded = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None or decoded.shape != frame.scene.image.shape or _pixel_sha(decoded) != frame.pixel_sha256:
            raise AutomationError('编队入口的落盘截图与采集不符。')
        return dict(self._frame_data(frame), screenshot=path.name, sha256=hashlib.sha256(raw).hexdigest())

    def _save_pair(self, frames, phase):
        self._current(frames[-1].scene, frames[-1].sequence)
        rows = [self._save_frame(frame, f'{phase}_{index}') for index, frame in enumerate(frames, 1)]
        if len({row['screenshot'] for row in rows}) != len(frames):
            raise AutomationError('编队入口校准需要独立的双帧截图。')
        self.guard_window()
        self._current(frames[-1].scene, frames[-1].sequence)
        return rows

    def _write_intent(self, frames):
        rows = self._save_pair(frames, 'before')
        size = [self.geometry.width, self.geometry.height]
        value = dict(schema=1, intent='open_phone_team', status='pending', sources=rows, client_size=size)
        payload = json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True).encode('utf-8')
        with self.intent_path.open('xb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        self.before = frames
        self.intent_bytes = payload
        self.record.update(before_frames=rows, intent=self.intent_path.name, client_size=size)

    def hold_intent(self):
        if self.intent_bytes is None or self.submission is None:
            raise AutomationError('编队入口缺少本次一次性动作意图。')
        rows = json.loads(self.intent_bytes)['sources']
        sources = [self._path(self.directory / row['screenshot']) for row in rows]
        return hold_read_sources([self.intent_path, *sources])

    def authorize(self, scene):
        frame = self.submission
        if (self.record['input_status'] != 'not_sent' or self.intent_bytes is None
                or len(self.before) != 2 or frame is None or frame.scene is not scene):
            raise AutomationError('编队入口缺少本次一次性动作意图。')
        self._current(scene, frame.sequence)
        with self.intent_path.open('rb') as stream:
            raw = stream.read(len(self.intent_bytes) + 1)
        if raw != self.intent_bytes:
            raise AutomationError('编队入口动作意图在发送前已改变。')
        rows = json.loads(self.intent_bytes)['sources']
        for previous, row in zip(self.before, rows):
            self._check_frame(previous)
            path = self._path(self.directory / row['screenshot'])
            if hashlib.sha256(self._png(path)).hexdigest() != row['sha256']:
                raise AutomationError('编队入口截图在发送前已改变。')
        self._check_frame(frame)
        self._current(scene, frame.sequence)
        return frame.target

    def mark_attempt(self, scene):
        self._current(scene, self.submission.sequence)
        if not self._adjacent(*self.before) or not self._adjacent(self.before[-1], self.submission):
            raise AutomationError('编队入口的连续来源已过期。')
        self.record['input_status'] = 'unconfirmed'
        self.record['submission_frame'] = self._frame_data(self.submission)

    def _diagnostic(self):
        if self.c.last_scene is not None:
            path = self.c.evidence(self.c.last_scene, 'team_preset_unverified')
            self.record['diagnostic_screenshot'] = Path(path).name

    def _observe_destination(self, frames, phase):
        self.record['after_frames'] = self._save_pair(frames, phase)
        if frames[-1].team_page is None:
            return False
        self.arrival = frames
        self.record['destination_status'] = 'team_page_verified'
        return True

    def save_report(self, temporary, write_report):
        destination = self.directory / 'report.json'
        if not self.arrival:
            write_report()
            replace_file(temporary, destination)
            return
        rows = self.record['after_frames']
        sources = [*self.record['before_frames'], *rows]
        if 'submission_frame' in self.record:
            sources.append(self.record['submission_frame'])
        try:
            files = [(self._path(self.directory / row['screenshot']), row['sha256']) for row in sources]
            paths = [path for path, _ in files]
            if len(set(paths)) != len(paths):
                raise AutomationError('编队到页报告复用了采集截图。')
            if self.intent_bytes is not None:
                paths.append(self.intent_path)
            with hold_read_sources(paths):
                payload = write_report()

                def recheck():
                    current = self.arrival[-1]
                    self._current(current.scene, current.sequence)
                    for frame in self.arrival:
                        self._check_frame(frame)
                    for path, expected in files:
                        if hashlib.sha256(self._png(path)).hexdigest() != expected:
                            raise AutomationError('编队到页报告的截图已改变。')
                    if self.intent_bytes is not None:
                        with self.intent_path.open('rb') as stream:
                            if stream.read(len(self.intent_bytes) + 1) != self.intent_bytes:
                                raise AutomationError('编队到页报告的原入口意图已改变。')
                    with temporary.open(encoding='utf-8') as stream:
                        if stream.read(len(payload) + 1) != payload:
                            raise AutomationError('编队到页的待发布报告已改变。')
                    self.guard_window()
                    if self.window.emergency_pressed():
                        raise Stopped('F10 紧急停止。')
                    self._current(current.scene, current.sequence)
                    if not self._adjacent(*self.arrival):
                        raise AutomationError('编队到页的连续双帧已过期。')

                replace_file(temporary, destination, before_replace=recheck)
        except (AutomationError, OSError, UnicodeError) as error:
            self.record['destination_status'] = 'unknown'
            report = self.c.report
            report.status = 'stopped' if isinstance(error, Stopped) else 'partial'
            report.failure_task = OPERATION
            report.error = '编队到页报告未核实：' + str(error)
            result = next(item for item in report.results if item.task == OPERATION)
            result.status = 'partial'
            result.detail = '到页报告未核实，保留原图和输入状态。'
            write_report()
            replace_file(temporary, destination)

    def run(self):
        if self.c.report.operation != OPERATION or getattr(self.c, 'team_preset_reader', None) is not None:
            raise AutomationError('编队入口校准须经本次独立任务。')
        self.c.team_preset_reader = self
        self.c.report.team_preset_calibration = self.record
        self.c.report.safe_next = SAFE_NEXT
        self.window_key = self.window.current_window_key()
        if type(self.window_key) is not str or not self.window_key:
            raise AutomationError('编队入口校准未核实前台窗口来源。')
        before = self._pair()
        if not before:
            self._diagnostic()
            return TaskResult(OPERATION, 'partial', '当前手机的编队入口待核实，已保留现场。')
        if before[-1].team_page is not None:
            self.record.update(scope='observe_current_team', client_size=[self.geometry.width, self.geometry.height])
            self._observe_destination(before, 'existing')
            return TaskResult(OPERATION, 'ok', '已核实当前普通编队页，已保存校准证据。')
        self._write_intent(before)
        # The evidence write can take time at 4K. Read the phone again before
        # authorizing the actual target and veto any intervening page change.
        self.submission = self._capture()
        if (not self._adjacent(before[-1], self.submission)
                or not self._agree(before[-1].target, self.submission.target)):
            raise AutomationError('编队入口落盘后当前手机或唯一控件已经改变。')
        submitted_at = self.c.team_preset_entry_input(self.submission.scene)
        self.record['submission_frame'] = self._save_frame(self.submission, 'submission')
        after = self._pair(after=submitted_at)
        if after and self._observe_destination(after, 'after'):
            return TaskResult(OPERATION, 'ok', '已核实打开普通编队页，已保存校准证据。')
        if not after:
            self._diagnostic()
        return TaskResult(OPERATION, 'partial', '已发送一次手机编队入口，已记录当前可取得的到页证据。')
