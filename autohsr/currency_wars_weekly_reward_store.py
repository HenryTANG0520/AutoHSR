"""Durable intents and original evidence for a bounded weekly reward attempt."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import math
from pathlib import Path
import uuid

from .currency_wars_loop_store import _hex, _immutable, _read, _write
from .currency_wars_points_run import _hash
from .currency_wars_points import game_week, local_now
from .models import AutomationError


class RewardStore:
    def __init__(self,root):
        self.root=Path(root).resolve();self.pointer=self.root/'currency-weekly-rewards-current.json'
        self.path=None;self.data=None

    def inside(self,value):
        path=Path(value).resolve()
        if not path.is_relative_to(self.root) or path==self.root:
            raise AutomationError('积分领奖证据不在运行目录内。')
        return path

    @staticmethod
    def validate(data):
        if (type(data) is not dict or type(data.get('schema')) is not int or data['schema']!=1
                or not _hex(data.get('id')) or not _hex(data.get('account_key'),64)
                or data.get('mode')!='weekly_rewards' or data.get('status') not in ('active','complete')
                or data.get('phase') not in ('lobby','panel','overlay','panel_after_claim','panel_settled','returned','blocked')
                or type(data.get('actions')) is not list or len(data['actions'])>(5 if 'limit_recovery' in data else 4)
                or type(data.get('current')) is not int or not 0<=data['current']<=18000
                or data.get('completion_verified') is not False
                or data.get('match_started') is not False
                or type(data.get('confidence')) not in (int,float) or not math.isfinite(data['confidence']) or not .85<=data['confidence']<=.99
                or any(type(data.get(k)) is not bool for k in ('rewards_verified','weekly_rewards_verified','claimed_now'))):
            raise AutomationError('积分领奖记录结构无效。')
        if game_week(datetime.fromisoformat(data['observed_at']))!=data['game_week']:
            raise AutomationError('积分领奖记录游戏周不符。')
        initial=data.get('initial',{})
        if (initial.get('account_key')!=data['account_key'] or initial.get('game_week')!=data['game_week']
                or initial.get('observed_at')!=data['observed_at'] or initial.get('current')!=data['current']
                or initial.get('period',{}).get('verified') is not True):
            raise AutomationError('积分领奖缺少同账号、同周与原积分来源。')
        if data['weekly_rewards_verified'] is not (data['rewards_verified'] and data['current']==18000):
            raise AutomationError('积分领奖周完成字段不符。')
        if data['status']=='complete' and (data['phase']!='returned' or data['rewards_verified'] is not True):
            raise AutomationError('积分领奖完成记录缺少返回核实。')
        owner=data.get('weekly_owner')
        if owner is not None and (type(owner) is not dict or set(owner)!={'loop_id','account','week'}
                or not _hex(owner['loop_id']) or owner['account']!=data['account_key'] or owner['week']!=data['game_week']):
            raise AutomationError('积分领奖周常归属无效。')
        for index,action in enumerate(data['actions']):
            if (type(action) is not dict or type(action.get('id')) is not int or action['id']!=index or type(action.get('epoch')) is not int
                    or action.get('status') not in ('pending','unknown','verified')
                    or action.get('intent') not in ('open_points_rewards','claim_weekly_rewards','dismiss_weekly_rewards','return_weekly_lobby')
                    or index<len(data['actions'])-1 and action['status']!='verified'):
                raise AutomationError('积分领奖动作记录无效。')
        if 'limit_recovery' in data:
            recovery=data['limit_recovery']
            if (type(recovery) is not dict or set(recovery)!={'blocked_id','panel_state','run_dir','epoch','sources'}
                    or type(recovery['blocked_id']) is not int or recovery['blocked_id']!=1
                    or recovery['panel_state'] not in ('available','settled')
                    or type(recovery['epoch']) is not int or recovery['epoch']<0
                    or not isinstance(recovery['run_dir'],str) or recovery['run_dir'] not in data['continuations']
                    or type(recovery['sources']) is not list or len(recovery['sources'])!=2):
                raise AutomationError('助燃券满额后的面板恢复记录无效。')

    def load(self):
        if not self.pointer.exists():return None
        pointer=_read(self.pointer)
        if type(pointer) is not dict or set(pointer)!={'id'} or not _hex(pointer['id']):
            raise AutomationError('积分领奖入口记录无效。')
        self.path=self.root/'currency-weekly-rewards'/pointer['id']/'session.json'
        self.data=_read(self.path);self.validate(self.data)
        if self.data['id']!=pointer['id']:raise AutomationError('积分领奖入口与原件不符。')
        return self.data

    def preflight(self,resume=False):
        data=self.load()
        if type(resume) is not bool:raise ValueError('积分领奖接续开关须为布尔值。')
        receipt=self.path.parent/'receipt.json' if data is not None else None
        if data is not None and (data['status']=='active' or not receipt.exists()):
            if not resume:raise AutomationError('已有未完成积分领奖记录；未导航或再次领取，请明确接续。')
            if any(a['status']!='verified' for a in data['actions']):
                raise AutomationError('上次积分领奖输入尚未核实，未重放；保留原报告和证据。')
            self.check_evidence()
            if data['phase']!='returned' and game_week(local_now())!=data['game_week']:
                raise AutomationError('未完成积分领奖已跨游戏周，未导航或重置原目标。')
        elif data is not None:
            self.check_receipt()
            if resume:raise AutomationError('积分领奖已完整提交；没有待接续记录。')
        elif resume:raise AutomationError('没有可接续的未完成积分领奖记录。')
        return data

    def _require_saved(self,expected):
        if _read(self.path)!=expected:
            raise AutomationError('积分领奖已落盘的原记录改变，保留现场。')

    def save(self,*,expected=None):
        if expected is None:
            self.validate(self.data);_write(self.path,self.data)
            return
        try:
            self.validate(self.data)
            _write(self.path,self.data,before_replace=lambda:self._require_saved(expected))
        except BaseException:
            self.data=expected
            raise

    def begin(self,observation,client,run_dir,*,weekly_owner=None):
        self.preflight()
        identity=uuid.uuid4().hex
        self.path=self.root/'currency-weekly-rewards'/identity/'session.json'
        self.data=dict(schema=1,id=identity,mode='weekly_rewards',status='active',phase='lobby',actions=[],
            account_key=observation['account_key'],game_week=observation['game_week'],observed_at=observation['observed_at'],
            current=observation['current'],client=client,run_dir=str(self.inside(run_dir)),continuations=[],
            confidence=observation['confidence'],
            initial=observation,rewards_verified=False,weekly_rewards_verified=False,claimed_now=False,completion_verified=False,match_started=False)
        if weekly_owner is not None:self.data['weekly_owner']=deepcopy(weekly_owner)
        self.save();_write(self.pointer,dict(id=identity))

    def pending(self,choice,epoch,evidence,*,recovery_panel=None):
        if any(a['status']!='verified' for a in self.data['actions']):
            raise AutomationError('积分领奖上一步尚未核实，未提交后续输入。')
        maximum=5 if 'limit_recovery' in self.data else 4
        if len(self.data['actions'])>=maximum:raise AutomationError('积分领奖动作达到上限，未重复领取。')
        action=dict(id=len(self.data['actions']),intent=choice.intent,expected=choice.expected,
            phase=self.data['phase'],epoch=epoch,status='pending',before=evidence,
            target=None if choice.target is None else dict(text=choice.target.text,box=list(choice.target.box),score=choice.target.score),key=choice.key)
        original=deepcopy(self.data) if 'limit_recovery' in self.data else None
        if original is not None and choice.intent=='claim_weekly_rewards':
            action['recovery_panel']=dict(run_dir=self.data['continuations'][-1],sources=deepcopy(recovery_panel))
            self._check_retry_panel(action)
        self.data['actions'].append(action)
        self.save(expected=original)

    def require_pending(self,choice,epoch):
        saved=_read(self.path);self.validate(saved)
        if saved!=self.data or not saved['actions']:raise AutomationError('积分领奖意图未完整落盘或已改变。')
        action=saved['actions'][-1]
        target=None if choice.target is None else dict(text=choice.target.text,box=list(choice.target.box),score=choice.target.score)
        if (action['status']!='pending' or action['intent']!=choice.intent or action['epoch']!=epoch
                or action['expected']!=choice.expected or action['target']!=target or action['key']!=choice.key):
            raise AutomationError('积分领奖意图、目标或输入代次不符。')
        self.check_source(action['before'])
        if action['id']==2 and choice.intent=='claim_weekly_rewards':
            self._check_limit_recovery()
            self._check_retry_panel(action)
            self._require_saved(saved)

    def can_recover_limit(self):
        actions=self.data['actions']
        return (self.data['phase']=='blocked' and 'limit_recovery' not in self.data
                and len(actions)==2 and actions[1]['intent']=='claim_weekly_rewards'
                and actions[1]['status']=='verified' and actions[1].get('result')=='fuel_ticket_limit')

    def recover_limit(self,sources,run_dir,epoch,*,before_replace,after_verify):
        if not self.can_recover_limit() or not self.data['continuations'] or self.data['continuations'][-1]!=str(run_dir):
            raise AutomationError('仅可在明确接续首次满额时核对恢复面板。')
        original=self.data
        recovered=deepcopy(original)
        state=sources[-1]['panel_state']
        recovered['limit_recovery']=dict(blocked_id=1,panel_state=state,run_dir=str(run_dir),epoch=epoch,
                                         sources=deepcopy(sources))
        recovered['phase']='panel_settled' if state=='settled' else 'panel'
        if state=='settled':recovered['settled_evidence']=deepcopy(sources)
        self.data=recovered
        try:
            self.validate(recovered)

            def recheck():
                self._require_saved(original)
                before_replace()
                self.check_evidence()
                self._require_saved(original)
                after_verify()

            _write(self.path,recovered,before_replace=recheck)
        except BaseException:
            self.data=original
            raise

    def _check_limit_recovery(self):
        recovery=self.data.get('limit_recovery')
        actions=self.data['actions']
        if (recovery is None or len(actions)<2 or actions[1]['intent']!='claim_weekly_rewards'
                or actions[1]['status']!='verified' or actions[1].get('result')!='fuel_ticket_limit'):
            raise AutomationError('助燃券满额恢复缺少原领取拒绝来源。')
        rejected=actions[1]
        self._check_pair(rejected.get('after'),'fuel_ticket_limit',rejected['epoch'])
        self._check_pair(recovery['sources'],'points_rewards',recovery['epoch'],
                         folder=recovery['run_dir'],panel_state=recovery['panel_state'])

    def _check_retry_panel(self,action):
        panel=action.get('recovery_panel')
        if (type(panel) is not dict or panel.get('run_dir') not in self.data['continuations']
                or self.data['limit_recovery']['panel_state']!='available'
                or action['before'].get('panel_state')!='available'
                or not self.inside(action['before']['path']).is_relative_to(self.inside(panel['run_dir']))):
            raise AutomationError('接续领取缺少当前可领取面板。')
        self._check_pair(panel.get('sources'),'points_rewards',action['epoch'],
                         folder=panel['run_dir'],panel_state='available')
        if panel['sources'][1]['captured_at']!=action['before']['captured_at']:
            raise AutomationError('接续领取目标与恢复面板末帧不同。')

    def _check_pair(self,sources,page,epoch,*,folder=None,panel_state=None):
        if (type(sources) is not list or len(sources)!=2 or sources[0]['path']==sources[1]['path']
                or sources[0]['captured_at']>=sources[1]['captured_at']):
            raise AutomationError('助燃券满额恢复须有两份独立画面证据。')
        for source in sources:
            self.check_source(source)
            if (source['page']!=page or source.get('panel_state')!=panel_state or source['input_epoch']!=epoch
                    or folder is not None and not self.inside(source['path']).is_relative_to(self.inside(folder))
                    or game_week(datetime.fromisoformat(source['observed_at']))!=self.data['game_week']):
                raise AutomationError('助燃券满额恢复画面与原账号周目标不符。')

    def verify(self,after,phase,*,result=None):
        action=self.data['actions'][-1]
        if action['status']!='pending':raise AutomationError('积分领奖动作不处于待核实状态。')
        original=deepcopy(self.data) if 'limit_recovery' in self.data else None
        action.update(status='verified',after=after,result=result or action['expected'])
        self.data['phase']=phase
        if action['intent']=='claim_weekly_rewards' and action['result']=='reward_overlay':
            self.data['claimed_now']=True
        if phase=='returned':
            self.data.update(status='complete',rewards_verified=True,weekly_rewards_verified=self.data['current']==18000)
        self.save(expected=original)

    def unknown(self,error):
        if self.data and self.data['actions'] and self.data['actions'][-1]['status']=='pending':
            original=deepcopy(self.data)
            self.data['actions'][-1].update(status='unknown',error=str(error))
            try:self.save(expected=original)
            except (OSError,ValueError,AutomationError):pass

    def check_source(self,source):
        import cv2
        from .models import Scene, Token
        from .currency_wars_points import period_evidence,read_points
        from .currency_wars_weekly_rewards import kind,panel_control,quantities
        path=self.inside(source['path'])
        folders=[self.inside(value) for value in [self.data['run_dir'],*self.data['continuations']]]
        if not any(path.is_relative_to(folder) and path!=folder for folder in folders):
            raise AutomationError('积分领奖证据不属于本次尝试或其原生接续。')
        if not path.is_file() or _hash(path)!=source['sha256']:
            raise AutomationError('积分领奖原始证据缺失或改变。')
        if (type(source.get('confidence')) not in (int,float) or not math.isfinite(source['confidence'])
                or source['confidence']!=self.data['confidence']
                or type(source.get('captured_at')) not in (int,float) or not math.isfinite(source['captured_at'])
                or type(source.get('tokens')) is not list or not 1<=len(source['tokens'])<=48):
            raise AutomationError('积分领奖原始字段或置信度来源无效。')
        image=cv2.imread(str(path))
        if image is None:raise AutomationError('积分领奖证据不是有效图像。')
        scene=Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in source['tokens']],image)
        confidence=source['confidence'];page=kind(scene,confidence)
        if page!=source['page']:raise AutomationError('积分领奖原始文字不能证明所记录页面。')
        if page in ('lobby','points_rewards'):
            points=read_points(scene,confidence)
            if (points.current!=source['current'] or points.limit!=source['limit']
                    or points.current!=self.data['current']):raise AutomationError('积分领奖积分来源不符。')
            if page=='lobby':
                now=datetime.fromisoformat(source['observed_at'])
                if game_week(now)!=self.data['game_week'] or period_evidence(scene,now,confidence)!=source['period']:
                    raise AutomationError('积分领奖原始倒计时来源不符。')
            else:
                try:state=panel_control(scene,confidence)[0]
                except AutomationError:state='unknown'
                if state!=source['panel_state']:raise AutomationError('积分领奖按钮状态与原图或文字不符。')
        if page=='reward_overlay' and quantities(scene,confidence)!=source['quantities']:
            raise AutomationError('积分奖励展示数量与原始字段不符。')

    def check_evidence(self):
        self.check_source(self.data['initial']['evidence'])
        intents=[a['intent'] for a in self.data['actions']]
        routes=[['open_points_rewards','return_weekly_lobby'],
                ['open_points_rewards','claim_weekly_rewards','dismiss_weekly_rewards','return_weekly_lobby']]
        recovery=self.data.get('limit_recovery')
        if recovery is not None:
            self._check_limit_recovery()
            routes=[['open_points_rewards','claim_weekly_rewards','return_weekly_lobby']]
            if recovery['panel_state']=='available':
                routes.append(['open_points_rewards','claim_weekly_rewards','claim_weekly_rewards',
                               'dismiss_weekly_rewards','return_weekly_lobby'])
        if not any(intents==route[:len(intents)] for route in routes):
            raise AutomationError('积分领奖动作不是有界原生顺序。')
        last=self.data['actions'][-1] if intents else None
        if last is None:expected='lobby'
        elif last['status']!='verified':expected=last['phase']
        else:
            expected={'open_points_rewards':'panel','claim_weekly_rewards':'overlay',
                      'dismiss_weekly_rewards':'panel_after_claim','return_weekly_lobby':'returned'}[last['intent']]
            if last['result']=='fuel_ticket_limit':
                expected='blocked'
                if recovery is not None and last['id']==recovery['blocked_id']:
                    expected='panel_settled' if recovery['panel_state']=='settled' else 'panel'
        if self.data['phase']!=expected and not (self.data['phase']=='panel_settled' and expected in ('panel','panel_after_claim')):
            raise AutomationError('积分领奖阶段缺少上一动作的独立来源。')
        delivered=any(a['intent']=='claim_weekly_rewards' and a['status']=='verified' and a['result']=='reward_overlay'
                      for a in self.data['actions'])
        if self.data['claimed_now'] is not delivered:
            raise AutomationError('积分领奖到账字段缺少独立奖励展示来源。')
        for action in self.data['actions']:
            self.check_source(action['before'])
            if action['id']==2 and action['intent']=='claim_weekly_rewards':
                self._check_retry_panel(action)
            if action['status']=='verified':
                if len(action.get('after',[]))!=2 or len({s['path'] for s in action['after']})!=2:
                    raise AutomationError('积分领奖反馈缺少两帧独立核实。')
                if action['after'][0]['captured_at']>=action['after'][1]['captured_at']:
                    raise AutomationError('积分领奖两帧反馈时序不符。')
                if action['result'] not in (action['expected'],'fuel_ticket_limit'):
                    raise AutomationError('积分领奖反馈类型不符。')
                if action['result']=='fuel_ticket_limit' and action['intent']!='claim_weekly_rewards':
                    raise AutomationError('助燃券满额来源不符。')
                if (action['result']=='fuel_ticket_limit' and action is not last
                        and (recovery is None or action['id']!=recovery['blocked_id'])):
                    raise AutomationError('助燃券满额后缺少独立恢复面板。')
                for source in action['after']:
                    self.check_source(source)
                    if source['page']!=action['result']:raise AutomationError('积分领奖反馈页面来源不符。')
        for source in self.data.get('settled_evidence',[]):
            self.check_source(source)
            if source['page']!='points_rewards' or source['panel_state']!='settled':
                raise AutomationError('积分领奖结清来源不能证明不可领取。')
        if self.data['phase']=='panel_settled' and len(self.data.get('settled_evidence',[]))!=2:
            raise AutomationError('积分领奖返回前缺少结清来源。')
        if self.data['phase']=='returned':
            if intents not in routes or any(a['status']!='verified' for a in self.data['actions']):
                raise AutomationError('积分领奖完成缺少原生领取／返回链。')
            if (len(self.data.get('settled_evidence',[]))!=2
                    or any(s['page']!='points_rewards' or s['current']!=self.data['current'] or s['panel_state']!='settled' for s in self.data['settled_evidence'])
                    or self.data['claimed_now'] is not ('dismiss_weekly_rewards' in intents)):
                raise AutomationError('积分领奖缺少不可领取状态或领取来源。')

    def check_receipt(self):
        receipt=_read(self.path.parent/'receipt.json')
        path=self.inside(receipt['report'])
        if (type(receipt.get('schema')) is not int or receipt['schema']!=1 or receipt.get('session')!=self.data
                or receipt.get('session_sha256')!=_hash(self.path) or receipt.get('report_sha256')!=_hash(path)):
            raise AutomationError('积分领奖回执、原报告或会话改变。')
        report=_read(path)
        if (report.get('currency_wars')!=self.data or report.get('status')!='success'
                or report.get('report_saved') is not True or report.get('operation')!='currency_wars_rewards'
                or path.name!='report.json' or self.inside(report['run_dir'])!=path.parent):
            raise AutomationError('积分领奖原报告未成功保存。')
        original=self.inside(receipt['original_report'])
        if (receipt.get('read_only_recovery') is not (path!=original)
                or original!=self.inside((self.data['continuations'] or [self.data['run_dir']])[-1])/'report.json'
                or receipt['original_report_sha256']!=(_hash(original) if original.is_file() else None)):
            raise AutomationError('积分领奖原失败报告或恢复归属改变。')
        self.check_evidence()

    def finalize(self,report):
        from .currency_wars_weekly_rewards import OPERATION
        if (report['operation']!=OPERATION or report['status']!='success' or report['report_saved'] is not True
                or self.data['status']!='complete' or self.data['phase']!='returned' or self.data['rewards_verified'] is not True
                or report['currency_wars']!=self.data or any(a['status']!='verified' for a in self.data['actions'])):
            raise AutomationError('积分领奖尚未完成原报告保存与返回核实。')
        self.check_evidence()
        path=self.inside(report['run_dir'])/'report.json'
        if _read(path)!=report:raise AutomationError('积分领奖原报告与本次记录不符。')
        original=self.inside((self.data['continuations'] or [self.data['run_dir']])[-1])/'report.json'
        receipt=dict(schema=1,session=deepcopy(self.data),session_sha256=_hash(self.path),
                     report=str(path),report_sha256=_hash(path),read_only_recovery=path!=original,
                     original_report=str(original),original_report_sha256=_hash(original) if original.is_file() else None)
        _immutable(self.path.parent/'receipt.json',receipt)
