from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4

from autohsr import game_update_launcher as launcher, workflow_lease as lease
from autohsr.models import AutomationError
from autohsr.redemption_server import HYP_KEYS


class LauncherOfferTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory()))
        self.game = self.root / 'game' / 'StarRail.exe'
        self.game.parent.mkdir()
        self.game.write_bytes(b'game fixture')
        self.config = self.game.with_name('config.ini')
        self.write_version('4.6.0')
        self.launcher = self.root / 'launcher.exe'
        self.launcher.write_bytes(b'launcher fixture')
        self.report = dict(status='success', installed_version='4.6.0',
                           release_version='4.7.0', update='available',
                           pre_download='advertised', pre_download_version='4.8.0')
        key = dict(HYP_KEYS)['cn']
        values = {(key, 'GameInstallPath'): str(self.game.parent),
                  (key.rsplit('\\', 1)[0], 'InstallPath'): str(self.root)}
        self.registry = self.enterContext(patch('autohsr.redemption_server._native_reader',
                                                side_effect=lambda *args: values.get(args)))
        self.enterContext(patch.object(launcher, '_native_reader', self.registry))
        self.feed = self.enterContext(patch.object(launcher, 'check_game_update', return_value=self.report))
        self.verify = self.enterContext(patch.object(launcher, '_verify_publisher'))
        self.open = self.enterContext(patch.object(launcher, '_open'))
        self.enterContext(patch.object(launcher, 'native_idle_lease'))

    def write_version(self, version):
        self.config.write_text(f'[General]\ngame_version={version}\n', encoding='utf8')

    def offer(self, action='update'):
        _, offer = launcher.prepare_launcher(self.game, 'cn', action)
        self.assertIsNotNone(offer)
        return offer

    def test_update_and_pre_download_use_separate_official_targets(self):
        self.assertEqual(self.offer().target, '4.7.0')
        self.assertEqual(self.offer('pre_download').target, '4.8.0')
        self.open.assert_not_called()
        self.verify.assert_not_called()

    def test_wrong_channel_and_unavailable_offer_cannot_launch(self):
        report, offer = launcher.prepare_launcher(self.game, 'global', 'update')
        self.assertEqual(report['launcher'], 'unverified')
        self.assertIsNone(offer)
        self.report['update'] = 'current'
        _, offer = launcher.prepare_launcher(self.game, 'cn', 'update')
        self.assertIsNone(offer)
        self.open.assert_not_called()

    def test_handoff_reports_request_separately_from_installation(self):
        offer = self.offer()
        report = launcher.handoff(offer)
        self.assertEqual((report['status'], report['launcher'], report['installation']),
                         ('partial', 'open_requested', 'unverified'))
        self.verify.assert_called_once_with(self.launcher, 'cn')
        self.open.assert_called_once_with(self.launcher, 'cn')
        self.assertNotIn(str(self.root), repr(report))
        self.assertEqual(launcher.verify_installation(offer)['status'], 'partial')
        self.write_version('4.7.0')
        self.assertEqual(launcher.verify_installation(offer)['status'], 'success')

    def test_changed_release_or_launcher_file_prevents_open(self):
        offer = self.offer()
        self.report['release_version'] = '4.8.0'
        with self.assertRaises(AutomationError):
            launcher.handoff(offer)
        self.report['release_version'] = offer.target
        self.launcher.write_bytes(b'changed launcher fixture')
        with self.assertRaises(AutomationError):
            launcher.handoff(offer)
        self.open.assert_not_called()

    def test_source_change_during_signature_validation_prevents_open(self):
        offer = self.offer()
        self.verify.side_effect = lambda *_: self.write_version('4.7.0')
        with self.assertRaises(AutomationError):
            launcher.handoff(offer)
        self.open.assert_not_called()

    def test_failed_publisher_and_stopped_handoff_do_not_issue_request(self):
        offer = self.offer()
        self.verify.side_effect = AutomationError('unverified signature')
        with self.assertRaises(AutomationError):
            launcher.handoff(offer)
        self.verify.side_effect = None
        cancelled = Mock(side_effect=[False, False, True])
        self.assertEqual(launcher.handoff(offer, cancelled=cancelled)['status'], 'stopped')
        self.open.assert_not_called()

    def test_tracking_requires_consecutive_target_reads_and_never_opens_launcher(self):
        offer = self.offer()
        self.feed.reset_mock()
        now = 0
        frames = iter(('4.6.0', '4.7.0', None, '4.7.0', '4.7.0'))
        native_verify = launcher.verify_installation

        def verify(_offer):
            version = next(frames)
            if version is None:
                raise AutomationError('temporary read failure')
            self.write_version(version)
            return native_verify(_offer)

        def wait(seconds):
            nonlocal now
            now += seconds

        updates = []
        stop = SimpleNamespace(is_set=lambda: False, wait=wait)
        with (patch.object(launcher.time, 'monotonic', side_effect=lambda: now),
              patch.object(launcher, 'verify_installation', side_effect=verify)):
            launcher.track_installation(offer, stop=stop, emit=updates.append)
        self.assertEqual([item['tracking'] for item in updates],
                         ['waiting', 'confirming', 'version_unavailable', 'confirming', 'verified'])
        self.assertEqual(updates[-1]['status'], 'success')
        self.feed.assert_not_called()
        self.open.assert_not_called()

    def test_tracking_ends_for_changed_source_or_elapsed_deadline(self):
        offer = self.offer()
        for changed in (False, True):
            with self.subTest(changed=changed):
                now = 0
                updates = []

                def wait(seconds):
                    nonlocal now
                    now += seconds

                stop = SimpleNamespace(is_set=lambda: False, wait=wait)
                verify = (Mock(side_effect=launcher.InstallationSourceChanged()) if changed
                          else Mock(return_value=dict(status='partial', installed_version='4.6.0',
                                                      target=offer.target, channel='cn')))
                with (patch.object(launcher.time, 'monotonic', side_effect=lambda: now),
                      patch.object(launcher, 'verify_installation', verify)):
                    launcher.track_installation(offer, stop=stop, emit=updates.append, timeout=9)
                expected = ['source_changed'] if changed else ['waiting', 'waiting', 'timeout']
                self.assertEqual([item['tracking'] for item in updates], expected)

    def test_tracking_cancellation_releases_wait_without_another_read(self):
        offer = self.offer()
        updates = []
        stop = Mock()
        stop.is_set.side_effect = [False, False, True]
        with patch.object(launcher, 'verify_installation', wraps=launcher.verify_installation) as verify:
            launcher.track_installation(offer, stop=stop, emit=updates.append)
        verify.assert_called_once_with(offer)
        stop.wait.assert_called_once()
        self.assertEqual([item['tracking'] for item in updates], ['waiting'])


