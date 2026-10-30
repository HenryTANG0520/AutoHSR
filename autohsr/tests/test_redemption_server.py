"""Server binding tests use temporary fake installs and injected registry data."""
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autohsr.models import AutomationError, InputInterrupted, Stopped
from autohsr.redemption_server import (HYP_KEYS, MAX_PATH_LENGTH, METHOD, VALUE_NAME,
    ServerResolution, UnknownServerError, require_binding, resolve)


class RedemptionServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.cn = self.install('CN Client')
        self.global_ = self.install('Global Client')

    def install(self, name):
        directory = self.root / name
        directory.mkdir()
        executable = directory / 'StarRail.exe'
        executable.write_bytes(b'fake executable; never run')
        return executable

    def reader(self, cn=None, global_=None):
        values = dict(zip((key for _, key in HYP_KEYS), (cn, global_)))
        calls = []

        def read(key, value_name):
            self.assertEqual(value_name, VALUE_NAME)
            self.assertIn(key, values)
            calls.append((key, value_name))
            value = values[key]
            if isinstance(value, Exception):
                raise value
            return value

        return read, calls

    def assert_unknown(self, executable, reader, reason=None):
        with self.assertRaises(UnknownServerError) as raised:
            resolve(executable, reader=reader)
        error = raised.exception
        self.assertIsInstance(error, AutomationError)
        if reason is not None:
            self.assertEqual(error.reason, reason)
        self.assertNotIn(str(self.root), str(error))
        self.assertNotIn(str(self.root), repr(error.args))
        return error

    def test_single_install_each_server_and_exact_two_value_reads(self):
        for server, executable, values in (
                ('cn', self.cn, (str(self.cn.parent), None)),
                ('global', self.global_, (None, str(self.global_.parent)))):
            read, calls = self.reader(*values)
            result = resolve(executable, reader=read)
            self.assertEqual(result.server, server)
            self.assertEqual(calls, [(key, VALUE_NAME) for _, key in HYP_KEYS])
            self.assertEqual(result.public_summary(), dict(server=server, method=METHOD))

    def test_dual_install_binds_current_executable_without_cn_priority(self):
        read, _ = self.reader(str(self.cn.parent), str(self.global_.parent))
        cn = resolve(self.cn, reader=read)
        global_ = resolve(self.global_, reader=read)
        self.assertEqual((cn.server, global_.server), ('cn', 'global'))
        self.assertNotEqual(cn.executable_key, global_.executable_key)
        self.assertNotEqual(cn.source_digest, global_.source_digest)

    def test_other_absolute_stale_install_is_nonmatch_for_either_server(self):
        stale = str(self.root / 'Uninstalled Client')
        for executable, values, server in (
                (self.cn, (str(self.cn.parent), stale), 'cn'),
                (self.global_, (stale, str(self.global_.parent)), 'global')):
            read, _ = self.reader(*values)
            self.assertEqual(resolve(executable, reader=read).server, server)

    def test_missing_or_stale_sources_cannot_select_a_default(self):
        for values in ((None, None), (str(self.root / 'old CN'), None),
                       (None, str(self.root / 'old Global'))):
            read, _ = self.reader(*values)
            self.assert_unknown(self.cn, read, 'unmatched')

    def test_both_sources_matching_same_executable_are_ambiguous(self):
        read, _ = self.reader(str(self.cn.parent), str(self.cn.parent))
        self.assert_unknown(self.cn, read, 'ambiguous')

    def test_installed_other_executable_does_not_prove_current_server(self):
        other = self.install('Unregistered Client')
        read, _ = self.reader(str(self.cn.parent), str(self.global_.parent))
        self.assert_unknown(other, read, 'unmatched')

    def test_unreadable_either_source_blocks_even_a_valid_other_match(self):
        for error in (PermissionError('private installation path'), OSError('denied'),
                      RuntimeError('cannot read private source'), KeyError('private source')):
            for values, executable in ((
                    (str(self.cn.parent), error), self.cn), (
                    (error, str(self.global_.parent)), self.global_)):
                read, _ = self.reader(*values)
                self.assert_unknown(executable, read, 'registry_unreadable')

    def test_injected_control_cancellation_is_not_reclassified_as_unknown(self):
        for error in (Stopped('cancelled'), InputInterrupted('cancelled')):
            read, _ = self.reader(str(self.cn.parent), error)
            with self.assertRaises(type(error)) as raised:
                resolve(self.cn, reader=read)
            self.assertIs(raised.exception, error)

    def test_malformed_registry_values_block_each_branch(self):
        bad_values = ('', 12, b'not a string', 'relative/install', ' ' + str(self.cn.parent),
            str(self.cn.parent) + '\n', str(self.cn.parent) + '\x00',
            str(self.cn.parent) + '\u202e', str(self.cn.parent) + '\ud800',
            str(self.root / 'bad*path'), str(self.root / 'quoted"path'),
            str(self.root / 'trailing.'), str(self.root) + '/' + 'a' * MAX_PATH_LENGTH)
        for bad in bad_values:
            for values, executable in (((str(self.cn.parent), bad), self.cn),
                                       ((bad, str(self.global_.parent)), self.global_)):
                read, _ = self.reader(*values)
                self.assert_unknown(executable, read, 'invalid_install_path')

    def test_current_executable_must_be_absolute_existing_file_with_exact_name(self):
        directory = self.root / 'Directory' / 'StarRail.exe'
        directory.mkdir(parents=True)
        wrong = self.root / 'Other.exe'
        wrong.write_bytes(b'not run')
        bad_values = (None, b'bad', 'StarRail.exe', self.root / 'missing' / 'StarRail.exe',
            directory, wrong, str(self.cn) + '\n', str(self.cn) + '\ud800',
            str(self.root) + '/' + 'a' * MAX_PATH_LENGTH)
        for value in bad_values:
            with patch('autohsr.redemption_server._native_reader', side_effect=AssertionError('must not read')):
                self.assert_unknown(value, None, 'invalid_executable')

    def test_dot_directory_aliases_resolve_to_same_binding_and_digest(self):
        alias = str(self.cn.parent / '..' / self.cn.parent.name)
        plain, _ = self.reader(str(self.cn.parent), None)
        aliased, _ = self.reader(alias, None)
        original = resolve(self.cn, reader=plain)
        result = resolve(Path(alias) / 'StarRail.exe', reader=aliased)
        self.assertEqual(result, original)
        require_binding(Path(alias) / 'StarRail.exe', original)

    @unittest.skipUnless(os.name == 'nt', 'case aliases require the Windows filesystem')
    def test_windows_case_aliases_do_not_change_server_or_proof(self):
        read, _ = self.reader(str(self.cn.parent).swapcase(), None)
        aliased = resolve(str(self.cn).swapcase(), reader=read)
        plain, _ = self.reader(str(self.cn.parent), None)
        self.assertEqual(aliased, resolve(self.cn, reader=plain))

    def test_frozen_serialized_proof_contains_only_server_method_and_hashes(self):
        read, _ = self.reader(str(self.cn.parent), None)
        result = resolve(self.cn, reader=read)
        self.assertEqual(set(result.to_dict()), {'server', 'method', 'executable_key', 'source_digest'})
        expected_key = hashlib.sha256(os.path.normcase(str(self.cn.resolve())).encode('utf-8')).hexdigest()
        self.assertEqual(result.executable_key, expected_key)
        self.assertEqual(ServerResolution(**json.loads(json.dumps(result.to_dict()))), result)
        for value in (result.executable_key, result.source_digest):
            self.assertRegex(value, r'^[0-9a-f]{64}$')
        self.assertNotIn(str(self.root), json.dumps(result.to_dict()))
        self.assertNotIn(str(self.root), repr(result))
        with self.assertRaises(FrozenInstanceError):
            result.server = 'global'

    def test_source_digest_binds_both_observed_install_sources(self):
        original, _ = self.reader(str(self.cn.parent), None)
        stale, _ = self.reader(str(self.cn.parent), str(self.root / 'stale'))
        result = resolve(self.cn, reader=original)
        changed = resolve(self.cn, reader=stale)
        self.assertEqual(result.executable_key, changed.executable_key)
        self.assertNotEqual(result.source_digest, changed.source_digest)

    def test_binding_recheck_never_reads_registry_and_rejects_changed_or_missing_exe(self):
        read, _ = self.reader(str(self.cn.parent), None)
        result = resolve(self.cn, reader=read)
        with patch('autohsr.redemption_server._native_reader', side_effect=AssertionError('no registry recheck')):
            self.assertIsNone(require_binding(self.cn, result))
            with self.assertRaises(UnknownServerError) as changed:
                require_binding(self.global_, result)
            self.assertEqual(changed.exception.reason, 'executable_changed')
            missing = self.root / 'missing' / 'StarRail.exe'
            with self.assertRaises(UnknownServerError):
                require_binding(missing, result)

    def test_binding_recheck_validates_proof_without_reading_registry(self):
        read, _ = self.reader(str(self.cn.parent), None)
        result = resolve(self.cn, reader=read)
        invalid = object.__new__(ServerResolution)
        for key, value in result.to_dict().items():
            object.__setattr__(invalid, key, value)
        object.__setattr__(invalid, 'source_digest', 'not-a-digest')
        with patch('autohsr.redemption_server._native_reader', side_effect=AssertionError('no registry')):
            for value in (None, result.to_dict(), invalid, object.__new__(ServerResolution)):
                with self.assertRaises(UnknownServerError) as error:
                    require_binding(self.cn, value)
                self.assertEqual(error.exception.reason, 'invalid_resolution')
        with self.assertRaises(ValueError):
            ServerResolution('cn', METHOD, 'raw path', '0' * 64)

    def test_native_reader_is_only_read_only_hkcu_hyp_values_using_fake_winreg(self):
        calls = []
        values = {key: value for (_, key), value in zip(HYP_KEYS, (str(self.cn.parent), None))}

        class Key:
            def __init__(self, subkey): self.subkey = subkey
            def __enter__(self): return self
            def __exit__(self, *_): return False

        def open_key(hive, subkey, reserved, access):
            calls.append((hive, subkey, reserved, access))
            if values[subkey] is None:
                raise FileNotFoundError('missing package')
            return Key(subkey)

        def query(key, value_name):
            self.assertEqual(value_name, VALUE_NAME)
            return values[key.subkey], 1

        fake = SimpleNamespace(HKEY_CURRENT_USER=object(), KEY_READ=0x20019,
            REG_SZ=1, REG_EXPAND_SZ=2, OpenKey=open_key, QueryValueEx=query)
        with patch.dict('sys.modules', {'winreg': fake}):
            self.assertEqual(resolve(self.cn).server, 'cn')
        self.assertEqual(calls, [(fake.HKEY_CURRENT_USER, key, 0, fake.KEY_READ) for _, key in HYP_KEYS])

    def test_native_reader_missing_value_access_denial_and_wrong_type_use_fake_winreg(self):
        class Key:
            def __enter__(self): return self
            def __exit__(self, *_): return False

        fake = SimpleNamespace(HKEY_CURRENT_USER=object(), KEY_READ=0x20019, REG_SZ=1,
            REG_EXPAND_SZ=2, OpenKey=lambda *_: Key(),
            QueryValueEx=lambda *_: (_ for _ in ()).throw(FileNotFoundError('missing value')))
        with patch.dict('sys.modules', {'winreg': fake}):
            self.assert_unknown(self.cn, None, 'unmatched')
            fake.QueryValueEx = lambda *_: (str(self.cn.parent), 4)
            self.assert_unknown(self.cn, None, 'invalid_install_path')
            fake.OpenKey = lambda *_: (_ for _ in ()).throw(PermissionError('private registry path'))
            self.assert_unknown(self.cn, None, 'registry_unreadable')


if __name__ == '__main__':
    unittest.main()
