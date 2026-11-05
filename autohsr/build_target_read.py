"""Open the observed Survival Index tab and capture its material panel."""
from pathlib import Path
import time

from .config import RESOURCE_ROOT
from .currency_wars_identity import AccountNotObserved, account_key
from .currency_wars_prepare import trusted
from .dungeon_workflow import guide_rows
from .dungeons import CATEGORIES, load_catalogue
from .models import FULL, AutomationError, EmptyCapture, InputInterrupted, Stopped, TaskResult, normalize
from .policy import FORBIDDEN, replenishment_dialog
from .workflows import TITLE


ENTRY = (.15, .265, .24, .33)
SECTIONS = (.36, .25, .70, .84)
MODAL_AREA = (.24, .18, .95, .98)
CHANGE_AREA = (.32, .15, .75, .43)
FRAGMENT_CONFIDENCE = .80
NARROW_NOISE_WIDTH = .005
SHORTFALL = '培养还需获取资源'
RECOMMENDATIONS = ('隧洞遗器推荐', '位面饰品推荐')
AUTHENTICATION = ('验证码', '账号登录', '扫码登录', '用户协议', '资源下载', '更新游戏')
MODAL = ('提示', '确认', '确定', '取消', '获得物品', '获得途径', '选择角色', '列车补给',
         '点击空白处关闭', '点击任意位置关闭', '点击空白处继续', '开始挑战')


def _has_split_label(scene, labels, roi, *, exact=True):
    """Match a known label across neighboring OCR boxes on one visual line."""
    parts = [(token, normalize(token.text)) for token in scene.tokens if token.within(roi)]
    parts = sorted(((token, text) for token, text in parts if text), key=lambda part: part[0].box[0])
    for index, (first, text) in enumerate(parts):
        if first.score < FRAGMENT_CONFIDENCE:
            continue
        if exact:
            endings = tuple(label[len(text):] for label in labels if text != label and label.startswith(text))
        else:
            endings = tuple(label[size:] for label in labels for size in range(1, len(label))
                            if text.endswith(label[:size]))
        if not endings:
            continue
        left = first
        line_top, line_bottom = first.box[1], first.box[3]
        shortest = line_bottom - line_top
        for right, suffix in parts[index + 1:]:
            gap = right.box[0] - left.box[2]
            if gap > .014:
                break
            top = max(line_top, right.box[1])
            bottom = min(line_bottom, right.box[3])
            height = min(shortest, right.box[3] - right.box[1])
            if gap < -.006 or bottom - top < .5 * height:
                continue
            if right.score < FRAGMENT_CONFIDENCE:
                if right.box[2] - right.box[0] <= NARROW_NOISE_WIDTH:
                    continue  # The next strong box must still be close to left.
                break
            if suffix in endings or (not exact and any(suffix.startswith(end) for end in endings)):
                return True
            endings = tuple(end[len(suffix):] for end in endings if end.startswith(suffix))
            if not endings:
                break
            left = right
            line_top, line_bottom, shortest = top, bottom, height
    return False


