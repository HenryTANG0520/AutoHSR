from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
from hashlib import sha256
import io
from itertools import count
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_identity import UID_COUNTEREVIDENCE
from autohsr.daily_message_observe import (MAX_CAPTURES, OPERATION, _MESSAGE_HEADER, _message_panel_frame, message_panel,
                                           observe_daily_messages, phone_message_entry)
from autohsr.daily_message_state import read_panel_state, unknown_panel_state
from autohsr.models import AutomationError, EmptyCapture, FocusLost, InputInterrupted, RunReport, Scene, Token
from autohsr.tests.test_daily_reward_observe import _Window
from autohsr.tests.test_du_team import fixture
from autohsr.vision import Vision


ACCOUNT = Token('UID:135792468', .99, (.018, .957, .106, .985))
OTHER = replace(ACCOUNT, text='UID:246813579')
STATE_FIXTURES = Path(__file__).parent / 'fixtures/daily_message_state'


def phone(*extras):
    scene = fixture('phone_mail_icon')
    scene.captured_at = time.monotonic()
    scene.tokens.extend(extras)
    return scene


def label(text, box, confidence=.99):
    return Token(text, confidence, box)


def panel(*tokens, header=True, content=True):
    # Static layout traced from the two public 4.6 PC preview strips.
    image = np.full((1080, 1920, 3), 29, dtype=np.uint8)
    image[176:908, 273:756] = 40
    if content:
        image[176:908, 756:1644] = 209
    if header:
        patch_image = cv2.imdecode(np.fromfile(_MESSAGE_HEADER, np.uint8), cv2.IMREAD_COLOR)
        height, width = patch_image.shape[:2]
        image[216:216 + height, 308:308 + width] = patch_image
    return Scene(list(tokens), image, captured_at=time.monotonic())


def state_frame(name, *tokens):
    data = (STATE_FIXTURES / name).read_bytes()
    reduced = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    image = cv2.resize(reduced, (1920, 1080), interpolation=cv2.INTER_NEAREST)
    return Scene(list(tokens), image, captured_at=time.monotonic())


class MessagePageTests(unittest.TestCase):
    def test_real_masked_phone_keeps_the_original_message_tile(self):
        scene = phone()
        expected, = [token for token in scene.tokens if token.text == '短信']
        self.assertIs(phone_message_entry(scene, .93), expected)

    def test_mail_and_title_only_are_not_phone_entry_evidence(self):
        mail = fixture('mail_claimable')
        mail.captured_at = time.monotonic()
        scene = phone()
        title = label('短信', (.022, .038, .060, .064))
        for page in (mail, replace(scene, tokens=[title]), phone(title)):
            with self.subTest(page=page.tokens[0].text):
                self.assertIsNone(phone_message_entry(page))

    def test_rejects_modal_missing_landmark_shifted_row_and_low_confidence(self):
        scene = phone()
        shifted = [replace(t, box=tuple(value + (.022 if i % 2 else 0)
                                        for i, value in enumerate(t.box)))
                   if t.text == '导航' else t for t in scene.tokens]
        weak = [replace(t, score=.79) if t.text == '短信' else t for t in scene.tokens]
        no_level = [t for t in scene.tokens if '开拓等级' not in t.text]
        blocked = phone(label('确认', (.45, .67, .51, .71)))
        for page in (blocked, replace(scene, tokens=shifted), replace(scene, tokens=weak),
                     replace(scene, tokens=no_level), replace(scene, captured_at=0)):
            self.assertIsNone(phone_message_entry(page))

    def test_message_panel_needs_the_title_art_and_the_unoccluded_layout(self):
        self.assertTrue(message_panel(panel()))
        self.assertFalse(message_panel(phone()))
        self.assertFalse(message_panel(panel(content=False)))
        self.assertFalse(message_panel(panel(header=False)))
        self.assertFalse(message_panel(panel(label('获得物品', (.44, .11, .52, .16)))))

    def test_anonymous_pc_source_frames_distinguish_badge_choices_fades_and_reward(self):
        manifest = json.loads((STATE_FIXTURES / 'manifest.json').read_text(encoding='utf8'))
        for case in manifest['cases']:
            name = case['file']
            with self.subTest(part=case['part'], time=case['time_seconds']):
                self.assertEqual(sha256((STATE_FIXTURES / name).read_bytes()).hexdigest(), case['sha256'])
                frame = _message_panel_frame(state_frame(name))
                state = None if frame is None else read_panel_state(frame)
                self.assertEqual(state, case['expected'])


