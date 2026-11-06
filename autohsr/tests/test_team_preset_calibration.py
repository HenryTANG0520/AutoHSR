"""Exercise the formal calibration CLI and dedicated Context input on a fake window."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from hashlib import sha256
import io
from itertools import count
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from autohsr.__main__ import main
from autohsr import team_preset_calibration as runtime
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, EmptyCapture, FocusLost, RunReport, Scene, Token
from autohsr.policy import guard_click
from autohsr.team_preset_calibration import TeamPresetCalibration
from autohsr.tests.test_du_team import fixture
from autohsr.windows import Geometry


OPERATION = 'team_preset_calibration'
ACCOUNT = Token('UID:100000000', .99, (.018, .957, .106, .985))
OTHER = Token('UID:200000000', .99, (.018, .957, .106, .985))


def phone(*extra, uid=ACCOUNT):
    scene = fixture('phone_mail_icon')
    scene.tokens.extend((uid, *extra))
    return scene


def unknown(*extra, uid=ACCOUNT):
    return Scene([uid, *extra], phone().image)


def calibrate(directory, frames, *, before_hook=None, after_hook=None, at_entry=None,
              before_publish=None, foreground=True, confidence=.65):
    config = directory / 'config.json'
    Settings(overlay_logs=True, ocr_confidence=confidence).save(config)
    config_bytes = config.read_bytes()
    entries = iter(frames)
    state = SimpleNamespace(context=None, scene=None, sent=[], collection=None)
    geometry = Geometry(10, 20, 1920, 1080)
    original_entry = Context.team_preset_entry_input
    original_publish = TeamPresetCalibration.save_report

    def capture():
        state.scene = next(entries, EmptyCapture('fixture blank'))
        if isinstance(state.scene, Exception):
            raise state.scene
        return state.scene.image.copy(), geometry

    def vision_at(collection):
        state.collection = collection

        def read(image, current_geometry):
            return Scene([token for token in state.scene.tokens if token.score >= collection], image, current_geometry)

        return SimpleNamespace(read=read)

    def entry(context, scene):
        state.context = context
        if at_entry:
            at_entry(state)
        return original_entry(context, scene)

    def click(x, y, expected, *, before_submit):
        if before_hook:
            before_hook(state)
        before_submit()
        state.sent.append((x, y, expected))
        if after_hook:
            after_hook(state)

    def publish(reader, temporary, write_report):
        if before_publish:
            before_publish(reader)
        return original_publish(reader, temporary, write_report)

    window = Mock(hwnd=11, capture=Mock(side_effect=capture), emergency_pressed=Mock(return_value=False),
                  current_window_key=Mock(return_value='fixture-window'))
    window.click.side_effect = click
    if not foreground:
        window.guard.side_effect = FocusLost('fixture background')
    kernel = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
    clock = SimpleNamespace(monotonic=lambda ticks=count(1000., .01): next(ticks))
    output = io.StringIO()
    with ExitStack() as stack:
        stack.enter_context(patch('autohsr.app.ROOT', directory))
        stack.enter_context(patch('autohsr.app.C.get_last_error', return_value=0))
        stack.enter_context(patch('autohsr.app.threading.Thread'))
        stack.enter_context(patch('autohsr.app.is_elevated', return_value=False))
        stack.enter_context(patch('autohsr.app.find_game', return_value=window))
        stack.enter_context(patch('autohsr.app.Vision', side_effect=vision_at))
        stack.enter_context(patch('autohsr.windows.kernel32', kernel))
        stack.enter_context(patch('autohsr.workflow_lease.NAME', f'Local\\AutoHSR.TeamPresetQA.{uuid4().hex}'))
        stack.enter_context(patch('autohsr.notify_runtime.hooks', side_effect=AssertionError('no notifications')))
        stack.enter_context(patch('autohsr.overlay.OverlayService', side_effect=AssertionError('no overlay')))
        stack.enter_context(patch.object(Runner, '_arm_hotkeys'))
        stack.enter_context(patch.object(Runner, '_prepare_daily_game', side_effect=AssertionError('no startup')))
        stack.enter_context(patch.object(Context, 'sleep', lambda context, seconds: context.checkpoint()))
        stack.enter_context(patch.object(Context, 'team_preset_entry_input', entry))
        stack.enter_context(patch.object(TeamPresetCalibration, 'save_report', publish))
        for module in ('app', 'challenge_pages', 'team_preset_calibration'):
            stack.enter_context(patch(f'autohsr.{module}.time', clock))
        stack.enter_context(redirect_stdout(output))
        stack.enter_context(redirect_stderr(io.StringIO()))
        code = main(['--team-preset-calibration', '--config', str(config)])
    report = json.loads(output.getvalue())
    if report['report_saved']:
        saved = Path(report['run_dir']) / 'report.json'
        assert json.loads(saved.read_text(encoding='utf-8')) == report
    assert config.read_bytes() == config_bytes
    return code, report, window, state


class TeamPresetCalibrationTests(unittest.TestCase):
    def run_calibration(self, frames, *, expected_code=1, **kwargs):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        code, report, window, state = calibrate(Path(folder.name), frames, **kwargs)
        self.assertEqual((code, report['operation']), (expected_code, OPERATION), report['error'])
        self.assertEqual(report['stamina_spent'], 0)
        self.assertEqual(report['team_selections'], [])
        self.assertFalse(report['team_preset_calibration']['preset_members_verified'])
        for method in (window.focus, window.key, window.move, window.scroll, window.drag, window.send):
            method.assert_not_called()
        return report, window, state

    def test_live_phone_fixture_authorizes_one_native_click_and_keeps_arrival_unknown(self):
        report, window, state = self.run_calibration([phone(), phone(), phone(), *[unknown() for _ in range(6)]])
        receipt = report['team_preset_calibration']
        self.assertEqual((report['status'], receipt['input_status'], receipt['destination_status']),
                         ('partial', 'sent', 'unknown'), report['error'])
        window.click.assert_called_once()
        self.assertEqual(len(state.sent), 1)
        x, y, geometry = state.sent[0]
        self.assertAlmostEqual(x, .6987, places=4)
        self.assertAlmostEqual(y, .8574, places=4)
        self.assertEqual(receipt['client_size'], [geometry.width, geometry.height])
        frames = [*receipt['before_frames'], receipt['submission_frame'], *receipt['after_frames']]
        self.assertEqual([frame['capture_sequence'] for frame in frames], [1, 2, 3, 8, 9])
        directory = Path(report['run_dir'])
        for frame in frames:
            self.assertEqual(sha256((directory / frame['screenshot']).read_bytes()).hexdigest(), frame['sha256'])
        intent = (directory / receipt['intent']).read_text(encoding='utf-8')
        self.assertEqual(json.loads(intent)['sources'], receipt['before_frames'])
        self.assertEqual(json.loads(intent)['status'], 'pending')
        self.assertNotIn('UID', intent)
        self.assertNotIn('100000000', json.dumps(report))

    def test_phone_still_visible_and_unknown_feedback_never_retry(self):
        frames = [phone() for _ in range(9)]
        report, window, state = self.run_calibration(frames)
        receipt = report['team_preset_calibration']
        self.assertEqual(receipt['input_status'], 'sent')
        self.assertEqual(receipt['destination_status'], 'unknown')
        self.assertEqual([frame['capture_sequence'] for frame in receipt['after_frames']], [8, 9])
        self.assertTrue(all(frame['phone_team_entry'] for frame in receipt['after_frames']))
        self.assertEqual(window.capture.call_count, 9)
        self.assertEqual(len(state.sent), 1)

    def test_wrong_page_or_weak_duplicate_disallows_entrance(self):
        candidate = Token('编队', .70, (.31, .32, .34, .35))
        cases = ([unknown(Token('预设编队', .99, (.02, .03, .09, .06)))],
                 [phone(candidate), phone(candidate)],
                 [phone(), EmptyCapture('gap'), phone()])
        for frames in cases:
            with self.subTest(frames=len(frames)):
                report, window, state = self.run_calibration(frames, confidence=.93)
                self.assertEqual(state.collection, .65)
                self.assertEqual(report['team_preset_calibration']['input_status'], 'not_sent')
                self.assertNotIn('intent', report['team_preset_calibration'])
                window.click.assert_not_called()

    def test_after_intent_reacquires_current_page_and_original_account(self):
        blockers = ('提示', '列车补给', '获得物品', '补充开拓力')
        contrasts = [unknown(), phone(uid=OTHER),
                     *(phone(Token(label, .72, (.4, .3, .6, .4))) for label in blockers)]
        for changed in contrasts:
            with self.subTest(tokens=len(changed.tokens)):
                report, window, state = self.run_calibration([phone(), phone(), changed], confidence=.93)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['team_preset_calibration']['input_status'], 'not_sent')
                self.assertIn('intent', report['team_preset_calibration'])
                window.click.assert_not_called()

    def test_background_and_send_time_epoch_change_block_before_native_submission(self):
        report, window, state = self.run_calibration([], foreground=False)
        self.assertEqual(report['team_preset_calibration']['input_status'], 'not_sent')
        window.capture.assert_not_called()
        window.click.assert_not_called()

        def new_epoch(state):
            state.context.runner.input_epoch += 1

        def other_window(state):
            state.context.window.current_window_key.return_value = 'fixture-window-reused'

        def f10(state):
            state.context.window.emergency_pressed.return_value = True

        for hook in (new_epoch, other_window, f10):
            with self.subTest(hook=hook.__name__):
                report, _, state = self.run_calibration([phone(), phone(), phone()], before_hook=hook)
                self.assertEqual(report['team_preset_calibration']['input_status'], 'not_sent')
                self.assertEqual(state.sent, [])

    def test_tampered_intent_and_native_rejection_preserve_distinct_states(self):
        def tamper(state):
            intent = state.context.team_preset_reader.intent_path
            intent.write_bytes(b'{}')

        report, window, state = self.run_calibration([phone(), phone(), phone()], at_entry=tamper)
        self.assertEqual(report['team_preset_calibration']['input_status'], 'not_sent')
        window.click.assert_not_called()

        def rejected(state):
            raise AutomationError('fixture native rejection')

        report, window, state = self.run_calibration([phone(), phone(), phone()], after_hook=rejected)
        self.assertEqual(report['status'], 'partial')
        self.assertEqual(report['team_preset_calibration']['input_status'], 'unconfirmed')
        window.click.assert_called_once()
        self.assertEqual(len(state.sent), 1)

    def test_current_account_changes_after_click_without_publishing_feedback(self):
        report, window, state = self.run_calibration([phone(), phone(), phone(), unknown(uid=OTHER)])
        receipt = report['team_preset_calibration']
        self.assertEqual((report['status'], receipt['input_status'], receipt['after_frames']), ('partial', 'sent', []))
        self.assertEqual(receipt['destination_status'], 'unknown')
        window.click.assert_called_once()

    @staticmethod
    def ordinary_team():
        from autohsr.tests.test_team_calibration_destination import normal_team_scene
        scene = normal_team_scene()
        scene.tokens.append(ACCOUNT)
        return scene

    def test_ordinary_team_arrival_and_existing_page_have_distinct_input_scope(self):
        for existing in (False, True):
            with self.subTest(existing=existing):
                frames = [self.ordinary_team(), self.ordinary_team()]
                if not existing:
                    frames[:0] = [phone(), phone(), phone(), EmptyCapture('opening')]
                report, window, state = self.run_calibration(frames, expected_code=0)
                receipt = report['team_preset_calibration']
                self.assertEqual(receipt['destination_status'], 'team_page_verified')
                self.assertEqual(receipt['input_status'], 'not_sent' if existing else 'sent')
                self.assertEqual(receipt['scope'], 'observe_current_team' if existing else 'open_team_from_phone')
                self.assertEqual(len(state.sent), 0 if existing else 1)
                self.assertEqual(window.click.call_count, 0 if existing else 1)
                self.assertEqual(len(receipt['after_frames']), 2)
                self.assertTrue(all(frame['team_page'] for frame in receipt['after_frames']))
                self.assertNotIn('fixture-window', json.dumps(report))

    def test_failed_report_recheck_keeps_input_and_withdraws_arrival(self):
        def tamper(reader):
            source = reader.directory / reader.record['after_frames'][-1]['screenshot']
            source.write_bytes(b'changed')

        def change_epoch(reader):
            reader.c.runner.input_epoch += 1

        def expire_first_frame(reader):
            first, last = reader.arrival

            def final_guard():
                runtime.time.monotonic = lambda: (first.captured_at + last.captured_at) / 2 + 8
                return 'fixture-window'

            reader.window.current_window_key.side_effect = final_guard

        for change in (tamper, change_epoch, expire_first_frame):
            with self.subTest(change=change.__name__):
                frames = [phone(), phone(), phone(), self.ordinary_team(), self.ordinary_team()]
                report, window, state = self.run_calibration(frames, before_publish=change)
                receipt = report['team_preset_calibration']
                self.assertEqual((report['status'], receipt['input_status'], receipt['destination_status']),
                                 ('partial', 'sent', 'unknown'))
                self.assertIn('到页报告未核实', report['error'])
                window.click.assert_called_once()

    def test_generic_context_inputs_and_daily_phone_still_reject_team_action(self):
        scene = phone()
        target = scene.find('编队', exact=True)
        with self.assertRaises(AutomationError):
            guard_click(scene, target)
        window = Mock()
        settings = Settings()
        daily = Context(SimpleNamespace(settings=settings, report=RunReport()), window, None)
        with self.assertRaises(AutomationError):
            daily.team_preset_entry_input(scene)
        scoped = Context(SimpleNamespace(settings=settings, report=RunReport(operation=OPERATION)), window, None)
        for call in (lambda: scoped.click(scene, target), lambda: scoped.key('esc'),
                     lambda: scoped.move(scene, target.center), lambda: scoped.scroll(1),
                     lambda: scoped.drag(scene, target.center, target.center)):
            with self.assertRaises(AutomationError):
                call()
        self.assertEqual(window.mock_calls, [])

    def test_cli_rejects_other_modes_and_options_before_reading_config(self):
        for flags in (['--run'], ['--challenge-prepare'], ['--launch'], ['--no-notify'], ['--new-battle-run']):
            with (self.subTest(flags=flags), patch('autohsr.__main__.Settings.load') as load,
                  redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as stopped):
                main(['--team-preset-calibration', *flags])
            self.assertEqual(stopped.exception.code, 2)
            load.assert_not_called()
