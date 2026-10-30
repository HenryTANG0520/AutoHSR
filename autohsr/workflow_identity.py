"""Private, observed account continuity for one explicitly started task tree.

Uses the existing strict Currency Wars UID parser for all native child contexts;
the independent DU/day and CW ledgers retain their original key formats.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import json
import math
import os
from pathlib import Path
import time
import uuid
import weakref

import cv2
import numpy as np

from .models import AutomationError, InputInterrupted, normalize
from .storage import replace_file

_scope = ContextVar('autohsr_workflow_identity', default=None)
MAX_FRAMES = 60
WAIT_SECONDS = 15.
RECHECK_DELAY = .15
MAX_PRIVATE_BYTES = 16 * 1024 * 1024
INPUT_METHODS = frozenset(('send', 'click', 'click_held', 'move', 'key', 'type_du_save_name', 'type_redemption_code',
                          'key_hold', 'field_interact', 'field_attack', 'dialogue_burst',
                          'field_motion', 'look', 'drag', 'scroll'))


@dataclass
class _State:
    owner: object
    run_dir: str
    verified_epoch: int | None = None
    candidate: str | None = None
    frames: list = field(default_factory=list)
    last_capture: float = 0.
    attempts: int = 0
    pending_at: float = field(default_factory=time.monotonic)
    startup: bool = False
    startup_page: bool = False
    current_epoch: int | None = None
    last_capture_serial: int = 0
    capture_epoch: int | None = None
    runner_ref: object = None


class _Window:
    def __init__(self, raw, context, scope):
        self._raw = raw._raw if isinstance(raw, _Window) else raw
        self._context, self._scope = context, scope

    def __getattr__(self, name):
        value = getattr(self._raw, name)
        if name not in INPUT_METHODS:
            return value
        def guarded(*args, **kwargs):
            self._scope.require(self._context)
            return value(*args, **kwargs)
        return guarded


@contextmanager
def account_scope(scope):
    if _scope.get() is not None:
        raise AutomationError('任务流程账号约束不能嵌套或替换。')
    token = _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(token)


def wrap_window(context, window):
    current = _scope.get()
    return _Window(window, context, current) if current is not None else window


def observe(context, scene):
    current = _scope.get()
    if current is None:
        return True
    current._capture_serial += 1
    return current.observe(context, scene, capture_serial=current._capture_serial)


def active():
    return _scope.get() is not None


def prepare(context):
    current = _scope.get()
    if current is None:
        return
    # Real Context.snapshot already waits for two frames. The loop also allows
    # a known first-login page to run the existing guarded startup workflow.
    for _ in range(MAX_FRAMES):
        context.checkpoint()
        scene = context.snapshot()
        state = current.state(context)
        if state.verified_epoch == context.runner.input_epoch:
            return
        if state.startup and state.startup_page:
            from .workflows import DailyWorkflow
            DailyWorkflow(context).ensure_main()
            continue
        if current.observe(context, scene):
            if state.verified_epoch == context.runner.input_epoch:
                return
        context.sleep(RECHECK_DELAY)
    raise AutomationError('当前账号未在有限观察内核实，未执行游戏任务。')


class WorkflowIdentity:
    def __init__(self, directory, *, required, publish=None):
        self.directory = Path(directory) / 'identity'
        self.required = required
        self.publish = publish or (lambda public: None)
        self._key = None
        self._first_runner = None
        self._states = []
        self._proofs = []
        self._conflict = False
        self._storage_failed = False
        self._capture_serial = 0
        self._private_digest = None
        self._evidence_invalid = False

    def public(self):
        for state in self._states:
            runner = state.runner_ref() if state.runner_ref is not None else None
            if runner is not None:
                state.current_epoch = runner.input_epoch
        verified = bool(self._key and not self._conflict and not self._storage_failed and not self._evidence_invalid and
                        all(state.verified_epoch is not None and state.verified_epoch == state.current_epoch for state in self._states))
        return dict(required=self.required, bound=self._key is not None, verified=verified,
                    checked_contexts=len({proof['run_dir'] for proof in self._proofs}),
                    observations=len(self._proofs), account_changed=self._conflict,
                    status='not_required' if not self.required else 'changed' if self._conflict else
                    'evidence_invalid' if self._evidence_invalid else
                    'storage_failed' if self._storage_failed else 'verified' if verified else
                    'needs_recheck' if self._key is not None else 'not_observed')

    def state(self, context):
        runner = context.runner
        state = getattr(runner, '_workflow_identity_state', None)
        if (not isinstance(state, _State) or state.owner is not self or state.run_dir != context.report.run_dir):
            self._integrity()
            directory = context.report.run_dir
            if not isinstance(directory, str) or not directory:
                raise AutomationError('账号核验缺少当前原生运行目录。')
            if self._first_runner is None:
                self._first_runner = runner
            state = _State(self, directory, startup=self._key is None and runner is self._first_runner)
            try:
                state.runner_ref = weakref.ref(runner)
            except TypeError:
                state.runner_ref = lambda: runner
            runner._workflow_identity_state = state
            self._states.append(state)
        return state

    def _persist(self, data):
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / 'state.json'
        temporary = self.directory / 'state.tmp'
        raw = json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2).encode('utf8')
        if len(raw) > MAX_PRIVATE_BYTES:
            raise AutomationError('账号证据记录超过16 MiB，未继续输入。')
        try:
            with temporary.open('wb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            replace_file(temporary, path)
            self._private_digest = hashlib.sha256(raw).hexdigest()
        finally:
            temporary.unlink(missing_ok=True)

    def _integrity(self):
        if self._key is None:
            return
        try:
            def digest(path):
                with Path(path).open('rb') as stream:
                    raw = stream.read(MAX_PRIVATE_BYTES + 1)
                if len(raw) > MAX_PRIVATE_BYTES:
                    raise ValueError('oversize')
                return hashlib.sha256(raw).hexdigest()
            if digest(self.directory / 'state.json') != self._private_digest:
                raise ValueError('changed state')
            for proof in self._proofs:
                for source in proof['sources']:
                    if digest(source['path']) != source['sha256']:
                        raise ValueError('changed source')
        except (OSError, ValueError):
            self._evidence_invalid = True
            self.publish(self.public())
            raise AutomationError('前序账号证据缺失或内容改变；原记录保留，未沿用旧结果继续输入。') from None

    def _commit(self, state, key):
        self._integrity()
        sources = []
        self.directory.mkdir(parents=True, exist_ok=True)
        for frame in state.frames:
            target = self.directory / (uuid.uuid4().hex + '.png')
            ok, encoded = cv2.imencode('.png', frame['crop'])
            if not ok:
                raise AutomationError('账号局部证据无法编码。')
            raw = encoded.tobytes()
            with target.open('xb') as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            sources.append(dict(path=str(target), sha256=hashlib.sha256(raw).hexdigest(),
                                captured_at=frame['captured_at'], input_epoch=frame['epoch'],
                                capture_serial=frame['capture_serial']))
        proof = dict(run_dir=state.run_dir, input_epoch=state.frames[-1]['epoch'], sources=sources)
        conflict = self._key is not None and self._key != key
        data = dict(schema=1, account_key=self._key or key, proofs=self._proofs + ([] if conflict else [proof]),
                    account_changed=conflict)
        if conflict:
            data['conflicting_observation'] = dict(account_key=key, **proof)
        self._persist(data)
        if conflict:
            self._conflict = True
        else:
            self._key = key
            self._proofs.append(proof)
            state.verified_epoch = proof['input_epoch']
            state.startup = False
        self.publish(self.public())
        if conflict:
            raise AutomationError('当前账号与本次任务流程已绑定账号不同；未继续输入或沿用前一账号结果。')

    def _check(self):
        if self._conflict or self._storage_failed or self._evidence_invalid:
            raise AutomationError('本次流程账号核验已停止；未重试输入或更换绑定账号。')

    def observe(self, context, scene, *, capture_serial=0):
        self._check()
        state = self.state(context)
        epoch = context.runner.input_epoch
        state.current_epoch = epoch
        now = time.monotonic()
        if (type(epoch) is not int or epoch < 0 or context.scene_epoch != epoch
                or not isinstance(scene.captured_at, (int, float)) or not math.isfinite(scene.captured_at)
                or not 0 <= now - scene.captured_at <= 8 or scene.captured_at < state.last_capture
                or (scene.captured_at == state.last_capture and not
                    (type(capture_serial) is int and capture_serial > state.last_capture_serial))):
            raise AutomationError('账号观察不是本次新鲜画面或输入代次已改变。')
        state.last_capture = scene.captured_at
        state.last_capture_serial = capture_serial
        if state.capture_epoch is not None and state.capture_epoch != epoch:
            state.verified_epoch = None
            state.pending_at, state.attempts = now, 0
            state.frames, state.candidate = [], None
        state.capture_epoch = epoch
        from .currency_wars_identity import account_key
        from .workflows import DailyWorkflow
        try:
            key = account_key(scene, max(.85, context.settings.ocr_confidence))
        except AutomationError:
            key = None
        fragments = any(token.within((0, .94, .35, 1)) and normalize(token.text).startswith('uid') for token in scene.tokens)
        login = DailyWorkflow._login(scene)
        state.startup_page = key is None and bool(login or DailyWorkflow._supply_overlay(scene) or DailyWorkflow._login_reward_overlay(scene))
        if login and self._key is not None:
            state.verified_epoch = None
            state.frames, state.candidate = [], None
            raise AutomationError('已绑定流程返回登录页；未自动登录或切换账号。')
        if key is None and not fragments and state.verified_epoch == epoch:
            return True  # Native page/input checks still apply when UID is hidden.
        if key is not None and key == self._key and state.verified_epoch == epoch:
            return True
        if state.verified_epoch is not None:
            state.verified_epoch = None
            state.pending_at, state.attempts = now, 0
            state.frames, state.candidate = [], None
        if key is None and self._key is None and state.startup and state.startup_page and not fragments:
            state.pending_at, state.attempts = now, 0
            return True
        if state.attempts == 0:
            state.pending_at = now
        state.attempts += 1
        if state.attempts > MAX_FRAMES or now - state.pending_at > WAIT_SECONDS:
            raise AutomationError('当前账号标识未在有限新鲜观察内完整核实；未沿用旧画面。')
        if key is None:
            state.frames, state.candidate = [], None
            if login and self._key is not None:
                raise AutomationError('任务交接后当前位于登录页；未自动沿用原账号结果。')
            return False
        image = scene.image
        if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim not in (2, 3)
                or image.shape[0] < 16 or image.shape[1] < 16):
            raise AutomationError('当前账号缺少原始局部图像证据。')
        height, width = image.shape[:2]
        crop = image[int(.94 * height):height, :max(1, int(.35 * width))].copy()
        if state.candidate != key:
            state.frames, state.candidate = [], key
        state.frames.append(dict(crop=crop, captured_at=scene.captured_at, epoch=epoch, capture_serial=capture_serial))
        if len(state.frames) < 2:
            return False
        if state.frames[0]['epoch'] != epoch:
            state.frames = state.frames[-1:]
            return False
        try:
            self._commit(state, key)
        except Exception:
            if not self._conflict:
                self._storage_failed = True
                self.publish(self.public())
            raise
        return True

    def require(self, context):
        self._check()
        state = self.state(context)
        state.current_epoch = context.runner.input_epoch
        if state.verified_epoch == context.runner.input_epoch and self._key is not None:
            return
        if self._key is None and state.startup and state.startup_page:
            return
        raise InputInterrupted('当前输入代次的账号尚未重新核实；旧目标已丢弃。')

    def mark(self):
        return len(self._proofs)

    def has_step_proof(self, before):
        return len(self._proofs) > before

    def require_step(self, before):
        self._check()
        self._integrity()
        if not self.has_step_proof(before) or not self.public()['verified']:
            raise AutomationError('子任务没有本次当前账号的完整证据；原报告保留，未将旧回执当作当前账号完成。')
