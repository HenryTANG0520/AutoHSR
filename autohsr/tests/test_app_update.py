"""Exercise release discovery, staged publication and the command line."""

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from hashlib import sha256
import io
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile

from autohsr import app_update
from autohsr.__main__ import main


def portable_zip():
    output = io.BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('AutoHSR/AutoHSR.exe', 'synthetic launcher')
        archive.writestr('AutoHSR/_internal/runtime.dll', 'synthetic runtime')
    return output.getvalue()


class AppUpdateTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.output = self.root / 'upgrade.zip'
        self.package = portable_zip()
        self.release = app_update.Release('v0.3.0', sha256(self.package).hexdigest())

    def test_latest_redirect_requires_a_stable_tag_and_its_own_checksum(self):
        response = Mock(status=302)
        response.getheader.return_value = app_update._TAG_PREFIX + self.release.tag

        @contextmanager
        def latest(url, deadline):
            self.assertEqual(url, app_update._LATEST)
            yield response, None

        checksum = f'{self.release.digest}  {self.release.filename}\n'.encode('ascii')
        with (patch.object(app_update, '_response', latest),
              patch.object(app_update, '_asset', return_value=iter((checksum,))) as asset):
            self.assertEqual(app_update.official_release(), self.release)
        asset.assert_called_once_with(self.release.asset + '.sha256', 1024, 15)

        for location in (app_update._TAG_PREFIX + 'v0.3.0-beta.1',
                         'https://github.com/other/AutoHSR/releases/tag/v0.3.0'):
            response.getheader.return_value = location
            with (patch.object(app_update, '_response', latest), patch.object(app_update, '_asset') as asset,
                  self.assertRaisesRegex(app_update.UpdateError, 'release_tag_unverified')):
                app_update.official_release()
            asset.assert_not_called()

    def test_cli_stages_verified_package_without_changing_nearby_data(self):
        config = self.root / 'config.json'
        config.write_bytes(b'user preferences')
        with (patch.object(app_update, 'official_release', return_value=self.release),
              patch.object(app_update, '_asset', return_value=iter((self.package,))),
              redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO())):
            self.assertEqual(main(['--app-update-stage', str(self.output)]), 0)
        report = json.loads(stdout.getvalue())
        self.assertEqual((report['update'], report['staged'], report['sha256']),
                         ('available', True, self.release.digest))
        self.assertEqual(self.output.read_bytes(), self.package)
        self.assertEqual(config.read_bytes(), b'user preferences')
        self.assertFalse(list(self.root.glob('.autohsr-update-*')))

    def test_wrong_checksum_and_nonportable_archive_leave_no_output(self):
        for tag, data, reason in (
                (self.release, b'short transfer', 'release_hash_mismatch'),
                (app_update.Release('v0.3.0', sha256(b'other').hexdigest()), b'other',
                 'release_archive_unverified')):
            with (patch.object(app_update, '_asset', return_value=iter((data,))),
                  self.assertRaisesRegex(app_update.UpdateError, reason)):
                app_update.stage_release(tag, self.output)
            self.assertFalse(self.output.exists())
            self.assertFalse(list(self.root.iterdir()))

    def test_existing_and_concurrent_destinations_are_preserved(self):
        self.output.write_bytes(b'existing')
        with (patch.object(app_update, '_asset') as asset,
              self.assertRaisesRegex(app_update.UpdateError, 'stage_destination_exists')):
            app_update.stage_release(self.release, self.output)
        asset.assert_not_called()
        self.assertEqual(self.output.read_bytes(), b'existing')
        self.output.unlink()

        link = os.link

        def compete(source, destination):
            destination.write_bytes(b'concurrent publisher')
            link(source, destination)

        with (patch.object(app_update, '_asset', return_value=iter((self.package,))),
              patch.object(app_update.os, 'link', side_effect=compete), self.assertRaises(OSError)):
            app_update.stage_release(self.release, self.output)
        self.assertEqual(self.output.read_bytes(), b'concurrent publisher')
        self.assertFalse(list(self.root.glob('.autohsr-update-*')))

    def test_check_and_refusal_of_older_release_do_not_download_a_package(self):
        earlier = app_update.Release('v0.1.0', self.release.digest)
        for arguments, code in ((['--app-update-check'], 0),
                                (['--app-update-stage', str(self.output)], 1)):
            with (patch.object(app_update, 'official_release', return_value=earlier),
                  patch.object(app_update, '_asset') as asset, redirect_stdout(io.StringIO()) as stdout):
                self.assertEqual(main(arguments), code)
            self.assertEqual(json.loads(stdout.getvalue())['update'], 'local_ahead')
            asset.assert_not_called()
            self.assertFalse(self.output.exists())
