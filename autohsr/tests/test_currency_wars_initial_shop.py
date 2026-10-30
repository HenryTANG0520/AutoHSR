"""Offline initial free-return contracts with old OCR fields and synthetic PNGs.

Only temporary synthetic evidence and invented account identifiers are used;
no Runner, Context, CLI, game input or execution marker is constructed.
"""
from copy import deepcopy
import json
from pathlib import Path
import re
import tempfile
import time
import unittest

import numpy as np
from PIL import Image

from autohsr.currency_wars_environment import ENVIRONMENT_POLICY, parse_environment_effect
from autohsr.currency_wars_identity import account_key
from autohsr.currency_wars_initial import accepted, begin, capture_current, record_arrival, validate_origin
from autohsr.currency_wars_initial_shop import (EXPECTED, INTENT, bind_intent, closed, feedback, proposal)
from autohsr.models import AutomationError, Scene, Token

FIXTURE = Path(__file__).parent / 'fixtures' / 'currency_wars_pages.json'
EFFECT = '获得1个随机2星2费角色，进入新节点时，这位角色永久获得随机属性加成。'
_LAST_CAPTURE = 0.


def frame(page='shop', *, gold=5, level=3, experience=(0, 6), hp=80, node='1-1', uid='100000001'):
    global _LAST_CAPTURE
    value = json.loads(FIXTURE.read_text(encoding='utf8'))['pages'][page]
    tokens = [Token(item['text'], item['score'], tuple(item['box'])) for item in value['tokens']]
    # Replace only each independent HUD field. Fixture page anchors stay intact.
    tokens = [token for token in tokens if not any(token.within(roi) for roi in
              ((.851, .829, .87, .868), (.125, .815, .185, .87), (.13, .865, .18, .9), (.735, .05, .78, .095)))]
    tokens = [Token(node, token.score, token.box) if re.fullmatch(r'[1-3]-[1-9][0-9]?', token.text) else token
              for token in tokens]
    if gold is not None:
        tokens.append(Token(str(gold), .99, (.852, .833, .869, .867)))
    if level is not None:
        tokens.append(Token('Lv.' + str(level), .99, (.14, .82, .18, .86)))
    if experience is not None:
        tokens.append(Token(str(experience[0]) + '/' + str(experience[1]), .99, (.14, .87, .17, .89)))
    if hp is not None and page == 'preparation':
        tokens.append(Token(str(hp), .99, (.74, .06, .77, .085)))
    tokens.append(Token('UID:' + uid, .99, (.01, .96, .15, .99)))
    # Synthetic captures remain fresh but distinct even on a coarse Windows
    # monotonic clock; this does not manufacture a second runtime observation.
    _LAST_CAPTURE = max(time.monotonic() - 1, _LAST_CAPTURE + .000001)
    return Scene(tokens, np.full((540, 960, 3), 80 if page == 'shop' else 40, np.uint8),
                 captured_at=_LAST_CAPTURE)


class InitialShopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.counter = 0

    def evidence(self, scene, name='frame'):
        self.counter += 1
        path = self.root / (str(self.counter) + '-' + name + '.png')
        Image.fromarray(scene.image[:, :, ::-1]).save(path)
        return str(path)

    def session(self, pages=('shop', 'shop'), *, experience=(0, 6)):
        source = frame()
        run_dir, epoch = str(self.root.resolve()), 4
        before_path = self.evidence(source, 'environment')
        kind, params, score, _ = parse_environment_effect(EFFECT)
        actions = [dict(id=index, action=name, status='verified', input_epoch=epoch,
                        before=before_path, after=before_path, target=[])
                   for index, name in enumerate(('start_standard_a8_40', 'advance_standard_preview', 'advance_standard_plane'))]
        actions.append(dict(id=3, action='confirm_standard_environment_1', status='pending', input_epoch=epoch,
                            expected='initial_board', target=[], before=before_path,
                            decision=dict(name='战力飙升', effect=EFFECT, kind=kind, parameters=dict(params),
                                          score=score, policy=ENVIRONMENT_POLICY)))
        session = dict(status='active', start_verified=True, mode='standard_development', rank=8, wealth=40,
            match_id='1' * 32, account_key=account_key(source), account_verified_run=run_dir,
            account_verified_epoch=epoch, entry=dict(rank_verified=True), rules_version='4.6',
            client=dict(version='4.6', verified_run=run_dir, input_epoch=epoch), actions=actions)
        begin(session, 3, run_dir=run_dir, epoch=epoch)
        for page in pages:
            scene = frame(page, experience=experience)
            path = self.evidence(scene, 'arrival')
            record_arrival(session, scene, evidence=path, run_dir=run_dir, epoch=epoch)
        actions[-1].update(status='verified', after=path)
        accepted(session, 3)
        return session

    def pending(self, session, before):
        choice = proposal(before, session)
        session['actions'].append(dict(id=len(session['actions']), action=choice.intent, expected=choice.expected,
            status='pending', input_epoch=session['initial_environment']['epoch'],
            before=self.evidence(before, 'before-close'), target=deepcopy(list(choice.payload))))
        bind_intent(session, choice, before)
        return choice

    def returns(self, session, choice, before):
        frames = [frame('preparation'), frame('preparation')]
        paths = [self.evidence(scene, 'after-close') for scene in frames]
        session['actions'][-1].update(status='verified', after=paths[-1])
        return frames, paths

    def test_direct_initial_shop_has_dedicated_free_intent_and_current_hud(self):
        session, scene = self.session(), frame()
        before = deepcopy(session)
        choice = proposal(scene, session)
        self.assertEqual((choice.intent, choice.expected), (INTENT, EXPECTED))
        self.assertEqual(choice.payload[:2], ('1-1', 3))
        self.assertEqual(choice.payload[6], dict(node='1-1', gold=5, level=3, hp=None, experience=[0, 6], deployment=None))
        self.assertEqual(choice.payload[7]['captured_at'], scene.captured_at)
        self.assertEqual(session, before)
        self.assertNotIn('pre_shop_snapshot', session)
        self.assertNotIn('shop_observed_nodes', session)

    def test_preparation_to_shop_animation_keeps_same_confirmation_source(self):
        session = self.session(('preparation', 'shop'))
        self.assertEqual(proposal(frame(), session).intent, INTENT)

    def test_current_shop_can_follow_accepted_preparation_without_any_middle_action(self):
        session = self.session(('preparation', 'preparation'))
        self.assertEqual(proposal(frame(), session).intent, INTENT)

    def test_observed_direct_preparation_does_not_capture_a_later_normal_shop(self):
        from autohsr.tests.test_currency_wars_initial import fixture, arrive, clone, shop_scene, write_scene
        from autohsr.currency_wars_standard_market import close_standard_shop
        board, session = fixture(self.root, empty=True)
        arrive(self.root, board, session)
        current = clone(board)
        observation = capture_current(session, current, evidence=write_scene(self.root, 'observed.png', current),
                                      run_dir=self.root, epoch=0)
        self.assertIsNotNone(observation)
        later = shop_scene(board)
        session['actions'].append(dict(id=4, action='open_standard_shop', expected='standard_shop_observe',
            input_epoch=0, status='verified', before=str(self.root / 'observed.png'),
            after=str(write_scene(self.root, 'normal-shop.png', later)), target=[]))
        before = deepcopy(session)
        self.assertIsNone(proposal(later, session))
        self.assertEqual(session, before)
        self.assertNotIn('initial_shop_return', session)
        self.assertNotIn('pre_shop_snapshot', session)
        with self.assertRaises(AutomationError):
            close_standard_shop(later, session)  # Normal shop still needs its own complete source.
        session['initial_environment']['post_choice_observation']['digest'] = '0' * 64
        with self.assertRaises(AutomationError):
            proposal(later, session)

    def test_hidden_optional_hud_stays_unknown_without_zero_filling(self):
        session = self.session(experience=None)
        before = frame(experience=None)
        choice = self.pending(session, before)
        self.assertIsNone(choice.payload[6]['experience'])
        self.assertIsNone(choice.payload[6]['hp'])
        self.assertIsNone(choice.payload[6]['deployment'])
        self.assertTrue(feedback(choice, frame('preparation', experience=(2, 6), hp=73), session, before=before))

    def test_missing_gold_or_level_blocks_even_if_original_values_are_cached(self):
        session = self.session()
        for scene in (frame(gold=None), frame(level=None)):
            with self.subTest(text=scene.text), self.assertRaises(AutomationError):
                proposal(scene, session)

    def test_wrong_account_node_epoch_or_run_cannot_borrow_initial_source(self):
        original = self.session()
        for name in ('account', 'node', 'epoch', 'run'):
            session, scene = deepcopy(original), frame()
            if name == 'account':
                scene = frame(uid='100000002')
            elif name == 'node':
                scene = frame(node='1-2')
            elif name == 'epoch':
                session['account_verified_epoch'] += 1
                session['client']['input_epoch'] += 1
            else:
                session['account_verified_run'] = 'another-synthetic-run'
            with self.subTest(name=name), self.assertRaises(AutomationError):
                proposal(scene, session)

    def test_boolean_zero_epoch_is_not_current_input_generation(self):
        from autohsr.tests.test_currency_wars_initial import fixture, arrive, shop_scene
        board, session = fixture(self.root, empty=True)
        arrive(self.root, board, session, mixed=True)
        scene = shop_scene(board)
        session['account_verified_epoch'] = False
        session['client']['input_epoch'] = False
        with self.assertRaises(AutomationError):
            proposal(scene, session)

    def test_old_scene_or_missing_image_never_authorizes_close(self):
        session = self.session()
        stale, no_image = frame(), frame()
        stale.captured_at -= 20
        no_image.image = None
        for scene in (stale, no_image):
            with self.assertRaises(AutomationError):
                proposal(scene, session)

    def test_close_control_must_be_unique_trusted_and_in_current_roi(self):
        session = self.session()
        for name in ('missing', 'duplicate', 'low_confidence', 'elsewhere'):
            scene = frame()
            controls = [token for token in scene.tokens if token.text == '收起']
            scene.tokens = [token for token in scene.tokens if token.text != '收起']
            if name == 'duplicate':
                scene.tokens += controls * 2
            elif name == 'low_confidence':
                scene.tokens.append(Token('收起', .2, controls[0].box))
            elif name == 'elsewhere':
                scene.tokens.append(Token('收起', .99, (.1, .4, .2, .45)))
            with self.subTest(name=name), self.assertRaises(AutomationError):
                proposal(scene, session)

    def test_unaccepted_old_or_incomplete_origin_is_not_synthesized(self):
        session = self.session()
        self.assertIsNone(proposal(frame(), dict(session, initial_environment=None)))
        for mutate in ('accepted', 'frames', 'origin'):
            broken = deepcopy(session)
            if mutate == 'accepted':
                broken['initial_environment']['selection_accepted'] = False
            elif mutate == 'frames':
                broken['initial_environment']['arrival_frames'].pop()
            else:
                broken['initial_environment']['origin']['action_digest'] = '0' * 64
            with self.subTest(mutate=mutate), self.assertRaises(AutomationError):
                proposal(frame(), broken)

    def test_intermediate_trade_or_arrival_action_is_not_a_free_initial_source(self):
        original = self.session()
        for name in ('buy_standard_offer', 'open_standard_shop', 'continue_standard_node', 'inspect_standard_unit'):
            session = deepcopy(original)
            session['actions'].append(dict(id=4, action=name, status='verified', input_epoch=4, target=[]))
            with self.subTest(name=name), self.assertRaises(AutomationError):
                proposal(frame(), session)

    def test_bind_is_once_only_and_only_context_can_rederive_exact_immediate_pending(self):
        session, before = self.session(), frame()
        choice = self.pending(session, before)
        snapshot = deepcopy(session['initial_shop_return'])
        with self.assertRaises(AutomationError):
            bind_intent(session, choice, before)
        with self.assertRaises(AutomationError):
            proposal(before, session)
        pending = session['actions'][-1]
        projected = dict(session, actions=session['actions'][:-1], rederiving_action=pending)
        self.assertEqual(proposal(before, projected), choice)
        self.assertEqual(session['initial_shop_return'], snapshot)
        changed = deepcopy(before); changed.image[30:40, 30:40] = 120
        with self.assertRaises(AutomationError):
            proposal(changed, projected)

    def test_unknown_pending_and_epoch_change_never_replay_or_rebind(self):
        session, before = self.session(), frame()
        choice = self.pending(session, before)
        session['actions'][-1]['status'] = 'unknown'
        projected = dict(session, actions=session['actions'][:-1], rederiving_action=session['actions'][-1])
        with self.assertRaises(AutomationError):
            proposal(before, projected)
        self.assertFalse(feedback(choice, frame('preparation'), session, before=before))
        session['actions'][-1]['status'] = 'pending'
        session['account_verified_epoch'] += 1
        self.assertFalse(feedback(choice, frame('preparation'), session, before=before))

    def test_feedback_checks_page_node_account_required_hud_and_known_experience(self):
        session, before = self.session(), frame()
        choice = self.pending(session, before)
        self.assertTrue(feedback(choice, frame('preparation'), session, before=before))
        invalid = [frame(), frame('preparation', node='1-2'), frame('preparation', uid='100000002'),
                   frame('preparation', gold=None), frame('preparation', level=None),
                   frame('preparation', gold=6), frame('preparation', level=4),
                   frame('preparation', experience=(1, 6))]
        for scene in invalid:
            with self.subTest(text=scene.text):
                self.assertFalse(feedback(choice, scene, session, before=before))

    def test_full_two_frame_return_keeps_initial_gift_unattributed_and_no_trade_source(self):
        session, before = self.session(('preparation', 'shop')), frame()
        choice = self.pending(session, before)
        original_initial = deepcopy(session['initial_environment'])
        frames, paths = self.returns(session, choice, before)
        receipt = closed(session, choice, before, frames, paths)
        self.assertTrue(receipt['free_view_only'])
        self.assertFalse(receipt['trade_authorized'])
        self.assertFalse(receipt['delivery_attributed'])
        self.assertNotIn('hp', receipt['known_fields_unchanged'])
        self.assertEqual(session['initial_shop_return']['status'], 'verified')
        self.assertEqual(session['actions'][-1]['initial_shop_return_receipt'], receipt)
        self.assertEqual(session['initial_environment'], original_initial)
        self.assertEqual(validate_origin(session, require_accepted=True)['declared_obligations'][0]['status'], 'unattributed')
        self.assertNotIn('pre_shop_snapshot', session)
        self.assertNotIn('shop_observed_nodes', session)
        self.assertIsNone(proposal(frame(), session))
        with self.assertRaises(AutomationError):
            closed(session, choice, before, frames, paths)

    def test_closed_requires_verified_action_two_independent_frames_and_files(self):
        for case in ('pending', 'one_frame', 'same_capture', 'same_file', 'hud_conflict', 'wrong_after'):
            session, before = self.session(), frame()
            choice = self.pending(session, before)
            frames, paths = self.returns(session, choice, before)
            if case == 'pending':
                session['actions'][-1]['status'] = 'pending'
            elif case == 'one_frame':
                frames, paths = frames[:1], paths[:1]
            elif case == 'same_capture':
                frames[1].captured_at = frames[0].captured_at
            elif case == 'same_file':
                paths[1] = paths[0]
            elif case == 'hud_conflict':
                frames[1] = frame('preparation', hp=81)
                paths[1] = self.evidence(frames[1])
                session['actions'][-1]['after'] = paths[1]
            else:
                session['actions'][-1]['after'] = session['actions'][-1]['before']
            old = deepcopy(session['initial_shop_return'])
            with self.subTest(case=case), self.assertRaises(AutomationError):
                closed(session, choice, before, frames, paths)
            self.assertEqual(session['initial_shop_return'], old)

    def test_original_or_return_evidence_tamper_preserves_pending_record(self):
        session, before = self.session(), frame()
        choice = self.pending(session, before)
        frames, paths = self.returns(session, choice, before)
        altered = deepcopy(frames[0]); altered.image[:] = 123
        Image.fromarray(altered.image[:, :, ::-1]).save(paths[0])
        old = deepcopy(session['initial_shop_return'])
        with self.assertRaises(AutomationError):
            closed(session, choice, before, frames, paths)
        self.assertEqual(session['initial_shop_return'], old)


if __name__ == '__main__':
    unittest.main()
