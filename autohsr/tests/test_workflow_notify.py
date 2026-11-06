"""Run the real notification adapter and private receipts with fake transports."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from autohsr import notify_runtime, workflow_notify
from autohsr.models import Stopped
from autohsr.notify_http import Reply
from autohsr.notify_profiles import NotifyError


PROFILE = 'synthetic-workflow-recipient'
SECRET = 'synthetic-workflow-credential'
RECIPIENT = 'https://example.test/synthetic-private-endpoint'
FIRST_LINE = '合成任务说明 {status}'
MESSAGE = FIRST_LINE + '\n第二行'


def profile(*, identity=PROFILE, url=RECIPIENT):
    return dict(id=identity, provider='webhook',
                params=dict(url=url, headers={'Authorization': 'Bearer ' + SECRET}))


class WorkflowNotifyTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.directory = self.root / 'workflow'
        self.directory.mkdir()
        self.stop = threading.Event()
        request = patch('autohsr.notify_http.build_opener', side_effect=AssertionError('live HTTP forbidden'))
        request.start()
        self.addCleanup(request.stop)

    def checkpoint(self):
        if self.stop.is_set():
            raise Stopped('测试停止')

    def service(self, request, value=None, *, local_send=None):
        service = notify_runtime.NotificationService(
            root=self.root / 'private', request=request,
            local_send=Mock(side_effect=AssertionError('live local delivery forbidden')) if local_send is None else local_send)
        service.store.save(profile() if value is None else value)
        return service

    def send(self, service, *, version=None, sequence=1, checkpoint=None, message=MESSAGE, identity=PROFILE):
        return workflow_notify.send_step(
            identity, message, directory=self.directory, run_key='synthetic-run-key', sequence=sequence,
            checkpoint=self.checkpoint if checkpoint is None else checkpoint,
            expected_version=version if version is not None else workflow_notify.freeze_profile(identity, service=service),
            service=service)

    def report(self, result, status, notification):
        self.assertEqual(result['operation'], 'workflow_notify')
        self.assertEqual(result['status'], status)
        self.assertEqual(result['notification']['status'], notification)
        self.assertIs(result['report_saved'], True)
        data = (Path(result['run_dir']) / 'report.json').read_bytes()
        self.assertEqual(json.loads(data), result)
        for private in (PROFILE, SECRET, RECIPIENT, FIRST_LINE, 'synthetic-run-key'):
            self.assertNotIn(private.encode('utf8'), data)
        return data

    def test_acceptance_publishes_anonymous_receipt_after_durable_intents(self):
        def accepted(call):
            step = self.directory / 'notify-1'
            raw = (step / 'intent.json').read_bytes()
            self.assertEqual(json.loads(raw)['status'], 'pending')
            for private in (PROFILE, SECRET, RECIPIENT, FIRST_LINE, 'synthetic-run-key'):
                self.assertNotIn(private.encode('utf8'), raw)
            path = next((self.root / 'private' / 'attempts').glob('*.json'))
            durable = json.loads(path.read_bytes())
            self.assertEqual(durable['status'], 'pending')
            self.assertEqual(durable['actions'], [dict(phase='send', index=0, status='pending')])
            for private in (SECRET, RECIPIENT, FIRST_LINE):
                self.assertNotIn(private.encode('utf8'), path.read_bytes())
            self.assertEqual(json.loads(call.data)['content'], MESSAGE)
            return Reply(200, b'{}')

        request = Mock(side_effect=accepted)
        service = self.service(request)
        first = self.send(service)
        before = self.report(first, 'success', 'accepted')
        service.store.save(profile(identity='another-profile'))
        replay = self.send(service, identity='another-profile', message='changed message')
        self.assertEqual(replay['notification'], dict(status='unknown', reason='already_attempted', reused=True))
        self.assertFalse(replay['report_saved'])
        self.assertEqual((Path(first['run_dir']) / 'report.json').read_bytes(), before)
        self.assertIs(service.request, request)
        request.assert_called_once()

    def test_explicit_rejection_and_unknown_timeout_stay_distinct(self):
        request = Mock(side_effect=[Reply(400, b'{}'), RuntimeError(RECIPIENT + SECRET)])
        service = self.service(request)
        self.report(self.send(service), 'failed', 'rejected')
        self.report(self.send(service, sequence=2), 'partial', 'unknown')
        self.assertEqual(request.call_count, 2)
        self.assertFalse(self.send(service, sequence=2)['report_saved'])
        self.assertEqual(request.call_count, 2)

    def test_frozen_profile_replacement_stops_before_any_submission(self):
        request = Mock(return_value=Reply(200, b'{}'))
        service = self.service(request)
        frozen = workflow_notify.freeze_profile(PROFILE, service=service)
        service.store.save(profile(url='https://other.example.test/new'), replace=True)
        result = self.send(service, version=frozen)
        self.report(result, 'failed', 'rejected')
        self.assertEqual(result['notification']['reason'], 'profile_changed')
        request.assert_not_called()

    def test_stop_before_intent_raises_and_stop_after_intent_saves(self):
        request = Mock(return_value=Reply(200, b'{}'))
        service = self.service(request)
        self.stop.set()
        with self.assertRaises(Stopped):
            self.send(service)
        self.assertFalse((self.directory / 'notify-1').exists())
        self.stop.clear()

        def after_intent():
            if (self.directory / 'notify-1' / 'intent.json').is_file():
                self.stop.set()
            self.checkpoint()

        self.report(self.send(service, checkpoint=after_intent), 'stopped', 'cancelled')
        request.assert_not_called()

    def test_late_stop_after_provider_pending_blocks_actual_transport(self):
        request = Mock(return_value=Reply(200, b'{}'))
        service = self.service(request)
        write = notify_runtime._write

        def late(path, value):
            write(path, value)
            if value['status'] == 'pending' and value['actions']:
                self.stop.set()

        with patch.object(notify_runtime, '_write', side_effect=late):
            result = self.send(service)
        self.report(result, 'stopped', 'cancelled')
        request.assert_not_called()
        self.stop.clear()
        self.assertTrue(self.send(service)['notification']['reused'])
        request.assert_not_called()

    def test_profile_change_after_provider_pending_blocks_actual_transport(self):
        request = Mock(return_value=Reply(200, b'{}'))
        service = self.service(request)
        write = notify_runtime._write

        def late(path, value):
            write(path, value)
            if value['status'] == 'pending' and value['actions']:
                service.store.save(profile(url='https://other.example.test/new'), replace=True)

        with patch.object(notify_runtime, '_write', side_effect=late):
            result = self.send(service)
        self.report(result, 'failed', 'rejected')
        self.assertEqual(result['notification']['reason'], 'profile_changed')
        request.assert_not_called()

    def test_actual_transport_keeps_version_held_and_late_stop_keeps_acceptance(self):
        def accepted(call):
            with self.assertRaises(PermissionError):
                with service.store.path(PROFILE).open('ab'):
                    pass
            self.stop.set()
            return Reply(200, b'{}')

        request = Mock(side_effect=accepted)
        service = self.service(request)
        self.report(self.send(service), 'success', 'accepted')
        with service.store.path(PROFILE).open('ab'):
            pass
        request.assert_called_once()

    def test_late_stop_with_no_reply_remains_unknown(self):
        def unanswered(call):
            self.stop.set()
            raise RuntimeError(SECRET)

        request = Mock(side_effect=unanswered)
        service = self.service(request)
        self.report(self.send(service), 'partial', 'unknown')
        request.assert_called_once()

    def test_dual_target_stop_keeps_first_acceptance_and_blocks_second_target(self):
        def accepted(call):
            self.assertEqual(json.loads(call.data)['message_type'], 'private')
            self.stop.set()
            return Reply(200, b'{"status":"ok","retcode":0}')

        request = Mock(side_effect=accepted)
        service = self.service(request, dict(id=PROFILE, provider='onebot', params={
            'endpoint': 'http://127.0.0.1:18080', 'token': SECRET, 'user_id': '123456', 'group_id': '123457'}))
        result = self.send(service)
        self.report(result, 'partial', 'partial')
        self.assertEqual(result['notification']['reason'], 'stopped_after_submission')
        self.assertEqual(result['notification']['accepted_submissions'], 1)
        request.assert_called_once()

    def test_dual_target_late_stop_keeps_first_acceptance_with_second_pending(self):
        request = Mock(return_value=Reply(200, b'{"status":"ok","retcode":0}'))
        service = self.service(request, dict(id=PROFILE, provider='onebot', params={
            'endpoint': 'http://127.0.0.1:18080', 'token': SECRET, 'user_id': '123456', 'group_id': '123457'}))
        write = notify_runtime._write

        def late(path, value):
            write(path, value)
            if len(value['actions']) == 2 and value['actions'][1]['status'] == 'pending':
                self.stop.set()

        with patch.object(notify_runtime, '_write', side_effect=late):
            result = self.send(service)
        self.report(result, 'partial', 'partial')
        self.assertEqual(result['notification']['accepted_submissions'], 1)
        request.assert_called_once()

    def test_failed_provider_preflight_proves_no_message_was_submitted(self):
        request = Mock(return_value=Reply(200, b'{}'))
        service = self.service(request, dict(id=PROFILE, provider='matrix', params={
            'homeserver': 'https://example.test', 'access_token': SECRET, 'room_id': '!fake:example.test'}))
        result = self.send(service)
        self.report(result, 'failed', 'rejected')
        self.assertEqual(result['notification']['reason'], 'submission_not_started')
        request.assert_called_once()
        self.assertEqual(request.call_args.args[0].phase, 'verify')

    def test_local_transport_is_also_checked_after_durable_intent(self):
        request = Mock(side_effect=AssertionError('HTTP forbidden for fixture'))
        local = Mock(return_value='accepted')
        service = self.service(request, dict(id=PROFILE, provider='winotify',
                                             params={'app_id': 'AutoHSR Offline Fixture'}), local_send=local)
        self.report(self.send(service), 'success', 'accepted')
        local.assert_called_once()
        self.assertIs(service.local_send, local)
        request.assert_not_called()

    def test_existing_report_is_preserved_when_outer_publish_loses_race(self):
        request = Mock(return_value=Reply(200, b'{}'))
        service = self.service(request)
        replace_file = workflow_notify.replace_file

        def concurrent_report(source, destination, **options):
            if destination.name == 'report.json':
                destination.write_bytes(b'external bytes')
            return replace_file(source, destination, **options)

        with patch.object(workflow_notify, 'replace_file', side_effect=concurrent_report):
            result = self.send(service)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['notification']['status'], 'accepted')
        self.assertEqual(result['notification']['reason'], 'receipt_write_failed')
        self.assertFalse(result['report_saved'])
        self.assertEqual((Path(result['run_dir']) / 'report.json').read_bytes(), b'external bytes')
        self.assertTrue(self.send(service)['notification']['reused'])
        request.assert_called_once()

    def test_concurrent_duplicate_cannot_submit_while_original_is_in_flight(self):
        entered, release = threading.Event(), threading.Event()

        def accepted(call):
            entered.set()
            self.assertTrue(release.wait(5))
            return Reply(200, b'{}')

        request = Mock(side_effect=accepted)
        service = self.service(request)
        with ThreadPoolExecutor(max_workers=1) as workers:
            first = workers.submit(self.send, service)
            try:
                self.assertTrue(entered.wait(5))
                duplicate = self.send(service)
                self.assertTrue(duplicate['notification']['reused'])
                self.assertFalse(duplicate['report_saved'])
            finally:
                release.set()
            self.report(first.result(5), 'success', 'accepted')
        request.assert_called_once()

    def test_message_limit_is_utf16_and_values_are_literal(self):
        self.assertEqual(workflow_notify.validate_message(MESSAGE), MESSAGE)
        self.assertEqual(workflow_notify.validate_message('😀' * 2048), '😀' * 2048)
        for value in ('  ', '\x00', '😀' * 2049):
            with self.subTest(length=len(value)), self.assertRaises(NotifyError):
                workflow_notify.validate_message(value)


if __name__ == '__main__':
    unittest.main()
