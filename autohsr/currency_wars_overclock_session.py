"""Read and revalidate the private evidence for a single overclock A0 start."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
from stat import S_ISREG
import uuid

from .currency_wars_state import strict_json
from .models import AutomationError, Token


START_OPERATION = 'currency_wars_overclock_start'
FLOW_OPERATION = 'currency_wars_flow_test'
START_ACTION = 'start_overclock_a0'
START_FEEDBACK = 'a0_boss_preview'
SESSION = 'currency-overclock-session.json'
_FLOW_JOURNAL = 'currency-flow.json'
_STANDARD_SESSION = 'currency-standard-session.json'
_HEX_DIGEST = re.compile('[0-9a-f]{64}')
_MATCH_ID = re.compile('[0-9a-f]{32}')


def _matches(pattern, value):
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def client_key(client):
    """Identify the installed launcher configuration without recording its paths."""
    try:
        paths = client['executable'], client['source']
        digest = client['sha256']
        if not all(isinstance(path, str) and Path(path).is_absolute() for path in paths):
            raise ValueError
        if not _matches(_HEX_DIGEST, digest):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise AutomationError('超频开局的客户端来源不可核实。') from None
    value = json.dumps([*(os.path.normcase(path) for path in paths), digest], ensure_ascii=True)
    return hashlib.sha256(b'autohsr-overclock-client-v1\0' + value.encode('ascii')).hexdigest()


def _exists(path):
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    return True


def _directory(path):
    if not path.is_dir() or path.resolve(strict=True) != path:
        raise AutomationError('超频开局的原运行目录不可核实。')
    return path


def _read(path, limit, check_source):
    from .currency_wars_overclock import _read_bytes

    if not S_ISREG(path.lstat().st_mode) or path.resolve(strict=True) != path:
        raise AutomationError('超频开局记录的路径或文件类型不可核实。')
    return _read_bytes(path, limit, check_source=check_source)


def _track_source(revisions, check_source):
    from .currency_wars_overclock import _require_stable_source

    def track(path):
        first = path not in revisions
        _require_stable_source(path, revisions)
        if first and check_source is not None:
            check_source(path)
            _require_stable_source(path, revisions)

    return track


def _known_flow(data, match_id):
    if (type(data) is not dict or data.get('mode') != 'flow_test'
            or data.get('completion_verified') is not False or data.get('gameplay_enabled') is not False
            or type(data.get('start_from_lobby_requested')) is not bool
            or type(data.get('target_level')) is not int or not 0 <= data['target_level'] <= 10
            or type(data.get('screenshot')) is not str or type(data.get('actions')) is not list
            or not isinstance(data.get('action_status'), str) or not data['action_status'].strip()
            or any(type(data.get(key, False)) is not bool
                   for key in ('started_from_lobby', 'overclock_a0_started'))):
        return False
    actions = data['actions']
    bound = 'overclock_session_id' in data
    if not actions:
        return (data['action_status'] in ('observing', 'needs_decision')
                and (not bound or _matches(_MATCH_ID, data['overclock_session_id']))
                and not data.get('started_from_lobby') and not data.get('overclock_a0_started'))
    if bound and (match_id is None or data['overclock_session_id'] != match_id):
        return False
    if (not bound or data['action_status'] in ('observing', 'pending', 'unknown', 'capture_timeout', 'timeout')
            or not all(type(action) is dict and action.get('status') == 'verified'
                       and isinstance(action.get('action'), str) and action['action'].strip() for action in actions)):
        return False
    starts = sum(action['action'] == START_ACTION for action in actions)
    return starts <= 1 and (not data.get('overclock_a0_started') or starts == 1)


class OverclockSession:
    def __init__(self, run_dir, *, advancing=False):
        from .currency_wars_overclock import MAX_JOURNAL_BYTES

        if type(advancing) is not bool:
            raise AutomationError('超频推进需要明确指定已核实开局。')
        try:
            self.run_dir = _directory(Path(run_dir).absolute())
            if self.run_dir == self.run_dir.parent:
                raise AutomationError('超频开局缺少独立运行目录。')
            self.path = self.run_dir.parent / SESSION
            self.advancing = advancing
            self.match_id = None
            self.data = None
            self.raw = None
            self._history = None
            self._active_sources = None
            self._current_flow = self.run_dir / _FLOW_JOURNAL

            if _exists(self._current_flow):
                raise AutomationError('本次运行目录已有流程记录，未覆盖。')
            if _exists(self.path.with_suffix('.tmp')):
                raise AutomationError('已有超频开局待发布记录，保留原件并停止。')
            if advancing:
                if not _exists(self.path):
                    raise AutomationError('没有已核实的超频 A0 开局可推进。')
                self.raw = _read(self.path, MAX_JOURNAL_BYTES, None)
                self.data = self.require_active()
                self.match_id = self.data['match_id']
            else:
                if _exists(self.path):
                    raise AutomationError('已有超频开局记录，须核对原局，未重新开始。')
                self.match_id = uuid.uuid4().hex
            self.require_history()
        except (OSError, ValueError, TypeError, RecursionError):
            raise AutomationError('超频开局的运行目录或原记录不可核实。') from None

    def envelope(self, data, account, client):
        if not _matches(_HEX_DIGEST, account):
            raise AutomationError('超频开局缺少可核实的账号。')
        return dict(data, schema=1, match_id=self.match_id, run_dir=str(self.run_dir),
                    account_key=account, client_key=client_key(client))

    def _history_paths(self):
        root = self.path.parent
        standard = root / _STANDARD_SESSION
        paths = {standard} if _exists(standard) else set()
        from .currency_wars_overclock import JOURNAL

        for directory in root.iterdir():
            if directory.is_dir():
                for name in (JOURNAL, _FLOW_JOURNAL):
                    path = directory / name
                    if path == self._current_flow:
                        continue
                    if _exists(path):
                        paths.add(path)
        return paths

    def require_history(self, check_source=None):
        """Reject changed or unresolved prior records without modifying them."""
        from .currency_wars_overclock import JOURNAL, MAX_JOURNAL_BYTES, _resolved_configuration
        from .currency_wars_points_run import require_no_active_match
        from .currency_wars_session import MAX_SESSION_BYTES, StandardSession

        try:
            paths = self._history_paths()
            revisions = {}
            track = _track_source(revisions, check_source)
            for path in sorted(paths):
                limit = MAX_SESSION_BYTES if path.name == _STANDARD_SESSION else MAX_JOURNAL_BYTES
                raw = _read(path, limit, track)
                data = strict_json(raw.decode('utf-8'))
                if path.name == _STANDARD_SESSION:
                    StandardSession.validate(data)
                    require_no_active_match(data, purpose='超频开局或推进')
                elif path.name == JOURNAL:
                    if not _resolved_configuration(data, path.parent, check_source=track):
                        raise AutomationError('原超频配置尚未核实，保留记录并停止。')
                elif not _known_flow(data, self.match_id if self.advancing else None):
                    raise AutomationError('原超频流程尚未核实或未绑定本局，保留记录并停止。')
                elif self.advancing and any(action['action'] == 'advance_boss_preview' for action in data['actions']):
                    raise AutomationError('原超频首领预览已经推进，未重复发送。')
                if _read(path, limit, track) != raw:
                    raise AutomationError('原货币战争记录已经改变，未继续。')
            for path in revisions:
                track(path)
            if self._history_paths() != paths or self._history is not None and self._history != revisions:
                raise AutomationError('原货币战争记录或证据集合已经改变，未继续。')
            self._history = revisions
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            raise AutomationError('原货币战争记录或证据不可核实，保留原件。') from None

    def require_active(self, check_source=None):
        """Reopen the root session and all three original PNG proofs."""
        from .currency_wars_overclock import (
            CALIBRATED_CLIENT, MAX_FRAME_AGE, MAX_JOURNAL_BYTES, _START_A0, _check_evidence, _recorded_evidence,
        )

        try:
            revisions = {}
            track = _track_source(revisions, check_source)
            raw = _read(self.path, MAX_JOURNAL_BYTES, track)
            if raw != self.raw:
                raise AutomationError('超频 A0 开局原记录已改变，未继续。')
            data = strict_json(raw.decode('utf-8'))
            if (type(data) is not dict or type(data.get('schema')) is not int or data['schema'] != 1
                    or not _matches(_MATCH_ID, data.get('match_id'))
                    or self.match_id is not None and data['match_id'] != self.match_id
                    or not _matches(_HEX_DIGEST, data.get('account_key'))
                    or not _matches(_HEX_DIGEST, data.get('client_key'))
                    or data.get('mode') != 'overclock_a0_start' or data.get('status') != 'verified'
                    or data.get('match_started') is not True or data.get('completion_verified') is not False
                    or data.get('mode_verified') is not True or data.get('difficulty_verified') is not True
                    or data.get('client_version') != CALIBRATED_CLIENT):
                raise AutomationError('没有已核实的超频 A0 开局可推进。')

            origin = _directory(Path(data['run_dir']))
            if origin.parent != self.path.parent:
                raise AutomationError('超频 A0 开局原运行目录不在本地记录根下。')
            actions, feedback, observation = data['actions'], data['feedback'], data['observation']
            if (type(actions) is not list or len(actions) != 1 or type(actions[0]) is not dict
                    or actions[0].get('action') != START_ACTION or actions[0].get('status') != 'verified'
                    or type(feedback) is not list or len(feedback) != 2 or type(observation) is not dict
                    or observation.get('state') != START_FEEDBACK or type(observation.get('enemy_difficulty')) is not int
                    or observation['enemy_difficulty'] != 1):
                raise AutomationError('超频 A0 开局缺少唯一动作或两帧首领反馈。')

            action = actions[0]
            epoch, box = action.get('input_epoch'), action.get('target')
            if (type(epoch) is not int or epoch < 0 or type(box) is not list or len(box) != 4
                    or any(type(edge) not in (int, float) or not 0 <= edge <= 1 for edge in box)
                    or box[0] >= box[2] or box[1] >= box[3]
                    or not Token(_START_A0.label, 1., tuple(box)).within(_START_A0.roi)):
                raise AutomationError('超频 A0 开局原目标或输入代次不可核实。')
            before = _recorded_evidence(action.get('before'), 'a0_observed')
            first, second = (_recorded_evidence(item, START_FEEDBACK) for item in feedback)
            if not before.captured_at < first.captured_at < second.captured_at <= first.captured_at + MAX_FRAME_AGE:
                raise AutomationError('超频 A0 开局原证据的时间顺序不可核实。')
            proofs = [_check_evidence(item, origin, check_source=track) for item in (before, first, second)]
            if len({revisions[path][:2] for path in proofs}) != 3:
                raise AutomationError('超频 A0 开局需要三张独立的原始 PNG。')
            for path in revisions:
                track(path)
            if self._active_sources is not None and self._active_sources != revisions:
                raise AutomationError('超频 A0 开局原证据已改变，未继续。')
            self._active_sources = revisions
            return data
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            raise AutomationError('超频 A0 开局原记录或截图不可核实，保留原件。') from None
