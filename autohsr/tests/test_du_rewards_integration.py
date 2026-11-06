"""Dedicated reward routing with fake CLI/Runner IO; never a live game."""
from contextlib import redirect_stderr, redirect_stdout
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, RunReport, TaskResult
from autohsr.tests import test_runner_recovery as native


class DuRewardsIntegrationTests(unittest.TestCase):
    def test_cli_freezes_explicit_scope_without_saving_or_starting_daily(self):
        from autohsr.__main__ import main
        for cassettes, periodic in ((False, False), (True, False), (False, True)):
            with self.subTest(cassettes=cassettes, periodic=periodic), tempfile.TemporaryDirectory() as folder:
                config = Path(folder) / 'settings.json'
                Settings(differential_universe_rewards=False, target_location='').save(config)
                original = config.read_bytes()
                fake = Mock()
                fake.run.return_value = RunReport(status='success', operation='du_rewards', report_saved=True)
                args = ['--du-rewards-only', '--config', str(config)]
                if cassettes:
                    args.append('--du-use-cassettes')
                if periodic:
                    args.append('--du-periodic-rewards')
                with patch('autohsr.app.Runner', return_value=fake) as factory, \
                     patch('autohsr.app.launch_game', side_effect=AssertionError('no launch')), \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main(args), 0)
                self.assertEqual(factory.call_args.kwargs['operation'], 'du_rewards')
                self.assertIs(factory.call_args.kwargs['du_use_cassettes'], cassettes)
                self.assertIs(factory.call_args.kwargs.get('du_periodic_rewards', False), periodic)
                self.assertFalse(factory.call_args.args[0].differential_universe_rewards)
                self.assertEqual(config.read_bytes(), original)

    def test_mixed_and_orphan_options_fail_before_config_or_game(self):
        from autohsr.__main__ import main
        cases = [
            ['--du-use-cassettes'], ['--differential-universe', '--du-use-cassettes'],
            ['--du-rewards-only', '--du-rewards'], ['--du-rewards-only', '--du-runs', '1'],
            ['--du-rewards-only', '--du-save'], ['--du-rewards-only', '--du-daily'],
            ['--du-rewards-only', '--resume-active-du'], ['--du-rewards-only', '--stamina', '10'],
            ['--du-rewards-only', '--new-battle-run'], ['--du-rewards-only', '--reward-only'],
            ['--du-rewards-only', '--redemption-code', 'synthetic'],
            ['--du-periodic-rewards'], ['--plan', '--du-periodic-rewards'],
            ['--du-rewards-only', '--du-periodic-rewards', '--du-use-cassettes'],
        ]
        for args in cases:
            with self.subTest(args=args), \
                 patch.object(Settings, 'load', side_effect=AssertionError('no config')), \
                 patch('autohsr.app.Runner', side_effect=AssertionError('no runner')), \
                 redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                 self.assertRaises(SystemExit):
                main(args)

    def test_native_routing_has_no_launch_daily_budget_or_du_run(self):
        with tempfile.TemporaryDirectory() as folder:
            helper = native.RunnerRecoveryTests()
            self.addCleanup(helper.doCleanups)
            context, finder = helper.fixture(Path(folder), SimpleNamespace())
            def rewards(c, *, use_cassettes=False):
                c.report.du_rewards = dict(schema=1, operation='du_rewards', status='complete',
                    rewards_verified=True, battle_started=False, use_cassettes=use_cassettes,
                    requested_categories=['拟合等级', '稳态数组', '可能性画廊'] +
                        (['月下奇谭'] if use_cassettes else []), all_notifications_cleared=True)
                return TaskResult('du_rewards', 'ok', 'red-dot rewards only')
            with patch('autohsr.du_rewards_only.run_rewards', side_effect=rewards) as run, \
                 patch.object(Runner, '_prepare_daily_game', side_effect=AssertionError('no launch')), \
                 patch.object(Runner, '_arm_hotkeys'), \
                 patch('autohsr.recovery.BattleBudget', side_effect=AssertionError('no budget')), \
                 patch('autohsr.differential_universe.DifferentialUniverseWorkflow.run',
                       side_effect=AssertionError('no DU run')), \
                 patch('autohsr.workflows.DailyWorkflow.ensure_main',
                       side_effect=AssertionError('no daily startup')):
                runner = Runner(Settings(overlay_logs=False, target_location=''), operation='du_rewards')
                context.report = runner.report
                report = runner.run()
            self.assertEqual(report.status, 'success')
            self.assertTrue(report.report_saved)
            self.assertTrue(report.du_rewards['rewards_verified'])
            self.assertEqual(report.differential_universe, {})
            self.assertEqual(report.weekly_plan, {})
            self.assertEqual((report.stamina_spent, report.battle_completed), (0, 0))
            self.assertFalse((Path(folder) / 'runs/battle-session.json').exists())
            run.assert_called_once_with(context, use_cassettes=False)
            finder.assert_called_once()

    def test_unknown_journal_blocks_before_game_or_hotkeys(self):
        for operation in ('du_rewards', 'differential_universe', 'daily'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                helper = native.RunnerRecoveryTests()
                self.addCleanup(helper.doCleanups)
                _, finder = helper.fixture(Path(folder), SimpleNamespace())
                with patch('autohsr.du_reward_store.preflight', side_effect=AutomationError('unknown reward intent')), \
                     patch.object(Runner, '_arm_hotkeys') as arm, \
                     patch.object(Runner, '_prepare_daily_game', side_effect=AssertionError('no launch')):
                    report = Runner(Settings(overlay_logs=False, differential_universe_rewards=True),
                                    operation=operation).run()
                self.assertEqual(report.status, 'failed')
                self.assertTrue(report.report_saved)
                self.assertEqual(report.operation, operation)
                self.assertIn('unknown reward intent', report.error)
                finder.assert_not_called()
                arm.assert_not_called()

    def test_generic_input_and_resource_option_cannot_escape_scope(self):
        c = SimpleNamespace(report=RunReport(operation='du_rewards'))
        c._require_gameplay_input = lambda: Context._require_gameplay_input(c)
        for method, args in ((Context._require_gameplay_input, ()),
                             (Context.click, (None, None)), (Context.key, ('esc',)),
                             (Context.drag, (None, (.1, .1), (.2, .2))),
                             (Context.scroll, (-1,)), (Context.move, (None, (.1, .1)))):
            with self.subTest(method=method.__name__), self.assertRaises(AutomationError):
                method(c, *args)
        for operation, option in (('daily', True), ('differential_universe', True),
                                   ('du_rewards', 1), ('du_rewards', 'true')):
            with self.subTest(operation=operation, option=option), self.assertRaises(ValueError):
                Runner(Settings(), operation=operation, du_use_cassettes=option)

    def test_notification_projects_reward_status_without_private_claims_or_score(self):
        from autohsr.notify_runtime import report_message
        report = RunReport(status='success', operation='du_rewards', report_saved=True,
            du_rewards=dict(rewards_verified=True, account_key='synthetic-private-key',
                            claims=[dict(item='synthetic-private-item')])).to_dict()
        title, body = report_message(Settings(), report)
        self.assertIn('差分奖励', title)
        self.assertIn('差分所选红点奖励：已核实', body)
        self.assertNotIn('synthetic-private', title + body)
        self.assertNotIn('差分完成', body)
        self.assertNotIn('周积分', body)


if __name__ == '__main__':
    unittest.main()
