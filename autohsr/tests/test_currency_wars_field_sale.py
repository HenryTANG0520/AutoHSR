"""On-field cleanup is an observed credit, a roster change and a policy source."""
from copy import deepcopy
from dataclasses import replace
from itertools import count
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

import numpy as np

from autohsr.currency_wars_collector import collected_snapshot,roster_cells
from autohsr.currency_wars_deployment import _crop
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action,run_standard,transition_ready
from autohsr.currency_wars_standard_ledger import ledger_status,valid_receipt
from autohsr.currency_wars_standard_sale import (FIELD_INSPECT,FIELD_SELL,REFUND_ROI,BUTTON_ROI,active_action,
    bind_intent,choose_sale,panel_feedback,proposal,sale_feedback)
from autohsr.models import AutomationError,InputInterrupted,Stopped,Token
from autohsr.tests import test_currency_wars_maximum_level as maximum
from autohsr.tests import test_currency_wars_standard_equipment as equipment
from autohsr.tests import test_currency_wars_standard_sale as bench
from autohsr.tests import test_currency_wars_standard_trading as trading

KEEP=('希儿','瓦尔特','刻律德菈','符玄','花火','佩拉','风堇','缇宝','开拓者','记忆开拓者')


def fixture(zone='front',slot=1,*,level=3):
    board,session=trading.full_board_fixture(gold=25,level=level)
    if level==10:maximum.maximum(board)
    records=session['collection']['units']
    for key in list(records):
        if key.startswith('bench:'):
            cell=next(c for c in roster_cells(board) if c.zone+':'+str(c.slot)==key)
            _crop(board.image,cell.roi)[:]=0;records.pop(key)
    names=iter(KEEP)
    for key,record in records.items():
        unit=record['unit'];unit.update(name='待售角色' if key==zone+':'+str(slot) else next(names),
            star=1,tier=1,traits=('测试',),equipment=(),eligible_zones=(unit['zone'],))
    session.update(strategy='seele',shop_observed_nodes=['1-1'])
    return board,session


def panel(board,session,zone='front',slot=1,*,refund=2):
    unit=session['collection']['units'][zone+':'+str(slot)]['unit']
    detail=equipment.panel(unit)
    result=deepcopy(board);h,w=result.image.shape[:2]
    result.image[round(.13*h):round(.9*h),round(.72*w):]=detail.image[round(.13*h):round(.9*h),round(.72*w):]
    result.tokens=[t for t in result.tokens if not (.72<t.center[0] and .13<t.center[1]<.9)]
    result.tokens.extend(t for t in detail.tokens if .72<t.center[0] and .13<t.center[1]<.9
        and not t.within(REFUND_ROI) and not t.within(BUTTON_ROI))
    result.tokens.extend((Token('+'+str(refund),.99,(.859,.835,.879,.861)),Token('出售',.99,(.909,.833,.935,.861))))
    return result


def inspected(board,session):
    choice=proposal(board,session)
    action=dict(id=len(session['actions']),action=choice.intent,status='pending',input_epoch=0,
        target=list(choice.payload),expected=choice.expected,before='board.png')
    session['actions'].append(action);bind_intent(session,choice,board)
    action.update(status='verified',after='panel.png')
    return choice


def sold(board,choice):
    result=deepcopy(board)
    cell=next(c for c in roster_cells(board) if (c.zone,c.slot)==(choice.payload[-1],choice.payload[4]))
    _crop(result.image,cell.roi)[:]=0
    state=read_match(board)
    trading.hud(result,gold=choice.payload[1]+choice.payload[10],deployment=(state.deployment[0]-1,state.deployment[1]))
    return result


def complete(folder,zone='front',slot=1,*,level=3,refund=2):
    board,session=fixture(zone,slot,level=level);detail=panel(board,session,zone,slot,refund=refund)
    preview=deepcopy(session);inspected(board,preview);choice=active_action(detail,preview)
    after=sold(board,choice)
    c=trading.StandardTradingTests().context(folder,board,session,[board,detail,detail,after,after])
    reads=0;snapshot=c.snapshot
    def bounded():
        nonlocal reads
        reads+=1
        if reads>18:raise AssertionError('field sale fixture exhausted')
        return snapshot()
    c.snapshot=bounded
    def stop():
        store=getattr(c,'currency_standard_session',None)
        if store and store.data.get('sale',{}).get('status')=='verified':raise Stopped('sale complete')
    c.checkpoint=stop
    with patch('autohsr.currency_wars_replay.save_sample'),unittest.TestCase().assertRaises(Stopped):run_standard(c)
    return c,StandardSession(c.currency_standard_session.path).data,board,after


