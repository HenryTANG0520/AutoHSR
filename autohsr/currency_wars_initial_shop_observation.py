"""Read-only execution proof for an initial shop whose first close is unsent.

The accepted environment is immutable historical provenance. This separate
two-frame proof binds a fresh execution scope, never a replacement game intent.
"""
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import time

import numpy as np
from PIL import Image

from .currency_wars_initial import validate_origin, evidence_ref, source_file_ref
from .models import AutomationError

KEY='initial_shop_observation'
HISTORY='initial_shop_observation_history'
POLICY='initial-free-shop-observation-v1'
WAIT_SECONDS=15.
MAX_FRAMES=60
MAX_ATTEMPTS=16


def _fail(message='初始免费收店的重新观察来源未核实，未提交输入。'):
    raise AutomationError(message)


def _digest(value):
    from .currency_wars_initial import _digest
    return _digest(value)


def _reference(origin):
    return dict(match_id=origin['match_id'],action_id=origin['action_id'],run_dir=origin['run_dir'],
        epoch=origin['epoch'],action_digest=origin['origin']['action_digest'],
        accepted_after=origin['accepted_after'],arrival_digest=origin['arrival_digest'])


def _scope(session):
    client=session.get('client',{});root=session.get('account_verified_run');epoch=session.get('account_verified_epoch')
    if (type(root) is not str or not root or type(epoch) is not int or epoch<0
            or type(client) is not dict or client.get('verified_run')!=root
            or type(client.get('input_epoch')) is not int or client['input_epoch']!=epoch
            or client.get('version')!='4.6' or session.get('rules_version')!='4.6'):
        _fail()
    try:
        canonical=Path(root).resolve(strict=True)
        if not canonical.is_dir() or str(canonical)!=root:_fail()
    except (OSError,ValueError):_fail()
    frozen={key:value for key,value in client.items() if key not in ('verified_run','input_epoch')}
    return root,epoch,frozen


def needed(session):
    if not session.get('initial_environment'):return False
    origin=validate_origin(session,require_accepted=True)
    data=session.get('initial_shop_return')
    if origin.get('post_choice_observation') is not None or isinstance(data,dict) and data.get('status')=='verified':
        return False
    root,epoch,_=_scope(session)
    return (root,epoch)!=(origin['run_dir'],origin['epoch']) or KEY in session or HISTORY in session


def begin(session, *, confidence=.65):
    from .currency_wars_initial_shop import _direct
    origin=validate_origin(session,require_accepted=True)
    _direct(session,origin)
    if 'initial_shop_return' in session or origin.get('post_choice_observation') is not None:
        _fail('已有收店意图或当前现状，未覆盖、重采或重放。')
    root,epoch,client=_scope(session)
    if (root,epoch)==(origin['run_dir'],origin['epoch']):_fail('原执行代次仍有效，不创建替代来源。')
    history=deepcopy(session.get(HISTORY,[]))
    if KEY in session or HISTORY in session:
        previous=validate(session,current=False,complete=False)
        if (previous['run_dir'],previous['epoch'])==(root,epoch):
            _fail('同一执行作用域的未核实观察不自动重试；明确新运行或新代次才可重新观察。')
        history.append(previous)
    if len(history)>=MAX_ATTEMPTS:_fail('初始免费收店只读观察达到有限尝试上限，原记录保留。')
    data=dict(schema=1,policy=POLICY,status='observing',origin=_reference(origin),
        prefix_digest=_digest(session['actions']),run_dir=root,epoch=epoch,client=client,
        account_key=origin['account_key'],confidence=max(.85,confidence),frames=[],history_digest=_digest(history))
    session[HISTORY]=history
    data['digest']=_digest(data);session[KEY]=data
    return deepcopy(data)


def _same_semantics(first,last):
    from .currency_wars_initial_shop import _unchanged
    return (_unchanged(first['hud'],last['hud']) and
        all(first['source'].get(key)==last['source'].get(key) for key in ('control_box','offers','probabilities')))


def _image_source(reference,root):
    if reference!=source_file_ref(reference['path'],root):_fail()
    with Path(reference['path']).open('rb') as stream:raw=stream.read(32*1024*1024+1)
    if len(raw)>32*1024*1024 or hashlib.sha256(raw).hexdigest()!=reference['sha256']:_fail()
    with Image.open(io.BytesIO(raw)) as bitmap:image=np.asarray(bitmap.convert('RGB'))[:,:,::-1].copy()
    return dict(shape=list(image.shape),pixel_sha256=hashlib.sha256(image[:round(image.shape[0]*.94)].tobytes()).hexdigest())


