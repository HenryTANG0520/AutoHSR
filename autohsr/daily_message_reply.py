"""Evidence for one explicitly requested reply in the calibrated SMS branch."""
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from hashlib import sha256
import time
import unicodedata

import cv2
import numpy as np

from .currency_wars_prepare import trusted
from .daily_event_observe import read_event_installation
from .daily_message_observe import _message_panel_frame
from .daily_message_state import _reply_options, _selected_row, read_reply_target_boxes
from .daily_message_reply_store import ReplyStore
from .daily_observe import MESSAGE_REPLY_OPERATION as OPERATION
from .models import AutomationError, InputInterrupted, ROI, Stopped, Token
from .storage import hold_read_sources
from .workflow_navigation import _seal
from .workflow_screen import _CurrentFrames, _MAX_AGE


REPLY_NODE = '珠珠鱼照片'
REPLY_CHOICE = '夸珠珠鱼可爱'
P179_SELECTION = ('工作与休假', '提议休假出游')
_VERSION = '4.6.0'
_SECTION = 2024900
_ITEM = 202490003
_P179_ITEM = 202500019
REPLY_SELECTIONS = {(REPLY_NODE, REPLY_CHOICE): _ITEM, P179_SELECTION: _P179_ITEM}
_FLOOR = .65
_TEXT_FLOOR = .90
_STARTER = '39cf455816495cd22f41fdc03d73ae18d97d16543eb7ddb010ef0d29a12dcbb5'
_CHOICES = (
    (202490003, 'e041baf6f693b3d621ae9c4caa8aa3d7c3e25174fb6fb1c76300bae0e4c286ff'),
    (202490005, '3a77aa304808105016490449f159ef4689e8144999d1c15ab739dd0aba72c9f3'),
    (202490007, '972a1cce86695e800bed5c8f727b3c21c3b37b0b93830dfedfe114bb52edb95f'),
)
_OUTGOING = '156c4280e9c0346232abcc2da0cbed9b0517b9f75b3385bc1f18ffff4143283e'
_HEADER = (525 / 1280, 120 / 720, 625 / 1280, 153 / 720)
_STARTER_AREA = (620 / 1280, 244 / 720, 925 / 1280, 369 / 720)
_VISIBLE_CHAT = (189 / 480, 57 / 270, 410 / 480, 224 / 270)
_OUTGOING_AREA = (807 / 1280, 553 / 720, 958 / 1280, 588 / 720)
_P178_SURFACE = ((315, 206, 352, 214), (305, 210, 309, 218), (354, 210, 358, 218), (368, 210, 373, 218))


@dataclass(frozen=True)
class _ReplyProfile:
    section: int
    item: int
    starter: str
    choices: tuple[tuple[int, str], ...]
    outgoing: str
    starter_area: ROI
    outgoing_area: ROI
    surface: tuple[tuple[int, int, int, int], ...]
    first_option_crop: ROI | None = None
    first_option_plain: str = ''


_P179 = _ReplyProfile(
    section=2025000, item=_P179_ITEM,
    starter='5c5e13ecd9f22aa031f1f6f3bce0f4495e27853392490eb06bbdae3013a33a03',
    choices=(
        (202500014, '88612719b5e3ef4267f32d511740e65f01e0e7f5d32705717d80957202aa8241'),
        (202500016, 'ab5b71a3a0726576c65af476129ce6e3f4ca21cdb02546cce75cb20aebb06cf1'),
        (_P179_ITEM, '2016514ff6d7ed6e4770e6cfa052b8935dfad99fd44f730e31809832516af05b'),
    ),
    outgoing='f7d10cbb91966a7dd6a59a2578a4243802b9f0c6833f4dbee1c5634832659c06',
    starter_area=(615 / 1280, 386 / 720, 910 / 1280, 427 / 720),
    outgoing_area=(615 / 1280, 478 / 720, 954 / 1280, 515 / 720),
    surface=((315, 182, 352, 191), (233, 185, 237, 191), (354, 185, 358, 191), (368, 185, 373, 191)),
    first_option_crop=(535 / 1280, 464 / 720, 1068 / 1280, 504 / 720),
    first_option_plain='6e921f632e15fa73ceb3b654ee94c728320fc3565aad7b83f8d41850b2028697',
)


def _profile(item_id):
    if type(item_id) is int:
        if item_id == _ITEM:
            return _ReplyProfile(_SECTION, _ITEM, _STARTER, _CHOICES, _OUTGOING,
                                 _STARTER_AREA, _OUTGOING_AREA, _P178_SURFACE)
        if item_id == _P179_ITEM:
            return _P179
    return None


@dataclass(frozen=True)
class _Panel:
    image: np.ndarray
    gray: np.ndarray
    tokens: tuple[Token, ...]
    conversation: tuple[str, tuple[int, int]]


def _normalized(text: str) -> str:
    return ''.join(unicodedata.normalize('NFKC', text).split())


def _text_digest(text: str) -> str:
    normalized = _normalized(text)
    return sha256(normalized.encode('utf-8')).hexdigest() if normalized else ''


