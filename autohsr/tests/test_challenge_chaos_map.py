"""Calibrated UI coordinates with synthetic images. Native replay is separate."""
from dataclasses import replace
import json
from pathlib import Path
import time
import unittest

import cv2
import numpy as np

from autohsr import challenge_pages as pages
from autohsr.challenge_chaos_map import collect_digits
from autohsr.models import Scene, Token


FIXTURE = json.loads((Path(__file__).parent / 'fixtures' / 'challenge_chaos_map_4_6.json').read_bytes())
SIZE = 1920, 1080


def _tokens(name):
    return [Token(text, score, tuple(box)) for text, score, box in FIXTURE[name + '_tokens']]


def _token(text, box, score=.99):
    return Token(text, score, tuple(value / size for value, size in zip(box, SIZE * 2)))


def lobby():
    scene = Scene(_tokens('lobby'), np.full((1080, 1920, 3), 25, np.uint8), captured_at=time.monotonic())
    template = pages._references()['star'][0]
    gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)
    silhouette = cv2.resize(gray, (25, 25), interpolation=cv2.INTER_NEAREST) > 127
    for label in (t for t in scene.tokens if t.text in ('08', '09', '10')):
        left, top, _, bottom = [round(value * size) for value, size in zip(label.box, SIZE * 2)]
        for x in (left + 11, left + 44, left + 77):
            scene.image[bottom + 9:bottom + 34, x:x + 25][silhouette] = [159, 111, 132]
        crystal = np.array([(left - 151, top + 25), (left - 111, top - 90), (left - 38, top - 52),
                            (left - 12, top + 17), (left - 69, top + 102), (left - 124, top + 79)])
        cv2.fillPoly(scene.image, [crystal], (245, 167, 45))
    for label, notice in ((scene.tokens[6], scene.tokens[7]), (scene.tokens[3], scene.tokens[4])):
        x = round(label.center[0] * SIZE[0])
        y = round(notice.box[3] * SIZE[1]) + 6
        outline = np.array([(x - 65, y), (x, y - 101), (x + 65, y)])
        cv2.polylines(scene.image, [outline], True, (190, 190, 190), 3)
    locked_eleven = scene.tokens[6]
    x, y = [round(value * size) for value, size in zip(locked_eleven.center, SIZE)]
    cv2.circle(scene.image, (x, y + 6), 110, (218, 218, 218), 3)
    return scene


def setup():
    scene = Scene(_tokens('setup'), np.full((1080, 1920, 3), [150, 58, 95], np.uint8),
                  captured_at=time.monotonic())
    for x in (635, 669, 703, 736, 769):
        cv2.rectangle(scene.image, (x, 125), (x + 26, 152), (240, 240, 240), 2)
    cv2.line(scene.image, (803, 137), (832, 137), (240, 240, 240), 2)
    cv2.line(scene.image, (818, 124), (818, 152), (240, 240, 240), 2)
    for y in (754, 868):
        for x in (1376, 1469, 1561, 1653):
            cv2.circle(scene.image, (x, y), 36, (220, 220, 220), 3)
    digits = iter((Token('1', .99, (0, 0, 1, 1)), Token('2', .99, (0, 0, 1, 1))))
    collect_digits(scene, .65, lambda _: next(digits))
    return scene


class ChaosCurrentMapTests(unittest.TestCase):
    def test_gray_locks_halo_and_only_the_calibrated_text_target(self):
        observed = pages.observe(lobby())
        self.assertEqual((observed.kind, observed.mode, observed.level), ('lobby', pages.MODE, None))
        self.assertEqual([(row['level'], row['available'], row['stars']) for row in observed.basis['levels']],
                         [(8, None, 0), (9, None, 0), (10, True, 0), (11, False, None), (12, False, None)])
        self.assertTrue(observed.basis['levels'][3]['lock_graphics']['ring_observed'])
        self.assertEqual([(intent, token.text) for intent, token in observed.targets], [('select_level', '10')])

    def test_ambiguous_or_unassociated_map_signals_never_offer_the_target(self):
        for token in (_token('未解锁', (918, 700, 980, 723)), _token('购买确认', (770, 520, 950, 550), .70),
                      _token('星启模式', (1580, 127, 1690, 151)), _token('11', (919, 647, 977, 680))):
            with self.subTest(text=token.text):
                scene = lobby()
                scene.tokens.append(token)
                self.assertEqual(pages.observe(scene).targets, ())

    def test_crystal_or_ocr_without_gray_stars_cannot_supply_ten(self):
        scene = lobby()
        scene.image[690:735, 914:1033] = 25
        observed = pages.observe(scene)
        self.assertEqual(observed.kind, 'lobby')
        self.assertIsNone(observed.basis['levels'][2]['available'])
        self.assertEqual(observed.targets, ())

    def test_local_read_can_recover_a_missing_locked_number_only_above_its_caption(self):
        scene = lobby()
        scene.tokens = [token for token in scene.tokens if token.text != '11']
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        digits = iter((Token('11', .99, (0, 0, 1, 1)), Token('12', .99, (0, 0, 1, 1))))
        collect_digits(scene, .65, lambda _: next(digits))
        observed = pages.observe(scene)
        self.assertEqual(observed.basis['levels'][3]['label_source'], 'lock_number_ocr')
        self.assertFalse(observed.basis['levels'][3]['available'])

    def test_setup_requires_real_title_shape_and_both_four_slot_groups(self):
        scene = setup()
        observed = pages.observe(scene)
        self.assertEqual((observed.kind, observed.mode, observed.level), ('team_setup', pages.MODE, 10))
        self.assertEqual([len(node['visible_slot_boxes']) for node in observed.basis['nodes']], [4, 4])
        self.assertEqual(observed.basis['team_feedback'], 'unknown')
        self.assertEqual(observed.targets, ())
        scene.image[820:916, 1605:1701] = [150, 58, 95]
        self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_short_screen_ocr_never_accepts_a_visible_trailing_stroke_or_obstruction(self):
        scene = setup()
        cv2.line(scene.image, (840, 137), (866, 137), (243, 243, 243), 3)
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = setup()
        scene.image[125:153, 838:876] = 0
        self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_setup_rejects_wrong_period_level_foreign_title_and_conflicting_node(self):
        for text in ('物竞天择其十一', '物竞天择其十二', '取象为文其四'):
            with self.subTest(text=text):
                scene = setup()
                scene.tokens[3] = replace(scene.tokens[3], text=text)
                self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = setup()
        scene.tokens.append(_token('3', (655, 856, 666, 881)))
        self.assertEqual(pages.observe(scene).kind, 'unknown')
