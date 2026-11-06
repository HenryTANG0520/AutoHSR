"""The activity-list target uses raw banner pixels, with rewards as counterevidence."""
from dataclasses import replace
from pathlib import Path
import time
import unittest

import cv2
import numpy as np

from autohsr.daily_event_navigation import odyssey_list_entry
from autohsr.models import Scene, Token


FIXTURES = Path(__file__).parent / 'fixtures' / 'daily_event_navigation'


def activity_frame(name='activity-list', *, size=(1920, 1080)):
    path = FIXTURES / f'{name}.png'
    image = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
    return Scene([], cv2.resize(image, size, interpolation=cv2.INTER_CUBIC), captured_at=time.monotonic())


class DailyEventNavigationTests(unittest.TestCase):
    def read(self, scene, version='4.6.0'):
        return odyssey_list_entry(scene, client_version=version, confidence=.85)

    def test_detects_actual_unselected_banner_in_two_scroll_positions(self):
        for size in ((960, 540), (1920, 1080), (3840, 2160)):
            with self.subTest(size=size):
                unscrolled = self.read(activity_frame(size=size))
                scrolled = self.read(activity_frame('activity-list-scrolled', size=size))
                self.assertEqual(unscrolled.text, '巡星之礼')
                self.assertAlmostEqual(unscrolled.center[0], .078125, places=3)
                self.assertAlmostEqual(unscrolled.center[1], .293, places=2)
                self.assertAlmostEqual(scrolled.center[1], .826, places=2)

    def test_wrong_version_reward_popup_and_dual_row_do_not_return_target(self):
        source = activity_frame(size=(1280, 720))
        self.assertIsNone(self.read(source, '4.7.0'))
        self.assertIsNone(self.read(activity_frame('claim-popup')))
        self.assertIsNone(self.read(replace(source, tokens=[Token('获得物品', .9, (.47, .14, .53, .19))])))
        source.image[400:430, 48:152] = source.image[196:226, 48:152]
        self.assertIsNone(self.read(source))

    def test_current_banner_without_separate_rewards_guide_anchors_is_rejected(self):
        source = activity_frame(size=(1280, 720))
        source.image[:80, 198:380] = 0
        self.assertIsNone(self.read(source))
