"""Standard investment reroll through the native input and durable journal."""
from copy import deepcopy
from dataclasses import replace
from itertools import count
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2

from autohsr.config import RESOURCE_ROOT
from autohsr.currency_wars_investment_policy import options as investment_options
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard
from autohsr.currency_wars_standard_investment import CLOSE_SHOP, CONFIRM, SELECT
from autohsr.currency_wars_standard_investment_refresh import BINDING, MAX_REFRESHES, _current_table, valid_receipt
from autohsr.currency_wars_standard_ledger import ledger_status
from autohsr.models import AutomationError, InputInterrupted, Scene, Stopped, Token, normalize
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_investment as investment
from autohsr.tests import test_currency_wars_standard_rewards as rewards


REFRESH = 'refresh_standard_investment'
UNSUPPORTED = (
    ('昼之半神星徽套组', '获得一个昼之半神星徽和一件遗器。'),
    ('追击星徽套组', '获得一个追击星徽和一件遗器。'),
    ('专家研讨会', '获得两个随机的专家徽记。'),
)
SUPPORTED = ('爆仓', investment.EXECUTE)
COUNTER_LEFT = (560, 1227, 1891)
OVERLAYS = {
    'quote_confirm': '「确认刷新」',
    'quote_charge': '「需消耗10金币」',
    'curly_confirm': '“确认”',
    'auth': '请输入验证码',
    'update': '「更新游戏」',
    'download': '资源下载中',
    'external': '“补充开拓力”',
    'external_price': '“请支付１０星琼”',
}
PRICE_OVERLAYS = {
    'subject_deduct': ('「刷新扣除10金币」',),
    'per_use_consume': ('「每次刷新消耗10金币」',),
    'quote_first': ('「花费十金币即可刷新本列」',),
    'fullwidth_payment': ('单次刷新将支付１０星琼',),
    'debit_after_refresh': ('刷新后扣除10金币',),
    'future_debit': ('扣除10金币之后再刷新投资策略',),
    'nested_modifier': ('刷新本列需先花费10金币',),
    'separated_quote': ('「刷新扣除」', '10金币'),
    'separated_subject': ('刷新', '花费', '10', '金币'),
    'amount_first': ('10金币可刷新本列',),
    'price_after_refresh': ('本列刷新：１０金币',),
    'separated_amount': ('刷新', '１０', '金币'),
    'missing_resource': ('本列刷新花费10',),
    'missing_amount': ('刷新支付金币',),
    'unread_quote': ('刷新扣除',),
    'standalone_price': ('价格：十金币',),
    'standalone_price_assignment': ('费用为10金币',),
    'standalone_rate': ('１０金币/次',),
    'unit_first': ('每次收取金币×10',),
}


def count_tokens(frame, counts):
    tokens = [token for token in frame.tokens if not normalize(token.text).startswith('刷新次数')]
    return tokens + [Token('刷新次数'+str(remaining), .99, (left/2560, 1120/1440, (left+152)/2560, 1160/1440))
                     for left, remaining in zip(COUNTER_LEFT, counts)]


def investment_page(cards, counts, *, selected=None, gray=()):
    frame = investment.page(cards, selected=selected)
    frame.tokens = count_tokens(frame, counts)
    icon = cv2.imread(str(RESOURCE_ROOT/'assets/templates/currency_investment_refresh_4_6.png'))
    for slot, (left, remaining) in enumerate(zip(COUNTER_LEFT, counts)):
        if remaining:
            frame.image[1107:1175, left-77:left-9] = icon if slot not in gray else (icon*.5).astype(icon.dtype)
    return frame


def place_price(frame, segments, left):
    width = .14/len(segments)
    for index, text in enumerate(segments):
        x = left + index*width
        frame.tokens.append(Token(text, .99, (x, .66, x+width*.9, .70)))


