"""Navigation authority, stale inputs and transition accounting; no game access."""
import io
import json
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_navigation import locate, next_action, page_kind, standard_selected
from autohsr.models import AutomationError, InputInterrupted, RunReport, Scene, Token
from autohsr.tests.test_currency_wars_prepare import phone


def scene(*items):
    return Scene([Token(text, .99, box) for text, box in items], captured_at=time.monotonic())


def menu():
    state = phone()
    state.tokens.append(Token('指南', .99, (.7, .6, .75, .63)))
    return state


def universe(selected=False):
    state = scene(('旷宇纷争', (.03, .04, .11, .08)), ('货币战争', (.18, .4, .23, .43)),
                  ('差分宇宙', (.18, .5, .23, .53)), ('前往参与', (.76, .8, .81, .83)))
    if selected:
        state.tokens.extend([Token('零和博弈', .99, (.79, .36, .84, .39)),
                             Token('晋升等级', .99, (.43, .52, .52, .56)),
                             Token('奖励预览', .99, (.58, .62, .64, .65))])
    return state


def mode(standard=True):
    return scene(('货币战争', (.03, .03, .10, .06)), ('标准博弈', (.06, .18, .13, .22)),
                 ('超频博弈', (.06, .36, .13, .40)), ('通关可获得积分', (.30, .42, .43, .45)),
                 ('对局记录', (.04, .88, .11, .91)),
                 ('标准博弈' if standard else '超频博弈', (.31, .13, .39, .17)),
                 ('进入标准博弈' if standard else '进入超频博弈', (.8, .88, .91, .92)))


def lobby():
    return scene(('货币战争', (.02, .06, .12, .10)), ('零和博弈', (.02, .12, .13, .16)),
                 ('创业指南', (.02, .24, .13, .28)), ('优势布局', (.02, .32, .13, .36)),
                 ('攻略大全', (.02, .39, .13, .43)), ('开始货币战争', (.75, .88, .92, .93)))


def points_rewards():
    return scene(('积分奖励', (.04, .30, .1, .33)), ('规则说明', (.82, .30, .87, .33)),
                 ('当前积分', (.08, .65, .14, .68)))


