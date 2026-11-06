"""Replay released directory fields with synthetic headers, account and window."""
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
import io
from itertools import count
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.build_target_read import BuildTargetRead
from autohsr.config import Settings
from autohsr.models import AutomationError, EmptyCapture, FocusLost, Scene, Token
from autohsr.windows import GameWindow, Geometry


def token(text, x, y, score=.99, *, width=.02):
    return Token(text, score, (x - width / 2, y - .01, x + width / 2, y + .01))


def directory_fields(suffix):
    path = Path(__file__).parent / 'fixtures' / 'dungeons' / 'guide_rows.json'
    samples = json.loads(path.read_text(encoding='utf-8'))['samples']
    selected = next(sample for sample in samples if sample['source'].endswith(suffix))
    return [Token(row['text'], row['score'], tuple(row['box'])) for row in selected['tokens']]


HEADERS = [token('星际和平指南', .08, .047), token('生存索引', .08, .073)]
ACCOUNT = token('UID:123456789', .05, .97)
OTHER = token('UID:123456780', .05, .97)


class Window:
    hwnd = 1
    geometry = (0, 0, 1920, 1080)

    def __init__(self, frames):
        self.frames = iter(frames)
        self.frame = []
        self.image = np.zeros((24, 32, 3), dtype=np.uint8)
        self.clicks = []
        self.interrupt_click = False

    def capture(self):
        self.frame = next(self.frames, self.frame)
        if isinstance(self.frame, Exception):
            raise self.frame
        return self.image, self.geometry

    def read(self, image, geometry):
        return Scene(list(self.frame), image, geometry)

    def guard(self, expected=None):
        if expected is not None and expected != self.geometry:
            raise AutomationError('fixture geometry changed')
        return self.geometry

    def focus(self):
        self.guard()

    def emergency_pressed(self):
        return False

    def click(self, x, y, geometry, *, before_send=None):
        self.guard(geometry)
        if before_send is not None:
            before_send()
        self.clicks.append((x, y))
        if self.interrupt_click:
            raise FocusLost('fixture interrupted after submit')


class NativeDispatchWindow(Window):
    geometry = Geometry(0, 0, 1920, 1080)
    click = GameWindow.click
    send = GameWindow.send
    emergency_pressed = staticmethod(GameWindow.emergency_pressed)


class BuildTargetReadTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = Settings(overlay_logs=False)
        fields = directory_fields('_calyx_golden_00.json')
        self.entry = next(item for item in fields if item.text == '培养目标')
        self.catalogue = [*HEADERS, ACCOUNT, *fields]
        # Title and number placement described by the official 3.1 example.
        # The number layout, transition and account below are simulated.
        self.panel = [*HEADERS, ACCOUNT, self.entry, token('培养还需获取资源', .47, .29),
                      token('28', .38, .40), token('30', .72, .38), token('进入', .84, .38),
                      token('隧洞遗器推荐', .47, .64), token('更换培养目标', .22, .88)]

    @contextmanager
    def runtime(self, frames, *, window_type=Window):
        window = window_type(frames)
        ticks = count(100, .01)
        clock = SimpleNamespace(monotonic=lambda: next(ticks))
        with ExitStack() as stack:
            stack.enter_context(patch('autohsr.app.ROOT', self.root))
            stack.enter_context(patch('autohsr.app.time', clock))
            stack.enter_context(patch('autohsr.build_target_read.time', clock))
            stack.enter_context(patch('autohsr.app.C.get_last_error', return_value=0))
            stack.enter_context(patch('autohsr.app.threading.Thread'))
            stack.enter_context(patch('autohsr.app.is_elevated', return_value=False))
            stack.enter_context(patch('autohsr.app.Vision', return_value=window))
            stack.enter_context(patch.object(Context, 'sleep', lambda ctx, seconds: ctx.checkpoint()))
            stack.enter_context(patch.object(Runner, '_arm_hotkeys'))
            stack.enter_context(patch.object(Runner, '_prepare_daily_game', side_effect=AssertionError('startup')))
            stack.enter_context(patch('autohsr.app.find_game', return_value=window))
            stack.enter_context(patch('autohsr.windows.kernel32', SimpleNamespace(
                CreateMutexW=Mock(return_value=1), CloseHandle=Mock(return_value=True))))
            yield window

    def native(self, frames):
        with self.runtime(frames) as window:
            runner = Runner(self.settings, operation='build_target_read')
            report = runner.run()
        self.assertIsNone(runner.battle_budget)
        self.assertEqual((report.stamina_spent, report.stamina_pending, report.battle_completed), (0, 0, 0))
        return report, window.clicks

    def test_formal_cli_clicks_real_entry_once_and_saves_only_scoped_page_result(self):
        config = self.root / 'config.json'
        self.settings.save(config)
        original = config.read_bytes()
        runs = self.root / 'runs'
        runs.mkdir()
        ledger = runs / 'battle-session.json'
        ledger.write_bytes(b'original pending evidence')
        output, logs = io.StringIO(), io.StringIO()
        with (self.runtime([self.catalogue, self.catalogue, EmptyCapture(), self.panel, self.panel]) as window,
              patch('autohsr.notify_runtime.hooks') as notify, redirect_stdout(output), redirect_stderr(logs)):
            self.assertEqual(main(['--read-build-target', '--config', str(config)]), 0)
        report = json.loads(output.getvalue())
        proof = report['build_target']
        self.assertEqual(window.clicks, [self.entry.center])
        self.assertEqual((report['operation'], report['status']), ('build_target_read', 'success'))
        self.assertEqual((proof['entry_input'], proof['page_verified']), ('sent', True))
        self.assertEqual(report['power_plan'], {})
        self.assertEqual((report['battle_completed'], report['stamina_spent'], report['stamina_pending']), (0, 0, 0))
        for field in ('entry_evidence', 'panel_evidence'):
            self.assertTrue((Path(report['run_dir']) / proof[field]).is_file())
        for stream in (output, logs):
            self.assertNotIn('123456789', stream.getvalue())
        self.assertEqual(config.read_bytes(), original)
        self.assertEqual(ledger.read_bytes(), b'original pending evidence')
        notify.assert_not_called()

    def test_existing_panel_uses_no_input(self):
        report, clicks = self.native([self.panel, self.panel])
        self.assertEqual(report.status, 'success', report.error)
        self.assertEqual(report.build_target['entry_input'], 'not_sent')
        self.assertEqual(clicks, [])

    def test_level_and_trace_complete_layout_verifies_current_panel_and_entry_feedback(self):
        # Calibrated positions from the 4.6.0 completed-cultivation panel.
        complete = [*HEADERS, ACCOUNT, self.entry, token('角色培养', .407, .292),
                    token('已完成等级、行迹的提升', .474, .340), token('遗器评级', .407, .405),
                    token('隧洞遗器推荐', .448, .452), token('位面饰品推荐', .446, .751),
                    token('更换培养目标', .241, .857), token('培养设置', .815, .854)]
        for frames, expected_clicks in (([complete, complete], []),
                                        ([self.catalogue, self.catalogue, complete, complete], [self.entry.center])):
            with self.subTest(expected_clicks=expected_clicks):
                report, clicks = self.native(frames)
                self.assertEqual((report.status, clicks), ('success', expected_clicks), report.error)
                self.assertTrue(report.build_target['page_verified'])

        contradictory = [*complete, token('已获得足够的等级和行迹材料', .46, .37)]
        obscured = [*complete, token('获得途径', .46, .46)]
        mixed = [*self.catalogue, *complete[4:]]
        for frame in (contradictory, obscured, mixed):
            with self.subTest(frame=frame):
                report, clicks = self.native([frame])
                self.assertEqual((report.status, clicks), ('failed', []))

    def test_unverified_source_and_obscured_guide_never_send_input(self):
        cases = {
            'sidebar alone': [*HEADERS, ACCOUNT, self.entry],
            'duplicate entry': [*self.catalogue, self.entry],
            'weak entry': [t for t in self.catalogue if t != self.entry] + [token('培养目标', .19, .30, score=.7)],
            'missing account': [t for t in self.catalogue if t != ACCOUNT],
            'wrong header': [t for t in self.catalogue if t != HEADERS[1]] + [token('每日实训', .08, .073)],
            'overlaid confirmation': [*self.catalogue, token('确认', .59, .64)],
            'material detail': [*self.catalogue, token('获得途径', .48, .48)],
            'role picker': [*self.catalogue, token('选择角色', .48, .34), token('确定', .56, .65)],
            'replenishment': [*self.catalogue, token('补充开拓力', .50, .37)],
            'update overlay': [*self.catalogue, token('更新游戏', .50, .45)],
            'split login overlay': [*self.catalogue, token('登录', .537, .461, .94), token('账号', .509, .461, .93)],
            'split verification overlay': [*self.catalogue, token('验', .48, .455), token('证', .503, .45),
                                           token('码', .526, .453)],
            'recommendations alone': [t for t in self.panel if t.text != '培养还需获取资源'],
        }
        for name, frame in cases.items():
            with self.subTest(name=name):
                report, clicks = self.native([frame])
                self.assertEqual((report.status, clicks), ('failed', []))

    def test_account_switch_is_rejected_before_input_and_during_feedback(self):
        changed_catalogue = [OTHER if t == ACCOUNT else t for t in self.catalogue]
        changed_panel = [OTHER if t == ACCOUNT else t for t in self.panel]
        report, clicks = self.native([self.catalogue, changed_catalogue])
        self.assertEqual((report.status, clicks), ('failed', []))
        self.assertIn('账号已改变', report.error)
        report, clicks = self.native([self.catalogue, self.catalogue, self.panel, changed_panel])
        self.assertEqual((report.status, clicks), ('partial', [self.entry.center]))
        self.assertFalse(report.build_target['page_verified'])
        self.assertIn('账号已改变', report.error)

    def test_blank_and_uid_omission_break_the_feedback_pair(self):
        no_account = [t for t in self.panel if t != ACCOUNT]
        report, clicks = self.native([self.catalogue, self.catalogue, self.panel, EmptyCapture(),
                                      self.panel, no_account, self.panel, EmptyCapture()])
        self.assertEqual((report.status, clicks), ('partial', [self.entry.center]))
        self.assertFalse(report.build_target['page_verified'])

    def test_visible_section_through_material_overlay_is_not_feedback(self):
        for fragments in ((token('获得途径', .48, .48),),
                          (token('获得', .509, .501, .91), token('途径', .537, .501, .93))):
            with self.subTest(fragments=fragments):
                overlay = [*self.panel, *fragments]
                report, clicks = self.native([self.catalogue, self.catalogue, overlay, overlay])
                self.assertEqual((report.status, clicks), ('partial', [self.entry.center]))
                self.assertEqual(report.build_target['entry_input'], 'sent')
                self.assertFalse(report.build_target['page_verified'])

    def test_unrelated_fragments_on_different_rows_or_far_apart_are_not_a_modal(self):
        for x, y in ((.537, .543), (.72, .501)):
            with self.subTest(x=x, y=y):
                panel = [*self.panel, token('获得', .509, .501), token('途径', x, y)]
                report, clicks = self.native([self.catalogue, self.catalogue, panel, panel])
                self.assertEqual((report.status, clicks), ('success', [self.entry.center]))
                self.assertTrue(report.build_target['page_verified'])

    def test_authentication_sentence_blocks_when_split_across_neighboring_boxes(self):
        for fragments in ((token('请完成账号登录后继续', .506, .461, width=.151),),
                          (token('请完成账号', .466, .461, width=.070),
                           token('登录后继续', .542, .463, width=.070)),
                          (token('请完成账', .46, .461, width=.060),
                           token('号', .503, .462, width=.020),
                           token('登录后继续', .554, .462, width=.070))):
            with self.subTest(fragments=fragments):
                report, clicks = self.native([[*self.catalogue, *fragments]])
                self.assertEqual((report.status, clicks), ('failed', []))

    def test_narrow_weak_noise_does_not_change_the_gap_between_authentication_boxes(self):
        for x, expected_status, expected_clicks in ((.539, 'failed', []),
                                                     (.556, 'success', [self.entry.center])):
            with self.subTest(x=x):
                catalogue = [*self.catalogue, token('账号', .505, .461, width=.026),
                             token('-', .522, .462, .42, width=.003),
                             token('登录', x, .461, width=.026)]
                frames = [catalogue, catalogue, self.panel, self.panel] if expected_clicks else [catalogue]
                report, clicks = self.native(frames)
                self.assertEqual((report.status, clicks), (expected_status, expected_clicks))

    def test_repeated_capture_time_does_not_verify_the_panel(self):
        original = Context.snapshot
        captured_at = None

        def fixed_panel_time(ctx):
            nonlocal captured_at
            scene = original(ctx)
            if ctx.window.clicks:
                if captured_at is None:
                    captured_at = scene.captured_at
                scene.captured_at = captured_at
            return scene

        with patch.object(Context, 'snapshot', fixed_panel_time):
            report, clicks = self.native([self.catalogue, self.catalogue, self.panel, self.panel])
        self.assertEqual((report.status, clicks), ('partial', [self.entry.center]))
        self.assertFalse(report.build_target['page_verified'])

    def test_focus_lost_at_dispatch_preserves_uncertain_action_and_does_not_repeat(self):
        with self.runtime([self.catalogue, self.catalogue, self.panel]) as window:
            window.interrupt_click = True
            report = Runner(self.settings, operation='build_target_read').run()
        self.assertEqual((report.status, window.clicks), ('partial', [self.entry.center]))
        self.assertEqual(report.build_target['entry_input'], 'unconfirmed')
        self.assertFalse(report.build_target['page_verified'])

    def test_native_click_rechecks_source_after_coordinate_and_input_preparation(self):
        cases = (('normal', 'success', 'sent', 1),
                 ('paused', 'failed', 'not_sent', 0),
                 ('stopped', 'stopped', 'not_sent', 0),
                 ('short write', 'partial', 'unconfirmed', 1))
        for phase, status, entry_input, sent in cases:
            with self.subTest(phase=phase), self.runtime(
                    [self.catalogue, self.catalogue, self.panel, self.panel], window_type=NativeDispatchWindow):
                runner = Runner(self.settings, operation='build_target_read')
                metrics = {76: 0, 77: 0, 78: 1920, 79: 1080}
                requested = []

                def get_system_metrics(index):
                    requested.append(index)
                    if phase == 'paused' and len(requested) == 1:
                        runner.toggle_pause()
                        runner.toggle_pause()
                    return metrics[index]

                def emergency_key(_key):
                    if phase == 'stopped':
                        runner.stop()
                    return 0

                dispatch = Mock(side_effect=lambda count, *_: count - (phase == 'short write'))
                fake_user32 = SimpleNamespace(GetSystemMetrics=get_system_metrics,
                                              GetAsyncKeyState=emergency_key, SendInput=dispatch)
                with patch('autohsr.windows.user32', fake_user32):
                    report = runner.run()
                self.assertEqual(requested, [76, 77, 78, 79])
                self.assertEqual(dispatch.call_count, sent)
                self.assertEqual((report.status, report.build_target['entry_input']), (status, entry_input))
                self.assertIs(report.build_target['page_verified'], status == 'success')

    def test_evidence_failure_or_expiry_cannot_authorize_input_or_result(self):
        original = Context.evidence
        for label, issue, expected_clicks in (
            ('build_target_entry', 'disk', []),
            ('build_target_entry', 'expiry', []),
            ('build_target_entry', 'epoch', []),
            ('build_target_panel', 'expiry', [self.entry.center]),
            ('build_target_panel', 'epoch', [self.entry.center]),
        ):
            def save(ctx, scene, name):
                if name == label and issue == 'disk':
                    raise OSError('fixture disk write failed')
                path = original(ctx, scene, name)
                if name == label:
                    if issue == 'expiry':
                        scene.captured_at -= 10
                    else:
                        ctx.runner.input_epoch += 1
                return path

            with self.subTest(label=label, issue=issue), patch.object(Context, 'evidence', save):
                report, clicks = self.native([self.catalogue, self.catalogue, self.panel, self.panel])
                self.assertEqual(clicks, expected_clicks)
                self.assertFalse(report.build_target['page_verified'])

    def test_geometry_change_at_post_save_checkpoint_does_not_verify_panel(self):
        original = Context.evidence
        with self.runtime([self.panel, self.panel]) as window:
            guard = window.guard

            def save(ctx, scene, name):
                path = original(ctx, scene, name)
                if name == 'build_target_panel':
                    def resize(expected=None):
                        if expected is None:
                            window.geometry = (0, 0, 1600, 900)
                        return guard(expected)

                    window.guard = resize
                return path

            with patch.object(Context, 'evidence', save):
                report = Runner(self.settings, operation='build_target_read').run()
        self.assertEqual((report.status, window.clicks), ('failed', []))
        self.assertFalse(report.build_target['page_verified'])

    def test_reading_context_rejects_generic_actions(self):
        window = Window([])
        ctx = Context(Runner(self.settings, operation='build_target_read'), window, window)
        scene = Scene(self.panel)
        for action, args in ((ctx.click, (scene, self.entry)), (ctx.key, ('esc',)),
                             (ctx.move, (scene, (.2, .3))), (ctx.scroll, (100,)),
                             (ctx.drag, (scene, (.2, .3), (.3, .4))), (ctx.build_target_entry_input, (scene,))):
            with self.subTest(action=action.__name__), self.assertRaises(AutomationError):
                action(*args)
        self.assertEqual(window.clicks, [])

    def test_last_classification_cannot_send_after_input_epoch_changes(self):
        original = BuildTargetRead._classify

        def change_epoch(reader, scene):
            result = original(reader, scene)
            if reader.record.get('entry_evidence'):
                reader.ctx.runner.input_epoch += 1
            return result

        with patch.object(BuildTargetRead, '_classify', change_epoch):
            report, clicks = self.native([self.catalogue, self.catalogue])
        self.assertEqual((report.status, clicks), ('failed', []))
        self.assertIn('代次', report.error)

    def test_cli_cannot_mix_reading_with_a_plan_or_manual_targets(self):
        for args in (['--run'], ['--plan'], ['--stamina', '10'], ['--power-plan-file', 'plan.json']):
            with (self.subTest(args=args), patch('autohsr.app.Runner') as runner,
                  redirect_stderr(io.StringIO()), self.assertRaises(SystemExit)):
                main(['--read-build-target', *args])
            runner.assert_not_called()
