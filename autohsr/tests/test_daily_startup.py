"""Daily startup through the real CLI and a fake native window."""
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

import numpy as np

from autohsr import windows
from autohsr.__main__ import main
from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, EmptyCapture, FocusLost, Scene, Stopped, TaskResult
from autohsr.workflows import DailyWorkflow
from autohsr.tests.test_core import FakeContext, token


def du_home():
    return Scene([token('差分宇宙', .09, .06), token('乐园漫记', .12, .11),
                  token('开始游戏', .83, .90)])


class DailyStartupTests(TestCase):
    def test_existing_game_is_reused_even_with_legacy_auto_launch_disabled(self):
        runner = Runner(Settings(auto_launch=False))
        window = Mock()
        with patch('autohsr.app.find_game', return_value=window) as find, \
                patch('autohsr.app.launch_game') as launch:
            runner._prepare_daily_game()
        find.assert_called_once_with(runner.settings.game_path)
        launch.assert_not_called()
        self.assertIs(runner._window, window)

    def test_absent_game_is_launched_once_then_waited_for(self):
        runner = Runner(Settings(auto_launch=False))
        window = Mock()
        with patch('autohsr.app.find_game', side_effect=[AutomationError('absent'), window]), \
                patch('autohsr.app.launch_game', return_value='launched') as launch:
            runner._prepare_daily_game()
        launch.assert_called_once_with(runner.settings)
        self.assertIs(runner._window, window)

    def test_window_wait_remains_stoppable(self):
        runner = Runner(Settings())
        runner._stop.wait = Mock(return_value=True)
        with patch('autohsr.app.find_game', side_effect=AutomationError('absent')), \
                patch('autohsr.app.launch_game', return_value='launched'):
            with self.assertRaises(Stopped):
                runner._prepare_daily_game()

    def test_du_start_game_is_never_a_login_target(self):
        mode = Scene([token('差分宇宙', .08, .04), token('模式选择', .08, .07),
                      token('常规演算', .2, .3), token('周期演算', .2, .5)])
        world = Scene([token('大世界提示', .5, .5)])
        phone = Scene([token('开拓等级', .8, .15), token('委托', .8, .6)])
        context = FakeContext([mode, du_home(), world, phone])
        context.template_matches['world_character'] = [(.965, .045, .99)]
        self.assertFalse(DailyWorkflow._login(du_home()))
        self.assertIs(DailyWorkflow(context).ensure_main(), phone)
        self.assertEqual(context.keys, ['esc'] * 3)
        self.assertEqual(context.clicks, [])

    def test_login_may_return_to_the_previous_du_menu(self):
        login = Scene([token('点击进入', .5, .92)])
        world = Scene([token('大世界提示', .5, .5)])
        phone = Scene([token('开拓等级', .8, .15), token('委托', .8, .6)])
        context = FakeContext([login, du_home(), world, phone])
        context.template_matches['world_character'] = [(.965, .045, .99)]
        self.assertIs(DailyWorkflow(context).ensure_main(), phone)
        self.assertEqual(context.clicks, ['点击进入'])
        self.assertEqual(context.keys, ['esc', 'esc'])

    def test_running_battle_is_not_escaped_as_a_menu(self):
        context = FakeContext([Scene([token('战斗设置', .5, .5)])])
        with self.assertRaises(AutomationError):
            DailyWorkflow(context).ensure_main()
        self.assertEqual(context.keys, [])


def page(*tokens):
    return Scene(list(tokens), image=np.full((540, 960, 3), 35, np.uint8))


def phone():
    return page(token('开拓等级', .8, .15), token('委托', .8, .6), token('UID:100000000', .08, .97))


def login():
    return page(token('点击进入', .5, .92))


def supply(*, revealed=False):
    fields = [token('列车补给', .5, .10), token('剩余25天', .5, .15), token('点击领取今日补给', .5, .85)]
    if revealed:
        fields.extend((token('90', .5, .55), token('星琼', .5, .59)))
    return page(*fields)


