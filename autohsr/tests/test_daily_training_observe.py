"""Independent activity and reward observations using the native card templates."""

from dataclasses import replace
from time import monotonic
from types import MethodType, SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from autohsr.app import Context
from autohsr.config import Settings
from autohsr.daily_training_observe import observe_training, training_condition_facts, training_observation_receipt
from autohsr.tests.test_daily_support import training as captured_support_card
from autohsr.tests.test_du_team import fixture
from autohsr.tests.test_reward_only_milestones import training
from autohsr.tests.test_workflow_navigation import badge
from autohsr.vision import Vision
from autohsr.workflows import DailyWorkflow


class DailyTrainingObservationTests(TestCase):
    def setUp(self):
        context = SimpleNamespace(settings=Settings(), vision=Vision.__new__(Vision), runner=SimpleNamespace())
        context.template = MethodType(Context.template, context)
        self.workflow = DailyWorkflow(context)

    def observe(self, first, second, *, version=None):
        first.captured_at = monotonic()
        second.captured_at = monotonic()
        return observe_training(self.workflow, (first, second), .85, client_version=version)

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

    def test_synthesis_condition_preserves_completed_missing_and_conflicting_cards(self):
        card = dict(task='synthesis', progress=1, target=1, points=100, state='claimable')
        observed = dict(game_day='2026-11-08', activity=400, visible_tasks=[card], synthesis_task='unknown')
        self.assertEqual(training_condition_facts(observed, '4.6.0'),
                         dict(training_activity=400, synthesis_needed=False))
        self.assertEqual(training_condition_facts(dict(observed, synthesis_task='available'), '4.6.0'),
                         dict(training_activity=400))
        scan = dict(game_day='2026-11-08', activity=400, state='unverified',
                    cards=[dict(card, progress=0, state='pending')])
        self.assertEqual(training_condition_facts(scan, '4.6.0'), dict(training_activity=400))
        del scan['game_day']
        self.assertEqual(training_condition_facts(scan, '4.6.0'), {})

    def test_known_cards_keep_progress_reward_and_claim_state_separate(self):
        captured = captured_support_card().tokens
        support = [token for token in captured if token.within((.325, .375, .475, .81))]
        photo = [badge('拍照1次', .22, .48), badge('进度：', .174, .40, width=.014),
                 badge('0／1', .202, .40, width=.013), badge('＋100', .22, .64), badge('进行中', .22, .76)]
        power = [badge('累计消耗120点开拓力', .56, .48), badge('进度120/120', .56, .40),
                 badge('+200', .56, .64), badge('领取', .56, .76)]
        labels = [*photo, *support, *power]
        result = self.observe(training(300, labels=labels), training(300, labels=labels), version='4.6.0')
        self.assertEqual(result['visible_tasks'], [
            dict(task='photo', progress=0, target=1, points=100, state='pending'),
            dict(task='support_win', progress=0, target=1, points=200, state='pending'),
            dict(task='spend_power', progress=120, target=120, points=200, state='claimable'),
        ])
        nav = dict(target='daily_training', page_verified=True, client_version='4.6.0', training_observation=result)
        self.assertEqual(training_observation_receipt(nav), result)
        self.assertIsNone(training_observation_receipt(dict(nav, client_version='4.7.0')))
        fabricated = [dict(result['visible_tasks'][0], state='claimed')]
        self.assertIsNone(training_observation_receipt(dict(nav, training_observation=dict(result, visible_tasks=fabricated))))

    def test_partial_moving_or_ambiguous_card_does_not_publish(self):
        photo = [badge('拍照1次', .22, .48), badge('进度0/1', .22, .40),
                 badge('+100', .22, .64), badge('进行中', .22, .76)]
        moved = [replace(token, box=(token.box[0]+.175, token.box[1], token.box[2]+.175, token.box[3]))
                 for token in photo]
        variants = (
            [*photo[:1], badge('进度0/10', .22, .40), *photo[2:]],
            [*photo[:2], replace(photo[2], score=.80), photo[3]],
            [*photo[:3], badge('已领取', .22, .76)],
            [*photo, badge('领取', .22, .76)],
            [*photo, badge('活跃度', .259, .68)],
            moved,
            [*photo, *moved],
        )
        for labels in variants:
            with self.subTest(labels=[token.text for token in labels]):
                result = self.observe(training(300, labels=photo), training(300, labels=labels), version='4.6.0')
                self.assertEqual(result['activity'], 300)
                self.assertNotIn('visible_tasks', result)

    def test_captured_four_card_layout_with_separate_activity_captions(self):
        result = self.observe(fixture('daily_survival_badge'), fixture('daily_survival_badge'), version='4.6.0')
        self.assertEqual(result['visible_tasks'], [
            dict(task='assignments', progress=1, target=1, points=100, state='activity_full'),
            dict(task='defeat_enemies', progress=20, target=20, points=100, state='activity_full'),
            dict(task='spend_power', progress=0, target=120, points=200, state='activity_full'),
            dict(task='support_win', progress=0, target=1, points=200, state='activity_full'),
        ])
