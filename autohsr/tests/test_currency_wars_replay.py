"""Local image/manifest validation, conservative replay, and independent CLI."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from autohsr.currency_wars import decide, observe
from autohsr.currency_wars_replay import load_sample, replay_sample, save_sample
from autohsr.models import AutomationError, Scene, Token


class ReplayTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.image = np.zeros((90, 160, 3), dtype=np.uint8)
        self.screenshot = self.root / "frame.png"
        self.screenshot.write_bytes(cv2.imencode(".png", self.image)[1].tobytes())
        self.scene = Scene([Token("货币战争", .99, (.1, .1, .7, .3))], image=self.image)
        self.manifest = save_sample(self.scene, self.screenshot, origin="synthetic")

    def edit(self, **fields):
        data = json.loads(self.manifest.read_text(encoding="utf-8"))
        data.update(fields)
        self.manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_replay_preserves_files_and_never_verifies_gameplay(self):
        self.edit(expected_mode_text_visible=True)
        before = (self.screenshot.read_bytes(), self.manifest.read_bytes())
        result = replay_sample(self.manifest)
        self.assertEqual(result["origin"], "synthetic")
        self.assertTrue(result["expectation_passed"])
        self.assertFalse(result["game_accessed"])
        self.assertEqual(result["decision"], dict(action="stop_without_input", reason="rules_unverified"))
        self.assertFalse(any(result["observation"][name] for name in ("page_verified", "rules_verified", "gameplay_enabled", "completion_verified")))
        self.assertEqual((self.screenshot.read_bytes(), self.manifest.read_bytes()), before)

    def test_loaded_historical_frame_cannot_masquerade_as_live(self):
        _, loaded = load_sample(self.manifest)
        self.assertEqual(loaded.captured_at, 0)

    def test_unknown_page_decision_stops(self):
        self.assertEqual(decide(observe(Scene([]), .65)).reason, "unknown_page")

    def test_changed_image_fails_hash_check(self):
        self.screenshot.write_bytes(self.screenshot.read_bytes() + b"modified")
        with self.assertRaisesRegex(AutomationError, "SHA256"):
            load_sample(self.manifest)

    def test_decoder_uses_the_exact_bytes_that_were_hashed(self):
        original = Path.read_bytes
        replacement = cv2.imencode(".png", np.full_like(self.image, 255))[1].tobytes()
        def read_and_replace(path):
            content = original(path)
            if path == self.screenshot:
                path.write_bytes(replacement)
            return content
        with patch.object(Path, "read_bytes", read_and_replace):
            _, loaded = load_sample(self.manifest)
        self.assertEqual(int(loaded.image.max()), 0)

    def test_parent_and_absolute_image_paths_are_rejected(self):
        for image in ("../outside.png", str(self.screenshot.resolve())):
            with self.subTest(image=image):
                self.edit(image=image)
                with self.assertRaisesRegex(AutomationError, "样本目录"):
                    load_sample(self.manifest)

    def test_dimension_mismatch_is_rejected(self):
        self.edit(dimensions=[1920, 1080])
        with self.assertRaisesRegex(AutomationError, "尺寸"):
            load_sample(self.manifest)

    def test_unknown_fields_cannot_enable_verified_rules(self):
        self.edit(rules_verified=True)
        with self.assertRaisesRegex(AutomationError, "字段"):
            load_sample(self.manifest)

    def test_invalid_token_coordinates_are_rejected(self):
        self.edit(tokens=[dict(text="货币战争", score=.99, box=[0, 0, 2, 1])])
        with self.assertRaises(AutomationError):
            load_sample(self.manifest)

    def test_missing_capture_metadata_is_rejected(self):
        self.edit(recorded_at="2026-10-17T12:00:00")
        with self.assertRaisesRegex(AutomationError, "时区"):
            load_sample(self.manifest)

    def test_reocr_compares_result_without_accepting_recorded_text_as_truth(self):
        self.edit(expected_mode_text_visible=True)
        with patch("autohsr.currency_wars_replay.IsolatedVision") as vision:
            vision.return_value.read.return_value = Scene([])
            result = replay_sample(self.manifest, reocr=True)
        self.assertTrue(result["recorded_mode_text_visible"])
        self.assertFalse(result["expectation_passed"])
        self.assertEqual(result["decision"]["reason"], "unknown_page")

    def test_cli_replay_skips_daily_config_and_runner(self):
        from autohsr.__main__ import main
        with patch("autohsr.config.Settings.load", side_effect=AssertionError("daily config touched")), \
                patch("autohsr.app.Runner") as runner, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(["--currency-wars-replay", str(self.manifest)]), 0)
        runner.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())["status"], "replayed")

    def test_cli_expectation_failure_and_incompatible_flags(self):
        from autohsr.__main__ import main
        self.edit(expected_mode_text_visible=False)
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(main(["--currency-wars-replay", str(self.manifest)]), 1)
            self.assertEqual(main(["--replay-ocr"]), 2)
            self.assertEqual(main(["--currency-wars-replay", str(self.manifest), "--new-battle-run"]), 2)
