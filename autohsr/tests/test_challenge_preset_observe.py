"""Exercise the formal preset observer through Runner, Context and a fake window."""

from contextlib import ExitStack, redirect_stderr, redirect_stdout
from hashlib import sha256
from io import StringIO
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, EmptyCapture, FocusLost, RunReport, Scene, Token
from autohsr.vision import Vision
from autohsr.windows import GameWindow, Geometry
from autohsr.workflow_identity import INPUT_METHODS


FLAG = '--challenge-preset-observe'
OPERATION = 'challenge_preset_observe'
MODE = 'memory_of_chaos'
GEOMETRY = Geometry(10, 20, 960, 540)
UID = Token('UID:135792468', .99, (.018, .957, .106, .985))
OTHER_UID = Token('UID:246813579', .99, (.018, .957, .106, .985))
WEAK_UID = Token(OTHER_UID.text, .72, OTHER_UID.box)
PAGES = (None, 'role_list', 'preset_list')


def frame(tab='preset_list', *, accounts=(UID,)):
    marker = PAGES.index(tab)
    pixels = np.full((GEOMETRY.height, GEOMETRY.width, 3), marker, dtype=np.uint8)
    pixels[GEOMETRY.height // 2:] = 120
    return Scene(list(accounts), pixels)


def empty_teams():
    return [[dict(position=position, occupancy='empty') for position in range(1, 5)] for _ in range(2)]


def read_page(scene, *_args, **_kwargs):
    tab = PAGES[int(scene.image[0, 0, 0])]
    if tab is None:
        return None
    rows = []
    if tab == 'preset_list':
        slots = [dict(position=position, level=dict(value=80), portrait=None) for position in range(1, 5)]
        rows.append(dict(name=dict(value='哈哈哈哈'), slots=slots))
    return dict(mode=MODE, level=10, tab=tab, anchors={}, setup_slots=empty_teams(), rows=rows)


def compare_pages(first, second):
    if first != second:
        return None
    presets = []
    for row in second['rows']:
        slots = [dict(position=slot['position'], visible_level=slot['level']['value'],
                      portrait_asset_id=None, portrait_name=None) for slot in row['slots']]
        presets.append(dict(name=row['name']['value'], slots=slots))
    return dict(mode=MODE, level=10, tab=second['tab'], visible_presets=presets,
                setup_slots=empty_teams(), eight_slots_empty=True)


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        self.now += .001
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class ChallengePresetObserveTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.config = self.root / 'config.json'
        self.game = str(self.root / 'override' / 'StarRail.exe')
        Settings(ocr_confidence=.93, overlay_logs=True, battle=True, allow_stamina_spend=True).save(self.config)

    def run_cli(self, frames, *, code=1, foreground=True, before_report=None, on_report_retry=None):
        from autohsr.challenge_preset_observe import MAX_AGE

        window = Mock(spec=GameWindow)
        window.hwnd = 11
        window.current_window_key.return_value = 'fixture-window'
        window.emergency_pressed.return_value = False
        blocked_inputs = [getattr(window, name) for name in sorted(INPUT_METHODS | {'focus'})]
        for method in blocked_inputs:
            method.side_effect = AssertionError('read-only preset observation attempted input or focus')
        frames = iter(frames)
        clock = Clock()
        state = SimpleNamespace(window=window, foreground=foreground, runner=None, report_attempts=0)

        def capture():
            clock.sleep(1)
            current = next(frames, EmptyCapture('fixture transition'))
            if isinstance(current, Exception):
                raise current
            state.tokens = current.tokens
            return current.image.copy(), GEOMETRY

        def guard(expected=None):
            if not state.foreground:
                raise FocusLost('fixture background')
            if expected is not None and expected != GEOMETRY:
                raise AutomationError('fixture geometry changed')
            return GEOMETRY

        window.capture.side_effect = capture
        window.guard.side_effect = guard

        def ocr(_image, *, use_cls):
            results = []
            for token in state.tokens:
                left, top, right, bottom = token.box
                polygon = [(x * GEOMETRY.width, y * GEOMETRY.height)
                           for x, y in ((left, top), (right, top), (right, bottom), (left, bottom))]
                results.append((polygon, token.text, token.score))
            return results, None

        def vision_factory(confidence):
            vision = Vision.__new__(Vision)
            vision.confidence = confidence
            vision.engine = ocr
            return vision

        original_save = Runner._save_run_report
        original_replace = Path.replace

        def save(runner, directory, *args, **kwargs):
            state.runner = runner
            if before_report is not None:
                before_report(directory)
            return original_save(runner, directory, *args, **kwargs)

        def replace(source, destination):
            if Path(destination).name == 'report.json':
                state.report_attempts += 1
                if state.report_attempts == 1 and on_report_retry is not None:
                    self.assertFalse(state.runner._monitor_end.is_set())
                    report = json.loads(source.read_bytes())
                    self.assertEqual(report['challenge']['status'], 'preset_tab_observed')
                    on_report_retry(state, clock, MAX_AGE, report['challenge']['evidence'])
                    raise PermissionError('fixture report sharing lock')
            return original_replace(source, destination)

        config_bytes = self.config.read_bytes()
        stdout, stderr = StringIO(), StringIO()
        kernel = Mock()
        kernel.CreateMutexW.return_value = 1
        find_game = Mock(return_value=window)
        native_user32 = Mock()
        with ExitStack() as stack:
            overrides = {
                'autohsr.app.ROOT': self.root,
                'autohsr.app.time': clock,
                'autohsr.challenge_preset_observe.time': clock,
                'autohsr.storage.time': clock,
                'autohsr.app.threading.Thread': Mock(),
                'autohsr.app.is_elevated': Mock(return_value=False),
                'autohsr.app.find_game': find_game,
                'autohsr.app.Vision': Mock(side_effect=vision_factory),
                'autohsr.windows.kernel32': kernel,
                'autohsr.windows.user32': native_user32,
                'autohsr.challenge_preset_observe.page.observe': Mock(side_effect=read_page),
                'autohsr.challenge_preset_observe.page.compare': Mock(side_effect=compare_pages),
            }
            for name, value in overrides.items():
                stack.enter_context(patch(name, value))
            forbidden = [stack.enter_context(patch(name, side_effect=AssertionError(name))) for name in (
                'autohsr.app.Runner._prepare_daily_game', 'autohsr.app.Runner.wait_for_focus',
                'autohsr.workflow_identity.prepare', 'autohsr.notify_runtime.hooks',
                'autohsr.overlay.OverlayService', 'autohsr.recovery.BattleBudget')]
            lease = stack.enter_context(patch('autohsr.workflow_lease.require_workflow_access'))
            stack.enter_context(patch('autohsr.app.C.get_last_error', return_value=0))
            stack.enter_context(patch.object(Runner, '_arm_hotkeys'))
            stack.enter_context(patch.object(Runner, '_save_run_report', save))
            stack.enter_context(patch.object(Path, 'replace', replace))
            stack.enter_context(redirect_stdout(stdout))
            stack.enter_context(redirect_stderr(stderr))
            exit_code = main([FLAG, '--config', str(self.config), '--game-path', self.game])

        for method in [*blocked_inputs, *forbidden]:
            method.assert_not_called()
        find_game.assert_called_once_with(self.game)
        kernel.CreateMutexW.assert_called_once()
        kernel.CloseHandle.assert_called_once()
        lease.assert_called_once()
        self.assertEqual(native_user32.mock_calls, [])
        self.assertEqual(self.config.read_bytes(), config_bytes)
        self.assertEqual(exit_code, code, stdout.getvalue() + stderr.getvalue())
        for uid in (UID, OTHER_UID):
            self.assertNotIn(uid.text.split(':')[1], stdout.getvalue() + stderr.getvalue())
        report = json.loads(stdout.getvalue())
        self.assertEqual(report['operation'], OPERATION)
        self.assertTrue(report['report_saved'])
        self.assertEqual(json.loads((Path(report['run_dir']) / 'report.json').read_bytes()), report)
        self.assertEqual(report['team_selections'], [])
        self.assertEqual(report['challenge']['input_status'], 'not_sent')
        self.assertEqual((report['battle_completed'], report['stamina_spent'], report['stamina_pending']), (0, 0, 0))
        return report, state

    def assert_unknown(self, report):
        self.assertNotEqual(report['status'], 'success')
        data = report['challenge']
        self.assertEqual(data['status'], 'unknown')
        for field in ('mode', 'level', 'tab', 'eight_slots_empty'):
            self.assertIsNone(data[field])
        self.assertEqual(data['visible_presets'], [])
        self.assertEqual(data['evidence'], [])

    def test_cli_uses_two_current_same_account_frames_without_a_plan(self):
        report, state = self.run_cli([frame(), frame()], code=0)
        data = report['challenge']
        self.assertEqual(report['status'], 'success')
        self.assertEqual((data['status'], data['mode'], data['level'], data['tab']),
                         ('preset_tab_observed', MODE, 10, 'preset_list'))
        self.assertTrue(data['eight_slots_empty'])
        self.assertEqual([row['name'] for row in data['visible_presets']], ['哈哈哈哈'])
        self.assertEqual(state.window.capture.call_count, 2)
        sources = data['evidence']
        self.assertEqual([row['capture_sequence'] for row in sources], [1, 2])
        self.assertLess(sources[0]['captured_at'], sources[1]['captured_at'])
        paths = [Path(report['run_dir']) / row['screenshot'] for row in sources]
        self.assertEqual(len(set(paths)), 2)
        for source, path in zip(sources, paths):
            self.assertEqual(path.parent, Path(report['run_dir']))
            self.assertEqual(path.suffix, '.png')
            self.assertEqual(sha256(path.read_bytes()).hexdigest(), source['sha256'])
            self.assertEqual(source['page']['tab'], 'preset_list')

    def test_role_list_is_observed_without_opening_the_preset_tab(self):
        report, _ = self.run_cli([frame('role_list'), frame('role_list')])
        self.assertEqual(report['status'], 'partial')
        data = report['challenge']
        self.assertEqual((data['status'], data['tab']), ('role_list_observed', 'role_list'))
        self.assertEqual(data['visible_presets'], [])
        self.assertEqual(len(data['evidence']), 2)

    def test_blank_or_unreadable_uid_breaks_the_pair(self):
        for gap in (EmptyCapture('fixture loading'), frame(accounts=())):
            with self.subTest(gap=type(gap).__name__):
                report, _ = self.run_cli([frame(), gap, frame(), frame()], code=0)
                self.assertEqual([row['capture_sequence'] for row in report['challenge']['evidence']], [3, 4])

    def test_switching_tabs_requires_a_new_matching_pair(self):
        report, _ = self.run_cli([frame('role_list'), frame(), frame()], code=0)
        self.assertEqual([row['capture_sequence'] for row in report['challenge']['evidence']], [2, 3])

    def test_unknown_or_account_conflict_does_not_publish_verified_fields(self):
        for label, frames in (
                ('wrong page', [frame(None), frame(None)]),
                ('changed account', [frame(), frame(accounts=(OTHER_UID,)), frame(), frame()]),
                ('weak complete counterevidence', [frame(), frame(accounts=(UID, WEAK_UID)), frame(), frame()])):
            with self.subTest(label=label):
                report, _ = self.run_cli(frames)
                self.assert_unknown(report)

    def test_background_window_cannot_be_focused_or_captured(self):
        report, state = self.run_cli([], foreground=False)
        state.window.capture.assert_not_called()
        self.assert_unknown(report)

    def test_report_retry_withdraws_verified_fields_on_foreground_loss_or_expiry(self):
        def lose_focus(state, _clock, _max_age, _sources):
            state.foreground = False

        def expire_first_only(_state, clock, max_age, sources):
            first, second = (row['captured_at'] for row in sources)
            clock.now = (first + second) / 2 + max_age
            self.assertGreater(clock.now - first, max_age)
            self.assertLess(clock.now - second, max_age)

        for interrupt in (lose_focus, expire_first_only):
            with self.subTest(interrupt=interrupt.__name__):
                report, state = self.run_cli([frame(), frame()], on_report_retry=interrupt)
                self.assertGreaterEqual(state.report_attempts, 2)
                self.assert_unknown(report)
                self.assertEqual(len(list(Path(report['run_dir']).glob('*.png'))), 2)

    def test_report_retry_still_observes_stop_and_generation_changes(self):
        def stop(state, _clock, _max_age, _sources):
            state.runner.stop()

        def press_f10(state, _clock, _max_age, _sources):
            state.window.emergency_pressed.return_value = True

        def change_epoch(state, _clock, _max_age, _sources):
            state.runner.input_epoch += 1

        for interrupt, status in ((stop, 'stopped'), (press_f10, 'stopped'), (change_epoch, 'partial')):
            with self.subTest(interrupt=interrupt.__name__):
                report, state = self.run_cli([frame(), frame()], on_report_retry=interrupt)
                self.assertGreaterEqual(state.report_attempts, 2)
                self.assertEqual(report['status'], status)
                self.assert_unknown(report)

    def test_valid_report_retries_while_source_files_are_read_locked(self):
        sources = []

        def require_read_lock(state, _clock, _max_age, rows):
            directory = Path(state.runner.report.run_dir)
            for row in rows:
                path = directory / row['screenshot']
                with self.assertRaises(PermissionError):
                    with path.open('r+b'):
                        pass
                sources.append(path)

        report, state = self.run_cli([frame(), frame()], code=0, on_report_retry=require_read_lock)
        self.assertEqual(state.report_attempts, 2)
        self.assertEqual(report['challenge']['status'], 'preset_tab_observed')
        self.assertEqual(len(sources), 2)
        for path in sources:
            with path.open('r+b'):
                pass

    def test_report_withdraws_verified_fields_when_a_png_changes(self):
        changed = {}

        def tamper(directory):
            paths = sorted(directory.glob('*.png'))
            self.assertEqual(len(paths), 2)
            path = paths[0]
            changed[path] = path.read_bytes() + b'changed'
            path.write_bytes(changed[path])

        report, _ = self.run_cli([frame(), frame()], before_report=tamper)
        self.assert_unknown(report)
        self.assertTrue(changed)
        for path, expected in changed.items():
            self.assertEqual(path.read_bytes(), expected)

    def test_cli_rejects_other_operations_and_overrides_before_config_load(self):
        for arguments in (('--challenge-prepare',), ('--team-preset-calibration',),
                          ('--challenge-lobby', MODE), ('--challenge-plan', 'plan.json'),
                          ('--new-battle-run',), ('--notify',), ('--resume-active-currency',), ('--launch',)):
            with self.subTest(arguments=arguments), redirect_stderr(StringIO()), patch.object(Settings, 'load') as load:
                with self.assertRaises(SystemExit) as failure:
                    main([FLAG, *arguments])
                self.assertEqual(failure.exception.code, 2)
                load.assert_not_called()

    def test_observer_context_cannot_borrow_any_existing_input_path(self):
        window = Mock()
        runner = SimpleNamespace(settings=Settings(), report=RunReport(operation=OPERATION))
        context = Context(runner, window, None)
        scene = frame()
        for method, args in (
                (context.click, (scene, (.2, .3))), (context.key, ('esc',)), (context.scroll, (1,)),
                (context.move, (scene, (.2, .3))), (context.drag, (scene, (.2, .3), (.3, .4))),
                (context.team_preset_entry_input, (scene,)), (context.challenge_lobby_input, (scene, None)),
                (context.challenge_prepare_input, (scene, None))):
            with self.subTest(method=method.__name__), self.assertRaises(AutomationError):
                method(*args)
        self.assertEqual(window.mock_calls, [])
