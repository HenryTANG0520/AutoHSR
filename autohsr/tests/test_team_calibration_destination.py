"""Pinned original emblem with synthetic ordinary team page OCR geometry."""
from dataclasses import replace
import json
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr.models import Scene, Token
from autohsr import team_calibration_destination as destination


def normal_team_scene(caption='已启用'):
    """Build synthetic OCR geometry with the fixed upstream emblem pixels."""
    path = (Path(__file__).resolve().parents[2] / 'assets/upstream/March7thAssistant'
            / 'team-calibration/configure_team.png')
    original = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_COLOR)
    image = np.empty((1080, 1920, 3), dtype=np.uint8)
    image[:] = np.linspace(24, 84, 1920, dtype=np.uint8)[None, :, None]
    image[50:89, 52:88] = original
    return Scene([
        Token('队伍', .99, (.051, .046, .084, .078)),
        Token('01', .99, (.174, .052, .194, .076)),
        Token('02', .99, (.280, .052, .300, .076)),
        Token('03', .99, (.387, .052, .407, .076)),
        Token(caption, .99, (.825, .894, .895, .921)),
    ], image, captured_at=time.monotonic())


def _change(scene, label, **fields):
    tokens = [replace(token, **fields) if token.text == label else token for token in scene.tokens]
    return replace(scene, tokens=tokens)


class TeamCalibrationDestinationTests(unittest.TestCase):
    def test_fixed_emblem_and_synthetic_ocr_return_json_evidence_for_each_status(self):
        for caption in ('已启用', '启用队伍'):
            with self.subTest(caption=caption):
                observed = destination.observe_team_page(normal_team_scene(caption))
                self.assertEqual(observed['status']['text'], caption)
                self.assertEqual(observed['source']['sha256'], destination._EMBLEM_SHA256)
                self.assertEqual(observed['source']['box'], [52 / 1920, 50 / 1080, 88 / 1920, 89 / 1080])
                self.assertEqual([item['number'] for item in observed['team_numbers']], [1, 2, 3])
                self.assertEqual(json.loads(json.dumps(observed, ensure_ascii=False)), observed)

    def test_resized_emblem_accepts_fractional_pixel_alignment(self):
        scene = normal_team_scene()
        image = cv2.resize(scene.image, (1280, 720), interpolation=cv2.INTER_AREA)
        self.assertIsNotNone(destination.observe_team_page(replace(scene, image=image)))

    def test_emblem_missing_outside_roi_or_ambiguous_leaves_no_page(self):
        scene = normal_team_scene()
        original = scene.image[50:89, 52:88].copy()
        missing = scene.image.copy()
        missing[50:89, 52:88] = missing[100:139, 52:88]
        self.assertIsNone(destination.observe_team_page(replace(scene, image=missing)))
        outside = missing.copy()
        outside[250:289, 52:88] = original
        self.assertIsNone(destination.observe_team_page(replace(scene, image=outside)))
        duplicate = scene.image.copy()
        duplicate[68:107, 98:134] = original
        self.assertIsNone(destination.observe_team_page(replace(scene, image=duplicate)))

    def test_original_file_hash_mismatch_leaves_no_page(self):
        scene = normal_team_scene()
        with patch.object(destination, '_EMBLEM_SHA256', '0' * 64):
            self.assertIsNone(destination.observe_team_page(scene))

    def test_status_must_be_complete_unique_strong_and_in_the_upstream_region(self):
        scene = normal_team_scene()
        for changed in (
            _change(scene, '已启用', text='启用'),
            _change(scene, '已启用', score=.849),
            _change(scene, '已启用', box=(.770, .894, .895, .921)),
        ):
            self.assertIsNone(destination.observe_team_page(changed))
        for text, box in (
            ('启用队伍', (.41, .30, .47, .33)),
            ('已启', (.882, .896, .906, .919)),
        ):
            with self.subTest(text=text):
                extra = Token(text, .65, box)
                changed = replace(scene, tokens=[*scene.tokens, extra])
                self.assertIsNone(destination.observe_team_page(changed, .95))

    def test_number_row_must_have_distinct_consecutive_two_digit_tokens(self):
        scene = normal_team_scene()
        for changed in (
            _change(scene, '02', text='03'),
            _change(scene, '02', text='2'),
            _change(scene, '02', box=(.28, .080, .30, .104)),
            _change(scene, '01', box=(.15, .052, .194, .076)),
            replace(scene, tokens=[t for t in scene.tokens if t.text not in ('01', '02')]),
        ):
            self.assertIsNone(destination.observe_team_page(changed))

    def test_shared_emblem_and_background_do_not_override_weak_wrong_page_or_modal(self):
        scene = normal_team_scene()
        for text in ('开始挑战', '快速编队', '侵蚀隧洞·侵冥之径', '混沌回忆', '位面饰品',
                     '是否确认更换队伍', '列车补给', '获得物品', '补充开拓力', '账号登录', '队伍预设', '预设编队'):
            with self.subTest(text=text):
                changed = replace(scene, tokens=[*scene.tokens, Token(text, .65, (.40, .40, .55, .43))])
                self.assertIsNone(destination.observe_team_page(changed, .95))

    def test_two_frames_require_same_status_row_and_overlapping_anchor_boxes(self):
        first = destination.observe_team_page(normal_team_scene())
        second = destination.observe_team_page(normal_team_scene())
        self.assertTrue(destination.same_team_page(first, second))
        self.assertFalse(destination.same_team_page(first, None))
        self.assertFalse(destination.same_team_page(first, {}))
        changed = destination.observe_team_page(normal_team_scene('启用队伍'))
        self.assertFalse(destination.same_team_page(first, changed))
        moved = {**second, 'source': {**second['source'], 'box': [.050, .046, .069, .082]}}
        self.assertFalse(destination.same_team_page(first, moved))
        moved = {**second, 'team_numbers': second['team_numbers'][1:]}
        self.assertFalse(destination.same_team_page(first, moved))


if __name__ == '__main__':
    unittest.main()