def _plain_digest(text: str) -> str:
    plain = ''.join(character for character in _normalized(text) if not unicodedata.category(character).startswith('P'))
    return sha256(plain.encode('utf-8')).hexdigest()


def _one_field(tokens, area: ROI, *, vertical_padding=0.) -> Token | None:
    candidates = [token for token in tokens if token.within(area)]
    if len(candidates) != 1:
        return None
    token = candidates[0]
    x1, y1, x2, y2 = token.box
    if (token.score >= _TEXT_FLOOR and area[0] <= x1 < x2 <= area[2]
            and area[1] - vertical_padding <= y1 < y2 <= area[3] + vertical_padding):
        return token
    return None


def _seen(tokens, area, digest):
    return [token for token in tokens if token.within(area) and _text_digest(token.text) == digest]


def _selected_panel(scene) -> _Panel | None:
    image = _message_panel_frame(scene)
    if image is None:
        return None
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    row = _selected_row(gray)
    if row is None:
        return None
    tokens = tuple(trusted(scene, _FLOOR).tokens)
    top = row[0]
    left = _one_field(tokens, (.209, (top + 1) / 270, .26, (top + 13) / 270))
    right = _one_field(tokens, _HEADER)
    if left is None or right is None:
        return None
    header = _text_digest(left.text)
    if not header or header != _text_digest(right.text):
        return None
    return _Panel(image, gray, tokens, (header, row))


def _has_starter(panel, profile):
    matches = _seen(panel.tokens, _VISIBLE_CHAT, profile.starter)
    return len(matches) == 1 and matches[0].score >= _TEXT_FLOOR and matches[0].within(profile.starter_area)


def _crop(image, box):
    x1, y1, x2, y2 = box
    return image[y1:y2, x1:x2]


def _outgoing_surface(panel, areas=_P178_SURFACE) -> bool:
    # Distinguish the warm rounded bubble from the full-width gray reply strips
    # and from the right pane's ordinary background using the rim and side margins.
    rim, left, right, pane = areas
    blue, green, red = _crop(panel.image, rim).astype(np.int16).transpose(2, 0, 1)
    warm = (red >= 220) & (red - blue >= 7) & (red - green >= 7)
    inner = min(np.median(_crop(panel.gray, left)), np.median(_crop(panel.gray, right)))
    outside = np.median(_crop(panel.gray, pane))
    return bool(np.max(np.mean(warm, axis=1)) >= .70 and inner >= 220 and inner - outside >= 12)


def _confirm_first_option(profile, label, digest, image, read):
    area = profile.first_option_crop
    if area is None or not callable(read) or _plain_digest(label.text) != profile.first_option_plain:
        return False
    height, width = image.shape[:2]
    bounds = tuple(round(value * size) for value, size in zip(area, (width, height) * 2))
    sample = cv2.resize(_crop(image, bounds), None, fx=2., fy=2., interpolation=cv2.INTER_CUBIC)
    local = _one_field(trusted(read(sample), _FLOOR).tokens, (.25, .10, .75, .90))
    if local is None or _text_digest(local.text) != digest:
        return False
    x, y = local.center
    projected = (area[0] + x * (area[2] - area[0]), area[1] + y * (area[3] - area[1]))
    return all(abs(a - b) <= .006 for a, b in zip(label.center, projected))


def _reply_target(panel, profile, image, read) -> Token | None:
    if (not _has_starter(panel, profile) or _seen(panel.tokens, _VISIBLE_CHAT, profile.outgoing)
            or _outgoing_surface(panel, profile.surface)):
        return None
    boxes = read_reply_target_boxes(panel.image)
    if len(boxes) != len(profile.choices):
        return None
    labels = {}
    for index, (box, (item, digest)) in enumerate(zip(boxes, profile.choices)):
        label = _one_field(panel.tokens, box, vertical_padding=.012)
        if label is None or (_text_digest(label.text) != digest
                             and (index != 0 or not _confirm_first_option(profile, label, digest, image, read))):
            return None
        labels[item] = label
    return labels.get(profile.item)


def _reply_feedback(panel, profile) -> Token | None:
    if (not _has_starter(panel, profile) or _reply_options(panel.gray)[0] != 'not_visible'
            or not _outgoing_surface(panel, profile.surface)):
        return None
    token = _one_field(panel.tokens, profile.outgoing_area)
    matches = _seen(panel.tokens, _VISIBLE_CHAT, profile.outgoing)
    return token if token is not None and matches == [token] else None


def _same_box(first, second):
    return all(abs(a - b) <= .004 for a, b in zip(first.box, second.box))


