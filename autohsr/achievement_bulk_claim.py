"""Foreground-only bridge from native captures to one achievement bulk claim."""
from dataclasses import asdict, replace
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import time

import numpy as np

from .achievement_bulk_protocol import (
    AchievementBulkReplay, BulkClaimResult, ClaimFrame, ClaimScope, MAX_AGE,
    _FILES, _SEND_FILES, _read_jade_balance, _write_once,
)
from .achievement_pages import (
    ACHIEVEMENT_CATEGORIES, _CAROUSEL, achievement_bulk_claim_target, achievement_jade_overlay_amount,
    achievement_overview_signature, achievement_receipt_fields,
)
from .currency_wars_identity import AccountNotObserved, checked_account_key
from .currency_wars_prepare import trusted
from .daily_event_observe import read_event_installation
from .daily_observe import ACHIEVEMENT_CLAIM_OPERATION as OPERATION
from .models import AutomationError, EmptyCapture, InputInterrupted, Stopped, TaskResult, normalize
from .storage import hold_read_sources, replace_file
from .workflow_screen import _CurrentFrames
from .workflows import DailyWorkflow


SAFE_NEXT = '请查看成就领奖回执和当前画面，未决动作保留原记录，不重放。'
_PENDING = 'achievement-bulk-pending.json'
_TERMINAL = 'achievement-bulk-terminal.json'
_MAX_CAPTURES = 12
_MAX_EVIDENCE = 64 * 1024 * 1024
_JOURNAL_FILES = (*_FILES.values(), *_SEND_FILES.values())


def initial_record():
    return dict(schema=1, client_version=None, account_verified=False, samples={}, **asdict(BulkClaimResult()))


def _json(value):
    return json.dumps(value, sort_keys=True, allow_nan=False).encode('utf-8')


def _bounded(path, maximum):
    with path.open('rb') as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise ValueError('成就领奖证据超过大小上限。')
    return raw


def _verified_file(directory, name, maximum):
    path = directory / name
    if path.parent != directory or path.resolve(strict=True) != path:
        raise AutomationError('成就领奖证据路径与原运行不符。')
    return sha256(_bounded(path, maximum)).hexdigest()


def _verify_files(directory, rows):
    for row in rows:
        if _verified_file(directory, row['file'], _MAX_EVIDENCE) != row['sha256']:
            raise AutomationError('成就领奖的原始截图已改变。')


def _journal_hashes(directory):
    return {name: _verified_file(directory, name, 8192) for name in _JOURNAL_FILES}


def preflight(root):
    """A previous unresolved attempt blocks a fresh run before window discovery."""
    marker = root / _PENDING
    if not os.path.lexists(marker):
        return
    try:
        if marker.resolve(strict=True) != marker:
            raise ValueError()
        raw = _bounded(marker, 4096)
        pending = json.loads(raw)
        run = pending['run']
        if (pending != {'operation': OPERATION, 'run': run}
                or not re.fullmatch(r'\d{8}_\d{6}_\d{6}', run)):
            raise ValueError()
        directory = root / run
        if directory.resolve(strict=True) != directory:
            raise ValueError()
        paths = (directory / _TERMINAL, directory / 'report.json')
        if any(path.resolve(strict=True) != path for path in paths):
            raise ValueError()
        terminal = json.loads(_bounded(paths[0], 4096))
        report = _bounded(paths[1], _MAX_EVIDENCE)
        saved = json.loads(report)
        if saved['operation'] != OPERATION or saved['report_saved'] is not True:
            raise ValueError()
        record = saved[OPERATION]
        completed = (record['bulk_input'] == record['confirm_input'] == 'sent'
                     and saved['status'] == 'success' and record['overview_controls_cleared'] is True)
        clear = (record['bulk_input'] == 'not_sent' and record['confirm_input'] == 'not_sent'
                 or completed)
        journal = _journal_hashes(directory) if completed else {}
        if terminal != dict(marker=sha256(raw).hexdigest(), report=sha256(report).hexdigest(), journal=journal):
            raise ValueError()
        if completed:
            for rows in record['samples'].values():
                _verify_files(directory, rows)
        if not clear or _bounded(marker, 4096) != raw:
            raise ValueError()
        marker.unlink()
    except (AutomationError, OSError, ValueError, KeyError, TypeError):
        raise AutomationError('已有未决成就领奖意图，请人工核对原运行；未访问游戏。') from None