def _checked(session,data,origin):
    if (type(data) is not dict or type(data.get('schema')) is not int or data['schema']!=1 or data.get('policy')!=POLICY
            or data.get('digest')!=_digest({k:v for k,v in data.items() if k!='digest'})
            or data.get('origin')!=_reference(origin) or data.get('account_key')!=origin['account_key']
            or type(data.get('epoch')) is not int or data['epoch']<0 or type(data.get('run_dir')) is not str
            or type(data.get('confidence')) not in (int,float) or not .85<=data['confidence']<=1
            or data.get('client',{}).get('version')!='4.6'
            or data.get('prefix_digest')!=_digest(session['actions'][:origin['action_id']+1])):_fail()
    frames=data.get('frames')
    if type(frames) is not list or len(frames)>2 or data.get('status') not in ('observing','verified','unknown'):_fail()
    if data['status']=='verified' and len(frames)!=2:_fail()
    for frame in frames:
        image=_image_source(frame['evidence'],data['run_dir'])
        if (any(frame.get('source',{}).get(key)!=value for key,value in image.items())
                or type(frame.get('source')) is not dict or frame['source'].get('captured_at')!=frame.get('captured_at')
                or type(frame.get('captured_at')) not in (int,float) or frame['captured_at']<=0
                or frame.get('hud',{}).get('node')!=origin['expected_node']):_fail()
    if len(frames)==2 and (frames[0]['captured_at']>=frames[1]['captured_at']
            or frames[0]['evidence']['path']==frames[1]['evidence']['path'] or not _same_semantics(*frames)):_fail()


def validate(session, *, current=True, complete=True):
    try:
        origin=validate_origin(session,require_accepted=True);data=session.get(KEY)
        history=session.get(HISTORY,[])
        if type(history) is not list or len(history)>=MAX_ATTEMPTS:_fail()
        for index,item in enumerate([*history,data]):
            _checked(session,item,origin)
            if item.get('history_digest')!=_digest(history[:index]):_fail('先前只读观察尝试已改变，未覆盖原件。')
        if complete and (data['status']!='verified' or len(data['frames'])!=2):_fail('重新观察未取得两份完整来源，原记录保留。')
        if current and (data['run_dir'],data['epoch'],data['client'])!=_scope(session):_fail('当前执行账号、客户端或代次与重新观察不符。')
        return deepcopy(data)
    except (AttributeError,KeyError,IndexError,TypeError,ValueError,OSError):_fail()


def record(session, scene, path, *, confidence=.65):
    from .currency_wars_initial_shop import _direct,_page
    origin=validate_origin(session,require_accepted=True);_direct(session,origin)
    if 'initial_shop_return' in session:_fail('已有收店提交，重新观察不能清除其状态。')
    data=validate(session,complete=False)
    if data['status']!='observing' or data['confidence']!=max(.85,confidence):_fail()
    _,payload=_page(scene,session,origin,confidence)
    item=dict(hud=deepcopy(payload[6]),source=deepcopy(payload[7]),captured_at=scene.captured_at,
              evidence=evidence_ref(scene,path,data['run_dir']))
    frames=data['frames']
    if frames:
        if scene.captured_at<=frames[-1]['captured_at']:return False
        if frames[-1]['evidence']['path']==item['evidence']['path'] or not _same_semantics(frames[-1],item):
            _fail('重新观察两帧页面、控件、候选或已读HUD冲突，未丢弃原帧重来。')
    if len(frames)>=2:_fail('重新观察来源已冻结，未增加或替换帧。')
    frames.append(item);data['status']='verified' if len(frames)==2 else 'observing'
    data['digest']=_digest({k:v for k,v in data.items() if k!='digest'});session[KEY]=data
    return len(frames)==2


def check_current(session, scene, origin, data, hud, source, confidence):
    from .currency_wars_initial_shop import _capture
    _capture(scene,fresh=True)
    if (data!=validate(session) or data['confidence']!=max(.85,confidence)
            or scene.captured_at<data['frames'][-1]['captured_at']
            or not _same_semantics(data['frames'][-1],dict(hud=hud,source=source))):_fail('当前收店页面不符本次重新观察，未使用旧目标。')


def ensure(c,store,scene):
    """Read at most two matching fresh sources; persist before any proposal."""
    if not needed(store.data):return scene
    if KEY in store.data:
        previous=validate(store.data,current=False,complete=False)
        if (previous['run_dir'],previous['epoch'],previous['client'])==_scope(store.data):
            validate(store.data)
            return scene
    from .currency_wars import CurrencyWarsWorkflow
    guard=CurrencyWarsWorkflow(c)
    begin(store.data,confidence=c.settings.ocr_confidence);store.persist()
    started=time.monotonic();inactive=c.runner.inactive_duration
    def elapsed():return max(0.,time.monotonic()-started-(c.runner.inactive_duration-inactive))
    try:
        for index in range(MAX_FRAMES):
            c.checkpoint();guard._require_current_scene(scene)
            if elapsed()>=WAIT_SECONDS:_fail('初始免费收店重新观察超时，未提交输入。')
            path=c.evidence(scene,'currency_initial_shop_reobserve_'+str(index+1))
            guard._require_current_scene(scene)
            if elapsed()>=WAIT_SECONDS:_fail('初始免费收店证据保存超过观察期限。')
            ready=record(store.data,scene,path,confidence=c.settings.ocr_confidence)
            if elapsed()>=WAIT_SECONDS:_fail('初始免费收店来源核验超过观察期限。')
            store.persist()
            if elapsed()>=WAIT_SECONDS:_fail('初始免费收店来源持久化超过观察期限。')
            if ready:return scene
            c.sleep(.15);scene=c.snapshot()
        _fail('初始免费收店重新观察达到有限帧上限。')
    except Exception:
        data=store.data[KEY];data['status']='unknown';data['failure']='observation_interrupted_or_unverified'
        data['digest']=_digest({k:v for k,v in data.items() if k!='digest'})
        try:store.persist()
        except (OSError,ValueError,AutomationError):pass
        raise
