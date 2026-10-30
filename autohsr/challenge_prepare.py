"""Observed preparation only; this module cannot select a team or start combat."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import time

from .models import AutomationError, EmptyCapture, InputInterrupted, Stopped, TaskResult
from .storage import replace_file

OPERATION = 'challenge_prepare'
MAX_BYTES = 8 * 1024 * 1024


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


class ChallengePreparation:
    def __init__(self, context):
        from .challenge_cli import validate_settings
        if context.report.operation != OPERATION:
            raise AutomationError('高难备战仅用于明确的独立准备任务。')
        self.c = context
        self.plan = validate_settings(context.settings, requested=True)
        directory = Path(context.report.run_dir)
        if not directory.is_absolute() or not directory.is_dir():
            raise AutomationError('高难备战缺少已建立的本次运行目录。')
        self.path = directory / 'challenge-preparation.json'
        if self.path.exists() or context.report.challenge:
            raise AutomationError('本次已有高难备战记录，未覆盖或重启。')
        self.epoch = context.runner.input_epoch
        self.account = None
        self.request = None
        self.data = dict(schema=1, operation=OPERATION, status='running', plan=self.plan.to_dict(),
            plan_digest=self.plan.digest, input_epoch=self.epoch, actions=[], observations=[],
            preparation_page_verified=False, team_verified=False, battle_started=False,
            completion_verified=False, selected_level=None)
        context.report.challenge = self.data
        context.challenge_preparation = self
        self._persist()

    def _persist(self):
        raw = _json(self.data).encode('utf-8')
        if len(raw) > MAX_BYTES:
            raise AutomationError('高难备战记录超过8 MiB，原记录保留。')
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('wb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, self.path)

    def _fresh(self, scene):
        from .challenge_plan import ChallengePlan
        self.c.checkpoint()
        if self.c.runner.input_epoch != self.epoch or self.c.scene_epoch != self.epoch:
            raise InputInterrupted('高难备战输入代次改变，旧选择不重发。')
        if ChallengePlan.from_dict(self.c.settings.challenge_plan).digest != self.plan.digest:
            raise AutomationError('高难计划已改变，未继续旧层数选择。')
        if (scene is not self.c.last_scene or type(scene.captured_at) not in (int, float)
                or not 0 <= time.monotonic() - scene.captured_at <= 8
                or scene.image is None or scene.geometry is None):
            raise AutomationError('高难备战需要当前新鲜画面及窗口来源。')
        if self.account is not None:
            from .currency_wars_identity import account_key
            if account_key(scene, max(.85, self.c.settings.ocr_confidence)) != self.account:
                raise AutomationError('高难备战账号改变，未继续选择。')

    def _source(self, scene, observation, label):
        self._fresh(scene)
        directory = Path(self.c.report.run_dir).resolve()
        path = Path(self.c.evidence(scene, 'challenge_' + label)).resolve()
        if not path.is_relative_to(directory) or path.suffix.lower() != '.png':
            raise AutomationError('高难备战证据不在本次运行目录内。')
        with path.open('rb') as stream:
            raw = stream.read(64 * 1024 * 1024 + 1)
        if not raw or len(raw) > 64 * 1024 * 1024:
            raise AutomationError('高难备战PNG证据大小异常。')
        import cv2
        import numpy as np
        image = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if image is None or image.shape != scene.image.shape or not np.array_equal(image, scene.image):
            raise AutomationError('高难备战落盘PNG与当前画面不同。')
        return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest(),
            pixel_sha256=_pixels(scene), shape=list(scene.image.shape), captured_at=scene.captured_at,
            kind=observation.kind, mode=observation.mode, level=observation.level,
            stars=observation.stars, basis=deepcopy(observation.basis))

    def _derive(self, scene):
        from .challenge_pages import observe, target
        observation = observe(scene, self.c.settings.ocr_confidence)
        level = self.plan.level_start
        token = target(scene, 'select_level', self.c.settings.ocr_confidence, level=level)
        if observation.kind != 'lobby' or observation.mode != self.plan.mode or token is None:
            raise AutomationError('当前混沌主页没有本次层数的唯一导航目标。')
        return PreparationAction('select_level', level, token)

    def authorize(self, scene, action):
        self._fresh(scene)
        if self.request != action or self._derive(scene) != action:
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
            evidence = stream.read(64 * 1024 * 1024 + 1)
        if (hashlib.sha256(evidence).hexdigest() != source['sha256']
                or source['pixel_sha256'] != _pixels(scene)
                or source['shape'] != list(scene.image.shape)
                or source['captured_at'] != scene.captured_at):
            raise AutomationError('高难层数选择证据与当前画面不同。')

    def _wait(self, acceptable, description):
        from .challenge_pages import observe, target
        from .currency_wars_identity import account_key
        frames, previous = [], None
        elapsed = 0.
        for _ in range(100):
            started, inactive = time.monotonic(), self.c.runner.inactive_duration
            try:
                scene = self.c.snapshot()
            except EmptyCapture:
                scene = None
            if scene is not None:
                self._fresh(scene)
                if self.account is None:
                    try:
                        self.account = account_key(scene, max(.85, self.c.settings.ocr_confidence))
                    except AutomationError:
                        self.account = None
                observation = observe(scene, self.c.settings.ocr_confidence)
                if observation.mode is not None and observation.mode != self.plan.mode:
                    raise AutomationError('当前高难模式与明确计划不符。')
                if self.account is not None and acceptable(scene, observation):
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
                        return scene, observation, frames
                else:
                    frames, previous = [], None
            self.c.sleep(.3)
            elapsed += max(0., time.monotonic() - started - (self.c.runner.inactive_duration - inactive))
            if elapsed >= 30:
                break
        if scene is not None:
            self.c.evidence(scene, 'challenge_unverified')
        raise AutomationError('高难备战未在有限观察内核实' + description + '，没有重发选择。')

    def run(self):
        from .challenge_pages import target
        level = self.plan.level_start
        ready = lambda page: page.kind == 'team_setup' and page.level == level and page.mode == self.plan.mode
        try:
            scene, observation, frames = self._wait(lambda scene, page: ready(page) or
                page.kind == 'lobby' and target(scene, 'select_level', self.c.settings.ocr_confidence,
                                               level=level) is not None, '当前模式与首个目标层')
            if not ready(observation):
                action = self._derive(scene)
                record = dict(intent=action.intent, level=level, target=list(action.target.box), status='pending',
                    input_epoch=self.epoch, plan_digest=self.plan.digest,
                    before=self._source(scene, observation, 'before_level_selection'), lobby_frames=frames)
                self.data['actions'].append(record)
                self.request = action
                self._persist()
                self.c.challenge_prepare_input(scene, action)
                record['status'] = 'submitted'
                self._persist()
                scene, observation, frames = self._wait(lambda scene, page: ready(page), '同层备战页面')
                record.update(status='verified', after=frames)
            else:
                self.data['entry'] = 'existing_team_setup'
            self.data.update(status='prepared', selected_level=level, preparation_page_verified=True,
                             preparation_frames=frames)
            self._persist()
            return TaskResult(OPERATION, 'ok', '已核实混沌目标层备战页面；未选角、开战、使用秘技或领奖。')
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
