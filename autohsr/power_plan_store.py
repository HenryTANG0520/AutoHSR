"""Archive the canonical budget before replacement; retain consumed goals."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from .models import AutomationError
from .storage import replace_file
from .power_plan import items,spec_digest,row_keys


def read(path):
    try:
        path=Path(path)
        if path.stat().st_size>16*1024*1024:raise ValueError('体力计划记录过大')
        data=json.loads(path.read_text('utf8'))
        if type(data) is not dict:raise ValueError('体力计划记录不是对象')
        return data
    except (OSError,ValueError,TypeError) as error:raise AutomationError('体力计划原记录无法核实：'+str(error)) from error


def write(path,data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    replace_file(temp,path)


def hex_id(value,size):return type(value) is str and re.fullmatch('[0-9a-f]{'+str(size)+'}',value) is not None


def inside(root,value):
    path=Path(value).resolve();root=Path(root).resolve()
    if path==root or not path.is_relative_to(root):raise AutomationError('体力计划证据路径不在运行目录。')
    return path


def file_ref(root,path):
    path=inside(root,path)
    return dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def read_ref(root,ref):
    if type(ref) is not dict or set(ref)!={'path','sha256'} or not hex_id(ref['sha256'],64):raise AutomationError('体力计划证据引用无效。')
    path=inside(root,ref['path'])
    try:value=hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:raise AutomationError('体力计划原证据无法读取。') from error
    if value!=ref['sha256']:raise AutomationError('体力计划原证据已改变。')
    return path


def folder(root,account,spec):
    if not hex_id(account,64) or not hex_id(spec,64):raise AutomationError('体力计划账号或目标标识无效。')
    # Two full SHA-256 directory names exceed MAX_PATH in ordinary Windows
    # user-data locations once the goal and archive IDs are appended. Records
    # retain the full digests; use 128-bit path keys for new folders and keep
    # existing layouts exactly where they are.
    legacy=Path(root)/'power-plans'/account/spec
    current=Path(root)/'power-plans'/account[:32]/spec[:32]
    if legacy.exists() and current.exists():raise AutomationError('体力计划新旧目录同时存在，未合并或重建进度。')
    return legacy if legacy.exists() else current


def pointer(root,directory):
    saved=read(directory/'current.json')
    if (set(saved)!={'schema','goal','head'} or type(saved['schema']) is not int
            or saved['schema']!=1 or not hex_id(saved['goal'],32)):
        raise AutomationError('体力计划目标索引损坏，未重建次数。')
    if saved['head'] is not None:read_ref(root,saved['head'])
    return saved


def validate(root,data,*,settled=False):
    """One canonical write contains both the resource and row counters."""
    try:
        plan=data['power_plan'];spec=items(plan['items']);count=len(spec)
        if (type(data.get('version')) is not int or data['version']!=1
                or data.get('status') not in ('active','success','partial','failed','stopped')
                or any(type(data.get(k)) is not int or data[k]<0 for k in ('spent','pending','completed','limit'))
                or not 10<=data['limit']<=240 or data['spent']+data['pending']>data['limit']
                or any(type(data.get(k,0)) is not int or not 0<=data.get(k,0)<=12 for k in ('immersifiers_spent','immersifiers_pending'))):raise ValueError('资源账本无效')
        if (type(plan['schema']) is not int or plan['schema']!=1 or not spec and plan.get('weekly_echo') is None
                or spec_digest([p.to_dict() for p in spec])!=plan['spec']
                or not hex_id(plan['account'],64) or not hex_id(plan['goal'],32) or not hex_id(plan['run'],32)
                or type(plan['keep']) is not bool or type(plan['fill']) is not bool
                or type(plan['sequence']) is not int or plan['sequence']<1
                or plan['run_status'] not in ('active','complete','partial')
                or any(type(plan[k]) is not list or len(plan[k])!=count or any(type(v) is not int or v<0 for v in plan[k]) for k in ('before','done'))
                or any(plan['before'][i]>spec[i].count for i in range(count))):raise ValueError('目标、归属或计数无效')
        run_dir=inside(root,data['run_dir'])
        from .echo_weekly import validate as validate_echo,remaining as echo_remaining
        weekly=validate_echo(plan.get('weekly_echo'),lambda ref:inside(run_dir,read_ref(root,ref)))
        fallback=items([dict(plan['fallback'],count=1)])[0] if plan['fill'] else None
        if not plan['fill'] and plan['fallback'] is not None:raise ValueError('补刷目标与开关不同')
        requested=plan['fallback_requested']
        if plan['fill'] and requested is not None and (type(requested) is not int or not 1<=requested<=9999):raise ValueError('补刷次数无效')
        if type(plan['configured_limit']) is not int or plan['configured_limit']!=data['limit'] or data['limit']%10:raise ValueError('初始预算不同')
        initial=plan['stamina_initial'];effective=plan['effective_limit']
        initial_tokens=plan['immersifiers_initial'];token_limit=plan['immersifiers_limit']
        if initial is None:
            if any(v is not None for v in (effective,initial_tokens,token_limit,plan['resources_evidence'])) or plan['charges'] or plan['intent'] is not None:raise ValueError('初始资源未核实')
        else:
            if (type(initial) is not int or not 0<=initial<=999 or type(effective) is not int
                    or effective!=min(data['limit'],initial//10*10)
                    or type(initial_tokens) is not int or not 0<=initial_tokens<=12
                    or type(token_limit) is not int or not 0<=token_limit<=initial_tokens
                    or data['spent']+data['pending']>effective
                    or data.get('immersifiers_spent',0)+data.get('immersifiers_pending',0)>token_limit):raise ValueError('支付超过冻结已有资源')
            inside(run_dir,read_ref(root,plan['resources_evidence']))
        active=plan['active_row']
        if active is not None and (type(active) is not int or not -2<=active<count
                or active==-1 and not plan['fill']
                or active==-2 and weekly is None
                or type(plan['active_count']) is not int or plan['active_count']<1
                or type(plan['active_before']) is not int or not 0<=plan['active_before']<=data['completed']):raise ValueError('执行条目无效')
        totals=[0]*count;stamina=immersifiers=completed=0
        if type(plan['charges']) is not list or len(plan['charges'])>1000:raise ValueError('支付记录无效')
        for i,charge in enumerate(plan['charges']):
            if (type(charge) is not dict or charge['id']!=i or type(charge['id']) is not int
                    or type(charge['row']) is not int or not -2<=charge['row']<count
                    or any(type(charge[k]) is not int or charge[k]<0 for k in ('stamina','immersifiers','count','epoch','before_epoch'))
                    or charge['epoch']<charge['before_epoch']
                    or charge['count']<1 or charge['account']!=plan['account']):raise ValueError('支付来源或数量无效')
            if charge['row']==-2 and any(c['row']!=-2 for c in plan['charges'][:i]):raise ValueError('历战优先阶段已结束')
            item=spec[charge['row']] if charge['row']>=0 else weekly if charge['row']==-2 else fallback
            if item is None or charge['count']>item.dungeon.batch or charge['stamina']+charge['immersifiers']*40!=charge['count']*item.dungeon.cost or charge['immersifiers'] and item.category!='planar':raise ValueError('支付资源与次数不符')
            if charge['row']>=0:totals[charge['row']]+=charge['count']
            stamina+=charge['stamina'];immersifiers+=charge['immersifiers'];completed+=charge['count']
            inside(run_dir,read_ref(root,charge['evidence']))
            inside(run_dir,read_ref(root,charge['before']))
        if totals!=plan['done'] or any(plan['before'][i]+totals[i]>spec[i].count for i in range(count)):raise ValueError('已完成计划计数不符')
        if stamina!=data['spent'] or immersifiers!=data.get('immersifiers_spent',0):raise ValueError('计划与资源账单不符')
        validate_echo(plan.get('weekly_echo'),lambda ref:inside(run_dir,read_ref(root,ref)),
                      completed=sum(c['count'] for c in plan['charges'] if c['row']==-2))
        intent=plan['intent']
        if intent is None:
            if data['pending'] or data.get('immersifiers_pending',0) or data['completed']!=completed:raise ValueError('支付或完成数尚未核实')
        else:
            if (settled or type(intent) is not dict or type(intent['id']) is not int or intent['id']!=len(plan['charges'])
                    or type(intent['row']) is not int or not -2<=intent['row']<count
                    or intent['row']!=active or intent['account']!=plan['account']
                    or any(type(intent[k]) is not int or intent[k]<0 for k in ('stamina','immersifiers','count','epoch','before_completed'))
                    or intent['stamina']!=data['pending'] or intent['immersifiers']!=data.get('immersifiers_pending',0)
                    or intent['before_completed']!=completed or data['completed'] not in (completed,completed+intent['count'])):raise ValueError('原支付意图尚未结束')
            item=spec[active] if active>=0 else weekly if active==-2 else fallback
            if (item is None or not 1<=intent['count']<=item.dungeon.batch
                    or intent['stamina']+40*intent['immersifiers']!=intent['count']*item.dungeon.cost
                    or intent['immersifiers'] and item.category!='planar'
                    or active>=0 and plan['before'][active]+plan['done'][active]+intent['count']>spec[active].count
                    or active==-2 and (echo_remaining(plan['weekly_echo']) is None or intent['count']>echo_remaining(plan['weekly_echo']))
                    or active==-2 and any(c['row']!=-2 for c in plan['charges'])
                    or completed-plan['active_before']+intent['count']>plan['active_count']):raise ValueError('支付意图超过当前条目')
            inside(run_dir,read_ref(root,intent['before']))
        fallback_count=sum(c['count'] for c in plan['charges'] if c['row']==-1)
        if plan['fill'] and requested is not None and fallback_count>requested:raise ValueError('补刷次数超过原请求')
        previous=plan['previous']
        if previous is None:
            if plan['sequence']!=1 or any(plan['before']):raise ValueError('首份计划不是从零开始')
        else:read_ref(root,previous)
        return plan
    except (KeyError,IndexError,TypeError,ValueError) as error:raise AutomationError('体力计划账本未核实：'+str(error)) from error


def archive(root,data):
    if not data.get('power_plan'):return
    plan=validate(root,data,settled=True)
    path=folder(root,plan['account'],plan['spec'])/('repeat' if plan['keep'] else plan['goal'])/(plan['run']+'.json')
    if path.exists():
        if read(path)!=data:raise AutomationError('原体力计划归档已存在且不同，未覆盖。')
    else:write(path,deepcopy(data))
    if not plan['keep']:
        directory=folder(root,plan['account'],plan['spec']);saved=pointer(root,directory)
        ref=file_ref(root,path)
        if saved['goal']!=plan['goal'] or saved['head'] not in (plan['previous'],ref):
            raise AutomationError('体力计划原索引与归档链不同，未替换预算。')
        if saved['head']!=ref:write(directory/'current.json',dict(saved,head=ref))


def prior(root,account,spec,goal):
    directory=folder(root,account,spec)/goal
    records=[]
    for path in directory.glob('*.json'):
        data=read(path);plan=validate(root,data,settled=True)
        if plan['account']!=account or plan['spec']!=spec or plan['goal']!=goal or plan['keep']:raise AutomationError('体力计划归档归属不同。')
        records.append((plan['sequence'],path,data,plan))
    records.sort(key=lambda row:row[0]);previous=None
    for index,(sequence,path,data,plan) in enumerate(records,1):
        if sequence!=index or plan['previous']!=previous:raise AutomationError('体力计划进度链缺失或分叉，未重建次数。')
        if index>1:
            completed=dict(zip(row_keys(last['items']),[a+b for a,b in zip(last['before'],last['done'])]))
            if plan['before']!=[completed[key] for key in row_keys(plan['items'])]:raise AutomationError('体力计划剩余次数与原记录不同。')
        previous=file_ref(root,path);last=plan
    return (records[-1][3],previous) if records else (None,None)
