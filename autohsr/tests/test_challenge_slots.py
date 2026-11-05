"""Synthetic slot calibration with original portraits and a real wrong-page negative."""
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr import challenge_pages as pages, challenge_roster as portraits, challenge_slots as slots
from autohsr.challenge_plan import from_values
from autohsr.models import Scene, Token
from autohsr.tests.test_challenge_modes import apocalypse_setup, fiction_setup
from autohsr.tests.test_challenge_pages import setup_scene, token


_MOCK_TEAMS = (('Firefly', 'RuanMei', 'Fugue', 'Lingsha'), ('Acheron', 'Jiaoqiu', 'Pela', 'Aventurine'))
_SLOTS = tuple(tuple((x, y, x + 135, y + 135) for x in (855, 1010, 1165, 1320)) for y in (608, 815))


def _layout(mode='memory_of_chaos'):
    marker = np.full((31, 35, 3), 12, np.uint8)
    cv2.rectangle(marker, (3, 4), (31, 26), (134, 190, 172), 2)
    cv2.circle(marker, (17, 14), 6, (57, 98, 230), -1)
    origins = {'memory_of_chaos': ((650, 570), (650, 790)),
               'pure_fiction': ((650, 572), (650, 790)),
               'apocalyptic_shadow': ((990, 270), (995, 537))}[mode]
    offsets = tuple(tuple(((left - x) / 1920, (top - y) / 1080, (right - x) / 1920, (bottom - y) / 1080)
                          for left, top, right, bottom in row) for row, (x, y) in zip(_SLOTS, origins))
    return slots._SlotLayout('synthetic_eight_slots', offsets, marker)


def _put(image, bitmap, x, y):
    height, width = bitmap.shape[:2]
    image[y:y + height, x:x + width] = bitmap


