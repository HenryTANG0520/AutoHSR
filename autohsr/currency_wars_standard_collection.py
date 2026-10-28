"""Bind ordinary character reads to the actual inspection input and epoch."""
from copy import deepcopy
import re

from .currency_wars_collector import owned_profile,roster_cells
from .currency_wars_identity import account_key
from .currency_wars_match import read_match
from .models import AutomationError,Token


STALE_CLOSE='close_standard_stale_unit'


def ordinary(session):
    for key in ('equipment','sale','exchange'):
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
                or action.get('id')!=index or action.get('action')!='inspect_standard_unit'
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


def board_feedback(choice, scene, confidence=.65):
    state=read_match(scene,confidence)
    if (not state or state.page!='preparation' or state.node!=choice.payload[0] or state.gold is None
            or state.hp is None or state.hp<=0 or type(state.level) is not int or not 1<=state.level<=10
            or not state.deployment or state.experience is None and state.level!=10):return False
    if choice.intent==STALE_CLOSE:return True
    try:
        source=next(c for c in roster_cells(scene,confidence) if (c.zone,c.slot)==choice.payload[1:3])
        return source.state=='occupied' and source.signature==choice.payload[3]
    except (AutomationError,StopIteration):return False


def bind_close(session, choice):
    if choice.intent!=STALE_CLOSE:return
    session['actions'][-1]['discarded_inspection']=deepcopy(session.get('inspecting'))


def closed(session, choice):
    if choice.intent==STALE_CLOSE:
        action=session['actions'][-1]
        session.setdefault('collection_resets',[]).append(dict(action_id=action['id'],node=choice.payload[0],
            reason='ordinary_panel_source_expired',inspecting=deepcopy(action.get('discarded_inspection'))))
        session.pop('collection',None)
        session['action_status']='collection_source_reset'
    session.pop('inspecting',None)
