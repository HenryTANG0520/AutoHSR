"""Fake recipients/transports only. A real HTTP opener is forbidden in tests."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from autohsr.config import Settings, SettingsError
from autohsr.models import RunReport, TaskResult
from autohsr.notify_profiles import PROVIDERS, NotifyError, ProfileStore, crypt, profile
from autohsr.notify_http import Call, Reply, _NoRedirect, request
from autohsr.notify_providers import acknowledgement, calls, execute
from autohsr.notify_runtime import NotificationService, hooks, report_message, validate_settings

SECRET = 'synthetic-secret-NOT-REAL'
PARAMS = {
 'telegram': dict(token=SECRET, userid='123456'),
 'matrix': dict(homeserver='https://matrix.example.test', access_token=SECRET, room_id='!fake:example.test'),
 'onebot': dict(endpoint='http://127.0.0.1:18080', token=SECRET, user_id='123456'),
 'gocqhttp': dict(endpoint='127.0.0.1:18080', token=SECRET, group_id='123456'),
 'smtp': dict(host='smtp.example.test', user='fake@example.test', password=SECRET),
 'wechatworkapp': dict(corpid='fake-corp', corpsecret=SECRET, agentid='123', touser='fake-user'),
 'wechatworkbot': dict(key=SECRET),
 'custom': dict(url='https://example.test/custom'),
 'lark': dict(webhook='https://example.test/lark', sign=SECRET),
 'serverchan3': dict(sendkey='sctp123t' + SECRET),
 'serverchanturbo': dict(sctkey=SECRET),
 'kook': dict(token=SECRET, target_id='123456'),
 'webhook': dict(url='https://example.test/webhook', headers=dict(Authorization='Bearer ' + SECRET)),
 'meow': dict(nickname='fake-user'),
 'bark': dict(key=SECRET),
 'dingtalk': dict(token=SECRET, secret=SECRET),
 'discord': dict(webhook='https://example.test/discord'),
 'gotify': dict(url='https://example.test/gotify', token=SECRET),
 'pushdeer': dict(token=SECRET),
 'pushplus': dict(token=SECRET),
 'qmsg': dict(key=SECRET),
 'qqbot': dict(appid='123456', client_secret=SECRET, openid='fake-open-id'),
 'winotify': dict(app_id='AutoHSR Offline Fixture'),
}


def record(provider='webhook', identity=None, **params):
    return dict(id=identity or ('test-' + provider), provider=provider, params=dict(PARAMS[provider], **params))


def reply_for(provider, call):
    if call.phase == 'authorize':
        return Reply(200, b'{"code":0,"errcode":0,"access_token":"ephemeral-fake-token"}')
    if call.phase == 'verify':
        return Reply(404, b'{"errcode":"M_NOT_FOUND"}')
    values = {
        'telegram': dict(ok=True), 'matrix': dict(event_id='$synthetic'),
        'onebot': dict(retcode=0, status='ok'), 'gocqhttp': dict(retcode=0, status='ok'),
        'wechatworkapp': dict(errcode=0), 'wechatworkbot': dict(errcode=0),
        'serverchan3': dict(code=0), 'serverchanturbo': dict(code=0), 'kook': dict(code=0),
        'lark': dict(code=0), 'meow': dict(status=200), 'bark': dict(code=200),
        'dingtalk': dict(errcode=0), 'gotify': dict(id=1), 'pushdeer': dict(code=0),
        'pushplus': dict(code=200), 'qmsg': dict(code=0, success=True), 'qqbot': dict(id='synthetic'),
    }
    return Reply(204, b'') if provider == 'discord' else Reply(200, json.dumps(values.get(provider, {})).encode())


class NotificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.live_network = patch('autohsr.notify_http.build_opener', side_effect=AssertionError('live HTTP forbidden'))
        self.live_network.start()
        self.addCleanup(self.live_network.stop)
        keyboard = patch('autohsr.notify_runtime._notification_key_state', return_value=(False, False, False))
        keyboard.start()
        self.addCleanup(keyboard.stop)

    def service(self, provider='webhook', *, requester=None, identity=None):
        service = NotificationService(root=self.root, request=requester or (lambda call: reply_for(provider, call)),
                                      local_send=Mock(return_value='accepted'))
        service.store.save(record(provider, identity))
        return service, service.store.load_version(identity or ('test-' + provider))

    def test_every_pinned_channel_validates_and_uses_only_fake_transports(self):
        self.assertEqual(set(PARAMS), set(PROVIDERS))
        for provider in PROVIDERS:
            with self.subTest(provider=provider):
                requested = []
                def fake(call):
                    requested.append(call)
                    self.assertNotIn(SECRET, repr(call))
                    return reply_for(provider, call)
                service, frozen = self.service(provider, requester=fake)
                outcome = service.deliver(frozen, '离线合成测试', '不发送给真实接收者', 'synthetic-' + provider)
                self.assertEqual(outcome['status'], 'accepted')
                self.assertNotIn(SECRET, json.dumps(outcome))
                self.assertNotIn(SECRET, service.store.path(frozen[0]['id']).read_bytes().decode('latin1'))
                if provider in ('smtp', 'winotify'):
                    self.assertEqual(requested, [])
                    service.local_send.assert_called_once()
                else:
                    self.assertTrue(requested)

    def test_real_current_user_dpapi_roundtrip_tamper_and_no_plaintext_store(self):
        value = record()
        store = ProfileStore(self.root)
        public = store.save(value)
        raw = store.path(value['id']).read_bytes()
        self.assertNotIn(SECRET.encode(), raw)
        self.assertEqual(store.load_private(value['id']), value)
        self.assertEqual(set(public), {'id', 'provider', 'credentials_saved'})
        altered = bytearray(raw); altered[-1] ^= 1
        store.path(value['id']).write_bytes(altered)
        with self.assertRaises(NotifyError):
            store.load_private(value['id'])

    def test_profile_replace_is_explicit_and_keeps_encrypted_original_backup(self):
        store = ProfileStore(self.root)
        value = record()
        store.save(value); original = store.path(value['id']).read_bytes()
        changed = record(url='https://other.example.test/new')
        with self.assertRaises(NotifyError):
            store.save(changed)
        self.assertEqual(store.path(value['id']).read_bytes(), original)
        store.save(changed, replace=True)
        self.assertEqual(store.load_private(value['id']), changed)
        self.assertEqual(next(store.path(value['id']).parent.glob('*.bak')).read_bytes(), original)

    def test_profile_and_url_inputs_do_not_inject_headers_or_paths(self):
        invalid = [record(identity='../escape'), record(url='https://user:password@example.test/hook'),
                   record(url='http://remote.example.test'), record(headers={'X-Test': SECRET + '\r\nHost: bad'}),
                   record(headers={'Host': 'bad.example.test'}), record('bark', cipherkey=SECRET),
                   record('matrix', access_token=SECRET + '\nBad'), record('kook', chat_type='2')]
        for value in invalid:
            with self.subTest(provider=value['provider']), self.assertRaises(NotifyError) as error:
                profile(value)
            self.assertNotIn(SECRET, str(error.exception))

    def test_acknowledgement_never_turns_missing_or_conflicting_json_into_success(self):
        for provider in ('telegram', 'matrix', 'onebot', 'serverchan3', 'lark', 'bark', 'qqbot', 'qmsg'):
            self.assertEqual(acknowledgement(provider, Reply(200, b'{}')), 'unknown')
            self.assertEqual(acknowledgement(provider, Reply(503, b'{"ok":true}')), 'unknown')
            self.assertEqual(acknowledgement(provider, Reply(302, b'')), 'unknown')
        self.assertEqual(acknowledgement('telegram', Reply(200, b'{"ok":false,"ok":true}')), 'unknown')
        self.assertEqual(acknowledgement('serverchan3', Reply(200, b'{"code":false}')), 'unknown')
        self.assertEqual(acknowledgement('lark', Reply(200, b'{"code":0,"StatusCode":1}')), 'unknown')

    def test_intention_is_durable_before_send_and_same_report_does_not_resend(self):
        calls_seen = []
        def fake(call):
            receipt = json.loads(next((self.root / 'attempts').glob('*.json')).read_text('utf8'))
            self.assertEqual(receipt['status'], 'pending')
            self.assertEqual(receipt['actions'][-1], dict(phase='send', index=0, status='pending'))
            calls_seen.append(call)
            return Reply(200, b'{}')
        service, frozen = self.service(requester=fake)
        first = service.deliver(frozen, 'title', 'body', 'same-report')
        before = next((self.root / 'attempts').glob('*.json')).read_bytes()
        second = service.deliver(frozen, 'title', 'body', 'same-report')
        self.assertEqual(first['status'], 'accepted')
        self.assertTrue(second['reused'])
        self.assertEqual(len(calls_seen), 1)
        self.assertEqual(next((self.root / 'attempts').glob('*.json')).read_bytes(), before)

    def test_timeout_stays_unknown_without_retry_or_secret_error_echo(self):
        fake = Mock(side_effect=RuntimeError('https://secret.example.test/' + SECRET))
        service, frozen = self.service(requester=fake)
        first = service.deliver(frozen, 'title', 'body', 'unknown-report')
        second = service.deliver(frozen, 'title', 'body', 'unknown-report')
        self.assertEqual(first['status'], 'unknown')
        self.assertEqual(second['status'], 'unknown')
        self.assertTrue(second['reused'])
        fake.assert_called_once()
        self.assertNotIn(SECRET, json.dumps([first, second]))

    def test_corrupt_cached_receipt_is_preserved_and_never_resubmitted(self):
        fake = Mock(return_value=Reply(200, b'{}'))
        service, frozen = self.service(requester=fake)
        service.deliver(frozen, 'title', 'body', 'damaged-receipt')
        path = next((self.root / 'attempts').glob('*.json'))
        data = json.loads(path.read_text('utf8'))
        for actions in ([None], [dict(phase='invented', index=0, status='verified')]):
            data['actions'] = actions
            before = json.dumps(data).encode('utf8')
            path.write_bytes(before)
            with self.subTest(actions=actions), self.assertRaises(NotifyError):
                service.deliver(frozen, 'title', 'body', 'damaged-receipt')
            self.assertEqual(path.read_bytes(), before)
        fake.assert_called_once()

    def test_receipt_write_failure_before_send_sends_nothing(self):
        fake = Mock()
        service, frozen = self.service(requester=fake)
        with patch('autohsr.notify_runtime._write', side_effect=OSError('synthetic failure')):
            with self.assertRaises(OSError):
                service.deliver(frozen, 'title', 'body', 'no-send')
        fake.assert_not_called()

    def test_receipt_failure_after_submission_keeps_unknown_and_blocks_replay(self):
        from autohsr import notify_runtime
        original = notify_runtime._write
        fake = Mock(return_value=Reply(200, b'{}'))
        service, frozen = self.service(requester=fake)
        def fail_after(path, data):
            if data['actions'] and data['actions'][-1]['status'] == 'accepted':
                raise OSError('synthetic after-send failure')
            original(path, data)
        with patch.object(notify_runtime, '_write', side_effect=fail_after):
            first = service.deliver(frozen, 'title', 'body', 'uncertain-write')
        second = service.deliver(frozen, 'title', 'body', 'uncertain-write')
        self.assertEqual(first['status'], 'unknown')
        self.assertEqual(second['status'], 'unknown')
        self.assertTrue(second['reused'])
        fake.assert_called_once()

    def test_changed_profile_never_retargets_a_frozen_run(self):
        fake = Mock()
        service, frozen = self.service(requester=fake)
        service.store.save(record(url='https://other.example.test'), replace=True)
        with self.assertRaises(NotifyError):
            service.deliver(frozen, 'title', 'body', 'frozen-profile')
        fake.assert_not_called()

    def test_matrix_encrypted_or_unreadable_room_is_not_sent_plaintext(self):
        for response in (Reply(200, b'{"algorithm":"m.megolm.v1.aes-sha2"}'), Reply(403, b'{}')):
            called = Mock(return_value=response)
            service, frozen = self.service('matrix', requester=called, identity='matrix-' + str(response.status))
            outcome = service.deliver(frozen, 'title', 'body', str(response.status))
            self.assertEqual(outcome['status'], 'unknown')
            called.assert_called_once()
            self.assertEqual(called.call_args.args[0].phase, 'verify')

    def test_oauth_failure_does_not_submit_a_message_or_persist_access_token(self):
        for provider in ('wechatworkapp', 'qqbot'):
            called = Mock(return_value=Reply(200, b'{"code":false,"access_token":"ephemeral-fake-token"}'))
            service, frozen = self.service(provider, requester=called)
            outcome = service.deliver(frozen, 'title', 'body', provider)
            self.assertEqual(outcome['status'], 'unknown')
            called.assert_called_once()
            self.assertEqual(called.call_args.args[0].phase, 'authorize')
        for path in (self.root / 'attempts').glob('*.json'):
            self.assertNotIn('ephemeral-fake-token', path.read_text('utf8'))

    def test_multiple_targets_stop_on_unknown_and_keep_prior_acceptance(self):
        fake = Mock(side_effect=[Reply(200, b'{"retcode":0,"status":"ok"}'), OSError('timeout')])
        value = record('onebot', group_id='654321')
        service = NotificationService(root=self.root, request=fake)
        service.store.save(value)
        frozen = service.store.load_version(value['id'])
        result = service.deliver(frozen, 'title', 'body', 'two-targets')
        self.assertEqual(result['status'], 'unknown')
        receipt = json.loads(next((self.root / 'attempts').glob('*.json')).read_text('utf8'))
        self.assertEqual([a['status'] for a in receipt['actions']], ['accepted', 'pending'])
        self.assertEqual(fake.call_count, 2)

    def test_safe_summary_excludes_raw_errors_ids_paths_and_unverified_numbers(self):
        settings = Settings()
        report = dict(operation='daily', status='partial', report_saved=True, daily_verified=True,
            error=SECRET, source='D:/fake/UID100000000', safe_next=SECRET, run_dir=SECRET,
            stamina_spent=120, stamina_pending=10, battle_completed=3,
            currency_wars=dict(account_key=SECRET, completed=2, victories=1, defeats=1),
            results=[dict(task='daily', status='ok')])
        title, body = report_message(settings, report)
        self.assertIn('部分完成', title)
        self.assertIn('已核实', body)
        self.assertIn('胜利：1；失败：1', body)
        self.assertNotIn(SECRET, title + body)
        self.assertNotIn('UID100000000', title + body)
        with self.assertRaises(NotifyError):
            report_message(replace(settings, notification_body='{error}'), report)

    def test_disabled_hook_is_exact_noop_and_reads_no_profiles(self):
        emit = Mock()
        with patch('autohsr.notify_runtime.ProfileStore.load_version', side_effect=AssertionError('must not read')):
            callback, wrapper = hooks(Settings(), emit)
            child = Mock()
            self.assertIs(callback, emit)
            self.assertIs(wrapper(child), child)

    def test_game_return_and_saved_report_are_unchanged_when_notification_fails(self):
        request_fake = Mock(side_effect=OSError('private-error-' + SECRET))
        service, frozen = self.service(requester=request_fake)
        settings = Settings(notification_enabled=True, notification_profiles=[frozen[0]['id']])
        events = []
        emit, wrap = hooks(settings, events.append, service=service)
        game = RunReport(status='success', daily_verified=True, report_saved=True, run_dir=str(self.root / 'game'))
        directory = Path(game.run_dir); directory.mkdir()
        file = directory / 'report.json'; file.write_text(json.dumps(game.to_dict()), 'utf8'); before = file.read_bytes()
        before_game = deepcopy(game)
        child = Mock()
        def run():
            emit(dict(type='finished', report=game.to_dict()))
            self.assertFalse(any(event['type'] == 'finished' for event in events))
            return game
        child.run.side_effect = run
        result = wrap(child).run()
        self.assertIs(result, game)
        self.assertEqual(game, before_game)
        self.assertEqual(file.read_bytes(), before)
        self.assertEqual(sum(event['type'] == 'finished' for event in events), 1)
        self.assertTrue(any(event['type'] == 'notification_result' and event['status'] == 'unknown' for event in events))

    def test_stop_during_notification_does_not_stop_finished_game_or_next_channel(self):
        service, first = self.service(identity='first')
        service.store.save(record(identity='second'))
        settings = Settings(notification_enabled=True, notification_profiles=['first', 'second'])
        events = []
        emit, wrap = hooks(settings, events.append, service=service)
        child = Mock(); child.run.return_value = RunReport(status='success', report_saved=True)
        wrapped = wrap(child)
        def response(call):
            wrapped.stop()
            return Reply(200, b'{}')
        service.request = Mock(side_effect=response)
        self.assertEqual(wrapped.run().status, 'success')
        child.stop.assert_not_called()
        self.assertEqual(service.request.call_count, 1)
        self.assertTrue(any(e['type'] == 'notification_summary' and e['status'] == 'cancelled' for e in events))

    def test_notification_stage_hands_off_real_listener_lifecycle_and_f10_cancels_next_target(self):
        service, first = self.service(identity='first')
        service.store.save(record(identity='second'))
        settings = Settings(notification_enabled=True, notification_profiles=['first', 'second'])
        events, started, stopped = [], threading.Event(), threading.Event()
        emit, wrap = hooks(settings, events.append, service=service)
        child = Mock()
        game = RunReport(status='success', report_saved=True)
        child.run.return_value = game
        wrapped = wrap(child)
        original_stop = wrapped.stop
        def stop_notification():
            original_stop()
            stopped.set()
        wrapped.stop = stop_notification
        def state(runner):
            self.assertIs(runner, child)
            self.assertTrue(wrapped.control.game_done)
            if started.is_set():
                return False, True, True
            return False, False, True
        def response(call):
            started.set()
            self.assertTrue(stopped.wait(2), 'notification listener did not observe F10')
            return Reply(200, b'{}')
        service.request = Mock(side_effect=response)
        with patch('autohsr.notify_runtime._notification_key_state', side_effect=state):
            self.assertIs(wrapped.run(), game)
        child.stop.assert_not_called()
        service.request.assert_called_once()
        self.assertTrue(wrapped.control._stop.is_set())
        self.assertEqual(sum(event['type'] == 'finished' for event in events), 1)
        self.assertFalse(any(thread.name == 'AutoHSR-notification-hotkeys' for thread in threading.enumerate()))

    def test_notification_f9_edges_require_foreground_and_do_not_pause_finished_game(self):
        service, frozen = self.service()
        events = []
        _, wrap = hooks(Settings(notification_enabled=True, notification_profiles=[frozen[0]['id']]), events.append, service=service)
        child = Mock(); wrapped = wrap(child); wrapped.control.game_done = True
        states = [(False, False, True), (True, False, True), (True, False, True),
                  (False, False, False), (True, False, False), (False, False, True),
                  (True, False, True), (False, True, True)]
        with patch('autohsr.notify_runtime._notification_key_state', side_effect=states):
            wrapped._watch_notification_hotkeys(threading.Event())
        self.assertEqual([event['paused'] for event in events if event['type'] == 'paused'], [True, False])
        child.toggle_pause.assert_not_called()
        child.stop.assert_not_called()

    def test_notification_hotkey_failure_stops_future_delivery_without_secret_log(self):
        service, frozen = self.service()
        events = []
        _, wrap = hooks(Settings(notification_enabled=True, notification_profiles=[frozen[0]['id']]), events.append, service=service)
        child = Mock(); wrapped = wrap(child); wrapped.control.game_done = True
        with patch('autohsr.notify_runtime._notification_key_state', side_effect=RuntimeError(SECRET)):
            wrapped._watch_notification_hotkeys(threading.Event())
        self.assertTrue(wrapped.control._stop.is_set())
        self.assertNotIn(SECRET, json.dumps(events))
        self.assertTrue(any(event['type'] == 'log' and event['level'] == 'error' for event in events))
        child.stop.assert_not_called()

    def test_filter_settings_are_transient_and_missing_profile_does_not_break_game(self):
        settings = Settings(notification_enabled=True, notification_profiles=['missing'], notification_statuses=['failed'])
        before = deepcopy(settings)
        events = []
        emit, wrap = hooks(settings, events.append, service=NotificationService(root=self.root, request=Mock()))
        child = Mock(); child.run.return_value = RunReport(status='success', report_saved=True)
        self.assertEqual(wrap(child).run().status, 'success')
        self.assertEqual(settings, before)
        self.assertTrue(any(e['type'] == 'notification_summary' and e['status'] == 'filtered' for e in events))
        with self.assertRaises(SettingsError):
            Settings(notification_enabled=True).validate('save')

    def test_http_redirect_timeout_and_oversized_response_never_leak_credentials(self):
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, '', {}, 'https://other.example.test'))
        with patch('autohsr.notify_http.build_opener') as opener:
            opener.return_value.open.side_effect = OSError('https://example.test/' + SECRET)
            with self.assertRaises(NotifyError) as error:
                request(Call('https://example.test/' + SECRET))
            self.assertNotIn(SECRET, str(error.exception))
        response = Mock(code=200)
        response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        response.read.return_value = b'x' * (1024 * 1024 + 1)
        response.read1 = response.read
        with patch('autohsr.notify_http.build_opener') as opener:
            opener.return_value.open.return_value = response
            with self.assertRaises(NotifyError):
                request(Call('https://example.test/' + SECRET))

    def test_custom_query_preserves_method_and_json_placeholders_are_literal(self):
        p = dict(url='https://example.test/custom', method='POST', datatype='params', data=dict(text='{message}'))
        call = calls('custom', p, 'title', 'body', 'id')[0]
        self.assertEqual(call.method, 'POST')
        self.assertIn('text=title%0Abody', call.url)
        self.assertIsNone(call.data)
        p = dict(url='https://example.test/custom', body=dict(text='{content}'))
        call = calls('webhook', p, 'title', '$(arbitrary-code); {literal}', 'id')[0]
        self.assertEqual(json.loads(call.data)['text'], '$(arbitrary-code); {literal}')

    def test_cli_profile_import_check_and_list_never_send_or_load_game(self):
        from autohsr.__main__ import main
        source = self.root / 'input.json'; source.write_text(json.dumps(record()), 'utf8'); before = source.read_bytes()
        store_path = self.root / 'vault'
        with patch('autohsr.config.Settings.load') as settings, patch('autohsr.app.Runner') as game, \
                patch('autohsr.notify_http.request', side_effect=AssertionError('never send')) as send:
            for arguments in ([ '--notify-providers'], ['--notify-profile-import', str(source), '--notify-store-dir', str(store_path)],
                              ['--notify-profile-check', 'test-webhook', '--notify-store-dir', str(store_path)],
                              ['--notify-profile-list', '--notify-store-dir', str(store_path)]):
                with redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
                    self.assertEqual(main(arguments), 0)
                    self.assertNotIn(SECRET, output.getvalue())
            settings.assert_not_called(); game.assert_not_called(); send.assert_not_called()
        self.assertEqual(source.read_bytes(), before)
        for arguments in (['--notify'], ['--notify-profile-check', ''], ['--notify-providers', '--config', 'fake.json']):
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                try:
                    result = main(arguments)
                except SystemExit as error:
                    result = error.code
                self.assertEqual(result, 2)

    def test_explicit_cli_test_uses_only_injected_service_and_no_game_configuration(self):
        from autohsr.__main__ import main
        service, frozen = self.service()
        with patch('autohsr.notify_runtime.NotificationService', return_value=service), \
                patch('autohsr.config.Settings.load') as settings, redirect_stdout(io.StringIO()) as output:
            self.assertEqual(main(['--notify-test', frozen[0]['id']]), 0)
        settings.assert_not_called()
        self.assertNotIn(SECRET, output.getvalue())

    def test_game_cli_overrides_wrap_one_parent_and_do_not_save_configuration(self):
        from autohsr.__main__ import main
        service, frozen = self.service()
        config = self.root / 'game-config.json'; Settings().save(config); original = config.read_bytes()
        game = RunReport(status='success', report_saved=True, daily_verified=True, operation='plan')
        with patch('autohsr.notify_runtime.NotificationService', return_value=service), \
                patch('autohsr.plan_runner.PlanRunner') as factory, redirect_stdout(io.StringIO()) as output, \
                redirect_stderr(io.StringIO()) as diagnostics:
            def create(settings, emit, **kwargs):
                self.assertTrue(settings.notification_enabled)
                self.assertEqual(settings.notification_profiles, [frozen[0]['id']])
                child = Mock()
                def run():
                    emit(dict(type='finished', report=game.to_dict()))
                    return game
                child.run.side_effect = run
                return child
            factory.side_effect = create
            self.assertEqual(main(['--plan', '--config', str(config), '--notify-profile', frozen[0]['id']]), 0)
        self.assertEqual(json.loads(output.getvalue()), game.to_dict())
        self.assertEqual(config.read_bytes(), original)
        self.assertNotIn(SECRET, diagnostics.getvalue())

    def test_workflow_cli_only_notifies_after_outer_completion(self):
        from autohsr.__main__ import main
        service, frozen = self.service()
        config = self.root / 'game-config.json'; Settings().save(config)
        definition = self.root / 'workflow.json'
        definition.write_text(json.dumps(dict(version=1, name='offline', steps=[dict(id='wait', type='wait', seconds=0)])), 'utf8')
        with patch('autohsr.notify_runtime.NotificationService', return_value=service), \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()):
            self.assertEqual(main(['--task-workflow', str(definition), '--config', str(config),
                                   '--notify-profile', frozen[0]['id']]), 0)
        self.assertEqual(json.loads(output.getvalue())['status'], 'success')
        self.assertEqual(len(list((self.root / 'attempts').glob('*.json'))), 1)

    def test_smtp_uses_tls_and_keeps_recipient_rejection_separate(self):
        from autohsr.notify_local import send
        connection = Mock()
        connection.send_message.return_value = {'refused@example.test': (550, b'blocked')}
        params = dict(PARAMS['smtp'], starttls=True, To=['one@example.test', 'refused@example.test'])
        with patch('autohsr.notify_local.smtplib.SMTP', return_value=connection) as factory:
            self.assertEqual(send('smtp', params, '标题', '离线测试'), 'partial')
        self.assertEqual(factory.call_args.kwargs['timeout'], 15)
        connection.starttls.assert_called_once()
        connection.login.assert_called_once_with('fake@example.test', SECRET)
        self.assertEqual(connection.send_message.call_args.kwargs['to_addrs'], ['one@example.test', 'refused@example.test'])
        connection.close.assert_called_once()

    def test_toast_keeps_untrusted_text_in_environment_and_launches_hidden(self):
        from autohsr.notify_local import send, TOAST_SCRIPT
        injected = '$(Start-Process fake); <xml>&' + SECRET
        with patch('autohsr.notify_local.subprocess.run', return_value=Mock(returncode=0)) as process:
            self.assertEqual(send('winotify', {}, injected, injected), 'accepted')
        self.assertEqual(process.call_args.kwargs['creationflags'], 0x08000000)
        self.assertNotIn(injected, ' '.join(process.call_args.args[0]))
        self.assertEqual(process.call_args.kwargs['env']['AUTOHSR_NOTIFY_TITLE'], injected)
        self.assertIn('SecurityElement', TOAST_SCRIPT)

    def test_http_body_reads_are_bounded_and_success_keeps_exact_response(self):
        response = Mock(code=200)
        response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        response.read1.side_effect = [b'{"ok":', b'true}', b'']
        with patch('autohsr.notify_http.build_opener') as opener:
            opener.return_value.open.return_value = response
            reply = request(Call('https://example.test'))
        self.assertEqual(reply, Reply(200, b'{"ok":true}'))
        self.assertTrue(all(call.args[0] <= 65536 for call in response.read1.call_args_list))
