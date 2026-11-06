"""Independent red-dot reward custody; unresolved inputs are never replayed."""
from copy import deepcopy
from datetime import date
import hashlib
import json
import math
import os
from pathlib import Path
import re

from .models import AutomationError
from .storage import replace_file

NAME = 'du-rewards-session.json'
MAX_BYTES = 16 * 1024 * 1024


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf-8')


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def read(path):
    from .currency_wars_state import strict_json
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise AutomationError('差分领奖记录过大，原记录保留。')
    return strict_json(raw.decode('utf-8'))


def _write(path, data, *, before_replace=None):
    raw = encoded(data)
    if len(raw) > MAX_BYTES:
        raise AutomationError('差分领奖记录过大，未提交输入。')
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    replace_file(temporary, path, before_replace=before_replace)


def _checked(root, data, *, sources=False):
    from .currency_wars_initial import source_file_ref
    from . import du_periodic_rewards as periodic
    if (type(data) is not dict or data.get('schema') != 1 or data.get('operation') != 'du_rewards'
            or data.get('digest') != digest({key: value for key, value in data.items() if key != 'digest'})):
        raise AutomationError('差分领奖原记录不完整，未补写或重放。')
    directory = Path(data['run_dir']).resolve(strict=True)
    if (not directory.is_relative_to(root) or directory == root
            or Path(data['journal']).resolve() != directory / 'du-rewards.json'
            or read(directory / 'du-rewards.json') != data):
        raise AutomationError('差分领奖原运行来源不一致，未继续。')
    observations=data['observations']
    if (type(observations) is not list or len(observations)>1000 or type(data.get('actions')) is not list
            or len(data['actions'])>240 or type(data.get('claims')) is not list
            or type(data.get('input_epoch')) is not int or type(data.get('window')) is not int):
        raise AutomationError('差分领奖记录结构不完整。')
    periodic_only = (data.get('requested_categories') == [periodic.CATEGORY]
                     or 'periodic_rewards_verified' in data or 'game_week' in data
                     or any(action['request']['intent'] in (periodic.OPEN, periodic.CLAIM)
                            for action in data['actions']))
    if periodic_only:
        week = date.fromisoformat(data['game_week'])
        if (week.weekday() != 0 or week.isoformat() != data['game_week']
                or data.get('requested_categories') != [periodic.CATEGORY]
                or type(data.get('periodic_rewards_verified')) is not bool or data.get('use_cassettes') is not False
                or data.get('battle_started') is not False
                or data.get('cassettes') != dict(initial_balance=None, limit=0, spent_verified=0)):
            raise AutomationError('差分周期领奖范围、游戏周或资源义务改变。')
    for index,item in enumerate(observations):
        stamp=item['captured_at']
        if (item.get('id')!=index or item.get('input_epoch')!=data['input_epoch'] or item.get('window')!=data['window']
                or type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp<=0):
            raise AutomationError('差分领奖观察代次或捕获来源不完整。')
        if periodic_only and (item.get('game_week') != data['game_week']
                or type(item.get('capture_sequence')) is not int or item['capture_sequence'] <= 0):
            raise AutomationError('差分周期领奖反馈缺少游戏周或捕获序号。')
    def pair(indexes,before=0,kind=None):
        if type(indexes) is not list or len(indexes)!=2 or any(type(index) is not int or not 0<=index<len(observations) for index in indexes):
            raise AutomationError('差分领奖缺少独立反馈对。')
        first,last=[observations[index] for index in indexes]
        if (not before<first['captured_at']<last['captured_at']
                or first['evidence']['path']==last['evidence']['path']
                or first.get('readback')!=last.get('readback')
                or kind is not None and any(item['kind']!=kind for item in (first,last))):
            raise AutomationError('差分领奖反馈对不连续或语义不同。')
        if periodic_only and (last['capture_sequence'] != first['capture_sequence'] + 1
                or first['evidence']['pixel_sha256'] == last['evidence']['pixel_sha256']):
            raise AutomationError('差分周期领奖反馈缺少两次连续的独立画面。')
        return last
    for index,action in enumerate(data['actions']):
        request=action['request'];before=action['before']
        if (action.get('id')!=index or request.get('id')!=index or type(before) is not int
                or not 0<=before<len(observations) or sum(request.get(field) is not None for field in ('target','key','drag'))!=1):
            raise AutomationError('差分领奖动作与原意图不完整。')
        if index and data['actions'][index-1]['status']=='verified':
            previous=observations[data['actions'][index-1]['after'][-1]];current=observations[before]
            if (current['captured_at']<previous['captured_at'] or current['captured_at']==previous['captured_at']
                    and (current['tokens_digest']!=previous['tokens_digest']
                         or current['evidence']['pixel_sha256']!=previous['evidence']['pixel_sha256'])):
                raise AutomationError('差分领奖动作之间的当前来源不连续。')
        if action['status']=='verified':pair(action['after'],observations[before]['captured_at'])
    aborted=(data.get('status')=='abort_before_input' and data.get('safe_to_restart') is True
             and data['actions']==[] and data['claims']==[] and data.get('obligation') is None
             and data.get('rewards_verified') is False
             and (not periodic_only or data['periodic_rewards_verified'] is False))
    # A periodic return can be fully observed before publication fails.
    # Validate the original chain even when the record must stay unknown.
    if (data.get('safe_to_restart') is True and not aborted
            or periodic_only and 'final_home_frames' in data):
        if not re.fullmatch('[0-9a-f]{64}',str(data.get('account_key',''))):
            raise AutomationError('差分领奖没有当前账号来源。')
        final=pair(data['final_home_frames'],kind='home')
        if final['readback'].get('account')!=data['account_key']:
            raise AutomationError('差分领奖最终主页账号不符。')
        if data['actions']:
            last=data['actions'][-1]
            if last['request']['intent']!='du_reward_back_home' or data['final_home_frames']!=last['after']:
                raise AutomationError('差分领奖最终主页不是最后返回动作的反馈。')
        elif data['final_home_frames']!=data['home_frames']:
            raise AutomationError('零输入差分领奖最终主页来源改变。')
        budget=data['cassettes'];spent=0
        sources_by_intent={'du_reward_dot':'拟合等级','du_reward_claim':'稳态数组',
            'du_reward_gallery_claim':'可能性画廊','du_reward_unlock':'月下奇谭'}
        if periodic_only:
            _checked_periodic(data, pair, final)
            sources_by_intent[periodic.CLAIM] = periodic.CATEGORY
        expected={action['id']:sources_by_intent[action['request']['intent']] for action in data['actions']
                  if action['request']['intent'] in sources_by_intent}
        actual={}
        for claim in data['claims']:
            action_id=claim.get('action_id')
            if type(action_id) is not int or action_id in actual:
                raise AutomationError('差分领奖领取动作与回执不唯一，未合并或丢弃原义务。')
            actual[action_id]=claim.get('source')
        if actual!=expected:
            raise AutomationError('差分领奖原领取动作缺少对应回执，未降为零领取或零消耗。')
        for index,claim in enumerate(data['claims']):
            if claim['id']!=index or claim['status']!='verified' or not 0<=claim['action_id']<len(data['actions']):
                raise AutomationError('差分领奖原领取义务未核实。')
            action=data['actions'][claim['action_id']]
            expected={'拟合等级':'fit_rewards','稳态数组':'steady_rewards','可能性画廊':'gallery_milestones',
                      '月下奇谭':'moon_rewards',periodic.CATEGORY:periodic.PANEL}[claim['source']]
            return_id=claim['return_action_id']
            expected_id=claim['action_id']+(2 if claim['source']=='月下奇谭' else 1)
            if type(return_id) is not int or return_id!=expected_id or not return_id<len(data['actions']):
                raise AutomationError('差分领奖返回动作不属于本次领取。')
            returned=data['actions'][return_id]
            if (claim['return_frames']!=returned['after'] or returned['request']['intent']!=
                    ('du_reward_back_moon_rewards' if claim['source']=='月下奇谭' else 'du_reward_dismiss')):
                raise AutomationError('差分领奖返回反馈不是本次对应动作来源。')
            returned_frame=pair(claim['return_frames'],kind=expected)
            if observations[returned['before']]['captured_at']<observations[action['after'][-1]]['captured_at']:
                raise AutomationError('差分领奖返回来源早于本次领取反馈。')
            readback=returned_frame['readback']
            if claim['source']=='月下奇谭':
                if (data['use_cassettes'] is not True or claim['amount']!=100
                        or claim['balance_before']!=budget['initial_balance']-spent
                        or claim['balance_after']!=claim['balance_before']-100):
                    raise AutomationError('月下卡带原消耗来源不符。')
                pair(claim['unlock_frames'],kind='moon_unlocked');spent+=100
                if claim['unlock_frames']!=action['after'] or readback.get('balance')!=claim['balance_after']:
                    raise AutomationError('月下卡带到账或返回余额不属于本次解锁。')
            else:
                if claim['overlay']!=action['after']:raise AutomationError('差分到账展示不是本次领取反馈。')
                overlay = pair(claim['overlay'],kind='reward_overlay')
                identity=claim['identity']
                if claim['source']=='拟合等级':
                    valid=readback.get('tier')==identity['tier'] and readback.get('state')==[identity['state']['level'],identity['state']['xp']]
                elif claim['source']=='可能性画廊':
                    valid=readback==dict(category=identity['category'],threshold=identity['threshold'],status='claimed')
                elif claim['source'] == periodic.CATEGORY:
                    scope = dict(account=data['account_key'], current=periodic.LIMIT, cap=periodic.LIMIT,
                                 game_week=data['game_week'])
                    items = overlay['readback']
                    valid = (identity == dict(**scope, tiers=list(periodic.TIERS))
                             and readback == dict(**scope, claimed_tiers=list(periodic.TIERS))
                             and type(items) is list and bool(items)
                             and all(type(quantity) is int and 0 < quantity <= 1000000000 for quantity in items))
                else:
                    valid=(readback.get('condition')==identity['condition'] and readback.get('claimed') is True
                        and all(readback.get('scope',{}).get(key)==identity['scope'][key] for key in ('tab','group','total')))
                if not valid:raise AutomationError('差分领奖返回不是原奖励档位的已领取状态。')
        if (budget['spent_verified']!=spent or type(budget['limit']) is not int or spent>budget['limit']
                or budget['initial_balance'] is not None and budget['limit']!=(budget['initial_balance']//100)*100):
            raise AutomationError('月下卡带冻结上限或已核实消耗改变。')
    if sources:
        for item in data['observations']:
            reference = item['evidence']
            if source_file_ref(reference['path'], directory) != reference:
                raise AutomationError('差分领奖原PNG来源改变，未继续。')
    return data


def _checked_periodic(data, pair, final):
    from . import du_periodic_rewards as periodic

    success = data['periodic_rewards_verified']
    restartable = data.get('safe_to_restart')
    expected_status = ('complete' if success else 'partial') if restartable else 'unknown'
    scope = dict(account=data['account_key'], current=periodic.LIMIT, cap=periodic.LIMIT,
                 game_week=data['game_week'])
    actions = data['actions']
    expected = [periodic.OPEN, periodic.CLAIM, periodic.DISMISS, periodic.BACK] if success else [
        periodic.OPEN, periodic.BACK]
    if ([action['request']['intent'] for action in actions] != expected
            or any(action['status'] != 'verified' for action in actions)
            or type(restartable) is not bool or data['status'] != expected_status
            or data.get('obligation') is not None or data.get('rewards_verified') is not (success and restartable)
            or data.get('remaining_categories') != ([] if success else [periodic.CATEGORY])):
        raise AutomationError('差分周期领奖动作、回执或最终状态不符。')
    home = pair(data['home_frames'], kind='home')
    opened = pair(actions[0]['after'], kind=periodic.PANEL)
    if (home['readback'] != dict(**scope, marked=True)
            or opened['readback'] != dict(**scope, available=success)
            or type(final['readback'].get('marked')) is not bool
            or final['readback'] != dict(**scope, marked=final['readback']['marked'])
            or success and final['readback']['marked']):
        raise AutomationError('差分周期领奖原主页、同周面板或返回范围不符。')
    observations = data['observations']
    previous = home
    for action in actions:
        before = observations[action['before']]
        first, last = (observations[index] for index in action['after'])
        request = action['request']
        if (any(before[field] != previous[field] for field in (
                    'capture_sequence', 'captured_at', 'kind', 'tokens_digest', 'game_week'))
                or before['evidence']['pixel_sha256'] != previous['evidence']['pixel_sha256']
                or first['capture_sequence'] <= before['capture_sequence']
                or (request['key'] != 'esc' if request['intent'] == periodic.BACK else request['target'] is None)):
            raise AutomationError('差分周期领奖动作缺少对应阶段的连续画面。')
        previous = last


def preflight(root):
    """Read-only admission before starting a native runner or visiting a game."""
    root = Path(root).resolve()
    path = root / NAME
    if not path.exists():
        return None
    try:
        data = _checked(root, read(path), sources=True)
        if (data.get('status') not in ('complete', 'partial', 'abort_before_input') or data.get('safe_to_restart') is not True
                or any(action.get('status') != 'verified' for action in data['actions'])
                or any(claim.get('status') != 'verified' for claim in data['claims'])
                or data.get('obligation') is not None):
            raise AutomationError('已有差分领奖提交或到账待核对，原记录保留；未重放或新开领奖。')
        return deepcopy(data)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        raise AutomationError('差分领奖原记录或证据未核实，未重放。') from error


def checked_run(root, directory):
    """Read this original run without treating it as permission to restart."""
    root, directory = Path(root).resolve(strict=True), Path(directory).resolve(strict=True)
    path = directory / 'du-rewards.json'
    if directory.parent != root or path.resolve(strict=True) != path:
        raise AutomationError('差分领奖原账本不在本次运行目录。')
    record = _checked(root, read(path), sources=True)
    if record['journal'] != str(path):
        raise AutomationError('差分领奖原账本与当前子报告来源不同。')
    return record


class RewardStore:
    def __init__(self, directory, data):
        self.directory = Path(directory).resolve(strict=True)
        self.root = self.directory.parent
        preflight(self.root)
        self.path = self.directory / 'du-rewards.json'
        if self.path.exists():
            raise AutomationError('本次已有差分领奖记录，未覆盖。')
        self.data = data
        data.update(journal=str(self.path), run_dir=str(self.directory))

    def persist(self, *, before_replace=None):
        self.data['digest'] = digest({key: value for key, value in self.data.items() if key != 'digest'})
        # Every input requires both writes. A crash after the first write can
        # only leave an unsent intent or block admission, never replay a claim.
        for path in (self.path, self.root / NAME):
            if before_replace is None:
                _write(path, self.data)
            else:
                _write(path, self.data, before_replace=before_replace)

    def require_durable(self):
        if (encoded(read(self.path)) != encoded(self.data) or encoded(read(self.root / NAME)) != encoded(self.data)
                or self.data.get('digest') != digest({key: value for key, value in self.data.items() if key != 'digest'})):
            raise AutomationError('差分领奖意图尚未完整落盘，未发送输入。')
