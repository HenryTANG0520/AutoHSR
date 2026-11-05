"""Archive routing and isolation: native coordinator with no real game access."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, InputInterrupted, RunReport
from autohsr.tests import test_runner_recovery as native


class ArchiveIntegrationTests(unittest.TestCase):
    def test_save_confirmation_interruption_does_not_reenter_general_flow(self):
        from autohsr.differential_universe import DifferentialUniverseWorkflow
        from autohsr.du_archive_store import preflight
        from autohsr.tests.test_du_archive_workflow import make_context, normal_pages
        with tempfile.TemporaryDirectory() as folder:
            pending, context, first = make_context(folder, normal_pages())
            entry = dict(pending.report['run_results'][-1])
            flow = DifferentialUniverseWorkflow(context, 1, resume_active=True)
            flow.report['current_run'] = 1
            flow.report['run_results'].append(entry)
            def send(*args):
                if context.window.click.call_count == 5:
                    raise InputInterrupted('synthetic confirmation interruption')
            context.window.click.side_effect = send
            with self.assertRaises(AutomationError):
                flow._progress_run(first, 'victory')
            self.assertEqual(context.window.click.call_count, 5)
            self.assertTrue(entry['save_attempted'])
            self.assertEqual(entry['save_status'], 'unknown')
            self.assertTrue(Path(entry['victory_evidence']).is_file())
            self.assertFalse(context.du_archive_workflow.finished)
            context.window.key.assert_not_called()
            with self.assertRaises(AutomationError):
                preflight(folder)

    def test_unverified_archive_blocks_before_game_hotkeys_or_budget(self):
        for operation in ('differential_universe', 'daily', 'du_rewards', 'currency_wars_standard'):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as folder:
                helper = native.RunnerRecoveryTests()
                self.addCleanup(helper.doCleanups)
                _, finder = helper.fixture(Path(folder), SimpleNamespace())
                with patch('autohsr.du_archive_store.preflight', side_effect=AutomationError('unverified archive intent')) as gate, \
                     patch.object(Runner, '_arm_hotkeys') as arm, \
                     patch.object(Runner, '_prepare_daily_game', side_effect=AssertionError('no startup')), \
                     patch('autohsr.recovery.BattleBudget', side_effect=AssertionError('no budget')):
                    report = Runner(Settings(overlay_logs=False), operation=operation).run()
                self.assertEqual(report.status, 'failed')
                self.assertTrue(report.report_saved)
                self.assertIn('unverified archive intent', report.error)
                gate.assert_called_once_with(Path(report.run_dir).parent)
                finder.assert_not_called()
                arm.assert_not_called()

    def test_readonly_currency_observation_keeps_archive_gate_exemption(self):
        with tempfile.TemporaryDirectory() as folder:
            helper = native.RunnerRecoveryTests()
            self.addCleanup(helper.doCleanups)
            context, finder = helper.fixture(Path(folder), SimpleNamespace())
            with patch('autohsr.du_archive_store.preflight', side_effect=AssertionError('readonly exemption')) as gate, \
                 patch.object(Runner, '_arm_hotkeys'):
                runner = Runner(Settings(overlay_logs=False), operation='currency_wars')
                context.report = runner.report
                runner.run()
            gate.assert_not_called()
            finder.assert_called_once()

    def test_unfinished_archive_cannot_escape_through_generic_inputs_or_direct_name(self):
        context = SimpleNamespace(report=RunReport(operation='differential_universe'))
        context.du_archive_workflow = SimpleNamespace(c=context, finished=False)
        context._require_gameplay_input = lambda: Context._require_gameplay_input(context)
        for method, args in ((Context.click, (None, None)), (Context.key, ('esc',)),
                             (Context.drag, (None, (.1,.1), (.2,.2))),
                             (Context.scroll, (-1,)), (Context.move, (None, (.1,.1))),
                             (Context.differential_universe_save_name, (None, 'AutoHSR-1'))):
            with self.subTest(method=method.__name__), self.assertRaises(AutomationError):
                method(context, *args)
        context.du_archive_workflow.finished = True
        with self.assertRaises(AutomationError):
            Context.click(context, None, None, du_intent='du_save_confirm')


if __name__ == '__main__':
    unittest.main()
