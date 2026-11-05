"""Free view return from this run's accepted initial environment confirmation.

This source is independent of normal shop opening/trading and node arrival.
Closing the view neither attributes an environment gift nor authorizes a trade.
"""
from copy import deepcopy
import hashlib
import json
import math
import time

from .currency_wars_identity import account_key
from .currency_wars_match import read_match
from .currency_wars_navigation import unique
from .currency_wars_prepare import trusted
from .models import AutomationError

INTENT = 'close_standard_initial_shop'
EXPECTED = 'standard_initial_shop_closed'
POLICY = 'initial-free-shop-return-v1'
REOBSERVED_POLICY = 'initial-free-shop-return-v2'
FIELDS = ('node', 'gold', 'level', 'hp', 'experience', 'deployment')
CONTROL = (.81, .88, .89, .95)


def _same(left, right):
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False,
                                    separators=(',', ':')).encode('utf8')).hexdigest()


def _scope(session, origin=None):
    from .currency_wars_initial import validate_origin
    origin = validate_origin(session, require_accepted=True) if origin is None else origin
    from .currency_wars_initial_shop_observation import KEY,HISTORY,validate
    if KEY in session or HISTORY in session:
        origin['_execution']=validate(session)
        return origin
    client = session.get('client', {})
    if (session.get('status') != 'active' or session.get('start_verified') is not True or
            session.get('entry', {}).get('rank_verified') is not True or
            type(origin.get('epoch')) is not int or type(session.get('account_verified_epoch')) is not int or
            type(client.get('input_epoch')) is not int or
            session.get('account_key') != origin['account_key'] or
            session.get('account_verified_run') != origin['run_dir'] or
            session.get('account_verified_epoch') != origin['epoch'] or
            client.get('verified_run') != origin['run_dir'] or client.get('input_epoch') != origin['epoch'] or
            client.get('version') != '4.6' or session.get('rules_version') != '4.6'):
        raise AutomationError('初始免费收店的同局、账号、运行、代次或版本未核实。')
    return origin


def _execution(origin):
    return origin.get('_execution',origin)


def _contract(origin):
    return (2,REOBSERVED_POLICY) if '_execution' in origin else (1,POLICY)


def _capture(scene, *, fresh):
    captured = getattr(scene, 'captured_at', None)
    if (type(captured) not in (int, float) or not math.isfinite(captured) or captured <= 0 or
            fresh and not 0 <= time.monotonic() - captured <= 8):
        raise AutomationError('初始免费收店需要当前新鲜画面；旧画面不重放。')
    image = getattr(scene, 'image', None)
    if (image is None or len(image.shape) != 3 or image.shape[2] not in (3, 4) or
            min(image.shape[:2]) < 100 or image.shape[0] * image.shape[1] > 16000000 or
            str(image.dtype) != 'uint8'):
        raise AutomationError('初始免费收店缺少可核对的当前游戏图像。')


def _hud(scene, page, confidence, *, fresh=True):
    _capture(scene, fresh=fresh)
    state = read_match(scene, confidence)
    if (not state or state.page != page or not state.node or type(state.gold) is not int or
            not 0 <= state.gold <= 99999 or type(state.level) is not int or not 1 <= state.level <= 10):
        raise AutomationError('初始免费收店的当前页面、节点、金币或等级未完整读取。')
    values = dict(node=state.node, gold=state.gold, level=state.level, hp=state.hp,
                  experience=list(state.experience) if state.experience is not None else None,
                  deployment=list(state.deployment) if state.deployment is not None else None)
    return state, values


def _unchanged(left, right):
    return all(left.get(key) is None or right.get(key) is None or _same(left[key], right[key]) for key in FIELDS)


def _page(scene, session, origin, confidence, *, fresh=True):
    state, hud = _hud(scene, 'shop', confidence, fresh=fresh)
    frames = origin['arrival_frames']
    if (hud['node'] != origin['expected_node'] or account_key(scene, max(.85, confidence)) != origin['account_key'] or
            scene.captured_at < frames[-1]['captured_at'] or
            any(frame['page'] not in ('shop', 'preparation') or frame['node'] != hud['node'] or
                not _unchanged(frame['board'], hud) for frame in frames)):
        raise AutomationError('当前商店不是本次环境确认后同账号、节点及已读HUD的直接延续。')
    control = unique(trusted(scene, confidence), '收起', CONTROL)
    # UID pixels/text are outside this page proof. Account continuity is checked
    # separately and retained only in this private local protocol.
    clean = trusted(scene, confidence)
    source = dict(captured_at=scene.captured_at, shape=list(scene.image.shape),
        pixel_sha256=hashlib.sha256(scene.image[:round(scene.image.shape[0] * .94)].tobytes()).hexdigest(),
        token_sha256=_digest([(token.text, token.score, list(token.box)) for token in clean.tokens
                             if token.center[1] < .94]),
        control_box=list(control.box),
        offers=[[offer.slot, offer.name, offer.cost] for offer in state.offers],
        probabilities=list(state.probabilities) if state.probabilities is not None else None)
    payload = (hud['node'], origin['action_id'], origin['origin']['action_digest'], origin['run_dir'],
               origin['epoch'], origin['account_key'], hud, source)
    return control, payload


