import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.currency_wars_control import inspect_controls
from autohsr.models import Stopped


class ControlTests(unittest.TestCase):
    def test_probe_options_cannot_enter_gameplay_operation(self):
        for operation in ('daily', 'currency_wars_flow_test', 'currency_wars_drag_test'):
            with self.assertRaises(ValueError):
                Runner(Settings(), operation=operation, currency_control_probe=True)
            with self.assertRaises(ValueError):
                Runner(Settings(), operation=operation, currency_timeout_probe=True)
        with self.assertRaises(ValueError):
            Runner(Settings(), operation='currency_wars', currency_control_probe=True, currency_timeout_probe=True)

    def test_stopped_probe_retains_observation_and_cancel_evidence(self):
        runner = SimpleNamespace(report=SimpleNamespace(operation='currency_wars',currency_wars={'decision':'stop_without_input'}),
                                 inactive_duration=0, input_epoch=2, log=Mock(), _resume_step=Mock(),toggle_pause=Mock())
        context = SimpleNamespace(runner=runner, checkpoint=Mock(side_effect=Stopped('stop')))
        with patch('autohsr.currency_wars_control.time.monotonic', side_effect=(0,1,5)):
            with self.assertRaises(Stopped): inspect_controls(context)
        probe = runner.report.currency_wars['control_probe']
        self.assertEqual(probe['observations'],1)
        self.assertEqual(probe['input_epoch'],2)
        self.assertFalse(probe['gameplay_inputs_allowed'])

    def test_bounded_probe_never_turns_into_endless_watch(self):
        runner = SimpleNamespace(report=SimpleNamespace(operation='currency_wars',currency_wars={}),
                                 inactive_duration=0,input_epoch=0,log=Mock(),_resume_step=Mock(),toggle_pause=Mock())
        context = SimpleNamespace(runner=runner,checkpoint=Mock())
        with patch('autohsr.currency_wars_control.time.monotonic',side_effect=(0,1,15,30)):
            inspect_controls(context)
        self.assertEqual(runner._resume_step.call_count,2)
        self.assertEqual(runner.toggle_pause.call_count,2)