def reply_once(context, store: ReplyStore, *, item_id: int, submit, record=None):
    """Run one calibrated reply using a dedicated submit adapter and stable ledger.

    The adapter accepts the selected scene, a normalized point and a before_submit
    hook. It must call the hook before recording its single accepted click.
    """
    profile = _profile(item_id)
    if profile is None:
        raise AutomationError('请明确选择当前已校准的短信回复条目。')
    floor = getattr(getattr(context, 'vision', None), 'confidence', None)
    if (context.report.operation != OPERATION or getattr(context.runner, '_foreground_only', False) is not True
            or type(floor) not in (int, float) or not 0 <= floor <= _FLOOR):
        raise AutomationError('短信单次回复需要独立前台候选和低阈值采集。')
    current = _CurrentFrames(context)
    installation = read_event_installation(current.window)
    if installation.version != _VERSION:
        raise AutomationError('当前客户端尚未校准单次短信回复。')
    if record is not None:
        record['client_version'] = installation.version

    def guard(pair):
        if read_event_installation(current.window) != installation:
            raise AutomationError('短信回复的客户端安装来源已改变。')
        current.guard()
        if context.runner.stop_requested or current.window.emergency_pressed():
            raise Stopped('短信回复已停止。')
        if context.runner.input_epoch != current.epoch:
            raise InputInterrupted('短信回复的输入代次已变化。')
        latest_frame = pair[-1]
        if (context.last_scene is not latest_frame.scene or context.capture_sequence != latest_frame.sequence
                or context.scene_epoch != current.epoch or not 0 <= time.monotonic() - pair[0].captured_at <= _MAX_AGE):
            raise AutomationError('短信回复的连续双帧已变化或过期。')

    first = current.capture()
    context.sleep(.30)
    last = current.capture()
    before, latest = (_selected_panel(frame.scene) for frame in (first, last))
    if before is None or latest is None or before.conversation != latest.conversation:
        raise AutomationError('两帧未核实同一选中短信会话。')
    conversation = latest.conversation
    current.verify_pair(first, last)
    if not _has_starter(before, profile) or not _has_starter(latest, profile):
        raise AutomationError('当前选中会话缺少所选短信节点的前置消息。')
    existing = store.status(last.account, profile.section)
    if record is not None:
        record['ledger_status'] = existing
    if existing != 'none':
        raise AutomationError('本账号的短信段落已有回复记录，未重复提交。')
    read = getattr(context.vision, 'read', None)
    local_reads = {}

    def target_on(panel, frame):
        def read_once(crop):
            # The later checks reverify the full frame digest before reusing
            # this bounded OCR result. Each native frame has its own reading.
            if frame.sequence not in local_reads:
                local_reads[frame.sequence] = read(crop)
            return local_reads[frame.sequence]

        return _reply_target(panel, profile, frame.image, read_once if callable(read) else None)

    first_target, target = (target_on(panel, frame) for panel, frame in ((before, first), (latest, last)))
    if first_target is None or target is None or not _same_box(first_target, target):
        raise AutomationError('两帧未核实明确选择的同位回复条。')
    reservation = None
    submitting = False

    def verify_target():
        current.verify_pair(first, last)
        for frame, expected in zip((first, last), (first_target, target)):
            panel = _selected_panel(frame.scene)
            if panel is None or panel.conversation != conversation or target_on(panel, frame) != expected:
                raise AutomationError('提交前短信会话或所选回复已改变。')
        guard((first, last))

    def before_submit():
        nonlocal reservation
        if not submitting or reservation is not None:
            raise AutomationError('短信回复的一次性提交已登记。')
        verify_target()
        reservation = store.reserve(last.account, profile.section)
        if record is not None:
            record['ledger_status'] = 'pending'
        pending_sources.enter_context(reservation.hold_pending())
        verify_target()

    with _seal((first, last)), hold_read_sources((installation.source,)), ExitStack() as pending_sources:
        verify_target()
        submitting = True
        try:
            submit(last.scene, target.center, before_submit=before_submit)
        finally:
            submitting = False
    if reservation is None:
        raise AutomationError('缺少本次短信点击的提交回执。')
    sent_at = time.monotonic()

    previous = None
    for _ in range(6):
        context.sleep(.30)
        frame = current.capture()
        if frame.account != last.account or frame.captured_at <= sent_at:
            raise AutomationError('短信回复后的账号或画面来源已改变，保留待核对。')
        panel = _selected_panel(frame.scene)
        if panel is not None and panel.conversation != conversation:
            raise AutomationError('短信回复后选中会话已改变，保留待核对。')
        feedback = None if panel is None else _reply_feedback(panel, profile)
        if feedback is None:
            previous = None
            continue
        if previous is not None and _same_box(previous[1], feedback):
            pair = (previous[0], frame)

            def verify_feedback():
                current.verify_pair(*pair)
                for capture, expected in zip(pair, (previous[1], feedback)):
                    after = _selected_panel(capture.scene)
                    if after is None or after.conversation != conversation or _reply_feedback(after, profile) != expected:
                        raise AutomationError('发出反馈已改变，保留短信待核对。')
                guard(pair)

            with _seal(pair), hold_read_sources((installation.source,)):
                reservation.confirm(before_replace=verify_feedback)

            @contextmanager
            def feedback_scope():
                with _seal(pair), hold_read_sources((installation.source,)):
                    verify_feedback()
                    yield

            if record is not None:
                record.update(ledger_status='confirmed', feedback_status='confirmed')
            return feedback_scope, reservation.hold_confirmed
        previous = frame, feedback
    raise AutomationError('缺少同一短信会话的连续发出反馈，保留待核对。')
