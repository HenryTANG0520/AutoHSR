import unittest

from autohsr.dungeons import BY_KEY
from autohsr.ux import planned_battle_metrics, reported_battle_metrics


class HomeFeedbackTests(unittest.TestCase):
    def test_regular_cost_is_an_estimate_not_an_observed_balance(self):
        self.assertEqual(planned_battle_metrics(BY_KEY["calyx_golden"], "24"), ("24 次", "预计 240 开拓力"))

    def test_existing_immersifiers_make_stamina_a_maximum(self):
        count, cost = planned_battle_metrics(BY_KEY["planar"], "2")
        self.assertEqual(count, "2 次")
        self.assertIn("最多 80 开拓力", cost)
        self.assertIn("已有沉浸器优先", cost)
        self.assertNotIn("预计", cost)

    def test_invalid_count_never_becomes_a_negative_or_excessive_cost(self):
        for value in ("", "bad", "0", "-2", "25", None):
            self.assertEqual(planned_battle_metrics(BY_KEY["calyx_golden"], value), ("— 次", "次数待填写"))

    def test_disabled_battle_has_no_zero_cost_badge(self):
        self.assertIsNone(planned_battle_metrics(BY_KEY["calyx_golden"], "bad", False))

    def test_result_shows_both_resources_without_using_current_form(self):
        metrics = reported_battle_metrics(dict(battle_completed=2, battle_requested=2, stamina_spent=40, immersifiers_spent=1))
        self.assertEqual(metrics, ("2/2 次", "已用 40 开拓力\n沉浸器 1"))

    def test_missing_counts_or_costs_do_not_become_zero(self):
        self.assertEqual(reported_battle_metrics({}), ("— 次", "消耗未记录"))
        self.assertEqual(reported_battle_metrics(dict(battle_completed=2)), ("2 次", "消耗未记录"))
        self.assertEqual(reported_battle_metrics(dict(battle_requested=2, stamina_spent=0)), ("— 次", "已用 0 开拓力"))

    def test_inconsistent_count_is_not_presented_as_completion(self):
        for value in (-1, True, 3, "2"):
            self.assertEqual(reported_battle_metrics(dict(battle_completed=value, battle_requested=2))[0], "— 次")

    def test_pending_either_resource_is_prominent(self):
        for field in ("stamina_pending", "immersifiers_pending"):
            for value in (1, None, True, -1):
                self.assertEqual(reported_battle_metrics(dict(stamina_spent=40, **{field:value}))[1], "消耗待核对")

    def test_zero_and_unknown_immersifiers_are_different(self):
        self.assertEqual(reported_battle_metrics(dict(stamina_spent=0, immersifiers_spent=0))[1], "已用 0 开拓力")
        self.assertIn("沉浸器待核对", reported_battle_metrics(dict(stamina_spent=0, immersifiers_spent=None))[1])


if __name__ == "__main__":
    unittest.main()
