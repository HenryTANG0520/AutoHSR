"""An old character panel must never become another slot's fresh identity."""
from copy import deepcopy
from dataclasses import asdict
from itertools import count
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import numpy as np

from autohsr.currency_wars_collector import owned_profile
from autohsr.currency_wars_deployment import _crop,bench_face
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_collection import (STALE_CLOSE,board_feedback,close_current,current_source,
    ordinary,profile,stale)
from autohsr.currency_wars_standard_flow import next_action,run_standard,transition_ready
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.models import AutomationError,InputInterrupted,Scene,Stopped,Token,normalize
from autohsr.tests import test_currency_wars_standard_trading as trading
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_rewards as rewards
from autohsr.tests import test_currency_wars_standard_investment as investment


def uid(scene,value='100000000'):
    scene.tokens=[t for t in scene.tokens if not normalize(t.text).startswith('uid')]
    scene.tokens.append(Token('UID:'+value,.99,(.01,.96,.1,.99)))
    return scene


def fixture(*,wrong_panel=False):
    board,session=trading.full_board_fixture(gold=30)
    unit=deepcopy(session['collection']['units']['bench:5' if wrong_panel else 'bench:4']['unit'])
    panel=uid(exchange.panel(unit,'1-1'))
    signature=session['collection']['units']['bench:4']['signature'];run=session['account_verified_run']
    session['actions']=[dict(id=0,action='inspect_standard_unit',status='verified',expected='character',input_epoch=0,
        target=['bench',4,'1-1',signature],inspection_run_dir=run,before='board.png',after='panel.png')]
    session['inspecting']=dict(zone='bench',slot=4,node='1-1',signature=signature,inspection_action_id=0,
        input_epoch=0,run_dir=run,before='board.png',after='panel.png')
    session['collection']['units']={};session['collection']['complete']=False
    return board,panel,session


def stop_after(c,intent):
    def check():
        store=getattr(c,'currency_standard_session',None)
        if store and store.data['actions'] and store.data['actions'][-1]['action']==intent and store.data['actions'][-1]['status']=='verified':
            raise Stopped('collection boundary')
    c.checkpoint=check


def synchronize(folder,c,*,epoch=0,keep_old_epoch=False):
    store=StandardSession(Path(folder)/'currency-standard-session.json')
    c.runner.input_epoch=epoch
    c.scene_epoch=epoch
    store.data['account_verified_epoch']=epoch
    store.data['collection']['input_epoch']=epoch
    store.data['client']['input_epoch']=epoch
    store.data['inspecting']['run_dir']=c.report.run_dir
    store.data['actions'][0]['inspection_run_dir']=c.report.run_dir
    if not keep_old_epoch:
        store.data['inspecting']['input_epoch']=epoch;store.data['actions'][0]['input_epoch']=epoch
    store.persist()