class MessageObserverTests(unittest.TestCase):
    def setUp(self):
        clock = count(1000.0, .05)
        clock_patch = patch('autohsr.daily_message_observe.time.monotonic', side_effect=lambda: next(clock))
        clock_patch.start()
        self.addCleanup(clock_patch.stop)

    @staticmethod
    def context(frames):
        source = iter(frames)
        first = phone()
        geometry = SimpleNamespace(height=first.image.shape[0], width=first.image.shape[1])
        state = SimpleNamespace(frame=None)

        def capture():
            state.frame = next(source, EmptyCapture('synthetic empty'))
            if isinstance(state.frame, Exception):
                raise state.frame
            return state.frame.image, geometry

        def read(image, bounds):
            return Scene(state.frame.tokens, image, bounds, field_reads=state.frame.field_reads)

        window = SimpleNamespace(current_window_key=Mock(return_value='test-window'),
                                 guard=Mock(return_value=geometry), capture=Mock(side_effect=capture))
        return SimpleNamespace(window=window, vision=SimpleNamespace(read=read, confidence=.65),
                               runner=SimpleNamespace(input_epoch=0, _foreground_only=True, stop_requested=False),
                               report=SimpleNamespace(operation=OPERATION),
                               settings=SimpleNamespace(ocr_confidence=.93),
                               sleep=Mock(), checkpoint=Mock())

    def test_two_distinct_same_account_frames_only_certify_phone_entry(self):
        context = self.context([phone(ACCOUNT), phone(ACCOUNT)])
        result = observe_daily_messages(context)
        self.assertEqual(result, dict(schema=1, phone_entry='observed', message_page='unknown',
                                     reward_status='unknown', input_sent=False,
                                     account_verified=True, captures=2, **unknown_panel_state()))

    def test_duplicate_buffers_and_missing_account_cannot_form_a_pair(self):
        first = phone(ACCOUNT)
        for frames in ([first, first], [first, phone(), phone(ACCOUNT)]):
            with self.subTest(size=len(frames)):
                context = self.context(frames)
                result = observe_daily_messages(context)
                self.assertEqual(result['phone_entry'], 'unknown')
                self.assertFalse(result['account_verified'])
                self.assertEqual(context.window.capture.call_count, MAX_CAPTURES)

    def test_phone_and_panel_never_form_a_pair_together(self):
        first = phone(ACCOUNT)
        destination = panel(ACCOUNT)
        self.assertEqual(first.image.shape, destination.image.shape)
        incomplete = observe_daily_messages(self.context([first, destination]))
        self.assertEqual(incomplete['message_page'], 'unknown')
        result = observe_daily_messages(self.context([first, destination, panel(ACCOUNT)]))
        self.assertEqual(result['message_page'], 'observed')
        self.assertEqual(result['phone_entry'], 'unknown')
        self.assertEqual(result['unread_status'], 'unknown')
        self.assertEqual(result['reward_status'], 'unknown')
        self.assertFalse(result['input_sent'])
        self.assertEqual(result['captures'], 3)

    def test_panel_substates_need_agreement_in_the_same_pair(self):
        two, three = 'options_two.png', 'options_three.png'
        for names, expected in (((two, two), ('options_visible', 2)), ((two, three), ('unknown', None))):
            with self.subTest(names=names):
                context = self.context([state_frame(name, ACCOUNT) for name in names])
                result = observe_daily_messages(context)
                self.assertEqual(result['message_page'], 'observed')
                self.assertEqual((result['reply_status'], result['reply_options']), expected)

    def test_badge_is_a_visible_state_and_disagreement_is_unknown(self):
        before, after = 'list_badge.png', 'options_three.png'
        for names, expected in (((before, before), 'badge_visible'), ((before, after), 'unknown')):
            with self.subTest(names=names):
                context = self.context([state_frame(name, ACCOUNT) for name in names])
                result = observe_daily_messages(context)
                self.assertEqual(result['unread_status'], expected)
                self.assertEqual(result['reward_status'], 'unknown')

    def test_conflicting_account_veto_and_focus_loss_stop_without_recovery(self):
        conflicting = phone(ACCOUNT)
        conflicting.field_reads[UID_COUNTEREVIDENCE] = (replace(OTHER, score=.68),)
        for frame, error in ((phone(OTHER), AutomationError), (conflicting, AutomationError),
                             (FocusLost('synthetic focus loss'), FocusLost)):
            with self.subTest(error=error):
                context = self.context([phone(ACCOUNT), frame])
                with self.assertRaises(error):
                    observe_daily_messages(context)
                self.assertEqual(context.window.capture.call_count, 2)

    def test_requires_dedicated_entry_and_discards_an_epoch_change(self):
        context = self.context([phone(ACCOUNT), phone(ACCOUNT)])
        context.report.operation = 'daily'
        with self.assertRaises(AutomationError):
            observe_daily_messages(context)
        context.window.capture.assert_not_called()
        context.report.operation = OPERATION
        context.vision.confidence = .93
        with self.assertRaises(AutomationError):
            observe_daily_messages(context)
        context.window.capture.assert_not_called()
        context.vision.confidence = .65
        context.sleep.side_effect = lambda _: setattr(context.runner, 'input_epoch', 1)
        with self.assertRaises(InputInterrupted):
            observe_daily_messages(context)
        self.assertEqual(context.window.capture.call_count, 1)


