"""Local custody of a potentially sent forced-curio discard."""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import re
import uuid

from .currency_wars_state import strict_json
from .du_archive_store import MAX_BYTES, encoded, start_source
from .models import AutomationError
from .storage import replace_file


FOLDER = 'du-curio-discard'
LEDGER = 'differential-universe-ledger.json'
CONFIRM = 'curio_discard_confirm'
NEW_START_PAGES = frozenset((
    'mask_choice', 'area_choice', 'station_choice', 'field_combat', 'field_anomaly',
    'field_rest', 'field_shop', 'field_wealth', 'field_blank', 'field_forge',
    'field_adventure', 'field_reward', 'field_event',
))
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
ERROR = '奇物舍弃待核对记录、原账本或证据无法核实，保留原状态。'


def _inside(root, path):
    path = Path(path).resolve()
    if path == root or not path.is_relative_to(root):
        raise AutomationError(ERROR)
    return path


def _read(path, limit=MAX_BYTES):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if not 0 < len(raw) <= limit:
        raise AutomationError(ERROR)
    return raw


def _ref(path, raw):
    return dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())


def _source(root, ref, limit=MAX_BYTES):
    path = _inside(root, ref['path'])
    raw = _read(path, limit)
    if ref != _ref(path, raw):
        raise AutomationError(ERROR)
    return path, raw


def _write(path, raw, limit=MAX_BYTES):
    if not 0 < len(raw) <= limit:
        raise AutomationError(ERROR)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if _read(path, limit) != raw:
        raise AutomationError(ERROR)


def _entry(ledger, scope):
    if ledger['schema_version'] != 1 or ledger['session_id'] != scope['session_id']:
        raise AutomationError(ERROR)
    matches = [row for row in ledger['run_results'] if row.get('run') == scope['run']]
    if len(matches) != 1 or matches[0].get('run_id') != scope['run_id']:
        raise AutomationError(ERROR)
    return matches[0]


def _new_start(directory, ledger, scope):
    entry = _entry(ledger, scope)
    rank = entry.get('difficulty_rank')
    difficulty = entry['difficulty_evidence']
    if (entry.get('origin') != 'fresh' or entry.get('status') not in ('running', 'completed')
            or entry.get('started_page') not in NEW_START_PAGES or entry.get('difficulty_verified') is not True
            or type(rank) is not int or not 1 <= rank <= 10 or difficulty.get('verified') is not True
            or difficulty.get('requested_rank') != rank or difficulty.get('displayed_rank_after') != rank):
        raise AutomationError('缺少已核实的新开局与难度来源，保留原奇物舍弃记录。')
    return start_source(ledger, entry, directory)


def _departure(directory, ledger, action):
    paths = action['departure_evidence']
    if (action['status'] != 'sent' or action['feedback_status'] != 'verified'
            or len(paths) != 2 or paths[0] == paths[1] or paths[1] != action['after_evidence']):
        raise AutomationError(ERROR)
    matching = [row['evidence'] for row in ledger['page_history'] if row.get('run') == action['run']
                and row.get('page_kind') == action['after_page'] and row.get('evidence') in paths]
    if matching != paths:
        raise AutomationError(ERROR)
    return [_ref(path, _read(path, MAX_EVIDENCE_BYTES)) for path in (_inside(directory, item) for item in paths)]


