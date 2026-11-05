"""Standard loot capacity with an existing, verified bench sale candidate."""
from copy import deepcopy
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _BENCH_CENTERS, _crop, bench_face
from autohsr.currency_wars_match import read_match
from autohsr.currency_wars_node import loot_centers
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_collection import retained
from autohsr.currency_wars_standard_deployment import standard_deployment
from autohsr.currency_wars_standard_flow import _loot_pickup_chain, next_action
from autohsr.currency_wars_standard_ledger import ledger_status, valid_receipt
from autohsr.currency_wars_standard_rewards import valid_effect
from autohsr.currency_wars_standard_sale import proposal
from autohsr.models import AutomationError, Stopped, Token, normalize
from autohsr.tests.test_currency_wars_character_rewards import modal as hiring_modal
from autohsr.tests.test_currency_wars_loot_capacity import ROOT as CRYSTALS, Harness, clone, fixture as loot_fixture
from autohsr.tests.test_currency_wars_standard_equipment import recommend
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

    def corrupt_before_input(self, intent, mutate, *, occurrence=1):
        dispatch = self.c.currency_standard_input
        seen = 0

        def invoke(scene, choice):
            nonlocal seen
            if choice.intent == intent:
                seen += 1
                if seen == occurrence:
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


class DoubleSaleHarness(SaleHarness):
    """Sales around visible pickups, with configurable bench refills."""
    def __init__(self, folder, *, changed_survivor=False, second_candidate=True, third_candidate=False,
                 crystal_count=2, refill_at=(1,)):
        super().__init__(folder)
        self.changed_survivor = changed_survivor
        self.crystal_count = crystal_count
        self.refill_at = refill_at
        actual_crop = cv2.imread(str(CRYSTALS/'four_blue.png'))
        loot = self.board.image[330:690,1700:2180]
        loot[:] = 0
        for x, y in ((108, 127), (406, 200), (287, 62))[:crystal_count]:
            loot[y-55:y+55,x-55:x+55] = actual_crop[y-55:y+55,x-55:x+55]
        self.crystal_counts = [len(loot_centers(self.board))]
        store = StandardSession(self.path)
        records = store.data['collection']['units']
        for zone, names in (('front', ('大丽花', '符玄', '杰帕德')),
                            ('bench', ('停云', '瓦尔特', '花火', '三月七', '阮梅', '知更鸟', '桂乃芬', '符玄', '大丽花'))):
            for slot, name in enumerate(names, 1):
                records[f'{zone}:{slot}']['unit'].update(name=name, traits=('测试',))
        records['bench:8']['unit'].update(star=2, tier=2)
        if not second_candidate:
            records['bench:8']['unit']['name'] = '镜流'
        if third_candidate:
            records['bench:7']['unit'].update(name='杰帕德', star=3, tier=3)
        self.units = {key: deepcopy(record['unit']) for key, record in records.items()}
        store.persist()

    def checkpoint(self):
        store = getattr(self.c, 'currency_standard_session', None)
        actions = store.data['actions'] if store is not None else []
        if len(actions) > 60*self.crystal_count:
            raise AssertionError('pickup fixture exceeded the expected action bound')
        if sum(action['action']=='collect_standard_loot' and action['status']=='verified' for action in actions) == self.crystal_count:
            raise Stopped('all fixture crystals collected')

    def remove_crystal(self, target):
        x, y, radius = target
        cx, cy, margin = round(x*2560), round(y*1440), round(radius*2560)+8
        self.board.image[cy-margin:cy+margin,cx-margin:cx+margin] = 0

    def fill_bench(self, slot, name):
        portrait = _crop(self.board.image, bench_face(slot))
        portrait[:] = np.random.default_rng(481+slot).integers(0,256,portrait.shape,dtype=np.uint8)
        self.units[f'bench:{slot}'] = dict(name=name, zone='bench', slot=slot, star=1, tier=1,
                                          eligible_zones=('front',), traits=('测试',), equipment=())

    def relocate_survivor(self):
        x, y, radius = loot_centers(self.board)[0]
        cx, cy, margin = round(x*2560), round(y*1440), round(radius*2560)+8
        old = self.board.image[cy-margin:cy+margin,cx-margin:cx+margin]
        self.board.image[560-margin:560+margin,1940-margin:1940+margin] = old.copy()
        old[:] = 0

    def click(self, *args):
        store = self.c.currency_standard_session
        action = store.data['actions'][-1]
        intent, target = action['action'], action.get('target', ())
        self.inputs.append(intent)
        if intent in ('inspect_standard_sale_unit', 'inspect_standard_unit', 'inspect_standard_reward_unit'):
            self.prep = self.board
            if intent == 'inspect_standard_sale_unit':
                zone, slot = 'bench', target[4]
                refund = 10-slot
            else:
                zone, slot = target[:2]
                refund = 1
            profile = {'unit': self.units[f'{zone}:{slot}']}
            sources = {'collection': {'units': {f'bench:{slot}': profile}}}
            self.board = character(self.prep, sources, slot=slot, refund=refund)
        elif intent == 'open_standard_equipment_recommendations':
            self.board = recommend(self.board)
        elif intent in ('close_standard_unit', 'close_standard_reward_unit'):
            self.board = self.prep
        elif intent == 'sell_standard_owned':
            self.board = sold(self.prep, SimpleNamespace(payload=target))
            self.freed_slot = target[4]
            del self.units[f'bench:{self.freed_slot}']
        elif intent == 'collect_standard_loot':
            self.remove_crystal(target)
            if len(self.crystal_counts) in self.refill_at:
                self.fill_bench(self.freed_slot, '罗刹' if self.freed_slot==9 else '阿兰')
                if self.changed_survivor:
                    self.relocate_survivor()
            self.crystal_counts.append(len(loot_centers(self.board)))
        else:
            raise AssertionError(f'unexpected fixture input {intent}')


