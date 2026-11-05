"""Investment box opening scope with existing redacted reward fields."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard, transition_ready
from autohsr.currency_wars_standard_investment import bind_reward, box_opening_page
from autohsr.currency_wars_standard_rewards import bind_source, enter as reward_enter
from autohsr.models import AutomationError, EmptyCapture, InputInterrupted
from autohsr.tests import test_currency_wars_standard_exchange as exchange
from autohsr.tests import test_currency_wars_standard_investment as investment
from autohsr.tests import test_currency_wars_standard_rewards as rewards


def pending_box(tier=2):
    effect = investment.DEFENSE if tier == 2 else investment.DEFENSE.replace('进阶', '简易')
    board, page, session = investment.fixture([('保守派', effect)])
    board = investment.gift_board(board)
    investment.select_and_confirm(board, page, session)
    opening = next_action(board, session=session)
    investment.append(session, opening, 'pending')
    bind_source(session, opening, board)
    bind_reward(session, opening)
    return board, opening, session


def observed_box(board, opening, session):
    page = rewards.modal('advanced_equipment_selection', board, gold=30, destination='2-1')
    session['actions'][-1]['status'] = 'verified'
    reward_enter(session, opening, page)
    return page


class InvestmentBoxSourceTests(unittest.TestCase):
    def test_pending_gift_preserves_original_box_kind_and_source(self):
        for tier, page in ((1, 'equipment_selection'), (2, 'advanced_equipment_selection')):
            with self.subTest(tier=tier):
                _, opening, session = pending_box(tier)
                original = deepcopy(session)
                self.assertEqual(box_opening_page(session, opening), page)
                self.assertEqual(session, original)

    def test_ordinary_box_has_no_investment_kind(self):
        board, _, session = rewards.box()
        opening = next_action(board, session={**session, 'reward': {}, 'actions': []})
        session.pop('reward')
        session['actions'][-1]['status'] = 'pending'
        self.assertIsNone(box_opening_page(session, opening))

    def test_changed_parent_slot_scope_or_pending_action_cannot_supply_feedback(self):
        _, opening, initial = pending_box()
        for change in ('parent', 'orphan', 'confirmation', 'slot', 'basis', 'run', 'epoch', 'completed', 'intent'):
            with self.subTest(change=change):
                session = deepcopy(initial)
                action = session['actions'][-1]
                choice = opening
                if change == 'parent':
                    action.pop('investment_parent_action_id')
                elif change == 'orphan':
                    session.pop('investment')
                elif change == 'confirmation':
                    session['actions'][session['investment']['claim_action_id']]['status'] = 'unknown'
                elif change == 'slot':
                    # Update the current payload too. It must still match the
                    # original investment slot, rather than its mutable copy.
                    node, slot, _ = opening.payload
                    action['target'] = [node, slot, 'f' * 64]
                    action['reward_basis']['cells']['bench:' + str(slot)] = ['reward', 'f' * 64]
                    session['investment']['reward_slots'] = {str(slot): 'f' * 64}
                    choice = replace(opening, payload=tuple(action['target']))
                elif change == 'basis':
                    action['reward_basis']['cells']['bench:' + str(opening.payload[1])] = ['empty', opening.payload[2]]
                elif change == 'run':
                    session['account_verified_run'] = 'next-fake-run'
                elif change == 'epoch':
                    session['account_verified_epoch'] += 1
                elif change == 'completed':
                    session['investment']['completed_slots'].append(opening.payload[1])
                else:
                    action['action'] = 'collect_standard_loot'
                with self.assertRaises(AutomationError):
                    box_opening_page(session, choice)

    def test_choose_rechecks_the_same_verified_opening_and_box_node(self):
        board, opening, initial = pending_box()
        correct = observed_box(board, opening, initial)
        self.assertEqual(next_action(correct, session=initial).intent, 'choose_standard_reward')
        for change in ('wrong_kind', 'wrong_node', 'wrong_recorded_kind', 'wrong_recorded_slot', 'unknown_open', 'foreign_tail'):
            with self.subTest(change=change):
                session = deepcopy(initial)
                page = correct
                if change == 'wrong_kind':
                    page = rewards.modal('equipment_selection', board, gold=30, destination='2-1')
                elif change == 'wrong_node':
                    page = rewards.modal('advanced_equipment_selection', board, gold=30, destination='2-2')
                elif change == 'wrong_recorded_kind':
                    session['reward']['page'] = 'equipment_selection'
                elif change == 'wrong_recorded_slot':
                    session['reward']['box_slot'] = 9
                elif change == 'unknown_open':
                    session['actions'][-1]['status'] = 'unknown'
                else:
                    session['actions'].append(dict(id=len(session['actions']), action='inspect_standard_unit', status='verified'))
                with self.assertRaises(AutomationError):
                    next_action(page, session=session)

    def test_verified_opening_retains_its_source_on_current_scope_resume(self):
        board, opening, session = pending_box()
        page = observed_box(board, opening, session)
        source = deepcopy(session['actions'][-1])
        session.update(account_verified_run='next-fake-run', account_verified_epoch=1)
        session['collection'].update(run_dir='next-fake-run', input_epoch=1, complete=False)
        session['client'].update(verified_run='next-fake-run', input_epoch=1)
        self.assertEqual(next_action(page, session=session).intent, 'choose_standard_reward')
        self.assertEqual(session['actions'][-1], source)


class InvestmentBoxFlowFeedbackTests(unittest.TestCase):
    def test_wrong_same_node_reward_is_not_feedback_for_the_advanced_gift(self):
        board, opening, session = pending_box()
        wrong = rewards.modal('equipment_selection', board, gold=30, destination='2-1')
        right = rewards.modal('advanced_equipment_selection', board, gold=30, destination='2-1')
        self.assertFalse(transition_ready(opening, wrong, before=board, session=session))
        self.assertTrue(transition_ready(opening, right, before=board, session=session))

    def test_same_kind_from_wrong_node_and_other_reward_kinds_keep_waiting(self):
        board, opening, session = pending_box(tier=1)
        for kind, node in (('advanced_equipment_selection', '2-1'), ('expert_selection', '2-1'),
                           ('equipment_selection', '2-2')):
            with self.subTest(kind=kind, node=node):
                page = rewards.modal(kind, board, gold=30, destination=node)
                self.assertFalse(transition_ready(opening, page, before=board, session=session))
        page = rewards.modal('equipment_selection', board, gold=30, destination='2-1')
        self.assertTrue(transition_ready(opening, page, before=board, session=session))

    def test_real_context_cannot_clear_opening_with_repeated_or_interrupted_feedback(self):
        for interruption in ('wrong_page', 'same_capture', 'empty_capture', 'replayed_after_wrong', 'epoch_change'):
            with self.subTest(interruption=interruption), tempfile.TemporaryDirectory() as folder:
                board, _, session = pending_box()
                session['actions'].pop()  # Let the real flow submit the opening once.
                original_count = len(session['actions'])
                right = rewards.modal('advanced_equipment_selection', board, gold=30, destination='2-1')
                wrong = rewards.modal('equipment_selection', board, gold=30, destination='2-1')
                uid = next(token for token in board.tokens if token.text.startswith('UID:'))
                right.tokens.append(uid)
                wrong.tokens.append(uid)
                context = exchange.StandardExchangeTests().context(folder, board, session, [board])

                # Fresh capture stamps remain in the actual Context clock's past.
                # Only the flow's wait clock is accelerated in this fake window.
                base = time.monotonic() - 1
                feedback = {
                    'wrong_page': [(right, 1), (wrong, 2), (right, 3)],
                    'same_capture': [(right, 1), (right, 1)],
                    'empty_capture': [(right, 1), (None, 2), (right, 1), (right, 3)],
                    'replayed_after_wrong': [(right, 1), (wrong, 3), (right, 2), (right, 4)],
                    'epoch_change': [(right, 1), (right, 2)],
                }
                source = iter([(board, 0), *feedback[interruption]])

                def snapshot():
                    frame, stamp = next(source, (None, 0))
                    if frame is None:
                        raise EmptyCapture('synthetic capture gap')
                    if interruption == 'epoch_change' and stamp == 2:
                        context.runner.input_epoch += 1
                        context.scene_epoch = context.runner.input_epoch
                    current = replace(frame, captured_at=base + stamp / 10)
                    context.last_scene = current
                    return current

                clock = SimpleNamespace(now=0.)
                clock.monotonic = lambda: clock.now
                context.snapshot = snapshot
                context.sleep = lambda seconds: setattr(clock, 'now', clock.now + seconds)
                with patch('autohsr.currency_wars_standard_flow.time', clock), \
                        patch('autohsr.currency_wars_replay.save_sample'):
                    if interruption == 'epoch_change':
                        with self.assertRaises(InputInterrupted):
                            run_standard(context)
                    else:
                        self.assertEqual(run_standard(context).status, 'partial')

                path = context.currency_standard_session.path
                saved = StandardSession(path).data
                self.assertEqual(len(saved['actions']), original_count + 1)
                opening = saved['actions'][-1]
                expected = 'pending' if interruption == 'epoch_change' else 'unknown'
                self.assertEqual((opening['action'], opening['status']), ('open_standard_bench_reward', expected))
                self.assertEqual(saved['investment']['status'], 'reward_verifying')
                self.assertFalse(saved['actions'][opening['investment_parent_action_id']]['investment_verified'])
                self.assertNotIn('reward', saved)
                context.window.click_held.assert_called_once()
                context.window.click.assert_not_called()

                original = path.read_bytes()
                context.snapshot = Mock()
                with self.assertRaises(AutomationError):
                    run_standard(context)
                context.snapshot.assert_not_called()
                context.window.click_held.assert_called_once()
                self.assertEqual(path.read_bytes(), original)

    def test_real_context_reads_the_persisted_box_binding_before_open_or_choose(self):
        for defect in ('opening_parent', 'opening_basis', 'choose_parent_missing', 'choose_parent_changed'):
            with self.subTest(defect=defect), tempfile.TemporaryDirectory() as folder:
                board, _, session = pending_box()
                session['actions'].pop()
                modal = rewards.modal('advanced_equipment_selection', board, gold=30, destination='2-1')
                context = exchange.StandardExchangeTests().context(folder, board, session, [board, modal])
                store = StandardSession(Path(folder) / 'currency-standard-session.json')
                context.currency_standard_session = store
                scene = context.snapshot()
                opening = next_action(scene, session=store.data)
                action = store.pending(opening.intent, 0, 'before.png', opening.expected)
                action['target'] = list(opening.payload)
                bind_source(store.data, opening, scene)
                bind_reward(store.data, opening)
                self.assertEqual(box_opening_page(store.data, opening), 'advanced_equipment_selection')
                choice = opening
                if defect.startswith('choose_'):
                    action.update(status='verified', after='box.png')
                    scene = context.snapshot()
                    reward_enter(store.data, opening, scene)
                    choice = next_action(scene, session=store.data)
                    claim = store.pending(choice.intent, 0, 'box.png', choice.expected)
                    claim['target'] = list(choice.payload)
                store.persist()
                self.assertEqual(next_action(scene, session=store.data), choice)

                # Keep the actual in-memory proposal, target and generic disk
                # pending fields valid. Only the durable opening source changes.
                disk = deepcopy(store.data)
                original_opening = disk['actions'][action['id']]
                if defect == 'opening_basis':
                    original_opening.pop('reward_basis')
                elif defect == 'choose_parent_changed':
                    original_opening['investment_parent_action_id'] -= 1
                else:
                    original_opening.pop('investment_parent_action_id')
                store.path.write_text(json.dumps(disk, ensure_ascii=False), encoding='utf-8')
                original = store.path.read_bytes()

                with self.assertRaises(AutomationError):
                    context.currency_standard_input(scene, choice)
                context.window.click_held.assert_not_called()
                context.window.click.assert_not_called()
                self.assertEqual(store.path.read_bytes(), original)
                saved = StandardSession(store.path).data
                self.assertEqual(saved['investment']['status'], 'reward_verifying')
                confirmation = saved['actions'][saved['investment']['claim_action_id']]
                self.assertEqual(confirmation['status'], 'verified')
                self.assertFalse(confirmation['investment_verified'])
