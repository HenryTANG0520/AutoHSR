"""Startup regressions: existing modes must never be mistaken for login."""
from unittest import TestCase
from unittest.mock import Mock, patch

from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, Scene, Stopped
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
