"""One investment selection, separate confirmation, and typed reward custody."""
from copy import deepcopy
import re

from .currency_wars import observe
from .currency_wars_collector import first_unit_probe, roster_cells
from .currency_wars_investment_policy import (AVOID, POLICY, choose, digest, option_digest, options,
    parse_effect, selected_slot)
from .currency_wars_match import read_match
from .currency_wars_navigation import unique
from .currency_wars_prepare import trusted
from .models import AutomationError, normalize


SELECT = 'select_standard_investment'
CONFIRM = 'confirm_standard_investment'


def _origin(actions, index):
    if type(index) is not int or not 1<=index<len(actions):
        raise AutomationError('投资策略缺少已核实位面来源。')
    parent,previous=actions[index],actions[index-1]
    target=parent.get('target',[])
    if (parent.get('id')!=index or previous.get('id')!=index-1
            or parent.get('action')!='advance_standard_next_plane' or parent.get('status')!='verified'
            or not parent.get('before') or not parent.get('after') or len(target)!=3
            or not isinstance(target[0],str) or not re.fullmatch(r'[1-2]-[1-9][0-9]?',target[0])
            or type(target[1]) is not int or not 0<=target[1]<index-1
            or actions[target[1]].get('action')!='start_standard_node' or actions[target[1]].get('status')!='verified'
            or not actions[target[1]].get('target') or actions[target[1]]['target'][0]!=target[0]
            or previous.get('action')!='continue_standard_node' or previous.get('status')!='verified'
            or not previous.get('before') or not previous.get('after')
            or previous.get('target')!=target[:2] or previous.get('feedback')!=dict(page_kind='plane_map',node=target[2])
            or target[2]!=str(int(target[0][0])+1)+'-1'):
        raise AutomationError('投资策略来源缺少对应胜利、继续与相邻位面链。')
    return target[2]


def enter(session, scene, confidence=.65):
    if observe(scene,confidence).page_kind!='investment_selection':return
    data=session.get('investment',{})
    if data and data.get('status')!='verified':return
    actions=session.get('actions',[])
    index=len(actions)-1
    node=_origin(actions,index)
    if session.get('expected_board')!=node or any(h.get('origin_action_id')==index for h in session.get('investment_history',[])):
        raise AutomationError('投资策略期望节点或本次来源已使用，未重新选择。')
    session['investment']=dict(status='awaiting',origin_action_id=index,expected_node=node)


def _scope(session):
    from .currency_wars_standard_ledger import ledger_status
    c,client=session.get('collection',{}),session.get('client',{})
    if (session.get('status')!='active' or not session.get('start_verified') or not session.get('entry',{}).get('rank_verified')
            or not isinstance(c.get('run_dir'),str) or not c['run_dir'] or type(c.get('input_epoch')) is not int
            or c['input_epoch']<0
            or not session.get('account_key') or session.get('account_verified_run')!=c.get('run_dir')
            or session.get('account_verified_epoch')!=c.get('input_epoch') or client.get('verified_run')!=c.get('run_dir')
            or client.get('input_epoch')!=c.get('input_epoch') or client.get('version')!='4.6'
            or session.get('rules_version')!='4.6' or ledger_status(session.get('actions',[]))!='clear'):
        raise AutomationError('投资策略的同局、账号、版本或来源账本未核实。')


