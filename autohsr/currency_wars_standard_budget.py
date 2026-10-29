"""Technical work bounds for one invocation, reset by proven game progress.

These counters are not game-resource budgets. Explicit resume starts a new
invocation allowance, while the same match's journal/action bound is retained.
OCR, elapsed time, UI toggles and same-node gifts cannot reset a phase.
"""
import re

from .currency_wars_session import MAX_ACTIONS
from .models import AutomationError

PHASE_ACTIONS = 512


def node(value):
    return isinstance(value,str) and re.fullmatch(r'[1-3]-[1-9][0-9]?',value) is not None


def _continued(session):
    history=session.get('node_history',[])
    if not isinstance(history,list) or len(history)>MAX_ACTIONS:
        raise AutomationError('节点步骤来源记录损坏，未重置执行上限。')
    if not history:return -1,None
    try:
        entry=history[-1];start=entry['start_action_id'];end=entry['continue_action_id'];actions=session['actions']
        if (type(start) is not int or type(end) is not int or not 0<=start<end<len(actions)
                or not node(entry['node']) or entry.get('status')!='advanced' or entry.get('node_verified') is not True
                or not isinstance(entry.get('result'),str) or not entry['result']):raise ValueError()
        a,b=actions[start],actions[end];feedback=b['feedback'];plane,number=map(int,entry['node'].split('-'))
        if feedback.get('page_kind')=='plane_map' and plane>=3:raise ValueError()
        destination=f'{plane+1}-1' if feedback.get('page_kind')=='plane_map' and plane<3 else f'{plane}-{number+1}'
        if (not node(destination) or feedback.get('page_kind') not in ('plane_map','preparation','shop','supply_selection')
                or feedback.get('node')!=destination
                or any(type(action.get('id')) is not int or action.get('id')!=index or action.get('status')!='verified'
                    or type(action.get('input_epoch')) is not int or action['input_epoch']<0
                    or not isinstance(action.get('before'),str) or not action['before']
                    or not isinstance(action.get('after'),str) or not action['after'] for index,action in ((start,a),(end,b)))
                or a.get('action')!='start_standard_node' or a.get('expected')!='standard_node_entered'
                or not isinstance(a.get('target'),list) or len(a['target'])!=4 or a['target'][0]!=entry['node']
                or any(type(value) is not int for value in a['target'][1:])
                or b.get('action')!='continue_standard_node' or b.get('expected')!='standard_node_advanced'
                or not isinstance(b.get('target'),list) or len(b['target'])!=2 or type(b['target'][1]) is not int
                or b.get('target')!=[entry['node'],start]):raise ValueError()
        return end,destination
    except (KeyError,TypeError,IndexError,ValueError,AttributeError) as exc:
        raise AutomationError('节点继续缺少原出战、胜利或已核实到达来源，未刷新步骤额度。') from exc


class StandardBudget:
    def __init__(self,session):
        self.start=len(session['actions'])

    def window(self,session):
        actions=session['actions'];end,destination=_continued(session)
        anchor=max(self.start,end+1);kind='continue_standard_node' if end>=self.start else 'invocation_start'
        if kind=='invocation_start':destination=None
        # Supply delivery can advance another node after continue opened the
        # selection page. Only its completed native effect may advance the bound.
        for action in reversed(actions[anchor:]):
            if action.get('action') not in ('choose_standard_reward','confirm_standard_supply') or action.get('reward_verified') is not True:continue
            effect=action.get('reward_effect',{})
            if not isinstance(effect,dict):raise AutomationError('补给回执结构损坏，未刷新执行上限。')
            source,target=effect.get('node'),effect.get('node_after')
            if source==target:continue
            from .currency_wars_standard_rewards import valid_effect
            if (not node(source) or not node(target) or effect.get('page')!='supply_selection'
                    or target!=source.split('-')[0]+'-'+str(int(source.split('-')[1])+1)
                    or type(action.get('id')) is not int or not 0<=action['id']<len(actions)
                    or actions[action['id']]!=action or not valid_effect(action,actions)):
                raise AutomationError('补给跨节点步骤没有实际交付回执，未刷新执行上限。')
            anchor=action['id']+1;destination=target;kind='verified_supply_delivery';break
        if anchor>len(actions) or self.start>len(actions):
            raise AutomationError('本局动作记录被缩短，未重置执行上限。')
        return dict(invocation_start=self.start,phase_start=anchor,phase_node=destination,boundary_kind=kind,
                    phase_actions=len(actions)-anchor,total_actions=len(actions),phase_limit=PHASE_ACTIONS,total_limit=MAX_ACTIONS)

    def check(self,session):
        window=self.window(session);session['execution_window']=window
        if window['total_actions']>=MAX_ACTIONS:
            return '本局已达到4096条动作记录上限，已停止；原始记录、资源和完成状态保留。'
        if window['phase_actions']>=PHASE_ACTIONS:
            return '当前节点阶段已达到512条动作上限，已停止；仅已核实跨节点推进可刷新本次阶段额度。'
        return None
