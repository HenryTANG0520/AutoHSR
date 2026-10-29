"""Bind ordinary character reads to the actual inspection input and epoch."""
from copy import deepcopy
from dataclasses import asdict
import json
import re

from .currency_wars_appearance import appearance,same_appearance
from .currency_wars_collector import owned_profile,roster_cells
from .currency_wars_identity import account_key
from .currency_wars_match import read_match
from .models import AutomationError,Token


STALE_CLOSE='close_standard_stale_unit'
IDENTITY_PRESERVING_ACTIONS=frozenset(('inspect_standard_unit','close_standard_unit','open_standard_equipment_recommendations',
    'open_standard_shop','close_standard_shop','buy_standard_experience','refresh_standard_shop'))


def _same(a,b):
    return json.dumps(a,sort_keys=True,allow_nan=False)==json.dumps(b,sort_keys=True,allow_nan=False)


def _board(scene,confidence):
    state=read_match(scene,confidence)
    if (not state or state.page!='preparation' or not state.node or state.gold is None or state.hp is None
            or state.hp<=0 or type(state.level) is not int or not 1<=state.level<=10 or not state.deployment
            or state.experience is None and state.level!=10 or scene.image is None):
        raise AutomationError('普通角色查看需要完整的当前备战资源与部署人数。')
    return dict(node=state.node,gold=state.gold,hp=state.hp,level=state.level,
        deployment=state.deployment,experience=state.experience,shape=list(scene.image.shape))


def ordinary(session):
    for key in ('equipment','sale','exchange','consumable','movement_popup'):
        data=session.get(key,{})
        if data and data.get('status')!='verified':return False
    return session.get('reward',{}).get('status') not in ('unit_verifying','unit_mismatch')


def _scope(session):
    collection=session.get('collection',{})
    return bool(session.get('status')=='active' and session.get('start_verified')
        and session.get('entry',{}).get('rank_verified') and session.get('account_key')
        and isinstance(collection.get('run_dir'),str) and collection['run_dir']
        and type(collection.get('input_epoch')) is int and collection['input_epoch']>=0
        and session.get('account_verified_run')==collection['run_dir']
        and session.get('account_verified_epoch')==collection['input_epoch'])


def current_source(session):
    """Missing or copied inspection metadata is not a new click source."""
    try:
        if not _scope(session):return False
        inspecting=session.get('inspecting',{});actions=session.get('actions',[])
        index=inspecting.get('inspection_action_id')
        if type(index) is not int or not 0<=index<len(actions):return False
        action=actions[index];zone=inspecting.get('zone');slot=inspecting.get('slot');signature=inspecting.get('signature')
        if (zone not in ('front','back','bench') or type(slot) is not int
                or not isinstance(inspecting.get('node'),str) or not re.fullmatch(r'[1-3]-[1-9][0-9]?',inspecting['node'])
                or not 1<=slot<=dict(front=4,back=6,bench=9)[zone]
                or not isinstance(signature,str) or not re.fullmatch('[0-9a-f]{64}',signature)
                or type(action.get('id')) is not int or action.get('id')!=index or action.get('action')!='inspect_standard_unit'
                or action.get('status')!='verified' or action.get('expected')!='character'
                or not action.get('before') or not action.get('after')
                or action.get('before')!=inspecting.get('before') or action.get('after')!=inspecting.get('after')
                or action.get('target')!=[zone,slot,inspecting.get('node'),signature]
                or action.get('inspection_run_dir')!=inspecting.get('run_dir')
                or inspecting.get('run_dir')!=session['collection']['run_dir']
                or type(inspecting.get('input_epoch')) is not int or type(action.get('input_epoch')) is not int
                or action.get('input_epoch')!=inspecting['input_epoch']
                or inspecting['input_epoch']!=session['collection']['input_epoch']):return False
        children=actions[index+1:]
        if len(children)>1:return False
        for child in children:
            target=child.get('target',[])
            if (child.get('action')!='open_standard_equipment_recommendations' or child.get('status')!='verified'
                    or child.get('input_epoch')!=inspecting['input_epoch'] or not child.get('before') or not child.get('after')
                    or len(target)!=4 or target[:2]!=[zone,slot] or target[3]!=signature):return False
        return True
    except (AttributeError,KeyError,TypeError,ValueError):return False


def stale(session):
    return ordinary(session) and not current_source(session)


def profile(scene, session, confidence=.65):
    if not current_source(session):raise AutomationError('角色面板缺少本次运行、输入代次和查看动作的连续来源。')
    if account_key(scene,max(.85,confidence))!=session['account_key']:
        raise AutomationError('角色采集时账号已改变，未记入本局阵容。')
    result=owned_profile(scene,session['inspecting'],confidence)
    source=session['inspecting']['inspection_action_id']
    children=session['actions'][source+1:]
    if children and children[-1]['target'][2]!=result.name:
        raise AutomationError('推荐页与本次已核实角色名称不同，未更新持有阵容。')
    return result


