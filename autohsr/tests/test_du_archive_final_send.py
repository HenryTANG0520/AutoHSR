"""Archive input boundary with real window dispatch, fake Win32, and real receipts."""
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from autohsr import du_archive_store, windows
from autohsr.du_archive_store import ArchiveStore, NAME, SEQUENCE, preflight, read
from autohsr.du_archive_workflow import ArchiveWorkflow, save_victory
from autohsr.models import AutomationError, Stopped
from autohsr.tests.test_du_archive_workflow import archive_replay_clock, make_context, normal_pages


@contextmanager
def native_archive():
    with archive_replay_clock() as advance, tempfile.TemporaryDirectory() as folder:
        flow, context, first = make_context(folder, normal_pages(), fresh=True)
        context.sleep.side_effect = advance
        window = windows.GameWindow.__new__(windows.GameWindow)
        window.hwnd = 123
        context.window = window
        platform = Mock()
        platform.IsWindow.return_value = True
        platform.IsWindowVisible.return_value = True
        platform.IsIconic.return_value = False
        platform.GetForegroundWindow.return_value = window.hwnd
        platform.GetAsyncKeyState.return_value = 0
        platform.GetSystemMetrics.side_effect = {76: 0, 77: 0, 78: 1920, 79: 1080}.__getitem__
        platform.MapVirtualKeyW.return_value = 1
        sends = []

        def send(count, *_):
            sends.append((context.du_archive_workflow.request.intent, count))
            return count

        platform.SendInput.side_effect = send
        with (patch.object(windows, 'user32', platform),
              patch.object(windows, 'geometry', return_value=first.geometry) as screen_geometry,
              patch.object(windows, 'time', SimpleNamespace(sleep=advance))):
            yield SimpleNamespace(folder=Path(folder), flow=flow, context=context, first=first,
                                  advance=advance, platform=platform, geometry=screen_geometry,
                                  sends=sends, send=send)


@contextmanager
def after_final_durable_check(intent, change):
    original = ArchiveStore.require_durable
    checks = 0

    def check(store):
        nonlocal checks
        original(store)
        if store.data['actions'][-1]['request']['intent'] == intent:
            checks += 1
            if checks == 2:
                change()

    with patch.object(ArchiveStore, 'require_durable', check):
        yield


