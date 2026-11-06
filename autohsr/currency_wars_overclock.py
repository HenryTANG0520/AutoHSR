"""Explicit mode selection and access to the calibrated overclock A0 page."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time

from .currency_wars import CurrencyWarsWorkflow, TASK, observe
from .currency_wars_identity import AccountNotObserved, account_key, installed_client
from .currency_wars_overclock_session import (
    FLOW_OPERATION, PREP_OPERATION, START_ACTION, START_FEEDBACK, START_OPERATION, OverclockSession, client_key,
)
from .currency_wars_overclock_preparation import MODE as PREPARATION_MODE
from .currency_wars_overclock_preparation_pages import (
    ACTIONS as PREPARATION_ACTIONS, PHASES as PREPARATION_PHASES, PreparationPage,
    preparation_target, read_preparation,
)
from .currency_wars_prepare import trusted
from .currency_wars_standard import NAVIGATION_BLOCKERS
from .currency_wars_state import strict_json
from .models import FULL, AutomationError, EmptyCapture, InputInterrupted, Scene, Stopped, TaskResult, Token, normalize
from .storage import file_revision, hold_read_sources, replace_file

OPERATION = 'currency_wars_overclock_configure'
LEGACY_HANDOFF_MODE = 'overclock_a0_legacy_handoff'
MODE_ROW = (0, .33, .2, .43)
MODE_TITLE = (.30, .11, .40, .18)
MODE_ENTRY = (.75, .85, .96, .94)
MODE_NAMES = ('标准博弈', '超频博弈')
RANK_MODE = (.02, .78, .2, .86)
CW_TITLE = (0, 0, .15, .08)
ACTIVE_MATCH = ('继续对局', '继续挑战', '继续货币战争', '未结算对局', '未结算的对局',
                '对局未完成', '对局进行中', '结束并结算', '放弃并结算')
READY_STATES = ('overclock_selected', 'a0_observed')
CALIBRATED_CLIENT = '4.6.0'
A0_OBJECTIVE = 'a0_difficulty'
A0_VETO_STATES = ('blocked', 'unexpected_page', 'standard_selected', 'rank_unsupported',
                  'controls_conflicting', 'effects_conflicting')
OBSERVE_SECONDS = 30.
MAX_FRAME_AGE = 8.
MAX_EVIDENCE_BYTES = 64 * 1024 * 1024
MAX_JOURNAL_BYTES = 1024 * 1024
JOURNAL = 'currency-overclock-config.json'
PNG_SIGNATURE = b'\x89PNG\r\n\x1a\n'
_DECORATION = str.maketrans('', '', '「」『』')


@dataclass(frozen=True)
class OverclockObservation:
    state: str
    mode: str | None = None
    rank: str | None = None
    enemy_difficulty: int | None = None


@dataclass(frozen=True)
class _Step:
    action: str
    before: str
    after: str
    label: str
    roi: tuple[float, float, float, float]


_SELECT = _Step('select_overclock', 'standard_selected', 'overclock_selected', '超频博弈', MODE_ROW)
_OPEN_A0 = _Step('open_overclock_difficulty', 'overclock_selected', 'a0_observed', '进入超频博弈', MODE_ENTRY)
_START_A0 = _Step(START_ACTION, 'a0_observed', START_FEEDBACK, '开始对局', (.80, .85, .97, .94))
_STEPS = {step.action: step for step in (_SELECT, _OPEN_A0)}


def _text(text):
    return normalize(text).translate(_DECORATION).replace('＋', '+')


def _matches(scene, labels, roi):
    return [t for t in scene.tokens if t.within(roi) and _text(t.text) in labels]


def read_overclock(scene, confidence=.65, *, require_a0_details=False) -> OverclockObservation:
    """One frame describes visible controls, without authorizing a start or rank change."""
    clean = trusted(scene, confidence)
    kind = observe(scene, confidence).page_kind
    title = _matches(clean, ('货币战争',), CW_TITLE)
    rows = _matches(clean, ('超频博弈',), MODE_ROW)
    headings = _matches(clean, MODE_NAMES, MODE_TITLE)
    entries = _matches(clean, ('进入标准博弈', '进入超频博弈'), MODE_ENTRY)
    rank_modes = _matches(clean, MODE_NAMES, RANK_MODE)
    mode_page = kind == 'mode_select' or bool(title and (headings or entries) and (rows or headings and entries))
    ranks = [t for t in clean.tokens if t.within((.02, .26, .20, .33))]
    a0_rank = any(re.fullmatch(r'a[0o]黑铁', _text(t.text)) for t in ranks)
    rank_page = kind == 'difficulty_select' or bool(title and (
        _matches(clean, ('超频博弈',), RANK_MODE)
        or a0_rank and clean.has('当前职级难度效果', (.34, .24, .70, .34))
    ))
    if (require_a0_details or mode_page or rank_page) and clean.has((*NAVIGATION_BLOCKERS, *ACTIVE_MATCH)):
        return OverclockObservation('blocked')
    if require_a0_details and kind not in ('unknown', 'mode_select', 'difficulty_select'):
        return OverclockObservation('unexpected_page')
    if not (mode_page or rank_page):
        return OverclockObservation('other_page')
    if require_a0_details and rank_page and entries:
        return OverclockObservation('controls_conflicting')
    if mode_page:
        if (kind != 'mode_select' or rank_page or len(title) != 1 or len(rows) != 1
                or len(headings) != 1 or len(entries) != 1
                or _matches(clean, ('开始对局',), MODE_ENTRY)
                or len(_matches(clean, ('标准博弈',), (0, .16, .2, .27))) != 1):
            return OverclockObservation('mode_unverified')
        heading, button = _text(headings[0].text), _text(entries[0].text)
        warning = _matches(clean, ('*无法通过该玩法模式提升职级', '无法通过该玩法模式提升职级'),
                           (.29, .27, .49, .34))
        if heading == '标准博弈' and button == '进入标准博弈' and not warning:
            return OverclockObservation('standard_selected', 'standard')
        if heading == '超频博弈' and button == '进入超频博弈' and len(warning) == 1:
            return OverclockObservation('overclock_selected', 'overclock')
        return OverclockObservation('mode_unverified')

    if (kind != 'difficulty_select' or len(title) != 1 or len(rank_modes) != 1
            or _text(rank_modes[0].text) != '超频博弈'
            or len(_matches(clean, ('开始对局',), (.80, .85, .97, .94))) != 1):
        return OverclockObservation('difficulty_unverified')
    if len(ranks) != 1:
        return OverclockObservation('rank_unverified', 'overclock')
    rank = _text(ranks[0].text)
    if not re.fullmatch(r'a[0o]黑铁', rank):
        state = 'rank_unsupported' if re.fullmatch(r'a[1-8][\u4e00-\u9fff0-9]{1,16}', rank) else 'rank_unverified'
        return OverclockObservation(state, 'overclock')
    bonus = _matches(clean, ('开局时获得【精密拆装扳手】',), (.36, .34, .65, .39))
    effects = [t for t in clean.tokens if '敌人难度' in _text(t.text) and t.within((.36, .38, .55, .44))]
    summary = [t for t in clean.tokens if '敌人难度' in _text(t.text) and t.within((.36, .17, .55, .23))]
    if require_a0_details:
        values = [_text(t.text) for t in (*effects, *summary)]
        if any(re.fullmatch(r'敌人难度\+[0-9]+', value) and value != '敌人难度+1' for value in values):
            return OverclockObservation('effects_conflicting', 'overclock', 'A0')
        detail_titles = _matches(clean, ('当前职级难度效果', '当前职级难度效果*效果叠加生效中'),
                                 (.36, .27, .64, .33))
        if len(detail_titles) != 1:
            return OverclockObservation('effects_unverified', 'overclock', 'A0')
    if (len(bonus) != 1 or any(len(field) != 1 or _text(field[0].text) != '敌人难度+1'
                                for field in (effects, summary))):
        return OverclockObservation('effects_unverified', 'overclock', 'A0')
    return OverclockObservation('a0_observed', 'overclock', 'A0', 1)


def _target(scene, confidence, step) -> Token:
    if read_overclock(scene, confidence, require_a0_details=step is not _SELECT).state != step.before:
        raise AutomationError('当前超频配置的模式页或入口未核实。')
    if step is _START_A0 and len(_matches(trusted(scene, confidence), (step.label,), FULL)) != 1:
        raise AutomationError('当前 A0 开始对局按钮不唯一。')
    minimum = max(.85, confidence) if step is not _SELECT else confidence
    targets = _matches(trusted(scene, minimum), (step.label,), step.roi)
    if len(targets) != 1:
        raise AutomationError('当前超频配置入口没有唯一可核实的目标。')
    return targets[0]


def read_overclock_start(scene, confidence=.65):
    observation = read_overclock(scene, confidence, require_a0_details=True)
    if observation.state == 'blocked' or observe(scene, confidence).page_kind != 'boss_preview':
        return observation
    clean = trusted(scene, confidence)
    if _matches(clean, ('开始对局', '进入标准博弈', '进入超频博弈'), FULL):
        return OverclockObservation('controls_conflicting')
    levels = [_text(t.text) for t in clean.tokens if t.within((.02, .87, .15, .95))
              and re.fullmatch(r'敌人难度[0-9]+', _text(t.text))]
    if levels != ['敌人难度1']:
        return OverclockObservation('boss_difficulty_conflicting')
    if (len(_matches(clean, ('本场对局首领',), (.72, .66, .85, .74))) != 1
            or len(_matches(clean, ('下一步',), (.74, .87, .84, .95))) != 1):
        return OverclockObservation('boss_preview_unverified')
    return OverclockObservation(START_FEEDBACK, enemy_difficulty=1)


def preview_factions(scene, confidence):
    clean = trusted(scene, confidence)
    names = []
    for left, right in ((.07, .20), (.22, .36), (.38, .52)):
        fields = [_text(t.text) for t in clean.tokens if t.within((left, .64, right, .70))]
        if len(fields) != 1 or not fields[0]:
            return None
        names.append(fields[0])
    return names


def require_legacy_frame(context, scene):
    """Keep the desktop flow on the account and installation it explicitly opened."""
    if getattr(context, '_currency_overclock_configuration', None) is not None:
        return
    confidence = context.settings.ocr_confidence
    if observe(scene, confidence).page_kind == 'unknown':
        return
    account = account_key(scene, confidence)
    if account_key(scene, max(.85, confidence)) != account:
        raise AutomationError('当前超频流程账号未核实。')
    window = context.window
    client = installed_client(window.current_executable())
    if client['full_version'] != CALIBRATED_CLIENT:
        raise AutomationError('当前超频流程的客户端版本证据不一致。')
    binding = (account, client_key(client), window, window.hwnd)
    prior = getattr(context, '_overclock_legacy_binding', None)
    if prior is not None and prior != binding:
        raise AutomationError('超频流程账号、安装来源或窗口已改变。')
    session = context.overclock_session
    if session.data is not None:
        if (session.data.get('match_started') is not True
                or (session.data['account_key'], session.data['client_key']) != binding[:2]):
            raise AutomationError('当前画面与原已核实的超频开局账号或安装来源不符。')
        window_key = session.data.get('window_key')
        if window_key is not None and window.current_window_key() != window_key:
            raise AutomationError('当前游戏窗口与原超频 A0 开局不一致。')
    context._overclock_legacy_binding = binding


def click_legacy_preview(context, scene, target):
    """Send the old preview step against its own pending intent and original opening."""
    from .currency_wars_entry import entry_target

    session = context.overclock_session
    guard = CurrencyWarsWorkflow(context)
    expected = context.report.currency_wars
    window, geometry = context.window, scene.geometry
    epoch = context.runner.input_epoch
    captured_at, occlusions = scene.captured_at, context.capture_occlusion_count
    frozen_image = _freeze_scene_pixels(scene, geometry)
    pixels = _pixels(frozen_image, geometry)
    checked_tokens = tuple(scene.tokens)
    revisions = {}
    try:
        with ExitStack() as sources:
            def hold_source(path):
                if path not in revisions:
                    _require_stable_source(path, revisions)
                    sources.enter_context(hold_read_sources((path,)))
                _require_stable_source(path, revisions)

            def before_send():
                unchanged = _hold_history_names(session.path.parent, sources)
                session.require_history(hold_source)
                original = session.require_active(hold_source)
                action = session.require_pending_preview(expected, hold_source)
                proof = _recorded_evidence(dict(screenshot=action.get('before'), sha256=action.get('before_sha256'),
                                                captured_at=action.get('captured_at'), state=START_FEEDBACK),
                                           START_FEEDBACK)
                _check_evidence(proof, session.run_dir, check_source=hold_source,
                                expected_pixels=(geometry, pixels))
                client = installed_client(window.current_executable())
                hold_source(Path(client['source']))
                context.checkpoint()
                guard._require_current_scene(scene)
                if (action.get('target') != list(target.box) or action.get('input_epoch') != epoch
                        or proof.captured_at != captured_at
                        or original.get('window_key') is not None
                        and proof.captured_at <= original['feedback'][-1]['captured_at']
                        or entry_target(scene, context.settings.ocr_confidence) != (
                            'advance_boss_preview', 'plane_map', target)):
                    raise AutomationError('首领预览的当前页面、目标或原截图已改变。')
                if session.advancing and (not original.get('preview_factions') or
                        preview_factions(scene, context.settings.ocr_confidence) != original['preview_factions']):
                    raise AutomationError('当前首领预览与原开局的阵营回执不一致。')
                window.guard(geometry)
                session.require_no_preparation()
                unchanged()
                if context.window is not window:
                    raise AutomationError('当前游戏窗口与原超频 A0 开局不一致。')
                window_key = original.get('window_key')
                if window_key is not None and window.current_window_key() != window_key:
                    raise AutomationError('当前游戏窗口与原超频 A0 开局不一致。')
                window.guard(geometry)
                if window.emergency_pressed():
                    raise Stopped('F10 紧急停止。')
                if context.runner.stop_requested:
                    raise Stopped('首领预览已停止，原记录保留。')
                if (context.runner.input_epoch != epoch or context.scene_epoch != epoch
                        or context.last_scene is not scene):
                    raise InputInterrupted('首领预览的输入代次已经改变。')
                if (scene.captured_at != captured_at or context.capture_occlusion_count != occlusions
                        or not 0 <= time.monotonic() - captured_at <= MAX_FRAME_AGE):
                    raise AutomationError('首领预览证据的时间或遮挡状态已改变。')
                _require_frozen_scene(scene, frozen_image, checked_tokens, geometry)
                session.preview_consumed = True
                context.last_scene, context._scroll_anchor = None, None

            window.click(*target.center, geometry, before_send=before_send)
    except OSError as error:
        raise AutomationError('首领预览原证据读取或共享读保护失败，保留原件。') from error


@dataclass(frozen=True, repr=False)
class _Frame:
    scene: Scene
    captured_at: float
    observation: OverclockObservation | PreparationPage
    account_observed: bool
    pixels: str
    occlusions: int


@dataclass(frozen=True)
class _Evidence:
    screenshot: str
    sha256: str
    captured_at: float
    state: str


@dataclass(frozen=True, repr=False)
class _Pending:
    frame: _Frame
    target: Token
    proof: _Evidence
    journal: bytes
    deadline: float
    history: frozenset[Path]


def _require_stable_source(path, revisions):
    """Bind a source before its content check and reject any later revision."""
    try:
        if path.resolve(strict=True) != path:
            raise AutomationError('超频配置原证据路径已改变，未发送输入。')
        revision = file_revision(path)
    except OSError as error:
        raise AutomationError('超频配置原证据或落盘记录不可复核，未发送输入。') from error
    if revisions.setdefault(path, revision) != revision:
        raise AutomationError('超频配置原证据或落盘记录已改变，未发送输入。')


def _read_bytes(path, limit, *, check_source=None):
    if check_source is not None:
        check_source(path)
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise AutomationError('超频配置证据的文件大小无效。')
    return raw


def _hold_history_names(directory, read_sources):
    """Keep an OS notification for name changes during the final history check."""
    import ctypes as C
    from ctypes import wintypes as W

    kernel = C.WinDLL('kernel32', use_last_error=True)
    watch = kernel.FindFirstChangeNotificationW
    watch.argtypes = (W.LPCWSTR, W.BOOL, W.DWORD)
    watch.restype = W.HANDLE
    wait = kernel.WaitForSingleObject
    wait.argtypes = (W.HANDLE, W.DWORD)
    wait.restype = W.DWORD
    close = kernel.FindCloseChangeNotification
    close.argtypes = (W.HANDLE,)
    close.restype = W.BOOL
    # Watch file and directory names in the whole runs subtree, including restores.
    handle = watch(str(directory), True, 0x01 | 0x02)
    if handle == W.HANDLE(-1).value:
        raise C.WinError(C.get_last_error())
    read_sources.callback(close, handle)

    def require_unchanged():
        status = wait(handle, 0)
        if status == 0:
            raise AutomationError('超频配置旧记录集合已改变，未发送输入。')
        if status != 258:  # WAIT_TIMEOUT means no change is pending.
            raise AutomationError('超频配置旧记录集合无法复核，未发送输入。')

    return require_unchanged


def _pixel_bytes(image, geometry):
    import numpy as np
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8
            or image.shape != (geometry.height, geometry.width, 3)):
        raise AutomationError('超频配置截图与窗口尺寸不符。')
    return image.tobytes()


def _pixels(image, geometry):
    return hashlib.sha256(_pixel_bytes(image, geometry)).hexdigest()


def _freeze_scene_pixels(scene, geometry):
    import numpy as np

    shape = (geometry.height, geometry.width, 3)
    # A bytes-backed view keeps the captured pixels immutable through native send.
    image = np.frombuffer(_pixel_bytes(scene.image, geometry), dtype=np.uint8).reshape(shape)
    scene.image = image
    return image


def _require_frozen_scene(scene, image, tokens, geometry):
    if (scene.geometry != geometry or scene.image is not image
            or image.shape != (geometry.height, geometry.width, 3) or image.dtype.name != 'uint8'
            or not image.flags.c_contiguous or image.flags.writeable or tuple(scene.tokens) != tokens):
        raise AutomationError('超频配置核实后的像素来源或文字已改变。')


def _png_pixels(raw, geometry):
    import cv2
    import numpy as np

    if (len(raw) < 24 or not raw.startswith(PNG_SIGNATURE) or raw[12:16] != b'IHDR'
            or int.from_bytes(raw[16:20], 'big') != geometry.width
            or int.from_bytes(raw[20:24], 'big') != geometry.height):
        raise AutomationError('超频配置落盘 PNG 与原窗口尺寸不符。')
    image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_UNCHANGED)
    return _pixels(image, geometry)


def _evidence_bytes(path, directory, *, check_source=None):
    source = Path(path)
    if not source.is_absolute() and not source.anchor:
        source = directory / source
    path = source.resolve(strict=True)
    if path != source or not path.is_relative_to(directory) or path.suffix.lower() != '.png' or not path.is_file():
        raise AutomationError('超频配置证据未保存在原运行目录。')
    return path, _read_bytes(path, MAX_EVIDENCE_BYTES, check_source=check_source)


def _check_evidence(proof, directory, *, check_source=None, expected_pixels=None):
    path, raw = _evidence_bytes(proof.screenshot, directory, check_source=check_source)
    if (len(raw) < 24 or not raw.startswith(PNG_SIGNATURE) or raw[12:16] != b'IHDR'
            or hashlib.sha256(raw).hexdigest() != proof.sha256):
        raise AutomationError('超频配置落盘证据已改变。')
    if expected_pixels is not None:
        geometry, digest = expected_pixels
        if _png_pixels(raw, geometry) != digest:
            raise AutomationError('超频配置落盘 PNG 与原画面像素不同。')
    return path


def _recorded_evidence(value, state):
    if type(value) is not dict:
        raise AutomationError('旧超频配置截图来源不完整。')
    path, digest, stamp = value.get('screenshot'), value.get('sha256'), value.get('captured_at')
    if (not isinstance(path, str) or not path or not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest)
            or type(stamp) not in (int, float) or not 0 < stamp <= 2**53 or value.get('state') != state):
        raise AutomationError('旧超频配置截图来源不完整。')
    return _Evidence(path, digest, stamp, state)


def _resolved_configuration(data, directory, *, check_source=None):
    if (type(data) is not dict or data.get('mode') != 'overclock_configuration'
            or data.get('match_started') is not False or data.get('completion_verified') is not False):
        return False
    actions = data.get('actions')
    if type(actions) is not list:
        return False
    if not actions:
        return data.get('status') in ('observing', 'partial', 'verified')
    if len(actions) != 1 or type(actions[0]) is not dict:
        return False
    action = actions[0]
    intent = action.get('action')
    step = _STEPS.get(intent) if isinstance(intent, str) else None
    if step is None:
        return False
    a0 = step is _OPEN_A0
    epoch, box = action.get('input_epoch'), action.get('target')
    observation, feedback = data.get('observation'), data.get('feedback')
    if (action.get('status') != 'verified'
            or data.get('status') != 'verified' or data.get('mode_verified') is not True
            or data.get('difficulty_verified') is not a0
            or type(epoch) is not int or epoch < 0 or type(box) is not list or len(box) != 4
            or any(type(edge) not in (int, float) or not 0 <= edge <= 1 for edge in box)
            or box[0] >= box[2] or box[1] >= box[3] or not Token(step.label, 1., tuple(box)).within(step.roi)
            or type(observation) is not dict or observation.get('state') != step.after
            or observation.get('mode') != 'overclock' or type(feedback) is not list or len(feedback) != 2):
        return False
    if a0:
        difficulty = observation.get('enemy_difficulty')
        if (data.get('objective') != A0_OBJECTIVE or data.get('client_version') != CALIBRATED_CLIENT
                or observation.get('rank') != 'A0' or type(difficulty) is not int or difficulty != 1):
            return False
    elif observation.get('rank') is not None or observation.get('enemy_difficulty') is not None:
        return False
    before = _recorded_evidence(action.get('before'), step.before)
    first, second = (_recorded_evidence(row, step.after) for row in feedback)
    if not before.captured_at < first.captured_at < second.captured_at <= first.captured_at + MAX_FRAME_AGE:
        return False
    return len({_check_evidence(proof, directory, check_source=check_source) for proof in (before, first, second)}) == 3


class _Configuration:
    def __init__(self, context, *, start=False, prepare=False):
        self.c = context
        self.operation = context.report.operation
        self.session = getattr(context, 'overclock_session', None) if start else None
        self.preparation = getattr(context, 'overclock_preparation', None) if prepare else None
        self.handoff = prepare and self.operation == FLOW_OPERATION
        if not context.report.run_dir or not (start or prepare) and self.operation != OPERATION:
            raise AutomationError('超频操作需要明确入口和本次未使用的运行记录。')
        if prepare and (self.operation not in (PREP_OPERATION, FLOW_OPERATION) or self.preparation is None):
            raise AutomationError('超频备战需要明确入口和原开局回执。')
        if self.handoff:
            session = self.preparation.session
            if (not session.legacy_handoff or context.runner.currency_start_from_lobby
                    or session is not getattr(context, 'overclock_session', None)):
                raise AutomationError('推进当前对局需要本次预检过的超频 A0 首备战回执。')
            self.preparation.require_complete()
        if start:
            start_allowed = self.operation == START_OPERATION or (
                self.operation == FLOW_OPERATION and context.runner.currency_start_from_lobby)
            if not start_allowed or not isinstance(self.session, OverclockSession) or self.session.data is not None:
                raise AutomationError('超频开局需要明确入口和本次未使用的开局意图。')
        self.directory = Path(context.report.run_dir).resolve(strict=True)
        if start and self.session.run_dir != self.directory:
            raise AutomationError('超频开局意图与本次运行目录不一致。')
        self.path = self.session.path if start else self.directory / JOURNAL
        if prepare:
            if self.preparation.session.run_dir != self.directory:
                raise AutomationError('超频备战回执与本次运行目录不一致。')
            self.path = self.preparation.path
        if not self.directory.is_dir() or not prepare and self.path.exists():
            raise AutomationError('超频模式配置的运行目录无效或已有记录。')
        self.epoch = context.runner.input_epoch
        self.confidence = context.settings.ocr_confidence
        self.step = _START_A0 if start else _OPEN_A0 if context.runner.currency_overclock_open_a0 else _SELECT
        self.ready_states = () if start else ('a0_observed',) if self.step is _OPEN_A0 else READY_STATES
        self.start_states = (self.step.before, *self.ready_states)
        if prepare:
            index = len(self.preparation.steps)
            self.step = (_Step(PREPARATION_ACTIONS[index], PREPARATION_PHASES[index],
                               PREPARATION_PHASES[index + 1], '', FULL)
                         if index < len(PREPARATION_ACTIONS) else None)
            self.start_states = (self.preparation.phase,)
            self.ready_states = self.start_states if self.step is None else ()
        self.client = None
        self.client_window = None
        self.window_key = self.preparation.window_key if prepare else None
        legacy = getattr(context, '_overclock_legacy_binding', None)
        self.account = legacy[0] if start and legacy is not None else None
        self.geometry = None
        self.pending = None
        self.saved_journal = None
        self.journal_revision = None
        self.guard = CurrencyWarsWorkflow(context)
        self.data = dict(mode='overclock_a0_start' if start else 'overclock_configuration',
                         status='observing', mode_verified=False,
                         difficulty_verified=False, match_started=False, completion_verified=False,
                         actions=[], observation=None, feedback=[])
        if self.step is _OPEN_A0:
            self.data['objective'] = A0_OBJECTIVE
        if prepare:
            self.saved_journal = self.preparation.raw
            self.journal_revision = self.preparation.revision
            self.account = self.preparation.session.data['account_key']
            self.data.update(mode=PREPARATION_MODE, match_started=True, mode_verified=True,
                             difficulty_verified=True, phase=self.preparation.phase, first_preparation_verified=False)
        if self.handoff:
            self.data.update(mode=LEGACY_HANDOFF_MODE, status='partial', handoff_verified=False,
                             gameplay_enabled=False, roster_verified=False, loot_verified=False)

    def _require_client(self):
        if self.step is _SELECT:
            return
        window = self.c.window
        source_window = (window, window.hwnd)
        client = installed_client(window.current_executable())
        if client['full_version'] != CALIBRATED_CLIENT or self.client is not None and client != self.client:
            raise AutomationError('当前客户端与超频 A0 难度页的原版本证据不一致。')
        if self.client_window is None:
            self.client_window = source_window
        self._require_client_window()
        legacy = getattr(self.c, '_overclock_legacy_binding', None)
        if self.session is not None and legacy is not None and legacy[1:] != (client_key(client), *source_window):
            raise AutomationError('超频开局的安装来源或窗口与本次入口不符。')
        if self.preparation is not None and client_key(client) != self.preparation.session.data['client_key']:
            raise AutomationError('当前客户端的安装来源与原超频 A0 开局不一致。')
        if self.session is not None and self.client is None:
            self.window_key = window.current_window_key()
        self._require_window_key()
        self.client = client

    def _require_client_window(self):
        if self.client_window is not None and self.client_window != (self.c.window, self.c.window.hwnd):
            raise AutomationError('超频 A0 难度页的原窗口已改变。')

    def _require_window_key(self):
        if self.window_key is not None and self.c.window.current_window_key() != self.window_key:
            raise AutomationError('当前游戏窗口与原超频 A0 开局不一致。')

    @contextmanager
    def _publication_scope(self, read_sources, recheck, proofs):
        revisions = {}
        with ExitStack() as stack:
            def hold_source(path):
                if path not in revisions:
                    _require_stable_source(path, revisions)
                    stack.enter_context(hold_read_sources((path,)))
                _require_stable_source(path, revisions)

            for path in read_sources:
                hold_source(path)
            if self.session is not None and len({revision[:2] for revision in revisions.values()}) != len(revisions):
                raise AutomationError('超频开局需要各自独立的原始证据。')
            if self.preparation is not None:
                unchanged = _hold_history_names(self.directory.parent, stack)
                self.preparation.require_sources(hold_source)
                if proofs:
                    self.preparation.require_new_proofs(proofs, revisions)
            recheck()
            if self.preparation is not None:
                unchanged()
            yield

    def _persist(self, data, *, check_sources=None, check_frames=None, read_sources=(), proofs=()):
        record = data
        private = self.session is not None or self.preparation is not None
        if private and not data['actions']:
            self.data = self.c.report.currency_wars = data
            return None
        if self.session is not None:
            record = self.session.envelope(data, self.account, self.client, window_key=self.window_key)
        if self.preparation is not None:
            record = self.preparation.envelope(data)
        payload = json.dumps(record, ensure_ascii=False, indent=2, allow_nan=False).encode('utf-8')
        if len(payload) > MAX_JOURNAL_BYTES:
            raise AutomationError('超频配置记录超过 1 MiB，原记录保留。')
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('xb' if private else 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        previous = self.saved_journal

        def recheck():
            if check_sources is not None:
                check_sources()
            if _read_bytes(temporary, MAX_JOURNAL_BYTES) != payload:
                raise AutomationError('超频配置待发布记录已改变。')
            self._check_journal(previous)
            if check_frames is not None:
                check_frames()

        def attempt():
            return self._publication_scope(read_sources, recheck, proofs)

        if private and previous is None:
            # On Windows rename without replacement fails if another receipt has appeared.
            with attempt():
                temporary.rename(self.path)
        elif read_sources or self.preparation is not None:
            replace_file(temporary, self.path, attempt_scope=attempt)
        else:
            replace_file(temporary, self.path, before_replace=recheck)
        self.saved_journal = payload
        if self.session is not None:
            self.session.raw, self.session.data = payload, record
        if self.preparation is not None:
            self.journal_revision = file_revision(self.path)
        self.data = self.c.report.currency_wars = data
        return payload

    def _check_journal(self, expected):
        try:
            if self.path.resolve(strict=True) != self.path:
                raise AutomationError('超频配置记录的来源路径已改变。')
            if self.preparation is not None and file_revision(self.path) != self.journal_revision:
                raise AutomationError('首次备战原记录的文件修订已改变。')
            actual = _read_bytes(self.path, MAX_JOURNAL_BYTES)
        except FileNotFoundError:
            actual = None
        if actual != expected:
            raise AutomationError('超频配置原落盘记录已改变，保留待核对证据。')

    def _history_paths(self):
        return frozenset(path for path in self.directory.parent.glob('*/' + JOURNAL) if path != self.path)

    def _require_history(self, expected):
        if self._history_paths() != expected:
            raise AutomationError('超频配置旧记录集合已改变，未发送输入。')

    def _history_allows_input(self, paths, *, check_source=None):
        # The native Runner mutex serializes configurations under this runs root.
        # Older journals carry no account binding, so ambiguous history vetoes input.
        try:
            for path in paths:
                if path.resolve(strict=True) != path or not path.is_file():
                    return False
                original = _read_bytes(path, MAX_JOURNAL_BYTES, check_source=check_source)
                data = strict_json(original.decode('utf-8'))
                if (not _resolved_configuration(data, path.parent, check_source=check_source)
                        or path.resolve(strict=True) != path
                        or _read_bytes(path, MAX_JOURNAL_BYTES, check_source=check_source) != original):
                    return False
        except (OSError, ValueError, AutomationError):
            return False
        return True

    def _current(self, scene=None):
        self.c.checkpoint()
        self._require_current(scene)

    def _require_current(self, scene=None):
        if self.c.runner.stop_requested:
            raise Stopped('超频配置已停止，原记录保留。')
        if self.c.runner.input_epoch != self.epoch:
            raise InputInterrupted('超频配置输入代次改变，原记录保留。')
        if scene is not None:
            self.guard._require_current_scene(scene, handoff_observation=self.handoff)
            if scene.geometry is None or scene.geometry != self.geometry:
                raise AutomationError('超频配置的窗口来源或位置已变化。')

    def _same_account(self, scene):
        try:
            collected = account_key(scene, self.confidence)
            if self.account is not None and collected != self.account:
                raise AutomationError('超频配置期间账号改变，原记录保留。')
            key = account_key(scene, max(.85, self.confidence))
        except AccountNotObserved:
            return False
        if key != collected:
            raise AutomationError('超频配置账号读数发生冲突。')
        self.account = key
        return True

    def _observe(self, scene):
        if self.preparation is not None:
            return read_preparation(scene, self.confidence)
        if self.step is _START_A0:
            return read_overclock_start(scene, self.confidence)
        return read_overclock(scene, self.confidence, require_a0_details=self.step is _OPEN_A0)

    def _target(self, scene):
        if self.preparation is not None:
            if not self.preparation.matches(self._observe(scene)):
                raise AutomationError('当前备战页面与上一阶段的双帧回执不一致。')
            return preparation_target(scene, self.step.action, self.confidence)
        return _target(scene, self.confidence, self.step)

    def _capture(self):
        try:
            scene = self.c.snapshot()
        except EmptyCapture:
            self._current()
            return None
        if self.geometry is None:
            self.geometry = scene.geometry
        self._current(scene)
        return _Frame(scene, scene.captured_at, self._observe(scene),
                      self._same_account(scene), _pixels(scene.image, self.geometry),
                      self.c.capture_occlusion_count)

    def _require_frame(self, frame, *, current=True):
        scene = frame.scene
        self._require_current(scene if current else None)
        if (scene.captured_at != frame.captured_at or not 0 <= time.monotonic() - frame.captured_at <= MAX_FRAME_AGE
                or scene.geometry != self.geometry or frame.occlusions != self.c.capture_occlusion_count):
            raise AutomationError('超频配置证据的时间、窗口或遮挡状态已改变。')

    def _check_frame(self, frame, *, current=True):
        scene = frame.scene
        self._require_frame(frame, current=current)
        if (not self._same_account(scene) or self._observe(scene) != frame.observation
                or _pixels(scene.image, self.geometry) != frame.pixels):
            raise AutomationError('超频配置证据的账号、页面或像素已改变。')
        self._require_frame(frame, current=current)

    def _evidence(self, frame, label):
        self._check_frame(frame)
        path = self.c.evidence(frame.scene, 'currency_overclock_' + label)
        path, raw = _evidence_bytes(path, self.directory)
        if _png_pixels(raw, self.geometry) != frame.pixels:
            raise AutomationError('超频配置落盘 PNG 与原画面像素不同。')
        self._check_frame(frame)
        return _Evidence(str(path), hashlib.sha256(raw).hexdigest(), frame.captured_at, frame.observation.state)

    def _check_saved(self, proof):
        _check_evidence(proof, self.directory)

    def authorize(self, scene, target, *, consume=False, read_sources=None):
        pending = self.pending
        if pending is None or scene is not pending.frame.scene or target != pending.target:
            raise AutomationError('超频配置缺少本次未使用的待核对意图。')
        self._require_current(scene)
        self._require_history(pending.history)
        revisions = {}

        def hold_source(path):
            if path not in revisions:
                _require_stable_source(path, revisions)
                read_sources.enter_context(hold_read_sources((path,)))
            _require_stable_source(path, revisions)

        if consume:
            if read_sources is None:
                raise AutomationError('超频配置原生发送缺少共享读保护。')
            for path in (self.path, Path(pending.proof.screenshot)):
                hold_source(path)
            if self.step is not _SELECT:
                hold_source(Path(self.client['source']))
        check_source = hold_source if consume else None
        if self.preparation is not None:
            self.preparation.require_no_temporary()
            self.preparation.require_sources(check_source)
            if consume:
                self.preparation.require_new_proofs((pending.proof,), revisions)
        elif self.session is not None:
            self.session.require_history(check_source)
        if self.preparation is None and not self._history_allows_input(pending.history, check_source=check_source):
            raise AutomationError('旧超频配置未核实，禁止再次发送。')
        self._check_saved(pending.proof)
        self._check_journal(pending.journal)
        if consume:
            frozen_image = _freeze_scene_pixels(scene, self.geometry)
            checked_tokens = tuple(scene.tokens)
        self._check_frame(pending.frame)
        if self._target(scene) != target:
            raise AutomationError('超频配置的当前页面目标已改变。')
        if consume:
            self._require_client()
            require_unchanged_history = _hold_history_names(self.directory.parent, read_sources)
            for path in revisions:
                _require_stable_source(path, revisions)
            self._require_history(pending.history)
            if self.session is not None or self.preparation is not None:
                live_executable = Path(self.c.window.current_executable()).resolve(strict=True)
                if live_executable != Path(self.client['executable']):
                    raise AutomationError('超频开局的当前窗口安装来源已改变。')
            self.c.window.guard(self.geometry)
            if self.preparation is not None:
                self.preparation.require_no_temporary()
            require_unchanged_history()
            self._require_client_window()
            self._require_window_key()
            self.c.window.guard(self.geometry)
            if self.c.window.emergency_pressed():
                raise Stopped('F10 紧急停止。')
            _require_frozen_scene(scene, frozen_image, checked_tokens, self.geometry)
        self._require_frame(pending.frame)
        if time.monotonic() >= pending.deadline:
            raise AutomationError('超频配置的输入前观察已超时。')
        if consume:
            self.pending = None

    def _initial(self, deadline):
        last = None
        stop_states = (A0_VETO_STATES if self.step is not _SELECT
                       else ('blocked', 'other_page', 'rank_unsupported'))
        if self.step is _START_A0:
            stop_states = (*stop_states, START_FEEDBACK, 'boss_difficulty_conflicting')
        if self.preparation is not None:
            stop_states = ('blocked', 'conflicting', 'other_page')
        if self.handoff:
            stop_states = (*stop_states, *PREPARATION_PHASES[:-1])
        for attempt in range(3):
            if time.monotonic() >= deadline:
                break
            if attempt:
                self.c.sleep(.3)
            frame = self._capture()
            if frame is not None:
                last = frame
                if frame.observation.state in stop_states:
                    break
                if frame.account_observed and frame.observation.state in self.start_states:
                    break
        return last

    def _verify(self, state, deadline, latest, first=None, *, before_input=None):
        last_observation = None
        for _ in range(30):
            if time.monotonic() >= deadline:
                break
            self.c.sleep(.3)
            frame = self._capture()
            if frame is None:
                latest = max(latest, time.monotonic())
                first = None
                continue
            last_observation = frame.observation
            increasing = frame.captured_at > latest
            latest = max(latest, frame.captured_at)
            if increasing and self.preparation is not None and last_observation.state in (
                    'blocked', 'conflicting', 'other_page'):
                return self._partial(last_observation.state, last_observation)
            if increasing and self.handoff and last_observation.state in PREPARATION_PHASES[:-1]:
                return self._partial('source_receipt_mismatch', last_observation)
            if increasing and self.step is not _SELECT and (
                    last_observation.state in A0_VETO_STATES
                    or last_observation.state == 'boss_difficulty_conflicting'):
                return self._partial(last_observation.state, last_observation)
            if not increasing or not frame.account_observed or frame.observation.state != state:
                first = None
                continue
            if self.preparation is not None:
                try:
                    if self.step is None:
                        if not self.preparation.matches(frame.observation):
                            raise AutomationError('当前备战与原回执不一致。')
                    else:
                        self.preparation.require_feedback(asdict(frame.observation))
                except AutomationError:
                    return self._partial('feedback_conflicting', frame.observation)
            if (first is None or frame.occlusions != first[0].occlusions
                    or time.monotonic() - first[0].captured_at > MAX_FRAME_AGE
                    or self.preparation is not None and frame.observation != first[0].observation):
                first = frame, self._evidence(frame, 'feedback_first')
                continue

            original, before = first
            after = self._evidence(frame, 'feedback_second')
            proofs = (before, after) if before_input is None else (before_input, before, after)
            if len({proof.screenshot for proof in proofs}) != len(proofs):
                raise AutomationError('超频配置需要各自独立的截图证据。')
            data = dict(self.data, status='verified', mode_verified=True,
                        difficulty_verified=state in ('a0_observed', START_FEEDBACK),
                        observation=asdict(frame.observation), feedback=[asdict(before), asdict(after)])
            if self.session is not None:
                data['match_started'] = True
                factions = preview_factions(frame.scene, self.confidence)
                if factions is not None and factions == preview_factions(original.scene, self.confidence):
                    data['preview_factions'] = factions
            if self.preparation is not None:
                data.update(difficulty_verified=True, phase=state,
                            first_preparation_verified=state == PREPARATION_PHASES[-1])
            if data['actions']:
                data['actions'] = [dict(data['actions'][0], status='verified')]

            def check_sources():
                self._current(frame.scene)
                self._require_client()
                self.c.window.guard(frame.scene.geometry)
                self._require_client_window()
                for proof in proofs:
                    self._check_saved(proof)

            def check_frames():
                self._check_frame(original, current=False)
                self._check_frame(frame)
                factions = data.get('preview_factions')
                if factions is not None and any(
                        preview_factions(item.scene, self.confidence) != factions for item in (original, frame)):
                    raise AutomationError('超频开局的首领预览阵营已改变。')
                if time.monotonic() >= deadline or time.monotonic() - original.captured_at > MAX_FRAME_AGE:
                    raise AutomationError('超频配置双帧回执已过期或原证据改变。')

            sources = ()
            if self.step is not _SELECT:
                sources = (Path(self.client['source']), *(Path(proof.screenshot) for proof in proofs))
            if self.preparation is not None and self.step is None:
                def verify_terminal():
                    self.preparation.require_no_temporary()
                    self._check_journal(self.saved_journal)
                    check_frames()
                    check_sources()

                with self._publication_scope((self.path, *sources), verify_terminal, proofs):
                    self._require_client_window()
                    self._require_window_key()
                    self.c.window.guard(self.geometry)
                    if self.c.window.emergency_pressed():
                        raise Stopped('F10 紧急停止。')
                    self._require_frame(original, current=False)
                    self._require_frame(frame)
                    if time.monotonic() >= deadline:
                        raise AutomationError('超频配置双帧回执已过期。')
                    if self.handoff:
                        data.update(handoff_verified=True, start_sha256=self.preparation.start_sha256,
                                    preparation_sha256=hashlib.sha256(self.saved_journal).hexdigest())
                    self._persist(data)
            else:
                self._persist(data, check_sources=check_sources, check_frames=check_frames,
                              read_sources=sources, proofs=proofs)
            if self.handoff:
                return TaskResult(TASK, 'partial', '已复核原局 1-1 首备战。阵容和掉落待核对，停在当前节点。')
            if self.preparation is not None:
                detail = ('已核实首个清洁备战 1-1。' if data['first_preparation_verified']
                          else '已核实本次超频 A0 备战步骤。')
                return TaskResult(TASK, 'ok', detail)
            if self.session is not None:
                return TaskResult(TASK, 'ok', '已核实超频 A0 开局与两张首领预览，当前停在预览页。')
            return TaskResult(TASK, 'ok', '已核实超频 A0 黑铁与敌人难度 1。' if data['difficulty_verified']
                              else '已核实超频模式选中。档位可在已打开的难度页核对。')
        return self._partial('feedback_unverified', last_observation)

    def _partial(self, reason, observation):
        actions = self.data['actions']
        scene = self.c.last_scene
        screenshot = (str(self.c.evidence(scene, 'currency_overclock_unverified'))
                      if scene is not None and scene.image is not None else None)
        self._persist(dict(self.data, status='partial', reason=reason, diagnostic_screenshot=screenshot,
                           actions=[dict(actions[0], status='unknown')] if actions else [],
                           observation=asdict(observation) if observation is not None else self.data['observation']))
        detail = ('超频 A0 备战待核对，原因见本次报告。' if self.preparation is not None
                  else '超频配置未取得可用的双帧核验，原因见本次报告。')
        return TaskResult(TASK, 'partial', detail)

    def run(self):
        self._require_client()
        if self.client is not None:
            self.data['client_version'] = self.client['full_version']
        self._persist(self.data)
        deadline = time.monotonic() + OBSERVE_SECONDS
        first = self._initial(deadline)
        if first is None:
            return self._partial('no_frame', None)
        state = first.observation.state
        if state not in self.start_states or not first.account_observed:
            return self._partial(state if state not in self.start_states else 'account_unverified', first.observation)
        if self.preparation is not None and not self.preparation.matches(first.observation):
            return self._partial('source_receipt_mismatch', first.observation)
        if self.preparation is not None and first.captured_at <= self.preparation.last_capture:
            return self._partial('source_not_new', first.observation)
        if time.monotonic() >= deadline:
            return self._partial('feedback_unverified', first.observation)
        if state in self.ready_states:
            return self._verify(state, deadline, first.captured_at, (first, self._evidence(first, 'feedback_first')))
        try:
            history = self._history_paths()
        except OSError:
            return self._partial('previous_selection_unresolved', first.observation)
        if self.preparation is None and not self._history_allows_input(history):
            return self._partial('previous_selection_unresolved', first.observation)

        try:
            target = self._target(first.scene)
        except AutomationError:
            if self.preparation is None:
                raise
            return self._partial('target_unverified', first.observation)
        before_label = ('before_preparation_step' if self.preparation is not None else
                        'before_start' if self.step is _START_A0 else
                        'before_open_difficulty' if self.step is _OPEN_A0 else 'before_select')
        before = self._evidence(first, before_label)
        action = dict(action=self.step.action, status='pending', input_epoch=self.epoch,
                      target=list(target.box), before=asdict(before))
        observation = asdict(first.observation)
        options = {}
        if self.preparation is not None:
            action['before_observation'] = observation
            options = dict(read_sources=(Path(before.screenshot),), proofs=(before,),
                           check_sources=lambda: self._check_saved(before))
        payload = self._persist(dict(self.data, status='pending', actions=[action], observation=observation),
                                **options)
        self.pending = _Pending(first, target, before, payload, deadline, history)
        self.c.currency_overclock_input(first.scene, target)
        if self.pending is not None:
            raise AutomationError('超频配置未经过本次输入门禁。')
        sent_after = time.monotonic()
        return self._verify(self.step.after, sent_after + OBSERVE_SECONDS, sent_after, before_input=before)


def configure_overclock(context):
    flow = _Configuration(context)
    context.report.safe_next = ('请核对当前超频难度页与原页面切换记录。'
                                if flow.step is _OPEN_A0 else '只核对超频模式与可见 A0 档位。对局操作使用原有独立入口。')
    return _run_configuration(context, flow)


def start_overclock(context):
    flow = _Configuration(context, start=True)
    context.report.safe_next = '请核对首领预览与原开局记录。待核对的开局保留在本地。'
    return _run_configuration(context, flow)


def prepare_overclock(context):
    flow = _Configuration(context, prepare=True)
    context.report.safe_next = '核对本次阶段回执。只有原局已核实的步骤可以接续，待核对输入保留原件。'
    return _run_configuration(context, flow)


def observe_legacy_handoff(context):
    flow = _Configuration(context, prepare=True)
    context.report.currency_wars = flow.data
    context.report.safe_next = '保留本次同节点证据，阵容、掉落及首节点出战继续待核对。'
    return _run_configuration(context, flow)


def _run_configuration(context, flow):
    context._currency_overclock_configuration = flow
    try:
        result = flow.run()
        context.runner.emit(dict(type=TASK, data=context.report.currency_wars))
        return result
    finally:
        context._currency_overclock_configuration = None
