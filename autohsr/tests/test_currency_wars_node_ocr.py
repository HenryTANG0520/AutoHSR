"""Field OCR preserves the original mistake and rejects contradictory evidence."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr.currency_wars_node import battle_node
from autohsr.currency_wars_node_ocr import BATTLE_FIELDS, refine_battle_node
from autohsr.currency_wars_replay import load_sample, save_sample
from autohsr.models import AutomationError, Scene, Token
from autohsr.ocr_isolation import IsolatedVision, _field_reads, field_read_payload
from autohsr.tests.test_currency_wars_node import screen


FIXTURES = Path(__file__).parent/'fixtures/currency_node_fields'
NORMAL, REWARD = BATTLE_FIELDS


def token(text='1-1', score=.99):
    return Token(text, score, (0., 0., 1., 1.))


def frame(raw='1-10'):
    scene = screen('battle', raw)
    scene.image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    header(scene.image)
    return scene


def header(image, *, shifted=False, text=None):
    height, width = image.shape[:2]
    left, right = ((.309, .350) if shifted else (.361, .402))
    x1, x2 = round(left*width), round(right*width)
    image[:round(.06*height), x1:x2+round(.006*width)] = 45
    cv2.line(image, (x1, 0), (x1, round(.055*height)), (180, 180, 180), 1)
    cv2.line(image, (x2, round(.008*height)), (x2, round(.042*height)), (160, 160, 160), 1)
    if text is not None:
        cv2.putText(image, text, (x1+7, round(.033*height)), cv2.FONT_HERSHEY_SIMPLEX, .65, (255, 255, 255), 1, cv2.LINE_AA)


def worker_fields(input_path, output_path, confidence):
    scene = refine_battle_node(frame(), Mock(read_node=Mock(side_effect=[token(), token()])))
    Path(output_path).write_text(json.dumps(dict(status='ok', tokens=[], field_reads=field_read_payload(scene))), encoding='utf-8')


class BattleNodeFieldTests(unittest.TestCase):
    def test_local_agreement_overrides_neighbor_percentage_without_erasing_raw_text(self):
        scene = frame()
        raw = list(scene.tokens)
        refined = refine_battle_node(scene, Mock(read_node=Mock(side_effect=[token(), token()])))
        self.assertEqual(battle_node(refined), '1-1')
        self.assertEqual(battle_node(scene), '1-10')
        self.assertEqual(refined.tokens, raw)
        self.assertIs(refined.image, scene.image)
        self.assertEqual(refined.captured_at, scene.captured_at)
        self.assertFalse(scene.field_reads)

    def test_two_digit_nodes_and_shifted_fields_are_not_shortened(self):
        for name in BATTLE_FIELDS:
            scene = frame('2-1')
            scene.image[:] = 0
            header(scene.image, shifted=name == REWARD)
            scene = refine_battle_node(scene, Mock(read_node=Mock(side_effect=[token('2-10'), token('2-10')])))
            self.assertEqual(battle_node(scene), '2-10')

    def test_unreadable_partial_low_confidence_and_disagreement_stay_unknown(self):
        for reads in ([None]*4, [token(), None, None, None],
                      [token(score=.89), token(), None, None],
                      [token(), token('1-10'), None, None],
                      [token(), token(), token('2-1'), token('2-1')],
                      [token(), token(), token('2-1'), None]):
            with self.subTest(reads=reads):
                scene = frame('1-1')
                header(scene.image, shifted=True)
                scene = refine_battle_node(scene, Mock(read_node=Mock(side_effect=reads)))
                self.assertIsNone(battle_node(scene))

    def test_wrong_page_missing_image_and_old_evidence_keep_their_original_contract(self):
        reader = Mock()
        for scene in (Scene([], image=np.zeros((100, 100, 3), np.uint8)), screen('battle')):
            self.assertIs(refine_battle_node(scene, reader), scene)
            self.assertFalse(scene.field_reads)
        reader.read_node.assert_not_called()
        self.assertEqual(battle_node(screen('battle', '3-12')), '3-12')

    def test_wrong_field_location_cannot_override_raw_ocr(self):
        scene = frame()
        scene.field_reads[NORMAL] = (token(), token())
        self.assertIsNone(battle_node(scene))

    def test_missing_or_ambiguous_dividers_do_not_authorize_a_read(self):
        for extra in (False, True):
            scene = frame()
            if extra:
                cv2.line(scene.image, (round(.39*1920), 9), (round(.39*1920), 45), (160, 160, 160), 1)
            else:
                scene.image[:, round(.40*1920):] = 0
            reader = Mock()
            refined = refine_battle_node(scene, reader)
            reader.read_node.assert_not_called()
            self.assertIsNone(battle_node(refined))

    def test_field_evidence_survives_spawned_worker_and_replay_without_fresh_timestamp(self):
        with patch('autohsr.ocr_isolation._ocr_job', worker_fields):
            scene = IsolatedVision(timeout=5).read(frame().image)
        self.assertEqual(battle_node(scene), '1-1')
        with tempfile.TemporaryDirectory() as folder:
            screenshot = Path(folder)/'field.png'
            screenshot.write_bytes(cv2.imencode('.png', scene.image)[1].tobytes())
            data, restored = load_sample(save_sample(scene, screenshot, origin='synthetic'))
        self.assertEqual(restored.field_reads, scene.field_reads)
        self.assertEqual(restored.captured_at, 0)
        self.assertEqual(battle_node(restored), '1-1')
        self.assertIn('field_reads', data)

    def test_malformed_field_payloads_fail_closed(self):
        for fields in ([], {NORMAL: []}, {NORMAL: [False]}, {NORMAL: [None]*9},
                       {'bad key': [None]}, {NORMAL: [dict(text='1-1', score=2, box=[0, 0, 1, 1])]}):
            with self.subTest(fields=fields), self.assertRaises(AutomationError):
                _field_reads(dict(field_reads=fields))

    def test_real_anonymized_replays_and_generated_two_digit_fields(self):
        from autohsr.vision import Vision
        reader = Vision()
        manifest = json.loads((FIXTURES/'manifest.json').read_text(encoding='utf-8'))
        for case in manifest['cases']:
            with self.subTest(case=case['image']):
                path = FIXTURES/case['image']
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), case['sha256'])
                width, height = case['dimensions']
                x1, y1, x2, y2 = case['crop']
                scene = frame()
                scene.image = np.zeros((height, width, 3), np.uint8)
                scene.image[y1:y2, x1:x2] = cv2.imread(str(path))
                refined = refine_battle_node(scene, reader)
                self.assertEqual(battle_node(refined), case['expected'])
        for name in BATTLE_FIELDS:
            for value in ('1-10', '2-12', '3-9'):
                with self.subTest(layout=name, value=value):
                    scene = frame()
                    scene.image = np.zeros((1080, 1920, 3), np.uint8)
                    header(scene.image, shifted=name == REWARD, text=value)
                    self.assertEqual(battle_node(refine_battle_node(scene, reader)), value)


if __name__ == '__main__':
    unittest.main()
