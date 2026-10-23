import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from autohsr.config import Settings
from autohsr.__main__ import main


class CliContractTests(unittest.TestCase):
    def test_ten_du_runs_and_optional_flags_are_transient_and_mode_scoped(self):
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/'config.json'
            Settings().save(config)
            original=config.read_bytes()
            with patch('autohsr.app.Runner') as runner,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                runner.return_value.run.return_value={'status':'success'}
                self.assertEqual(main(['--differential-universe','--du-runs','10','--du-team','哈哈哈哈','--du-mode','periodic','--du-save','--du-rewards','--config',str(config)]),0)
                settings=runner.call_args.args[0]
                self.assertEqual(settings.differential_universe_runs,10)
                self.assertTrue(settings.differential_universe_save)
                self.assertTrue(settings.differential_universe_rewards)
                self.assertEqual(settings.differential_universe_team,'哈哈哈哈')
                self.assertEqual(settings.differential_universe_mode,'periodic')
            self.assertEqual(config.read_bytes(),original)
            with patch('autohsr.gui.main') as gui,redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--du-save']),2)
                self.assertEqual(main(['--du-rewards']),2)
                self.assertEqual(main(['--du-team','哈哈哈哈']),2)
                self.assertEqual(main(['--du-mode','periodic']),2)
            gui.assert_not_called()

    def test_reward_only_is_an_in_memory_nonbattle_run(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            Settings().save(config)
            original = config.read_bytes()
            with patch('autohsr.app.Runner') as runner, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                runner.return_value.run.return_value = {'status': 'success'}
                self.assertEqual(main(['--run', '--reward-only', '--config', str(config)]), 0)
                settings = runner.call_args.args[0]
                self.assertFalse(settings.battle)
                self.assertTrue(settings.daily)
                self.assertFalse(settings.mail)
                self.assertEqual(runner.call_args.kwargs['operation'], 'reward_only')
            self.assertEqual(config.read_bytes(), original)

    def test_recovery_flags_without_run_never_open_gui(self):
        with patch('autohsr.gui.main') as gui, redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--reward-only']), 2)
            self.assertEqual(main(['--new-battle-run']), 2)
        gui.assert_not_called()

    def test_differential_universe_is_a_separate_three_run_capable_operation(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'config.json'
            Settings().save(config)
            original = config.read_bytes()
            with patch('autohsr.app.Runner') as runner, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                runner.return_value.run.return_value = {'status': 'success'}
                self.assertEqual(main(['--differential-universe', '--du-runs', '2', '--resume-active-du',
                                       '--du-periodic-rank', '5', '--config', str(config)]), 0)
                self.assertEqual(runner.call_args.kwargs['operation'], 'differential_universe')
                self.assertEqual(runner.call_args.kwargs['du_runs'], 2)
                self.assertTrue(runner.call_args.kwargs['du_resume_active'])
                self.assertEqual(runner.call_args.kwargs['du_periodic_rank'], 5)
                self.assertEqual(runner.call_args.args[0].differential_universe_runs, 2)
            self.assertEqual(config.read_bytes(), original)

    def test_du_run_count_requires_differential_universe_mode(self):
        with patch('autohsr.gui.main') as gui, redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--du-runs', '2']), 2)
        gui.assert_not_called()

    def test_du_resume_flag_requires_differential_universe_mode(self):
        with patch('autohsr.gui.main') as gui, redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--resume-active-du']), 2)
            self.assertEqual(main(['--differential-universe', '--du-periodic-rank', '5']), 2)
            self.assertEqual(main(['--differential-universe', '--resume-active-du', '--du-periodic-rank', '11']), 2)
        gui.assert_not_called()
