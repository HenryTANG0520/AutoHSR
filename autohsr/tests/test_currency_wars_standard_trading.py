"""Use actual page parsers, visual bench changes and Context input authority."""
from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import io
import re
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_collector import collected_snapshot, roster_cells
from autohsr.currency_wars_deployment import _crop, backend_layout, bench_face
from autohsr.currency_wars_match import read_match, verify_purchase
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard, transition_ready
from autohsr.currency_wars_standard_ledger import ledger_status, valid_receipt
from autohsr.currency_wars_standard_trading import (bench_signatures, experience_action, financial_feedback,
    purchase_action, record_financial_feedback)
from autohsr.models import AutomationError, InputInterrupted, Scene, Stopped, Token, normalize
from autohsr.tests import test_currency_wars_standard_flow as flow_helpers
from autohsr.tests import test_currency_wars_standard_market as market_helpers
from autohsr.tests.test_currency_wars_standard_deployment import frame_and_session


def hud(scene, *, gold=None, level=None, xp=None, deployment=None):
    for value, roi, label, pattern in ((gold,(.851,.829,.87,.868),str(gold),r'[0-9]+'),
                               (level,(.125,.815,.185,.87),'Lv.'+str(level),r'lv\.?[0-9]+'),
                               (xp,(.13,.865,.18,.9),None if xp is None else f'{xp[0]}/{xp[1]}',r'[0-9]+/[0-9]+'),
                               (deployment,(.43,.18,.55,.36),None if deployment is None else f'{deployment[0]}/{deployment[1]}',r'[iIl|]?[0-9]+/[0-9]+')):
        if value is not None:
            scene.tokens = [token for token in scene.tokens if not (token.within(roi) and re.fullmatch(pattern,normalize(token.text)))]
            scene.tokens.append(Token(label,.99,roi))
    return scene


def purchase_fixture(gold=25, price=1):
    board, session = frame_and_session()
    hud(board,gold=gold)
    session.update(strategy='aglaea',actions=[dict(id=0,action='open_standard_shop',status='verified',input_epoch=0,
                                                  before='board.png',after='shop.png')])
    session['shop_observed_nodes'] = []
    session['pre_shop_snapshot'] = asdict(collected_snapshot(board,session,0,'before_shop'))
    session['pre_shop_bench'] = bench_signatures(board)
    shop = market_helpers.ShopFieldsTests().scene()
    shop.image = board.image.copy()
    shop.captured_at = time.monotonic()
    shop.tokens = [token for token in shop.tokens if not normalize(token.text).startswith('uid')]
    shop.tokens.append(Token('UID:100000000',.99,(.01,.96,.1,.99)))
    hud(shop,gold=gold,level=3)
    price_roi = (.301+.14,.265,.317+.14,.305)
    shop.tokens = [token for token in shop.tokens if not token.within(price_roi)]
    shop.tokens.append(Token(str(price),.99,price_roi))
    return board,shop,session


def purchased(before, choice):
    after = Scene(list(before.tokens),before.image.copy(),captured_at=time.monotonic())
    slot,price = choice.payload[4],choice.payload[6]
    left = .192+.14*slot
    after.tokens = [token for token in after.tokens if not token.within((left,.265,left+.13,.305))]
    hud(after,gold=choice.payload[1]-price)
    patch = _crop(after.image,bench_face(6))
    patch[:] = np.random.default_rng(416).integers(0,256,patch.shape,dtype=np.uint8)
    return after


