"""Current-frame evidence and an append-only intent for one selected Odyssey day."""
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from threading import Lock
import time

import cv2
import numpy as np

from .challenge_pages import _clean, _inside, _overlaps
from .currency_wars_identity import UID_COUNTEREVIDENCE, checked_account_key, installed_client
from .daily_observe import EVENT_CLAIM_OPERATION as OPERATION
from .daily_event_pages import OdysseyObservation, _CENTERS, _VERSION, _label, _pale_fraction, read_gift_of_odyssey
from .models import AutomationError, Stopped, Token, normalize
from .storage import file_revision, hold_read_sources
from .vision import helper_overlay
from .warp_records import WarpError
from .warp_service import publish_new


ACTIVITY = 'gift_of_odyssey_4_6'
ITEM = '星轨专票'
_QUANTITY_BY_DAY = {3: 2, 4: 1, 5: 1, 6: 1, 7: 3}
_AGE = 8
_HEADER = (.461, .132, .539, .199)
_ITEM = (.465, .556, .535, .600)
_CLOSE = (.438, .708, .563, .757)
_NUMBER = (.489, .537, .511, .563)
_NUMBER_PATTERN = r'[1-9][0-9]?'
_ITEM_DETAIL = (.472, .560, .529, .592)
_CLOSE_SUFFIX = (.500, .714, .552, .752)
_CLOSE_WORDS = ('点击空白处关闭', '点空白处关闭')
_CLOSE_COMPRESSED = '点出登白处关闭'
_MARK_Y = (.475, .475, .475, .701, .701, .701, .591)


def _supported_day(day):
    return type(day) is int and day in _QUANTITY_BY_DAY


def read_day_button(scene, *, day, client_version, confidence=.65):
    """Return the read-only label of the separately chosen, enabled day."""
    if not _supported_day(day):
        return None
    page = read_gift_of_odyssey(scene, client_version=client_version, confidence=confidence)
    if page is None or day not in page.claimable_days:
        return None
    x, y = _CENTERS[day - 1]
    clean = _clean(scene, .65, blockers=())
    if clean is None or _card_check_mark(clean.image, day):
        return None
    return _label(clean, ('领取', '已领取'), (x - .044, y - .022, x + .044, y + .022),
                  max(.85, confidence))


def _crop(image, roi):
    height, width = image.shape[:2]
    left, top, right, bottom = (round(value * size) for value, size in zip(roi, (width, height, width, height)))
    return image[top:bottom, left:right]


def _contrast(image):
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return cv2.cvtColor(cv2.normalize(gray, None, 0, 255, cv2.NORM_MINMAX), cv2.COLOR_GRAY2BGR)


def _exact_text(reader, image, size, text, confidence):
    token = reader(cv2.resize(image, size, interpolation=cv2.INTER_CUBIC), text)
    return (isinstance(token, Token) and token.text == text and type(token.score) in (int, float)
            and max(.85, confidence) <= token.score <= 1)


