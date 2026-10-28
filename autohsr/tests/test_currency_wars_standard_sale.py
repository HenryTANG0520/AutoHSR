"""Sales bind fresh roster inspection, observed refunds and full-board feedback."""
from copy import deepcopy
from dataclasses import asdict, replace
from itertools import count
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.currency_wars_collector import collected_snapshot, roster_cells
from autohsr.currency_wars_deployment import _crop, bench_face
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard, transition_ready
from autohsr.currency_wars_standard_ledger import ledger_status, valid_receipt
from autohsr.currency_wars_standard_policy import rank_standard_offers
from autohsr.currency_wars_standard_sale import (BUTTON_ROI, REFUND_ROI, active_action, bind_intent,
    choose_sale, finish, panel_feedback, proposal, refund_target)
from autohsr.currency_wars_standard_trading import financial_feedback, purchase_action, record_financial_feedback
from autohsr.currency_wars_state import ShopOffer
from autohsr.models import AutomationError, InputInterrupted, Scene, Stopped, Token
from autohsr.tests import test_currency_wars_standard_exchange as exchange_helpers
from autohsr.tests import test_currency_wars_standard_trading as trading_helpers


def fixture(slot=4):
    board,session = trading_helpers.full_board_fixture(gold=25)
    records = session['collection']['units']
    record = records.pop('bench:4')
    portrait = _crop(board.image,bench_face(4)).copy()
    for old in (4,5):
        records.pop('bench:'+str(old),None)
        _crop(board.image,bench_face(old))[:] = 0
    _crop(board.image,bench_face(slot))[:] = portrait
    record['unit'].update(name='待售角色',slot=slot,traits=('测试',),equipment=(),eligible_zones=('back',))
    cell = next(c for c in roster_cells(board) if (c.zone,c.slot)==('bench',slot))
    record['signature'] = cell.signature
    records['bench:'+str(slot)] = record
    session['strategy'] = 'aglaea'
    return board,session


def character(board, session, slot=4, refund=2):
    unit = session['collection']['units']['bench:'+str(slot)]['unit']
    detail = exchange_helpers.panel(unit)
    panel = Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
    h,w = panel.image.shape[:2]
    panel.image[round(.13*h):round(.9*h),round(.72*w):] = detail.image[round(.13*h):round(.9*h),round(.72*w):]
    panel.tokens = [t for t in panel.tokens if not (.72 < t.center[0] and .13 < t.center[1] < .9)]
    panel.tokens += [t for t in detail.tokens if .72 < t.center[0] and .13 < t.center[1] < .9
                    and not t.within(REFUND_ROI) and not t.within(BUTTON_ROI)]
    panel.tokens += [Token('+'+str(refund),.99,(.859,.835,.879,.861)),Token('出售',.99,(.909,.833,.935,.861))]
    return panel


def inspected(board, session):
    choice = proposal(board,session)
    action = dict(id=len(session['actions']),action=choice.intent,status='pending',input_epoch=0,
                  target=list(choice.payload),expected=choice.expected,before='board.png')
    session['actions'].append(action)
    bind_intent(session,choice,board)
    action.update(status='verified',after='panel.png')
    session['inspecting'] = dict(zone='bench',slot=choice.payload[4],node=choice.payload[0],signature=choice.payload[8],
                                 run_dir=session['account_verified_run'],input_epoch=0)
    return choice


def sold(board, choice):
    result = Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
    _crop(result.image,bench_face(choice.payload[4]))[:] = 0
    trading_helpers.hud(result,gold=choice.payload[1]+choice.payload[10])
    return result


