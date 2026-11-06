"""Daily page transitions for a task-tree step and its native input gate."""

from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from hashlib import sha256
import math
import time

import numpy as np

from .build_target_read import _has_split_label
from .config import RESOURCE_ROOT
from .currency_wars_identity import AccountNotObserved, UID_COUNTEREVIDENCE, checked_account_key
from .currency_wars_prepare import trusted
from .daily_event_navigation import odyssey_list_entry, reward_guide_entry
from .daily_event_observe import read_event_installation
from .daily_event_pages import _VERSION, phone_journey_event_entry, read_gift_of_odyssey
from .daily_message_observe import message_panel, phone_message_entry
from .daily_message_world import world_message_target
from .daily_reward_observe import phone_achievement_target
from .daily_visa_pages import (VISA_LAYOUT_VERSION, refine_small_visa_title, visa_character_tab, visa_overview,
                              visa_support_section)
from .dungeons import CATEGORIES
from .free_rewards import battlepass_modal, battlepass_page, mail_entry, mailbox
from .models import FULL, AutomationError, EmptyCapture, InputInterrupted, Stopped, TaskResult, Token, normalize
from .policy import du_guide_details, has_du_field_plane_marker
from .screenshot_tool import MAX_PIXELS
from .storage import hold_read_sources
from .task_workflow import (ACTIVITY_WORKFLOW_PAGES, BATTLEPASS_WORKFLOW_PAGES, MESSAGE_WORKFLOW_PAGE,
                            VISA_CHARACTERS_PAGE, WORKFLOW_NAVIGATION_TARGETS, WORLD_WORKFLOW_PAGE)
from .team_calibration_pages import calibration_overlay
from .vision import helper_overlay
from .workflow_battlepass_tabs import exact_battlepass_tab, small_selection_agrees
from .workflows import DailyWorkflow, TITLE


OPERATION = 'workflow_open_page'
TARGETS = WORKFLOW_NAVIGATION_TARGETS
SAFE_NEXT = '请核对当前页面和本次导航回执，反馈待核对时保留当前画面。'
COLLECTION_FLOOR = .65
_MAX_AGE = 8.
_MAX_CAPTURES = 6
_MAX_ACTIONS = 4
_GUIDE_TITLES = {'行动摘要': 'guide', '每日实训': 'daily_training', '生存索引': 'survival_index',
                 '旷宇纷争': 'guide', '逐光捡金': 'guide'}
_GUIDE_PAGES = ('guide', 'daily_training', 'survival_index')
_VISA_COLLECTION = 'visa_collection'
_BATTLEPASS_LAYOUT_VERSION = '4.6.0'
_WORLD_LAYOUT_VERSION = '4.6.0'
_WORLD_RETURN_PANELS = (*_GUIDE_PAGES, 'assignments', 'mail', 'battlepass')
_WORLD_PHONE_ROI = (.005, .041, .042, .105)
_WORLD_PHONE_CENTER = (.018, .067, .028, .083)
_WORLD_STOP = ('跳过剧情', '跳过当前剧情', '退出剧情', '自动播放', '对话记录', '跳过对话', '确认跳过',
               '挑战失败', '战斗胜利', '点击进入', '开始游戏', '账号登录', '扫码登录', '验证码',
               '购买确认', '确认付款', '确认领取', '领取成功', '奖励详情', '开启无名勋礼')
