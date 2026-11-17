"""Opt-in weekly relic salvage. Daily and plan runners do not call this module.

Behavior follows the public March7thAssistant weekly cleanup: on the chosen
weekday after the 04:00 game refresh, salvage 4★ and below, optionally marking
5★ with smart discard first. Screen rectangles below are search regions for
already recognized text. Clicks go to that text, never to a bare coordinate.
A due run may launch or focus the game; an unrecognized page stops before the
salvage confirmation and does not record the weekly timestamp.
"""
from __future__ import annotations

from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import time

from .models import AutomationError, EmptyCapture, Scene, Token, normalize
from .storage import replace_file
from .weekly_plan import CHINA

OPERATION = 'weekly_relic_cleanup'
LEDGER_NAME = 'weekly-relic-cleanup.json'
REFRESH_HOUR = 4
MAX_BATCHES = 7
BATCH_LIMIT = 500
MINIMUM_SCORE = 0.85

# 1920×1080 reference edges. They only limit which OCR token may be used.
def _edges(x1, y1, x2, y2):
    return (x1 / 1920, y1 / 1080, x2 / 1920, y2 / 1080)


TITLE = (0.0, 0.0, 0.30, 0.12)
# The relic-tab row is not yet taken from a current-client capture.
TAB_ROW = (0.06, 0.12, 0.62, 0.24)
BREAK_TITLE = _edges(75, 35, 300, 105)
BAG_BREAK = _edges(1130, 945, 1390, 1030)
SALVAGE_BREAK = _edges(1430, 945, 1875, 1025)
SALVAGE_COUNT = _edges(610, 875, 830, 930)
QUICK_BUTTON = _edges(1200, 950, 1430, 1030)
QUICK_TITLE = _edges(425, 295, 625, 350)
FOUR_STAR = _edges(460, 590, 955, 650)
DISCARDED_RULE = _edges(460, 415, 955, 475)
QUICK_CONFIRM = _edges(775, 725, 1145, 795)
SMART_BUTTON = _edges(570, 945, 805, 1030)
SMART_TITLE = _edges(425, 295, 615, 345)
SMART_COUNT = _edges(605, 302, 830, 350)
CLEAR_RULES = _edges(570, 725, 935, 795)
UNMATCHED_RULE = _edges(465, 450, 950, 510)
ZERO_RULE = _edges(465, 570, 950, 630)
SMART_CONFIRM = _edges(985, 725, 1355, 795)
PROTECT_LABEL = _edges(1295, 655, 1415, 704)
PROTECT_STATE = _edges(1375, 640, 1515, 725)
BATCH_TITLE = _edges(755, 310, 930, 360)
BATCH_CONFIRM = _edges(985, 790, 1355, 855)
DECOMPOSE_TITLE = (0.32, 0.26, 0.68, 0.42)
DECOMPOSE_BODY = (0.22, 0.40, 0.78, 0.64)
DECOMPOSE_CONFIRM = (0.52, 0.64, 0.78, 0.84)
CANCEL_BAND = (0.22, 0.62, 0.48, 0.86)
REWARD_TITLE = (0.25, 0.04, 0.75, 0.40)
REWARD_BODY = (0.20, 0.35, 0.80, 0.72)
REWARD_CLOSE = (0.25, 0.68, 0.75, 0.98)
_COMMERCE = ('购买', '星琼', '燃料', '支付', '充值', '兑换', '确认购买', '使用燃料')


def validate_settings(settings):
    from .config import SettingsError
    if type(settings.break_down_level_four_relicset) is not bool:
        raise SettingsError('break_down_level_four_relicset', '周遗器清理开关必须为布尔值。')
    if type(settings.weekly_relic_smart_discard_enable) is not bool:
        raise SettingsError('weekly_relic_smart_discard_enable', '周遗器智能弃置开关必须为布尔值。')
    day = settings.weekly_relic_cleanup_day_of_week
    if type(day) is not int or isinstance(day, bool) or not 1 <= day <= 7:
        raise SettingsError('weekly_relic_cleanup_day_of_week', '周遗器清理星期必须为 1～7。')


def game_week_start(now, hour=REFRESH_HOUR):
    """Monday refresh that opens the current game week, in Beijing time."""
    if now.tzinfo is None:
        raise AutomationError('周遗器清理需要北京时间。')
    local = now.astimezone(CHINA)
    start = (local - timedelta(days=local.weekday())).replace(
        hour=hour, minute=0, second=0, microsecond=0)
    if local < start:
        start -= timedelta(days=7)
    return start