def full_board_fixture(gold=25, level=3, experience=(0,6)):
    board,session = frame_and_session()
    records = session['collection']['units']
    for slot in (4,5):
        records['bench:'+str(slot)]['unit'].update(name='备战弱角'+str(slot),tier=1,traits=())
    old = [records['bench:'+str(i)] for i in range(1,4)]
    for i in range(1,4):
        _crop(board.image,bench_face(i))[:] = 0
        records.pop('bench:'+str(i))
    _,centers = backend_layout(board.image)
    locations = [('front',1,990/2560,.33,.41),('back',1,centers[0],.58,.66),('front',2,1180/2560,.33,.41)]
    if level > 3:
        locations += [('front',i,x/2560,.33,.41) for i,x in enumerate((1370,1560),3)]
        locations += [('back',i,centers[i-1],.58,.66) for i in range(2,7)]
        locations = locations[:level]
    for index, (zone,slot,x,top,bottom) in enumerate(locations):
        patch = _crop(board.image,(x-.025,top,x+.025,bottom))
        patch[:] = np.random.default_rng(700+index).integers(0,256,patch.shape,dtype=np.uint8)
    hud(board,gold=gold,level=level,xp=experience,deployment=(level,level))
    board.tokens.append(Token('4',.99,(.16,.91,.17,.93)))
    cells = {(cell.zone,cell.slot):cell for cell in roster_cells(board)}
    for index,(zone,slot,*_) in enumerate(locations):
        cell = cells[(zone,slot)]
        unit = dict(old[index]['unit'],zone=zone,slot=slot) if index < len(old) else dict(
            name='其他角色'+str(index),zone=zone,slot=slot,star=1,tier=1,traits=(),equipment=(),eligible_zones=(zone,))
        records[zone+':'+str(slot)] = dict(unit=unit,
                                         signature=cell.signature,node=cell.node,source='field.png')
    session['strategy'] = 'default'
    return board,session


