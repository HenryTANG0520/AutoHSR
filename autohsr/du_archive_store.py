"""Durable custody for one DU archive; uncertain saves are never replayed."""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re

from .models import AutomationError
from .storage import replace_file

NAME = 'du-archive-session.json'
MAX_BYTES = 16 * 1024 * 1024
MAX_HISTORY = 1024
POLICY = 'du-archive-v1'
SEQUENCE = ('du_save_open', 'du_save_slot', 'du_save_create', 'du_save_focus',
            'du_save_name', 'du_save_confirm', 'du_save_close')
STAGES = dict(zip(SEQUENCE, ('management', 'empty', 'rename', 'rename', 'named', 'saved', 'returned')))


def encoded(data):
    return json.dumps(data, ensure_ascii=False, sort_keys=True, allow_nan=False).encode('utf8')


def digest(data):
    return hashlib.sha256(encoded(data)).hexdigest()


def read(path):
    from .currency_wars_state import strict_json
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise AutomationError('差分保存记录超过限额，未继续。')
    return strict_json(raw.decode('utf8'))


def _write(path, data):
    import os
    raw = encoded(data)
    if len(raw) > MAX_BYTES:
        raise AutomationError('差分保存记录超过限额，未提交输入。')
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('wb') as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    replace_file(temporary, path)


def _chain(root, data):
    """Follow only explicitly frozen protocol parents, never discover old runs."""
    records = [data];seen = {data['journal']};current = data
    while True:
        sequence = current.get('sequence')
        if type(sequence) is not int or sequence < 1:
            raise AutomationError('差分保存回执顺序不完整。')
        prior = current.get('prior')
        if prior is None:
            if sequence != 1:raise AutomationError('差分保存前次回执链缺失。')
            return records
        path = Path(prior['path']).resolve(strict=True)
        if (not path.is_relative_to(root) or str(path) in seen or path == root):
            raise AutomationError('差分保存前次回执链不属本地原件。')
        with path.open('rb') as stream:raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES or hashlib.sha256(raw).hexdigest() != prior['sha256']:
            raise AutomationError('差分保存前次回执原件改变。')
        previous = read(path)
        if (previous.get('schema') != 1 or previous.get('policy') != POLICY
                or previous.get('operation') != 'du_archive' or previous.get('journal') != str(path)
                or previous.get('digest') != prior['digest']
                or previous.get('digest') != digest({k:v for k,v in previous.items() if k != 'digest'})
                or previous.get('sequence') != sequence-1
                or previous.get('status') not in ('complete','abort_before_input') or previous.get('safe_to_restart') is not True):
            raise AutomationError('差分保存前次回执尚未完整核实。')
        records.append(previous);seen.add(str(path));current = previous
        if len(records) > MAX_HISTORY:
            raise AutomationError('差分保存来源链超过核对限额，未截断旧记录。')