class ChallengeSlotTests(unittest.TestCase):
    def setUp(self):
        self.now = 1000.
        clock = SimpleNamespace(monotonic=lambda: self.now)
        self.enterContext(patch.object(pages, 'time', clock))
        self.enterContext(patch.object(portraits, 'time', clock))
        self.layout = _layout()
        self.originals = {name: bitmap for name, bitmap, _ in portraits._references()}

    def plan(self, mode='memory_of_chaos', teams=_MOCK_TEAMS):
        return from_values(mode, [2, 4], *teams)

    def scene(self, mode, stamp, teams=_MOCK_TEAMS, *, level=2, uid='100000001', node=1):
        if mode == 'apocalyptic_shadow':
            scene = apocalypse_setup()
            # This is only consumed by the fake independent node/level read.
            scene.tokens.append(token(f'测试当前节点{node}第{level}层', (915, 94, 1180, 115)))
        else:
            builder = setup_scene if mode == 'memory_of_chaos' else fiction_setup
            scene = builder(level)
        for row, members in zip(_SLOTS, teams):
            for box, asset in zip(row, members):
                if asset is not None:
                    marker = self.layout.empty_marker if asset == 'empty' else self.originals[asset]
                    _put(scene.image, marker, box[0] + 8, box[1] + 8)
        if uid is not None:
            scene.tokens.append(token(f'UID:{uid}', (15, 1035, 200, 1060)))
        scene.captured_at = stamp
        return scene

    def capture(self, plan, scene, ordinal, epoch=4):
        return slots.RosterCapture(scene, epoch, ordinal, plan.digest)

    def compare(self, plan, first, second, **kwargs):
        layout = self.layout if plan.mode == 'memory_of_chaos' else _layout(plan.mode)
        with patch.object(slots, '_SLOT_LAYOUTS', {plan.mode: layout}):
            return slots.compare_roster_frames(plan, self.capture(plan, first, 21),
                                               self.capture(plan, second, 22), **kwargs)

    def pair(self, plan, teams=_MOCK_TEAMS):
        return [self.scene(plan.mode, stamp, teams) for stamp in (self.now - .2, self.now - .1)]

    def test_two_fresh_captures_compare_eight_exact_slots_for_chaos_and_fiction(self):
        for mode in ('memory_of_chaos', 'pure_fiction'):
            with self.subTest(mode=mode):
                plan = self.plan(mode)
                first, second = self.pair(plan)
                self.assertTrue(np.array_equal(first.image, second.image))
                value = self.compare(plan, first, second)
                self.assertEqual(value['status'], 'compared')
                self.assertIs(value['eight_slots_occupied'], True)
                self.assertIs(value['eight_identities_known'], True)
                self.assertIs(value['team_members_match'], True)
                self.assertIs(value['slot_order_match'], True)
                self.assertIs(value['duplicate_unit'], False)
                self.assertEqual(value['availability'], 'unknown')
                self.assertFalse(value['execution_supported'])
                self.assertEqual([[slot['asset_id'] for slot in team] for team in value['teams']],
                                 [list(team) for team in plan.teams])
                self.assertTrue(all(len(slot['evidence']) == 2 for team in value['teams'] for slot in team))
                exported = json.dumps(value, allow_nan=False)
                self.assertNotIn('100000001', exported)
                self.assertNotIn('account_key', exported)

    def test_order_membership_and_confirmed_unit_duplicates_are_distinct(self):
        plan = self.plan()
        left, right = _MOCK_TEAMS
        swapped = ((left[1], left[0], *left[2:]), right)
        value = self.compare(plan, *self.pair(plan, swapped))
        self.assertIs(value['team_members_match'], True)
        self.assertIs(value['slot_order_match'], False)
        swapped_teams = ((right[0], *left[1:]), (left[0], *right[1:]))
        self.assertIs(self.compare(plan, *self.pair(plan, swapped_teams))['team_members_match'], False)
        outfit = (('FireflySpringMissive', *left[1:]), right)
        different_exact = self.compare(plan, *self.pair(plan, outfit))
        self.assertEqual(different_exact['teams'][0][0]['asset_id'], 'FireflySpringMissive')
        self.assertIs(different_exact['team_members_match'], False)
        duplicate = (left, ('FireflySpringMissive', *right[1:]))
        value = self.compare(plan, *self.pair(plan, duplicate))
        self.assertIs(value['eight_slots_occupied'], True)
        self.assertIs(value['duplicate_unit'], True)
        self.assertIs(value['team_members_match'], False)

    def test_explicit_empty_and_unread_slot_do_not_collapse_into_the_same_state(self):
        plan = self.plan()
        left, right = _MOCK_TEAMS
        empty = self.compare(plan, *self.pair(plan, (('empty', *left[1:]), right)))
        self.assertEqual(empty['teams'][0][0]['occupancy'], 'empty')
        self.assertIs(empty['eight_slots_occupied'], False)
        self.assertIs(empty['team_members_match'], False)
        unread = self.compare(plan, *self.pair(plan, ((None, *left[1:]), right)))
        self.assertEqual(unread['teams'][0][0]['occupancy'], 'unknown')
        self.assertIsNone(unread['eight_slots_occupied'])
        self.assertIsNone(unread['team_members_match'])
        self.assertIsNone(unread['duplicate_unit'])

    def test_two_partial_or_moving_teams_do_not_combine_into_eight_identities(self):
        plan = self.plan()
        left, right = _MOCK_TEAMS
        first = self.scene(plan.mode, self.now - .2, ((None, *left[1:]), right))
        second = self.scene(plan.mode, self.now - .1, ((left[0], None, *left[2:]), right))
        value = self.compare(plan, first, second)
        self.assertIsNone(value['eight_slots_occupied'])
        self.assertEqual([slot['occupancy'] for slot in value['teams'][0][:2]], ['unknown', 'unknown'])
        first, second = self.pair(plan)
        second = self.scene(plan.mode, second.captured_at, (('FireflySpringMissive', *left[1:]), right))
        value = self.compare(plan, first, second)
        self.assertIs(value['eight_slots_occupied'], True)
        self.assertIsNone(value['eight_identities_known'])
        self.assertIsNone(value['team_members_match'])

    def test_shared_short_name_and_competing_form_are_never_exact_identity(self):
        left, right = _MOCK_TEAMS
        planned = (('March7th', *left[1:]), right)
        plan = self.plan(teams=planned)
        first, second = self.pair(plan, ((None, *left[1:]), right))
        for scene in (first, second):
            scene.tokens.append(token('三月七', (865, 614, 910, 635)))
        self.assertIsNone(self.compare(plan, first, second)['teams'][0][0]['asset_id'])

        first, second = self.pair(plan, planned)
        bank = portraits._scaled_references(1920)
        exact = next(item for item in bank if item[0] == 'March7th')
        rival = ('March7thImaginary', *exact[1:])
        with patch.object(portraits, '_scaled_references', return_value=(*bank, rival)):
            ambiguous = self.compare(plan, first, second)
        self.assertEqual(ambiguous['teams'][0][0]['identity_status'], 'ambiguous')
        self.assertEqual(ambiguous['teams'][0][0]['alternatives'], ['March7th', 'March7thImaginary'])
        self.assertIs(ambiguous['eight_slots_occupied'], True)
        self.assertIsNone(ambiguous['team_members_match'])

    def test_changed_missing_or_conflicting_account_cannot_match_the_same_pixels(self):
        plan = self.plan()
        first = self.pair(plan)[0]
        for uid in ('100000002', None, '100000001'):
            with self.subTest(uid=uid):
                second = self.scene(plan.mode, self.now - .1, uid=uid)
                if uid == '100000001':
                    second.tokens.append(token('UID:100000003', (15, 1035, 200, 1060), score=.80))
                value = self.compare(plan, first, second)
                self.assertEqual(value['reason'], 'unverified_or_changed_account')
                self.assertIsNone(value['team_members_match'])

    def test_capture_pair_requires_distinct_ordered_frames_and_the_frozen_plan(self):
        plan = self.plan()
        first, second = (self.capture(plan, scene, ordinal)
                         for ordinal, scene in enumerate(self.pair(plan), 21))
        for invalid in (replace(second, scene=first.scene), replace(second, ordinal=23),
                        replace(second, input_epoch=5), replace(second, plan_digest='other-plan'),
                        replace(second, plan_digest=np.array(['not', 'a digest']))):
            value = slots.compare_roster_frames(plan, first, invalid)
            self.assertEqual(value['reason'], 'invalid_capture_pair_or_plan')
        second.scene.captured_at = first.scene.captured_at
        self.assertEqual(slots.compare_roster_frames(plan, first, second)['reason'],
                         'invalid_capture_pair_or_plan')
        second.scene.captured_at += .1
        second.scene.image = first.scene.image
        self.assertEqual(self.compare(plan, first.scene, second.scene)['reason'], 'reused_capture_buffer')

    def test_wrong_mode_and_level_are_ineligible_before_slot_matching(self):
        plan = self.plan('pure_fiction')
        first = self.pair(plan)[0]
        for mode, level in (('memory_of_chaos', 2), ('pure_fiction', 3), ('pure_fiction', None)):
            second = self.scene(mode, self.now - .1, level=level)
            with patch.object(slots, '_read_slot', side_effect=AssertionError('invalid page reached slots')):
                value = self.compare(plan, first, second)
            self.assertEqual(value['reason'], 'wrong_mode_or_level')

    def test_slot_offsets_follow_their_header_but_cannot_pair_shifted_geometry(self):
        plan = self.plan()
        first, second = self.pair(plan)

        def shift_top_row(scene):
            strip = scene.image[560:760, 630:1480].copy()
            scene.image[560:760, 630:1480] = 12
            _put(scene.image, strip, 662, 560)

        shift_top_row(second)
        self.assertEqual(self.compare(plan, first, second)['reason'], 'changed_slot_geometry')
        shift_top_row(first)
        value = self.compare(plan, first, second)
        self.assertIs(value['slot_order_match'], True)
        self.assertAlmostEqual(value['teams'][0][0]['box'][0], (855 + 32) / 1920)

    def test_apocalyptic_requires_an_independently_read_expected_node_on_both_frames(self):
        plan = self.plan('apocalyptic_shadow')
        first, second = self.pair(plan)
        real_observe = pages.observe

        def fixture_observe(scene, confidence):
            page = real_observe(scene, confidence)
            self.assertEqual(page.kind, 'node_setup')
            marker = next((item.text for item in scene.tokens if item.text.startswith('测试当前节点')), None)
            return replace(page, level=2, basis=dict(page.basis, selected_node=int(marker[6]) if marker else None))

        self.assertIsNone(self.compare(plan, first, second, expected_node=1)['team_members_match'])
        with patch.object(pages, 'observe', side_effect=fixture_observe):
            self.assertIs(self.compare(plan, first, second, expected_node=1)['team_members_match'], True)
            self.assertEqual(self.compare(plan, first, second, expected_node=2)['reason'], 'wrong_or_unverified_node')
            changed = self.scene(plan.mode, self.now - .1, node=2)
            self.assertEqual(self.compare(plan, first, changed, expected_node=1)['reason'], 'wrong_or_unverified_node')
            changed.tokens.pop(-2)
            self.assertEqual(self.compare(plan, first, changed, expected_node=1)['reason'], 'wrong_or_unverified_node')

    def test_roster_pair_fails_closed_on_layout_overlap_and_mid_scan_account_change(self):
        plan = self.plan()
        first, second = self.pair(plan)
        read_slot = slots._read_slot
        good_layout = self.layout
        left, right = self.layout.offsets
        self.layout = replace(self.layout, offsets=((left[1], *left[1:]), right))
        self.assertEqual(self.compare(plan, first, second)['reason'], 'unverified_slot_sources')
        self.layout = good_layout

        def read_and_change(*args):
            for scene in (first, second):
                scene.tokens[-1] = token('UID:100000004', (15, 1035, 200, 1060))
            return read_slot(*args)

        with patch.object(slots, '_read_slot', side_effect=read_and_change):
            self.assertEqual(self.compare(plan, first, second)['reason'], 'capture_pair_changed_during_scan')

    def test_changed_slot_pixels_or_page_scope_during_scan_do_not_create_a_receipt(self):
        plan = self.plan()
        read_slot = slots._read_slot
        for change in ('pixels', 'layer'):
            with self.subTest(change=change):
                first, second = self.pair(plan)

                def read_and_change(*args):
                    if change == 'pixels':
                        first.image[0, 0] = 0
                    else:
                        first.tokens[1] = token('第03层', (820, 160, 940, 190))
                    return read_slot(*args)

                with patch.object(slots, '_read_slot', side_effect=read_and_change):
                    value = self.compare(plan, first, second)
                self.assertEqual(value['reason'], 'capture_pair_changed_during_scan')
                self.assertIsNone(value['team_members_match'])

    def test_runtime_observation_without_layout_exposes_only_list_candidates(self):
        for mode in ('memory_of_chaos', 'pure_fiction', 'apocalyptic_shadow'):
            with self.subTest(mode=mode):
                scene = self.scene(mode, self.now - .2)
                _put(scene.image, self.originals['Acheron'], 80, 180)
                value = slots.observe_setup_roster(scene)
                self.assertEqual(value['mode'], mode)
                self.assertEqual([item['asset_id'] for item in value['candidate_list']['candidates']], ['Acheron'])
                self.assertEqual(value['candidate_list']['availability'], 'unknown')
                self.assertEqual(value['team_slots']['reason'], 'missing_slot_calibration')
                self.assertIsNone(value['team_slots']['team_members_match'])
                self.assertTrue(all(item['occupancy'] == 'unknown'
                                    for team in value['team_slots']['teams'] for item in team))

    def test_real_redacted_planar_preset_does_not_supply_high_difficulty_candidates(self):
        fixture = Path(__file__).parent / 'fixtures/du_runtime/planar_preset_enabled'
        meta = json.loads(fixture.with_suffix('.json').read_text(encoding='utf-8'))
        raw = fixture.with_suffix('.png').read_bytes()
        self.assertTrue(meta['masked_identifiers'])
        scene = Scene([Token(**row) for row in meta['tokens']],
                      cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR), captured_at=self.now)
        with patch.object(portraits, 'observe_candidates', side_effect=AssertionError('wrong page')):
            value = slots.observe_setup_roster(scene)
        self.assertIsNone(value['candidate_list'])
        self.assertEqual(value['team_slots']['reason'], 'unverified_setup_page')