_WORLD_MODAL_PHRASES = ('确认购买', '是否购买', '确认支付', '请支付', '确认付款', '确认领取', '跳过当前剧情')
_WORLD_ACTIVITY = ('旅情事记', '巡星之礼', '奖励指南')
_PHONE_CAPTIONS = {
    'guide': (('指南', '星际和平指南'), (.655, .713, .742, .763)),
    'assignments': (('委托',), (.884, .357, .921, .398)),
    'battlepass': (('无名勋礼',), (.733, .586, .801, .651)),
}
_MAIL_CAPTION = (.944, .215, .999, .300)
_MAIL_CENTER = (.966, .240, .981, .273)
_TAB = {
    'daily_training': ('每日实训', 'daily_tab', (.158, .150, .222, .243), (.177, .176, .204, .224)),
    'survival_index': ('生存索引', 'survival_tab', (.217, .150, .285, .252), (.234, .177, .267, .231)),
}
_CATEGORIES = ('培养目标', '位面饰品', *(item.label for item in CATEGORIES))
_BLOCKERS = ('列车补给', '获得物品', '选择奖励', '请选择奖励', '切换账号', '退出登录',
             '点击空白处关闭', '点击任意位置关闭', '点击空白处继续', '重新连接', '网络连接失败',
             '资源下载', '确认购买', '确认支付', '退出挑战', '开始挑战', '是否消耗')
_DIALOG = ('提示', '温馨提示', '确认', '确定', '取消', '知道了', '我知道了', '支付', '付款')
_DIALOG_AREA = (.25, .20, .75, .86)


@dataclass(frozen=True)
class _Frame:
    scene: object
    image: np.ndarray
    sequence: int
    captured_at: float
    account: str
    page: str | None
    tokens: tuple
    counterevidence: tuple
    digest: bytes


@dataclass(frozen=True)
class _Action:
    name: str
    pages: tuple[str, ...]
    token: Token | None = None  # Only the two explicitly named Esc actions have no token.


def _digest(image):
    return sha256(np.ascontiguousarray(image)).digest()


def _inside(box, region):
    x1, y1, x2, y2 = box
    return region[0] <= x1 < x2 <= region[2] and region[1] <= y1 < y2 <= region[3]


def _matches(scene, labels, region=FULL):
    wanted = {normalize(label) for label in labels}
    return [token for token in scene.tokens if normalize(token.text) in wanted and token.within(region)]


def _unique(matches, region, confidence):
    if len(matches) == 1 and matches[0].score >= confidence and _inside(matches[0].box, region):
        return matches[0]
    return None


def classify_page(scene, confidence, daily, *, battlepass_subpages=False):
    """Classify an existing scene using the calibrated daily navigation landmarks."""
    low = trusted(scene, COLLECTION_FLOOR)
    if (calibration_overlay(low) or helper_overlay(low) or daily._login(low) or daily._in_battle(low)
            or battlepass_modal(low) or low.has(_BLOCKERS, exact=True) or low.has(_DIALOG, _DIALOG_AREA, exact=True)
            or _has_split_label(low, _BLOCKERS, FULL) or _has_split_label(low, _DIALOG, _DIALOG_AREA)):
        raise AutomationError('当前有登录、战斗、弹窗或遮挡，日常页面导航已停止。')
    if low.has(('加载中', '正在加载', '登录中'), exact=True):
        return None
    view = trusted(scene, confidence)
    pages = []
    if phone_achievement_target(scene, confidence) is not None:
        pages.append('phone')
    title = _unique(_matches(low, ('星际和平指南',), TITLE), TITLE, confidence)
    active = _unique(_matches(low, _GUIDE_TITLES, TITLE), TITLE, confidence)
    if title is not None and active is not None:
        page = _GUIDE_TITLES[normalize(active.text)]
        if ((page != 'daily_training' or daily._activity(view) is not None)
                and (page != 'survival_index' or view.has(_CATEGORIES, (.10, .22, .39, .94), exact=True))):
            pages.append(page)
    if _unique(_matches(low, ('委托',), TITLE), TITLE, confidence) and daily._persistent_assignments(view):
        pages.append('assignments')
    if _unique(_matches(low, ('邮箱', '邮件'), TITLE), TITLE, confidence) and mailbox(view):
        pages.append('mail')
    if _unique(_matches(low, ('无名勋礼',), TITLE), TITLE, confidence) and (kind := battlepass_page(view)):
        if battlepass_subpages and _unique(_matches(low, ('奖励', '任务'), TITLE), TITLE, confidence) is None:
            return None
        pages.append('battlepass_' + kind if battlepass_subpages else 'battlepass')
    if pages:
        return pages[0] if len(pages) == 1 else None
    if not low.has('开拓等级', (.55, .05, .99, .35)) and daily._world(low):
        return 'world'
    return None


