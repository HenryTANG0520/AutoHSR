"""Terminal defeat is distinct from node victory, technical failure and retry."""
import hashlib
import json
import re

from .currency_wars import observe
from .currency_wars_node import result_node
from .currency_wars_prepare import trusted
from .models import AutomationError


STEPS={
    'match_defeat':(('前往结算',),'defeat_rating'),
    'defeat_rating':(('下一步',),'defeat_summary'),
    'defeat_summary':(('下一页','下顶'),'match_statistics'),
    'match_statistics':(('返回货币战争','返回货百战争'),'lobby'),
}
INTENTS=frozenset('settle_standard_defeat_'+kind for kind in STEPS)


def attempt(session):
    data=session.get('node_attempt',{});actions=session.get('actions',[])
    index=data.get('start_action_id');node=data.get('node');frames=data.get('defeat_frames')
    if (session.get('status') not in ('active','settled') or session.get('start_verified') is not True
            or not isinstance(node,str) or not re.fullmatch(r'[1-3]-[1-9][0-9]?',node)
            or type(index) is not int or not 0<=index<len(actions)
            or actions[index].get('action')!='start_standard_node' or actions[index].get('status')!='verified'
            or not actions[index].get('before') or not actions[index].get('after')
            or not actions[index].get('target') or actions[index]['target'][0]!=node
            or data.get('status')!='defeated' or data.get('node_verified') is not False
            or data.get('result_kind')!='match_defeat' or data.get('defeat_observed') is not True
            or not isinstance(frames,list) or len(frames)!=2
            or any(not isinstance(p,str) or not p for p in frames) or len(set(frames))!=2 or data.get('result')!=frames[-1]
            or session.get('match_defeat_observed') is not True or session.get('defeat_start_action_id')!=index
            or session.get('match_victory_observed') is True or session.get('completion_verified') is not False):
        raise AutomationError('失败结算缺少同局出战、对应节点和两帧整局结束来源。')
    return data


def payload(session):
    source=attempt(session)
    raw=json.dumps(dict(node=source['node'],start_action_id=source['start_action_id'],frames=source['defeat_frames']),
                   sort_keys=True,separators=(',',':')).encode('utf8')
    return source['node'],source['start_action_id'],hashlib.sha256(raw).hexdigest()


def target(scene,kind,confidence=.65):
    labels,expected=STEPS[kind];clean=trusted(scene,confidence)
    candidates=[t for t in clean.tokens if t.text.strip() in labels and t.within((.45,.79,.55,.87))]
    if len(candidates)!=1:raise AutomationError('失败结算控件未唯一核实。')
    return expected,candidates[0]


def proposal(scene,session,confidence=.65):
    from .currency_wars_standard_flow import StandardAction
    kind=observe(scene,confidence).page_kind
    involved=kind in STEPS and (kind!='match_statistics' or session.get('match_defeat_observed') is True)
    if not involved:return None
    source=attempt(session);value=payload(session);actions=session['actions']
    if session.get('status')!='active':raise AutomationError('本局已结束，未重复失败结算。')
    from .currency_wars_standard_ledger import ledger_status
    if ledger_status(actions)!='clear':raise AutomationError('失败结算前仍有未核实动作或支付，未继续。')
    for name in ('exchange','equipment','reward','consumable','investment','movement_popup','popup','reorder','sale'):
        if session.get(name) and session[name].get('status')!='verified':
            raise AutomationError('失败结算前仍有未完成的协议：'+name)
    index=list(STEPS).index(kind)
    if index==0:
        if actions[-1]['id']!=source['start_action_id'] or result_node(scene,confidence)!=source['node']:
            raise AutomationError('当前整局结束不属于最近已核实出战。')
    else:
        previous=list(STEPS)[index-1];last=actions[-1]
        if (last.get('action')!='settle_standard_defeat_'+previous or last.get('status')!='verified'
                or last.get('expected')!=kind or last.get('target')!=list(value)
                or not last.get('before') or not last.get('after')):
            raise AutomationError('失败结算缺少上一页面及同一结算来源，未跳步。')
    if kind=='defeat_summary':
        tokens=trusted(scene,confidence).tokens
        nodes={m[1] for t in tokens if t.within((.40,.16,.53,.21))
               and (m:=re.fullmatch(r'([1-3]-[1-9][0-9]?)(?:战斗|奖励|首领)?',t.text.strip()))}
        if nodes!={source['node']}:raise AutomationError('失败阵容总览与原节点不同。')
    expected,button=target(scene,kind,confidence)
    return StandardAction('settle_standard_defeat_'+kind,expected,button,payload=value)


