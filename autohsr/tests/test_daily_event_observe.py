"""Exercise the formal Context with fake native windows and real local version files."""
from dataclasses import asdict, replace
from itertools import count
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2

from autohsr.app import Context
from autohsr.currency_wars_identity import UID_COUNTEREVIDENCE
from autohsr.daily_event_observe import OPERATION, DailyEventObserver, initial_record
from autohsr.models import AutomationError, EmptyCapture, FocusLost, Scene, Stopped, Token
from autohsr.storage import replace_file
from autohsr.tests.test_daily_event_pages import _odyssey, _paint, _phone
from autohsr.windows import Geometry


ACCOUNT = Token('UID:135792468', .99, (.014, .951, .111, .982))
OTHER = Token('UID:246813579', .99, ACCOUNT.box)
CENTERS = ((.551, .551), (.638, .551), (.725, .551),
           (.551, .774), (.638, .774), (.725, .774), (.829, .774))


def _account(scene, account=ACCOUNT):
    if account is not None:
        scene.tokens.append(account)
    return scene


def _phone_frame():
    scene = _account(_phone())
    scene.image = cv2.resize(scene.image, (960, 540))
    return scene


def _settled():
    scene = _odyssey()
    scene.tokens = [token for token in scene.tokens if token.text not in ('领取', '已领取')]
    for x, y in CENTERS:
        _paint(scene.image, (x - .040, y - .019, x + .040, y + .019), (72, 98, 115))
        scene.tokens.append(Token('已领取', .94, (x - .016, y - .010, x + .016, y + .010)))
    return _account(scene)


class FakeWindow:
    confidence = .65

    def __init__(self, frames, executable):
        self.frames = iter(frames)
        self.executable = executable
        self.geometry = Geometry(0, 0, 960, 540)
        self.identity = 'synthetic-private-window-key'
        self.foreground = True
        self.capture_calls = 0
        self.emergency_pressed = Mock(return_value=False)
        for name in ('focus', 'send', 'click', 'key', 'move', 'drag', 'scroll'):
            setattr(self, name, Mock(side_effect=AssertionError('an observation must have zero input')))

    def guard(self, expected=None):
        if not self.foreground:
            raise FocusLost('synthetic focus loss')
        if expected is not None and expected != self.geometry:
            raise AutomationError('synthetic geometry change')
        return self.geometry

    def current_window_key(self):
        self.guard()
        return self.identity

    def current_executable(self):
        self.guard()
        return str(self.executable)

    def capture(self):
        self.capture_calls += 1
        self.frame = next(self.frames, None)
        if self.frame is None:
            raise EmptyCapture('no further frame')
        return self.frame.image, self.geometry

    def read(self, image, geometry):
        return Scene(list(self.frame.tokens), image, geometry, field_reads=dict(self.frame.field_reads))


