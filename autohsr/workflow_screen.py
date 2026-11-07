"""Read two current native frames without game input or public frame evidence."""
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
import math
from pathlib import Path
import re
import time

import numpy as np
from PIL import Image

from .currency_wars_identity import checked_account_key
from .currency_wars_prepare import trusted
from .models import AutomationError, EmptyCapture, InputInterrupted, Stopped
from .screenshot_tool import MAX_BYTES, MAX_PIXELS, save_selection
from .storage import file_revision, hold_read_sources
from .task_workflow import GAME_CAPTURE_TASK
from .team_calibration_pages import calibration_overlay
from .vision import helper_overlay
from .workflow_vision import game_template_path, prepare_observation
from .workflows import DailyWorkflow


OPERATIONS = {'workflow_game_image': 'image_found', 'workflow_game_text': 'text_found'}
_QUERY_KEYS = frozenset(('template', 'text', 'region', 'threshold', 'contains'))
_MAX_AGE = 8.
_BLOCKERS = ('登录中', '加载中', '正在加载', '切换账号', '重新连接', '网络连接失败', '连接中断',
             '点击空白处关闭', '确认支付', '确认购买')


class WorkflowScreenError(AutomationError):
    """A current game observation remained unverified."""


def _digest(image):
    return sha256(np.ascontiguousarray(image)).digest()


@dataclass(frozen=True)
class _Frame:
    scene: object
    image: np.ndarray
    sequence: int
    captured_at: float
    account: str
    digest: bytes


