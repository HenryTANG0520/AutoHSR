"""A movement popup acknowledges input; returned identities prove movement.

March7th reference: check_festival_star_popup. Pinned source/license are in
assets/upstream/March7thAssistant/source.json. Other popup kinds stay unknown.
"""
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import re

import cv2
import numpy as np

from .currency_wars import observe
from .currency_wars_appearance import appearance,_decoded,same_appearance
from .currency_wars_collector import owned_profile,roster_cells
from .currency_wars_deployment import _crop
from .currency_wars_equipment_catalog import inventory,inventory_counts
from .currency_wars_match import read_match
from .currency_wars_prepare import trusted
from .currency_wars_state import StrategySnapshot
from .models import AutomationError,Token,normalize

MOVES=frozenset(('deploy_standard_owned','stage_standard_exchange'))
SELECT='select_standard_movement_star'
CONFIRM='confirm_standard_movement_star'
INSPECT='inspect_standard_popup_unit'
CLOSE='close_standard_popup_unit'
STALE='close_standard_popup_stale_panel'
ACTIONS=frozenset((SELECT,CONFIRM,INSPECT,CLOSE,STALE))
CENTERS=(.422,.545,.669)
STAR_TRIGGERS=frozenset(('加拉赫','大丽花','花火','星期日','知更鸟','黑天鹅'))


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def candidates(scene,confidence=.65):
    clean=trusted(scene,confidence)
    if observe(clean,confidence).page_kind!='star_selection' or scene.image is None:
        raise AutomationError('移动后的盛会之星页面未核实。')
    if any(re.search('消耗|花费|支付|购买|星琼',normalize(t.text)) and t.within((.33,.04,.9,.6)) for t in clean.tokens):
        raise AutomationError('强化候选出现未知费用，未按免费选择。')
    details=sorted((t for t in clean.tokens if t.within((.17,.345,.94,.40)) and re.fullmatch(r'q?详情',normalize(t.text))),key=lambda t:t.center[0])
    names=sorted((t for t in clean.tokens if t.within((.17,.30,.94,.35))
                  and re.fullmatch(r'盛会之星[一—-]([\u4e00-\u9fff]{1,12})女士',normalize(t.text))),key=lambda t:t.center[0])
    if (not 1<=len(details)<=6 or len(names)!=len(details)
            or any(abs(a.center[0]-b.center[0])>.025 for a,b in zip(names,details))
            or any(not .10<=b.center[0]-a.center[0]<=.15 for a,b in zip(details,details[1:]))):
        raise AutomationError('强化名字与独立详情控件未完整逐列对应。')
    result=[(slot,re.fullmatch(r'盛会之星[一—-]([\u4e00-\u9fff]{1,12})女士',normalize(t.text))[1],t) for slot,t in enumerate(names)]
    if len({r[1] for r in result})!=len(result):raise AutomationError('盛会之星候选重复。')
    return tuple(result)


def table(scene,confidence=.65):
    return [[slot,name,normalize(token.text)] for slot,name,token in candidates(scene,confidence)]


