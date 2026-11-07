"""Portable runtime installation, interrupted recovery and protected user data."""

from contextlib import redirect_stdout
from hashlib import sha256
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
from unittest import TestCase
from unittest.mock import patch
from zipfile import ZipFile

from autohsr import app_update_install as updater
from autohsr.__main__ import main
from autohsr.app_update import Release, UpdateError


class SimulatedInterruption(BaseException):
    pass


class AppUpdateInstallTests(TestCase):
    def setUp(self):
        self.folder = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.root = self.folder / 'installed'
        self.exe = self.root / 'AutoHSR.exe'
        self.original = self.root / '_internal' / 'assets' / 'old.txt'
        self.original.parent.mkdir(parents=True)
        self.exe.write_bytes(b'MZ old runtime')
        self.original.write_bytes(b'old resource')
        self.data = {self.root / 'config.json': b'settings', self.root / 'runs' / 'ledger.json': b'ledger',
                     self.root / 'notifications.local' / 'fixture': b'encrypted config',
                     self.root / 'user-note.txt': b'user note'}
        for path, value in self.data.items():
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(value)
        self.archive = self.folder / 'release.zip'
        self.release = self.package()

    def package(self, extra=None):
        with ZipFile(self.archive, 'w') as archive:
            archive.writestr('AutoHSR/AutoHSR.exe', b'MZ new runtime')
            archive.writestr('AutoHSR/_internal/assets/new.txt', b'new resource')
            archive.writestr('AutoHSR/config.json', b'not installed over user settings')
            if extra is not None:
                archive.writestr(extra, b'unsafe path')
        return Release('v0.3.0', sha256(self.archive.read_bytes()).hexdigest())

    def assert_user_data(self):
        self.assertEqual({path: path.read_bytes() for path in self.data}, self.data)

    def test_cli_install_and_rollback_only_replace_the_two_runtime_items(self):
        with patch.object(updater, 'official_release', return_value=self.release):
            for expected, arguments in (
                    ('installed', ['--app-update-install', str(self.archive), '--app-update-target', str(self.root)]),
                    ('installed', ['--app-update-status', str(self.root)]),
                    ('original', ['--app-update-rollback', str(self.root)]),
                    ('original', ['--app-update-accept', str(self.root)])):
                with redirect_stdout(io.StringIO()) as output:
                    self.assertEqual(main(arguments), 0, output.getvalue())
                self.assertEqual(json.loads(output.getvalue())['installation'], expected)
                self.assertEqual(self.exe.read_bytes(), b'MZ ' + (b'new' if expected == 'installed' else b'old') + b' runtime')
                self.assert_user_data()
        self.assertFalse((self.root / '.autohsr-update').exists())
        self.assertEqual(self.original.read_bytes(), b'old resource')

    def test_interrupted_runtime_swap_can_be_rolled_back_from_file_positions(self):
        rename = Path.rename
        destination = self.root / '_internal'

        def interrupt(source, target):
            if target == destination:
                raise SimulatedInterruption()
            return rename(source, target)

        with patch.object(Path, 'rename', new=interrupt), self.assertRaises(SimulatedInterruption):
            updater.install(self.archive, self.root, self.release)
        self.assertEqual(updater.maintenance(self.root, 'status')['installation'], 'interrupted')
        self.assertFalse(self.exe.exists())
        self.assertEqual(updater.maintenance(self.root, 'rollback')['installation'], 'original')
        self.assertEqual(self.exe.read_bytes(), b'MZ old runtime')
        self.assert_user_data()

    def test_offline_install_uses_the_explicit_checksum_and_can_accept_the_new_runtime(self):
        checksum = self.folder / 'official.sha256'
        checksum.write_text(f'{self.release.digest}  {self.release.filename}\n', encoding='ascii')
        with patch.object(updater, 'official_release') as network:
            with redirect_stdout(io.StringIO()) as output:
                code = main(['--app-update-install', str(self.archive), '--app-update-target', str(self.root),
                             '--app-update-checksum', str(checksum)])
            self.assertEqual(code, 0, output.getvalue())
            network.assert_not_called()
        with patch.object(updater, 'require_closed', wraps=updater.require_closed) as closed:
            result = updater.maintenance(self.root, 'accept')
        journal = self.root / '.autohsr-update'
        closed.assert_called_once_with(journal / 'previous' / 'AutoHSR.exe', journal / 'next' / 'AutoHSR.exe')
        self.assertEqual((result['installation'], result['backup_retained']), ('installed', False))
        self.assertEqual(self.exe.read_bytes(), b'MZ new runtime')
        self.assert_user_data()
        self.assertFalse((self.root / '.autohsr-update').exists())

    def test_failed_swap_restores_original_runtime_without_restarting(self):
        rename = Path.rename

        def fail(source, target):
            if source.parent.name == 'next' and source.name == '_internal':
                raise PermissionError('synthetic lock')
            return rename(source, target)

        with patch.object(Path, 'rename', new=fail), self.assertRaises(PermissionError):
            updater.install(self.archive, self.root, self.release)
        self.assertEqual(updater.maintenance(self.root, 'status')['installation'], 'original')
        self.assertEqual(self.exe.read_bytes(), b'MZ old runtime')
        self.assert_user_data()

    def test_archive_traversal_is_rejected_before_moving_the_installation(self):
        damaged = self.package('AutoHSR/_internal/../config.json')
        with self.assertRaisesRegex(UpdateError, 'release_layout_unverified'):
            updater.install(self.archive, self.root, damaged)
        self.assertFalse((self.root / '.autohsr-update').exists())
        self.assertEqual(self.exe.read_bytes(), b'MZ old runtime')
        self.assert_user_data()

    def test_a_running_target_is_rejected_by_the_real_windows_process_guard(self):
        ping = shutil.which('ping.exe')
        self.assertIsNotNone(ping)
        shutil.copyfile(ping, self.exe)
        process = subprocess.Popen([str(self.exe), '-n', '30', '127.0.0.1'],
                                   creationflags=subprocess.CREATE_NO_WINDOW,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with self.assertRaisesRegex(UpdateError, 'installation_running'):
                updater.install(self.archive, self.root, self.release)
            self.assertFalse((self.root / '.autohsr-update').exists())
            self.assert_user_data()
        finally:
            process.terminate()
            process.wait(timeout=10)
