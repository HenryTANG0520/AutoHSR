"""Synthetic UID frames only; no real game, accounts, cache, or screenshots."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from autohsr.app import Context, Runner
from autohsr.config import Settings
from autohsr.models import AutomationError, InputInterrupted, Scene, Token
from autohsr.workflow_identity import WorkflowIdentity, account_scope, wrap_window, INPUT_METHODS
from autohsr.workflow_lease import workflow_lease
from autohsr.tests.test_task_workflow import identity_scene, recipe, task


class IdentityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.public = []
        self.scope = WorkflowIdentity(self.root, required=True, publish=self.public.append)

    def context(self, name='first'):
        runner = SimpleNamespace(input_epoch=0, _workflow_identity_state=None)
        return SimpleNamespace(runner=runner, report=SimpleNamespace(run_dir=str(self.root / name)),
                               settings=Settings(), scene_epoch=0)

    def observe(self, context, identity='100000000'):
        time.sleep(.02)  # Distinct real monotonic capture ticks on Windows.
        return self.scope.observe(context, identity_scene(identity))

    def bind(self, context=None, identity='100000000'):
        context = context or self.context()
        self.assertFalse(self.observe(context, identity))
        self.assertTrue(self.observe(context, identity))
        self.scope.require(context)
        return context

    def test_two_fresh_frames_and_private_crops_precede_inputs(self):
        context = self.context()
        raw = Mock()
        with account_scope(self.scope):
            window = wrap_window(context, raw)
            with self.assertRaises(InputInterrupted):
                window.click(.1, .2, None)
            self.assertFalse(self.observe(context))
            with self.assertRaises(InputInterrupted):
                window.click(.1, .2, None)
            self.assertTrue(self.observe(context))
            window.click(.1, .2, None)
        raw.click.assert_called_once()
        state = json.loads((self.root / 'identity/state.json').read_text('utf8'))
        self.assertEqual(len(state['proofs'][0]['sources']), 2)
        for source in state['proofs'][0]['sources']:
            self.assertEqual(hashlib.sha256(Path(source['path']).read_bytes()).hexdigest(), source['sha256'])
        public = json.dumps(self.public)
        self.assertNotIn('100000000', public)
        self.assertNotIn(state['account_key'], public)
        self.assertNotIn('account_key', public)

    def test_every_native_input_method_is_gated_and_metadata_delegates(self):
        context = self.context()
        raw = Mock(hwnd=1234, path='synthetic')
        with account_scope(self.scope):
            window = wrap_window(context, raw)
            for name in INPUT_METHODS:
                with self.subTest(name=name), self.assertRaises(InputInterrupted):
                    getattr(window, name)()
                getattr(raw, name).assert_not_called()
            self.assertEqual(window.hwnd, 1234)
            window.guard()
            raw.guard.assert_called_once()

    def test_same_account_across_contexts_requires_another_pair(self):
        first = self.bind()
        mark = self.scope.mark()
        second = self.context('second')
        with self.assertRaises(InputInterrupted):
            self.scope.require(second)
        self.assertFalse(self.observe(second))
        with self.assertRaises(AutomationError):
            self.scope.require_step(mark)
        self.assertTrue(self.observe(second))
        self.scope.require_step(mark)
        self.assertEqual(self.scope.public()['checked_contexts'], 2)
        self.assertEqual(self.scope.public()['observations'], 2)

    def test_changed_account_latches_without_replacing_original_binding(self):
        first = self.bind()
        before = json.loads((self.root / 'identity/state.json').read_text('utf8'))
        second = self.context('second')
        self.assertFalse(self.observe(second, '200000000'))
        with self.assertRaises(AutomationError):
            self.observe(second, '200000000')
        after = json.loads((self.root / 'identity/state.json').read_text('utf8'))
        self.assertEqual(after['account_key'], before['account_key'])
        self.assertEqual(after['proofs'], before['proofs'])
        self.assertTrue(after['account_changed'])
        self.assertTrue(self.scope.public()['account_changed'])
        for context in (first, second):
            with self.assertRaises(AutomationError):
                self.scope.require(context)

    def test_one_wrong_read_needs_two_original_reads_to_recover(self):
        context = self.bind()
        self.assertFalse(self.observe(context, '200000000'))
        with self.assertRaises(InputInterrupted):
            self.scope.require(context)
        self.assertFalse(self.observe(context))
        self.assertTrue(self.observe(context))
        self.assertFalse(self.scope.public()['account_changed'])

    def test_epoch_change_discards_previous_pair_and_hidden_uid_is_unknown(self):
        context = self.bind()
        context.runner.input_epoch = context.scene_epoch = 1
        self.assertFalse(self.scope.public()['verified'])
        self.assertEqual(self.scope.public()['status'], 'needs_recheck')
        with self.assertRaises(InputInterrupted):
            self.scope.require(context)
        hidden = identity_scene()
        hidden.tokens.clear()
        self.assertFalse(self.scope.observe(context, hidden))
        self.assertFalse(self.observe(context))
        self.assertTrue(self.observe(context))
        state = json.loads((self.root / 'identity/state.json').read_text('utf8'))
        self.assertEqual([source['input_epoch'] for source in state['proofs'][-1]['sources']], [1, 1])

    def test_hidden_uid_in_verified_epoch_retains_native_context(self):
        context = self.bind()
        hidden = identity_scene()
        hidden.tokens.clear()
        self.assertTrue(self.scope.observe(context, hidden))
        self.scope.require(context)
        self.assertEqual(self.scope.public()['observations'], 1)

    def test_low_confidence_partial_and_conflicting_tokens_are_not_guessed(self):
        variants = [Token('UID:100000000', .5, (.01, .96, .15, .99)),
                    Token('UID:1000?', .99, (.01, .96, .15, .99))]
        for token in variants:
            context = self.bind(self.context('case-' + str(len(self.public))))
            scene = identity_scene()
            scene.tokens = [token]
            self.assertFalse(self.scope.observe(context, scene))
            with self.assertRaises(InputInterrupted):
                self.scope.require(context)
            self.assertFalse(self.observe(context))
            self.assertTrue(self.observe(context))
        context = self.context('conflicting')
        scene = identity_scene()
        scene.tokens.append(Token('UID:200000000', .99, (.01, .96, .16, .99)))
        self.assertFalse(self.scope.observe(context, scene))

    def test_duplicate_stale_future_or_old_epoch_frame_cannot_form_proof(self):
        context = self.context()
        scene = identity_scene()
        self.assertFalse(self.scope.observe(context, scene))
        with self.assertRaises(AutomationError):
            self.scope.observe(context, scene)
        for age in (-100, 100):
            frame = identity_scene()
            frame.captured_at = time.monotonic() + age
            with self.assertRaises(AutomationError):
                self.scope.observe(context, frame)
        context.runner.input_epoch = 1
        with self.assertRaises(AutomationError):
            self.scope.observe(context, identity_scene())

    def test_pending_first_epoch_frame_does_not_mix_with_next_epoch(self):
        context = self.context()
        self.assertFalse(self.observe(context))
        context.runner.input_epoch = context.scene_epoch = 1
        self.assertFalse(self.observe(context))
        self.assertTrue(self.observe(context))
        state = json.loads((self.root / 'identity/state.json').read_text('utf8'))
        self.assertEqual([source['input_epoch'] for source in state['proofs'][0]['sources']], [1, 1])

    def test_long_pause_during_initial_pair_starts_a_new_bounded_observation(self):
        context = self.context()
        self.assertFalse(self.observe(context))
        self.scope.state(context).pending_at = time.monotonic() - 100
        context.runner.input_epoch = context.scene_epoch = 2
        self.assertFalse(self.observe(context))
        self.assertTrue(self.observe(context))
        sources = json.loads((self.root / 'identity/state.json').read_text('utf8'))['proofs'][0]['sources']
        self.assertEqual([source['input_epoch'] for source in sources], [2, 2])

    def test_storage_failure_cannot_authorize_inputs_or_silently_rebind(self):
        context = self.context()
        self.assertFalse(self.observe(context))
        with patch.object(self.scope, '_persist', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.observe(context)
        with self.assertRaises(AutomationError):
            self.scope.require(context)
        self.assertEqual(self.scope.public()['status'], 'storage_failed')
        self.assertFalse(self.scope.public()['bound'])

    def test_missing_identity_has_a_finite_observation_limit(self):
        context = self.context()
        with patch('autohsr.workflow_identity.MAX_FRAMES', 1):
            frame = identity_scene()
            frame.tokens.clear()
            self.assertFalse(self.scope.observe(context, frame))
            time.sleep(.02)
            frame = identity_scene()
            frame.tokens.clear()
            with self.assertRaises(AutomationError):
                self.scope.observe(context, frame)
        self.assertFalse(self.scope.public()['verified'])

    def test_only_first_context_may_prepare_known_login_before_binding(self):
        context = self.context()
        frame = identity_scene()
        frame.tokens = [Token('点击进入', .99, (.4, .9, .6, .95))]
        self.assertTrue(self.scope.observe(context, frame))
        self.scope.require(context)
        second = self.context('second')
        frame = identity_scene()
        frame.tokens = [Token('点击进入', .99, (.4, .9, .6, .95))]
        self.assertFalse(self.scope.observe(second, frame))
        with self.assertRaises(InputInterrupted):
            self.scope.require(second)

    def test_bound_account_login_page_never_permits_login_input(self):
        context = self.bind()
        for with_uid in (False, True):
            frame = identity_scene()
            frame.tokens = (frame.tokens if with_uid else []) + [Token('点击进入', .99, (.4, .9, .6, .95))]
            with self.assertRaises(AutomationError):
                self.scope.observe(context, frame)
            with self.assertRaises(InputInterrupted):
                self.scope.require(context)

    def test_real_context_waits_for_pair_then_blocks_after_epoch_change(self):
        runner = SimpleNamespace(settings=Settings(daily_synthesis=False), report=SimpleNamespace(
            run_dir=str(self.root / 'native'), operation='daily'), input_epoch=0,
            checkpoint=Mock(), log=Mock())
        raw = Mock()
        raw.capture.return_value = (np.zeros((100, 200, 3), dtype=np.uint8), None)
        vision = Mock()
        vision.read.side_effect = lambda image, geometry: identity_scene()
        with account_scope(self.scope):
            context = Context(runner, raw, vision)
            # Context.checkpoint delegates to Runner; use the real capture loop.
            context.snapshot()
            self.assertEqual(raw.capture.call_count, 2)
            context.window.key('esc')
            runner.input_epoch = 1
            with self.assertRaises(InputInterrupted):
                context.window.key('esc')
            context.snapshot()
            self.assertEqual(raw.capture.call_count, 4)
        self.assertEqual(raw.key.call_count, 1)

    def test_cross_task_switch_preserves_first_daily_and_blocks_second_actions(self):
        from autohsr.tests.test_task_workflow import WorkflowTests
        case = WorkflowTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.accounts = ['100000000', '200000000']
        report = case.runner(recipe(task('daily'), task('du', 'differential_universe'))).run()
        self.assertEqual(report.status, 'partial')
        self.assertEqual(len(case.calls), 1)
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.stamina_spent, 120)
        self.assertTrue(report.workflow['identity']['account_changed'])
        self.assertIn('账号', report.workflow['steps'][1]['error'])

    def test_identity_mismatch_leaves_original_daily_budget_untouched(self):
        from autohsr.tests.test_runner_recovery import RunnerRecoveryTests
        workflow = SimpleNamespace(ensure_main=Mock(), battle=Mock())
        context, find = RunnerRecoveryTests.fixture(self, self.root, workflow)
        ledger = self.root / 'runs/battle-session.json'
        ledger.parent.mkdir()
        ledger.write_text(json.dumps(dict(version=1, spent=120, pending=0, limit=240, status='success')), 'utf8')
        original = ledger.read_bytes()
        self.bind()
        settings = Settings(assignments=False, battle=True, daily=False)
        runner = Runner(settings)
        context.runner, context.settings, context.report, context.scene_epoch = runner, settings, runner.report, 0
        context.snapshot.side_effect = lambda: identity_scene('200000000')
        context.checkpoint, context.sleep = runner.checkpoint, time.sleep
        with workflow_lease(), account_scope(self.scope):
            report = runner.run()
        self.assertEqual(report.status, 'failed')
        self.assertEqual(ledger.read_bytes(), original)
        workflow.battle.assert_not_called()
        self.assertEqual(find.call_count, 1)

    def test_old_pending_budget_still_blocks_before_game_or_identity_capture(self):
        from autohsr.tests.test_runner_recovery import RunnerRecoveryTests
        context, find = RunnerRecoveryTests.fixture(self, self.root, SimpleNamespace(ensure_main=Mock()))
        ledger = self.root / 'runs/battle-session.json'
        ledger.parent.mkdir()
        ledger.write_text(json.dumps(dict(version=1, spent=0, pending=10, limit=240, status='partial')), 'utf8')
        original = ledger.read_bytes()
        with workflow_lease(), account_scope(self.scope):
            report = Runner(Settings(assignments=False, battle=True, daily=False)).run()
        self.assertEqual(report.status, 'failed')
        self.assertEqual(ledger.read_bytes(), original)
        find.assert_not_called()
        context.snapshot.assert_not_called()

    def test_historical_report_without_current_observation_cannot_complete_step(self):
        mark = self.scope.mark()
        with self.assertRaises(AutomationError):
            self.scope.require_step(mark)
        self.assertFalse(self.scope.has_step_proof(mark))
        context = self.bind()
        self.scope.require_step(mark)
        new_mark = self.scope.mark()
        with self.assertRaises(AutomationError):
            self.scope.require_step(new_mark)

    def test_deleted_prior_crop_blocks_next_context_without_rebinding(self):
        self.bind()
        path = self.root / 'identity/state.json'
        original = path.read_bytes()
        data = json.loads(original)
        Path(data['proofs'][0]['sources'][0]['path']).unlink()
        with self.assertRaises(AutomationError):
            self.scope.state(self.context('next'))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(self.scope.public()['status'], 'evidence_invalid')

    def test_changed_state_and_changed_crop_cannot_be_saved_as_new_proof(self):
        for name in ('state', 'crop'):
            scope = WorkflowIdentity(self.root / name, required=True)
            context = self.context(name)
            time.sleep(.02)
            self.assertFalse(scope.observe(context, identity_scene()))
            time.sleep(.02)
            self.assertTrue(scope.observe(context, identity_scene()))
            state_path = self.root / name / 'identity/state.json'
            data = json.loads(state_path.read_text('utf8'))
            target = state_path if name == 'state' else Path(data['proofs'][0]['sources'][0]['path'])
            target.write_bytes(b'synthetic tampering')
            with self.assertRaises(AutomationError):
                scope.require_step(0)
            self.assertEqual(target.read_bytes(), b'synthetic tampering')
            self.assertFalse(scope.public()['verified'])