def selected(scene,confidence=.65):
    rows=candidates(scene,confidence);clean=trusted(scene,confidence)
    markers=[t for t in clean.tokens if normalize(t.text)=='已选择' and t.within((.17,.14,.94,.20))]
    controls=[t for t in clean.tokens if normalize(t.text)=='确认选择' and t.within((.68,.49,.87,.56))]
    if len(controls)!=1:raise AutomationError('强化确认控件未唯一核实。')
    box=controls[0].box;button=_crop(scene.image,(box[0]-.01,box[1]-.01,box[2]+.01,box[3]+.01))
    enabled=bool(button.size and np.mean(np.min(button,axis=2)>180)>=.6)
    gold=[];frames=[]
    for slot,_,title in rows:
        x=title.center[0];scores=[]
        for dx in np.linspace(-.065,-.052,14):
            patch=_crop(scene.image,(x+dx,.16,x+dx+.002,.33))
            scores.append(float(np.mean(np.min(patch,axis=2)>200)) if patch.size else 0.)
        panel=_crop(scene.image,(x+.043,.18,x+.053,.285))
        hsv=cv2.cvtColor(panel,cv2.COLOR_BGR2HSV)
        highlighted=np.mean((hsv[:,:,0]>=10)&(hsv[:,:,0]<=45)&(hsv[:,:,1]>=30)&(hsv[:,:,2]>=180))>=.55
        if highlighted:gold.append(slot)
        if highlighted and max(scores,default=0.)>=.15:frames.append(slot)
    if not markers and not gold and not enabled:return None
    if len(frames)!=1 or gold!=frames or not enabled or len(markers)>1:
        raise AutomationError('强化边框、整卡金色和确认可用态不一致。')
    slot=frames[0]
    if markers:
        expected=min(rows,key=lambda r:abs(markers[0].center[0]-r[2].center[0]))
        if expected[0]!=slot or abs(markers[0].center[0]-expected[2].center[0])>.06:
            raise AutomationError('强化文字与当前金色卡片不一致。')
    return slot


def _expected(action):
    basis=action['popup_basis'];raw=basis['snapshot']
    snapshot=StrategySnapshot.from_dict(json.loads(json.dumps(raw)))
    if (not snapshot.roster_complete or not snapshot.known('roster','roster_complete','node','gold','hp','level','capacity','mode','rank','wealth','game_version','rules_version')
            or (snapshot.mode,snapshot.rank,snapshot.wealth,snapshot.game_version,snapshot.rules_version)!=('standard',8,40,'4.6','4.6')
            or [getattr(snapshot,k) for k in ('node','gold','hp','level')]!=[basis[k] for k in ('node','gold','hp','level')]
            or snapshot.input_epoch!=basis['input_epoch'] or type(action.get('input_epoch')) is not int
            or action['input_epoch']!=basis['input_epoch']):
        raise AutomationError('弹窗缺少移动前完整持有阵容。')
    if action.get('expected')!=dict(deploy_standard_owned='standard_owned_deployed',stage_standard_exchange='standard_exchange_inspectable').get(action.get('action')):
        raise AutomationError('移动输入的原期望转换不符。')
    expected={u['zone']+':'+str(u['slot']):dict(u) for u in raw['roster']}
    cells=basis['cells'];target=action['target']
    if action['action']=='deploy_standard_owned':
        if len(target)!=8:raise ValueError('部署目标无效')
        start='bench:'+str(target[4]);end=target[5]+':'+str(target[6])
        if target[:4]!=[basis[k] for k in ('node','gold','hp','level')] or cells[start]!=['occupied',target[7]] or cells[end][0]!='empty':
            raise ValueError('部署来源无效')
        unit=expected.pop(start);unit.update(zone=target[5],slot=target[6]);expected[end]=unit
        deployment=[basis['deployment'][0]+1,basis['deployment'][1]]
    elif action['action']=='stage_standard_exchange':
        if len(target)!=14:raise ValueError('换人目标无效')
        start=target[4]+':'+str(target[5]);end=target[6]+':'+str(target[7])
        if (target[:4]!=[basis[k] for k in ('node','gold','hp','level')] or cells[start]!=['occupied',target[8]]
                or cells[end]!=['occupied',target[9]] or expected[start]['name']!=target[10] or expected[start]['star']!=target[11]
                or expected[end]['name']!=target[12] or expected[end]['star']!=target[13]):raise ValueError('换人来源无效')
        a,b=expected[start],expected[end]
        expected[start]=dict(b,zone=target[4],slot=target[5]);expected[end]=dict(a,zone=target[6],slot=target[7])
        deployment=basis['deployment']
    else:raise ValueError('不是已授权移动')
    if (set(cells)!={f'{z}:{i}' for z,n in (('front',4),('back',6),('bench',9)) for i in range(1,n+1)}
            or not set(expected)<=set(cells) or any(u['star'] is None or u['tier'] is None for u in expected.values())
            or any(u['zone']!='bench' and u['zone'] not in (u['eligible_zones'] or ()) for u in expected.values())):
        raise ValueError('完整移动阵容无效')
    return expected,{start,end},deployment


