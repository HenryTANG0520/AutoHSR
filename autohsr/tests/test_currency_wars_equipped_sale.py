"""Gear-return sales use native IO contracts and synthetic calibrated items."""
from copy import deepcopy
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock,patch
import numpy as np

from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import run_standard,next_action
from autohsr.currency_wars_standard_ledger import ledger_status,valid_receipt
from autohsr.currency_wars_standard_sale import (proposal,bind_intent,panel_feedback,active_action,
    sale_feedback,target_zone,inspection_target)
from autohsr import currency_wars_sale_equipment as gear
from autohsr.models import AutomationError,Stopped
from autohsr.tests import test_currency_wars_field_sale as field
from autohsr.tests import test_currency_wars_standard_sale as bench
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_trading as trading
from autohsr.tests import test_currency_wars_consumables as tools

YS=(330,430,535,640,745,845)


def bank(scene,items=(),tool=None):
    scene.image[140:905,2290:2540]=0
    scene.tokens=[t for t in scene.tokens if not t.within((2290/2560,140/1440,2540/2560,905/1440))]
    for i,name in enumerate(items):equipment.place(scene.image,name,((2350,2460)[i//6],YS[i%6]))
    if tool is not None:tools.place_tool(scene,*tool)


def fixture(zone='front',slot=1,worn=('armor',),items=('shoe',),tool=None,level=3):
    board,session=bench.fixture(slot) if zone=='bench' else field.fixture(zone,slot,level=level)
    session['collection']['units'][zone+':'+str(slot)]['unit']['equipment']=tuple(worn)
    bank(board,items,tool)
    return board,session


def detail(board,session,zone,slot,refund=2):
    page=field.panel(board,session,zone,slot,refund=refund)
    unit=session['collection']['units'][zone+':'+str(slot)]['unit']
    equipped=equipment.panel(unit,unit['equipment'])
    page.image[1040:1130,2100:]=equipped.image[1040:1130,2100:]
    return page


def inspected(board,session):
    choice=proposal(board,session)
    action=dict(id=len(session['actions']),action=choice.intent,status='pending',input_epoch=0,
                target=list(choice.payload),expected=choice.expected,before='board.png')
    session['actions'].append(action);bind_intent(session,choice,board)
    action.update(status='verified',after='detail.png')
    return choice


def sold(board,choice,items,tool=None):
    page=deepcopy(board);zone=target_zone(choice.payload)
    cell=next(c for c in roster_cells(board) if (c.zone,c.slot)==(zone,choice.payload[4]))
    _crop(page.image,cell.roi)[:]=0
    old=read_match(board)
    trading.hud(page,gold=choice.payload[1]+choice.payload[10],deployment=(old.deployment[0]-int(zone!='bench'),old.deployment[1]))
    bank(page,items,tool)
    return page


def transaction(zone='front',slot=1,worn=('armor',),items=('shoe',),tool=None,level=3):
    board,session=fixture(zone,slot,worn,items,tool,level);page=detail(board,session,zone,slot)
    inspect=inspected(board,session)
    choice=active_action(page,session)
    after=sold(board,choice,items+worn,tool)
    return board,session,page,inspect,choice,after


def credited(session,choice,receipt):
    actions=deepcopy(session['actions'])
    actions.append(dict(id=len(actions),action=choice.intent,status='verified',input_epoch=0,
        target=list(choice.payload),expected=choice.expected,before='detail.png',after='after.png',receipt=receipt))
    return actions


class EquippedSaleTests(unittest.TestCase):
    def test_all_three_zones_use_typed_targets_and_exact_return_receipts(self):
        for zone,slot in (('front',4),('back',6),('bench',9)):
            with self.subTest(zone=zone):
                board,session,page,inspect,choice,after=transaction(zone,slot,worn=('armor','armor','boots'),level=10)
                self.assertEqual(target_zone(inspect.payload),zone);self.assertEqual(target_zone(choice.payload),zone)
                self.assertEqual(inspection_target(choice.payload),list(inspect.payload))
                self.assertTrue(panel_feedback(inspect,board,page))
                receipt=sale_feedback(choice,page,after,session);self.assertIsNotNone(receipt)
                self.assertEqual(receipt['equipment_return']['equipment'],['armor','armor','boots'])
                actions=credited(session,choice,receipt)
                self.assertTrue(valid_receipt(actions[-1]));self.assertEqual(ledger_status(actions),'clear')

    def test_missing_duplicate_return_extra_item_or_changed_tool_does_not_settle_sale(self):
        board,session,page,_,choice,_=transaction(worn=('armor','armor'),tool=('wrench',2))
        for items,tool in ((('shoe','armor'),('wrench',2)),(('shoe','armor','armor','knife'),('wrench',2)),
                           (('shoe','armor','armor'),('wrench',1))):
            with self.subTest(items=items,tool=tool):
                self.assertIsNone(sale_feedback(choice,page,sold(board,choice,items,tool),session))

    def test_native_context_sells_once_and_persists_return_source(self):
        for zone,slot,level in (('front',1,3),('back',6,10),('bench',9,3)):
            board,session,page,_,choice,after=transaction(zone,slot,worn=('armor','boots'),level=level)
            original=fixture(zone,slot,worn=('armor','boots'),level=level)[1]
            with self.subTest(zone=zone),tempfile.TemporaryDirectory() as folder:
                c=trading.StandardTradingTests().context(folder,board,original,[board,page,page,after,after])
                def stop():
                    current=getattr(c,'currency_standard_session',None)
                    if current and current.data.get('sale',{}).get('status')=='verified':raise Stopped('sale complete')
                c.checkpoint=stop
                with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
                data=StandardSession(c.currency_standard_session.path).data
                self.assertEqual(ledger_status(data['actions']),'clear')
                self.assertEqual([a['action'] for a in data['actions']].count(choice.intent),1)
                self.assertEqual(data['actions'][-1]['receipt']['equipment_return']['stock_after'],dict(shoe=1,armor=1,boots=1))
                self.assertNotIn('collection',data)
                self.assertEqual(next_action(after,session=data).intent,'inspect_standard_unit')

    def test_components_and_finished_equipment_return_in_current_inventory_order(self):
        for name in ('armor','shoe','boots','hard_armor','energy_sail'):
            with self.subTest(name=name):
                board,session,page,_,choice,_=transaction('bench',4,worn=(name,),items=('knife',))
                after=sold(board,choice,(name,'knife'))
                self.assertIsNotNone(sale_feedback(choice,page,after,session))

    def test_zero_and_infinite_tools_remain_independent_of_returned_equipment(self):
        for quantity in (0,'infinite'):
            with self.subTest(quantity=quantity):
                _,session,page,_,choice,after=transaction(tool=('wrench',quantity))
                receipt=sale_feedback(choice,page,after,session)
                self.assertIsNotNone(receipt)
                self.assertEqual(ledger_status(credited(session,choice,receipt)),'clear')

    def test_unknown_inventory_skips_equipped_sale_without_disabling_empty_gear_sale(self):
        board,session=fixture()
        board.image[286:374,2306:2394]=np.random.default_rng(4).integers(0,256,(88,88,3),dtype=np.uint8)
        self.assertIsNone(proposal(board,session))
        session['collection']['units']['front:1']['unit']['equipment']=()
        self.assertIsNotNone(proposal(board,session))

    def test_insufficient_visible_space_and_unknown_worn_items_are_not_sold(self):
        for worn,items in ((('armor',),('shoe',)*12),(('armor','boots'),('shoe',)*11),(('unknown_gear',),())):
            with self.subTest(worn=worn,slots=len(items)):
                board,session=fixture(worn=worn,items=items)
                self.assertIsNone(proposal(board,session))

    def test_changed_current_equipment_cannot_authorize_the_frozen_sale(self):
        board,session=fixture();inspect=inspected(board,session)
        bad=deepcopy(session);bad['collection']['units']['front:1']['unit']['equipment']=('boots',)
        page=detail(board,bad,'front',1)
        self.assertFalse(panel_feedback(inspect,board,page))
        with self.assertRaises(AutomationError):active_action(page,session)

    def test_missing_or_tampered_inventory_and_return_sources_keep_the_ledger_unknown(self):
        _,session,page,_,choice,after=transaction('back',1)
        actions=credited(session,choice,sale_feedback(choice,page,after,session))
        self.assertEqual(ledger_status(actions),'clear')
        for mutation in ('return','source','counts','capacity','unit','epoch','field_copy','descriptor','bonus','old_transaction'):
            with self.subTest(mutation=mutation):
                bad=deepcopy(actions);a,b=bad[-2:]
                if mutation=='return':b['receipt'].pop('equipment_return')
                elif mutation=='source':a.pop('equipped_sale_basis')
                elif mutation=='counts':a['equipped_sale_basis']['inventory']['counts']['shoe']+=1
                elif mutation=='capacity':a['equipped_sale_basis']['inventory']['capacity']=0
                elif mutation=='unit':a['equipped_sale_basis']['unit']['equipment']=[]
                elif mutation=='epoch':a['equipped_sale_basis']['input_epoch']=True
                elif mutation=='field_copy':a['field_sale_basis']['inventory']['counts']['shoe']+=1
                elif mutation=='descriptor':b['target'][-1]=gear.TAG+'["unknown"]'
                elif mutation=='old_transaction':a['equipped_sale_basis']['snapshot']['transaction_status']='unknown'
                else:b['receipt']['equipment_return']['stock_after']['knife']=1
                self.assertEqual(ledger_status(bad),'unknown')

    def test_one_good_frame_then_missing_return_stays_unknown_and_is_not_replayed(self):
        board,session,page,_,choice,after=transaction()
        missing=sold(board,choice,('shoe',));original=fixture()[1]
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,original,[board,page,page,after,missing,missing])
            reads=0;read=c.snapshot
            def snapshot():
                nonlocal reads
                reads+=1
                return read()
            c.snapshot=snapshot
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',
                    SimpleNamespace(monotonic=Mock(side_effect=lambda:200 if reads>=6 else 0))):
                self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['action'],choice.intent)
            self.assertEqual(saved['actions'][-1]['status'],'unknown');self.assertNotIn('receipt',saved['actions'][-1])
            before=c.window.click.call_count
            with self.assertRaises(AutomationError):run_standard(c)
            self.assertEqual(before,2);self.assertEqual(c.window.click.call_count,before)

    def test_inventory_or_financial_intention_write_failure_prevents_the_corresponding_input(self):
        for stage in ('inspection','sale'):
            with self.subTest(stage=stage),tempfile.TemporaryDirectory() as folder:
                board,original=fixture();preview=deepcopy(original);inspect=inspected(board,preview)
                page=detail(board,original,'front',1)
                c=trading.StandardTradingTests().context(folder,board,original,[board,page,page])
                persist=StandardSession.persist
                def blocked(store):
                    action=store.data['actions'][-1] if store.data.get('actions') else {}
                    if (action.get('status')=='pending' and
                            (stage=='inspection' and action.get('equipped_sale_basis') is not None
                             or stage=='sale' and action.get('action')=='sell_standard_field_owned')):
                        raise OSError('equipped sale journal blocked')
                    return persist(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',blocked),self.assertRaises(OSError):
                    run_standard(c)
                self.assertEqual(c.window.click.call_count,0 if stage=='inspection' else 1)
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertEqual(saved['actions'][-1]['action'],inspect.intent)
                self.assertNotEqual(saved['actions'][-1]['action'],'sell_standard_field_owned')