def _current(scene,session,origin,confidence,*,fresh=True):
    target,payload=_page(scene,session,origin,confidence,fresh=fresh)
    execution=origin.get('_execution')
    if execution is not None:
        from .currency_wars_initial_shop_observation import check_current
        if fresh:check_current(session,scene,origin,execution,payload[6],payload[7],confidence)
        payload=(*payload[:3],execution['run_dir'],execution['epoch'],*payload[5:],execution['digest'])
    return target,payload


def _direct(session, origin):
    actions = session.get('actions', [])
    index = origin['action_id']
    if (len(actions) != index + 1 or not actions or actions[-1].get('id') != index or
            any(action.get('status') != 'verified' for action in actions)):
        raise AutomationError('初始免费收店只允许直接紧邻原环境确认，不能借用交易或节点到达来源。')


def _bound(session, choice, origin, *, statuses=('pending',)):
    actions, data = session.get('actions', []), session.get('initial_shop_return', {})
    index = origin['action_id'] + 1
    schema,policy=_contract(origin);execution=_execution(origin)
    if (not isinstance(data, dict) or type(data.get('schema')) is not int or data.get('schema') != schema or data.get('policy') != policy or
            data.get('status') != 'pending' or data.get('close_action_id') != index or
            type(data.get('close_action_id')) is not int or type(data.get('epoch')) is not int or
            data.get('origin_action_id') != origin['action_id'] or
            data.get('origin_digest') != origin['origin']['action_digest'] or
            data.get('run_dir') != execution['run_dir'] or data.get('epoch') != execution['epoch'] or
            (schema==2 and data.get('observation_digest')!=execution['digest']) or
            (schema==1 and ('observation_digest' in data or len(choice.payload)!=8)) or
            (schema==2 and (len(choice.payload)!=9 or choice.payload[8]!=execution['digest'])) or
            data.get('account_key') != origin['account_key'] or not _same(data.get('payload'), list(choice.payload)) or
            len(actions) != index + 1 or type(actions[-1].get('id')) is not int or actions[-1].get('id') != index or
            actions[-1].get('action') != INTENT or actions[-1].get('expected') != EXPECTED or
            actions[-1].get('status') not in statuses or type(actions[-1].get('input_epoch')) is not int or
            actions[-1].get('input_epoch') != execution['epoch'] or
            not _same(actions[-1].get('target'), list(choice.payload)) or
            actions[-1].get('before') != data.get('before_evidence', {}).get('path') or
            any(action.get('status') != 'verified' for action in actions[:-1])):
        raise AutomationError('初始免费收店的独立意图或原环境确认绑定不完整；未重复输入。')
    return data, actions[-1]