class ArchiveFinalSendTests(unittest.TestCase):
    def assert_not_sent(self, runtime, intent):
        record = read(runtime.folder / NAME)
        self.assertEqual(read(record['journal']), record)
        self.assertEqual([step['request']['intent'] for step in record['actions']],
                         list(SEQUENCE[:SEQUENCE.index(intent)+1]))
        self.assertTrue(all(step['status'] == 'verified' for step in record['actions'][:-1]))
        self.assertEqual(record['actions'][-1]['status'], 'not_sent')
        self.assertEqual(record['actions'][-1]['after'], [])
        self.assertNotIn(intent, [request for request, _ in runtime.sends])
        self.assertFalse(record['return_verified'])
        self.assertEqual(record['save_verified'], intent == 'du_save_close')
        if intent == 'du_save_open':
            self.assertEqual(record['status'], 'abort_before_input')
            self.assertEqual(preflight(runtime.folder), record)
        else:
            self.assertEqual(record['status'], 'unknown')
            with self.assertRaisesRegex(AutomationError, '待核对'):
                preflight(runtime.folder)

    def test_all_archive_actions_recheck_age_after_the_second_durable_read(self):
        for intent in SEQUENCE:
            with self.subTest(intent=intent), native_archive() as runtime:
                with after_final_durable_check(intent, lambda: runtime.advance(9)):
                    with self.assertRaises(AutomationError):
                        save_victory(runtime.flow, runtime.first)
                self.assert_not_sent(runtime, intent)

    def test_final_boundary_rejects_changed_scene_epoch_or_foreground(self):
        for change in ('scene', 'epoch', 'foreground', 'geometry'):
            with self.subTest(change=change), native_archive() as runtime:
                def invalidate():
                    if change == 'scene':
                        runtime.context.last_scene = replace(runtime.context.last_scene)
                    elif change == 'epoch':
                        runtime.context.runner.input_epoch += 1
                    elif change == 'foreground':
                        runtime.platform.GetForegroundWindow.return_value = 99
                    else:
                        runtime.geometry.return_value = replace(runtime.first.geometry, left=1)

                # Escape must be bound to the same geometry as the archive frame.
                with after_final_durable_check('du_save_close', invalidate):
                    with self.assertRaises(AutomationError):
                        save_victory(runtime.flow, runtime.first)
                self.assert_not_sent(runtime, 'du_save_close')

    def test_f10_after_the_last_source_check_blocks_the_first_packet(self):
        with native_archive() as runtime:
            require = ArchiveWorkflow.require_current_input

            def stop_after_read(workflow, scene, action):
                require(workflow, scene, action)
                runtime.platform.GetAsyncKeyState.return_value = 1

            with patch.object(ArchiveWorkflow, 'require_current_input', stop_after_read):
                with self.assertRaises(Stopped):
                    save_victory(runtime.flow, runtime.first)
            self.assert_not_sent(runtime, 'du_save_open')

    def test_partial_native_name_attempt_remains_unknown_and_releases_keys(self):
        with native_archive() as runtime:
            def fail_first_name_batch(count, *args):
                result = runtime.send(count, *args)
                if runtime.sends[-1] == ('du_save_name', 2) and runtime.sends.count(runtime.sends[-1]) == 1:
                    return count - 1
                return result

            runtime.platform.SendInput.side_effect = fail_first_name_batch
            with self.assertRaisesRegex(AutomationError, 'Windows 拒绝'):
                save_victory(runtime.flow, runtime.first)
            self.assertEqual([count for intent, count in runtime.sends if intent == 'du_save_name'], [2, 2])
            record = read(runtime.folder / NAME)
            self.assertEqual(record['actions'][-1]['status'], 'unknown')
            self.assertFalse(record['save_verified'])
            with self.assertRaisesRegex(AutomationError, '待核对'):
                preflight(runtime.folder)

    def test_persisted_pending_attempt_survives_interruption_without_reclassification(self):
        class InterruptedProcess(BaseException):
            pass

        with native_archive() as runtime:
            runtime.platform.SendInput.side_effect = InterruptedProcess
            with self.assertRaises(InterruptedProcess):
                save_victory(runtime.flow, runtime.first)
            canonical = runtime.folder / NAME
            record = read(canonical)
            journal = Path(record['journal'])
            original = (canonical.read_bytes(), journal.read_bytes())
            self.assertEqual(record['actions'][-1]['status'], 'pending')
            flow, context, first = make_context(runtime.folder, normal_pages(), fresh=True)
            with self.assertRaisesRegex(AutomationError, '待核对'):
                save_victory(flow, first)
            context.window.click.assert_not_called()
            self.assertEqual((canonical.read_bytes(), journal.read_bytes()), original)

    def test_unsent_receipt_write_failure_keeps_archive_blocked(self):
        with native_archive() as runtime:
            write = du_archive_store._write

            def fail_canonical(path, data):
                if path.name == NAME and data['actions'] and data['actions'][-1]['status'] == 'not_sent':
                    raise OSError('synthetic write failure on the canonical receipt')
                write(path, data)

            with (patch.object(du_archive_store, '_write', fail_canonical),
                  after_final_durable_check('du_save_open', lambda: runtime.advance(9))):
                with self.assertRaises(AutomationError):
                    save_victory(runtime.flow, runtime.first)
            self.assertEqual(runtime.sends, [])
            self.assertFalse(runtime.context.du_archive_workflow.finished)
            self.assertEqual(read(runtime.folder / NAME)['actions'][-1]['status'], 'pending')
            with self.assertRaises(AutomationError):
                preflight(runtime.folder)
