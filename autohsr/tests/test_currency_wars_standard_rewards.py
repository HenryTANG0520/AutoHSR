"""Reward origin, choice, confirmation and delivery are different evidence."""
from copy import deepcopy
from dataclasses import asdict
from itertools import count
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import re

import numpy as np

from autohsr.currency_wars_collector import collected_snapshot, roster_cells
from autohsr.currency_wars_deployment import _crop, bench_face
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard, transition_ready
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_progress import advancement_feedback
from autohsr.currency_wars_standard_rewards import (PAGES, active_action, basis, bind_source, enter, feedback,
    open_bench_action, returned, valid_effect, _options)
from autohsr.models import AutomationError, InputInterrupted, Scene, Stopped, Token, normalize
from autohsr.tests import test_currency_wars_standard_trading as trading_helpers
from autohsr.tests import test_currency_wars_standard_exchange as exchange_helpers
from autohsr.tests import test_currency_wars_standard_equipment as equipment_helpers
from autohsr.tests.test_currency_wars_node import screen


def node(scene, value):
    scene.tokens = [t for t in scene.tokens if not (t.within((.1,.02,.30,.14)) and re.fullmatch(r'[1-3]-[0-9]+',t.text))]
    scene.tokens.append(Token(value,.99,(.137,.085,.16,.115)))
    return scene


def modal(kind, board, gold=25, destination='1-1'):
    if kind=='advanced_equipment_selection':
        import json
        data=json.loads((Path(__file__).parent/'fixtures/currency_wars_advanced_box.json').read_text(encoding='utf-8'))
        scene=Scene([Token(**t) for t in data['tokens']])
    else:
        scene=screen(kind)
    scene.image=board.image.copy();scene.captured_at=time.monotonic()
    node(scene,destination)
    trading_helpers.hud(scene,gold=gold,level=3,xp=(0,6),deployment=(3,3))
    return scene


def box(kind='equipment_selection', strategy='default', cash=4):
    before,session=trading_helpers.full_board_fixture(gold=25)
    session['strategy']=strategy
    _crop(before.image,bench_face(3))[:]=np.random.default_rng(22).integers(0,256,_crop(before.image,bench_face(3)).shape,dtype=np.uint8)
    before.tokens.append(Token('开启',.99,(.344,.819,.371,.866)))
    choice=open_bench_action(before,session)
    source=basis(before,session,choice.intent)
    action=dict(id=0,action=choice.intent,status='verified',input_epoch=0,target=list(choice.payload),
                before='before.png',after='modal.png',reward_basis=source)
    session['actions'].append(action)
    page=modal(kind,before)
    if kind=='expert_selection':
        page.tokens=[t for t in page.tokens if not t.within((.81,.25,.85,.30))]
        page.tokens.append(Token(str(cash),.99,(.828,.26,.849,.292)))
    enter(session,choice,page)
    return before,page,session


def delivered_box(before, choice):
    after=Scene([t for t in before.tokens if normalize(t.text)!='开启'],before.image.copy(),captured_at=time.monotonic())
    _crop(after.image,bench_face(3))[:]=0
    trading_helpers.hud(after,gold=25+choice.payload[7])
    if choice.payload[5]:equipment_helpers.place(after.image,choice.payload[5],(2460,330))
    return after


