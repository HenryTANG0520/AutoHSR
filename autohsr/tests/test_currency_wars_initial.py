"""Initial custody using synthetic scenes and temporary PNGs; no Runner input."""
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np
from PIL import Image

from autohsr.currency_wars_collector import roster_cells
from autohsr.currency_wars_deployment import _crop, bench_face
from autohsr.currency_wars_environment import ENVIRONMENT_POLICY, parse_environment_effect
from autohsr.currency_wars_identity import account_key
from autohsr.currency_wars_initial import (KEY, accepted, begin, capture_current, evidence_ref,
    record_arrival, source_file_ref, validate_origin)
from autohsr.currency_wars_standard_collection import (bind_inspection, bind_close, close_current,
    closed, profile)
from autohsr.currency_wars_standard_flow import StandardAction
from autohsr.models import AutomationError, Scene, Token, normalize
from autohsr.tests.test_currency_wars_standard_deployment import frame_and_session
from autohsr.tests.test_currency_wars_standard_equipment import panel


def clone(scene):
    return Scene(list(scene.tokens), scene.image.copy(), captured_at=time.monotonic(),
                 field_reads=deepcopy(scene.field_reads))


def write_scene(folder, name, scene):
    path = Path(folder) / name
    Image.fromarray(scene.image[:, :, ::-1]).save(path)
    return path


def fixture(folder, *, empty=False):
    board, session = frame_and_session()
    for slot in range(1 if empty else 2, 6):
        _crop(board.image, bench_face(slot))[:] = (80, 35, 25)
        session['collection']['units'].pop('bench:'+str(slot))
    root = str(Path(folder).resolve())
    session.update(mode='standard_development', match_id='a'*32, rank=8, wealth=40,
        account_verified_run=root, account_verified_epoch=0)
    session['client'].update(verified_run=root, input_epoch=0)
    session['collection'].update(run_dir=root, input_epoch=0)
    before = str(write_scene(folder, 'initial-confirm-before.png', board))
    session['actions'] = [dict(id=i, action=name, status='verified', input_epoch=0,
        before=before, after=before) for i, name in enumerate(
        ('start_standard_a8_40', 'advance_standard_preview', 'advance_standard_plane'))]
    effect = '获得1个随机2星2费角色，进入新节点时，这位角色永久获得随机属性加成。'
    kind, parameters, score, reason = parse_environment_effect(effect)
    session['actions'].append(dict(id=3, action='confirm_standard_environment_1', status='pending',
        expected='initial_board', input_epoch=0, before=before,
        decision=dict(name='战力飙升', kind=kind, effect=effect, parameters=dict(parameters),
                      score=score, reason=reason, policy=ENVIRONMENT_POLICY)))
    board.captured_at = time.monotonic()
    return board, session


def shop_scene(board):
    path = Path(__file__).parent / 'fixtures/currency_wars_pages.json'
    raw = json.loads(path.read_text(encoding='utf-8'))['pages']['shop']['tokens']
    tokens = [Token(**t) for t in raw]
    tokens = [t for t in tokens if not (t.within((.851, .829, .87, .868))
              or t.within((.125, .815, .185, .87)) or t.within((.13, .865, .18, .90))
              or normalize(t.text).startswith('uid'))]
    tokens += [Token('17', .99, (.852, .84, .867, .86)), Token('LV.3', .99, (.14, .82, .18, .86)),
               Token('UID:100000000', .99, (.01, .96, .1, .99))]
    return Scene(tokens, board.image.copy(), captured_at=time.monotonic())


def arrive(folder, board, session, *, mixed=False):
    begin(session, 3, run_dir=folder, epoch=0)
    first = clone(board)
    one = write_scene(folder, 'arrival-one.png', first)
    assert not record_arrival(session, first, evidence=one, run_dir=folder, epoch=0)
    last = shop_scene(board) if mixed else clone(board)
    two = write_scene(folder, 'arrival-two.png', last)
    assert record_arrival(session, last, evidence=two, run_dir=folder, epoch=0)
    session['actions'][3].update(status='verified', after=str(write_scene(folder, 'confirm-after.png', last)))
    accepted(session, 3)
    return last