def bind_move(session,choice,scene,confidence=.65):
    if choice.intent not in MOVES:return
    positions=(('bench',choice.payload[4]),) if choice.intent=='deploy_standard_owned' else ((choice.payload[4],choice.payload[5]),(choice.payload[6],choice.payload[7]))
    units=[session.get('collection',{}).get('units',{}).get(z+':'+str(i),{}).get('unit',{}) for z,i in positions]
    if not any(u.get('name') in STAR_TRIGGERS or '盛会之星' in (u.get('traits') or ()) for u in units):return
    from .currency_wars_standard_rewards import basis
    action=session['actions'][-1]
    action['popup_basis']=basis(scene,session,choice.intent,confidence)
    action['popup_appearances']={c.zone+':'+str(c.slot):(appearance(scene,c.roi) if c.state=='occupied' else None) for c in roster_cells(scene,confidence)}
    _expected(action)


def arrival(choice,scene,session,confidence=.65):
    if choice.intent not in MOVES or observe(scene,confidence).page_kind!='star_selection':return None
    action=session['actions'][-1]
    if 'popup_basis' not in action:raise AutomationError('本次移动没有已核实的盛会之星来源。')
    _,changed,_=_expected(action);basis=action['popup_basis']
    triggers=[u for u in basis['snapshot']['roster'] if u['zone']+':'+str(u['slot']) in changed
              and (u['name'] in STAR_TRIGGERS or '盛会之星' in (u.get('traits') or ()))]
    if not triggers:raise AutomationError('本次移动角色没有盛会之星来源，未处理孤立弹窗。')
    from .currency_wars_rewards import _node,_gold
    if _node(scene,confidence)!=basis['node'] or _gold(scene,confidence)!=basis['gold']:
        raise AutomationError('强化弹窗的节点或金币不符。')
    try:
        rows=table(scene,confidence)
        if sum(r[1]=='花火' for r in rows)!=1:return None
        if not {r[1] for r in rows}<={u['name'] for u in basis['snapshot']['roster']}:return None
        selected(scene,confidence)
    except AutomationError:return None  # Bounded observation may outlast card animation/OCR occlusion.
    return digest(rows)


def opened(session,choice,scene,confidence=.65):
    action=session['actions'][-1];signature=arrival(choice,scene,session,confidence)
    if not signature:raise AutomationError('没有本次移动后的已核实弹窗。')
    rows=table(scene,confidence)
    action.update(movement_popup=dict(kind='star_selection',options=rows,basis=digest(action['popup_basis'])),
                  popup_verified=False,movement_verified=False)
    session['movement_popup']=dict(status='awaiting',parent_action_id=action['id'],options=signature,proofs={})
    session['action_status']='movement_popup_pending'


def _parent(session):
    data=session.get('movement_popup',{})
    if not data or data.get('status')=='verified':return None
    index=data.get('parent_action_id');actions=session.get('actions',[])
    if (type(index) is not int or not 0<=index<len(actions) or not valid_parent(actions[index],actions)
            or data.get('options')!=digest(actions[index]['movement_popup']['options'])):
        raise AutomationError('移动弹窗缺少本局已落盘来源。')
    return actions[index]


def _scope(session):
    from .currency_wars_standard_ledger import ledger_status
    parent=_parent(session);c=session.get('collection',{});client=session.get('client',{})
    if (parent is None or session.get('status')!='active' or not session.get('start_verified') or not session.get('entry',{}).get('rank_verified')
            or not session.get('account_key') or session.get('account_verified_run')!=c.get('run_dir')
            or type(c.get('input_epoch')) is not int or session.get('account_verified_epoch')!=c['input_epoch']
            or client.get('verified_run')!=c.get('run_dir') or client.get('input_epoch')!=c['input_epoch']
            or client.get('version')!='4.6' or session.get('rules_version')!='4.6'
            or ledger_status(session['actions'],popup_projection=parent['id'])!='clear'):
        raise AutomationError('移动弹窗的账号、版本、输入代次或独立账本未核实。')
    return parent


