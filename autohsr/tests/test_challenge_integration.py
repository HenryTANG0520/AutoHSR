"""High-difficulty configuration/CLI/native routing, with fake IO only."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Context, Runner
from autohsr.challenge_cli import read_plan
from autohsr.config import Settings, SettingsError
from autohsr.models import AutomationError, RunReport, TaskResult
from autohsr.tests import test_runner_recovery as native


PLAN = dict(mode='memory_of_chaos', levels=[7, 12],
    team1=['Firefly', 'RuanMei', 'Fugue', 'Lingsha'],
    team2=['Acheron', 'Jiaoqiu', 'Pela', 'Aventurine'])


class ChallengeIntegrationTests(unittest.TestCase):
    def test_dormant_default_and_explicit_save_do_not_access_game(self):
        with tempfile.TemporaryDirectory() as folder, \
             patch('autohsr.app.find_game', side_effect=AssertionError('no game')):
            path = Path(folder) / 'config.json'
            original = Settings(challenge_plan=PLAN)
            snapshot = replace(original)
            original.challenge_plan['team1'][0] = 'Herta'
            self.assertEqual(snapshot.challenge_plan['team1'][0], 'Firefly')
            snapshot.save(path)
            self.assertEqual(Settings.load(path).challenge_plan, PLAN)
            Settings().validate('save')
            self.assertEqual(Settings().challenge_plan, {})
        with self.assertRaises(SettingsError):
            Settings().validate('challenge_prepare')
        for mode in ('pure_fiction', 'apocalyptic_shadow'):
            plan = dict(PLAN, mode=mode, levels=[1, 4])
            Settings(challenge_plan=plan).validate('save')
            with self.assertRaises(SettingsError):
                Settings(challenge_plan=plan).validate('challenge_prepare')

    def test_preview_has_strict_bounded_json_without_loading_config_or_runner(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'plan.json'
            path.write_text(json.dumps(PLAN), encoding='utf-8')
            output = io.StringIO()
            with patch.object(Settings, 'load', side_effect=AssertionError('no config')), \
                 patch('autohsr.app.Runner', side_effect=AssertionError('no runner')), redirect_stdout(output):
                self.assertEqual(main(['--challenge-check', str(path)]), 0)
            data = json.loads(output.getvalue())
            self.assertEqual(data['plan'], PLAN)
            self.assertFalse(data['game_accessed'])
            for content in ('{"mode":"memory_of_chaos","mode":"pure_fiction"}',
                            '{"mode": NaN}', ' ' * (64 * 1024 + 1)):
                path.write_text(content, encoding='utf-8')
                with self.assertRaises(ValueError):
                    read_plan(path)

    def test_prepare_cli_freezes_current_override_without_saving(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            plan = Path(folder) / 'plan.json'
            Settings().save(config)
            before = config.read_bytes()
            plan.write_text(json.dumps(PLAN), encoding='utf-8')
            fake = Mock()
            fake.run.return_value = RunReport(status='success', operation='challenge_prepare')
            with patch('autohsr.app.Runner', return_value=fake) as factory, \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--challenge-prepare', '--challenge-plan', str(plan), '--config', str(config)]), 0)
            self.assertEqual(factory.call_args.kwargs['operation'], 'challenge_prepare')
            self.assertEqual(factory.call_args.args[0].challenge_plan, PLAN)
            self.assertEqual(config.read_bytes(), before)

    def test_mixed_or_orphan_options_are_rejected_before_config_or_game(self):
        from autohsr.__main__ import main
        for args in (['--challenge-plan', 'not-read.json'],
                     ['--challenge-prepare', '--stamina', '10'],
                     ['--challenge-prepare', '--reward-only'],
                     ['--challenge-prepare', '--redemption-code', 'x'],
                     ['--challenge-prepare', '--du-team', 'x'],
                     ['--challenge-check', 'not-read.json', '--config', 'not-read.json']):
            with self.subTest(args=args), patch.object(Settings, 'load', side_effect=AssertionError('no config')), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main(args)

    def test_native_preparation_has_no_daily_startup_or_resource_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            helper = native.RunnerRecoveryTests()
            self.addCleanup(helper.doCleanups)
            context, find = helper.fixture(Path(folder), SimpleNamespace())
            with patch('autohsr.challenge_prepare.prepare_challenge', return_value=TaskResult('challenge_prepare', 'ok', 'prepared only')) as prepare, \
                 patch.object(Runner, '_prepare_daily_game', side_effect=AssertionError('no launch/navigation')), \
                 patch.object(Runner, '_arm_hotkeys'), \
                 patch('autohsr.recovery.BattleBudget', side_effect=AssertionError('no daily budget')):
                report = Runner(Settings(challenge_plan=PLAN, overlay_logs=False), operation='challenge_prepare').run()
            self.assertEqual(report.status, 'success')
            self.assertTrue(report.report_saved)
            self.assertEqual(report.stamina_spent, 0)
            self.assertEqual(report.battle_completed, 0)
            prepare.assert_called_once_with(context)
            find.assert_called_once()
            self.assertFalse((Path(folder) / 'runs/battle-session.json').exists())

    def test_generic_input_cannot_bypass_high_difficulty_contract(self):
        c = SimpleNamespace(report=RunReport(operation='challenge_prepare'))
        with self.assertRaises(AutomationError):
            Context._require_gameplay_input(c)
        with self.assertRaises(AutomationError):
            Context.redemption_input(c, None, None)
        with self.assertRaises(AutomationError):
            Context.challenge_prepare_input(SimpleNamespace(report=RunReport(operation='daily')), None, None)

    def test_outer_notification_names_the_preparation_scope_without_private_details(self):
        from autohsr.notify_runtime import report_message
        report = RunReport(status='success', operation='challenge_prepare', report_saved=True,
            challenge=dict(plan=PLAN, account_key='fake-private-key', preparation_page_verified=True)).to_dict()
        title, body = report_message(Settings(), report)
        self.assertIn('高难备战', title)
        self.assertNotIn('fake-private-key', title + body)
        self.assertNotIn('Firefly', title + body)