def active_action(scene, session, confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    data=session.get('investment',{})
    kind=observe(scene,confidence).page_kind
    if not data or data.get('status')=='verified':
        if kind=='investment_selection':raise AutomationError('当前投资策略页没有本局已核实位面来源。')
        return None
    if _origin(session.get('actions',[]),data.get('origin_action_id'))!=data.get('expected_node'):
        raise AutomationError('投资策略来源与期望节点不同。')
    if data.get('status')=='reward_verifying':
        return _reward_action(scene,session,confidence)
    if data.get('status')!='awaiting' or kind!='investment_selection':
        raise AutomationError('投资策略选择或交付未核实，未继续其他操作。')
    _scope(session)
    choices=options(scene,confidence)
    existing,_,_=refresh_bonus(session,node=data['expected_node'])
    eligible=tuple(c for c in choices if not existing or c.kind!='refresh_experience')
    option=choose(eligible,session.get('strategy','default'))
    payload=(data['expected_node'],data['origin_action_id'],option.slot,normalize(option.name.text),
             option.kind,normalize(option.effect),option_digest(choices),dict(option.parameters).get('boxes',0))
    selected=selected_slot(scene,choices)
    if selected is None:
        return StandardAction(SELECT,'standard_investment_selected',option.name,
                              details=(option.name.text,option.kind,option.parameters,POLICY),payload=payload)
    previous=(session.get('actions') or [{}])[-1]
    if (selected!=option.slot or previous.get('action')!=SELECT or previous.get('status')!='verified'
            or previous.get('target')!=list(payload)):
        raise AutomationError('选中的投资策略不是本次已落盘选择，未确认或改选。')
    pending=session.get('rederiving_action')
    if pending and pending.get('action')==CONFIRM and pending.get('selection_proof')!=dict(
            source_action_id=previous['id'],input_epoch=session['collection']['input_epoch'],
            run_dir=session['collection']['run_dir'],options=payload[6]):
        raise AutomationError('投资策略确认缺少本次新鲜选中画面的落盘来源。')
    return StandardAction(CONFIRM,'standard_investment_applied',
        unique(trusted(scene,confidence),'确认',(.47,.89,.53,.93)),
        details=(option.name.text,option.kind,option.parameters,POLICY),payload=payload)


def feedback(choice, scene, session, confidence=.65):
    data=session.get('investment',{})
    if data.get('status')!='awaiting' or choice.payload[:2]!=(data.get('expected_node'),data.get('origin_action_id')):
        return False
    if choice.intent==SELECT:
        try:
            choices=options(scene,confidence)
            return option_digest(choices)==choice.payload[6] and selected_slot(scene,choices)==choice.payload[2]
        except AutomationError:return False
    state=read_match(scene,confidence)
    if (not state or state.page!='preparation' or state.node!=choice.payload[0] or state.gold is None
            or state.hp is None or state.hp<=0 or type(state.level) is not int or not 1<=state.level<=10 or not state.deployment
            or state.experience is None and state.level!=10):return False
    try:
        cells=roster_cells(scene,confidence)
        return (all(c.state in ('empty','occupied','reward') for c in cells)
                and sum(c.state=='reward' for c in cells)==choice.payload[7])
    except AutomationError:return False


def bind_selection(session, choice, scene, epoch, run_dir, confidence=.65):
    if choice.intent!=CONFIRM:return
    from .currency_wars_standard_trading import _prior
    if active_action(scene,_prior(session,CONFIRM),confidence)!=choice:
        raise AutomationError('投资策略确认前的当前选中状态已变。')
    session['actions'][-1]['selection_proof']=dict(source_action_id=len(session['actions'])-2,
        input_epoch=epoch,run_dir=str(run_dir),options=choice.payload[6])


def confirmed(session, choice, scene, confidence=.65):
    data=session['investment'];action=session['actions'][-1];state=read_match(scene,confidence)
    _,parameters,_=parse_effect(choice.payload[5])
    slots={str(c.slot):c.signature for c in roster_cells(scene,confidence) if c.state=='reward'}
    action['investment_effect']=dict(node=state.node,origin_action_id=choice.payload[1],slot=choice.payload[2],
        name=choice.payload[3],kind=choice.payload[4],parameters=dict(parameters),options=choice.payload[6],
        board=[state.node,state.gold,state.hp,state.level,list(state.experience) if state.experience else None,list(state.deployment)],
        reward_slots=slots,reward_actions=[])
    action['investment_verified']=False
    data.update(claim_action_id=action['id'],choice=list(choice.payload),reward_slots=slots,completed_slots=[])
    session.pop('collection',None)
    if slots:data['status']='reward_verifying'
    else:_finish(session)


def _finish(session):
    data=session['investment'];data['status']='verified'
    session['actions'][data['claim_action_id']]['investment_verified']=True
    session['actions'][data['origin_action_id']]['investment_verified']=True
    session.setdefault('investment_history',[]).append(deepcopy(data))
    session['action_status']='investment_verified'
    session.pop('expected_board',None)


def _claim(session):
    data=session['investment'];claim=session['actions'][data['claim_action_id']]
    if not valid_effect(claim,session['actions']):raise AutomationError('投资策略待交付记录损坏，未领物或清账。')
    return claim


def _reward_action(scene, session, confidence):
    from .currency_wars_standard_flow import StandardAction
    from .currency_wars_standard_rewards import open_bench_action
    data=session['investment'];claim=_claim(session);kind=observe(scene,confidence).page_kind
    reward=session.get('reward',{})
    if kind in ('equipment_selection','advanced_equipment_selection'):
        expected='advanced_equipment_selection' if claim['investment_effect']['parameters']['box_tier']==2 else 'equipment_selection'
        source=reward.get('origin_action_id')
        parent=session['actions'][source] if type(source) is int and 0<=source<len(session['actions']) else {}
        if kind!=expected or parent.get('investment_parent_action_id')!=claim['id']:
            raise AutomationError('实际武装箱种类或来源与投资策略赠品不同，未选择。')
        return None  # The existing typed reward workflow owns this choice.
    if kind=='character':return None  # Existing fresh-identity collector only.
    state=read_match(scene,confidence)
    if not state or state.page!='preparation' or state.node!=data['expected_node']:
        raise AutomationError('投资策略赠品尚未对应交付，未离开或领取其他物品。')
    probe=first_unit_probe(scene,confidence,session.get('collection',{}).get('units'),session=session) if session.get('strategy')!='default' else None
    if probe is not None:
        cell,target=probe
        return StandardAction('inspect_standard_unit','character',target,payload=(cell.zone,cell.slot,cell.node,cell.signature))
    opening=open_bench_action(scene,session,confidence)
    if opening is None or str(opening.payload[1]) not in data['reward_slots'] or opening.payload[1] in data['completed_slots']:
        raise AutomationError('投资策略指定的未领取武装箱未出现，未重复开启。')
    if opening.payload[2]!=data['reward_slots'][str(opening.payload[1])]:
        raise AutomationError('投资策略武装箱来源格已改变。')
    return opening


def reward_scope(session, intent):
    """Project one validated gift obligation only for its typed reward protocol."""
    data=session.get('investment',{})
    if data.get('status')!='reward_verifying':return dict(session,reward_investment_scope=None)
    if intent not in ('open_standard_bench_reward','choose_standard_reward','close_standard_stale_unit'):
        raise AutomationError('投资策略赠品未核实，当前动作不能借用领取范围。')
    claim=_claim(session)
    from .currency_wars_standard_ledger import ledger_status
    if ledger_status(session['actions'],investment_projection=claim['id'])!='clear':
        raise AutomationError('领取投资赠品前还有其他待核对记录。')
    return dict(session,reward_investment_scope=claim['id'])


def bind_reward(session, choice):
    data=session.get('investment',{})
    if data.get('status')=='reward_verifying' and choice.intent=='open_standard_bench_reward':
        _claim(session)
        if str(choice.payload[1]) not in data['reward_slots'] or choice.payload[1] in data['completed_slots']:
            raise AutomationError('开启位置不是当前投资策略待交付的赠品。')
        session['actions'][-1]['investment_parent_action_id']=data['claim_action_id']


def reward_completed(session):
    data=session.get('investment',{});reward=session.get('reward',{})
    if data.get('status')!='reward_verifying' or reward.get('status')!='verified':return
    source=session['actions'][reward['origin_action_id']]
    if source.get('investment_parent_action_id')!=data['claim_action_id']:return
    slot=source['target'][1]
    if slot in data['completed_slots']:raise AutomationError('同一投资策略赠品已经计入，未重复记账。')
    data['completed_slots'].append(slot)
    claim=session['actions'][data['claim_action_id']]
    claim['investment_effect']['reward_actions'].append(reward['claim_action_id'])
    if len(data['completed_slots'])==len(data['reward_slots']):_finish(session)


def valid_effect(action, actions):
    try:return _valid_effect(action,actions)
    except (AutomationError,AttributeError,IndexError,KeyError,TypeError,ValueError):return False


def _valid_effect(action, actions):
    target,effect=action.get('target',[]),action.get('investment_effect',{})
    if (action.get('action')!=CONFIRM or action.get('status')!='verified' or not action.get('before') or not action.get('after')
            or not isinstance(target,(list,tuple)) or len(target)!=8 or not isinstance(effect,dict)
            or _origin(actions,target[1])!=target[0] or type(target[2]) is not int or not 0<=target[2]<=2
            or not isinstance(target[3],str) or not 0<len(target[3])<=80 or target[3] in AVOID
            or not isinstance(target[5],str) or not 0<len(target[5])<=1000
            or not isinstance(target[6],str) or not re.fullmatch(r'[0-9a-f]{64}',target[6])
            or type(target[7]) is not int or not 0<=target[7]<=3 or type(action.get('id')) is not int
            or not target[1]<action['id']-1<len(actions)):
        return False
    previous=actions[action['id']-1]
    if (previous.get('action')!=SELECT or previous.get('status')!='verified' or previous.get('target')!=list(target)
            or not previous.get('before') or not previous.get('after')):return False
    proof=action.get('selection_proof',{})
    if (not isinstance(proof,dict) or type(proof.get('source_action_id')) is not int or type(proof.get('input_epoch')) is not int
            or proof.get('source_action_id')!=action['id']-1
            or proof.get('input_epoch')!=action.get('input_epoch') or proof.get('options')!=target[6]
            or not isinstance(proof.get('run_dir'),str) or not proof['run_dir']):return False
    kind,params,score=parse_effect(target[5]);params=dict(params)
    if (score is None or kind!=target[4] or params.get('boxes',0)!=target[7]
            or [effect.get(k) for k in ('node','origin_action_id','slot','name','kind','options')]
              !=[target[0],target[1],target[2],target[3],target[4],target[6]] or effect.get('parameters')!=params):return False
    board=effect.get('board')
    if (not isinstance(board,list) or len(board)!=6 or board[0]!=target[0]
            or type(board[1]) is not int or not 0<=board[1]<=99999
            or type(board[2]) is not int or not 0<board[2]<=100 or type(board[3]) is not int or not 1<=board[3]<=10
            or board[4] is None and board[3]!=10
            or board[4] is not None and (not isinstance(board[4],list) or len(board[4])!=2
                or any(type(v) is not int for v in board[4]) or not 0<=board[4][0]<board[4][1]<=9999)
            or not isinstance(board[5],list) or len(board[5])!=2 or any(type(v) is not int for v in board[5])
            or not 0<=board[5][0]<=board[5][1]<=20):return False
    slots=effect.get('reward_slots');rewards=effect.get('reward_actions')
    if (not isinstance(slots,dict) or len(slots)!=target[7] or not isinstance(rewards,list) or len(rewards)>target[7]
            or any(not re.fullmatch('[1-9]',s) or not isinstance(sig,str) or not re.fullmatch('[0-9a-f]{64}',sig) for s,sig in slots.items())):return False
    if action.get('investment_verified') is True and len(rewards)!=target[7]:return False
    seen=set()
    from .currency_wars_standard_rewards import valid_effect as valid_reward
    expected='advanced_equipment_selection' if params.get('box_tier')==2 else 'equipment_selection'
    for index in rewards:
        if type(index) is not int or not action['id']<index<len(actions):return False
        reward=actions[index]
        if not valid_reward(reward,actions) or reward.get('reward_verified') is not True or reward['target'][2]!=expected:return False
        parent=actions[reward['target'][1]];slot=str(parent['target'][1])
        if (parent.get('action')!='open_standard_bench_reward' or parent.get('investment_parent_action_id')!=action['id']
                or slot in seen or slots.get(slot)!=parent['target'][2]):return False
        seen.add(slot)
    return True


def refresh_bonus(session, *, node=None):
    actions=session.get('actions',[]);sources=[];amount=0
    for action in actions:
        if action.get('action')!=CONFIRM or action.get('status')!='verified' or action.get('investment_verified') is not True:continue
        if not valid_effect(action,actions):raise AutomationError('已选投资策略回执损坏，不能推导刷新经验。')
        if action['investment_effect']['kind']=='refresh_experience':
            if node is not None and tuple(map(int,node.split('-')))<tuple(map(int,action['investment_effect']['node'].split('-'))):
                raise AutomationError('当前节点早于赠经验策略取得节点，未将旧局策略用于新开局。')
            amount+=action['investment_effect']['parameters']['experience']
            sources.append([action['id'],action['target']])
    if amount>99:raise AutomationError('叠加刷新经验超过当前可核验范围。')
    if len(sources)>1:raise AutomationError('多项刷新赠经验的叠加方式尚未核实，未推断总收益。')
    return amount,[s[0] for s in sources],digest(sources)


def verified_names(session):
    return tuple(a['investment_effect']['name'] for a in session.get('actions',[]) if a.get('action')==CONFIRM
        and a.get('investment_verified') is True and valid_effect(a,session['actions']))


def valid_refresh_bonus(action, actions):
    try:
        amount,sources,signature=refresh_bonus(dict(actions=actions[:action['id']]),node=action['target'][0])
        if action['target'][4]==0:amount=0
        if not amount:return len(action['target'])==7
        return (len(action['target'])==11 and action['target'][7]==amount and action['target'][10]==signature
                and action['receipt'].get('bonus_sources')==sources)
    except (AutomationError,IndexError,KeyError,TypeError,ValueError):return False
