"""Exercise the explicit command with the real Runner and a fake Win32 window."""
from contextlib import contextmanager, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

import cv2

from autohsr import app, daily_event_claim_flow as flow
from autohsr.__main__ import main
from autohsr.config import Settings
from autohsr.daily_observe import EVENT_CLAIM_OPERATION
from autohsr.models import Token
from autohsr.tests import test_daily_event_claim as cases
from autohsr.tests.test_daily_event_navigation import activity_frame
from autohsr.tests.test_du_team import fixture
from autohsr.tests.test_workflow_navigation import world_hud
from autohsr.vision import Vision


class DailyEventClaimCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = cases.DailyEventClaimTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.config = self.fixture.root / 'settings.json'
        Settings().save(self.config)
        self.original_config = self.config.read_bytes()
        for module in ('autohsr.daily_event_claim', 'autohsr.challenge_pages'):
            self.enterContext(patch(module + '.time', time))
        self.window = self.fixture.window
        self.window.capture = Mock(side_effect=self.capture)
        self.enterContext(patch.object(app, 'ROOT', self.fixture.root))
        self.enterContext(patch.object(app, 'find_game', return_value=self.window))
        self.enterContext(patch.object(app, 'is_elevated', return_value=False))
        self.enterContext(patch.object(app, 'Vision', return_value=SimpleNamespace(
            confidence=.65, read=lambda image, _: self.scene, _read_field=self.field,
            template=Vision.__new__(Vision).template)))
        self.frames = iter(())
        self.account = cases.ACCOUNT

    def capture(self):
        self.scene, amount, *account = next(self.frames)
        self.scene.tokens.append(account[0] if account else self.account)
        self.scene.geometry = self.fixture.geometry
        self.amount = amount
        return self.scene.image, self.fixture.geometry

    def field(self, _image, pattern):
        if self.amount is not None and pattern == cases.claim._NUMBER_PATTERN:
            return Token(str(self.amount), .97, (0, 0, 1, 1))
        return None

    def invoke(self, *flags, report_saved=True):
        with redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr:
            code = main(['--daily-event-claim', '4', '--config', str(self.config), '--game-path', str(self.fixture.exe), *flags])
        self.close_notice = stderr.getvalue()
        data = json.loads(stdout.getvalue())
        self.assertIs(data['report_saved'], report_saved)
        if report_saved:
            self.assertEqual(json.loads((Path(data['run_dir']) / 'report.json').read_text(encoding='utf8')), data)
        self.assertNotIn(cases.ACCOUNT.text, stdout.getvalue())
        self.assertNotIn(str(self.fixture.exe), stdout.getvalue())
        self.assertEqual(self.config.read_bytes(), self.original_config)
        return code, data

    def test_official_entry_observes_one_popup_and_rejects_a_repeat(self):
        self.frames = iter([(cases.day_cards({1, 2, 3}), None) for _ in range(2)]
                           + [(cases.popup(), 1) for _ in range(2)])
        code, report = self.invoke()
        claim = report['daily_event_claim']
        self.assertNotIn('workflow_navigation', report)
        self.assertEqual((code, report['status']), (1, 'partial'), report['error'])
        self.assertEqual((claim['state'], claim['submission'], claim['popup'], claim['quantity']),
                         ('pending', 'sent', 'observed', 1))
        self.assertEqual(self.window.capture.call_count, 4)
        receipts = list((self.fixture.root / 'runs' / 'daily-event-claim').glob('*.json'))
        self.assertEqual({json.loads(path.read_text(encoding='utf8'))['state'] for path in receipts},
                         {'pending', 'reserved', 'submitted'})
        originals = {path: path.read_bytes() for path in receipts}
        self.frames = iter((cases.day_cards({1, 2, 3}), None) for _ in range(2))
        code, report = self.invoke()
        self.assertEqual((code, report['status']), (1, 'failed'))
        self.assertEqual({path: path.read_bytes() for path in receipts}, originals)
        self.fixture.native.SendInput.assert_called_once()

    def queue_navigation(self, start, *, handoff_account=cases.ACCOUNT, workflow=False):
        def frames():
            size = (self.fixture.geometry.width, self.fixture.geometry.height)
            if start == 'phone':
                for _ in range(3 if workflow else 2):
                    scene = fixture('phone_mail_icon')
                    scene.image = cv2.resize(scene.image, size)
                    yield scene, None
            if start in ('phone', 'activity_list'):
                for _ in range(2):
                    yield activity_frame(size=size), None
            for _ in range(2):
                yield cases.day_cards({1, 2, 3}), None
            self.account = handoff_account
            for _ in range(2):
                yield cases.day_cards({1, 2, 3}), None
            for _ in range(2):
                yield cases.popup(), 1
            if workflow:
                for _ in range(2):
                    yield cases.day_cards({1, 2, 3, 4}), None

        self.frames = frames()

    def test_explicit_navigation_reaches_then_submits_only_the_selected_day(self):
        self.queue_navigation('phone')
        code, report = self.invoke('--navigate-daily-event')
        navigation = report['workflow_navigation']
        self.assertTrue(navigation['page_verified'], report['error'])
        self.assertEqual([(row['action'], row['destination_page']) for row in navigation['actions']],
                         [('open_journey_events', 'activity_list'), ('open_odyssey', 'odyssey')])
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status'], claim['day'], claim['submission'], claim['popup']),
                         (1, 'partial', 4, 'sent', 'observed'), report['error'])
        self.assertEqual(self.fixture.native.SendInput.call_count, 3)

    def test_explicit_navigation_on_open_page_sends_only_the_claim(self):
        self.queue_navigation('odyssey')
        _, report = self.invoke('--navigate-daily-event')
        self.assertTrue(report['workflow_navigation']['page_verified'], report['error'])
        self.assertEqual(report['workflow_navigation']['actions'], [])
        self.assertEqual(report['daily_event_claim']['popup'], 'observed', report['error'])
        self.fixture.native.SendInput.assert_called_once()

    def test_changed_account_after_arrival_sends_no_claim_or_reservation(self):
        self.queue_navigation('activity_list', handoff_account=cases.OTHER)
        code, report = self.invoke('--navigate-daily-event')
        self.assertTrue(report['workflow_navigation']['page_verified'], report['error'])
        self.assertEqual((code, report['status'], report['daily_event_claim']['submission']),
                         (1, 'partial', 'not_sent'))
        self.assertIn('本次到页', report['error'])
        self.assertFalse((self.fixture.root / 'runs' / 'daily-event-claim').exists())
        self.fixture.native.SendInput.assert_called_once()

    def test_navigation_does_not_open_phone_or_claim_from_world(self):
        scene = world_hud()
        scene.tokens.clear()
        scene.image = cv2.resize(scene.image, (self.fixture.geometry.width, self.fixture.geometry.height))
        self.frames = iter([(scene, None)])
        code, report = self.invoke('--navigate-daily-event')
        self.assertEqual((code, report['status'], report['daily_event_claim']['submission']),
                         (1, 'failed', 'not_sent'))
        self.assertIn('预期之外', report['error'])
        self.assertEqual(report['workflow_navigation']['actions'], [])
        self.assertFalse((self.fixture.root / 'runs' / 'daily-event-claim').exists())
        self.fixture.native.SendInput.assert_not_called()

    def queue_manual_return(self, claimed, *, next_frames=()):
        self.frames = iter([(cases.day_cards({1, 2, 3}), None) for _ in range(2)]
                           + [(cases.popup(), 1) for _ in range(3)]
                           + list(next_frames) + [(cases.day_cards(claimed), None) for _ in range(2)])

    def test_opt_in_observes_manual_return_with_one_claim_batch(self):
        self.queue_manual_return({1, 2, 3, 4})
        code, report = self.invoke('--observe-daily-event-return')
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status']), (0, 'success'), report['error'])
        self.assertEqual((claim['state'], claim['stage'], claim['submission'], claim['popup'], claim['quantity']),
                         ('verified', 'done', 'sent', 'observed', 1))
        self.assertIn('请手动关闭当前弹窗', self.close_notice)
        self.assertEqual(self.window.capture.call_count, 7)
        self.fixture.native.SendInput.assert_called_once()
        verified, = (self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')
        self.assertTrue(json.loads(verified.read_text(encoding='utf8'))['same_card_claimed'])

    def invoke_workflow(self, *, navigate=False):
        root = self.fixture.root
        recipe = root / 'recipe.json'
        recipe.write_text(json.dumps(dict(version=1, name='Odyssey', steps=[
            dict(id='odyssey', type='task', task=EVENT_CLAIM_OPERATION, params=dict(day=4, navigate=navigate)),
            dict(id='after', type='wait', seconds=0),
        ])), encoding='utf8')
        with (patch('autohsr.task_workflow_run.ROOT', root),
              patch('autohsr.workflow_lease.NAME', 'Local\\AutoHSR.OdysseyTaskQA.' + uuid4().hex),
              patch('autohsr.workflow_lease.NATIVE_NAME', 'Local\\AutoHSR.OdysseyNativeQA.' + uuid4().hex),
              redirect_stdout(io.StringIO()) as stdout, redirect_stderr(io.StringIO()) as stderr):
            code = main(['--task-workflow', str(recipe), '--config', str(self.config)])
        self.close_notice = stderr.getvalue()
        self.assertNotIn(cases.ACCOUNT.text, stdout.getvalue())
        self.assertNotIn(cases.OTHER.text, stdout.getvalue())
        self.assertEqual(self.config.read_bytes(), self.original_config)
        return code, json.loads(stdout.getvalue())

    def test_task_workflow_continues_only_after_same_card_is_verified(self):
        self.frames = iter([(cases.day_cards({1, 2, 3}), None) for _ in range(4)]
                           + [(cases.popup(), 1) for _ in range(3)]
                           + [(cases.day_cards({1, 2, 3, 4}), None) for _ in range(2)])
        code, report = self.invoke_workflow()
        self.assertEqual((code, report['status']), (0, 'success'), report['workflow']['steps'])
        claim, after = report['workflow']['steps']
        self.assertEqual(after['status'], 'success')
        self.assertTrue(claim['account_verified'])
        native = json.loads(Path(claim['source']['path']).read_text(encoding='utf8'))
        self.assertEqual(claim['daily_event_claim'], native['daily_event_claim'])
        self.assertEqual(claim['daily_event_claim']['state'], 'verified')
        self.assertIn('请手动关闭当前弹窗', self.close_notice)
        self.fixture.native.SendInput.assert_called_once()

    def test_task_workflow_can_navigate_from_phone_to_the_selected_claim(self):
        self.queue_navigation('phone', workflow=True)
        code, report = self.invoke_workflow(navigate=True)
        self.assertEqual((code, report['status']), (0, 'success'), report['workflow']['steps'])
        claim = report['workflow']['steps'][0]
        native = json.loads(Path(claim['source']['path']).read_text(encoding='utf8'))
        self.assertEqual([(row['action'], row['destination_page'])
                          for row in native['workflow_navigation']['actions']],
                         [('open_journey_events', 'activity_list'), ('open_odyssey', 'odyssey')])
        self.assertEqual(claim['daily_event_claim']['state'], 'verified')
        self.assertEqual(self.fixture.native.SendInput.call_count, 3)

    def test_task_workflow_pending_return_retains_receipt_and_stops_followup(self):
        self.frames = iter([(cases.day_cards({1, 2, 3}), None) for _ in range(4)]
                           + [(cases.popup(), 1) for _ in range(2)]
                           + [(cases.day_cards({1, 2, 3, 4, 5}), None) for _ in range(2)])
        code, report = self.invoke_workflow()
        self.assertEqual((code, report['status']), (1, 'partial'))
        claim, = report['workflow']['steps']
        self.assertEqual(claim['daily_event_claim']['state'], 'pending')
        self.assertTrue(report['workflow']['input_blocked'])
        self.fixture.native.SendInput.assert_called_once()
        self.frames = iter([(cases.day_cards({1, 2, 3}), None) for _ in range(4)])
        code, repeated = self.invoke_workflow()
        self.assertEqual((code, repeated['status']), (1, 'partial'))
        self.fixture.native.SendInput.assert_called_once()

    def test_task_workflow_account_change_before_submission_creates_no_intent(self):
        self.frames = iter([(cases.day_cards({1, 2, 3}), None) for _ in range(3)]
                           + [(cases.day_cards({1, 2, 3}), None, cases.OTHER) for _ in range(2)])
        code, report = self.invoke_workflow()
        self.assertEqual((code, report['status']), (1, 'partial'))
        self.assertTrue(report['workflow']['identity']['account_changed'])
        self.assertTrue(report['workflow']['input_blocked'])
        self.fixture.native.SendInput.assert_not_called()
        self.assertFalse((self.fixture.root / 'runs' / 'daily-event-claim').exists())

    def test_another_day_changing_with_the_selected_day_does_not_settle(self):
        self.queue_manual_return({1, 2, 3, 4, 5})
        code, report = self.invoke('--observe-daily-event-return')
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status']), (1, 'partial'))
        self.assertEqual((claim['state'], claim['stage'], claim['submission']), ('pending', 'return_unverified', 'sent'))
        self.assertFalse(list((self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')))
        self.fixture.native.SendInput.assert_called_once()

    def test_one_return_frame_showing_another_claimed_day_is_counterevidence(self):
        def without_fifth_day(scene):
            x, y = cases.claim._CENTERS[4]
            label = scene.find('领取', (x - .025, y - .020, x + .025, y + .020), exact=True)
            self.assertIsNotNone(label)
            scene.tokens.remove(label)
            return scene

        before = [without_fifth_day(cases.day_cards({1, 2, 3})) for _ in range(2)]
        self.frames = iter([(scene, None) for scene in before] + [(cases.popup(), 1) for _ in range(2)]
                           + [(cases.day_cards({1, 2, 3, 4, 5}), None),
                              (without_fifth_day(cases.day_cards({1, 2, 3, 4})), None)])
        code, report = self.invoke('--observe-daily-event-return')
        state = report['daily_event_claim']
        self.assertEqual((code, report['status'], state['state'], state['submission']),
                         (1, 'partial', 'pending', 'sent'))
        self.assertEqual(self.window.capture.call_count, 6)
        self.assertFalse(list((self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')))
        self.fixture.native.SendInput.assert_called_once()

    def test_conflicting_account_between_popup_and_return_leaves_the_original_pending(self):
        conflict = cases.popup()
        conflict.tokens.append(cases.OTHER)
        self.queue_manual_return({1, 2, 3, 4}, next_frames=[(conflict, 1)])
        code, report = self.invoke('--observe-daily-event-return')
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status'], claim['state'], claim['stage']),
                         (1, 'partial', 'pending', 'return_unverified'))
        self.assertEqual(self.window.capture.call_count, 6)
        self.assertFalse(list((self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')))
        self.fixture.native.SendInput.assert_called_once()

    def test_f10_at_manual_close_handoff_keeps_sent_without_return_or_new_click(self):
        self.queue_manual_return({1, 2, 3, 4})
        emit = app.Runner.emit

        def stop_on_handoff(runner, event):
            emit(runner, event)
            if event.get('type') == 'daily_event_manual_close':
                self.fixture.native.GetAsyncKeyState.return_value = 1

        with patch.object(app.Runner, 'emit', new=stop_on_handoff):
            code, report = self.invoke('--observe-daily-event-return')
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status'], claim['state'], claim['stage'], claim['submission']),
                         (130, 'stopped', 'pending', 'return_unverified', 'sent'))
        self.assertEqual(self.window.capture.call_count, 4)
        self.assertFalse(list((self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')))
        self.fixture.native.SendInput.assert_called_once()

    def test_report_does_not_claim_success_after_the_return_receipt_is_replaced(self):
        self.queue_manual_return({1, 2, 3, 4})
        replacement = b'{"external":true}'
        publish = flow.publish_claim_report

        def replace_before_report(directory, report, **kwargs):
            if 'hold_evidence' in kwargs:
                verified, = (self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')
                verified.write_bytes(replacement)
            return publish(directory, report, **kwargs)

        with patch.object(flow, 'publish_claim_report', side_effect=replace_before_report):
            code, report = self.invoke('--observe-daily-event-return')
        claim = report['daily_event_claim']
        self.assertEqual((code, report['status'], claim['state'], claim['stage']),
                         (1, 'partial', 'pending', 'return_unverified'))
        verified, = (self.fixture.root / 'runs' / 'daily-event-claim').glob('*.verified.json')
        self.assertEqual(verified.read_bytes(), replacement)
        self.fixture.native.SendInput.assert_called_once()

    def _replace_with_same_bytes(self, path):
        raw, identity = path.read_bytes(), path.stat().st_ino
        external = path.with_name('outside.tmp')
        external.write_bytes(raw)
        external.replace(path)
        self.assertNotEqual(path.stat().st_ino, identity)
        return raw

    def _check_same_byte_replacement_before_report(self, suffix):
        self.queue_manual_return({1, 2, 3, 4})
        ledger = self.fixture.root / 'runs' / 'daily-event-claim'
        replaced = {}
        publish = flow.publish_claim_report

        def replace_before_report(directory, report, **kwargs):
            if 'hold_evidence' in kwargs:
                receipt, = ledger.glob(suffix)
                replaced[receipt] = self._replace_with_same_bytes(receipt)
            return publish(directory, report, **kwargs)

        with patch.object(flow, 'publish_claim_report', side_effect=replace_before_report):
            code, report = self.invoke('--observe-daily-event-return')
        state = report['daily_event_claim']
        self.assertEqual((code, report['status'], state['state'], state['submission']),
                         (1, 'partial', 'pending', 'sent'))
        self.assertEqual(len(replaced), 1)
        self.assertEqual({path: path.read_bytes() for path in replaced}, replaced)
        self.fixture.native.SendInput.assert_called_once()

    def test_original_verified_receipt_must_keep_its_file_identity_until_report(self):
        self._check_same_byte_replacement_before_report('*.verified.json')

    def test_original_submitted_receipt_must_keep_its_file_identity_until_report(self):
        self._check_same_byte_replacement_before_report('*.submitted.json')

    def test_same_byte_replacement_at_verified_rename_is_not_the_created_receipt(self):
        self.queue_manual_return({1, 2, 3, 4})
        native_rename = os.rename
        replaced = {}

        def swap_after_rename(source, destination):
            native_rename(source, destination)
            path = Path(destination)
            if path.name.endswith('.verified.json'):
                replaced[path] = self._replace_with_same_bytes(path)

        with patch('autohsr.warp_service.os.rename', side_effect=swap_after_rename):
            code, report = self.invoke('--observe-daily-event-return')
        state = report['daily_event_claim']
        self.assertEqual((code, report['status'], state['state'], state['submission']),
                         (1, 'partial', 'pending', 'sent'))
        self.assertEqual(len(replaced), 1)
        self.assertEqual({path: path.read_bytes() for path in replaced}, replaced)
        self.fixture.native.SendInput.assert_called_once()

    def test_competing_report_at_native_link_preserves_same_card_receipt_and_blocks_retry(self):
        self.queue_manual_return({1, 2, 3, 4})
        ledger = self.fixture.root / 'runs' / 'daily-event-claim'
        expected_report = b'{"external":"run report"}'
        originals = {}
        native_link = os.link

        def occupy_report(source, destination):
            originals.update({path: path.read_bytes() for path in ledger.glob('*.json')})
            with destination.open('xb') as stream:
                stream.write(expected_report)
            return native_link(source, destination)

        with patch.object(flow.os, 'link', side_effect=occupy_report):
            code, report = self.invoke('--observe-daily-event-return', report_saved=False)
        state = report['daily_event_claim']
        self.assertEqual((code, report['status'], state['state'], state['submission']),
                         (1, 'partial', 'verified', 'sent'))
        self.assertIn('同日卡回执已保存', report['report_write_error'])
        directory = Path(report['run_dir'])
        self.assertEqual((directory / 'report.json').read_bytes(), expected_report)
        self.assertFalse(list(directory.glob('.odyssey-report-*.tmp')))
        self.assertEqual({json.loads(raw)['state'] for raw in originals.values()},
                         {'pending', 'reserved', 'submitted', 'verified'})
        self.frames = iter((cases.day_cards({1, 2, 3}), None) for _ in range(2))
        code, retry = self.invoke()
        self.assertEqual((code, retry['status']), (1, 'failed'))
        self.assertEqual((directory / 'report.json').read_bytes(), expected_report)
        self.assertEqual({path: path.read_bytes() for path in ledger.glob('*.json')}, originals)
        self.fixture.native.SendInput.assert_called_once()

    def test_preflight_failure_preserves_competing_report_and_existing_temporary(self):
        self.fixture.native.GetForegroundWindow.return_value = 55
        prior = b'{"external":"preflight"}'
        native_link = os.link

        def occupy_report(source, destination):
            destination.write_bytes(prior)
            destination.with_suffix('.tmp').write_bytes(prior)
            return native_link(source, destination)

        with patch.object(flow.os, 'link', side_effect=occupy_report):
            code, report = self.invoke(report_saved=False)
        self.assertEqual((code, report['status'], report['daily_event_claim']['submission']),
                         (1, 'failed', 'not_sent'))
        directory = Path(report['run_dir'])
        self.assertEqual((directory / 'report.json').read_bytes(), prior)
        self.assertEqual((directory / 'report.tmp').read_bytes(), prior)
        self.assertFalse(list(directory.glob('.odyssey-report-*.tmp')))
        self.fixture.native.SendInput.assert_not_called()

    def test_report_stage_replaced_by_identical_bytes_stays_unpublished_and_foreign_stage_remains(self):
        self.queue_manual_return({1, 2, 3, 4})
        read_sources = flow.hold_read_sources
        replacements = {}

        def replace_before_stage_lock(paths):
            for path in paths:
                if path.name.startswith('.odyssey-report-'):
                    replacements[path] = self._replace_with_same_bytes(path)
            return read_sources(paths)

        with patch.object(flow, 'hold_read_sources', side_effect=replace_before_stage_lock):
            code, report = self.invoke('--observe-daily-event-return', report_saved=False)
        self.assertEqual((code, report['status'], report['daily_event_claim']['state']),
                         (1, 'partial', 'verified'))
        self.assertFalse((Path(report['run_dir']) / 'report.json').exists())
        self.assertEqual(len(replacements), 1)
        self.assertEqual({path: path.read_bytes() for path in replacements}, replacements)
        self.fixture.native.SendInput.assert_called_once()

    def test_native_link_and_readback_hold_the_original_at_each_name(self):
        self.queue_manual_return({1, 2, 3, 4})
        native_link = os.link
        read_sources = flow.hold_read_sources
        attempts = []

        def try_replacing(source, destination):
            competing = destination.with_name('outside.tmp')
            competing.write_bytes(b'external')
            with self.assertRaises(OSError):
                competing.replace(source)
            native_link(source, destination)
            attempts.append(competing)

        @contextmanager
        def try_replacing_during_readback(paths):
            with read_sources(paths):
                for path in paths:
                    if path.name == 'report.json':
                        with self.assertRaises(OSError):
                            attempts[0].replace(path)
                yield

        with (patch.object(flow.os, 'link', side_effect=try_replacing),
              patch.object(flow, 'hold_read_sources', side_effect=try_replacing_during_readback)):
            code, report = self.invoke('--observe-daily-event-return')
        self.assertEqual((code, report['status'], report['daily_event_claim']['state']),
                         (0, 'success', 'verified'))
        self.assertEqual([path.read_bytes() for path in attempts], [b'external'])
        self.assertFalse(list(Path(report['run_dir']).glob('.odyssey-report-*.tmp')))
        self.fixture.native.SendInput.assert_called_once()

    def test_report_replaced_after_native_link_does_not_claim_it_was_saved(self):
        self.queue_manual_return({1, 2, 3, 4})
        native_link = os.link
        replaced = {}

        def replace_before_readback(source, destination):
            native_link(source, destination)
            replaced[destination] = self._replace_with_same_bytes(destination)

        with patch.object(flow.os, 'link', side_effect=replace_before_readback):
            code, report = self.invoke('--observe-daily-event-return', report_saved=False)
        self.assertEqual((code, report['status'], report['daily_event_claim']['state']),
                         (1, 'partial', 'verified'))
        self.assertEqual(len(replaced), 1)
        self.assertEqual({path: path.read_bytes() for path in replaced}, replaced)
        self.assertFalse(list(Path(report['run_dir']).glob('.odyssey-report-*.tmp')))
        self.fixture.native.SendInput.assert_called_once()

    def test_return_option_cannot_start_an_unrelated_operation(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
            with patch('autohsr.daily_event_claim_cli.Settings.load') as load:
                main(['--run', '--observe-daily-event-return'])
            load.assert_not_called()
        self.assertEqual(stopped.exception.code, 2)
        self.fixture.native.SendInput.assert_not_called()

    def test_other_foreground_window_never_captures_or_sends(self):
        self.fixture.native.GetForegroundWindow.return_value = 55
        code, report = self.invoke()
        self.assertEqual((code, report['status'], report['daily_event_claim']['submission']),
                         (1, 'failed', 'not_sent'))
        self.window.capture.assert_not_called()
        self.fixture.native.SendInput.assert_not_called()

    def desktop_runner(self, *, observe_return=False):
        return app.Runner(Settings(game_path=str(self.fixture.exe)), operation=EVENT_CLAIM_OPERATION,
                          daily_event_claim_day=4, daily_event_observe_return=observe_return,
                          observation_wait_for_foreground=True)

    def test_desktop_waits_for_manual_foreground_before_claim_and_return(self):
        self.queue_manual_return({1, 2, 3, 4})
        native = self.fixture.native
        native.GetForegroundWindow.return_value = 55

        def handoff(_):
            self.window.capture.assert_not_called()
            native.SendInput.assert_not_called()
            native.GetForegroundWindow.return_value = self.window.hwnd

        clock = SimpleNamespace(monotonic=time.monotonic, sleep=Mock(side_effect=handoff))
        with patch('autohsr.screenshot_tool.time', clock):
            report = self.desktop_runner(observe_return=True).run().to_dict()
        clock.sleep.assert_called_once()
        self.assertEqual(report['status'], 'success', report['error'])
        self.assertEqual(report['daily_event_claim']['state'], 'verified')
        native.SendInput.assert_called_once()
        self.window.focus.assert_not_called()

    def test_desktop_f10_during_handoff_prevents_capture_and_claim(self):
        native = self.fixture.native
        native.GetForegroundWindow.return_value = 55

        def stop(_):
            native.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key == 0x79 else 0

        clock = SimpleNamespace(monotonic=time.monotonic, sleep=Mock(side_effect=stop))
        with patch('autohsr.screenshot_tool.time', clock):
            report = self.desktop_runner().run().to_dict()
        self.assertEqual(report['status'], 'stopped', report['error'])
        clock.sleep.assert_called_once()
        self.assertEqual(report['daily_event_claim']['submission'], 'not_sent')
        self.window.capture.assert_not_called()
        native.SendInput.assert_not_called()
        self.assertFalse((self.fixture.root / 'runs' / 'daily-event-claim').exists())

    def test_unrelated_and_duplicate_flags_fail_before_settings(self):
        for args in (['--navigate-daily-event'], ['--daily-event-claim=4', '--new-battle-run'],
                     ['--daily-event-claim=4', '--daily-event-claim=5'],
                     ['--daily-event-claim=4', '--config=a', '--config=b'],
                     ['--daily-event-claim=4', '--navigate-daily-event', '--navigate-daily-event']):
            with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped:
                with patch('autohsr.daily_event_claim_cli.Settings.load') as load:
                    main(args)
                load.assert_not_called()
            self.assertEqual(stopped.exception.code, 2)
