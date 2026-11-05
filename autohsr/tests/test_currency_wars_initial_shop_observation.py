"""Initial free return after re-observation; synthetic Context and files only."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock,patch

from autohsr.app import Context
from autohsr.currency_wars_initial_shop import proposal,bind_intent,validate_return
from autohsr.currency_wars_initial_shop_observation import KEY,HISTORY,begin,record,validate,ensure
from autohsr.currency_wars_standard_flow import run_standard
from autohsr.currency_wars_session import StandardSession
from autohsr.models import AutomationError,Stopped
from autohsr.tests import test_currency_wars_initial as initial
from autohsr.tests import test_currency_wars_initial_flow as flow


class InitialShopObservationTests(unittest.TestCase):
    def scenes(self,board):
        first=initial.shop_scene(board);second=initial.shop_scene(board)
        while second.captured_at<=first.captured_at:
            time.sleep(.001);second=initial.shop_scene(board)
        return first,second

    def prove(self,c,board,store):
        begin(store.data,confidence=c.settings.ocr_confidence)
        first,second=self.scenes(board)
        suffix=len(store.data.get(HISTORY,[]))
        for index,scene in enumerate((first,second)):
            path=initial.write_scene(c.report.run_dir,f'observe-{suffix}-{index}.png',scene)
            self.assertEqual(record(store.data,scene,path,confidence=c.settings.ocr_confidence),index==1)
        store.persist()
        return second

    def pending(self,c,scene,store):
        c.last_scene=scene;c.scene_epoch=c.runner.input_epoch
        choice=proposal(scene,store.data,c.settings.ocr_confidence)
        action=store.pending(choice.intent,c.runner.input_epoch,c.evidence(scene,'before-close'),choice.expected)
        action['target']=list(choice.payload)
        bind_intent(store.data,choice,scene,c.settings.ocr_confidence);store.persist()
        return choice

    def resumed_context(self, folder, *, new_run):
        helper=flow.InitialFlowTests()
        c,board,store=helper.context(folder)
        _,source=initial.fixture(c.report.run_dir)
        store.data['actions']=source['actions']
        initial.arrive(c.report.run_dir,board,store.data,mixed=True)
        origin=deepcopy(store.data['initial_environment'])
        if new_run:
            current=Path(folder)/'new-child';current.mkdir()
            c.report.run_dir=str(current)
        else:
            c.runner.input_epoch=2
        c.scene_epoch=c.runner.input_epoch
        store.data.update(account_verified_run=c.report.run_dir,account_verified_epoch=c.runner.input_epoch)
        store.data['client'].update(verified_run=c.report.run_dir,input_epoch=c.runner.input_epoch)
        store.persist()
        return helper,c,board,store,origin

    def check_flow(self, *, new_run):
        with tempfile.TemporaryDirectory() as folder:
            helper,c,board,store,origin=self.resumed_context(folder,new_run=new_run)
            helper.states(c,[initial.shop_scene(board),initial.shop_scene(board),initial.clone(board),initial.clone(board)])
            helper.stop_after(c,'close_standard_initial_shop')
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['initial_environment'],origin)
            self.assertEqual(saved['actions'][-1]['action'],'close_standard_initial_shop')
            self.assertEqual(c.window.click.call_count,1)

    def test_fresh_same_run_epoch_can_observe_then_submit_first_close(self):
        self.check_flow(new_run=False)

    def test_explicit_new_run_can_observe_then_submit_first_close(self):
        self.check_flow(new_run=True)

    def test_new_frames_can_have_different_pixels_without_changing_the_accepted_origin(self):
        with tempfile.TemporaryDirectory() as folder:
            _,c,board,store,origin=self.resumed_context(folder,new_run=True)
            begin(store.data);first,second=self.scenes(board);second.image[0,0]=[7,19,41]
            for index,scene in enumerate((first,second)):
                path=initial.write_scene(c.report.run_dir,f'animated-{index}.png',scene)
                self.assertEqual(record(store.data,scene,path),index==1)
            proof=validate(store.data)
            self.assertNotEqual(proof['frames'][0]['evidence']['pixel_sha256'],proof['frames'][1]['evidence']['pixel_sha256'])
            self.assertEqual(store.data['initial_environment'],origin)

    def test_read_only_history_keeps_verified_proof_when_a_second_epoch_needs_a_new_pair(self):
        with tempfile.TemporaryDirectory() as folder:
            _,c,board,store,origin=self.resumed_context(folder,new_run=False)
            self.prove(c,board,store);old=deepcopy(store.data[KEY])
            c.runner.input_epoch+=2
            store.data['account_verified_epoch']=c.runner.input_epoch;store.data['client']['input_epoch']=c.runner.input_epoch
            self.prove(c,board,store)
            self.assertEqual(store.data[HISTORY],[old]);self.assertEqual(validate(store.data)['epoch'],4)
            self.assertEqual(store.data['initial_environment'],origin)
            store.data[HISTORY][0]['frames'][0]['source']['offers']=[]
            with self.assertRaises(AutomationError):validate(store.data)

    def test_stop_after_first_read_keeps_unknown_attempt_and_new_scope_can_reobserve(self):
        with tempfile.TemporaryDirectory() as folder:
            helper,c,board,store,origin=self.resumed_context(folder,new_run=False)
            original_snapshot=c.snapshot
            first=initial.shop_scene(board);helper.states(c,[]);c.last_scene=first
            with self.assertRaises(Stopped):ensure(c,store,first)
            old=deepcopy(store.data[KEY]);self.assertEqual(old['status'],'unknown');self.assertEqual(len(old['frames']),1)
            with self.assertRaises(AutomationError):ensure(c,store,initial.shop_scene(board))
            c.runner.input_epoch+=2;c.scene_epoch=c.runner.input_epoch
            store.data['account_verified_epoch']=c.runner.input_epoch;store.data['client']['input_epoch']=c.runner.input_epoch
            first,second=self.scenes(board);c.snapshot=original_snapshot;helper.states(c,[second]);c.last_scene=first
            self.assertIs(ensure(c,store,first),second)
            self.assertEqual(store.data[HISTORY],[old]);self.assertEqual(validate(store.data)['status'],'verified')
            self.assertEqual(store.data['initial_environment'],origin);c.window.click.assert_not_called()

    def test_pending_or_unknown_close_cannot_begin_another_read_only_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            _,c,board,store,_=self.resumed_context(folder,new_run=False)
            scene=self.prove(c,board,store);self.pending(c,scene,store)
            for status in ('pending','unknown'):
                store.data['actions'][-1]['status']=status
                old=deepcopy(store.data)
                with self.assertRaises(AutomationError):begin(store.data)
                self.assertEqual(store.data,old)

    def test_duplicate_capture_or_same_evidence_file_cannot_form_the_pair(self):
        for same in ('capture','file'):
            with self.subTest(same=same),tempfile.TemporaryDirectory() as folder:
                _,c,board,store,_=self.resumed_context(folder,new_run=False)
                begin(store.data);first,second=self.scenes(board)
                path=initial.write_scene(c.report.run_dir,'first.png',first);self.assertFalse(record(store.data,first,path))
                if same=='capture':
                    second.captured_at=first.captured_at
                    path2=initial.write_scene(c.report.run_dir,'second.png',second)
                    self.assertFalse(record(store.data,second,path2))
                else:
                    with self.assertRaises(AutomationError):record(store.data,second,path)
                self.assertEqual(len(store.data[KEY]['frames']),1)
                with self.assertRaises(AutomationError):validate(store.data)

    def test_changed_client_page_hud_or_missing_png_keeps_proof_unverified(self):
        for change in ('client','hud','node','account','png'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                _,c,board,store,_=self.resumed_context(folder,new_run=False)
                begin(store.data);first,second=self.scenes(board)
                path=initial.write_scene(c.report.run_dir,'first.png',first);record(store.data,first,path)
                if change=='client':store.data['client']['full_version']='4.6.1'
                elif change=='png':path.write_bytes(b'corrupted synthetic PNG')
                else:
                    from autohsr.models import Token,normalize
                    if change=='hud':second.tokens=[Token('18',t.score,t.box) if t.text=='17' else t for t in second.tokens]
                    elif change=='node':second.tokens=[Token('1-2',t.score,t.box) if t.text=='1-1' else t for t in second.tokens]
                    else:second.tokens=[Token('UID:200000000',t.score,t.box) if normalize(t.text).startswith('uid') else t for t in second.tokens]
                path2=initial.write_scene(c.report.run_dir,'second.png',second)
                with self.assertRaises(AutomationError):record(store.data,second,path2)
                self.assertEqual(len(store.data[KEY]['frames']),1)

    def test_evidence_write_failure_never_creates_close_or_clicks(self):
        with tempfile.TemporaryDirectory() as folder:
            _,c,board,store,origin=self.resumed_context(folder,new_run=False)
            scene=initial.shop_scene(board);c.last_scene=scene;c.evidence=Mock(side_effect=OSError('synthetic write failure'))
            with self.assertRaises(OSError):ensure(c,store,scene)
            self.assertEqual(store.data[KEY]['status'],'unknown')
            self.assertNotIn('initial_shop_return',store.data);c.window.click.assert_not_called()
            self.assertEqual(store.data['initial_environment'],origin)

    def test_final_observation_write_crossing_deadline_keeps_attempt_unverified(self):
        with tempfile.TemporaryDirectory() as folder:
            helper,c,board,store,origin=self.resumed_context(folder,new_run=False)
            first,second=self.scenes(board);helper.states(c,[second]);c.last_scene=first
            clock=[0.];writes=[0];persist=store.persist
            def write():
                persist();writes[0]+=1
                if writes[0]==2:clock[0]=14.8
                elif writes[0]>=3:clock[0]=15.01
            store.persist=write
            with patch('autohsr.currency_wars_initial_shop_observation.time',SimpleNamespace(monotonic=lambda:clock[0])):
                with self.assertRaises(AutomationError):ensure(c,store,first)
            self.assertEqual(store.data[KEY]['status'],'unknown')
            self.assertEqual(len(store.data[KEY]['frames']),2)
            self.assertEqual(StandardSession(store.path).data[KEY]['status'],'unknown')
            self.assertNotIn('initial_shop_return',store.data);c.window.click.assert_not_called()
            self.assertEqual(store.data['initial_environment'],origin)

    def test_changed_client_without_new_run_or_epoch_cannot_claim_another_attempt(self):
        with tempfile.TemporaryDirectory() as folder:
            _,c,board,store,_=self.resumed_context(folder,new_run=False)
            self.prove(c,board,store);old=deepcopy(store.data[KEY])
            store.data['client']['full_version']='4.6.1'
            with self.assertRaises(AutomationError):begin(store.data)
            self.assertEqual(store.data[KEY],old);self.assertEqual(store.data[HISTORY],[])

    def test_context_requires_current_durable_observation_and_cannot_drop_it_in_memory(self):
        for change in ('deleted','memory','epoch','client','file'):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as folder:
                _,c,board,store,_=self.resumed_context(folder,new_run=False)
                scene=self.prove(c,board,store);choice=self.pending(c,scene,store)
                c.currency_standard_session=store
                if change=='deleted':store.data.pop(KEY)
                elif change=='memory':store.data[KEY]['digest']='0'*64
                elif change=='epoch':c.runner.input_epoch+=1
                elif change=='client':store.data['client']['version']='4.7'
                else:Path(store.data[KEY]['frames'][0]['evidence']['path']).write_bytes(b'changed PNG')
                with self.assertRaises(AutomationError):Context.currency_standard_input(c,scene,choice)
                c.window.click.assert_not_called()

    def test_new_return_receipt_rejects_missing_proof_downgrade_and_source_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            helper,c,board,store,_=self.resumed_context(folder,new_run=True)
            helper.states(c,[initial.shop_scene(board),initial.shop_scene(board),initial.clone(board),initial.clone(board)])
            helper.stop_after(c,'close_standard_initial_shop')
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            data=c.currency_standard_session.data;validate_return(data)
            for change in ('proof','history','schema','receipt','path'):
                bad=deepcopy(data)
                if change=='proof':bad.pop(KEY)
                elif change=='history':bad[HISTORY].append(deepcopy(bad[KEY]))
                elif change=='schema':bad['initial_shop_return']['schema']=1
                elif change=='receipt':bad['initial_shop_return']['receipt']['trade_authorized']=True
                else:bad['initial_shop_return']['receipt']['frames'][0]['evidence']['path']=bad['actions'][-1]['before']
                with self.subTest(change=change),self.assertRaises(AutomationError):validate_return(bad)