class _CurrentFrames:
    def __init__(self, context):
        self.context = context
        context.checkpoint()
        self.window = context.window
        self.epoch = context.runner.input_epoch
        self.occlusions = context.capture_occlusion_count
        self.geometry = self.window.guard()
        self.key = self.window.current_window_key()
        if not self.key or self.geometry is None:
            raise WorkflowScreenError('游戏画面缺少可核实的当前前台窗口。')
        if not 0 < self.geometry.width * self.geometry.height <= MAX_PIXELS:
            raise WorkflowScreenError('游戏客户区像素超出画面判断上限。')

    def guard(self):
        context = self.context
        if context.runner.stop_requested or self.window.emergency_pressed():
            raise Stopped('游戏画面判断已停止。')
        if context.runner.input_epoch != self.epoch:
            raise InputInterrupted('游戏画面判断的输入代次已变化。')
        context.checkpoint()
        if context.runner.input_epoch != self.epoch:
            raise InputInterrupted('游戏画面判断的输入代次已变化。')
        if (context.window is not self.window or self.window.current_window_key() != self.key
                or self.window.guard(self.geometry) != self.geometry):
            raise WorkflowScreenError('游戏画面判断的窗口来源已变化。')
        if context.capture_occlusion_count != self.occlusions:
            raise WorkflowScreenError('本次游戏画面观察遇到助手遮挡。')

    def _account(self, scene):
        clean = trusted(scene, .65)
        if (DailyWorkflow._login(clean) or calibration_overlay(clean) or helper_overlay(clean)
                or clean.has(_BLOCKERS, exact=True)):
            raise WorkflowScreenError('当前游戏画面处于登录、加载或遮挡状态。')
        try:
            return checked_account_key(scene, self.context.settings.ocr_confidence)
        except AutomationError:
            raise WorkflowScreenError('当前账号标识缺失或冲突，游戏画面待核实。') from None

    def capture(self):
        self.guard()
        context = self.context
        previous, sequence = context.last_scene, context.capture_sequence
        started = time.monotonic()
        try:
            scene = context.snapshot()
        except EmptyCapture:
            raise WorkflowScreenError('当前游戏画面为空或仍在加载。') from None
        self.guard()
        image = scene.image
        if (scene is previous or scene is not context.last_scene or context.capture_sequence <= sequence
                or context.scene_epoch != self.epoch or scene.geometry != self.geometry
                or type(scene.captured_at) not in (float, int) or not math.isfinite(scene.captured_at)
                or scene.captured_at < started or not 0 <= time.monotonic() - scene.captured_at <= _MAX_AGE
                or not isinstance(image, np.ndarray) or image.dtype != np.uint8
                or image.shape != (self.geometry.height, self.geometry.width, 3)):
            raise WorkflowScreenError('游戏画面判断缺少同一窗口的本次新鲜帧。')
        sample = image[::max(1, self.geometry.height // 160), ::max(1, self.geometry.width // 240)]
        if float(np.std(sample, axis=(0, 1)).max()) < 2:
            raise WorkflowScreenError('当前游戏画面为空或仍在加载。')
        account = self._account(scene)
        return _Frame(scene, image, context.capture_sequence, scene.captured_at, account, _digest(image))

    def verify_pair(self, first, second):
        self.guard()
        context = self.context
        if (second.scene is not context.last_scene or context.capture_sequence != second.sequence
                or context.scene_epoch != self.epoch or second.sequence != first.sequence + 1
                or first.scene is second.scene or np.may_share_memory(first.image, second.image)
                or not first.captured_at < second.captured_at
                or not 0 <= time.monotonic() - first.captured_at <= _MAX_AGE):
            raise WorkflowScreenError('游戏画面判断缺少连续独立的新鲜双帧。')
        for frame in (first, second):
            if (frame.scene.image is not frame.image or frame.scene.captured_at != frame.captured_at
                    or frame.scene.geometry != self.geometry or _digest(frame.image) != frame.digest
                    or self._account(frame.scene) != frame.account):
                raise WorkflowScreenError('游戏画面的原始帧或账号核验已变化。')
        if first.account != second.account:
            raise WorkflowScreenError('游戏画面判断期间当前账号已改变。')
        self.guard()


def observe_game(context, query):
    """Return exactly one agreed boolean for the current account's game frames."""
    field = OPERATIONS.get(context.report.operation)
    if (field is None or getattr(context.runner, '_foreground_only', False) is not True
            or not isinstance(query, dict) or query.keys() - _QUERY_KEYS
            or (query.get('template') is not None) != (field == 'image_found')):
        raise WorkflowScreenError('游戏画面判断需要专用只读入口和明确条件。')
    reader = _CurrentFrames(context)
    if field == 'image_found':
        query = dict(query, template=game_template_path(query['template'], Path.cwd()))
    with prepare_observation(**query, checkpoint=reader.guard) as (found_field, match):
        first = reader.capture()
        first_result = match(first.image, native_bgr=True)
        context.sleep(.15)
        second = reader.capture()
        reader.verify_pair(first, second)
        second_result = match(second.image, native_bgr=True)
        reader.verify_pair(first, second)
        if first_result != second_result or found_field != field:
            raise WorkflowScreenError('游戏画面的两次识别结果不一致。')
    reader.guard()
    return {field: first_result}


def _pixel_box(region, width, height):
    return [round(value * size) for value, size in zip(region, (width, height) * 2)]


def capture_region(context, region, directory):
    if context.report.operation != GAME_CAPTURE_TASK or not context.runner._foreground_only:
        raise WorkflowScreenError('游戏截图须使用任务流的独立前台入口。')
    reader = _CurrentFrames(context)
    first = reader.capture()
    context.sleep(.15)
    second = reader.capture()
    reader.verify_pair(first, second)
    width, height = reader.geometry.width, reader.geometry.height
    box = _pixel_box(region, width, height)
    left, top, right, bottom = box
    if min(right-left, bottom-top) < 16:
        raise WorkflowScreenError('截图选区须至少为 16×16 像素。')

    def check():
        reader.verify_pair(first, second)
        return False

    path = directory / 'capture.png'
    image = Image.fromarray(second.image[:, :, ::-1])
    digest = save_selection(image, box, path, check)
    check()
    return dict(captured=True, file=path.name, source_size=[width, height], box=box, sha256=digest)


def verified_capture(result, region):
    """Bind a workflow capture receipt to its original local PNG."""
    from .workflow_bundle import _path

    capture = result.get('workflow_screen')
    if (not isinstance(capture, dict) or capture.keys() != {'captured', 'file', 'source_size', 'box', 'sha256'}
            or capture['captured'] is not True or capture['file'] != 'capture.png'
            or not isinstance(capture['sha256'], str) or re.fullmatch('[a-f0-9]{64}', capture['sha256']) is None):
        return None
    size = capture['source_size']
    if (not isinstance(size, list) or len(size) != 2 or any(type(value) is not int or value <= 0 for value in size)
            or size[0] * size[1] > MAX_PIXELS):
        return None
    box = _pixel_box(region, *size)
    recorded_box = capture['box']
    if (not isinstance(recorded_box, list) or any(type(value) is not int for value in recorded_box)
            or recorded_box != box or min(box[2]-box[0], box[3]-box[1]) < 16):
        return None
    try:
        path = _path(Path(result['run_dir']) / capture['file'])
        with hold_read_sources((path,)):
            revision = file_revision(path)
            with path.open('rb') as stream:
                raw = stream.read(MAX_BYTES + 1)
            if file_revision(path) != revision or not 0 < len(raw) <= MAX_BYTES:
                return None
            if sha256(raw).hexdigest() != capture['sha256']:
                return None
        with Image.open(BytesIO(raw)) as image:
            if image.format != 'PNG' or image.size != (box[2]-box[0], box[3]-box[1]):
                return None
            image.verify()
    except (KeyError, OSError, SyntaxError, TypeError, ValueError):
        return None
    return capture
