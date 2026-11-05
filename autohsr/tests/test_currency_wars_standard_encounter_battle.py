"""Encounter entry receipts use the standard flow and native fake Win32."""
from copy import deepcopy
from dataclasses import replace
import unittest
from unittest.mock import patch

import numpy as np

from autohsr.currency_wars_deployment import _crop
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_node import start_target
from autohsr.currency_wars_session import require_session_access
from autohsr.currency_wars_standard_encounter import CONFIRM, SELECT
from autohsr.currency_wars_standard_encounter_battle import BINDING, CLOSE, START, proposal
from autohsr.models import AutomationError, EmptyCapture, Stopped, Token
from autohsr.tests import test_currency_wars_standard_encounter as fixture
from autohsr.tests.test_currency_wars_deployment import deployment_frame
from autohsr.tests.test_currency_wars_standard_node import current
from autohsr.tests.test_currency_wars_standard_trading import hud


NODE, SOURCE = '1-7', '1-6'
CHOOSE = [fixture.CONTINUE, SELECT, CONFIRM]


def ready():
    scene = fixture.preparation(NODE)
    scene.image = deployment_frame(6).image
    random = np.random.default_rng(87)
    for positions, top, bottom in (((990, 1180, 1370, 1560), .33, .41), ((805, 995), .58, .66)):
        for x in positions:
            center = x/2560
            portrait = _crop(scene.image, (center-.02, top, center+.02, bottom))
            portrait[:] = random.integers(0, 256, portrait.shape, dtype=np.uint8)
    return scene


def result(label='遭遇'):
    scene = current('node_result', NODE)
    scene.tokens = [replace(token, text=NODE+label) if token.text == NODE+'战斗' else token
                    for token in scene.tokens]
    return scene


def battle_with_banner(text):
    scene = current('battle', NODE)
    scene.tokens.append(Token(text, .95, (.41, .39, .59, .48)))
    return scene