class CurioDiscardStore:
    def __init__(self, directory, account):
        if (not isinstance(directory, (str, Path)) or not directory or not isinstance(account, str)
                or not re.fullmatch('[0-9a-f]{64}', account)):
            raise AutomationError(ERROR)
        try:
            self.directory = Path(directory).resolve(strict=True)
        except (OSError, ValueError):
            raise AutomationError(ERROR) from None
        self.root = self.directory.parent
        self.account = account
        self.pointer = _inside(self.root, self.root / (FOLDER + '-current') / (account + '.json'))

    @staticmethod
    def _ledger(directory):
        return strict_json(_read(_inside(directory, directory / LEDGER)).decode('utf8'))

    def _original(self, reference):
        path, raw = _source(self.root, reference)
        directory = path.parent.parent
        intent = strict_json(raw.decode('utf8'))
        if (directory.parent != self.root or path.parent.name != FOLDER or intent['schema'] != 1
                or intent['account'] != self.account or intent['status'] != 'pending'
                or path.name != intent['id'] + '-intent.json'):
            raise AutomationError(ERROR)
        _source(path.parent, intent['before'], MAX_EVIDENCE_BYTES)
        ledger = self._ledger(directory)
        _entry(ledger, intent)
        matches = [item for item in ledger['actions'] if item.get('index') == intent['action_index']]
        if (len(matches) != 1 or matches[0].get('run') != intent['run']
                or matches[0].get('intent') != CONFIRM or matches[0].get('action') != intent['action']
                or matches[0].get('status') not in ('requested','sent','not_sent')):
            raise AutomationError(ERROR)
        return intent, directory, ledger, matches[0]

    def _current(self):
        try:
            raw = _read(self.pointer)
        except FileNotFoundError:
            return None
        data = strict_json(raw.decode('utf8'))
        if set(data) != {'intent', 'resolution'}:
            raise AutomationError(ERROR)
        intent, directory, ledger, action = self._original(data['intent'])
        reference = data['resolution']
        if reference is not None:
            path, raw = _source(self.root, reference)
            result = strict_json(raw.decode('utf8'))
            owner = path.parent.parent
            if (owner.parent != self.root or path.parent.name != FOLDER or result['intent'] != data['intent']
                    or result['account'] != intent['account'] or result['schema'] != 1):
                raise AutomationError(ERROR)
            status = result['status']
            if status == 'not_sent' and owner == directory and action['status'] == 'not_sent':
                return data
            if status == 'verified' and owner == directory and result['departure'] == _departure(directory, ledger, action):
                return data
            if (status == 'superseded_by_verified_start'
                    and result['fresh'] != {key:intent[key] for key in ('session_id','run','run_id')}
                    and result['start'] == _new_start(owner, self._ledger(owner), result['fresh'])):
                return data
            raise AutomationError(ERROR)
        return data

    def current(self):
        try:
            return self._current()
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
            raise AutomationError(ERROR) from None

    def _publish(self, state):
        temp = self.pointer.with_name(uuid.uuid4().hex + '.tmp')
        try:
            _write(temp, encoded(state))
            replace_file(temp, self.pointer)
            if self.current() != state:
                raise AutomationError(ERROR)
        finally:
            temp.unlink(missing_ok=True)

    def arm(self, scope, request, scene, *, window, epoch):
        prior = self.current()
        if prior is not None and prior['resolution'] is None:
            raise AutomationError('同账号的上次奇物舍弃反馈待核对，未重复确认。')
        try:
            import cv2

            ident = uuid.uuid4().hex
            folder = _inside(self.directory, self.directory / FOLDER)
            before = folder / (ident + '-before.png')
            # Retain the current title and card pixels, excluding the bottom band.
            image = scene.image
            if image is None or image.shape[0] < 32:
                raise AutomationError(ERROR)
            ok, data = cv2.imencode('.png', image[:int(.90 * image.shape[0])])
            if not ok:
                raise AutomationError(ERROR)
            png = data.tobytes()
            _write(before, png, MAX_EVIDENCE_BYTES)
            intent = dict(schema=1, account=self.account, status='pending', id=ident, **scope,
                          action_index=request['index'], action=request['action'], window=window,
                          epoch=epoch, before=_ref(before, png))
            path = folder / (ident + '-intent.json')
            raw = encoded(intent)
            _write(path, raw)
            state = dict(intent=_ref(path, raw), resolution=None)
            self._original(state['intent'])
            self._publish(state)
            return state
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
            raise AutomationError('奇物舍弃意图未完整写入和回读，未发送确认。') from None

    def finish(self, state, status, *, fresh=None):
        try:
            if state['resolution'] is not None or self.current() != state:
                raise AutomationError(ERROR)
            intent, directory, ledger, action = self._original(state['intent'])
            result = dict(schema=1, intent=state['intent'], account=self.account, status=status)
            if status == 'not_sent' and directory == self.directory and action['status'] == 'not_sent':
                pass
            elif status == 'verified' and directory == self.directory:
                result['departure'] = _departure(directory, ledger, action)
            elif status == 'superseded_by_verified_start' and fresh != {key:intent[key] for key in ('session_id','run','run_id')}:
                result.update(fresh=fresh, start=_new_start(self.directory, self._ledger(self.directory), fresh))
            else:
                raise AutomationError(ERROR)
            folder = _inside(self.directory, self.directory / FOLDER)
            path = folder / (uuid.uuid4().hex + '-resolution.json')
            raw = encoded(result)
            _write(path, raw)
            self._publish(dict(intent=state['intent'], resolution=_ref(path, raw)))
        except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
            raise AutomationError(ERROR) from None
