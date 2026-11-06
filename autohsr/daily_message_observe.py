"""Read-only observation of the calibrated 4.6 phone entry and message panel."""
from __future__ import annotations

import re
import time

import cv2
import numpy as np

from .challenge_pages import _clean
from .config import RESOURCE_ROOT
from .currency_wars_identity import AccountNotObserved, checked_account_key
from .daily_reward_observe import COLLECTION_FLOOR, MAX_AGE, MAX_CAPTURES, _blocked
from .daily_message_state import read_panel_state, unknown_panel_state
from .models import AutomationError, EmptyCapture, InputInterrupted, Scene, Stopped, TaskResult, Token, normalize
from .storage import replace_file
from .team_calibration_pages import _grid_label, calibration_overlay
from .vision import Vision, helper_overlay
from .workflows import TITLE


OPERATION = 'daily_message_observe'
SAFE_NEXT = '请手动打开手机菜单或新消息通知面板，再执行只读核对。'
_LEVEL = (.656, .212, .764, .272)
_GRID = (
    ('短信', (.676, .592, .722, .643)),
    ('跃迁', (.811, .592, .858, .643)),
    ('指南', (.676, .713, .722, .762)),
    ('导航', (.811, .713, .858, .762)),
)
_MESSAGE_HEADER = RESOURCE_ROOT / 'assets/upstream/March7thAssistant/daily-message/incoming_message.png'
_HEADER_ROI = (.145, .174, .256, .252)
_PANEL_PATCHES = ((.145, .18, .162, .23), (.68, .18, .80, .235),
                  (.76, .77, .83, .82), (.87, .19, .92, .24))


def phone_message_entry(scene: Scene, confidence: float = .85) -> Token | None:
    """Return OCR evidence for the phone tile, with no input authorization."""
    if type(confidence) not in (int, float) or not 0 <= confidence <= 1:
        return None
    clean = _clean(scene, COLLECTION_FLOOR, blockers=())
    if (clean is None or helper_overlay(clean) or _blocked(clean)
            or clean.has(('短信', '邮件', '邮箱', '成就', '活动', '设置'), TITLE, exact=True)):
        return None
    if sum(normalize(token.text) == '短信' for token in clean.tokens) != 1:
        return None
    minimum = max(.85, confidence)
    levels = [token for token in clean.tokens if token.within(_LEVEL)
              and re.fullmatch(r'开拓等级(?:[0-9]{1,3})?', normalize(token.text))]
    if len(levels) != 1 or levels[0].score < minimum:
        return None
    tiles = [_grid_label(clean.tokens, name, region, minimum) for name, region in _GRID]
    if any(tile is None for tile in tiles):
        return None
    message, warp, guide, navigation = tiles
    mx, my = message.center
    wx, wy = warp.center
    gx, gy = guide.center
    nx, ny = navigation.center
    if (abs(my - wy) <= .010 and abs(gy - ny) <= .010
            and abs(mx - gx) <= .010 and abs(wx - nx) <= .010
            and .118 <= wx - mx <= .151 and .105 <= gy - my <= .136):
        return message
    return None


def message_panel(scene: Scene) -> bool:
    """Identify the two-column notification panel without reading its contents."""
    return _message_panel_frame(scene) is not None


def _message_panel_frame(scene: Scene) -> np.ndarray | None:
    clean = _clean(scene, COLLECTION_FLOOR, blockers=())
    if (clean is None or helper_overlay(clean) or calibration_overlay(clean)
            or clean.has(('获得物品', '确认', '取消', '重新连接'), (.22, .04, .80, .88), exact=True)):
        return None
    # Match the same coarse layout visible in the independent PC preview
    # frames. The title by itself survives some transitions and overlays.
    frame = cv2.resize(clean.image, (480, 270), interpolation=cv2.INTER_AREA)
    levels = [float(np.median(frame[round(y1 * 270):round(y2 * 270), round(x1 * 480):round(x2 * 480)]))
              for x1, y1, x2, y2 in _PANEL_PATCHES]
    left, top, bottom, outside = levels
    if max(left, outside) > 85 or min(top, bottom) < 155 or not _MESSAGE_HEADER.is_file():
        return None
    try:
        if Vision.__new__(Vision).template(Scene([], frame), _MESSAGE_HEADER, _HEADER_ROI, .86) is not None:
            return frame
    except (AutomationError, OSError):
        return None
    return None


def initial_record():
    return dict(schema=1, phone_entry='unknown', message_page='unknown',
                reward_status='unknown', input_sent=False, account_verified=False, captures=0,
                **unknown_panel_state())


def observe_daily_messages(context) -> dict:
    """Observe an already-foreground client from the dedicated read-only runner."""
    return DailyMessageObserver(context).observe()


