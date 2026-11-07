"""Only synthetic credentials, local PNGs and fake SMTP connections are used."""

from contextlib import nullcontext, redirect_stderr, redirect_stdout
import io
import json
import os
from pathlib import Path
import smtplib
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from PIL import Image, PngImagePlugin

from autohsr import notify_runtime, reward_guide_notify, workflow_notify
from autohsr.__main__ import main
from autohsr.config import Settings
from autohsr.models import Stopped
from autohsr.reward_guide_export import export_reward_guide
from autohsr.task_workflow_run import TaskWorkflowRunner


class RewardGuideNotifyTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.service = notify_runtime.NotificationService(root=self.root / 'private-store', request=Mock(
            side_effect=AssertionError('no HTTP or unsupported provider traffic')))
        self.profile = dict(id='guide-test', provider='smtp', params=dict(host='smtp.example.test',
                            user='private-sender@example.test', password='private-test-password',
                            To=['private-first@example.test', 'private-second@example.test']))
        self.service.store.save(self.profile)
        self.png = self.root / 'private-user-calendar.png'
        Image.new('RGB', (192, 176), (31, 95, 180)).save(self.png)
        self.smtp = self.enterContext(patch('autohsr.notify_local.smtplib.SMTP'))
        self.ssl = self.enterContext(patch('autohsr.notify_local.smtplib.SMTP_SSL'))
        self.connection = Mock()
        self.connection.send_message.return_value = {}
        self.smtp.return_value = self.ssl.return_value = self.connection
        self.addCleanup(self.service.request.assert_not_called)

    def notify(self, image=None, profile=None, **options):
        result = reward_guide_notify.send_reward_guide(image or self.png, profile or self.profile['id'],
                                                     service=self.service, **options)
        self.assert_public(result)
        return result

    def assert_public(self, result):
        self.assertEqual(set(result), {'status', 'reason', 'reused'})
        public = json.dumps(result)
        for private in (str(self.root), self.png.name, self.profile['id'], 'private-', '@example.test', 'smtp.example.test'):
            self.assertNotIn(private, public)

    def command(self, *, image=None, profile=None):
        return ['--reward-guide-notify', str(image or self.png),
                '--reward-guide-notify-profile', profile or self.profile['id']]

    def cli(self, flags=None, *, code=0):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(reward_guide_notify, 'NotificationService', return_value=self.service), \
                patch('autohsr.config.Settings.load', side_effect=AssertionError('no game settings')), \
                patch('autohsr.app.find_game', side_effect=AssertionError('no game window')), \
                redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(self.command() if flags is None else flags), code)
        self.assertEqual(errors.getvalue(), '')
        result = json.loads(output.getvalue())
        self.assert_public(result)
        return result

    def attempts(self):
        return [json.loads(path.read_text(encoding='utf8'))
                for path in (self.service.root / 'attempts').glob('*.json')]

    def workflow(self, *, profile=None):
        profile = self.profile['id'] if profile is None else profile
        path = self.root / 'flow.json'
        step = dict(id='image', type='task', task='workflow_notify',
                    params=dict(profile=profile, message='PRIVATE_WORKFLOW_MESSAGE', png=self.png.name))
        path.write_text(json.dumps(dict(version=1, name='PNG', steps=[step])), encoding='utf8')
        config = self.root / 'config.json'
        Settings().save(config)
        return ['--task-workflow', str(path), '--config', str(config), '--workflow-allow-notify',
                '--workflow-notify-png', str(self.png), profile]

    def workflow_cli(self, args, *, code=0):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(reward_guide_notify, 'NotificationService', return_value=self.service), \
                patch.object(workflow_notify, 'NotificationService', return_value=self.service), \
                patch('autohsr.task_workflow_run.ROOT', self.root), \
                patch('autohsr.task_workflow_run.workflow_lease', side_effect=nullcontext), \
                patch.object(TaskWorkflowRunner, '_hotkeys'), \
                patch('autohsr.app.find_game', side_effect=AssertionError('no game window')), \
                redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(main(args), code, errors.getvalue())
        return json.loads((errors if code == 2 else output).getvalue())

    def test_workflow_sends_explicit_png_and_shares_calendar_attempt(self):
        args = self.workflow()

        def submit(mail, **_):
            intents = list((self.root / 'runs').rglob('notify-1/intent.json'))
            self.assertEqual(len(intents), 1)
            self.assertEqual(json.loads(intents[0].read_bytes())['status'], 'pending')
            self.assertEqual(self.attempts()[0]['actions'], [dict(phase='send', index=0, status='pending')])
            self.assertEqual(str(mail['Subject']), 'AutoHSR · 任务流程通知')
            self.assertIn('PRIVATE_WORKFLOW_MESSAGE', mail.get_body().get_content())
            attachment, = mail.iter_attachments()
            self.assertEqual(attachment.get_filename(), 'reward-guide.png')
            self.assertEqual(attachment.get_payload(decode=True), self.png.read_bytes())
            return {}

        self.connection.send_message.side_effect = submit
        first = self.workflow_cli(args)
        self.assertEqual(first['workflow']['steps'][0]['notification'],
                         dict(status='accepted', reason='provider_accepted', reused=False))
        report, = (self.root / 'runs').rglob('notify-1/report.json')
        for private in (self.png.name, self.profile['id'], 'PRIVATE_WORKFLOW_MESSAGE', '@example.test'):
            self.assertNotIn(private, report.read_text('utf8'))
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('test', 'changed metadata')
        Image.new('RGB', (192, 176), (31, 95, 180)).save(self.png, pnginfo=metadata)
        self.assertTrue(self.notify()['reused'])
        repeated = self.workflow_cli(args, code=1)
        self.assertEqual(repeated['workflow']['steps'][0]['notification'],
                         dict(status='unknown', reason='already_attempted', reused=True))
        self.connection.send_message.assert_called_once()

    def test_workflow_requires_matching_manual_grant_and_encrypted_smtp(self):
        args = self.workflow()
        with patch.object(reward_guide_notify, 'freeze_png') as png, \
                patch.object(reward_guide_notify, 'freeze_smtp_profile') as profile:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as missing:
                main(args[:-3])
            self.assertEqual(missing.exception.code, 2)
            mismatched = self.workflow_cli(args[:-1] + ['other'], code=2)
            self.assertIn('完全一致', mismatched['error'])
            profile.assert_not_called()
            png.assert_not_called()

        self.service.store.save(dict(id='discord-test', provider='discord', params=dict(webhook='https://example.test/hook')))
        with patch.object(reward_guide_notify, 'freeze_png') as png:
            rejected = self.workflow_cli(self.workflow(profile='discord-test'), code=2)
            self.assertIn('SSL 或 STARTTLS', rejected['error'])
            png.assert_not_called()
        self.assertEqual(self.attempts(), [])
        self.ssl.assert_not_called()

    def test_workflow_revokes_frozen_image_or_profile_before_smtp(self):
        args = self.workflow()
        run = TaskWorkflowRunner.run

        def replace_image(runner):
            self.png.write_bytes(b'not the approved PNG')
            return run(runner)

        def replace_profile(runner):
            self.service.store.save(dict(self.profile, params=dict(self.profile['params'],
                                    To='different@example.test')), replace=True)
            return run(runner)

        for action, reason in ((replace_image, 'attachment_changed'), (replace_profile, 'profile_changed')):
            Image.new('RGB', (192, 176), (31, 95, 180)).save(self.png)
            with self.subTest(reason=reason), patch.object(TaskWorkflowRunner, 'run', action):
                result = self.workflow_cli(args, code=1)
                self.assertEqual(result['workflow']['steps'][0]['notification'],
                                 dict(status='rejected', reason=reason, reused=False))
        self.assertEqual(self.attempts(), [])
        self.ssl.assert_not_called()

    def test_exported_png_attaches_exact_pixels_after_durable_intent_and_reuses(self):
        stitched = self.root / 'explicit-export.png'
        self.assertEqual(export_reward_guide([self.png], stitched)['status'], 'ok')
        source = stitched.read_bytes()

        def inspect_mail(message, *, from_addr, to_addrs):
            pending, = self.attempts()
            self.assertEqual(pending['actions'], [dict(phase='send', index=0, status='pending')])
            self.assertEqual(pending['status'], 'pending')
            attachment, = message.iter_attachments()
            self.assertEqual(attachment.get_content_type(), 'image/png')
            self.assertEqual(attachment.get_filename(), 'reward-guide.png')
            self.assertEqual(attachment.get_payload(decode=True), source)
            self.assertNotIn(stitched.name, message.as_string())
            self.assertEqual(from_addr, self.profile['params']['user'])
            self.assertEqual(to_addrs, self.profile['params']['To'])
            return {}

        self.connection.send_message.side_effect = inspect_mail
        first = self.notify(stitched)
        self.assertEqual(first, dict(status='accepted', reason='provider_accepted', reused=False))
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('private-note', 'changed metadata with unchanged pixels')
        Image.new('RGB', (192, 176), (31, 95, 180)).save(self.png, compress_level=0, pnginfo=metadata)
        self.assertEqual(self.notify(), dict(first, reused=True))
        self.assertEqual(stitched.read_bytes(), source)
        self.ssl.assert_called_once()
        self.smtp.assert_not_called()
        self.connection.send_message.assert_called_once()
        self.connection.close.assert_called_once()

    def test_starttls_accepts_tall_png_and_strips_metadata_without_resizing(self):
        params = dict(self.profile['params'], ssl=False, starttls=True)
        self.service.store.save(dict(self.profile, id='starttls-test', params=params))
        metadata = PngImagePlugin.PngInfo()
        metadata.add_text('private-note', 'local metadata must not be attached')
        Image.new('RGB', (128, 4100), (9, 19, 29)).save(self.png, pnginfo=metadata)
        self.assertEqual(self.notify(profile='starttls-test')['status'], 'accepted')
        self.smtp.assert_called_once()
        self.ssl.assert_not_called()
        self.connection.starttls.assert_called_once()
        attachment, = self.connection.send_message.call_args.args[0].iter_attachments()
        with Image.open(io.BytesIO(attachment.get_payload(decode=True))) as image:
            self.assertEqual(image.size, (128, 4100))
            self.assertEqual(image.getpixel((0, 0)), (9, 19, 29))
            self.assertEqual(image.info, {})

    def test_unsupported_or_unencrypted_profile_stops_before_reading_png(self):
        self.service.store.save(dict(id='discord-test', provider='discord', params=dict(webhook='https://example.test/hook')))
        self.service.store.save(dict(self.profile, id='plain-test',
                                params=dict(self.profile['params'], ssl=False, allow_insecure=True)))
        with patch.object(reward_guide_notify, '_load_attachment', side_effect=AssertionError('no PNG read')):
            for profile, reason in (('discord-test', 'unsupported_provider'), ('plain-test', 'tls_required'),
                                    ('not-saved', 'invalid_profile')):
                with self.subTest(profile=profile):
                    self.assertEqual(self.notify(profile=profile), dict(status='rejected', reason=reason, reused=False))
        self.smtp.assert_not_called()
        self.ssl.assert_not_called()
        self.assertEqual(self.attempts(), [])

    def test_invalid_png_and_limits_never_open_a_connection(self):
        rgb = Image.new('RGB', (192, 176))
        rgb.save(self.png, format='JPEG')
        self.assertEqual(self.notify()['reason'], 'invalid_attachment')
        rgb.save(self.png, save_all=True, append_images=[Image.new('RGB', rgb.size, 'red')])
        self.assertEqual(self.notify()['reason'], 'invalid_attachment')
        Image.new('RGBA', (192, 176), (9, 19, 29, 200)).save(self.png)
        self.assertEqual(self.notify()['reason'], 'invalid_attachment')
        rgb.save(self.png)
        raw = bytearray(self.png.read_bytes())
        raw[raw.index(b'IDAT') + 5] ^= 1
        self.png.write_bytes(raw)
        self.assertEqual(self.notify()['reason'], 'invalid_attachment')
        Image.new('RGB', (64, 12289)).save(self.png)
        self.assertEqual(self.notify()['reason'], 'attachment_limit')
        rgb.save(self.png)
        with patch.object(reward_guide_notify, 'MAX_PNG_ATTACHMENT_BYTES', 100):
            self.assertEqual(self.notify()['reason'], 'attachment_limit')
        self.smtp.assert_not_called()
        self.ssl.assert_not_called()
        self.assertEqual(self.attempts(), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows reparse-point rules')
    def test_actual_directory_junctions_are_rejected_before_transport(self):
        from _winapi import CreateJunction

        image_dir = self.root / 'image-dir'
        image_dir.mkdir()
        self.png.replace(image_dir / self.png.name)
        alias = self.root / 'image-alias'
        CreateJunction(str(image_dir), str(alias))
        self.assertEqual(self.notify(alias / self.png.name)['reason'], 'invalid_attachment')

        profile_dir = self.service.store.path(self.profile['id']).parent
        moved = profile_dir.with_name('profiles-moved')
        profile_dir.rename(moved)
        CreateJunction(str(moved), str(profile_dir))
        self.assertEqual(self.notify(image_dir / self.png.name)['reason'], 'invalid_profile')
        self.ssl.assert_not_called()
        self.assertEqual(self.attempts(), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows filesystem sharing')
    def test_source_and_profile_are_locked_through_submission(self):
        profile_path = self.service.store.path(self.profile['id'])

        def protected(*_args, **_kwargs):
            for path in (self.png, profile_path):
                with self.assertRaises(OSError):
                    path.write_bytes(b'altered')
                with self.assertRaises(OSError):
                    path.rename(path.with_suffix('.moved'))
            return {}

        self.connection.send_message.side_effect = protected
        self.assertEqual(self.notify()['status'], 'accepted')
        self.connection.send_message.assert_called_once()

    def test_pending_action_does_not_authorize_a_changed_profile_or_same_bytes_new_source(self):
        write = notify_runtime._write
        same_bytes = self.root / 'same-bytes.png'
        same_bytes.write_bytes(self.png.read_bytes())
        alternate = self.root / 'alternate.png'
        Image.new('RGB', (192, 176), 'blue').save(alternate)

        def race(path, data):
            write(path, data)
            if data['status'] == 'pending' and data['actions']:
                if same_bytes.exists():
                    same_bytes.replace(self.png)
                else:
                    self.service.store.save(dict(self.profile, params=dict(self.profile['params'],
                                            To='replacement@example.test')), replace=True)

        with patch.object(notify_runtime, '_write', side_effect=race):
            self.assertEqual(self.notify()['reason'], 'attachment_changed')
            self.assertEqual(self.notify(alternate)['reason'], 'profile_changed')
        self.ssl.assert_not_called()
        self.connection.send_message.assert_not_called()

    def test_stop_during_authentication_prevents_the_attachment(self):
        stopped = False

        def stop(*_):
            nonlocal stopped
            stopped = True

        def checkpoint():
            if stopped:
                raise Stopped('private-test-marker')

        self.connection.login.side_effect = stop
        self.assertEqual(self.notify(checkpoint=checkpoint), dict(status='cancelled', reason='stopped_before_send', reused=False))
        self.connection.send_message.assert_not_called()
        self.connection.close.assert_called_once()
        self.assertEqual(self.notify(), dict(status='unknown', reason='delivery_unknown', reused=True))

    def test_injected_transport_requires_the_submit_guard_and_never_opens_smtp(self):
        self.service.local_send = Mock(return_value='accepted')
        self.assertEqual(self.notify()['reason'], 'submission_not_started')
        self.assertEqual(self.notify(), dict(status='unknown', reason='delivery_unknown', reused=True))
        self.service.local_send.assert_called_once()

        def transport(provider, _params, _title, _body, *, png, before_submit):
            self.assertEqual(provider, 'smtp')
            self.assertTrue(png.startswith(b'\x89PNG\r\n\x1a\n'))
            before_submit()
            return 'accepted'

        Image.new('RGB', (192, 176), 'red').save(self.png)
        self.service.local_send.side_effect = transport
        self.assertEqual(self.notify()['status'], 'accepted')
        self.smtp.assert_not_called()
        self.ssl.assert_not_called()

    def test_partial_rejected_and_unknown_responses_are_distinct_and_unknown_is_not_retried(self):
        refused = self.profile['params']['To'][1]
        for color, response, status in ((1, {refused: (550, b'private-response')}, 'partial'),
                                         (2, smtplib.SMTPRecipientsRefused({refused: (550, b'private-response')}), 'rejected'),
                                         (3, TimeoutError('private-response'), 'unknown'), (4, None, 'unknown')):
            with self.subTest(status=status):
                Image.new('RGB', (192, 176), (color, 10, 10)).save(self.png)
                self.connection.send_message.reset_mock()
                self.connection.send_message.side_effect = [response]
                first = self.notify()
                self.assertEqual(first['status'], status)
                self.assertEqual(self.notify(), dict(first, reused=True))
                self.connection.send_message.assert_called_once()

    def test_failed_acknowledgement_write_keeps_pending_without_repeat(self):
        write = notify_runtime._write

        def fail_acknowledgement(path, data):
            if any(row['status'] == 'accepted' for row in data['actions']):
                raise OSError('private-test-marker')
            return write(path, data)

        with patch.object(notify_runtime, '_write', side_effect=fail_acknowledgement):
            self.assertEqual(self.notify(), dict(status='unknown', reason='receipt_write_failed', reused=False))
        pending, = self.attempts()
        self.assertEqual(pending['status'], 'pending')
        self.assertEqual(self.notify(), dict(status='unknown', reason='delivery_unknown', reused=True))
        self.connection.send_message.assert_called_once()

    def test_formal_cli_accepts_explicit_file_and_profile_and_reuses_success(self):
        export = self.root / 'selected calendar.png'
        self.assertEqual(export_reward_guide([self.png], export)['status'], 'ok')
        first = self.cli(self.command(image=export))
        self.assertEqual(first, dict(status='accepted', reason='provider_accepted', reused=False))
        attachment, = self.connection.send_message.call_args.args[0].iter_attachments()
        self.assertEqual(attachment.get_filename(), 'reward-guide.png')
        self.assertEqual(attachment.get_payload(decode=True), export.read_bytes())
        reused = self.cli([f"--reward-guide-notify-profile={self.profile['id']}", f'--reward-guide-notify={export}'])
        self.assertEqual(reused, dict(first, reused=True))
        self.connection.send_message.assert_called_once()

    def test_formal_cli_rejects_incomplete_duplicate_and_combined_arguments_before_dispatch(self):
        valid = self.command()
        bad_flags = (valid[:2], valid[2:], valid + valid[2:], valid[:2] + valid, valid + ['--run'],
                     valid + ['--screen-test'], valid + ['--daily-event-claim', '7'],
                     valid + ['--notify-test', 'text-test'], valid + ['--notify-profile', 'text-test'],
                     valid + ['--notify-store-dir', str(self.root)], valid + ['--config', 'unused.json'],
                     valid + ['--reward-guide-output', 'unused.png'], valid[2:] + ['--check'],
                     valid[:2] + ['--reward-guide-notify-profil', self.profile['id']])
        with patch.object(reward_guide_notify, 'send_reward_guide') as deliver, \
                patch('autohsr.config.Settings.load') as settings, patch('autohsr.app.find_game') as window:
            for flags in bad_flags:
                with self.subTest(flags=flags), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()), \
                        self.assertRaises(SystemExit) as error:
                    main(flags)
                self.assertEqual(error.exception.code, 2)
        deliver.assert_not_called()
        settings.assert_not_called()
        window.assert_not_called()
        self.ssl.assert_not_called()

    def test_formal_cli_revokes_authorization_on_source_and_profile_changes(self):
        write = notify_runtime._write

        def rewrite_source():
            Image.new('RGB', (192, 176), 'purple').save(self.png)

        def replace_profile():
            self.service.store.save(dict(self.profile, params=dict(self.profile['params'],
                                    To='different@example.test')), replace=True)

        for mutate, reason in ((rewrite_source, 'attachment_changed'), (replace_profile, 'profile_changed')):
            def race(path, data):
                write(path, data)
                if data['status'] == 'pending' and data['actions']:
                    mutate()

            with self.subTest(reason=reason), patch.object(notify_runtime, '_write', side_effect=race):
                self.assertEqual(self.cli(code=1), dict(status='rejected', reason=reason, reused=False))
        self.ssl.assert_not_called()
        self.connection.send_message.assert_not_called()

    def test_formal_cli_keeps_rejected_unknown_partial_and_stopped_statuses(self):
        self.service.store.save(dict(id='discord-test', provider='discord', params=dict(webhook='https://example.test/hook')))
        rejected = self.cli(self.command(profile='discord-test'), code=1)
        self.assertEqual(rejected, dict(status='rejected', reason='unsupported_provider', reused=False))
        self.ssl.assert_not_called()

        self.connection.send_message.side_effect = TimeoutError('private-remote-response')
        unknown = self.cli(code=1)
        self.assertEqual(unknown, dict(status='unknown', reason='delivery_unknown', reused=False))
        self.assertEqual(self.cli(code=1), dict(unknown, reused=True))
        self.connection.send_message.assert_called_once()

        Image.new('RGB', (192, 176), 'green').save(self.png)
        refused = self.profile['params']['To'][1]
        self.connection.send_message.side_effect = None
        self.connection.send_message.return_value = {refused: (550, b'private-remote-response')}
        self.assertEqual(self.cli(code=1), dict(status='partial', reason='provider_partial', reused=False))

        Image.new('RGB', (192, 176), 'black').save(self.png)
        self.connection.send_message.reset_mock()
        self.connection.login.side_effect = KeyboardInterrupt
        self.assertEqual(self.cli(code=130), dict(status='cancelled', reason='stopped_before_send', reused=False))
        self.connection.send_message.assert_not_called()
