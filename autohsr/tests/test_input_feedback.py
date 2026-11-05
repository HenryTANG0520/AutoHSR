from dataclasses import replace
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from autohsr.config import Settings, SettingsError
from autohsr.ux import issue_text, standard_activity, standard_run_verified


class InputFeedbackTests(unittest.TestCase):
    def test_backend_validation_identifies_the_field_without_parsing_messages(self):
        cases = (("game_path", "wrong.exe"), ("target_name", ""), ("target_location", ""),
                 ("stamina_limit", 25), ("challenge_count", 25), ("action_delay", float("nan")),
                 ("battle_timeout", 50), ("ocr_confidence", 2), ("differential_universe_runs", 11),
                 ("differential_universe_team", ""), ("weekly_time", "24:00"), ("weekly_runs", 0),
                 ("weekly_day", 8), ("weekly_mode", "unknown"))
        for field, value in cases:
            with self.subTest(field=field):
                with self.assertRaises(SettingsError) as caught:
                    replace(Settings(), **{field: value}).validate("plan")
                self.assertEqual(caught.exception.field, field)
                self.assertIsInstance(caught.exception, ValueError)

    def test_unknown_costs_and_failure_are_visible_before_full_summary(self):
        message = issue_text(dict(status="partial", daily_verified=True, stamina_spent=120,
            stamina_pending=10, immersifiers_pending=2, error="未识别邮箱入口\n当前页面未知"))
        self.assertEqual(message, "10 开拓力待核对 · 2 沉浸器待核对 · 未识别邮箱入口 当前页面未知")

    def test_unsaved_report_is_visible_even_without_backend_error(self):
        self.assertEqual(issue_text(dict(status="success", report_saved=False)), "报告未保存")
        self.assertEqual(issue_text(dict(status="partial", stamina_pending=None)), "开拓力待核对")

    def test_optional_failure_is_not_hidden_by_verified_daily(self):
        report = dict(status="partial", daily_verified=True, results=[dict(task="daily", status="ok", detail="已领取"),
            dict(task="mail", status="partial", detail="邮箱入口未识别")])
        self.assertEqual(issue_text(report), "邮箱入口未识别")
        self.assertEqual(issue_text(dict(status="success", report_saved=True, results=[])), "")

    def test_staged_exchange_is_not_presented_as_verified(self):
        data = dict(action_status="transition_verified", actions=[dict(status="verified", movement_verified=False)],
                    exchange=dict(status="verifying"))
        self.assertEqual(standard_activity(data), "核验换人角色")
        data["exchange"]["status"] = "identity_mismatch"
        self.assertEqual(standard_activity(data), "换人角色不符")

    def test_verified_exchange_requires_matching_identity_state(self):
        data = dict(action_status="exchange_verified", exchange=dict(status="verified"))
        self.assertEqual(standard_activity(data), "换人已核实")
        data["exchange"] = {}
        self.assertEqual(standard_activity(data), "换人结果待核对")

    def test_development_victory_needs_both_completion_and_settlement(self):
        data = dict(mode="standard_development", status="settled", action_status="settled",
                    completion_verified=True, settlement_verified=True)
        self.assertTrue(standard_run_verified(data))
        for field in ("completion_verified", "settlement_verified"):
            pending = dict(data, **{field: False})
            self.assertFalse(standard_run_verified(pending))
            self.assertEqual(standard_activity(pending), "结算待核对")

    def test_inventory_change_is_not_equipment_completion(self):
        data = dict(action_status="transition_verified", equipment=dict(status="verifying"),
                    actions=[dict(status="verified", equipment_verified=False)])
        self.assertEqual(standard_activity(data), "核验角色装备")
        data["equipment"]["status"] = "equipment_mismatch"
        self.assertEqual(standard_activity(data), "角色装备不符")
        self.assertFalse(standard_run_verified(data))

    def test_equipment_feedback_requires_completed_equipment_state(self):
        data = dict(action_status="equipment_verified", equipment=dict(status="verified"))
        self.assertEqual(standard_activity(data), "装备已核实")
        self.assertFalse(standard_run_verified(data))
        data["equipment"] = {}
        self.assertEqual(standard_activity(data), "装备结果待核对")


class InputFocusSectionTests(unittest.TestCase):
    def focus(self):
        from autohsr.desktop_focus import InputFocus
        focus = InputFocus.__new__(InputFocus)
        focus.pending = ('currency_runs', 'currency_wars', 'loop', 'currency_runs_entry')
        focus.ui = SimpleNamespace(closing=False, busy=False, input_error_field='currency_runs',
            active_page='currency_wars', currency_sections={'loop': 'loop-page'},
            currency_tabs=SimpleNamespace(select=Mock(return_value='loop-page')),
            settings_sections={'weekly': 'weekly-page'},
            settings_tabs=SimpleNamespace(select=Mock(return_value='weekly-page')))
        return focus

    def test_error_focus_belongs_to_the_visible_currency_or_settings_section(self):
        focus = self.focus()
        self.assertTrue(focus.owns_current_page())
        focus.ui.currency_tabs.select.return_value = 'standard-page'
        self.assertFalse(focus.owns_current_page())
        focus.pending = ('weekly_time', 'settings', 'weekly', 'weekly_time_entry')
        focus.ui.input_error_field, focus.ui.active_page = 'weekly_time', 'settings'
        self.assertTrue(focus.owns_current_page())
        focus.ui.settings_tabs.select.return_value = 'game-page'
        self.assertFalse(focus.owns_current_page())

    def test_cancelled_focus_does_not_access_retired_widgets(self):
        for change in ({'closing': True}, {'busy': True}, {'input_error_field': None}, {'active_page': 'home'}):
            with self.subTest(change=change):
                focus = self.focus()
                focus.ui.currency_tabs.select.side_effect = RuntimeError('retired widget')
                for key, value in change.items():
                    setattr(focus.ui, key, value)
                self.assertFalse(focus.owns_current_page())
                focus.ui.currency_tabs.select.assert_not_called()


if __name__ == "__main__":
    unittest.main()
