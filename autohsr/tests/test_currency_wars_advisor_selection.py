"""An accepted advisor selection is distinct from a delivered unit or purchase."""
from copy import deepcopy
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from autohsr.currency_wars_character_rewards import observe_shop
from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop,bench_face
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import StandardAction,next_action,run_standard
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_standard_rewards import active_action,basis,enter,feedback,verify_unit,valid_effect
from autohsr.models import AutomationError,Scene,Stopped,Token,normalize
from autohsr.tests import test_currency_wars_character_rewards as character
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_trading as trading


def selection(*,empty=False,extra_box=False,source='bench',kind='expert_selection'):
    def setup(board,session):
        # The trade fixture's synthetic weak units have no trait tokens;
        # advisor identity comparisons use actual readable trait panels.
        for record in session['collection']['units'].values():
            if not record['unit'].get('traits'):record['unit']['traits']=('测试',)
        if empty:
            for cell in roster_cells(board):_crop(board.image,cell.roi)[:]=0
            trading.hud(board,deployment=(0,3))
            session['collection'].update(complete=False,units={})
        if extra_box:
            roi=bench_face(8);patch=_crop(board.image,roi)
            patch[:]=np.random.default_rng(88).integers(0,256,patch.shape,dtype=np.uint8)
            x=(roi[0]+roi[2])/2
            board.tokens.append(Token('开启',.99,(x-.015,.819,x+.015,.866)))
    before,page,session=character.fixture(kind,modify=setup)
    if source=='crystal':
        before.tokens=[t for t in before.tokens if not (normalize(t.text)=='开启' and t.within((.33,.78,.38,.92)))]
        _crop(before.image,bench_face(3))[:]=0
        parent=session['actions'][0]
        parent.update(action='collect_standard_loot',target=[.7,.34,.01])
        parent['reward_basis']=basis(before,session,'collect_standard_loot')
        session.pop('reward')
        page=character.modal(before,kind,('银狼','刃','青雀','停云','现金为王'))
        enter(session,StandardAction('collect_standard_loot','loot_collected',None,payload=(.7,.34,.01)),page)
    choice=active_action(page,session)
    after=Scene([t for t in before.tokens if not (normalize(t.text)=='开启' and t.within((.33,.78,.38,.92)))],
                before.image.copy(),captured_at=time.monotonic())
    _crop(after.image,bench_face(3))[:]=0
    return before,page,session,choice,after,deepcopy(session['collection']['units'])


def verify(session,choice,after,units):
    action=character.receipt(session,choice,after)
    session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
    character.collect(session,after,units)
    problem=verify_unit(session,after,0)
    return action,problem


def context_states(page,after,units):
    states=[page,after,after]
    for cell in sorted((c for c in roster_cells(after) if c.state=='occupied'),key=lambda c:(c.zone!='bench',c.zone,c.slot)):
        unit=units[cell.zone+':'+str(cell.slot)]['unit']
        states.extend((equipment.panel(unit,unit['equipment']),after))
    return states


def stop_verified(c):
    def check():
        store=getattr(c,'currency_standard_session',None)
        if store and store.data.get('reward',{}).get('status')=='verified':raise Stopped('selection verified')
    c.checkpoint=check


def quote(*,advisor=True,price=True):
    _,shop,_=trading.purchase_fixture();trading.hud(shop,gold=25)
    left=.192
    shop.tokens=[t for t in shop.tokens if not t.within((left,.265,left+.125,.305))]
    shop.tokens.append(Token('银狼' if advisor else '其他角色',.99,(left,.27,left+.09,.30)))
    if price:shop.tokens.append(Token('6',.99,(left+.109,.27,left+.125,.30)))
    return shop


