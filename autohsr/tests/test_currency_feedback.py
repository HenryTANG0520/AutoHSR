import copy
import unittest

from autohsr.currency_feedback import observation, result
from autohsr.ux import standard_activity, reward_delivery_verified


def delivered_reward():
    return dict(mode="standard_development", action_status="reward_verified", start_verified=True,
        reward=dict(status="verified", origin_action_id=0, claim_action_id=1),
        actions=[dict(id=0, status="verified", reward_verified=True),
                 dict(id=1, status="verified", reward_verified=True,
                      reward_effect=dict(unit="阿格莱雅", unit_verified=True, other_roster_verified=True, inventory_checked=True))])


class CurrencyFeedbackTests(unittest.TestCase):
    def test_confirmed_click_without_unit_delivery_is_still_pending(self):
        data = delivered_reward()
        data["reward"]["status"] = "unit_verifying"
        data["actions"][1]["reward_verified"] = False
        self.assertEqual(standard_activity(data), "核验补给角色")
        self.assertFalse(reward_delivery_verified(data))
        self.assertIn("整局未完成", observation(data))
        self.assertNotIn("奖励交付已核实", observation(data))

    def test_awaiting_and_wrong_roster_are_distinct(self):
        for state, label in (("awaiting", "核对奖励交付"), ("unit_mismatch", "补给角色不符")):
            data = delivered_reward()
            data["reward"]["status"] = state
            self.assertEqual(standard_activity(data), label)
            self.assertFalse(reward_delivery_verified(data))

    def test_verified_reward_requires_both_linked_action_flags(self):
        for index in (0, 1):
            data = delivered_reward()
            data["actions"][index]["reward_verified"] = False
            self.assertEqual(standard_activity(data), "奖励交付待核对")
        data["reward"]["claim_action_id"] = 7
        self.assertFalse(reward_delivery_verified(data))

    def test_unit_delivery_requires_independent_inventory_and_roster_checks(self):
        for field in ("unit_verified", "inventory_checked", "other_roster_verified"):
            data = delivered_reward()
            data["actions"][1]["reward_effect"][field] = False
            self.assertFalse(reward_delivery_verified(data))
        data = delivered_reward()
        self.assertTrue(reward_delivery_verified(data))
        self.assertEqual(standard_activity(data), "奖励交付已核实")
        self.assertIn("整局未完成", observation(data))

    def test_box_and_cash_without_a_unit_do_not_require_roster_growth(self):
        data = delivered_reward()
        data["actions"][1]["reward_effect"].update(unit="", other_roster_verified=False)
        self.assertTrue(reward_delivery_verified(data))

    def test_readonly_result_distinguishes_unknown_money_from_observed_zero(self):
        data = dict(page_kind="preparation", page_verified=True, match=dict(node="2-1", gold=0, level=None, deployment=[0, 8]))
        title, detail = result(dict(operation="currency_wars", status="partial", currency_wars=data))
        self.assertEqual(title, "只读识别结束")
        self.assertIn("金币 0", detail)
        self.assertIn("等级 未识别", detail)
        self.assertNotIn("全部完成", title+detail)
        self.assertNotIn("整局完成", title+detail)
        data["match"]["gold"] = None
        self.assertIn("金币 未识别", observation(data))

    def test_known_field_names_without_page_evidence_do_not_confirm_a_page(self):
        for kind in ("world_entry", "lobby", "new_internal_page"):
            data = dict(page_kind=kind, page_verified=False, mode_text_visible=True)
            self.assertIn("当前页面未核实", observation(data))
            self.assertNotIn("已识别", observation(data))
            self.assertNotIn("new_internal_page", observation(data))

    def test_unknown_stage_and_storage_paths_stay_in_raw_report(self):
        data = dict(mode="flow_test", action_status="internal_new_action", screenshot="C:/private/evidence.png",
                    actions=[dict(node_verified=True, decision=dict(name="阿格莱雅", score=1234))])
        value = observation(data)
        self.assertIn("已验证 1 个节点", value)
        self.assertIn("当前动作待核对", value)
        self.assertNotIn("internal_new_action", value)
        self.assertNotIn("C:/private", value)
        self.assertNotIn("1234", value)

    def test_failure_reason_and_next_step_survive_short_title(self):
        report = dict(operation="currency_wars_standard", status="failed", report_saved=False,
                      error="补给角色未增加", safe_next="保留现场并核对领取记录。",
                      currency_wars=dict(mode="standard_development", reason="补给角色未增加", reward=dict(status="unit_mismatch")))
        original = copy.deepcopy(report)
        title, detail = result(report)
        self.assertEqual(title, "运行失败")
        self.assertTrue(detail.startswith("报告未保存"))
        self.assertEqual(detail.count("补给角色未增加"), 1)
        self.assertIn("下一步：保留现场", detail)
        self.assertIn("补给角色不符", detail)
        self.assertEqual(report, original)

    def test_later_failure_preserves_proven_development_settlement(self):
        report = dict(operation="currency_wars_standard", status="failed", report_saved=False,
            currency_wars=dict(mode="standard_development", status="settled", action_status="settled",
                               completion_verified=True, settlement_verified=True))
        title, detail = result(report)
        self.assertIn("开发局结算已核实", title)
        self.assertIn("后续未完成", title)
        self.assertIn("未计独立验收", detail)
        self.assertIn("报告未保存", detail)
        report["currency_wars"]["settlement_verified"] = False
        self.assertNotIn("开发局结算已核实", result(report)[0])

    def test_stopped_local_action_is_not_a_complete_match(self):
        title, detail = result(dict(operation="currency_wars_node_test", status="stopped",
            currency_wars=dict(mode="single_node_test", origin_node="1-4", node_verified=True)))
        self.assertEqual(title, "已停止")
        self.assertIn("节点胜利已验证", detail)
        self.assertIn("整局未完成", detail)

    def test_preparation_retains_no_new_match_boundary(self):
        data = dict(mode="entry_navigation", entry_ready=True, rank_verified=True)
        self.assertIn("标准A8财富造物主40已核实", observation(data))
        self.assertIn("未开始新对局", observation(data))


if __name__ == "__main__":
    unittest.main()
