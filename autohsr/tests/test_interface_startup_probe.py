"""Pure mock tests for the scoped formal-CLI startup wrapper."""
from __future__ import annotations

from contextlib import contextmanager, redirect_stderr, redirect_stdout
from copy import deepcopy
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from tools import interface_startup_probe as probe


PRIVATE = 'PRIVATE_UID_987654321_INSTALL_PATH_AND_RAW_OCR'


class Stopped(Exception):
    pass


class Settings:
    baseline = None
    loads = []

    @classmethod
    def load(cls, *args, **kwargs):
        cls.loads.append((args, kwargs))
        return cls.baseline

    def save(self, *args, **kwargs):
        raise AssertionError('Probe must not save settings')


class Context:
    def __init__(self):
        self.calls, self.saved = [], []

    def currency_prepare_click(self, scene, intent, target):
        self.calls.append(('click', scene, intent, target))
        return 'original_click'

    def currency_prepare_back(self, scene):
        self.calls.append(('back', scene))
        return 'original_back'

    def currency_navigation_input(self, scene, choice):
        self.calls.append(('navigation', scene, choice.intent))
        return 'original_navigation'

    def evidence(self, scene, label):
        self.saved.append((scene, label))
        return PRIVATE


class DailyWorkflow:
    def __init__(self, context):
        self.context = context

    def _world(self, scene):
        return scene == 'verified_world'


class StartupProbeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.context = Context()
        Settings.baseline = SimpleNamespace(overlay_logs=True, notification_enabled=True, stamina_limit=240,
                                           battle=True, assignments=True, marker=PRIVATE)
        Settings.loads = []
        self.originals = tuple(Context.__dict__[name] for name in
            ('currency_prepare_click', 'currency_prepare_back', 'currency_navigation_input'))
        self.original_load = Settings.__dict__['load']
        self.cli_calls = []

    def runtime(self, callback):
        def cli_main(argv):
            self.cli_calls.append(argv)
            print(PRIVATE)
            print(PRIVATE, file=sys.stderr)
            return callback(argv)
        return SimpleNamespace(cli_main=cli_main, Settings=Settings, Context=Context,
                               Stopped=Stopped, DailyWorkflow=DailyWorkflow)

    def run_probe(self, callback, scope='phone'):
        return probe.run_probe(scope, output_root=self.root, runtime=self.runtime(callback))

    def assert_restored(self):
        self.assertEqual(tuple(Context.__dict__[name] for name in
            ('currency_prepare_click', 'currency_prepare_back', 'currency_navigation_input')), self.originals)
        self.assertIs(Settings.__dict__['load'], self.original_load)

    def test_allowed_start_and_world_phone_still_delegate_to_originals(self):
        def cli(argv):
            self.assertEqual(self.context.currency_prepare_click('login', 'enter_game', 'target'), 'original_click')
            self.assertEqual(self.context.currency_prepare_back('verified_world'), 'original_back')
            return 1
        result = self.run_probe(cli)
        self.assertEqual(self.cli_calls, [['--currency-wars-prepare', '--no-notify']])
        self.assertEqual([row['intent'] for row in result['input_actions']], ['enter_game', 'open_phone'])
        self.assertTrue(all(row['status'] == 'method_returned' for row in result['input_actions']))
        self.assertEqual(self.context.calls, [('click', 'login', 'enter_game', 'target'), ('back', 'verified_world')])
        self.assert_restored()

    def test_reward_and_other_prepare_clicks_stop_before_original_and_save_evidence(self):
        for intent in ('claim_supply', 'close_supply', 'close_login_reward', PRIVATE):
            with self.subTest(intent='fixed_or_unknown'):
                self.context = Context()
                result = self.run_probe(lambda argv: self.context.currency_prepare_click('scene', intent, 'target'))
                self.assertEqual(result['code'], 1)
                self.assertEqual(result['input_actions'], [])
                self.assertEqual(self.context.calls, [])
                self.assertEqual(self.context.saved, [('scene', 'interface_startup_scope_boundary')])
                self.assertNotIn(PRIVATE, json.dumps(result))
                self.assert_restored()

    def test_unknown_or_menu_escape_does_not_delegate_back(self):
        result = self.run_probe(lambda argv: self.context.currency_prepare_back('known_menu'))
        self.assertEqual(result['status'], 'stopped_before_menu_escape')
        self.assertEqual(self.context.calls, [])
        self.assertEqual(len(self.context.saved), 1)
        self.assert_restored()

    def test_five_currency_home_navigation_intents_delegate_but_open_mode_does_not(self):
        def cli(argv):
            for intent in sorted(probe.NAVIGATION):
                self.assertEqual(self.context.currency_navigation_input('scene', SimpleNamespace(intent=intent)), 'original_navigation')
            self.context.currency_navigation_input('lobby', SimpleNamespace(intent='open_mode'))
        result = self.run_probe(cli, 'currency-home')
        self.assertEqual(self.cli_calls, [['--currency-wars-locate', '--no-notify']])
        self.assertEqual(result['status'], 'stopped_before_open_mode')
        self.assertEqual(len(self.context.calls), 5)
        self.assertEqual(set(row['intent'] for row in result['input_actions']), probe.NAVIGATION)
        self.assertEqual(self.context.saved, [('lobby', 'interface_startup_scope_boundary')])
        self.assert_restored()

    def test_phone_scope_cannot_delegate_navigation_or_reward_detours(self):
        for intent in ('open_guide', 'close_points_rewards', 'select_standard', PRIVATE):
            with self.subTest(intent='fixed_or_unknown'):
                self.context = Context()
                result = self.run_probe(lambda argv: self.context.currency_navigation_input('scene', SimpleNamespace(intent=intent)))
                self.assertEqual(result['input_actions'], [])
                self.assertEqual(self.context.calls, [])
                self.assertEqual(result['status'], 'stopped_before_unapproved_navigation')
                self.assert_restored()

    def test_repeated_intent_is_not_replayed(self):
        def cli(argv):
            self.context.currency_prepare_click('login', 'enter_game', 'target')
            self.context.currency_prepare_click('login', 'enter_game', 'target')
        result = self.run_probe(cli)
        self.assertEqual(len(self.context.calls), 1)
        self.assertEqual(len(result['input_actions']), 1)
        self.assertEqual(result['status'], 'stopped_before_repeated_input')
        self.assertEqual(len(self.cli_calls), 1)
        self.assert_restored()

    def test_load_only_changes_overlay_on_a_copy_and_does_not_save(self):
        before = deepcopy(vars(Settings.baseline))
        def cli(argv):
            settings = Settings.load('fake_config_not_opened', flag=True)
            self.assertIsNot(settings, Settings.baseline)
            self.assertEqual(vars(settings), dict(before, overlay_logs=False))
            self.assertIn('--no-notify', argv)
            return 1
        self.run_probe(cli)
        self.assertEqual(vars(Settings.baseline), before)
        self.assertEqual(Settings.loads, [(('fake_config_not_opened',), {'flag': True})])
        self.assert_restored()

    def test_raw_cli_output_and_errors_stay_in_unique_local_directories(self):
        def failure(argv):
            raise RuntimeError(PRIVATE)
        first = self.run_probe(failure)
        second = self.run_probe(lambda argv: 2)
        self.assertEqual(first['code'], 2)
        self.assertNotIn(PRIVATE, json.dumps(first))
        self.assertNotIn(PRIVATE, json.dumps(second))
        folders = list(self.root.iterdir())
        self.assertEqual(len(folders), 2)
        self.assertTrue(all(PRIVATE in (folder/'stdout.log').read_text('utf-8') for folder in folders))
        self.assertTrue(all(PRIVATE in (folder/'stderr.log').read_text('utf-8') for folder in folders))
        self.assert_restored()

    def test_direct_standard_descriptor_output_is_local_too(self):
        def cli(argv):
            os.write(1, (PRIVATE+'_FD1\n').encode('utf-8'))
            os.write(2, (PRIVATE+'_FD2\n').encode('utf-8'))
            return 1
        result = self.run_probe(cli)
        folder, = self.root.iterdir()
        self.assertIn(PRIVATE+'_FD1', (folder/'stdout.log').read_text('utf-8'))
        self.assertIn(PRIVATE+'_FD2', (folder/'stderr.log').read_text('utf-8'))
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assert_restored()

    def test_summary_write_failure_preserves_already_delegated_actions(self):
        def cli(argv):
            self.context.currency_prepare_click('login', 'enter_game', 'target')
            return 1
        with patch.object(Path, 'write_text', side_effect=OSError(PRIVATE)):
            result = self.run_probe(cli)
        self.assertEqual(result['status'], 'probe_summary_unverified')
        self.assertEqual(result['code'], 2)
        self.assertEqual(result['input_actions'], [dict(intent='enter_game', status='method_returned')])
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assert_restored()

    def test_stream_close_failure_preserves_actions_without_public_exception(self):
        original_streams = probe._local_streams
        @contextmanager
        def failing_streams(stdout, stderr):
            with original_streams(stdout, stderr):
                yield
            raise OSError(PRIVATE)
        def cli(argv):
            self.context.currency_prepare_click('login', 'enter_game', 'target')
            return 1
        with patch.object(probe, '_local_streams', failing_streams):
            result = self.run_probe(cli)
        self.assertEqual(result['code'], 2)
        self.assertEqual(result['status'], 'probe_storage_failed')
        self.assertEqual(result['input_actions'], [dict(intent='enter_game', status='method_returned')])
        self.assertNotIn(PRIVATE, json.dumps(result))
        self.assert_restored()

    def test_evidence_failure_still_prevents_input_and_restores_patches(self):
        def failure(*args):
            raise OSError(PRIVATE)
        self.context.evidence = failure
        result = self.run_probe(lambda argv: self.context.currency_prepare_click('scene', 'claim_supply', 'target'))
        self.assertEqual(result['status'], 'scope_evidence_unverified')
        self.assertEqual(result['code'], 2)
        self.assertEqual(result['input_actions'], [])
        self.assertEqual(self.context.calls, [])
        self.assert_restored()

    def test_original_guard_failure_is_unverified_and_never_retried(self):
        def original(context, scene, intent, target):
            raise RuntimeError(PRIVATE)
        with patch.object(Context, 'currency_prepare_click', original):
            result = self.run_probe(lambda argv: self.context.currency_prepare_click('scene', 'enter_game', 'target'))
            self.assertIs(Context.currency_prepare_click, original)
        self.assertEqual(result['input_actions'], [dict(intent='enter_game', status='unverified')])
        self.assertEqual(len(self.cli_calls), 1)
        self.assertEqual(result['code'], 2)
        self.assert_restored()

    def test_missing_scope_never_imports_runtime_or_calls_formal_cli(self):
        output = io.StringIO()
        with patch.object(probe, '_runtime', side_effect=AssertionError('runtime must stay inactive')) as runtime:
            with redirect_stdout(output), redirect_stderr(output), self.assertRaises(SystemExit) as stopped:
                probe.main([])
        self.assertEqual(stopped.exception.code, 2)
        runtime.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_actual_cli_receives_no_notify_and_only_preparation_operation(self):
        cli = importlib.import_module('autohsr.__main__')
        runners, notification_settings = [], []
        class FakeRunner:
            def __init__(inner, settings, emit, **kwargs):
                runners.append(kwargs)
                self.assertIs(settings.overlay_logs, False)
                inner.settings = settings
            def run(inner):
                return {'status': 'partial', 'error': PRIVATE}
        app = SimpleNamespace(Runner=FakeRunner, inspect_game=lambda settings: None, launch_game=lambda settings: None)
        def hooks(settings, emit):
            notification_settings.append(settings.notification_enabled)
            return emit, lambda runner: runner
        Settings.baseline.validate = lambda operation: None
        notify = SimpleNamespace(hooks=hooks)
        with patch.object(cli, 'Settings', Settings), patch.dict(sys.modules,
                {'autohsr.app': app, 'autohsr.notify_runtime': notify}):
            for scope in probe.SCOPES:
                runtime = SimpleNamespace(cli_main=cli.main, Settings=Settings, Context=Context,
                    Stopped=Stopped, DailyWorkflow=DailyWorkflow)
                result = probe.run_probe(scope, output_root=self.root, runtime=runtime)
                self.assertEqual(result['code'], 1)
                self.assertNotIn(PRIVATE, json.dumps(result))
        self.assertEqual(notification_settings, [False, False])
        self.assertEqual([row['operation'] for row in runners], ['currency_wars_prepare']*2)
        self.assertTrue(all(row['new_battle_run'] is False for row in runners))
        self.assertNotIn('currency_locate', runners[0])
        self.assertIs(runners[1]['currency_locate'], True)
        self.assertEqual(vars(Settings.baseline)['overlay_logs'], True)
        self.assert_restored()


if __name__ == '__main__':
    unittest.main()
