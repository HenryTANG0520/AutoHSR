"""Free bench capacity before loot: real gates, synthetic board, public crops.

No Runner.run, Windows input owner, process, account or game is accessed.
"""
from copy import deepcopy
from dataclasses import asdict, replace
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np
from PIL import Image

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop, bench_face
from autohsr.currency_wars_loot import loot_target
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_deployment import standard_deployment
from autohsr.currency_wars_standard_flow import next_action, run_standard
from autohsr.models import AutomationError, InputInterrupted, RunReport, Scene, Stopped, Token
from autohsr.tests.test_currency_wars_standard_deployment import frame_and_session, units
from autohsr.tests.test_currency_wars_standard_trading import hud


ROOT = Path(__file__).parent / 'fixtures/currency_crystals'


def clone(value):
    return Scene(list(value.tokens), value.image.copy(), value.geometry, value.captured_at)


def fixture(*, free=False, deployed=0, crystals=True):
    board, data = frame_and_session()
    hud(board,deployment=(deployed,3))
    for slot in range(1,10):
        image = _crop(board.image,bench_face(slot))
        image[:] = np.random.default_rng(slot).integers(0,256,image.shape,dtype=np.uint8)
    if free:_crop(board.image,bench_face(9))[:]=0
    if deployed:
        for slot,x in enumerate((990,1180,1370)[:deployed],1):
            image=_crop(board.image,(x/2560-.025,.33,x/2560+.025,.41))
            image[:]=np.random.default_rng(80+slot).integers(0,256,image.shape,dtype=np.uint8)
    if crystals:board.image[330:690,1700:2180]=cv2.imread(str(ROOT/'gray_blue.png'))
    cells=roster_cells(board);existing=units();records={}
    for cell in cells:
        if cell.state!='occupied':continue
        unit=(existing[cell.slot-1] if cell.zone=='bench' and cell.slot<=5 else
              replace(existing[0],name='候选'+str(cell.slot) if cell.zone=='bench' else '场上'+str(cell.slot),
                      zone=cell.zone,slot=cell.slot,star=1,tier=1,eligible_zones=('front','back')))
        records[cell.zone+':'+str(cell.slot)]=dict(unit=asdict(unit),signature=cell.signature,node=cell.node,source='fixture.png')
    data.update(strategy='default',collection=dict(data['collection'],units=records,complete=True))
    return board,data


class Harness:
    """Only Context/flow execute; the window changes an in-memory Scene."""
    def __init__(self, folder, *, mode='move', free=False):
        self.board,self.data=fixture(free=free)
        self.mode=mode;self.stage='before';self.captures=[];self.migrated=None;self.released=False
        self.now=time.monotonic();self.directory=Path(folder)/'attempt';self.directory.mkdir()
        self.clock=SimpleNamespace(monotonic=lambda:self.now)
        self.settings=Settings(overlay_logs=False)
        report=RunReport(operation='currency_wars_standard',run_dir=str(self.directory))
        runner=SimpleNamespace(settings=self.settings,report=report,input_epoch=0,inactive_duration=0.,
            currency_resume=True,currency_strategy='default',_pause=threading.Event(),_stop=threading.Event(),
            log=Mock(),emit=Mock())
        window=SimpleNamespace(guard=Mock(),drag=Mock(side_effect=self.drag),move=Mock(),click=Mock(side_effect=self.click))
        self.c=Context(runner,window,Mock());runner.checkpoint=self.checkpoint
        self.c.sleep=lambda seconds:setattr(self,'now',self.now+seconds)
        self.c.snapshot=self.snapshot;self.c.evidence=self.evidence
        directory=str(self.directory)
        self.data.update(account_verified_run=directory,account_verified_epoch=0,
            client=dict(self.data['client'],verified_run=directory,input_epoch=0),
            collection=dict(self.data['collection'],run_dir=directory,input_epoch=0))
        store=StandardSession(Path(folder)/'currency-standard-session.json')
        store.begin(directory,dict(rank_verified=True,rank=8,wealth=40))
        store.data.update(deepcopy(self.data));store.persist()
        self.path=store.path
        self.source_count=0

    def checkpoint(self):
        if self.c.runner._stop.is_set():raise Stopped('synthetic stop')
        store=getattr(self.c,'currency_standard_session',None)
        if store and store.data['actions'] and store.data['actions'][-1]['action']=='collect_standard_loot' and store.data['actions'][-1]['status']=='verified':
            raise Stopped('end of the requested fake scenario')

    def snapshot(self):
        self.now+=.01
        current=clone(self.board);current.captured_at=self.now
        self.c.last_scene=current;self.c.scene_epoch=self.c.runner.input_epoch
        self.captures.append((self.stage,current.captured_at))
        return current

    def evidence(self,current,label):
        self.source_count+=1
        path=self.directory/(str(self.source_count)+'_'+label+'.png')
        Image.fromarray(current.image[:,:,::-1]).save(path)
        return path

    def drag(self,start,end,geometry,*,checkpoint,**kwargs):
        self.released=False
        try:
            if self.mode=='pause':self.c.runner._pause.set()
            checkpoint()
            if self.mode=='unchanged':return
            action=self.c.currency_standard_session.data['actions'][-1]
            slot=action['target'][4]
            if self.mode!='count_only':
                face=_crop(self.board.image,bench_face(slot)).copy();height,width=face.shape[:2]
                x=round(end[0]*2560)-width//2
                self.board.image[480:480+height,x:x+width]=face
                _crop(self.board.image,bench_face(slot))[:]=0
            gold=read_match(self.board).gold+1 if self.mode=='gold_changed' else None
            hud(self.board,deployment=(1,3),gold=gold)
            self.stage='deployed'
        finally:self.released=True

    def click(self,*args):
        action=self.c.currency_standard_session.data['actions'][-1]
        if action['action']!='collect_standard_loot':raise AssertionError('unexpected fake click')
        self.migrated=deepcopy(self.c.currency_standard_session.data['collection'])
        self.board.image[330:690,1700:2180]=cv2.imread(str(ROOT/'blue_after_gray.png'))
        self.stage='collected'

    def run(self):
        # Module bindings are injected; stdlib time and time.monotonic stay real.
        with patch('autohsr.app.time',self.clock),patch('autohsr.currency_wars.time',self.clock), \
             patch('autohsr.currency_wars_standard_flow.time',self.clock):
            return run_standard(self.c)


