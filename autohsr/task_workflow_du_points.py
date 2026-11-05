"""Check the native DU receipt before a task tree can use periodic points."""
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re

from . import du_periodic_points as points
from .currency_wars_initial import source_file_ref
from .models import AutomationError
from .task_workflow import WorkflowError


_LEDGER = 'differential-universe-ledger.json'
_MANIFEST = 'evidence_manifest.json'
_KEYS = ('session_id', 'requested_runs', 'completed_runs', 'current_run', 'run_results', 'periodic_points_goal')
_LIMIT = 64 * 1024 * 1024
_SHA256 = re.compile(r'[a-f0-9]{64}')


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _read(path, limit=_LIMIT):
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError('invalid receipt size')
    return raw


class _Evidence:
    def __init__(self, run_dir):
        self.root = Path(run_dir).resolve(strict=True)
        raw = _read(self.path(self.root / _MANIFEST))
        checksum = _read(self.path(self.root / 'evidence_manifest.sha256'), 256).decode('ascii').split()
        document = json.loads(raw)
        if (checksum != [_sha(raw), _MANIFEST] or document['algorithm'] != 'sha256'
                or type(document['files']) is not list):
            raise ValueError('invalid receipt manifest')
        self.index = {}
        for file in document['files']:
            name, length, digest = file['path'], file['size_bytes'], file['sha256']
            if (type(name) is not str or name in self.index or type(length) is not int or length < 0
                    or not _SHA256.fullmatch(digest)):
                raise ValueError('invalid receipt manifest row')
            self.index[name] = length, digest

    def path(self, value):
        path = Path(value)
        if (not path.is_absolute() or path.parent.resolve(strict=True) != self.root
                or path.resolve(strict=True) != self.root / path.name or not path.is_file()):
            raise ValueError('receipt source is outside this run')
        return self.root / path.name

    def verify(self, value, *, name=None, suffix=None):
        path = self.path(value)
        if name is not None and path.name != name or suffix is not None and not path.name.endswith(suffix):
            raise ValueError('receipt source has the wrong role')
        raw = _read(path)
        if self.index.get(path.name) != (len(raw), _sha(raw)):
            raise ValueError('receipt source differs from the native manifest')
        return raw


def _matches(left, right):
    # JSON booleans are not integer counters, including in nested rows.
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def _wins(data, maximum, evidence):
    completed, rows = data['completed_runs'], data['run_results']
    if (type(completed) is not int or not 0 <= completed <= maximum or type(rows) is not list
            or not completed <= len(rows) <= min(maximum, completed + 1)
            or type(data['current_run']) is not int or data['current_run'] != len(rows)):
        raise ValueError('invalid native completion count')
    for number, row in enumerate(rows, 1):
        if (type(row['run']) is not int or row['run'] != number or type(row['counted_run']) is not int
                or row['counted_run'] != number or row['origin'] != 'fresh'):
            raise ValueError('wrong native run origin')
        if number > completed:
            if row['counted'] is not False or row['status'] not in ('starting', 'not_started', 'running'):
                raise ValueError('invalid unfinished native run')
            continue
        if (row['status'] != 'completed' or row['counted'] is not True or row['mode'] != '周期演算'
                or row['difficulty_verified'] is not True or row['return_page'] not in ('home', 'mode_select', 'periodic_setup')):
            raise ValueError('native win was not counted and returned')
        captured = row['completion_evidence']
        if (not isinstance(row['run_id'], str) or not row['run_id'] or captured['run_id'] != row['run_id']
                or captured['session_id'] != data['session_id']):
            raise ValueError('completion captures belong to a different native run')
        for role, label in (('victory', 'victory'), ('return', 'fresh_return')):
            source = captured[role]
            if source['path'] != row[role + '_evidence']:
                raise ValueError('native completion capture path changed')
            raw = evidence.verify(source['path'], suffix=f'_du_{number:02d}_{label}.png')
            if _sha(raw) != source['sha256']:
                raise ValueError('native completion capture bytes changed')
    return completed


