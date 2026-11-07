"""Independent activity and reward observations using the native card templates."""

from time import monotonic
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.daily_training_observe import observe_training, training_observation_receipt
from autohsr.tests.test_reward_only_milestones import training
from autohsr.vision import Vision
from autohsr.workflows import DailyWorkflow


class DailyTrainingObservationTests(TestCase):
    def setUp(self):
        context = SimpleNamespace(settings=Settings(), vision=Vision.__new__(Vision), runner=SimpleNamespace())
        context.template = MethodType(Context.template, context)
        self.workflow = DailyWorkflow(context)

    def observe(self, first, second):
        first.captured_at = monotonic()
        second.captured_at = monotonic()
        return observe_training(self.workflow, (first, second), .85)

    def test_activity_stays_visible_when_a_reached_tier_changes_or_is_missing(self):
        first = training(400, gifts=(400,), claimed=(100, 200, 300))
        changed = training(400, claimed=(100, 200, 300, 400))
        missing = training(400, claimed=(100, 200, 300))
        for name, other in (('changed', changed), ('missing', missing)):
            with self.subTest(case=name):
                result = self.observe(first, other)
                self.assertEqual(result['activity'], 400)
                self.assertIsNone(result['milestones'])
        self.assertIsNone(self.observe(first, training(500, claimed=(100, 200, 300, 400, 500))))

    def test_full_activity_and_claimable_rewards_are_separate(self):
        reached = dict(gifts=(500,), claimed=(100, 200, 300, 400))
        result = self.observe(training(500, **reached), training(500, **reached))
        self.assertEqual(result['activity'], 500)
        self.assertEqual(result['support_task'], 'activity_full')
        self.assertEqual(result['milestones'], dict(claimed=[100, 200, 300, 400], claimable=[500]))
        navigation = dict(target='daily_training', page_verified=True, training_observation=result)
        self.assertEqual(training_observation_receipt(navigation), result)
        self.assertIsNone(training_observation_receipt(dict(navigation, page_verified=False)))
        self.assertIsNone(training_observation_receipt(dict(navigation, training_observation=dict(result, uid='private'))))

    def test_crossing_the_daily_reset_does_not_report_an_opportunity(self):
        with patch('autohsr.daily_training_observe._task_game_day', side_effect=('2026-11-07', '2026-11-08')):
            self.assertIsNone(self.observe(training(400), training(400)))
