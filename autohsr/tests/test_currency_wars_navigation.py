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
from unittest.mock import Mock, call, patch

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.currency_wars_navigation import locate, next_action, page_kind, standard_selected
from autohsr.models import AutomationError, InputInterrupted, RunReport, Scene, Token
from autohsr.storage import replace_file
from autohsr.tests.test_currency_wars_prepare import phone
from autohsr.tests.test_currency_wars_standard import rank_page as standard_rank_page


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


def rank_page(current=50, values=(50, 49, 48), *, account=1):
    state = standard_rank_page(current, values)
    if account is not None:
        state.tokens.append(Token(f'UID{10**8+account}', .99, (.02, .96, .13, .99)))
    return state


class NavigationTests(unittest.TestCase):
    def context(self):
        return SimpleNamespace(settings=Settings(), template=Mock(return_value=None),
                               runner=SimpleNamespace(currency_configure=False))

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
        c.runner.currency_configure = True
        self.assertEqual(next_action(mode(), c).intent, 'open_standard_difficulty')

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
        with self.assertRaises(ValueError):
            Runner(Settings(), operation='currency_wars_prepare', currency_configure=True)

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
        pending = iter(states)
        def snapshot():
            c.last_scene = next(pending, c.last_scene)
            return c.last_scene
        c.snapshot = snapshot
        c.evidence = lambda state, label: folder / (label+'.png')
        def submit(state, choice):
            journal = json.loads((folder/'currency-navigation.json').read_text(encoding='utf-8'))
            self.assertEqual(journal['actions'][-1]['status'], 'pending')
        c.currency_navigation_input = Mock(side_effect=submit)
        return c

    def rank_context(self, folder, states, *, target=48):
        runner = Runner(Settings(), operation='currency_wars_prepare', currency_locate=True,
                        currency_configure=True, currency_wealth=target)
        runner.report.run_dir = str(folder)
        runner.report.currency_wars = dict(game_ready=True)
        c = Context(runner, Mock(), Mock())
        c.checkpoint, c.sleep = Mock(), Mock()
        pending = iter(states)
        captured_at = time.monotonic() - .1

        def snapshot():
            nonlocal captured_at
            c.last_scene = state = next(pending)
            captured_at += .001
            state.captured_at = captured_at
            return state

        c.snapshot = Mock(side_effect=snapshot)
        c.evidence = lambda state, label: Path(folder)/(label+'.png')
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

    def test_configured_wealth_is_reported_after_fresh_selected_rank_through_context(self):
        with tempfile.TemporaryDirectory() as folder:
            initial = rank_page(50, (50, 49))
            intermediate = rank_page(49, (50, 49, 48))
            unselected = rank_page(49, (49, 48, 47))
            selected = rank_page(48, (49, 48, 47))
            c = self.rank_context(folder, (initial, intermediate, unselected, selected))
            window, capture = c.window, c.snapshot
            journal = Path(folder)/'currency-navigation.json'

            def snapshot():
                state = capture()
                if state is unselected:
                    data = json.loads(journal.read_text(encoding='utf-8'))
                    self.assertNotIn('wealth', data)
                    self.assertEqual(data['actions'][-1]['status'], 'pending')
                return state

            def check_pending(*_):
                data = json.loads(journal.read_text(encoding='utf-8'))
                self.assertEqual(data['actions'][-1]['status'], 'pending')
                self.assertNotIn('wealth', data)

            c.snapshot = snapshot
            window.click.side_effect = check_pending
            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'):
                result = locate(c)
            data = json.loads(journal.read_text(encoding='utf-8'))
            self.assertEqual(window.click.call_args_list, [
                call(*initial.find('49', exact=True).center, initial.geometry),
                call(*intermediate.find('48', exact=True).center, intermediate.geometry),
            ])
            window.key.assert_not_called()
            self.assertEqual([a['status'] for a in data['actions']], ['verified', 'verified'])
            self.assertTrue(data['rank_verified'])
            self.assertEqual((data['rank'], data['wealth']), (8, 48))
            self.assertFalse(data['completion_verified'])
            self.assertEqual(result.status, 'partial')
            self.assertIn('A8财富造物主48', result.detail)
            self.assertEqual(Path(data['screenshot']).name, 'currency_rank_48_ready.png')

    def test_account_change_keeps_original_rank_intents_without_further_input(self):
        for change_at, statuses in ((49, ['pending']), (48, ['verified', 'pending'])):
            with self.subTest(change_at=change_at), tempfile.TemporaryDirectory() as folder:
                initial = rank_page(50, (50, 49))
                intermediate = rank_page(49, (50, 49, 48), account=2 if change_at == 49 else 1)
                selected = rank_page(48, account=2)
                c = self.rank_context(folder, (initial, intermediate, selected))
                with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'), \
                     self.assertRaisesRegex(AutomationError, '账号.*不同'):
                    locate(c)
                data = json.loads((Path(folder)/'currency-navigation.json').read_text(encoding='utf-8'))
                self.assertEqual(c.window.click.call_count, len(statuses))
                self.assertEqual([a['status'] for a in data['actions']], statuses)
                self.assertNotIn('rank_verified', data)
                self.assertNotIn('wealth', data)

    def test_missing_rank_account_is_bounded_before_input_and_can_recover_in_feedback(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.rank_context(folder, (rank_page(48, account=None) for _ in range(3)))
            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'):
                locate(c)
            self.assertEqual(c.snapshot.call_count, 3)
            self.assertEqual(c.report.currency_wars['action_status'], 'needs_observation')
            self.assertNotIn('rank_verified', c.report.currency_wars)
            c.window.click.assert_not_called()
        with tempfile.TemporaryDirectory() as folder:
            states = (rank_page(49, account=None), rank_page(49), rank_page(48, account=None), rank_page(48))
            c = self.rank_context(folder, states)
            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'):
                locate(c)
            self.assertEqual(c.snapshot.call_count, 4)
            self.assertEqual(c.report.currency_wars['wealth'], 48)
            c.window.click.assert_called_once()

    def test_evidence_write_interruptions_keep_rank_and_action_unverified(self):
        for label, ranks, statuses in (
                ('currency_rank_48_ready', (48,), []),
                ('currency_navigation_after_select_rank_48', (49, 48), ['pending'])):
            for cause in ('epoch', 'age'):
                with self.subTest(label=label, cause=cause), tempfile.TemporaryDirectory() as folder:
                    c = self.rank_context(folder, (rank_page(rank) for rank in ranks))
                    evidence = c.evidence

                    def interrupt(state, saved_label):
                        if saved_label == label:
                            if cause == 'epoch':
                                c.runner.input_epoch += 1
                            else:
                                state.captured_at -= 9
                        return evidence(state, saved_label)

                    c.evidence = interrupt
                    with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'), \
                         self.assertRaises(InputInterrupted if cause == 'epoch' else AutomationError):
                        locate(c)
                    data = json.loads((Path(folder)/'currency-navigation.json').read_text(encoding='utf-8'))
                    self.assertEqual(c.window.click.call_count, len(statuses))
                    self.assertEqual([a['status'] for a in data['actions']], statuses)
                    self.assertNotIn('rank_verified', data)
                    self.assertNotIn('wealth', data)

    def test_rank_send_rechecks_current_account_and_durable_intent(self):
        for change in ('account', 'journal'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                c = self.rank_context(folder, (rank_page(49),))
                journal = Path(folder)/'currency-navigation.json'

                def before_send(_):
                    if change == 'account':
                        c.last_scene.tokens[-1] = rank_page(49, account=2).tokens[-1]
                    else:
                        journal.write_text('{}', encoding='utf-8')

                c.log = Mock(side_effect=before_send)
                message = '账号.*不同' if change == 'account' else '意图未完整落盘'
                with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'), \
                     self.assertRaisesRegex(AutomationError, message):
                    locate(c)
                c.window.click.assert_not_called()
                self.assertEqual(c.report.currency_wars['actions'][0]['status'], 'pending')
                self.assertNotIn('rank_verified', c.report.currency_wars)

    def test_rank_send_rechecks_epoch_after_target_rederivation(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.rank_context(folder, (rank_page(49),))
            calls = 0

            def derive(scene, context):
                nonlocal calls
                choice = next_action(scene, context)
                calls += 1
                if calls == 2:
                    c.runner.toggle_pause()
                    c.runner.toggle_pause()
                return choice

            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'), \
                 patch('autohsr.currency_wars_navigation.next_action', side_effect=derive), \
                 self.assertRaises(InputInterrupted):
                locate(c)
            c.window.click.assert_not_called()
            journal = json.loads((Path(folder)/'currency-navigation.json').read_text(encoding='utf-8'))
            self.assertEqual(journal['actions'][0]['status'], 'pending')
            self.assertNotIn('rank_verified', journal)

    def test_failed_rank_receipt_replacement_preserves_pending_in_report_and_journal(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.rank_context(folder, (rank_page(49), rank_page(48)))

            def fail_verified(source, destination, *, before_replace=None):
                record = json.loads(source.read_text(encoding='utf-8'))
                if record['action_status'] == 'transition_verified':
                    raise OSError('synthetic receipt replacement failure')
                replace_file(source, destination, before_replace=before_replace)

            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'), \
                 patch('autohsr.currency_wars_navigation.replace_file', side_effect=fail_verified), \
                 self.assertRaises(OSError):
                locate(c)
            c.window.click.assert_called_once()
            journal = json.loads((Path(folder)/'currency-navigation.json').read_text(encoding='utf-8'))
            self.assertEqual(c.report.currency_wars, journal)
            self.assertEqual(journal['actions'][0]['status'], 'pending')
            self.assertNotIn('rank_verified', journal)

    def test_rank_receipt_retry_rechecks_epoch_before_replacing_journal(self):
        for ranks, status, click_count in (((48,), 'rank_ready', 0), ((49, 48), 'transition_verified', 1)):
            with self.subTest(status=status), tempfile.TemporaryDirectory() as folder:
                c = self.rank_context(folder, (rank_page(rank) for rank in ranks))
                journal = Path(folder)/'currency-navigation.json'
                attempts = []
                original_replace = Path.replace

                def lock_once(source, destination):
                    if Path(destination) == journal:
                        record = json.loads(source.read_text(encoding='utf-8'))
                        if record['action_status'] == status:
                            attempts.append(status)
                            if len(attempts) == 1:
                                raise PermissionError('synthetic sharing lock')
                    return original_replace(source, destination)

                def invalidate(_):
                    c.runner.input_epoch += 1

                with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'), \
                     patch.object(Path, 'replace', lock_once), patch('autohsr.storage.time.sleep', side_effect=invalidate), \
                     self.assertRaises(InputInterrupted):
                    locate(c)
                saved = json.loads(journal.read_text(encoding='utf-8'))
                self.assertEqual(attempts, [status])
                self.assertEqual(c.window.click.call_count, click_count)
                self.assertEqual([action['status'] for action in saved['actions']], ['pending'] * click_count)
                self.assertEqual(c.report.currency_wars, saved)
                self.assertNotIn('rank_verified', saved)

    def test_explicit_wealth_can_cross_the_full_range_with_confirmed_single_steps(self):
        def frames():
            started = time.monotonic() - .1
            for step, current in enumerate(range(50, 0, -1)):
                values = (current, current-1) if current > 1 else (2, 1)
                state = rank_page(current, values)
                state.captured_at = started + .001 * step
                yield state

        with tempfile.TemporaryDirectory() as folder:
            c = self.flow_context(Path(folder), frames())
            c.runner.currency_configure = True
            c.runner.currency_wealth = 1
            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'):
                locate(c)
            data = c.report.currency_wars
            self.assertEqual(data['wealth'], 1)
            self.assertTrue(data['rank_verified'])
            self.assertEqual([a['action'] for a in data['actions']],
                             [f'select_rank_{rank}' for rank in range(49, 0, -1)])
            self.assertTrue(all(a['status'] == 'verified' for a in data['actions']))

    def test_unreachable_requested_wealth_does_not_write_rank_or_send_input(self):
        with tempfile.TemporaryDirectory() as folder:
            state = rank_page(48)
            state.captured_at = time.monotonic()
            c = self.flow_context(Path(folder), [state])
            c.runner.currency_configure = True
            c.runner.currency_wealth = 20
            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'):
                locate(c)
            data = c.report.currency_wars
            self.assertEqual(data['action_status'], 'needs_observation')
            self.assertNotIn('wealth', data)
            self.assertNotIn('rank_verified', data)
            c.currency_navigation_input.assert_not_called()

    def test_auth_overlay_does_not_verify_the_pending_rank_click(self):
        with tempfile.TemporaryDirectory() as folder:
            initial, blocked = rank_page(49), rank_page(48)
            initial.captured_at = blocked.captured_at = time.monotonic()
            blocked.tokens.append(Token('验证码', .99, (.41, .43, .51, .49)))
            c = self.flow_context(Path(folder), [initial, blocked])
            c.runner.currency_configure = True
            c.runner.currency_wealth = 48
            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'), \
                 patch('autohsr.currency_wars_navigation.time', SimpleNamespace(monotonic=Mock(side_effect=[0, 61]))):
                locate(c)
            data = c.report.currency_wars
            c.currency_navigation_input.assert_called_once()
            self.assertEqual(data['actions'][0]['status'], 'unknown')
            self.assertNotIn('rank_verified', data)
            self.assertNotIn('wealth', data)

    def test_already_selected_rank_behind_update_is_not_reported(self):
        with tempfile.TemporaryDirectory() as folder:
            blocked = rank_page(48)
            blocked.captured_at = time.monotonic()
            blocked.tokens.append(Token('更新游戏', .99, (.41, .43, .51, .49)))
            c = self.flow_context(Path(folder), [blocked])
            c.runner.currency_configure = True
            c.runner.currency_wealth = 48
            with patch('autohsr.currency_wars_navigation.prepare'), patch('autohsr.currency_wars_replay.save_sample'):
                locate(c)
            data = c.report.currency_wars
            c.currency_navigation_input.assert_not_called()
            self.assertFalse(data['entry_ready'])
            self.assertEqual(data['action_status'], 'needs_observation')
            self.assertNotIn('rank_verified', data)
            self.assertNotIn('wealth', data)

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

    def test_configure_cli_is_explicit_separate_from_locate(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)/'config.json'
            Settings().save(config)
            before = config.read_bytes()
            with patch('autohsr.app.Runner') as runner, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                runner.return_value.run.return_value = {'status': 'partial'}
                self.assertEqual(main(['--currency-wars-configure', '--config', str(config)]), 1)
                self.assertEqual(runner.call_args.kwargs['operation'], 'currency_wars_prepare')
                self.assertTrue(runner.call_args.kwargs['currency_locate'])
                self.assertTrue(runner.call_args.kwargs['currency_configure'])
                self.assertNotIn('currency_wealth', runner.call_args.kwargs)
                for value in (1, 50):
                    self.assertEqual(main(['--currency-wars-configure', '--currency-wealth', str(value),
                                           '--config', str(config)]), 1)
                    self.assertEqual(runner.call_args.kwargs['currency_wealth'], value)
            self.assertEqual(config.read_bytes(), before)

    def test_cli_rejects_out_of_scope_or_invalid_wealth_before_loading_configuration(self):
        from autohsr.__main__ import main
        other_modes = ((), ('--currency-wars-prepare',), ('--currency-wars-locate',), ('--currency-wars-standard',),
                       ('--currency-wars-loop',), ('--currency-wars-points',), ('--currency-wars-rewards',),
                       ('--plan',), ('--currency-wars-replay', 'not-read.sample.json'))
        cases = [(*mode, '--currency-wealth', '40') for mode in other_modes]
        cases.extend(('--currency-wars-configure', '--currency-wealth', value) for value in ('0', '51', '1.5', 'True'))
        with patch.object(Settings, 'load') as load, patch('autohsr.app.Runner') as runner:
            for args in cases:
                with self.subTest(args=args), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    main(list(args))
                self.assertEqual(error.exception.code, 2)
            load.assert_not_called()
            runner.assert_not_called()

    def test_runner_rejects_invalid_wealth_and_explicit_overrides_for_other_operations(self):
        configure = dict(operation='currency_wars_prepare', currency_locate=True, currency_configure=True)
        for value in (0, 51, True, 1.5, '40'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Runner(Settings(), **configure, currency_wealth=value)
        for operation, locate_enabled, configure_enabled in (
                ('currency_wars_prepare', True, False), ('currency_wars_standard', True, True),
                ('currency_wars_points', True, False), ('daily', False, False)):
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                Runner(Settings(), operation=operation, currency_locate=locate_enabled,
                       currency_configure=configure_enabled, currency_wealth=40)


if __name__ == '__main__':
    unittest.main()
