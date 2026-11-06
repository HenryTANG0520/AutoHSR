"""The real optional DU save chain with durable, non-replayable intentions.

The existing OCR page/empty-slot/name rules are retained. Synthetic mechanism
tests do not establish real archive-page or automatic-name calibration.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
import time
import uuid

from . import du_saves as pages
from .currency_wars_identity import account_key
from .currency_wars_initial import evidence_ref, source_file_ref, _pixels
from .currency_wars_prepare import trusted
from .du_archive_store import ArchiveStore, MAX_BYTES, POLICY, digest, preflight, read, saved_rows_match, start_source
from .models import AutomationError, EmptyCapture, InputInterrupted, Token, normalize


@dataclass(frozen=True)
class ArchiveAction:
    id: int
    intent: str
    target: Token | None = None
    key: str | None = None
    name: str | None = None


def _token(value):
    return None if value is None else dict(text=value.text, score=value.score, box=list(value.box))


def _request(action):
    return dict(id=action.id, intent=action.intent, target=_token(action.target), key=action.key, name=action.name)


def _victory(scene):
    from .differential_universe import classify_page
    return classify_page(scene) == 'victory'


def _list(scene):
    return [dict(text=normalize(t.text), box=list(t.box)) for t in scene.tokens
            if t.within((.01,.14,.18,.65)) and (normalize(t.text) == '暂无存档'
                or re.fullmatch(r'autohsr-\d+', normalize(t.text)))]


class ArchiveWorkflow:
    def __init__(self, flow):
        self.flow, self.c = flow, flow.ctx
        c = self.c
        self.finished = False
        if c.report.operation != 'differential_universe' or c.settings.differential_universe_save is not True:
            raise AutomationError('保存本局只用于明确开启保存的差分演算。')
        self.entry = flow.report['run_results'][-1]
        if self.entry.get('save_attempted',False) is not False:
            raise AutomationError('本局已有保存尝试，旧记录未迁移或重放。')
        if self.entry.get('origin') not in ('fresh','resumed_trial') or (self.entry['origin']=='resumed_trial' and getattr(flow,'resume_active',False) is not True):
            raise AutomationError('保存本局缺少明确新开或接续来源。')
        self.run_dir = str(Path(c.report.run_dir).resolve(strict=True))
        self.epoch, self.window = c.runner.input_epoch, getattr(c.window, 'hwnd', None)
        if type(self.epoch) is not int or self.epoch < 0 or type(self.window) is not int or self.window <= 0:
            raise AutomationError('差分保存缺少本次窗口或输入代次。')
        self.confidence = max(.85, c.settings.ocr_confidence)
        preflight(Path(self.run_dir).parent)
        identity = uuid.uuid4().hex
        self.data = dict(schema=1, operation='du_archive', policy=POLICY, id=identity,
            session_id=flow.session_id, run_id=self.entry.get('run_id'), epoch=self.epoch, window=self.window,
            status='observing', account_key=None, origin_frames=[], observations=[], actions=[], plan=None,
            save_verified=False, skip_verified=False, skip_reason=None, return_verified=False, safe_to_restart=False,
            start_proof=None, legacy_history_reconciled=False, legacy_history_policy='no_scan_or_migration')
        if any(type(self.data.get(key)) is not str or not 1 <= len(self.data[key]) <= 80 for key in ('session_id','run_id')):
            raise AutomationError('差分保存缺少本局运行来源。')
        # Capture the immutable fresh-start source before its normal DU ledger
        # is updated again. A fresh UUID alone never proves another game.
        if self.entry.get('origin') == 'fresh':
            self.data['start_proof'] = self._start_proof(identity)
        self.store = ArchiveStore(self.run_dir, self.data)
        self.request = None
        self.stage = 'origin'
        self._origin_account = None
        c.du_archive_workflow = self
        self.entry['save_attempted'] = True
        self._persist()

    def _start_proof(self, identity):
        ledger = Path(self.run_dir) / 'differential-universe-ledger.json'
        with ledger.open('rb') as stream:raw = stream.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise AutomationError('差分保存新开局来源过大，未继续。')
        current = read(ledger)
        keys = ('run','run_id','origin','status','difficulty_verified','difficulty_rank','difficulty_evidence','started_page','started_evidence')
        frozen = {key:deepcopy(self.entry.get(key)) for key in keys}
        if current.get('session_id') != self.flow.session_id or any(current['run_results'][-1].get(k) != v for k,v in frozen.items()):
            raise AutomationError('差分保存新开局来源尚未落盘。')
        image = source_file_ref(frozen['started_evidence'], self.run_dir)
        source = start_source(current,frozen,self.run_dir)
        folder = Path(self.run_dir) / 'du-archives';folder.mkdir(exist_ok=True)
        copy = folder / (identity + '-start.json')
        import os
        with copy.open('xb') as stream:
            stream.write(raw);stream.flush();os.fsync(stream.fileno())
        return dict(entry=frozen, image=image, source=source,
            ledger=dict(path=str(copy), size=len(raw), sha256=hashlib.sha256(raw).hexdigest()))

    def _persist(self):
        self.store.persist()
        self.entry.update(save_status='saved' if self.data['save_verified'] else 'no_verified_empty_slot'
            if self.data['skip_verified'] else 'unknown' if self.data['status'] == 'unknown'
            else 'abort_before_input' if self.data['status']=='abort_before_input' else 'pending',
            save_name=self.data['plan']['name'] if self.data['plan'] is not None else None,
            save_return_verified=self.data['return_verified'],
            save_receipt=dict(journal=str(self.store.path), digest=self.data['digest'], status=self.data['status']))
        if self.data['save_verified']:
            self.entry['save_evidence'] = self.data['observations'][self.data['saved_frames'][-1]]['evidence']['path']

    def _clean(self, scene):
        return trusted(scene, self.confidence)

    def _fresh(self, scene):
        self.c.checkpoint()
        stamp = getattr(scene, 'captured_at', None)
        if (self.c.report.operation != 'differential_universe' or self.c.settings.differential_universe_save is not True
                or self.c.runner.input_epoch != self.epoch or self.c.scene_epoch != self.epoch
                or str(Path(self.c.report.run_dir).resolve()) != self.run_dir or getattr(self.c.window, 'hwnd', None) != self.window
                or self.flow.session_id != self.data['session_id'] or self.flow.report['run_results'][-1] is not self.entry
                or self.entry.get('run_id') != self.data['run_id'] or scene is not self.c.last_scene
                or type(stamp) not in (int,float) or not math.isfinite(stamp) or not 0 <= time.monotonic()-stamp <= 8
                or max(.85,self.c.settings.ocr_confidence) != self.confidence):
            raise InputInterrupted('差分保存来源、代次或当前画面改变，旧动作不重发。')
        frozen = self.data['account_key'] or self._origin_account
        clean = self._clean(scene)
        visible = [t for t in scene.tokens if t.within((0,.94,.35,1))
                   and (normalize(t.text).startswith(('uid','ui')) or re.fullmatch(r'\d{8,10}',normalize(t.text)))]
        if frozen is not None and visible:
            if (len(visible)!=1 or visible[0].score < self.confidence
                    or not re.fullmatch(r'uid\d{8,10}',normalize(visible[0].text))
                    or account_key(clean,self.confidence) != frozen):
                raise AutomationError('差分保存可见账号不可完整核实或改变，原意图保留。')

    def _facts(self, scene, stage):
        page = self._clean(scene)
        if stage in ('origin','returned'):
            if not _victory(page) or not _victory(scene):return None
            if stage == 'origin':
                try:current = account_key(page,self.confidence)
                except AutomationError:return None
                if self._origin_account is not None and current != self._origin_account:
                    raise AutomationError('差分保存起点两帧账号改变。')
                self._origin_account = current
                if page.has('本局已存档'):raise AutomationError('本局已有存档标记，未猜测原保存或重复提交。')
                return dict(account_key=current, already_saved=False)
            return dict(victory=True, saved_marker=page.has('本局已存档'))
        if stage in ('management','empty','saved'):
            if not pages.management(page) or pages.rename_dialog(page):return None
            rows = _list(page)
            slot = pages.empty_slot(page)
            facts = dict(rows=rows, slot=_token(slot), next_name=pages.next_name(page))
            if stage == 'management':return facts
            plan = self.data['plan']
            if stage == 'empty':
                if (rows != self.data['observations'][plan['before_frames'][-1]]['facts']['rows']
                        or not page.has('暂无存档',(.35,.45,.8,.60),exact=True)
                        or page.find('保存本轮数据',(.46,.62,.70,.74),exact=True) is None):return None
                return dict(name=plan['name'], rows=rows, empty_details=True)
            name = plan['name']
            labels = [t for t in page.tokens if t.within((.01,.14,.18,.65)) and normalize(t.text) == normalize(name)]
            details = [t for t in page.tokens if t.within((.21,.09,.60,.15)) and normalize(t.text) == normalize(name)]
            old = self.data['observations'][plan['before_frames'][-1]]['facts']['rows']
            before_names = Counter(row['text'] for row in old if row['text'] != '暂无存档')
            after_names = Counter(row['text'] for row in rows if row['text'] != '暂无存档')
            before_empty = sum(row['text'] == '暂无存档' for row in old)
            after_empty = sum(row['text'] == '暂无存档' for row in rows)
            if (len(labels) != 1 or len(details) != 1 or after_names != before_names + Counter([normalize(name)])
                    or after_empty != before_empty-1 or not saved_rows_match(old,rows,plan['slot'],name)):return None
            return dict(name=name, rows=rows, list_box=list(labels[0].box), detail_box=list(details[0].box))
        if stage in ('rename','named'):
            if not pages.rename_dialog(page):return None
            if stage == 'rename':return dict(rename=True)
            name = self.data['plan']['name']
            fields = [t for t in page.tokens if t.within((.30,.46,.70,.51)) and normalize(t.text) == normalize(name)]
            return dict(name=name, field_box=list(fields[0].box)) if len(fields) == 1 else None
        return None

    def _source(self, scene, stage, facts):
        self._fresh(scene)
        path = self.c.evidence(scene, 'du_archive_' + self.data['id'][:8] + '_' + str(len(self.data['observations'])))
        reference = evidence_ref(scene, path, self.run_dir)
        self._fresh(scene)
        item = dict(id=len(self.data['observations']), stage=stage, facts=deepcopy(facts),
            epoch=self.epoch, window=self.window, captured_at=scene.captured_at, evidence=reference,
            tokens_digest=digest([_token(t) for t in self._clean(scene).tokens]))
        self.data['observations'].append(item)
        return item['id']

    def _wait(self, stage, *, initial=None, after=0):
        started = time.monotonic();inactive = self.c.runner.inactive_duration
        frames, signature, last = [], None, after
        for index in range(60):
            self.c.checkpoint()
            if time.monotonic()-started-(self.c.runner.inactive_duration-inactive) >= 20:break
            try:scene = initial if index == 0 and initial is not None else self.c.snapshot()
            except EmptyCapture:scene = None
            if scene is not None:
                self._fresh(scene)
                facts = self._facts(scene, stage)
                if facts is not None:
                    current = digest(facts)
                    if current != signature:frames = []
                    signature = current
                    if scene.captured_at > last:
                        source = self._source(scene, stage, facts)
                        if any(self.data['observations'][i]['evidence']['path'] == self.data['observations'][source]['evidence']['path'] for i in frames):
                            raise AutomationError('差分保存两帧不能复用同一PNG。')
                        frames.append(source);last = scene.captured_at;self._persist()
                        if time.monotonic()-started-(self.c.runner.inactive_duration-inactive) >= 20:
                            raise AutomationError('差分保存来源持久化超时。')
                        if len(frames) == 2:self.stage = stage;return scene, frames
                    else:frames = [];signature = None
                else:frames = [];signature = None
            else:frames = [];signature = None
            self.c.sleep(.15)
        raise AutomationError('差分保存未取得两份对应的新鲜反馈，原意图不重发。')

    def authorize(self, scene, action):
        self._fresh(scene);self.store.require_durable()
        if type(action) is not ArchiveAction or self.request != action or action.id != len(self.data['actions'])-1:
            raise AutomationError('差分保存动作不是本次待提交意图。')
        row = self.data['actions'][action.id]
        if row['status'] != 'pending' or row['request'] != _request(action):
            raise AutomationError('差分保存动作或目标与落盘意图不符。')
        before = self.data['observations'][row['before']]
        if (before['captured_at'] != scene.captured_at or before['tokens_digest'] != digest([_token(t) for t in self._clean(scene).tokens])
                or before['evidence']['pixel_sha256'] != _pixels(scene.image)
                or source_file_ref(before['evidence']['path'],self.run_dir) != before['evidence']):
            raise AutomationError('差分保存当前来源与原PNG或字段不同。')
        if sum(value is not None for value in (action.target,action.key,action.name)) != 1:
            raise AutomationError('差分保存只允许一个明确输入。')
        page = self._clean(scene);plan = self.data['plan']
        if action.name is not None:
            if action.intent != 'du_save_name' or plan is None or action.name != plan['name']:
                raise AutomationError('差分保存名称不是本次冻结名称。')
            pages.guard_name(page, action.name)
        elif action.key is not None:
            if (action.intent != 'du_save_close' or action.key != 'esc' or not pages.management(page)
                    or not (self.data['save_verified'] ^ self.data['skip_verified'])):
                raise AutomationError('差分保存尚未核实，不允许关闭或通用按键。')
        else:
            pages.guard_save_click(page, action.target, action.intent)
            if action.intent == 'du_save_slot' and (plan is None or _token(action.target) != plan['slot']):
                raise AutomationError('差分保存空槽不是本次冻结目标。')
            if action.intent == 'du_save_confirm' and self._facts(scene,'named') is None:
                raise AutomationError('差分保存确认前没有完整回读确切冻结名称。')

    def require_current_input(self, scene, action):
        self._fresh(scene)
        if self.request is not action or self.data['actions'][action.id]['status'] != 'pending':
            raise AutomationError('差分保存最后核验的动作已变化。')

    def mark_not_sent(self, action):
        if self.request is action and self.data['actions'][action.id]['status'] == 'pending':
            self.data['actions'][action.id]['status'] = 'not_sent'

    def _step(self, scene, intent, stage, *, target=None, key=None, name=None):
        facts = self._facts(scene,self.stage)
        if facts is None:raise AutomationError('差分保存提交前页面来源不完整。')
        before = self._source(scene,self.stage,facts)
        action = ArchiveAction(len(self.data['actions']),intent,target,key,name)
        row = dict(id=action.id, request=_request(action), status='pending', before=before, after=[])
        self.data['actions'].append(row);self.request = action;self._persist()
        self.c.differential_universe_archive_input(scene,action)
        row['status'] = 'submitted';self._persist()
        after,frames = self._wait(stage,after=scene.captured_at)
        row.update(status='verified',after=frames);self.request = None;self._persist()
        return after,frames

    def run(self, scene):
        try:
            scene,frames = self._wait('origin',initial=scene)
            self.data.update(account_key=self._origin_account,origin_frames=frames,status='active');self._persist()
            target = self._clean(scene).find('记录本次存档',(.50,.85,.75,.97),exact=True)
            if target is None:raise AutomationError('本次胜利页未核实记录存档按钮。')
            scene,frames = self._step(scene,'du_save_open','management',target=target)
            facts = self.data['observations'][frames[-1]]['facts']
            if facts['slot'] is None:
                # No empty label is not evidence that all slots are occupied.
                # Abandon saving without selecting a slot; verify closing separately.
                self.data.update(skip_verified=True, skip_reason='no_verified_empty_slot');self._persist()
            else:
                name = facts['next_name']
                if not re.fullmatch(r'AutoHSR(?: - |-)\d{1,6}',name):raise AutomationError('本次自动编号超出已有命名协议。')
                self.data['plan'] = dict(name=name,slot=deepcopy(facts['slot']),before_frames=frames);self._persist()
                slot = pages.empty_slot(self._clean(scene))
                scene,_ = self._step(scene,'du_save_slot','empty',target=slot)
                target = self._clean(scene).find('保存本轮数据',(.46,.62,.70,.74),exact=True)
                scene,_ = self._step(scene,'du_save_create','rename',target=target)
                scene,_ = self._step(scene,'du_save_focus','rename',target=Token('存档名输入框',1,(.31,.47,.69,.50)))
                scene,_ = self._step(scene,'du_save_name','named',name=name)
                target = self._clean(scene).find('确认',(.51,.58,.72,.67),exact=True)
                scene,frames = self._step(scene,'du_save_confirm','saved',target=target)
                self.data.update(save_verified=True,saved_frames=frames);self._persist()
            scene,frames = self._step(scene,'du_save_close','returned',key='esc')
            self.data.update(return_verified=True,return_frames=frames,status='complete',safe_to_restart=True);self._persist()
            preflight(self.store.root)
            self.finished = True
            return scene,'victory'
        except Exception as error:
            for action in self.data['actions']:
                if action['status'] in ('pending','submitted'):action['status'] = 'unknown'
            unsent = (all(action['status'] == 'not_sent' for action in self.data['actions'])
                      and not self.data['save_verified'] and not self.data['skip_verified'])
            self.data.update(status='abort_before_input' if unsent else 'unknown',safe_to_restart=unsent)
            try:self._persist();self.finished = unsent
            except (OSError,ValueError,AutomationError):pass
            if isinstance(error,InputInterrupted):
                raise AutomationError('差分保存被暂停或失焦中断，原动作待核对，未继续返回或重发。') from error
            raise


def save_victory(flow, scene):
    return ArchiveWorkflow(flow).run(scene)