def quote_variants():
    directions = (('前置', ('刷新本列', '需', '１０', '金币')),
                  ('后置', ('需', '１０', '金币', '即可', '刷新本列')))
    for direction, pieces in directions:
        for missing in ('', '需', '金币', '１０'):
            parts = [piece for piece in pieces if piece != missing]
            for layout in ('整句', '拆框', '跨列'):
                if layout == '整句':
                    tokens = [Token('「'+''.join(parts)+'」', .99, (.14, .541, .34, .565))]
                elif layout == '拆框':
                    width = .20/len(parts)
                    tokens = [Token(part, .99, (.14+i*width, .541, .14+(i+.9)*width, .565))
                              for i, part in enumerate(parts)]
                else:
                    cut = len(parts)//2
                    tokens = [Token(''.join(parts[:cut]), .99, (.325, .541, .363, .565)),
                              Token(''.join(parts[cut:]), .99, (.378, .541, .428, .565))]
                yield (direction, missing, layout), tokens
    for amount in ('「１０金币」', '１０', '“金币”', '需１０'):
        yield amount, [Token(amount, .99, (.14, .541, .25, .565))]
    yield '低可信报价', [Token('１０金币', .62, (.14, .541, .25, .565))]
    yield '跨列拆词', [Token('刷', .99, (.325, .541, .363, .565)),
                       Token('新', .99, (.378, .541, .416, .565))]


def split_scoped_rules(frame):
    frame.tokens = [token for token in frame.tokens if not token.within((.38, .48, .88, .74))]
    variants = ((.40, ('消耗2金币', '后', '下一场战斗中我方伤害提高15%。')),
                (.66, ('商店每次刷新', '消耗10金币', '后，可获得2经验值。')))
    for x, lines in variants:
        for index, text in enumerate(lines):
            y = .488+index*.027
            frame.tokens.append(Token(text, .99, (x, y, x+.12, y+.024)))
    return frame


def fixture(node='2-1'):
    board, _, session = investment.fixture(UNSUPPORTED)
    if node == '3-1':
        rewards.node(board, node)
        started, advanced, plane = session['actions']
        for action in (started, advanced, plane):
            action['target'][0] = '2-6'
        advanced['feedback']['node'] = plane['target'][2] = node
        session['expected_board'] = session['investment']['expected_node'] = node
        session['node_attempt']['node'] = '2-6'
        for record in session['collection']['units'].values():
            record['node'] = node
    return board, session


def context(folder, board, session, frames):
    result = exchange.StandardExchangeTests().context(folder, board, session, frames)
    investment.fresh_captures(result)
    return result


def stop_after_confirmation(context):
    if context.currency_standard_session.data['investment']['status'] == 'verified':
        raise Stopped('investment applied')