class DailyEventObserverTests(unittest.TestCase):
    def setUp(self):
        ticks = count(100., .001)
        clock = SimpleNamespace(monotonic=lambda: next(ticks))
        for module in ('autohsr.app', 'autohsr.workflow_screen', 'autohsr.challenge_pages'):
            self.enterContext(patch(module + '.time', clock))
        self.root = Path(self.enterContext(TemporaryDirectory())).resolve()
        self.executable = self.install('synthetic-live-install', '4.6.0')
        self.config = self.executable.with_name('config.ini')
        self.configured_path = self.install('configured-but-not-current', '4.7.0')

    def install(self, name, version):
        directory = self.root / name
        directory.mkdir()
        path = directory / 'StarRail.exe'
        path.write_bytes(b'synthetic executable, never launched')
        path.with_name('config.ini').write_text(f'[General]\ngame_version={version}\n', encoding='utf8')
        return path

    def observer(self, frames):
        runner = SimpleNamespace(settings=SimpleNamespace(ocr_confidence=.65, game_path=str(self.configured_path)),
                                 report=SimpleNamespace(operation=OPERATION, daily_event_observe=initial_record(),
                                                        status='partial', error='', failure_task='', results=[]),
                                 stop_requested=False, input_epoch=2, _foreground_only=True, _challenge_read_only=True,
                                 checkpoint=Mock(), log=Mock(), wait_for_focus=Mock())
        runner.stop = Mock(side_effect=lambda: setattr(runner, 'stop_requested', True))
        window = FakeWindow(frames, self.executable)
        context = Context(runner, window, window)
        context.sleep = Mock(side_effect=lambda _seconds: context.checkpoint())
        context.evidence = Mock(side_effect=AssertionError('no raw activity screenshot should be exported'))
        self.addCleanup(self.assert_no_input, window, runner, context)
        return DailyEventObserver(context), window

    def assert_no_input(self, window, runner, context):
        runner.wait_for_focus.assert_not_called()
        context.evidence.assert_not_called()
        for name in ('focus', 'send', 'click', 'key', 'move', 'drag', 'scroll'):
            getattr(window, name).assert_not_called()

    def run_observer(self, observer):
        result = observer.run()
        self.assertEqual(result.task, OPERATION)
        report = observer.context.report
        report.results.append(result)
        report.status = 'success' if result.status == 'ok' else result.status
        self.assertIs(report.daily_event_observe, observer.record)
        return result

    def save(self, observer):
        temporary = self.root / 'report.tmp'
        report = observer.context.report

        def write_report():
            payload = json.dumps(dict(status=report.status, error=report.error, failure_task=report.failure_task,
                                      daily_event_observe=report.daily_event_observe,
                                      results=[asdict(row) for row in report.results]),
                                 ensure_ascii=False, indent=2)
            temporary.write_text(payload, encoding='utf8')
            return payload

        observer.save_verified_report(temporary, write_report)
        raw = temporary.with_name('report.json').read_text(encoding='utf8')
        for private in (str(self.executable.parent), 'synthetic-live-install', 'synthetic-private-window-key',
                        ACCOUNT.text, OTHER.text, 'account_key', 'sha256', 'config.ini', 'StarRail.exe'):
            self.assertNotIn(private, raw)
        return json.loads(raw)

    def test_two_fresh_phone_frames_report_the_actual_process_version(self):
        observer, window = self.observer([_phone_frame(), _phone_frame()])
        self.assertEqual(self.run_observer(observer).status, 'ok')
        self.assertEqual(window.capture_calls, 2)
        self.assertEqual(observer.record, dict(initial_record(), client_version='4.6.0', page='phone_entry',
                                               page_verified=True, account_verified=True))
        self.assertEqual(self.save(observer)['status'], 'success')

    def test_double_frame_intersection_keeps_conflicting_or_missing_cards_unknown(self):
        first, second = _account(_odyssey()), _account(_odyssey())
        second.tokens = [replace(token, text='已领取') if token.text == '领取' and .60 < token.center[0] < .68 else token
                         for token in second.tokens if token.text != '领取' or not .70 < token.center[0] < .76]
        _paint(second.image, (.600, .754, .677, .793), (72, 98, 115))
        observer, window = self.observer([first, second])
        self.assertEqual(self.run_observer(observer).status, 'partial')
        self.assertTrue(observer.record['page_verified'])
        self.assertEqual(observer.record['claimable_state'], 'available')
        self.assertEqual(observer.record['claimable_days'], [7])
        self.assertEqual(observer.record['claimed_days'], [4])
        self.assertEqual(observer.record['unknown_days'], [1, 2, 3, 5, 6])
        self.assertEqual(window.capture_calls, 2)
        self.assertEqual(self.save(observer)['daily_event_observe'], observer.record)

    def test_zero_available_requires_all_seven_claimed_in_both_frames(self):
        observer, _ = self.observer([_settled(), _settled()])
        self.assertEqual(self.run_observer(observer).status, 'ok')
        self.assertEqual(observer.record['claimable_state'], 'none')
        self.assertEqual(observer.record['claimed_days'], list(range(1, 8)))
        incomplete = _settled()
        incomplete.tokens.pop(-2)
        observer, _ = self.observer([_settled(), incomplete])
        self.assertEqual(self.run_observer(observer).status, 'partial')
        self.assertEqual(observer.record['claimable_state'], 'unknown')
        self.assertEqual(observer.record['unknown_days'], [7])

    def test_page_transition_and_reward_popup_do_not_infer_arrival_or_delivery(self):
        popup = _account(_odyssey())
        popup.tokens.append(Token('获得物品', .99, (.473, .144, .527, .179)))
        for second in (_phone_frame(), popup):
            with self.subTest(phone=second is not popup):
                observer, _ = self.observer([_account(_odyssey()), second])
                result = self.run_observer(observer)
                self.assertNotEqual(result.status, 'ok')
                self.assertEqual(observer.record, dict(initial_record(), client_version='4.6.0'))

    def test_conflicting_or_missing_uid_and_shared_pixels_fail_closed(self):
        conflict = _account(_odyssey())
        conflict.field_reads[UID_COUNTEREVIDENCE] = (replace(OTHER, score=.72),)
        cases = (_account(_odyssey(), OTHER), _account(_odyssey(), None), conflict, _account(_odyssey()))
        for index, second in enumerate(cases):
            with self.subTest(index=index):
                first = _account(_odyssey())
                if index == len(cases) - 1:
                    second.image = first.image
                observer, _ = self.observer([first, second])
                self.assertEqual(self.run_observer(observer).status, 'failed')
                self.assertFalse(observer.record['page_verified'])

    def test_unsupported_installation_does_not_capture_and_drift_stops_pair(self):
        observer, window = self.observer([_phone_frame(), _phone_frame()])
        window.executable = self.configured_path
        self.assertEqual(self.run_observer(observer).status, 'failed')
        self.assertEqual(observer.record['client_version'], '4.7.0')
        self.assertEqual(window.capture_calls, 0)
        observer, window = self.observer([_phone_frame(), _phone_frame()])
        observer.context.sleep.side_effect = lambda _seconds: self.config.write_text(
            '[General]\ngame_version=4.7.0\n', encoding='utf8')
        self.assertEqual(self.run_observer(observer).status, 'failed')
        self.assertEqual(window.capture_calls, 1)
        self.assertFalse(observer.record['page_verified'])

    def test_late_version_focus_window_epoch_or_time_revokes_verified_partial(self):
        for failure in ('version', 'focus', 'window', 'epoch', 'time', 'readout'):
            with self.subTest(failure=failure):
                self.config.write_text('[General]\ngame_version=4.6.0\n', encoding='utf8')
                observer, window = self.observer([_account(_odyssey()), _account(_odyssey())])
                self.assertEqual(self.run_observer(observer).status, 'partial')
                self.assertTrue(observer.record['page_verified'])
                if failure == 'version':
                    self.config.write_text('[General]\ngame_version=4.7.0\n', encoding='utf8')
                elif failure == 'focus':
                    window.foreground = False
                elif failure == 'window':
                    window.identity = 'different'
                elif failure == 'epoch':
                    observer.context.runner.input_epoch += 1
                elif failure == 'readout':
                    observer.context.last_scene.tokens = [
                        token for token in observer.context.last_scene.tokens if token.text != '领取']
                if failure == 'time':
                    now = observer.context.last_scene.captured_at + 9
                    with patch('autohsr.workflow_screen.time.monotonic', return_value=now):
                        report = self.save(observer)
                else:
                    report = self.save(observer)
                self.assertEqual(report['status'], 'failed')
                self.assertEqual(report['results'][-1]['status'], 'failed')
                self.assertEqual(report['daily_event_observe'], dict(initial_record(), client_version='4.6.0'))

    def test_f10_at_publication_revokes_result_and_sets_native_stop(self):
        observer, window = self.observer([_phone_frame(), _phone_frame()])
        self.run_observer(observer)
        window.emergency_pressed.return_value = True
        report = self.save(observer)
        self.assertEqual(report['status'], 'stopped')
        self.assertEqual(report['results'][-1]['status'], 'stopped')
        self.assertEqual(report['daily_event_observe'], dict(initial_record(), client_version='4.6.0'))
        observer.context.runner.stop.assert_called_once()

    def test_source_record_and_staged_bytes_are_both_checked(self):
        observer, _ = self.observer([_phone_frame(), _phone_frame()])
        self.assertEqual(self.run_observer(observer).status, 'ok')
        observer.context.report.daily_event_observe = {'raw': ACCOUNT.text}
        self.assertFalse(self.save(observer)['daily_event_observe']['page_verified'])
        observer, _ = self.observer([_phone_frame(), _phone_frame()])
        self.assertEqual(self.run_observer(observer).status, 'ok')

        def tamper(source, destination, **options):
            if 'attempt_scope' in options:
                source.write_bytes(b'\xffexternal-bytes')
            return replace_file(source, destination, **options)

        with patch('autohsr.daily_event_observe.replace_file', side_effect=tamper):
            saved = self.save(observer)
        self.assertEqual(saved['status'], 'failed')
        self.assertFalse(saved['daily_event_observe']['page_verified'])

    def test_installed_source_is_held_at_replace_and_output_error_propagates(self):
        observer, _ = self.observer([_account(_odyssey()), _account(_odyssey())])
        self.run_observer(observer)
        native_replace = Path.replace
        checked = []

        def replace_while_held(temporary, target):
            with self.assertRaises(PermissionError):
                with self.config.open('ab'):
                    pass
            checked.append(True)
            return native_replace(temporary, target)

        with patch.object(Path, 'replace', new=replace_while_held):
            self.assertTrue(self.save(observer)['daily_event_observe']['page_verified'])
        self.assertEqual(checked, [True])
        with self.config.open('ab'):
            pass
        with patch('autohsr.daily_event_observe.replace_file', side_effect=OSError('synthetic report I/O')):
            with self.assertRaisesRegex(OSError, 'synthetic report I/O'):
                self.save(observer)

    def test_runner_stop_during_first_pair_propagates_without_positive_record(self):
        observer, _ = self.observer([_phone_frame(), _phone_frame()])
        observer.context.sleep.side_effect = Stopped('opaque internal reason')
        with self.assertRaisesRegex(Stopped, '活动观察已停止'):
            observer.run()
        self.assertFalse(observer.record['page_verified'])


if __name__ == '__main__':
    unittest.main()