def _observations(goal, completed, evidence):
    history = goal['observations']
    if type(history) is not list or len(history) > completed + 1:
        raise ValueError('invalid native score history')
    previous = None
    for count, row in enumerate(history):
        current, cap, sources = row['current'], row['cap'], row['evidence']
        observed = datetime.fromisoformat(row['observed_at'])
        week = points.game_week(observed)
        if (type(row['completed_runs']) is not int or row['completed_runs'] != count or row['game_week'] != week
                or type(current) is not int or type(cap) is not int or not 0 <= current <= cap or cap == 0
                or row['capped'] is not (current == cap) or type(sources) is not list or len(sources) != 2
                or previous and (previous['capped'] or previous['cap'] != cap
                                 or previous['current'] > current or previous['game_week'] != week)):
            raise ValueError('conflicting native score observation')
        for index, source in enumerate(sources, 1):
            raw = evidence.verify(source['path'], suffix=f'_du_points_after_{count}_{index}.png')
            if _sha(raw) != source['sha256'] or source_file_ref(source['path'], evidence.root) != source:
                raise ValueError('score capture differs from its native reference')
        previous = row
    return previous


def verify_native_receipt(result, source, maximum):
    """Verify only this run's native score observations and counted fresh wins."""
    try:
        data = result['differential_universe']
        goal = data['periodic_points_goal']
        if (goal['source'] != 'du_home' or type(goal['maximum']) is not int or goal['maximum'] != maximum
                or data['mode'] != '周期演算' or type(data['requested_runs']) is not int
                or data['requested_runs'] != maximum or not isinstance(data['session_id'], str) or not data['session_id']):
            raise ValueError('native points scope differs from request')
        evidence = _Evidence(result['run_dir'])
        if Path(data['run_dir']).resolve(strict=True) != evidence.root:
            raise ValueError('native points scope is not the child run')
        if _sha(evidence.verify(source['path'], name='report.json')) != source['sha256']:
            raise ValueError('native report changed during handoff')
        ledger = json.loads(evidence.verify(data['ledger_path'], name=_LEDGER))
        if (type(ledger['schema_version']) is not int or ledger['schema_version'] != 1
                or any(not _matches(ledger[key], data[key]) for key in _KEYS)):
            raise ValueError('native ledger disagrees with the native report')
        completed = _wins(data, maximum, evidence)
        last = _observations(goal, completed, evidence)
        status = goal['status']
        if (status not in ('capped', 'exhausted', 'observing', 'below_cap', 'unverified')
                or result['status'] == 'success' and status != 'capped'
                or status in ('capped', 'exhausted') and (not last or last['completed_runs'] != completed
                    or len(data['run_results']) != completed or last['capped'] is not (status == 'capped'))
                or status == 'exhausted' and completed != maximum
                or status == 'below_cap' and (not last or last['capped'])):
            raise ValueError('native score and completion states disagree')
        return last
    except (AutomationError, KeyError, OSError, TypeError, ValueError) as error:
        raise WorkflowError('差分积分的原报告、账本或截图证据未核实，未采用局数或推进游戏任务。') from error


def goal_for_current_week(goal, last):
    """Keep the observation intact when its game week is over."""
    if last is None:
        return goal
    now = points.local_now()
    if datetime.fromisoformat(last['observed_at']) > now:
        raise WorkflowError('差分积分观察时间晚于当前时间，未采用该结果。')
    if points.game_week(now) == last['game_week']:
        return goal
    return dict(goal, status='unverified', reason='game_week_changed')


def current_projection(result, last):
    """An earlier game week's points stay historical; its verified wins stay intact."""
    data = result['differential_universe']
    native = data['periodic_points_goal']
    goal = goal_for_current_week(native, last)
    if goal is native:
        return result, False
    return dict(result, status='partial' if result['status'] == 'success' else result['status'],
                differential_universe=dict(data, periodic_points_goal=goal)), True
