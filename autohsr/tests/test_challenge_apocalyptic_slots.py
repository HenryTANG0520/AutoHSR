"""Regular Apocalyptic Shadow slot receipts through the read-only CLI."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr.challenge_prepare import ChallengePreparation
from autohsr.challenge_roster import _references
from autohsr.tests.test_challenge_apocalyptic_prepare import APOCALYPTIC_PLAN, frame, text
from autohsr.tests.test_challenge_integration import prepare_with_fake_window


def circular_slots(*, empty=(), roster_only=False, pointer=False):
    scene = frame('node_setup', level='04')
    scene.tokens.append(text('角色详情', (.601, .899, .655, .929)))
    pixels = np.full((454, 802, 3), 32, np.uint8)
    images = {name: image for name, image, _ in _references()}
    mask = np.zeros((29, 29), np.uint8)
    cv2.circle(mask, (14, 14), 14, 1, -1)
    centers = (430, 467, 503, 539) if not roster_only else (42, 94, 146, 198)
    for row, (y, assets) in enumerate(zip((168, 287), (APOCALYPTIC_PLAN['team1'], APOCALYPTIC_PLAN['team2'])), 1):
        for position, (x, asset) in enumerate(zip(centers, assets), 1):
            cv2.circle(pixels, (x, y), 16, (171, 169, 170), 1, cv2.LINE_AA)
            if (row, position) in empty:
                head = np.array([(x, y - 7), (x + 3, y - 5), (x, y - 3), (x - 3, y - 5)])
                body = np.array([(x, y - 1), (x + 4, y + 2), (x, y + 7), (x - 4, y + 2)])
                cv2.fillConvexPoly(pixels, head, (148, 148, 148))
                cv2.fillConvexPoly(pixels, body, (148, 148, 148))
            else:
                portrait = cv2.resize(images[asset], (29, 29), interpolation=cv2.INTER_AREA)
                crop = pixels[y - 14:y + 15, x - 14:x + 15]
                crop[mask > 0] = portrait[mask > 0]
    if pointer:
        arrow = np.array([(531, 155), (548, 166), (542, 168), (547, 174),
                          (543, 178), (537, 171), (532, 176)])
        cv2.fillPoly(pixels, [arrow], (177, 229, 248), cv2.LINE_AA)
        cv2.fillConvexPoly(pixels, np.array([(534, 160), (542, 166), (535, 170)]), (20, 20, 20))
    scene.image = cv2.resize(pixels, (1920, 1080))
    return scene


class ApocalypticSlotReceiptTests(unittest.TestCase):
    def run_prepare(self, scenes, level=4):
        plan = dict(APOCALYPTIC_PLAN, levels=[level, 4])
        with tempfile.TemporaryDirectory() as folder:
            code, report, window = prepare_with_fake_window(Path(folder), scenes, plan=plan)
            challenge = report['challenge']
            saved = Path(report['run_dir']) / 'challenge-preparation.json'
            self.assertEqual(json.loads(saved.read_bytes()), challenge)
        for method in (window.focus, window.click, window.key, window.drag, window.send):
            method.assert_not_called()
        self.assertEqual(challenge['actions'], [])
        self.assertFalse(challenge['team_verified'])
        return code, challenge

    def test_eight_occupied_slots_do_not_imply_identity_or_selected_node(self):
        code, data = self.run_prepare([circular_slots(), circular_slots()])
        self.assertEqual(code, 0)
        self.assertTrue(data['preparation_page_verified'])
        slots = data['page_observation']['team_slots']
        self.assertEqual(slots['node_order'], [1, 2])
        self.assertIsNone(slots['selected_node'])
        self.assertIs(slots['eight_slots_occupied'], True)
        self.assertIsNone(slots['eight_identities_known'])
        self.assertIsNone(slots['team_members_match'])
        self.assertFalse(slots['execution_supported'])
        for row in slots['teams']:
            self.assertEqual([slot['position'] for slot in row], [1, 2, 3, 4])
            for slot in row:
                self.assertEqual((slot['occupancy'], slot['identity_status'], slot['asset_id']),
                                 ('occupied', 'unknown', None))
                self.assertEqual([item['source'] for item in slot['evidence']], ['circular_portrait'] * 2)

    def test_a_confirmed_empty_slot_and_an_inconsistent_pair_are_distinct(self):
        for persistent, expected in ((True, 'empty'), (False, 'unknown')):
            with self.subTest(persistent=persistent):
                empty = ((1, 4),)
                code, data = self.run_prepare([circular_slots(empty=empty),
                                               circular_slots(empty=empty if persistent else ())])
                slots = data['page_observation']['team_slots']
                self.assertEqual((code, slots['teams'][0][3]['occupancy']), (0, expected))
                self.assertIs(slots['eight_slots_occupied'], False if persistent else None)
                self.assertIs(slots['team_members_match'], False if persistent else None)
                if persistent:
                    evidence = slots['teams'][0][3]['evidence']
                    self.assertEqual([item['source'] for item in evidence], ['empty_slot_glyph'] * 2)

    def test_candidate_area_and_wrong_plan_cannot_substitute_for_team_slots(self):
        roster = circular_slots(roster_only=True)
        roster.tokens.append(text('队伍2', (.103, .525, .136, .550)))
        code, data = self.run_prepare([roster, roster])
        self.assertEqual(code, 0)
        self.assertEqual(data['page_observation']['team_slots']['status'], 'unknown')
        code, data = self.run_prepare([circular_slots(), circular_slots()], level=3)
        self.assertEqual(code, 1)
        self.assertNotIn('team_slots', data['page_observation'])

    def test_pointer_on_empty_slot_keeps_occupancy_unknown(self):
        scene = circular_slots(empty=((1, 4),), pointer=True)
        code, data = self.run_prepare([scene, scene])
        slots = data['page_observation']['team_slots']
        self.assertEqual((code, slots['teams'][0][3]['occupancy']), (0, 'unknown'))
        self.assertIsNone(slots['eight_slots_occupied'])

    def test_changed_capture_after_reading_slots_cannot_publish_receipt(self):
        read = ChallengePreparation._apocalyptic_slot_evidence

        def change_after_read(workflow, pair):
            result = read(workflow, pair)
            self.assertEqual(result['status'], 'compared')
            pair[0].scene.image[350:450, 1000:1400] = 0
            return result

        with patch.object(ChallengePreparation, '_apocalyptic_slot_evidence', change_after_read):
            code, data = self.run_prepare([circular_slots(), circular_slots()])
        self.assertEqual(code, 1)
        self.assertNotIn('page_observation', data)
