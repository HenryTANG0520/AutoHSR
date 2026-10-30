"""Initial choice custody and post-choice observations, never invented gifts.

The caller persists these in-memory records before further input. No function
issues input, writes evidence, repairs an old action, or clears a transaction.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time

import numpy as np
from PIL import Image

from .currency_wars import observe
from .currency_wars_collector import collected_snapshot, roster_cells
from .currency_wars_consumables import stock, GEAR, TOOLS
from .currency_wars_environment import ENVIRONMENT_POLICY, parse_environment_effect
from .currency_wars_identity import account_key
from .currency_wars_match import read_match
from .models import AutomationError


KEY = 'initial_environment'
POLICY = 'initial-environment-v1'
_CONFIRM = re.compile(r'confirm_standard_environment_[0-2]')
_READ_ACTIONS = frozenset(('inspect_standard_unit', 'close_standard_unit', 'close_standard_stale_unit',
                         'open_standard_equipment_recommendations', 'close_standard_initial_shop'))


def _fail(message='初始环境来源未核实，原记录保留。'):
    raise AutomationError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _pixels(image):
    return hashlib.sha256(str(tuple(image.shape)).encode('ascii') + image.tobytes()).hexdigest()


def source_file_ref(path, run_dir):
    """A bounded local PNG reference; paths never belong in public model data."""
    try:
        root = Path(run_dir).resolve(strict=True)
        file = Path(path).resolve(strict=True)
        if not root.is_dir() or not file.is_file() or not file.is_relative_to(root):
            _fail()
        with file.open('rb') as stream:
            raw = stream.read(32*1024*1024+1)
        if len(raw) > 32*1024*1024:
            _fail()
        with Image.open(io.BytesIO(raw)) as bitmap:
            if bitmap.format != 'PNG' or bitmap.width*bitmap.height > 16_777_216:
                _fail()
            image = np.asarray(bitmap.convert('RGB'))[:, :, ::-1].copy()
        return dict(path=str(file), sha256=hashlib.sha256(raw).hexdigest(),
                    pixel_sha256=_pixels(image), shape=list(image.shape))
    except (OSError, ValueError, TypeError, Image.DecompressionBombError):
        _fail('初始环境证据文件不可核实，未更换或补造来源。')


def evidence_ref(scene, path, run_dir):
    reference = source_file_ref(path, run_dir)
    image = getattr(scene, 'image', None)
    if (not isinstance(image, np.ndarray) or image.dtype != np.uint8 or image.ndim != 3
            or image.shape[2] != 3 or reference['shape'] != list(image.shape)
            or reference['pixel_sha256'] != _pixels(image)):
        _fail('初始环境证据与当前画面像素不符。')
    return reference


def _verify_file(reference, run_dir):
    if type(reference) is not dict or source_file_ref(reference.get('path'), run_dir) != reference:
        _fail('初始环境原证据哈希已改变。')


def _base_scope(session):
    if (type(session) is not dict or type(session.get('entry')) is not dict or type(session.get('client')) is not dict
            or session.get('status') != 'active' or session.get('start_verified') is not True
            or session.get('mode') != 'standard_development' or session.get('rank') != 8
            or session.get('wealth') != 40 or session.get('entry', {}).get('rank_verified') is not True
            or not re.fullmatch('[0-9a-f]{32}', str(session.get('match_id', '')))
            or not re.fullmatch('[0-9a-f]{64}', str(session.get('account_key', '')))
            or session.get('client', {}).get('version') != '4.6' or session.get('rules_version') != '4.6'):
        _fail('初始环境缺少本局、标准难度、账号或版本来源。')


def _phase(session, run_dir, epoch):
    _base_scope(session)
    if type(epoch) is not int or epoch < 0:
        _fail()
    try:
        root = str(Path(run_dir).resolve(strict=True))
        same = lambda value: str(Path(value).resolve(strict=True)) == root
        client = session['client']
        if (not same(session.get('account_verified_run')) or session.get('account_verified_epoch') != epoch
                or not same(client.get('verified_run')) or client.get('input_epoch') != epoch):
            _fail('初始环境当前运行与输入代次尚未核实。')
        return root
    except (OSError, TypeError, ValueError):
        _fail()


def _declarations(decision):
    if type(decision) is not dict or not isinstance(decision.get('effect'), str):
        _fail()
    kind, parameters, score, _ = parse_environment_effect(decision['effect'])
    if (kind is None or decision.get('kind') != kind or decision.get('parameters') != dict(parameters)
            or decision.get('policy') != ENVIRONMENT_POLICY or type(decision.get('score')) not in (int, float)
            or decision['score'] != score or not isinstance(decision.get('name'), str)
            or not 0 < len(decision['name']) <= 80):
        _fail('初始环境完整声明与已解析效果不一致。')
    return [dict(kind=kind, parameters=dict(parameters), status='unattributed', delivery_verified=False)]


def _original_action(session, record):
    actions = session.get('actions', [])
    index = record.get('action_id')
    if type(index) is not int or not 0 <= index < len(actions):
        _fail()
    action = actions[index]
    original = record.get('origin', {}).get('action')
    if (type(action) is not dict or type(original) is not dict
            or _digest(original) != record['origin'].get('action_digest')
            or type(action.get('id')) is not int or action.get('id') != index or original.get('id') != index
            or type(original.get('id')) is not int or type(original.get('input_epoch')) is not int
            or original.get('status') != 'pending' or action.get('status') not in ('pending', 'verified')
            or not _CONFIRM.fullmatch(str(original.get('action', '')))
            or original.get('expected') != 'initial_board' or original.get('input_epoch') != record.get('epoch')
            or set(action)-set(original)-{'after'}
            or _digest({k: v for k, v in action.items() if k not in ('status', 'after')})
              != _digest({k: v for k, v in original.items() if k not in ('status', 'after')})
            or original.get('target', []) not in ([], [record.get('expected_node')])
            or record['origin'].get('prefix_digest') != _digest(actions[:index])):
        _fail('初始环境原确认动作已改变或尚待核对，未重放或补写。')
    _verify_file(record['origin']['before'], record['run_dir'])
    if record['origin']['before']['path'] != str(Path(original.get('before')).resolve()):
        _fail()
    return action


def _same_board(first, last):
    if type(first) is not dict or type(last) is not dict:
        _fail()
    return all(first.get(key) is None or last.get(key) is None or first[key] == last[key]
               for key in ('gold', 'hp', 'level', 'experience', 'deployment'))


def _validate_observation(session, observation):
    if observation is None:
        return
    if (type(observation) is not dict or observation.get('baseline_scope') != 'post_choice'
            or observation.get('delivery_verified') is not False
            or observation.get('digest') != _digest({k: v for k, v in observation.items() if k != 'digest'})):
        _fail('初始环境首次当前观察已改变，未覆盖原件。')
    _verify_file(observation['evidence'], observation['run_dir'])
    for proof in observation['action_proofs']:
        index = proof['id']
        if (_digest(session['actions'][index]) != proof['digest']
                or session['actions'][index].get('status') != 'verified'):
            _fail('初始环境当前观察的角色查看来源已改变。')
        for reference in proof['files']:
            _verify_file(reference, observation['run_dir'])


def validate_origin(session, *, require_accepted=False):
    """Validate immutable local custody, without restricting a later child tail."""
    try:
        _base_scope(session)
        record = session.get(KEY)
        if (type(record) is not dict or record.get('schema') != 1 or record.get('policy') != POLICY
                or record.get('match_id') != session.get('match_id') or record.get('account_key') != session.get('account_key')
                or record.get('expected_node') != '1-1'
                or type(record.get('epoch')) is not int or record['epoch'] < 0
                or type(record.get('selection_accepted')) is not bool
                or record.get('declared_obligations') != _declarations(record['origin']['action']['decision'])):
            _fail()
        action = _original_action(session, record)
        frames = record.get('arrival_frames')
        if (type(frames) is not list or len(frames) > 2
                or record.get('arrival_digest') != _digest(frames)):
            _fail('初始环境返回证明已改变。')
        for frame in frames:
            if (frame.get('node') != record['expected_node'] or frame.get('page') not in ('shop', 'preparation')
                    or frame.get('account_key') != record['account_key'] or frame.get('run_dir') != record['run_dir']
                    or type(frame.get('epoch')) is not int or frame.get('epoch') != record['epoch']
                    or type(frame.get('captured_at')) not in (float, int)
                    or not math.isfinite(frame['captured_at']) or frame['captured_at'] <= 0):
                _fail()
            _verify_file(frame['evidence'], record['run_dir'])
        if len(frames) == 2:
            if (frames[1]['captured_at'] <= frames[0]['captured_at']
                    or frames[1]['evidence']['path'] == frames[0]['evidence']['path']
                    or not _same_board(frames[0]['board'], frames[1]['board'])):
                _fail('初始环境两帧返回来源不连续。')
        if require_accepted or record['selection_accepted']:
            if not record['selection_accepted'] or len(frames) != 2 or action.get('status') != 'verified':
                _fail('初始环境选择尚未由两帧和原确认动作核实。')
            after = source_file_ref(action.get('after'), record['run_dir'])
            if (after != record.get('accepted_after')
                    or (after['pixel_sha256'], after['shape']) !=
                       (frames[-1]['evidence']['pixel_sha256'], frames[-1]['evidence']['shape'])):
                _fail('初始环境原确认反馈与两帧返回不符。')
        _validate_observation(session, record.get('post_choice_observation'))
        return deepcopy(record)
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, OSError):
        _fail()


def begin(session, action_id, *, run_dir, epoch, expected_node='1-1'):
    root = _phase(session, run_dir, epoch)
    if KEY in session:
        record = validate_origin(session)
        if (record['action_id'], record['run_dir'], record['epoch'], record['expected_node']) != (action_id, root, epoch, expected_node):
            _fail('已有初始环境记录，未覆盖或接纳另一来源。')
        return record
    actions = session.get('actions', [])
    if (type(action_id) is not int or action_id != len(actions)-1 or expected_node != '1-1'
            or action_id < 0 or any(a.get('status') != 'verified' for a in actions[:action_id])):
        _fail()
    action = actions[action_id]
    prefix = [a.get('action') for a in actions[:action_id]
              if not re.fullmatch(r'select_standard_environment_[0-2]', str(a.get('action', '')))]
    if (type(action.get('id')) is not int or action.get('id') != action_id or action.get('status') != 'pending'
            or type(action.get('input_epoch')) is not int or action.get('input_epoch') != epoch
            or action.get('expected') != 'initial_board'
            or not _CONFIRM.fullmatch(str(action.get('action', '')))
            or action.get('target', []) not in ([], [expected_node])
            or prefix != ['start_standard_a8_40', 'advance_standard_preview', 'advance_standard_plane']
            or session.get('expected_board', '1-1') != '1-1'
            or any(_CONFIRM.fullmatch(str(a.get('action', ''))) for a in actions[:action_id])):
        _fail('初始来源只绑定本次待提交确认，不补写历史旧局。')
    obligations = _declarations(action.get('decision'))
    original = json.loads(json.dumps(action, ensure_ascii=False, allow_nan=False))
    record = dict(schema=1, policy=POLICY, match_id=session['match_id'], action_id=action_id,
        expected_node=expected_node, run_dir=root, epoch=epoch, account_key=session['account_key'],
        origin=dict(action=original, action_digest=_digest(original), prefix_digest=_digest(actions[:action_id]),
                    before=source_file_ref(action.get('before'), root)),
        arrival_frames=[], arrival_digest=_digest([]), selection_accepted=False,
        declared_obligations=obligations, post_choice_observation=None, status='pending')
    session[KEY] = record
    return deepcopy(record)


def _current(session, scene, run_dir, epoch, confidence):
    root = _phase(session, run_dir, epoch)
    captured = getattr(scene, 'captured_at', None)
    if (type(captured) not in (int, float) or not math.isfinite(captured)
            or captured <= 0 or not 0 <= time.monotonic()-captured <= 8):
        _fail('初始环境当前画面已过期。')
    if account_key(scene, max(.85, confidence)) != session['account_key']:
        _fail('初始环境账号来源改变，未继续观察或输入。')
    return root


def record_arrival(session, scene, *, evidence, run_dir, epoch, confidence=.65) -> bool:
    record = validate_origin(session)
    root = _current(session, scene, run_dir, epoch, confidence)
    if (root, epoch) != (record['run_dir'], record['epoch']):
        _fail('初始环境返回跨运行或输入代次，未拼接旧帧。')
    if len(session['actions'])-1 != record['action_id']:
        _fail('初始环境返回前已有其他动作。')
    state = read_match(scene, confidence)
    if observe(scene, confidence).page_kind not in ('shop', 'preparation') or not state:
        return False
    if state.node != record['expected_node']:
        _fail('初始环境返回节点不符。')
    if state.gold is None or type(state.level) is not int or not 1 <= state.level <= 10:
        return False
    frame = dict(evidence=evidence_ref(scene, evidence, root), captured_at=scene.captured_at,
        page=state.page, node=state.node, run_dir=root, epoch=epoch, account_key=session['account_key'],
        board=dict(gold=state.gold, hp=state.hp, level=state.level,
                   experience=list(state.experience) if state.experience else None,
                   deployment=list(state.deployment) if state.deployment else None))
    frames = record['arrival_frames']
    if frame in frames:
        return len(frames) == 2
    if len(frames) == 2:
        _fail('初始环境返回证明已冻结，未覆盖原帧。')
    if frames and (frame['captured_at'] <= frames[0]['captured_at']
                   or frame['evidence']['path'] == frames[0]['evidence']['path']
                   or not _same_board(frame['board'], frames[0]['board'])):
        _fail('初始环境两帧返回不一致，未重复确认。')
    frames.append(frame)
    record.update(arrival_frames=frames, arrival_digest=_digest(frames), status='arrived' if len(frames) == 2 else 'pending')
    session[KEY] = record
    return len(frames) == 2


def accepted(session, action_id):
    record = validate_origin(session)
    action = _original_action(session, record)
    if record['action_id'] != action_id or action.get('status') != 'verified' or len(record['arrival_frames']) != 2:
        _fail('初始环境选择尚未由原确认与两帧返回核实。')
    after = source_file_ref(action.get('after'), record['run_dir'])
    last = record['arrival_frames'][-1]['evidence']
    if (after['pixel_sha256'], after['shape']) != (last['pixel_sha256'], last['shape']):
        _fail('初始环境确认反馈不是本次返回画面。')
    if record['selection_accepted']:
        return record
    record.update(selection_accepted=True, accepted_after=after, status='selection_accepted')
    session[KEY] = record
    return deepcopy(record)


def capture_current(session, scene, *, evidence, run_dir, epoch, confidence=.65):
    if KEY not in session:
        return None  # Legacy matches gain no reconstructed initial provenance.
    record = validate_origin(session, require_accepted=True)
    if record['post_choice_observation'] is not None:
        return deepcopy(record['post_choice_observation'])
    root = _current(session, scene, run_dir, epoch, confidence)
    state = read_match(scene, confidence)
    if not state or state.page != 'preparation' or state.node != record['expected_node']:
        return None
    actions = session['actions']
    if any(a.get('status') != 'verified' or a.get('action') not in _READ_ACTIONS
           for a in actions[record['action_id']+1:]):
        _fail('首次当前观察前已有非查看动作，未将后续结果回填为初始基线。')
    cells = roster_cells(scene, confidence)
    if len(cells) != 19:
        _fail()
    snapshot = collected_snapshot(scene, session, epoch, 'initial_post_choice', confidence, allow_reward_items=True)
    if not snapshot.roster_complete:
        return None
    proofs = []
    collection = session.get('collection', {})
    if collection.get('run_dir') != root or collection.get('input_epoch') != epoch:
        _fail()
    for cell in cells:
        if cell.state != 'occupied':
            continue
        unit = collection['units'][cell.zone+':'+str(cell.slot)]
        close_id = unit.get('collection_close_action_id')
        inspect_id = unit.get('inspection_action_id')
        if (type(close_id) is not int or type(inspect_id) is not int
                or not record['action_id'] < inspect_id < close_id < len(actions)):
            _fail('首次当前角色缺少确认后的独立查看与关闭来源。')
        for index in (inspect_id, close_id):
            action = actions[index]
            if action.get('input_epoch') != epoch:
                _fail()
            files = [source_file_ref(action.get(name), root) for name in ('before', 'after')]
            if index == close_id:
                files.append(source_file_ref(unit.get('source'), root))
            proofs.append(dict(id=index, digest=_digest(action), files=files))
    observed_stock = stock(scene, confidence)
    if len(observed_stock) != 14 or [c.slot for c in observed_stock] != list(range(14)):
        _fail('首次当前库存十四格来源不完整。')
    inventory_cells = [asdict(c) for c in observed_stock]
    complete = all((c.name is None and c.quantity is None and not c.textured)
        or (c.name in GEAR and type(c.quantity) is int and c.quantity == 1)
        or (c.name in TOOLS and (type(c.quantity) is int and 0 <= c.quantity <= 99999 or c.quantity == 'infinite'))
        for c in observed_stock)
    observation = dict(baseline_scope='post_choice', selection_action_id=record['action_id'],
        run_dir=root, epoch=epoch, captured_at=scene.captured_at, node=state.node,
        evidence=evidence_ref(scene, evidence, root), roster_complete=True,
        snapshot=json.loads(json.dumps(asdict(snapshot), ensure_ascii=False, allow_nan=False)),
        cells=[asdict(c) for c in cells], inventory_cells=inventory_cells, inventory_complete=complete,
        action_proofs=proofs, delivery_verified=False, status='observed' if complete else 'partial')
    observation = json.loads(json.dumps(observation, ensure_ascii=False, allow_nan=False))
    observation['digest'] = _digest(observation)
    record.update(post_choice_observation=observation, status=observation['status'])
    session[KEY] = record
    return deepcopy(observation)
