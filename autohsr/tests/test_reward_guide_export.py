"""Exercise local PNG export and actual Windows publication sharing rules."""

from contextlib import contextmanager
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np
from PIL import Image, PngImagePlugin

from autohsr import reward_guide_export as service
from autohsr.models import Stopped
from autohsr.tests.test_reward_guide_stitch import _calendar


class RewardGuideExportTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.output = self.root / 'output'
        self.output.mkdir()
        self.target = self.output / 'calendar.png'
        self.image = _calendar()
        self.first, self.second = self.root / 'page1.png', self.root / 'page2.PNG'
        self.write(self.first, self.image[:176])
        self.write(self.second, self.image[61:237])

    def write(self, path, pixels, **kwargs):
        Image.fromarray(pixels[:, :, ::-1]).save(path, format='PNG', **kwargs)

    def export(self, sources=None, **kwargs):
        return service.export_reward_guide([self.first, self.second] if sources is None else sources,
                                           self.target, **kwargs)

    def assert_unpublished(self, result, status, overlaps=()):
        self.assertEqual(result, dict(status=status, overlap_rows=list(overlaps), width=None, height=None))
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_single_and_three_ordered_crops_have_exact_pixels_and_anonymous_receipts(self):
        third = self.root / 'last.png'
        self.write(third, self.image[157:333])
        originals = {path: path.read_bytes() for path in (self.first, self.second, third)}
        for inputs, height, seams in (([self.first], 176, []), ([self.first, self.second, third], 333, [115, 80])):
            with self.subTest(count=len(inputs)):
                result = self.export(inputs)
                self.assertEqual(result, dict(status='ok', overlap_rows=seams, width=192, height=height))
                self.assertNotIn(str(self.root), json.dumps(result))
                with Image.open(self.target) as exported:
                    self.assertEqual(exported.format, 'PNG')
                    np.testing.assert_array_equal(np.asarray(exported)[:, :, ::-1], self.image[:height])
                self.target.unlink()
        self.assertEqual({path: path.read_bytes() for path in originals}, originals)
        self.assertEqual(list(self.output.iterdir()), [])

    def test_opaque_alpha_is_accepted_and_source_metadata_is_discarded(self):
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('unrelated-source-comment', 'test metadata')
        image = Image.fromarray(self.image[:176, :, ::-1]).convert('RGBA')
        image.save(self.first, pnginfo=metadata)
        self.assertEqual(self.export()['status'], 'ok')
        with Image.open(self.target) as exported:
            self.assertEqual(exported.mode, 'RGB')
            self.assertNotIn('unrelated-source-comment', exported.info)

    def test_invalid_png_variants_and_bounds_leave_no_output(self):
        original = self.second.read_bytes()
        image = Image.fromarray(self.image[61:237, :, ::-1])
        image.save(self.second, format='JPEG')
        self.assert_unpublished(self.export(), 'invalid_source')
        self.second.write_bytes(original[:-1] + b'\x00')
        self.assert_unpublished(self.export(), 'invalid_source')
        bad = bytearray(original)
        bad[bad.index(b'IDAT') + 5] ^= 1
        self.second.write_bytes(bad)
        self.assert_unpublished(self.export(), 'invalid_source')
        translucent = image.copy()
        translucent.putalpha(200)
        translucent.save(self.second)
        self.assert_unpublished(self.export(), 'invalid_source')
        image.save(self.second, save_all=True, append_images=[image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)])
        self.assert_unpublished(self.export(), 'invalid_source')
        Image.new('RGB', (4097, 64)).save(self.second)
        self.assert_unpublished(self.export(), 'limit')
        self.assert_unpublished(self.export([self.first] * 4), 'limit')
        with patch.object(service, 'MAX_BYTES', 128):
            self.assert_unpublished(self.export(), 'limit')

    def test_wrong_order_duplicates_and_ambiguous_seams_leave_no_png(self):
        self.assert_unpublished(self.export([self.second, self.first]), 'wrong_direction')
        self.assert_unpublished(self.export([self.first, self.second, self.first]), 'duplicate', (115,))
        repeated = np.tile(self.image[:36], (4, 1, 1))
        self.write(self.first, np.concatenate((self.image[111:127], repeated)))
        self.write(self.second, np.concatenate((repeated, self.image[126:142])))
        self.assert_unpublished(self.export(), 'ambiguous')

    def test_occupied_target_and_last_moment_competitor_keep_the_original(self):
        self.target.write_bytes(b'first original')
        self.assertEqual(self.export()['status'], 'invalid_target')
        self.assertEqual(self.target.read_bytes(), b'first original')
        self.target.unlink()
        link = os.link

        def race(source, destination):
            destination.write_bytes(b'late original')
            return link(source, destination)

        with patch.object(service.os, 'link', side_effect=race):
            result = self.export()
        self.assertEqual(result, dict(status='invalid_target', overlap_rows=[115], width=None, height=None))
        self.assertEqual(self.target.read_bytes(), b'late original')
        self.assertEqual(list(self.output.iterdir()), [self.target])

    def test_substituted_source_before_its_lock_is_rejected(self):
        replacement = self.root / 'replace.png'
        self.write(replacement, self.image[170:346])
        hold = service.hold_read_sources

        @contextmanager
        def race(paths):
            if tuple(paths) == (self.first, self.second):
                replacement.replace(self.first)
            with hold(paths):
                yield

        with patch.object(service, 'hold_read_sources', race):
            self.assert_unpublished(self.export(), 'source_changed')

    def test_staged_tampering_before_the_lock_and_directory_swap_prevent_publication(self):
        hold = service.hold_read_sources

        @contextmanager
        def tamper(paths):
            for path in paths:
                if path.parent.parent == self.output:
                    contents = path.read_bytes()
                    path.write_bytes(contents[:-1] + b'\x01')
            with hold(paths):
                yield

        with patch.object(service, 'hold_read_sources', tamper):
            self.assert_unpublished(self.export(), 'publish_failed', (115,))

        stitch = service.stitch_reward_guide

        def relocate(frames):
            self.output.rename(self.root / 'moved-output')
            self.output.mkdir()
            return stitch(frames)

        with patch.object(service, 'stitch_reward_guide', side_effect=relocate):
            self.assert_unpublished(self.export(), 'invalid_target', (115,))
        self.assertEqual(list((self.root / 'moved-output').iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows hard-link identity')
    def test_identical_staged_hard_link_to_an_existing_file_is_rejected(self):
        existing = self.root / 'existing.png'
        self.write(existing, self.image[:237])
        original = existing.read_bytes()
        hold = service.hold_read_sources

        @contextmanager
        def substitute(paths):
            for path in paths:
                if path.name == 'calendar.tmp':
                    self.assertEqual(path.read_bytes(), original)
                    path.unlink()
                    os.link(existing, path)
                    self.assertTrue(os.path.samefile(existing, path))
            with hold(paths):
                yield

        with patch.object(service, 'hold_read_sources', substitute):
            self.assert_unpublished(self.export(), 'publish_failed', (115,))
        self.assertEqual(existing.read_bytes(), original)
        self.assertEqual(existing.stat().st_nlink, 1)

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_real_ntfs_holds_inputs_and_staged_parent_through_the_exclusive_link(self):
        link = os.link
        original = self.first.read_bytes()

        def probe(staged, destination):
            for mutate in (lambda: self.first.write_bytes(b'altered'),
                           lambda: self.first.rename(self.root / 'moved-source.png'),
                           lambda: staged.write_bytes(b'altered'),
                           lambda: self.output.rename(self.root / 'moved-output')):
                with self.assertRaises(OSError):
                    mutate()
            return link(staged, destination)

        with patch.object(service.os, 'link', side_effect=probe):
            result = self.export()
        self.assertEqual(result['status'], 'ok')
        self.assertEqual(self.first.read_bytes(), original)
        with Image.open(self.target) as published:
            np.testing.assert_array_equal(np.asarray(published)[:, :, ::-1], self.image[:237])

    def test_stop_at_final_check_and_late_stop_after_commit(self):
        original_verify, original_link = service._verify_sources, os.link
        checked = 0
        late_stop = False

        def verify(sources):
            nonlocal checked
            original_verify(sources)
            checked += 1

        def checkpoint():
            if checked == 2 or late_stop:
                raise Stopped('stop')

        with patch.object(service, '_verify_sources', verify):
            self.assert_unpublished(self.export(checkpoint=checkpoint), 'stopped', (115,))

        def commit(staged, destination):
            nonlocal late_stop
            original_link(staged, destination)
            late_stop = True

        checked = 0
        with patch.object(service.os, 'link', side_effect=commit):
            self.assertEqual(self.export(checkpoint=checkpoint)['status'], 'ok')
        self.assertTrue(late_stop)
        self.assertTrue(self.target.is_file())

    @unittest.skipUnless(os.name == 'nt', 'Windows local-path rules')
    def test_unc_is_rejected_without_accessing_the_share(self):
        unc = r'\\example.invalid\share\selected.png'
        original_stat = Path.lstat

        def lstat(path, *args, **kwargs):
            self.assertFalse(str(path).startswith('\\\\'))
            return original_stat(path, *args, **kwargs)

        with patch.object(Path, 'lstat', lstat):
            self.assert_unpublished(self.export([unc]), 'invalid_source')
            result = service.export_reward_guide([self.first], unc)
            self.assertEqual(result, dict(status='invalid_target', overlap_rows=[], width=None, height=None))