class StandardTradingTests(unittest.TestCase):
    def context(self, folder, board, session, states):
        c = flow_helpers.StandardFlowTests().context(folder,states,resume=True)
        session = deepcopy(session)
        session['account_verified_run'] = c.report.run_dir
        session['client']['verified_run'] = c.report.run_dir
        session['collection']['run_dir'] = c.report.run_dir
        session['pre_shop_snapshot'] = asdict(collected_snapshot(board,session,0,'before_shop'))
        store = StandardSession(Path(folder)/'currency-standard-session.json')
        store.begin(folder,dict(rank_verified=True))
        store.data.update(session)
        store.persist()
        c.window = Mock()
        c.currency_standard_input = Mock(side_effect=lambda scene,choice:Context.currency_standard_input(c,scene,choice))
        return c

    def test_real_offer_texts_and_complete_board_choose_core_with_current_price(self):
        for gold,price in ((25,1),(30,6),(30,12),(0,0)):
            with self.subTest(price=price):
                _,shop,session = purchase_fixture(gold,price)
                choice = purchase_action(shop,session)
                self.assertEqual(choice.intent,'buy_standard_offer')
                self.assertEqual(choice.payload[5:7],('阿格莱雅',price))
                self.assertEqual(next_action(shop,session=session),choice)
                session['actions'].append(dict(action=choice.intent,status='pending',target=list(choice.payload),expected=choice.expected))
                self.assertEqual(next_action(shop,session=session),choice)

    def test_account_epoch_version_ledger_and_bench_change_block_paid_proposals(self):
        for mutation in ('epoch','version','pending','bench','snapshot'):
            _,shop,session = purchase_fixture()
            if mutation == 'epoch':
                session['account_verified_epoch'] = 1
            elif mutation == 'version':
                session['client']['version'] = '4.7'
            elif mutation == 'pending':
                session['actions'][-1]['status'] = 'unknown'
            elif mutation == 'bench':
                _crop(shop.image,bench_face(1))[:] = 0
            else:
                session['pre_shop_snapshot']['gold'] = 30
            with self.subTest(mutation=mutation), self.assertRaises(AutomationError):
                purchase_action(shop,session)

    def test_payment_offer_and_visual_feedback_must_all_match_without_legacy_scope_change(self):
        for price in (0,1,6,12):
            _,shop,session = purchase_fixture(30,price)
            choice = purchase_action(shop,session)
            after = purchased(shop,choice)
            receipt = financial_feedback(choice,shop,after)
            self.assertIsNotNone(receipt)
            self.assertTrue(transition_ready(choice,after,before=shop))
            action = dict(action=choice.intent,status='verified',target=list(choice.payload),before='before.png',after='after.png',receipt=receipt)
            self.assertTrue(valid_receipt(action))
            self.assertEqual(ledger_status([action]),'clear')
            if price not in (1,2,3,4,5):
                offer = next(offer for offer in read_match(shop).offers if offer.slot == choice.payload[4])
                self.assertEqual(verify_purchase(read_match(shop),read_match(after),offer),'unknown')
            for mutation in ('money','other_offer','unchanged_bench','same_offer','node','fading_bench'):
                bad = Scene(list(after.tokens),after.image.copy(),captured_at=time.monotonic())
                if mutation == 'money':
                    hud(bad,gold=29-price)
                elif mutation == 'other_offer':
                    bad.tokens = [Token('其他名字',t.score,t.box) if t.text == '藿藿' else t for t in bad.tokens]
                elif mutation == 'unchanged_bench':
                    bad.image = shop.image.copy()
                elif mutation == 'same_offer':
                    bad.tokens = list(shop.tokens)
                    hud(bad,gold=30-price)
                elif mutation == 'node':
                    bad.tokens = [Token('1-2',t.score,t.box) if t.text == '1-1' else t for t in bad.tokens]
                else:
                    patch = _crop(bad.image,bench_face(6))
                    patch[:] = np.random.default_rng(73).integers(100,138,patch.shape,dtype=np.uint8)
                with self.subTest(price=price,mutation=mutation):
                    self.assertIsNone(financial_feedback(choice,shop,bad))

    def test_one_purchase_returns_to_board_and_requires_recollection_before_more_trading(self):
        _,shop,session = purchase_fixture()
        choice = purchase_action(shop,session)
        after = purchased(shop,choice)
        action = dict(id=1,action=choice.intent,status='verified',target=list(choice.payload),input_epoch=0,
                      before='before.png',after='after.png')
        session['actions'].append(action)
        record_financial_feedback(session,choice,financial_feedback(choice,shop,after))
        session.pop('collection')
        close = next_action(after,session=session)
        self.assertEqual(close.intent,'close_standard_shop_after_purchase')
        self.assertEqual(close.payload[1],24)
        session['actions'].append(dict(id=2,action=close.intent,status='pending',target=list(close.payload),expected=close.expected))
        self.assertEqual(next_action(after,session=session),close)
        self.assertEqual(ledger_status(session['actions']),'pending')

    def test_full_flow_uses_durable_context_input_and_two_frames_then_invalidates_roster(self):
        board,shop,session = purchase_fixture()
        choice = purchase_action(shop,session)
        first,second = purchased(shop,choice),purchased(shop,choice)
        returned = Scene(list(board.tokens),second.image.copy(),captured_at=time.monotonic())
        hud(returned,gold=24)
        with tempfile.TemporaryDirectory() as folder:
            c = self.context(folder,board,session,[shop,first,second,returned])
            def stop_after_phase():
                actions = getattr(c,'currency_standard_session',SimpleNamespace(data={})).data.get('actions',[])
                if actions and actions[-1]['action']=='close_standard_shop_after_purchase' and actions[-1]['status']=='verified':
                    raise Stopped('fixture phase completed')
            c.checkpoint = stop_after_phase
            with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaises(Stopped):
                run_standard(c)
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual([a['action'] for a in saved['actions']],
                             ['open_standard_shop','buy_standard_offer','close_standard_shop_after_purchase'])
            self.assertEqual([a['status'] for a in saved['actions']],['verified']*3)
            self.assertEqual(saved['actions'][1]['receipt']['gold_after'],24)
            self.assertNotIn('collection',saved)
            self.assertNotIn('1-1',saved['shop_observed_nodes'])
            self.assertEqual(ledger_status(saved['actions']),'clear')
            self.assertEqual(c.window.click.call_count,2)
            self.assertEqual(c.currency_standard_input.call_count,2)
            self.assertFalse(saved['completion_verified'])

    def test_unknown_paid_feedback_is_kept_and_never_replayed_on_resume(self):
        board,shop,session = purchase_fixture()
        with tempfile.TemporaryDirectory() as folder:
            c = self.context(folder,board,session,[shop,shop])
            with patch('autohsr.currency_wars_replay.save_sample'), \
                    patch('autohsr.currency_wars_standard_flow.time',SimpleNamespace(monotonic=Mock(side_effect=[0,61]))):
                self.assertEqual(run_standard(c).status,'partial')
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'unknown')
            self.assertNotIn('receipt',saved['actions'][-1])
            c.window.click.assert_called_once()
            with self.assertRaises(AutomationError):run_standard(c)
            c.window.click.assert_called_once()

    def test_experience_flow_rederives_its_own_intent_and_uses_context_once(self):
        board,session = full_board_fixture(gold=22)
        first = Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
        second = Scene(list(board.tokens),board.image.copy(),captured_at=time.monotonic())
        hud(first,gold=18,xp=(4,6));hud(second,gold=18,xp=(4,6))
        with tempfile.TemporaryDirectory() as folder:
            c = self.context(folder,board,session,[board,first,second])
            def stop_after_purchase():
                actions = getattr(c,'currency_standard_session',SimpleNamespace(data={})).data.get('actions',[])
                if actions and actions[-1].get('action')=='buy_standard_experience' and actions[-1].get('status')=='verified':
                    raise Stopped('experience fixture completed')
            c.checkpoint = stop_after_purchase
            with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaises(Stopped):
                run_standard(c)
            saved = StandardSession(c.currency_standard_session.path).data
            c.window.click.assert_called_once()
            self.assertTrue(valid_receipt(saved['actions'][-1]))
            self.assertEqual(saved['actions'][-1]['receipt']['gold_after'],18)

    def test_pause_wrong_account_and_write_failure_do_not_settle_a_payment(self):
        for case in ('pause','account','write'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                board,shop,session = purchase_fixture()
                after = purchased(shop,purchase_action(shop,session))
                c = self.context(folder,board,session,[shop,after,after])
                if case=='pause':
                    c.currency_standard_input.side_effect = InputInterrupted('pause')
                elif case=='account':
                    snapshot = c.snapshot
                    count = 0
                    def changed_account():
                        nonlocal count
                        scene = snapshot();count += 1
                        if count==2:
                            scene.tokens[-1] = Token('UID:200000000',.99,(.01,.96,.1,.99))
                        return scene
                    c.snapshot = changed_account
                original = StandardSession.persist
                def persist(store):
                    if case=='write' and store.data['actions'][-1].get('action')=='buy_standard_offer':
                        raise OSError('simulated sharing lock')
                    return original(store)
                with patch('autohsr.currency_wars_replay.save_sample'), patch.object(StandardSession,'persist',persist), \
                        self.assertRaises((AutomationError,OSError)):
                    run_standard(c)
                saved = StandardSession(c.currency_standard_session.path).data
                if case=='write':
                    c.window.click.assert_not_called()
                    self.assertEqual(len(saved['actions']),1)
                else:
                    self.assertEqual(saved['actions'][-1]['status'],'pending')
                    self.assertNotIn('receipt',saved['actions'][-1])
                    self.assertEqual(c.window.click.call_count,1 if case=='account' else 0)

    def test_a_recorded_strategy_cannot_be_changed_by_a_resume_flag(self):
        board,shop,session = purchase_fixture()
        with tempfile.TemporaryDirectory() as folder:
            c = self.context(folder,board,session,[shop])
            c.runner.currency_strategy = 'seele'
            c.snapshot = Mock()
            with self.assertRaises(AutomationError):run_standard(c)
            c.snapshot.assert_not_called()
            c.window.click.assert_not_called()
            self.assertEqual(StandardSession(c.currency_standard_session.path).data['strategy'],'aglaea')

    def test_own_pending_close_or_start_is_rederived_without_bypassing_decisions(self):
        _,shop,session = purchase_fixture(gold=10)
        close = next_action(shop,session=session)
        self.assertEqual(close.intent,'close_standard_shop')
        session['actions'].append(dict(action=close.intent,status='pending',target=list(close.payload),expected=close.expected))
        self.assertEqual(next_action(shop,session=session),close)
        board,session = full_board_fixture(gold=0)
        start = next_action(board,session=session)
        self.assertEqual(start.intent,'start_standard_node')
        session['actions'].append(dict(id=0,action=start.intent,status='pending',target=list(start.payload),expected=start.expected))
        session['node_attempt'] = dict(node='1-1',status='start_pending',start_action_id=0)
        self.assertEqual(next_action(board,session=session),start)

    def test_experience_is_bought_one_step_at_a_time_with_exact_spend_and_progress(self):
        before,session = full_board_fixture(gold=22)
        choice = experience_action(before,session)
        self.assertEqual(choice.intent,'buy_standard_experience')
        first = Scene(list(before.tokens),before.image.copy(),captured_at=time.monotonic())
        hud(first,gold=18,xp=(4,6))
        receipt = financial_feedback(choice,before,first)
        self.assertIsNotNone(receipt)
        action = dict(action=choice.intent,status='verified',target=list(choice.payload),before='before.png',after='first.png')
        session['actions'].append(action)
        record_financial_feedback(session,choice,receipt)
        second_choice = experience_action(first,session)
        self.assertEqual(second_choice.payload[1],18)
        final = Scene(list(first.tokens),first.image.copy(),captured_at=time.monotonic())
        hud(final,gold=14,level=4,xp=(2,10),deployment=(3,4))
        receipt = financial_feedback(second_choice,first,final)
        self.assertIsNotNone(receipt)
        action = dict(action=second_choice.intent,status='verified',target=list(second_choice.payload),before='first.png',after='final.png')
        session['actions'].append(action)
        record_financial_feedback(session,second_choice,receipt)
        self.assertNotIn('1-1',session['shop_observed_nodes'])
        self.assertEqual(ledger_status(session['actions']),'clear')
        self.assertIsNone(experience_action(final,session))
        for bad in (hud(Scene(list(final.tokens),final.image.copy()),gold=13),
                    hud(Scene(list(final.tokens),final.image.copy()),xp=(3,10)),
                    hud(Scene(list(final.tokens),final.image.copy()),deployment=(3,3))):
            self.assertIsNone(financial_feedback(second_choice,first,bad))

    def test_maximum_level_needs_both_level_and_visible_maximum_label(self):
        before,session = full_board_fixture(gold=20,level=9,experience=(8,10))
        choice = experience_action(before,session)
        after = Scene(list(before.tokens),before.image.copy())
        hud(after,gold=16,level=10,deployment=(9,10))
        after.tokens = [t for t in after.tokens if not t.within((.13,.865,.18,.9))]
        self.assertIsNone(financial_feedback(choice,before,after))
        after.tokens.append(Token('已满级',.99,(.13,.78,.18,.81)))
        receipt = financial_feedback(choice,before,after)
        self.assertIsNotNone(receipt)
        action = dict(action=choice.intent,status='verified',target=list(choice.payload),before='before.png',after='after.png',receipt=receipt)
        self.assertTrue(valid_receipt(action))

    def test_corrupt_or_unknown_financial_receipts_cannot_clear_the_ledger(self):
        _,shop,session = purchase_fixture()
        choice = purchase_action(shop,session)
        action = dict(action=choice.intent,status='verified',target=list(choice.payload),before='before.png',after='after.png',
                      receipt=financial_feedback(choice,shop,purchased(shop,choice)))
        for mutation in ('missing','price','target','picture','action','types'):
            bad = deepcopy(action)
            if mutation == 'missing':bad.pop('receipt')
            elif mutation == 'price':bad['receipt']['gold_after'] -= 1
            elif mutation == 'target':bad['target'][5] = '其他角色'
            elif mutation == 'picture':bad['receipt']['bench_after'] = bad['receipt']['bench_before']
            elif mutation == 'action':bad['action'] = 'unknown_payment'
            else:bad['target'] = ['1-1']
            with self.subTest(mutation=mutation):
                self.assertEqual(ledger_status([bad]),'unknown')
        self.assertEqual(ledger_status([dict(action='continue_standard_node',status='verified')]),'clear')

    def test_cli_strategy_is_scoped_ephemeral_and_runner_rejects_other_operations(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'config.json'
            Settings().save(config)
            original = config.read_bytes()
            for strategy in ('default','aglaea','seele'):
                with patch('autohsr.app.Runner') as runner, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    runner.return_value.run.return_value = dict(status='partial')
                    main(['--currency-wars-standard','--currency-strategy',strategy,'--config',str(config)])
                    self.assertEqual(runner.call_args.kwargs['currency_strategy'],strategy)
            self.assertEqual(config.read_bytes(),original)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            main(['--currency-strategy','aglaea','--check'])
        with self.assertRaises(ValueError):Runner(Settings(),currency_strategy='aglaea')


if __name__ == '__main__':
    unittest.main()
