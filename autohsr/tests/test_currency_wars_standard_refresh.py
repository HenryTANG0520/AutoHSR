"""Current-price refreshes preserve growth phases and never replay unknown IO."""
from copy import deepcopy
from dataclasses import asdict, replace
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autohsr.currency_wars_collector import collected_snapshot
from autohsr.currency_wars_deployment import _crop, bench_face
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard, transition_ready
from autohsr.currency_wars_standard_ledger import ledger_status, valid_receipt
from autohsr.currency_wars_standard_policy import refresh_reason
from autohsr.currency_wars_standard_refresh import (PRICE_ROI, BUTTON_ROI, MAX_NODE_REFRESHES,
    MAX_NODE_REFRESH_SPEND, offer_table, refresh_action, refresh_price, supplement_refresh_price, table_digest)
from autohsr.currency_wars_standard_trading import (bench_signatures, financial_feedback,
    purchase_action, record_financial_feedback, shop_return_values)
from autohsr.currency_wars_state import UnitState
from autohsr.models import AutomationError, InputInterrupted, Scene, Stopped, Token, normalize
from autohsr.tests import test_currency_wars_standard_trading as helpers
from autohsr.tests import test_currency_wars_standard_policy as policy_helpers
from autohsr.tests import test_currency_wars_standard_market as market_helpers


def fixture(gold=30, price=2):
    board,session = helpers.full_board_fixture(gold=gold)
    _,shop,_ = helpers.purchase_fixture(gold=gold)
    shop.image = board.image.copy()
    # Five unrelated offers isolate refresh from the higher-priority purchase.
    for slot in range(5):
        left = .192+.14*slot
        shop.tokens = [t for t in shop.tokens if not t.within((left,.265,left+.115,.305))]
        shop.tokens.append(Token('其他候选'+str(slot),.99,(left,.27,left+.09,.30)))
    shop.tokens = [t for t in shop.tokens if not t.within(PRICE_ROI) and not t.within(BUTTON_ROI)]
    shop.tokens += [Token('刷新',.99,(.8297,.438,.8557,.465)),Token(str(price),.99,PRICE_ROI)]
    helpers.hud(shop,xp=(0,6))
    session.update(strategy='aglaea',actions=[dict(id=0,action='open_standard_shop',status='verified',input_epoch=0,
                                                before='board.png',after='shop.png')])
    session['pre_shop_snapshot'] = asdict(collected_snapshot(board,session,0,'before_shop'))
    session['pre_shop_bench'] = bench_signatures(board)
    return board,shop,session


def refreshed(before, choice, *, core=False, identical=False):
    after = Scene(list(before.tokens),before.image.copy(),captured_at=time.monotonic())
    helpers.hud(after,gold=choice.payload[1]-choice.payload[4])
    if not identical:
        left = .192
        after.tokens = [t for t in after.tokens if not t.within((left,.265,left+.115,.305))]
        after.tokens.append(Token('阿格莱雅' if core else '刷新候选',.99,(left,.27,left+.09,.30)))
    return after


def recorded(session, before, choice, after):
    action = dict(id=len(session['actions']),action=choice.intent,status='verified',input_epoch=0,
                  target=list(choice.payload),expected=choice.expected,before='before.png',after='after.png')
    session['actions'].append(action)
    record_financial_feedback(session,choice,financial_feedback(choice,before,after))
    return action