class ColdStartEntryTests(TestCase):
    def test_explicit_missing_config_rejects_daily_before_runner_or_launch(self):
        with TemporaryDirectory() as tmp:
            absent = Path(tmp) / 'absent config.json'
            for mode, option in (('--run', ['--config', str(absent)]),
                                 ('--plan', ['--config=' + str(absent)])):
                with self.subTest(mode=mode), redirect_stderr(io.StringIO()) as errors, \
                        patch('autohsr.app.Runner') as runner, patch('autohsr.app.launch_game') as launch:
                    self.assertEqual(main([mode, *option]), 2)
                    self.assertIn('明确指定的配置文件不存在', json.loads(errors.getvalue())['error'])
                    runner.assert_not_called()
                    launch.assert_not_called()
            self.assertFalse(absent.exists())

    def invoke(self, frames, *, plan=False, rewards=False, cold=True, stop=None, battle=False):
        temporary = TemporaryDirectory(prefix='hsr-cold-')
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        config = root / 'config.json'
        Settings(assignments=False, battle=battle, daily=not battle, daily_synthesis=False,
                 overlay_logs=False, mail=False, battlepass=False).save(config)
        initial_config = config.read_bytes()
        geometry = windows.Geometry(0, 0, 960, 540)
        window = windows.GameWindow.__new__(windows.GameWindow)
        window.hwnd, window.path, window.focus = 50971, None, Mock()
        native = Mock()
        native.IsWindow.return_value = 1
        native.IsIconic.return_value = 0
        native.GetForegroundWindow.return_value = window.hwnd
        native.GetAsyncKeyState.return_value = 0
        native.GetSystemMetrics.side_effect = {76:0, 77:0, 78:1920, 79:1080}.__getitem__
        now, index = 10., 0
        current, active = None, None
        sent, executed, capture_epochs = [], [], []

        class SyntheticContext(Context):
            def __init__(self, runner, observed_window, vision):
                super().__init__(runner, observed_window, vision)
                window.owner = runner

            def sleep(self, seconds):
                nonlocal now
                now += seconds
                if stop == 'request':
                    self.runner.stop()
                self.checkpoint()

        def capture():
            nonlocal index, current
            current = frames[min(index, len(frames)-1)]
            index += 1
            capture_epochs.append(window.owner.input_epoch)
            if isinstance(current, FocusLost) and stop == 'f10':
                native.GetForegroundWindow.return_value = 7700
                native.GetAsyncKeyState.return_value = 0x8001
            elif isinstance(current, FocusLost) and stop == 'refocus':
                def briefly_elsewhere():
                    native.GetForegroundWindow.side_effect = None
                    return 7700
                native.GetForegroundWindow.side_effect = briefly_elsewhere
            if isinstance(current, Exception):
                raise current
            return current.image, geometry

        def read(_image, _geometry):
            if stop == 'replace_epoch' and index == 1:
                window.owner.input_epoch += 1
            return replace(current, tokens=list(current.tokens), geometry=geometry)

        def click(x, y, expected, **options):
            nonlocal active
            active = next(t.text for t in current.tokens if abs(t.center[0]-x)<1e-6 and abs(t.center[1]-y)<1e-6)
            try:
                return windows.GameWindow.click(window, x, y, expected, **options)
            finally:
                active = None

        def send(count, events, _size):
            sent.append((active, tuple(event.type for event in events)))
            return count

        def daily(workflow):
            self.assertIsNone(workflow.ctx._daily_startup)
            executed.append('daily')
            if stop == 'daily_failure':
                raise AutomationError('synthetic training failure')
            workflow.ctx.report.daily_verified = True
            return TaskResult('daily', 'ok', 'synthetic daily receipt')

        def fight(workflow):
            self.assertIsNone(workflow.ctx._daily_startup)
            executed.append('battle')
            workflow.ctx.snapshot()
            raise AssertionError('an empty battle capture must propagate')

        window.capture, window.click = capture, click
        native.SendInput.side_effect = send
        vision = SimpleNamespace(read=read, template=lambda *_args, **_options: None)
        native_mutex = SimpleNamespace(CreateMutexW=Mock(return_value=1), CloseHandle=Mock())
        output = io.StringIO()
        with (ExitStack() as stack, redirect_stdout(output), redirect_stderr(io.StringIO())):
            for name, value in (
                ('autohsr.app.ROOT', root), ('autohsr.plan_runner.ROOT', root), ('autohsr.app.Context', SyntheticContext),
                ('autohsr.app.C.get_last_error', Mock(return_value=0)), ('autohsr.app.threading.Thread', Mock()),
                ('autohsr.app.Vision', Mock(return_value=vision)), ('autohsr.app.is_elevated', Mock(return_value=False)),
                ('autohsr.windows.kernel32', native_mutex), ('autohsr.windows.user32', native),
                ('autohsr.windows.geometry', Mock(return_value=geometry)),
                ('autohsr.workflows.time', SimpleNamespace(monotonic=lambda: now)),
            ):
                stack.enter_context(patch(name, value))
            stack.enter_context(patch.object(DailyWorkflow, 'daily', daily))
            stack.enter_context(patch.object(DailyWorkflow, 'battle', fight))
            for name in ('assignments', 'mail', 'battlepass'):
                stack.enter_context(patch.object(DailyWorkflow, name, side_effect=AssertionError('extra task')))
            finds = [AutomationError('synthetic absent'), window] if cold else [window]
            stack.enter_context(patch('autohsr.app.find_game', side_effect=finds))
            launch = stack.enter_context(patch('autohsr.app.launch_game', return_value='synthetic launch'))
            args = ['--plan' if plan else '--run', '--config', str(config)]
            if rewards:
                args.append('--reward-only')
            code = main(args)
        self.assertEqual(launch.call_count, int(cold))
        self.assertEqual(config.read_bytes(), initial_config)
        saved = json.loads(output.getvalue())
        self.assertTrue(saved['report_saved'])
        return SimpleNamespace(code=code, report=saved, sent=sent, executed=executed, captures=index,
                               epochs=capture_epochs, root=root)

    def test_black_splash_login_and_second_black_reach_daily(self):
        result = self.invoke([EmptyCapture('blank'), page(token('启动画面', .5, .5)), login(), login(),
                              EmptyCapture('after login'), page(), phone(), phone()])
        self.assertEqual(result.code, 0)
        self.assertEqual(result.executed, ['daily'])
        self.assertEqual(result.sent, [('点击进入', (0,0,0))])
        self.assertEqual(result.report['stamina_spent'], 0)
        self.assertEqual(result.report['failure_task'], '')

    def test_plan_observes_splash_before_its_account_preparation(self):
        result = self.invoke([EmptyCapture('blank'), page(token('启动画面', .5, .5)), phone()], plan=True)
        self.assertEqual(result.code, 0)
        self.assertEqual(result.executed, ['daily'])
        self.assertEqual(result.sent, [])
        self.assertGreaterEqual(result.captures, 4)

    def test_repeated_black_and_unknown_splash_expire_without_input(self):
        for frame in (EmptyCapture('blank'), page(token('启动画面', .5, .5))):
            with self.subTest(frame=type(frame).__name__):
                result = self.invoke([frame])
                self.assertEqual(result.code, 1)
                self.assertIn('日常启动观察超时', result.report['error'])
                self.assertEqual(result.report['failure_task'], 'startup')
                self.assertLessEqual(result.captures, 91)
                self.assertEqual(result.sent, [])
                self.assertEqual(result.report['stamina_spent'], 0)
                if isinstance(frame, Scene):
                    self.assertTrue(list(Path(result.report['run_dir']).glob('*daily_startup_timeout.png')))

    def test_stop_and_focus_f10_use_existing_controls(self):
        for first, stop in ((EmptyCapture('blank'), 'request'), (FocusLost('lost'), 'f10')):
            with self.subTest(stop=stop):
                result = self.invoke([first, phone()], stop=stop)
                self.assertEqual(result.report['status'], 'stopped')
                self.assertEqual(result.sent, [])
                self.assertEqual(result.executed, [])

    def test_generation_change_discards_the_old_login_frame(self):
        result = self.invoke([login(), phone(), phone()], stop='replace_epoch')
        self.assertEqual(result.code, 0)
        self.assertEqual(result.sent, [])
        self.assertEqual(result.epochs[:2], [0, 1])
        refocused = self.invoke([FocusLost('lost'), phone()], stop='refocus')
        self.assertEqual(refocused.code, 0)
        self.assertEqual(refocused.sent, [])
        self.assertEqual(refocused.epochs[:2], [0, 2])

    def test_reward_only_allows_login_but_stops_before_attached_rewards(self):
        for overlay in (supply(), page(token('获得物品', .5, .22), token('点击空白处关闭', .5, .82))):
            with self.subTest(overlay=overlay.tokens[0].text):
                result = self.invoke([EmptyCapture('blank'), login(), login(), overlay], rewards=True)
                self.assertEqual(result.code, 1)
                self.assertIn('仅补领奖遇到', result.report['error'])
                self.assertEqual(result.sent, [('点击进入', (0,0,0))])
                self.assertEqual(result.executed, [])
                self.assertEqual(result.report['stamina_spent'], 0)

    def test_reward_only_reaches_daily_claims_without_a_battle_budget(self):
        result = self.invoke([EmptyCapture('blank'), page(), phone()], rewards=True, battle=True)
        self.assertEqual(result.code, 0)
        self.assertEqual(result.executed, ['daily'])
        self.assertEqual(result.sent, [])
        self.assertEqual((result.report['stamina_spent'], result.report['stamina_pending']), (0, 0))
        self.assertFalse((result.root / 'runs' / 'battle-session.json').exists())

    def test_ordinary_daily_keeps_the_two_verified_free_supply_steps(self):
        result = self.invoke([page(), login(), login(), supply(), supply(), supply(revealed=True),
                              supply(revealed=True), phone(), phone()])
        self.assertEqual(result.code, 0)
        self.assertEqual([target for target, _ in result.sent], ['点击进入', '点击领取今日补给', '点击领取今日补给'])

    def test_manual_blockers_and_battle_capture_use_original_gates(self):
        blocked = self.invoke([page(token('下载更新', .5, .5))])
        self.assertIn('手动完成', blocked.report['error'])
        self.assertEqual(blocked.captures, 1)
        self.assertEqual(blocked.sent, [])
        battle = self.invoke([phone(), phone(), EmptyCapture('synthetic battle frame')], battle=True)
        self.assertEqual(battle.code, 1)
        self.assertEqual(battle.executed, ['battle'])
        self.assertEqual(battle.captures, 3)
        self.assertIn('synthetic battle frame', battle.report['error'])
        self.assertEqual(battle.report['failure_task'], 'battle')

    def test_existing_game_reaches_the_original_navigation_immediately(self):
        result = self.invoke([phone()], cold=False)
        self.assertEqual(result.code, 0)
        self.assertEqual(result.captures, 2)
        self.assertEqual(result.sent, [])
        warm_blank = self.invoke([EmptyCapture('blank'), page(), phone()], cold=False)
        self.assertEqual(warm_blank.code, 0)
        self.assertEqual(warm_blank.sent, [])

    def test_later_daily_failure_has_the_task_name(self):
        result = self.invoke([phone()], cold=False, stop='daily_failure')
        self.assertEqual(result.code, 1)
        self.assertEqual(result.report['failure_task'], 'daily')
        self.assertIn('synthetic training failure', result.report['error'])