def feedback(choice,scene,session,confidence=.65):
    if choice.intent not in INTENTS:return False
    try:
        if choice.payload!=payload(session):return False
        kind=observe(scene,confidence).page_kind
        if kind!=choice.expected:return False
        if kind=='defeat_summary':
            nodes={m[1] for t in trusted(scene,confidence).tokens if t.within((.40,.16,.53,.21))
                   and (m:=re.fullmatch(r'([1-3]-[1-9][0-9]?)(?:战斗|奖励|首领)?',t.text.strip()))}
            return nodes=={choice.payload[0]}
        return True
    except (AutomationError,KeyError,TypeError,IndexError,ValueError):return False


def chain(session):
    """Validate without treating a current lobby alone as a settled defeat."""
    source=attempt(session);value=list(payload(session));actions=session['actions'];tail=actions[-4:]
    if (len(actions)<5 or actions[-5]['id']!=source['start_action_id'] or len(tail)!=4
            or any(a.get('id')!=len(actions)-4+i or a.get('action')!='settle_standard_defeat_'+kind
                   or a.get('expected')!=STEPS[kind][1] or a.get('target')!=value or a.get('status')!='verified'
                   or not a.get('before') or not a.get('after') for i,(a,kind) in enumerate(zip(tail,STEPS)))):
        raise AutomationError('整局失败四步结算链不完整。')
    return source


def settled(session):
    try:
        if (session.get('status')!='settled' or session.get('match_outcome')!='defeat'
                or session.get('defeat_settlement_verified') is not True or session.get('settlement_verified') is not True):return False
        chain(session)
        from .currency_wars_standard_ledger import ledger_status
        return ledger_status(session['actions'])=='clear'
    except (AutomationError,AttributeError,KeyError,TypeError,IndexError,ValueError):return False


def completed(session,choice,scene,confidence=.65):
    if choice.intent!='settle_standard_defeat_match_statistics':return False
    if not feedback(choice,scene,session,confidence):raise AutomationError('失败结算的返回主页未核实。')
    chain(session)
    session.update(status='settled',match_outcome='defeat',defeat_settlement_verified=True,
        settlement_verified=True,completion_verified=False,action_status='defeat_settled',
        reason='标准开发对局失败，结算返回已核实；未记录胜利或独立验收。')
    return True


def archive_proof(store,session,report_path,*,recovery=False,candidate=None):
    from .currency_wars_session import StandardSession,read_session
    StandardSession.validate(session)
    if not settled(session) or not session.get('development_only'):
        raise AutomationError('整局失败缺少完整结算，不能归档或开始下一局。')
    for name in ('exchange','equipment','reward','consumable','investment','movement_popup','popup','reorder','sale'):
        if session.get(name) and session[name].get('status')!='verified':raise AutomationError('失败局仍有未完成协议：'+name)
    first=session['actions'][0];source=attempt(session)
    if (first.get('action')!='start_standard_a8_40' or first.get('status')!='verified'
            or first.get('expected')!='boss_preview' or first.get('target',[])!=[]
            or not re.fullmatch('[0-9a-f]{64}',str(session.get('account_key','')))):
        raise AutomationError('失败局缺少本局开局或账号来源。')
    paths=list(source['defeat_frames'])
    for action in (first,session['actions'][source['start_action_id']],*session['actions'][-4:]):
        paths.extend((action.get('before'),action.get('after')))
    files={}
    for name in paths:
        if not isinstance(name,str) or not name:raise AutomationError('失败结算缺少原始证据。')
        path=store._inside(name)
        if not path.is_file() or path.stat().st_size==0:raise AutomationError('失败结算原证据丢失。')
        files[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
    path=store._inside(report_path);report=candidate if candidate is not None else read_session(path)
    if (report.get('status')!='partial' or report.get('report_saved') is not True
            or report.get('operation')!=('currency_wars_standard_recovery' if recovery else 'currency_wars_standard')
            or report.get('currency_wars')!=session):
        raise AutomationError('失败局原报告或只读恢复报告尚未保存，未进入下一局。')
    return dict(ending_evidence=files,report=str(path),
        report_sha256=None if candidate is not None else hashlib.sha256(path.read_bytes()).hexdigest(),
        recovered=recovery,outcome='defeat')