class AdvisorSelectionTests(unittest.TestCase):
    def test_unchanged_roster_settles_only_an_accepted_advisor_selection(self):
        for source in ('bench','crystal'):
            before,page,session,choice,after,units=selection(source=source)
            self.assertTrue(feedback(choice,page,after,session))
            action,problem=verify(session,choice,after,units)
            with self.subTest(source=source):
                self.assertIsNone(problem);self.assertTrue(action['reward_verified'])
                self.assertEqual(action['reward_effect']['delivery_kind'],'advisor_selection')
                self.assertIs(action['reward_effect']['unit_verified'],False)
                self.assertTrue(action['reward_effect']['roster_unchanged'])
                self.assertNotIn('advisor_shop_observations',session)
                self.assertNotIn('purchase_verified',action['reward_effect'])
                self.assertEqual(session['action_status'],'advisor_selected')
                self.assertEqual(ledger_status(session['actions']),'clear')
                self.assertIn(next_action(after,session=session).intent,('open_standard_shop','inspect_standard_sale_unit'))

    def test_known_empty_roster_can_finish_and_open_the_shop_without_an_identity_fallback(self):
        before,page,session,choice,after,units=selection(empty=True)
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,[page,after,after])
            stop_verified(c)
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertTrue(saved['collection']['complete']);self.assertEqual(saved['collection']['units'],{})
            self.assertEqual(saved['actions'][1]['reward_effect']['roster_after'],[])
            self.assertEqual(ledger_status(saved['actions']),'clear');self.assertEqual(c.window.click.call_count,1)
            self.assertEqual(next_action(after,session=saved).intent,'open_standard_shop')
        bad=Scene(list(after.tokens),after.image.copy())
        trading.hud(bad,deployment=(1,3))
        with self.assertRaises(AutomationError):next_action(bad,session=saved)
        saved['collection']['units']['bench:4']={'unit':{'name':'旧缓存'}}
        with self.assertRaises(AutomationError):next_action(after,session=saved)

    def test_formal_context_reads_every_owned_unit_before_settling_a_selection(self):
        before,page,session,choice,after,units=selection()
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,context_states(page,after,units))
            stop_verified(c)
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(sum(a['action']=='inspect_standard_reward_unit' for a in saved['actions']),len(units))
            self.assertEqual(sum(a['action']=='choose_standard_reward' for a in saved['actions']),1)
            self.assertFalse(saved['actions'][1]['reward_effect']['unit_verified'])
            self.assertEqual(saved['actions'][1]['reward_effect']['delivery_kind'],'advisor_selection')
            self.assertEqual(ledger_status(saved['actions']),'clear');self.assertFalse(saved['completion_verified'])

    def test_no_unit_contract_is_still_a_mismatch(self):
        before,page,session,choice,after,units=selection(kind='hiring_selection')
        action,problem=verify(session,choice,after,units)
        self.assertIsNotNone(problem);self.assertFalse(action['reward_verified'])
        self.assertEqual(session['reward']['status'],'unit_mismatch')
        self.assertEqual(ledger_status(session['actions']),'pending')

    def test_moved_missing_changed_or_unknown_owned_units_do_not_settle_as_a_selection(self):
        for mutation in ('position','missing','star','tier','gear','trait','unknown'):
            before,page,session,choice,after,units=selection()
            unit=units['bench:4']['unit']
            if mutation=='position':
                _crop(after.image,bench_face(6))[:]=_crop(after.image,bench_face(4))
                _crop(after.image,bench_face(4))[:]=0
                unit['slot']=6;units['bench:6']=units.pop('bench:4')
            elif mutation=='missing':
                _crop(after.image,bench_face(4))[:]=0;units.pop('bench:4')
            elif mutation=='star':unit['star']=3
            elif mutation=='tier':unit['tier']=5
            elif mutation=='gear':unit['equipment']=('armor',)
            elif mutation=='trait':unit['traits']=('改变的羁绊',)
            else:unit['equipment']=None
            action=character.receipt(session,choice,after)
            session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
            character.collect(session,after,units)
            with self.subTest(mutation=mutation):
                verify_unit(session,after,0)
                self.assertFalse(action['reward_verified'])
                self.assertNotEqual(ledger_status(session['actions']),'clear')

    def test_unconsumed_invitation_or_changed_other_reward_cannot_settle_the_selection(self):
        for mutation in ('same_box','other_box'):
            before,page,session,choice,after,units=selection(extra_box=True)
            if mutation=='same_box':after=before
            else:_crop(after.image,bench_face(8))[:]=0
            self.assertFalse(feedback(choice,page,after,session))

    def test_remaining_boxes_are_preserved_during_character_recollection_and_opened_next(self):
        for delivered in (False,True):
            before,page,session,choice,after,units=selection(extra_box=True)
            if delivered:
                after,units=character.delivered(before,session,choice)
                after.tokens.extend(t for t in before.tokens if normalize(t.text)=='开启' and t.within((.63,.78,.75,.92)))
            self.assertTrue(feedback(choice,page,after,session))
            action,problem=verify(session,choice,after,units)
            with self.subTest(delivered=delivered):
                self.assertIsNone(problem);self.assertTrue(action['reward_verified'])
                self.assertEqual(action['reward_effect']['unit_verified'],delivered)
                self.assertEqual(session['reward']['after_reward_items'].keys(),{'bench:8'})
                opening=next_action(after,session=session)
                self.assertEqual(opening.intent,'open_standard_bench_reward');self.assertEqual(opening.payload[1],8)

    def test_changed_remaining_reward_during_inspection_stays_unsettled(self):
        before,page,session,choice,after,units=selection(extra_box=True)
        action=character.receipt(session,choice,after)
        session['collection']=dict(run_dir=session['account_verified_run'],input_epoch=0,units={},complete=False)
        character.collect(session,after,units)
        _crop(after.image,bench_face(8))[:]=20
        self.assertIsNotNone(verify_unit(session,after,0));self.assertFalse(action['reward_verified'])

    def test_damaged_selection_receipt_cannot_clear_the_ledger_or_claim_unlock_or_purchase(self):
        before,page,session,choice,after,units=selection()
        action,problem=verify(session,choice,after,units)
        self.assertIsNone(problem);self.assertTrue(valid_effect(action,session['actions']))
        for mutation in ('unit','kind','flag','roster','position','source','stars','gear','unlock','purchase'):
            actions=deepcopy(session['actions']);effect=actions[1]['reward_effect']
            if mutation=='unit':effect['unit_verified']=True
            elif mutation=='kind':effect['delivery_kind']='unit'
            elif mutation=='flag':effect['advisor_selection_verified']=False
            elif mutation=='roster':effect['roster_after'][0]['star']=4
            elif mutation=='position':effect['roster_after'][0]['slot']=6
            elif mutation=='source':effect['accepted_selection']['action_id']=3
            elif mutation=='stars':effect['stars_after']=[1]
            elif mutation=='gear':effect['equipment_after']=['armor']
            elif mutation=='unlock':effect['advisor_unlock_verified']=True
            else:effect['purchase_verified']=True
            with self.subTest(mutation=mutation):self.assertEqual(ledger_status(actions),'unknown')

    def test_only_later_priced_quote_proves_availability_for_an_accepted_selection(self):
        before,page,session,choice,after,units=selection()
        action,problem=verify(session,choice,after,units);self.assertIsNone(problem)
        for advisor,price in ((False,True),(True,False),(True,True)):
            current=deepcopy(session);shop=quote(advisor=advisor,price=price)
            opening=dict(id=2,action='open_standard_shop',status='verified',input_epoch=0,before='board.png',after='shop.png')
            current['actions'].append(opening);observe_shop(current,shop,opening)
            with self.subTest(advisor=advisor,price=price):
                self.assertEqual(bool(current.get('advisor_shop_observations')),advisor and price)
                self.assertFalse(current['actions'][1]['reward_effect']['unit_verified'])
                self.assertNotIn('purchase_verified',current['actions'][1]['reward_effect'])

    def test_formal_shop_observation_after_selection_never_creates_a_purchase(self):
        for advisor in (False,True):
            before,page,session,choice,after,units=selection(empty=True)
            action,problem=verify(session,choice,after,units);self.assertIsNone(problem)
            shop=quote(advisor=advisor)
            with self.subTest(advisor=advisor),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,after,session,[after,shop])
                def stop_open():
                    store=getattr(c,'currency_standard_session',None)
                    if store and store.data['actions'][-1].get('action')=='open_standard_shop' and store.data['actions'][-1]['status']=='verified':
                        raise Stopped('shop observed')
                c.checkpoint=stop_open
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertEqual(c.window.click.call_count,1)
                self.assertEqual(bool(saved.get('advisor_shop_observations')),advisor)
                self.assertFalse(any(a['action']=='buy_standard_offer' for a in saved['actions']))
                self.assertFalse(saved['actions'][1]['reward_effect']['unit_verified'])
                self.assertEqual(ledger_status(saved['actions']),'clear')

    def test_formal_recollection_keeps_the_next_box_as_a_separate_unclaimed_reward(self):
        before,page,session,choice,after,units=selection(extra_box=True)
        next_page=character.old.modal('equipment_selection',after)
        states=context_states(page,after,units)+[next_page]
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,states)
            def stop_open():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data['actions'][-1].get('action')=='open_standard_bench_reward' and store.data['actions'][-1]['id']>1 and store.data['actions'][-1]['status']=='verified':
                    raise Stopped('next box opened')
            c.checkpoint=stop_open
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['reward_history'][-1]['delivery_kind'],'advisor_selection')
            self.assertEqual(saved['reward']['status'],'awaiting');self.assertEqual(saved['reward']['page'],'equipment_selection')
            self.assertTrue(saved['reward']['basis']['snapshot']['roster_complete'])
            self.assertEqual(saved['actions'][-1]['target'][1],8)
            self.assertEqual(sum(a['action']=='choose_standard_reward' for a in saved['actions']),1)
            c.window.click_held.assert_called_once()

    def test_selection_receipt_write_failure_recomputes_from_a_fresh_board_without_reclaiming(self):
        before,page,session,choice,after,units=selection()
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,before,session,context_states(page,after,units))
            persist=StandardSession.persist
            def save(store):
                if store.data.get('action_status')=='advisor_selected':raise OSError('receipt write failed')
                return persist(store)
            with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',save),self.assertRaises(OSError):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['reward']['status'],'unit_verifying');self.assertEqual(ledger_status(saved['actions']),'pending')
            count=c.window.click.call_count;stop_verified(c)
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            self.assertEqual(c.window.click.call_count,count)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(ledger_status(saved['actions']),'clear')
            self.assertEqual(sum(a['action']=='choose_standard_reward' for a in saved['actions']),1)


if __name__=='__main__':unittest.main()
