"""Exercise seams on synthetic lists, independently of game or capture code."""

import unittest

import cv2
import numpy as np

from autohsr.reward_guide_stitch import stitch_reward_guide


def _calendar(rows=396):
    image = np.full((rows, 192, 3), (241, 240, 242), np.uint8)
    for i, y in enumerate(range(0, rows - 16, 36)):
        cv2.line(image, (0, y), (191, y), (204, 203, 209), 1)
        cv2.rectangle(image, (5, y + 5), (33, y + 30), (65 + i * 11, 91, 159 - i * 8), -1)
        cv2.rectangle(image, (147, y + 9), (185, y + 26), (114, 129, 149), -1)
        cv2.putText(image, f'Event {i + 1}', (39, y + 20), cv2.FONT_HERSHEY_SIMPLEX,
                    .43, (55, 62, 69), 1, cv2.LINE_AA)
    return image


class RewardGuideStitchTests(unittest.TestCase):
    def test_stitches_exactly_three_crops_without_repeating_seams(self):
        image = _calendar()
        frames = (image[:176], image[61:237], image[157:333])
        result = stitch_reward_guide(frames)
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.overlap_rows, (115, 80))
        np.testing.assert_array_equal(result.image, image[:333])
        self.assertFalse(np.shares_memory(result.image, image))

    def test_crop_view_and_small_brightness_drift_are_supported(self):
        image = _calendar()
        left = image[:176, 2:-2]
        right = cv2.add(image[68:244], (2, 2, 2, 0))[:, 2:-2]
        self.assertFalse(left.flags.c_contiguous)
        result = stitch_reward_guide([left, right])
        self.assertEqual(result.status, 'ok')
        self.assertEqual(result.overlap_rows, (108,))
        np.testing.assert_array_equal(result.image, np.concatenate((left, right[108:])))
        self.assertFalse(np.shares_memory(stitch_reward_guide([left]).image, left))

    def test_duplicate_of_current_or_earlier_crop_stops_without_an_image(self):
        image = _calendar()
        first, second = image[:176], image[61:237]
        for frames, seams in (([first, first], ()), ([first, cv2.add(first, (2, 2, 2, 0))], ()),
                              ([first, second, first], (115,))):
            with self.subTest(seams=seams):
                result = stitch_reward_guide(frames)
                self.assertEqual(result.status, 'duplicate')
                self.assertEqual(result.overlap_rows, seams)
                self.assertIsNone(result.image)

    def test_repeated_rows_with_multiple_good_offsets_are_ambiguous(self):
        card = _calendar()[:36]
        repeated = np.tile(card, (4, 1, 1))
        first = np.concatenate((_calendar()[111:127], repeated))
        second = np.concatenate((repeated, _calendar()[126:142]))
        result = stitch_reward_guide([first, second])
        self.assertEqual(result.status, 'ambiguous')
        self.assertIsNone(result.image)

    def test_one_plausible_offset_in_each_direction_is_ambiguous(self):
        image = _calendar()
        first, second = image[:72], image[72:144]
        result = stitch_reward_guide([np.concatenate((first, second)), np.concatenate((second, first))])
        self.assertEqual(result.status, 'ambiguous')
        self.assertIsNone(result.image)

    def test_wrong_direction_and_missing_or_too_short_overlap_stop(self):
        image = _calendar()
        for frames, status in (([image[61:237], image[:176]], 'wrong_direction'),
                               ([image[:176], image[176:352]], 'no_overlap'),
                               ([image[:176], image[162:338]], 'no_overlap'),
                               ([image[:176], np.roll(image[61:237], 2, axis=1)], 'no_overlap')):
            with self.subTest(status=status):
                result = stitch_reward_guide(frames)
                self.assertEqual(result.status, status)
                self.assertIsNone(result.image)

    def test_plausible_edge_anchors_with_changed_middle_do_not_authorize_a_seam(self):
        image = _calendar()
        first, second = image[:176], image[61:237].copy()
        second[51:60, 70:95] = (91, 66, 34)
        result = stitch_reward_guide([first, second])
        self.assertEqual(result.status, 'no_overlap')
        self.assertIsNone(result.image)

    def test_stationary_vertical_stripes_do_not_establish_scroll(self):
        first = np.full((176, 192, 3), 233, np.uint8)
        first[:, 40:70] = 90
        second = first.copy()
        first[:16] = 131
        second[-16:] = 155
        result = stitch_reward_guide([first, second])
        self.assertEqual(result.status, 'no_overlap')
        self.assertIsNone(result.image)

    def test_third_crop_must_agree_with_oldest_shared_pixels(self):
        image = _calendar()
        second = cv2.add(image[61:237], (3, 3, 3, 0))
        third = cv2.add(image[122:298], (6, 6, 6, 0))
        self.assertEqual(stitch_reward_guide([second, third]).status, 'ok')
        result = stitch_reward_guide([image[:176], second, third])
        self.assertEqual(result.status, 'inconsistent')
        self.assertEqual(result.overlap_rows, (115,))
        self.assertIsNone(result.image)

    def test_malformed_crops_and_bounds(self):
        crop = _calendar()[:176]
        for frames in ([], crop, [crop[:, :, 0]], [crop.astype(np.float32)],
                       [crop[:63]], [crop, crop[:, :-1]]):
            with self.subTest(kind=type(frames).__name__):
                self.assertEqual(stitch_reward_guide(frames).status, 'invalid')
        edge = np.zeros((64, 4097, 3), np.uint8)
        oversized_total = np.zeros((1600, 2600, 3), np.uint8)
        for frames in ([crop] * 4, [edge], [oversized_total] * 3):
            with self.subTest(shape=frames[0].shape, count=len(frames)):
                result = stitch_reward_guide(frames)
                self.assertEqual(result.status, 'limit')
                self.assertIsNone(result.image)