class InvestmentRefreshFlowTests(unittest.TestCase):
    def test_public_redacted_plane_three_card_text_has_continuous_columns(self):
        path = Path(__file__).parent/'fixtures/currency_wars_investment_plane3.json'
        fixture_data = json.loads(path.read_text(encoding='utf-8'))
        scene = Scene([Token(**token) for token in fixture_data['tokens']])
        rows, counters = _current_table(scene, investment_options(scene), '3-1', .65)
        self.assertEqual([row[3] for row in rows], [1, 1, 1])
        self.assertEqual([normalize(token.text) for token in counters], ['刷新次数1']*3)

    def test_formal_refresh_confirms_only_a_choice_from_the_verified_new_table(self):
        board, session = fixture()
        before = investment_page(UNSUPPORTED, (1, 1, 1))
        cards = (SUPPORTED, *UNSUPPORTED[1:])
        after = investment_page(cards, (0, 1, 1))
        marked = investment_page(cards, (0, 1, 1), selected=0)
        with tempfile.TemporaryDirectory() as folder:
            current = context(folder, board, session,
                [before, after, deepcopy(after), marked, deepcopy(marked), board, deepcopy(board)])
            current.checkpoint = lambda: stop_after_confirmation(current)
            with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaisesRegex(Stopped, 'investment applied'):
                run_standard(current)
            saved = StandardSession(current.currency_standard_session.path).data
            actions = saved['actions']
            refreshed, selected, confirmed = actions[3:]
            self.assertEqual([item['action'] for item in (refreshed, selected, confirmed)], [REFRESH, SELECT, CONFIRM])
            self.assertEqual(current.window.click.call_count, 3)
            self.assertEqual(current.window.click.call_args_list[0].args[:2], (517/2560, 1141/1440))
            self.assertEqual(selected[BINDING], confirmed[BINDING])
            self.assertEqual(confirmed[BINDING]['refresh_action_id'], refreshed['id'])
            self.assertEqual(confirmed['target'][6], refreshed['investment_refresh_receipt']['candidates_digest'])
            self.assertEqual(confirmed['target'][3], SUPPORTED[0])
            self.assertEqual(ledger_status(actions), 'clear')
            for field in ('receipt', 'frame', 'selection', 'confirmation', 'plane'):
                with self.subTest(tampered=field):
                    damaged = deepcopy(actions)
                    if field == 'receipt':
                        damaged[3]['investment_refresh_receipt']['remaining_after'] = 1
                    elif field == 'frame':
                        damaged[3]['progress_frames'][0]['candidates_digest'] = '0'*64
                    elif field == 'plane':
                        damaged[2]['after'] = 'different-plane.png'
                    else:
                        damaged[4 if field == 'selection' else 5].pop(BINDING)
                    self.assertEqual(ledger_status(damaged), 'unknown')

    def test_plane_three_uses_highest_quota_then_left_tie_even_when_first_card_does_not_change(self):
        board, session = fixture('3-1')
        original = (UNSUPPORTED[0], ('黄金收益', '获得10金币。'), ('现金为王', investment.CASH_XP))
        before = investment_page(original, (2, 3, 0))
        same = investment_page(original, (2, 2, 0))
        cards = (SUPPORTED, *original[1:])
        after = investment_page(cards, (1, 2, 0))
        marked = investment_page(cards, (1, 2, 0), selected=0)
        shop = investment.automatic_shop(board)
        with tempfile.TemporaryDirectory() as folder:
            current = context(folder, board, session,
                [before, same, deepcopy(same), after, deepcopy(after), marked, deepcopy(marked),
                 board, deepcopy(board), shop, deepcopy(shop), board, deepcopy(board)])

            def stop_after_shop():
                last = current.currency_standard_session.data['actions'][-1]
                if last['action'] == CLOSE_SHOP and last['status'] == 'verified':
                    raise Stopped('investment shop closed')

            current.checkpoint = stop_after_shop
            with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaisesRegex(Stopped, 'investment shop closed'):
                run_standard(current)
            actions = StandardSession(current.currency_standard_session.path).data['actions']
            first, second, selected, confirmed, closed = actions[3:]
            self.assertEqual([first['target'][:4], second['target'][:4]], [['3-1', 2, 1, 3], ['3-1', 2, 0, 2]])
            self.assertFalse(first['investment_refresh_receipt']['card_changed'])
            self.assertTrue(second['investment_refresh_receipt']['card_changed'])
            self.assertEqual(selected[BINDING]['refresh_action_id'], second['id'])
            self.assertEqual(confirmed[BINDING], selected[BINDING])
            self.assertEqual(closed['target'][:2], ['3-1', confirmed['id']])
            self.assertEqual(current.window.click.call_count, 5)
            self.assertEqual(ledger_status(actions), 'clear')

    def test_missing_or_blocked_current_controls_never_send(self):
        for failure in ('zero', 'grey_maximum', 'edge_clipped', 'one_read', 'two_read', 'counter_low',
                        'duplicate', 'cost', 'confirm_overlay', 'selected', 'wrong_node', 'missing_effect',
                        *OVERLAYS, *PRICE_OVERLAYS):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                board, session = fixture()
                counts = (0, 0, 0) if failure == 'zero' else (3, 2, 1)
                frame = investment_page(UNSUPPORTED, counts, selected=0 if failure == 'selected' else None,
                                        gray=(0,) if failure == 'grey_maximum' else ())
                if failure == 'edge_clipped':
                    frame.image[1107:1175, 483:520] = 0
                elif failure in ('one_read', 'two_read'):
                    missing = (.24, .76) if failure == 'one_read' else (.76,)
                    frame.tokens = [t for t in frame.tokens if not (.43 <= t.center[1] <= .84
                        and any(abs(t.center[0]-x)<.10 for x in missing))]
                elif failure == 'counter_low':
                    frame.tokens[-1] = replace(frame.tokens[-1], score=.86)
                elif failure == 'duplicate':
                    frame.tokens.append(frame.tokens[-1])
                elif failure == 'cost':
                    frame.tokens.append(Token('需消耗10金币', .99, (.46, .67, .54, .71)))
                elif failure == 'confirm_overlay':
                    frame.tokens.append(Token('「确认」', .99, (.59, .65, .65, .68)))
                elif failure == 'wrong_node':
                    frame.tokens.append(Token('3-1', .99, (.12, .052, .15, .081)))
                elif failure == 'missing_effect':
                    frame.tokens = [t for t in frame.tokens if not t.within((.64, .48, .86, .74))]
                    frame.tokens.append(Token('。', .99, (.72, .49, .77, .53)))
                elif failure in OVERLAYS:
                    frame.tokens.append(Token(OVERLAYS[failure], .99, (.56, .66, .62, .70)))
                elif failure in PRICE_OVERLAYS:
                    place_price(frame, PRICE_OVERLAYS[failure], .18)
                current = context(folder, board, session, [frame, board, deepcopy(board)])
                clock = SimpleNamespace(monotonic=Mock(side_effect=count(0, 31)))
                with (patch('autohsr.currency_wars_replay.save_sample'),
                      patch('autohsr.currency_wars_standard_flow.time', clock)):
                    self.assertEqual(run_standard(current).status, 'partial')
                current.window.click.assert_not_called()
                current.window.click_held.assert_not_called()
                self.assertEqual(len(StandardSession(current.currency_standard_session.path).data['actions']), 3)

    def test_local_icon_works_at_supported_scales_and_normal_selection_does_not_require_it(self):
        _, session = fixture()
        frame = investment_page(UNSUPPORTED, (0, 1, 0))
        for width, height in ((1280, 720), (1920, 1080), (2560, 1440), (3840, 2160)):
            with self.subTest(width=width):
                scaled = replace(frame, image=cv2.resize(frame.image, (width, height)))
                choice = next_action(scaled, session=session)
                self.assertEqual(choice.intent, REFRESH)
                self.assertEqual(choice.payload[:4], ('2-1', 2, 1, 1))
                self.assertAlmostEqual(choice.target.center[0], (1227-43)/2560, places=3)
        for total in (1, 2, 3):
            with self.subTest(total=total):
                options = investment.page((SUPPORTED, *UNSUPPORTED[:total-1]))
                self.assertEqual(next_action(options, session=session).intent, SELECT)
        recurring = (('现金为王', investment.CASH_XP), ('参与条件', '需要1个击破角色参加下一场战斗。'), UNSUPPORTED[2])
        self.assertEqual(next_action(investment_page(recurring, (1, 0, 0)), session=session).intent, REFRESH)

    def test_formal_refresh_preserves_later_battle_and_explicit_shop_effects(self):
        board, session = fixture()
        cards = (UNSUPPORTED[0], ('消费规则变体', '消耗2金币后，下一场战斗中我方伤害提高15%。'),
                 ('商店收益变体', '商店每次刷新消耗10金币后，可获得2经验值。'))
        before = split_scoped_rules(investment_page(cards, (2, 1, 1)))
        supported = (SUPPORTED, *cards[1:])
        after = split_scoped_rules(investment_page(supported, (1, 1, 1)))
        marked = split_scoped_rules(investment_page(supported, (1, 1, 1), selected=0))
        with tempfile.TemporaryDirectory() as folder:
            current = context(folder, board, session,
                [before, after, deepcopy(after), marked, deepcopy(marked), board, deepcopy(board)])
            current.checkpoint = lambda: stop_after_confirmation(current)
            with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaisesRegex(Stopped, 'investment applied'):
                run_standard(current)
            actions = StandardSession(current.currency_standard_session.path).data['actions']
            self.assertEqual([item['action'] for item in actions[3:]], [REFRESH, SELECT, CONFIRM])
            refresh = actions[3]
            self.assertEqual(refresh['investment_refresh_origin']['candidates_before'][1:],
                             refresh['investment_refresh_receipt']['candidates_after'][1:])
            self.assertEqual(ledger_status(actions), 'clear')

    def test_ambiguous_quote_fragments_cannot_send_or_verify_refresh(self):
        board, session = fixture()
        first = investment_page(UNSUPPORTED, (2, 1, 1))
        deducted = investment_page(UNSUPPORTED, (1, 1, 1))
        for variant, tokens in quote_variants():
            for stage in ('before', 'feedback'):
                with self.subTest(variant=variant, stage=stage), tempfile.TemporaryDirectory() as folder:
                    before = replace(first, tokens=list(first.tokens))
                    after = replace(deducted, tokens=list(deducted.tokens))
                    (before if stage == 'before' else after).tokens.extend(tokens)
                    second = replace(after, tokens=list(after.tokens))
                    third = replace(after, tokens=list(after.tokens))
                    current = context(folder, board, session, [before, after, second, third])
                    if stage == 'before':
                        submit = current.currency_standard_input.side_effect

                        def stop_on_input(scene, choice):
                            submit(scene, choice)
                            raise Stopped('unexpected refresh input')

                        current.currency_standard_input.side_effect = stop_on_input
                    else:
                        def stop_on_receipt():
                            if current.currency_standard_session.data['actions'][-1].get('investment_refresh_receipt'):
                                raise Stopped('unexpected refresh receipt')

                        current.checkpoint = stop_on_receipt
                    clock = SimpleNamespace(monotonic=Mock(side_effect=count(0, 20)))
                    with (patch('autohsr.currency_wars_replay.save_sample'),
                          patch('autohsr.currency_wars_standard_flow.time', clock)):
                        try:
                            run_standard(current)
                        except Stopped as error:
                            self.assertTrue(str(error).startswith('unexpected refresh'))
                    actions = StandardSession(current.currency_standard_session.path).data['actions']
                    self.assertEqual(current.window.click.call_count, int(stage == 'feedback'))
                    self.assertEqual(len(actions), 3+int(stage == 'feedback'))
                    if stage == 'feedback':
                        self.assertEqual(actions[-1]['status'], 'unknown')
                        self.assertNotIn('investment_refresh_receipt', actions[-1])

    def test_split_gift_amount_belongs_only_to_its_complete_sentence(self):
        _, session = fixture()
        cards = (('金币赠送', '获得10金币。'), *UNSUPPORTED[1:])
        frame = investment_page(cards, (2, 1, 1))
        frame.tokens = [token for token in frame.tokens if not token.within((.12, .48, .36, .74))]
        frame.tokens.extend((Token('获得', .99, (.14, .489, .18, .513)),
                             Token('１０', .99, (.185, .489, .209, .513)),
                             Token('金币。', .99, (.214, .489, .27, .513))))
        self.assertEqual(next_action(frame, session=session).intent, REFRESH)
        for fragment in ('１０金币', '１０', '１０金', '扣10', '获得10金币.10'):
            with self.subTest(fragment=fragment):
                interrupted = replace(frame, tokens=[*frame.tokens, Token(fragment, .99, (.14, .520, .23, .544))])
                with self.assertRaises(AutomationError):
                    next_action(interrupted, session=session)
        doubled = replace(frame, tokens=[*frame.tokens, Token('１０', .99, (.210, .489, .225, .513))])
        with self.assertRaises(AutomationError):
            next_action(doubled, session=session)

    def test_technical_cap_carries_across_the_whole_plane(self):
        board, session = fixture()
        remaining = [99, 99, 99]
        base = investment_page(UNSUPPORTED, remaining)
        frames = [base]
        for _ in range(MAX_REFRESHES):
            slot = remaining.index(max(remaining))
            remaining[slot] -= 1
            tokens = count_tokens(base, remaining)
            frames.extend((replace(base, tokens=tokens), replace(base, tokens=tokens)))
        with tempfile.TemporaryDirectory() as folder:
            current = context(folder, board, session, frames)
            with patch('autohsr.currency_wars_replay.save_sample'):
                self.assertEqual(run_standard(current).status, 'partial')
            saved = StandardSession(current.currency_standard_session.path).data
            self.assertEqual(current.window.click.call_count, 30)
            self.assertEqual([action['action'] for action in saved['actions'][3:]], [REFRESH]*30)
            self.assertTrue(all(valid_receipt(action, saved['actions']) for action in saved['actions'][3:]))
            self.assertEqual(ledger_status(saved['actions']), 'clear')

    def test_inconsistent_feedback_keeps_one_intent_and_cannot_replay(self):
        supported = (SUPPORTED, *UNSUPPORTED[1:])
        other = (SUPPORTED, ('另一套组', '获得一件其他遗器。'), UNSUPPORTED[2])
        alternative = (('另一个徽记', '获得一个徽记。'), *UNSUPPORTED[1:])
        for failure in ('other_column', 'other_card', 'extra_deduction', 'stale_capture', 'unstable_table',
                        'wrong_page', 'foreign_account', 'epoch_change', 'missing_result_card', *OVERLAYS, *PRICE_OVERLAYS):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as folder:
                board, session = fixture()
                before = investment_page(UNSUPPORTED, (2, 1, 1))
                after = investment_page(supported, (1, 1, 1))
                if failure == 'other_column':
                    after.tokens = count_tokens(after, (2, 0, 1))
                elif failure == 'other_card':
                    after = investment_page(other, (1, 1, 1))
                elif failure == 'extra_deduction':
                    after.tokens = count_tokens(after, (0, 1, 1))
                elif failure == 'wrong_page':
                    after = board
                elif failure == 'missing_result_card':
                    after.tokens = [t for t in after.tokens if not t.within((.12, .43, .35, .84))]
                elif failure in OVERLAYS:
                    # The overlay covers the rerolled card, which is allowed to change.
                    after.tokens.append(Token(OVERLAYS[failure], .99, (.18, .66, .24, .70)))
                elif failure in PRICE_OVERLAYS:
                    place_price(after, PRICE_OVERLAYS[failure], .18)
                middle = investment_page(alternative, (1, 1, 1)) if failure == 'unstable_table' else deepcopy(after)
                current = context(folder, board, session, [before, after, middle, deepcopy(after)])
                snapshot = current.snapshot
                captures, captured_at = 0, None

                def capture():
                    nonlocal captures, captured_at
                    scene = snapshot()
                    captures += 1
                    if captures > 1 and failure == 'stale_capture':
                        if captured_at is None:
                            captured_at = scene.captured_at
                        scene.captured_at = captured_at
                    if captures == 2 and failure == 'foreign_account':
                        scene.tokens = [replace(t, text='UID:200000000') if normalize(t.text).startswith('uid') else t
                                        for t in scene.tokens]
                    if captures == 3 and failure == 'epoch_change':
                        current.runner.input_epoch += 1
                    return scene

                current.snapshot = capture
                clock = SimpleNamespace(monotonic=Mock(side_effect=count(0, 20)))
                with (patch('autohsr.currency_wars_replay.save_sample'),
                      patch('autohsr.currency_wars_standard_flow.time', clock)):
                    if failure == 'foreign_account':
                        with self.assertRaisesRegex(AutomationError, '账号来源不一致'):
                            run_standard(current)
                    elif failure == 'epoch_change':
                        with self.assertRaises(InputInterrupted):
                            run_standard(current)
                    else:
                        self.assertEqual(run_standard(current).status, 'partial')
                path = current.currency_standard_session.path
                saved = StandardSession(path).data
                latest = saved['actions'][-1]
                self.assertEqual(latest['action'], REFRESH)
                self.assertEqual(latest['status'], 'pending' if failure in ('foreign_account', 'epoch_change') else 'unknown')
                self.assertNotIn('investment_refresh_receipt', latest)
                self.assertEqual(saved['investment']['status'], 'awaiting')
                self.assertEqual(current.window.click.call_count, 1)
                journal = path.read_bytes()
                current.snapshot = Mock()
                with self.assertRaisesRegex(AutomationError, '上次标准动作尚未核实'):
                    run_standard(current)
                current.snapshot.assert_not_called()
                self.assertEqual(current.window.click.call_count, 1)
                self.assertEqual(path.read_bytes(), journal)

    def test_context_rechecks_persisted_refresh_origin_and_later_bindings(self):
        for blocked, sent in ((REFRESH, 0), (SELECT, 1), (CONFIRM, 2)):
            with self.subTest(blocked=blocked), tempfile.TemporaryDirectory() as folder:
                board, session = fixture()
                before = investment_page(UNSUPPORTED, (1, 1, 1))
                supported = (SUPPORTED, *UNSUPPORTED[1:])
                after = investment_page(supported, (0, 1, 1))
                marked = investment_page(supported, (0, 1, 1), selected=0)
                current = context(folder, board, session, [before, after, deepcopy(after), marked, deepcopy(marked)])
                dispatch = current.currency_standard_input.side_effect

                def submit(scene, choice):
                    if choice.intent == blocked:
                        disk = StandardSession(current.currency_standard_session.path)
                        last = disk.data['actions'][-1]
                        if blocked == REFRESH:
                            last['investment_refresh_origin']['control'][0] += .005
                        elif blocked == SELECT:
                            disk.data['actions'][-2]['investment_refresh_receipt']['card_changed'] = False
                        else:
                            last.pop(BINDING)
                        disk.persist()
                    dispatch(scene, choice)

                current.currency_standard_input.side_effect = submit
                with (patch('autohsr.currency_wars_replay.save_sample'),
                      self.assertRaisesRegex(AutomationError, '与落盘记录一致')):
                    run_standard(current)
                last = StandardSession(current.currency_standard_session.path).data['actions'][-1]
                self.assertEqual((last['action'], last['status']), (blocked, 'pending'))
                self.assertEqual(current.window.click.call_count, sent)

    def test_refresh_write_failure_before_input_or_receipt_leaves_original_pending(self):
        persist = StandardSession.persist
        for stage in ('intent', 'receipt'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as folder:
                board, session = fixture()
                before = investment_page(UNSUPPORTED, (1, 1, 1))
                after = investment_page((SUPPORTED, *UNSUPPORTED[1:]), (0, 1, 1))
                current = context(folder, board, session, [before, after, deepcopy(after)])

                def fail_write(store):
                    last = store.data['actions'][-1]
                    field = 'investment_refresh_origin' if stage == 'intent' else 'investment_refresh_receipt'
                    if last['action'] == REFRESH and field in last:
                        raise OSError('synthetic write interruption')
                    return persist(store)

                with (patch('autohsr.currency_wars_replay.save_sample'), patch.object(StandardSession, 'persist', fail_write),
                      self.assertRaisesRegex(OSError, 'synthetic write interruption')):
                    run_standard(current)
                last = StandardSession(current.currency_standard_session.path).data['actions'][-1]
                self.assertEqual((last['action'], last['status']), (REFRESH, 'pending'))
                self.assertNotIn('investment_refresh_receipt', last)
                self.assertEqual(current.window.click.call_count, int(stage == 'receipt'))
                with self.assertRaisesRegex(AutomationError, '上次标准动作尚未核实'):
                    run_standard(current)
                self.assertEqual(current.window.click.call_count, int(stage == 'receipt'))

    def test_resume_uses_verified_refresh_once_and_requires_current_exact_table(self):
        board, session = fixture()
        session['client']['executable'] = 'fake-game-executable'
        before = investment_page(UNSUPPORTED, (1, 1, 1))
        supported = (SUPPORTED, *UNSUPPORTED[1:])
        after = investment_page(supported, (0, 1, 1))
        marked = investment_page(supported, (0, 1, 1), selected=0)
        with tempfile.TemporaryDirectory() as first:
            original = context(first, board, session, [before, after, deepcopy(after)])

            def pause_after_refresh():
                last = original.currency_standard_session.data['actions'][-1]
                if last['action'] == REFRESH and last['status'] == 'verified':
                    raise Stopped('refresh saved')

            original.checkpoint = pause_after_refresh
            with patch('autohsr.currency_wars_replay.save_sample'), self.assertRaisesRegex(Stopped, 'refresh saved'):
                run_standard(original)
            path = original.currency_standard_session.path
            saved, journal = StandardSession(path).data, path.read_bytes()
            original.window.click.assert_called_once()
        for changed in (False, True):
            with self.subTest(changed=changed), tempfile.TemporaryDirectory() as second:
                frame = investment_page(supported, (1, 1, 1)) if changed else deepcopy(after)
                resumed = context(second, board, session, [frame, marked, deepcopy(marked), board, deepcopy(board)])
                path = Path(second)/'currency-standard-session.json'
                path.write_bytes(journal)
                resumed.checkpoint = lambda: stop_after_confirmation(resumed)
                with (patch('autohsr.currency_wars_replay.save_sample'),
                      patch('autohsr.currency_wars_identity.installed_client', return_value=dict(saved['client']))):
                    if changed:
                        self.assertEqual(run_standard(resumed).status, 'partial')
                    else:
                        with self.assertRaisesRegex(Stopped, 'investment applied'):
                            run_standard(resumed)
                actions = StandardSession(path).data['actions']
                source = deepcopy(saved['actions'])
                if not changed:
                    source[2]['investment_verified'] = True
                self.assertEqual(actions[:4], source)
                self.assertEqual([action['action'] for action in actions[4:]], [] if changed else [SELECT, CONFIRM])
                self.assertEqual(resumed.window.click.call_count, 0 if changed else 2)
