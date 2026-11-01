import copy
import unittest

from autohsr.ux import plan_result


def report(tasks=(), **values):
    data = dict(operation="plan", status="success", report_saved=True, daily_verified=False,
                stamina_spent=0, stamina_pending=0, immersifiers_spent=0, immersifiers_pending=0,
                results=[], weekly_plan=dict(daily_tasks=list(tasks), status="not_due",
                mode="differential_universe", week="2026-10-26", due_at="2026-10-29T03:00:00+00:00",
                message="周常未到计划时间。"))
    data.update(values)
    return data


class PlanFeedbackTests(unittest.TestCase):
    def test_noop_is_not_completion_or_an_unverified_daily(self):
        data = report()
        before = copy.deepcopy(data)
        label, text = plan_result(data)
        self.assertEqual(label, "本次无需执行")
        self.assertIn("周常未到期", text)
        self.assertIn("2026-10-29 11:00（北京时间）", text)
        self.assertNotIn("完成", text)
        self.assertNotIn("实训", text)
        self.assertNotIn("开拓力", text)
        self.assertNotIn("游戏保留", text)
        self.assertEqual(data, before)

    def test_requested_reward_and_unrequested_costs_have_different_visibility(self):
        data = report(("daily",), daily_verified=True)
        label, text = plan_result(data)
        self.assertEqual(label, "日常已完成")
        self.assertIn("实训奖励已核实", text)
        self.assertIn("周常未到期", text)
        self.assertNotIn("开拓力", text)
        data["daily_verified"] = False
        self.assertIn("实训奖励未核实", plan_result(data)[1])

    def test_partial_result_preserves_verified_costs_pending_costs_and_recovery(self):
        data = report(("battle", "daily"), status="partial", daily_verified=True, stamina_spent=120,
                      stamina_pending=10, immersifiers_spent=2, immersifiers_pending=None,
                      battle_completed=12, battle_requested=24, error="原图无法核实结算。",
                      safe_next="先核对原报告与当前结算。")
        data["weekly_plan"].update(status="needs_review", message="周常尚未完成。")
        before = copy.deepcopy(data)
        label, text = plan_result(data)
        self.assertEqual(label, "部分完成")
        for value in ("12/24 次", "已确认 120 开拓力", "10 开拓力待核对", "已确认 2 沉浸器",
                      "沉浸器待核对", "实训奖励已核实", "原图无法核实结算", "先核对原报告"):
            self.assertIn(value, text)
        self.assertEqual(data, before)

    def test_unrequested_but_recorded_cost_and_positive_proof_are_never_hidden(self):
        data = report(daily_verified=True, stamina_spent=30, stamina_pending=None)
        label, text = plan_result(data)
        self.assertEqual(label, "结果待核对")
        self.assertIn("已确认 30 开拓力", text)
        self.assertIn("开拓力待核对", text)
        self.assertIn("实训奖励已核实", text)

    def test_unknown_costs_do_not_become_zero(self):
        text = plan_result(report(status="stopped", stamina_spent=None, stamina_pending=-1,
                                  immersifiers_spent=None, immersifiers_pending=None))[1]
        self.assertIn("开拓力消耗未记录", text)
        self.assertIn("沉浸器消耗未记录", text)
        self.assertIn("开拓力待核对", text)
        self.assertNotIn("已确认 0", text)

    def test_unsaved_success_cannot_get_a_completion_label(self):
        data = report(report_saved=False)
        data["weekly_plan"].update(status="complete", message="本周演算完成。")
        self.assertEqual(plan_result(data)[0], "结果待核对")

    def test_frozen_week_and_reward_boundary_survive_completion(self):
        data = report()
        data["weekly_plan"].update(status="complete", message="本周 1 局已完成；周积分奖励未核实。")
        label, text = plan_result(data)
        self.assertEqual(label, "周常演算完成")
        self.assertIn("2026-10-26 当周 1 局", text)
        self.assertIn("周积分奖励未核实", text)
        self.assertNotIn("实训", text)

    def test_legacy_or_invalid_scope_uses_the_original_feedback(self):
        for scope in (None, False, {}, "daily", ["daily", "daily"], [True], ["unknown"]):
            with self.subTest(scope=scope):
                data = report()
                data["weekly_plan"]["daily_tasks"] = scope
                self.assertIsNone(plan_result(data))
        self.assertIsNone(plan_result(dict(operation="daily", weekly_plan=dict(daily_tasks=[]))))

    def test_exit_result_is_only_shown_when_it_was_actually_reported(self):
        data = report(results=[dict(task="close_game", status="failed", detail="窗口仍存在。")])
        self.assertIn("游戏退出未确认", plan_result(data)[1])

    def test_unzoned_deadline_is_not_reinterpreted_as_beijing_time(self):
        data = report()
        data["weekly_plan"]["due_at"] = "2026-10-29T11:00:00"
        text = plan_result(data)[1]
        self.assertNotIn("北京时间", text)
        self.assertIn("周常未到计划时间", text)