class NavigationTests(unittest.TestCase):
    def context(self):
        return SimpleNamespace(settings=Settings(), template=Mock(return_value=None))

    def test_redacted_real_navigation_anchors_and_missing_anchor_counterexamples(self):
        fixtures = json.loads((Path(__file__).parent/'fixtures/currency_wars_navigation.json').read_text(encoding='utf-8'))
        for kind, data in fixtures['pages'].items():
            state = Scene([Token(t['text'], t['score'], tuple(t['box'])) for t in data['tokens']])
            self.assertEqual(page_kind(state), 'mode_select' if kind == 'standard_selected' else kind)
            if kind == 'standard_selected':
                self.assertTrue(standard_selected(state))
            if kind == 'currency_guide':
                for label in ('零和博弈', '晋升等级', '奖励预览'):
                    altered = Scene([t for t in state.tokens if t.text != label])
                    self.assertNotEqual(page_kind(altered), 'currency_guide')

    def test_left_category_alone_does_not_authorize_participate(self):
        c = self.context()
        self.assertEqual(next_action(universe(), c).intent, 'select_currency_guide')
        self.assertEqual(next_action(universe(True), c).intent, 'participate')
        c.template.assert_not_called()

    def test_unique_trusted_phone_target_required(self):
        c, state = self.context(), menu()
        self.assertEqual(next_action(state, c).intent, 'open_guide')
        state.tokens.append(state.tokens[-1])
        with self.assertRaises(AutomationError):
            next_action(state, c)
        state = menu()
        state.tokens[-1] = replace(state.tokens[-1], score=.5)
        with self.assertRaises(AutomationError):
            next_action(state, c)

    def test_guide_tab_uses_current_template_and_checks_location(self):
        c = self.context()
        state = scene(('星际和平指南', (.02, .04, .14, .09)))
        for match in (None, (.9, .2, .99), (.3, .2, .5)):
            c.template.return_value = match
            with self.assertRaises(AutomationError):
                next_action(state, c)
        c.template.return_value = (.31, .19, .96)
        self.assertEqual(next_action(state, c).intent, 'open_universe_guide')

    def test_standard_selected_stops_before_enter_match(self):
        c = self.context()
        self.assertTrue(standard_selected(mode()))
        self.assertIsNone(next_action(mode(), c))
        self.assertEqual(next_action(mode(False), c).intent, 'select_standard')
        only_title = scene(('标准博弈', (.31, .13, .39, .17)))
        self.assertFalse(standard_selected(only_title))

    def test_decorative_quotes_and_noninteractive_notice_do_not_create_extra_clicks(self):
        c, state = self.context(), lobby()
        state.tokens[-1] = replace(state.tokens[-1], text='开始「货币战争」')
        self.assertEqual(next_action(state, c).intent, 'open_mode')
        state.tokens.append(Token('积分线已更新', .99, (.45, .48, .56, .51)))
        self.assertEqual(next_action(state, c).intent, 'open_mode')
        # The same text outside the calibrated lobby is not a generic close.
        with self.assertRaises(AutomationError):
            next_action(scene(('积分线已更新', (.45, .48, .56, .51))), c)

    def test_world_label_requires_matching_interact_icon(self):
        c = self.context()
        state = scene(('朝露公馆', (.02, .02, .12, .06)), ('状态效果', (.88, .15, .94, .2)),
                      ('货币战争', (.61, .5, .7, .53)))
        for match in (None, (.1, .51, .99), (.58, .6, .99)):
            c.template.return_value = match
            with self.assertRaises(AutomationError):
                next_action(state, c)
        c.template.return_value = (.58, .515, .99)
        self.assertEqual(next_action(state, c).key, 'f')

    def test_readonly_and_old_flow_cannot_use_navigation(self):
        state = menu()
        for operation, enabled in [('currency_wars', False), ('currency_wars_flow_test', False),
                                   ('currency_wars_prepare', False), ('currency_wars_prepare', True)]:
            context = Context(Runner(Settings(), operation=operation, currency_locate=enabled), Mock(), Mock())
            context.last_scene = state
            context.checkpoint, context.sleep = Mock(), Mock()
            choice = next_action(state, context)
            if enabled:
                context.currency_navigation_input(state, choice)
                context.window.click.assert_called_once_with(*choice.target.center, state.geometry)
            else:
                with self.assertRaises(AutomationError):
                    context.currency_navigation_input(state, choice)
                context.window.click.assert_not_called()
        with self.assertRaises(ValueError):
            Runner(Settings(), operation='daily', currency_locate=True)

    def test_epoch_or_forged_target_discards_input(self):
        state = menu()
        c = Context(Runner(Settings(), operation='currency_wars_prepare', currency_locate=True), Mock(), Mock())
        c.last_scene, c.checkpoint = state, Mock()
        choice = next_action(state, c)
        with self.assertRaises(AutomationError):
            c.currency_navigation_input(state, replace(choice, key='enter'))
        c.runner.input_epoch += 1
        with self.assertRaises(InputInterrupted):
            c.currency_navigation_input(state, choice)
        c.window.click.assert_not_called()
        c.window.key.assert_not_called()

    def flow_context(self, folder, states):
        c = self.context()
        c.report = RunReport(operation='currency_wars_prepare', run_dir=str(folder))
        c.report.currency_wars = dict(game_ready=True)
        c.runner = SimpleNamespace(currency_locate=True, input_epoch=0, inactive_duration=0, emit=Mock())
        c.scene_epoch, c.last_scene = 0, None
        c.checkpoint, c.sleep, c.log = Mock(), Mock(), Mock()
        pending = list(states)
        def snapshot():
            c.last_scene = pending.pop(0) if pending else c.last_scene
            return c.last_scene
        c.snapshot = snapshot
        c.evidence = lambda state, label: folder / (label+'.png')
        def submit(state, choice):
            journal = json.loads((folder/'currency-navigation.json').read_text(encoding='utf-8'))
            self.assertEqual(journal['actions'][-1]['status'], 'pending')
        c.currency_navigation_input = Mock(side_effect=submit)
        return c

    def test_one_step_journal_verified_before_next_and_stops_at_standard(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.flow_context(Path(folder), [menu(), universe(True), lobby(), mode()])
            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'):
                result = locate(c)
            self.assertEqual(result.status, 'partial')
            self.assertEqual([a['status'] for a in c.report.currency_wars['actions']], ['verified'] * 3)
            self.assertTrue(c.report.currency_wars['entry_ready'])
            self.assertFalse(c.report.currency_wars['completion_verified'])
            self.assertEqual(c.currency_navigation_input.call_count, 3)

    def test_feedback_timeout_never_repeats_input(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.flow_context(Path(folder), [menu()])
            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'), \
                 patch('autohsr.currency_wars_navigation.time', SimpleNamespace(monotonic=Mock(side_effect=[0, 61]))):
                locate(c)
            c.currency_navigation_input.assert_called_once()
            self.assertEqual(c.report.currency_wars['action_status'], 'unknown')
            self.assertFalse(c.report.currency_wars['entry_ready'])

    def test_verified_rewards_detour_closes_and_rederives_lobby_target(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.flow_context(Path(folder), [lobby(), points_rewards(), lobby(), mode()])
            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'):
                locate(c)
            actions = c.report.currency_wars['actions']
            self.assertEqual([a['action'] for a in actions], ['open_mode', 'close_points_rewards', 'open_mode'])
            self.assertEqual([a['status'] for a in actions], ['verified'] * 3)
            self.assertTrue(c.report.currency_wars['entry_ready'])

    def test_cli_selects_explicit_navigation_without_saving_settings(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)/'config.json'
            Settings().save(config)
            before = config.read_bytes()
            with patch('autohsr.app.Runner') as runner, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                runner.return_value.run.return_value = {'status': 'partial'}
                self.assertEqual(main(['--currency-wars-locate', '--config', str(config)]), 1)
                self.assertEqual(runner.call_args.kwargs['operation'], 'currency_wars_prepare')
                self.assertTrue(runner.call_args.kwargs['currency_locate'])
            self.assertEqual(config.read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
