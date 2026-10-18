import io
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from autohsr.config import Settings
from autohsr.__main__ import main


class CliContractTests(unittest.TestCase):
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
