"""One input owner and one resource budget for an ordered dungeon plan."""
from dataclasses import replace
import time
import uuid

from .models import AutomationError,DungeonQuotaExhausted,InputInterrupted,Scene,TaskResult
from .power_plan import PowerItem,plan_spec,row_keys,digest
from .power_plan_store import folder,write,prior,file_ref,pointer,fs_path


def account(ctx,scene):
    from .du_daily import account_key
    ctx.checkpoint()
    if (not isinstance(scene,Scene) or scene is not ctx.last_scene or ctx.scene_epoch!=ctx.runner.input_epoch
            or scene.captured_at<=0 or time.monotonic()-scene.captured_at>8):
        raise AutomationError('体力计划画面代次已变化，需要重新识别。')
    return digest(account_key(Scene([t for t in scene.tokens if t.score>=max(.85,ctx.settings.ocr_confidence)])))


class PowerRun:
    def __init__(self,ctx,*,new_goal=False):
        self.parent=ctx;self.budget=ctx.battle_budget;self.report=ctx.report
        self.settings=replace(ctx.settings);self.items,self.spec=plan_spec(self.settings)
        if not self.budget or not self.budget.active or self.report.stamina_pending or self.report.immersifiers_pending:
            raise AutomationError('体力计划缺少唯一运行预算，或原支付仍待核对。')
        self.root=self.budget.runs
        identity=account(ctx,ctx.snapshot());directory=folder(self.root,identity,self.spec)
        before=[0]*len(self.items);previous=None;sequence=1
        if self.settings.power_plan_keep:
            goal=uuid.uuid4().hex
        else:
            index=directory/'current.json'
            if fs_path(index).exists() and not new_goal:
                saved=pointer(self.root,directory)
                goal=saved['goal']
            else:
                if not new_goal and fs_path(directory).exists() and any(p.is_dir() and p.name!='repeat' for p in fs_path(directory).iterdir()):
                    raise AutomationError('体力计划原目标索引缺失，未重置已完成次数。')
                goal=uuid.uuid4().hex;saved=dict(schema=1,goal=goal,head=None);write(index,saved)
            last,previous=prior(self.root,identity,self.spec,goal)
            if previous!=saved['head']:raise AutomationError('体力计划原进度链与索引不同，未重建次数。')
            if last is not None:
                completed=dict(zip(row_keys(last['items']),[a+b for a,b in zip(last['before'],last['done'])]))
                before=[completed[key] for key in row_keys([p.to_dict() for p in self.items])];sequence=last['sequence']+1
        fallback=None
        if self.settings.power_plan_fill:
            from .dungeons import category_for
            category=category_for(self.settings)
            fallback=dict(category=category.key,target=self.settings.target_name.strip(),location=self.settings.target_location.strip())
        self.data=dict(schema=1,account=identity,spec=self.spec,goal=goal,run=uuid.uuid4().hex,
            keep=self.settings.power_plan_keep,fill=self.settings.power_plan_fill,items=[p.to_dict() for p in self.items],
            before=before,done=[0]*len(self.items),previous=previous,sequence=sequence,charges=[],intent=None,
            run_status='active',active_row=None,active_count=None,active_before=0,
            fallback=fallback,fallback_requested=self.settings.challenge_count if fallback else None,
            configured_limit=self.settings.stamina_limit,stamina_initial=None,effective_limit=None,
            immersifiers_initial=None,immersifiers_limit=None,resources_evidence=None,results=[])
        from .echo_weekly import create
        self.data['weekly_echo']=create(self.settings,started_at=self.report.started_at)
        self.ctx=ctx;self.report.power_plan=self.data;self.budget.power_plan=self
        self.budget._write()
        self.publish('ready')

    def remaining(self,index):return self.items[index].count-self.data['before'][index]-self.data['done'][index]

    def item(self,index):
        if index>=0:return self.items[index]
        if index==-2:
            from .echo_weekly import target
            return target(self.data['weekly_echo'])
        return PowerItem(**dict(self.data['fallback'],count=1))

    def quota_proof(self,ctx,scene,remaining):
        from .dungeon_workflow import weekly_rewards
        if type(remaining) is not int or not 0<=remaining<=3 or weekly_rewards(scene)!=remaining:
            raise AutomationError('历战周次数缺少原指南画面来源。')
        evidence=self.witness(ctx,scene,'power_plan_quota_source')
        return dict(remaining=remaining,epoch=ctx.runner.input_epoch,account=self.data['account'],
                    completed=self.report.battle_completed,evidence=evidence)

    def observe_echo(self,ctx,scene,remaining,*,proof=None):
        from .echo_weekly import require_week,remaining as quota
        echo=self.data['weekly_echo'];require_week(echo)
        available=quota(echo)
        if type(remaining) is not int or not 0<=remaining<=3 or available is not None and remaining>available:
            raise AutomationError('历战当前周次数未核实，或超过原冻结额度。')
        if proof is None:proof=self.quota_proof(ctx,scene,remaining)
        if type(proof) is not dict or any(type(proof.get(k)) is not int for k in ('remaining','epoch','completed')):
            raise AutomationError('历战周次数来源字段无效。')
        if proof['epoch']!=ctx.runner.input_epoch:
            raise InputInterrupted('历战周次数读取后输入代次已变化，需要重新核实指南。')
        if (account(ctx,scene)!=self.data['account'] or proof.get('remaining')!=remaining
                or proof.get('account')!=self.data['account']
                or proof.get('completed')!=self.report.battle_completed):
            raise AutomationError('历战周次数来源的账号、代次或支付进度已变化。')
        echo['observations'].append(dict(remaining=remaining,completed=echo['completed'],evidence=dict(proof['evidence'])))
        echo['state']='complete' if remaining==0 else 'active'
        self.budget._write();self.publish('weekly')

    def publish(self,stage):
        emit=getattr(self.parent.runner,'emit',None)
        if not callable(emit):return
        rows=[dict(item.to_dict(),before=self.data['before'][i],done=self.data['done'][i],remaining=self.remaining(i))
              for i,item in enumerate(self.items)]
        echo=self.data.get('weekly_echo');weekly=None
        if echo is not None:
            from .echo_weekly import remaining
            weekly={k:echo[k] for k in ('week','due','target','maximum','completed','state')}
            weekly=dict(weekly,remaining=remaining(echo),target=dict(weekly['target']))
        emit(dict(type='power_plan_progress',stage=stage,rows=rows,active_row=self.data['active_row'],weekly_echo=weekly,
            active_count=self.data['active_count'],keep=self.data['keep'],fill=self.data['fill'],
            battle_completed=self.report.battle_completed,stamina_spent=self.report.stamina_spent,
            stamina_pending=self.report.stamina_pending,immersifiers_spent=self.report.immersifiers_spent,
            immersifiers_pending=self.report.immersifiers_pending,effective_limit=self.data['effective_limit'],
            immersifiers_limit=self.data['immersifiers_limit'],goal_complete=all(self.remaining(i)==0 for i in range(len(self.items)))))

    def check(self):
        self.ctx.checkpoint()
        if self.data['intent'] is not None or self.report.stamina_pending or self.report.immersifiers_pending:
            raise AutomationError('体力计划原支付尚未核实，未重放或切换目标。')

    def witness(self,ctx,scene,label):
        if account(ctx,scene)!=self.data['account']:raise AutomationError('当前账号与原体力计划不同。')
        return file_ref(self.root,ctx.evidence(scene,label))

    def freeze_resources(self,ctx,scene,available,immersifiers):
        self.check()
        if self.data['stamina_initial'] is not None:raise AutomationError('体力计划已有初始资源，未重新冻结预算。')
        if any(type(v) is not int or not 0<=v<=999 for v in (available,immersifiers)) or immersifiers>12:
            raise AutomationError('体力计划初始资源未核实。')
        proof=self.witness(ctx,scene,'power_plan_resources')
        self.data.update(stamina_initial=available,effective_limit=min(self.settings.stamina_limit,available//10*10),
            immersifiers_initial=immersifiers,immersifiers_limit=immersifiers,resources_evidence=proof)
        self.budget._write()
        self.publish('resources')

    def tokens(self,actual):
        initial=self.data['immersifiers_initial'];limit=self.data['immersifiers_limit']
        if type(actual) is not int or initial is None or not 0<=actual<=12:
            raise AutomationError('体力计划沉浸器余额尚未核实。')
        remaining=limit-self.report.immersifiers_spent
        if actual>remaining:raise AutomationError('沉浸器余额超过原冻结资源计划，未扩大消耗。')
        if actual<remaining:
            self.data['immersifiers_limit']=self.report.immersifiers_spent+actual
            self.budget._write()
        return actual

    def bind(self,ctx,index,count):
        self.check();self.ctx=ctx
        self.data.update(active_row=index,active_count=count,active_before=self.report.battle_completed)
        self.budget.settings=ctx.settings;self.budget._write()
        self.publish('item')

    def reserve(self,cost,immersifiers):
        self.check();row=self.data['active_row']
        item=self.item(row) if row is not None else None
        if item is None or (self.ctx.settings.dungeon_category,self.ctx.settings.target_name,self.ctx.settings.target_location)!=(item.category,item.target,item.location):
            raise AutomationError('体力计划当前目标与冻结条目不同。')
        if self.data['effective_limit'] is None or self.report.stamina_spent+cost>self.data['effective_limit']:
            raise AutomationError('体力计划支付超过初始已有资源。')
        if self.report.immersifiers_spent+immersifiers>self.data['immersifiers_limit'] or immersifiers and item.category!='planar':
            raise AutomationError('体力计划沉浸器支付超过原范围。')
        nominal=cost+40*immersifiers
        if nominal<=0 or nominal%item.dungeon.cost:raise AutomationError('体力计划价格与副本单价不同。')
        count=nominal//item.dungeon.cost
        if row==-2:
            from .echo_weekly import remaining,require_week
            echo=self.data['weekly_echo'];require_week(echo)
            if remaining(echo) is None or count>remaining(echo) or any(c['row']!=-2 for c in self.data['charges']):
                raise AutomationError('历战缺少本次可用周次数，或优先阶段已经结束。')
        if not 1<=count<=item.dungeon.batch or self.report.battle_completed-self.data['active_before']+count>self.data['active_count']:
            raise AutomationError('体力计划批量或本项次数超过冻结目标。')
        if row>=0 and count>self.remaining(row):raise AutomationError('体力计划条目已完成，未重复支付。')
        evidence=self.witness(self.ctx,self.ctx.last_scene,'power_plan_before_'+str(len(self.data['charges'])))
        self.data['intent']=dict(id=len(self.data['charges']),row=row,count=count,stamina=cost,immersifiers=immersifiers,
            before_completed=self.report.battle_completed,account=self.data['account'],epoch=self.ctx.runner.input_epoch,before=evidence)

    def confirm(self,cost,immersifiers):
        intent=self.data['intent']
        if (intent is None or intent['stamina']!=cost or intent['immersifiers']!=immersifiers
                or self.report.battle_completed!=intent['before_completed']):
            raise AutomationError('体力计划结算与原支付次数不同。')
        evidence=self.witness(self.ctx,self.ctx.last_scene,'power_plan_success_'+str(intent['id']))
        charge={key:value for key,value in intent.items() if key!='before_completed'}
        charge.update(evidence=evidence,before_epoch=intent['epoch'],epoch=self.ctx.runner.input_epoch)
        self.data['charges'].append(charge)
        if intent['row']>=0:self.data['done'][intent['row']]+=intent['count']
        if intent['row']==-2:self.data['weekly_echo']['completed']+=intent['count']
        self.report.battle_completed=intent['before_completed']+intent['count']
        self.data['intent']=None

    def finish(self,partial=False):
        self.check();self.data.update(run_status='partial' if partial else 'complete',active_row=None,active_count=None)
        self.data['goal_complete']=all(self.remaining(i)==0 for i in range(len(self.items)))
        self.budget._write()
        self.publish('partial' if partial else 'complete')


class PowerWorkflow:
    def __init__(self,ctx,*,new_goal=False,workflow_factory=None):
        from .workflows import DailyWorkflow
        self.ctx=ctx;self.new_goal=new_goal;self.factory=workflow_factory or DailyWorkflow

    def view(self,state,item,count):
        settings=replace(state.settings,dungeon_category=item.category,target_name=item.target,target_location=item.location,
            challenge_count=count,rounds=min(state.settings.rounds,item.dungeon.batch),
            stamina_limit=state.data['effective_limit'] if state.data['effective_limit'] is not None else state.settings.stamina_limit)
        view=self.ctx.item_view(settings)
        return view,self.factory(view)

    def resources(self,state):
        planned=[item for i,item in enumerate(state.items) if state.remaining(i)]
        echo=state.data.get('weekly_echo')
        if echo is not None and echo['due']:planned.insert(0,state.item(-2))
        if state.data['fallback'] is not None:planned.append(PowerItem(**dict(state.data['fallback'],count=1)))
        if not planned:return
        probe=next((item for item in planned if item.category=='planar'),
                   next((item for item in planned if not item.dungeon.weekly_limit),planned[0]))
        view,workflow=self.view(state,probe,1)
        try:scene=workflow._open_calyx()
        except DungeonQuotaExhausted as error:scene=error.scene
        stamina=workflow._available(scene)
        if probe.category=='planar':
            from .planar_resources import inventory
            immersifiers=inventory(scene)
        else:immersifiers=0
        state.freeze_resources(view,scene,stamina,immersifiers)
        self.ctx.last_scene,self.ctx.scene_epoch=view.last_scene,view.scene_epoch

    def execute(self,state,item,index,requested):
        state.check()
        if index==-2:
            from .echo_weekly import require_week
            require_week(state.data['weekly_echo'])
        if index!=-2 and state.data['effective_limit'] is not None and state.data['effective_limit']-state.report.stamina_spent<item.dungeon.cost:
            if item.category!='planar' or state.data['immersifiers_limit']==state.report.immersifiers_spent:return None
        view,workflow=self.view(state,item,1)
        try:scene=workflow._open_calyx()
        except DungeonQuotaExhausted as error:
            if index==-2:
                state.observe_echo(view,error.scene,0)
                self.ctx.last_scene,self.ctx.scene_epoch=view.last_scene,view.scene_epoch
                return None
            proof=state.witness(view,error.scene,'power_plan_weekly_exhausted')
            state.data['results'].append(dict(row=index,requested=requested,completed=0,stamina=0,immersifiers=0,
                status='deferred',reason='weekly_exhausted',detail=str(error),evidence=proof))
            state.budget._write()
            self.ctx.last_scene,self.ctx.scene_epoch=view.last_scene,view.scene_epoch
            return None
        available=workflow._available(scene)
        if type(available) is not int:raise AutomationError('本项体力余额未核实。')
        remaining=max(0,min(state.data['effective_limit']-state.report.stamina_spent,available))
        tokens=0
        if item.category=='planar':
            from .planar_resources import inventory
            tokens=state.tokens(inventory(scene))
        count=min(requested,remaining//item.dungeon.cost+tokens)
        if item.dungeon.weekly_limit:
            quota=getattr(workflow,'_weekly_rewards',None)
            if type(quota) is not int or not 0<=quota<=3:raise AutomationError('历战当前周次数未核实。')
            if index==-2:state.observe_echo(view,scene,quota,proof=getattr(workflow,'_weekly_rewards_proof',None))
            count=min(count,quota)
        if count<=0:return None
        view.settings=replace(view.settings,challenge_count=count);workflow.settings=view.settings
        state.bind(view,index,count);base=state.report.battle_completed
        before=state.report.stamina_spent;immersifiers=state.report.immersifiers_spent
        try:
            try:result=workflow.battle(completed_base=base,aggregate=True)
            except DungeonQuotaExhausted as error:
                state.check()
                if index==-2:state.observe_echo(view,error.scene,0)
                else:state.witness(view,error.scene,'power_plan_weekly_exhausted')
                result=TaskResult('battle','ok','已核实本周额度用尽，未完成的原次数保留。')
        finally:self.ctx.last_scene,self.ctx.scene_epoch=view.last_scene,view.scene_epoch
        state.data['results'].append(dict(row=index,requested=count,completed=state.report.battle_completed-base,
            stamina=state.report.stamina_spent-before,immersifiers=state.report.immersifiers_spent-immersifiers,status=result.status,detail=result.detail))
        state.budget._write();return result

    def weekly(self,state):
        echo=state.data.get('weekly_echo')
        if echo is None or not echo['due']:return False
        if echo['state'] in ('complete','limited','partial'):return echo['state']=='partial'
        item=state.item(-2);result=self.execute(state,item,-2,3-echo['completed'])
        if echo['state']!='complete' and result is not None:
            from .echo_weekly import require_week
            require_week(echo)
            view,workflow=self.view(state,item,1)
            try:
                try:scene=workflow._open_calyx();quota=getattr(workflow,'_weekly_rewards',None)
                except DungeonQuotaExhausted as error:scene,quota=error.scene,0
                state.observe_echo(view,scene,quota,proof=getattr(workflow,'_weekly_rewards_proof',None))
            finally:self.ctx.last_scene,self.ctx.scene_epoch=view.last_scene,view.scene_epoch
        if echo['state']!='complete':
            echo['state']='limited' if result is None or result.status=='ok' else 'partial'
            state.budget._write();state.publish('weekly')
        return result is not None and result.status!='ok'

    def run(self):
        if not self.ctx.settings.allow_stamina_spend:return TaskResult('battle','skipped','未授权资源消耗，体力计划未执行。')
        state=getattr(self.ctx.battle_budget,'power_plan',None)
        if state is None:state=PowerRun(self.ctx,new_goal=self.new_goal)
        state.check();partial=False
        if (state.data.get('weekly_echo') is not None and state.data['weekly_echo']['due']
                and state.data['weekly_echo']['state'] in ('waiting','active')):
            from .echo_weekly import require_week
            require_week(state.data['weekly_echo'])
        if state.data['effective_limit'] is None:self.resources(state)
        partial=self.weekly(state)
        for i,item in enumerate(state.items):
            if state.remaining(i)==0:continue
            result=self.execute(state,item,i,state.remaining(i))
            if result is None:break
            partial=partial or result.status!='ok'
            if result.status!='ok' or state.remaining(i)>0:break
        if state.data['fallback'] is not None:
            item=PowerItem(**dict(state.data['fallback'],count=1))
            completed=sum(c['count'] for c in state.data['charges'] if c['row']==-1)
            requested=state.data['fallback_requested']
            remaining=9999 if requested is None else max(0,requested-completed)
            if remaining:
                result=self.execute(state,item,-1,remaining)
                partial=partial or result is not None and result.status!='ok'
        state.finish(partial)
        total=sum(state.remaining(i) for i in range(len(state.items)))
        deferred='历战本周额度已用尽，原次数保留；' if any(r.get('reason')=='weekly_exhausted' for r in state.data['results']) else ''
        echo=state.data.get('weekly_echo')
        if echo is not None:
            from .echo_weekly import remaining
            if not echo['due']:deferred='历战周计划尚未到期；'+deferred
            elif echo['state']=='complete':deferred=f'已核实历战目标周（{echo["week"]}起）额度用尽，本次确认{echo["completed"]}次；'+deferred
            else:deferred=f'历战本次确认{echo["completed"]}次，目标周剩余{remaining(echo)}次；'+deferred
        return TaskResult('battle','partial' if partial else 'ok',
            f'{deferred}本次确认{state.report.battle_completed}次挑战，{state.report.stamina_spent}开拓力、{state.report.immersifiers_spent}沉浸器；原计划剩余{total}次。')
