"""The whole worn set is re-read; no guessed roll, item count or benefit."""
from copy import deepcopy
from dataclasses import replace
from itertools import count
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

from autohsr.currency_wars_collector import collected_snapshot,roster_cells
from autohsr.currency_wars_consumables import stock,counts
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_consumables import (STAGE,proposal,bind_intent,feedback,valid_effect)
from autohsr.currency_wars_standard_flow import run_standard,next_action
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.currency_wars_worn_reforge import eligible,quality,worn_target
from autohsr.models import AutomationError,Stopped
from autohsr.tests import test_currency_wars_consumables as tools
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_trading as trading


def fixture(worn=('armor',),*,strategy='aglaea',quantity=2,zone='front',lower=False):
    board,session=tools.fixture('stove',quantity,strategy=strategy,worn=worn)
    # Clear the icon AND badge extent to the same empty-slot background.
    board.image[286:390,2416:2520]=board.image[430,2460]
    if lower:
        tools.update_quantity(board,next(c for c in stock(board) if c.name=='stove'),0)
        tools.place_tool(board,'stove',None,6)
    core=session['collection']['units']['front:2']['unit']
    core['traits']=('追击','公司')
    if zone=='back':
        core['eligible_zones']=('front','back')
        other=session['collection']['units']['back:1']['unit']
        other.update(zone='front',slot=2,eligible_zones=('front',))
        core.update(zone='back',slot=1)
        session['collection']['units']['front:2']['unit']=other
        session['collection']['units']['back:1']['unit']=core
    return board,session


def result(board,session,after_worn):
    after=deepcopy(board);units=deepcopy(session['collection']['units'])
    source=next(c for c in stock(board) if c.name=='stove' and c.quantity!=0)
    if source.quantity_source=='single_cell':
        height,width=equipment.template('stove').shape[:2]
        x,y=round(source.point[0]*2560),round(source.point[1]*1440)
        left,top=round(x-width/2),round(y-height/2)
        after.image[top:top+height,left:left+width]=board.image[y-44,x-44]
    elif source.quantity!='infinite':tools.update_quantity(after,source,source.quantity-1)
    name='阿格莱雅' if session['strategy']=='aglaea' else '希儿'
    key=next(k for k,r in units.items() if r['unit']['name']==name)
    units[key]['unit']['equipment']=after_worn
    return after,units


def complete(folder,worn=('armor',),after_worn=('pistol',),**kwargs):
    board,session=fixture(worn,**kwargs);after,units=result(board,session,after_worn)
    c=exchange.StandardExchangeTests().context(folder,board,session,tools.states(board,after,units,name='stove'))
    reads=0;snapshot=c.snapshot
    def bounded():
        nonlocal reads
        reads+=1
        if reads>32:raise AssertionError('worn reforge fixture exhausted')
        return snapshot()
    c.snapshot=bounded
    def done():
        data=getattr(getattr(c,'currency_standard_session',None),'data',{})
        if data.get('consumable',{}).get('status')=='verified':raise Stopped('worn set verified')
    c.checkpoint=done
    with patch('autohsr.currency_wars_replay.save_sample'),unittest.TestCase().assertRaises(Stopped):run_standard(c)
    return c,StandardSession(c.currency_standard_session.path).data,board,after