class HiringSaleHarness(DoubleSaleHarness):
    def __init__(self, folder, *, wrong_slot=False, moved_crystal=False, same_name=False):
        super().__init__(folder, refill_at=())
        self.wrong_slot = wrong_slot
        self.moved_crystal = moved_crystal
        self.hired_name = '停云' if same_name else '罗刹'
        if same_name:
            self.units['bench:1']['star'] = 2
            store = StandardSession(self.path)
            store.data['collection']['units']['bench:1']['unit']['star'] = 2
            store.persist()

    def click(self, *args):
        action = self.c.currency_standard_session.data['actions'][-1]
        intent, target = action['action'], action.get('target', ())
        if intent == 'collect_standard_loot' and len(self.crystal_counts) == 1:
            self.inputs.append(intent)
            self.remove_crystal(target)
            self.crystal_counts.append(len(loot_centers(self.board)))
            self.open_hiring()
        elif intent == 'choose_standard_reward':
            self.inputs.append(intent)
            self.board = self.return_board
            slot = self.freed_slot
            if self.wrong_slot:
                # Keep the roster multiset valid for the existing reward, but
                # move the original occupant into the sale's freed slot.
                old, freed = (_crop(self.board.image, bench_face(index)) for index in (1, slot))
                freed[:] = cv2.resize(old, (freed.shape[1], freed.shape[0]))
                self.units[f'bench:{slot}'] = dict(self.units['bench:1'], slot=slot)
                slot = 1
            self.fill_bench(slot, target[6])
            if self.moved_crystal:
                self.relocate_survivor()
            self.stage = 'hiring_returned'
        else:
            if intent == 'inspect_standard_reward_unit' and self.stage == 'hiring_returned':
                self.stage = 'hiring_recollect'
            super().click(*args)

    def open_hiring(self):
        self.return_board = self.board
        state = read_match(self.board)
        self.board = hiring_modal(self.board, names=(self.hired_name,), tier=1)
        self.board.tokens = [token for token in self.board.tokens if not normalize(token.text).startswith('uid')]
        self.board.tokens.extend(token for token in self.return_board.tokens if normalize(token.text).startswith('uid'))
        hud(self.board, gold=state.gold, level=state.level, xp=state.experience, deployment=state.deployment)
        self.board.image[330:690,1700:2180] = 0
        self.stage = 'hiring_open'