class CollectionSourceTests(unittest.TestCase):
    def test_source_requires_the_actual_inspection_and_matching_nonce(self):
        _,_,session=fixture();self.assertTrue(current_source(session))
        for mutation in ('missing','index','epoch','run','source_run','before','after','target','expected','unknown','other_action'):
            data=deepcopy(session)
            if mutation=='missing':data['inspecting'].pop('inspection_action_id')
            elif mutation=='index':data['inspecting']['inspection_action_id']=4
            elif mutation=='epoch':data['inspecting']['input_epoch']=1
            elif mutation=='run':data['inspecting']['run_dir']='other'
            elif mutation=='source_run':data['actions'][0]['inspection_run_dir']='old'
            elif mutation in ('before','after'):data['inspecting'][mutation]='wrong.png'
            elif mutation=='target':data['actions'][0]['target'][1]=5
            elif mutation=='expected':data['actions'][0]['expected']='preparation'
            elif mutation=='unknown':data['actions'][0]['status']='unknown'
            else:data['actions'].append(dict(id=1,action='close_standard_unit',status='verified',input_epoch=0))
            with self.subTest(mutation=mutation):self.assertFalse(current_source(data))

    def test_fresh_profile_checks_the_current_account_before_reading_identity(self):
        _,panel,session=fixture()
        self.assertEqual((profile(panel,session).zone,profile(panel,session).slot),('bench',4))
        uid(panel,'200000000')
        with self.assertRaises(AutomationError):profile(panel,session)
        self.assertEqual(session['collection']['units'],{})

    def test_recommendations_need_the_same_slot_signature_epoch_and_character(self):
        _,panel,session=fixture();unit=owned_profile(panel,session['inspecting'])
        child=dict(id=1,action='open_standard_equipment_recommendations',status='verified',input_epoch=0,
            target=['bench',4,unit.name,session['inspecting']['signature']],before='panel.png',after='recommendations.png')
        session['actions'].append(child)
        self.assertTrue(current_source(session));self.assertEqual(profile(panel,session).name,unit.name)
        child['target'][2]='另一角色'
        with self.assertRaises(AutomationError):profile(panel,session)
        child['target'][1]=5;self.assertFalse(current_source(session))

    def test_old_panel_is_closed_before_any_identity_can_enter_the_new_collection(self):
        board,panel,session=fixture(wrong_panel=True)
        shown=owned_profile(panel,session['inspecting']).name
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[panel,board,board]);stop_after(c,STALE_CLOSE)
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(c.window.click.call_count,1)
            self.assertNotIn('collection',saved);self.assertNotIn('inspecting',saved)
            self.assertEqual(saved['collection_resets'][0]['inspecting']['slot'],4)
            self.assertEqual(saved['actions'][0]['status'],'verified')
            self.assertNotIn(shown,str(saved.get('collection',{})))
            self.assertEqual(ledger_status(saved['actions']),'clear')

    def test_pause_in_the_same_run_discards_the_old_panel_without_replaying_inspection(self):
        board,panel,session=fixture(wrong_panel=True)
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[panel,board,board])
            synchronize(folder,c,epoch=1,keep_old_epoch=True);stop_after(c,STALE_CLOSE)
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual([a['action'] for a in saved['actions']],['inspect_standard_unit',STALE_CLOSE])
            self.assertEqual(saved['actions'][-1]['input_epoch'],1)
            self.assertEqual(saved['collection_resets'][0]['inspecting']['input_epoch'],0)

    def test_reinspection_rebinds_the_correct_identity_after_a_stale_close(self):
        board,panel,session=fixture(wrong_panel=True)
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[panel,board,board]);stop_after(c,STALE_CLOSE)
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            saved['collection']=dict(run_dir=saved['account_verified_run'],input_epoch=0,units={},complete=False)
            _,right,_=fixture()
            second=Path(folder)/'second';second.mkdir()
            c=trading.StandardTradingTests().context(second,board,saved,[board,right,board,board]);stop_after(c,'close_standard_unit')
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            record=saved['collection']['units']['bench:4']
            self.assertEqual(record['unit']['name'],owned_profile(right,session['inspecting']).name)
            self.assertEqual(record['inspection_action_id'],2)
            self.assertEqual(record['run_dir'],c.report.run_dir)
            self.assertEqual(c.window.click.call_count,2)

    def test_formal_fresh_inspection_and_close_publish_their_own_source(self):
        board,panel,session=fixture();session['actions']=[];session.pop('inspecting')
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[board,panel,board,board]);stop_after(c,'close_standard_unit')
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            record=saved['collection']['units']['bench:4']
            self.assertEqual(record['inspection_action_id'],0)
            self.assertEqual(saved['actions'][0]['inspection_run_dir'],c.report.run_dir)
            self.assertNotIn('inspecting',saved);self.assertEqual(c.window.click.call_count,2)

    def test_close_feedback_needs_the_same_node_and_original_source_portrait(self):
        board,panel,session=fixture();unit=profile(panel,session)
        session['collection']['units']['bench:4']=dict(unit=asdict(unit))
        choice=next_action(panel,session=session)
        self.assertEqual(choice.expected,'standard_collected_unit_board')
        self.assertTrue(board_feedback(choice,board))
        for mutation in ('node','portrait','balance','hp'):
            after=Scene(list(board.tokens),board.image.copy())
            if mutation=='node':rewards.node(after,'1-2')
            elif mutation=='portrait':_crop(after.image,bench_face(4))[:]=np.random.default_rng(88).integers(0,256,_crop(after.image,bench_face(4)).shape,dtype=np.uint8)
            elif mutation=='balance':after.tokens=[t for t in after.tokens if not t.within((.851,.829,.87,.868))]
            else:after.tokens=[t for t in after.tokens if not t.within((.735,.05,.78,.095))]
            with self.subTest(mutation=mutation):self.assertFalse(transition_ready(choice,after))

    def test_old_source_cannot_reconcile_an_unknown_inspection_or_trade(self):
        _,panel,session=fixture();session['inspecting']['run_dir']='old'
        for name in ('inspect_standard_unit','buy_standard_offer'):
            data=deepcopy(session);data['actions'][0].update(action=name,status='unknown')
            with self.subTest(action=name),self.assertRaises(AutomationError):next_action(panel,session=data)

    def test_pending_stale_close_rederives_only_the_current_node(self):
        _,panel,session=fixture();session['inspecting']['run_dir']='old'
        choice=next_action(panel,session=session)
        session['actions'].append(dict(id=1,action=choice.intent,status='pending',expected=choice.expected,input_epoch=0,target=list(choice.payload)))
        self.assertEqual(next_action(panel,session=session),choice)
        rewards.node(panel,'1-2')
        with self.assertRaises(AutomationError):next_action(panel,session=session)

    def test_unknown_close_keeps_the_original_intention_and_cannot_publish_a_completed_roster(self):
        board,panel,session=fixture();session['actions']=[];session.pop('inspecting')
        changed=Scene(list(board.tokens),board.image.copy())
        _crop(changed.image,bench_face(4))[:]=np.random.default_rng(43).integers(0,256,_crop(changed.image,bench_face(4)).shape,dtype=np.uint8)
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[board,panel,changed,changed])
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',SimpleNamespace(monotonic=Mock(side_effect=count(0,31)))):
                self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'unknown')
            self.assertEqual(ledger_status(saved['actions']),'unknown')
            self.assertFalse(saved['collection']['complete']);self.assertEqual(c.window.click.call_count,2)
            with self.assertRaises(AutomationError):run_standard(c)
            self.assertEqual(c.window.click.call_count,2)

    def test_specialized_exchange_sale_equipment_and_reward_protocols_keep_their_own_scope(self):
        _,_,session=fixture()
        for key,status in (('exchange','verifying'),('equipment','verifying'),('sale','inspecting'),('reward','unit_verifying')):
            data=deepcopy(session);data[key]=dict(status=status);data['inspecting']['run_dir']='old'
            with self.subTest(protocol=key):self.assertFalse(ordinary(data));self.assertFalse(stale(data))

    def test_expired_gift_collection_can_close_readonly_without_settling_the_gift_obligation(self):
        board,scene,session=investment.fixture([('保守派',investment.DEFENSE)])
        board=investment.gift_board(board);investment.select_and_confirm(board,scene,session)
        _,panel,old=fixture(wrong_panel=True);session['inspecting']=old['inspecting'];rewards.node(panel,'2-1')
        self.assertEqual(next_action(panel,session=session).intent,STALE_CLOSE)
        rewards.node(panel,'2-2')
        with self.assertRaises(AutomationError):next_action(panel,session=session)
        rewards.node(panel,'2-1')
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[panel,board,board]);stop_after(c,STALE_CLOSE)
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(ledger_status(saved['actions']),'pending')
            self.assertEqual(saved['investment']['status'],'reward_verifying')
            self.assertFalse(saved['actions'][4]['investment_verified']);self.assertEqual(c.window.click.call_count,1)
            self.assertNotIn('collection',saved)

    def test_pause_account_or_write_failure_never_erases_the_old_source_or_resends_input(self):
        for case in ('pause','account','write','receipt'):
            board,panel,session=fixture(wrong_panel=True)
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c=trading.StandardTradingTests().context(folder,board,session,[panel,board,board])
                if case=='pause':c.currency_standard_input.side_effect=InputInterrupted('paused')
                snapshot=c.snapshot
                def read():
                    scene=snapshot()
                    if case=='account' and scene is board:uid(scene,'200000000')
                    return scene
                c.snapshot=read;persist=StandardSession.persist
                def save(store):
                    last=store.data['actions'][-1]
                    if case=='write' and last['action']==STALE_CLOSE:raise OSError('close write failed')
                    if case=='receipt' and last['action']==STALE_CLOSE and last['status']=='verified':raise OSError('result write failed')
                    return persist(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',save),self.assertRaises((AutomationError,OSError)):
                    run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertIn('inspecting',saved);self.assertNotIn('collection_resets',saved)
                if case=='write':self.assertEqual(len(saved['actions']),1)
                else:self.assertEqual(saved['actions'][-1]['status'],'pending')
                self.assertEqual(c.window.click.call_count,0 if case in ('pause','write') else 1)


if __name__=='__main__':unittest.main()