def close_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    if not stale(session):raise AutomationError('当前不是需淘汰的普通角色采集来源。')
    from .currency_wars_standard_trading import _prior
    from .currency_wars_standard_investment import reward_scope
    from .currency_wars_standard_ledger import ledger_status
    prior=reward_scope(_prior(session,STALE_CLOSE),STALE_CLOSE)
    state=read_match(scene,confidence)
    if (not _scope(prior) or not state or state.page!='character' or not state.node
            or account_key(scene,max(.85,confidence))!=prior['account_key']
            or prior.get('reward_investment_scope') is not None and state.node!=prior['investment']['expected_node']
            or ledger_status(prior.get('actions',[]),investment_projection=prior.get('reward_investment_scope'))!='clear'):
        raise AutomationError('收起旧角色面板前，当前账号、节点或账本仍需核对。')
    return StandardAction(STALE_CLOSE,'standard_stale_unit_board',Token('收起旧角色采集面板',1.,(.49,.49,.51,.51)),payload=(state.node,))


def close_current(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    unit=profile(scene,session,confidence);inspecting=session['inspecting']
    payload=(inspecting['node'],unit.zone,unit.slot,inspecting['signature'],inspecting['inspection_action_id'])
    return StandardAction('close_standard_unit','standard_collected_unit_board',Token('关闭已采集角色面板',1.,(.49,.49,.51,.51)),payload=payload)


def bind_inspection(session, choice, scene, confidence=.65):
    if choice.intent!='inspect_standard_unit':return
    action=session['actions'][-1]
    cell=next(c for c in roster_cells(scene,confidence) if (c.zone,c.slot)==choice.payload[:2])
    if (not _scope(session) or cell.state!='occupied' or (cell.zone,cell.slot,cell.node,cell.signature)!=choice.payload
            or action.get('action')!=choice.intent or action.get('status')!='pending' or action.get('target')!=list(choice.payload)
            or action.get('input_epoch')!=session['collection']['input_epoch']):
        raise AutomationError('普通角色查看意图与当前槽位或输入代次不符。')
    action['collection_appearance']=appearance(scene,cell.roi)
    action['collection_basis']=_board(scene,confidence)


def _close_source(session, choice):
    action=session['actions'][-1]
    if (action.get('action')!='close_standard_unit' or action.get('expected')!=choice.expected
            or action.get('status') not in ('pending','verified') or action.get('target')!=list(choice.payload)
            or type(action.get('input_epoch')) is not int
            or action.get('input_epoch')!=session['collection']['input_epoch']):raise ValueError('关闭来源无效')
    prior=dict(session,actions=session['actions'][:-1])
    if not current_source(prior):raise ValueError('查看来源已失效')
    inspecting=session['inspecting'];index=inspecting['inspection_action_id'];inspection=session['actions'][index]
    if list(choice.payload)!=[inspecting['node'],inspecting['zone'],inspecting['slot'],inspecting['signature'],index]:
        raise ValueError('关闭与查看位置不符')
    record=session['collection']['units'][inspecting['zone']+':'+str(inspecting['slot'])]
    proof=action['collection_read']
    if (not record.get('source') or proof['source']!=record['source'] or not _same(proof['unit'],record['unit'])
            or type(record.get('inspection_action_id')) is not int or record.get('inspection_action_id')!=index
            or record.get('run_dir')!=session['collection']['run_dir']
            or record.get('input_epoch')!=session['collection']['input_epoch']
            or proof['appearance']!=inspection['collection_appearance']):raise ValueError('角色读取来源不符')
    return inspection,record


def board_feedback(choice, scene, confidence=.65, *, session=None):
    state=read_match(scene,confidence)
    if (not state or state.page!='preparation' or state.node!=choice.payload[0] or state.gold is None
            or state.hp is None or state.hp<=0 or type(state.level) is not int or not 1<=state.level<=10
            or not state.deployment or state.experience is None and state.level!=10):return False
    if choice.intent==STALE_CLOSE:return True
    try:
        source=next(c for c in roster_cells(scene,confidence) if (c.zone,c.slot)==choice.payload[1:3])
        if session and 'collection_read' in session['actions'][-1]:
            inspection,_=_close_source(session,choice)
            return (source.state=='occupied' and _same(inspection['collection_basis'],_board(scene,confidence))
                and same_appearance(inspection['collection_appearance'],appearance(scene,source.roi)))
        return source.state=='occupied' and source.signature==choice.payload[3]
    except (AutomationError,StopIteration,AttributeError,KeyError,TypeError,ValueError):return False


def bind_close(session, choice, scene=None, confidence=.65):
    if choice.intent==STALE_CLOSE:
        session['actions'][-1]['discarded_inspection']=deepcopy(session.get('inspecting'))
    elif choice.intent=='close_standard_unit':
        prior=dict(session,actions=session['actions'][:-1])
        if not current_source(prior):raise AutomationError('普通角色关闭前查看来源已失效。')
        inspection=session['actions'][session['inspecting']['inspection_action_id']]
        if 'collection_appearance' not in inspection:return  # Old exact-signature reads remain exact only.
        unit=profile(scene,prior,confidence)
        record=session['collection']['units'][unit.zone+':'+str(unit.slot)]
        if not _same(record.get('unit'),asdict(unit)):raise AutomationError('当前角色与本次已采集身份不符。')
        session['actions'][-1]['collection_read']=dict(unit=asdict(unit),source=record['source'],appearance=inspection['collection_appearance'])


def closed(session, choice, scene=None, confidence=.65):
    if choice.intent==STALE_CLOSE:
        action=session['actions'][-1]
        session.setdefault('collection_resets',[]).append(dict(action_id=action['id'],node=choice.payload[0],
            reason='ordinary_panel_source_expired',inspecting=deepcopy(action.get('discarded_inspection'))))
        session.pop('collection',None)
        session['action_status']='collection_source_reset'
    elif 'collection_read' in session['actions'][-1]:
        action=session['actions'][-1]
        if action.get('status')!='verified' or not action.get('after') or not board_feedback(choice,scene,confidence,session=session):
            raise AutomationError('关闭角色后的槽位、资源或查看来源未核实，未发布身份。')
        _,record=_close_source(session,choice)
        cell=next(c for c in roster_cells(scene,confidence) if (c.zone,c.slot)==choice.payload[1:3])
        action['collection_receipt']=dict(signature=cell.signature,appearance=appearance(scene,cell.roi),
            source=action['after'],basis=_board(scene,confidence))
        record.update(inspection_signature=choice.payload[3],signature=cell.signature,signature_source=action['after'],
            collection_close_action_id=action['id'])
    session.pop('inspecting',None)


def retained(scene, cell, record, session):
    """A similar crop alone cannot carry a cached identity into a fresh frame."""
    try:
        if not _scope(session) or cell.state!='occupied':return False
        if account_key(scene,.85)!=session['account_key']:return False
        collection=session['collection'];actions=session['actions'];index=record['collection_close_action_id']
        if not _same(record,collection['units'].get(cell.zone+':'+str(cell.slot))):return False
        if type(index) is not int or not 0<=index<len(actions):return False
        close=actions[index];target=close['target'];inspection_index=target[4]
        if type(inspection_index) is not int or not 0<=inspection_index<index:return False
        inspection=actions[inspection_index]
        inspecting=dict(zone=cell.zone,slot=cell.slot,node=cell.node,signature=record['inspection_signature'],
            inspection_action_id=inspection_index,run_dir=record['run_dir'],input_epoch=record['input_epoch'],
            before=inspection['before'],after=inspection['after'])
        prior=dict(session,actions=actions[:index+1],inspecting=inspecting)
        from .currency_wars_standard_flow import StandardAction
        _close_source(prior,StandardAction('close_standard_unit','standard_collected_unit_board',None,payload=tuple(target)))
        receipt=close['collection_receipt']
        if (type(close.get('id')) is not int or close.get('id')!=index or close.get('status')!='verified' or not close.get('before') or not close.get('after')
                or record['node']!=cell.node or record['run_dir']!=collection['run_dir']
                or record['input_epoch']!=collection['input_epoch']
                or receipt['source']!=close['after'] or receipt['source']!=record['signature_source']
                or receipt['signature']!=record['signature']
                or not _same(receipt['basis'],inspection['collection_basis'])
                or not same_appearance(inspection['collection_appearance'],receipt['appearance'])):return False
        for offset,child in enumerate(actions[index+1:],index+1):
            from .currency_wars_standard_reorder import preserves
            permitted=child.get('action') in IDENTITY_PRESERVING_ACTIONS or preserves(child,record,cell,actions)
            if (type(child.get('id')) is not int or child.get('id')!=offset
                    or not permitted or child.get('status')!='verified'
                    or type(child.get('input_epoch')) is not int or child.get('input_epoch')!=collection['input_epoch']
                    or not child.get('before') or not child.get('after')):return False
        return same_appearance(receipt['appearance'],appearance(scene,cell.roi))
    except (AutomationError,AttributeError,KeyError,IndexError,TypeError,ValueError):return False
