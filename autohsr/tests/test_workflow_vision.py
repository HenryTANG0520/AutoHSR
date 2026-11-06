"""Observe explicitly selected image files without input or game state."""
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

import cv2
import numpy as np
from PIL import Image

from autohsr.models import Scene, Stopped, Token
from autohsr.workflow_vision import WorkflowVisionError, observe


class WorkflowVisionTests(TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.directory = Path(temp.name)
        self.image = self.directory / 'private-source.png'
        self.template = self.directory / 'private-template.png'
        self.needle = np.full((20, 24, 3), 215, dtype=np.uint8)
        self.needle[3:16, 4:7] = (12, 54, 120)
        self.needle[12:16, 4:21] = (40, 130, 58)
        self.needle[5:10, 11:20] = (20, 40, 180)
        Image.fromarray(self.needle).save(self.template)
        self.source = np.full((72, 96, 3), 215, dtype=np.uint8)
        self.source[14:34, 10:34] = self.needle
        Image.fromarray(self.source).save(self.image)

    def image_result(self, **options):
        return observe(self.image, template=self.template, checkpoint=lambda: None, **options)

    def test_image_matches_at_native_scale_and_only_inside_requested_crop(self):
        yes, no = ({'status': 'success', 'image_found': found} for found in (True, False))
        self.assertEqual(self.image_result(threshold=1), yes)
        self.assertEqual(self.image_result(region=[0, 0, .5, .5]), yes)
        self.assertEqual(self.image_result(region=[.5, 0, 1, 1]), no)
        self.assertEqual(self.image_result(region=[0, 0, .23, .5]), no)
        self.assertEqual(self.image_result(region=[.2, .2, .21, .21]), no)
        jpg = self.image.with_suffix('.jpeg')
        Image.fromarray(self.source).save(jpg, quality=98, subsampling=0)
        self.assertEqual(observe(jpg, template=self.template, checkpoint=lambda: None), yes)

    def test_normalized_high_score_from_faint_noise_is_a_valid_nonmatch(self):
        means = self.needle.mean(axis=(0, 1))
        faint = np.rint(means + (self.needle - means) * .09).astype(np.uint8)
        self.assertGreater(float(cv2.matchTemplate(faint, self.needle, cv2.TM_CCOEFF_NORMED)[0, 0]), .98)
        self.source[14:34, 10:34] = faint
        Image.fromarray(self.source).save(self.image)
        self.assertEqual(self.image_result(), {'status': 'success', 'image_found': False})

    def test_blank_sparse_and_oversize_templates_fail_instead_of_reporting_nonmatch(self):
        solid = np.full((20, 24, 3), (40, 90, 180), dtype=np.uint8)
        sparse = solid.copy()
        sparse[8, 11] = (255, 255, 255)
        for pixels in (solid, sparse):
            Image.fromarray(pixels).save(self.template)
            with self.assertRaisesRegex(WorkflowVisionError, '缺少可区分'):
                self.image_result()
        for size in ((7, 16), (1025, 1025)):
            Image.new('RGB', size).save(self.template)
            with self.assertRaisesRegex(WorkflowVisionError, '总像素'):
                self.image_result()

    def test_transparent_source_does_not_expose_invisible_rgb_to_matching(self):
        transparent = np.zeros((72, 96, 4), dtype=np.uint8)
        transparent[:, :, :3] = self.source
        Image.fromarray(transparent).save(self.image)
        self.assertEqual(self.image_result(), {'status': 'success', 'image_found': False})

    def test_ocr_gets_only_the_crop_and_returns_only_one_flag(self):
        token = Token('委托 已完成', .99, (.1, .15, .8, .6))
        outside = Token('委托', .999, (.8, .1, 1.1, .5))
        weak = Token('委托', .58, (.2, .2, .8, .5))
        reader = Mock()
        reader.read.return_value = Scene([token, outside, weak])
        kwargs = dict(text='委托', region=[.5, .5, 1, 1], threshold=.85, checkpoint=lambda: None)
        with patch('autohsr.workflow_vision.Vision', return_value=reader) as initialize:
            self.assertEqual(observe(self.image, **kwargs), {'status': 'success', 'text_found': False})
            self.assertEqual(observe(self.image, contains=True, **kwargs), {'status': 'success', 'text_found': True})
            reader.read.return_value = Scene([])
            self.assertEqual(observe(self.image, contains=True, **kwargs), {'status': 'success', 'text_found': False})
        self.assertEqual(initialize.call_args.args, (.85,))
        self.assertEqual(reader.read.call_args.args[0].shape, (36, 48, 3))
        self.assertTrue(np.all(reader.read.call_args.args[0] == 215))

    def test_damaged_or_uncertain_sources_report_fixed_private_errors(self):
        original = self.image.read_bytes()
        corrupted_crc = bytearray(original)
        corrupted_crc[29] ^= 1
        for raw in (b'not an image', original[:-12], bytes(corrupted_crc)):
            self.image.write_bytes(raw)
            with self.assertRaises(WorkflowVisionError) as error:
                self.image_result()
            self.assertNotIn(str(self.image), str(error.exception))
            self.assertTrue(error.exception.__suppress_context__)
        self.image.unlink()
        with self.assertRaises(WorkflowVisionError) as error:
            self.image_result()
        self.assertNotIn(self.image.name, str(error.exception))

    def test_invalid_arguments_and_region_fail_before_reading_or_ocr(self):
        for options in (dict(), dict(template=self.template, text='双条件'), dict(text='!!!'),
                        dict(text='文字', threshold=True), dict(text='文字', threshold=float('nan')),
                        dict(text='文字', region=[0, 0, float('inf'), 1]),
                        dict(text='文字', region=[0, 0, .001, .001]), dict(template=self.template, contains=True)):
            with self.subTest(options=options), patch('autohsr.workflow_vision.Vision') as engine:
                with self.assertRaises(WorkflowVisionError):
                    observe(self.image, checkpoint=lambda: None, **options)
                engine.assert_not_called()

    def test_ocr_failure_and_cancel_never_return_an_observation(self):
        reader = Mock()
        reader.read.side_effect = RuntimeError('private-ocr-output')
        with patch('autohsr.workflow_vision.Vision', return_value=reader):
            with self.assertRaises(WorkflowVisionError) as error:
                observe(self.image, text='目标', checkpoint=lambda: None)
            self.assertNotIn('private-ocr-output', str(error.exception))
        reader.reset_mock(side_effect=True)
        reader.read.return_value = Scene([Token('目标', .99, (.1, .1, .9, .8))])

        def stop_after_read():
            if reader.read.called:
                raise Stopped('synthetic stop')

        with (patch('autohsr.workflow_vision.Vision', return_value=reader),
              self.assertRaisesRegex(Stopped, 'synthetic stop')):
            observe(self.image, text='目标', checkpoint=stop_after_read)

    def test_local_sources_are_read_locked_until_matching_finishes(self):
        if os.name != 'nt':
            self.skipTest('requires Windows file sharing')
        replacement = self.directory / 'replacement.png'
        Image.new('RGB', (32, 32)).save(replacement)
        match = cv2.matchTemplate

        def while_matching(*args):
            for path in (self.image, self.template):
                with self.assertRaises(PermissionError):
                    os.replace(replacement, path)
            return match(*args)

        with patch('autohsr.workflow_vision.cv2.matchTemplate', side_effect=while_matching):
            self.assertTrue(self.image_result()['image_found'])

    def test_changed_source_revision_cannot_publish_a_match(self):
        with (patch('autohsr.workflow_vision.file_revision', side_effect=[(1,), (2,), (3,)]),
              self.assertRaisesRegex(WorkflowVisionError, '观察期间发生变化')):
            self.image_result()