def place_box(scene, slot, *, pixels=True):
    x = _BENCH_CENTERS[slot-1]
    scene.tokens.append(Token('开启', .99, (x-.012, .82, x+.012, .86)))
    if pixels:
        art = _crop(scene.image, bench_face(slot))
        art[:] = np.random.default_rng(322+slot).integers(0, 256, art.shape, dtype=np.uint8)


class BenchHiringSaleHarness(HiringSaleHarness):
    def __init__(self, folder, *, fault=None):
        super().__init__(folder)
        self.fault = fault
        self.c.window.click_held = Mock(side_effect=self.held)
        self.before_open = self.after_open = None
        self.first_modal_stamp = None
        sleep = self.c.sleep
        self.c.sleep = lambda seconds: sleep(31 if seconds == .5 and fault and self.first_modal_stamp is None
                                            else seconds)

    def click(self, *args):
        action = self.c.currency_standard_session.data['actions'][-1]
        intent = action['action']
        if intent == 'collect_standard_loot' and len(self.crystal_counts) == 1:
            self.inputs.append(intent)
            self.remove_crystal(action['target'])
            self.crystal_counts.append(len(loot_centers(self.board)))
            place_box(self.board, self.freed_slot, pixels=self.fault != 'label_only')
            if self.fault == 'extra_box':
                place_box(self.board, 3)
            self.stage = 'box_received'
            return
        if intent == 'choose_standard_reward':
            x = _BENCH_CENTERS[self.freed_slot-1]
            self.return_board.tokens = [t for t in self.return_board.tokens
                                        if normalize(t.text) != '开启' or abs(t.center[0]-x) > .01]
            _crop(self.return_board.image, bench_face(self.freed_slot))[:] = 0
        super().click(*args)

    def held(self, x, y, geometry, *, checkpoint):
        checkpoint()
        action = self.c.currency_standard_session.data['actions'][-1]
        self.inputs.append(action['action'])
        self.before_open = (clone(self.board), deepcopy(self.c.currency_standard_session.data))
        self.open_hiring()

    def snapshot(self):
        scene = super().snapshot()
        if self.fault == 'stale_open' and self.stage == 'hiring_open':
            if self.first_modal_stamp is None:
                self.first_modal_stamp = scene.captured_at
            else:
                scene.captured_at = self.first_modal_stamp
                self.first_modal_stamp = None
        return scene

    def checkpoint(self):
        super().checkpoint()
        store = getattr(self.c, 'currency_standard_session', None)
        if store and store.data['actions'] and self.after_open is None:
            last = store.data['actions'][-1]
            if last['action'] == 'open_standard_bench_reward' and last['status'] == 'verified':
                self.after_open = clone(self.board), deepcopy(store.data)


