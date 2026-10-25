"""Foreground log delivery must not depend on or feed back into game OCR."""
import json
from pathlib import Path
import queue
import tempfile
from unittest import TestCase
from unittest.mock import Mock

from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.overlay import OverlayService, apply_event, overlay_bounds


class OverlayTests(TestCase):
    def test_old_configs_default_enabled_and_switch_round_trips(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text('{}', encoding='utf8')
            self.assertTrue(Settings.load(path).overlay_logs)
            Settings(overlay_logs=False).save(path)
            self.assertFalse(Settings.load(path).overlay_logs)
            data = json.loads(path.read_text('utf8'))
            data['overlay_logs'] = 'false'
            path.write_text(json.dumps(data), encoding='utf8')
            with self.assertRaisesRegex(ValueError, 'overlay_logs'):
                Settings.load(path)

    def test_overlay_tracks_client_on_both_monitors(self):
        self.assertEqual(overlay_bounds(100, 200, 1920, 1080), (120, 990, 480, 220))
        self.assertEqual(overlay_bounds(-1920, 0, 1920, 1080), (-1900, 790, 480, 220))
        self.assertIsNone(overlay_bounds(0, 0, 800, 450))

    def test_runner_preserves_file_event_delivery_and_forwards_live_status(self):
        events = []
        runner = Runner(Settings(), events.append)
        runner._overlay = Mock()
        runner.log('test', 'warning')
        runner.emit(dict(type='paused', paused=True))
        self.assertEqual(events[0], dict(type='log', message='test', level='warning'))
        self.assertEqual(runner._overlay.publish.call_count, 2)
        overlay = Mock()
        for event in events:
            apply_event(overlay, event)
        overlay.append.assert_called_once_with('test', 'warning')
        overlay.set_status.assert_called_once_with('已暂停')

    def test_display_congestion_never_blocks_runner_or_leaks_scene_payloads(self):
        service = OverlayService()
        service.inbox = queue.Queue(maxsize=1)
        service.publish(dict(type='log', message='first'))
        service.publish(dict(type='log', message='second'))
        self.assertEqual(service.inbox.get_nowait()['message'], 'first')
        service.publish(dict(type='du_observation', screenshot='private.png'))
        self.assertTrue(service.inbox.empty())

    def test_close_is_idempotent_even_when_never_started(self):
        service = OverlayService()
        service.start(None)
        service.close()
        service.close()
        self.assertIsNone(service.process)
