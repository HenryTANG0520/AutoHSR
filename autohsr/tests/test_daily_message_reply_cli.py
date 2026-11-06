"""Exercise the explicit SMS command through Runner and fake native input."""
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from hashlib import sha256
import io
from itertools import count, islice
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2

from autohsr import app, daily_message_reply as reply, daily_message_reply_store, windows, workflow_lease
from autohsr.__main__ import main
from autohsr.config import Settings
from autohsr.currency_wars_identity import checked_account_key
from autohsr.daily_message_reply_store import ReplyStore
from autohsr.models import Scene, Token
from autohsr.tests import test_daily_event_claim as native_cases, test_daily_message_reply as replay
from autohsr.tests.test_daily_message_observe import ACCOUNT, OTHER, phone


class DailyMessageReplyCliTests(unittest.TestCase):
    def setUp(self):
        self.fixture = native_cases.DailyEventClaimTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.window = self.fixture.window
        self.native = self.fixture.native
        self.window.capture = Mock(side_effect=self.capture)
        self.frames = iter(())
        self.local_ocr = Mock(side_effect=AssertionError('unexpected local OCR'))

        self.config = self.fixture.root / 'settings.json'
        Settings(auto_launch=True, overlay_logs=True, battle=True, allow_stamina_spend=True,
                 ocr_confidence=.93).save(self.config)
        self.original_config = self.config.read_bytes()
        self.ledger_dir = self.fixture.root / 'runs' / 'daily-message-reply'

        ticks = count(100., .005)
        self.enterContext(patch('time.monotonic', side_effect=lambda: next(ticks)))
        self.enterContext(patch('autohsr.challenge_pages.time', time))
        self.enterContext(patch.multiple(
            reply,
            _STARTER=reply._text_digest(replay._SYNTHETIC_STARTER),
            _CHOICES=tuple((item, reply._text_digest(label)) for (item, _), label in
                           zip(reply._CHOICES, replay._SYNTHETIC_OPTIONS)),
            _OUTGOING=reply._text_digest(replay._SYNTHETIC_OUTGOING),
        ))
        kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock(),
                                 OpenMutexW=Mock(return_value=None))
        self.enterContext(patch.object(windows, 'kernel32', kernel))
        self.enterContext(patch.object(workflow_lease, '_kernel', return_value=kernel))
        self.enterContext(patch.object(app.C, 'get_last_error', return_value=0))
        self.enterContext(patch.object(app, 'ROOT', self.fixture.root))
        self.find_game = self.enterContext(patch.object(app, 'find_game', return_value=self.window))
        self.enterContext(patch.object(app, 'is_elevated', return_value=False))
        self.enterContext(patch.object(app, 'Vision', side_effect=self.vision))
        self.enterContext(patch.object(app.threading, 'Thread', return_value=Mock()))
        self.enterContext(patch.object(app.Runner, '_arm_hotkeys'))
        self.enterContext(patch.object(app.Context, 'sleep', lambda context, _: context.checkpoint()))
        for target in ('autohsr.app.launch', 'autohsr.app.Runner._prepare_daily_game',
                       'autohsr.app.Runner.wait_for_focus', 'autohsr.app.save_scene',
                       'autohsr.overlay.OverlayService', 'autohsr.notify_runtime.hooks',
                       'autohsr.recovery.BattleBudget', 'autohsr.du_reward_store.preflight',
                       'autohsr.du_archive_store.preflight',
                       'autohsr.currency_wars_weekly_reward_store.RewardStore'):
            forbidden = self.enterContext(patch(target, side_effect=AssertionError(target)))
            self.addCleanup(forbidden.assert_not_called)

    def vision(self, floor):
        self.assertLessEqual(floor, .65)
        return SimpleNamespace(confidence=floor, read=self.read)

    def capture(self):
        self.scene = next(self.frames)
        geometry = self.fixture.geometry
        self.scene.image = cv2.resize(self.scene.image, (geometry.width, geometry.height),
                                      interpolation=cv2.INTER_NEAREST)
        self.scene.geometry = geometry
        return self.scene.image, geometry

    def read(self, image, geometry=None):
        if geometry is None:
            return self.local_ocr(image)
        self.assertIs(image, self.scene.image)
        self.assertEqual(geometry, self.scene.geometry)
        return self.scene

    def args(self, selection=None):
        if selection is None:
            selection = (reply.REPLY_NODE, reply.REPLY_CHOICE)
        return ['--daily-message-reply', *selection,
                '--config', str(self.config), '--game-path', str(self.fixture.exe)]

    def invoke(self, selection=None):
        with redirect_stdout(io.StringIO()) as stdout:
            code = main(self.args(selection))
        output = stdout.getvalue()
        report = json.loads(output)
        self.assertEqual(report['operation'], reply.OPERATION)
        self.assertTrue(report['report_saved'])
        directory = Path(report['run_dir'])
        self.assertEqual(json.loads((directory / 'report.json').read_text(encoding='utf8')), report)
        self.assertFalse((directory / 'report.tmp').exists())
        self.assertFalse(list(directory.glob('*.png')))
        for value in (ACCOUNT.text, str(self.fixture.exe), replay._SYNTHETIC_STARTER,
                      *replay._SYNTHETIC_OPTIONS):
            self.assertNotIn(value, output)
        self.assertEqual(self.config.read_bytes(), self.original_config)
        return code, report

    def ledger(self):
        return {path.name: path.read_bytes() for path in self.ledger_dir.glob('reply-*.json')}

    def replace_with_identical_record(self, path):
        replacement = path.with_suffix('.replacement')
        replacement.write_bytes(path.read_bytes())
        self.assertNotEqual(path.stat().st_ino, replacement.stat().st_ino)
        replacement.replace(path)

    def assert_ledger_status(self, expected):
        record, = (json.loads(value) for value in self.ledger().values())
        self.assertEqual(set(record), {'schema', 'section', 'attempt', 'status'})
        self.assertEqual(record['status'], expected)

    def assert_result(self, result, expected):
        code, report = result
        record = report['daily_message_reply']
        self.assertEqual((code, report['status'], record['input_status'],
                          record['feedback_status'], record['ledger_status']), expected, report['error'])

    def expected_click(self, target):
        x, y = target.center
        geometry = self.fixture.geometry
        px = geometry.left + round(x * (geometry.width - 1))
        py = geometry.top + round(y * (geometry.height - 1))
        return ((0xC001, round(px * 65535 / 1919), round(py * 65535 / 1079)), (2, 0, 0), (4, 0, 0))

    def assert_replay_blocked(self, ledger_status, packet_count):
        original = self.ledger()
        self.frames = islice(replay.replay_frames(), 2)
        self.assert_result(self.invoke(), (1, 'partial', 'not_sent', 'unknown', ledger_status))
        self.assertEqual(self.ledger(), original)
        self.assertEqual(self.native.SendInput.call_count, packet_count)

    def test_verified_reply_uses_one_exact_click_and_cannot_replay(self):
        frames = list(replay.replay_frames())
        expected = self.expected_click(frames[1].tokens[4])
        self.frames = iter(frames)

        def send_with_pending(count, items, size):
            self.assertEqual(self.window.capture.call_count, 2)
            self.assert_ledger_status('pending')
            return self.fixture.send_input(count, items, size)

        self.native.SendInput.side_effect = send_with_pending
        self.assert_result(self.invoke(), (0, 'success', 'sent', 'confirmed', 'confirmed'))
        self.find_game.assert_called_once()
        self.assertEqual(self.window.capture.call_count, 4)
        self.assertEqual(self.fixture.packets, [expected])
        self.assert_ledger_status('confirmed')
        self.assert_replay_blocked('confirmed', 1)

    def test_p179_needs_exact_local_first_option_before_clicking_the_third(self):
        directory = replay.FIXTURES.with_name('daily_message_reply_p179')
        manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf8'))
        cases = manifest['cases']
        self.assertEqual([case['phase'] for case in cases], ['before', 'before', 'no_outgoing', 'after', 'after'])
        for case in cases:
            self.assertEqual(sha256((directory / case['file']).read_bytes()).hexdigest(), case['sha256'])

        plain, second, third = replay._SYNTHETIC_OPTIONS
        exact = '合成，选项甲！'
        outgoing = third + '。'
        labels = {'starter': replay._SYNTHETIC_STARTER, 'option_1_punctuation_omission': plain,
                  'option_2': second, 'option_3': third, 'outgoing': outgoing}
        profile = replace(
            reply._P179,
            starter=reply._text_digest(labels['starter']),
            choices=tuple((item, reply._text_digest(label)) for (item, _), label in
                          zip(reply._P179.choices, (exact, second, third))),
            outgoing=reply._text_digest(outgoing),
            first_option_plain=reply._plain_digest(exact),
        )
        self.enterContext(patch.object(reply, '_P179', profile))

        def frame(case):
            fields = [Token('甲乙', case[key]['score'], tuple(case[key]['box']))
                      for key in ('left_header', 'right_header')]
            fields.extend(Token(labels[field['field']], field['score'], tuple(field['box']))
                          for field in case['full_frame_vision'])
            return replay.state_frame(case['file'], ACCOUNT, *fields, directory=directory)

        geometry = self.fixture.geometry
        source_width, source_height = manifest['source_px']
        x0, y0, x1, y1 = manifest['regions_xyxy_half_open']['option_1_native_ocr']
        crop_width = round(x1 * geometry.width / source_width) - round(x0 * geometry.width / source_width)
        crop_height = round(y1 * geometry.height / source_height) - round(y0 * geometry.height / source_height)
        local = Token(exact, .97, (.37, .25, .625, .75))

        def supply_local(fields):
            def read_crop(image):
                self.assertEqual(image.shape, (2 * crop_height, 2 * crop_width, 3))
                self.assertEqual(self.window.capture.call_count, 2)
                self.native.SendInput.assert_not_called()
                return Scene(list(fields), image)

            self.local_ocr.reset_mock()
            self.local_ocr.side_effect = read_crop
            self.window.capture.reset_mock()

        for name, fields in (('missing', ()), ('weak', (replace(local, score=.89),)),
                             ('conflict', (local, replace(local, text='合成冲突项'))),
                             ('displaced', (replace(local, box=(.26, .25, .42, .75)),))):
            with self.subTest(local=name):
                supply_local(fields)
                self.frames = (frame(case) for case in cases[:2])
                self.assert_result(self.invoke(reply.P179_SELECTION),
                                   (1, 'failed', 'not_sent', 'unknown', 'none'))
                self.local_ocr.assert_called()
                self.assertFalse(self.ledger())
                self.native.SendInput.assert_not_called()

        supply_local((local,))
        before = [frame(case) for case in cases[:2]]
        target, = [token for token in before[-1].tokens if token.text == third]
        account = checked_account_key(before[-1], .93)
        ReplyStore(self.ledger_dir).reserve(account, reply._SECTION)
        original = self.ledger()
        self.frames = iter(before + [frame(case) for case in cases[2:]])
        code, report = self.invoke(reply.P179_SELECTION)
        self.assert_result((code, report), (0, 'success', 'sent', 'confirmed', 'confirmed'))
        record = report['daily_message_reply']
        self.assertEqual((record['node'], record['choice']), reply.P179_SELECTION)
        self.local_ocr.assert_called()
        self.assertEqual(self.window.capture.call_count, 5)
        self.native.SendInput.assert_called_once()
        self.assertEqual(self.fixture.packets, [self.expected_click(target)])
        records = self.ledger()
        self.assertEqual({name: records[name] for name in original}, original)
        receipt, = (json.loads(raw) for name, raw in records.items() if name not in original)
        self.assertEqual((receipt['section'], receipt['status']), (manifest['section'], 'confirmed'))
        self.assert_replay_blocked('pending', 1)

    def test_wrong_page_never_creates_an_intent_or_submits(self):
        self.frames = iter((phone(ACCOUNT), phone(ACCOUNT)))
        self.assert_result(self.invoke(), (1, 'failed', 'not_sent', 'unknown', 'none'))
        self.window.capture.assert_called()
        self.assertFalse(self.ledger())
        self.native.SendInput.assert_not_called()

    def test_unknown_selection_and_other_flags_are_rejected_before_native(self):
        args = self.args()
        for rejected in ([args[0], args[1], '不支持的合成回复', *args[3:]],
                         [*args, '--new-battle-run'],
                         [*args, '--config', str(self.config)]):
            with self.subTest(args=rejected), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                main(rejected)
            self.assertEqual(error.exception.code, 2)
        self.find_game.assert_not_called()
        self.window.capture.assert_not_called()
        self.native.SendInput.assert_not_called()
        self.assertFalse(self.ledger())

    def test_other_foreground_window_never_captures_or_submits(self):
        self.native.GetForegroundWindow.return_value = 55
        self.assert_result(self.invoke(), (1, 'failed', 'not_sent', 'unknown', 'none'))
        self.window.capture.assert_not_called()
        self.native.SendInput.assert_not_called()
        self.assertFalse(self.ledger())

    def test_desktop_opt_in_waits_for_manual_foreground_before_capture_and_input(self):
        self.frames = iter(replay.replay_frames())
        self.native.GetForegroundWindow.return_value = 55

        def handoff(_):
            self.window.capture.assert_not_called()
            self.native.SendInput.assert_not_called()
            self.native.GetForegroundWindow.return_value = self.window.hwnd

        clock = SimpleNamespace(monotonic=time.monotonic, sleep=Mock(side_effect=handoff))
        runner = app.Runner(Settings.load(self.config), operation=reply.OPERATION,
                            daily_message_reply=(reply.REPLY_NODE, reply.REPLY_CHOICE),
                            observation_wait_for_foreground=True)
        with patch('autohsr.screenshot_tool.time', clock):
            report = runner.run().to_dict()
        clock.sleep.assert_called_once()
        self.assertEqual(report['status'], 'success')
        self.assertEqual(report['daily_message_reply']['feedback_status'], 'confirmed')
        self.native.SendInput.assert_called_once()
        self.assert_ledger_status('confirmed')
        self.assertEqual(self.config.read_bytes(), self.original_config)

    def test_desktop_foreground_wait_honors_f10_without_capture_or_ledger(self):
        self.native.GetForegroundWindow.return_value = 55

        def stop(_):
            self.native.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key == 0x79 else 0

        clock = SimpleNamespace(monotonic=time.monotonic, sleep=Mock(side_effect=stop))
        runner = app.Runner(Settings.load(self.config), operation=reply.OPERATION,
                            daily_message_reply=(reply.REPLY_NODE, reply.REPLY_CHOICE),
                            observation_wait_for_foreground=True)
        with patch('autohsr.screenshot_tool.time', clock):
            report = runner.run().to_dict()
        clock.sleep.assert_called_once()
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(report['daily_message_reply']['input_status'], 'not_sent')
        self.window.capture.assert_not_called()
        self.native.SendInput.assert_not_called()
        self.assertFalse(self.ledger())

    def test_short_batch_only_releases_left_button_and_pending_blocks_replay(self):
        frames = list(replay.replay_frames())
        self.frames = iter(frames)
        self.fixture.accepted = 2
        self.assert_result(self.invoke(), (1, 'partial', 'unconfirmed', 'unknown', 'pending'))
        self.assertEqual(self.window.capture.call_count, 2)
        self.assertEqual(self.fixture.packets, [self.expected_click(frames[1].tokens[4]), ((4, 0, 0),)])
        self.assert_ledger_status('pending')
        self.assert_replay_blocked('pending', 2)

        original = self.ledger()
        self.fixture.accepted = 3
        self.frames = (replace(frame, tokens=[OTHER, *frame.tokens[1:]]) for frame in replay.replay_frames())
        self.assert_result(self.invoke(), (0, 'success', 'sent', 'confirmed', 'confirmed'))
        records = self.ledger()
        self.assertEqual({name: records[name] for name in original}, original)
        self.assertEqual(len(records), 2)
        self.assertEqual(self.native.SendInput.call_count, 3)
        self.assert_replay_blocked('pending', 3)

    def test_focus_loss_after_reservation_never_submits_and_keeps_pending(self):
        self.frames = islice(replay.replay_frames(), 2)
        reserve = ReplyStore.reserve

        def lose_focus(store, account, section):
            reservation = reserve(store, account, section)
            self.assert_ledger_status('pending')
            self.native.GetForegroundWindow.return_value = 55
            return reservation

        with patch.object(ReplyStore, 'reserve', lose_focus):
            self.assert_result(self.invoke(), (1, 'partial', 'not_sent', 'unknown', 'pending'))
        self.assertEqual(self.window.capture.call_count, 2)
        self.native.SendInput.assert_not_called()
        self.assert_ledger_status('pending')

    def test_same_bytes_replaced_after_reservation_publish_cannot_authorize_input(self):
        self.frames = iter(replay.replay_frames())
        publish = daily_message_reply_store._publish
        replaced = Mock()

        def publish_and_replace(path, payload, **kwargs):
            revision = publish(path, payload, **kwargs)
            if kwargs.get('exclusive'):
                self.replace_with_identical_record(path)
                replaced(path.read_bytes(), path.stat().st_ino)
            return revision

        with patch.object(daily_message_reply_store, '_publish', publish_and_replace):
            self.assert_result(self.invoke(), (1, 'partial', 'not_sent', 'unknown', 'pending'))
        replaced.assert_called_once()
        record, = self.ledger_dir.iterdir()
        self.assertEqual((record.read_bytes(), record.stat().st_ino), replaced.call_args.args)
        self.assert_replay_blocked('pending', 0)

    def test_pending_file_replaced_during_feedback_is_preserved_and_blocks_replay(self):
        self.frames = iter(replay.replay_frames())
        confirm = daily_message_reply_store._Reservation.confirm
        changed = Mock()

        def confirm_with_replacement(reservation, *, before_replace):
            def verify_feedback():
                before_replace()
                record, = self.ledger_dir.glob('reply-*.json')
                self.assert_ledger_status('pending')
                self.replace_with_identical_record(record)
                changed(record.read_bytes(), record.stat().st_ino)

            confirm(reservation, before_replace=verify_feedback)

        with patch.object(daily_message_reply_store._Reservation, 'confirm', confirm_with_replacement):
            self.assert_result(self.invoke(), (1, 'partial', 'sent', 'unknown', 'pending'))
        changed.assert_called_once()
        record, = self.ledger_dir.iterdir()
        self.assertEqual((record.read_bytes(), record.stat().st_ino), changed.call_args.args)
        self.assert_replay_blocked('pending', 1)

    def assert_publication_rejects_changed_ledger(self, change, next_ledger_status):
        self.frames = iter(replay.replay_frames())
        save_report = app.Runner._save_run_report
        changed = Mock()

        def before_report(runner, directory, *args, **kwargs):
            if kwargs.get('daily_observation_reader') is not None:
                record, = self.ledger_dir.glob('reply-*.json')
                self.assert_ledger_status('confirmed')
                change(record)
                changed(record.read_bytes(), record.stat().st_ino)
            return save_report(runner, directory, *args, **kwargs)

        with patch.object(app.Runner, '_save_run_report', before_report):
            self.assert_result(self.invoke(), (1, 'partial', 'sent', 'unknown', 'pending'))
        changed.assert_called_once()
        record, = self.ledger_dir.iterdir()
        self.assertEqual((record.read_bytes(), record.stat().st_ino), changed.call_args.args)
        self.assert_replay_blocked(next_ledger_status, 1)

    def test_confirmed_ledger_with_identical_bytes_but_new_identity_vetoes_success(self):
        self.assert_publication_rejects_changed_ledger(self.replace_with_identical_record, 'confirmed')

    def test_confirmed_ledger_with_changed_content_vetoes_success(self):
        def write_pending(path):
            path.write_bytes(path.read_bytes().replace(b'"status":"confirmed"', b'"status":"pending"'))

        self.assert_publication_rejects_changed_ledger(write_pending, 'pending')

    @unittest.skipUnless(os.name == 'nt', 'Windows sharing semantics')
    def test_report_retry_holds_and_rechecks_the_confirmed_ledger_even_when_stopped(self):
        self.frames = iter(replay.replay_frames())
        save_report = app.Runner._save_run_report
        replace_path = Path.replace
        attempted = Mock()

        def stop_before_report(runner, directory, *args, **kwargs):
            if kwargs.get('daily_observation_reader') is not None:
                self.native.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key == 0x79 else 0
            return save_report(runner, directory, *args, **kwargs)

        def replace_report(source, destination):
            if source.name == 'report.tmp':
                attempted()
                if attempted.call_count == 1:
                    draft = json.loads(source.read_text(encoding='utf8'))
                    self.assertEqual(draft['status'], 'stopped')
                    self.assertEqual(draft['daily_message_reply']['ledger_status'], 'confirmed')
                    record, = self.ledger_dir.glob('reply-*.json')
                    with self.assertRaises(PermissionError):
                        record.write_bytes(record.read_bytes())
                    raise PermissionError('offline report sharing violation')
            return replace_path(source, destination)

        def replace_ledger_between_attempts(_):
            record, = self.ledger_dir.glob('reply-*.json')
            self.replace_with_identical_record(record)

        with patch.object(app.Runner, '_save_run_report', stop_before_report), \
                patch.object(Path, 'replace', replace_report), \
                patch('autohsr.storage.time.sleep', side_effect=replace_ledger_between_attempts) as wait:
            self.assert_result(self.invoke(), (130, 'stopped', 'sent', 'unknown', 'pending'))
        wait.assert_called_once()
        self.assertEqual(attempted.call_count, 2)
        self.native.GetAsyncKeyState.side_effect = None
        self.assert_replay_blocked('confirmed', 1)

    def assert_publication_interrupt(self, interrupt, code, status):
        self.frames = iter(replay.replay_frames())
        save_report = app.Runner._save_run_report
        at_publication = Mock()

        def before_report(runner, directory, *args, **kwargs):
            reader = kwargs.get('daily_observation_reader')
            if reader is not None:
                self.assertEqual(reader.record['feedback_status'], 'confirmed')
                self.assert_ledger_status('confirmed')
                at_publication()
                interrupt()
            return save_report(runner, directory, *args, **kwargs)

        with patch.object(app.Runner, '_save_run_report', before_report):
            self.assert_result(self.invoke(), (code, status, 'sent', 'unknown', 'confirmed'))
        at_publication.assert_called_once()
        self.assertEqual(self.window.capture.call_count, 4)
        self.native.SendInput.assert_called_once()
        self.assert_ledger_status('confirmed')

    def test_focus_loss_at_publication_revokes_feedback_and_keeps_confirmation(self):
        def lose_focus():
            self.native.GetForegroundWindow.return_value = 55

        self.assert_publication_interrupt(lose_focus, 1, 'partial')

    def test_f10_at_publication_revokes_feedback_and_keeps_confirmation(self):
        def press_f10():
            self.native.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key == 0x79 else 0

        self.assert_publication_interrupt(press_f10, 130, 'stopped')