class LootSaleContextTests(unittest.TestCase):
    def test_crystal_bench_box_opens_original_slot_and_hiring_returns_to_it(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = BenchHiringSaleHarness(folder)
            with self.assertRaises(Stopped):
                harness.run()
            self.assertEqual(harness.crystal_counts, [2, 1, 0])
            self.assertEqual(harness.inputs.count('sell_standard_owned'), 2)
            self.assertEqual(harness.inputs.count('choose_standard_reward'), 1)
            harness.c.window.click_held.assert_called_once()
            self.assertEqual(harness.c.window.click_held.call_args.args[:2], (_BENCH_CENTERS[8], 1210/1440))
            data = StandardSession(harness.path).data
            actions = data['actions']
            pickup = next(a for a in actions if a['action'] == 'collect_standard_loot')
            opening = next(a for a in actions if a['action'] == 'open_standard_bench_reward')
            claim = actions[opening['id']+1]
            self.assertEqual(pickup['loot_pickup_kind'], 'bench_box')
            self.assertEqual(opening['target'][1:], pickup['loot_pickup']['bench_box'])
            self.assertEqual(opening['loot_box_pickup_action_id'], pickup['id'])
            self.assertEqual(claim['target'][1:3], [opening['id'], 'hiring_selection'])
            self.assertEqual(claim['loot_reward_return']['added_bench_slot'], 9)
            self.assertTrue(claim['loot_reward_return']['unit_slot_verified'])
            self.assertTrue(valid_effect(claim, actions))
            self.assertEqual(ledger_status(actions), 'clear')
            self.assertGreaterEqual(sum(stage == 'box_received' for stage,_ in harness.captures), 2)
            self.assertGreaterEqual(sum(stage == 'hiring_open' for stage,_ in harness.captures), 2)

            board, pending = harness.before_open
            waiting = dict(pending, actions=deepcopy(pending['actions'][:-1]))
            wrong = clone(board)
            place_box(wrong, 3)  # A visible unrelated opening must never replace the bound one.
            with self.assertRaisesRegex(AutomationError, '原槽'):
                next_action(wrong, session=waiting)
            existing = deepcopy(waiting)
            cell3 = next(c for c in roster_cells(wrong) if (c.zone, c.slot) == ('bench', 3))
            existing['actions'][pickup['id']]['reward_basis']['cells']['bench:3'] = [cell3.state, cell3.signature]
            existing['collection']['units'].pop('bench:3')
            self.assertEqual(next_action(wrong, session=existing).payload, tuple(opening['target']))
            changed = clone(board)
            _crop(changed.image, bench_face(9))[0, 0] ^= 255
            with self.assertRaisesRegex(AutomationError, '原槽'):
                next_action(changed, session=waiting)
            missing = deepcopy(waiting)
            missing['actions'][pickup['id']]['loot_pickup'].pop('bench_box')
            with self.assertRaisesRegex(AutomationError, '领取和槽位来源'):
                next_action(board, session=missing)
            page, active = harness.after_open
            history = deepcopy(active)
            history['reward']['origin_action_id'] = pickup['loot_sale_action_id']
            with self.assertRaisesRegex(AutomationError, '开启来源'):
                next_action(page, session=history)

    def test_pending_open_never_uses_a_different_durable_pickup(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = BenchHiringSaleHarness(folder)
            def substitute(actions):
                actions[-1]['loot_box_pickup_action_id'] = actions[0]['id']

            harness.corrupt_before_input('open_standard_bench_reward', substitute)
            with self.assertRaisesRegex(AutomationError, '落盘槽位'):
                harness.run()
            harness.c.window.click_held.assert_not_called()
            self.assertNotIn('choose_standard_reward', harness.inputs)
            self.assertEqual(harness.path.read_bytes(), harness.tampered_bytes)
            self.assertEqual(StandardSession(harness.path).data['actions'][-1]['status'], 'pending')

    def test_unresolved_bench_box_is_never_replayed(self):
        for fault in ('label_only', 'extra_box', 'stale_open'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                harness = BenchHiringSaleHarness(folder, fault=fault)
                self.assertEqual(harness.run().status, 'partial')
                held = 1 if fault == 'stale_open' else 0
                self.assertEqual(harness.c.window.click_held.call_count, held)
                self.assertNotIn('choose_standard_reward', harness.inputs)
                saved_bytes = harness.path.read_bytes()
                last = StandardSession(harness.path).data['actions'][-1]
                self.assertEqual(last['status'], 'unknown')
                self.assertEqual(last['action'], 'open_standard_bench_reward' if held else 'collect_standard_loot')
                with self.assertRaisesRegex(AutomationError, '上次标准动作尚未核实'):
                    harness.run()
                self.assertEqual(harness.path.read_bytes(), saved_bytes)
                self.assertEqual(harness.c.window.click_held.call_count, held)

    def test_hiring_reward_refills_slot_then_remaining_crystal_can_be_collected(self):
        for same_name in (False, True):
            with self.subTest(same_name=same_name), tempfile.TemporaryDirectory() as folder:
                harness = HiringSaleHarness(folder, same_name=same_name)
                reason = ''
                try:
                    reason = harness.run().detail
                except Stopped:
                    pass
                saved = StandardSession(harness.path).data
                actions = saved['actions']
                self.assertGreaterEqual(len(actions), 4, reason)
                sale, origin, claim = actions[1:4]
                self.assertTrue(valid_receipt(sale))
                self.assertEqual(origin['action'], 'collect_standard_loot')
                self.assertEqual((claim['action'], claim['target'][1:3]), ('choose_standard_reward', [origin['id'], 'hiring_selection']))
                self.assertTrue(origin['reward_verified'])
                self.assertTrue(claim['reward_verified'])
                self.assertTrue(valid_effect(claim, actions))
                self.assertEqual(origin.get('loot_pickup', {}).get('reward_page'), 'hiring_selection')
                refill = claim.get('loot_reward_return', {})
                self.assertEqual(refill.get('added_bench_slot'), 9)
                self.assertIs(refill.get('unit_slot_verified'), True)
                slot_read = refill['unit_slot_read']
                inspect_id = slot_read['action_id']
                self.assertRegex(slot_read['signature'], r'^[0-9a-f]{64}$')
                inspected_action, closed_action = actions[inspect_id:inspect_id+2]
                self.assertEqual(inspected_action['action'], 'inspect_standard_reward_unit')
                self.assertEqual(inspected_action['target'], ['bench', 9, '1-1', slot_read['signature']])
                self.assertEqual(closed_action['action'], 'close_standard_reward_unit')
                self.assertTrue(all(action['status']=='verified' and action['before'] and action['after']
                                    for action in (inspected_action, closed_action)))
                self.assertEqual(inspected_action['input_epoch'], closed_action['input_epoch'])
                effect = claim['reward_effect']
                self.assertEqual(effect['delivery_kind'], 'unit')
                self.assertEqual(effect['unit'], harness.hired_name)
                self.assertEqual(effect['stars_before'], [2] if same_name else [])
                self.assertEqual(effect['stars_after'], [2,1] if same_name else [1])
                self.assertEqual(effect['tiers_after'], [1,1] if same_name else [1])
                inspected = [action['target'][:2] for action in actions if action['action']=='inspect_standard_reward_unit']
                self.assertEqual(len({tuple(target) for target in inspected}), 12)
                self.assertIn(['bench', 9], inspected)
                self.assertGreaterEqual(sum(stage=='hiring_returned' for stage,_ in harness.captures), 2)
                self.assertEqual(harness.crystal_counts, [2,1,0], reason)
                sales = [action for action in actions if action['action']=='sell_standard_owned']
                self.assertEqual([action['target'][4] for action in sales], [9,8])
                start, end = sale['id'], sales[1]['id']-1
                basis = actions[start-1]['loot_sale_basis']
                self.assertIsNotNone(_loot_pickup_chain(actions, start, end, basis))
                damaged = deepcopy(actions)
                damaged[inspect_id]['target'][3] = None
                self.assertTrue(valid_effect(damaged[claim['id']], damaged))
                self.assertIsNone(_loot_pickup_chain(damaged, start, end, basis))
                self.assertEqual(harness.inputs.count('choose_standard_reward'), 1)
                self.assertEqual(ledger_status(actions), 'clear')
                self.assertNotIn('open_standard_shop', harness.inputs)

    def test_verified_hiring_does_not_unlock_sale_for_wrong_slot_or_moved_crystal(self):
        for case in ('wrong_slot', 'moved_crystal'):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as folder:
                harness = HiringSaleHarness(folder, **{case: True})
                self.assertEqual(harness.run().status, 'partial')
                actions = StandardSession(harness.path).data['actions']
                sale, origin, claim = actions[1:4]
                self.assertTrue(valid_receipt(sale))
                self.assertTrue(origin['reward_verified'])
                self.assertTrue(claim['reward_verified'])
                self.assertTrue(valid_effect(claim, actions))
                self.assertIsNot(claim.get('loot_reward_return', {}).get('unit_slot_verified'), True)
                self.assertEqual(ledger_status(actions), 'clear')
                self.assertEqual(harness.crystal_counts, [2,1])
                self.assertEqual(harness.inputs.count('choose_standard_reward'), 1)
                self.assertEqual(harness.inputs.count('inspect_standard_sale_unit'), 1)
                self.assertEqual(harness.inputs.count('sell_standard_owned'), 1)
                self.assertEqual(harness.inputs.count('collect_standard_loot'), 1)

    def test_hiring_same_name_moved_copy_does_not_prove_refill_at_the_freed_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = HiringSaleHarness(folder, same_name=True, wrong_slot=True)
            try:
                self.assertEqual(harness.run().status, 'partial')
            except Stopped:
                pass  # Check whether the old code actually sent the extra input.
            actions = StandardSession(harness.path).data['actions']
            sale, origin, claim = actions[1:4]
            self.assertTrue(valid_receipt(sale))
            self.assertTrue(origin['reward_verified'])
            self.assertTrue(claim['reward_verified'])
            self.assertTrue(valid_effect(claim, actions))
            effect = claim['reward_effect']
            self.assertEqual((effect['unit'], effect['stars_before'], effect['stars_after']), ('停云', [2], [2,1]))
            self.assertEqual([harness.units[f'bench:{slot}']['star'] for slot in (1,9)], [1,2])
            self.assertEqual(ledger_status(actions), 'clear')
            self.assertIsNot(claim.get('loot_reward_return', {}).get('unit_slot_verified'), True,
                             f'after {harness.inputs.count("sell_standard_owned")} sales and crystals {harness.crystal_counts}')
            self.assertEqual(harness.crystal_counts, [2,1])
            self.assertEqual(harness.inputs.count('inspect_standard_sale_unit'), 1)
            self.assertEqual(harness.inputs.count('sell_standard_owned'), 1)

    def test_missing_durable_hiring_effect_blocks_second_sale_input(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = HiringSaleHarness(folder)
            harness.corrupt_before_input('inspect_standard_sale_unit', lambda actions: actions[3].pop('reward_effect'),
                                         occurrence=2)
            with self.assertRaises(AutomationError):
                harness.run()
            self.assertEqual(harness.inputs.count('inspect_standard_sale_unit'), 1)
            self.assertEqual(harness.inputs.count('sell_standard_owned'), 1)
            self.assertEqual(harness.inputs.count('choose_standard_reward'), 1)
            self.assertEqual(harness.path.read_bytes(), harness.tampered_bytes)
            actions = StandardSession(harness.path).data['actions']
            self.assertTrue(valid_receipt(actions[1]))
            self.assertEqual(actions[-1]['status'], 'pending')
            self.assertEqual(actions[-1]['target'][4], 8)

    def test_full_field_recovers_second_crystal_after_first_refills_the_freed_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = DoubleSaleHarness(folder)
            try:
                result = harness.run()
            except Stopped:
                pass
            else:
                data = StandardSession(harness.path).data
                self.assertEqual(harness.crystal_counts, [2, 1, 0],
                                 f'{result.detail}，商店来源 {data.get("shop_observed_nodes")}')
                self.fail('fixture did not reach the second verified pickup')
            data = StandardSession(harness.path).data
            actions = [action for action in data['actions']
                       if action['action'] in ('inspect_standard_sale_unit', 'sell_standard_owned', 'collect_standard_loot')]
            self.assertEqual([a['action'] for a in actions],
                             ['inspect_standard_sale_unit', 'sell_standard_owned', 'collect_standard_loot']*2)
            self.assertTrue(all(a['status']=='verified' for a in actions))
            self.assertEqual(harness.crystal_counts, [2, 1, 0])
            self.assertEqual([actions[index]['target'][4] for index in (1,4)], [9, 8])
            self.assertTrue(all(valid_receipt(actions[index]) for index in (1,4)))
            self.assertEqual([actions[index]['receipt']['refund'] for index in (1,4)], [1, 2])
            self.assertEqual(ledger_status(data['actions']), 'clear')
            reread = data['actions'][actions[2]['id']+1:actions[3]['id']]
            closed = [action['collection_read']['unit'] for action in reread if action['action']=='close_standard_unit']
            self.assertEqual(len(closed), 12)
            self.assertEqual(len({(unit['zone'], unit['slot']) for unit in closed}), 12)
            self.assertEqual([unit['name'] for unit in closed if unit['zone']=='bench' and unit['slot']==9], ['罗刹'])
            after_second_sale = data['actions'][actions[4]['id']+1:actions[5]['id']]
            reread_slots = [tuple(action['target'][1:3]) for action in after_second_sale if action['action']=='close_standard_unit']
            self.assertEqual(len(reread_slots), 11)
            self.assertEqual(len(set(reread_slots)), 11)
            self.assertNotIn('open_standard_shop', harness.inputs)
            self.assertEqual(data['shop_observed_nodes'], [])
            harness.c.window.drag.assert_not_called()

    def test_second_crystal_requires_same_survivor_and_a_current_safe_sale_candidate(self):
        for options in (dict(changed_survivor=True), dict(second_candidate=False)):
            with self.subTest(**options), tempfile.TemporaryDirectory() as folder:
                harness = DoubleSaleHarness(folder, **options)
                self.assertEqual(harness.run().status, 'partial')
                data = StandardSession(harness.path).data
                self.assertEqual(harness.crystal_counts, [2, 1])
                self.assertEqual(harness.inputs.count('inspect_standard_sale_unit'), 1)
                self.assertEqual(harness.inputs.count('sell_standard_owned'), 1)
                first_sale, first_loot = data['actions'][1:3]
                self.assertTrue(valid_receipt(first_sale))
                self.assertEqual(first_loot['status'], 'verified')
                self.assertEqual(data['shop_observed_nodes'], [])

    def test_second_pickup_with_empty_bench_uses_original_path_without_another_sale(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = DoubleSaleHarness(folder, refill_at=())
            with self.assertRaises(Stopped):
                harness.run()
            self.assertEqual(harness.crystal_counts, [2, 1, 0])
            self.assertEqual(harness.inputs.count('inspect_standard_sale_unit'), 1)
            self.assertEqual(harness.inputs.count('sell_standard_owned'), 1)
            self.assertEqual(harness.inputs.count('collect_standard_loot'), 2)
            self.assertNotIn('open_standard_shop', harness.inputs)

    def test_third_pickup_keeps_sale_source_across_an_intermediate_free_pickup(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = DoubleSaleHarness(folder, crystal_count=3, refill_at=(2,))
            self.assertEqual(harness.crystal_counts, [3])
            try:
                result = harness.run()
            except Stopped:
                pass
            else:
                self.fail(f'{result.detail}，晶矿计数 {harness.crystal_counts}')
            saved = StandardSession(harness.path).data
            actions = [action for action in saved['actions']
                       if action['action'] in ('inspect_standard_sale_unit', 'sell_standard_owned', 'collect_standard_loot')]
            self.assertEqual([action['action'] for action in actions], [
                'inspect_standard_sale_unit', 'sell_standard_owned', 'collect_standard_loot', 'collect_standard_loot',
                'inspect_standard_sale_unit', 'sell_standard_owned', 'collect_standard_loot',
            ])
            self.assertTrue(all(action['status']=='verified' for action in actions))
            self.assertEqual(harness.crystal_counts, [3, 2, 1, 0])
            self.assertEqual([actions[index]['loot_sale_action_id'] for index in (2, 3, 6)],
                             [actions[1]['id'], actions[1]['id'], actions[5]['id']])
            self.assertEqual([actions[index]['reward_basis']['cells']['bench:9'][0] for index in (2,3,6)],
                             ['empty', 'empty', 'occupied'])
            self.assertTrue(all(valid_receipt(actions[index]) for index in (1,5)))
            self.assertNotIn('open_standard_shop', harness.inputs)
            self.assertEqual(saved['shop_observed_nodes'], [])

    def test_third_sale_rechecks_first_pickup_ancestor(self):
        for missing_ancestor in (True, False):
            with self.subTest(missing_ancestor=missing_ancestor), tempfile.TemporaryDirectory() as folder:
                harness = DoubleSaleHarness(folder, crystal_count=3, refill_at=(1,2), third_candidate=True)
                if missing_ancestor:
                    def remove_first_pickup(actions):
                        next(action for action in actions if action['action']=='collect_standard_loot').pop('loot_pickup')

                    harness.corrupt_before_input('inspect_standard_sale_unit', remove_first_pickup, occurrence=3)
                    with self.assertRaisesRegex(AutomationError, '连续晶矿缺少前次已核实'):
                        harness.run()
                    self.assertEqual(harness.path.read_bytes(), harness.tampered_bytes)
                else:
                    try:
                        result = harness.run()
                    except Stopped:
                        pass
                    else:
                        self.fail(f'{result.detail}，晶矿计数 {harness.crystal_counts}')
                data = StandardSession(harness.path).data
                sales = [action for action in data['actions'] if action['action']=='sell_standard_owned']
                pickups = [action for action in data['actions'] if action['action']=='collect_standard_loot']
                slots = [9, 8] if missing_ancestor else [9, 8, 7]
                self.assertEqual(harness.inputs.count('inspect_standard_sale_unit'), len(slots))
                self.assertEqual(harness.inputs.count('sell_standard_owned'), len(slots))
                self.assertEqual(harness.crystal_counts, [3,2,1] if missing_ancestor else [3,2,1,0])
                self.assertEqual([sale['target'][4] for sale in sales], slots)
                self.assertTrue(all(valid_receipt(sale) for sale in sales))
                self.assertEqual([pickup['loot_sale_action_id'] for pickup in pickups], [sale['id'] for sale in sales])
                if missing_ancestor:
                    self.assertEqual(data['actions'][-1]['status'], 'pending')
                    self.assertEqual(data['actions'][-1]['target'][4], 7)
                    self.assertNotIn('loot_pickup', pickups[0])
                    self.assertIn('loot_pickup', pickups[1])
                self.assertNotIn('open_standard_shop', harness.inputs)

    def test_missing_durable_first_pickup_feedback_blocks_the_second_sale_inspection(self):
        with tempfile.TemporaryDirectory() as folder:
            harness = DoubleSaleHarness(folder)
            harness.corrupt_before_input('inspect_standard_sale_unit', lambda actions: actions[2].pop('after'), occurrence=2)
            with self.assertRaises(AutomationError):
                harness.run()
            self.assertEqual(harness.inputs.count('inspect_standard_sale_unit'), 1)
            self.assertEqual(harness.inputs.count('sell_standard_owned'), 1)
            self.assertEqual(harness.crystal_counts, [2, 1])
            self.assertEqual(harness.path.read_bytes(), harness.tampered_bytes)
            saved = StandardSession(harness.path).data
            self.assertTrue(valid_receipt(saved['actions'][1]))

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
