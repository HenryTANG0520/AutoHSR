"""Observed in-game redemption with durable per-account submission receipts."""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import time

from .config import ROOT
from .models import AutomationError, EmptyCapture, FocusLost, InputInterrupted, Stopped, TaskResult
from .storage import replace_file

TASK = 'redemption'
TERMINAL = frozenset(('redeemed', 'already_used', 'expired', 'invalid'))


@dataclass(frozen=True)
class RedemptionAction:
    intent: str
    target: object = None
    text: str = ''
    key: str = ''


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


class RedemptionWorkflow:
    def __init__(self, context, *, batch=None, store=None):
        self.c = context
        from .redemption_settings import resolve_batch
        from .redemption_store import RedemptionStore
        self.batch = batch or resolve_batch(context.settings, cancel=context.checkpoint)
        self.store = store or RedemptionStore(ROOT / 'runs/redemption-ledger.json')
        self.epoch = context.runner.input_epoch
        self.account = None
        self.code = None
        self.entry = None
        self.request = None
        self.echo = []
        self.path = Path(context.report.run_dir) / 'redemption-session.json'
        if self.path.exists() or context.report.redemption:
            raise AutomationError('本次运行已有兑换记录，未覆盖或重启整批。')
        self.data = dict(schema=1, status='running', server=self.batch.server,
            source=deepcopy(self.batch.source), codes=list(self.batch.codes), skipped=list(self.batch.skipped),
            batch_digest=hashlib.sha256(_json([self.batch.server, self.batch.codes, self.batch.source]).encode()).hexdigest(),
            input_epoch=self.epoch, actions=[], results=[], mail='not_requested')
        context.report.redemption = self.data
        context.redemption_workflow = self
        self._persist()

    def _persist(self):
        # Aggregate only independently confirmed outcomes. A later close,
        # another code, or a stop must not erase an already saved success.
        self.data['submitted'] = sum(not row['reused'] for row in self.data['results'])
        self.data['redeemed'] = sum(row['status'] == 'redeemed' and not row['reused'] for row in self.data['results'])
        self.data['reused'] = sum(row['reused'] for row in self.data['results'])
        raw = _json(self.data).encode('utf-8')
        if len(raw) > 16 * 1024 * 1024:
            raise AutomationError('兑换记录达到16 MiB上限，原记录保留。')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_bytes(raw)
        replace_file(temporary, self.path)

    def _fresh(self, scene, *, account=True):
        c = self.c
        c.checkpoint()
        if c.runner.input_epoch != self.epoch or c.scene_epoch != self.epoch:
            raise InputInterrupted('兑换流程输入代次已改变，旧目标与当前提交保留待核对。')
        if (scene is not c.last_scene or type(scene.captured_at) not in (int, float)
                or not 0 <= time.monotonic() - scene.captured_at <= 8 or scene.image is None
                or scene.geometry is None):
            raise AutomationError('兑换流程需要当前新鲜的游戏画面。')
        if account:
            from .currency_wars_identity import account_key
            observed = account_key(scene, max(.85, c.settings.ocr_confidence))
            if observed != self.account:
                raise AutomationError('兑换账号已改变，未发送或重放兑换码。')

    def _snapshot(self):
        scene = self.c.snapshot()
        self._fresh(scene, account=self.account is not None)
        return scene

    def _evidence(self, scene, label):
        return str(self.c.evidence(scene, 'redemption_' + label))

    def _bind_account(self):
        from .currency_wars_identity import account_key
        frames = []
        for _ in range(24):
            scene = self._snapshot()
            observed = account_key(scene, max(.85, self.c.settings.ocr_confidence))
            if self.account is not None and observed != self.account:
                raise AutomationError('兑换前的两帧账号不一致。')
            self.account = observed
            if frames and scene.captured_at <= frames[-1]['captured_at']:
                self.c.sleep(.15)
                continue
            frames.append(dict(captured_at=scene.captured_at, evidence=self._evidence(scene, 'account_' + str(len(frames)+1))))
            if len(frames) == 2:
                break
        else:
            raise AutomationError('兑换前未取得两份独立账号画面，未输入。')
        self.data.update(account_key=self.account, account_frames=frames)
        self._persist()
        return scene

    def _form(self, scene):
        from .redemption_pages import read_form
        return read_form(scene, self.c.settings.ocr_confidence)

    def _result(self, scene):
        from .redemption_pages import read_result
        result = read_result(scene, self.c.settings.ocr_confidence)
        return result if result is not None and result.status in TERMINAL else None

    def _derive(self, scene, intent):
        from .redemption_pages import phone_more_target, redemption_entry
        confidence = self.c.settings.ocr_confidence
        if intent == 'open_more':
            target = phone_more_target(scene, confidence)
        elif intent == 'open_form':
            target = redemption_entry(scene, confidence)
        elif intent in ('focus_code', 'type_code', 'submit_code'):
            form = self._form(scene)
            if form is None or self._result(scene) is not None:
                raise AutomationError('兑换表单或当前输入区域尚未核实。')
            target = form.confirm_target if intent == 'submit_code' else form.input_target
            if intent == 'submit_code' and (form.current_code != self.code or len(self.echo) != 2):
                raise AutomationError('当前完整兑换码尚未两帧读回，未点击确认。')
            if intent == 'type_code':
                actions = self.data['actions']
                previous = actions[-2] if actions and actions[-1]['status'] == 'pending' else actions[-1] if actions else {}
                if previous.get('intent') != 'focus_code' or previous.get('status') != 'verified':
                    raise AutomationError('兑换码输入前尚未核实本次输入框点击。')
                return RedemptionAction(intent, target, text=self.code)
        elif intent == 'close_result':
            result = self._result(scene)
            if not result or result.status not in TERMINAL or not self.entry:
                raise AutomationError('当前兑换结果未核实，未关闭通用提示。')
            settled = self.store.lookup(self.account, self.batch.server, self.code)
            if not settled or settled['id'] != self.entry['id'] or settled['status'] != result.status:
                raise AutomationError('当前兑换结果与已保存回执不符。')
            target = result.close_target
            if target is None and getattr(result, 'key', '') == 'esc':
                return RedemptionAction(intent, key='esc')
        elif intent == 'return_phone':
            if self._form(scene) is None:
                raise AutomationError('返回前未核实兑换表单，未发送Esc。')
            return RedemptionAction(intent, key='esc')
        else:
            raise AutomationError('未知兑换动作。')
        if target is None:
            raise AutomationError('兑换页面没有唯一可用的当前目标。')
        return RedemptionAction(intent, target)

    def authorize(self, scene, action):
        self._fresh(scene)
        if self.request != action or self._derive(scene, action.intent) != action:
            raise AutomationError('兑换动作与当前页面或本次意图不同。')
        if self.path.stat().st_size > 16 * 1024 * 1024:
            raise AutomationError('兑换记录大小异常，未输入。')
        from .currency_wars_state import strict_json
        stored = strict_json(self.path.read_text(encoding='utf-8'))
        if _json(stored) != _json(self.data) or not stored.get('actions') or stored['actions'][-1]['status'] != 'pending':
            raise AutomationError('兑换意图尚未完整落盘，未输入。')
        if action.intent == 'submit_code':
            if self.entry is None:
                raise AutomationError('兑换确认缺少本次待核对收据。')
            entry = self.store.require_pending(self.entry['id'], self.account, self.batch.server, self.code, self.epoch)
            if (entry != self.entry or Path(entry['run_dir']).resolve() != Path(self.c.report.run_dir).resolve()
                    or entry['claim']['basis'].get('action_id') != self.data['actions'][-1]['id']):
                raise AutomationError('本次兑换确认与落盘收据不一致。')
            reference = entry['claim']['evidence']
            if (list(scene.image.shape) != reference['shape'] or
                    hashlib.sha256(str(tuple(scene.image.shape)).encode('ascii') + scene.image[:, :, ::-1].tobytes()).hexdigest()
                    != reference['pixel_sha256'] or
                    entry['claim']['basis'].get('form_digest') != self._form(scene).source_digest):
                raise AutomationError('本次兑换提交证据与当前表单像素或字段来源不符。')

    def _act(self, scene, intent, *, before=None):
        self._fresh(scene)
        action = self._derive(scene, intent)
        record = dict(id=len(self.data['actions']), intent=intent, status='pending', code=self.code,
            input_epoch=self.epoch, before=before or self._evidence(scene, 'before_' + intent),
            target=list(action.target.box) if action.target else None, text=action.text, key=action.key)
        self.data['actions'].append(record)
        self.request = action
        self._persist()
        self.c.redemption_input(scene, action)
        return record

    def _wait(self, read, description, *, two=False):
        frames, values, previous = [], [], None
        elapsed = 0.
        while elapsed < 30:
            started, inactive = time.monotonic(), self.c.runner.inactive_duration
            try:
                scene = self._snapshot()
            except EmptyCapture:
                scene = None
            value = read(scene) if scene is not None else None
            stamp = getattr(value, 'status', value) if value else None
            if value:
                if frames and stamp != previous:
                    frames, values = [], []
                if not frames or scene.captured_at > frames[-1]['scene'].captured_at:
                    frames.append(dict(scene=scene, captured_at=scene.captured_at,
                        evidence=self._evidence(scene, description + '_' + str(len(frames)+1))))
                    values.append(value)
                previous = stamp
                if len(frames) >= (2 if two else 1):
                    return frames, values
            else:
                frames, values, previous = [], [], None
            self.c.sleep(.25)
            elapsed += max(0., time.monotonic() - started - (self.c.runner.inactive_duration - inactive))
        raise AutomationError('兑换反馈超时：' + description + '；未重复输入。')

    def _verified(self, record, frames):
        record.update(status='verified', after=frames[-1]['evidence'])
        self.request = None
        self._persist()
        return frames[-1]['scene']

    def _ensure_form(self):
        from .free_rewards import phone
        from .redemption_pages import redemption_entry
        scene = self._snapshot()
        if self._result(scene) is not None:
            raise AutomationError('已有兑换结果未归属本次提交，未借用旧提示。')
        if self._form(scene) is not None:
            return scene
        if redemption_entry(scene, self.c.settings.ocr_confidence) is None and phone(scene):
            action = self._act(scene, 'open_more')
            frames, _ = self._wait(lambda s: redemption_entry(s, self.c.settings.ocr_confidence), 'more_open')
            scene = self._verified(action, frames)
        action = self._act(scene, 'open_form')
        frames, _ = self._wait(self._form, 'form_open')
        return self._verified(action, frames)

    def _redeem_one(self, code):
        self.code, self.entry, self.echo = code, None, []
        old = self.store.lookup(self.account, self.batch.server, code)
        if old is not None:
            if old['status'] not in TERMINAL:
                raise AutomationError('该账号已有未核实兑换提交，未重放或覆盖。')
            self.data['results'].append(dict(code=code, status=old['status'], reused=True))
            self._persist()
            return
        scene = self._ensure_form()
        if self._form(scene).current_code != code:
            action = self._act(scene, 'focus_code')
            frames, _ = self._wait(self._form, 'input_focus')
            scene = self._verified(action, frames)
            action = self._act(scene, 'type_code')
            frames, _ = self._wait(lambda s: bool((f := self._form(s)) and f.current_code == code), 'code_echo', two=True)
            scene = self._verified(action, frames)
        else:
            frames, _ = self._wait(lambda s: bool((f := self._form(s)) and f.current_code == code), 'code_echo', two=True)
            scene = frames[-1]['scene']
        self.echo = [dict(captured_at=f['captured_at'], evidence=f['evidence']) for f in frames]
        self.data['current_echo'] = deepcopy(self.echo)
        before = self._evidence(scene, 'before_submit')
        basis = dict(action_id=len(self.data['actions']), batch_digest=self.data['batch_digest'],
                     form_digest=self._form(scene).source_digest, echo=deepcopy(self.echo))
        self.entry = self.store.claim(self.account, self.batch.server, code, run_dir=self.c.report.run_dir,
            epoch=self.epoch, evidence=before, basis=basis)
        self.data['pending_entry_id'] = self.entry['id']
        action = self._act(scene, 'submit_code', before=before)
        frames, results = self._wait(lambda s: r if (r := self._result(s)) and r.status in TERMINAL else None,
                                     'result', two=True)
        outcome = results[-1].status
        self.entry = self.store.finish(self.entry['id'], outcome, evidence=[f['evidence'] for f in frames],
            basis=dict(input_epoch=self.epoch, captures=[f['captured_at'] for f in frames],
                       action_id=action['id'], batch_digest=self.data['batch_digest']))
        self.data['results'].append(dict(code=code, status=outcome, reused=False, entry_id=self.entry['id']))
        self.data.pop('pending_entry_id', None)
        scene = self._verified(action, frames)
        from .free_rewards import phone
        action = self._act(scene, 'close_result')
        frames, _ = self._wait(lambda s: phone(s) or self._form(s), 'result_closed')
        scene = self._verified(action, frames)
        if not phone(scene):
            action = self._act(scene, 'return_phone')
            frames, _ = self._wait(phone, 'phone_returned')
            self._verified(action, frames)

    def run(self):
        from .workflows import DailyWorkflow
        try:
            if self.batch.codes:
                from .redemption_pages import phone, redemption_entry
                initial = self._snapshot()
                if self._result(initial) is not None:
                    raise AutomationError('当前已有未归属本批次的兑换结果，未借用或关闭。')
                if (self._form(initial) is None and not phone(initial, self.c.settings.ocr_confidence)
                        and redemption_entry(initial, self.c.settings.ocr_confidence) is None):
                    DailyWorkflow(self.c).ensure_main()
                self._bind_account()
            for code in self.batch.codes:
                self.c.checkpoint()
                self._redeem_one(code)
            successes = sum(r['status'] == 'redeemed' and not r['reused'] for r in self.data['results'])
            if successes and self.c.settings.redemption_claim_mail:
                if self.c.report.operation == 'daily' and self.c.settings.mail:
                    self.data['mail'] = 'deferred_to_daily_mail'
                else:
                    result = DailyWorkflow(self.c).mail()
                    self.data['mail'] = dict(status=result.status, detail=result.detail)
                    if result.status != 'ok':
                        self.data['status'] = 'partial'
                        self._persist()
                        return TaskResult(TASK, 'partial', '兑换结果已保存，邮件附件尚未完整核实。')
            self.data.update(status='completed', submitted=sum(not r['reused'] for r in self.data['results']), redeemed=successes)
            self._persist()
            return TaskResult(TASK, 'ok', f'兑换批次已处理：新提交{self.data["submitted"]}个，成功{successes}个；逐码结果已保存。')
        except (AutomationError, OSError, ValueError) as error:
            self.data.update(status='stopped' if isinstance(error, Stopped) else 'partial', error=str(error))
            if self.data['actions'] and self.data['actions'][-1]['status'] == 'pending':
                self.data['actions'][-1]['status'] = 'unknown'
            self._persist()
            raise


def run_redemption(context, *, batch=None, store=None):
    return RedemptionWorkflow(context, batch=batch, store=store).run()
