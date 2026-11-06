"""Replay the observed Reward Guide list bounds."""

from dataclasses import replace
import time
import unittest

import cv2
import numpy as np

from autohsr.daily_reward_guide_pages import reward_guide_page
from autohsr.models import Token
from autohsr.reward_guide_viewport import reward_guide_viewport
from autohsr.tests.test_daily_reward_guide_pages import FIXTURES, guide_scene
from autohsr.vision import Vision


_BEFORE, _AFTER = 'viewport-7014.png', 'viewport-7026.png'


class RewardGuideViewportTests(unittest.TestCase):
    def viewport(self, scene, version='4.6.0'):
        return reward_guide_viewport(scene, client_version=version, confidence=.85)

    def test_real_list_section_returns_native_content_box(self):
        for width, box in ((960, (189, 171, 702, 472)), (1280, (252, 228, 936, 630)),
                           (1920, (378, 342, 1404, 945)), (3840, (756, 684, 2808, 1890))):
            with self.subTest(width=width):
                view = self.viewport(guide_scene(_BEFORE, width=width))
                self.assertIsNotNone(view)
                self.assertEqual(view.visible_section, 'ongoing')
                self.assertEqual(view.content_box, box)

    def test_rapidocr_page_gate_and_static_pair_never_establish_scroll(self):
        vision = Vision(.65)
        for name in (_BEFORE, _AFTER):
            scene = vision.read(guide_scene(name).image)
            self.assertIsNotNone(self.viewport(scene))
        raw_crops = [cv2.imdecode(np.fromfile(FIXTURES / name, np.uint8), cv2.IMREAD_COLOR)[114:315, 126:468]
                     for name in (_BEFORE, _AFTER)]
        self.assertLessEqual(cv2.norm(*raw_crops, cv2.NORM_INF), 4)

    def test_verified_page_without_its_heading_or_bright_rail_cannot_supply_a_crop(self):
        source = guide_scene()
        self.assertTrue(reward_guide_page(source, client_version='4.6.0', confidence=.85))
        self.assertIsNone(self.viewport(source))
        for left, top, right, bottom in ((118, 95, 166, 116), (350, 101, 451, 109)):
            with self.subTest(left=left):
                scene = guide_scene(_BEFORE)
                scene.image[2 * top:2 * bottom, 2 * left:2 * right] = 0
                self.assertTrue(reward_guide_page(scene, client_version='4.6.0', confidence=.85))
                self.assertIsNone(self.viewport(scene))

    def test_first_fade_frame_identifies_page_but_cannot_supply_a_crop(self):
        vision = Vision(.65)
        for width in (960, 1920):
            with self.subTest(width=width):
                scene = vision.read(guide_scene('viewport-fade-7041.png', width=width).image)
                self.assertTrue(reward_guide_page(scene, client_version='4.6.0', confidence=.85))
                self.assertIsNone(self.viewport(scene))

    def test_wrong_version_stale_fading_or_overlay_rejects_viewport(self):
        scene = guide_scene(_BEFORE)
        self.assertIsNone(self.viewport(scene, '4.7.0'))
        self.assertIsNone(self.viewport(replace(scene, captured_at=time.monotonic() - 9)))
        self.assertIsNone(self.viewport(guide_scene('fade-2348.png')))
        scene.tokens.append(Token('获得物品', .9, (.43, .45, .58, .5)))
        self.assertIsNone(self.viewport(scene))
