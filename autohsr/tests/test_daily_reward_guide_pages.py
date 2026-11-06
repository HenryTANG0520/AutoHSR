"""Replay public Reward Guide anchors and nearby false positives."""

from dataclasses import replace
from pathlib import Path
import time
import unittest

import cv2
import numpy as np

from autohsr.daily_reward_guide_pages import reward_guide_page
from autohsr.models import Scene, Token
from autohsr.tests.test_daily_event_navigation import activity_frame
from autohsr.vision import Vision


FIXTURES = Path(__file__).parent / 'fixtures' / 'daily_reward_guide'
_HIGHLIGHTS = Token('旅程热点', .999, (.0555, .1361, .1125, .1681))


def guide_scene(name='highlights-2328.png', *, width=1280):
    image = cv2.imdecode(np.fromfile(FIXTURES / name, np.uint8), cv2.IMREAD_COLOR)
    image = cv2.resize(image, (width, width * 9 // 16), interpolation=cv2.INTER_CUBIC)
    return Scene([_HIGHLIGHTS], image, captured_at=time.monotonic())


class DailyRewardGuidePagesTests(unittest.TestCase):
    def read(self, scene, version='4.6.0'):
        return reward_guide_page(scene, client_version=version, confidence=.85)

    def test_actual_highlights_tab_at_multiple_sizes(self):
        for name in ('highlights-2328.png', 'highlights-2346.png'):
            for width in (960, 1280, 1920, 3840):
                with self.subTest(name=name, width=width):
                    self.assertTrue(self.read(guide_scene(name, width=width)))

    def test_rapidocr_matches_visible_tab_but_fade_stays_unknown(self):
        vision = Vision(.65)
        for name, expected in (('highlights-2328.png', True), ('highlights-2346.png', True),
                               ('fade-2348.png', False)):
            with self.subTest(name=name):
                scene = vision.read(guide_scene(name).image)
                self.assertTrue(scene.has('旅程热点', exact=True))
                self.assertEqual(self.read(scene), expected)

    def test_entry_badge_nearby_list_and_claim_popup_are_not_the_guide(self):
        for name in ('activity-list', 'activity-list-scrolled', 'claim-popup'):
            with self.subTest(name=name):
                scene = activity_frame(name, size=(1280, 720))
                scene.tokens = [_HIGHLIGHTS, Token('奖励指南', .98, (.20, .04, .28, .08))]
                self.assertFalse(self.read(scene))

    def test_requires_both_anchors_and_each_visible_surface(self):
        for name, (left, top, right, bottom) in (
            ('title', (12, 12, 70, 31)), ('banner', (174, 61, 274, 78)),
            ('selected tab', (82, 43, 99, 69)), ('cyan panel', (341, 53, 451, 84)),
            ('list body', (365, 114, 447, 317)),
        ):
            with self.subTest(name=name):
                scene = guide_scene()
                scene.image[2 * top:2 * bottom, 2 * left:2 * right] = 0
                self.assertFalse(self.read(scene))

    def test_dialog_counterevidence_wins_over_intact_page(self):
        for text in ('获得物品', '确认', '重新连接'):
            with self.subTest(text=text):
                scene = guide_scene()
                scene.tokens.append(Token(text, .70, (.42, .52, .58, .57)))
                self.assertFalse(self.read(scene))

    def test_version_freshness_and_unambiguous_tab(self):
        scene = guide_scene()
        self.assertFalse(self.read(scene, '4.7.0'))
        self.assertFalse(self.read(replace(scene, captured_at=time.monotonic() - 9)))
        for tokens in ([], [_HIGHLIGHTS, _HIGHLIGHTS],
                       [replace(_HIGHLIGHTS, score=.84)], [replace(_HIGHLIGHTS, text='常时传略')],
                       [replace(_HIGHLIGHTS, box=(.0555, .24, .1125, .27))]):
            with self.subTest(tokens=tokens):
                self.assertFalse(self.read(replace(scene, tokens=tokens)))
