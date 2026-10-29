"""Durable, local ownership and receipts for sequential native standard matches."""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import uuid

from .currency_wars_session import StandardSession, read_session, require_session_access
from .currency_wars_state import strict_json
from .models import AutomationError
from .storage import replace_file


def runs_value(value):
    if type(value) is not int or not 0 <= value <= 2147483647:
        raise ValueError('货币战争局数须为0～2147483647的整数；0表示直到停止。')
    return value


def _hex(value, length=32):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{'+str(length)+'}', value) is not None


def validate_owner(value):
    if (type(value) is not dict or set(value) != {'loop_id', 'slot', 'reservation_id'}
            or not _hex(value['loop_id']) or not _hex(value['reservation_id'])
            or type(value['slot']) is not int or value['slot'] < 1):
        raise ValueError('循环对局归属记录无效')


def _raw(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode('utf-8')


def _read(path):
    with path.open('rb') as stream:
        raw = stream.read(1024*1024+1)
    if len(raw) > 1024*1024:
        raise AutomationError('循环记录超过大小限制，未继续。')
    return strict_json(raw.decode('utf-8'))


def _write(path, value):
    raw = _raw(value)
    if len(raw) > 1024*1024:
        raise AutomationError('循环记录超过大小限制，未继续。')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        stream.write(raw)
        stream.flush()
        import os
        os.fsync(stream.fileno())
    replace_file(temporary, path)


def _immutable(path, value):
    raw = _raw(value)
    if path.exists():
        if path.read_bytes() != raw:
            raise AutomationError('已有逐局回执内容不符，未覆盖。')
        return
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        import os
        os.fsync(stream.fileno())


@contextmanager
def loop_lock(root):
    """OS lock releases on process exit; a crashed loop leaves no stale flag."""
    import msvcrt
    root.mkdir(parents=True, exist_ok=True)
    with (root/'currency-loop.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise AutomationError('另一个货币战争循环正在运行。') from error
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


class LoopStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.pointer = self.root/'currency-loop-current.json'
        self.journal = self.root/'currency-standard-session.json'
        self.data = None
        self.path = None

    def _inside(self, value):
        path = Path(value).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise AutomationError('循环证据路径不在本地运行目录内。')
        return path

    def load(self):
        if not self.pointer.exists():
            return None
        pointer = _read(self.pointer)
        if type(pointer) is not dict or set(pointer) != {'loop_id'} or not _hex(pointer['loop_id']):
            raise AutomationError('循环入口记录无效，未开始新局。')
        self.path = self.root/'currency-loops'/pointer['loop_id']/'loop.json'
        data = _read(self.path)
        self.validate(data)
        if data['loop_id'] != pointer['loop_id']:
            raise AutomationError('循环入口与逐局目录不一致。')
        self.data = data
        return data

    @staticmethod
    def validate(data):
        from .currency_wars_names import validate_name
        from .currency_wars_standard_policy import STRATEGIES
        from .currency_wars_equipment_mode import validate_fast_mode
        if (type(data) is not dict or data.get('schema') != 1 or not _hex(data.get('loop_id'))
                or data.get('status') not in ('active', 'complete', 'cancelled', 'exhausted', 'expired')
                or type(data.get('completed')) is not int or data['completed'] < 0
                or type(data.get('options')) is not dict):
            raise AutomationError('循环记录结构无效。')
        options = data['options']
        required = {'runs', 'strategy', 'remembrance_name', 'equipment_fast_mode'}
        if not required <= set(options) or set(options)-required-{'until_points'}:
            raise AutomationError('循环设置结构无效。')
        if type(options.get('until_points', False)) is not bool:
            raise AutomationError('周积分循环开关须为布尔值。')
        runs_value(options['runs']); validate_name(options['remembrance_name']); validate_fast_mode(options['equipment_fast_mode'])
        if (options['strategy'] not in STRATEGIES or options['runs'] and data['completed'] > options['runs']
                or data.get('account_key') is not None and not _hex(data['account_key'], 64)
                or data.get('last_receipt') is not None and not _hex(data['last_receipt'], 64)):
            raise AutomationError('循环设置、账号或回执无效。')
        active = data.get('active')
        if active is not None:
            validate_owner(active.get('owner'))
            if (active['owner']['loop_id'] != data['loop_id'] or active['owner']['slot'] != data['completed']+1
                    or active.get('match_id') is not None and not _hex(active['match_id'])
                    or data['status'] != 'active'):
                raise AutomationError('循环当前局归属或编号无效。')
        from .currency_wars_points_goal import enabled, validate
        validate(data)
        if enabled(data):
            goal = data['points_goal']
            full = (goal['observation'] is not None and goal['observation']['weekly_target_verified'] is True
                    and goal['observation']['game_week'] == goal['week'] and goal['checked_completed'] == data['completed'])
            if (data['status'] == 'complete' and not full
                    or data['status'] == 'exhausted' and (not options['runs'] or data['completed'] != options['runs'] or full)):
                raise AutomationError('周积分目标终态与积分或局数不符。')
        elif (data['status'] in ('exhausted', 'expired')
              or data['status'] == 'complete' and (not options['runs'] or data['completed'] != options['runs'])):
            raise AutomationError('循环完成计数或终态无效。')
        from .currency_wars_weekly import validate_week
        validate_week(data)

    def save(self):
        self.validate(self.data)
        _write(self.path, self.data)

    def begin(self, options, *, weekly=None):
        previous = self.load()
        from .currency_wars_weekly import WeekSpec, check_complete, ensure_index, index_path, unfinished
        if previous is not None and unfinished(self):
            raise AutomationError('原货币战争周常尚未结束，未覆盖为新循环。')
        if previous is not None and previous.get('weekly_plan',{}).get('state')=='complete':check_complete(self)
        if previous is not None and previous['status'] == 'active':
            raise AutomationError('已有未结束循环；请明确接续，未创建第二份目标。')
        if weekly is not None:
            from .currency_wars_points import game_week,local_now
            if not isinstance(weekly,WeekSpec) or weekly.week!=game_week(local_now()):
                raise AutomationError('周常目标类型无效或已跨周，未建立新循环。')
            if index_path(self.root,weekly.account,weekly.week).exists():
                raise AutomationError('该账号本周已有目标，未新增局数预算。')
        loop_id = uuid.uuid4().hex
        self.path = self.root/'currency-loops'/loop_id/'loop.json'
        self.data = dict(schema=1, loop_id=loop_id, options=deepcopy(options), status='active',
                         completed=0, last_receipt=None, account_key=None, active=None, development_only=True)
        if options.get('until_points', False):
            from .currency_wars_points_goal import begin
            self.data['points_goal'] = begin()
        if weekly is not None:
            self.data['weekly_plan']=weekly.metadata()
            self.data['account_key']=weekly.account
            self.data['points_goal']['week']=weekly.week
        self.save()
        _write(self.pointer, dict(loop_id=loop_id))
        if weekly is not None:ensure_index(self)

    def reserve(self):
        if self.data['active'] is None:
            self.data['active'] = dict(owner=dict(loop_id=self.data['loop_id'], slot=self.data['completed']+1,
                                                 reservation_id=uuid.uuid4().hex), match_id=None,
                                       initial_run_dir=None, latest_run_dir=None)
            self.save()
        return LoopGuard(self)

    def archive_unstarted(self):
        """Preserve a never-submitted owned reservation before points navigation.

        A pending/unknown start is deliberately ineligible. A rename crash is
        recovered from the durable intent, without repeating any game input.
        """
        data = self.data
        active = data['active']
        if active is None:
            if data.get('empty_archive_intent') is not None:
                raise AutomationError('空局归档意图缺少当前归属。')
            return
        intent = data.get('empty_archive_intent')
        guard = LoopGuard(self)
        if intent is None:
            session = StandardSession(self.journal).data
            guard.require_access(session)
            if session is None:
                destination = self.path.parent/('unstarted-reservation-'+active['owner']['reservation_id']+'.json')
                _immutable(destination, dict(schema=1, owner=active['owner'], match_id=None, input_started=False))
                data['active'] = None
                self.save()
                return
            if (session['status'] != 'start_pending' or session['actions']
                    or session.get('completion_verified') is not False or session.get('start_verified') is True):
                raise AutomationError('本局已有开局输入或结果，不能作为空记录归档。')
            destination = self.path.parent/('unstarted-'+session['match_id']+'.session.json')
            if destination.exists():
                raise AutomationError('空局归档目标已存在且无提交意图，未覆盖。')
            intent = dict(archive=str(destination), owner=deepcopy(active['owner']), match_id=session['match_id'],
                          session_sha256=hashlib.sha256(self.journal.read_bytes()).hexdigest())
            data['empty_archive_intent'] = intent
            self.save()
        destination = self._inside(intent['archive'])
        if (set(intent) != {'archive','owner','match_id','session_sha256'} or intent['owner'] != active['owner']
                or not _hex(intent['match_id']) or not _hex(intent['session_sha256'],64)
                or destination != self.path.parent/('unstarted-'+intent['match_id']+'.session.json')):
            raise AutomationError('空局归档的路径、身份或归属不符。')
        if self.journal.exists() and destination.exists():
            raise AutomationError('当前与空局归档同时存在，未删除记录。')
        source = self.journal if self.journal.exists() else destination
        if not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest() != intent['session_sha256']:
            raise AutomationError('空局归档来源缺失或改变。')
        session = StandardSession(source).data
        guard.require_access(session)
        if (session['match_id'] != intent['match_id'] or session['status'] != 'start_pending' or session['actions']
                or session.get('completion_verified') is not False or session.get('start_verified') is True):
            raise AutomationError('不能将已提交或未核实的开局作为空记录归档。')
        if source == self.journal:
            self.journal.rename(destination)
        _immutable(destination.with_suffix('.receipt.json'), dict(schema=1, input_started=False, **intent))
        data['active'] = None
        data.pop('empty_archive_intent')
        self.save()

    def check_tail(self):
        """Verify the last committed receipt against its unchanged archive."""
        if self.data['completed'] == 0:
            if self.data['last_receipt'] is not None:
                raise AutomationError('空循环存在不符回执。')
            return
        path = self.path.parent/(str(self.data['completed'])+'.session.receipt.json')
        receipt = _read(path)
        if (receipt.get('slot') != self.data['completed'] or receipt.get('count') is not True
                or hashlib.sha256(path.read_bytes()).hexdigest() != self.data['last_receipt']):
            raise AutomationError('上一局回执被改动，未继续循环。')
        archive = self._inside(receipt['archive'])
        if hashlib.sha256(archive.read_bytes()).hexdigest() != receipt['session_sha256']:
            raise AutomationError('上一局归档被改动，未继续循环。')
        session = StandardSession(archive).data
        owner = session.get('loop_owner', {})
        if (owner.get('loop_id') != self.data['loop_id'] or owner.get('slot') != self.data['completed']
                or session['match_id'] != receipt['match_id'] or session.get('account_key') != self.data['account_key']):
            raise AutomationError('上一局归属或账号不符，未继续循环。')
        proof = self.proof(session, receipt['report'], recovery=receipt['recovered'])
        if any(proof[key] != receipt[key] for key in proof):
            raise AutomationError('上一局原始证据改变，未继续循环。')

    def proof(self, session, report_path, *, recovery=False, candidate=None):
        """Require native final-node provenance, all four transitions and files."""
        from .currency_wars_ending import ENDING_STEPS
        from .currency_wars_standard_progress import verified_attempt
        from .currency_wars_standard_ledger import ledger_status
        StandardSession.validate(session)
        active = dict(session, status='active')
        attempt = verified_attempt(active)
        start_id = attempt['start_action_id']
        actions = session['actions']
        started = actions[0] if actions else {}
        if (session.get('start_verified') is not True or started.get('action') != 'start_standard_a8_40'
                or started.get('expected') != 'boss_preview' or started.get('status') != 'verified'
                or started.get('target', []) != []):
            raise AutomationError('本局缺少已核实开局的原始动作来源。')
        if (session['status'] != 'settled' or session['completion_verified'] is not True
                or session.get('settlement_verified') is not True or not session.get('development_only')
                or not attempt['node'].startswith('3-') or attempt.get('result_kind') != 'final_victory'
                or session.get('match_victory_observed') is not True or session.get('victory_start_action_id') != start_id
                or not _hex(session.get('account_key'), 64) or ledger_status(actions) != 'clear'
                or len(actions) < 5 or actions[-5]['id'] != start_id):
            raise AutomationError('本局缺少完整胜利、结算或账本核验，未归档或计数。')
        for name in ('exchange', 'equipment', 'reward', 'consumable', 'investment', 'popup', 'reorder', 'sale'):
            protocol = session.get(name)
            if protocol and protocol.get('status') != 'verified':
                raise AutomationError('本局仍有未完成的核验：'+name)
        sources = [attempt['result']]
        for action, page in zip(actions[-4:], ENDING_STEPS):
            if (action['action'] != 'settle_standard_'+page or action['expected'] != ENDING_STEPS[page][1]
                    or action.get('target') != [attempt['node'], start_id] or action['status'] != 'verified'):
                raise AutomationError('终局四步结算链不完整，未归档。')
        for action in [started, actions[start_id], *actions[-4:]]:
            sources.extend([action.get('before'), action.get('after')])
        files = {}
        for source in sources:
            if not isinstance(source, str) or not source:
                raise AutomationError('结算缺少原始证据路径。')
            path = self._inside(source)
            if not path.is_file() or path.stat().st_size == 0:
                raise AutomationError('结算原始证据缺失，未归档。')
            files[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
        report_path = self._inside(report_path)
        report = candidate if candidate is not None else read_session(report_path)
        if (report.get('status') != 'success' or report.get('report_saved') is not True
                or report.get('operation') != ('currency_wars_standard_recovery' if recovery else 'currency_wars_standard')
                or report.get('currency_wars') != session):
            raise AutomationError('本局成功报告尚未完整保存，未归档或进入下一局。')
        return dict(ending_evidence=files, report=str(report_path),
                    report_sha256=hashlib.sha256(report_path.read_bytes()).hexdigest() if candidate is None else None,
                    recovered=recovery)

    def archive(self, *, count=True, recover=False):
        """Intent -> rename -> immutable receipt -> counter; restart repeats no IO."""
        data = self.data
        active = data['active']
        intent = data.get('archive_intent')
        if intent is None:
            session = StandardSession(self.journal).data
            if session is None:
                raise AutomationError('当前对局记录缺失，未计数。')
            if count:
                LoopGuard(self).require_access(session, settled=True)
            elif session.get('loop_owner') is not None:
                raise AutomationError('已有对局属于另一个循环，未转移归属。')
            report_dir = (session.get('continuations') or [session['run_dir']])[-1]
            report_path = self._inside(report_dir)/'report.json'
            recovery = False
            if recover:
                # An explicit resume can save a new, read-only audit without
                # rewriting a failed original report or replaying settlement.
                original = str(report_path)
                original_hash = hashlib.sha256(report_path.read_bytes()).hexdigest() if report_path.is_file() else None
                report_path = self.path.parent/(session['match_id']+'.recovery.json')
                audit = dict(operation='currency_wars_standard_recovery', status='success', report_saved=True,
                             currency_wars=session, original_report=original, original_report_sha256=original_hash,
                             read_only=True, development_only=True)
                # Validate all native evidence before creating a recovery file.
                # Use a temporary candidate only; it never changes game records.
                self.proof(session, report_path, recovery=True, candidate=audit)
                _immutable(report_path, audit)
                recovery = True
            proof = self.proof(session, report_path, recovery=recovery)
            slot = active['owner']['slot'] if count else 'prior-'+session['match_id']
            destination = self.path.parent/(str(slot)+'.session.json')
            if destination.exists():
                raise AutomationError('归档目标已存在但尚无提交意图，未覆盖。')
            intent = dict(count=count, archive=str(destination), session_sha256=hashlib.sha256(self.journal.read_bytes()).hexdigest(),
                          match_id=session['match_id'], slot=slot, previous=data['last_receipt'], **proof)
            data['archive_intent'] = intent
            self.save()
        elif intent['count'] is not count:
            raise AutomationError('归档恢复用途与已记录意图不符。')
        destination = self._inside(intent['archive'])
        slot = active['owner']['slot'] if count else 'prior-'+intent['match_id']
        if (intent['slot'] != slot or destination != self.path.parent/(str(slot)+'.session.json')
                or intent['previous'] != data['last_receipt']):
            raise AutomationError('归档目的地、局号或前序回执不符。')
        source_exists = self.journal.exists()
        if source_exists and destination.exists():
            raise AutomationError('当前与归档对局同时存在，未删除任何记录。')
        actual = self.journal if source_exists else destination
        if not actual.is_file() or hashlib.sha256(actual.read_bytes()).hexdigest() != intent['session_sha256']:
            raise AutomationError('归档源缺失或与已记录意图不符。')
        session = StandardSession(actual).data
        if session['match_id'] != intent['match_id']:
            raise AutomationError('归档对局身份改变。')
        if count:
            LoopGuard(self).require_access(session, settled=True)
            if data['account_key'] != session.get('account_key'):
                raise AutomationError('结算账号尚未与循环绑定，未计数。')
        proof = self.proof(session, intent['report'], recovery=intent['recovered'])
        if any(proof[key] != intent[key] for key in proof):
            raise AutomationError('归档证据在提交期间改变，未计数。')
        if source_exists:
            # Path.rename refuses an existing destination on Windows.
            self.journal.rename(destination)
        receipt_path = destination.with_suffix('.receipt.json')
        _immutable(receipt_path, dict(schema=1, development_only=True, **intent))
        if count:
            data['completed'] += 1
            data['last_receipt'] = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            data['active'] = None
        data.pop('archive_intent')
        self.save()


class LoopGuard:
    """The child checks this reservation before preparing and before every IO."""
    def __init__(self, store):
        self.store = store
        self.owner = deepcopy(store.data['active']['owner'])
        self.week = store.data.get('points_goal', {}).get('week')
        self.weekly = deepcopy(store.data.get('weekly_plan'))

    def current(self):
        data = _read(self.store.path)
        self.store.validate(data)
        if (data['status'] != 'active' or data['active'] is None or data['active']['owner'] != self.owner
                or data['options'] != self.store.data['options']
                or data.get('points_goal', {}).get('week') != self.week):
            raise AutomationError('循环归属或冻结设置改变，未继续输入。')
        if data.get('weekly_plan')!=self.weekly:
            raise AutomationError('周常冻结目标在本局期间改变，未继续输入。')
        self.store.data.clear()
        self.store.data.update(data)
        return self.store.data

    def require_access(self, session, resume=False, *, settled=False, input_pending=False):
        data = self.current()
        active = data['active']
        if session is None:
            if active['match_id'] is not None or resume or settled:
                raise AutomationError('循环所属当前局缺失，未重开。')
            return
        owner = session.get('loop_owner')
        empty = session['status'] == 'start_pending' and not session['actions']
        if (owner != self.owner and not (owner is None and empty and session['run_dir'] == active['initial_run_dir'])
                or active['match_id'] not in (None, session['match_id'])):
            raise AutomationError('当前标准对局不属于此循环，未接管。')
        options = data['options']
        if owner is not None and any(session.get(key, default) != options[key] for key, default in
                                     (('strategy', 'default'), ('remembrance_name', ''), ('equipment_fast_mode', False))):
            raise AutomationError('当前局与循环冻结设置不符。')
        if data['account_key'] is not None and session.get('account_key') not in (None, data['account_key']):
            raise AutomationError('当前局账号与循环记录不符。')
        if settled:
            if session['status'] != 'settled':
                raise AutomationError('当前局尚未结算。')
        elif input_pending:
            if session['status'] not in ('active', 'start_pending'):
                raise AutomationError('循环当前局状态不允许输入。')
        elif not empty:
            require_session_access(session, resume)
        elif resume:
            raise AutomationError('尚无开局输入，不能作为已开局接续。')

    def register_run(self, directory):
        data = self.current()
        path = str(self.store._inside(directory))
        active = data['active']
        if active['initial_run_dir'] is None:
            active['initial_run_dir'] = path
        active['latest_run_dir'] = path
        self.store.save()

    def bind(self, session):
        self.require_access(session.data, resume=session.data['status'] == 'active')
        session.data['loop_owner'] = deepcopy(self.owner)
        session.persist()
        self.store.data['active']['match_id'] = session.data['match_id']
        self.store.save()

    def authorize(self, scene, session, confidence):
        from .currency_wars_identity import account_key
        self.require_access(session, input_pending=True)
        current = account_key(scene, confidence)
        data = self.store.data
        if data['account_key'] is not None and data['account_key'] != current:
            raise AutomationError('当前账号与循环记录不同，未开始或继续对局。')
        if data['active']['match_id'] != session['match_id'] or session.get('loop_owner') != self.owner:
            raise AutomationError('本局归属尚未写入，未发送输入。')
        if session['actions'] and session['actions'][-1]['action'] == 'start_standard_a8_40':
            self.require_start()
        if data['account_key'] is None:
            data['account_key'] = current
            self.store.save()

    def require_start(self):
        from .currency_wars_points_goal import require_start
        self.current()
        require_start(self.store)