def collect_role(folder, board, session):
    """Drive real collection functions with a synthetic independent panel."""
    if not session['collection']['units']:
        session['collection']['complete'] = True
        return
    original = deepcopy(session['collection']['units']['bench:1']['unit'])
    session['collection'].update(complete=False, units={})
    cell = next(c for c in roster_cells(board) if c.zone == 'bench' and c.slot == 1)
    detail = panel(original)
    detail.tokens.append(Token('UID:100000000', .99, (.01, .96, .1, .99)))
    root = str(Path(folder).resolve())
    before = str(write_scene(folder, 'inspect-before.png', board))
    shown = str(write_scene(folder, 'inspect-after.png', detail))
    index = len(session['actions'])
    inspect = dict(id=index, action='inspect_standard_unit', expected='character', status='pending',
        input_epoch=0, before=before, target=['bench', 1, '1-1', cell.signature])
    session['actions'].append(inspect)
    bind_inspection(session, StandardAction('inspect_standard_unit', 'character', None,
        payload=tuple(inspect['target'])), board)
    inspect.update(status='verified', after=shown, inspection_run_dir=root)
    session['inspecting'] = dict(zone='bench', slot=1, node='1-1', signature=cell.signature,
        input_epoch=0, run_dir=root, before=before, after=shown, inspection_action_id=index)
    unit = profile(detail, session)
    session['collection']['units']['bench:1'] = dict(unit=asdict(unit), signature=cell.signature,
        node='1-1', source=shown, input_epoch=0, run_dir=root, inspection_action_id=index)
    choice = close_current(detail, session)
    close = dict(id=len(session['actions']), action=choice.intent, expected=choice.expected,
        target=list(choice.payload), status='pending', input_epoch=0, before=shown)
    session['actions'].append(close)
    bind_close(session, choice, detail)
    close.update(status='verified', after=str(write_scene(folder, 'close-after.png', board)))
    closed(session, choice, board)
    session['collection']['complete'] = True


