"""Independent DU rewards use task-tree contracts, fake workers and temp files."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autohsr.config import Settings
from autohsr.models import RunReport
from autohsr.task_workflow import GAME_TASKS, WorkflowError, compile_recipe, task_spec
from autohsr.task_workflow_run import TaskWorkflowRunner
from autohsr.tests import test_plan_sequence_scope as lease_fixtures
from autohsr.tests import test_task_workflow as identity_fixtures
from autohsr.workflow_lease import require_workflow_access


def task(identity, operation='du_rewards', **params):
    return dict(id=identity, type='task', task=operation, params=params)


def recipe(*nodes):
    return dict(version=1, name='合成差分领奖任务', steps=list(nodes))


def packet(use=False, *, status='complete', verified=True):
    return dict(schema=1, operation='du_rewards', status=status, rewards_verified=verified,
        battle_started=False, use_cassettes=use, claims=[dict(category='fitting', status='verified')],
        actions=[], observations=[], remaining_categories=[],
        requested_categories=['拟合等级', '稳态数组', '可能性画廊'] + (['月下奇谭'] if use else []),
        skipped_optional_categories=[] if use else ['月下奇谭'], all_notifications_cleared=False,
        cassettes=dict(initial_balance=None, limit=0, spent_verified=0))


class DURewardsWorkflowTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        kernel = lease_fixtures.MemoryKernel()
        self.kernel = kernel
        for target, value in (('autohsr.workflow_lease._kernel', lambda: kernel),
                ('autohsr.workflow_lease.C.set_last_error', kernel.set_error),
                ('autohsr.workflow_lease.C.get_last_error', kernel.get_error)):
            mock = patch(target, value, create=True);mock.start();self.addCleanup(mock.stop)
        mock = patch.object(TaskWorkflowRunner, '_hotkeys', lambda runner: runner._end.wait())
        mock.start();self.addCleanup(mock.stop)
        self.settings = Settings(overlay_logs=False)
        self.calls, self.responses, self.accounts = [], [], []
        self.after = None

    def runner(self, document):
        self.owner = TaskWorkflowRunner(self.settings, document, root=self.root / 'workflow',
            base_dir=self.root, runner_factory=self.factory)
        return self.owner

    def factory(self, settings, emit, **options):
        owner = self
        class Child:
            input_epoch = 0
            stop_requested = False
            def stop(self):self.stop_requested = True
            def toggle_pause(self):return False
            def run(self):
                require_workflow_access()
                intent = json.loads((Path(owner.owner.report.run_dir) / 'steps.jsonl').read_text('utf8').splitlines()[-1])
                owner.assertEqual(intent['event'], 'intent')
                owner.calls.append((replace(settings), deepcopy(options)))
                folder = owner.root / ('child-' + str(len(owner.calls)));folder.mkdir()
                operation = options['operation']
                value = RunReport(operation=operation, status='success', report_saved=True, run_dir=str(folder)).to_dict()
                if operation == 'du_rewards':value['du_rewards'] = packet(options['du_use_cassettes'])
                if operation == 'daily':value.update(daily_verified=True, stamina_spent=40)
                if operation == 'differential_universe':value['differential_universe'] = dict(completed_runs=1, marker='original DU')
                overrides = owner.responses.pop(0) if owner.responses else {}
                value.update(overrides)
                from autohsr.workflow_identity import _scope
                scope = _scope.get()
                account = owner.accounts.pop(0) if owner.accounts else '100000000'
                context = SimpleNamespace(runner=self, report=SimpleNamespace(run_dir=str(folder)), settings=settings, scene_epoch=0)
                scope.observe(context, identity_fixtures.identity_scene(account))
                scope.observe(context, identity_fixtures.identity_scene(account))
                (folder / 'report.json').write_text(json.dumps(value, ensure_ascii=False), 'utf8')
                if owner.after:owner.after(value)
                return value
        return Child()

    def test_compile_and_spec_default_off_do_not_enable_legacy_rewards_or_daily(self):
        self.settings.differential_universe_rewards = True
        self.settings.differential_universe_daily = True
        node = task('reward')
        compiled = compile_recipe(recipe(node))
        current, options = task_spec(self.settings, node, self.root)
        self.assertIn('du_rewards', GAME_TASKS)
        self.assertEqual(options, dict(operation='du_rewards', du_use_cassettes=False))
        self.assertIsNot(current, self.settings)
        self.assertTrue(current.differential_universe_rewards)
        self.assertTrue(current.differential_universe_daily)
        self.assertEqual(compiled.profile['du_rewards_calls'], 1)
        self.assertEqual(compiled.profile['du_runs'], 0)
        self.assertEqual(compiled.profile['daily_calls'], 0)
        _, enabled = task_spec(self.settings, task('reward', use_cassettes=True), self.root)
        self.assertIs(enabled['du_use_cassettes'], True)
        for params in ({'use_cassettes': 1}, {'use_cassettes': 'true'}, {'resume': True}, {'runs': 2}, {'mode': 'periodic'}):
            with self.subTest(params=params), self.assertRaises(WorkflowError):
                compile_recipe(recipe(task('bad', **params)))

    def test_static_reservation_rejects_duplicate_repeat_and_selected_subtree_bypass(self):
        duplicates = recipe(task('a'), task('b', use_cassettes=True))
        loop = recipe(dict(id='loop', type='for', count=2, steps=[task('reward')]))
        while_loop = recipe(dict(id='before', type='wait', seconds=0),
            dict(id='again', type='while', max_iterations=2,
                condition=dict(step='before', field='status', op='eq', value='success'), steps=[task('reward')]))
        for document in (duplicates, loop, while_loop):
            with self.subTest(document=document), self.assertRaises(WorkflowError):compile_recipe(document)
        with self.assertRaises(WorkflowError):compile_recipe(duplicates, selected_path='0')
        self.assertEqual(compile_recipe(recipe(dict(task('disabled'), enabled=False), task('a'))).profile['du_rewards_calls'], 1)

    def test_exclusive_branches_share_one_reservation(self):
        condition = dict(step='before', field='status', op='eq', value='success')
        document = recipe(dict(id='before', type='wait', seconds=0), dict(id='branch', type='if',
            condition=condition, steps=[task('left')], else_steps=[task('right', use_cassettes=True)]))
        self.assertEqual(compile_recipe(document).profile['du_rewards_calls'], 1)

    def test_old_and_disabled_reward_profiles_keep_the_exact_frozen_manifest_key_set(self):
        expected = dict(daily_calls=0, du_calls=0, currency_calls=0, du_runs=0, currency_games=0, executions=1)
        self.assertEqual(compile_recipe(recipe(dict(id='local', type='wait', seconds=0))).profile, expected)
        self.assertEqual(compile_recipe(recipe(dict(task('off'), enabled=False))).profile, expected)
        daily = dict(expected, daily_calls=1)
        self.assertEqual(compile_recipe(recipe(task('daily', 'daily', tasks=['daily']))).profile, daily)
        selected = recipe(task('reward'), dict(id='local', type='wait', seconds=0))
        self.assertEqual(compile_recipe(selected, selected_path='1').profile, expected)
        self.assertEqual(compile_recipe(selected, selected_path='0').profile['du_rewards_calls'], 1)

    def test_only_coexecuting_legacy_and_new_cassette_owners_conflict(self):
        legacy = task('old', 'differential_universe', rewards=True)
        paid = task('new', use_cassettes=True)
        with self.assertRaises(WorkflowError):compile_recipe(recipe(legacy, paid))
        self.assertEqual(compile_recipe(recipe(legacy, task('free'))).profile['du_rewards_calls'], 1)
        self.assertEqual(compile_recipe(recipe(task('old', 'differential_universe'), paid)).profile['du_rewards_calls'], 1)
        branch = dict(id='choose', type='if',
            condition=dict(step='before', field='status', op='eq', value='success'),
            steps=[legacy], else_steps=[paid])
        self.assertEqual(compile_recipe(recipe(dict(id='before', type='wait', seconds=0), branch)).profile['du_rewards_calls'], 1)
        self.assertEqual(compile_recipe(recipe(dict(legacy, enabled=False), paid)).profile['du_rewards_calls'], 1)
        # A saved legacy switch does not change the DU task's explicit default.
        self.settings.differential_universe_rewards = True
        settings, options = task_spec(self.settings, task('du', 'differential_universe'), self.root)
        self.assertFalse(settings.differential_universe_rewards)
        self.assertEqual(options['operation'], 'differential_universe')
        # No independent task: existing selected-subtree semantics are intact.
        old_only = recipe(legacy, task('old2', 'differential_universe', rewards=True))
        self.assertEqual(compile_recipe(old_only, selected_path='0').profile['du_calls'], 1)

    def test_daily_and_du_then_rewards_preserve_separate_original_results(self):
        result = self.runner(recipe(task('daily', 'daily', tasks=['daily']),
            task('du', 'differential_universe'), task('reward'))).run()
        self.assertEqual(result.status, 'success')
        self.assertTrue(result.daily_verified)
        self.assertEqual(result.stamina_spent, 40)
        self.assertEqual(result.differential_universe, dict(completed_runs=1, marker='original DU'))
        self.assertEqual(result.du_rewards, packet())
        entry = result.workflow['steps'][-1]
        self.assertEqual(entry['du_rewards'], packet())
        self.assertEqual(entry['facts'], dict(status='success', du_rewards_verified=True))
        self.assertIsNot(entry['du_rewards'], result.du_rewards)
        self.assertEqual(result.weekly_plan, {})
        self.assertTrue(result.workflow['identity']['bound'])
        self.assertEqual([options['operation'] for _, options in self.calls], ['daily', 'differential_universe', 'du_rewards'])
        self.assertIs(self.calls[-1][1]['du_use_cassettes'], False)
        raw = Path(entry['source']['path']).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), entry['source']['sha256'])
        self.assertEqual(json.loads(raw)['du_rewards'], entry['du_rewards'])
        self.assertEqual(json.loads((Path(result.run_dir) / 'report.json').read_text('utf8')), result.to_dict())
        self.assertEqual(self.kernel.handles, set())

    def test_explicit_cassettes_and_partial_claims_are_preserved_but_block_later_game(self):
        partial = packet(True, status='partial', verified=False)
        self.responses = [dict(status='partial', du_rewards=partial)]
        first = dict(task('reward', use_cassettes=True), on_failure='continue')
        result = self.runner(recipe(first, dict(id='local', type='wait', seconds=0),
            task('later', 'differential_universe'))).run()
        self.assertEqual(result.status, 'partial')
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result.du_rewards, partial)
        self.assertEqual(result.workflow['steps'][0]['du_rewards'], partial)
        self.assertEqual(result.workflow['steps'][0]['facts'], dict(status='partial', du_rewards_verified=False))
        self.assertTrue(result.workflow['input_blocked'])
        self.assertEqual(result.workflow['steps'][1]['status'], 'success')

    def test_free_requested_scope_can_complete_with_optional_moon_marked_and_continue_game(self):
        result = self.runner(recipe(task('reward'), task('later', 'differential_universe'))).run()
        self.assertEqual(result.status, 'success')
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(result.du_rewards['requested_categories'], ['拟合等级', '稳态数组', '可能性画廊'])
        self.assertEqual(result.du_rewards['skipped_optional_categories'], ['月下奇谭'])
        self.assertFalse(result.du_rewards['all_notifications_cleared'])
        self.assertTrue(result.workflow['steps'][0]['facts']['du_rewards_verified'])

    def test_missing_duplicate_or_unrequested_category_cannot_claim_success(self):
        cases = [(False, ['拟合等级', '稳态数组']),
                 (False, ['拟合等级', '稳态数组', '稳态数组']),
                 (False, ['拟合等级', '稳态数组', '可能性画廊', '月下奇谭']),
                 (True, ['拟合等级', '稳态数组', '可能性画廊'])]
        for index, (use, categories) in enumerate(cases):
            with self.subTest(use=use, categories=categories):
                self.root = self.root / ('category-' + str(index));self.root.mkdir()
                self.calls = []
                value = packet(use);value['requested_categories'] = categories
                self.responses = [dict(du_rewards=value)]
                result = self.runner(recipe(dict(task('reward', use_cassettes=use), on_failure='continue'),
                    task('later', 'differential_universe'))).run()
                self.assertEqual(result.status, 'partial')
                self.assertEqual(len(self.calls), 1)
                self.assertTrue(result.workflow['input_blocked'])
                self.assertEqual(result.workflow['steps'][0]['du_rewards'], value)

    def test_zero_input_abort_keeps_its_native_failure_and_original_packet(self):
        value = packet(status='abort_before_input', verified=False)
        value.update(safe_to_restart=True, claims=[], actions=[], obligation=None)
        self.responses = [dict(status='failed', du_rewards=value)]
        result = self.runner(recipe(dict(task('reward'), on_failure='continue'),
            task('later', 'differential_universe'))).run()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.du_rewards, value)
        entry = result.workflow['steps'][0]
        self.assertEqual(entry['status'], 'failed')
        self.assertEqual(entry['facts'], dict(status='failed', du_rewards_verified=False))
        self.assertNotIn('error', entry)

    def test_unknown_failed_or_false_success_cannot_advance_game(self):
        for issue in ('unknown', 'failed', 'incomplete', 'truthy', 'battle', 'permission'):
            with self.subTest(issue=issue):
                root = self.root / issue;root.mkdir()
                self.root = root
                value = packet()
                status = 'success'
                if issue in ('unknown', 'failed'):status = 'partial' if issue == 'unknown' else 'failed';value.update(status='unknown', rewards_verified=False)
                elif issue == 'incomplete':value.update(status='partial', rewards_verified=False)
                elif issue == 'truthy':value['rewards_verified'] = 1
                elif issue == 'battle':value['battle_started'] = True
                else:value['use_cassettes'] = True
                self.calls = [];self.responses = [dict(status=status, du_rewards=value)]
                result = self.runner(recipe(dict(task('reward'), on_failure='continue'), task('later', 'differential_universe'))).run()
                self.assertEqual(result.status, 'partial')
                self.assertEqual(len(self.calls), 1)
                self.assertEqual(result.workflow['steps'][0]['du_rewards'], value)
                self.assertTrue(result.workflow['input_blocked'])

    def test_rewards_never_infer_du_victories_or_periodic_score_from_unused_fields(self):
        runner = self.runner(recipe(task('reward')))
        raw = dict(operation='du_rewards', status='success', du_rewards=packet(),
            differential_universe=dict(completed_runs=99, score_rewards_verified=True),
            currency_wars=dict(victories=99, rewards_verified=True))
        self.assertEqual(runner._facts(raw), dict(status='success', du_rewards_verified=True))
        runner._copy_totals(raw)
        self.assertEqual(runner.report.differential_universe, {})
        self.assertEqual(runner.report.currency_wars, {})
        self.assertEqual(runner.report.weekly_plan, {})

    def test_source_tampering_and_changed_account_block_the_formal_game_path(self):
        self.after = lambda value: Path(value['run_dir'], 'report.json').write_text('{}', 'utf8')
        result = self.runner(recipe(task('reward'), task('later', 'differential_universe'))).run()
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.du_rewards, {})
        self.assertNotIn('source', result.workflow['steps'][0])
        self.assertEqual(self.kernel.handles, set())
        self.after = None;self.calls = [];self.accounts = ['100000000', '200000000']
        self.root = self.root / 'changed-account';self.root.mkdir()
        result = self.runner(recipe(task('du', 'differential_universe'), task('reward'))).run()
        self.assertEqual(result.status, 'partial')
        self.assertEqual(result.differential_universe['completed_runs'], 1)
        self.assertEqual(result.du_rewards, {})
        self.assertEqual(self.kernel.handles, set())


if __name__ == '__main__':
    unittest.main()
