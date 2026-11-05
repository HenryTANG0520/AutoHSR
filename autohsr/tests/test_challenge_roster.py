"""Original-template collages and injected matches, not real-page calibration."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr import challenge_roster as roster
from autohsr.models import Scene


def candidate_scene(*identities, width=1920, positions=None):
    """Invented list layout made only from the pinned full original portraits."""
    image = np.full((1080, 1920, 3), 12, np.uint8)
    originals = {name: original for name, original, _ in roster._references()}
    for index, identity in enumerate(identities):
        x, y = positions[index] if positions else (80 + index % 3 * 145, 180 + index // 3 * 150)
        bitmap = originals[identity]
        image[y:y + bitmap.shape[0], x:x + bitmap.shape[1]] = bitmap
    if width != 1920:
        image = cv2.resize(image, (width, round(1080 * width / 1920)),
                           interpolation=cv2.INTER_AREA if width < 1920 else cv2.INTER_NEAREST)
    return Scene([], image, captured_at=time.monotonic())


class ChallengeRosterTests(unittest.TestCase):
    def clear_bank(self):
        roster._references.cache_clear()
        roster._scaled_references.cache_clear()

    def test_original_105_template_manifest_and_blobs_are_checked(self):
        bank = roster._references()
        self.assertEqual(len(bank), 105)
        self.assertEqual(len({identity for identity, _, _ in bank}), 105)
        for identity, image, source in bank:
            raw = (roster.ASSET_ROOT / source['file']).read_bytes()
            self.assertEqual(source['file'], identity + '.png')
            self.assertEqual(hashlib.sha256(raw).hexdigest(), source['sha256'])
            self.assertEqual(hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest(), source['git_blob'])
            self.assertEqual(image.dtype, np.uint8)

    def test_original_candidates_have_only_asset_evidence_and_no_input_authority(self):
        value = roster.observe_candidates(candidate_scene('Acheron', 'Firefly'))
        self.assertEqual(value['status'], 'observed')
        self.assertEqual({item['asset_id'] for item in value['candidates']}, {'Acheron', 'Firefly'})
        self.assertEqual(value['templates_checked'], 105)
        self.assertEqual(value['source']['crop_xywh'], [30, 115, 530, 810])
        for key in ('ownership', 'availability', 'selected', 'complete'):
            self.assertEqual(value[key], 'unknown')
        self.assertIs(value['execution_supported'], False)
        self.assertIs(value['full_real_page_calibrated'], False)
        self.assertNotIn('targets', value)
        self.assertNotIn('token', value)
        for item in value['candidates']:
            self.assertEqual(set(item), {'asset_id', 'box', 'score', 'template'})
            self.assertTrue(item['template']['source_path'].endswith(item['asset_id'] + '.png'))
        json.dumps(value, allow_nan=False)

    def test_half_and_double_resolution_keep_the_same_normalized_candidate_box(self):
        boxes = []
        for width in (960, 1920, 3840):
            with self.subTest(width=width):
                value = roster.observe_candidates(candidate_scene('Acheron', width=width))
                self.assertEqual(value['status'], 'observed')
                self.assertEqual([item['asset_id'] for item in value['candidates']], ['Acheron'])
                boxes.append(value['candidates'][0]['box'])
        for box in boxes[1:]:
            self.assertTrue(np.allclose(box, boxes[0], atol=2 / 960))

    def test_full_edge_card_is_distinct_from_cut_off_or_occluded_portrait(self):
        near = candidate_scene('Acheron', positions=[(32, 117)])
        self.assertEqual(roster.observe_candidates(near)['candidates'][0]['asset_id'], 'Acheron')
        cut = candidate_scene('Acheron', positions=[(10, 180)])
        self.assertEqual(roster.observe_candidates(cut)['candidates'], [])
        covered = candidate_scene('Acheron')
        covered.image[180:230, 80:135] = 12
        self.assertEqual(roster.observe_candidates(covered)['candidates'], [])

    def test_same_unit_variants_are_not_collapsed_into_one_asset_identity(self):
        names = ('March7th', 'March7thImaginary', 'March7thNascentSpring')
        value = roster.observe_candidates(candidate_scene(*names))
        self.assertEqual(value['status'], 'observed')
        self.assertEqual({item['asset_id'] for item in value['candidates']}, set(names))
        self.assertEqual(value['selected'], 'unknown')
        self.assertEqual(value['complete'], 'unknown')

    def test_overlapping_two_identities_are_ambiguous_instead_of_highest_winner(self):
        scene = candidate_scene('Acheron')
        original = next(item for item in roster._scaled_references(1920) if item[0] == 'Acheron')
        duplicate = ('Firefly', original[1], original[2], dict(original[3]))
        # An injected conflicting identity tests the resolver. Production
        # loaders still require every original's own manifest SHA and Git blob.
        with patch.object(roster, '_scaled_references', return_value=(original, duplicate)):
            value = roster.observe_candidates(scene)
        self.assertEqual(value['status'], 'ambiguous')
        self.assertEqual(value['candidates'], [])
        self.assertEqual(value['ambiguities'][0]['asset_ids'], ['Acheron', 'Firefly'])
        self.assertEqual(len(value['ambiguities'][0]['matches']), 2)

    def test_close_rival_below_positive_threshold_still_prevents_false_unique_identity(self):
        def item(identity, score, box):
            return dict(asset_id=identity, score=score, box=box, template={})
        a = item('Acheron', .970, [0, 0, .1, .1])
        b = item('Firefly', .950, [.01, .01, .11, .11])
        clear = item('RuanMei', .999, [.2, .2, .3, .3])
        candidates, ambiguous = roster._group([a, b, clear])
        self.assertEqual(candidates, [clear])
        self.assertEqual(ambiguous[0]['asset_ids'], ['Acheron', 'Firefly'])

    def test_full_template_competitor_is_not_discarded_even_with_large_score_gap(self):
        first = dict(asset_id='Acheron', score=.999, box=[0, 0, .1, .1], template={})
        second = dict(asset_id='Firefly', score=.936, box=[.01, .01, .11, .11], template={})
        candidates, ambiguous = roster._group([first, second])
        self.assertEqual(candidates, [])
        self.assertEqual(ambiguous[0]['matches'], [first, second])

    def test_outside_list_does_not_become_a_candidate_or_team_feedback(self):
        value = roster.observe_candidates(candidate_scene('Acheron', positions=[(800, 400)]))
        self.assertEqual(value['status'], 'unknown')
        self.assertEqual(value['candidates'], [])
        self.assertEqual(value['complete'], 'unknown')
        apocalypse = roster.observe_candidates(candidate_scene('Acheron'), mode='apocalyptic_shadow')
        self.assertEqual(apocalypse['source']['path'], 'tasks/challenge/apocalyptic.py')
        self.assertEqual(apocalypse['source']['crop_xywh'], [30, 110, 550, 850])

    def test_stale_invalid_missing_or_tampered_references_return_bounded_unknown(self):
        scene = candidate_scene('Acheron')
        stale = deepcopy(scene);stale.captured_at -= 9
        for invalid in (stale, Scene([]), SimpleNamespace(image=np.zeros((4, 4, 3), np.uint8), captured_at=time.monotonic())):
            with self.subTest(invalid=type(invalid).__name__):
                self.assertEqual(roster.observe_candidates(invalid)['status'], 'unknown')
        manifest = (roster.ASSET_ROOT / 'sources.json').read_bytes()
        self.addCleanup(self.clear_bank)
        for kind in ('missing', 'manifest', 'template'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                if kind != 'missing':
                    (root / 'sources.json').write_bytes(manifest if kind == 'template' else manifest + b' ')
                if kind == 'template':
                    (root / 'Acheron.png').write_bytes(b'tampered synthetic reference')
                self.clear_bank()
                scene.captured_at = time.monotonic()
                with patch.object(roster, 'ASSET_ROOT', root):
                    value = roster.observe_candidates(scene)
                self.assertEqual(value['status'], 'unknown')
                self.assertEqual(value['candidates'], [])
                self.assertNotIn(folder, json.dumps(value))
        self.clear_bank()

    def test_scan_expiring_during_work_discards_candidate_authority_and_unsupported_mode_is_unknown(self):
        scene = candidate_scene('Acheron');clock = [scene.captured_at]
        real = roster._matches
        def scan(*args):
            value = real(*args);clock[0] += 9
            return value
        with patch.object(roster, 'time', SimpleNamespace(monotonic=lambda: clock[0])), patch.object(roster, '_matches', side_effect=scan):
            value = roster.observe_candidates(scene)
        self.assertEqual(value['status'], 'unknown')
        self.assertEqual(value['reason'], 'scene_expired_during_scan')
        self.assertEqual(value['candidates'], [])
        self.assertEqual(roster.observe_candidates(scene, mode='daily')['reason'], 'unsupported_mode')


if __name__ == '__main__':
    unittest.main()