def _checked(root, data, *, check_history=True):
    from .currency_wars_initial import source_file_ref
    if (type(data) is not dict or type(data.get('schema')) is not int or data['schema'] != 1
            or data.get('operation') != 'du_archive' or data.get('policy') != POLICY
            or data.get('digest') != digest({k:v for k,v in data.items() if k != 'digest'})
            or not re.fullmatch('[0-9a-f]{32}', str(data.get('id', '')))
            or data.get('status') not in ('observing', 'active', 'complete', 'unknown', 'abort_before_input')
            or type(data.get('epoch')) is not int or data['epoch'] < 0
            or type(data.get('window')) is not int or data['window'] <= 0
            or any(type(data.get(key)) is not bool for key in ('save_verified', 'skip_verified', 'return_verified', 'safe_to_restart'))):
        raise AutomationError('差分保存记录结构或摘要未核实。')
    directory = Path(data['run_dir']).resolve(strict=True)
    path = directory / 'du-archives' / (data['id'] + '.json')
    if directory.parent != root or str(path) != data.get('journal') or read(path) != data:
        raise AutomationError('差分保存双份记录或原目录不一致。')
    for key in ('session_id', 'run_id'):
        if type(data.get(key)) is not str or not 1 <= len(data[key]) <= 80:
            raise AutomationError('差分保存缺少本局来源。')
    history = _chain(root,data)
    identities = [(item.get('session_id'),item.get('run_id')) for item in history]
    if len(set(identities)) != len(identities):
        raise AutomationError('差分保存来源链重复使用本局标识。')
    if check_history:
        for previous in history[1:]:
            _checked(root,previous,check_history=False)
    if data.get('start_proof') is not None:
        _check_start(data)
    if data['status'] != 'abort_before_input' and any(item['status']=='complete' for item in history[1:]):
        _check_start(data)
    observations, actions = data.get('observations'), data.get('actions')
    if (type(observations) is not list or len(observations) > 128
            or type(actions) is not list or len(actions) > len(SEQUENCE)):
        raise AutomationError('差分保存来源数量不完整。')
    for index, item in enumerate(observations):
        stamp = item['captured_at']
        if (type(item.get('id')) is not int or item['id'] != index
                or item.get('epoch') != data['epoch'] or item.get('window') != data['window']
                or type(stamp) not in (int,float) or not math.isfinite(stamp) or stamp <= 0
                or item.get('stage') not in ('origin', *STAGES.values()) or type(item.get('facts')) is not dict
                or not re.fullmatch('[0-9a-f]{64}', str(item.get('tokens_digest', '')))
                or source_file_ref(item['evidence']['path'], directory) != item['evidence']):
            raise AutomationError('差分保存原PNG、观察代次或字段来源改变。')
    def pair(indexes, stage, before=0):
        if (type(indexes) is not list or len(indexes) != 2
                or any(type(i) is not int or not 0 <= i < len(observations) for i in indexes)):
            raise AutomationError('差分保存缺少独立双帧来源。')
        first, last = [observations[i] for i in indexes]
        if (any(item['stage'] != stage for item in (first,last))
                or not before < first['captured_at'] < last['captured_at']
                or first['evidence']['path'] == last['evidence']['path'] or first['facts'] != last['facts']):
            raise AutomationError('差分保存双帧反馈不连续或字段冲突。')
        return last['facts']
    aborted = (data['status'] == 'abort_before_input' and not actions and data['safe_to_restart']
               and not data['save_verified'] and not data['skip_verified'] and not data['return_verified'])
    if not aborted:
        if not re.fullmatch('[0-9a-f]{64}', str(data.get('account_key', ''))):
            raise AutomationError('差分保存当前账号来源缺失。')
        origin = pair(data['origin_frames'], 'origin')
        if origin.get('account_key') != data['account_key'] or origin.get('already_saved') is not False:
            raise AutomationError('差分保存不是本次未保存的胜利来源。')
    plan = data.get('plan')
    skipped = data['skip_verified']
    expected = ('du_save_open', 'du_save_close') if skipped else SEQUENCE
    for index, action in enumerate(actions):
        request, before = action['request'], action['before']
        if (type(action.get('id')) is not int or action['id'] != index or request.get('id') != index
                or request.get('intent') != expected[index] or type(before) is not int
                or not 0 <= before < len(observations)
                or action.get('status') not in ('pending','submitted','verified','unknown')
                or sum(request.get(key) is not None for key in ('target','key','name')) != 1):
            raise AutomationError('差分保存动作或原意图链不完整。')
        if index and actions[index-1]['status'] != 'verified':
            raise AutomationError('差分保存越过未核实动作。')
        if action['status'] == 'verified':
            facts = pair(action['after'], STAGES[request['intent']], observations[before]['captured_at'])
            if request['intent'] in ('du_save_name','du_save_confirm') and facts.get('name') != plan['name']:
                raise AutomationError('差分保存确切名称与反馈不符。')
    if plan is not None:
        if (type(plan) is not dict or not re.fullmatch(r'AutoHSR(?: - |-)\d{1,6}', str(plan.get('name','')))
                or not actions or plan.get('before_frames') != actions[0]['after']):
            raise AutomationError('差分保存名称或空槽来源未冻结。')
        management = pair(plan['before_frames'], 'management')
        if management.get('slot') != plan.get('slot') or management.get('next_name') != plan['name']:
            raise AutomationError('差分保存冻结空槽或原编号来源不符。')
    if data['save_verified']:
        confirm = next((a for a in actions if a['request']['intent'] == 'du_save_confirm'), None)
        if (skipped or plan is None or confirm is None or confirm['status'] != 'verified'
                or data.get('saved_frames') != confirm['after']):
            raise AutomationError('差分保存成功缺少本次确认来源。')
        saved = pair(data['saved_frames'], 'saved')
        management = pair(plan['before_frames'], 'management')
        if (saved.get('name') != plan['name'] or not saved_rows_match(management['rows'],saved.get('rows'),plan['slot'],plan['name'])
                or saved.get('list_box') not in [r['box'] for r in saved['rows'] if r['text']==_normal(plan['name'])]):
            raise AutomationError('差分保存成功名称或冻结空槽行不符。')
    if skipped:
        if (data.get('skip_reason') != 'no_verified_empty_slot' or plan is not None
                or data['save_verified'] or not actions or actions[0]['status'] != 'verified'):
            raise AutomationError('差分未核实空槽的放弃保存来源不完整。')
        if pair(actions[0]['after'], 'management').get('slot') is not None:
            raise AutomationError('差分放弃保存原因与已核实空槽冲突。')
    elif data.get('skip_reason') is not None:
        raise AutomationError('差分未跳过保存却带放弃原因。')
    if data['return_verified']:
        if (not actions or actions[-1]['request']['intent'] != 'du_save_close'
                or actions[-1]['status'] != 'verified' or data.get('return_frames') != actions[-1]['after']):
            raise AutomationError('差分保存返回不属于最后关闭动作。')
        pair(data['return_frames'], 'returned')
    if data['status'] == 'complete' and (not data['safe_to_restart'] or not data['return_verified']
            or not (data['save_verified'] ^ skipped) or len(actions) != len(expected)
            or any(action['status'] != 'verified' for action in actions)):
        raise AutomationError('差分保存完整状态缺少保存或返回核实。')
    if data['safe_to_restart'] and not (aborted or data['status'] == 'complete'):
        raise AutomationError('差分保存未知状态不能解除防重发。')
    return data