def supply_fixture(count_options=5, strategy='default'):
    before,session=trading_helpers.full_board_fixture(gold=25)
    session['strategy']=strategy
    source=basis(before,session,'start_standard_node')
    session['actions']=[dict(id=0,action='start_standard_node',status='verified',input_epoch=0,target=['1-1',25,100,3],
                             before='before.png',after='result.png',reward_basis=source),
                        dict(id=1,action='continue_standard_node',status='verified',input_epoch=0,target=['1-1',0],
                             before='result.png',after='supply.png',feedback=dict(page_kind='supply_selection',node='1-2'))]
    session['node_attempt']=dict(node='1-1',start_action_id=0,status='advanced',node_verified=True,result='result.png',result_kind='node_result')
    page=modal('supply_selection',before,destination='1-2')
    # These cases isolate selection/delivery after the refresh quota is spent.
    # Dedicated refresh fixtures restore a positive count and its visible Q control.
    page.tokens=[Token('剩余次数：0',t.score,t.box) if normalize(t.text).startswith('剩余次数') else t for t in page.tokens]
    if count_options==4:
        names=[('新角色甲','轮滑鞋'),('新角色乙','光能电池'),('希儿','折叠小刀'),('新角色丁','量产型装甲')]
        page.tokens=[t for t in page.tokens if not t.within((.03,.50,.97,.55)) and not t.within((.03,.61,.97,.67))]
        for x,(name,item) in zip((.223,.407,.592,.777),names):
            page.tokens += [Token(name,.99,(x-.04,.505,x+.04,.54)),Token(item,.99,(x-.05,.62,x+.05,.66))]
    from autohsr.currency_wars_standard_flow import StandardAction
    enter(session,StandardAction('continue_standard_node','standard_node_advanced',None,payload=('1-1',0)),page)
    return before,page,session


def selected(page, session):
    choice=active_action(page,session)
    after=Scene(list(page.tokens),page.image.copy(),captured_at=time.monotonic())
    after.tokens=[Token(t.text.replace('已选择0/1','已选择1/1'),t.score,t.box) for t in after.tokens]
    x=choice.target.center[0]
    _crop(after.image,(x-.065,.59,x+.065,.69))[:]=240
    return choice,after


def supply_board(before, choice, missing=False):
    after=Scene(list(before.tokens),before.image.copy(),captured_at=time.monotonic());node(after,'1-3')
    equipment_helpers.place(after.image,choice.payload[5],(2460,330))
    if not missing:
        _crop(after.image,bench_face(6))[:]=np.random.default_rng(55).integers(0,256,_crop(after.image,bench_face(6)).shape,dtype=np.uint8)
    return after


