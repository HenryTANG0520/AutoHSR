"""Standard loot capacity with an existing, verified bench sale candidate."""
from copy import deepcopy
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop, bench_face
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_node import loot_centers
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_collection import retained
from autohsr.currency_wars_standard_deployment import standard_deployment
from autohsr.currency_wars_standard_flow import next_action
from autohsr.currency_wars_standard_ledger import ledger_status, valid_receipt
from autohsr.currency_wars_standard_sale import proposal
from autohsr.models import AutomationError, Stopped
from autohsr.tests.test_currency_wars_loot_capacity import Harness, clone, fixture as loot_fixture
from autohsr.tests.test_currency_wars_standard_sale import character, sold
from autohsr.tests.test_currency_wars_standard_trading import hud


def fixture():
    board, data = loot_fixture(deployed=3)
    data['shop_observed_nodes'] = [read_match(board).node]
    records = data['collection']['units']
    for record in records.values():
        unit = record['unit']
        if unit['zone'] == 'bench':
            unit.update(star=1, tier=1, eligible_zones=('front',), traits=(), equipment=())
        else:
            unit.update(star=3, tier=4, eligible_zones=(unit['zone'],), traits=(), equipment=())
    records['front:1']['unit']['name'] = '大丽花'
    records['bench:1']['unit']['traits'] = ('测试',)
    records['bench:9']['unit'].update(name='大丽花', traits=('测试',))
    return board, data


class LootSaleTests(unittest.TestCase):
    def test_verified_full_field_reuses_the_existing_bench_sale_proposal(self):
        board, data = fixture()
        self.assertIsNone(standard_deployment(board, data))
        sale = proposal(board, data)
        self.assertEqual(sale.intent, 'inspect_standard_sale_unit')
        self.assertEqual(sale.payload[4], 9)
        self.assertEqual(sale.details[2], ('max_star_duplicate',))
        self.assertEqual(next_action(board, session=data), sale)

    def test_unobserved_shop_or_missing_candidate_does_not_authorize_sale(self):
        for case in ('unobserved_shop', 'no_candidate', 'unknown_gold', 'field_sale'):
            with self.subTest(case=case):
                board, data = fixture()
                if case == 'unobserved_shop':
                    data['shop_observed_nodes'] = []
                elif case == 'no_candidate':
                    data['collection']['units']['bench:9']['unit']['name'] = '另一位角色'
                elif case == 'unknown_gold':
                    board.tokens = [token for token in board.tokens if not token.within((.851,.829,.87,.868))]
                elif case == 'field_sale':
                    data['strategy'] = 'seele'
                    data['collection']['units']['front:1']['unit']['name'] = '希儿'
                    self.assertEqual(proposal(board, data).intent, 'inspect_standard_field_sale_unit')
                with self.assertRaises(AutomationError):
                    next_action(board, session=data)


class SaleHarness(Harness):
    def __init__(self, folder, *, feedback='normal'):
        super().__init__(folder)
        self.board, data = fixture()
        self.before = self.board
        self.feedback = feedback
        self.inputs = []
        self.recollecting = False
        self.recollected = None
        self.original_units = deepcopy(data['collection']['units'])
        self.tampered_bytes = None
        store = StandardSession(self.path)
        store.data['collection']['units'] = data['collection']['units']
        store.data['shop_observed_nodes'] = data['shop_observed_nodes']
        store.persist()

    def corrupt_before_input(self, intent, mutate):
        dispatch = self.c.currency_standard_input

        def invoke(scene, choice):
            if choice.intent == intent:
                saved = json.loads(self.path.read_text(encoding='utf-8'))
                mutate(saved['actions'])
                self.tampered_bytes = json.dumps(saved, ensure_ascii=False).encode('utf-8')
                self.path.write_bytes(self.tampered_bytes)
            return dispatch(scene, choice)

        self.c.currency_standard_input = invoke

    def checkpoint(self):
        super().checkpoint()
        store = getattr(self.c, 'currency_standard_session', None)
        if self.feedback != 'recollect_portrait' or self.recollecting or store is None:
            return
        actions = store.data['actions']
        if actions and actions[-1]['action'] == 'sell_standard_owned' and actions[-1]['status'] == 'verified':
            self.recollecting = True
            self.sold_board = self.board
            store.data['collection']['units'].pop('bench:1')
            store.persist()

    def click(self, *args):
        store = self.c.currency_standard_session
        action = store.data['actions'][-1]
        self.inputs.append(action['action'])
        if action['action'] == 'inspect_standard_sale_unit':
            self.board = character(self.before, store.data, slot=9, refund=1)
            self.stage = 'inspected'
        elif action['action'] == 'sell_standard_owned':
            self.board = sold(self.before, SimpleNamespace(payload=action['target']))
            self.stage = 'sold'
            if self.feedback == 'crystals_missing':
                self.board.image[330:690,1700:2180] = 0
            elif self.feedback == 'wrong_refund':
                hud(self.board, gold=action['target'][1]+2)
        elif action['action'] == 'inspect_standard_unit' and self.recollecting:
            if action['target'][:2] != ['bench', 1]:
                raise AssertionError('recollection requested an unexpected slot')
            self.board = character(self.sold_board, {'collection': {'units': self.original_units}}, slot=1)
            self.stage = 'reinspected'
        elif action['action'] == 'close_standard_unit' and self.recollecting:
            self.board = clone(self.sold_board)
            cell = next(cell for cell in roster_cells(self.board) if (cell.zone, cell.slot) == ('bench', 1))
            crop = _crop(self.board.image, cell.roi)
            crop[:] = np.clip(crop.astype(int)+1, 0, 255).astype(np.uint8)
            self.recollected = clone(self.board)
            self.stage = 'recollected'
        else:
            super().click(*args)

    def run(self):
        with patch('autohsr.currency_wars_equipment.equipment_slots', return_value=('empty',)*3):
            return super().run()


