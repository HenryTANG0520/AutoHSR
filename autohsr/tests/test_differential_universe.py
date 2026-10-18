from __future__ import annotations

import unittest
from unittest.mock import Mock

from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow, classify_page
from autohsr.models import AutomationError, Scene, Token
from autohsr.policy import (guard_differential_universe_click,
                            guard_differential_universe_field_input,
                            guard_differential_universe_field_interact, guard_click)
from autohsr.app import Runner


def scene(*labels):
    tokens = []
    for index, label in enumerate(labels):
        x = .1 + (index % 4) * .2
        y = .1 + (index // 4) * .2
        tokens.append(Token(label, .99, (x, y, x + .12, y + .04)))
    return Scene(tokens)


class DifferentialUniverseTests(unittest.TestCase):
    def test_settings_bound_automatic_runs_without_daily_battle_validation(self):
        settings = Settings(target_location="", differential_universe_runs=3)
        settings.validate("differential_universe")
        for value in (0, 4, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    Settings(differential_universe_runs=value).validate("differential_universe")

    def test_runner_rejects_out_of_range_run_count(self):
        for value in (0, 4, True):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    Runner(Settings(), operation="differential_universe", du_runs=value)

    def test_mode_page_classification_uses_current_season_labels(self):
        self.assertEqual(classify_page(scene("差分宇宙", "模式选择", "常规演算", "周期演算")), "mode_select")
        self.assertEqual(classify_page(scene("差分宇宙", "乐园漫记", "难度X", "进入星阶模式")), "difficulty_setup")
        self.assertEqual(classify_page(scene("差分宇宙", "周期演算：碰碰运气", "乐园漫记", "难度V",
                                            "启动「差分宇宙」")), "periodic_setup")
        self.assertEqual(classify_page(scene("星阶模式", "拓星模式", "练习模式", "启动「差分宇宙」")), "star_rank_setup")
        self.assertEqual(classify_page(scene("差分宇宙", "选择一张面具", "敷衍面具")), "mask_choice")
        self.assertEqual(classify_page(scene("差分宇宙", "敷衍面具", "面具效果", "确定")), "unknown")
        mask_detail = Scene([Token("差分宇宙", .99, (.05, .03, .16, .08)),
                             Token("万随面具", .99, (.60, .82, .75, .87)),
                             Token("面具效果", .99, (.60, .45, .70, .50)),
                             Token("确定", .99, (.72, .86, .94, .92))])
        self.assertEqual(classify_page(mask_detail), "mask_detail")
        self.assertEqual(classify_page(scene("差分宇宙", "敷衍面具", "选择下一站", "选择一张站点卡",
                                            "战斗", "异常", "铸造", "确定")), "station_choice")
        self.assertEqual(classify_page(scene("差分宇宙", "选择下一站", "在这个区域中可以遇到风险较大的事件",
                                            "战斗", "异常", "铸造", "确定")), "station_choice")
        self.assertEqual(classify_page(scene("差分宇宙", "敷衍面具", "选择你的奇迹", "罕见奇迹", "确定")),
                         "miracle_choice")
        self.assertEqual(classify_page(scene("失去站点卡", "失去数量：3", "点击空白处关闭")), "tutorial_overlay")
        self.assertEqual(classify_page(scene("敷衍面具", "获得愿力 +30", "0/125", "1 >> 2")), "mask_reward_overlay")
        self.assertEqual(classify_page(scene("（1/20）第一位面-战斗", "等级86惊梦剧团", "Saber")), "field_combat")

    def test_reward_choices_take_priority_over_exploration_hud(self):
        self.assertEqual(classify_page(scene("（1/20）第一位面-战斗", "查看祝福与方程", "选择祝福", "候选祝福")),
                         "blessing_choice")
        self.assertEqual(classify_page(scene("（1/20）第一位面-战斗", "查看祝福与方程", "选择方程", "候选方程")),
                         "equation_choice")

    def test_active_save_is_not_classified_as_a_fresh_start(self):
        self.assertEqual(classify_page(scene("差分宇宙", "乐园漫记", "继续游戏")), "active_save")

    def test_current_run_pages_cover_each_plane_and_keep_map_separate(self):
        for plane in ("第一位面", "第二位面", "第三位面", "第四位面", "第五位面", "第六位面"):
            with self.subTest(plane=plane):
                page = scene(f"（3/20）{plane}-战斗", "Lv1/20")
                self.assertEqual(classify_page(page), "field_combat")
                guard_differential_universe_field_input(page, action="move_w")
                anomaly = scene(f"（2/20）{plane}-异常", "LV2/20")
                self.assertEqual(classify_page(anomaly), "field_anomaly")
                guard_differential_universe_field_input(anomaly, action="move_a")
        partial_battle = scene("（1/13）第一位面-战", "等级86幻造生物", "Lv1/20")
        self.assertEqual(classify_page(partial_battle), "field_combat")
        guard_differential_universe_field_input(partial_battle, action="move_w")
        periodic_ocr_drop = scene("（1/13）第 位面-战斗", "等级86幻造生物", "Lv1/20")
        self.assertEqual(classify_page(periodic_ocr_drop), "field_combat")
        guard_differential_universe_field_input(periodic_ocr_drop, action="move_w")
        map_page = scene("差分宇宙", "地图", "当前区域", "战斗", "区域-随机", "探索进度：第一位面1/6")
        self.assertEqual(classify_page(map_page), "route")
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_input(map_page, action="move_w")

    def test_anomaly_interaction_requires_visible_safe_prompt(self):
        page = scene("（2/20）第一位面-异常", "交互", "调查")
        guard_differential_universe_field_interact(
            page, Token("交互", .99, (.48, .48, .54, .52)))
        guard_differential_universe_field_interact(
            page, Token("F 卡牌交互", .99, (.48, .48, .60, .52)))
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(
                page, Token("消耗宇宙碎片开启", .99, (.48, .48, .60, .52)))
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(
                scene("差分宇宙主页", "交互"), Token("交互", .99, (.48, .48, .54, .52)))

    def test_area_choice_shop_and_synthesis_pages_are_distinct(self):
        self.assertEqual(classify_page(scene("选择区域", "区域-随机", "区域-商店", "区域-合成")), "area_choice")
        self.assertEqual(classify_page(scene("黑塔的商店", "宇宙碎片", "离开商店")), "shop")
        self.assertEqual(classify_page(scene("奇物合成", "合成", "退出")), "synthesis")
        page = scene("选择区域", "区域-随机", "区域-商店")
        target = Token("区域-商店", .99, (.65, .45, .77, .50))
        guard_differential_universe_click(page, target, intent="area_select")
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page, Token("购买奇物", .99, (.65, .45, .77, .50)), intent="area_select")
        guard_differential_universe_click(scene("黑塔的商店", "宇宙碎片", "离开商店"),
                                          Token("离开商店", .99, (.8, .9, .95, .95)), intent="leave_area")

    def test_station_choice_is_free_and_position_guarded(self):
        page = scene("差分宇宙", "选择下一站", "选择一张站点卡", "战斗", "异常", "铸造")
        target = Token("异常", .99, (.49, .70, .55, .74))
        guard_differential_universe_click(page, target, intent="station_select")
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page, Token("铸造", .99, (.68, .70, .76, .74)),
                                               intent="station_select")
        guard_differential_universe_click(page, Token("确定", .99, (.60, .89, .67, .92)),
                                          intent="station_confirm")
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(scene("差分宇宙", "确定"),
                                              Token("确定", .99, (.60, .89, .67, .92)),
                                              intent="station_confirm")

        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        workflow = DifferentialUniverseWorkflow(context, 1)
        battle = Token("战斗", .99, (.29, .70, .36, .74))
        anomaly = Token("异常", .99, (.49, .70, .55, .74))
        cards = Scene([battle, anomaly, Token("铸造", .99, (.68, .70, .76, .74))])
        self.assertIs(workflow._station_choice_target(cards), battle)
        self.assertIs(workflow._station_choice_target(Scene([anomaly])), anomaly)

    def test_area_route_prefers_battle_when_battle_is_available(self):
        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        workflow = DifferentialUniverseWorkflow(context, 1)
        battle = Token("区域-战斗", .99, (.28, .48, .38, .54))
        reward = Token("区域-奖励", .99, (.62, .48, .72, .54))
        self.assertIs(workflow._area_choice_target(Scene([reward, battle])), battle)

    def test_periodic_start_requires_explicit_user_selected_page(self):
        page = scene("差分宇宙", "周期演算：碰碰运气", "乐园漫记", "难度V")
        target = Token("启动「差分宇宙」", .99, (.78, .88, .96, .92))
        guard_differential_universe_click(page, target, intent="periodic_start")
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(scene("差分宇宙", "常规演算", "难度I"), target,
                                              intent="periodic_start")

    def test_du_inputs_require_named_non_spending_ocr_targets(self):
        fresh = scene("差分宇宙", "常规演算")
        allowed = Token("常规演算", .99, (.2, .2, .3, .24))
        guard_differential_universe_click(fresh, allowed)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(fresh, (.5, .5))
        for label in ("黑塔的商店", "合成奇物", "使用燃料", "兑换星琼"):
            with self.subTest(label=label), self.assertRaises(AutomationError):
                guard_differential_universe_click(fresh, Token(label, .99, (.4, .4, .5, .45)))

    def test_reward_choice_requires_verified_choice_page_and_safe_position(self):
        target = Token("灼热的祝福效果", .99, (.2, .4, .4, .44))
        mask_detail = Scene([Token("差分宇宙", .99, (.05, .03, .16, .08)),
                             Token("万随面具", .99, (.60, .82, .75, .87)),
                             Token("面具效果", .99, (.60, .45, .70, .50)),
                             Token("确定", .99, (.72, .86, .94, .92))])
        guard_differential_universe_click(scene("选择祝福", "候选效果"), target, intent="choice")
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(scene("差分宇宙主页"), target, intent="choice")
        guard_differential_universe_click(scene("差分宇宙", "选择方程", "请选方程"),
                                          Token("确认", .99, (.8, .88, .9, .92)))
        guard_differential_universe_click(mask_detail, Token("确定", .99, (.72, .86, .94, .92)),
                                          intent="choice_confirm")
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(scene("差分宇宙主页"),
                                              Token("确定", .99, (.72, .86, .94, .92)),
                                              intent="choice_confirm")

    def test_field_attack_requires_first_plane_battle_marker_and_bounded_icon_anchor(self):
        target = Token("差分宇宙基础攻击", .99, (.858, .844, .885, .888))
        guard_differential_universe_click(scene("（1/20）第一位面-战斗"), target, intent="field_attack")
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(scene("差分宇宙主页"), target, intent="field_attack")
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(scene("（1/20）第一位面-战斗"),
                                              Token("Saber", .99, (.858, .844, .885, .888)),
                                              intent="field_attack")
        locked = Token("差分宇宙已锁定敌方目标", .99, (.19, .47, .22, .53))
        guard_differential_universe_click(scene("（1/20）第一位面-战斗"), locked, intent="field_target_attack")
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(scene("差分宇宙主页"), locked, intent="field_target_attack")
        partial_battle = scene("第一位面-战", "等级86惊梦剧团", "Lv1/20")
        visible_enemy = Token("差分宇宙可见敌方目标", .98, (.16, .40, .24, .48))
        guard_differential_universe_click(partial_battle, visible_enemy, intent="field_enemy_attack")
        periodic_ocr_drop = scene("（1/13）第 位面-战斗", "等级86幻造生物", "Lv1/20")
        guard_differential_universe_click(periodic_ocr_drop, visible_enemy, intent="field_enemy_attack")
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(scene("第一位面-异常", "等级86惊梦剧团", "Lv1/20"),
                                              visible_enemy, intent="field_enemy_attack")

    def test_visible_enemy_template_can_anchor_field_attack(self):
        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        context.template = Mock(side_effect=[None, (.20, .44, .72), (.25, .46, .97),
                                             (.70, .43, .83), (.55, .40, .91)])
        workflow = DifferentialUniverseWorkflow(context, 1)
        workflow._daily._icon = Mock(return_value=None)
        result = workflow._field_attack_target(scene("第一位面-战", "等级86惊梦剧团", "Lv1/20"))
        self.assertEqual(result[1], "field_enemy_attack")
        self.assertAlmostEqual(result[0].center[0], .25)
        self.assertEqual([call.args[1] for call in context.template.call_args_list],
                         ["du_field_enemy", "du_field_enemy_2", "du_field_enemy_3", "du_field_enemy_4",
                          "du_field_enemy_5"])

    def test_field_enemy_is_engaged_before_using_visible_gate_exit(self):
        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        workflow = DifferentialUniverseWorkflow(context, 1)
        current = scene("（1/13）第一位面-战斗", "等级86惊梦剧团", "随意门")
        enemy = Token("差分宇宙可见敌方目标", .97, (.20, .40, .25, .50))
        centered_enemy = Token("差分宇宙可见敌方目标", .97, (.46, .40, .54, .50))
        workflow._field_attack_target = Mock(side_effect=[
            (enemy, "field_enemy_attack"), (centered_enemy, "field_enemy_attack"),
            (centered_enemy, "field_enemy_attack"), (centered_enemy, "field_enemy_attack")])
        workflow._click = Mock(return_value=(scene("挑战成功"), "node_victory"))
        workflow._observe = Mock(return_value="field_combat")
        context.differential_universe_move.return_value = current
        workflow._find = Mock(return_value=Token("随意门", .99, (.45, .45, .52, .5)))

        result, kind = workflow._field_combat(current)

        self.assertEqual(kind, "node_victory")
        workflow._click.assert_called_once_with(
            current, centered_enemy, intent="field_enemy_attack", label="field_attack")
        self.assertEqual([call.args[1:] for call in context.differential_universe_move.call_args_list],
                         [("a", 600), ("w", 600), ("w", 600)])
        workflow._find.assert_not_called()

    def test_labeled_enemy_blocks_gate_exit_when_target_template_misses(self):
        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        workflow = DifferentialUniverseWorkflow(context, 1)
        current = scene("（1/13）第一位面-战斗", "等级86惊梦剧团", "随意门")
        workflow._field_attack_target = Mock(return_value=None)
        workflow._find = Mock(return_value=Token("随意门", .99, (.45, .45, .52, .5)))
        workflow._observe = Mock(return_value="field_combat")
        context.differential_universe_look.return_value = current
        context.differential_universe_move.return_value = current

        with self.assertRaisesRegex(AutomationError, "十次有界探索移动"):
            workflow._field_combat(current)

        context.differential_universe_enter_random_gate.assert_not_called()
        self.assertEqual(context.differential_universe_look.call_count, 3)
        self.assertEqual(context.differential_universe_move.call_count, 10)

    def test_field_without_visible_enemy_uses_only_bounded_search_inputs(self):
        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        workflow = DifferentialUniverseWorkflow(context, 1)
        current = scene("（1/20）第一位面-战斗", "等级86惊梦剧团", "红色导航标记")
        workflow._daily._icon = Mock(return_value=None)
        workflow._click = Mock()
        workflow._observe = Mock(return_value="field_combat")
        context.differential_universe_look.return_value = current
        context.differential_universe_move.return_value = current
        with self.assertRaisesRegex(AutomationError, "十次有界探索移动"):
            workflow._field_combat(current)
        workflow._click.assert_not_called()
        self.assertEqual(context.differential_universe_look.call_count, 3)
        self.assertEqual(context.differential_universe_move.call_count, 10)

    def test_lowest_difficulty_is_clicked_by_template_and_requires_ocr_confirmation(self):
        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        context.evidence.return_value = "evidence.png"
        context.template.return_value = (.065, .164, .99)
        workflow = DifferentialUniverseWorkflow(context, 1)
        setup = scene("差分宇宙", "乐园漫记", "难度X", "进入星阶模式")
        selected = scene("差分宇宙", "乐园漫记", "难度I", "进入星阶模式")
        workflow._click = Mock(return_value=(selected, "difficulty_setup"))
        result = workflow._select_lowest_difficulty(setup)
        self.assertIs(result, selected)
        workflow._click.assert_called_once()
        self.assertEqual(workflow._click.call_args.kwargs["intent"], "difficulty_selection")
        self.assertTrue(workflow.report["difficulty_selection"]["verified"])
        self.assertEqual(workflow.report["difficulty_selection"]["displayed_rank_after"], 1)

    def test_generic_daily_click_does_not_gain_differential_universe_menu_permission(self):
        menu = Scene([
            Token("开拓等级", .99, (.7, .1, .8, .14)),
            Token("委托", .99, (.7, .4, .76, .44)),
            Token("差分宇宙", .99, (.7, .5, .82, .54)),
        ])
        target = menu.tokens[-1]
        with self.assertRaises(AutomationError):
            guard_click(menu, target)

    def test_workflow_never_uses_periodic_mode_from_mode_select(self):
        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        workflow = DifferentialUniverseWorkflow(context, 1)
        self.assertEqual(workflow.report["mode"], "拓星模式 / 常规演算")
        self.assertNotIn("周期演算", " ".join(workflow.report["actions"]))

    def test_explicit_resume_adopts_only_a_recognized_active_page(self):
        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        workflow = DifferentialUniverseWorkflow(context, 1, resume_active=True)
        active = scene("差分宇宙", "选择一张面具", "敷衍面具")
        mode = scene("差分宇宙", "模式选择", "常规演算", "周期演算")
        workflow._snapshot = Mock(side_effect=[(active, "mask_choice"), (mode, "mode_select")])
        workflow._progress_run = Mock(side_effect=[(mode, "mode_select", True), (mode, "mode_select", True)])
        workflow._prepare_and_start = Mock(side_effect=lambda scene, kind: (
            workflow.report.update(difficulty_selection={"requested_rank": 1, "displayed_rank_after": 1,
                                                         "verified": True}) or
            (scene, kind)))
        context.evidence.return_value = "evidence.png"
        result = workflow.run()
        self.assertEqual(result.status, "ok")
        self.assertTrue(workflow.report["resumed_active_run"])
        self.assertEqual(workflow.report["completed_runs"], 1)
        self.assertEqual(len(workflow.report["run_results"]), 2)
        self.assertEqual(workflow.report["run_results"][0]["status"], "returned_uncounted")
        self.assertFalse(workflow.report["run_results"][0]["counted"])
        self.assertTrue(workflow.report["run_results"][1]["counted"])
        self.assertEqual(workflow._progress_run.call_count, 2)

    def test_explicit_resume_stops_on_unrecognized_page(self):
        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        workflow = DifferentialUniverseWorkflow(context, 1, resume_active=True)
        workflow._snapshot = Mock(return_value=(scene("UID:000000000"), "unknown"))
        with self.assertRaisesRegex(AutomationError, "不是已识别的运行中页面"):
            workflow.run()

    def test_periodic_active_resume_counts_current_run_without_starting_another(self):
        context = Mock()
        context.settings = Settings()
        context.report = Mock(differential_universe={})
        workflow = DifferentialUniverseWorkflow(context, 1, resume_active=True, periodic_rank=5)
        active = scene("差分宇宙", "选择一张面具", "欢愉假面")
        returned = scene("差分宇宙", "周期演算", "难度V")
        workflow._snapshot = Mock(return_value=(active, "mask_choice"))
        workflow._progress_run = Mock(return_value=(returned, "periodic_setup", True))
        context.evidence.return_value = "return.png"
        result = workflow.run()
        self.assertEqual(result.status, "ok")
        self.assertEqual(workflow.report["mode"], "周期演算")
        self.assertEqual(workflow.report["completed_runs"], 1)
        self.assertEqual(len(workflow.report["run_results"]), 1)
        self.assertEqual(workflow.report["run_results"][0]["status"], "completed")
        self.assertTrue(workflow.report["run_results"][0]["counted"])
        workflow._progress_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
