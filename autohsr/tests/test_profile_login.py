"""Cached login source is read-only and tied to the unique client channel."""

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
import winreg

from autohsr.currency_wars_identity import account_key_from_uid
from autohsr.models import AutomationError
from autohsr.profile_login import GAME_KEYS, LAST_UID, _cached_key


class CachedLoginSourceTests(TestCase):
    def test_reads_only_last_uid_from_channel_of_live_executable(self):
        for server in ('cn', 'global'):
            with (self.subTest(server=server), patch('autohsr.profile_login.resolve',
                    return_value=SimpleNamespace(server=server)) as resolve,
                    patch('autohsr.profile_login.require_binding') as binding,
                    patch.object(winreg, 'OpenKey') as open_key,
                    patch.object(winreg, 'QueryValueEx', return_value=(100000000, winreg.REG_DWORD)) as query):
                self.assertEqual(_cached_key('live', 'configured'), account_key_from_uid('100000000'))
                resolve.assert_called_once_with('live')
                binding.assert_called_once_with('configured', resolve.return_value)
                open_key.assert_called_once_with(winreg.HKEY_CURRENT_USER, GAME_KEYS[server], 0, winreg.KEY_READ)
                query.assert_called_once_with(open_key.return_value.__enter__.return_value, LAST_UID)

    def test_unverified_installation_stops_before_game_registry_access(self):
        with (patch('autohsr.profile_login.resolve', side_effect=AutomationError('synthetic private path')),
                patch.object(winreg, 'OpenKey') as open_key):
            with self.assertRaisesRegex(AutomationError, '当前安装或游戏上次账号无法核实'):
                _cached_key('live', 'configured')
        open_key.assert_not_called()