class MessageCliTests(unittest.TestCase):
    def run_cli(self, frames, *, publication=None, foreground=True, wait_for_foreground=False,
                mode='messages', client_version='4.6.0', code=0):
        window = _Window(frames)
        if mode == 'odyssey':
            from autohsr.windows import Geometry

            height, width = frames[0].image.shape[:2]
            window.geometry = Geometry(0, 0, width, height)
            window.guard.return_value = window.geometry
        if not foreground:
            if wait_for_foreground:
                checks = count()

                def guard(*_):
                    if next(checks) == 0:
                        raise FocusLost('waiting for user handoff')
                    return window.geometry

                window.guard.side_effect = guard
            else:
                window.guard.side_effect = FocusLost('synthetic focus loss')
        original_save = Runner._save_run_report
        ticks = count(100., .01)
        clock = SimpleNamespace(monotonic=lambda: next(ticks))
        kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
        user32 = SimpleNamespace(GetAsyncKeyState=Mock(return_value=0),
                                 SendInput=Mock(side_effect=AssertionError('no native input')))
        output, logs = io.StringIO(), io.StringIO()

        def vision(floor):
            reader = window.vision(floor)
            reader.confidence = floor
            if mode == 'screen':
                reader.template = Vision.__new__(Vision).template
            return reader

        def publish(runner, directory, *args, **kwargs):
            if publication is not None:
                publication(runner, window, clock, user32)
            return original_save(runner, directory, *args, **kwargs)

        with TemporaryDirectory() as folder, ExitStack() as stack:
            root = Path(folder)
            if mode == 'odyssey':
                executable = root / 'StarRail.exe'
                executable.touch()
                (root / 'config.ini').write_text(f'[General]\ngame_version={client_version}\n', encoding='utf8')
                window.current_executable = Mock(return_value=executable)
            config = root / 'config.json'
            Settings(auto_launch=True, overlay_logs=True, battle=True, allow_stamina_spend=True,
                     ocr_confidence=.65 if mode == 'odyssey' else .93).save(config)
            original = config.read_bytes()
            for target, value in (
                    ('autohsr.app.ROOT', root), ('autohsr.app.time', clock),
                    ('autohsr.daily_message_observe.time', clock), ('autohsr.challenge_pages.time', clock),
                    ('autohsr.workflow_screen.time', clock),
                    ('autohsr.windows.kernel32', kernel), ('autohsr.windows.user32', user32),
                    ('autohsr.app.find_game', Mock(return_value=window)),
                    ('autohsr.app.Vision', Mock(side_effect=vision)),
                    ('autohsr.app.C.get_last_error', Mock(return_value=0)),
                    ('autohsr.app.threading.Thread', Mock()), ('autohsr.app.Runner._arm_hotkeys', Mock()),
                    ('autohsr.workflow_lease.require_workflow_access', Mock()),
                    ('autohsr.app.is_elevated', Mock(return_value=False))):
                stack.enter_context(patch(target, value))
            for target in ('autohsr.app.Runner._prepare_daily_game', 'autohsr.app.launch',
                           'autohsr.notify_runtime.hooks', 'autohsr.overlay.OverlayService',
                           'autohsr.recovery.BattleBudget', 'autohsr.du_reward_store.preflight',
                           'autohsr.du_archive_store.preflight', 'autohsr.currency_wars_weekly_reward_store.RewardStore'):
                stack.enter_context(patch(target, side_effect=AssertionError(target)))
            stack.enter_context(patch.object(Context, 'sleep', lambda ctx, _: ctx.checkpoint()))
            stack.enter_context(patch.object(Runner, '_save_run_report', publish))
            if wait_for_foreground:
                from autohsr.daily_observe import runner_for

                stack.enter_context(patch('autohsr.daily_observe.runner_for',
                                          lambda settings, emit, mode: runner_for(
                                              settings, emit, mode, wait_for_foreground=True)))
            stack.enter_context(redirect_stdout(output))
            stack.enter_context(redirect_stderr(logs))
            flags = ['--screen-test'] if mode == 'screen' else ['--daily-reward-observe', mode]
            self.assertEqual(main([*flags, '--config', str(config)]), code, output.getvalue() + logs.getvalue())
            report = json.loads(output.getvalue())
            directory = Path(report['run_dir'])
            if report['report_saved']:
                self.assertEqual(json.loads((directory / 'report.json').read_text(encoding='utf8')), report)
            self.assertFalse((directory / 'report.tmp').exists())
            self.assertFalse(list(directory.glob('*.png')))
            self.assertEqual(config.read_bytes(), original)
        self.assertEqual(report['operation'], {'messages': OPERATION, 'odyssey': 'daily_event_observe',
                                               'screen': 'screen_test'}[mode])
        self.assertNotIn('daily_reward_observe', report)
        self.assertEqual((report['stamina_limit'], report['stamina_spent'], report['stamina_pending']), (0, 0, 0))
        if mode == 'messages':
            self.assertFalse(report[OPERATION]['input_sent'])
        window.focus.assert_not_called()
        user32.SendInput.assert_not_called()
        for token in (ACCOUNT.text[4:], OTHER.text[4:], 'private_message_fixture'):
            self.assertNotIn(token, output.getvalue() + logs.getvalue())
        if code and mode == 'messages':
            self.assertNotIn('"status": "ok"', logs.getvalue())
        return report

    def test_cli_publishes_only_the_observed_view_and_anonymous_status(self):
        for state, frames in (
                ('phone_entry', [phone(ACCOUNT), phone(ACCOUNT)]),
                ('message_page', [panel(ACCOUNT, label('private_message_fixture', (.5, .4, .65, .43))),
                                  panel(ACCOUNT)])):
            with self.subTest(state=state):
                report = self.run_cli(frames)
                self.assertEqual(report[OPERATION][state], 'observed')
                self.assertEqual(report[OPERATION]['captures'], 2)
                self.assertTrue(report[OPERATION]['account_verified'])
                self.assertEqual(report[OPERATION]['reward_status'], 'unknown')

    def test_cli_publishes_agreed_reply_fields_and_revokes_them_on_late_stop(self):
        def frames():
            return [state_frame('options_two.png', ACCOUNT) for _ in range(2)]

        def press_f10(_runner, _window, _clock, user32):
            user32.GetAsyncKeyState.return_value = 1

        observed = self.run_cli(frames())
        self.assertEqual(observed[OPERATION]['reply_options'], 2)
        stopped = self.run_cli(frames(), code=1, publication=press_f10)
        self.assertEqual(stopped['status'], 'stopped')
        self.assertEqual({key: stopped[OPERATION][key] for key in unknown_panel_state()}, unknown_panel_state())

    def test_cli_background_and_mixed_pages_keep_unknown(self):
        failed = self.run_cli([], foreground=False, code=1)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed[OPERATION]['captures'], 0)
        partial = self.run_cli([phone(ACCOUNT), panel(ACCOUNT)], code=1)
        self.assertEqual(partial['status'], 'partial')
        self.assertEqual(partial[OPERATION]['captures'], MAX_CAPTURES)
        self.assertEqual(partial[OPERATION]['message_page'], 'unknown')

    def test_publication_rejects_focus_epoch_staleness_and_f10(self):
        def interrupt(mode):
            def change(runner, window, clock, user32):
                if mode == 'focus':
                    window.guard.side_effect = FocusLost('synthetic focus loss')
                elif mode == 'epoch':
                    runner.input_epoch += 1
                elif mode == 'stale':
                    clock.monotonic = lambda: 200.
                elif mode == 'window':
                    window.current_window_key.return_value = 'different-window'
                else:
                    user32.GetAsyncKeyState.return_value = 1
            return change

        for mode in ('focus', 'epoch', 'stale', 'f10', 'window'):
            with self.subTest(mode=mode):
                report = self.run_cli([phone(ACCOUNT), phone(ACCOUNT)], publication=interrupt(mode), code=1)
                self.assertEqual(report['status'], 'stopped' if mode == 'f10' else 'partial')
                self.assertEqual(report['failure_task'], OPERATION)
                self.assertEqual(report[OPERATION]['phone_entry'], 'unknown')
                self.assertFalse(report[OPERATION]['account_verified'])
                self.assertEqual(report[OPERATION]['captures'], 2)

    def test_sharing_retry_rechecks_epoch_before_publishing(self):
        original_replace = Path.replace
        state = {}

        def remember(runner, *_):
            state['runner'] = runner

        def replace_once(source, target):
            if source.name == 'report.tmp' and 'retried' not in state:
                state['retried'] = True
                state['runner'].input_epoch += 1
                raise PermissionError('synthetic sharing violation')
            return original_replace(source, target)

        with patch.object(Path, 'replace', replace_once):
            report = self.run_cli([phone(ACCOUNT), phone(ACCOUNT)], publication=remember, code=1)
        self.assertTrue(state['retried'])
        self.assertTrue(report['report_saved'])
        self.assertEqual(report[OPERATION]['phone_entry'], 'unknown')
        self.assertEqual(report['status'], 'partial')

    def test_report_write_failure_clears_observation_in_the_final_result(self):
        original_replace = Path.replace

        def fail_report(source, target):
            if source.name == 'report.tmp':
                raise OSError('private_message_fixture')
            return original_replace(source, target)

        with patch.object(Path, 'replace', fail_report):
            report = self.run_cli([phone(ACCOUNT), phone(ACCOUNT)], code=1)
        self.assertFalse(report['report_saved'])
        self.assertFalse(report[OPERATION]['account_verified'])
        self.assertEqual(report[OPERATION]['phone_entry'], 'unknown')
        self.assertEqual(report[OPERATION]['captures'], 2)
        self.assertEqual(report['status'], 'failed')

    def test_generic_input_and_resource_plan_are_refused(self):
        runner = Runner(Settings(), operation=OPERATION)
        context = Context(runner, None, None)
        for action in (lambda: context.key('p'), lambda: context.click(None, (.5, .5)),
                       lambda: context.drag(None, (.4, .4), (.5, .5)), lambda: context.scroll(1),
                       lambda: context.move(None, (.5, .5))):
            with self.assertRaisesRegex(AutomationError, '只允许观察'):
                action()
        for options in (dict(new_battle_run=True), dict(use_power_plan=True), dict(weekly_plan={})):
            with self.assertRaises(ValueError):
                Runner(Settings(), operation=OPERATION, **options)
        self.assertNotIn(OPERATION, RunReport().to_dict())

    def test_desktop_handoff_can_wait_for_the_user_without_activating_the_window(self):
        report = self.run_cli([phone(ACCOUNT), phone(ACCOUNT)], foreground=False, wait_for_foreground=True)
        self.assertEqual(report[OPERATION]['phone_entry'], 'observed')
        with self.assertRaises(ValueError):
            Runner(Settings(), operation='daily', observation_wait_for_foreground=True)

    @staticmethod
    def odyssey():
        from autohsr.tests.test_daily_event_pages import _odyssey

        scene = _odyssey()
        scene.tokens.append(ACCOUNT)
        return scene

    def test_odyssey_cli_publishes_confirmed_days_even_when_other_days_are_unknown(self):
        report = self.run_cli([self.odyssey(), self.odyssey()], mode='odyssey', code=1)
        record = report['daily_event_observe']
        self.assertEqual(report['status'], 'partial')
        self.assertTrue(record['page_verified'])
        self.assertEqual(record['client_version'], '4.6.0')
        self.assertEqual(record['claimable_days'], [5, 6, 7])
        self.assertEqual(record['unknown_days'], [1, 2, 3])
        self.assertNotIn('executable', record)

    def test_screen_test_cli_is_read_only_and_supports_explicit_desktop_handoff(self):
        frames = [phone(ACCOUNT), phone(ACCOUNT)]
        for handoff in (False, True):
            with self.subTest(handoff=handoff):
                report = self.run_cli(frames, mode='screen', foreground=not handoff, wait_for_foreground=handoff)
                self.assertEqual(report['screen_test'], dict(schema=1, page='phone', page_verified=True,
                                                            account_verified=True, input_sent=False))
        self.assertNotIn('screen_test', RunReport().to_dict())

    def test_screen_test_cli_revokes_result_on_late_focus_loss(self):
        def lose_focus(runner, window, clock, user32):
            window.guard.side_effect = FocusLost('synthetic late focus loss')

        report = self.run_cli([phone(ACCOUNT), phone(ACCOUNT)], mode='screen', publication=lose_focus, code=1)
        self.assertEqual(report['screen_test'], dict(schema=1, page='unknown', page_verified=False,
                                                    account_verified=False, input_sent=False))

    def test_screen_test_cli_rejects_conflicting_arguments_before_reading_settings(self):
        for extra in (['--reward-only'], ['--stamina', '20'], ['--daily-reward-observe', 'messages'],
                      ['--screen-test']):
            with self.subTest(extra=extra), redirect_stderr(io.StringIO()), patch.object(
                    Settings, 'load', side_effect=AssertionError('invalid flags reached config')):
                with self.assertRaises(SystemExit) as error:
                    main(['--screen-test', *extra])
                self.assertEqual(error.exception.code, 2)

    def test_odyssey_cli_version_mismatch_and_publication_focus_loss_keep_days_unknown(self):
        def lose_focus(runner, window, clock, user32):
            window.guard.side_effect = FocusLost('synthetic late focus loss')

        for version, publication in (('4.7.0', None), ('4.6.0', lose_focus)):
            with self.subTest(version=version):
                report = self.run_cli([self.odyssey(), self.odyssey()], mode='odyssey',
                                      client_version=version, publication=publication, code=1)
                record = report['daily_event_observe']
                self.assertFalse(record['page_verified'])
                self.assertEqual(record['claimable_days'], [])
                self.assertEqual(record['client_version'], version)