class StandardSaleTests(unittest.TestCase):
    def test_all_nine_bench_slots_have_current_targets_and_verified_identity_panels(self):
        for slot in range(1,10):
            with self.subTest(slot=slot),patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3):
                board,session = fixture(slot)
                inspect = proposal(board,session)
                self.assertEqual(inspect.payload[4],slot)
                self.assertEqual(next_action(board,session=session),inspect)
                panel = character(board,session,slot)
                self.assertTrue(panel_feedback(inspect,board,panel))
                inspected(board,session)
                sale = active_action(panel,session)
                self.assertEqual(sale.intent,'sell_standard_owned')
                self.assertEqual(sale.payload[4],slot)
                after = sold(board,sale)
                self.assertIsNotNone(financial_feedback(sale,panel,after,session=session))

    def test_useful_exchange_core_unknown_equipment_and_incomplete_roster_are_protected(self):
        board,session = fixture()
        snapshot = collected_snapshot(board,session,0,'sale_test')
        bench = next(unit for unit in snapshot.roster if unit.zone=='bench')
        for changed in (replace(bench,name='阿格莱雅'),replace(bench,name='昔涟'),replace(bench,name='瓦尔特'),
                        replace(bench,equipment=None),replace(bench,equipment=('已装备',)),replace(bench,star=3)):
            current = replace(snapshot,roster=tuple(changed if unit==bench else unit for unit in snapshot.roster))
            with self.subTest(unit=changed):
                self.assertIsNone(choose_sale(current,'aglaea'))
        with self.assertRaises(AutomationError):choose_sale(replace(snapshot,roster_complete=False),'aglaea')
        self.assertIsNone(choose_sale(replace(snapshot,capacity=4),'aglaea'))

    def test_default_waits_until_all_eligible_positions_are_occupied(self):
        board,session = fixture()
        snapshot = collected_snapshot(board,session,0,'sale_test')
        self.assertIsNone(choose_sale(snapshot,'default'))
        # A front-only bench unit cannot use future back slots after all four
        # front slots are occupied. Actual names/stars remain independent.
        field = tuple(replace(unit,zone='front',slot=i+1,eligible_zones=('front',))
                      for i,unit in enumerate(u for u in snapshot.roster if u.zone!='bench'))
        extra = replace(field[-1],name='第四名前台',slot=4)
        bench = replace(next(u for u in snapshot.roster if u.zone=='bench'),eligible_zones=('front',))
        full = replace(snapshot,capacity=4,roster=field+(extra,bench))
        self.assertEqual(choose_sale(full,'default')[0],bench)
        self.assertIsNone(choose_sale(replace(full,roster=field+(extra,replace(bench,eligible_zones=('front','back')))),'default'))

    def test_named_strategies_do_not_buy_support_or_unrelated_duplicates_to_sell_again(self):
        board,session = fixture()
        snapshot = collected_snapshot(board,session,0,'sale_test')
        for strategy,name in (('aglaea','藿藿'),('seele','瓦尔特'),('aglaea','待售角色')):
            roster = tuple(replace(unit,name=name) if unit.zone=='bench' else unit for unit in snapshot.roster)
            current = replace(snapshot,roster=roster,offers=(ShopOffer(0,name,price=1),))
            with self.subTest(strategy=strategy,name=name):
                self.assertFalse(rank_standard_offers(current,strategy))

    def test_refund_is_not_inferred_from_tier_and_conflicting_or_unsigned_values_block(self):
        for refund in (0,1,2,6,12,99):
            board,session = fixture()
            panel = character(board,session,refund=refund)
            self.assertEqual(refund_target(panel)[0],refund)
        for value in ('2','-2','+102','+01','+2金币'):
            panel.tokens = [t for t in panel.tokens if not t.within(REFUND_ROI)]
            panel.tokens.append(Token(value,.99,REFUND_ROI))
            with self.subTest(value=value),self.assertRaises(AutomationError):refund_target(panel)
        panel.tokens = [t for t in panel.tokens if not t.within(REFUND_ROI)]
        panel.tokens += [Token('+2',.99,REFUND_ROI),Token('+3',.99,REFUND_ROI)]
        with self.assertRaises(AutomationError):refund_target(panel)

    def test_full_context_clicks_one_inspection_then_one_sale_and_records_actual_refund(self):
        for slot,refund in ((1,0),(4,6),(8,12),(9,2)):
            with self.subTest(slot=slot,refund=refund),tempfile.TemporaryDirectory() as folder:
                board,session = fixture(slot)
                panel = character(board,session,slot,refund)
                after = Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
                _crop(after.image,bench_face(slot))[:] = 0
                trading_helpers.hud(after,gold=25+refund)
                c = trading_helpers.StandardTradingTests().context(folder,board,session,[board,panel,panel,after,after])
                def stop_sold():
                    store = getattr(c,'currency_standard_session',None)
                    if store and store.data.get('sale',{}).get('status')=='verified':
                        raise Stopped('sale fixture complete')
                c.checkpoint = stop_sold
                with patch('autohsr.currency_wars_replay.save_sample'), \
                        patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3),self.assertRaises(Stopped):
                    run_standard(c)
                saved = StandardSession(c.currency_standard_session.path).data
                self.assertEqual([a['action'] for a in saved['actions']],['inspect_standard_sale_unit','sell_standard_owned'])
                self.assertTrue(valid_receipt(saved['actions'][-1]))
                self.assertEqual(saved['actions'][-1]['receipt']['refund'],refund)
                self.assertEqual(saved['actions'][-1]['receipt']['gold_after'],25+refund)
                self.assertNotIn('bench:'+str(slot),saved['collection']['units'])
                self.assertEqual(ledger_status(saved['actions']),'clear')
                self.assertEqual(c.window.click.call_count,2)
                self.assertFalse(saved['completion_verified'])

    def test_wrong_profile_or_new_equipment_never_authorizes_sale(self):
        for mutation in ('name','star','tier','equipment','source'):
            board,session = fixture()
            inspected(board,session)
            panel = character(board,session)
            if mutation == 'name':
                panel.tokens = [Token('其他角色',t.score,t.box) if t.text=='待售角色' else t for t in panel.tokens]
            elif mutation == 'star':
                session['sale']['inspect_target'][6] = 2
                session['actions'][0]['target'][6] = 2
            elif mutation == 'tier':
                panel.tokens = [Token('2',t.score,t.box) if t.box==exchange_helpers.TIER_FIELD else t for t in panel.tokens]
            elif mutation == 'source':
                session['actions'].append(dict(id=1,action='close_standard_unit',status='verified',input_epoch=0))
            with self.subTest(mutation=mutation),patch('autohsr.currency_wars_equipment.equipment_slots',
                    return_value=('unknown','empty','empty') if mutation=='equipment' else ('empty',)*3),self.assertRaises(AutomationError):
                active_action(panel,session)

    def test_gold_source_empty_and_every_other_slot_must_match_for_a_credit_receipt(self):
        board,session = fixture(9)
        inspected(board,session)
        panel = character(board,session,9,12)
        with patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3):
            choice = active_action(panel,session)
            after = sold(board,choice)
            receipt = financial_feedback(choice,panel,after,session=session)
            self.assertIsNotNone(receipt)
            action = dict(id=1,action=choice.intent,status='verified',input_epoch=0,target=list(choice.payload),
                          before='panel.png',after='after.png')
            session['actions'].append(action)
            record_financial_feedback(session,choice,receipt)
            self.assertTrue(valid_receipt(action))
            self.assertEqual(ledger_status([action]),'unknown')  # An orphan credit has no inspected source.
            chain = deepcopy(session['actions'])
            chain[0]['input_epoch'] = 1
            self.assertEqual(ledger_status(chain),'unknown')
            chain = deepcopy(session['actions'])
            chain[0]['target'][4] = 8
            self.assertEqual(ledger_status(chain),'unknown')
            for key,value in (('gold_after',38),('refund',2),('source_empty',False),('name','其他角色'),('inspect_action_id',3)):
                bad = deepcopy(action);bad['receipt'][key] = value
                with self.subTest(field=key):self.assertFalse(valid_receipt(bad))
            bad = deepcopy(action)
            bad['receipt']['cells_after']['bench:1'] = list(bad['receipt']['cells_before']['bench:9'])
            from autohsr.currency_wars_standard_sale import board_digest
            bad['receipt']['board_after'] = board_digest(bad['receipt']['cells_after'])
            self.assertFalse(valid_receipt(bad))
        for mutation in ('money','not_empty','other_bench','field','hp','node','level','xp','deployment'):
            board,session = fixture(9);inspected(board,session);panel = character(board,session,9,12)
            with patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3):
                choice = active_action(panel,session);bad = sold(board,choice)
                if mutation=='money':trading_helpers.hud(bad,gold=36)
                elif mutation=='not_empty':bad.image = board.image.copy()
                elif mutation=='other_bench':_crop(bad.image,bench_face(1))[:] = _crop(board.image,bench_face(9))
                elif mutation=='field':
                    cell = next(c for c in roster_cells(board) if c.zone=='front' and c.state=='occupied')
                    _crop(bad.image,cell.roi)[:] = 0
                elif mutation=='hp':bad.tokens = [Token('99',t.score,t.box) if t.within((.735,.05,.78,.095)) else t for t in bad.tokens]
                elif mutation=='node':bad.tokens = [Token('1-2',t.score,t.box) if t.text=='1-1' else t for t in bad.tokens]
                elif mutation=='level':trading_helpers.hud(bad,level=4)
                elif mutation=='xp':trading_helpers.hud(bad,xp=(2,6))
                else:trading_helpers.hud(bad,deployment=(2,3))
                with self.subTest(mutation=mutation):self.assertIsNone(financial_feedback(choice,panel,bad,session=session))

    def test_a_new_wrong_panel_or_changed_visible_portrait_cannot_complete_the_inspection(self):
        for mutation in ('name','portrait','level','xp'):
            board,session = fixture()
            choice = proposal(board,session)
            panel = character(board,session)
            if mutation=='name':panel.tokens = [Token('其他角色',t.score,t.box) if t.text=='待售角色' else t for t in panel.tokens]
            elif mutation=='portrait':_crop(panel.image,bench_face(4))[:] = 0
            elif mutation=='level':trading_helpers.hud(panel,level=4)
            else:trading_helpers.hud(panel,xp=(2,6))
            with self.subTest(mutation=mutation),patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3):
                self.assertFalse(panel_feedback(choice,board,panel))

    def test_pause_or_new_runner_discards_the_old_sale_panel_and_closes_before_reinspection(self):
        for scope in ('epoch','run'):
            board,session = fixture();inspected(board,session);panel = character(board,session)
            session['account_verified_epoch' if scope=='epoch' else 'account_verified_run'] = 1 if scope=='epoch' else 'new-run'
            close = active_action(panel,session)
            self.assertEqual(close.intent,'close_standard_sale_stale_panel')
            self.assertTrue(transition_ready(close,board,before=panel,session=session))
            finish(session,cancelled=True)
            self.assertEqual(session['sale_history'][-1]['status'],'cancelled')
            self.assertNotIn('collection',session)

    def test_unknown_sale_is_kept_and_resume_never_repeats_it(self):
        board,session = fixture();panel = character(board,session)
        with tempfile.TemporaryDirectory() as folder:
            c = trading_helpers.StandardTradingTests().context(folder,board,session,[board,panel,panel,board,board])
            with patch('autohsr.currency_wars_replay.save_sample'), \
                    patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3), \
                    patch('autohsr.currency_wars_standard_flow.time',SimpleNamespace(monotonic=Mock(side_effect=count(0,31)))):
                self.assertEqual(run_standard(c).status,'partial')
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['action'],'sell_standard_owned')
            self.assertEqual(saved['actions'][-1]['status'],'unknown')
            self.assertNotIn('receipt',saved['actions'][-1])
            with self.assertRaises(AutomationError):run_standard(c)
            self.assertEqual(c.window.click.call_count,2)

    def test_write_pause_and_account_failures_do_not_settle_or_repeat_a_sale(self):
        for case in ('write','pause','account'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                board,session = fixture();panel = character(board,session)
                after = Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
                _crop(after.image,bench_face(4))[:] = 0;trading_helpers.hud(after,gold=27)
                c = trading_helpers.StandardTradingTests().context(folder,board,session,[board,panel,panel,after,after])
                original_input = c.currency_standard_input.side_effect
                def submit(scene,choice):
                    if case=='pause' and choice.intent=='sell_standard_owned':raise InputInterrupted('pause')
                    return original_input(scene,choice)
                c.currency_standard_input.side_effect = submit
                original_snapshot = c.snapshot
                def snapshot():
                    current = original_snapshot()
                    if case=='account' and current is after:
                        current.tokens = [Token('UID:200000000',t.score,t.box) if t.text.startswith('UID:') else t for t in current.tokens]
                    return current
                c.snapshot = snapshot
                original_persist = StandardSession.persist
                def persist(store):
                    if case=='write' and store.data['actions'] and store.data['actions'][-1]['action']=='sell_standard_owned':
                        raise OSError('locked journal')
                    return original_persist(store)
                with patch('autohsr.currency_wars_replay.save_sample'), \
                        patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3), \
                        patch.object(StandardSession,'persist',persist),self.assertRaises((AutomationError,OSError)):
                    run_standard(c)
                saved = StandardSession(c.currency_standard_session.path).data
                if case=='write':self.assertEqual(len(saved['actions']),1)
                else:
                    self.assertEqual(saved['actions'][-1]['status'],'pending')
                    self.assertNotIn('receipt',saved['actions'][-1])
                self.assertEqual(c.window.click.call_count,2 if case=='account' else 1)

    def test_a_discarded_name_cannot_be_bought_back_on_the_same_node(self):
        _,shop,session = trading_helpers.purchase_fixture()
        self.assertEqual(purchase_action(shop,session).payload[5],'阿格莱雅')
        session['discarded_units'] = [dict(node='1-1',name='阿格莱雅',reason='test')]
        choice = purchase_action(shop,session)
        self.assertTrue(choice is None or choice.payload[5]!='阿格莱雅')
        session['discarded_units'][0]['node'] = '1-2'
        self.assertEqual(purchase_action(shop,session).payload[5],'阿格莱雅')

    def test_confirmed_credit_with_failed_final_journal_write_cannot_start_more_input(self):
        board,session = fixture();panel = character(board,session)
        after = Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
        _crop(after.image,bench_face(4))[:] = 0
        trading_helpers.hud(after,gold=27)
        with tempfile.TemporaryDirectory() as folder:
            c = trading_helpers.StandardTradingTests().context(folder,board,session,[board,panel,panel,after,after])
            original = StandardSession.persist
            def fail_receipt_write(store):
                if (store.data['actions'] and store.data['actions'][-1]['action']=='sell_standard_owned'
                        and store.data['actions'][-1]['status']=='verified'):
                    raise OSError('receipt write failed after visible credit')
                return original(store)
            with patch('autohsr.currency_wars_replay.save_sample'), \
                    patch('autohsr.currency_wars_equipment.equipment_slots',return_value=('empty',)*3), \
                    patch.object(StandardSession,'persist',fail_receipt_write),self.assertRaises(OSError):
                run_standard(c)
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'pending')
            self.assertNotIn('receipt',saved['actions'][-1])
            with self.assertRaises(AutomationError):run_standard(c)
            self.assertEqual(c.window.click.call_count,2)


if __name__ == '__main__':
    unittest.main()