class DailyMessageObserver:
    def __init__(self, context):
        self.context = context
        self.record = initial_record()
        self._publication_guard = None
        self.result = None

    def run(self):
        self.observe()
        if self.record['phone_entry'] == 'observed':
            self.result = TaskResult(OPERATION, 'ok', '已核实当前手机短信入口。')
        elif self.record['message_page'] == 'observed':
            self.result = TaskResult(OPERATION, 'ok', '已核实当前新消息通知面板。')
        else:
            self.result = TaskResult(OPERATION, 'partial', '短信入口或面板待同账号双帧核实。')
        return self.result

    def invalidate(self, status, detail):
        self.record.update(phone_entry='unknown', message_page='unknown', account_verified=False,
                           **unknown_panel_state())
        if self.result is not None:
            self.result.status, self.result.detail = status, detail

    def save_verified_report(self, temporary, write_report):
        report = self.context.report
        destination = temporary.with_name('report.json')
        payload = write_report()

        def verify():
            if (self._publication_guard is None or report.daily_message_observe is not self.record
                    or temporary.read_text(encoding='utf8') != payload):
                raise AutomationError('短信观察报告来源未核实。')
            self._publication_guard()

        try:
            replace_file(temporary, destination, before_replace=verify)
        except AutomationError as error:
            stopped = isinstance(error, Stopped)
            if stopped:
                self.context.runner.stop()
            status = 'stopped' if stopped else 'partial'
            detail = '短信观察已停止。' if stopped else '短信观察发布前的窗口、代次或采集时效待核实。'
            self.invalidate(status, detail)
            report.status, report.error, report.failure_task = status, detail, OPERATION
            write_report()
            replace_file(temporary, destination)

    def observe(self):
        context = self.context
        runner = context.runner
        if context.report.operation != OPERATION or runner._foreground_only is not True:
            raise AutomationError('短信观察需要独立的前台只读运行入口。')
        floor = context.vision.confidence
        if type(floor) not in (int, float) or not 0 <= floor <= COLLECTION_FLOOR:
            raise AutomationError('短信观察须以 0.65 或更低采集阈值保留账号与遮挡反证。')
        window = context.window
        window_key = window.current_window_key()
        if not window_key:
            raise AutomationError('短信观察无法核实当前窗口来源。')
        geometry = window.guard()
        epoch = runner.input_epoch
        confidence = context.settings.ocr_confidence

        def check_current():
            if runner.stop_requested:
                raise Stopped('短信观察已停止。')
            if runner.input_epoch != epoch:
                raise InputInterrupted('短信观察期间输入代次已改变。')
            if context.window is not window or window.current_window_key() != window_key:
                raise AutomationError('短信观察期间窗口来源已改变。')
            window.guard(geometry)

        result = self.record
        previous = None
        account = None
        for attempt in range(MAX_CAPTURES):
            if attempt:
                context.sleep(.30)
            context.checkpoint()
            check_current()
            captured_at = time.monotonic()
            result['captures'] += 1
            try:
                # Use the guarded capture directly. The normal snapshot path can wait
                # for focus recovery, while this operation must stop on focus loss.
                image, captured_geometry = window.capture()
            except EmptyCapture:
                previous = None
                continue
            if (captured_geometry != geometry or not isinstance(image, np.ndarray) or image.dtype != np.uint8
                    or image.shape != (geometry.height, geometry.width, 3)):
                raise AutomationError('短信观察期间客户区尺寸已改变。')
            scene = context.vision.read(image, geometry)
            if not isinstance(scene, Scene) or scene.image is not image or scene.geometry != geometry:
                raise AutomationError('短信观察缺少当前采集对应的识别结果。')
            scene.captured_at = captured_at
            context.checkpoint()
            check_current()
            if helper_overlay(scene):
                previous = None
                continue
            try:
                current_account = checked_account_key(scene, confidence)
            except AccountNotObserved:
                previous = None
                continue
            if account is not None and current_account != account:
                raise AutomationError('短信观察期间当前账号已改变。')
            account = current_account
            entry = phone_message_entry(scene, confidence)
            panel_state = None
            if entry is not None:
                view = 'phone_entry'
            else:
                panel_frame = _message_panel_frame(scene)
                if panel_frame is None:
                    previous = None
                    continue
                view = 'message_page'
                panel_state = read_panel_state(panel_frame)
            if previous is not None:
                first, first_view, first_entry, first_panel_state = previous
                if (first_view == view and first.captured_at < captured_at
                        and 0 <= time.monotonic() - first.captured_at <= MAX_AGE
                        and not np.may_share_memory(first.image, scene.image)
                        and (entry is None or all(abs(a - b) <= .006 for a, b in zip(first_entry.box, entry.box)))):
                    check_current()
                    oldest_capture = first.captured_at

                    def verify_publication():
                        if window.emergency_pressed():
                            raise Stopped('F10 紧急停止。')
                        check_current()
                        if window.emergency_pressed() or runner.stop_requested:
                            raise Stopped('F10 紧急停止。')
                        if runner.input_epoch != epoch:
                            raise InputInterrupted('短信观察期间输入代次已改变。')
                        if not 0 <= time.monotonic() - oldest_capture <= MAX_AGE:
                            raise AutomationError('短信观察的双帧在报告发布前已过期。')

                    self._publication_guard = verify_publication
                    result[view] = 'observed'
                    result['account_verified'] = True
                    if panel_state is not None and panel_state == first_panel_state:
                        result.update(panel_state)
                    return result
            previous = scene, view, entry, panel_state
        return result
