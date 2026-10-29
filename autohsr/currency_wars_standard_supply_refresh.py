"""A fresh supply refresh quota, one click and an immutable candidate chain.

March7th reference: check_supply_phase. Pinned source and GPL license are in
assets/upstream/March7thAssistant/source.json; inputs use native Context.
"""
from copy import deepcopy
from functools import lru_cache
import hashlib
import json
import re

import cv2
import numpy as np

from .config import RESOURCE_ROOT
from .currency_wars import observe
from .currency_wars_match import read_match
from .currency_wars_supply import supply_count
from .currency_wars_supply_policy import groups,matches
from .models import AutomationError,Scene,Token,normalize

ACTION='refresh_standard_supply'
EXPECTED='standard_supply_refreshed'
POLICY='standard-supply-refresh-v1'
MAX_REFRESHES=5
COUNTER=(.70,.88,.79,.945)
ICON=(.66,.875,.705,.945)
FIELDS=('currency_supply_refresh_raw','currency_supply_refresh_binary')
HUD=('node','gold','hp','level','experience','deployment')


def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _parse(tokens,confidence):
    if not tokens:return None
    if any(t is None or not max(.9,confidence)<=t.score<=1 or not t.within(COUNTER) for t in tokens):
        raise AutomationError('补给刷新次数读取不完整或可信度不足。')
    values=set();labels=[];numbers=[]
    for t in tokens:
        text=normalize(t.text)
        m=re.fullmatch(r'剩余(?:刷新)?次数([0-9]{1,2})',text)
        if m:values.add(int(m[1]))
        elif text in ('剩余次数','剩余刷新次数'):labels.append(t)
        elif re.fullmatch(r'[0-9]{1,2}',text):numbers.append(t)
        else:raise AutomationError('补给刷新次数包含矛盾或未知文字。')
    if numbers:
        if not labels and not values:raise AutomationError('补给数字缺少当前剩余次数标题。')
        for number in numbers:
            if labels and not any(number.center[0]>label.center[0] and abs(number.center[1]-label.center[1])<.025 for label in labels):
                raise AutomationError('补给次数数字没有对应当前标题。')
            values.add(int(normalize(number.text)))
    if not values:return None
    if len(values)!=1:raise AutomationError('补给剩余次数读数冲突。')
    box=(min(t.box[0] for t in tokens),min(t.box[1] for t in tokens),max(t.box[2] for t in tokens),max(t.box[3] for t in tokens))
    value=next(iter(values))
    return value,Token('剩余次数'+str(value),min(t.score for t in tokens),box)


def remaining(scene,confidence=.65):
    raw=[t for t in scene.tokens if t.within(COUNTER)]
    result=_parse(raw,confidence)
    if any(k in scene.field_reads for k in FIELDS):
        variants=[_parse(scene.field_reads.get(k,()),confidence) for k in FIELDS]
        if any(v is None for v in variants) or variants[0][0]!=variants[1][0] or result and result[0]!=variants[0][0]:
            raise AutomationError('补给次数的原图与二值局部读取未对应。')
        result=result or variants[0]
    if result is None:raise AutomationError('当前补给剩余刷新次数未核实。')
    return result


def supplement_remaining(scene,reader):
    if scene.image is None or observe(scene,.65).page_kind!='supply_selection' or not hasattr(reader,'read'):return scene
    try:remaining(scene);return scene
    except AutomationError:pass
    h,w=scene.image.shape[:2];x1,y1,x2,y2=COUNTER
    patch=scene.image[round(y1*h):round(y2*h),round(x1*w):round(x2*w)]
    fields=dict(scene.field_reads)
    binary=cv2.threshold(cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY),160,255,cv2.THRESH_BINARY)[1]
    for key,sample in zip(FIELDS,(patch,binary)):
        local=reader.read(cv2.resize(sample,None,fx=3,fy=3))
        if len(local.tokens)>8:raise AutomationError('补给次数局部文字超出可核验范围。')
        fields[key]=tuple(Token(t.text,t.score,(x1+t.box[0]*(x2-x1),y1+t.box[1]*(y2-y1),
            x1+t.box[2]*(x2-x1),y1+t.box[3]*(y2-y1))) for t in local.tokens) or (None,)
    return Scene(scene.tokens,scene.image,scene.geometry,scene.captured_at,fields)


