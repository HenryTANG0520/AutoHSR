"""Independent observed-score operation and saved, account/week-bound evidence."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import uuid

from .currency_wars import CurrencyWarsWorkflow,TASK
from .currency_wars_identity import account_key,installed_client
from .currency_wars_navigation import locate
from .currency_wars_points import game_week,local_now,period_evidence,proof_tokens,read_points
from .currency_wars_state import strict_json
from .models import AutomationError,Scene,TaskResult,Token
from .storage import replace_file

OPERATION='currency_wars_points'


def require_no_active_match(data):
    if data is not None and (data['status']!='settled' or data.get('completion_verified') is not True
                            or data.get('settlement_verified') is not True
                            or any(a.get('status')!='verified' for a in data['actions'])):
        raise AutomationError('已有未核实结束的标准对局；积分导航未开始，不放弃或重开当前局。')


def _inside(root,value):
    path=Path(value).resolve()
    if not path.is_relative_to(root) or path==root:
        raise AutomationError('积分证据路径不在本地运行目录内。')
    return path


def _hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _read(path):
    with path.open('rb') as stream:raw=stream.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:raise AutomationError('积分记录超过大小限制。')
    return strict_json(raw.decode('utf-8'))


def _write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    replace_file(temp,path)


def receipt_path(root,data):
    if (not isinstance(data.get('account_key'),str) or re.fullmatch(r'[0-9a-f]{64}',data['account_key']) is None
            or not isinstance(data.get('observation_id'),str) or re.fullmatch(r'[0-9a-f]{32}',data['observation_id']) is None):
        raise AutomationError('积分账号或观察记录标识无效。')
    return root/'currency-points'/data['account_key']/data['game_week']/(data['observation_id']+'.json')


def inspect_points(c):
    if c.report.operation!=OPERATION:
        raise AutomationError('积分核对须使用独立入口。')
    result=locate(c,stop_at_lobby=True)
    navigation=c.report.currency_wars
    if not navigation.get('entry_ready') or navigation.get('page_kind')!='lobby':return result
    guard=CurrencyWarsWorkflow(c)
    last_error=None
    for _ in range(3):
        c.checkpoint();scene=c.snapshot();guard._require_current_scene(scene)
        try:
            points=read_points(scene,c.settings.ocr_confidence)
            if points.page!='lobby':raise AutomationError('积分核对返回页不是已核实主页。')
            identity=account_key(scene,max(.85,c.settings.ocr_confidence))
            break
        except AutomationError as error:
            last_error=error;c.sleep(.2)
    else:raise last_error
    now=local_now()
    weekly=getattr(c.runner,'currency_weekly_guard',None)
    if weekly is not None:weekly.require_observation(identity,game_week(now),points.current)
    period=period_evidence(scene,now,c.settings.ocr_confidence)
    guard._require_current_scene(scene)
    screenshot=Path(c.evidence(scene,'currency_weekly_points'))
    root=Path(c.report.run_dir).parent.resolve()
    _inside(root,screenshot)
    data=dict(schema=1,mode='weekly_points',observation_id=uuid.uuid4().hex,account_key=identity,
              game_week=game_week(now),observed_at=now.isoformat(),run_dir=c.report.run_dir,
              confidence=max(.85,c.settings.ocr_confidence),
              input_epoch=c.scene_epoch,points_verified=True,current=points.current,limit=points.limit,
              score_complete=points.complete,period=period,weekly_target_verified=points.complete and period['verified'],
              rewards_verified=False,completion_verified=False,match_started=False,navigation=navigation,
              source=str(screenshot),source_sha256=_hash(screenshot),tokens=proof_tokens(scene,points.page))
    data['receipt_path']=str(receipt_path(root,data))
    client=installed_client(getattr(getattr(c,'window',None),'path',None))
    data['client']={key:client[key] for key in ('version','full_version','kind','sha256') if key in client}
    c.checkpoint()
    guard._require_current_scene(scene)
    c.report.currency_wars=data
    c.report.safe_next=('本周积分已达标，奖励领取尚未核实。' if data['weekly_target_verified'] else
                        '当前显示满分，但游戏周倒计时尚未核实。' if points.complete else '积分未满；本次未开始对局或领取积分奖励。')
    c.runner.emit(dict(type=TASK,data=data))
    return TaskResult(TASK,'ok',f'当前积分{points.current}/{points.limit}；奖励领取未核实。')


def validate_observation(root,data):
    if (type(data) is not dict or type(data.get('schema')) is not int or data['schema']!=1 or data.get('mode')!='weekly_points'
            or data.get('points_verified') is not True or data.get('rewards_verified') is not False
            or data.get('completion_verified') is not False or data.get('match_started') is not False
            or type(data.get('input_epoch')) is not int or data['input_epoch']<0
            or type(data.get('current')) is not int or type(data.get('limit')) is not int):
        raise AutomationError('积分观察记录结构或范围无效。')
    now=datetime.fromisoformat(data['observed_at'])
    if game_week(now)!=data['game_week']:
        raise AutomationError('积分观察时间与游戏周不一致。')
    path=receipt_path(root,data)
    if str(path)!=data.get('receipt_path'):
        raise AutomationError('积分回执路径不符。')
    tokens=data.get('tokens')
    if not isinstance(tokens,list) or not 1<=len(tokens)<=32:
        raise AutomationError('积分文字来源缺失或超出范围。')
    scene=Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in tokens])
    confidence=data.get('confidence')
    if type(confidence) not in (int,float) or not math.isfinite(confidence) or not .85<=confidence<=.99:
        raise AutomationError('积分字段置信度来源无效。')
    points=read_points(scene,confidence)
    if (points.page!='lobby' or points.current!=data['current'] or points.limit!=data['limit']
            or points.complete is not data.get('score_complete')
            or json.dumps(period_evidence(scene,now,confidence),sort_keys=True,allow_nan=False)!=json.dumps(data.get('period'),sort_keys=True,allow_nan=False)
            or (points.complete and data['period']['verified']) is not data.get('weekly_target_verified')
            or proof_tokens(scene,points.page)!=tokens):
        raise AutomationError('积分结果与原始字段、倒计时或限定来源不符。')
    directory=_inside(root,data['run_dir'])
    source=_inside(root,data['source'])
    if not source.is_relative_to(directory) or not source.is_file() or _hash(source)!=data['source_sha256']:
        raise AutomationError('积分原始证据缺失、越界或改变。')
    return path


def finalize(report):
    """Called after native report writing, while this Runner still owns the lock."""
    if report.operation!=OPERATION or report.status!='success' or report.report_saved is not True:
        raise AutomationError('积分报告尚未完整保存。')
    root=Path(report.run_dir).parent.resolve();data=report.currency_wars
    path=validate_observation(root,data)
    report_path=Path(report.run_dir)/'report.json'
    saved=_read(report_path)
    if saved!=json.loads(json.dumps(report.to_dict())):
        raise AutomationError('积分原报告与本次观察不一致。')
    receipt=dict(schema=1,observation=data,report=str(report_path),report_sha256=_hash(report_path))
    # Observation IDs are random; never replace an older account/week record.
    if path.exists():raise AutomationError('积分观察回执已存在，未覆盖。')
    _write(path,receipt)
    _write(path.parent/'latest.json',dict(schema=1,receipt=str(path),sha256=_hash(path)))


def read_receipt(root,path):
    """Validate an immutable observation and its original saved report."""
    root=Path(root).resolve();path=_inside(root,path)
    receipt=_read(path)
    if (type(receipt) is not dict or set(receipt)!={'schema','observation','report','report_sha256'}
            or type(receipt['schema']) is not int or receipt['schema']!=1):
        raise AutomationError('积分回执结构无效。')
    data=receipt['observation']
    if validate_observation(root,data)!=path:
        raise AutomationError('积分归属或原始来源不符。')
    report_path=_inside(root,receipt['report']);saved=_read(report_path)
    if (report_path!=Path(data['run_dir']).resolve()/'report.json'
            or _hash(report_path)!=receipt['report_sha256'] or saved.get('status')!='success'
            or saved.get('report_saved') is not True or saved.get('operation')!=OPERATION
            or saved.get('currency_wars')!=data or Path(saved['run_dir']).resolve()!=report_path.parent):
        raise AutomationError('积分原报告缺失或改变。')
    return receipt


def latest(root,account,week):
    """Historical evidence only; callers must obtain current account identity."""
    root=Path(root).resolve()
    if not isinstance(account,str) or not isinstance(week,str) or re.fullmatch(r'[0-9a-f]{64}',account) is None or re.fullmatch(r'\d{4}-\d{2}-\d{2}',week) is None:
        raise AutomationError('积分账号或游戏周标识无效。')
    directory=root/'currency-points'/account/week
    pointer=_read(directory/'latest.json')
    if (type(pointer) is not dict or set(pointer)!={'schema','receipt','sha256'}
            or type(pointer['schema']) is not int or pointer['schema']!=1):
        raise AutomationError('积分入口记录结构无效。')
    path=_inside(root,pointer['receipt'])
    if path.parent!=directory or _hash(path)!=pointer['sha256']:
        raise AutomationError('积分入口与回执不一致。')
    receipt=read_receipt(root,path)
    data=receipt['observation']
    if data['account_key']!=account or data['game_week']!=week:
        raise AutomationError('积分归属或原始来源不符。')
    return receipt