def _crop(image, region):
    h, w = image.shape[:2]
    x1, y1, x2, y2 = (round(value * size) for value, size in zip(region, (w, h, w, h)))
    return image[y1:y2, x1:x2]


def _jade_icon(scene):
    """Narrow 16:9 warp counter check, paired with the dedicated balance reader."""
    import cv2
    h, w = scene.image.shape[:2]
    if not 1.72 <= w / h <= 1.84:
        return False
    crown = _crop(scene.image, (.854, .041, .867, .060))
    base = _crop(scene.image, (.850, .063, .870, .080))
    if not crown.size or not base.size:
        return False
    top = cv2.cvtColor(crown, cv2.COLOR_BGR2HSV)
    bottom = cv2.cvtColor(base, cv2.COLOR_BGR2HSV)
    pale = (top[:, :, 1] < 95) & (top[:, :, 2] > 190)
    blue = ((bottom[:, :, 0] >= 79) & (bottom[:, :, 0] <= 115)
            & (bottom[:, :, 1] > 70) & (bottom[:, :, 2] > 155))
    return float(pale.mean()) > .35 and float(blue.mean()) > .22


def _card_locations(scene):
    return {normalize(t.text): t.center[0] for t in trusted(scene, .85).tokens
            if t.within(_CAROUSEL) and normalize(t.text) in ACHIEVEMENT_CATEGORIES}


def _red_pixels(image):
    b, g, r = np.moveaxis(image.astype(np.int16), -1, 0)
    return (r >= 140) & (r - b >= 60) & (r - g >= 65)


def _marked_cards(scene):
    import cv2
    h, w = scene.image.shape[:2]
    if not 1.72 <= w / h <= 1.84:
        return {}
    markers = {}
    red = _red_pixels(scene.image)
    red[:round(h * .19)] = False
    red[round(h * .35):] = False
    _, _, stats, centers = cv2.connectedComponentsWithStats(red.astype(np.uint8))
    cards = _card_locations(scene)
    for (x, y, width, height, _), (cx, _) in zip(stats[1:], centers[1:]):
        if not (.010 <= width / w <= .027 and .019 <= height / h <= .055):
            continue
        owners = [name for name, center in cards.items() if .022 <= cx / w - center <= .064]
        region = (x / w, y / h, (x + width) / w, (y + height) / h)
        patch = _crop(scene.image, region)
        if len(owners) == 1 and float(np.mean(patch.min(axis=2) > 195)) > .015:
            name = owners[0]
            if name in markers:
                return {}
            markers[name] = region
    return markers


def _cleared(scene, original, markers):
    if not markers:
        return False
    before, after = _card_locations(original), _card_locations(scene)
    for name, region in markers.items():
        if name not in after or abs(after[name] - before[name]) > .008:
            return False
        patch = _crop(scene.image, region)
        if not patch.size or float(_red_pixels(patch).mean()) > .025 or float(patch.std()) < 8:
            return False
    return True