@lru_cache(maxsize=1)
def icon_template():
    root=RESOURCE_ROOT/'assets/currency-supply'
    meta=json.loads((root/'sources.json').read_text(encoding='utf-8'))['items'][0]
    raw=(root/meta['file']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise AutomationError('补给刷新控件参考哈希不符。')
    return cv2.imdecode(np.frombuffer(raw,np.uint8),cv2.IMREAD_COLOR)


def icon_ready(scene):
    if scene.image is None:return False
    image=cv2.resize(scene.image,(2560,1440));x1,y1,x2,y2=ICON
    patch=image[round(y1*1440):round(y2*1440),round(x1*2560):round(x2*2560)]
    ref=icon_template()
    if min(patch.shape[:2])<min(ref.shape[:2]) or any(a<b for a,b in zip(patch.shape[:2],ref.shape[:2])):return False
    scores=cv2.matchTemplate(patch,ref,cv2.TM_CCOEFF_NORMED);_,score,_,point=cv2.minMaxLoc(scores)
    x,y=point;matched=patch[y:y+ref.shape[0],x:x+ref.shape[1]]
    return score>=.92 and np.mean(np.min(matched,axis=2)>190)>.30


def table(scene,confidence=.65):
    from .currency_wars_standard_rewards import _options
    from .currency_wars_supply_fields import rows
    result=[]
    for option,(_,role,equipment) in zip(_options(scene,'supply_selection',confidence),rows(scene,confidence)):
        slot,name,item,unit,gold,target=option
        result.append(dict(slot=slot,name=name,item_name=normalize(equipment.text),item=item))
    return result


def modal_hud(scene,confidence=.65):
    state=read_match(scene,confidence,include_rewards=True)
    if not state or state.page!='supply_selection' or not state.node:raise AutomationError('刷新需要当前补给页与节点。')
    result=json.loads(json.dumps({k:getattr(state,k) for k in HUD}))
    if not _valid_hud(result):raise AutomationError('补给当前可见资源或人数无效，未刷新。')
    return result


def _source(actions,index,node):
    if type(index) is not int or not 0<=index<len(actions):raise AutomationError('补给到达动作编号无效。')
    parent=actions[index];target=parent.get('target',[])
    if not isinstance(target,(list,tuple)) or len(target)!=2 or type(target[1]) is not int or not 0<=target[1]<index:
        raise AutomationError('补给出战来源编号无效。')
    start=actions[target[1]]
    if (parent.get('id')!=index or parent.get('action')!='continue_standard_node' or parent.get('status')!='verified'
            or len(target)!=2 or type(target[1]) is not int or not 0<=target[1]<index
            or not parent.get('before') or not parent.get('after') or parent.get('feedback')!=dict(page_kind='supply_selection',node=node)
            or start.get('action')!='start_standard_node' or start.get('status')!='verified' or start.get('target',[None])[0]!=target[0]
            or not start.get('before') or not start.get('after')
            or start.get('reward_basis',{}).get('snapshot',{}).get('roster_complete') is not True):
        raise AutomationError('补给刷新缺少本次出战与到达来源。')
    return start['reward_basis']


def _basis_valid(basis,source,node):
    if (not isinstance(basis,dict) or not isinstance(source,dict) or not isinstance(basis.get('inventory'),dict)
            or any(not isinstance(k,str) or type(v) is not int or v<0 for k,v in basis['inventory'].items())
            or not isinstance(basis.get('cells'),dict) or not isinstance(basis.get('snapshot'),dict)
            or not isinstance(basis['snapshot'].get('roster'),list)):return False
    return (basis.get('node')==node and all(basis.get(k)==source.get(k) for k in ('snapshot','cells','inventory'))
            and basis.get('snapshot',{}).get('mode')=='standard'
            and basis['snapshot'].get('game_version')=='4.6' and basis['snapshot'].get('rules_version')=='4.6')


def _chain(actions,index):
    tail=actions[index+1:];selection=None
    if tail and tail[-1].get('action')=='select_standard_supply':selection=tail[-1];tail=tail[:-1]
    if any(a.get('action')!=ACTION or not valid_receipt(a,actions) for a in tail) or len(tail)>MAX_REFRESHES:
        raise AutomationError('补给刷新记录不连续或存在未核实动作。')
    for a,b in zip(tail,tail[1:]):
        if (a['target'][1]!=index or b['target'][1]!=index or a['target'][5]!=b['target'][5]
                or a['supply_refresh_origin']['strategy']!=b['supply_refresh_origin']['strategy']
                or a['supply_refresh_receipt']['remaining_after']!=b['target'][2]
                or digest(a['supply_refresh_receipt']['candidates_after'])!=b['target'][3]
                or digest(a['supply_refresh_receipt']['hud_after'])!=b['target'][4]):
            raise AutomationError('补给次数、原始候选或资源来源链不连续。')
    if tail and tail[0]['target'][1]!=index:raise AutomationError('补给刷新不能跨领取来源使用。')
    return tail,selection


def refresh_action(scene,session,data,confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    if data['page']!='supply_selection':return None
    index=data['origin_action_id'];actions=session['actions']
    source=_source(actions,index,data['basis']['node'])
    if not _basis_valid(data['basis'],source,data['basis']['node']):raise AutomationError('补给冻结阵容或库存来源不符。')
    history,selection=_chain(actions,index)
    candidates=table(scene,confidence)
    if history:
        last=history[-1]
        if (candidates!=last['supply_refresh_receipt']['candidates_after'] or remaining(scene,confidence)[0]!=last['supply_refresh_receipt']['remaining_after']
                or modal_hud(scene,confidence)!=last['supply_refresh_receipt']['hud_after'] or digest(data['basis'])!=last['target'][5]
                or session.get('strategy')!=last['supply_refresh_origin']['strategy']):
            raise AutomationError('当前补给次数、资源或完整候选不符上次已核实刷新。')
        if selection and selection.get('supply_refresh_binding')!=_binding(last):raise AutomationError('补给选中项缺少本次刷新来源。')
    count=supply_count(scene,confidence)
    if selection and (selection.get('status')!='verified' or count!=1):raise AutomationError('补给已有选择动作，未重新刷新或选择。')
    if count!=0:return None
    from .currency_wars_standard_rewards import _options
    options=_options(scene,'supply_selection',confidence);desired=groups(data,session.get('strategy','default'))
    if not desired or matches(options,desired[0]):return None
    quota,target=remaining(scene,confidence)
    if quota==0 or len(history)>=MAX_REFRESHES:return None
    if not icon_ready(scene):raise AutomationError('当前补给刷新控件未核实，未按裸坐标点击。')
    hud=modal_hud(scene,confidence)
    return StandardAction(ACTION,EXPECTED,target,details=(session['strategy'],quota,desired[0],POLICY),
        payload=(hud['node'],index,quota,digest(candidates),digest(hud),digest(data['basis'])))


def bind_intent(session,choice,scene,confidence=.65):
    from .currency_wars_standard_rewards import _scope,_active
    prior=_scope(session,ACTION);data=_active(prior)
    if refresh_action(scene,prior,data,confidence)!=choice:raise AutomationError('补给刷新意图与当前完整页面不符。')
    session['actions'][-1]['supply_refresh_origin']=dict(basis=deepcopy(data['basis']),before_table=table(scene,confidence),
        before_hud=modal_hud(scene,confidence),run_dir=prior['collection']['run_dir'],input_epoch=prior['collection']['input_epoch'],
        strategy=prior['strategy'],game_version='4.6',rules_version='4.6')


def feedback(choice,before,after,session,confidence=.65):
    try:
        action=session['actions'][-1];origin=action['supply_refresh_origin'];target=choice.payload
        return (before.image is not None and after.image is not None and action['action']==ACTION and action['target']==list(target)
            and remaining(before,confidence)[0]==target[2] and table(before,confidence)==origin['before_table']
            and modal_hud(before,confidence)==origin['before_hud']
            and supply_count(after,confidence)==0 and remaining(after,confidence)[0]==target[2]-1
            and modal_hud(after,confidence)==origin['before_hud'] and len(table(after,confidence))==len(origin['before_table']))
    except (AutomationError,KeyError,IndexError,TypeError):return False


def refreshed(session,choice,scene,confidence=.65):
    action=session['actions'][-1];origin=action['supply_refresh_origin'];after=table(scene,confidence)
    action['supply_refresh_receipt']=dict(schema=1,quota_used=1,remaining_before=choice.payload[2],remaining_after=remaining(scene,confidence)[0],
        candidates_before=origin['before_table'],candidates_after=after,candidates_changed=after!=origin['before_table'],
        hud_before=origin['before_hud'],hud_after=modal_hud(scene,confidence))
    if not valid_receipt(action,session['actions']):raise AutomationError('补给刷新回执未对应本次意图，原记录保留。')
    session['reward'].setdefault('supply_refresh_ids',[]).append(action['id'])
    session['action_status']='supply_refreshed'


def _valid_table(rows,private_names=()):
    from .currency_wars_standard_rewards import ITEM_IDS
    return (isinstance(rows,list) and len(rows) in (4,5) and len({r['name'] for r in rows})==len(rows)
        and all(set(r)=={'slot','name','item_name','item'} and type(r['slot']) is int and r['slot']==i
            and isinstance(r['name'],str) and (r['name'] in private_names or re.fullmatch(r'(?:[\u4e00-\u9fffa-z0-9·.]{1,40}|unknown:[0-9a-f]{64})',r['name']))
            and isinstance(r['item_name'],str) and re.fullmatch(r'[\u4e00-\u9fff]{2,20}',r['item_name'])
            and r['item']==ITEM_IDS.get(r['item_name']) for i,r in enumerate(rows)))


def _valid_hud(hud):
    if not isinstance(hud,dict) or set(hud)!=set(HUD) or not re.fullmatch(r'[1-3]-[1-9][0-9]?',hud['node']):return False
    for key,low,high in (('gold',0,99999),('hp',1,100),('level',1,10)):
        if hud[key] is not None and (type(hud[key]) is not int or not low<=hud[key]<=high):return False
    for key in ('experience','deployment'):
        value=hud[key]
        if value is not None and (not isinstance(value,list) or len(value)!=2 or any(type(v) is not int for v in value)
                or not 0<=value[0]<=value[1] or not 1<=value[1]<=(10 if key=='deployment' else 9999)):return False
    return True


def valid_receipt(action,actions):
    try:
        target=action['target'];origin=action['supply_refresh_origin'];receipt=action['supply_refresh_receipt'];index=action['id']
        if (action.get('action')!=ACTION or action.get('status')!='verified' or action.get('expected')!=EXPECTED
                or type(index) is not int or not 0<=index<len(actions) or actions[index]!=action
                or len(target)!=6 or type(target[1]) is not int or not 0<=target[1]<index
                or type(target[2]) is not int or not 1<=target[2]<=99
                or any(not isinstance(v,str) or not re.fullmatch('[0-9a-f]{64}',v) for v in target[3:])
                or not action.get('before') or not action.get('after')
                or type(action.get('input_epoch')) is not int or action['input_epoch']<0 or action['input_epoch']!=origin['input_epoch']
                or not isinstance(origin.get('run_dir'),str) or not origin['run_dir'] or origin.get('strategy') not in ('aglaea','seele')
                or origin.get('game_version')!='4.6' or origin.get('rules_version')!='4.6'
                or receipt.get('schema')!=1 or type(receipt.get('quota_used')) is not int or receipt['quota_used']!=1
                or type(receipt.get('remaining_before')) is not int or receipt['remaining_before']!=target[2]
                or type(receipt.get('remaining_after')) is not int or receipt['remaining_after']!=target[2]-1
                or not _valid_table(origin['before_table'],origin['basis']['snapshot'].get('private_names',()))
                or not _valid_table(receipt['candidates_after'],origin['basis']['snapshot'].get('private_names',()))
                or len(origin['before_table'])!=len(receipt['candidates_after']) or receipt.get('candidates_before')!=origin['before_table']
                or type(receipt.get('candidates_changed')) is not bool or receipt['candidates_changed']!=(receipt['candidates_after']!=origin['before_table'])
                or not _valid_hud(origin['before_hud']) or receipt.get('hud_before')!=origin['before_hud'] or receipt.get('hud_after')!=origin['before_hud']
                or target[0]!=origin['before_hud']['node'] or digest(origin['before_table'])!=target[3]
                or digest(origin['before_hud'])!=target[4] or digest(origin['basis'])!=target[5]):return False
        source=_source(actions,target[1],target[0])
        return _basis_valid(origin['basis'],source,target[0])
    except (AutomationError,AttributeError,IndexError,KeyError,TypeError,ValueError):return False


def _binding(action):
    return dict(origin_action_id=action['target'][1],refresh_action_id=action['id'],table_digest=digest(action['supply_refresh_receipt']['candidates_after']))


def valid_prefix(action,actions):
    try:
        history,selection=_chain(actions[:action['id']+1],action['target'][1])
        return selection is None and bool(history) and history[-1]['id']==action['id']
    except (AutomationError,AttributeError,IndexError,KeyError,TypeError,ValueError):return False


def bind_choice(session,choice,scene,confidence=.65):
    data=session['reward'];actions=session['actions'];history,selection=_chain(actions[:-1],data['origin_action_id'])
    if not history:return
    last=history[-1]
    if table(scene,confidence)!=last['supply_refresh_receipt']['candidates_after']:raise AutomationError('领取前的完整补给候选已变。')
    actions[-1]['supply_refresh_binding']=_binding(last)


def valid_claim_chain(action,actions):
    try:
        target=action['target'];select=actions[action['id']-1]
        history,extra=_chain(actions[:action['id']-1],target[1])
        if not history:return not action.get('supply_refresh_binding') and not select.get('supply_refresh_binding')
        if extra is not None:return False
        last=history[-1];rows=last['supply_refresh_receipt']['candidates_after']
        return (action.get('supply_refresh_binding')==_binding(last)==select.get('supply_refresh_binding')
            and target[0]==last['target'][0] and target[8]==digest([[r['slot'],r['name'],r['item'],None if r['name'].startswith('unknown:') else r['name'],0] for r in rows]))
    except (AutomationError,AttributeError,IndexError,KeyError,TypeError,ValueError):return False