def is_due(now, day, timestamp, hour=REFRESH_HOUR):
    """True when this game week's chosen weekday has passed and the ledger is older."""
    if type(day) is not int or isinstance(day, bool) or not 1 <= day <= 7:
        return False
    if type(timestamp) is not int or isinstance(timestamp, bool) or timestamp < 0:
        return False
    start = game_week_start(now, hour)
    scheduled = start + timedelta(days=day - 1)
    last = datetime.fromtimestamp(timestamp, CHINA)
    return now.astimezone(CHINA) >= scheduled and last < start


def decision(settings, timestamp, now, *, invoked):
    """Daily and plan callers pass invoked=False and therefore never run."""
    if invoked is not True:
        return 'not_invoked'
    if settings.break_down_level_four_relicset is not True:
        return 'disabled'
    if not is_due(now, settings.weekly_relic_cleanup_day_of_week, timestamp):
        return 'not_due'
    return 'run'


class TimestampStore:
    """Completion ledger. It is not part of config.json and is written once per success."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.write_count = 0

    def read(self) -> int:
        path = self.path
        if not path.exists():
            return 0
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError
            data = json.loads(path.read_text(encoding='utf-8'))
            value = data['weekly_relic_cleanup_timestamp']
            if (type(data.get('schema')) is not int or data['schema'] != 1
                    or type(value) is not int or isinstance(value, bool) or value < 0):
                raise ValueError
        except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError, UnicodeError):
            raise AutomationError('周遗器清理完成时间无法核对，未开始。') from None
        return value

    def write(self, stamp: int) -> None:
        if type(stamp) is not int or isinstance(stamp, bool) or stamp < 0:
            raise AutomationError('周遗器完成时间无效，未保存。')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(
            {'schema': 1, 'weekly_relic_cleanup_timestamp': stamp},
            ensure_ascii=False, indent=2), encoding='utf-8')
        replace_file(temporary, self.path)
        if self.read() != stamp:
            raise AutomationError('周遗器完成时间保存后回读不一致。')
        self.write_count += 1


def unique_text(scene, label, roi, minimum=MINIMUM_SCORE):
    if not isinstance(scene, Scene):
        return None
    wanted = normalize(label)
    hits = [token for token in scene.tokens
            if token.within(roi) and token.score >= minimum and normalize(token.text) == wanted]
    return hits[0] if len(hits) == 1 else None


def region_text(scene, roi):
    tokens = [token for token in scene.tokens if token.within(roi)]
    tokens.sort(key=lambda token: (round(token.center[1], 3), token.center[0]))
    return ''.join(token.text for token in tokens)


def shows_count(text, count):
    if type(count) is not int or isinstance(count, bool) or count < 0:
        return False
    compact = normalize(text).replace('／', '/')
    return re.search(rf'(?<!\d){count}(?!\d)', compact) is not None


def read_count(scene, roi):
    raw = region_text(scene, roi)
    compact = normalize(raw).replace('／', '/')
    matches = re.findall(r'(?<!\d)(\d+)/500(?!\d)', compact)
    if len(matches) != 1:
        raise AutomationError(f'无法确认已选遗器数量：{raw!r}')
    value = int(matches[0])
    if value > BATCH_LIMIT:
        raise AutomationError(f'无法确认已选遗器数量：{raw!r}')
    return value


def commerce(scene):
    return any(scene.has(word, exact=True) for word in _COMMERCE)


def modal_kind(scene):
    if not isinstance(scene, Scene) or commerce(scene):
        return None
    if unique_text(scene, '确认分解', DECOMPOSE_TITLE) is not None:
        return 'decompose'
    if unique_text(scene, '批量弃置', BATCH_TITLE) is not None:
        return 'batch'
    if unique_text(scene, '待弃置遗器', SMART_TITLE) is not None:
        return 'smart'
    if (unique_text(scene, '快速选择', QUICK_TITLE) is not None
            and unique_text(scene, '4星及以下', FOUR_STAR) is not None):
        return 'quick'
    if (unique_text(scene, '获得物品', REWARD_TITLE) is not None
            and unique_text(scene, '遗器残骸', REWARD_BODY) is not None):
        return 'reward'
    return None


def bag_page(scene):
    if commerce(scene) or modal_kind(scene) is not None:
        return False
    if unique_text(scene, '背包', TITLE) is None or unique_text(scene, '遗器', TAB_ROW) is None:
        return False
    if unique_text(scene, '遗器分解', BREAK_TITLE) is not None:
        return False
    return any(unique_text(scene, label, TAB_ROW) is not None for label in ('光锥', '材料', '消耗品'))


def relic_bag_page(scene):
    return bag_page(scene) and unique_text(scene, '分解', BAG_BREAK) is not None


def salvage_page(scene):
    return (modal_kind(scene) is None and not commerce(scene)
            and unique_text(scene, '遗器分解', BREAK_TITLE) is not None
            and unique_text(scene, '快速选择', QUICK_BUTTON) is not None)


def quick_dialog(scene):
    return modal_kind(scene) == 'quick' and unique_text(scene, '取消', CANCEL_BAND) is not None


def protection_on(scene):
    return (modal_kind(scene) == 'smart'
            and unique_text(scene, '弃置保护', PROTECT_LABEL) is not None
            and unique_text(scene, '已开启', PROTECT_STATE) is not None)


def decompose_confirm_token(scene, count):
    if modal_kind(scene) != 'decompose' or unique_text(scene, '取消', CANCEL_BAND) is None:
        return None
    body = region_text(scene, DECOMPOSE_BODY)
    preview = normalize(body)
    if not shows_count(body, count) or ('件遗器' not in preview and '遗器残骸' not in preview):
        return None
    return unique_text(scene, '确认', DECOMPOSE_CONFIRM)


def reward_close_token(scene):
    if modal_kind(scene) != 'reward':
        return None
    return unique_text(scene, '点击空白处关闭', REWARD_CLOSE)


# Same 4.6 phone-grid slots as team_calibration_pages.phone_team_target.
_LEVEL = (.656, .212, .764, .272)
_LEVEL_CAPTION = re.compile(r'开拓等级(?:\d{1,3})?')
_TEAM = (.676, .833, .722, .882)
_GUIDE = (.676, .713, .722, .762)
_PHONE_BAG = (.743, .833, .790, .882)
_TASK = (.811, .833, .858, .882)
_PHONE_BLOCKERS = frozenset((
    '提示', '温馨提示', '确定', '知道了', '我知道了', '兑换码', '漫游签证',
    '星际和平指南', '生存索引', '角色编队', '预设编队', '编队预设', '队伍预设',
    '队伍详情', '角色列表', '当前队伍', '切换命途',
))
_PHONE_PHRASES = (
    '确认', '取消', '是否', '前往编队', '进入编队', '将清空', '点击空白处关闭',
    '验证码', '扫码登录', '重新连接', '连接失败', '加载中',
)


def _inside(box, roi):
    return all(box[index] >= roi[index] for index in (0, 1)) and all(
        box[index + 2] <= roi[index + 2] for index in (0, 1))


def _overlaps(box, roi):
    return all(max(box[index], roi[index]) < min(box[index + 2], roi[index + 2]) for index in (0, 1))


def _grid_label(tokens, label, roi, minimum):
    hits = [token for token in tokens if _overlaps(token.box, roi)]
    if len(hits) != 1:
        return None
    token = hits[0]
    width, height = token.box[2] - token.box[0], token.box[3] - token.box[1]
    if (token.text.strip() != label or token.score < minimum or not _inside(token.box, roi)
            or not .016 <= width <= .034 or not .017 <= height <= .035):
        return None
    return token


def bag_target(scene, confidence=0.65):
    """Return the phone-grid 背包 token. A loose 背包 word is not an entry."""
    if (not isinstance(scene, Scene) or not isinstance(scene.tokens, (list, tuple))
            or type(confidence) not in (int, float) or not 0 <= confidence <= 1):
        return None
    if not any(getattr(token, 'text', None) == '背包' for token in scene.tokens):
        return None
    words = [normalize(token.text) for token in scene.tokens]
    if (words.count('编队') != 1 or _PHONE_BLOCKERS.intersection(words)
            or any(phrase in word for phrase in _PHONE_PHRASES for word in words)):
        return None
    minimum = max(.85, confidence)
    levels = [token for token, word in zip(scene.tokens, words)
              if _LEVEL_CAPTION.fullmatch(word) and _overlaps(token.box, _LEVEL)]
    if len(levels) != 1 or levels[0].score < minimum or not _inside(levels[0].box, _LEVEL):
        return None
    team = _grid_label(scene.tokens, '编队', _TEAM, minimum)
    guide = _grid_label(scene.tokens, '指南', _GUIDE, minimum)
    bag = _grid_label(scene.tokens, '背包', _PHONE_BAG, minimum)
    task = _grid_label(scene.tokens, '任务', _TASK, minimum)
    if team is None or guide is None or bag is None or task is None:
        return None
    team_x, team_y = team.center
    guide_x, guide_y = guide.center
    bag_x, bag_y = bag.center
    task_x, task_y = task.center
    if (abs(team_x - guide_x) > .010 or not .108 <= team_y - guide_y <= .132
            or max(team_y, bag_y, task_y) - min(team_y, bag_y, task_y) > .010
            or not .055 <= bag_x - team_x <= .082 or not .055 <= task_x - bag_x <= .082):
        return None
    return bag


def guard_click(scene, target, intent, state):
    if not isinstance(target, Token):
        raise AutomationError('遗器清理只允许点击已识别的文字控件。')
    if commerce(scene):
        raise AutomationError('遗器清理页面含支付或兑换内容，已停止。')
    if not isinstance(state, dict):
        raise AutomationError('遗器清理缺少本次数量记录，未发送点击。')
    kind = modal_kind(scene)
    allowed = False
    if intent == 'open_bag':
        allowed = target is bag_target(scene) and kind is None
    elif intent == 'open_relic_tab':
        allowed = (bag_page(scene) and not relic_bag_page(scene)
                   and target is unique_text(scene, '遗器', TAB_ROW))
    elif intent == 'open_salvage':
        allowed = relic_bag_page(scene) and target is unique_text(scene, '分解', BAG_BREAK)
    elif intent == 'open_smart_discard':
        allowed = salvage_page(scene) and target is unique_text(scene, '智能弃置', SMART_BUTTON)
    elif intent == 'clear_discard_rules':
        allowed = kind == 'smart' and target is unique_text(scene, '全部清除', CLEAR_RULES)
    elif intent == 'choose_unmatched_rule':
        allowed = kind == 'smart' and target is unique_text(scene, '不匹配任意推荐角色', UNMATCHED_RULE)
    elif intent == 'choose_zero_enhancement':
        allowed = kind == 'smart' and target is unique_text(scene, '0次', ZERO_RULE)
    elif intent == 'enable_protection':
        allowed = (kind == 'smart' and not protection_on(scene)
                   and unique_text(scene, '弃置保护', PROTECT_LABEL) is not None
                   and target is unique_text(scene, '未开启', PROTECT_STATE))
    elif intent == 'confirm_smart_rules':
        try:
            visible = read_count(scene, SMART_COUNT)
        except AutomationError:
            visible = 0
        allowed = (protection_on(scene) and visible > 0
                   and target is unique_text(scene, '确认', SMART_CONFIRM)
                   and unique_text(scene, '取消', CANCEL_BAND) is not None)
    elif intent == 'confirm_mark_discard':
        marked = state.get('marked')
        body = region_text(scene, (0.25, 0.25, 0.75, 0.70))
        allowed = (kind == 'batch' and type(marked) is int and marked > 0 and shows_count(body, marked)
                   and unique_text(scene, '取消', CANCEL_BAND) is not None
                   and target is unique_text(scene, '确认弃置', BATCH_CONFIRM))
    elif intent == 'open_quick_select':
        allowed = salvage_page(scene) and target is unique_text(scene, '快速选择', QUICK_BUTTON)
    elif intent == 'select_discarded':
        allowed = quick_dialog(scene) and target is unique_text(scene, '全选已弃置', DISCARDED_RULE)
    elif intent == 'select_four_star':
        allowed = (quick_dialog(scene) and target is unique_text(scene, '4星及以下', FOUR_STAR)
                   and normalize(target.text) != normalize('5星及以下'))
    elif intent == 'confirm_quick_select':
        allowed = quick_dialog(scene) and target is unique_text(scene, '确认', QUICK_CONFIRM)
    elif intent == 'request_decompose':
        pending = state.get('pending_count')
        allowed = (salvage_page(scene) and type(pending) is int and 0 < pending <= BATCH_LIMIT
                   and pending >= state.get('marked', 0)
                   and read_count(scene, SALVAGE_COUNT) == pending
                   and target is unique_text(scene, '分解', SALVAGE_BREAK))
    elif intent == 'confirm_decompose':
        pending = state.get('pending_count')
        allowed = type(pending) is int and target is decompose_confirm_token(scene, pending)
    elif intent == 'close_reward':
        allowed = target is reward_close_token(scene)
    elif intent == 'dismiss_dialog':
        allowed = kind in {'smart', 'batch', 'quick', 'decompose'} and target is unique_text(scene, '取消', CANCEL_BAND)
    if not allowed:
        raise AutomationError('遗器清理目标、数量或页面不符，未发送点击。')


def _live_dependencies():
    """Real window and OCR entry. Tests pass their own triple and never import Win32."""
    from .vision import Vision
    from .windows import find_game, launch
    return find_game, launch, Vision


class LiveRelicPort:
    """Foreground capture and token clicks for one weekly relic cleanup."""

    def __init__(self, window, vision, *, action_delay=1.0, sleeper=time.sleep):
        self.window = window
        self.vision = vision
        self.action_delay = action_delay
        self.sleeper = sleeper
        self._scene = None

    def scene(self):
        blank = None
        for _ in range(4):
            try:
                image, geometry = self.window.capture()
            except EmptyCapture as error:
                blank = error
                self.sleeper(0.5)
                continue
            scene = self.vision.read(image, geometry)
            scene.geometry = geometry
            if not scene.captured_at:
                scene.captured_at = time.monotonic()
            self._scene = scene
            return scene
        raise AutomationError('游戏画面持续空白，未发送遗器清理输入。') from blank

    def click(self, scene, token, intent):
        del intent  # Cleanup.guard_click already bound this token to the intent.
        if not isinstance(token, Token):
            raise AutomationError('遗器清理只允许点击已识别的文字控件。')
        if scene is not self._scene or time.monotonic() - scene.captured_at > 8:
            raise AutomationError('识别画面已经过期，请重新识别后操作。')
        if token not in scene.tokens or scene.geometry is None:
            raise AutomationError('遗器清理点击目标不在当前画面。')
        self.window.click(token.center[0], token.center[1], scene.geometry)
        self._scene = None
        self.sleeper(self.action_delay)

    def press_key(self, name='esc'):
        if name != 'esc':
            raise AutomationError('周遗器清理返回只允许 Esc。')
        expected = self._scene.geometry if self._scene is not None else None
        self.window.key('esc', expected=expected)
        self._scene = None
        self.sleeper(self.action_delay)

    def press_escape(self):
        self.press_key('esc')

    def _resting(self, scene):
        if modal_kind(scene) or salvage_page(scene) or bag_page(scene) or relic_bag_page(scene):
            return False
        from .workflows import DailyWorkflow
        return bag_target(scene) is not None or DailyWorkflow._phone(scene)

    def go_home(self):
        """Leave the relic pages. Stop once a phone menu is visible, or after five returns."""
        for _ in range(5):
            scene = self.scene()
            if self._resting(scene):
                return
            if not (salvage_page(scene) or bag_page(scene) or relic_bag_page(scene) or modal_kind(scene)):
                return
            self.press_escape()

    def return_home(self):
        self.go_home()


def open_live_port(settings, *, dependencies=None, sleeper=time.sleep, attempts=120):
    """Focus a running game, or launch StarRail.exe and wait for its window.

    Clicks stay on this port. The daily Context rejects the bag page, and this
    command is not part of --run or --plan.
    """
    if type(attempts) is not int or isinstance(attempts, bool) or attempts < 1:
        raise AutomationError('周遗器清理的启动等待无效。')
    find_game, launch_game, vision_type = dependencies or _live_dependencies()
    try:
        window = find_game(settings.game_path)
    except AutomationError:
        launch_game(settings.game_path)
        window = None
        for _ in range(attempts):
            sleeper(1)
            try:
                window = find_game(settings.game_path)
                break
            except AutomationError:
                window = None
        if window is None:
            raise AutomationError(f'启动后{attempts}秒仍未找到游戏窗口，已停止。')
    window.focus()
    delay = settings.action_delay
    if type(delay) not in (int, float):
        delay = 1.0
    return LiveRelicPort(window, vision_type(settings.ocr_confidence), action_delay=delay, sleeper=sleeper)


class Cleanup:
    def __init__(self, port, smart: bool):
        self.port = port
        self.smart = smart is True
        self.state = {'pending_count': 0, 'marked': 0}
        self.clicks = []
        self.decompose_confirmed = 0
        self.decomposed_batches = 0
        self.salvage_entered = False
        self.exit_attempted = False
        self.exit_error = None

    def _click(self, token, intent):
        scene = self.port.scene()
        guard_click(scene, token, intent, self.state)
        self.clicks.append((intent, token.text))
        self.port.click(scene, token, intent)

    def _click_text(self, label, roi, intent):
        token = unique_text(self.port.scene(), label, roi)
        if token is None:
            raise AutomationError(f'未找到或无法点击：{label}')
        self._click(token, intent)

    def salvage_count(self):
        if not salvage_page(self.port.scene()):
            raise AutomationError('无法确认遗器分解页')
        return read_count(self.port.scene(), SALVAGE_COUNT)

    def enter(self):
        if salvage_page(self.port.scene()):
            return
        if not relic_bag_page(self.port.scene()):
            if bag_page(self.port.scene()):
                self._click_text('遗器', TAB_ROW, 'open_relic_tab')
            else:
                target = bag_target(self.port.scene())
                if target is None:
                    raise AutomationError('无法确认背包遗器入口')
                self._click(target, 'open_bag')
                if not relic_bag_page(self.port.scene()):
                    if not bag_page(self.port.scene()):
                        raise AutomationError('打开背包后未进入遗器页')
                    self._click_text('遗器', TAB_ROW, 'open_relic_tab')
            if not relic_bag_page(self.port.scene()):
                raise AutomationError('未进入遗器背包，停止清理')
        self._click_text('分解', BAG_BREAK, 'open_salvage')
        if not salvage_page(self.port.scene()):
            raise AutomationError('无法进入遗器分解页')

    def ensure_protection(self):
        if protection_on(self.port.scene()):
            return
        if unique_text(self.port.scene(), '弃置保护', PROTECT_LABEL) is None:
            raise AutomationError('无法确认弃置保护控件')
        switch = unique_text(self.port.scene(), '未开启', PROTECT_STATE)
        if switch is None:
            raise AutomationError('无法确认弃置保护开关状态')
        self._click(switch, 'enable_protection')
        if not protection_on(self.port.scene()):
            raise AutomationError('无法确认弃置保护已开启')

    def mark_smart_discard(self):
        self._click_text('智能弃置', SMART_BUTTON, 'open_smart_discard')
        if modal_kind(self.port.scene()) != 'smart':
            raise AutomationError('未进入智能弃置弹窗')
        self._click_text('全部清除', CLEAR_RULES, 'clear_discard_rules')
        self._click_text('不匹配任意推荐角色', UNMATCHED_RULE, 'choose_unmatched_rule')
        self._click_text('0次', ZERO_RULE, 'choose_zero_enhancement')
        self.ensure_protection()
        count = read_count(self.port.scene(), SMART_COUNT)
        if count == 0:
            self.port.press_escape()
            if not salvage_page(self.port.scene()):
                raise AutomationError('关闭智能弃置后未返回遗器分解页')
            return 0
        self.state['marked'] = count
        self._click_text('确认', SMART_CONFIRM, 'confirm_smart_rules')
        if modal_kind(self.port.scene()) != 'batch':
            raise AutomationError('未出现批量弃置确认弹窗')
        if unique_text(self.port.scene(), '确认弃置', BATCH_CONFIRM) is None:
            raise AutomationError('批量弃置模式未选中')
        self._click_text('确认弃置', BATCH_CONFIRM, 'confirm_mark_discard')
        if not salvage_page(self.port.scene()):
            raise AutomationError('确认弃置后未返回遗器分解页')
        return count

    def select_for_salvage(self, include_discarded):
        if not salvage_page(self.port.scene()):
            raise AutomationError('无法确认遗器分解页')
        self._click_text('快速选择', QUICK_BUTTON, 'open_quick_select')
        if not quick_dialog(self.port.scene()):
            raise AutomationError('未进入快速选择弹窗')
        if include_discarded:
            self._click_text('全选已弃置', DISCARDED_RULE, 'select_discarded')
        self._click_text('4星及以下', FOUR_STAR, 'select_four_star')
        self._click_text('确认', QUICK_CONFIRM, 'confirm_quick_select')
        if not salvage_page(self.port.scene()):
            raise AutomationError('快速选择后未返回遗器分解页')
        return self.salvage_count()

    def decompose(self, count):
        self.state['pending_count'] = count
        if self.salvage_count() != count:
            raise AutomationError('分解前数量已变化，未分解')
        self._click_text('分解', SALVAGE_BREAK, 'request_decompose')
        token = decompose_confirm_token(self.port.scene(), count)
        if token is None:
            raise AutomationError('分解确认未显示相同数量的遗器预览，未分解')
        self._click(token, 'confirm_decompose')
        self.decompose_confirmed += 1
        close = reward_close_token(self.port.scene())
        if close is None:
            raise AutomationError('分解后未看到遗器残骸获得提示，结果未核实')
        self._click(close, 'close_reward')
        if not salvage_page(self.port.scene()):
            raise AutomationError('遗器分解未完成')

    def _attempt_close_dialog(self):
        for _ in range(3):
            scene = self.port.scene()
            kind = modal_kind(scene)
            if kind is None and not self.salvage_entered:
                return
            acted = False
            if kind == 'reward':
                close = reward_close_token(scene)
                if close is not None:
                    self._click(close, 'close_reward')
                    acted = True
            elif kind in {'smart', 'batch', 'quick', 'decompose'}:
                cancel = unique_text(scene, '取消', CANCEL_BAND)
                if cancel is not None:
                    self._click(cancel, 'dismiss_dialog')
                    acted = True
            if not acted and (kind is not None or self.salvage_entered):
                self.port.press_escape()
                self.salvage_entered = False
                acted = True
            if not acted or self.port.scene() is scene:
                return

    def return_to_safe(self):
        try:
            self._attempt_close_dialog()
        except Exception as error:
            self.exit_error = error
        try:
            self.port.return_home()
        except Exception as error:
            self.exit_error = self.exit_error or error
            return
        self.exit_attempted = True

    def _run_batches(self):
        self.enter()
        self.salvage_entered = True
        for _batch in range(MAX_BATCHES):
            if self.salvage_count() != 0:
                raise AutomationError('分解页已有其他选中的遗器，停止清理')
            marked = self.mark_smart_discard() if self.smart else 0
            self.state['marked'] = marked
            selected = self.select_for_salvage(self.smart)
            if selected < marked:
                raise AutomationError(
                    f'快速选择后已选数量少于智能弃置数量：{selected} < {marked}，停止清理')
            if selected == 0:
                return
            self.decompose(selected)
            self.decomposed_batches += 1
            if selected < BATCH_LIMIT:
                return
        raise AutomationError('连续七批仍有待分解遗器，停止清理')

    def run(self):
        self.exit_error = None
        self.exit_attempted = False
        try:
            self._run_batches()
            return True
        finally:
            self.return_to_safe()


def perform(settings, store, now, *, invoked=False, port_factory=None):
    validate_settings(settings)
    if invoked is not True or settings.break_down_level_four_relicset is not True:
        reason = 'not_invoked' if invoked is not True else 'disabled'
        return {'status': 'skipped', 'operation': OPERATION, 'reason': reason,
                'timestamp_written': False, 'weekly_relic_cleanup_timestamp': None}
    timestamp = store.read()
    reason = decision(settings, timestamp, now, invoked=True)
    if reason != 'run':
        return {'status': 'skipped', 'operation': OPERATION, 'reason': reason,
                'timestamp_written': False, 'weekly_relic_cleanup_timestamp': timestamp}
    if port_factory is None:
        raise AutomationError('周遗器清理缺少画面入口，未启动游戏。')
    port = port_factory(settings)
    cleanup = Cleanup(port, settings.weekly_relic_smart_discard_enable)
    cleanup.run()
    if cleanup.exit_error is not None or cleanup.exit_attempted is not True:
        raise AutomationError('周遗器清理结束时未能尝试返回已知画面，未记录完成时间。')
    stamp = int(now.timestamp())
    store.write(stamp)
    return {'status': 'success', 'operation': OPERATION, 'reason': 'completed',
            'timestamp_written': True, 'weekly_relic_cleanup_timestamp': stamp,
            'decomposed_batches': cleanup.decomposed_batches,
            'decompose_confirmed': cleanup.decompose_confirmed}