def _card_check_mark(image, day):
    """Find the single pale check on the ticket, away from the button label."""
    x = _CENTERS[day - 1][0]
    y = _MARK_Y[day - 1]
    crop = cv2.resize(_crop(image, (x - .029, y - .031, x + .029, y + .031)), (36, 24),
                      interpolation=cv2.INTER_AREA)
    low = crop.min(axis=2)
    mask = ((low >= 165) & (crop.max(axis=2) - low <= 35)).astype(np.uint8)
    _, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    components = [(label, *stats[label]) for label in range(1, len(stats)) if stats[label, 4] >= 5]
    if len(components) != 1:
        return False
    label, left, top, width, height, area = components[0]
    if (not 9 <= left <= 16 or not 5 <= top <= 10 or not 7 <= width <= 12
            or not 6 <= height <= 10 or not 12 <= area <= .55 * width * height):
        return False
    mark = labels[top:top + height, left:left + width] == label
    lead = np.nonzero(mark[:, :2])[0]
    bend = np.nonzero(mark[:, 2:width // 2 + 1])[0]
    tail = np.nonzero(mark[:, -2:])[0]
    return (bool(len(bend)) and lead.max() < bend.max() == height - 1
            and tail.min() <= 1 and tail.max() < lead.min())


def _claim_page_states(scene, page, text_reader, confidence):
    if page is None:
        return page
    clean = _clean(scene, .65, blockers=())
    if clean is None:
        return None
    active, claimed = set(page.claimable_days), set(page.claimed_days)
    blocked = {day for day in active if _card_check_mark(clean.image, day)}
    active -= blocked
    for day in page.unknown_days:
        x, y = _CENTERS[day - 1]
        bounds = (x - .044, y - .022, x + .044, y + .022)
        labels = [token for token in clean.tokens if normalize(token.text) in ('领取', '已领取')
                  and _overlaps(token.box, bounds)]
        if len(labels) > 1 or any(not _inside(token.box, bounds) for token in labels):
            continue
        pale = _pale_fraction(clean.image, x, y, .039, .017)
        word = normalize(labels[0].text) if labels else None
        marked = _card_check_mark(clean.image, day)
        if pale <= .10 and word != '领取' and marked:
            claimed.add(day)
        elif not marked and pale >= .40 and word == '领取' and callable(text_reader):
            patch = _crop(clean.image, (x - .021, y - .021, x + .037, y + .021))
            if _exact_text(text_reader, _contrast(patch), (240, 72), '领取', confidence):
                active.add(day)
    unknown = (set(page.unknown_days) | blocked) - active - claimed
    return OdysseyObservation(tuple(sorted(active)), tuple(sorted(claimed)), tuple(sorted(unknown)))


def _single_ticket_tile(image):
    def colors(center):
        tile = _crop(image, (center - .017, .448, center + .017, .531)).astype(np.int16)
        blue, green, red = np.moveaxis(tile, 2, 0)
        warm = (red > 158) & (green > 120) & (red - blue > 24)
        pale = (red > 170) & (green > 135) & (blue > 90)
        return float(warm.mean()), float(pale.mean())

    return colors(.50)[0] >= .45 and all(colors(x)[1] <= .10 for x in (.36, .438, .562, .64))


def _popup_labels(scene, text_reader, confidence):
    if not _label(scene, ('获得物品',), _HEADER, max(.85, confidence)):
        return False
    item = _label(scene, (ITEM,), _ITEM, max(.80, confidence)) is not None
    prompt = _label(scene, (*_CLOSE_WORDS, _CLOSE_COMPRESSED), _CLOSE, .65)
    if prompt is None:
        return False
    word = normalize(prompt.text)
    close = word in _CLOSE_WORDS and prompt.score >= max(.75, confidence)
    if not callable(text_reader):
        return bool(item and close)
    if not item and _label(scene, (ITEM,), _ITEM, .65):
        item = _exact_text(text_reader, _crop(scene.image, _ITEM_DETAIL), (280, 72), ITEM, confidence)
    if word == _CLOSE_COMPRESSED and prompt.score >= max(.80, confidence):
        # The compressed fifth-day popup has a repeatable error in the left glyphs.
        # Only a separate exact read of the intact suffix supports observing that popup.
        suffix = _crop(scene.image, _CLOSE_SUFFIX)
        close = all(_exact_text(text_reader, view, (170, 68), '白处关闭', confidence)
                    for view in (suffix, _contrast(suffix)))
    return bool(item and close)


def read_ticket_popup(scene, *, quantity_reader, text_reader=None, confidence=.65):
    """Observe one item independently of its cause. A localized OCR reader checks the count."""
    if (not callable(quantity_reader) or type(confidence) not in (int, float)
            or not 0 <= confidence <= 1 or not isinstance(getattr(scene, 'tokens', None), (list, tuple))):
        return None
    clean = _clean(scene, .65, blockers=())
    if clean is None or helper_overlay(clean) or clean.has(
            ('确认支付', '确认购买', '切换账号', '重新连接', '加载中', '正在加载',
             '登录中', '账号登录', '退出登录', '列车补给', '网络连接失败', '连接中断'), exact=True):
        return None
    if not _single_ticket_tile(clean.image) or not _popup_labels(clean, text_reader, confidence):
        return None
    if any(token.within((.29, .561, .71, .605)) and not token.within(_ITEM)
           for token in clean.tokens):
        return None
    patch = cv2.resize(_crop(clean.image, _NUMBER), (84, 60), interpolation=cv2.INTER_CUBIC)
    readings = (quantity_reader(patch, _NUMBER_PATTERN), quantity_reader(_contrast(patch), _NUMBER_PATTERN))
    if any(not isinstance(token, Token) or type(token.text) is not str or type(token.score) not in (int, float)
           or not max(.85, confidence) <= token.score <= 1 or not re.fullmatch(_NUMBER_PATTERN, token.text)
           for token in readings):
        return None
    first, second = (int(token.text) for token in readings)
    if first != second or any(token.within(_NUMBER) and re.fullmatch(_NUMBER_PATTERN, normalize(token.text))
                              and int(normalize(token.text)) != first for token in clean.tokens):
        return None
    return first


def _digest(image):
    return sha256(np.ascontiguousarray(image)).digest()


@dataclass(frozen=True)
class _Scope:
    day: int
    executable: Path
    installation: tuple[str, str, tuple[int, int, int, int, int]]
    key: str
    epoch: int
    occlusions: int
    account: str
    geometry: object
    confidence: float


@dataclass(frozen=True)
class _Frame:
    context: object
    scene: object
    image: np.ndarray
    tokens: tuple
    uid_facts: tuple
    pixels: bytes
    window: object
    scope: _Scope
    sequence: int
    captured_at: float
    page: object
    button: Token | None
    tickets: int | None
    guard: object
    current: object


def _uid_facts(scene):
    return tuple(scene.field_reads.get(UID_COUNTEREVIDENCE, ()))


def _require_intact(frame, *, pixels=True):
    scene = frame.scene
    geometry = frame.scope.geometry
    if (scene.geometry != geometry or scene.image is not frame.image
            or frame.image.shape != (geometry.height, geometry.width, 3) or frame.image.dtype != np.uint8
            or scene.captured_at != frame.captured_at or tuple(scene.tokens) != frame.tokens
            or _uid_facts(scene) != frame.uid_facts or (pixels and _digest(frame.image) != frame.pixels)
            or (not pixels and frame.image.flags.writeable)):
        raise AutomationError('巡星之礼原帧或账号读数已变化。')


def bind_current_claim_frame(context, *, day, quantity_reader=None, text_reader=None):
    """Bind an already captured frame to an explicitly chosen day."""
    if not _supported_day(day):
        raise AutomationError('巡星之礼只核对明确选择的第三至第七日。')
    runner, window, scene = context.runner, context.window, context.last_scene
    if (context.report.operation != OPERATION or getattr(runner, '_foreground_only', False) is not True
            or scene is None):
        raise AutomationError('巡星之礼领取候选需要本次独立前台画面。')
    vision = getattr(context, 'vision', None)
    floor, confidence = getattr(vision, 'confidence', None), context.settings.ocr_confidence
    if (type(floor) not in (int, float) or not 0 <= floor <= .65
            or type(confidence) not in (int, float) or not 0 <= confidence <= 1):
        raise AutomationError('巡星之礼领取候选须保留账号与遮挡的采集反证。')
    epoch, sequence, occlusions = runner.input_epoch, context.capture_sequence, context.capture_occlusion_count
    stamp = scene.captured_at
    image, geometry = scene.image, scene.geometry
    if (_clean(scene, .65, blockers=()) is None or geometry is None or type(sequence) is not int or sequence <= 0
            or type(epoch) is not int or type(occlusions) is not int or context.scene_epoch != epoch
            or image.shape != (geometry.height, geometry.width, 3)):
        raise AutomationError('当前活动画面缺少有效的客户区和采集来源。')
    if runner.stop_requested or window.emergency_pressed():
        raise Stopped('巡星之礼领取候选已停止。')
    key = window.current_window_key()

    def require_running():
        if runner.stop_requested or window.emergency_pressed():
            raise Stopped('巡星之礼领取候选已停止。')

    def current():
        require_running()
        context.checkpoint()
        if not key or window.current_window_key() != key or window.guard(geometry) != geometry:
            raise AutomationError('巡星之礼当前画面的窗口待核实。')
        require_running()
        if (context.last_scene is not scene or context.capture_sequence != sequence
                or context.scene_epoch != epoch or runner.input_epoch != epoch
                or context.capture_occlusion_count != occlusions or context.report.operation != OPERATION
                or context.runner is not runner or context.window is not window
                or context.vision is not vision or vision.confidence != floor
                or context.settings.ocr_confidence != confidence
                or runner._foreground_only is not True or not 0 <= time.monotonic() - stamp <= _AGE):
            raise AutomationError('巡星之礼当前画面的采集来源或代次待核实。')

    current()
    executable = Path(window.current_executable()).resolve(strict=True)
    source = executable.with_name('config.ini')

    def installed():
        if source.resolve(strict=True) != source:
            raise AutomationError('巡星之礼当前客户端配置来源已变化。')
        client = installed_client(window.current_executable())
        if Path(client['executable']) != executable or Path(client['source']) != source:
            raise AutomationError('巡星之礼当前客户端来源已变化。')
        return client['full_version'], client['sha256'], file_revision(source)

    with hold_read_sources((source,)):
        installation = installed()
        if installation[0] != _VERSION:
            raise AutomationError('当前客户端没有巡星之礼领取候选证据。')
        tokens, uid_facts, pixels = tuple(scene.tokens), _uid_facts(scene), _digest(image)
        account = checked_account_key(scene, confidence)
        page = read_gift_of_odyssey(scene, client_version=_VERSION, confidence=confidence)
        page = _claim_page_states(scene, page, text_reader, confidence)
        button = read_day_button(scene, day=day, client_version=_VERSION, confidence=confidence)
        tickets = read_ticket_popup(scene, quantity_reader=quantity_reader, text_reader=text_reader,
                                    confidence=confidence)
        current()

    def guard():
        current()
        if installed() != installation:
            raise AutomationError('巡星之礼当前客户端版本或配置已变化。')
        current()

    scope = _Scope(day, executable, installation, key, epoch, occlusions, account, geometry, confidence)
    frame = _Frame(context, scene, image, tokens, uid_facts, pixels, window, scope,
                   sequence, stamp, page, button, tickets, guard, current)
    _require_intact(frame)
    return frame


def _pair(frames, *, origin=None):
    if not isinstance(frames, (tuple, list)) or len(frames) != 2 or any(not isinstance(frame, _Frame) for frame in frames):
        raise AutomationError('巡星之礼需要两份独立画面。')
    first, second = frames
    reference = first if origin is None else origin
    now = time.monotonic()
    if (first.scene is second.scene or np.may_share_memory(first.image, second.image)
            or first.sequence + 1 != second.sequence or not first.captured_at < second.captured_at
            or not now - _AGE <= first.captured_at < second.captured_at <= now):
        raise AutomationError('巡星之礼双帧时序或独立性待核实。')
    for frame in frames:
        if (frame.context is not reference.context or frame.window is not reference.window
                or frame.scope != reference.scope):
            raise AutomationError('巡星之礼窗口、账号或活动来源已变化。')
        _require_intact(frame)
    return first, second


def _days(frames, status):
    return set(getattr(frames[0].page, status)).intersection(getattr(frames[1].page, status))


def _raw(record):
    return json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True).encode('utf8')


def _require_fresh(frames, *, pixels=True):
    if not 0 <= time.monotonic() - frames[0].captured_at <= _AGE:
        raise AutomationError('巡星之礼原始画面已经过期。')
    for frame in frames:
        _require_intact(frame, pixels=pixels)


def _publish(path, raw, checkpoint, frames):
    def check():
        checkpoint()
        frames[-1].guard()
        _require_fresh(frames)
        return False

    source = frames[-1].scope.executable.with_name('config.ini')
    with hold_read_sources((source,)):
        try:
            publish_new(path, lambda stream: stream.write(raw), cancel=check, limit=4096)
        except WarpError:
            raise AutomationError('巡星之礼已有记录或写入未核实，保留原件且不重放。') from None
        with _hold_records(((path, raw),)):
            return file_revision(path)


def _require_records(rows):
    for path, raw in rows:
        if path.resolve(strict=True) != path:
            raise AutomationError('巡星之礼原意图或提交回执来源已变化。')
        with path.open('rb') as stream:
            if stream.read(4097) != raw:
                raise AutomationError('巡星之礼原意图或提交回执已变化。')


@contextmanager
def _hold_records(rows):
    with hold_read_sources(tuple(path for path, _ in rows)):
        _require_records(rows)
        yield


@contextmanager
def _hold_pixels(frames):
    images = tuple(frame.image for frame in frames if frame.image.flags.writeable)
    try:
        for image in images:
            image.setflags(write=False)
        yield
    finally:
        for image in images:
            image.setflags(write=True)


def _attempt_paths(path):
    return (path, path.with_suffix('.reserved.json'), path.with_suffix('.submitted.json'),
            path.with_suffix('.verified.json'))


def _selected_pair(before, day):
    frames = _pair(before)
    first, second = frames
    if (second.scope.day != day
            or any(frame.page is None or frame.button is None or frame.tickets is not None for frame in frames)
            or any(abs(a - b) > .006 for a, b in zip(first.button.box, second.button.box))):
        raise AutomationError('巡星之礼指定日卡的可领取按钮待核对。')
    return frames


class ClaimIntent:
    """A durable pending intent with one native submission boundary."""
    def __init__(self, path, raw, before, *, revision):
        self._path, self._raw, self._before = path, raw, before
        _, self._reserved_path, self._sent_path, self._verified_path = _attempt_paths(path)
        self._authorization = _raw(dict(schema=1, state='reserved', intent_sha256=sha256(raw).hexdigest(),
                                        sequence=before[-1].sequence))
        self._intent_revision = revision
        self._authorization_revision = None
        self._submit_lock = Lock()
        self._attempted = False
        self._sent = None

    def _require_original_records(self):
        if file_revision(self._path) != self._intent_revision:
            raise AutomationError('巡星之礼原意图文件已变化。')
        if (self._authorization_revision is not None
                and file_revision(self._reserved_path) != self._authorization_revision):
            raise AutomationError('巡星之礼原提交保留文件已变化。')

    def submit(self, context):
        """Consume this intent at the native click boundary for its bound Context."""
        from .windows import GameWindow

        origin = self._before[-1]
        window = origin.window
        if context is not origin.context:
            raise AutomationError('巡星之礼提交必须属于创建意图的运行。')

        def require_native_sender():
            if type(window) is not GameWindow or window.send != GameWindow.send.__get__(window, GameWindow):
                raise AutomationError('巡星之礼领取缺少本次原生点击来源。')

        require_native_sender()
        if not self._submit_lock.acquire(blocking=False):
            raise AutomationError('巡星之礼指定日已在提交，保留原意图。')
        try:
            if self._attempted or any(os.path.lexists(path) for path in
                                      (self._reserved_path, self._sent_path, self._verified_path)):
                raise AutomationError('巡星之礼指定日已有提交保留或回执。')
            before = _selected_pair(self._before, origin.scope.day)
            intent = (self._path, self._raw)
            authorization = (self._reserved_path, self._authorization)
            source = origin.scope.executable.with_name('config.ini')
            with hold_read_sources((source,)), _hold_records((intent,)), _hold_pixels(before):
                self._require_original_records()
                self._authorization_revision = _publish(self._reserved_path, self._authorization,
                                                        context.checkpoint, before)
                with _hold_records((authorization,)):
                    def before_submit():
                        if self._attempted:
                            raise AutomationError('巡星之礼提交授权已经消费。')
                        if any(os.path.lexists(path) for path in (self._sent_path, self._verified_path)):
                            raise AutomationError('巡星之礼指定日出现其它提交或已核实回执。')
                        _require_records((intent, authorization))
                        self._require_original_records()
                        for frame in _selected_pair(before, origin.scope.day):
                            confidence = frame.scope.confidence
                            if (checked_account_key(frame.scene, confidence) != frame.scope.account
                                    or read_day_button(frame.scene, day=frame.scope.day, client_version=_VERSION,
                                                       confidence=confidence) is not frame.button):
                                raise AutomationError('巡星之礼提交前的账号或指定日按钮已变化。')
                        origin.guard()
                        _require_fresh(before)
                        origin.current()
                        _require_fresh(before, pixels=False)
                        require_native_sender()
                        self._attempted = True

                    GameWindow.click(window, *origin.button.center, origin.scope.geometry,
                                     before_submit=before_submit)
                    if not self._attempted:
                        raise AutomationError('巡星之礼原生提交边界待核对。')
                    sent = _raw(dict(schema=1, state='submitted', intent_sha256=sha256(self._raw).hexdigest(),
                                     authorization_sha256=sha256(self._authorization).hexdigest(),
                                     sequence=origin.sequence))
                    _publish(self._sent_path, sent, context.checkpoint, before)
                    self._sent = sent
        finally:
            if self._attempted and context.last_scene is origin.scene:
                context.last_scene = context._scroll_anchor = None
            self._submit_lock.release()

    def verify(self, popup, after, *, checkpoint):
        """Publish a verified chain only after the exact receipt and same card both agree."""
        origin = self._before[-1]
        day = origin.scope.day
        quantity = _QUANTITY_BY_DAY[day]
        if self._sent is None:
            raise AutomationError('巡星之礼提交仍待核对，保留原意图。')
        before = _pair(self._before)
        reward = _pair(popup, origin=origin)
        returned = _pair(after, origin=origin)
        if (origin.sequence + 1 != reward[0].sequence or reward[-1].sequence + 1 != returned[0].sequence
                or not origin.captured_at < reward[0].captured_at < reward[1].captured_at < returned[0].captured_at
                or any(frame.tickets != quantity or frame.page is not None for frame in reward)
                or any(frame.page is None for frame in returned)):
            raise AutomationError('巡星之礼单笔星轨专票弹窗或同卡返回待核对。')
        active_before = set(before[0].page.claimable_days).union(before[1].page.claimable_days)
        claimed_before = _days(before, 'claimed_days')
        active_after, claimed_after = (_days(returned, field) for field in ('claimable_days', 'claimed_days'))
        if claimed_after != claimed_before | {day} or not active_before - {day} <= active_after:
            raise AutomationError('巡星之礼同一日卡的领取变化待核对。')
        record = dict(schema=1, state='verified', activity=ACTIVITY, client_version=_VERSION, day=day,
                      button_observed=True, submission_acknowledged=True, item=ITEM, quantity=quantity,
                      same_card_claimed=True)
        with _hold_records(((self._path, self._raw), (self._reserved_path, self._authorization),
                            (self._sent_path, self._sent))):
            self._require_original_records()
            _publish(self._verified_path, _raw(record), checkpoint, before + reward + returned)
        return record


def prepare_claim(directory, before, *, day, checkpoint):
    """Reserve one explicitly selected day across restarts before any submission."""
    checkpoint()
    if not _supported_day(day):
        raise AutomationError('巡星之礼只核对明确选择的第三至第七日。')
    frames = _selected_pair(before, day)
    second = frames[-1]
    root = Path(directory).resolve(strict=True)
    if not root.is_dir():
        raise AutomationError('请选择已存在的巡星之礼本地回执目录。')
    account = second.scope.account
    key = sha256(f'{ACTIVITY}:{day}:{account}'.encode('ascii')).hexdigest()
    path = root / (key + '.intent.json')
    if any(os.path.lexists(candidate) for candidate in _attempt_paths(path)):
        raise AutomationError('巡星之礼指定日已有待核对或已核实记录。')
    payload = _raw(dict(schema=1, state='pending', activity=ACTIVITY, client_version=_VERSION, day=day,
                        button_observed=True, source_sequence=second.sequence, origin=second.pixels.hex()))
    revision = _publish(path, payload, checkpoint, frames)
    return ClaimIntent(path, payload, frames, revision=revision)