@contextmanager
def _seal(frames):
    writable = [frame.image for frame in frames if frame.image.flags.writeable]
    try:
        for image in writable:
            image.flags.writeable = False
        yield
    finally:
        for image in writable:
            image.flags.writeable = True


class WorkflowNavigation:
    def __init__(self, context, target):
        if target not in TARGETS:
            raise AutomationError('请选择受支持的日常页面。')
        self.c = context
        self.target = target
        self.record = {'target': target, 'page_verified': False, 'actions': []}
        context.report.workflow_navigation = self.record
        self.daily = DailyWorkflow(context)
        self.confidence = max(.85, context.settings.ocr_confidence)
        self.window = context.window
        self.epoch = context.runner.input_epoch
        self.occlusions = context.capture_occlusion_count
        self.key = self.geometry = self.account = None
        self.intent = self.arrival = None
        self._installation = None
        self.started = False

    @property
    def installation_source(self):
        return self._installation.source if self._installation is not None else None

    def _control(self):
        c = self.c
        if self.window.emergency_pressed() or c.runner.stop_requested:
            raise Stopped('日常页面导航已停止。')
        if c.runner.input_epoch != self.epoch:
            raise InputInterrupted('日常页面导航的输入代次已变化。')
        if (c.window is not self.window or c.capture_occlusion_count != self.occlusions
                or c.report.operation != OPERATION or getattr(c, 'workflow_navigation', None) is not self
                or c.report.workflow_navigation is not self.record or self.record.get('target') != self.target):
            raise AutomationError('日常页面导航的窗口、入口或遮挡状态已变化。')

    def _guard(self):
        self._control()
        if self._installation is not None and read_event_installation(self.window) != self._installation:
            raise AutomationError('日常页面导航的游戏安装来源或版本已变化。')
        if (not self.key or self.window.current_window_key() != self.key
                or self.window.guard(self.geometry) != self.geometry):
            raise AutomationError('日常页面导航的前台窗口来源已变化。')
        self._control()

    def _page(self, scene):
        page = classify_page(scene, self.confidence, self.daily,
                             battlepass_subpages=self.target in BATTLEPASS_WORKFLOW_PAGES)
        if (page in BATTLEPASS_WORKFLOW_PAGES
                and not small_selection_agrees(scene.image, page.removeprefix('battlepass_'))):
            return None
        return page

    def _world_return_page(self, scene, page):
        low = trusted(scene, COLLECTION_FLOOR)
        header = ''.join(token.text for token in low.tokens if token.within(TITLE))
        if (low.has(_WORLD_STOP, exact=True) or _has_split_label(low, _WORLD_STOP, FULL)
                or low.has(_WORLD_MODAL_PHRASES, _DIALOG_AREA)
                or _has_split_label(low, _WORLD_MODAL_PHRASES, _DIALOG_AREA, exact=False)
                or low.has(_WORLD_ACTIVITY, TITLE, exact=True) or _has_split_label(low, _WORLD_ACTIVITY, TITLE)
                or has_du_field_plane_marker(header) or du_guide_details(low) or message_panel(low)):
            raise AutomationError('当前有剧情、玩法或未核实的遮挡，返回大世界已停止。')
        if page != WORLD_WORKFLOW_PAGE:
            return page
        # The generic world anchor is also visible in some special modes.
        phone = self.daily._icon(low, 'workflow_world_phone', _WORLD_PHONE_ROI, threshold=.95)
        if phone is not None:
            x, y = phone
            left, top, right, bottom = _WORLD_PHONE_CENTER
            if left <= x <= right and top <= y <= bottom:
                return page
        return None

    def _phone_control(self, scene, page):
        low = trusted(scene, COLLECTION_FLOOR)
        if page != 'mail':
            labels, box = _PHONE_CAPTIONS[page]
            return _unique(_matches(low, labels), box, self.confidence)
        matches = _matches(low, ('邮件', '邮箱'))
        if matches:
            return _unique(matches, _MAIL_CAPTION, self.confidence)
        icon = mail_entry(low)
        return icon if icon is not None and icon.score >= max(.94, self.confidence) and icon.within(_MAIL_CENTER) else None

    def _guide_control(self, scene, page):
        label, template, box, center = _TAB[page]
        matches = _matches(trusted(scene, COLLECTION_FLOOR), (label,), box)
        if matches:
            return _unique(matches, box, self.confidence)
        minimum = .88
        match = self.c.template(scene, template, box, threshold=minimum)
        if match is None and page == 'survival_index':
            minimum = .94
            match = self.c.template(scene, 'survival_tab_base', box, threshold=minimum)
        if match is None and page == 'daily_training':
            # Existing 4.6 unselected tab glyph, calibrated to the same physical slot.
            path = RESOURCE_ROOT / 'assets' / 'ui' / 'tab-daily.png'
            if path.is_file():
                match = self.c.vision.template(scene, path, box, minimum)
        if not isinstance(match, (tuple, list)) or len(match) != 3:
            return None
        x, y, score = match
        if not (all(math.isfinite(value) for value in match) and minimum <= score <= 1
                and center[0] <= x <= center[2] and center[1] <= y <= center[3]):
            return None
        return Token(label, score, (x-.005, y-.006, x+.005, y+.006))

    def _read_page(self, scene):
        page = self._page(scene)
        if self.target == WORLD_WORKFLOW_PAGE:
            return self._world_return_page(scene, page)
        if self.target == MESSAGE_WORKFLOW_PAGE:
            panel = message_panel(scene)
            if page not in (None, 'world'):
                return None if panel else page
            if phone_message_entry(scene, self.confidence) is not None:
                return None if panel else 'phone'
            if panel:
                return MESSAGE_WORKFLOW_PAGE
            return 'world' if world_message_target(scene) is not None else None
        if page is not None or self._installation is None or self.target in BATTLEPASS_WORKFLOW_PAGES:
            return page
        if self.target == VISA_CHARACTERS_PAGE:
            if visa_overview(scene, self.confidence):
                return _VISA_COLLECTION
            return VISA_CHARACTERS_PAGE if visa_support_section(scene, self.confidence) else None
        options = dict(client_version=self._installation.version, confidence=self.confidence)
        if self.target == 'reward_guide':
            from .daily_reward_guide_pages import reward_guide_page

            if reward_guide_page(scene, **options):
                return 'reward_guide'
        if read_gift_of_odyssey(scene, **options) is not None:
            return 'odyssey'
        list_entry = reward_guide_entry if self.target == 'reward_guide' else odyssey_list_entry
        if list_entry(scene, **options) is not None:
            return 'activity_list'
        return None

    def _action(self, frame):
        page = frame.page
        if self.target == WORLD_WORKFLOW_PAGE:
            if page == 'phone':
                return _Action('return_to_hub', (WORLD_WORKFLOW_PAGE,))
            if page in _WORLD_RETURN_PANELS:
                return _Action('return_to_hub', (WORLD_WORKFLOW_PAGE, 'phone'))
            return None
        if self.target == MESSAGE_WORKFLOW_PAGE:
            token = world_message_target(frame.scene) if page == 'world' else None
            return _Action('open_messages', (MESSAGE_WORKFLOW_PAGE,), token) if token else None
        if self.target == VISA_CHARACTERS_PAGE:
            if page != _VISA_COLLECTION or self._installation is None:
                return None
            tab = visa_character_tab(frame.scene, client_version=self._installation.version, confidence=self.confidence)
            return _Action('open_' + VISA_CHARACTERS_PAGE, (VISA_CHARACTERS_PAGE,), tab) if tab is not None else None
        if self.target in BATTLEPASS_WORKFLOW_PAGES:
            if page == 'phone':
                token = self._phone_control(frame.scene, 'battlepass')
                return _Action('open_battlepass', BATTLEPASS_WORKFLOW_PAGES, token) if token else None
            if page in BATTLEPASS_WORKFLOW_PAGES:
                kind = self.target.removeprefix('battlepass_')
                tab = exact_battlepass_tab(trusted(frame.scene, self.confidence), kind)
                return _Action('open_' + self.target, (self.target,), tab) if tab else None
            return None
        if page == 'world':
            return None if message_panel(frame.scene) else _Action('open_phone', ('phone',))
        if self._installation is not None and page in ('phone', 'activity_list', 'odyssey'):
            options = dict(client_version=self._installation.version, confidence=self.confidence)
            if page == 'phone':
                token = phone_journey_event_entry(frame.scene, **options)
                destinations = ('activity_list', 'odyssey')
                if self.target == 'reward_guide':
                    destinations += ('reward_guide',)
                return _Action('open_journey_events', destinations, token) if token else None
            if self.target == 'reward_guide':
                token = reward_guide_entry(frame.scene, **options)
                return _Action('open_reward_guide', ('reward_guide',), token) if token else None
            token = odyssey_list_entry(frame.scene, **options)
            return _Action('open_odyssey', ('odyssey',), token) if token else None
        if page == 'phone':
            target = 'guide' if self.target in _GUIDE_PAGES else self.target
            token = self._phone_control(frame.scene, target)
            return _Action('open_' + target, _GUIDE_PAGES if target == 'guide' else (target,), token) if token else None
        if page in _GUIDE_PAGES and self.target in _TAB:
            token = self._guide_control(frame.scene, self.target)
            return _Action('open_' + self.target, (self.target,), token) if token else None
        return _Action('return_to_hub', ('world', 'phone')) if page in TARGETS and page not in ACTIVITY_WORKFLOW_PAGES else None

    def _satisfies(self, page):
        return page == self.target or self.target == 'guide' and page in _GUIDE_PAGES

    def _account(self, scene):
        account = checked_account_key(scene, self.confidence)
        if self.account is not None and self.account != account:
            raise AutomationError('日常页面导航期间当前账号已变化。')
        return account

    def _capture(self):
        c = self.c
        self._guard()
        previous, sequence, started = c.last_scene, c.capture_sequence, time.monotonic()
        scene = c.snapshot()
        self._guard()
        image = scene.image
        if (scene is previous or scene is not c.last_scene or c.capture_sequence <= sequence
                or c.scene_epoch != self.epoch or scene.geometry != self.geometry
                or not started <= scene.captured_at <= time.monotonic() or not self._fresh(scene.captured_at)
                or not isinstance(image, np.ndarray) or image.dtype != np.uint8
                or image.shape != (self.geometry.height, self.geometry.width, 3)):
            raise AutomationError('日常页面导航缺少同窗的新鲜画面。')
        sample = image[::max(1, image.shape[0] // 160), ::max(1, image.shape[1] // 240)]
        if float(np.std(sample, axis=(0, 1)).max()) < 2:
            raise EmptyCapture('日常页面导航的过场画面为空。')
        if self.target == VISA_CHARACTERS_PAGE and self._installation is not None:
            refine_small_visa_title(scene, c.vision, self.confidence, client_version=self._installation.version)
        page = self._read_page(scene)
        account = self._account(scene)
        self.account = account
        return _Frame(scene, image, c.capture_sequence, scene.captured_at, account, page, tuple(scene.tokens),
                      tuple(scene.field_reads.get(UID_COUNTEREVIDENCE) or ()), _digest(image))

    @staticmethod
    def _fresh(captured_at):
        return 0 <= time.monotonic() - captured_at <= _MAX_AGE

    @staticmethod
    def _adjacent(first, second):
        return (second.sequence == first.sequence + 1 and first.scene is not second.scene
                and not np.may_share_memory(first.image, second.image) and first.captured_at < second.captured_at
                and first.account == second.account and first.page is not None and first.page == second.page)

    def _pair(self, *, after=None, expected=(), source=None):
        previous = None
        for attempt in range(_MAX_CAPTURES):
            if attempt or after is not None:
                self.c.sleep(.22)
            try:
                frame = self._capture()
            except (EmptyCapture, AccountNotObserved):
                previous = None
                continue
            if frame.page is None or after is not None and frame.captured_at <= after:
                previous = None
                continue
            if expected and frame.page not in expected:
                if frame.page != source:
                    raise AutomationError('日常页面导航到了预期之外的页面，未再发送输入。')
                previous = None
                continue
            if previous is not None and self._adjacent(previous, frame) and self._fresh(previous.captured_at):
                return previous, frame
            previous = frame
        raise AutomationError('日常页面缺少连续独立的到页证据，未重复发送输入。')

    def _retained(self, frame):
        scene = frame.scene
        return (self._fresh(frame.captured_at) and scene.geometry == self.geometry
                and scene.captured_at == frame.captured_at and scene.image is frame.image
                and tuple(scene.tokens) == frame.tokens
                and tuple(scene.field_reads.get(UID_COUNTEREVIDENCE) or ()) == frame.counterevidence)

    def _latest(self, frame):
        if (self.c.last_scene is not frame.scene or self.c.capture_sequence != frame.sequence
                or self.c.scene_epoch != self.epoch or not self._retained(frame)):
            raise AutomationError('日常页面导航的当前帧或来源已变化。')

    def _verify(self, pair):
        first, second = pair
        self._guard()
        self._latest(second)
        if not self._adjacent(first, second) or not self._fresh(first.captured_at):
            raise AutomationError('日常页面导航的双帧已过期或发生替换。')
        for frame in pair:
            scene = frame.scene
            if (not self._retained(frame) or _digest(frame.image) != frame.digest or self._account(scene) != frame.account
                    or self._read_page(scene) != frame.page):
                raise AutomationError('日常页面导航的原始双帧、账号或页面已改变。')

    def _final_guard(self, pair):
        self._guard()
        self._latest(pair[-1])
        if not self._retained(pair[0]) or any(frame.image.flags.writeable for frame in pair):
            raise AutomationError('日常页面导航的封存双帧已变化。')
        self.window.require_foreground()
        self._control()

    def _planned(self, pair):
        first, second = map(self._action, pair)
        if first is None or second is None or first.name != second.name or first.pages != second.pages:
            raise AutomationError('日常页面导航缺少双帧一致的唯一入口。')
        tolerances = (2 / 852, 2 / 480) * 2 if self.target == MESSAGE_WORKFLOW_PAGE else (.006,) * 4
        if (first.token is None) != (second.token is None) or (first.token is not None and (
                normalize(first.token.text) != normalize(second.token.text)
                or any(abs(a-b) > tolerance for a, b, tolerance in
                       zip(first.token.box, second.token.box, tolerances)))):
            raise AutomationError('日常页面导航入口的位置在双帧间改变。')
        return second

    def dispatch(self, scene, action):
        intent = self.intent
        if intent is None or scene is not intent[0][-1].scene or action != intent[1].name:
            raise AutomationError('没有本次日常页面导航的一次性意图。')
        pair, planned = intent
        row = None
        sent_at = None

        def before_submit():
            nonlocal row, sent_at
            if self.intent is not intent:
                raise AutomationError('本次日常页面导航的意图已消费。')
            self._verify(pair)
            if self._planned(pair) != planned:
                raise AutomationError('日常页面导航的目标控件在提交前已变化。')
            self._final_guard(pair)
            self.intent = None
            sent_at = time.monotonic()
            row = dict(action=planned.name, source_page=pair[-1].page, expected_pages=list(planned.pages),
                       input_status='unconfirmed', destination_status='unknown')
            self.record['actions'].append(row)
            self.c.last_scene, self.c._scroll_anchor = None, None

        installation = self.installation_source
        source = hold_read_sources((installation,)) if installation is not None else nullcontext()
        with _seal(pair), source:
            self._verify(pair)
            if planned.token is None:
                if planned.name not in ('open_phone', 'return_to_hub'):
                    raise AutomationError('日常页面导航缺少受支持的原生输入。')
                self.window.key('esc', expected=self.geometry, before_submit=before_submit)
            else:
                self.window.click(*planned.token.center, self.geometry, before_submit=before_submit)
        if row is None:
            raise AutomationError('日常页面导航缺少原生提交回执。')
        row['input_status'] = 'sent'
        return sent_at

    def guard_publication(self):
        if self.arrival is None or self.record['page_verified'] is not True or not self._satisfies(self.arrival[-1].page):
            raise AutomationError('日常页面导航缺少本次到页回执。')
        with _seal(self.arrival):
            self._verify(self.arrival)
            self._final_guard(self.arrival)

    def run(self):
        if self.started or getattr(self.c.runner, '_foreground_only', False) is not True:
            raise AutomationError('日常页面导航需要独立的当前前台运行。')
        self.started = True
        self.c.checkpoint()
        self._control()
        self.geometry = self.window.guard()
        self.key = self.window.current_window_key()
        if self.geometry is None or not 0 < self.geometry.width * self.geometry.height <= MAX_PIXELS:
            raise AutomationError('日常页面导航缺少可核实的游戏客户区。')
        self._guard()
        expected, version = (), None
        if self.target == VISA_CHARACTERS_PAGE:
            expected, version = (_VISA_COLLECTION, VISA_CHARACTERS_PAGE), VISA_LAYOUT_VERSION
        elif self.target in BATTLEPASS_WORKFLOW_PAGES:
            expected, version = ('phone', *BATTLEPASS_WORKFLOW_PAGES), _BATTLEPASS_LAYOUT_VERSION
        elif self.target == WORLD_WORKFLOW_PAGE:
            expected, version = (WORLD_WORKFLOW_PAGE, 'phone', *_WORLD_RETURN_PANELS), _WORLD_LAYOUT_VERSION
        elif self.target in (*ACTIVITY_WORKFLOW_PAGES, MESSAGE_WORKFLOW_PAGE):
            version = _VERSION
        if version is not None:
            self._installation = read_event_installation(self.window)
            if self._installation.version != version:
                raise AutomationError('当前客户端尚未校准所选页面导航。')
            self.record['client_version'] = self._installation.version
        pair = self._pair(expected=expected)
        while not self._satisfies(pair[-1].page):
            if len(self.record['actions']) >= _MAX_ACTIONS:
                raise AutomationError('日常页面导航达到本次输入上限。')
            planned = self._planned(pair)
            self.intent = pair, planned
            sent_at = self.c.workflow_navigation_input(pair[-1].scene, planned.name)
            if self.intent is not None or type(sent_at) is not float or not math.isfinite(sent_at):
                raise AutomationError('日常页面导航未收到本次原生提交反馈。')
            pair = self._pair(after=sent_at, expected=planned.pages, source=pair[-1].page)
            self._verify(pair)
            self.record['actions'][-1].update(destination_status='verified', destination_page=pair[-1].page)
        self.arrival = pair
        self.record['page_verified'] = True
        try:
            self.guard_publication()
        except BaseException:
            self.record['page_verified'] = False
            raise
        return TaskResult(OPERATION, 'ok', '已核实到达请求的日常页面。')
