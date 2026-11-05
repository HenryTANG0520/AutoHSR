"""A standard crystal click keeps overflow observation separate from delivery."""
from pathlib import Path
import tempfile
from unittest import TestCase
from unittest.mock import patch

import cv2

from autohsr.currency_wars_loot import loot_feedback
from autohsr.currency_wars_session import StandardSession
from autohsr.models import AutomationError, InputInterrupted, Stopped, Token, normalize
from autohsr.tests.test_currency_wars_loot_capacity import ROOT, Harness, clone


NOTICE = Token('备战席已满，请出售角色或提升等级', .993, (.4193, .4824, .5995, .5065))
BLOCKED = Token('备战席已满，需要售卖备战区角色才可开启晶矿', .99, NOTICE.box)


def ground(scene, sample):
    scene.image[330:690, 1700:2180] = cv2.imread(str(ROOT/f'overflow_{sample}.png'))


class OverflowHarness(Harness):
    def __init__(self, folder, variant):
        super().__init__(folder, free=True)
        ground(self.board, 'before')
        self.variant = variant
        self.frame_number = 0
        self.first_stamp = None
        sleep = self.c.sleep

        def tick(seconds):
            if self.frame_number == 2 and variant == 'interrupted':
                self.c.runner.input_epoch += 1
            if variant in ('stale', 'missing_account'):
                advance_timeout = self.frame_number % 2 == 0
            elif variant == 'shifted_after_clear':
                advance_timeout = self.frame_number >= 3
            else:
                advance_timeout = variant not in ('transient', 'interrupted')
            fast = seconds == .5 and self.frame_number and advance_timeout
            sleep(31 if fast else seconds)

        self.c.sleep = tick

    def click(self, *args):
        action = self.c.currency_standard_session.data['actions'][-1]
        if action['action'] != 'collect_standard_loot':
            raise AssertionError('overflow must not send a second kind of click')
        self.before_click = clone(self.board)
        self.stage = 'clicked'
        self.board.tokens.append(BLOCKED if self.variant == 'present' else NOTICE)

    def snapshot(self):
        scene = super().snapshot()
        if self.stage != 'clicked':
            return scene
        self.frame_number += 1
        if self.variant != 'present':
            ground(scene, 'after' if self.frame_number == 1 else 'later')
        if self.variant == 'unclear':
            scene.image[330:690, 1700:2180] = 0
        if self.variant in ('transient', 'shifted_after_clear') and self.frame_number >= 3:
            scene.tokens.remove(NOTICE)
        if self.variant == 'shifted_after_clear' and self.frame_number >= 3:
            prior = scene.image[510:620, 1861:1971]
            scene.image[475:585, 1729:1839] = prior.copy()
            prior[:] = 0
        if self.variant == 'missing_account' and self.frame_number % 2 == 0:
            scene.tokens = [t for t in scene.tokens if not normalize(t.text).startswith('uid')]
        if self.variant == 'stale':
            if self.frame_number % 2 == 1:
                self.first_stamp = scene.captured_at
            else:
                scene.captured_at = self.first_stamp
        return scene


class StandardOverflowTests(TestCase):
    def test_persistent_overflow_keeps_ground_state_separate_and_stops(self):
        variants = {
            'removed': ('removed', '晶矿消失'),
            'present': ('present', '仍看得到'),
            'unclear': ('unclear', '晶矿状态未核实'),
        }
        for variant, (state, message) in variants.items():
            with (self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder,
                  patch('autohsr.currency_wars_replay.save_sample')):
                harness = OverflowHarness(folder, variant)
                result = harness.run()
                self.assertEqual(result.status, 'partial')
                self.assertIn(message, result.detail)
                saved = harness.path.read_bytes()
                data = StandardSession(harness.path).data
                action, = data['actions']
                self.assertEqual(action['status'], 'unknown')
                self.assertAlmostEqual(action['target'][0]*2560, 2033, delta=2)
                observation, = action['loot_overflow_observations']
                self.assertEqual((observation['crystal_state'], observation['delivery_status']), (state, 'unverified'))
                first, second = observation['frames']
                self.assertLess(first['captured_at'], second['captured_at'])
                self.assertTrue(all(Path(frame['evidence']).is_file() for frame in observation['frames']))
                self.assertNotIn('loot_pickup', action)
                with self.assertRaisesRegex(AutomationError, '上次标准动作尚未核实'):
                    harness.run()
                self.assertEqual(harness.path.read_bytes(), saved)
                harness.c.window.click.assert_called_once()
                harness.c.window.drag.assert_not_called()

    def test_stale_or_unattributed_frames_cannot_form_an_observation(self):
        for variant in ('stale', 'missing_account'):
            with (self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder,
                  patch('autohsr.currency_wars_replay.save_sample')):
                harness = OverflowHarness(folder, variant)
                self.assertEqual(harness.run().status, 'partial')
                action, = StandardSession(harness.path).data['actions']
                self.assertEqual(action['status'], 'unknown')
                self.assertNotIn('loot_overflow_observations', action)
                harness.c.window.click.assert_called_once()

    def test_return_after_overflow_requires_the_same_surviving_crystals(self):
        with tempfile.TemporaryDirectory() as folder, patch('autohsr.currency_wars_replay.save_sample'):
            harness = OverflowHarness(folder, 'shifted_after_clear')
            self.assertEqual(harness.run().status, 'partial')
            action, = StandardSession(harness.path).data['actions']
            self.assertEqual(loot_feedback(harness.before_click, harness.c.last_scene, action['target']), 'disappeared')
            self.assertEqual(action['status'], 'unknown')
            harness.c.window.click.assert_called_once()

    def test_transient_overflow_allows_normal_feedback_and_interruption_preserves_the_observation(self):
        for variant, error, expected in (('transient', Stopped, 'verified'),
                                         ('interrupted', InputInterrupted, 'pending')):
            with (self.subTest(variant=variant), tempfile.TemporaryDirectory() as folder,
                  patch('autohsr.currency_wars_replay.save_sample')):
                harness = OverflowHarness(folder, variant)
                with self.assertRaises(error):
                    harness.run()
                action, = StandardSession(harness.path).data['actions']
                self.assertEqual(action['status'], expected)
                observation, = action['loot_overflow_observations']
                self.assertEqual(observation['crystal_state'], 'removed')
                harness.c.window.click.assert_called_once()
