"""Private step receipts for continuing one verified overclock A0 opening."""
from __future__ import annotations

import hashlib
from pathlib import Path

from .currency_wars_overclock_preparation_pages import (
    ACTIONS, PHASES, preparation_target_box, valid_preparation_key,
)
from .currency_wars_overclock_session import (
    PREP_JOURNAL, _HEX_DIGEST, _directory, _exists, _matches, _read, _track_source,
)
from .currency_wars_state import strict_json
from .models import AutomationError


MODE = 'overclock_a0_preparation'
INSURANCE = '人身意外险'


def _key(index, observation):
    if type(observation) is not dict or observation.get('state') != PHASES[index]:
        raise AutomationError('首次备战的历史阶段不可核实。')
    stored = observation.get('key')
    if not valid_preparation_key(PHASES[index], stored):
        raise AutomationError('首次备战的历史页面读数与校准阶段不一致。')
    return tuple(stored)


def _before_after(index, before, after):
    if index == 2 and before[:3] != after[:3]:
        raise AutomationError('投保前后的三张环境卡不一致。')


class PreparationJournal:
    def __init__(self, session):
        from .currency_wars_overclock import MAX_JOURNAL_BYTES

        self.session = session
        self.path = session.path.parent / PREP_JOURNAL
        self.start_sha256 = hashlib.sha256(session.raw).hexdigest()
        self.window_key = session.data.get('window_key')
        self.origin = Path(session.data['run_dir'])
        self.opening_stamp = session.data['feedback'][-1]['captured_at']
        self.initial_key = _key(0, dict(state=PHASES[0], key=session.data.get('preview_factions')))
        if not _matches(_HEX_DIGEST, self.window_key):
            raise AutomationError('原超频 A0 开局缺少跨运行窗口证据，保留原件。')
        self.raw = None
        self.steps = []
        self._sources = None
        try:
            self.require_no_temporary()
            if _exists(self.path):
                revisions = {}
                track = _track_source(revisions, None)
                self.raw = _read(self.path, MAX_JOURNAL_BYTES, track)
                data = strict_json(self.raw.decode('utf-8'))
                if (type(data) is not dict or type(data.get('schema')) is not int or data['schema'] != 1
                        or data.get('mode') != MODE or data.get('match_id') != session.match_id
                        or data.get('start_sha256') != self.start_sha256 or data.get('status') != 'verified'
                        or type(data.get('steps')) is not list or not 1 <= len(data['steps']) <= len(ACTIONS)):
                    raise AutomationError('首次备战记录待核对或未绑定原开局，未重放输入。')
                self.steps = data['steps']
                self._require_steps()
                if _read(self.path, MAX_JOURNAL_BYTES, track) != self.raw:
                    raise AutomationError('首次备战记录在预检期间改变，未继续。')
                self.revision = revisions[self.path]
            else:
                self.revision = None
        except (OSError, KeyError, ValueError, TypeError, RecursionError):
            raise AutomationError('首次备战的历史记录或截图不可核实，保留原件。') from None

    @property
    def phase(self):
        return PHASES[len(self.steps)]

    @property
    def key(self):
        return tuple(self.steps[-1]['observation']['key']) if self.steps else self.initial_key

    @property
    def last_capture(self):
        return self.steps[-1]['feedback'][-1]['captured_at'] if self.steps else self.opening_stamp

    def matches(self, observation):
        return observation.state == self.phase and observation.key == self.key

    def require_complete(self):
        if len(self.steps) != len(ACTIONS):
            raise AutomationError('推进当前对局前须核实原开局的全部四个首备战步骤。')

    def require_no_temporary(self):
        if _exists(self.path.with_suffix('.tmp')):
            raise AutomationError('已有首次备战待发布记录，保留原件。')

    def require_feedback(self, observation):
        index = len(self.steps)
        after = _key(index + 1, observation)
        _before_after(index, self.key, after)

    def _require_steps(self, check_source=None):
        from .currency_wars_overclock import MAX_FRAME_AGE, _check_evidence, _recorded_evidence

        revisions = {}
        track = _track_source(revisions, check_source)
        # The opening has already reopened its original PNGs. Their identities
        # cannot reappear in a later step, even through another path.
        identities = {revision[:2] for path, revision in self.session._active_sources.items()
                      if path != self.session.path}
        directories = {self.origin, self.session.run_dir}
        stamp = self.opening_stamp
        key = self.initial_key
        for index, step in enumerate(self.steps):
            if type(step) is not dict or step.get('status') != 'verified' or step.get('action') != ACTIONS[index]:
                raise AutomationError('首次备战有未核实的动作，未重放输入。')
            origin = _directory(Path(step['run_dir']))
            epoch, box, feedback = step['input_epoch'], step['target'], step['feedback']
            slot = key.index(INSURANCE) if index == 2 and INSURANCE in key[:3] else None
            if (origin.parent != self.path.parent or origin in directories or type(epoch) is not int or epoch < 0
                    or not preparation_target_box(ACTIONS[index], box, slot=slot)
                    or type(feedback) is not list or len(feedback) != 2
                    or _key(index, step['before_observation']) != key):
                raise AutomationError('首次备战的原运行、目标或动作来源不一致。')
            directories.add(origin)
            after_key = _key(index + 1, step['observation'])
            _before_after(index, key, after_key)
            key = after_key
            before = _recorded_evidence(step['before'], PHASES[index])
            first, second = (_recorded_evidence(item, PHASES[index + 1]) for item in feedback)
            if not stamp < before.captured_at < first.captured_at < second.captured_at <= first.captured_at + MAX_FRAME_AGE:
                raise AutomationError('首次备战原证据的时间顺序不可核实。')
            stamp = second.captured_at
            for proof in (before, first, second):
                path = _check_evidence(proof, origin, check_source=track)
                identity = revisions[path][:2]
                if identity in identities:
                    raise AutomationError('首次备战每步需要独立的原始 PNG。')
                identities.add(identity)
        for path in revisions:
            track(path)
        if self._sources is not None and revisions != self._sources:
            raise AutomationError('首次备战的历史截图已改变，未继续。')
        self._sources = revisions

    def require_sources(self, check_source=None):
        try:
            self.session.require_active(check_source)
            self.session.require_history(check_source)
            self._require_steps(check_source)
        except (OSError, KeyError, ValueError, TypeError, RecursionError):
            raise AutomationError('原开局或首次备战证据不可核实，保留原件。') from None

    def require_new_proofs(self, proofs, revisions):
        old = {value[:2] for value in self.session._active_sources.values()}
        old.update(value[:2] for value in self._sources.values())
        fresh = {revisions[Path(proof.screenshot)][:2] for proof in proofs}
        if len(fresh) != len(proofs) or fresh & old or proofs[0].captured_at <= self.last_capture:
            raise AutomationError('首次备战需要晚于原回执且各自独立的 PNG 证据。')

    def envelope(self, data):
        step = data['actions'][0]
        current = dict(step, run_dir=str(self.session.run_dir), observation=data['observation'],
                       feedback=data['feedback'])
        return dict(schema=1, mode=MODE, match_id=self.session.match_id, start_sha256=self.start_sha256,
                    status=data['status'], steps=[*self.steps, current])
