"""Standard start continuity and input authority; fake game windows only."""
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
from autohsr import currency_wars_standard_market  # Import before patching its dependency in individual tests.
from autohsr.config import Settings
from autohsr.currency_wars_session import StandardSession
from autohsr.currency_wars_standard_flow import next_action, run_standard
from autohsr.models import AutomationError, InputInterrupted, RunReport, TaskResult, Token, normalize
from autohsr.tests.test_currency_wars_node import screen
from autohsr.tests.test_currency_wars_standard import rank_page


def ready():
    state = rank_page(40, (40, 39, 38))
    state.captured_at = time.monotonic()
    state.tokens.append(Token('UID:100000000',.99,(.01,.96,.10,.99)))
    return state


class StandardFlowTests(unittest.TestCase):
    def store(self, folder):
        store = StandardSession(Path(folder)/'currency-standard-session.json')
        store.begin(Path(folder)/'attempt', dict(rank_verified=True, rank=8, wealth=40))
        from autohsr.currency_wars_identity import account_key
        store.data['account_key'] = account_key(ready())
        store.persist()
        return store

    def test_scope_rank_target_and_durable_intent_all_required(self):
        state = ready()
        choice = next_action(state)
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder)
            for op in ('currency_wars', 'currency_wars_prepare', 'currency_wars_flow_test', 'currency_wars_standard'):
                c = Context(Runner(Settings(), operation=op), Mock(), Mock())
                c.last_scene, c.currency_standard_session = state, store
                c.checkpoint, c.sleep = Mock(), Mock()
                with self.assertRaises(AutomationError):
                    c.currency_standard_input(state, choice)
                c.window.click.assert_not_called()
            store.pending(choice.intent, 0, 'before.png', choice.expected)
            c.currency_standard_input(state, choice)
            c.window.click.assert_called_once_with(*choice.target.center, state.geometry)
            self.assertIsNone(c.last_scene)

    def test_wrong_rank_forged_target_and_epoch_change_cannot_start(self):
        with self.assertRaises(AutomationError):
            next_action(rank_page(41, (41, 40, 39)))
        with tempfile.TemporaryDirectory() as folder:
            state = ready()
            choice = next_action(state)
            store = self.store(folder)
            store.pending(choice.intent, 0, 'before.png', choice.expected)
            c = Context(Runner(Settings(), operation='currency_wars_standard'), Mock(), Mock())
            c.last_scene, c.currency_standard_session = state, store
            c.checkpoint, c.sleep = Mock(), Mock()
            with self.assertRaises(AutomationError):
                c.currency_standard_input(state, replace(choice, target=state.tokens[0]))
            original=list(state.tokens)
            state.tokens=[t for t in state.tokens if not normalize(t.text).startswith('uid')]
            state.tokens.append(Token('UID:200000000',.99,(.01,.96,.10,.99)))
            with self.assertRaises(AutomationError):
                c.currency_standard_input(state,choice)
            state.tokens=original
            c.runner.input_epoch += 1
            with self.assertRaises(InputInterrupted):
                c.currency_standard_input(state, choice)
            c.window.click.assert_not_called()

    def test_unwritten_corrupt_or_other_match_record_never_grants_input(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder)
            store.pending('start_standard_a8_40', 0, 'before.png', 'boss_preview')
            store.require_pending('start_standard_a8_40', 0)
            data = json.loads(store.path.read_text(encoding='utf-8'))
            for change in ({'match_id':'a'*32}, {'wealth':50}, {'actions':[]}):
                altered = {**data, **change}
                store.path.write_text(json.dumps(altered), encoding='utf-8')
                with self.assertRaises(AutomationError):
                    store.require_pending('start_standard_a8_40', 0)
            store.path.write_text('{"schema":1,"schema":1}', encoding='utf-8')
            with self.assertRaises(AutomationError):
                StandardSession(store.path)

    def test_pending_actions_cannot_be_repeated_and_failed_write_prevents_authority(self):
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder)
            store.pending('start_standard_a8_40', 0, 'before.png', 'boss_preview')
            with self.assertRaises(AutomationError):
                store.pending('start_standard_a8_40', 0, 'again.png', 'boss_preview')
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder)
            with patch('autohsr.currency_wars_session.replace_file', side_effect=OSError('locked')):
                with self.assertRaises(OSError):
                    store.pending('start_standard_a8_40', 0, 'before.png', 'boss_preview')
            with self.assertRaises(AutomationError):
                store.require_pending('start_standard_a8_40', 0)

    def context(self, folder, states, *, resume=False):
        attempt = Path(folder)/('resume' if resume else 'attempt')
        attempt.mkdir()
        c = SimpleNamespace(settings=Settings(), report=RunReport(operation='currency_wars_standard', run_dir=str(attempt)),
                            runner=SimpleNamespace(currency_resume=resume, input_epoch=0, inactive_duration=0, emit=Mock()),
                            scene_epoch=0, last_scene=None, checkpoint=Mock(), log=Mock(), sleep=Mock())
        c._currency_weekly_checkpoint = lambda: Context._currency_weekly_checkpoint(c)
        pending = list(states)
        def snapshot():
            c.last_scene = pending.pop(0) if pending else c.last_scene
            c.last_scene.tokens = [t for t in c.last_scene.tokens if not normalize(t.text).startswith('uid')]
            c.last_scene.tokens.append(Token('UID:100000000',.99,(.01,.96,.10,.99)))
            c.last_scene.captured_at = time.monotonic()
            return c.last_scene
        c.snapshot = snapshot
        c.evidence = lambda state, label: attempt/(label+'.png')
        def submit(state, choice):
            c.currency_standard_session.require_pending(choice.intent, 0)
        c.currency_standard_input = Mock(side_effect=submit)
        return c

    def locate(self, c):
        c.report.currency_wars = dict(rank_verified=True, rank=8, wealth=40, actions=[])
        return TaskResult('currency_wars','partial','rank ready')

    def test_start_preview_map_verify_each_step_and_environment_stops_for_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.context(folder, [ready(), screen('boss_preview'), screen('plane_map'), screen('environment')])
            with patch('autohsr.currency_wars_standard_flow.locate', self.locate), \
                 patch('autohsr.currency_wars_replay.save_sample'):
                result = run_standard(c)
            self.assertEqual(result.status, 'partial')
            self.assertEqual(c.currency_standard_input.call_count, 3)
            data = c.report.currency_wars
            self.assertTrue(data['start_verified'])
            self.assertEqual(data['status'], 'active')
            self.assertEqual([a['status'] for a in data['actions']], ['verified']*3)
            self.assertEqual(data['page_kind'], 'environment')
            self.assertFalse(data['completion_verified'])
            # A new start cannot overwrite the existing match.
            with self.assertRaises(AutomationError):
                run_standard(c)

    def test_unknown_start_feedback_is_preserved_and_not_retried_on_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.context(folder, [ready(), ready()])
            clock = SimpleNamespace(monotonic=Mock(side_effect=[0, 61]))
            with patch('autohsr.currency_wars_standard_flow.locate', self.locate), \
                 patch('autohsr.currency_wars_replay.save_sample'), patch('autohsr.currency_wars_standard_flow.time', clock):
                run_standard(c)
            c.currency_standard_input.assert_called_once()
            self.assertEqual(c.report.currency_wars['actions'][0]['status'], 'unknown')
            resumed = self.context(folder, [screen('boss_preview')], resume=True)
            with self.assertRaises(AutomationError):
                run_standard(resumed)
            resumed.currency_standard_input.assert_not_called()

    def test_resume_without_matching_active_record_does_not_access_game(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.context(folder, [ready()], resume=True)
            c.snapshot = Mock()
            with self.assertRaises(AutomationError):
                run_standard(c)
            c.snapshot.assert_not_called()
            c.currency_standard_input.assert_not_called()

    def test_loot_resume_requires_two_consistent_disappearance_frames(self):
        from autohsr.tests.test_currency_wars_loot import TARGET
        from autohsr.tests.test_currency_wars_standard_trading import full_board_fixture,hud
        from autohsr.currency_wars_collector import roster_cells
        from autohsr.currency_wars_deployment import _crop
        from autohsr.models import Scene
        # Reward collection now observes the current roster first. Provide a
        # real six-slot layout and explicitly empty roster, while retaining
        # the independent two-frame disappearance assertion below.
        before,_ = full_board_fixture(gold=12,experience=(0,4))
        for cell in roster_cells(before):_crop(before.image,cell.roi)[:] = 0
        hud(before,deployment=(0,3))
        after = Scene(list(before.tokens),before.image.copy())
        before.image[463:515,1765:1817] = 190
        with tempfile.TemporaryDirectory() as folder:
            store = self.store(folder)
            store.data.update(status='active', start_verified=True)
            store.persist()
            c = self.context(folder, [before, after, after], resume=True)
            with patch('autohsr.currency_wars_node.loot_centers', side_effect=lambda s:(TARGET,) if s is before else ()), \
                 patch('autohsr.currency_wars_loot.loot_centers', side_effect=lambda s:(TARGET,) if s is before else ()), \
                 patch('autohsr.currency_wars_collector.first_unit_probe', side_effect=AutomationError('fixture ends after loot')), \
                 patch('autohsr.currency_wars_replay.save_sample'):
                run_standard(c)
            c.currency_standard_input.assert_called_once()
            action = c.report.currency_wars['actions'][0]
            self.assertEqual(action['action'], 'collect_standard_loot')
            self.assertEqual(action['status'], 'verified')
            self.assertEqual(action['target'], list(TARGET))

    def test_unknown_readonly_shop_open_can_be_observed_without_resending(self):
        from autohsr.currency_wars_match import MatchState
        with tempfile.TemporaryDirectory() as folder:
            store=self.store(folder)
            store.data.update(status='active',start_verified=True,
                              pre_shop_snapshot=dict(node='1-1',gold=5,hp=80,level=3))
            action=store.pending('open_standard_shop',0,'before.png','standard_shop_observe')
            action.update(status='unknown',target=['1-1',5,80,3])
            store.persist()
            scene = screen('shop')
            # This fixture proves reconciliation only; without a close target
            # the workflow cannot legitimately dispatch the following action.
            scene.tokens = [t for t in scene.tokens if normalize(t.text) != '收起']
            c=self.context(folder,[scene],resume=True)
            state=MatchState('shop',node='1-1',gold=5,hp=None,level=3)
            with patch('autohsr.currency_wars_match.read_match',return_value=state), \
                 patch('autohsr.currency_wars_replay.save_sample'):
                run_standard(c)
            c.currency_standard_input.assert_not_called()
            saved=c.report.currency_wars['actions'][-1]
            self.assertEqual((saved['status'],saved['original_status']),('verified','unknown'))
            self.assertEqual(saved['reconciliation'],'observed_shop_without_input')

    def test_cli_new_start_and_resume_do_not_save_daily_settings(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/'config.json'
            Settings().save(config)
            original = config.read_bytes()
            for resume in (False, True):
                with patch('autohsr.app.Runner') as runner, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    runner.return_value.run.return_value = dict(status='partial')
                    args = ['--currency-wars-standard', '--config', str(config)] + (['--resume-active-currency'] if resume else [])
                    self.assertEqual(main(args), 1)
                    self.assertEqual(runner.call_args.kwargs['operation'], 'currency_wars_standard')
                    self.assertEqual(runner.call_args.kwargs['currency_resume'], resume)
            self.assertEqual(config.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
