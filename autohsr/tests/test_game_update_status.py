"""Read-only release checks through the production CLI and package parser."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import game_update_status as update
from autohsr.__main__ import main
from autohsr.config import Settings


def package_feed(*, channel='cn', release='4.6.0', upcoming=None):
    game = dict(id='64kMb5iAWu', biz='hkrpg_cn') if channel == 'cn' else dict(id='4ziysqXOQ8', biz='hkrpg_global')
    return dict(retcode=0, data=dict(game_packages=[dict(
        game=game, main=dict(major=dict(version=release)),
        pre_download=dict(major=dict(version=upcoming) if upcoming else None, patches=[]))]))


class GameUpdateStatusTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.game = self.root / 'private-installation' / 'StarRail.exe'
        self.game.parent.mkdir()
        self.game.write_bytes(b'executable fixture')
        self.install = self.game.with_name('config.ini')
        self.install.write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
        self.config = self.root / 'settings.json'
        Settings(game_path=str(self.game)).save(self.config)

    def invoke(self, channel, raw):
        with (patch.object(update, '_fetch', return_value=raw) as fetch,
              redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO())):
            code = main(['--game-update-check', channel, '--config', str(self.config)])
        self.assertNotIn('private-installation', stdout.getvalue())
        fetch.assert_called_once_with(channel)
        return code, json.loads(stdout.getvalue())

    def test_public_feed_is_compared_without_changing_either_installation_or_settings(self):
        before = self.install.read_bytes(), self.config.read_bytes()
        for release, expected in (('4.4.0', 'local_ahead'), ('4.6.0', 'current'), ('4.10.0', 'available')):
            with self.subTest(release=release):
                code, report = self.invoke('cn', json.dumps(package_feed(release=release)).encode())
                self.assertEqual((code, report['update'], report['pre_download']), (0, expected, 'not_advertised'))
                self.assertEqual((report['installed_version'], report['release_version']), ('4.6.0', release))
        self.assertEqual((self.install.read_bytes(), self.config.read_bytes()), before)

    def test_pre_download_listing_is_separate_from_a_released_update(self):
        feed = package_feed(channel='global', upcoming='4.7.0')
        code, report = self.invoke('global', json.dumps(feed).encode())
        self.assertEqual((code, report['update'], report['pre_download']), (0, 'current', 'advertised'))
        self.assertEqual(report['pre_download_version'], '4.7.0')
        self.install.write_text('[General]\ngame_version=4.7.0\n', encoding='utf8')
        _, report = self.invoke('global', json.dumps(feed).encode())
        self.assertEqual((report['update'], report['pre_download']), ('local_ahead', 'local_at_or_ahead'))

    def test_download_sizes_use_exact_source_patch_or_full_game_and_exclude_voice(self):
        feed = package_feed(release='4.7.0', upcoming='4.8.0')
        package = feed['data']['game_packages'][0]
        package['main']['major']['game_pkgs'] = [dict(size='800')]
        package['main']['patches'] = [dict(version='4.6.0', game_pkgs=[dict(size='20'), dict(size=30)],
                                            audio_pkgs=[dict(size='1000')])]
        package['pre_download']['major']['game_pkgs'] = [dict(size='900')]
        code, report = self.invoke('cn', json.dumps(feed).encode())
        self.assertEqual(code, 0)
        self.assertEqual(report['update_package'], dict(kind='patch', files=2, download_bytes=50))
        self.assertEqual(report['pre_download_package'], dict(kind='full', files=1, download_bytes=900))
        package['main']['patches'][0]['game_pkgs'][1]['size'] = True
        code, report = self.invoke('cn', json.dumps(feed).encode())
        self.assertEqual(code, 0)
        self.assertEqual(report['update'], 'available')
        self.assertNotIn('update_package', report)

    def test_wrong_channel_or_incomplete_feed_cannot_report_no_update(self):
        duplicate = json.dumps(package_feed()).replace('"retcode": 0', '"retcode": 2, "retcode": 0')
        incomplete = package_feed()
        incomplete['data']['game_packages'][0]['pre_download']['patches'] = [{}]
        for raw in (json.dumps(package_feed(channel='global')), duplicate, json.dumps(incomplete),
                    json.dumps(package_feed(upcoming='4.5.0'))):
            code, report = self.invoke('cn', raw.encode())
            self.assertEqual((code, report['reason'], report['update'], report['pre_download']),
                             (1, 'package_feed_unverified', 'unknown', 'unknown'))

    def test_unreadable_or_changing_installation_cannot_produce_a_comparison(self):
        def changed(_):
            self.install.write_text('[General]\ngame_version=4.7.0\n', encoding='utf8')
            return json.dumps(package_feed()).encode()

        with patch.object(update, '_fetch', side_effect=changed):
            report = update.check_game_update(self.game, 'cn')
        self.assertEqual((report['reason'], report['installed_version']), ('installation_changed', None))
        with patch.object(update, '_fetch') as fetch:
            report = update.check_game_update(self.root / 'missing.exe', 'cn')
        self.assertEqual(report['reason'], 'installation_unverified')
        fetch.assert_not_called()

    def test_network_failure_and_redirect_keep_both_states_unknown(self):
        connection = Mock()
        response = connection.getresponse.return_value = Mock()
        response.status = 302
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        with patch.object(update.http.client, 'HTTPSConnection', return_value=connection) as client:
            report = update.check_game_update(self.game, 'cn')
        client.assert_called_once_with('hyp-api.mihoyo.com', timeout=8)
        self.assertEqual((report['reason'], report['update'], report['pre_download']),
                         ('package_feed_unavailable', 'unknown', 'unknown'))
        response.read1.assert_not_called()
        connection.request.assert_called_once()
        connection.close.assert_called_once()