class EncounterBattleTests(unittest.TestCase):
    def setUp(self):
        self.replay = fixture.StandardEncounterTests()
        self.addCleanup(self.replay.doCleanups)

    def run_battle(self, feedback=(), *, shop=False, board=None, failure=None, stale=()):
        frames = [current('node_result', SOURCE), fixture.modal(), fixture.modal(),
                  fixture.modal(selected=1), fixture.modal(selected=1)]
        board = ready() if board is None else board
        if shop:
            frames.extend(hud(fixture.preparation(NODE, shop=True), level=6) for _ in range(2))
        frames.extend((board, board))
        frames.extend(feedback)
        return self.replay.run_path(SOURCE, frames, battle_node=NODE, stop_at_arrival=False,
                                    native_failure=failure, stale=stale)

    def assert_intents(self, outcome, expected):
        self.assertEqual([intent for intent, _ in outcome.calls], expected, str(outcome.error))

    def test_ready_missing_type_with_original_receipt_starts_once_and_observes_same_node(self):
        stages = [battle_with_banner('战斗阶段'), battle_with_banner('遭遇强敌来袭'),
                  battle_with_banner('战斗开始'), EmptyCapture('blank'),
                  current('battle', NODE), current('battle', NODE), result()]
        outcome = self.run_battle(stages, failure='battle_holds')
        self.assert_intents(outcome, [*CHOOSE, START])
        self.assertEqual(outcome.injected, ['battle_holds'])
        self.assertIsInstance(outcome.error, Stopped)
        action = outcome.data['actions'][-1]
        self.assertEqual(action['feedback'], {'page_kind': 'battle', 'node': NODE})
        self.assertEqual(action['target'][0], NODE)
        self.assertEqual(action[BINDING]['arrival_action_id'], 3)
        self.assertEqual(len(action['encounter_frames']), 2)
        attempt = outcome.data['node_attempt']
        self.assertTrue(attempt['battle_observed'])
        self.assertTrue(attempt['node_verified'])
        self.assertEqual(attempt['result_kind'], 'node_result')
        self.assertFalse(outcome.data['completion_verified'])

    def test_automatic_shop_requires_its_own_same_node_free_close_receipt(self):
        outcome = self.run_battle([current('battle', NODE), current('battle', NODE), result()], shop=True)
        self.assert_intents(outcome, [*CHOOSE, CLOSE, START])
        self.assertIsInstance(outcome.error, Stopped)
        close = outcome.data['actions'][-2]
        self.assertEqual(close[BINDING]['arrival_action_id'], 3)
        self.assertEqual(close['feedback']['node'], NODE)
        self.assertEqual(len(close['encounter_frames']), 2)
        self.assertTrue(outcome.data['node_attempt']['node_verified'])

        seed = self.replay.complete(SOURCE, NODE, shop=True).data
        self.assertRaises(AutomationError, proposal, ready(), seed, read_match(ready()), .65)
        seed['actions'].append(dict(id=4, action=CLOSE, status='verified', input_epoch=0,
                                    expected='standard_arrival_shop_closed', target=[NODE, 9, 8, SOURCE, 0]))
        self.assertRaises(AutomationError, proposal, ready(), seed, read_match(ready()), .65)

    def test_missing_or_stale_receipt_does_not_authorize_by_node_name(self):
        board = ready()
        state = read_match(board)
        old = self.replay.complete(SOURCE, NODE).data
        without = dict(old, node_history=[])
        self.assertIsNone(proposal(board, without, state, .65))
        with self.assertRaises(AutomationError):
            start_target(board)
        with (patch('autohsr.currency_wars_node.loot_centers', return_value=((.7, .3),)),
              self.assertRaises(AutomationError)):
            proposal(board, old, state, .65)
        for field in ('epoch', 'run', 'client', 'other_account'):
            with self.subTest(field=field):
                changed = deepcopy(old)
                if field == 'epoch':
                    changed['account_verified_epoch'] = changed['client']['input_epoch'] = 1
                elif field == 'run':
                    changed['account_verified_run'] = changed['client']['verified_run'] = 'other invocation'
                elif field == 'client':
                    changed['client']['sha256'] = 'f'*64
                else:
                    changed['account_key'] = 'a'*64
                with self.assertRaises(AutomationError):
                    proposal(board, changed, state, .65)

    def test_current_roster_button_and_type_still_gate_the_start(self):
        no_front = ready()
        no_front.image[:] = 0
        empty_slot = hud(ready(), deployment=(5, 6))
        duplicate = ready()
        duplicate.tokens.append(Token('出战', .99, (.92, .69, .95, .72)))
        conflicting_uid = ready()
        conflicting_uid.tokens.append(replace(fixture.UID, text='UID:200000000', score=.74))
        other_type = fixture.preparation(NODE, known_type=True)
        for board in (no_front, empty_slot, duplicate, conflicting_uid, other_type):
            with self.subTest(case=board.tokens):
                outcome = self.run_battle(board=board)
                self.assert_intents(outcome, CHOOSE)
                self.assertEqual(outcome.data['actions'][-1]['action'], CONFIRM)

    def test_alternating_banner_blank_and_stale_battle_cannot_settle_entry(self):
        feedback = [battle_with_banner('战斗开始'), current('battle', NODE),
                    EmptyCapture('gap'), current('battle', NODE), current('battle', NODE)]
        outcome = self.run_battle(feedback, stale=(12,))
        self.assert_intents(outcome, [*CHOOSE, START])
        self.assertEqual(outcome.data['actions'][-1]['status'], 'unknown')
        self.assertFalse(outcome.data['node_attempt']['node_verified'])
        with self.assertRaises(AutomationError):
            require_session_access(outcome.data, True)

    def test_conflicting_node_and_result_type_stay_pending(self):
        for conflicting in (current('battle', '1-8'), result('战斗')):
            with self.subTest(tokens=conflicting.tokens):
                outcome = self.run_battle([conflicting])
                self.assert_intents(outcome, [*CHOOSE, START])
                self.assertIsInstance(outcome.error, AutomationError)
                self.assertEqual(outcome.data['actions'][-1]['status'], 'pending')
                self.assertFalse(outcome.data['node_attempt']['node_verified'])

    def test_two_complete_results_can_verify_entry_without_inventing_battle(self):
        outcome = self.run_battle([result(), result()])
        self.assert_intents(outcome, [*CHOOSE, START])
        self.assertIsInstance(outcome.error, Stopped)
        self.assertEqual(outcome.data['actions'][-1]['feedback']['page_kind'], 'node_result')
        self.assertTrue(outcome.data['node_attempt']['node_verified'])
        self.assertFalse(outcome.data['node_attempt']['battle_observed'])

    def test_native_guard_rejects_either_arrival_image_version_or_epoch_change(self):
        for failure in ('arrival_first', 'arrival_last', 'version', 'start_epoch', 'start_focus', 'start_f10'):
            with self.subTest(failure=failure):
                outcome = self.run_battle(failure=failure)
                self.assert_intents(outcome, CHOOSE)
                self.assertEqual(outcome.injected, [failure])
                self.assertEqual(outcome.data['actions'][-1]['status'], 'pending')
                self.assertEqual(outcome.data['node_attempt']['status'], 'start_pending')

    def test_partial_native_batch_remains_pending_and_cannot_be_retried(self):
        outcome = self.run_battle(failure='partial_start')
        self.assert_intents(outcome, [*CHOOSE, START])
        self.assertEqual(outcome.injected, ['partial_start'])
        self.assertEqual(outcome.data['actions'][-1]['status'], 'pending')
        with self.assertRaises(AutomationError):
            require_session_access(outcome.data, True)

    def test_failed_entry_receipt_write_keeps_the_original_pending_source(self):
        outcome = self.run_battle([current('battle', NODE), current('battle', NODE)], failure='battle_publish')
        self.assert_intents(outcome, [*CHOOSE, START])
        self.assertEqual(outcome.injected, ['battle_publish'])
        self.assertIsInstance(outcome.error, PermissionError)
        durable, reported = outcome.data['actions'][-1], outcome.report['actions'][-1]
        self.assertEqual(durable, reported)
        self.assertEqual(durable['status'], 'pending')
        self.assertNotIn('after', durable['encounter_origin'])