def _board(scene,parent,confidence):
    state=read_match(scene,confidence);basis=parent['popup_basis'];expected,changed,deployment=_expected(parent)
    if (not state or state.page!='preparation' or [state.node,state.gold,state.hp,state.level]!=[basis[k] for k in ('node','gold','hp','level')]
            or (list(state.experience) if state.experience else None)!=basis['experience'] or list(state.deployment or ())!=deployment
            or dict(inventory_counts(inventory(scene,confidence)))!=basis['inventory']):
        raise AutomationError('强化返回的资源、人数或仓库与移动来源不同。')
    cells={c.zone+':'+str(c.slot):c for c in roster_cells(scene,confidence)}
    if (set(k for k,c in cells.items() if c.state=='occupied')!=set(expected)
            or any(c.state!=basis['cells'][k][0] or c.state=='occupied' and not same_appearance(parent['popup_appearances'][k],appearance(scene,c.roi))
                   for k,c in cells.items() if k not in changed)):
        raise AutomationError('强化返回的十九格或移动目标不符。')
    return cells


def _fresh(session,proof):
    return (type(proof.get('input_epoch')) is int and proof['input_epoch']==session.get('account_verified_epoch')
            and proof.get('run_dir')==session.get('account_verified_run'))


def panel_stale(session):
    return bool(_parent(session) and not _fresh(session,session.get('inspecting',{})))


def require_panel_account(scene,session,confidence=.65):
    if _parent(session) is None:return
    from .currency_wars_identity import account_key
    if account_key(scene,max(.85,confidence))!=session.get('account_key'):
        raise AutomationError('强化角色采集时账号已改变，未记入本局证明。')