class AchievementBulkClaim:
    def __init__(self, context):
        self.c = context
        self.record = initial_record()
        self.directory = Path(context.report.run_dir).resolve()
        self.reader = self.replay = self.current = self._installation = None
        self.marker = self.directory.parent / _PENDING
        self.marker_raw = None
        self._submission = None
        self._publication_frames = ()
        self._attempted = set()

    def _guard(self, *, installation=False):
        self.reader.guard()
        if installation:
            if read_event_installation(self.reader.window) != self._installation:
                raise AutomationError('当前游戏客户端安装来源或版本已变化。')
            self.reader.guard()
        runner = self.c.runner
        if runner.stop_requested or self.reader.window.emergency_pressed():
            raise Stopped('成就领奖已停止。')
        if runner.input_epoch != self.reader.epoch:
            raise InputInterrupted('成就领奖的输入代次已变化。')

    def _account(self, scene):
        visible = trusted(scene, .65)
        if DailyWorkflow._login_blocked(visible) or DailyWorkflow._supply_overlay(visible):
            raise AutomationError('当前游戏处于登录、更新或列车补给页面。')
        return checked_account_key(scene, self.c.settings.ocr_confidence)

    def _capture(self):
        self._guard()
        scene = self.c.snapshot()
        self._guard()
        geometry = self.reader.geometry
        if (self.c.last_scene is not scene or self.c.scene_epoch != self.reader.epoch or scene.geometry != geometry
                or not 0 <= time.monotonic() - scene.captured_at <= MAX_AGE
                or not isinstance(scene.image, np.ndarray) or scene.image.dtype != np.uint8
                or scene.image.shape != (geometry.height, geometry.width, 3)):
            raise AutomationError('成就领奖缺少当前窗口的新鲜客户区。')
        account = self._account(scene)
        scope = ClaimScope(account, self.reader.window.hwnd, self.reader.epoch, self.record['client_version'])
        if self.replay is None:
            self.replay = AchievementBulkReplay(self.directory, scope)
            self.record['account_verified'] = True
        elif scope != self.replay.scope:
            raise AutomationError('成就领奖期间当前账号已改变。')
        self.current = ClaimFrame(scope, self.c.capture_sequence, scene)
        return self.current

    def _collect(self, count, read):
        frames, value = [], None
        for index in range(_MAX_CAPTURES):
            if index:
                self.c.sleep(.20)
            try:
                frame = self._capture()
            except (AccountNotObserved, EmptyCapture):
                frames, value = [], None
                continue
            observed = read(frame)
            if observed is None:
                frames, value = [], None
                continue
            if observed != value or frames and frames[-1].sequence + 1 != frame.sequence:
                frames = []
            value = observed
            frames.append(frame)
            if len(frames) == count:
                return tuple(frames), value
        return (), None

    def _save(self, name, frames):
        rows = []
        for frame in frames:
            path, digest = self.c.evidence(frame.scene, f'achievement_{name}', with_sha256=True)
            path = Path(path)
            if path.resolve(strict=True) != path or path.parent != self.directory:
                raise AutomationError('成就领奖截图不在本次运行目录。')
            rows.append(dict(file=path.name, sha256=digest, sequence=frame.sequence))
        self.record['samples'][name] = rows
        return rows

    def _mark_pending(self):
        raw = _json(dict(operation=OPERATION, run=self.directory.name))
        _write_once(self.marker, raw)
        self.marker_raw = raw

    def _send(self, action, frames):
        self._guard(installation=True)
        rows = self._save(action, frames)
        if action == 'claim':
            self._mark_pending()
            reserve = self.replay.reserve_claim
        else:
            reserve = self.replay.reserve_confirmation
        digest = reserve(frames[:2], frames[-1], time.monotonic())
        self._submission = (action, frames, rows, digest)
        self.c.achievement_bulk_input(frames[-1].scene, action)

    def _sync(self):
        if self.replay is not None:
            self.record.update(asdict(self.replay.result))
            for action, field in (('claim', 'bulk_input'), ('confirm', 'confirm_input')):
                if action in self._attempted and self.record[field] == 'not_sent':
                    self.record[field] = 'unknown'
        if self.c.runner.stop_requested:
            self.record['stopped'] = True

    def dispatch(self, scene, action):
        if self._submission is None or self._submission[0] != action:
            raise AutomationError('成就领奖缺少本次专用提交。')
        _, frames, rows, digest = self._submission
        self._submission = None
        current = frames[-1]
        if current is not self.current or scene is not current.scene:
            raise AutomationError('成就领奖发送来源已过期。')
        previous = (self.record['samples']['claim'] + self.record['samples']['receipt']) if action == 'confirm' else []
        evidence = [*previous, *rows]
        paths = (self.marker, self._installation.source, *(self.directory / row['file'] for row in evidence))
        sent_at = None

        def authorize():
            self._guard(installation=True)
            if (self.c.last_scene is not scene or self.c.capture_sequence != current.sequence
                    or self.c.scene_epoch != current.scope.input_epoch
                    or any(self._account(frame.scene) != current.scope.account_key for frame in frames)
                    or _bounded(self.marker, 4096) != self.marker_raw):
                raise AutomationError('成就领奖当前账号、画面或排他意图已变化。')
            _verify_files(self.directory, evidence)
            return self.replay.authorize_submission(action, current, time.monotonic())

        def before_submit():
            nonlocal sent_at
            if authorize() != target:
                raise AutomationError('成就领奖目标在原生提交前已变化。')
            self._guard()
            sent_at = time.monotonic()
            self._attempted.add(action)
            self.c.last_scene, self.c._scroll_anchor = None, None

        try:
            with self.replay.hold_submission(action, paths):
                target = authorize()
                self.reader.window.click(*target.center, scene.geometry, before_submit=before_submit)
            if sent_at is None:
                raise AutomationError('成就领奖缺少原生提交标记。')
        except BaseException:
            try:
                self.replay.record_send(digest, 'not_sent' if sent_at is None else 'unknown',
                                        sent_at if sent_at is not None else time.monotonic(), scope=current.scope)
            finally:
                self._sync()
            raise
        self.replay.record_send(digest, 'sent', sent_at, scope=current.scope)
        self._sync()

    def _partial(self, detail):
        return TaskResult(OPERATION, 'partial', detail)

    @staticmethod
    def _claim_view(frame):
        if achievement_bulk_claim_target(frame.scene) is not None:
            return achievement_overview_signature(frame.scene)
        return None

    @staticmethod
    def _wallet(frame):
        return _read_jade_balance(replace(frame, jade_icon_verified=_jade_icon(frame.scene)))

    @staticmethod
    def _wallet_frames(frames):
        return tuple(replace(frame, jade_icon_verified=True) for frame in frames)

    def run(self):
        try:
            return self._run()
        finally:
            self._sync()

    def _run(self):
        self.reader = _CurrentFrames(self.c)
        self._installation = read_event_installation(self.reader.window)
        self.reader.guard()
        version = self._installation.version
        self.record['client_version'] = version
        if version != '4.6.0':
            raise AutomationError('当前客户端版本未校准成就领奖。')
        ready, initial = self._collect(2, lambda f: self._claim_view(f) or self._wallet(f))
        if not ready:
            raise AutomationError('请手动打开有金色一键按钮的成就总览并保持游戏前台。')
        if self._claim_view(ready[-1]) is None:
            self.replay.observe_balance_before(self._wallet_frames(ready))
            self._save('balance_before', ready)
            self.c.log('已记星琼基线，请手动打开成就总览。')
            ready, initial = self._collect(2, self._claim_view)
        if not ready:
            return self._partial('已记录星琼基线，未核实可领取成就总览。')
        third = self._capture()
        original = ready[-1].scene
        markers = _marked_cards(original)
        if markers.keys() != _marked_cards(ready[0].scene).keys():
            markers = {}
        self._send('claim', (*ready, third))

        def receipt(frame, known=None):
            fields = achievement_receipt_fields(frame.scene, established_total=known)
            return fields[0] if fields is not None else None

        received, total = self._collect(2, receipt)
        if not received or not self.replay.observe_receipt(received):
            return self._partial('一键领取已发送，专属成就奖励明细待核实。')
        self._save('receipt', received)
        confirm, _ = self._collect(3, lambda f: total if receipt(f, total) == total else None)
        if not confirm:
            return self._partial('专属明细已核实，确认按钮待重新核对。')
        self._send('confirm', confirm)
        overlay, _ = self._collect(2, lambda f: total if achievement_jade_overlay_amount(f.scene) == total else None)
        if not overlay or not self.replay.observe_overlay(overlay):
            return self._partial('专属确认已发送，星琼物品遮罩待核实。')
        self._save('overlay', overlay)
        self.c.log('已核实星琼物品遮罩，请手动关闭提示，等待回页核对。')
        returned, _ = self._collect(2, lambda f: initial if achievement_overview_signature(f.scene) == initial else None)
        if not returned or not self.replay.observe_return(tuple(
                replace(f, controls_cleared=_cleared(f.scene, original, markers)) for f in returned)):
            return self._partial('物品展示已核实，关闭后的成就总览待核实。')
        self._save('return', returned)
        self._publication_frames = returned
        if self.replay.result.jade_balance_before is not None:
            self.c.log('已核实回页。可手动打开原跃迁页核对星琼余额。')
            wallet, _ = self._collect(2, self._wallet)
            if wallet and self.replay.observe_balance_after(self._wallet_frames(wallet)):
                self._save('balance_after', wallet)
                self._publication_frames = wallet
        return TaskResult(OPERATION, 'ok', '已核实专属明细、星琼物品展示及同账号回页。')

    def save_verified_report(self, temporary, write_report):
        self._sync()
        report = self.c.report
        paths = tuple(self.directory / row['file'] for rows in self.record['samples'].values() for row in rows)

        def check():
            self._guard(installation=True)
            for rows in self.record['samples'].values():
                _verify_files(self.directory, rows)
            frame = self.current
            if (frame is None or frame.scene is not self.c.last_scene or frame.sequence != self.c.capture_sequence
                    or self.c.scene_epoch != self.reader.epoch
                    or self._account(frame.scene) != self.replay.scope.account_key
                    or not 0 <= time.monotonic() - self._publication_frames[0].scene.captured_at <= MAX_AGE
                    or _bounded(self.marker, 4096) != self.marker_raw):
                raise AutomationError('成就领奖报告发布前账号已变化。')
            self._guard()

        try:
            if report.status == 'success':
                check()
            write_report()
            payload = _bounded(temporary, _MAX_EVIDENCE)
            completed = report.status == 'success' and self.record['overview_controls_cleared']
            journal = _journal_hashes(self.directory) if completed else {}
            if self.marker_raw is not None and (not self._attempted or completed):
                _write_once(self.directory / _TERMINAL, _json(
                    dict(marker=sha256(self.marker_raw).hexdigest(), report=sha256(payload).hexdigest(),
                         journal=journal)))

            def check_publication():
                if (_bounded(temporary, _MAX_EVIDENCE) != payload
                        or completed and _journal_hashes(self.directory) != journal):
                    raise AutomationError('成就领奖原动作记录或报告临时文件已变化。')
                check()

            held = (*paths, *(self.directory / name for name in journal))
            if self.marker_raw is not None:
                held = (*held, self.marker)
            if report.status == 'success':
                held = (*held, self._installation.source)
            with hold_read_sources(held):
                replace_file(temporary, self.directory / 'report.json',
                             before_replace=check_publication if report.status == 'success' else None)
        except (AutomationError, ValueError) as error:
            self.record['account_verified'] = False
            if isinstance(error, Stopped):
                self.c.runner.stop()
                self.record['stopped'] = True
            report.status = 'stopped' if isinstance(error, Stopped) else 'partial'
            report.failure_task, report.error = OPERATION, str(error)
            report.results[-1] = self._partial('已保留发送和反馈，发布前的当前来源待核对。')
            write_report()
            replace_file(temporary, self.directory / 'report.json')
