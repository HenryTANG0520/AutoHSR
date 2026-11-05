"""Pure fake-window UI capture checks; no game, native window, or real OCR."""
from __future__ import annotations

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from tools import interface_capture as capture


SECRET = 'PRIVATE_ACCOUNT_987654321_AND_INSTALL_PATH'


def token(text, box, score=.9):
    return SimpleNamespace(text=text, box=box, score=score)


def normal_tokens():
    return [token('角色列表', (.05, .18, .30, .23)),
            token('预设编队', (.05, .28, .30, .33)),
            token('UID 987654321', (.01, .95, .25, .99))]


def safe_tokens():
    return [token('角色列表', (.05, .10, .30, .20)), token('等级80', (.10, .40, .30, .50))]


def client(_executable):
    return dict(version='4.6', full_version='4.6.0', kind='launcher_game_version',
                executable=SECRET, source=SECRET, sha256=SECRET)


class FakeWindow:
    def __init__(self):
        # Distinct nonzero pixels make removed bands and masks measurable.
        self.image = np.arange(100*200*3, dtype=np.uint32).reshape(100, 200, 3).astype(np.uint8)
        self.geometry = SimpleNamespace(width=200, height=100)
        self.capture_count = 0
        self.version_count = 0

    def capture(self):
        self.capture_count += 1
        return self.image, self.geometry

    def current_executable(self):
        self.version_count += 1
        return SECRET

    def __getattr__(self, name):
        if name in ('focus', 'click', 'key', 'drag', 'move', 'scroll', 'send', 'release_inputs', 'launch'):
            raise AssertionError('read-only capture attempted input or focus')
        raise AttributeError(name)


class FakeVision:
    def __init__(self, responses=None, mutate=False):
        self.responses = list(responses if responses is not None else (normal_tokens(), safe_tokens()))
        self.images = []
        self.mutate = mutate

    def read(self, image, geometry=None):
        self.images.append(image.copy())
        if self.mutate:
            image[:] = 255
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return SimpleNamespace(tokens=value)


class InterfaceCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.window = FakeWindow()
        self.vision = FakeVision()

    def run_capture(self, **kwargs):
        return capture.capture_interface(self.window, output_root=self.root,
            vision_factory=lambda: self.vision, client_reader=client, **kwargs)

    def directory(self, result):
        return self.root/result['capture_id']

    def manifest(self, result):
        return json.loads((self.directory(result)/'manifest.json').read_text('utf-8'))

    def public_pixels(self, result):
        return cv2.imdecode(np.frombuffer((self.root/result['image']['file']).read_bytes(), np.uint8), cv2.IMREAD_COLOR)

    def test_capture_preserves_original_and_ocr_but_returns_only_safe_metadata(self):
        result = self.run_capture(label='preset_1')
        self.assertEqual(result['status'], 'ready')
        self.assertEqual((self.window.capture_count, self.window.version_count), (1, 1))
        self.assertIs(result['input_sent'], False)
        self.assertIs(result['focus_requested'], False)
        self.assertIs(result['navigation_performed'], False)
        public = json.dumps(result, ensure_ascii=False)
        metadata = self.manifest(result)
        self.assertNotIn(SECRET, public)
        self.assertNotIn('987654321', public)
        self.assertNotIn('UID', public)
        self.assertNotIn(SECRET, json.dumps(metadata))
        self.assertEqual(result['game_client'], dict(status='verified', version='4.6',
            full_version='4.6.0', kind='launcher_game_version'))
        raw_path = self.directory(result)/'private/raw.png'
        raw_pixels = cv2.imdecode(np.frombuffer(raw_path.read_bytes(), np.uint8), cv2.IMREAD_COLOR)
        np.testing.assert_array_equal(raw_pixels, self.window.image)
        ocr = (self.directory(result)/'private/ocr.json').read_text('utf-8')
        self.assertIn('987654321', ocr)  # Kept locally, never copied into the public result.
        self.assertEqual(result['image']['width'], 200)
        self.assertEqual(result['image']['height'], 78)
        pixels = self.public_pixels(result)
        np.testing.assert_array_equal(pixels[30, 20], self.window.image[42, 20])
        self.assertTrue(np.all(pixels[:24, 100:] == 0))  # Phone profile excluded too.
        np.testing.assert_array_equal(pixels, self.vision.images[1])

    def test_png_ocr_and_manifest_hashes_bind_the_actual_local_files(self):
        result = self.run_capture()
        metadata = self.manifest(result)
        for source in metadata['sources'].values():
            data = (self.directory(result)/source['file']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), source['sha256'])
        manifest = (self.directory(result)/'manifest.json').read_bytes()
        self.assertEqual(hashlib.sha256(manifest).hexdigest(), result['metadata']['sha256'])
        self.assertEqual((self.directory(result)/'manifest.sha256').read_text().strip(), result['metadata']['sha256'])
        checked = json.loads((self.directory(result)/'private/public-ocr-check.json').read_text('utf-8'))
        self.assertEqual(checked['source_sha256'], result['image']['sha256'])
        original_ocr = json.loads((self.directory(result)/'private/ocr.json').read_text('utf-8'))
        self.assertEqual(original_ocr['source_sha256'], metadata['sources']['raw']['sha256'])

    def test_uid_at_unexpected_middle_row_is_masked_before_model_image(self):
        for parts in ([token('UID:987654321', (.05, .45, .35, .49), .01)],
                      [token('U', (.05, .45, .07, .49)), token('I', (.08, .45, .09, .49)),
                       token('D', (.10, .45, .12, .49)), token('987', (.13, .45, .18, .49)),
                       token('654', (.19, .45, .24, .49)), token('321', (.25, .45, .30, .49))],
                      [token('９８７６５４３２１', (.05, .45, .35, .49))]):
            with self.subTest(parts=len(parts)):
                self.vision = FakeVision([normal_tokens()+parts, safe_tokens()])
                result = self.run_capture()
                self.assertEqual(result['status'], 'ready')
                self.assertTrue(np.all(self.public_pixels(result)[33:37, :] == 0))

    def test_explicit_full_crop_cannot_restore_top_bottom_or_profile(self):
        result = self.run_capture(crop='0,0,1,1')
        self.assertEqual(self.manifest(result)['redaction']['crop_px'], [0, 12, 200, 90])
        self.vision = FakeVision()
        result = self.run_capture(crop=(.1, .2, .4, .6))
        self.assertEqual(self.public_pixels(result).shape, (40, 60, 3))
        np.testing.assert_array_equal(self.public_pixels(result), self.window.image[20:60, 20:80])

    def test_sensitive_second_pass_blocks_image_path_and_keeps_source(self):
        self.vision = FakeVision([normal_tokens(), [token('UID987654321', (.2, .4, .5, .5))]])
        result = self.run_capture()
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['reason'], 'redaction_check_sensitive')
        self.assertNotIn('image', result)
        self.assertFalse((self.directory(result)/'public').exists())
        self.assertTrue((self.directory(result)/'private/raw.png').is_file())
        self.assertTrue((self.directory(result)/'private/public-ocr-check.json').is_file())
        self.assertNotIn('987654321', json.dumps(result))

    def test_empty_or_invalid_ocr_never_produces_public_image(self):
        invalid = token('UID987654321', (float('nan'), .4, .5, .5))
        cases = ([[], safe_tokens()], [normal_tokens(), []], [[invalid], safe_tokens()],
                 [normal_tokens(), [invalid]], [RuntimeError(SECRET), safe_tokens()])
        for responses in cases:
            with self.subTest(case=type(responses[0]).__name__):
                self.vision = FakeVision(responses)
                result = self.run_capture()
                self.assertEqual(result['status'], 'blocked')
                self.assertNotIn('image', result)
                self.assertNotIn(SECRET, json.dumps(result))
                self.assertFalse((self.directory(result)/'public').exists())

    def test_login_fields_are_local_only_even_if_cropped_ocr_would_be_clean(self):
        self.vision = FakeVision([normal_tokens()+[token('扫码登录', (.4, .5, .6, .6))], safe_tokens()])
        result = self.run_capture()
        self.assertEqual(result['reason'], 'sensitive_page')
        self.assertNotIn('image', result)
        self.assertEqual(len(self.vision.images), 1)

    def test_login_fields_found_only_by_cropped_ocr_block_public_image(self):
        for label in ('扫码登录', '验证码：'):
            with self.subTest(label=label):
                self.vision = FakeVision([normal_tokens(), safe_tokens()+[token(label, (.4, .5, .6, .6))]])
                result = self.run_capture()
                self.assertEqual(result['status'], 'blocked')
                self.assertEqual(result['reason'], 'sensitive_page')
                self.assertNotIn('image', result)
                directory = self.directory(result)
                self.assertFalse((directory/'public').exists())
                self.assertTrue((directory/'private/raw.png').is_file())
                checked = (directory/'private/public-ocr-check.json').read_text('utf-8')
                self.assertIn(label, checked)
                self.assertNotIn(label, json.dumps(result, ensure_ascii=False))

    def test_unknown_or_new_client_version_does_not_force_a_read_only_failure(self):
        for value, expected in ((dict(version='5.0', full_version='5.0.0', kind='launcher_game_version'), 'verified'),
                                (dict(version='2019.4', full_version='2019.4.3', kind='exe_version'), 'unknown'),
                                ({'source': SECRET}, 'unknown')):
            with self.subTest(version=expected):
                self.vision = FakeVision()
                result = capture.capture_interface(self.window, output_root=self.root,
                    vision_factory=lambda: self.vision, client_reader=lambda _path: value)
                self.assertEqual(result['status'], 'ready')
                self.assertEqual(result['game_client']['status'], expected)
                self.assertNotIn(SECRET, json.dumps(result))

    def test_ocr_cannot_mutate_the_preserved_or_verified_pixels(self):
        self.vision = FakeVision(mutate=True)
        original = self.window.image.copy()
        result = self.run_capture()
        self.assertEqual(result['status'], 'ready')
        np.testing.assert_array_equal(self.window.image, original)
        np.testing.assert_array_equal(self.public_pixels(result), self.vision.images[1])

    def test_repeated_label_creates_new_evidence_without_overwriting(self):
        first = self.run_capture()
        first_raw = (self.directory(first)/'private/raw.png').read_bytes()
        self.vision = FakeVision()
        second = self.run_capture()
        self.assertNotEqual(first['capture_id'], second['capture_id'])
        self.assertEqual((self.directory(first)/'private/raw.png').read_bytes(), first_raw)

    def test_invalid_crop_is_rejected_before_accessing_window(self):
        for crop in ('0,nan,1,1', (0, .95, 1, 1), (0, 0, 2, 1), (1, 0, 0, 1)):
            with self.subTest(crop=crop):
                with self.assertRaises(capture.CaptureRejected):
                    self.run_capture(crop=crop)
        self.assertEqual(self.window.capture_count, 0)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_write_failure_never_returns_an_image_path(self):
        original_write = capture._write
        def fail_public(path, raw):
            if path.parent.name == 'public':
                raise OSError(SECRET)
            original_write(path, raw)
        with patch.object(capture, '_write', side_effect=fail_public):
            result = self.run_capture()
        self.assertEqual(result['status'], 'blocked')
        self.assertNotIn('image', result)
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertTrue((self.directory(result)/'private/raw.png').is_file())

    def test_cli_fake_window_has_safe_output_and_no_focus_or_input(self):
        output = io.StringIO()
        with redirect_stdout(output):
            code = capture.main(['--output-root', str(self.root), '--label', 'currency_lobby'],
                window_factory=lambda: self.window, vision_factory=lambda: self.vision, client_reader=client)
        self.assertEqual(code, 0)
        value = json.loads(output.getvalue())
        self.assertEqual(value['status'], 'ready')
        self.assertNotIn(SECRET, output.getvalue())
        self.assertNotIn('987654321', output.getvalue())
        self.assertEqual(self.window.capture_count, 1)

    def test_cli_capture_or_window_failure_does_not_expose_exception(self):
        output = io.StringIO()
        def missing():
            raise RuntimeError(SECRET)
        with redirect_stdout(output):
            code = capture.main(['--output-root', str(self.root)], window_factory=missing)
        self.assertEqual(code, 1)
        value = json.loads(output.getvalue())
        self.assertNotIn('image', value)
        self.assertNotIn(SECRET, output.getvalue())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_capture_guard_failure_does_not_try_focus_or_read_client(self):
        def lost_focus():
            self.window.capture_count += 1
            raise RuntimeError(SECRET)
        self.window.capture = lost_focus
        result = self.run_capture()
        self.assertEqual(result['status'], 'blocked')
        self.assertNotIn('image', result)
        self.assertEqual((self.window.capture_count, self.window.version_count), (1, 0))
        self.assertNotIn(SECRET, json.dumps(result))
        self.assertFalse((self.directory(result)/'public').exists())

    def test_manifest_write_failure_suppresses_public_image_in_cli_result(self):
        original_write = capture._write
        def fail_manifest(path, raw):
            if path.name == 'manifest.json':
                raise OSError(SECRET)
            original_write(path, raw)
        output = io.StringIO()
        with patch.object(capture, '_write', side_effect=fail_manifest), redirect_stdout(output):
            code = capture.main(['--output-root', str(self.root)], window_factory=lambda: self.window,
                vision_factory=lambda: self.vision, client_reader=client)
        self.assertEqual(code, 1)
        self.assertNotIn('image', json.loads(output.getvalue()))
        self.assertNotIn(SECRET, output.getvalue())


if __name__ == '__main__':
    unittest.main()