def active_action(scene,session,confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    parent=_parent(session)
    if parent is None:return None
    parent=_scope(session);data=session['movement_popup'];kind=observe(scene,confidence).page_kind
    index=parent['id'];basis=parent['popup_basis'];stamp=data['options']
    if data['status']=='awaiting':
        if kind!='star_selection' or table(scene,confidence)!=parent['movement_popup']['options']:
            raise AutomationError('移动弹窗候选或种类改变，未确认。')
        from .currency_wars_rewards import _node,_gold
        if (_node(scene,confidence),_gold(scene,confidence))!=(basis['node'],basis['gold']):raise AutomationError('强化节点或余额变化。')
        rows=candidates(scene,confidence);slot,name,target=next(r for r in rows if r[1]=='花火')
        payload=(basis['node'],index,stamp,slot,name)
        if selected(scene,confidence)!=slot:
            if any(a.get('action')==SELECT and a.get('popup_parent_action_id')==index for a in session['actions'][index+1:]):
                raise AutomationError('已核实的强化选择状态已变，未重新选择或覆盖。')
            return StandardAction(SELECT,'standard_movement_star_selected',target,payload=payload)
        controls=[t for t in trusted(scene,confidence).tokens if normalize(t.text)=='确认选择' and t.within((.68,.49,.87,.56))]
        if len(controls)!=1:raise AutomationError('强化确认控件未唯一核实。')
        pending=session.get('rederiving_action')
        if pending and pending.get('action')==CONFIRM and pending.get('popup_selection_proof')!=dict(
                options=stamp,input_epoch=session['account_verified_epoch'],run_dir=session['account_verified_run'],slot=slot):
            raise AutomationError('强化确认没有当前选中画面的落盘证明。')
        return StandardAction(CONFIRM,'standard_movement_star_returned',controls[0],payload=payload)
    if data['status']!='verifying':raise AutomationError('移动弹窗尚未完成核验。')
    if kind=='character':
        inspect=session.get('inspecting',{})
        if panel_stale(session):return StandardAction(STALE,'standard_popup_unit_board',Token('收起旧强化角色面板',1.,(.49,.49,.51,.51)),payload=(basis['node'],index))
        profile=owned_profile(scene,inspect,confidence);key=profile.zone+':'+str(profile.slot)
        proof=data['proofs'].get(key,{})
        if not _fresh(session,proof) or proof.get('unit')!=json.loads(json.dumps(asdict(profile))):raise AutomationError('强化后的当前身份尚未核实。')
        return StandardAction(CLOSE,'standard_popup_unit_board',Token('关闭强化身份核验面板',1.,(.49,.49,.51,.51)),
            payload=(basis['node'],index,key,inspect['signature'],inspect['inspection_action_id']))
    cells=_board(scene,parent,confidence)
    for key,cell in sorted(cells.items(),key=lambda pair:(pair[1].zone!='bench',pair[1].zone,pair[1].slot)):
        if cell.state!='occupied':continue
        proof=data['proofs'].get(key,{})
        if proof.get('closed') and _fresh(session,proof) and same_appearance(proof['appearance'],appearance(scene,cell.roi)):continue
        x,y=cell.point
        return StandardAction(INSPECT,'character',Token('核实强化后角色身份',1.,(x-.01,y-.01,x+.01,y+.01)),
            payload=(cell.zone,cell.slot,cell.node,cell.signature,index))
    raise AutomationError('强化角色来源已齐但完成记录尚未落盘。')


def bind_intent(session,choice,scene,confidence=.65):
    if choice.intent not in ACTIONS:return
    action=session['actions'][-1]
    action['popup_parent_action_id']=session['movement_popup']['parent_action_id']
    parent=_parent(session)
    if parent is None:raise AutomationError('强化输入没有原移动。')
    if choice.intent==CONFIRM:
        action['popup_selection_proof']=dict(options=session['movement_popup']['options'],input_epoch=session['account_verified_epoch'],
            run_dir=session['account_verified_run'],slot=choice.payload[3])
    if choice.intent==INSPECT:
        session['movement_popup']['proofs'].pop(choice.payload[0]+':'+str(choice.payload[1]),None)
        cell=next(c for c in roster_cells(scene,confidence) if (c.zone,c.slot)==choice.payload[:2])
        action['popup_appearance']=appearance(scene,cell.roi)


def feedback(choice,scene,session,confidence=.65):
    try:
        parent=_parent(session)
        if parent is None:return False
        if choice.intent==SELECT:return (table(scene,confidence)==parent['movement_popup']['options'] and selected(scene,confidence)==choice.payload[3])
        cells=_board(scene,parent,confidence)
        if choice.intent==CLOSE:
            proof=session['movement_popup']['proofs'][choice.payload[2]]
            return same_appearance(proof['appearance'],appearance(scene,cells[choice.payload[2]].roi))
        return choice.intent in (CONFIRM,STALE)
    except (AutomationError,KeyError,ValueError):return False


def profile(session,unit,inspecting,source,epoch,scene,confidence=.65):
    parent=_parent(session)
    if parent is None or panel_stale(session):return None
    require_panel_account(scene,session,confidence)
    key=unit.zone+':'+str(unit.slot);expected,_,_=_expected(parent);actual=json.loads(json.dumps(asdict(unit)))
    action=session['actions'][inspecting['inspection_action_id']]
    if (action.get('action')!=INSPECT or action.get('status')!='verified' or action.get('popup_parent_action_id')!=parent['id']
            or action.get('target')!=[unit.zone,unit.slot,inspecting['node'],inspecting['signature'],parent['id']]
            or action.get('inspection_run_dir')!=inspecting.get('run_dir') or action.get('input_epoch')!=epoch
            or key not in expected or any(actual[k]!=v for k,v in expected[key].items() if v is not None)):
        session['movement_popup'].update(status='identity_mismatch',failed_slot=key,actual=actual,
            expected_unit=expected.get(key),source=str(source))
        return '强化后的角色名称、星级、费用、装备或位置与原移动不符。'
    session['movement_popup']['proofs'][key]=dict(unit=actual,signature=inspecting['signature'],input_epoch=epoch,
        run_dir=session['account_verified_run'],source=str(source),inspection_action_id=action['id'],closed=False,
        appearance=action['popup_appearance'])
    return None


def returned(session,choice,scene,confidence=.65):
    if choice.intent not in (CONFIRM,CLOSE,STALE):return
    data=session['movement_popup'];parent=_parent(session);cells=_board(scene,parent,confidence)
    if choice.intent==CONFIRM:
        data.update(status='verifying',confirm_action_id=session['actions'][-1]['id'],proofs={})
        session['collection'].update(units={},complete=False)
        session['action_status']='movement_popup_identity_pending'
        session.pop('inspecting',None);return
    if choice.intent==CLOSE:
        data['proofs'][choice.payload[2]].update(closed=True,close_action_id=session['actions'][-1]['id'])
    session.pop('inspecting',None)
    expected,_,_=_expected(parent)
    if all(data['proofs'].get(k,{}).get('closed') and _fresh(session,data['proofs'][k]) and same_appearance(data['proofs'][k]['appearance'],appearance(scene,cells[k].roi)) for k in expected):
        parent.update(popup_verified=True,movement_verified=True,popup_receipt=dict(deepcopy(data),status='verified'))
        parent['popup_receipt'].update(final_action_id=session['actions'][-1]['id'],board_source=session['actions'][-1]['after'],
            cells={k:[c.state,c.signature] for k,c in cells.items()},verified_run=session['account_verified_run'],
            input_epoch=session['account_verified_epoch'],appearances={k:appearance(scene,cells[k].roi) for k in expected})
        for key in expected:
            record=session['collection']['units'][key]
            record.update(inspection_signature=data['proofs'][key]['signature'],signature=cells[key].signature,
                signature_source=session['actions'][-1]['after'],popup_parent_action_id=parent['id'])
        data['status']='verified';session['collection']['complete']=True
        session['action_status']='movement_popup_verified'


def valid_child(action,actions):
    try:
        index=action['popup_parent_action_id'];parent=actions[index];target=action['target'];name=action['action']
        expected={SELECT:'standard_movement_star_selected',CONFIRM:'standard_movement_star_returned',INSPECT:'character',
                  CLOSE:'standard_popup_unit_board',STALE:'standard_popup_unit_board'}
        if (type(index) is not int or not 0<=index<action['id'] or parent['action'] not in MOVES
                or actions[action['id']]!=action or type(action.get('input_epoch')) is not int or action['input_epoch']<0
                or action.get('expected')!=expected.get(name)
                or parent['status']!='verified' or action.get('status')!='verified' or not action.get('before') or not action.get('after')):return False
        if name in (SELECT,CONFIRM):
            rows=parent['movement_popup']['options'];stamp=digest(rows)
            if (len(target)!=5 or type(target[1]) is not int or type(target[3]) is not int or not 0<=target[3]<len(rows)
                    or target[:3]!=[parent['popup_basis']['node'],index,stamp] or rows[target[3]][1]!=target[4] or target[4]!='花火'):return False
            proof=action.get('popup_selection_proof',{})
            return name==SELECT or (proof.get('options')==stamp and proof.get('slot')==target[3]
                and proof.get('input_epoch')==action['input_epoch'] and isinstance(proof.get('run_dir'),str) and bool(proof['run_dir']))
        expected,_,_=_expected(parent)
        if name==INSPECT:return (len(target)==5 and type(target[1]) is int and type(target[4]) is int and target[4]==index
            and target[0]+':'+str(target[1]) in expected and target[2]==parent['popup_basis']['node']
            and isinstance(target[3],str) and re.fullmatch('[0-9a-f]{64}',target[3]) is not None)
        if target[:2]!=[parent['popup_basis']['node'],index] or type(target[1]) is not int:return False
        return ((name==STALE and len(target)==2) or (name==CLOSE and len(target)==5 and target[2] in expected
            and isinstance(target[3],str) and re.fullmatch('[0-9a-f]{64}',target[3]) is not None
            and type(target[4]) is int and index<target[4]<action['id']))
    except (IndexError,KeyError,TypeError,ValueError):return False


def valid_parent(action,actions):
    try:
        popup=action['movement_popup'];expected,_,_=_expected(action)
        if (action.get('status')!='verified' or not action.get('before') or not action.get('after')
                or type(action.get('id')) is not int or not 0<=action['id']<len(actions) or actions[action['id']]!=action
                or popup.get('kind')!='star_selection' or popup.get('basis')!=digest(action['popup_basis'])
                or type(action.get('popup_verified')) is not bool or not 1<=len(popup['options'])<=6
                or sorted(r[0] for r in popup['options'])!=list(range(len(popup['options']))) or sum(r[1]=='花火' for r in popup['options'])!=1):return False
        if set(action['popup_appearances'])!=set(action['popup_basis']['cells']):return False
        for key,value in action['popup_basis']['cells'].items():
            if value[0]=='occupied':_decoded(action['popup_appearances'][key])
            elif action['popup_appearances'][key] is not None:return False
        if (len({r[1] for r in popup['options']})!=len(popup['options']) or any(len(r)!=3 or not re.fullmatch(r'[\u4e00-\u9fff]{1,12}',r[1])
                or not re.fullmatch(r'盛会之星[一—-]'+re.escape(r[1])+r'女士',r[2]) for r in popup['options'])):return False
        if not {r[1] for r in popup['options']}<={u['name'] for u in expected.values()}:return False
        end=action.get('popup_receipt',{}).get('final_action_id',len(actions)-1) if action['popup_verified'] else len(actions)-1
        if type(end) is not int or not action['id']<=end<len(actions):return False
        history=actions[action['id']+1:end+1]
        if (any(a.get('action') not in ACTIONS or a.get('popup_parent_action_id')!=action['id'] for a in history)
                or any(sum(a.get('action')==kind for a in history)>1 for kind in (SELECT,CONFIRM))):return False
        if not action['popup_verified']:return action.get('movement_verified') is False
        receipt=action['popup_receipt'];proofs=receipt['proofs'];confirm=actions[receipt['confirm_action_id']]
        if (action.get('movement_verified') is not True or receipt.get('parent_action_id')!=action['id']
                or set(proofs)!=set(expected) or confirm.get('action')!=CONFIRM or not valid_child(confirm,actions)
                or receipt['final_action_id']!=max(p['close_action_id'] for p in proofs.values())
                or receipt.get('status')!='verified' or receipt.get('board_source')!=actions[end].get('after')
                or set(receipt['cells'])!=set(action['popup_basis']['cells'])):return False
        _,changed,_=_expected(action)
        if (any(receipt['cells'][k][0]!=v[0] or v[0]=='occupied' and not same_appearance(action['popup_appearances'][k],receipt['appearances'][k])
                for k,v in action['popup_basis']['cells'].items() if k not in changed)
                or {k for k,v in receipt['cells'].items() if v[0]=='occupied'}!=set(expected)):return False
        for key,proof in proofs.items():
            inspect=actions[proof['inspection_action_id']];close=actions[proof['close_action_id']]
            if (proof.get('closed') is not True or not proof.get('source') or not valid_child(inspect,actions) or not valid_child(close,actions)
                    or inspect.get('action')!=INSPECT or close.get('action')!=CLOSE or not confirm['id']<inspect['id']<close['id']
                    or inspect['target'][:2]!=[expected[key]['zone'],expected[key]['slot']]
                    or close['target'][2:]!=[key,proof['signature'],inspect['id']]
                    or proof['input_epoch']!=inspect['input_epoch'] or proof['input_epoch']!=close['input_epoch']
                    or proof['run_dir']!=inspect.get('inspection_run_dir')
                    or proof['run_dir']!=receipt.get('verified_run') or proof['input_epoch']!=receipt.get('input_epoch')
                    or proof['appearance']!=inspect.get('popup_appearance')
                    or not same_appearance(proof['appearance'],receipt['appearances'][key])
                    or any(proof['unit'][k]!=v for k,v in expected[key].items() if v is not None)):return False
        return True
    except (AutomationError,AttributeError,IndexError,KeyError,TypeError,ValueError):return False
