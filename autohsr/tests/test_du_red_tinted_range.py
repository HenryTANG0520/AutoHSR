"""Saturated range-marker phases still require the actual enemy HUD."""
import json
from pathlib import Path
import unittest
from unittest.mock import Mock

import cv2

from autohsr.du_navigation import FieldMotionWatch,attack_reticle,verified_attack_reticle
from autohsr.models import Scene,Token


def fixture():
    path=Path(__file__).parent/'fixtures/du_runtime/red_tinted_attack_circle'
    data=json.loads(path.with_suffix('.json').read_text('utf8'))
    return Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                 cv2.imread(str(path.with_suffix('.png'))))


class DuRedTintedRangeTests(unittest.TestCase):
    def test_native_red_core_has_correct_bearing_across_resolutions(self):
        page=fixture()
        for width in (960,1280,1920,3840):
            with self.subTest(width=width):
                image=cv2.resize(page.image,(width,round(page.image.shape[0]*width/page.image.shape[1])))
                marker=verified_attack_reticle(Scene(page.tokens,image))
                self.assertIsNotNone(marker)
                self.assertAlmostEqual(marker.center[0],.813,delta=.015)
                self.assertAlmostEqual(marker.center[1],.42,delta=.015)

    def test_red_marker_without_enemy_bar_never_proves_attack_range(self):
        page=fixture()
        no_bar=Scene([t for t in page.tokens if '等级' not in t.text],page.image)
        self.assertIsNotNone(attack_reticle(no_bar))
        self.assertIsNone(verified_attack_reticle(no_bar))

    def test_live_approach_stops_on_red_marker_and_preserves_its_bearing(self):
        page=fixture()
        vision=Mock()
        vision.read.return_value=Scene([Token('等级90幻造生物',.99,(.1,.1,.8,.8))])
        watch=FieldMotionWatch(page,vision,profile='engage')
        self.assertEqual(watch(page.image),'attack_reticle')
        self.assertIsNotNone(watch.attack_frame)
        self.assertAlmostEqual(watch.attack_target.center[0],.813,delta=.015)
        vision.read.return_value=Scene([])
        unverified=FieldMotionWatch(page,vision,profile='engage')
        self.assertIsNone(unverified(page.image))

