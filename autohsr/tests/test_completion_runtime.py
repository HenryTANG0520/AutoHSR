from contextlib import nullcontext, redirect_stderr, redirect_stdout
from io import StringIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr import completion_runtime as completion
from autohsr.completion_window import CloseTarget
from autohsr.config import Settings
from autohsr.models import AutomationError, RunReport, TaskResult


class CompletionTests(TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(TemporaryDirectory()))
        self.saved = self.directory / 'report.json'
        self.receipt = self.directory / 'completion.json'
        self.events = []
        self.sound = self.enterContext(patch.object(completion, '_play'))
        self.enterContext(patch.object(completion, 'native_idle_lease', side_effect=nullcontext))
        self.target = self.enterContext(patch('autohsr.completion_window.CloseTarget')).return_value
        self.target.matches.return_value = False
        self.target.request.return_value = 'ok', 'same process closed'

    def report(self, **changes):
        defaults = dict(operation='plan', status='success', run_dir=str(self.directory),
                        report_saved=True, finished_at='2026-11-08T03:00:00+08:00',
                        results=[TaskResult('daily', 'ok', 'selected task complete')])
        report = RunReport(**(defaults | changes))
        self.saved.write_text(json.dumps(report.to_dict()), encoding='utf8')
        return report

    def wrap(self, report, *, second_window=False, stopped=False):
        settings = Settings(finish_sound=True, finish_close_game=True)
        emit, factory = completion.hooks(settings, self.events.append)
        base = Mock(stop_requested=stopped)

        def run():
            completion.bind_window(SimpleNamespace(hwnd=11))
            if second_window:
                completion.bind_window(SimpleNamespace(hwnd=12))
            emit(dict(type='finished', report=report.to_dict()))
            return report

        base.run.side_effect = run
        return factory(base)

    def test_completion_waits_for_a_durable_success_and_preserves_original(self):
        report = self.report()
        original = self.saved.read_bytes()
        runner = self.wrap(report)

        def assert_pending(_):
            self.assertEqual(json.loads(self.receipt.read_text(encoding='utf8'))['close_game'], 'pending')
            return 'ok', 'same process closed'

        self.target.request.side_effect = assert_pending
        self.assertIs(runner.run(), report)
        self.assertEqual(self.saved.read_bytes(), original)
        self.assertEqual(report.exit_status, 'ok')
        self.assertEqual(json.loads(self.receipt.read_text(encoding='utf8'))['sound'], 'requested')
        self.assertEqual([event['type'] for event in self.events], ['finished'])
        self.sound.assert_called_once()
        self.target.release.assert_called_once()
        with self.assertRaises(AutomationError):
            runner.run()

    def test_partial_or_stopped_or_unsaved_results_never_act(self):
        for flags, stop in ((dict(status='partial'), False), (dict(stamina_pending=20), False),
                            (dict(report_saved=False), False), ({}, True)):
            with self.subTest(flags=flags, stop=stop):
                report = self.report(**flags)
                self.wrap(report, stopped=stop).run()
                self.assertEqual(report.exit_status, 'skipped')
                self.assertFalse(self.receipt.exists())
        self.sound.assert_not_called()
        self.target.request.assert_not_called()

    def test_changed_window_only_skips_close(self):
        report = self.report()
        self.wrap(report, second_window=True).run()
        self.assertEqual(report.exit_status, 'skipped')
        self.sound.assert_called_once()
        self.target.request.assert_not_called()

    def test_old_pending_receipt_blocks_replay(self):
        report = self.report()
        self.receipt.write_text('old pending', encoding='utf8')
        self.wrap(report).run()
        self.assertEqual(self.receipt.read_text(encoding='utf8'), 'old pending')
        self.assertEqual(report.exit_status, 'skipped')
        self.sound.assert_not_called()
        self.target.request.assert_not_called()

    def test_missing_or_changed_saved_report_blocks_actions(self):
        report = self.report()
        self.saved.write_text('{"status":"partial"}', encoding='utf8')
        self.wrap(report).run()
        self.assertEqual(report.exit_status, 'skipped')
        self.sound.assert_not_called()
        self.target.request.assert_not_called()

    def test_unconfirmed_close_does_not_turn_success_into_failure(self):
        report = self.report()
        self.target.request.return_value = 'partial', 'window still present'
        self.wrap(report).run()
        self.assertEqual((report.status, report.exit_status), ('success', 'partial'))

    def test_cli_normal_daily_and_reward_only_have_distinct_completion_scope(self):
        from autohsr.__main__ import main
        game = self.directory / 'StarRail.exe'
        game.touch()
        config = self.directory / 'config.json'
        Settings(game_path=str(game), battle=False, finish_sound=True, finish_close_game=True).save(config)

        def factory(settings, emit, *, operation, **options):
            def run():
                completion.bind_window(SimpleNamespace(hwnd=11))
                return self.report(operation=operation)
            return Mock(run=run, stop_requested=False)

        with patch('autohsr.app.Runner', side_effect=factory), redirect_stderr(StringIO()):
            for flags, expected in ((['--reward-only'], 'not_requested'), ([], 'ok')):
                with self.subTest(flags=flags), redirect_stdout(StringIO()) as output:
                    self.assertEqual(main(['--run', '--config', str(config), *flags]), 0)
                    self.assertEqual(json.loads(output.getvalue())['exit_status'], expected)
        self.sound.assert_called_once()
        self.target.request.assert_called_once()


class CloseTargetTests(TestCase):
    def test_only_bound_window_receives_close_and_timeout_does_not_repeat(self):
        target = CloseTarget.__new__(CloseTarget)
        target.hwnd, target.pid, target.handle = 11, 10, 20
        target._window_pid = Mock(return_value=12)
        target._wait = Mock(return_value=258)
        target._hotkey = Mock(return_value=0)
        target._post = Mock(return_value=True)
        self.assertEqual(target.request(lambda: False)[0], 'skipped')
        target._post.assert_not_called()
        target._window_pid.return_value = 10
        self.assertEqual(target.request(lambda: False)[0], 'partial')
        target._post.assert_called_once_with(11, 0x10, 0, 0)

    def test_process_exit_is_distinct_from_message_sent(self):
        target = CloseTarget.__new__(CloseTarget)
        target.hwnd, target.pid, target.handle = 11, 10, 20
        target._window_pid = Mock(return_value=10)
        target._wait = Mock(side_effect=[258, 258, 0])
        target._hotkey = Mock(return_value=0)
        target._post = Mock(return_value=True)
        self.assertEqual(target.request(lambda: False)[0], 'ok')