class LootCapacityLogicTests(unittest.TestCase):
    def test_full_bench_uses_existing_free_deployment_before_one_crystal(self):
        board,data=fixture()
        self.assertEqual(sum(c.zone=='bench' and c.state=='occupied' for c in roster_cells(board)),9)
        expected=standard_deployment(board,data)
        self.assertIsNotNone(expected)
        action=next_action(board,session=data)
        self.assertEqual(action.intent,'deploy_standard_owned')
        self.assertEqual(action.target,expected[0])
        self.assertEqual(action.payload,expected[3])
        self.assertEqual(action.details[:4],(expected[1].name,expected[1].star,expected[1].tier,expected[0].zone))

    def test_a_verified_existing_empty_slot_keeps_the_original_pickup(self):
        board,data=fixture(free=True)
        action=next_action(board,session=data)
        self.assertEqual(action.intent,'collect_standard_loot')
        self.assertEqual(action.payload,loot_target(board))

    def test_full_field_unknown_roles_or_no_legal_team_do_not_fall_back_to_sale_or_exchange(self):
        for defect in ('full_field','unknown_star','unknown_zone','all_duplicates'):
            with self.subTest(defect=defect):
                board,data=fixture(deployed=3 if defect=='full_field' else 0)
                if defect=='unknown_star':data['collection']['units']['bench:1']['unit']['star']=None
                if defect=='unknown_zone':data['collection']['units']['bench:1']['unit']['eligible_zones']=None
                if defect=='all_duplicates':
                    for record in data['collection']['units'].values():record['unit']['name']='同一角色'
                with self.assertRaises(AutomationError):next_action(board,session=data)

    def test_unreadable_or_reward_cells_and_missing_bench_cell_never_count_as_full(self):
        for defect in ('unknown','reward','missing'):
            with self.subTest(defect=defect):
                board,data=fixture()
                if defect=='unknown':
                    image=_crop(board.image,bench_face(9));image[:]=100;image[::2]=120
                    with self.assertRaises(AutomationError):next_action(board,session=data)
                elif defect=='reward':
                    x=next(c.point[0] for c in roster_cells(board) if c.zone=='bench' and c.slot==9)
                    board.tokens.append(Token('开启',.99,(x-.01,.82,x+.01,.86)))
                    action=next_action(board,session=data)
                    self.assertNotEqual(action.intent,'deploy_standard_owned')
                else:
                    original=roster_cells(board)
                    with patch('autohsr.currency_wars_collector.roster_cells',return_value=tuple(c for c in original if (c.zone,c.slot)!=('bench',9))), \
                         patch('autohsr.currency_wars_standard_rewards.open_bench_action',return_value=None):
                        with self.assertRaises(AutomationError):next_action(board,session=data)

    def test_pending_pickup_is_not_replaced_and_unknown_pickup_or_deployment_cannot_retry(self):
        for status,action in (('pending','collect_standard_loot'),('unknown','collect_standard_loot'),('unknown','deploy_standard_owned')):
            with self.subTest(status=status,action=action):
                board,data=fixture()
                data['actions']=[dict(id=0,action=action,status=status,input_epoch=0,before='fixture.png',
                    expected='loot_collected',target=[.7,.34,.01])]
                with self.assertRaises(AutomationError):next_action(board,session=data)

    def test_initial_post_choice_and_stale_unit_probe_remain_ahead_of_capacity(self):
        board,data=fixture()
        data['initial_environment']=dict(post_choice_observation=None)
        with patch('autohsr.currency_wars_initial.validate_origin',side_effect=AutomationError('initial proof missing')):
            with self.assertRaisesRegex(AutomationError,'initial proof missing'):next_action(board,session=data)
        del data['initial_environment']
        data['collection']['units'].pop('bench:1')
        self.assertEqual(next_action(board,session=data).intent,'inspect_standard_unit')


