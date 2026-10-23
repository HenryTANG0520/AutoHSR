import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from types import SimpleNamespace

from autohsr.config import Settings
from autohsr.models import Scene, FocusLost
from autohsr.ux import report_context, recovery_text, exit_text, input_readiness


class ContractTests(unittest.TestCase):
    def test_unknown_game_privilege_is_not_treated_as_ready(self):
        self.assertIsNone(input_readiness(False, None))
        self.assertFalse(input_readiness(False, True))
        self.assertTrue(input_readiness(True, True))
        self.assertTrue(input_readiness(False, False))
    def test_independent_operations_ignore_irrelevant_battle_fields(self):
        bad = Settings(target_name='', stamina_limit=999, rounds=0)
        for operation in ('check', 'launch'):
            bad.validate(operation)
        with self.assertRaises(ValueError):
            bad.validate('daily')
        bad.battle = False
        bad.validate('daily')

    def test_legacy_report_time_is_labelled_and_day_is_not_invented(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'report.json'
            path.write_text('{}')
            context = report_context({}, path)
            self.assertIn('文件时间', context)
            self.assertIn('游戏日未核实', context)

    def test_battle_start_requires_explicit_map_even_if_only_one_row_is_visible(self):
        settings = Settings(target_location='')
        settings.validate('save')  # old draft remains readable/editable
        with self.assertRaisesRegex(ValueError, '地点'):
            settings.validate('daily')
        settings.battle = False
        settings.validate('daily')

    def test_failure_and_exit_results_are_independent_of_core_proof(self):
        report = dict(daily_verified=True, stamina_spent=210, results=[
            dict(task='mail', status='partial', detail='邮件入口未识别'),
            dict(task='close_game', status='skipped', detail='已选任务未全部核实')])
        self.assertIn('邮件入口', recovery_text(report))
        self.assertIn('仅补领奖', recovery_text(report))
        self.assertIn('游戏保留', exit_text(report))

    def test_token_only_payment_is_visible_and_needs_resource_reconciliation(self):
        from autohsr.ux import immersifier_text
        report=dict(error='结算未知',immersifiers_spent=2,immersifiers_pending=3)
        self.assertIn('仅补领奖',recovery_text(report))
        self.assertIn('沉浸器已确认 2，待核对 3',immersifier_text(report))
        self.assertEqual(immersifier_text({}),'')

    def test_focus_wait_does_not_force_focus_and_emits_both_states(self):
        from autohsr.app import Runner
        events = []
        runner = Runner(Settings(battle=False), events.append)
        window = Mock()
        window.emergency_pressed.return_value = False
        window.guard.side_effect = [FocusLost('lost'), object()]
        runner.wait_for_focus(window)
        window.focus.assert_not_called()
        self.assertEqual([e['waiting'] for e in events if e['type']=='focus_wait'], [True, False])
        self.assertGreater(runner.input_epoch, 0)

    def test_f10_can_stop_before_game_window_is_found(self):
        from unittest.mock import patch
        from autohsr.app import Runner
        runner = Runner(Settings())
        runner._monitor_end = SimpleNamespace(wait=Mock(side_effect=[False, True]))
        user = SimpleNamespace(GetAsyncKeyState=lambda key: 0x8000 if key == 0x79 else 0)
        with patch('autohsr.windows.user32', user):
            runner._hotkeys()
        self.assertTrue(runner._stop.is_set())

    def test_ocr_interruption_recaptures_instead_of_reusing_old_target(self):
        from autohsr.app import Context
        runner = SimpleNamespace(settings=Settings(), report=Mock(), input_epoch=0, checkpoint=Mock())
        calls = 0
        def checkpoint():
            nonlocal calls
            calls += 1
            if calls == 2:
                runner.input_epoch += 1
        runner.checkpoint.side_effect = checkpoint
        old, fresh = Scene([]), Scene([])
        window, vision = Mock(), Mock()
        window.capture.return_value = (object(), object())
        vision.read.side_effect = [old, fresh]
        context = Context(runner, window, vision)
        self.assertIs(context.snapshot(), fresh)
        self.assertEqual(window.capture.call_count, 2)
        window.click.assert_not_called()
