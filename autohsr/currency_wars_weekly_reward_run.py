"""Bounded reward IO, two-frame feedback, and a separate post-report receipt."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from .currency_wars import CurrencyWarsWorkflow, TASK
from .currency_wars_identity import account_key, installed_client
from .currency_wars_navigation import locate
from .currency_wars_points import game_week, local_now, period_evidence, proof_tokens, read_points
from .currency_wars_points_run import _hash
from .currency_wars_weekly_rewards import BUTTON, CLOSE, EMPTY, OPERATION, kind, next_action, panel_control, quantities
from .currency_wars_weekly_reward_store import RewardStore
from .models import AutomationError, EmptyCapture, TaskResult, normalize


def client(c):
    metadata=installed_client(c.window.path)
    return {key:metadata[key] for key in ('version','full_version','kind','sha256') if key in metadata}


def current(c,scene,data=None):
    c.checkpoint();CurrencyWarsWorkflow(c)._require_current_scene(scene)
    identity=account_key(scene,max(.85,c.settings.ocr_confidence))
    if data is not None:
        if identity!=data['account_key']:raise AutomationError('当前账号与积分领奖记录不同。')
        if game_week(local_now())!=data['game_week']:raise AutomationError('积分领奖已跨游戏周，未使用旧目标继续输入。')
    return identity


def evidence(c,scene,label):
    current(c,scene)
    path=c.evidence(scene,'currency_weekly_rewards_'+label)
    page=kind(scene,max(.85,c.settings.ocr_confidence))
    confidence=max(.85,c.settings.ocr_confidence)
    tokens=proof_tokens(scene,page) if page in ('lobby','points_rewards') else []
    for token in scene.tokens:
        text=normalize(token.text)
        allowed=(page=='points_rewards' and (text=='一键领取' and token.within(BUTTON)
                      or text in EMPTY and token.within(BUTTON))
                 or page=='reward_overlay' and (text=='获得物品' and token.within((.25,.04,.75,.25))
                      or text=='点击空白处关闭' and token.within(CLOSE)
                      or token.within((.10,.24,.90,.64)) and re.fullmatch(r'[x×]?\d[\d,，]{0,9}',text))
                 or page=='fuel_ticket_limit' and token.within((.20,.30,.80,.60)) and text and text in '背包内助燃券持有数量已达上限')
        entry=dict(text=token.text,score=token.score,box=list(token.box))
        if allowed and 'uid' not in text.casefold() and entry not in tokens:tokens.append(entry)
    result=dict(path=str(path),sha256=_hash(path),page=page,input_epoch=c.scene_epoch,confidence=confidence,
                captured_at=scene.captured_at,observed_at=local_now().isoformat(),tokens=tokens)
    if page in ('lobby','points_rewards'):
        points=read_points(scene,max(.85,c.settings.ocr_confidence))
        result.update(current=points.current,limit=points.limit)
        if page=='points_rewards':
            try:result['panel_state']=panel_control(scene,confidence)[0]
            except AutomationError:result['panel_state']='unknown'
        else:result['period']=period_evidence(scene,local_now(),confidence)
    if page=='reward_overlay':result['quantities']=quantities(scene,max(.85,c.settings.ocr_confidence))
    c.checkpoint();CurrencyWarsWorkflow(c)._require_current_scene(scene)
    return result


def _publish(c,store):
    c.report.currency_wars=deepcopy(store.data)
    c.runner.emit(dict(type=TASK,data=deepcopy(store.data)))


def _stable(c,store,expected,*,settled=False,epoch=None):
    """Unknown/loading is bounded rereading, never a repeated submission."""
    sources=[];signature=None
    confidence=max(.85,c.settings.ocr_confidence)
    epoch=c.runner.input_epoch if epoch is None else epoch
    for _ in range(40):
        c.checkpoint()
        if c.runner.input_epoch!=epoch:raise AutomationError('积分领奖输入代次改变，旧反馈资格已丢弃。')
        try:scene=c.snapshot()
        except EmptyCapture:c.sleep(.3);continue
        if c.runner.input_epoch!=epoch:raise AutomationError('积分领奖反馈截图代次改变。')
        CurrencyWarsWorkflow(c)._require_current_scene(scene)
        page=kind(scene,confidence)
        try:identity=account_key(scene,confidence)
        except AutomationError:
            sources=[];c.sleep(.3);continue
        if identity!=store.data['account_key']:raise AutomationError('领奖反馈账号改变，未继续输入。')
        if game_week(local_now())!=store.data['game_week']:raise AutomationError('领奖反馈已跨游戏周，原记录保留。')
        if page=='fuel_ticket_limit' and expected=='reward_overlay':
            value=(page,)
        elif page!=expected:
            sources=[];c.sleep(.3);continue
        else:
            try:
                if page in ('lobby','points_rewards'):
                    points=read_points(scene,confidence)
                    if points.current!=store.data['current']:raise AutomationError('领奖反馈积分改变。')
                    if settled and panel_control(scene,confidence)[0]!='settled':
                        sources=[];c.sleep(.3);continue
                    if page=='lobby' and period_evidence(scene,local_now(),confidence)['verified'] is not True:
                        raise AutomationError('领奖返回主页后的游戏周倒计时未核实。')
                    value=(page,points.current)
                else:value=(page,tuple(quantities(scene,confidence)))
            except AutomationError:
                sources=[];c.sleep(.3);continue
        if value!=signature:sources=[]
        signature=value;sources.append(evidence(c,scene,'feedback_'+page))
        if len(sources)==2:return scene,sources,page
        c.sleep(.3)
    raise AutomationError('积分领奖反馈未获得两帧一致核实，未重发输入。')


def inspect_rewards(c):
    if c.report.operation!=OPERATION:raise AutomationError('积分领奖须使用独立入口。')
    c.report.safe_next='积分领奖未完成；保留当前记录和原报告，未知领取不重发；仅已核实步骤可明确接续。'
    store=RewardStore(Path(c.report.run_dir).parent)
    prior=store.preflight(c.runner.currency_rewards_resume)
    c.currency_weekly_rewards=store
    if c.runner.currency_rewards_resume:
        if prior['phase']=='returned' and prior['rewards_verified'] is True:
            # Normally handled by Runner before game preparation; kept here
            # too for direct Context use and report-only recovery.
            _publish(c,store);return TaskResult(TASK,'ok','原领奖与返回证据完整；只读补存原报告回执。')
        if client(c)!=prior['client'] or max(.85,c.settings.ocr_confidence)!=prior['confidence']:
            raise AutomationError('当前客户端或识别设置与本次领奖原记录不同。')
        scene=c.snapshot();current(c,scene,store.data)
        store.data['continuations'].append(c.report.run_dir);store.save()
    else:
        result=locate(c,stop_at_lobby=True)
        if not c.report.currency_wars.get('entry_ready'):return result
        scene=c.snapshot();identity=current(c,scene)
        confidence=max(.85,c.settings.ocr_confidence);points=read_points(scene,confidence)
        now=local_now();period=period_evidence(scene,now,confidence)
        if points.page!='lobby' or period['verified'] is not True:
            raise AutomationError('积分领奖前的主页积分或游戏周倒计时未核实。')
        observed=dict(account_key=identity,game_week=game_week(now),observed_at=now.isoformat(),current=points.current,
                      confidence=confidence,period=period,evidence=evidence(c,scene,'initial'))
        metadata=client(c);current(c,scene)
        store.begin(observed,metadata,c.report.run_dir)
    try:
        for _ in range(6):
            current(c,scene,store.data)
            phase=store.data['phase']
            if phase=='blocked':
                c.report.safe_next='助燃券满额已核实，当前没有清理或重复领取；保留原记录，满额处理仍待接入。'
                _publish(c,store);return TaskResult(TASK,'partial',c.report.safe_next)
            if phase=='panel_after_claim' or phase=='panel' and panel_control(scene,max(.85,c.settings.ocr_confidence))[0]=='settled':
                scene,sources,_=_stable(c,store,'points_rewards',settled=True)
                store.data.update(phase='panel_settled',settled_evidence=sources);store.save()
            choice=next_action(scene,store.data,max(.85,c.settings.ocr_confidence))
            store.pending(choice,c.runner.input_epoch,evidence(c,scene,'before_'+choice.intent))
            _publish(c,store)
            c.currency_weekly_reward_input(scene,choice)
            scene,sources,page=_stable(c,store,choice.expected,epoch=store.data['actions'][-1]['epoch'])
            phase={'open_points_rewards':'panel','claim_weekly_rewards':'overlay',
                   'dismiss_weekly_rewards':'panel_after_claim','return_weekly_lobby':'returned'}[choice.intent]
            if page=='fuel_ticket_limit':phase='blocked'
            store.verify(sources,phase,result=page)
            if phase=='returned':
                _publish(c,store)
                c.report.safe_next='当前可领取积分奖励状态及返回已核实；周积分是否满额单独记录，不表示对局通关。'
                return TaskResult(TASK,'ok','本次领取并核实返回。' if store.data['claimed_now'] else '两帧核实当前无可领取积分奖励，已返回主页。')
            _publish(c,store)
        raise AutomationError('积分领奖阶段超过有界步骤，原记录保留。')
    except Exception as error:
        store.unknown(error);_publish(c,store);raise


def finalize(report):
    store=RewardStore(Path(report.run_dir).parent);store.load()
    store.finalize(report.to_dict())
