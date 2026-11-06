"""Handoff from a saved DU points goal to its separate reward receipt."""
from contextlib import ExitStack, contextmanager
import hashlib
import json
import os
from pathlib import Path
import uuid

from .du_periodic_rewards import LIMIT
from .du_points_followup import FollowupWeek
from .du_reward_store import NAME as NATIVE_REWARD_RECEIPT, checked_run
from .models import AutomationError, Stopped
from .storage import hold_read_sources, replace_file
from .weekly_plan import _json_bytes, claim_account_key


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _child_sources(path, record):
    return (path, record['journal'], *(row['evidence']['path'] for row in record['observations']))


class WeeklyRewardHandoff:
    def __init__(self, receipt):
        data = receipt.data
        if (not isinstance(data, dict) or data.get('objective') != 'points' or data.get('state') != 'complete'
                or data.get('week') != receipt.slot.week):
            raise AutomationError('只有已保存的满额积分回执可交接周期领奖。')
        self.receipt = receipt
        self.root = receipt.root
        self.goal_bytes = _json_bytes(data)
        self.scope = dict(receipt.points_scope(data), receipt=str(receipt.path),
                          receipt_sha256=_sha(self.goal_bytes))
        self.week = self.scope['week']
        self.permission = FollowupWeek(self.week)
        self.path = receipt.folder / 'periodic-rewards' / f'{self.week}.json'
        self._held = False

    def require_current(self):
        if not self._held:
            raise AutomationError('周期领奖缺少本次原积分来源锁。')
        self.permission.require_current()

    def require_account(self, scene, confidence):
        if claim_account_key(scene, confidence) != self.scope['account_key']:
            raise AutomationError('当前差分主页账号与原周常积分回执不一致，未输入。')

    @contextmanager
    def hold_goal(self):
        receipt = self.receipt
        data = receipt.data
        with ExitStack() as locks:
            try:
                if self._held or receipt.path.resolve(strict=True) != receipt.path:
                    raise ValueError('invalid weekly receipt path')
                paths = (receipt.path, data['report'], data['ledger']['path'], *data['evidence'])
                locks.enter_context(hold_read_sources(paths))
                if receipt.path.read_bytes() != self.goal_bytes or _json_bytes(data) != self.goal_bytes:
                    raise ValueError('changed weekly receipt')
                original = receipt._report(data)
                last = original['differential_universe']['periodic_points_goal']['observations'][-1]
                if receipt._state(data, original) != 'complete' or last['current'] != LIMIT or last['cap'] != LIMIT:
                    raise ValueError('unverified capped weekly points')
            except (OSError, ValueError, KeyError, TypeError, IndexError) as error:
                raise AutomationError('差分周常原积分回执、报告、账本或截图未核实。') from error
            self.permission.require_current()
            self._held = True
            try:
                yield
            finally:
                self._held = False

    def inspect_child(self, report):
        if not report.get('du_rewards'):
            return None
        directory = Path(report['run_dir']).resolve(strict=True)
        record = checked_run(self.root, directory)
        if (report.get('operation') != 'du_rewards' or record != report['du_rewards']
                or record.get('weekly_points_source') != self.scope or record.get('game_week') != self.week):
            raise AutomationError('周期领奖子报告与本周原积分来源或独立账本不一致。')
        return record

    def _finished_child(self, path, report=None):
        if path.name != 'report.json' or path.resolve(strict=True) != path or path.parent.parent != self.root:
            raise AutomationError('周期领奖报告不在原生运行目录。')
        raw = path.read_bytes()
        if report is not None and raw != _json_bytes(report):
            raise AutomationError('周期领奖原生报告已变化。')
        stored = json.loads(raw)
        if (stored.get('status') != 'success' or stored.get('report_saved') is not True
                or Path(stored['run_dir']).resolve(strict=True) != path.parent):
            raise AutomationError('周期领奖报告未完整保存。')
        record = self.inspect_child(stored)
        if (record is None or record.get('status') != 'complete' or record.get('safe_to_restart') is not True
                or record.get('rewards_verified') is not True or record.get('periodic_rewards_verified') is not True):
            raise AutomationError('周期领奖到账或返回证据未完整核实。')
        journal = Path(record['journal'])
        data = dict(version=1, source=self.scope, report=str(path), report_sha256=_sha(raw),
                    journal=str(journal), journal_sha256=_sha(journal.read_bytes()))
        return data, record

    def read_finished(self):
        self.require_current()
        if self.path.resolve() != self.path:
            raise AutomationError('周期领奖周回执路径已变化。')
        if not self.path.exists():
            return None
        with hold_read_sources((self.path,)):
            data = json.loads(self.path.read_bytes())
            path = Path(data['report'])
            verified, record = self._finished_child(path)
            if data != verified:
                raise AutomationError('周期领奖周回执与原报告不一致。')
            with hold_read_sources(_child_sources(path, record)):
                if data != self._finished_child(path)[0]:
                    raise AutomationError('周期领奖周回执或原证据已变化。')
                self.require_current()
        return data

    def publish(self, report, record, *, checkpoint, stopped):
        self.require_current()
        path = Path(report['run_dir']).resolve(strict=True) / 'report.json'
        data, checked = self._finished_child(path, report)
        if checked != record:
            raise AutomationError('周期领奖原生账本已变化。')
        self.path.parent.mkdir(exist_ok=True)
        if self.path.parent.resolve(strict=True) != self.path.parent:
            raise AutomationError('周期领奖周回执目录已变化。')
        candidate = _json_bytes(data)
        temporary = self.path.with_suffix(f'.{uuid.uuid4().hex}.tmp')
        with temporary.open('xb') as stream:
            stream.write(candidate)
            stream.flush()
            os.fsync(stream.fileno())

        @contextmanager
        def verified_attempt():
            canonical = self.root / NATIVE_REWARD_RECEIPT
            sources = (*_child_sources(path, record), canonical)
            with hold_read_sources(sources):
                if (self.path.exists() or temporary.read_bytes() != candidate
                        or _sha(canonical.read_bytes()) != data['journal_sha256']
                        or self._finished_child(path, report)[0] != data):
                    raise AutomationError('周期领奖周回执已存在或原证据已变化，保留原件。')
                if stopped():
                    raise Stopped('计划已停止，已保留差分积分和独立领奖原回执。')
                self.require_current()
                yield

        replace_file(temporary, self.path, before_replace=checkpoint, attempt_scope=verified_attempt, exclusive=True)
        return data