def _normal(text):
    from .models import normalize
    return normalize(text)


def _same_row(first, second):
    return min(first[3],second[3]) > max(first[1],second[1])


def saved_rows_match(before, after, slot, name):
    """Replace exactly the observed empty row; every other slot is conserved."""
    if type(before) is not list or type(after) is not list or len(before) != len(after):return False
    frozen = [i for i,row in enumerate(before) if row['text']=='暂无存档' and row['box']==slot['box']]
    added = [i for i,row in enumerate(after) if row['text']==_normal(name) and _same_row(row['box'],slot['box'])]
    if len(frozen)!=1 or len(added)!=1:return False
    remaining = [row for i,row in enumerate(after) if i!=added[0]]
    for index,row in enumerate(before):
        if index==frozen[0]:continue
        matches = [i for i,value in enumerate(remaining) if value['text']==row['text'] and _same_row(value['box'],row['box'])]
        if len(matches)!=1:return False
        remaining.pop(matches[0])
    return not remaining


def _check_start(data):
    from .currency_wars_initial import source_file_ref
    proof = data.get('start_proof')
    if type(proof) is not dict:
        raise AutomationError('前次保存已完成；当前没有本程序新开演算来源，未重复保存。')
    reference = proof['ledger'];path = Path(reference['path']).resolve(strict=True)
    directory = Path(data['run_dir']).resolve(strict=True)
    if not path.is_relative_to(directory) or path == directory:
        raise AutomationError('差分保存新开局原件不属本次运行。')
    with path.open('rb') as stream:raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES or len(raw) != reference['size'] or hashlib.sha256(raw).hexdigest() != reference['sha256']:
        raise AutomationError('差分保存新开局台账原件改变。')
    from .currency_wars_state import strict_json
    ledger = strict_json(raw.decode('utf8'));entry = ledger['run_results'][-1]
    frozen = proof['entry']
    if (ledger.get('schema_version') != 1 or ledger.get('session_id') != data['session_id']
            or any(entry.get(key) != value for key,value in frozen.items())
            or frozen.get('run_id') != data['run_id'] or frozen.get('origin') != 'fresh'
            or frozen.get('status') != 'running' or frozen.get('difficulty_verified') is not True
            or type(frozen.get('difficulty_rank')) is not int or not 1 <= frozen['difficulty_rank'] <= 10
            or type(frozen.get('difficulty_evidence')) is not dict
            or frozen['difficulty_evidence'].get('verified') is not True
            or frozen['difficulty_evidence'].get('displayed_rank_after') != frozen['difficulty_rank']
            or frozen['difficulty_evidence'].get('requested_rank') != frozen['difficulty_rank']
            or source_file_ref(frozen['started_evidence'], directory) != proof['image']):
        raise AutomationError('差分保存没有同本局的新开局、难度及原PNG来源。')
    if start_source(ledger,frozen,directory) != proof.get('source'):
        raise AutomationError('差分保存启动动作、页面历史或原PNG关联改变。')