class StandardRewardTests(unittest.TestCase):
    def test_boxes_rank_actual_known_gear_for_the_frozen_core_strategy(self):
        for strategy,kind,expected in (('default','equipment_selection','armor'),('aglaea','equipment_selection','shoe'),
                                       ('aglaea','advanced_equipment_selection','boots'),('default','advanced_equipment_selection','hard_armor')):
            before,page,session=box(kind,strategy)
            choice=active_action(page,session)
            self.assertEqual(choice.payload[5],expected)
            self.assertEqual(next_action(page,session=session),choice)
            self.assertTrue(feedback(choice,page,delivered_box(before,choice),session))
            session['actions'].append(dict(id=1,action=choice.intent,status='pending',input_epoch=0,target=list(choice.payload),expected=choice.expected))
            self.assertEqual(next_action(page,session=session),choice)

    def test_cash_is_observed_not_fixed_and_receipt_needs_matching_income(self):
        for amount in (0,1,2,3,4,12,99):
            before,page,session=box('expert_selection',cash=amount)
            choice=active_action(page,session)
            self.assertEqual(choice.payload[7],amount)
            page.tokens.append(Token(str(amount),.99,(.828,.26,.849,.292)))
            self.assertEqual(active_action(page,session),choice)
            after=delivered_box(before,choice)
            self.assertTrue(feedback(choice,page,after,session))
            trading_helpers.hud(after,gold=24+amount)
            self.assertFalse(feedback(choice,page,after,session))
            page.tokens.append(Token(str((amount+1)%100),.99,(.828,.26,.849,.292)))
            with self.assertRaises(AutomationError):active_action(page,session)

    def test_missing_origin_changed_candidates_missing_price_and_unknown_gear_do_not_fall_back(self):
        for mutation in ('origin','version','gold','missing','cash','unknown'):
            _,page,session=box('expert_selection' if mutation=='cash' else 'equipment_selection')
            if mutation=='origin':session.pop('reward')
            elif mutation=='version':session['client']['version']='4.7'
            elif mutation=='gold':trading_helpers.hud(page,gold=26)
            elif mutation=='missing':page.tokens=[t for t in page.tokens if normalize(t.text)!='量产型装甲']
            elif mutation=='cash':page.tokens=[t for t in page.tokens if not t.within((.81,.25,.85,.30))]
            else:
                for i,x in enumerate((.346,.497,.647,.799)):
                    page.tokens=[t for t in page.tokens if not t.within((x-.065,.25,x+.065,.29))]
                    page.tokens.append(Token('未知装备',.99,(x-.04,.255,x+.04,.285)))
            with self.subTest(mutation=mutation),self.assertRaises(AutomationError):active_action(page,session)

    def test_supply_four_and_five_pairs_select_then_confirm_the_same_visible_card(self):
        for count_options in (4,5):
            _,page,session=supply_fixture(count_options,'seele')
            choice,after=selected(page,session)
            self.assertEqual(len(_options(page,'supply_selection',.65)),count_options)
            session['actions'].append(dict(id=2,action=choice.intent,status='verified',input_epoch=0,target=list(choice.payload),before='p.png',after='s.png'))
            confirm=active_action(after,session)
            self.assertEqual(confirm.intent,'confirm_standard_supply')
            self.assertEqual(confirm.payload,choice.payload)
            after.image[:]=0
            with self.assertRaises(AutomationError):active_action(after,session)

    def test_supply_arrival_and_return_are_adjacent_nodes_and_extra_supply_has_explicit_source(self):
        before,page,session=supply_fixture()
        self.assertEqual(advancement_feedback(page,'1-1'),dict(page_kind='supply_selection',node='1-2'))
        choice,highlight=selected(page,session)
        session['actions'].append(dict(id=2,action=choice.intent,status='verified',input_epoch=0,target=list(choice.payload),before='p.png',after='s.png'))
        choice=active_action(highlight,session);after=supply_board(before,choice)
        self.assertTrue(feedback(choice,page,after,session))
        for other in ('1-1','1-2','1-4','2-1'):
            node(after,other);self.assertFalse(feedback(choice,page,after,session),other)
        session['reward']['same_node_supply_allowed']=True;node(after,'1-2')
        self.assertTrue(feedback(choice,page,after,session))

    def test_full_context_opens_a_box_once_with_held_click_and_records_verified_gear(self):
        before,page,session=box();session['actions']=[];session.pop('reward')
        opening=open_bench_action(before,session)
        # Recreate only expected fixture effects; execution derives its own choice.
        _,_,ready=box();choose=active_action(page,ready);after=delivered_box(before,choose)
        with tempfile.TemporaryDirectory() as folder:
            c=exchange_helpers.StandardExchangeTests().context(folder,before,session,[before,page,after,after])
            def stop_done():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data.get('reward',{}).get('status')=='verified':raise Stopped('box fixture complete')
            c.checkpoint=stop_done
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual([a['action'] for a in saved['actions']],['open_standard_bench_reward','choose_standard_reward'])
            self.assertTrue(saved['actions'][-1]['reward_verified'])
            self.assertEqual(ledger_status(saved['actions']),'clear')
            c.window.click_held.assert_called_once();c.window.click.assert_called_once()
            self.assertFalse(saved['completion_verified'])

    def test_full_supply_effect_recollects_all_units_before_reporting_delivery(self):
        for count_options in (4,5):
            before,page,session=supply_fixture(count_options)
            choice,highlight=selected(page,session);after=supply_board(before,choice)
            units=deepcopy(session['collection']['units'])
            for record in units.values():record['unit']['equipment']=()
            units['bench:6']=dict(unit=dict(name=choice.payload[6],zone='bench',slot=6,star=1,tier=1,
                traits=('测试',),equipment=(),eligible_zones=('front','back')))
            cells=sorted((cell for cell in roster_cells(after) if cell.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot))
            states=[page,highlight,highlight,after,after]
            for cell in cells:
                states += [exchange_helpers.panel(units[cell.zone+':'+str(cell.slot)]['unit'],'1-3'),after]
            with self.subTest(count_options=count_options),tempfile.TemporaryDirectory() as folder:
                c=trading_helpers.StandardTradingTests().context(folder,before,session,states)
                def stop_done():
                    store=getattr(c,'currency_standard_session',None)
                    if store and store.data.get('reward',{}).get('status')=='verified':raise Stopped('supply delivered')
                c.checkpoint=stop_done
                with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3),self.assertRaises(Stopped):
                    run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                claim=next(a for a in saved['actions'] if a['action']=='confirm_standard_supply')
                self.assertTrue(claim['reward_verified']);self.assertTrue(claim['reward_effect']['unit_verified'])
                self.assertEqual(claim['reward_effect']['stars_before'],[])
                self.assertEqual(claim['reward_effect']['stars_after'],[1])
                self.assertEqual(len(saved['collection']['units']),len(cells))
                self.assertEqual(ledger_status(saved['actions']),'clear')

    def test_missing_supply_unit_cannot_be_marked_complete_or_claimed_again(self):
        before,page,session=supply_fixture();choice,highlight=selected(page,session);after=supply_board(before,choice,True)
        units=deepcopy(session['collection']['units'])
        states=[page,highlight,highlight,after,after]
        for cell in sorted((c for c in roster_cells(after) if c.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot)):
            states += [exchange_helpers.panel(units[cell.zone+':'+str(cell.slot)]['unit'],'1-3'),after]
        with tempfile.TemporaryDirectory() as folder:
            c=trading_helpers.StandardTradingTests().context(folder,before,session,states)
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3),self.assertRaises(AutomationError):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['reward']['status'],'unit_mismatch')
            claim=next(a for a in saved['actions'] if a['action']=='confirm_standard_supply')
            self.assertFalse(claim['reward_verified']);self.assertEqual(ledger_status(saved['actions']),'pending')
            count_before=c.window.click.call_count
            with patch('autohsr.currency_wars_replay.save_sample'):
                self.assertEqual(run_standard(c).status,'partial')
            self.assertEqual(c.window.click.call_count,count_before)

    def test_unchanged_or_extra_inventory_changes_never_verify_a_claim(self):
        before,page,session=box();choice=active_action(page,session)
        for mutation in ('unchanged','extra','unit','node','money'):
            after=delivered_box(before,choice)
            if mutation=='unchanged':after.image=before.image.copy()
            elif mutation=='extra':equipment_helpers.place(after.image,'star',(2460,430))
            elif mutation=='unit':_crop(after.image,bench_face(4))[:]=0
            elif mutation=='node':node(after,'1-2')
            else:trading_helpers.hud(after,gold=24)
            with self.subTest(mutation=mutation):self.assertFalse(feedback(choice,page,after,session))

    def test_named_reward_strategy_collects_before_opening_and_never_treats_unknown_gear_as_empty(self):
        before,page,session=box(strategy='aglaea')
        self.assertFalse(collected_snapshot(before,session,0,'ordinary_trade').roster_complete)
        self.assertTrue(session['reward']['basis']['snapshot']['roster_complete'])
        incomplete=deepcopy(session);incomplete['reward']['basis']['snapshot']['roster_complete']=False
        with self.assertRaises(AutomationError):active_action(page,incomplete)
        unknown=deepcopy(session)
        unknown['reward']['basis']['snapshot']['roster'].append(dict(name='阿格莱雅',equipment=None))
        with self.assertRaises(AutomationError):active_action(page,unknown)
        session.pop('reward');session['actions']=[];session['collection']['units']={}
        self.assertEqual(next_action(before,session=session).intent,'inspect_standard_unit')

    def test_hidden_box_money_still_uses_its_preopening_balance_and_cash_needs_current_money(self):
        before,page,session=box()
        page.tokens=[t for t in page.tokens if not t.within((.851,.829,.87,.868))]
        session['reward']['money_observed']=False
        self.assertIsNone(read_match(page,include_rewards=True).gold)
        choice=active_action(page,session);after=delivered_box(before,choice)
        self.assertTrue(feedback(choice,page,after,session))
        trading_helpers.hud(after,gold=26)
        self.assertFalse(feedback(choice,page,after,session))
        _,page,session=box('expert_selection')
        page.tokens=[t for t in page.tokens if not t.within((.851,.829,.87,.868))]
        with self.assertRaises(AutomationError):active_action(page,session)

    def test_reward_receipts_reject_mismatched_effects_origins_and_damaged_shapes(self):
        before,page,session=box();choice=active_action(page,session)
        session['actions'].append(dict(id=1,action=choice.intent,status='verified',input_epoch=0,
            target=list(choice.payload),before='choice.png',after='delivered.png'))
        returned(session,choice,delivered_box(before,choice))
        self.assertEqual(ledger_status(session['actions']),'clear')
        for field,value in (('item','knife'),('gold',3),('unit','希儿'),('node_after','1-2'),('inventory_checked',False)):
            actions=deepcopy(session['actions']);actions[-1]['reward_effect'][field]=value
            with self.subTest(effect=field):self.assertEqual(ledger_status(actions),'unknown')
        for index,value in ((1,{}),(2,[]),(3,4),(5,[]),(6,'希儿'),(7,True),(8,None)):
            actions=deepcopy(session['actions']);actions[-1]['target'][index]=value
            with self.subTest(target=index):self.assertEqual(ledger_status(actions),'unknown')
        for value in (None,[],{'node':'2-1'}):
            actions=deepcopy(session['actions']);actions[0]['reward_basis']=value
            with self.subTest(basis=value):self.assertEqual(ledger_status(actions),'unknown')
        before,page,session=supply_fixture();select,highlight=selected(page,session)
        session['actions'].append(dict(id=2,action=select.intent,status='verified',input_epoch=0,
            target=list(select.payload),before='options.png',after='selected.png'))
        claim=active_action(highlight,session)
        session['actions'].append(dict(id=3,action=claim.intent,status='verified',input_epoch=0,
            target=list(claim.payload),before='selected.png',after='delivered.png'))
        returned(session,claim,supply_board(before,claim))
        self.assertEqual(ledger_status(session['actions']),'pending')
        for mutation in ('selection','source','kind','unit','stars'):
            actions=deepcopy(session['actions'])
            if mutation=='selection':actions[2]['target'][3]=(actions[2]['target'][3]+1)%5
            elif mutation=='source':actions[1]['feedback']['node']='2-1'
            elif mutation=='kind':actions[-1]['action']='choose_standard_reward'
            elif mutation=='unit':actions[-1]['target'][6]=[]
            else:
                actions[-1]['reward_verified']=True
                actions[-1]['reward_effect'].update(unit_verified=True,other_roster_verified=True,stars_before=[1],stars_after=[1])
            with self.subTest(supply=mutation):self.assertEqual(ledger_status(actions),'unknown')

    def test_unknown_claim_feedback_remains_durable_and_is_not_replayed(self):
        before,page,session=box()
        with tempfile.TemporaryDirectory() as folder:
            c=trading_helpers.StandardTradingTests().context(folder,before,session,[page,page,page])
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',SimpleNamespace(monotonic=Mock(side_effect=count(0,31)))):
                self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'unknown')
            with self.assertRaises(AutomationError):run_standard(c)
            c.window.click.assert_called_once()

    def test_write_pause_and_account_failures_do_not_settle_a_claim(self):
        for case in ('write','pause','account'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                before,page,session=box();after=delivered_box(before,active_action(page,session))
                c=trading_helpers.StandardTradingTests().context(folder,before,session,[page,after,after])
                original_input=c.currency_standard_input.side_effect
                if case=='pause':c.currency_standard_input.side_effect=InputInterrupted('pause')
                snapshot=c.snapshot
                def read():
                    current=snapshot()
                    if case=='account' and current is after:
                        current.tokens=[Token('UID:200000000',t.score,t.box) if t.text.startswith('UID:') else t for t in current.tokens]
                    return current
                c.snapshot=read
                original=StandardSession.persist
                def persist(store):
                    if case=='write' and store.data['actions'][-1]['action']=='choose_standard_reward':raise OSError('claim write failed')
                    return original(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',persist),self.assertRaises((AutomationError,OSError)):
                    run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                if case=='write':self.assertEqual(len(saved['actions']),1)
                else:self.assertEqual(saved['actions'][-1]['status'],'pending')
                self.assertEqual(c.window.click.call_count,1 if case=='account' else 0)


if __name__=='__main__':unittest.main()