class BuildTargetRead:
    def __init__(self, ctx):
        self.ctx = ctx
        self.epoch = ctx.runner.input_epoch
        self.confidence = max(.85, ctx.settings.ocr_confidence)
        self.catalogue = set(load_catalogue(RESOURCE_ROOT / 'assets' / 'dungeons.json'))
        self.account = None
        self.geometry = None
        self.source = None
        self.record = {'entry_input': 'not_sent', 'page_verified': False}

    def _current_account(self, scene):
        try:
            key = account_key(scene, self.confidence)
        except AccountNotObserved:
            key = None
        age = time.monotonic() - scene.captured_at
        if self.ctx.runner.stop_requested:
            raise Stopped('任务已停止。')
        if self.ctx.runner.input_epoch != self.epoch or self.ctx.scene_epoch != self.epoch:
            raise InputInterrupted('培养目标观察的输入代次已改变，请重新核对当前页面。')
        if (scene is not self.ctx.last_scene or scene.geometry is None or scene.captured_at <= 0
                or not 0 <= age <= 8):
            raise AutomationError('培养目标观察缺少当前新鲜画面。')
        if self.geometry is None:
            self.geometry = scene.geometry
        elif scene.geometry != self.geometry:
            raise AutomationError('培养目标观察期间窗口位置或大小已改变。')
        if key is None:
            return False
        if self.account is None:
            self.account = key
        elif self.account != key:
            raise AutomationError('培养目标观察期间当前账号已改变。')
        return True

    def _classify(self, scene):
        fragments = trusted(scene, 0.)
        if (replenishment_dialog(scene) or scene.has(AUTHENTICATION)
                or scene.has(MODAL, MODAL_AREA, exact=True)
                or scene.has('更换培养目标', CHANGE_AREA, exact=True)
                or _has_split_label(fragments, AUTHENTICATION, FULL, exact=False)
                or _has_split_label(fragments, MODAL, MODAL_AREA)
                or _has_split_label(fragments, ('更换培养目标',), CHANGE_AREA)
                or scene.has(FORBIDDEN + ('每日实训', '旷宇纷争', '行动摘要'), TITLE, exact=True)):
            return None, None
        page = trusted(scene, self.confidence)
        if not (page.has('星际和平指南', TITLE, exact=True) and page.has('生存索引', TITLE, exact=True)):
            return None, None
        entries = [token for token in scene.tokens if token.within(ENTRY) and normalize(token.text) == '培养目标']
        if len(entries) != 1 or entries[0] not in page.tokens:
            return None, None
        headings = (SHORTFALL, *RECOMMENDATIONS)
        panel = page.has(SHORTFALL, SECTIONS, exact=True)
        catalogue_row = any(mission in self.catalogue for category in CATEGORIES
                            for mission, _ in guide_rows(page, category.key))
        if panel and not catalogue_row:
            return 'panel', entries[0]
        if (catalogue_row and not scene.has(headings, SECTIONS, exact=True)
                and not _has_split_label(fragments, headings, SECTIONS)):
            return 'catalogue', entries[0]
        return None, None

    def _observe(self, *, after=None):
        previous = None
        for attempt in range(8):
            if attempt:
                self.ctx.sleep(.35)
            try:
                scene = self.ctx.snapshot()
            except EmptyCapture:
                previous = None
                continue
            self.ctx.checkpoint()
            if not self._current_account(scene):
                previous = None
                continue
            kind, entry = self._classify(scene)
            if kind is None or after is not None and (kind != 'panel' or scene.captured_at <= after.captured_at):
                previous = None
                continue
            if previous is not None:
                old_kind, old_entry, old_scene = previous
                if (scene is not old_scene and old_scene.captured_at < scene.captured_at
                        and 0 <= time.monotonic() - old_scene.captured_at <= 8 and kind == old_kind
                        and all(abs(a - b) <= .01 for a, b in zip(entry.center, old_entry.center))):
                    return scene, kind
            previous = kind, entry, scene
        if after is not None:
            raise AutomationError('培养目标入口已发送，未从连续新画面核实到页。')
        raise AutomationError('未从连续新画面核实生存索引、培养目标入口及同一账号。')

    def _save(self, scene, label):
        path = self.ctx.evidence(scene, label)
        if path is None or not Path(path).is_file():
            raise AutomationError('培养目标画面未保存。')
        return Path(path).name

    def authorize_entry(self, scene):
        if (scene is not self.source or self.record['entry_input'] != 'not_sent'
                or not self.record.get('entry_evidence')):
            raise AutomationError('缺少本次培养目标入口的当前来源。')
        kind, entry = self._classify(scene)
        if kind != 'catalogue' or not self._current_account(scene):
            raise AutomationError('当前生存索引未核实唯一培养目标入口及原账号。')
        return entry

    def run(self):
        if self.ctx.report.operation != 'build_target_read' or getattr(self.ctx, 'build_target_reader', None) is not None:
            raise AutomationError('培养目标读取需要独立运行入口及单次观察。')
        self.ctx.build_target_reader = self
        self.ctx.report.build_target = self.record
        scene, kind = self._observe()
        if kind == 'catalogue':
            self.source = scene
            self.record['entry_evidence'] = self._save(scene, 'build_target_entry')
            self.ctx.build_target_entry_input(scene)
            self.ctx.sleep(self.ctx.settings.action_delay)
            scene, _ = self._observe(after=self.source)
        self.record['panel_evidence'] = self._save(scene, 'build_target_panel')
        self.ctx.checkpoint()
        self.ctx.window.guard(scene.geometry)
        if not self._current_account(scene):
            raise AutomationError('保存培养目标页后无法核实当前账号。')
        self.record['page_verified'] = True
        return TaskResult('build_target_read', 'ok', '已核实培养目标页并保存本地证据。材料缺口与副本来源待校准。')