class StandardRefreshTests(unittest.TestCase):
    def test_saved_anonymized_shop_text_identifies_the_real_two_gold_button(self):
        shop = market_helpers.ShopFieldsTests().scene()
        self.assertEqual(refresh_price(shop),2)

    def test_current_button_price_including_free_and_multi_digit_is_used(self):
        for price in (0,1,2,6,12):
            with self.subTest(price=price):
                _,shop,session = fixture(price=price)
                choice = refresh_action(shop,session)
                self.assertEqual(choice.intent,'refresh_standard_shop')
                self.assertEqual(choice.payload[4],price)
                self.assertEqual(next_action(shop,session=session),choice)
                session['actions'].append(dict(action=choice.intent,status='pending',target=list(choice.payload),
                                                expected=choice.expected))
                self.assertEqual(next_action(shop,session=session),choice)

    def test_refresh_price_conflicts_unsupported_reading_and_wrong_button_block_input(self):
        for mutation in ('missing','conflict','negative','wide','low_confidence','wrong_button','duplicate_button'):
            _,shop,session = fixture()
            if mutation == 'missing':
                shop.tokens = [t for t in shop.tokens if not t.within(PRICE_ROI)]
            elif mutation == 'conflict':
                shop.tokens.append(Token('3',.99,PRICE_ROI))
            elif mutation in ('negative','wide','low_confidence'):
                shop.tokens = [Token('-2' if mutation=='negative' else '102' if mutation=='wide' else '2',
                                     .2 if mutation=='low_confidence' else .99,t.box) if t.within(PRICE_ROI) else t
                               for t in shop.tokens]
            elif mutation == 'wrong_button':
                shop.tokens = [Token('刷新',t.score,(.4,.4,.5,.5)) if normalize(t.text)=='刷新' else t for t in shop.tokens]
            else:
                shop.tokens.append(Token('刷新',.99,BUTTON_ROI))
            with self.subTest(mutation=mutation), self.assertRaises(AutomationError):
                refresh_action(shop,session)

    def test_missing_price_crop_needs_agreeing_high_confidence_variants(self):
        _,shop,_ = fixture()
        shop.tokens = [t for t in shop.tokens if not t.within(PRICE_ROI)]
        reader = Mock(spec=['read_number'])
        reader.read_number.side_effect = [Token('12',.99,(0,0,1,1)),Token('12',.95,(0,0,1,1))]
        result = supplement_refresh_price(shop,reader)
        self.assertEqual(refresh_price(result),12)
        for second in ('2','112',None):
            reader.read_number.side_effect = [Token('12',.99,(0,0,1,1)),
                                             Token(second,.99,(0,0,1,1)) if second else None]
            with self.subTest(second=second),self.assertRaises(AutomationError):
                refresh_price(supplement_refresh_price(shop,reader))
        shop.tokens.append(Token('102',.99,PRICE_ROI))
        reader.reset_mock()
        self.assertIs(supplement_refresh_price(shop,reader),shop)
        reader.read_number.assert_not_called()

    def test_gold_changed_table_and_unchanged_bench_are_all_required_even_when_free(self):
        for price in (0,2,12):
            _,shop,session = fixture(price=price)
            choice = refresh_action(shop,session)
            after = refreshed(shop,choice)
            receipt = financial_feedback(choice,shop,after)
            self.assertIsNotNone(receipt)
            self.assertTrue(transition_ready(choice,after,before=shop))
            action = recorded(session,shop,choice,after)
            self.assertTrue(valid_receipt(action))
            for mutation in ('money','identical','bench','missing_offer','missing_price','node','level','xp','odds'):
                bad = Scene(list(after.tokens),after.image.copy(),captured_at=time.monotonic())
                if mutation == 'money':
                    helpers.hud(bad,gold=29-price)
                elif mutation == 'identical':
                    bad = refreshed(shop,choice,identical=True)
                elif mutation == 'bench':
                    _crop(bad.image,bench_face(4))[:] = 0
                elif mutation == 'missing_offer':
                    bad.tokens = [t for t in bad.tokens if normalize(t.text)!='刷新候选']
                elif mutation == 'missing_price':
                    bad.tokens = [t for t in bad.tokens if not t.within((.301,.265,.317,.305))]
                elif mutation == 'node':
                    bad.tokens = [Token('1-2',t.score,t.box) if t.text=='1-1' else t for t in bad.tokens]
                elif mutation == 'level':
                    helpers.hud(bad,level=4)
                elif mutation == 'xp':
                    helpers.hud(bad,xp=(2,6))
                else:
                    bad.tokens = [t for t in bad.tokens if not t.within((.49,.33,.55,.39))]
                with self.subTest(price=price,mutation=mutation):
                    self.assertIsNone(financial_feedback(choice,shop,bad))

    def test_unknown_missing_offer_is_not_assumed_to_be_purchased(self):
        for mutation in ('name','price'):
            _,shop,session = fixture()
            roi = (.192,.265,.307,.305) if mutation=='name' else (.301,.265,.317,.305)
            shop.tokens = [t for t in shop.tokens if not t.within(roi)]
            with self.subTest(mutation=mutation),self.assertRaises(AutomationError):
                refresh_action(shop,session)

    def test_all_five_sold_out_slots_need_all_five_verified_purchase_sources(self):
        from autohsr.currency_wars_match import MatchState
        empty = MatchState('shop',node='1-1',offers=())
        for known in ((),(0,),(0,1,2,3)):
            with self.subTest(known=known),self.assertRaises(ValueError):
                offer_table(empty,known)
        table = offer_table(empty,range(5))
        self.assertEqual(table,[None]*5)
        self.assertEqual(len(table_digest(table)),64)
        with self.assertRaises(ValueError):table_digest(table,complete=True)

    def test_receipt_chain_updates_balance_and_evidence_before_buying_the_new_core(self):
        _,shop,session = fixture()
        choice = refresh_action(shop,session)
        after = refreshed(shop,choice,core=True)
        action = recorded(session,shop,choice,after)
        purchase = next_action(after,session=session)
        self.assertEqual(purchase.intent,'buy_standard_offer')
        self.assertEqual(purchase.payload[1],28)
        self.assertEqual(purchase.payload[5],'阿格莱雅')
        self.assertEqual(session['pre_shop_snapshot']['gold'],30)  # Original evidence is immutable.
        self.assertEqual(ledger_status(session['actions']),'clear')
        for mutation in ('gold','table','bench','status','orphan','source_gold'):
            bad = deepcopy(session)
            current = bad['actions'][-1]
            if mutation == 'gold':current['receipt']['gold_after'] = 29
            elif mutation == 'table':current['receipt']['offers_after'][0][0] = '错误角色'
            elif mutation == 'bench':current['receipt']['bench_after'] = '0'*64
            elif mutation == 'status':current['status'] = 'unknown'
            elif mutation == 'orphan':bad['actions'] = [current]
            else:bad['pre_shop_snapshot']['gold'] = 31
            with self.subTest(mutation=mutation),self.assertRaises(AutomationError):
                purchase_action(after,bad)
        self.assertTrue(valid_receipt(action))

    def test_refresh_close_returns_actual_balance_and_keeps_the_roster(self):
        _,shop,session = fixture()
        choice = refresh_action(shop,session)
        after = refreshed(shop,choice)
        recorded(session,shop,choice,after)
        # Exhaust the node budget so the next proposal closes this shop.
        with patch('autohsr.currency_wars_standard_policy.refresh_reason',return_value=None):
            close = next_action(after,session=session)
            self.assertEqual(close.intent,'close_standard_shop')
            self.assertEqual(close.payload,('1-1',28,session['pre_shop_snapshot']['hp'],3))
            self.assertEqual(shop_return_values(after,session), (close.payload,False))

    def test_node_refresh_limits_survive_closing_and_reopening_the_shop(self):
        board,current,session = fixture(price=0)
        for index in range(MAX_NODE_REFRESHES):
            choice = refresh_action(current,session)
            self.assertIsNotNone(choice)
            after = refreshed(current,choice)
            after.tokens = [Token('新候选'+str(index),t.score,t.box) if normalize(t.text)=='刷新候选' else t
                            for t in after.tokens]
            recorded(session,current,choice,after)
            current = after
        self.assertIsNone(refresh_action(current,session))
        for action in ('close_standard_shop','open_standard_shop'):
            session['actions'].append(dict(id=len(session['actions']),action=action,status='verified',input_epoch=0,
                                           before='before.png',after='after.png'))
        session['pre_shop_snapshot'] = asdict(collected_snapshot(board,session,0,'reopened'))
        self.assertIsNone(refresh_action(current,session))

    def test_cost_budget_is_accumulated_from_receipts_instead_of_cached_money(self):
        _,current,session = fixture(gold=40,price=4)
        for index in range(3):
            choice = refresh_action(current,session)
            after = refreshed(current,choice)
            after.tokens = [Token('新候选'+str(index),t.score,t.box) if normalize(t.text)=='刷新候选' else t
                            for t in after.tokens]
            recorded(session,current,choice,after)
            current = after
        self.assertEqual(session['actions'][-1]['receipt']['gold_after'],28)
        self.assertIsNone(refresh_action(current,session))

    def test_growth_phases_space_interest_and_per_node_limits_control_refreshing(self):
        state = policy_helpers.state(gold=30)
        for star,level,allowed in ((0,5,False),(0,6,True),(1,6,False),(1,7,True),(3,8,False),(3,9,True)):
            roster = tuple(replace(unit,name='希儿',star=star) if i==0 and star else unit
                           for i,unit in enumerate(state.roster))
            current = replace(state,level=level,roster=roster)
            with self.subTest(star=star,level=level):
                self.assertEqual(bool(refresh_reason(current,'seele',2,0,0)),allowed)
        self.assertFalse(refresh_reason(state,'default',2,0,0))  # Whole-level XP takes priority.
        self.assertTrue(refresh_reason(replace(state,gold=16),'default',2,0,0))
        self.assertFalse(refresh_reason(state,'aglaea',2,MAX_NODE_REFRESHES,0))
        self.assertFalse(refresh_reason(state,'aglaea',2,0,MAX_NODE_REFRESH_SPEND))
        self.assertFalse(refresh_reason(replace(state,gold=12),'aglaea',2,0,0))
        self.assertTrue(refresh_reason(replace(state,gold=12,hp=30),'aglaea',2,0,0))
        full = replace(state,roster=state.roster+tuple(UnitState('备战'+str(i),'bench',i,1,1) for i in range(1,10)),
                       bench_capacity=9,bench_occupied=9)
        self.assertFalse(refresh_reason(full,'aglaea',2,0,0))
        self.assertFalse(refresh_reason(replace(state,capacity=4),'aglaea',2,0,0))

    def test_full_context_records_before_one_click_and_waits_for_two_complete_frames(self):
        board,shop,session = fixture()
        choice = refresh_action(shop,session)
        after = refreshed(shop,choice,core=True)
        partial = Scene([t for t in after.tokens if normalize(t.text)!='阿格莱雅'],after.image.copy())
        with tempfile.TemporaryDirectory() as folder:
            c = helpers.StandardTradingTests().context(folder,board,session,[shop,partial,after,after])
            c.snapshot = Mock(side_effect=c.snapshot)
            def stop_after_refresh():
                actions = getattr(c,'currency_standard_session',SimpleNamespace(data={})).data.get('actions',[])
                if actions and actions[-1].get('action') == 'refresh_standard_shop' and actions[-1].get('status') == 'verified':
                    raise Stopped('refresh fixture completed')
            c.checkpoint = stop_after_refresh
            with patch('autohsr.currency_wars_replay.save_sample'),self.assertRaises(Stopped):
                run_standard(c)
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertTrue(valid_receipt(saved['actions'][-1]))
            self.assertEqual(saved['actions'][-1]['receipt']['gold_after'],28)
            self.assertEqual(saved['pre_shop_snapshot']['gold'],30)
            self.assertTrue(saved['collection']['complete'])
            self.assertEqual(c.snapshot.call_count,4)
            c.window.click.assert_called_once()
            c.currency_standard_input.assert_called_once()

    def test_unknown_refresh_is_not_replayed_and_cannot_be_closed_or_used_for_buying(self):
        board,shop,session = fixture()
        with tempfile.TemporaryDirectory() as folder:
            c = helpers.StandardTradingTests().context(folder,board,session,[shop,shop])
            with patch('autohsr.currency_wars_replay.save_sample'),patch('autohsr.currency_wars_standard_flow.time',
                    SimpleNamespace(monotonic=Mock(side_effect=[0,61]))):
                self.assertEqual(run_standard(c).status,'partial')
            saved = StandardSession(c.currency_standard_session.path).data
            self.assertEqual(saved['actions'][-1]['status'],'unknown')
            self.assertNotIn('receipt',saved['actions'][-1])
            with self.assertRaises(AutomationError):run_standard(c)
            with self.assertRaises(AutomationError):shop_return_values(shop,saved)
            c.window.click.assert_called_once()

    def test_pause_write_failure_and_account_change_never_create_a_verified_refresh(self):
        for case in ('pause','write','account'):
            board,shop,session = fixture()
            after = refreshed(shop,refresh_action(shop,session))
            with self.subTest(case=case),tempfile.TemporaryDirectory() as folder:
                c = helpers.StandardTradingTests().context(folder,board,session,[shop,after,after])
                if case == 'pause':c.currency_standard_input.side_effect = InputInterrupted('pause')
                elif case == 'account':
                    snapshot = c.snapshot
                    def wrong_account():
                        current = snapshot()
                        if current is after:
                            current.tokens = [Token('UID:200000000',t.score,t.box) if normalize(t.text).startswith('uid') else t
                                              for t in current.tokens]
                        return current
                    c.snapshot = wrong_account
                original = StandardSession.persist
                def persist(store):
                    if case=='write' and store.data['actions'][-1].get('action')=='refresh_standard_shop':
                        raise OSError('simulated locked journal')
                    return original(store)
                with patch('autohsr.currency_wars_replay.save_sample'),patch.object(StandardSession,'persist',persist), \
                        self.assertRaises((AutomationError,OSError)):
                    run_standard(c)
                saved = StandardSession(c.currency_standard_session.path).data
                if case == 'write':
                    c.window.click.assert_not_called()
                    self.assertEqual(len(saved['actions']),1)
                else:
                    self.assertEqual(saved['actions'][-1]['status'],'pending')
                    self.assertNotIn('receipt',saved['actions'][-1])
                    self.assertEqual(c.window.click.call_count,1 if case=='account' else 0)


if __name__ == '__main__':
    unittest.main()