class WornReforgeTests(unittest.TestCase):
    def test_both_named_strategies_and_positions_use_one_to_three_known_items(self):
        variants=[(('armor',),('pistol',)),(('armor','life_flower'),('pistol','battery')),
            (('armor','life_flower','energy_sail'),('pistol','battery','propeller'))]
        for strategy,zone in (('aglaea','front'),('seele','front'),('aglaea','back')):
            for before,after in variants:
                with self.subTest(strategy=strategy,zone=zone,before=before),tempfile.TemporaryDirectory() as folder:
                    c,saved,board,_=complete(folder,before,after,strategy=strategy,zone=zone)
                    action=saved['actions'][0];effect=action['consumable_effect']
                    self.assertTrue(worn_target(action['target']))
                    self.assertEqual(action['target'][8],zone)
                    self.assertEqual(effect['worn_after'],list(after))
                    self.assertEqual(quality(before),quality(after))
                    self.assertEqual(effect['worn_result'],'changed_observed')
                    self.assertTrue(valid_effect(action,saved['actions']))
                    self.assertEqual(ledger_status(saved['actions']),'clear')
                    self.assertEqual(c.window.drag.call_count,1)
                    self.assertFalse(saved['completion_verified'])

    def test_infinite_changed_and_finite_unchanged_have_distinct_observed_results(self):
        for quantity,after,lower in (('infinite',('pistol',),False),(2,('armor',),False),(1,('pistol',),True)):
            with self.subTest(quantity=quantity,lower=lower),tempfile.TemporaryDirectory() as folder:
                c,saved,_,board=complete(folder,quantity=quantity,after_worn=after,lower=lower)
                action=saved['actions'][0];effect=action['consumable_effect']
                self.assertEqual(effect['worn_result'],'unchanged_observed' if after==('armor',) else 'changed_observed')
                self.assertEqual(effect['quantity_used'],0 if quantity=='infinite' else 1)
                if lower:self.assertEqual(action['consumable_origin']['count_mode'],'single_cell')
                self.assertIsNone(proposal(board,saved))
                self.assertEqual(c.window.drag.call_count,1)

    def test_unchanged_infinite_result_stays_unsettled_without_a_second_use(self):
        board,session=fixture(quantity='infinite');after,units=result(board,session,('armor',))
        with tempfile.TemporaryDirectory() as folder:
            c=exchange.StandardExchangeTests().context(folder,board,session,tools.states(board,after,units,name='stove'))
            with patch('autohsr.currency_wars_replay.save_sample'):self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertFalse(saved['actions'][0]['consumable_verified'])
            self.assertEqual(saved['consumable']['status'],'verifying')
            self.assertEqual(ledger_status(saved['actions']),'pending')
            self.assertEqual(c.window.drag.call_count,1)

    def test_protected_unknown_empty_gear_and_existing_precise_targets_are_preserved(self):
        for strategy,worn in (('aglaea',('boots','armor')),('aglaea',('shoe',)),('aglaea',('propeller',)),
                              ('seele',('knife','armor')),('seele',('firestorm',)),('seele',('star',)),
                              ('aglaea',()),('aglaea',None),('aglaea',('unknown',))):
            board,session=fixture(worn,strategy=strategy)
            with self.subTest(strategy=strategy,worn=worn):
                if worn is None or worn==('unknown',):
                    with self.assertRaises(AutomationError):proposal(board,session)
                else:self.assertIsNone(proposal(board,session))
        board,session=fixture();equipment.place(board.image,'armor',(2460,330))
        self.assertEqual(proposal(board,session).payload[8],'inventory')
        board,session=fixture();session['strategy']='default'
        self.assertIsNone(proposal(board,session))

    def test_tool_acknowledgement_requires_exact_stock_without_adding_a_rerolled_bank_item(self):
        board,session=fixture();choice=proposal(board,session)
        session['actions'].append(dict(id=0,action=STAGE,status='pending',target=list(choice.payload),input_epoch=0,before='before.png'))
        bind_intent(session,choice,board)
        after,_=result(board,session,('pistol',))
        self.assertTrue(feedback(choice,board,after,session))
        for case in ('unchanged_counter','extra_item','gold','hp','xp'):
            bad=deepcopy(after)
            if case=='unchanged_counter':bad=deepcopy(board)
            elif case=='extra_item':equipment.place(bad.image,'pistol',(2460,330))
            elif case=='gold':trading.hud(bad,gold=1)
            elif case=='hp':
                bad.tokens=[replace(t,text='99') if t.within((.735,.05,.78,.095)) else t for t in bad.tokens]
            else:trading.hud(bad,xp=(1,6))
            with self.subTest(case=case):self.assertFalse(feedback(choice,board,bad,session))

    def test_mixed_quality_gear_and_ordered_profile_proof_cannot_be_forged(self):
        with tempfile.TemporaryDirectory() as folder:
            _,saved,_,_=complete(folder,('armor','energy_sail'),('pistol','propeller'))
        self.assertEqual(ledger_status(saved['actions']),'clear')
        for case in ('quality','count','wrong_actor','before','policy','source','result','profile_missing','profile_equipment','profile_source','epoch','mixed_epoch','bank','quantity_bool','quantity_float','quality_bool'):
            data=deepcopy(saved);action=data['actions'][0];effect=action['consumable_effect'];origin=action['consumable_origin']
            proof=next(p for p in effect['profile_proofs'] if (p['zone'],p['slot'])==tuple(action['target'][8:10]))
            profile=data['actions'][proof['inspection_action_id']]['worn_reforge_profile']
            if case=='quality':effect['worn_after']=['armor','pistol']
            elif case=='count':effect['worn_after']=['pistol']
            elif case=='wrong_actor':profile['unit']['name']='其他角色'
            elif case=='before':origin['worn_reforge']['equipment_before']=['armor']
            elif case=='policy':origin['worn_reforge']['policy']='invented'
            elif case=='source':origin['worn_reforge']['source'][1]=True
            elif case=='result':effect['worn_result']='unchanged_observed'
            elif case=='profile_missing':data['actions'][proof['inspection_action_id']].pop('worn_reforge_profile')
            elif case=='profile_equipment':profile['unit']['equipment']=['propeller','pistol']
            elif case=='profile_source':profile['source']='unrelated.png'
            elif case=='epoch':profile['input_epoch']=False
            elif case=='mixed_epoch':effect['profile_proofs'][0]['input_epoch']=1
            elif case=='quantity_bool':effect['quantity_used']=True
            elif case=='quantity_float':effect['quantity_used']=1.0
            elif case=='quality_bool':origin['worn_reforge']['quality_before']['basic']=True
            else:effect['stock_after']['pistol']=1
            with self.subTest(case=case):self.assertNotEqual(ledger_status(data['actions']),'clear')

    def test_wrong_worn_count_quality_or_other_unit_changes_do_not_complete(self):
        for case in ('quality','count','other','name','star','tier'):
            board,session=fixture(('armor','energy_sail'));after,units=result(board,session,('pistol','propeller'))
            unit=units['front:2']['unit']
            if case=='quality':unit['equipment']=('armor','pistol')
            elif case=='count':unit['equipment']=('pistol',)
            elif case=='other':units['back:1']['unit']['equipment']=('pistol',)
            elif case=='name':unit['name']='其他角色'
            elif case=='star':unit['star']=2
            else:unit['tier']=5
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,board,session,tools.states(board,after,units,name='stove'))
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(AutomationError):run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertFalse(saved['actions'][0]['consumable_verified'])
                self.assertEqual(saved['consumable']['status'],'mismatch')
                self.assertEqual(c.window.drag.call_count,1)

    def test_unchanged_counter_or_extra_bank_item_keeps_unknown_without_replay(self):
        for case in ('counter','bank'):
            board,session=fixture();after,units=result(board,session,('pistol',))
            if case=='counter':tools.update_quantity(after,next(c for c in stock(after) if c.name=='stove'),2)
            else:equipment.place(after.image,'pistol',(2460,330))
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,board,session,[board,after,after])
                with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',SimpleNamespace(monotonic=Mock(side_effect=count(0,31)))):
                    self.assertEqual(run_standard(c).status,'partial')
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertEqual(saved['actions'][0]['status'],'unknown')
                with self.assertRaises(AutomationError):run_standard(c)
                self.assertEqual(c.window.drag.call_count,1)

    def test_each_role_node_has_one_attempt_even_if_same_gear_is_observed(self):
        with tempfile.TemporaryDirectory() as folder:_,saved,_,board=complete(folder,after_worn=('armor',))
        unit=next(u for u in collected_snapshot(board,saved,0,'current').roster if u.name=='阿格莱雅')
        self.assertFalse(eligible('aglaea',unit,'1-1',saved['actions']))
        self.assertFalse(eligible('aglaea',replace(unit,zone='back',slot=1),'1-1',saved['actions']))
        self.assertTrue(eligible('aglaea',unit,'1-2',saved['actions']))

    def test_source_and_receipt_write_failures_never_repeat_the_consumption(self):
        for case in ('source','receipt'):
            board,session=fixture();after,units=result(board,session,('pistol',))
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,board,session,tools.states(board,after,units,name='stove'))
                persist=StandardSession.persist
                def fail(store):
                    actions=store.data.get('actions',[]);action=actions[0] if actions else {}
                    if case=='source' and action.get('consumable_origin',{}).get('worn_reforge'):raise OSError('source write')
                    if case=='receipt' and action.get('consumable_verified'):raise OSError('receipt write')
                    return persist(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',fail),self.assertRaises(OSError):run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertFalse(saved['actions'][0].get('consumable_verified'))
                self.assertEqual(c.window.drag.call_count,0 if case=='source' else 1)

    def test_pause_and_changed_account_leave_the_original_use_pending(self):
        from autohsr.models import InputInterrupted
        for case in ('pause','account'):
            board,session=fixture();after,_=result(board,session,('pistol',))
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c=exchange.StandardExchangeTests().context(folder,board,session,[board,after,after])
                submit=c.currency_standard_input.side_effect
                def send(scene,choice):
                    if case=='pause':raise InputInterrupted('paused')
                    return submit(scene,choice)
                c.currency_standard_input.side_effect=send
                snapshot=c.snapshot
                def read():
                    scene=snapshot()
                    if case=='account' and scene is after:
                        from autohsr.tests.test_currency_wars_standard_collection import uid
                        uid(scene,'200000000')
                    return scene
                c.snapshot=read
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(AutomationError):run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertEqual(saved['actions'][0]['status'],'pending')
                self.assertFalse(saved['actions'][0]['consumable_verified'])
                self.assertEqual(c.window.drag.call_count,0 if case=='pause' else 1)


if __name__=='__main__':unittest.main()
