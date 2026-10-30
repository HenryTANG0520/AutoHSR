"""Configuration, CLI, native routing and text input with isolated fake IO."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Runner
from autohsr.config import Settings, SettingsError
from autohsr.models import InputInterrupted, RunReport, TaskResult
from autohsr.redemption_codes import CatalogFetchError
from autohsr.redemption_settings import resolve_batch
from autohsr.windows import GameWindow, Geometry
from autohsr.tests import test_runner_recovery as native_helpers


class RedemptionIntegrationTests(unittest.TestCase):
    def test_disabled_defaults_validate_without_network_and_manual_input_is_frozen(self):
        with patch('autohsr.redemption_codes.fetch_catalog', side_effect=AssertionError('no implicit fetch')):
            settings = Settings()
            settings.validate('save')
            self.assertFalse(settings.redemption_enabled)
            settings = Settings(redemption_enabled=True, redemption_source='manual', redemption_codes=['MiXeD7', '中文兑换码', 'MiXeD7'])
            settings.validate('redemption')
            batch = resolve_batch(settings)
            self.assertEqual(batch.codes, ('MiXeD7', '中文兑换码'))
            cloned = replace(settings)
            settings.redemption_codes.append('later')
            self.assertNotEqual(cloned.redemption_codes, settings.redemption_codes)
            self.assertEqual(batch.codes, ('MiXeD7', '中文兑换码'))
        for invalid in (' abc', 'a\nb', 'abc;cmd', ''):
            with self.subTest(code=invalid), self.assertRaises(SettingsError):
                Settings(redemption_codes=[invalid]).validate('save')

    def test_file_mode_is_offline_and_online_failure_uses_versioned_local_catalog(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'codes.json'
            path.write_text(json.dumps([dict(server='cn', code='testCode', expires_at=None)]), encoding='utf-8')
            with patch('autohsr.redemption_codes.fetch_catalog', side_effect=AssertionError('file mode offline')):
                self.assertEqual(resolve_batch(Settings(redemption_source='file', redemption_catalog=str(path))).codes, ('testCode',))
        with patch('autohsr.redemption_codes.fetch_catalog', side_effect=CatalogFetchError([])):
            batch = resolve_batch(Settings())
            self.assertTrue(batch.source['fallback'])
        interrupted = InputInterrupted('cancelled')
        with patch('autohsr.redemption_codes.fetch_catalog', side_effect=interrupted), self.assertRaises(InputInterrupted) as caught:
            resolve_batch(Settings())
        self.assertIs(caught.exception, interrupted)

    def test_local_preview_bypasses_config_runner_and_all_network(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'codes.json'
            path.write_text(json.dumps([dict(server='cn', code='CaseKept', expires_at=None)]), encoding='utf-8')
            stdout = io.StringIO()
            with patch.object(Settings, 'load', side_effect=AssertionError('no config read')), \
                 patch('autohsr.app.Runner', side_effect=AssertionError('no runner')), \
                 patch('autohsr.redemption_codes.fetch_catalog', side_effect=AssertionError('no network')), \
                 redirect_stdout(stdout):
                self.assertEqual(main(['--redemption-check', str(path), '--redemption-server', 'cn']), 0)
            data = json.loads(stdout.getvalue())
            self.assertEqual(data['codes'], ['CaseKept'])
            self.assertFalse(data['game_accessed'])

    def test_standalone_cli_uses_native_operation_and_does_not_save_overrides(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            Settings().save(path)
            original = path.read_bytes()
            fake = Mock()
            fake.run.return_value = RunReport(status='success', operation='redemption')
            with patch('autohsr.app.Runner', return_value=fake) as factory, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--redeem-codes', '--config', str(path), '--redemption-code', 'lowerCase7',
                                       '--redemption-server', 'global', '--no-redemption-mail']), 0)
            settings = factory.call_args.args[0]
            self.assertEqual(factory.call_args.kwargs['operation'], 'redemption')
            self.assertEqual((settings.redemption_source, settings.redemption_codes, settings.redemption_server),
                             ('manual', ['lowerCase7'], 'global'))
            self.assertFalse(settings.redemption_claim_mail)
            self.assertEqual(path.read_bytes(), original)

    def test_tool_scope_and_missing_run_arguments_fail_before_access(self):
        from autohsr.__main__ import main
        for args in (['--redemption-code', 'abc'], ['--redemption-check', 'missing'],
                     ['--redemption-fetch', '--redemption-server', 'cn', '--notify'],
                     ['--check', '--redemption-code', 'abc']):
            with self.subTest(args=args), patch('autohsr.app.find_game', side_effect=AssertionError('no game')), \
                 patch('autohsr.redemption_codes.fetch_catalog', side_effect=AssertionError('no network')), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    main(args)

    def test_unicode_writer_releases_modifiers_and_packet_even_on_interruption(self):
        window = GameWindow.__new__(GameWindow)
        window.send = Mock()
        geometry = Geometry(0, 0, 1920, 1080)
        with patch('autohsr.windows.user32.SendInput', side_effect=lambda size, *args: size) as release, \
             patch('autohsr.windows.time.sleep'):
            window.type_redemption_code('a中文7', geometry, checkpoint=lambda: None)
        self.assertEqual(window.send.call_count, 5)
        self.assertEqual(release.call_count, 5)
        packets = window.send.call_args_list[2].args[0]
        self.assertEqual((packets[0].ki.wScan, packets[0].ki.dwFlags, packets[1].ki.dwFlags), (ord('中'), 4, 6))
        window.send.reset_mock()
        window.send.side_effect = InputInterrupted('synthetic interrupted selection')
        with patch('autohsr.windows.user32.SendInput', return_value=2) as release, self.assertRaises(InputInterrupted):
            window.type_redemption_code('abc', geometry, checkpoint=lambda: None)
        release.assert_called_once()
        with self.assertRaises(Exception):
            window.type_redemption_code('a\ncmd', geometry, checkpoint=lambda: None)

    def test_native_redemption_route_never_creates_battle_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            helper = native_helpers.RunnerRecoveryTests()
            self.addCleanup(helper.doCleanups)
            helper.fixture(Path(folder), SimpleNamespace())
            with patch('autohsr.redemption_run.run_redemption', return_value=TaskResult('redemption', 'ok', 'synthetic batch done')) as run, \
                 patch('autohsr.recovery.BattleBudget', side_effect=AssertionError('no battle budget')):
                report = Runner(Settings(redemption_source='manual', redemption_codes=['abc'], overlay_logs=False), operation='redemption').run()
            self.assertEqual(report.status, 'success')
            self.assertTrue(report.report_saved)
            self.assertEqual(report.stamina_spent, 0)
            run.assert_called_once()

    def test_daily_order_and_reward_only_exclusion_preserve_existing_settings(self):
        settings = Settings(assignments=False, battle=False, daily=True, mail=True, battlepass=False,
                            redemption_enabled=True, redemption_source='manual', redemption_codes=['abc'])
        runner = Runner(settings)
        runner.checkpoint = Mock()
        order = []
        def task(name):
            def call():
                order.append(name)
                if name == 'daily':
                    runner.report.daily_verified = True
                return TaskResult(name, 'ok', 'synthetic verified')
            return call
        workflow = SimpleNamespace(daily=task('daily'), redemption=task('redemption'), mail=task('mail'))
        runner._run_tasks(SimpleNamespace(), workflow)
        self.assertEqual(order, ['daily', 'redemption', 'mail'])
        other = Runner(settings, operation='reward_only')
        other.checkpoint = Mock()
        other._run_tasks(SimpleNamespace(), workflow)
        self.assertEqual(order.count('redemption'), 1)

    def test_task_tree_explicit_selection_does_not_inherit_hidden_redemption(self):
        from autohsr.task_workflow import compile_recipe, task_spec
        base = Settings(redemption_enabled=True, redemption_source='manual', redemption_codes=['abc'])
        def node(tasks):
            return dict(id='daily-step', type='task', task='daily', params=dict(tasks=tasks))
        current, _ = task_spec(base, node(['daily']), Path('.'))
        self.assertFalse(current.redemption_enabled)
        recipe = compile_recipe(dict(version=1, name='fixture', steps=[node(['redemption'])]))
        current, options = task_spec(base, recipe.steps[0], recipe.base_dir)
        self.assertTrue(current.redemption_enabled)
        self.assertFalse(current.battle)
        self.assertFalse(current.daily)
        self.assertEqual(options['operation'], 'daily')

    def test_schedule_freezes_local_catalog_before_enabling_execution(self):
        from autohsr.schedule_dispatch import NativeScheduleExecutor
        from autohsr.schedule_plan import ScheduleError, validate
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            catalog = root / 'codes.json'
            catalog.write_text('[]', encoding='utf-8')
            target = dict(type='task', task='daily', params=dict(tasks=['redemption'],
                redemption_source='file', redemption_catalog='codes.json'))
            plan = validate(dict(version=1, id='fixture', name='fixture', time='08:30', weekdays=[1], target=target))
            executor = NativeScheduleExecutor(Settings(), base_dir=root, run_root=root / 'runs', busy_probe=lambda: False)
            frozen = executor.freeze(plan)
            self.assertEqual(len(frozen['dependencies']), 1)
            catalog.write_text('[{}]', encoding='utf-8')
            with self.assertRaises(ScheduleError):
                executor.revalidate(frozen)
