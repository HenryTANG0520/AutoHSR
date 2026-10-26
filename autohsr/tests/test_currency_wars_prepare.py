"""Startup-only guards and one-input feedback; fake windows, no account access."""
import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_prepare import click_target, key_allowed, prepare
from autohsr.models import AutomationError, EmptyCapture, InputInterrupted, RunReport, Scene, Token


def login():
    # Non-personal anchors transcribed from the 2026-10-26 startup capture.
    return Scene([Token('点击进入', .99, (.47, .924, .53, .954)),
                  Token('登出', .99, (.94, .35, .97, .39)),
                  Token('退出', .99, (.94, .44, .97, .48)),
                  Token('CNPR0DWin4.6.0_D16854589_A16781679_L16781679', .99, (.01, .96, .25, .99))],
                  captured_at=time.monotonic())


def phone():
    return Scene([Token('开拓等级', .99, (.65, .1, .75, .2)),
                  Token('委托', .99, (.6, .4, .7, .5))], captured_at=time.monotonic())


class PrepareTests(unittest.TestCase):
    def test_login_requires_each_anchor_and_no_authentication_modal(self):
        state = login()
        self.assertEqual(click_target(state)[0], 'enter_game')
        for i, token in enumerate(state.tokens):
            for replacement in (None, Token(token.text, .5, token.box)):
                altered = Scene(state.tokens[:i] + ([] if replacement is None else [replacement]) + state.tokens[i + 1:])
                with self.assertRaises(AutomationError):
                    click_target(altered)
        state.tokens.append(Token('验证码', .99, (.4, .4, .6, .5)))
        with self.assertRaises(AutomationError):
            click_target(state)
        self.assertFalse(key_allowed(state))

    def test_readonly_and_generic_inputs_stay_forbidden(self):
        state = login()
        intent, target = click_target(state)
        for operation in ('currency_wars', 'currency_wars_flow_test', 'currency_wars_prepare'):
            window = Mock()
            context = Context(Runner(Settings(), operation=operation), window, Mock())
            context.last_scene = state
            context.sleep = Mock()
            context.checkpoint = Mock()
            with self.assertRaises(AutomationError):
                context.click(state, target)
            if operation == 'currency_wars_prepare':
                context.currency_prepare_click(state, intent, target)
                window.click.assert_called_once_with(*target.center, state.geometry)
            else:
                with self.assertRaises(AutomationError):
                    context.currency_prepare_click(state, intent, target)
                window.click.assert_not_called()

    def test_pause_discards_startup_target(self):
        state = login()
        context = Context(Runner(Settings(), operation='currency_wars_prepare'), Mock(), Mock())
        context.last_scene = state
        context.runner.input_epoch = 1
        context.checkpoint = Mock()
        with self.assertRaises(InputInterrupted):
            context.currency_prepare_click(state, *click_target(state))
        context.window.click.assert_not_called()

    def context(self, folder, scenes):
        c = SimpleNamespace(settings=Settings(), report=RunReport(operation='currency_wars_prepare', run_dir=str(folder)),
             runner=SimpleNamespace(input_epoch=0, inactive_duration=0, emit=Mock()), scene_epoch=0,
             last_scene=None, checkpoint=Mock(), sleep=Mock(), log=Mock(), template=Mock(return_value=None))
        pending = list(scenes)
        def snapshot():
            current = pending.pop(0) if pending else c.last_scene
            if isinstance(current, Exception):
                raise current
            c.last_scene = current
            return current
        c.snapshot = snapshot
        c.evidence = lambda scene, label: folder / (label + '.png')
        def submitted(*args):
            journal = json.loads((folder / 'currency-prepare.json').read_text(encoding='utf-8'))
            self.assertEqual(journal['actions'][-1]['status'], 'pending')
        c.currency_prepare_click = Mock(side_effect=submitted)
        c.currency_prepare_back = Mock(side_effect=submitted)
        return c

    def test_one_enter_click_and_phone_feedback_saved_without_starting_match(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            c = self.context(folder, [login(), phone()])
            result = prepare(c)
            self.assertEqual(result.status, 'partial')
            c.currency_prepare_click.assert_called_once()
            self.assertTrue(c.report.currency_wars['game_ready'])
            self.assertFalse(c.report.currency_wars['completion_verified'])
            self.assertEqual(c.report.currency_wars['actions'][0]['status'], 'verified')
            self.assertEqual(c.report.stamina_spent, 0)

    def test_blank_initial_frame_reobserves_and_ready_phone_sends_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            c = self.context(Path(directory), [EmptyCapture('transition'), phone()])
            prepare(c)
            c.currency_prepare_click.assert_not_called()
            c.currency_prepare_back.assert_not_called()
            self.assertTrue(c.report.currency_wars['game_ready'])

    def test_world_opens_phone_once_and_requires_phone_feedback(self):
        with tempfile.TemporaryDirectory() as directory:
            c = self.context(Path(directory), [Scene([], captured_at=time.monotonic()), phone()])
            with patch('autohsr.currency_wars_prepare.ready_kind', side_effect=['world', 'phone', 'phone']):
                prepare(c)
            c.currency_prepare_back.assert_called_once()
            c.currency_prepare_click.assert_not_called()
            self.assertEqual(c.report.currency_wars['actions'][0]['action'], 'open_phone')
            self.assertEqual(c.report.currency_wars['page_kind'], 'phone')

    def test_unknown_feedback_never_replays_enter(self):
        with tempfile.TemporaryDirectory() as directory:
            state = login()
            c = self.context(Path(directory), [state, state])
            clock = SimpleNamespace(monotonic=Mock(side_effect=[0, 0, 121]))
            with patch('autohsr.currency_wars_prepare.time', clock):
                prepare(c)
            c.currency_prepare_click.assert_called_once()
            self.assertEqual(c.report.currency_wars['action_status'], 'unknown')
            self.assertFalse(c.report.currency_wars['game_ready'])

    def test_unknown_page_sends_no_input(self):
        with tempfile.TemporaryDirectory() as directory:
            c = self.context(Path(directory), [Scene([], captured_at=time.monotonic())])
            prepare(c)
            c.currency_prepare_click.assert_not_called()
            c.currency_prepare_back.assert_not_called()

    def test_formal_cli_is_separate_and_does_not_save_or_run_daily(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.json'
            Settings().save(config)
            before = config.read_bytes()
            with patch('autohsr.app.Runner') as runner, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                runner.return_value.run.return_value = {'status': 'partial'}
                self.assertEqual(main(['--currency-wars-prepare', '--config', str(config)]), 1)
                self.assertEqual(runner.call_args.kwargs['operation'], 'currency_wars_prepare')
            self.assertEqual(config.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