class ShellRequestTests(TestCase):
    def test_native_call_uses_one_fixed_game_argument_per_channel(self):
        file = Path('C:/fixture launcher/launcher.exe')
        execute = Mock(return_value=33)
        with patch.object(launcher.C, 'WinDLL', return_value=SimpleNamespace(ShellExecuteW=execute)):
            for channel, game in (('cn', 'hkrpg_cn'), ('global', 'hkrpg_global')):
                launcher._open(file, channel)
                execute.assert_called_with(None, 'open', str(file), '--game=' + game, str(file.parent), 1)
            execute.return_value = 5
            with self.assertRaises(AutomationError):
                launcher._open(file, 'cn')

    def test_native_run_blocks_handoff_lease_until_released(self):
        suffix = uuid4().hex
        with patch.object(lease, 'NAME', 'Local\\AutoHSR.TestWorkflow.' + suffix), \
                patch.object(lease, 'NATIVE_NAME', 'Local\\AutoHSR.TestNative.' + suffix):
            kernel = lease._kernel()
            held = kernel.CreateMutexW(None, False, lease.NATIVE_NAME)
            self.assertTrue(held)
            try:
                with self.assertRaises(AutomationError), lease.native_idle_lease():
                    self.fail('handoff acquired the active native run')
            finally:
                kernel.CloseHandle(held)
            with lease.native_idle_lease():
                with self.assertRaises(AutomationError), lease.workflow_lease():
                    self.fail('workflow acquired the active handoff')
