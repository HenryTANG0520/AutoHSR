"""Verify the public offline entry does not open configuration or the game."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from PIL import Image

from autohsr.__main__ import main
from autohsr.tests.test_reward_guide_stitch import _calendar


class RewardGuideCliTests(unittest.TestCase):
    def test_formal_cli_uses_ordered_crops_and_keeps_an_existing_target(self):
        with TemporaryDirectory() as folder, patch('autohsr.__main__.Settings.load') as load:
            root = Path(folder)
            first, second, target = (root / name for name in ('top.png', 'bottom.png', 'guide.png'))
            image = _calendar()[:, :, ::-1]
            Image.fromarray(image[:176]).save(first)
            Image.fromarray(image[61:237]).save(second)
            args = ['--reward-guide-stitch', str(first), str(second), '--reward-guide-output', str(target)]
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 0)
            self.assertEqual(json.loads(output.getvalue()),
                             dict(status='ok', overlap_rows=[115], width=192, height=237))
            original = target.read_bytes()
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 1)
            self.assertEqual(json.loads(output.getvalue())['status'], 'invalid_target')
            self.assertEqual(target.read_bytes(), original)
            load.assert_not_called()

    def test_incomplete_or_combined_args_do_not_call_the_exporter(self):
        for args in (['--reward-guide-output', 'dest.png'],
                     ['--reward-guide-stitch', 'source.png'],
                     ['--reward-guide-stitch', 'source.png', '--reward-guide-output', 'dest.png', '--config', 'a']):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                with patch('autohsr.reward_guide_export.export_reward_guide') as export:
                    main(args)
                export.assert_not_called()
            self.assertEqual(stopped.exception.code, 2)
