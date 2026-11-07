from unittest import TestCase

import cv2
import numpy as np

from autohsr.models import Scene
from autohsr.support_gift_observe import _template, gift_receipt, observe_support_gift
from autohsr.vision import Vision


def with_support_gift(image, *positions, remove_badge=False):
    image = image.copy()
    original = _template().copy()
    if remove_badge:
        original[:15, 44:, :3] = (80, 156, 205)
    width = image.shape[1]
    sample = cv2.resize(original, None, fx=width / 1920, fy=width / 1920)
    height, size = sample.shape[:2]
    for x, y in positions:
        left, top = round(x * width), round(y * image.shape[0])
        patch = image[top:top + height, left:left + size]
        alpha = sample[:, :, 3:4].astype(float) / 255
        patch[:] = sample[:, :, :3] * alpha + patch * (1 - alpha)
    return image


class SupportGiftObservationTests(TestCase):
    def picture(self, width, *positions, remove_badge=False):
        image = np.full((width * 9 // 16, width, 3), 47, dtype=np.uint8)
        return Scene([], with_support_gift(image, *positions, remove_badge=remove_badge))

    def test_matches_reference_in_two_frames_without_proving_claimability(self):
        vision = Vision.__new__(Vision)
        for width in (960, 1920):
            with self.subTest(width=width):
                pair = [self.picture(width, (.77, .23)) for _ in range(2)]
                result = observe_support_gift(pair, vision)
                self.assertEqual(result, dict(indicator='visible', claimable_state='unknown',
                                              claim_receipt_status='not_observed'))
                self.assertEqual(gift_receipt(dict(target='visa_characters', page_verified=True,
                    client_version='4.6.0', support_gift_observation=result)), result)

    def test_hidden_shifted_duplicate_or_missing_badge_never_proves_indicator(self):
        vision = Vision.__new__(Vision)
        first = self.picture(1920, (.77, .23))
        for second in (self.picture(1920), self.picture(1920, (.81, .23)),
                       self.picture(1920, (.77, .23), (.84, .23)),
                       self.picture(1920, (.77, .23), remove_badge=True)):
            self.assertEqual(observe_support_gift((first, second), vision)['indicator'], 'unknown')