def proposal(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    state = read_match(scene, confidence)
    if not state or state.page != 'shop' or not session.get('initial_environment'):
        return None
    from .currency_wars_initial import validate_origin
    origin = validate_origin(session, require_accepted=True)
    data = session.get('initial_shop_return')
    if origin.get('post_choice_observation') is not None or isinstance(data, dict) and data.get('status') == 'verified':
        return None  # A later, normally opened shop must use the normal contract.
    origin = _scope(session, origin)
    _direct(session, origin)
    target, payload = _current(scene, session, origin, confidence)
    choice = StandardAction(INTENT, EXPECTED, target, payload=payload)
    pending = session.get('rederiving_action')
    if data is not None or pending is not None:
        # Only Context's immediate exact revalidation may project this run's
        # newly persisted pending action. A pending record is never a resume.
        if not isinstance(pending, dict) or pending.get('status') != 'pending':
            raise AutomationError('已有初始免费收店记录待核对，未重新提交。')
        projected = dict(session, actions=[*session['actions'], pending])
        _bound(projected, choice, origin)
    return choice


def bind_intent(session, choice, scene, confidence=.65):
    if choice.intent != INTENT:
        return None
    from .currency_wars_initial import evidence_ref
    origin = _scope(session)
    if 'initial_shop_return' in session:
        raise AutomationError('初始免费收店已有独立记录，未覆盖或重新绑定。')
    target, payload = _current(scene, session, origin, confidence)
    actions = session.get('actions', [])
    index = origin['action_id'] + 1
    execution=_execution(origin);schema,policy=_contract(origin)
    if (choice.expected != EXPECTED or choice.target != target or not _same(choice.payload, payload) or
            len(actions) != index + 1 or type(actions[-1].get('id')) is not int or actions[-1].get('id') != index or
            actions[-1].get('action') != INTENT or actions[-1].get('expected') != EXPECTED or
            actions[-1].get('status') != 'pending' or type(actions[-1].get('input_epoch')) is not int or
            actions[-1].get('input_epoch') != execution['epoch'] or
            not _same(actions[-1].get('target'), list(payload)) or
            any(action.get('status') != 'verified' for action in actions[:-1])):
        raise AutomationError('初始免费收店未先绑定本次原环境确认与落盘意图。')
    before = evidence_ref(scene, actions[-1].get('before'), execution['run_dir'])
    data = dict(schema=schema, policy=policy, status='pending', close_action_id=index,
                origin_action_id=origin['action_id'], origin_digest=origin['origin']['action_digest'],
                run_dir=execution['run_dir'], epoch=execution['epoch'], account_key=origin['account_key'],
                payload=deepcopy(list(payload)), before_evidence=before, receipt=None)
    if schema==2:data['observation_digest']=execution['digest']
    session['initial_shop_return'] = data
    return deepcopy(data)


def feedback(choice, scene, session, confidence=.65, *, before=None):
    if choice.intent != INTENT or choice.expected != EXPECTED or before is None:
        return False
    try:
        from .currency_wars_initial import evidence_ref
        origin = _scope(session)
        data, action = _bound(session, choice, origin, statuses=('pending', 'verified'))
        _, payload = _current(before, session, origin, confidence, fresh=False)
        if not _same(payload, choice.payload):
            return False
        if not _same(evidence_ref(before, action['before'], _execution(origin)['run_dir']), data['before_evidence']):
            return False
        _, after = _hud(scene, 'preparation', confidence)
        return bool(scene.captured_at > before.captured_at and
                    account_key(scene, max(.85, confidence)) == origin['account_key'] and
                    after['node'] == origin['expected_node'] and _unchanged(choice.payload[6], after))
    except (AutomationError, AttributeError, KeyError, TypeError, IndexError, ValueError):
        return False


def closed(session, choice, before, frames, evidence_paths, confidence=.65):
    if choice.intent != INTENT:
        return None
    from .currency_wars_initial import evidence_ref, source_file_ref
    origin = _scope(session)
    data, action = _bound(session, choice, origin, statuses=('verified',))
    if (not isinstance(frames, (list, tuple)) or len(frames) != 2 or
            not isinstance(evidence_paths, (list, tuple)) or len(evidence_paths) != 2 or
            not frames[0].captured_at < frames[1].captured_at or
            any(not feedback(choice, frame, session, confidence, before=before) for frame in frames)):
        raise AutomationError('初始免费返回缺少两份独立的新鲜备战反馈；原意图保持待核对。')
    execution=_execution(origin);schema,policy=_contract(origin)
    refs = [evidence_ref(frame, path, execution['run_dir']) for frame, path in zip(frames, evidence_paths)]
    if refs[0]['path'] == refs[1]['path']:
        raise AutomationError('初始免费返回不能重复使用同一份反馈文件。')
    values = [_hud(frame, 'preparation', confidence)[1] for frame in frames]
    if not _unchanged(values[0], values[1]):
        raise AutomationError('初始免费返回两帧已读HUD冲突，未标记完成。')
    final = source_file_ref(action.get('after'), execution['run_dir'])
    if any(final.get(key) != refs[-1].get(key) for key in ('pixel_sha256', 'shape')):
        raise AutomationError('初始免费返回原动作after并非最后一帧反馈。')
    receipt = dict(schema=schema, policy=policy, origin_action_id=origin['action_id'],
        close_action_id=action['id'], node=origin['expected_node'],
        before=deepcopy(data['before_evidence']), before_hud=deepcopy(choice.payload[6]),
        frames=[dict(evidence=ref, captured_at=frame.captured_at, board=value)
                for ref, frame, value in zip(refs, frames, values)],
        known_fields_unchanged=[key for key in FIELDS if choice.payload[6].get(key) is not None and
                                all(value.get(key) is not None for value in values)],
        free_view_only=True, trade_authorized=False, delivery_attributed=False)
    if schema==2:receipt['observation_digest']=execution['digest']
    data.update(status='verified', receipt=deepcopy(receipt))
    action['initial_shop_return_receipt'] = deepcopy(receipt)
    validate_return(session)
    return receipt


def validate_return(session):
    """Check either return schema independently, including historical PNGs.

    A new execution scope cannot become a legacy return by removing its proof.
    This does not claim the current execution still owns a historical epoch.
    """
    from .currency_wars_initial import validate_origin,source_file_ref
    try:
        origin=validate_origin(session,require_accepted=True);index=origin['action_id']+1
        actions=session.get('actions',[]);data=session.get('initial_shop_return')
        closes=[a for a in actions[index:] if a.get('action')==INTENT]
        if data is None:
            if closes:raise ValueError('missing return source')
            return
        if type(data) is not dict or len(closes)!=1 or len(actions)<=index:raise ValueError('ambiguous return')
        action=actions[index];payload=action.get('target',[]);schema=data.get('schema')
        if type(schema) is not int or schema not in (1,2):raise ValueError('return schema')
        policy=POLICY if schema==1 else REOBSERVED_POLICY
        if (action is not closes[0] or type(action.get('id')) is not int or action['id']!=index
                or data.get('close_action_id')!=index or data.get('origin_action_id')!=origin['action_id']
                or data.get('origin_digest')!=origin['origin']['action_digest'] or data.get('policy')!=policy
                or not isinstance(payload,list) or len(payload)!=(8 if schema==1 else 9)
                or payload[:3]!=[origin['expected_node'],origin['action_id'],origin['origin']['action_digest']]
                or payload[5]!=origin['account_key'] or data.get('account_key')!=origin['account_key']
                or data.get('run_dir')!=payload[3] or data.get('epoch')!=payload[4]
                or type(data.get('epoch')) is not int or type(action.get('input_epoch')) is not int
                or action['input_epoch']!=payload[4] or data.get('payload')!=payload):raise ValueError('return scope')
        from .currency_wars_initial_shop_observation import KEY,HISTORY,validate
        if schema==2:
            proof=validate(session,current=False)
            if ((payload[3],payload[4],payload[8])!=(proof['run_dir'],proof['epoch'],proof['digest'])
                    or data.get('observation_digest')!=proof['digest']):raise ValueError('execution proof')
        elif (KEY in session or HISTORY in session or 'observation_digest' in data
              or (payload[3],payload[4])!=(origin['run_dir'],origin['epoch'])):raise ValueError('legacy downgrade')
        before=source_file_ref(action.get('before'),data['run_dir'])
        if before!=data.get('before_evidence'):raise ValueError('before source')
        if data.get('status')=='pending' and action.get('status')=='pending':
            if data.get('receipt') is not None:raise ValueError('premature return')
            return
        receipt=data.get('receipt')
        if (data.get('status')!='verified' or action.get('status')!='verified' or type(receipt) is not dict
                or type(receipt.get('schema')) is not int or receipt['schema']!=schema or receipt.get('policy')!=policy
                or receipt.get('origin_action_id')!=origin['action_id'] or receipt.get('close_action_id')!=index
                or receipt.get('node')!=origin['expected_node'] or receipt.get('before')!=before
                or receipt.get('before_hud')!=payload[6] or action.get('initial_shop_return_receipt')!=receipt
                or receipt.get('free_view_only') is not True or receipt.get('trade_authorized') is not False
                or receipt.get('delivery_attributed') is not False):raise ValueError('return receipt')
        if (schema==2 and receipt.get('observation_digest')!=payload[8]
                or schema==1 and 'observation_digest' in receipt):raise ValueError('receipt downgrade')
        frames=receipt.get('frames')
        if type(frames) is not list or len(frames)!=2:raise ValueError('return pair')
        previous=payload[7]['captured_at'];paths={before['path']}
        for frame in frames:
            value=frame['board'];stamp=frame['captured_at'];reference=frame['evidence']
            if (type(stamp) not in (int,float) or not math.isfinite(stamp) or not stamp>previous
                    or value.get('node')!=origin['expected_node'] or set(value)!=set(FIELDS)
                    or type(value.get('gold')) is not int or not 0<=value['gold']<=99999
                    or type(value.get('level')) is not int or not 1<=value['level']<=10
                    or not _unchanged(payload[6],value) or reference['path'] in paths
                    or source_file_ref(reference['path'],data['run_dir'])!=reference):raise ValueError('return frame')
            paths.add(reference['path']);previous=stamp
        if not _unchanged(frames[0]['board'],frames[1]['board']):raise ValueError('return semantics')
        known=[key for key in FIELDS if payload[6].get(key) is not None and all(frame['board'].get(key) is not None for frame in frames)]
        last=source_file_ref(action.get('after'),data['run_dir'])
        if (receipt.get('known_fields_unchanged')!=known
                or any(last[key]!=frames[-1]['evidence'][key] for key in ('pixel_sha256','shape'))):raise ValueError('final source')
    except (AutomationError,AttributeError,IndexError,KeyError,TypeError,ValueError,OSError):
        raise AutomationError('初始免费收店原回执或执行来源未核实，未降级、补写或重放。') from None
