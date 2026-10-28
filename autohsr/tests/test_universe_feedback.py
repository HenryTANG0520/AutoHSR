import unittest

from autohsr.ux import universe_result


class UniverseFeedbackTests(unittest.TestCase):
    def report(self, **extra):
        return dict(status="success", differential_universe=dict(requested_runs=3,
            completed_runs=3, mode="周期演算", **extra))

    def test_failed_followup_preserves_completed_runs_and_actual_error(self):
        report = self.report(last_message="三局已完成", reward_collection=dict(status="failed",
            failure_reason="拟合奖励页未返回", claims=[dict(mode_cassettes_used=100)]))
        report.update(status="failed", error="拟合奖励页未返回")
        title, detail = universe_result(report)
        self.assertIn("领奖未完成", title)
        self.assertIn("3/3", title)
        self.assertNotIn("已停止", title)
        self.assertEqual(detail.count("拟合奖励页未返回"), 1)
        self.assertIn("已使用 100 月下卡带", detail)
        self.assertNotIn("三局已完成", detail)

    def test_success_requires_known_complete_count_not_form_defaults(self):
        for count in (None, "3", True, -1, 4):
            report = self.report()
            report["differential_universe"]["completed_runs"] = count
            title, _ = universe_result(report)
            self.assertIn("待核对", title)
            self.assertNotIn("演算完成", title)
        report = self.report()
        report["differential_universe"]["completed_runs"] = 1
        title, _ = universe_result(report)
        self.assertIn("1/3", title)
        self.assertIn("待核对", title)

    def test_unknown_cost_is_not_zero_or_completed_reward(self):
        report = self.report(reward_collection=dict(status="complete", claims=[dict(mode_cassettes_used=None)]),
            daily_interludes=[dict(status="complete", stamina_spent=None, immersifiers_spent=0)])
        _, detail = universe_result(report)
        self.assertIn("红点奖励未完成", detail)
        self.assertIn("卡带消耗待核对", detail)
        self.assertIn("消耗待核对", detail)
        self.assertNotIn("0 开拓力", detail)

    def test_optional_records_are_independent_and_skip_is_not_failure(self):
        report = self.report(run_results=[dict(save_status="saved", save_name="AutoHSR-2", save_evidence="save.png"),
            dict(save_status="skipped_full")],
            daily_interludes=[dict(status="before_start_day", start_day="2026-11-01")],
            reward_collection=dict(status="complete", home_evidence="home.png", claims=[]))
        title, detail = universe_result(report)
        self.assertIn("演算完成", title)
        self.assertIn("已保存：AutoHSR-2", detail)
        self.assertIn("存档槽已满", detail)
        self.assertIn("红点奖励已核实领完", detail)
        self.assertIn("未到开始日期", detail)
        self.assertNotIn("未完成", detail)

    def test_resumed_uncounted_is_distinct_from_requested_goal(self):
        report = self.report(run_results=[dict(origin="resumed_trial", status="returned_uncounted", counted=False)])
        _, detail = universe_result(report)
        self.assertIn("接续通关 1 局 · 0 局计入本次目标", detail)

    def test_missing_result_keeps_reason_and_does_not_dump_payload(self):
        title, detail = universe_result(dict(status="failed", report_saved=False,
            error="游戏窗口未找到", safe_next="检查游戏路径", differential_universe=dict(
                session_id="private-session", page_history=[dict(ocr_text="raw-ocr")], actions=[dict(intent="du_move")])) )
        self.assertIn("局数未核实", title)
        self.assertIn("报告未保存", detail)
        self.assertIn("游戏窗口未找到", detail)
        self.assertIn("检查游戏路径", detail)
        for fragment in ("private-session", "raw-ocr", "du_move", "page_history"):
            self.assertNotIn(fragment, detail)


if __name__ == "__main__":
    unittest.main()