def start_source(ledger, entry, directory):
    """Bind the real sent launch to its observed transition and started entry."""
    from .currency_wars_initial import source_file_ref
    from .models import normalize
    run = entry.get('run')
    started = entry.get('started_page')
    forbidden = ('unknown','blocked','victory','defeat','home','guide','mode_select','difficulty_setup',
                 'star_rank_setup','periodic_setup','team_selection','save_management','save_name','resume_confirm')
    if type(run) is not int or run < 1 or type(started) is not str or not started or started in forbidden:
        raise AutomationError('差分保存没有本局启动后运行页面来源。')
    actions, history = ledger.get('actions'), ledger.get('page_history')
    if type(actions) is not list or type(history) is not list or len(actions)>20000 or len(history)>20000:
        raise AutomationError('差分保存启动动作或页面历史缺失。')
    launches = [(i,item) for i,item in enumerate(actions) if item.get('run')==run
        and item.get('status')=='sent' and item.get('intent') in ('periodic_start','navigation')
        and normalize(item.get('action','')) in ('启动差分宇宙','启动「差分宇宙」')]
    if len(launches)!=1:raise AutomationError('差分保存没有唯一已发送启动动作。')
    position, launch = launches[0]
    # A confirmed low-rank warning is the only extra input the existing start
    # path permits before it records started_page; loading is observation only.
    low = [(i,item) for i,item in enumerate(actions) if i>position and item.get('run')==run
        and item.get('intent')=='du_low_rank_confirm' and item.get('status')=='sent']
    if launch.get('after_page')=='low_rank_warning':
        if len(low)!=1:raise AutomationError('差分保存低难度启动确认来源缺失。')
        last_position, boundary = low[0]
    else:
        last_position, boundary = position, launch
    begin = [i for i,item in enumerate(history) if item.get('run')==run
        and item.get('evidence')==launch.get('after_evidence') and item.get('page_kind')==launch.get('after_page')]
    end = [i for i,item in enumerate(history) if item.get('run')==run
        and item.get('evidence')==entry.get('started_evidence') and item.get('page_kind')==started]
    edge = [i for i,item in enumerate(history) if item.get('run')==run
        and item.get('evidence')==boundary.get('after_evidence') and item.get('page_kind')==boundary.get('after_page')]
    if len(begin)!=1 or len(end)!=1 or len(edge)!=1 or not begin[0]<=edge[0]<=end[0]:
        raise AutomationError('差分保存启动反馈未关联本局页面历史。')
    transition = history[edge[0]:end[0]+1]
    if (any(item.get('run')!=run for item in history[begin[0]:end[0]+1])
            or any(item.get('page_kind')!='unknown' for item in transition[:-1])):
        raise AutomationError('差分保存启动反馈被其他页面打断。')
    sources = []
    for item in history[begin[0]:end[0]+1]:
        if item.get('page_kind') in ('victory','defeat','save_management','save_name'):
            raise AutomationError('差分保存不能以结算或存档页面证明新开局。')
        sources.append(source_file_ref(item['evidence'],directory))
    return dict(action_index=position,last_action_index=last_position,history_start=begin[0],history_end=end[0],images=sources)


def preflight(root):
    root = Path(root).resolve()
    path = root / NAME
    if not path.exists():
        return None
    try:
        data = _checked(root, read(path))
        if data['status'] not in ('complete','abort_before_input') or not data['safe_to_restart']:
            raise AutomationError('已有差分保存意图或返回待核对，未重放或另开保存。')
        return deepcopy(data)
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        raise AutomationError('差分保存原记录或来源未核实，未补写或重放。') from None


class ArchiveStore:
    def __init__(self, directory, data):
        self.directory = Path(directory).resolve(strict=True)
        self.root = self.directory.parent
        previous = preflight(self.root)
        history = _chain(self.root,previous) if previous is not None else []
        if any(item['session_id']==data['session_id'] and item['run_id']==data['run_id'] for item in history):
            raise AutomationError('本局已有差分保存记录，未重复保存。')
        self.data = data
        self.path = self.directory / 'du-archives' / (data['id'] + '.json')
        if self.path.exists():
            raise AutomationError('本次差分保存原件已存在，未覆盖。')
        data.update(run_dir=str(self.directory), journal=str(self.path))
        data['prior'] = None;data['sequence'] = previous['sequence']+1 if previous else 1
        if data.get('start_proof') is not None:
            _check_start(data)
        if previous is not None:
            if any(item['status']=='complete' for item in history):
                _check_start(data)
            previous_path = Path(previous['journal'])
            data['prior'] = dict(path=str(previous_path), sha256=hashlib.sha256(previous_path.read_bytes()).hexdigest(), digest=previous['digest'])

    def persist(self):
        self.data['digest'] = digest({k:v for k,v in self.data.items() if k != 'digest'})
        _write(self.path, self.data)
        _write(self.root / NAME, self.data)

    def require_durable(self):
        if (encoded(read(self.path)) != encoded(self.data) or encoded(read(self.root / NAME)) != encoded(self.data)
                or self.data.get('digest') != digest({k:v for k,v in self.data.items() if k != 'digest'})):
            raise AutomationError('差分保存意图未完整双写，未发送输入。')
        try:
            # Ancestor PNGs were checked by constructor preflight and are
            # checked again on completion. Per-input checks retain their whole
            # immutable metadata chain and recheck every current source PNG.
            _checked(self.root,self.data,check_history=False)
        except (OSError,ValueError,KeyError,TypeError,IndexError,AttributeError):
            raise AutomationError('差分保存原意图、回执链或PNG来源未核实。') from None
