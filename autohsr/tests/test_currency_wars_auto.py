"""Pure Scene/CV calibration and counterexamples; no Runner or native windows."""
from dataclasses import FrozenInstanceError
import hashlib
import json
import math
from pathlib import Path
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr.currency_wars_auto import read_auto
from autohsr.models import Scene, Token


ASSETS = Path(__file__).resolve().parents[2] / 'assets/currency-auto'


def image(path):
    return cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_COLOR)


def battle_tokens():
    # Synthetic, account-free CW anchors. Only the control pixels are real.
    return [Token('1-1', .99, (.35, .01, .39, .04)),
            Token('羁绊', .99, (.85, .18, .90, .22)),
            Token('伤害', .99, (.92, .18, .97, .22))]


def manifest():
    return json.loads((ASSETS / 'sources.json').read_text(encoding='utf-8'))


def real_case(name):
    case = next(c for c in manifest()['samples'] if c['id'] == name)
    width, height = case['source_dimensions']
    pixels = np.zeros((height, width, 3), np.uint8)
    x1, y1, x2, y2 = case['crop_xyxy']
    pixels[y1:y2, x1:x2] = image(ASSETS / case['file'])
    return Scene(battle_tokens(), pixels)


class CurrencyAutoTests(unittest.TestCase):
    def test_real_cw_control_crops_keep_calibration_neighbors_and_unknowns_separate(self):
        data = manifest()
        self.assertFalse(data['independent_real_holdout'])
        self.assertFalse(data['off_state_calibrated'])
        self.assertFalse(data['live_acceptance'])
        self.assertEqual(len(data['samples']), 12)
        for case in data['samples']:
            with self.subTest(sample=case['id'], group=case['group']):
                result = read_auto(real_case(case['id']))
                self.assertEqual(result.state, case['expected'])
                self.assertTrue(math.isfinite(result.score))
                self.assertGreaterEqual(result.score, 0)
                self.assertLessEqual(result.score, 1)
        self.assertEqual(next(c for c in data['samples'] if c['id'] == 'cw_on_01')['client_version'], '4.6.0')
        self.assertTrue(all(c['client_version'] == 'unverified' for c in data['samples']
                            if c['id'].startswith(('cw_dim_', 'cw_ambiguous_', 'cw_transition_'))))

    def test_sources_are_minimal_unchanged_public_crops_with_anonymous_metadata(self):
        text = (ASSETS / 'sources.json').read_text(encoding='utf-8')
        self.assertNotIn('runs/', text)
        self.assertNotIn('runs\\', text)
        self.assertNotIn('UID:', text)
        self.assertNotIn('D:\\', text)
        self.assertNotIn('C:\\', text)
        for case in manifest()['samples']:
            path = ASSETS / case['file']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), case['sha256'])
            x1, y1, x2, y2 = case['crop_xyxy']
            self.assertLessEqual(y2 / case['source_dimensions'][1], .07)
            self.assertGreaterEqual(x1 / case['source_dimensions'][0], .83)
            self.assertEqual(image(path).shape[:2], (y2-y1, x2-x1))
            self.assertTrue(case['excludes_identifiers'])
        for reference in manifest()['references']:
            path = ASSETS / reference['file']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), reference['sha256'])

    def test_result_is_immutable_anonymous_json_and_never_contains_a_target(self):
        result = read_auto(real_case('cw_on_01'))
        with self.assertRaises(FrozenInstanceError):
            result.state = 'off'
        self.assertIsInstance(result.diagnostics, tuple)
        data = result.to_dict()
        self.assertEqual(set(data), {'state', 'score', 'diagnostics'})
        self.assertFalse(data['diagnostics']['off_calibrated'])
        serialized = json.dumps(data, allow_nan=False)
        for forbidden in ('target', 'point', 'account', 'UID', 'run_dir', 'screenshot'):
            self.assertNotIn(forbidden, serialized)
        data['diagnostics']['reason'] = 'changed_copy'
        self.assertNotEqual(dict(result.diagnostics)['reason'], 'changed_copy')
        self.assertFalse(hasattr(result, 'target'))
        self.assertFalse(hasattr(result, 'point'))

    def test_identical_toolbar_without_cw_page_or_with_a_modal_stays_unknown(self):
        scene = real_case('cw_on_01')
        self.assertEqual(read_auto(Scene([], scene.image)).state, 'unknown')
        scene.tokens += [Token('请选择投资策略', .99, (.44, .07, .56, .11))]
        self.assertEqual(read_auto(scene).state, 'unknown')
        scene.tokens = [Token('战斗', .99, (.35, .01, .39, .04))]
        self.assertEqual(read_auto(scene).state, 'unknown')

    def test_real_ult_occlusion_and_missing_pause_do_not_certify_on(self):
        for name in ('cw_occluded_01', 'cw_occluded_02'):
            result = read_auto(real_case(name))
            self.assertEqual(result.state, 'unknown')
            self.assertEqual(dict(result.diagnostics)['reason'], 'pause_context_missing')
        scene = real_case('cw_on_01')
        scene.image[:216, 3648:] = 0
        self.assertEqual(read_auto(scene).state, 'unknown')

    def test_gray_derived_on_is_not_a_real_off_calibration(self):
        scene = real_case('cw_on_01')
        scene.image = cv2.cvtColor(cv2.cvtColor(scene.image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        result = read_auto(scene)
        self.assertEqual(result.state, 'unknown')
        self.assertNotEqual(result.state, 'off')
        self.assertFalse(dict(result.diagnostics)['off_calibrated'])

    def test_real_dim_slash_requires_both_references_not_just_white_pixels(self):
        for name in ('cw_dim_01', 'cw_dim_02'):
            result = read_auto(real_case(name))
            self.assertEqual(result.state, 'disabled')
            self.assertEqual(dict(result.diagnostics)['reason'], 'cw_and_real_disabled_reference')
        result = read_auto(real_case('cw_dim_03'))
        self.assertEqual(result.state, 'unknown')
        self.assertGreater(dict(result.diagnostics)['planar_dim'], .92)
        self.assertLess(dict(result.diagnostics)['dim'], .92)

    def test_gold_panel_and_left_corner_character_are_not_on(self):
        scene = real_case('cw_on_01')
        scene.image[:216, 3379:3648] = (40, 180, 235)
        self.assertEqual(read_auto(scene).state, 'unknown')
        scene.image[:] = 0
        cv2.putText(scene.image, 'C', (10, 1930), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (20, 220, 255), 3)
        self.assertEqual(read_auto(scene).state, 'unknown')

    def test_spatially_unrelated_pause_and_duplicate_glyphs_are_rejected(self):
        # Synthetic placement mechanism; not an additional real game sample.
        scene = real_case('cw_on_01')
        scene.image = cv2.resize(scene.image, (1920, 1080))
        native_on = cv2.resize(image(ASSETS / 'auto_on.png'), None, fx=.5, fy=.5)
        height, width = native_on.shape[:2]
        scene.image[:108, 1689:1824] = 0
        scene.image[32:32+height, 1775:1775+width] = native_on
        self.assertEqual(read_auto(scene).state, 'unknown')
        scene.image[:108, 1689:1824] = 0
        for x in (1695, 1775):
            scene.image[32:32+height, x:x+width] = native_on
        self.assertEqual(read_auto(scene).state, 'unknown')

    def test_reference_failure_and_unsupported_images_are_unknown(self):
        scene = real_case('cw_on_01')
        with patch('autohsr.currency_wars_auto._templates', side_effect=OSError('unavailable')):
            self.assertEqual(read_auto(scene).state, 'unknown')
        for pixels in (None, np.zeros((10, 20, 3), np.uint8), np.zeros((1080, 1920), np.uint8),
                       np.zeros((1080, 1920, 4), np.uint8), np.zeros((1080, 1920, 3), np.float32),
                       np.zeros((1080, 1080, 3), np.uint8)):
            self.assertEqual(read_auto(Scene(battle_tokens(), pixels)).state, 'unknown')
        for confidence in (True, float('nan'), float('inf'), -1, 2, '0.65'):
            self.assertEqual(read_auto(scene, confidence).state, 'unknown')
        self.assertEqual(read_auto(None).state, 'unknown')

    def test_real_on_pixels_at_original_and_canonical_scale(self):
        scene = real_case('cw_on_01')
        self.assertEqual(read_auto(scene).state, 'on')
        scene.image = cv2.resize(scene.image, (1920, 1080))
        self.assertEqual(read_auto(scene).state, 'on')
        # Lower-resolution derivatives are synthetic and may remain unknown;
        # they must not turn a dim/obscured toolbar into an off/click target.
        for name in ('cw_dim_03', 'cw_occluded_01'):
            scene = real_case(name)
            for width, height in ((1920, 1080), (1280, 720), (960, 540)):
                pixels = cv2.resize(scene.image, (width, height))
                self.assertEqual(read_auto(Scene(scene.tokens, pixels)).state, 'unknown')


if __name__ == '__main__':
    unittest.main()