class InitialEnvironmentTests(unittest.TestCase):
    def test_current_pending_binding_is_idempotent_but_never_adopts_verified_or_other_plane(self):
        with tempfile.TemporaryDirectory() as folder:
            board, session = fixture(folder)
            first = begin(session, 3, run_dir=folder, epoch=0)
            self.assertEqual(first, begin(session, 3, run_dir=folder, epoch=0))
            self.assertFalse(first['selection_accepted'])
            self.assertFalse(first['declared_obligations'][0]['delivery_verified'])
            session['actions'][3]['decision']['parameters']['count'] = 3
            with self.assertRaises(AutomationError):
                begin(session, 3, run_dir=folder, epoch=0)
            self.assertEqual(session[KEY], first)
        for change in ('verified', 'plane', 'past_battle', 'effect', 'epoch_bool'):
            with tempfile.TemporaryDirectory() as folder:
                _, session = fixture(folder)
                if change == 'verified': session['actions'][3]['status'] = 'verified'
                elif change == 'plane': session['expected_board'] = '2-1'
                elif change == 'past_battle': session['actions'][1]['action'] = 'start_standard_node'
                elif change == 'effect': session['actions'][3]['decision']['effect'] += '并扣除金币'
                else: session['actions'][3]['input_epoch'] = False
                with self.assertRaises(AutomationError):
                    begin(session, 3, run_dir=folder, epoch=0)
                self.assertNotIn(KEY, session)

    def test_two_distinct_captures_can_have_identical_pixels_and_acceptance_never_proves_gift(self):
        with tempfile.TemporaryDirectory() as folder:
            board, session = fixture(folder)
            arrive(folder, board, session)
            value = validate_origin(session, require_accepted=True)
            self.assertEqual(len(value['arrival_frames']), 2)
            self.assertNotEqual(value['arrival_frames'][0]['captured_at'], value['arrival_frames'][1]['captured_at'])
            self.assertEqual(value['arrival_frames'][0]['evidence']['sha256'], value['arrival_frames'][1]['evidence']['sha256'])
            self.assertTrue(value['selection_accepted'])
            self.assertEqual(value['declared_obligations'][0]['status'], 'unattributed')
            self.assertFalse(value['declared_obligations'][0]['delivery_verified'])
            self.assertEqual(accepted(session, 3), value)

    def test_prep_to_shop_keeps_hidden_hp_and_experience_unknown(self):
        with tempfile.TemporaryDirectory() as folder:
            board, session = fixture(folder)
            arrive(folder, board, session, mixed=True)
            frames = validate_origin(session, require_accepted=True)['arrival_frames']
            self.assertEqual([f['page'] for f in frames], ['preparation', 'shop'])
            self.assertEqual(frames[0]['board']['hp'], 100)
            self.assertIsNone(frames[1]['board']['hp'])
            self.assertIsNone(frames[1]['board']['deployment'])

    def test_reused_capture_changed_account_node_epoch_and_visible_gold_never_accept(self):
        for change in ('capture', 'account', 'node', 'epoch', 'gold'):
            with tempfile.TemporaryDirectory() as folder:
                board, session = fixture(folder)
                begin(session, 3, run_dir=folder, epoch=0)
                first = clone(board)
                record_arrival(session, first, evidence=write_scene(folder, 'one.png', first), run_dir=folder, epoch=0)
                frozen = deepcopy(session[KEY])
                second = clone(board)
                epoch = 0
                if change == 'capture': second.captured_at = first.captured_at
                elif change == 'account':
                    second.tokens = [Token('UID:200000000', t.score, t.box) if normalize(t.text).startswith('uid') else t for t in second.tokens]
                elif change == 'node': second.tokens = [Token('1-2', t.score, t.box) if t.text == '1-1' else t for t in second.tokens]
                elif change == 'epoch': epoch = 1
                else: second.tokens.append(Token('18', .99, (.852, .84, .867, .86)))
                path = write_scene(folder, 'two.png', second)
                if change == 'gold':
                    self.assertFalse(record_arrival(session, second, evidence=path, run_dir=folder, epoch=epoch))
                else:
                    with self.assertRaises(AutomationError):
                        record_arrival(session, second, evidence=path, run_dir=folder, epoch=epoch)
                self.assertEqual(session[KEY], frozen)
                with self.assertRaises(AutomationError): accepted(session, 3)

    def test_evidence_must_be_in_run_exact_png_pixels_and_unchanged_after_acceptance(self):
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as other:
            board, session = fixture(folder)
            path = write_scene(other, 'outside.png', board)
            with self.assertRaises(AutomationError): evidence_ref(board, path, folder)
            path = write_scene(folder, 'wrong.png', board)
            altered = clone(board); altered.image[0, 0] = 255
            with self.assertRaises(AutomationError): evidence_ref(altered, path, folder)
            arrive(folder, board, session)
            path = Path(session[KEY]['arrival_frames'][0]['evidence']['path'])
            Image.new('RGB', (10, 10)).save(path)
            with self.assertRaises(AutomationError): validate_origin(session, require_accepted=True)

    def test_complete_native_role_inspection_is_post_choice_only_even_when_declared_unit_matches(self):
        with tempfile.TemporaryDirectory() as folder:
            board, session = fixture(folder)
            arrive(folder, board, session)
            collect_role(folder, board, session)
            board.captured_at = time.monotonic()
            result = capture_current(session, board, evidence=write_scene(folder, 'current.png', board), run_dir=folder, epoch=0)
            self.assertTrue(result['roster_complete'])
            self.assertEqual(result['baseline_scope'], 'post_choice')
            self.assertEqual((result['snapshot']['roster'][0]['star'], result['snapshot']['roster'][0]['tier']), (2, 2))
            self.assertEqual(len(result['cells']), 19)
            self.assertEqual(len(result['inventory_cells']), 14)
            self.assertTrue(result['inventory_complete'])
            self.assertFalse(result['delivery_verified'])
            self.assertFalse(session[KEY]['declared_obligations'][0]['delivery_verified'])
            durable = json.loads(json.dumps(session, ensure_ascii=False, allow_nan=False))
            self.assertEqual(durable[KEY], session[KEY])
            self.assertEqual(validate_origin(durable, require_accepted=True), session[KEY])
            original = deepcopy(result)
            session['actions'].append(dict(id=len(session['actions']), action='buy_standard_offer', status='pending', input_epoch=0))
            self.assertEqual(capture_current(session, board, evidence='not-read.png', run_dir=folder, epoch=0), original)
            self.assertEqual(session['actions'][-1]['status'], 'pending')

    def test_unknown_stock_is_preserved_and_first_partial_observation_cannot_be_upgraded(self):
        with tempfile.TemporaryDirectory() as folder:
            board, session = fixture(folder, empty=True)
            arrive(folder, board, session)
            area = board.image[300:360, 2320:2380]
            area[:] = np.random.default_rng(184).integers(0, 256, area.shape, dtype=np.uint8)
            board.captured_at = time.monotonic()
            value = capture_current(session, board, evidence=write_scene(folder, 'unknown-stock.png', board), run_dir=folder, epoch=0)
            self.assertFalse(value['inventory_complete'])
            self.assertEqual(value['status'], 'partial')
            self.assertTrue(any(c['name'] is None and c['textured'] for c in value['inventory_cells']))
            board.image[300:360, 2320:2380] = (80, 35, 25)
            self.assertEqual(capture_current(session, board, evidence='unused.png', run_dir=folder, epoch=0), value)

    def test_missing_close_legacy_identity_never_becomes_first_current_source(self):
        with tempfile.TemporaryDirectory() as folder:
            board, session = fixture(folder)
            arrive(folder, board, session)
            with self.assertRaises(AutomationError):
                capture_current(session, board, evidence=write_scene(folder, 'legacy.png', board), run_dir=folder, epoch=0)
            self.assertIsNone(session[KEY]['post_choice_observation'])
            session['collection']['complete'] = False
            self.assertIsNone(capture_current(session, board, evidence='not-read.png', run_dir=folder, epoch=0))

    def test_old_missing_initial_record_is_not_backfilled_and_existing_failure_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            board, session = fixture(folder)
            self.assertIsNone(capture_current(session, board, evidence='unused.png', run_dir=folder, epoch=0))
            begin(session, 3, run_dir=folder, epoch=0)
            session['actions'][3]['status'] = 'unknown'
            original = deepcopy(session)
            with self.assertRaises(AutomationError): begin(session, 3, run_dir=folder, epoch=0)
            with self.assertRaises(AutomationError): accepted(session, 3)
            self.assertEqual(session, original)

    def test_verified_flag_without_second_capture_pixels_cannot_accept(self):
        with tempfile.TemporaryDirectory() as folder:
            board, session = fixture(folder)
            begin(session, 3, run_dir=folder, epoch=0)
            for name in ('first.png', 'second.png'):
                current = clone(board)
                record_arrival(session, current, evidence=write_scene(folder, name, current), run_dir=folder, epoch=0)
            bad = clone(board); bad.image[0, 0] = 255
            session['actions'][3].update(status='verified', after=str(write_scene(folder, 'different-after.png', bad)))
            frozen = deepcopy(session[KEY])
            with self.assertRaises(AutomationError): accepted(session, 3)
            self.assertEqual(session[KEY], frozen)
            self.assertFalse(session[KEY]['selection_accepted'])

    def test_initial_prefix_and_collector_evidence_are_immutable_after_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            board, session = fixture(folder)
            arrive(folder, board, session)
            collect_role(folder, board, session)
            board.captured_at = time.monotonic()
            capture_current(session, board, evidence=write_scene(folder, 'current.png', board), run_dir=folder, epoch=0)
            frozen = deepcopy(session[KEY])
            session['actions'][4]['target'][1] = 2
            with self.assertRaises(AutomationError): validate_origin(session, require_accepted=True)
            self.assertEqual(session[KEY], frozen)
        with tempfile.TemporaryDirectory() as folder:
            _, session = fixture(folder)
            begin(session, 3, run_dir=folder, epoch=0)
            session['actions'][1]['after'] = session['actions'][1]['after']+'.altered'
            with self.assertRaises(AutomationError): validate_origin(session)

    def test_stale_capture_and_unresolved_payment_do_not_create_a_current_baseline(self):
        with tempfile.TemporaryDirectory() as folder:
            board, session = fixture(folder, empty=True)
            begin(session, 3, run_dir=folder, epoch=0)
            board.captured_at = 0
            with self.assertRaises(AutomationError):
                record_arrival(session, board, evidence='not-read.png', run_dir=folder, epoch=0)
            self.assertEqual(session[KEY]['arrival_frames'], [])
            board.captured_at = time.monotonic()
            arrive(folder, board, session)
            session['actions'].append(dict(id=4, action='buy_standard_offer', status='pending', input_epoch=0))
            frozen = deepcopy(session)
            with self.assertRaises(AutomationError):
                capture_current(session, board, evidence='not-read.png', run_dir=folder, epoch=0)
            self.assertEqual(session, frozen)


if __name__ == '__main__':
    unittest.main()
