"""Mute gate policy with fake devices; unit tests never change system audio."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from autohsr.audio import mute_verified


class AudioGateTests(unittest.TestCase):
    def fixture(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        return Path(folder.name)

    def test_original_state_is_saved_before_mute_and_readback_is_required(self):
        root = self.fixture()
        audio = Mock()
        audio.read.side_effect = [[dict(id="speaker", muted=False, volume_scalar=.61)],
                                  [dict(id="speaker", muted=True, volume_scalar=.61)]]
        def mute(ids):
            original = json.loads((root / "audio-before.json").read_text(encoding="utf-8"))
            self.assertFalse(original["endpoints"][0]["muted"])
            self.assertEqual(ids, ["speaker"])
        audio.mute.side_effect = mute
        result = mute_verified(audio, root)
        self.assertTrue(result["muted_verified"])
        self.assertFalse(result["game_launched"] or result["unmuted"])
        self.assertEqual(audio.read.call_count, 2)

    def test_empty_or_unknown_read_does_not_mute(self):
        for states in ([], [dict(id="speaker", muted=None)]):
            audio = Mock()
            audio.read.return_value = states
            with self.assertRaises(OSError):
                mute_verified(audio, self.fixture())
            audio.mute.assert_not_called()

    def test_failed_original_record_does_not_change_audio(self):
        root = self.fixture()
        (root / "audio-before.json").write_text("existing original", encoding="utf-8")
        audio = Mock()
        audio.read.return_value = [dict(id="speaker", muted=False)]
        with self.assertRaises(FileExistsError):
            mute_verified(audio, root)
        audio.mute.assert_not_called()
        self.assertEqual((root / "audio-before.json").read_text(), "existing original")

    def test_unmuted_or_changed_device_fails_verification(self):
        for after in ([dict(id="speaker", muted=False)], [dict(id="new-device", muted=True)]):
            audio = Mock()
            audio.read.side_effect = [[dict(id="speaker", muted=False)], after]
            root = self.fixture()
            with self.assertRaisesRegex(OSError, "禁止启动"):
                mute_verified(audio, root)
            self.assertFalse(json.loads((root / "audio-after.json").read_text(encoding="utf-8"))["muted_verified"])

    def test_mute_failure_keeps_original_and_never_restores(self):
        root = self.fixture()
        audio = Mock()
        audio.read.return_value = [dict(id="speaker", muted=False, volume_scalar=1)]
        audio.mute.side_effect = OSError("mute rejected")
        with self.assertRaisesRegex(OSError, "rejected"):
            mute_verified(audio, root)
        self.assertTrue((root / "audio-before.json").exists())
        audio.mute.assert_called_once_with(["speaker"])
