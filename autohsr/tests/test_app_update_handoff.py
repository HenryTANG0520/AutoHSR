"""Real file exchanges behind the independent handoff and startup probe."""

from hashlib import sha256
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from zipfile import ZipFile

from autohsr import app_update, app_update_dispatch as dispatch, app_update_handoff as handoff
from autohsr.app_update_install import maintenance


class AppUpdateHandoffTests(TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.exe = self.root / 'AutoHSR.exe'
        self.runtime = self.root / '_internal'
        (self.runtime / 'assets').mkdir(parents=True)
        (self.runtime / 'autohsr-version.txt').write_text('0.2.0', encoding='ascii')
        self.exe.write_bytes(b'MZ old')
        self.settings = self.root / 'config.json'
        self.settings.write_bytes(b'private settings fixture')
        package = io.BytesIO()
        with ZipFile(package, 'w') as archive:
            archive.writestr('AutoHSR/AutoHSR.exe', b'MZ new')
            archive.writestr('AutoHSR/_internal/assets/example', b'new asset')
            archive.writestr('AutoHSR/_internal/autohsr-version.txt', '0.3.0')
        self.package = package.getvalue()
        self.release = app_update.Release('v0.3.0', sha256(self.package).hexdigest())

    def queue(self, *, restart=True):
        with (patch.object(dispatch, 'official_release', return_value=self.release),
              patch.object(dispatch, '_spawn') as launch):
            result = dispatch.begin(self.root, restart=restart)
        self.assertEqual(result['status'], 'queued')
        job = self.root / 'runs' / 'app-update' / result['job']
        launch.assert_called_once_with(job)
        self.assertEqual(handoff.read_job(job), (job, self.root, self.release, restart, '0.2.0'))
        return job

    def run_job(self, job, *, probe_error=None):
        with (patch.object(handoff, 'official_release', return_value=self.release),
              patch.object(app_update, '_asset', return_value=iter((self.package,))),
              patch.object(handoff, '_probe', side_effect=probe_error) as probe,
              patch.object(handoff.subprocess, 'Popen') as restart):
            code = handoff.worker(job)
        self.assertEqual(self.settings.read_bytes(), b'private settings fixture')
        self.assertFalse((job / self.release.filename).exists())
        return code, handoff.read_record(job / 'result.json'), probe, restart

    def test_closed_target_installs_and_verifies_before_launching_desktop(self):
        job = self.queue()
        code, result, probe, restart = self.run_job(job)
        self.assertEqual((code, result['desktop_restart'], result['runtime_verified']), (0, 'launched', True))
        self.assertEqual(self.exe.read_bytes(), b'MZ new')
        self.assertEqual(maintenance(self.root, 'status')['installation'], 'installed')
        probe.assert_called_once_with(self.root, job, self.release)
        self.assertEqual(restart.call_args.args[0], [str(self.exe)])
        self.assertEqual(restart.call_args.kwargs['env']['PYINSTALLER_RESET_ENVIRONMENT'], '1')

    def test_failed_startup_probe_rolls_back_and_never_launches_desktop(self):
        job = self.queue()
        code, result, _, restart = self.run_job(job, probe_error=app_update.UpdateError('new_runtime_unverified'))
        self.assertEqual((code, result['installation'], result['reason']), (1, 'original', 'new_runtime_unverified'))
        self.assertEqual(self.exe.read_bytes(), b'MZ old')
        self.assertEqual(handoff.installed_version(self.root), '0.2.0')
        restart.assert_not_called()

    def test_waiting_does_not_terminate_the_current_app_and_timeout_stops(self):
        busy = app_update.UpdateError('installation_running')
        with (patch.object(handoff, 'require_closed', side_effect=(busy, None)) as closed,
              patch.object(handoff, 'sleep') as wait):
            handoff._wait_closed(self.root)
        self.assertEqual(closed.call_count, 2)
        wait.assert_called_once_with(.25)
        with (patch.object(handoff, 'require_closed', side_effect=busy),
              patch.object(handoff, 'monotonic', side_effect=(0, 121)),
              self.assertRaisesRegex(app_update.UpdateError, 'installation_close_timeout')):
            handoff._wait_closed(self.root)

    def test_probe_binds_binary_version_and_can_run_without_opening_a_window(self):
        job = self.queue(restart=False)
        (self.runtime / 'autohsr-version.txt').write_text('0.3.0', encoding='ascii')
        from autohsr import gui

        interpreter = Mock()
        with (patch.object(dispatch.sys, 'frozen', True, create=True),
              patch.multiple(dispatch, ROOT=self.root, RESOURCE_ROOT=self.runtime, __version__='0.3.0'),
              patch.object(gui.tk, 'Tcl', interpreter)):
            dispatch.probe(job)
        interpreter.assert_called_once_with()
        self.assertEqual(json.loads((job / 'probe.json').read_text('utf8')),
                         {'protocol': 1, 'job': job.name, 'version': '0.3.0'})
        with patch.object(handoff.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
            handoff._probe(self.root, job, self.release)
            with self.assertRaisesRegex(app_update.UpdateError, 'new_runtime_unverified'):
                handoff._probe(self.root, job, app_update.Release('v0.4.0', self.release.digest))