class LootSaleContextTests(unittest.TestCase):
    def test_durable_source_loss_blocks_inspect_sale_and_followup_clicks(self):
        cases = (
            ('inspect_standard_sale_unit', 'normal', lambda actions: actions[0].pop('loot_sale_basis'), []),
            ('sell_standard_owned', 'normal', lambda actions: actions[0]['decision'].pop('loot_sale_basis_sha256'),
             ['inspect_standard_sale_unit']),
            ('collect_standard_loot', 'normal', lambda actions: actions[-2].pop('receipt'),
             ['inspect_standard_sale_unit', 'sell_standard_owned']),
            ('collect_standard_loot', 'recollect_portrait', lambda actions: actions[-2].pop('collection_receipt'),
             ['inspect_standard_sale_unit', 'sell_standard_owned', 'inspect_standard_unit', 'close_standard_unit']),
        )
        for intent, feedback, mutate, allowed in cases:
            with self.subTest(intent=intent, feedback=feedback), tempfile.TemporaryDirectory() as folder:
                harness = SaleHarness(folder, feedback=feedback)
                harness.corrupt_before_input(intent, mutate)
                with self.assertRaises(AutomationError):
                    harness.run()
                self.assertEqual(harness.inputs, allowed)
                self.assertEqual(harness.path.read_bytes(), harness.tampered_bytes)
                if feedback == 'recollect_portrait':
                    saved = StandardSession(harness.path).data
                    self.assertTrue(valid_receipt(saved['actions'][1]))

    def test_existing_inspection_and_sale_then_one_original_loot_input(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = SaleHarness(folder)
            with self.assertRaises(Stopped):
                harness.run()
            data = StandardSession(harness.path).data
            self.assertEqual(harness.inputs, ['inspect_standard_sale_unit', 'sell_standard_owned', 'collect_standard_loot'])
            inspection, sale, loot = data['actions']
            self.assertTrue(valid_receipt(sale))
            self.assertEqual(ledger_status(data['actions']), 'clear')
            self.assertEqual(sale['receipt']['refund'], 1)
            self.assertEqual(sale['receipt']['cells_after']['bench:9'][0], 'empty')
            self.assertEqual(inspection['loot_sale_basis']['crystals'], [list(c) for c in loot_centers(harness.before)])
            self.assertEqual(loot['status'], 'verified')
            self.assertTrue(loot['reward_basis']['snapshot']['roster_complete'])
            self.assertNotIn('bench:9', harness.migrated['units'])
            self.assertGreaterEqual(sum(stage=='sold' for stage,_ in harness.captures), 2)
            self.assertGreaterEqual(sum(stage=='collected' for stage,_ in harness.captures), 2)
            harness.c.window.drag.assert_not_called()

    def test_verified_same_slot_recollection_allows_pickup_after_small_portrait_change(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = SaleHarness(folder, feedback='recollect_portrait')
            try:
                result = harness.run()
            except Stopped:
                pass
            else:
                data = StandardSession(harness.path).data
                self.fail(f'{result.detail}，动作 {[a["action"] for a in data["actions"]]}')
            data = StandardSession(harness.path).data
            self.assertEqual(harness.inputs, ['inspect_standard_sale_unit', 'sell_standard_owned',
                                              'inspect_standard_unit', 'close_standard_unit', 'collect_standard_loot'])
            sale, inspect, close, loot = data['actions'][1:]
            self.assertTrue(valid_receipt(sale))
            self.assertEqual(inspect['target'][3], sale['receipt']['cells_after']['bench:1'][1])
            self.assertNotEqual(close['collection_receipt']['signature'], inspect['target'][3])
            self.assertEqual(loot['status'], 'verified')
            # The existing pickup can reuse the receipt and today's verified
            # roster, but neither a missing proof nor a freshly changed role.
            data['actions'].pop()
            data['collection'] = harness.migrated
            current = harness.recollected
            self.assertEqual(next_action(current, session=data).intent, 'collect_standard_loot')
            for case in ('missing_close_receipt', 'changed_role_read', 'changed_portrait', 'exchanged_slots'):
                with self.subTest(case=case):
                    candidate, scene = deepcopy(data), clone(current)
                    cell = next(c for c in roster_cells(scene) if (c.zone, c.slot) == ('bench', 1))
                    if case == 'missing_close_receipt':
                        del candidate['actions'][-1]['collection_receipt']
                    elif case == 'changed_role_read':
                        record = candidate['collection']['units']['bench:1']
                        record['unit']['name'] = '不同角色'
                        candidate['actions'][-1]['collection_read']['unit']['name'] = '不同角色'
                        self.assertTrue(retained(scene, cell, record, candidate))
                    elif case == 'changed_portrait':
                        crop = _crop(scene.image, cell.roi)
                        crop[:] = np.random.default_rng(117).integers(0, 256, crop.shape, dtype=np.uint8)
                    else:
                        first, second = (_crop(scene.image, bench_face(slot)) for slot in (1, 2))
                        first[:], second[:] = second.copy(), first.copy()
                    with self.assertRaisesRegex(AutomationError, '原晶矿、空位'):
                        next_action(scene, session=candidate)

    def test_reload_preserves_sale_and_allows_only_fresh_observation_or_original_pickup(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = SaleHarness(folder, feedback='crystals_missing')
            self.assertEqual(harness.run().status, 'partial')
            data = StandardSession(harness.path).data
            sale = data['actions'][-1]
            current = sold(harness.before, SimpleNamespace(payload=sale['target']))
            current.image[330:690,1700:2180] = np.roll(current.image[330:690,1700:2180], 3, axis=1)
            self.assertEqual(next_action(current, session=data).intent, 'collect_standard_loot')
            new_scope = deepcopy(data)
            new_scope['collection'].update(units={}, complete=False)
            self.assertEqual(next_action(current, session=new_scope).intent, 'inspect_standard_unit')
            changed = clone(current)
            _crop(changed.image, bench_face(9))[:] = _crop(harness.before.image, bench_face(9))
            with self.assertRaisesRegex(AutomationError, '原晶矿、空位'):
                next_action(changed, session=data)
            hud(current, gold=sale['receipt']['gold_after']+1)
            with self.assertRaisesRegex(AutomationError, '原晶矿、空位'):
                next_action(current, session=data)
            self.assertTrue(valid_receipt(StandardSession(harness.path).data['actions'][-1]))

    def test_dropped_or_changed_sale_crystal_source_cannot_fall_back_to_ordinary_sale(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = SaleHarness(folder, feedback='crystals_missing')
            self.assertEqual(harness.run().status, 'partial')
            data = StandardSession(harness.path).data
            sale = data['actions'][-1]
            current = sold(harness.before, SimpleNamespace(payload=sale['target']))
            self.assertEqual(next_action(current, session=data).intent, 'collect_standard_loot')
            for case in ('basis_missing', 'marker_missing', 'crystal_source_changed'):
                with self.subTest(case=case):
                    candidate = deepcopy(data)
                    source = candidate['actions'][0]
                    if case == 'basis_missing':
                        del source['loot_sale_basis']
                    elif case == 'marker_missing':
                        del source['decision']['loot_sale_basis_sha256']
                    else:
                        source['loot_sale_basis']['crystals'][0][0] += .001
                    with self.assertRaisesRegex(AutomationError, '原晶矿来源缺失或不一致'):
                        next_action(current, session=candidate)
            self.assertTrue(valid_receipt(StandardSession(harness.path).data['actions'][-1]))

    def test_disappearing_crystals_hold_after_verified_sale_without_replaying(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = SaleHarness(folder, feedback='crystals_missing')
            self.assertEqual(harness.run().status, 'partial')
            data = StandardSession(harness.path).data
            self.assertEqual(harness.inputs, ['inspect_standard_sale_unit', 'sell_standard_owned'])
            self.assertTrue(valid_receipt(data['actions'][-1]))
            self.assertEqual(ledger_status(data['actions']), 'clear')
            self.assertEqual(data['action_status'], 'needs_observation')
            with self.assertRaisesRegex(AutomationError, '原晶矿、空位'):
                next_action(harness.board, session=data)
            self.assertTrue(valid_receipt(StandardSession(harness.path).data['actions'][-1]))

    def test_wrong_sale_refund_never_unlocks_pickup_or_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = SaleHarness(folder, feedback='wrong_refund')
            self.assertEqual(harness.run().status, 'partial')
            data = StandardSession(harness.path).data
            self.assertEqual(harness.inputs, ['inspect_standard_sale_unit', 'sell_standard_owned'])
            self.assertEqual(data['actions'][-1]['status'], 'unknown')
            self.assertNotIn('receipt', data['actions'][-1])
            with self.assertRaises(AutomationError):
                harness.run()
            self.assertEqual(harness.inputs, ['inspect_standard_sale_unit', 'sell_standard_owned'])