class LootCapacityContextTests(unittest.TestCase):
    def test_context_feedback_and_migration_free_one_slot_before_original_loot_chain(self):
        with tempfile.TemporaryDirectory() as folder:
            harness=Harness(folder)
            try:harness.run()
            except Stopped:pass
            else:
                data=StandardSession(harness.path).data
                self.fail(str(dict(reason=data.get('reason'),actions=[{k:a.get(k) for k in ('action','status','feedback')} for a in data['actions']])))
            data=StandardSession(harness.path).data
            self.assertEqual([a['action'] for a in data['actions']],['deploy_standard_owned','collect_standard_loot'])
            self.assertTrue(all(a['status']=='verified' for a in data['actions']))
            first=data['actions'][0];slot=first['target'][4]
            self.assertTrue(first['feedback']['source_empty'])
            self.assertEqual(first['feedback']['deployment_after'],[1,3])
            self.assertEqual(harness.migrated['units']['front:1']['unit']['name'],first['decision']['name'])
            self.assertNotIn('bench:'+str(slot),harness.migrated['units'])
            self.assertEqual(len(harness.migrated['units']),9)
            self.assertTrue(harness.migrated['complete'])
            self.assertGreaterEqual(sum(stage=='deployed' for stage,_ in harness.captures),2)
            self.assertGreaterEqual(sum(stage=='collected' for stage,_ in harness.captures),2)
            harness.c.window.drag.assert_called_once();harness.c.window.click.assert_called_once()
            self.assertFalse(data['completion_verified'])

    def test_existing_empty_capacity_does_not_drag(self):
        with tempfile.TemporaryDirectory() as folder:
            harness=Harness(folder,free=True)
            with self.assertRaises(Stopped):harness.run()
            harness.c.window.drag.assert_not_called();harness.c.window.click.assert_called_once()

    def test_failed_or_count_only_deployment_never_collects_or_retries_on_resume(self):
        for mode in ('unchanged','count_only','gold_changed'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as folder:
                harness=Harness(folder,mode=mode)
                self.assertEqual(harness.run().status,'partial')
                data=StandardSession(harness.path).data
                self.assertEqual(len(data['actions']),1);self.assertEqual(data['actions'][0]['status'],'unknown')
                harness.c.window.drag.assert_called_once();harness.c.window.click.assert_not_called()
                with self.assertRaises(AutomationError):harness.run()
                harness.c.window.drag.assert_called_once()

    def test_pause_in_held_drag_and_failed_intent_write_never_pick_up(self):
        with tempfile.TemporaryDirectory() as folder:
            harness=Harness(folder,mode='pause')
            with self.assertRaises(InputInterrupted):harness.run()
            self.assertTrue(harness.released);harness.c.window.click.assert_not_called()
            data=StandardSession(harness.path).data
            self.assertEqual(data['actions'][-1]['status'],'pending')
        with tempfile.TemporaryDirectory() as folder:
            harness=Harness(folder);persist=StandardSession.persist
            def failed(store):
                if store.data['actions'] and store.data['actions'][-1]['status']=='pending':raise OSError('synthetic write failure')
                return persist(store)
            with patch.object(StandardSession,'persist',failed),self.assertRaises(OSError):harness.run()
            harness.c.window.drag.assert_not_called();harness.c.window.click.assert_not_called()

    def test_changed_account_epoch_or_source_after_pending_never_dispatches_drag(self):
        for defect in ('account','epoch','source'):
            with self.subTest(defect=defect),tempfile.TemporaryDirectory() as folder:
                harness=Harness(folder)
                original=harness.checkpoint
                def checkpoint():
                    original()
                    store=getattr(harness.c,'currency_standard_session',None)
                    if store and store.data['actions'] and store.data['actions'][-1]['status']=='pending':
                        if defect=='epoch':harness.c.runner.input_epoch=1
                        elif defect=='account':
                            harness.c.last_scene.tokens=[replace(t,text='UID:200000000') if t.text.startswith('UID') else t for t in harness.c.last_scene.tokens]
                        else:_crop(harness.c.last_scene.image,bench_face(1))[:]=90
                harness.c.runner.checkpoint=checkpoint
                with self.assertRaises(AutomationError):harness.run()
                harness.c.window.drag.assert_not_called();harness.c.window.click.assert_not_called()


if __name__=='__main__':unittest.main()
