"""Zero-input evidence from the current challenge preset list."""
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import time

import cv2
import numpy as np

from . import challenge_preset_page as page
from .challenge_account import verified_account
from .currency_wars_identity import AccountNotObserved, UID_VETO_FLOOR
from .models import AutomationError, EmptyCapture, InputInterrupted, Scene, Stopped, TaskResult
from .storage import hold_read_sources, replace_file


OPERATION = 'challenge_preset_observe'
SAFE_NEXT = '请在前台的「物竞天择其十」备战页查看「预设编队」，逐页另行观察。'
MAX_AGE = 8
MAX_CAPTURES = 6
_MAX_PNG_BYTES = 64 * 1024 * 1024


def initial_record():
    return dict(schema=1, operation=OPERATION, status='unknown', mode=None, level=None, tab=None,
                visible_presets=[], setup_slots=[], eight_slots_empty=None, evidence=[], input_status='not_sent')


@dataclass(frozen=True)
class _Frame:
    scene: Scene
    sequence: int
    captured_at: float
    pixels: str
    observation: dict


class PresetObserver:
    def __init__(self, context):
        if context.report.operation != OPERATION:
            raise AutomationError('高难预设观察需要独立入口。')
        self.c = context
        self.window = context.window
        self.window_key = self.window.current_window_key()
        if type(self.window_key) is not str or not self.window_key:
            raise AutomationError('高难预设观察未核实窗口来源。')
        self.directory = Path(context.report.run_dir).resolve(strict=True)
        self.epoch = context.runner.input_epoch
        self.confidence = context.settings.ocr_confidence
        context.vision.uid_counterevidence_floor = UID_VETO_FLOOR
        self.account = None
        self.geometry = None
        self.frames = ()
        self.sources = ()
        self.observed = None

    def _account(self, scene):
        return verified_account(scene, self.confidence, expected=self.account, veto_floor=UID_VETO_FLOOR)

    def _current(self, scene, sequence):
        if self.c.runner.stop_requested or self.window.emergency_pressed():
            raise Stopped('高难预设观察已停止。')
        if self.c.runner.input_epoch != self.epoch or self.c.scene_epoch != self.epoch:
            raise InputInterrupted('高难预设观察的输入代次已改变。')
        if (self.c.report.operation != OPERATION or self.c.last_scene is not scene or self.c.capture_sequence != sequence
                or self.c.window is not self.window or self.geometry is None or scene.geometry != self.geometry
                or not 0 <= time.monotonic() - scene.captured_at <= MAX_AGE):
            raise AutomationError('高难预设观察缺少同一窗口的当前画面。')

    @staticmethod
    def _adjacent(first, second):
        return (first.sequence + 1 == second.sequence and first.scene is not second.scene
                and first.captured_at < second.captured_at
                and 0 <= time.monotonic() - first.captured_at <= MAX_AGE
                and not np.may_share_memory(first.scene.image, second.scene.image))

    def _guard(self, frames):
        if self.window.current_window_key() != self.window_key:
            raise AutomationError('高难预设观察的窗口来源已改变。')
        self.window.guard(self.geometry)
        self._current(frames[-1].scene, frames[-1].sequence)
        if not self._adjacent(*frames):
            raise AutomationError('高难预设观察的相邻双帧已过期。')

    def _png(self, path):
        if path.parent != self.directory or path.suffix != '.png' or path.resolve(strict=True) != path:
            raise AutomationError('高难预设截图超出本次运行目录。')
        with path.open('rb') as stream:
            raw = stream.read(_MAX_PNG_BYTES + 1)
        if (len(raw) > _MAX_PNG_BYTES or not raw.startswith(b'\x89PNG\r\n\x1a\n') or raw[12:16] != b'IHDR'
                or int.from_bytes(raw[16:20], 'big') != self.geometry.width
                or int.from_bytes(raw[20:24], 'big') != self.geometry.height):
            raise AutomationError('高难预设截图的格式或窗口尺寸无效。')
        return raw

    def _save_frame(self, frame, index):
        path = Path(self.c.evidence(frame.scene, f'challenge_preset_observe_{index}')).absolute()
        raw = self._png(path)
        decoded = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if decoded is None or sha256(decoded.tobytes()).hexdigest() != frame.pixels:
            raise AutomationError('高难预设截图与采集不同。')
        return dict(screenshot=path.name, sha256=sha256(raw).hexdigest(), capture_sequence=frame.sequence,
                    captured_at=frame.captured_at, page=frame.observation)

    def run(self):
        previous = None
        for attempt in range(MAX_CAPTURES):
            if attempt:
                self.c.sleep(.30)
            try:
                scene = self.c.snapshot()
                if self.geometry is None:
                    self.geometry = scene.geometry
                sequence = self.c.capture_sequence
                self._current(scene, sequence)
                self.account = self._account(scene)
            except (EmptyCapture, AccountNotObserved):
                previous = None
                continue
            image = scene.image
            if not isinstance(image, np.ndarray) or image.shape != (self.geometry.height, self.geometry.width, 3):
                raise AutomationError('高难预设观察的采集尺寸与窗口不符。')
            pixels = sha256(image.tobytes()).hexdigest()
            observation = page.observe(scene, self.confidence)
            if observation is None:
                previous = None
                continue
            frame = _Frame(scene, sequence, scene.captured_at, pixels, observation)
            if previous is not None and self._adjacent(previous, frame):
                compared = page.compare(previous.observation, frame.observation)
                if compared is not None:
                    frames = previous, frame
                    self._guard(frames)
                    sources = tuple(self._save_frame(item, index) for index, item in enumerate(frames, 1))
                    if sources[0]['screenshot'] == sources[1]['screenshot']:
                        raise AutomationError('高难预设观察需要分别保存两张画面。')
                    self.frames, self.sources, self.observed = frames, sources, compared
                    return TaskResult(OPERATION, 'partial', '已采集高难预设双帧，等待报告复核。')
            previous = frame
        if self.c.last_scene is not None:
            path = self.c.evidence(self.c.last_scene, 'challenge_preset_unverified')
            self.c.report.challenge['diagnostic_screenshot'] = Path(path).name
        return TaskResult(OPERATION, 'partial', '当前高难备战页缺少同账号相邻双帧。')

    def save_report(self, temporary, write_report):
        report = self.c.report
        destination = self.directory / 'report.json'
        if self.observed is None:
            write_report()
            replace_file(temporary, destination)
            return
        result = next(item for item in report.results if item.task == OPERATION)
        paths = [self.directory / row['screenshot'] for row in self.sources]
        try:
            with hold_read_sources(paths):
                self._guard(self.frames)
                is_preset = self.observed['tab'] == 'preset_list'
                status = 'preset_tab_observed' if is_preset else 'role_list_observed'
                report.challenge.update(self.observed, status=status, evidence=list(self.sources))
                report.status = 'success' if is_preset else 'partial'
                report.failure_task = '' if is_preset else OPERATION
                result.status = 'ok' if is_preset else 'partial'
                result.detail = ('已核实混沌十层当前预设页和可见行。' if is_preset else
                                 '已核实混沌十层当前为角色列表，请打开预设编队后再次观察。')
                payload = write_report()

                def recheck():
                    for frame, path, source in zip(self.frames, paths, self.sources):
                        scene = frame.scene
                        if (scene.geometry != self.geometry or scene.captured_at != frame.captured_at
                                or sha256(scene.image.tobytes()).hexdigest() != frame.pixels
                                or self._account(scene) != self.account
                                or page.observe(scene, self.confidence) != frame.observation
                                or sha256(self._png(path)).hexdigest() != source['sha256']):
                            raise AutomationError('高难预设观察的原画面、账号或证据已改变。')
                    with temporary.open(encoding='utf-8') as stream:
                        if stream.read(len(payload) + 1) != payload:
                            raise AutomationError('高难预设观察的待发布报告已改变。')
                    self._guard(self.frames)

                replace_file(temporary, destination, before_replace=recheck)
        except (AutomationError, OSError, UnicodeError) as error:
            report.challenge = initial_record()
            report.status = 'stopped' if isinstance(error, Stopped) else 'partial'
            report.failure_task = OPERATION
            report.error = '高难预设报告未核实：' + str(error)
            result.status = 'partial'
            result.detail = '高难预设报告未核实，保留本次原图。'
            write_report()
            replace_file(temporary, destination)
