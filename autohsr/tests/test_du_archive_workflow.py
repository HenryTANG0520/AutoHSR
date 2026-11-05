"""Real archive Context dispatch with synthetic pages and temporary evidence."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import uuid

import numpy as np
from PIL import Image

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.du_archive_store import NAME, digest, encoded, preflight
from autohsr.du_archive_workflow import ArchiveAction, ArchiveWorkflow, save_victory
from autohsr.models import AutomationError, EmptyCapture, InputInterrupted, RunReport, Scene, Stopped, Token
from autohsr.windows import Geometry


def token(text,x,y):return Token(text,.99,(x-.01,y-.01,x+.01,y+.01))


def scene(kind, *, name='AutoHSR - 2', uid='100000000'):
    """Artificial OCR/layout, not a calibrated full game screenshot."""
    if kind == 'victory':
        words=[token(s,.1,.1) for s in ('探索成功','分析报告','差分宇宙构筑内容','周期演算（13/13）')]
        words += [token('返回主界面',.40,.91),token('记录本次存档',.62,.91)]
    elif kind in ('management','empty','saved','occupied'):
        words=[token('差分宇宙',.08,.04),token('存档管理',.08,.075),token('AutoHSR-1',.06,.20)]
        if kind in ('management','empty'):words.append(token('暂无存档',.06,.32))
        if kind == 'empty':words += [token('暂无存档',.58,.53),token('保存本轮数据',.58,.68)]
        if kind == 'saved':words += [token(name,.06,.32),token(name,.35,.12)]
        if kind == 'occupied':words += [token('AutoHSR - 2',.06,.32),token('AutoHSR - 2',.35,.12)]
    elif kind=='field':
        words=[token('1/13位面-战斗',.12,.035),token('Lv1/20',.1,.08)]
    else:
        words=[token('更改存档名',.50,.38),token('取消',.40,.62),token('确认',.62,.62)]
        if kind == 'named':words.append(token(name,.40,.48))
    if uid is not None:words.append(token('UID:'+uid,.07,.975))
    return Scene(words,np.full((540,960,3),30,np.uint8),Geometry(0,0,960,540),time.monotonic())


def normal_pages(*, name='AutoHSR - 2', no_empty=False):
    kinds=['victory','victory','occupied','occupied','victory','victory'] if no_empty else [
        'victory','victory','management','management','empty','empty','rename','rename',
        'rename','rename','named','named','saved','saved','victory','victory']
    return [scene(kind,name=name) for kind in kinds]


def fresh_ledger(flow,c,*,transition=False):
    """Synthetic sent launch and actual history shape from Flow._click."""
    entry=flow.report['run_results'][-1];run=entry['run']
    flow.report['actions']=[item for item in flow.report['actions'] if item.get('run')!=run]
    flow.report['page_history']=[item for item in flow.report['page_history'] if item.get('run')!=run]
    start=scene('field');path=c.evidence(start,'start_'+str(run))
    entry.update(difficulty_verified=True,difficulty_rank=5,started_page='field_combat',
        difficulty_evidence=dict(verified=True,requested_rank=5,displayed_rank_after=5),started_evidence=str(path))
    after=c.evidence(scene('rename') if transition else start,'launch_after_'+str(run))
    kind='unknown' if transition else 'field_combat'
    flow.report['actions'].append(dict(index=len(flow.report['actions'])+1,run=run,action='启动「差分宇宙」',
        intent='periodic_start',status='sent',after_evidence=str(after),after_page=kind))
    flow.report['page_history'].append(dict(index=len(flow.report['page_history'])+1,run=run,
        page_kind=kind,evidence=str(after),ocr_text='加载中' if transition else start.text))
    flow.report['page_history'].append(dict(index=len(flow.report['page_history'])+1,run=run,
        page_kind='field_combat',evidence=str(path),ocr_text=start.text))
    if not transition:
        # Flow._observe's same final image is referenced directly, not twice.
        flow.report['actions'][-1]['after_evidence']=str(path)
        flow.report['page_history'].pop(-2)
    write_ledger(flow,c)


def write_ledger(flow,c):
    ledger=dict(schema_version=1,**deepcopy(flow.report))
    Path(c.report.run_dir,'differential-universe-ledger.json').write_text(json.dumps(ledger),'utf8')


def install_pages(context,pages):
    source=iter(pages)
    def snapshot():
        try:item=next(source)
        except StopIteration:raise Stopped('synthetic frames ended')
        if isinstance(item,Exception):raise item
        current=Scene(list(item.tokens),item.image.copy(),item.geometry,time.monotonic())
        context.last_scene=current;context.scene_epoch=context.runner.input_epoch
        return current
    context.snapshot=snapshot
    return snapshot()


def make_context(folder, pages, *, fresh=False, session_id=None, run_id=None):
    directory=Path(folder)/uuid.uuid4().hex;directory.mkdir()
    settings=Settings(differential_universe_save=True,overlay_logs=False)
    report=RunReport(operation='differential_universe',run_dir=str(directory))
    runner=SimpleNamespace(settings=settings,report=report,input_epoch=0,inactive_duration=0.,
        _stop=threading.Event(),_pause=threading.Event(),log=Mock())
    def checkpoint():
        if runner._stop.is_set():raise Stopped('synthetic stop')
    runner.checkpoint=checkpoint
    window=SimpleNamespace(hwnd=123,guard=Mock(),click=Mock(),key=Mock(),type_du_save_name=Mock())
    context=Context(runner,window,Mock());context.sleep=Mock()
    def evidence(current,label):
        path=directory/(label+'.png');Image.fromarray(current.image[:,:,::-1]).save(path)
        return path
    context.evidence=evidence
    entry=dict(run=1,run_id=run_id or str(uuid.uuid4()),origin='fresh' if fresh else 'resumed_trial',status='running')
    session_id=session_id or str(uuid.uuid4())
    report.differential_universe.update(session_id=session_id,requested_runs=1,current_run=1,completed_runs=0,run_results=[entry],actions=[],page_history=[])
    flow=SimpleNamespace(ctx=context,report=report.differential_universe,session_id=session_id,resume_active=not fresh)
    if fresh:fresh_ledger(flow,context)
    else:write_ledger(flow,context)
    return flow,context,install_pages(context,pages)


class ArchiveWorkflowTests(unittest.TestCase):
    def test_normal_chain_uses_real_context_and_saves_before_closing_without_touching_du_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages())
            def close(key):
                record=json.loads(Path(folder,NAME).read_text('utf8'))
                self.assertTrue(record['save_verified']);self.assertFalse(record['return_verified'])
                self.assertEqual(record['actions'][-1]['request']['intent'],'du_save_close')
                self.assertEqual(record['actions'][-1]['status'],'pending')
            c.window.key.side_effect=close
            after,kind=save_victory(flow,first)
            data=preflight(folder);entry=flow.report['run_results'][-1]
            self.assertEqual(kind,'victory');self.assertIs(after,c.last_scene)
            self.assertEqual([a['request']['intent'] for a in data['actions']],
                ['du_save_open','du_save_slot','du_save_create','du_save_focus','du_save_name','du_save_confirm','du_save_close'])
            self.assertTrue(all(a['status']=='verified' for a in data['actions']))
            self.assertEqual(entry['save_status'],'saved');self.assertEqual(entry['save_name'],'AutoHSR - 2')
            self.assertTrue(c.du_archive_workflow.finished);self.assertTrue(data['return_verified'])
            self.assertEqual(flow.report['completed_runs'],0)
            c.window.type_du_save_name.assert_called_once()
            self.assertEqual(c.window.type_du_save_name.call_args.args[0],'AutoHSR - 2')

    def test_no_verified_empty_slot_only_opens_and_closes_without_claiming_full_capacity(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages(no_empty=True))
            save_victory(flow,first);data=preflight(folder)
            self.assertEqual([a['request']['intent'] for a in data['actions']],['du_save_open','du_save_close'])
            self.assertTrue(data['skip_verified']);self.assertFalse(data['save_verified'])
            self.assertEqual(flow.report['run_results'][-1]['save_status'],'no_verified_empty_slot')
            self.assertEqual(data['skip_reason'],'no_verified_empty_slot')
            c.window.type_du_save_name.assert_not_called();self.assertEqual(c.window.click.call_count,1)

    def test_missing_obscured_or_custom_named_rows_do_not_prove_full_capacity(self):
        for variant in ('missing', 'obscured', 'custom'):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder:
                pages = normal_pages(no_empty=True)
                for page in pages[2:4]:
                    original = page.tokens
                    page.tokens = [t for t in original if not t.text.startswith('AutoHSR')]
                    if variant == 'obscured':
                        page.tokens.append(token('加载中', .06, .32))
                    elif variant == 'custom':
                        page.tokens += [replace(t,text='旅行纪念') for t in original if t.text.startswith('AutoHSR')]
                flow,c,first = make_context(folder,pages)
                save_victory(flow,first)
                record = preflight(folder)
                self.assertEqual(flow.report['run_results'][-1]['save_status'],'no_verified_empty_slot')
                self.assertEqual(record['skip_reason'],'no_verified_empty_slot')
                self.assertFalse(record['save_verified'])
                self.assertTrue(record['return_verified'])
                self.assertEqual(c.window.click.call_count,1)
                c.window.type_du_save_name.assert_not_called()

    def test_confirmation_sent_then_interrupted_blocks_new_runner_and_retains_original(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages())
            def interrupt(*args):
                if c.du_archive_workflow.request.intent=='du_save_confirm':raise InputInterrupted('synthetic pause')
            c.window.click.side_effect=interrupt
            with self.assertRaises(AutomationError) as raised:save_victory(flow,first)
            self.assertNotIsInstance(raised.exception,InputInterrupted)
            self.assertFalse(c.du_archive_workflow.finished)
            data=json.loads(Path(folder,NAME).read_text('utf8'));original=Path(data['journal']).read_bytes()
            self.assertEqual(data['actions'][-1]['status'],'unknown')
            other,d,again=make_context(folder,normal_pages())
            with self.assertRaises(AutomationError):save_victory(other,again)
            self.assertEqual(Path(data['journal']).read_bytes(),original);d.window.click.assert_not_called()

    def test_saved_fact_survives_close_failure_but_future_input_and_save_remain_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages())
            c.window.key.side_effect=InputInterrupted('synthetic close interruption')
            with self.assertRaises(AutomationError):save_victory(flow,first)
            data=json.loads(Path(folder,NAME).read_text('utf8'))
            self.assertTrue(data['save_verified']);self.assertFalse(data['return_verified'])
            self.assertEqual(data['status'],'unknown');self.assertFalse(c.du_archive_workflow.finished)
            self.assertEqual(flow.report['run_results'][-1]['save_status'],'saved')
            with self.assertRaises(AutomationError):preflight(folder)

    def test_completed_save_cannot_be_repeated_by_a_new_resumed_uuid_before_victory_return(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages());save_victory(flow,first)
            original=Path(c.du_archive_workflow.store.path).read_bytes()
            resumed,d,again=make_context(folder,normal_pages())
            with self.assertRaises(AutomationError):save_victory(resumed,again)
            d.window.click.assert_not_called();self.assertEqual(Path(c.du_archive_workflow.store.path).read_bytes(),original)

    def test_a_later_native_fresh_game_can_save_and_links_prior_immutable_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages(),fresh=True);save_victory(flow,first)
            original=Path(c.du_archive_workflow.store.path).read_bytes()
            other,d,again=make_context(folder,normal_pages(),fresh=True);save_victory(other,again)
            data=preflight(folder)
            self.assertEqual(data['prior']['path'],str(c.du_archive_workflow.store.path))
            self.assertEqual(Path(c.du_archive_workflow.store.path).read_bytes(),original)
            self.assertIsNotNone(data['start_proof'])

    def test_missing_origin_uid_has_zero_input_abort_and_does_not_borrow_old_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            pages=[scene('victory',uid=None),scene('victory',uid=None)]
            flow,c,first=make_context(folder,pages)
            with self.assertRaises(Stopped):save_victory(flow,first)
            data=preflight(folder)
            self.assertEqual(data['status'],'abort_before_input');self.assertEqual(data['actions'],[])
            self.assertTrue(c.du_archive_workflow.finished);c.window.click.assert_not_called()
            other,d,again=make_context(folder,normal_pages());save_victory(other,again)

    def test_changed_epoch_between_context_checks_never_sends_the_pending_input(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages())
            c.window.guard.side_effect=lambda geometry:setattr(c.runner,'input_epoch',1)
            with self.assertRaises(AutomationError):save_victory(flow,first)
            c.window.click.assert_not_called()
            self.assertEqual(json.loads(Path(folder,NAME).read_text('utf8'))['actions'][-1]['status'],'unknown')

    def test_existing_or_partial_name_and_changed_uid_do_not_authorize_confirmation(self):
        for change in ('name','uid'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                pages=normal_pages()
                if change=='name':pages[10:12]=[scene('named',name='AutoHSR-99'),scene('named',name='AutoHSR-99')]
                else:pages[2:4]=[scene('management',uid='200000000'),scene('management',uid='200000000')]
                flow,c,first=make_context(folder,pages)
                with self.assertRaises(AutomationError):save_victory(flow,first)
                intents=[a['request']['intent'] for a in c.du_archive_workflow.data['actions']]
                self.assertNotIn('du_save_confirm',intents)

    def test_dual_write_failure_before_input_and_damaged_completed_sources_do_not_unlock(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages())
            from autohsr import du_archive_store as store
            write=store._write
            def fail(path,data):
                if data['actions'] and path.name==NAME:raise OSError('synthetic canonical write failure')
                return write(path,data)
            with patch.object(store,'_write',side_effect=fail),self.assertRaises(OSError):save_victory(flow,first)
            c.window.click.assert_not_called()
            with self.assertRaises(AutomationError):preflight(folder)
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages());save_victory(flow,first)
            data=preflight(folder);Path(data['observations'][-1]['evidence']['path']).write_bytes(b'changed PNG')
            with self.assertRaises(AutomationError):preflight(folder)

    def test_legacy_attempt_flag_is_not_migrated_into_a_new_save(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages())
            flow.report['run_results'][-1]['save_attempted']=True
            with self.assertRaises(AutomationError):save_victory(flow,first)
            c.window.click.assert_not_called();self.assertFalse(Path(folder,NAME).exists())

    def test_fresh_flag_and_victory_png_without_real_sent_start_cannot_authorize(self):
        for defect in ('victory','missing_action','wrong_history','wrong_run'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as folder:
                flow,c,first=make_context(folder,normal_pages(),fresh=True)
                entry=flow.report['run_results'][-1]
                if defect=='victory':
                    entry.update(started_page='victory',started_evidence=str(c.evidence(scene('victory'),'bad_start')))
                    flow.report['actions']=[];flow.report['page_history']=[]
                elif defect=='missing_action':flow.report['actions']=[]
                elif defect=='wrong_history':flow.report['page_history'][-1]['evidence']=str(c.evidence(scene('field'),'unrelated'))
                else:flow.report['actions'][-1]['run']=2
                write_ledger(flow,c)
                with self.assertRaises(AutomationError):save_victory(flow,first)
                c.window.click.assert_not_called();self.assertFalse(Path(folder,NAME).exists())

    def test_fresh_launch_may_have_observation_only_unknown_transition(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages(),fresh=True)
            fresh_ledger(flow,c,transition=True)
            save_victory(flow,first)
            proof=preflight(folder)['start_proof']
            self.assertEqual(len(proof['source']['images']),2)
            self.assertEqual(proof['entry']['started_page'],'field_combat')

    def test_all_known_ancestor_pngs_are_checked_and_ancestor_game_cannot_be_reused(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages(),fresh=True);save_victory(flow,first)
            original=deepcopy(c.du_archive_workflow.data)
            other,d,again=make_context(folder,normal_pages(),fresh=True);save_victory(other,again)
            repeated,e,last=make_context(folder,normal_pages(),fresh=True,
                session_id=original['session_id'],run_id=original['run_id'])
            with self.assertRaises(AutomationError):save_victory(repeated,last)
            e.window.click.assert_not_called()
            Path(original['observations'][0]['evidence']['path']).write_bytes(b'damaged ancestor')
            with self.assertRaises(AutomationError):preflight(folder)

    def test_ten_fresh_games_in_one_native_context_keep_separate_immutable_receipts(self):
        with tempfile.TemporaryDirectory() as folder:
            flow,c,first=make_context(folder,normal_pages(),fresh=True)
            originals=[]
            for run in range(1,11):
                if run>1:
                    flow.report['current_run']=run
                    flow.report['run_results'].append(dict(run=run,run_id=str(uuid.uuid4()),origin='fresh',status='running'))
                    fresh_ledger(flow,c)
                    first=install_pages(c,normal_pages())
                save_victory(flow,first)
                originals.append((c.du_archive_workflow.store.path,c.du_archive_workflow.store.path.read_bytes()))
            self.assertEqual(preflight(folder)['sequence'],10)
            self.assertEqual(len({path for path,_ in originals}),10)
            self.assertTrue(all(path.read_bytes()==raw for path,raw in originals))
            self.assertEqual(flow.report['completed_runs'],0)

    def test_name_feedback_normalizes_format_but_input_and_receipt_remain_exact(self):
        for name in ('AutoHSR-2','aUtOhSr -2'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                flow,c,first=make_context(folder,normal_pages(name=name));save_victory(flow,first)
                self.assertEqual(preflight(folder)['plan']['name'],'AutoHSR - 2')
                self.assertEqual(c.window.type_du_save_name.call_args.args[0],'AutoHSR - 2')
        for name in ('AutoHSR-20','AutoHSR-2x'):
            with self.subTest(name=name),tempfile.TemporaryDirectory() as folder:
                flow,c,first=make_context(folder,normal_pages(name=name))
                with self.assertRaises(AutomationError):save_victory(flow,first)
                self.assertNotIn('du_save_confirm',[a['request']['intent'] for a in c.du_archive_workflow.data['actions']])

    def test_saved_feedback_is_bound_to_exact_empty_row_and_preserves_other_rows(self):
        for correct in (False,True):
            with self.subTest(correct=correct),tempfile.TemporaryDirectory() as folder:
                frames=normal_pages()
                for index in (2,3,4,5):frames[index].tokens.append(token('暂无存档',.06,.44))
                for index in (12,13):
                    if not correct:
                        frames[index].tokens=[replace(t,box=token(t.text,.06,.44).box)
                            if t.text=='AutoHSR - 2' and t.center[0]<.18 else t for t in frames[index].tokens]
                    frames[index].tokens.append(token('暂无存档',.06,.44 if correct else .32))
                flow,c,first=make_context(folder,frames)
                if correct:
                    save_victory(flow,first);data=preflight(folder)
                    # Same field edit/recomputed dual JSON cannot clear the frozen row.
                    for item in data['observations']:
                        if item['stage']=='saved':
                            for row in item['facts']['rows']:
                                if row['text']=='autohsr-2':row['box']=list(token('x',.06,.44).box)
                            item['facts']['list_box']=list(token('x',.06,.44).box)
                    data['digest']=digest({k:v for k,v in data.items() if k!='digest'})
                    Path(data['journal']).write_bytes(encoded(data));Path(folder,NAME).write_bytes(encoded(data))
                    with self.assertRaises(AutomationError):preflight(folder)
                else:
                    with self.assertRaises(AutomationError):save_victory(flow,first)
                    self.assertFalse(c.du_archive_workflow.data['save_verified']);c.window.key.assert_not_called()

    def test_raw_visible_unreadable_or_conflicting_uid_is_not_hidden_but_true_hidden_is_allowed(self):
        for defect in ('low','truncated','conflict','hidden'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as folder:
                frames=normal_pages()
                for current in frames[2:]:
                    current.tokens=[t for t in current.tokens if not t.text.startswith('UID')]
                    if defect=='low':current.tokens.append(replace(token('UID:100000000',.07,.975),score=.3))
                    elif defect=='truncated':current.tokens.append(token('UID:1000',.07,.975))
                    elif defect=='conflict':current.tokens += [token('UID:100000000',.07,.975),token('UID:200000000',.17,.975)]
                flow,c,first=make_context(folder,frames)
                if defect=='hidden':save_victory(flow,first);self.assertTrue(preflight(folder)['save_verified'])
                else:
                    with self.assertRaises(AutomationError):save_victory(flow,first)
                    self.assertEqual(c.window.click.call_count,1)
                    self.assertFalse(c.du_archive_workflow.finished)


if __name__=='__main__':unittest.main()
