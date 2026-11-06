"""Observe preparation pages and authorize the limited existing level selection."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import time

from .challenge_account import verified_account
from .currency_wars_identity import AccountNotObserved
from .models import AutomationError, EmptyCapture, InputInterrupted, Stopped, TaskResult
from .storage import hold_read_sources, replace_file

OPERATION = 'challenge_prepare'
APOCALYPTIC_MODE = 'apocalyptic_shadow'
MAX_BYTES = 8 * 1024 * 1024
MAX_PNG_BYTES = 64 * 1024 * 1024
MAX_SCENE_AGE = 8
UID_VETO_FLOOR = .65


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _pixels(scene):
    image = scene.image
    return hashlib.sha256(str(tuple(image.shape)).encode('ascii') + image.tobytes()).hexdigest()


@dataclass(frozen=True)
class PreparationAction:
    intent: str
    level: int
    target: object


@dataclass(frozen=True)
class _ObservedFrame:
    scene: object
    observation: object
    source: dict


class ChallengePreparation:
    def __init__(self, context):
        from .challenge_cli import validate_settings
        if context.report.operation != OPERATION:
            raise AutomationError('高难备战仅用于明确的独立准备任务。')
        self.c = context
        self.plan = validate_settings(context.settings, requested=True)
        if getattr(context.runner, '_challenge_prepare_mode', self.plan.mode) != self.plan.mode:
            raise AutomationError('高难计划模式已改变。')
        self.read_only = self.plan.mode == APOCALYPTIC_MODE
        if self.read_only:
            context.vision.uid_counterevidence_floor = UID_VETO_FLOOR
        directory = Path(context.report.run_dir)
        if not directory.is_absolute() or not directory.is_dir():
            raise AutomationError('高难备战缺少已建立的本次运行目录。')
        self.path = directory / 'challenge-preparation.json'
        if self.path.exists() or context.report.challenge:
            raise AutomationError('本次已有高难备战记录，未覆盖或重启。')
        self.epoch = context.runner.input_epoch
        self.account = None
        self.request = None
        self._readonly_receipt = None
        self.data = dict(schema=1, operation=OPERATION, status='running', plan=self.plan.to_dict(),
            plan_digest=self.plan.digest, input_epoch=self.epoch, actions=[], observations=[],
            preparation_page_verified=False, team_verified=False, battle_started=False,
            completion_verified=False, selected_level=None)
        context.report.challenge = self.data
        context.challenge_preparation = self
        self._persist()

    def _persist(self, data=None, *, before_replace=None):
        raw = _json(self.data if data is None else data).encode('utf-8')
        if len(raw) > MAX_BYTES:
            raise AutomationError('高难备战记录超过8 MiB，原记录保留。')
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if before_replace is None:
            replace_file(temporary, self.path)
        else:
            replace_file(temporary, self.path, before_replace=before_replace)

    def _check_attempt(self):
        from .challenge_plan import ChallengePlan
        self.c.checkpoint()
        if (self.c.runner.input_epoch != self.epoch
                or self.c.last_scene is not None and self.c.scene_epoch != self.epoch):
            raise InputInterrupted('高难备战输入代次改变，旧选择不重发。')
        if ChallengePlan.from_dict(self.c.settings.challenge_plan).digest != self.plan.digest:
            raise AutomationError('高难计划已改变，未继续旧层数选择。')

    def _fresh(self, scene, *, allow_missing_account=False):
        current = self._require_current(scene, allow_missing_account=allow_missing_account)
        if current and self.request is not None:
            # Context calls this again after the window guard, at the last
            # gate before sending the pending level selection.
            self._verify_request(scene)
            self._require_current(scene)
        return current

    def _require_current(self, scene, *, allow_missing_account=False):
        self._check_attempt()
        if (scene is not self.c.last_scene or type(scene.captured_at) not in (int, float)
                or not 0 <= time.monotonic() - scene.captured_at <= MAX_SCENE_AGE
                or scene.image is None or scene.geometry is None):
            raise AutomationError('高难备战需要当前新鲜画面及窗口来源。')
        try:
            self.account = self._read_account(scene)
        except AccountNotObserved:
            if allow_missing_account:
                return False
            raise
        return True

    def _read_account(self, scene):
        return verified_account(scene, self.c.settings.ocr_confidence, expected=self.account,
                                veto_floor=UID_VETO_FLOOR if self.read_only else None)

    def _read_png(self, path):
        directory = Path(self.c.report.run_dir).resolve()
        path = Path(path).resolve()
        if not path.is_relative_to(directory) or path.suffix.lower() != '.png':
            raise AutomationError('高难备战证据不在本次运行目录内。')
        with path.open('rb') as stream:
            raw = stream.read(MAX_PNG_BYTES + 1)
        if not raw or len(raw) > MAX_PNG_BYTES:
            raise AutomationError('高难备战PNG证据大小异常。')
        return path, raw

    def _source(self, scene, observation, label):
        self._fresh(scene)
        path, raw = self._read_png(self.c.evidence(scene, 'challenge_' + label))
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape != scene.image.shape or not np.array_equal(image, scene.image):
            raise AutomationError('高难备战落盘PNG与当前画面不同。')
        record = dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
            pixel_sha256=_pixels(scene), shape=list(scene.image.shape), captured_at=scene.captured_at,
            kind=observation.kind, mode=observation.mode, level=observation.level,
            stars=observation.stars, basis=deepcopy(observation.basis))
        if observation.kind == 'team_setup' and observation.mode == self.plan.mode:
            # Optional roster observations are separate from page readiness.
            from .challenge_slots import _setup_roster
            record['basis'].update(_setup_roster(scene, observation))
        return record

    def _derive(self, scene):
        from .challenge_pages import observe
        observation = observe(scene, self.c.settings.ocr_confidence)
        level = self.plan.level_start
        choices = [token for intent, token in observation.targets
                   if intent == 'select_level' and int(token.text) == level]
        if observation.kind != 'lobby' or observation.mode != self.plan.mode or len(choices) != 1:
            raise AutomationError('当前高难主页没有本次层数的唯一导航目标。')
        return PreparationAction('select_level', level, choices[0])

    def authorize(self, scene, action):
        if self.read_only or self.request is None or self.request != action:
            raise AutomationError('高难层数选择与当前页面或冻结计划不符。')
        self._fresh(scene)

    def _verify_request(self, scene):
        if self._derive(scene) != self.request:
            raise AutomationError('高难层数选择与当前页面或冻结计划不符。')
        with self.path.open('rb') as stream:
            raw = stream.read(MAX_BYTES + 1)
        from .currency_wars_state import strict_json
        if len(raw) > MAX_BYTES or _json(strict_json(raw.decode('utf-8'))) != _json(self.data):
            raise AutomationError('高难选择意图未完整落盘。')
        actions = self.data['actions']
        if len(actions) != 1 or actions[-1]['status'] != 'pending':
            raise AutomationError('高难备战只允许本次首个目标层的一次选择。')
        source = actions[-1]['before']
        path = Path(source['path']).resolve()
        if not path.is_relative_to(Path(self.c.report.run_dir).resolve()):
            raise AutomationError('高难选择证据来源越界。')
        with path.open('rb') as stream:
            evidence = stream.read(MAX_PNG_BYTES + 1)
        if (hashlib.sha256(evidence).hexdigest() != source['sha256']
                or source['pixel_sha256'] != _pixels(scene)
                or source['shape'] != list(scene.image.shape)
                or source['captured_at'] != scene.captured_at):
            raise AutomationError('高难层数选择证据与当前画面不同。')

    def _wait(self, acceptable, description, *, after_input=None):
        from .challenge_pages import observe, target
        frames, previous = [], None
        feedback = after_input is not None
        latest_capture = after_input
        deadline = time.monotonic() - self.c.runner.inactive_duration + 30
        for _ in range(100):
            try:
                scene = self.c.snapshot()
            except EmptyCapture:
                self._check_attempt()
                gap_at = time.monotonic()
                latest_capture = gap_at if latest_capture is None else max(latest_capture, gap_at)
                frames, previous = [], None
                scene = None
            if scene is not None:
                account_observed = self._fresh(scene, allow_missing_account=feedback or self.account is None)
                observation = observe(scene, self.c.settings.ocr_confidence)
                if observation.mode is not None and observation.mode != self.plan.mode:
                    raise AutomationError('当前高难模式与明确计划不符。')
                increasing = latest_capture is None or scene.captured_at > latest_capture
                if feedback and increasing:
                    latest_capture = scene.captured_at
                if account_observed and increasing and acceptable(scene, observation):
                    token = target(scene, 'select_level', self.c.settings.ocr_confidence, level=self.plan.level_start)
                    signature = (observation.kind, observation.mode, observation.level, observation.stars,
                                 token.box if token is not None else None)
                    if signature != previous:
                        frames = []
                    previous = signature
                    if not frames or scene.captured_at > frames[-1]['captured_at']:
                        frames.append(self._source(scene, observation, 'observation_' + str(len(self.data['observations']))))
                        self.data['observations'].append(frames[-1])
                        self.data['account_key'] = self.account
                        self._persist()
                    if len(frames) == 2:
                        self._fresh(scene)
                        if time.monotonic() - self.c.runner.inactive_duration >= deadline:
                            break
                        return scene, observation, frames, deadline
                else:
                    frames, previous = [], None
            self.c.sleep(.3)
            if time.monotonic() - self.c.runner.inactive_duration >= deadline:
                break
        if scene is not None:
            self.c.evidence(scene, 'challenge_unverified')
        raise AutomationError('高难备战未在有限观察内核实' + description + '，没有重发选择。')

    def _observe_apocalyptic(self):
        import numpy as np
        from .challenge_apocalyptic_prepare import observe, same_page
        previous, geometry = None, None
        last_scene = None
        latest_capture = 0.
        deadline = time.monotonic() - self.c.runner.inactive_duration + 30
        for attempt in range(8):
            if attempt:
                self.c.sleep(.3)
            if time.monotonic() - self.c.runner.inactive_duration >= deadline:
                break
            try:
                scene = self.c.snapshot()
            except EmptyCapture:
                self._check_attempt()
                latest_capture = max(latest_capture, time.monotonic())
                previous = None
                continue
            last_scene = scene
            account = self._fresh(scene, allow_missing_account=True)
            if geometry is None:
                geometry = scene.geometry
            if scene.geometry != geometry or scene.image.shape != (geometry.height, geometry.width, 3):
                raise AutomationError('末日备战采集窗口来源发生变化。')
            increasing = scene.captured_at > latest_capture
            latest_capture = max(latest_capture, scene.captured_at)
            if not account or not increasing:
                previous = None
                continue
            pixel_sha256 = _pixels(scene)
            page = observe(scene, self.c.settings.ocr_confidence)
            if page.kind == 'unknown':
                previous = None
                continue
            sequence = self.c.capture_sequence
            source = self._source(scene, page, f'apocalyptic_{sequence}')
            if source['pixel_sha256'] != pixel_sha256:
                raise AutomationError('末日备战识别后的图像像素发生变化。')
            source['capture_sequence'] = sequence
            source['geometry'] = [geometry.left, geometry.top, geometry.width, geometry.height]
            frame = _ObservedFrame(scene, page, source)
            self.data['observations'].append(source)
            self.data['account_key'] = self.account
            self._persist()
            if (previous is not None and sequence == previous.source['capture_sequence'] + 1
                    and not np.may_share_memory(previous.scene.image, scene.image)
                    and same_page(previous.observation, page)):
                return self._publish_apocalyptic((previous, frame), deadline)
            previous = frame
        if last_scene is not None and self.c.last_scene is None:
            self.c.evidence(last_scene, 'challenge_unverified')
        raise AutomationError('末日备战缺少同账号连续两张可核实的当前页面。')

    def _recheck_apocalyptic(self, pair, deadline):
        from .challenge_apocalyptic_prepare import observe
        current = pair[-1].scene
        confidence = self.c.settings.ocr_confidence
        self._fresh(current)
        first, last = (frame.source for frame in pair)
        if (first['captured_at'] >= last['captured_at'] or first['capture_sequence'] + 1 != last['capture_sequence']
                or Path(first['path']).samefile(last['path'])):
            raise AutomationError('末日备战回执需要两次独立采集和独立原图。')
        for frame in pair:
            scene, source = frame.scene, frame.source
            path, raw = self._read_png(source['path'])
            g = scene.geometry
            if (g != current.geometry or source['captured_at'] != scene.captured_at or source['path'] != str(path)
                    or source['geometry'] != [g.left, g.top, g.width, g.height]
                    or source['sha256'] != hashlib.sha256(raw).hexdigest()
                    or source['pixel_sha256'] != _pixels(scene)
                    or observe(scene, confidence) != frame.observation
                    or self._read_account(scene) != self.account):
                raise AutomationError('末日备战回执与原画面不同。')
        self._fresh(current)
        self.c.window.guard(current.geometry)
        # The native guard can finish after an F9 or F10 event.
        runner = self.c.runner
        if runner.stop_requested:
            raise Stopped('末日备战观察已停止。')
        if runner.input_epoch != self.epoch or self.c.scene_epoch != self.epoch:
            raise InputInterrupted('末日备战观察的输入代次已改变。')
        now = time.monotonic()
        if (current is not self.c.last_scene or self.c.capture_sequence != last['capture_sequence']
                or not 0 <= now - first['captured_at'] <= MAX_SCENE_AGE
                or now - runner.inactive_duration >= deadline):
            raise AutomationError('末日备战回执超过本次连续观察范围。')

    @staticmethod
    def _check_payload(path, expected):
        with path.open('rb') as stream:
            if stream.read(len(expected) + 1) != expected:
                raise AutomationError('末日备战待保存记录或原回执发生变化。')

    def _publish_apocalyptic(self, pair, deadline):
        page = pair[-1].observation
        sources = [frame.source for frame in pair]
        ready = page.kind == 'node_setup' and page.level == self.plan.level_start
        receipt = dict(kind=page.kind, mode=page.mode, level=page.level, node=page.basis.get('node'),
                       period=page.basis.get('period'), frames=sources)
        data = dict(self.data, status='prepared' if ready else 'page_observed',
                    page_observation=receipt, preparation_page_verified=ready)
        if ready:
            data.update(entry='existing_node_setup', preparation_frames=sources)
        payload = _json(data).encode('utf-8')

        def recheck():
            self._check_payload(self.path.with_suffix('.tmp'), payload)
            self._recheck_apocalyptic(pair, deadline)

        with hold_read_sources(row['path'] for row in sources):
            self._persist(data, before_replace=recheck)
        self._readonly_receipt = pair, deadline, payload
        self.data.update(data)
        if ready:
            return TaskResult(OPERATION, 'ok', '已核实末日幻影首个目标难度的双节点备战页面。')
        self.c.report.safe_next = '可在同账号打开计划首个难度的双节点备战页后重新核对。'
        return TaskResult(OPERATION, 'partial', '已保存末日幻影当前页面的双帧观察，目标难度备战待核实。')

    def save_report(self, temporary, write_report):
        destination = self.path.parent / 'report.json'
        pair, deadline, receipt_payload = self._readonly_receipt
        result = next(item for item in self.c.report.results if item.task == OPERATION)
        try:
            with hold_read_sources([self.path, *(frame.source['path'] for frame in pair)]):
                payload = write_report()

                def recheck():
                    self._check_payload(self.path, receipt_payload)
                    if self.c.report.challenge is not self.data or _json(self.data).encode('utf-8') != receipt_payload:
                        raise AutomationError('末日备战报告字段与原回执不同。')
                    with temporary.open(encoding='utf-8') as stream:
                        if stream.read(len(payload) + 1) != payload:
                            raise AutomationError('末日备战待保存报告发生变化。')
                    self._recheck_apocalyptic(pair, deadline)

                replace_file(temporary, destination, before_replace=recheck)
        except (AutomationError, OSError, ValueError, TypeError) as error:
            self.data.clear()
            self.data.update(json.loads(receipt_payload))
            self.data.pop('page_observation', None)
            self.data.pop('preparation_frames', None)
            self.data.pop('entry', None)
            self.data.update(status='stopped' if isinstance(error, Stopped) else 'partial',
                             preparation_page_verified=False)
            report = self.c.report
            report.challenge = self.data
            report.status = self.data['status']
            report.failure_task = OPERATION
            report.error = str(error)
            report.safe_next = '保留末日备战原回执和截图，重新核对当前前台页面。'
            result.status = report.status
            result.detail = '末日备战最终报告未核实，原回执保留。'
            write_report()
            replace_file(temporary, destination)

    def run(self):
        from .challenge_pages import observe, target
        level = self.plan.level_start
        ready = lambda page: page.kind == 'team_setup' and page.level == level and page.mode == self.plan.mode
        try:
            if self.read_only:
                return self._observe_apocalyptic()
            scene, observation, frames, deadline = self._wait(lambda scene, page: ready(page) or
                page.kind == 'lobby' and target(scene, 'select_level', self.c.settings.ocr_confidence,
                                               level=level) is not None, '当前模式与首个目标层')
            record = None
            if not ready(observation):
                action = self._derive(scene)
                record = dict(intent=action.intent, level=level, target=list(action.target.box), status='pending',
                    input_epoch=self.epoch, plan_digest=self.plan.digest,
                    before=self._source(scene, observation, 'before_level_selection'), lobby_frames=frames)
                self.data['actions'].append(record)
                self.request = action
                self._persist()
                after_input = self.c.challenge_prepare_input(scene, action)
                self.request = None
                record['status'] = 'submitted'
                self._persist()
                scene, _, frames, deadline = self._wait(lambda scene, page: ready(page), '同层备战页面',
                                                         after_input=after_input)

            prepared = dict(self.data, status='prepared', selected_level=level, preparation_page_verified=True,
                            preparation_frames=frames)
            if record is None:
                prepared['entry'] = 'existing_team_setup'
            else:
                prepared['actions'] = [dict(record, status='verified', after=frames)]

            def recheck():
                self._fresh(scene)
                self.c.window.guard(scene.geometry)
                if (scene.captured_at != frames[-1]['captured_at']
                        or not ready(observe(scene, self.c.settings.ocr_confidence))):
                    raise AutomationError('高难备战最终记录与原观察不同。')
                self._fresh(scene)
                if time.monotonic() - self.c.runner.inactive_duration >= deadline:
                    raise AutomationError('高难备战确认超过有限观察时间。')

            self._persist(prepared, before_replace=recheck)
            self.data.update(prepared)
            return TaskResult(OPERATION, 'ok', '已核实本次目标层备战页面。')
        except Exception as error:
            if self.data['actions'] and self.data['actions'][-1]['status'] in ('pending', 'submitted'):
                self.data['actions'][-1]['status'] = 'unknown'
            self.data['status'] = 'stopped' if isinstance(error, Stopped) else 'partial' if self.data['actions'] else 'failed'
            self.data['error_type'] = type(error).__name__
            try:
                self._persist()
            except Exception:
                pass  # Preserve the original exception and the last durable intent.
            raise


def prepare_challenge(context):
    return ChallengePreparation(context).run()