class FieldSaleTests(unittest.TestCase):
    def test_all_four_front_and_six_back_slots_bind_the_actual_zone(self):
        for zone,total in (('front',4),('back',6)):
            for slot in range(1,total+1):
                with self.subTest(zone=zone,slot=slot):
                    board,session=fixture(zone,slot,level=10)
                    choice=proposal(board,session);detail=panel(board,session,zone,slot)
                    self.assertEqual((choice.intent,choice.payload[-1],choice.payload[4]),(FIELD_INSPECT,zone,slot))
                    self.assertEqual(next_action(board,session=session),choice)
                    self.assertTrue(panel_feedback(choice,board,detail))
                    inspected(board,session);sale=active_action(detail,session)
                    self.assertEqual((sale.intent,sale.payload[-1]),(FIELD_SELL,zone))
                    self.assertIsNotNone(sale_feedback(sale,detail,sold(board,sale),session))

    def test_formal_context_records_zero_refund_maximum_level_and_both_zones(self):
        for zone,slot,level,refund in (('front',1,3,0),('back',1,3,12),('front',4,10,99),('back',6,10,6)):
            with self.subTest(zone=zone,slot=slot),tempfile.TemporaryDirectory() as folder:
                c,saved,before,after=complete(folder,zone,slot,level=level,refund=refund)
                action=saved['actions'][-1];receipt=action['receipt']
                self.assertEqual([a['action'] for a in saved['actions']],[FIELD_INSPECT,FIELD_SELL])
                self.assertTrue(valid_receipt(action));self.assertEqual(ledger_status(saved['actions']),'clear')
                self.assertEqual(receipt['zone'],zone);self.assertEqual(receipt['refund'],refund)
                self.assertEqual(receipt['deployment_after'],[level-1,level])
                self.assertNotIn(zone+':'+str(slot),saved['collection']['units'])
                self.assertEqual(len(saved['collection']['units']),level-1)
                self.assertFalse(saved['collection']['complete']);self.assertEqual(c.window.click.call_count,2)
                self.assertFalse(saved['completion_verified']);self.assertEqual(read_match(after).gold,25+refund)
                self.assertEqual(saved['discarded_units'][0]['name'],'待售角色')
                saved['collection']['complete']=True
                self.assertEqual(next_action(after,session=saved).intent,'open_standard_shop')

    def test_seele_ownership_strategy_names_and_known_empty_equipment_are_required(self):
        board,session=fixture();snapshot=collected_snapshot(board,session,0,'field policy')
        actor=next(u for u in snapshot.roster if u.name=='待售角色')
        self.assertEqual(choose_sale(snapshot,'seele')[0],actor)
        for strategy in ('default','aglaea'):self.assertIsNone(choose_sale(snapshot,strategy))
        for change in (dict(name='希儿'),dict(name='瓦尔特'),dict(equipment=None),dict(equipment=('armor',))):
            roster=tuple(replace(u,**change) if u==actor else u for u in snapshot.roster)
            if 'name' in change:
                # Keep field names unique while proving core protection.
                roster=tuple(replace(u,name='风堇') if u.name==change['name'] and u!=replace(actor,**change) else u for u in roster)
            with self.subTest(change=change):self.assertIsNone(choose_sale(replace(snapshot,roster=roster),'seele'))
        no_core=tuple(replace(u,name='其他辅助') if u.name=='希儿' else u for u in snapshot.roster)
        self.assertIsNone(choose_sale(replace(snapshot,roster=no_core),'seele'))
        for bad in (dict(eligible_zones=None),dict(star=None),dict(tier=None)):
            with self.subTest(bad=bad),self.assertRaises(AutomationError):choose_sale(replace(snapshot,roster=tuple(replace(u,**bad) if u==actor else u for u in snapshot.roster)),'seele')

    def test_underfilled_team_can_be_cleaned_before_new_shop_observation(self):
        board,session=fixture();trading.hud(board,deployment=(3,4),level=4)
        choice=proposal(board,session)
        self.assertEqual(choice.intent,FIELD_INSPECT)

    def test_refund_and_every_remaining_cell_count_and_resource_are_verified(self):
        board,session=fixture();detail=panel(board,session);inspected(board,session);choice=active_action(detail,session)
        after=sold(board,choice)
        for case in ('gold','hp','xp','count','capacity','node','level','other','not_empty','shape'):
            bad=deepcopy(after)
            if case=='gold':trading.hud(bad,gold=28)
            elif case=='hp':bad.tokens=[Token('99',t.score,t.box) if t.within((.735,.05,.78,.095)) else t for t in bad.tokens]
            elif case=='xp':trading.hud(bad,xp=(1,6))
            elif case=='count':trading.hud(bad,deployment=(3,3))
            elif case=='capacity':trading.hud(bad,deployment=(2,4))
            elif case=='level':trading.hud(bad,level=4)
            elif case=='node':
                from autohsr.tests.test_currency_wars_standard_rewards import node
                node(bad,'1-2')
            elif case=='shape':bad.image=bad.image[1:]
            else:
                cells=roster_cells(board)
                cell=(next(c for c in cells if (c.zone,c.slot)==('front',1)) if case=='not_empty'
                    else next(c for c in cells if c.zone=='back' and c.state=='occupied'))
                _crop(bad.image,cell.roi)[:]=_crop(board.image,cell.roi) if case=='not_empty' else 255-_crop(board.image,cell.roi)
            with self.subTest(case=case):self.assertIsNone(sale_feedback(choice,detail,bad,session))

    def test_field_receipt_cannot_be_relabelled_as_bench_or_lose_its_policy_source(self):
        with tempfile.TemporaryDirectory() as folder:_,saved,_,_=complete(folder)
        self.assertEqual(ledger_status(saved['actions']),'clear')
        for case in ('zone','bench','origin','core','policy','counter','xp','xp_bool','xp_float','source_epoch','source_id','field_target','slot_bool','slot_float','unit_float','schema_bool'):
            data=deepcopy(saved);action=data['actions'][-1];receipt=action['receipt'];inspection=data['actions'][0]
            if case=='zone':receipt['zone']='back'
            elif case=='bench':action.update(action='sell_standard_owned',target=action['target'][:12])
            elif case=='origin':inspection.pop('field_sale_basis')
            elif case=='core':
                for unit in inspection['field_sale_basis']['snapshot']['roster']:
                    if unit['name']=='希儿':unit['name']='未知辅助'
            elif case=='policy':inspection['field_sale_basis']['strategy']='default'
            elif case=='counter':receipt['deployment_after'][0]+=1
            elif case=='xp':receipt['experience_after']=[1,6]
            elif case=='xp_bool':receipt['experience_after']=[False,6]
            elif case=='xp_float':receipt['experience_after']=[0.0,6]
            elif case=='source_epoch':inspection['field_sale_basis']['input_epoch']=True
            elif case=='source_id':inspection['field_sale_basis']['inspect_action_id']=False
            elif case=='slot_bool':inspection['target'][4]=True
            elif case=='slot_float':inspection['target'][4]=1.0
            elif case=='unit_float':inspection['field_sale_basis']['unit']['star']=1.0
            elif case=='schema_bool':receipt['schema']=True
            else:inspection['target'][-1]='back'
            with self.subTest(case=case):self.assertNotEqual(ledger_status(data['actions']),'clear')

    def test_legacy_bench_sale_format_and_policy_are_preserved(self):
        board,session=bench.fixture();detail=panel(board,session,'bench',4)
        bench.inspected(board,session);choice=active_action(detail,session)
        self.assertEqual((choice.intent,len(choice.payload)),('sell_standard_owned',12))
        receipt=sale_feedback(choice,detail,bench.sold(board,choice),session)
        action=dict(id=1,action=choice.intent,status='verified',target=list(choice.payload),expected=choice.expected,
            input_epoch=0,before='panel.png',after='board.png',receipt=receipt)
        self.assertTrue(valid_receipt(action));self.assertEqual(ledger_status(session['actions']+[action]),'clear')

    def test_small_pixel_changes_are_scoped_to_this_field_sale_and_not_a_different_portrait(self):
        board,session=fixture();detail=panel(board,session);inspected(board,session);choice=active_action(detail,session)
        after=sold(board,choice)
        for cell in roster_cells(after):
            if cell.state=='occupied':
                crop=_crop(after.image,cell.roi);crop[:]=np.clip(crop.astype(int)+1,0,255).astype(np.uint8)
        receipt=sale_feedback(choice,detail,after,session)
        self.assertIsNotNone(receipt)
        action=dict(id=1,action=choice.intent,status='verified',target=list(choice.payload),expected=choice.expected,
            input_epoch=0,before='panel.png',after='sold.png',receipt=receipt)
        self.assertTrue(valid_receipt(action));self.assertEqual(ledger_status(session['actions']+[action]),'clear')
        cell=next(c for c in roster_cells(after) if c.state=='occupied')
        crop=_crop(after.image,cell.roi);crop[:]=np.random.default_rng(58).integers(0,256,crop.shape,dtype=np.uint8)
        self.assertIsNone(sale_feedback(choice,detail,after,session))
        broken=deepcopy(action);broken['receipt']['appearances_after'][cell.zone+':'+str(cell.slot)]='e30='
        self.assertFalse(valid_receipt(broken))

    def test_expired_source_is_closed_before_any_sale_in_a_new_run(self):
        board,session=fixture();detail=panel(board,session);inspected(board,session)
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[detail,board,board])
            def stop():
                store=getattr(c,'currency_standard_session',None)
                if store and store.data.get('sale',{}).get('status')=='cancelled':raise Stopped('old panel closed')
            c.checkpoint=stop
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):run_standard(c)
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual([a['action'] for a in saved['actions']],[FIELD_INSPECT,'close_standard_sale_stale_panel'])
            self.assertNotIn('collection',saved);self.assertEqual(c.window.click.call_count,1)
            self.assertEqual(ledger_status(saved['actions']),'clear')

    def test_bad_inspection_proof_blocks_before_a_financial_intent_or_input(self):
        for case in ('missing','appearance','unit','run','epoch','strategy','unknown'):
            board,session=fixture();detail=panel(board,session);inspected(board,session)
            inspection=session['actions'][0]
            if case=='missing':inspection.pop('field_sale_basis')
            elif case=='appearance':inspection['field_sale_basis']['appearances']['front:1']='e30='
            elif case=='unit':inspection['field_sale_basis']['unit']['star']=4
            elif case=='run':inspection['field_sale_basis']['run_dir']='unrelated'
            elif case=='epoch':inspection['field_sale_basis']['input_epoch']=1
            elif case=='strategy':inspection['field_sale_basis']['strategy']='default'
            else:inspection['status']='unknown'
            with self.subTest(case=case),self.assertRaises(AutomationError):active_action(detail,session)
            self.assertEqual(len(session['actions']),1)

    def test_unknown_field_credit_is_not_replayed_on_resume(self):
        board,session=fixture();detail=panel(board,session);preview=deepcopy(session);inspected(board,preview)
        choice=active_action(detail,preview);bad=sold(board,choice);trading.hud(bad,gold=28)
        with tempfile.TemporaryDirectory() as folder:
            c=trading.StandardTradingTests().context(folder,board,session,[board,detail,detail,bad,bad])
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',SimpleNamespace(monotonic=Mock(side_effect=count(0,31)))):
                self.assertEqual(run_standard(c).status,'partial')
            saved=StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['action'],FIELD_SELL);self.assertEqual(saved['actions'][-1]['status'],'unknown')
            self.assertNotIn('receipt',saved['actions'][-1]);self.assertEqual(ledger_status(saved['actions']),'unknown')
            self.assertEqual(c.window.click.call_count,2)
            with self.assertRaises(AutomationError):run_standard(c)
            self.assertEqual(c.window.click.call_count,2)

    def test_source_write_credit_write_pause_account_and_receipt_failure_keep_original_intents(self):
        for case in ('source_write','credit_write','pause','account','receipt'):
            board,session=fixture();detail=panel(board,session);preview=deepcopy(session);inspected(board,preview)
            after=sold(board,active_action(detail,preview))
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c=trading.StandardTradingTests().context(folder,board,session,[board,detail,detail,after,after])
                submit=c.currency_standard_input.side_effect
                def send(scene,choice):
                    if case=='pause' and choice.intent==FIELD_SELL:raise InputInterrupted('paused')
                    return submit(scene,choice)
                c.currency_standard_input.side_effect=send
                snapshot=c.snapshot
                def read():
                    scene=snapshot()
                    if case=='account' and scene is after:
                        from autohsr.tests.test_currency_wars_standard_collection import uid
                        uid(scene,'200000000')
                    return scene
                c.snapshot=read;persist=StandardSession.persist
                def save(store):
                    last=store.data.get('actions',[])[-1] if store.data.get('actions') else {}
                    if case=='source_write' and last.get('field_sale_basis'):raise OSError('source write')
                    if case=='credit_write' and last.get('action')==FIELD_SELL:raise OSError('intent write')
                    if case=='receipt' and last.get('action')==FIELD_SELL and last.get('status')=='verified':raise OSError('receipt write')
                    return persist(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',save),self.assertRaises((AutomationError,OSError)):run_standard(c)
                saved=StandardSession(c.currency_standard_session.path).data
                self.assertNotIn('receipt',saved['actions'][-1]);self.assertNotEqual(saved.get('sale',{}).get('status'),'verified')
                self.assertEqual(c.window.click.call_count,0 if case=='source_write' else 1 if case in ('credit_write','pause') else 2)


if __name__=='__main__':unittest.main()
