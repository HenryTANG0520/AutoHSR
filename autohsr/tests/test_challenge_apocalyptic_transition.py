"""Observe a complete regular 04 picker sequence through the read-only CLI."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2

from autohsr.challenge_apocalyptic_prepare import observe
from autohsr.challenge_prepare import ChallengePreparation
from autohsr.challenge_roster import _references
from autohsr.models import EmptyCapture
from autohsr.tests.test_challenge_apocalyptic_prepare import APOCALYPTIC_PLAN, text
from autohsr.tests.test_challenge_apocalyptic_slots import circular_slots
from autohsr.tests.test_challenge_integration import prepare_with_fake_window


def picker(*, empty=(), badge=None, focus=2):
    scene = circular_slots(empty=empty)
    scene.tokens = [token for token in scene.tokens if token.text not in ('难度04', '支配遗忘')]
    scene.tokens.extend((text('角色列表', (.065, .125, .112, .151)),
                         text('预设编队', (.200, .126, .247, .152))))
    image = cv2.resize(scene.image, (802, 454), interpolation=cv2.INTER_AREA)
    image[55:71, 17:124] = 225
    image[55:71, 129:235] = 35
    card = next(image for name, image, _ in _references() if name == 'Aventurine')
    image[204:238, 72:121] = cv2.resize(card, (49, 34))
    if badge is not None:
        image[238:249, 73:121] = 230
        scene.tokens.append(text(f'队伍{badge}', (.106, .524, .135, .547)))
    height, width = scene.image.shape[:2]
    left_width = round(247 * width / 802)
    scene.image[:, :left_width] = cv2.resize(image[:, :247], (left_width, height))
    left, right = (round(x * width / 802) for x in (562, 671))
    for y in ((150, 185) if focus == 1 else (269, 305)):
        top, bottom = (round(value * height / 454) for value in (y, y + 2))
        scene.image[top:bottom, left:right] = 235
    return scene


def transition_frames():
    empty = ((2, 3),)
    return [circular_slots(), picker(empty=empty), picker(empty=empty, badge=2),
            picker(badge=2), circular_slots(), circular_slots()]


class ApocalypticCandidateTransitionTests(unittest.TestCase):
    def run_prepare(self, frames):
        with tempfile.TemporaryDirectory() as folder:
            code, report, window = prepare_with_fake_window(Path(folder), frames,
                plan=dict(APOCALYPTIC_PLAN, levels=[4, 4]))
            data = report['challenge']
            path = Path(report['run_dir']) / 'challenge-preparation.json'
            self.assertEqual(json.loads(path.read_bytes()), data)
        for method in (window.focus, window.click, window.key, window.send, window.drag):
            method.assert_not_called()
        self.assertEqual(data['actions'], [])
        self.assertFalse(data['team_verified'])
        return code, data

    def test_observed_badge_then_one_filled_slot_stays_bound_to_the_two_return_frames(self):
        code, data = self.run_prepare(transition_frames())
        self.assertEqual(code, 0)
        observed = data['page_observation']['candidate_slot_transition']
        self.assertEqual((observed['level'], observed['node'], observed['position']), (4, 2, 3))
        self.assertTrue(observed['badge_before_occupancy'])
        self.assertTrue(observed['returned_portrait_verified'])
        self.assertIsNone(observed['picker_level'])
        self.assertEqual(observed['identity_status'], 'unknown')
        self.assertFalse(observed['execution_supported'])
        sources = data['observations']
        self.assertEqual([s['kind'] for s in sources], ['node_setup', 'candidate_picker', 'candidate_picker',
                                                        'candidate_picker', 'node_setup', 'node_setup'])
        self.assertEqual(set(row['sha256'] for row in observed['frames'].values()),
                         set(row['sha256'] for row in sources))
        self.assertEqual(sorted(row['capture_sequence'] for row in observed['frames'].values()), list(range(1, 7)))

    def test_badge_only_two_slot_changes_and_wrong_node_leave_no_transition(self):
        before = ((2, 3),)
        two = ((2, 2), (2, 3))
        cases = (
            ('badge only', (picker(empty=before), picker(empty=before, badge=2), picker(empty=before, badge=2))),
            ('two slots', (picker(empty=two), picker(empty=two, badge=2), picker(badge=2))),
            ('other node', (picker(empty=before), picker(empty=before, badge=1), picker(badge=1))),
        )
        for label, middle in cases:
            with self.subTest(label=label):
                code, data = self.run_prepare([circular_slots(), *middle, circular_slots(), circular_slots()])
                self.assertEqual(code, 0)
                self.assertNotIn('candidate_slot_transition', data['page_observation'])

    def test_unread_second_bar_or_another_node_portrait_change_blocks_the_sequence(self):
        for change in ('second bar', 'inactive portrait'):
            with self.subTest(change=change):
                frames = transition_frames()
                image = cv2.resize(frames[2].image, (802, 454), interpolation=cv2.INTER_AREA)
                if change == 'second bar':
                    image[238:249, 130:177] = 230
                else:
                    image[151:186, 450:485] = image[151:186, 413:448]
                frames[2].image = cv2.resize(image, (1920, 1080))
                code, data = self.run_prepare(frames)
                self.assertEqual(code, 0)
                self.assertNotIn('candidate_slot_transition', data['page_observation'])

    def test_missing_bracket_or_an_empty_capture_cannot_join_the_picker_to_04(self):
        frames = transition_frames()
        for contrast in (frames[1:], [*frames[:4], EmptyCapture('gap'), *frames[4:]]):
            code, data = self.run_prepare(contrast)
            self.assertEqual(code, 0)
            self.assertNotIn('candidate_slot_transition', data['page_observation'])

    def test_level_visible_behind_the_active_picker_is_a_transition_frame(self):
        scene = picker(empty=((2, 3),), badge=2)
        scene.tokens.extend((text('难度04', (.138, .191, .174, .213)),
                             text('支配遗忘', (.117, .223, .194, .260))))
        self.assertEqual(observe(scene).kind, 'unknown')
        faded = circular_slots()
        image = cv2.resize(faded.image, (802, 454), interpolation=cv2.INTER_AREA)
        image[269:271, 562:671] = 112
        faded.image = cv2.resize(image, (1920, 1080))
        self.assertEqual(observe(faded).kind, 'unknown')

    def test_changed_picker_png_prevents_publishing_the_observed_sequence(self):
        publish = ChallengePreparation._publish_apocalyptic

        def modify_source(workflow, pair, deadline, *, trace=()):
            self.assertEqual(len(trace), 6)
            with Path(trace[2].source['path']).open('ab') as stream:
                stream.write(b'changed picker')
            return publish(workflow, pair, deadline, trace=trace)

        with patch.object(ChallengePreparation, '_publish_apocalyptic', modify_source):
            code, data = self.run_prepare(transition_frames())
        self.assertEqual(code, 1)
        self.assertNotIn('page_observation', data)
