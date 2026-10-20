"""Cross-category accounting and navigation regressions; no game inputs."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from autohsr.config import Settings
from autohsr.dungeons import CATEGORIES, Dungeon, category_for, load_catalogue, save_catalogue
from autohsr.dungeon_workflow import guide_rows
from autohsr.models import AutomationError, Scene, Token
from autohsr.workflows import DailyWorkflow
from autohsr.tests.test_core import FakeContext, token, calyx_scene


class DungeonTests(unittest.TestCase):
    def test_legacy_config_retains_calyx_category_and_budget_semantics(self):
        for name, key in (("回忆之蕾", "calyx_golden"), ("毁灭之蕾", "calyx_crimson")):
            settings = Settings(target_name=name)
            self.assertEqual(category_for(settings).key, key)
            self.assertIsNone(settings.challenge_count)

    def test_count_cost_and_category_boundaries_are_checked_before_game_access(self):
        for key, count, budget in (("cavern", 7, 240), ("echo_of_war", 4, 240),
                                   ("stagnant_shadow", 2, 30), ("invalid", 1, 240),
                                   ("calyx_golden", True, 240), ("calyx_golden", 1.0, 240)):
            with self.subTest(key=key, count=count):
                with self.assertRaises(ValueError):
                    Settings(dungeon_category=key, challenge_count=count, stamina_limit=budget).validate()

    def test_fixed_cost_dungeons_do_not_infer_cost_from_missing_round_slider(self):
        for category in CATEGORIES[2:5]:
            with self.subTest(category=category.key):
                settings = Settings(dungeon_category=category.key, target_name="测试副本", target_location="测试地点", use_support=False)
                scene = Scene([token(category.label, .1, .05), token("挑战", .9, .92),
                               token(str(category.cost), .7, .92), token("120/300", .8, .1)])
                ctx = FakeContext([scene], settings)
                workflow = DailyWorkflow(ctx)
                self.assertEqual(workflow._limit_batch(scene, 240)[1], category.cost)
                self.assertEqual(workflow._limit_batch(scene, category.cost - 10)[1], 0)
                scene.tokens = [t for t in scene.tokens if t.text != "120/300"]
                with self.assertRaises(AutomationError):
                    workflow._limit_batch(scene, 240)

    def test_one_requested_calyx_stops_even_with_unused_budget(self):
        settings = Settings(stamina_limit=240, rounds=1, challenge_count=1, use_support=False)
        team = Scene([token("队伍", .1, .05), token("开始挑战", .8, .9)])
        success = Scene([token("挑战成功", .5, .3), token("退出关卡", .8, .9)])
        ctx = FakeContext([calyx_scene(cost=10, rounds=1), team, success, Scene([])], settings)
        self.assertEqual(DailyWorkflow(ctx).battle().status, "ok")
        self.assertEqual(ctx.report.battle_completed, 1)
        self.assertEqual(ctx.report.stamina_spent, 10)
        self.assertEqual(ctx.clicks.count("开始挑战"), 1)

    def test_each_fixed_category_counts_completions_instead_of_ten_point_units(self):
        for category in CATEGORIES[2:5]:
            with self.subTest(category=category.key):
                settings = Settings(dungeon_category=category.key, challenge_count=2, use_support=False)
                details = Scene([token(category.label, .1, .05), token("挑战", .9, .92),
                                 token(str(category.cost), .7, .92), token("240/300", .8, .1)])
                team = Scene([token("队伍", .1, .05), token("开始挑战", .8, .9)])
                success = Scene([token("挑战成功", .5, .3), token("退出关卡", .8, .9)])
                ctx = FakeContext([details, team, success, details, team, success, Scene([])], settings)
                workflow = DailyWorkflow(ctx)
                with patch.object(workflow, "_open_calyx", side_effect=lambda:ctx.snapshot()), \
                     patch.object(workflow, "_disable_quick_refill", side_effect=lambda scene:scene):
                    self.assertEqual(workflow.battle().status, "ok")
                self.assertEqual(ctx.report.battle_completed, 2)
                self.assertEqual(ctx.report.stamina_spent, category.cost * 2)
                self.assertEqual(ctx.clicks.count("开始挑战"), 2)

    def test_non_calyx_slider_uses_the_category_cost_for_each_increment(self):
        for category in CATEGORIES[2:]:
            with self.subTest(category=category.key):
                settings = Settings(dungeon_category=category.key, rounds=2, challenge_count=2)
                def details(count):
                    return Scene([token(category.label,.1,.05),token("开始挑战" if category.key == "planar" else "挑战",.9,.92),
                                  token(str(category.cost*count),.7,.92),token(f"挑战次数{count}",.8,.8),
                                  token("240/300",.8,.1),token("+",.962,.82)])
                one,two=details(1),details(2)
                ctx=FakeContext([one,two],settings)
                self.assertEqual(DailyWorkflow(ctx)._limit_batch(one,240)[1],category.cost*2)
                self.assertEqual(ctx.clicks,["+"])

    def test_batch_accounting_requires_matching_settlement_waves_and_keeps_pending_on_mismatch(self):
        from autohsr.recovery import BattleBudget
        for actual in (1,2):
            with self.subTest(actual=actual), tempfile.TemporaryDirectory() as folder:
                settings=Settings(dungeon_category="cavern",rounds=2,challenge_count=2,stamina_limit=80,use_support=False)
                details=Scene([token("侵蚀隧洞",.1,.05),token("挑战",.9,.92),token("80",.7,.92),
                               token("挑战次数2",.8,.8),token("240/300",.8,.1)])
                team=Scene([token("队伍",.1,.05),token("开始挑战",.8,.9)])
                result=Scene([token("挑战成功",.5,.3),token("退出关卡",.8,.9),token(f"上轮挑战波次：{actual}",.62,.85)])
                ctx=FakeContext([details,team,result,Scene([])],settings)
                ctx.battle_budget=BattleBudget(Path(folder),settings,ctx.report)
                ctx.battle_budget.begin()
                workflow=DailyWorkflow(ctx)
                with patch.object(workflow,"_open_calyx",side_effect=lambda:ctx.snapshot()), \
                     patch.object(workflow,"_disable_quick_refill",side_effect=lambda scene:scene):
                    if actual == 1:
                        with self.assertRaisesRegex(AutomationError,"波次"):
                            workflow.battle()
                        self.assertEqual((ctx.report.stamina_spent,ctx.report.stamina_pending,ctx.report.battle_completed),(0,80,0))
                        self.assertNotIn("退出关卡",ctx.clicks)
                    else:
                        self.assertEqual(workflow.battle().status,"ok")
                        self.assertEqual((ctx.report.stamina_spent,ctx.report.stamina_pending,ctx.report.battle_completed),(80,0,2))

    def test_catalogue_requires_map_and_button_in_same_complete_row(self):
        scene = Scene([token("回忆之蕾", .48, .36), token("绘世学院", .49, .40),
                       token("进入", .81, .38), token("以太之蕾", .48, .60),
                       token("进入", .81, .62)])
        rows = guide_rows(scene, "calyx_golden")
        self.assertEqual([item for item, _ in rows], [Dungeon("calyx_golden", "回忆之蕾", "绘世学院")])
        scene.tokens = [t for t in scene.tokens if t.text != "绘世学院"]
        self.assertEqual(guide_rows(scene, "calyx_golden"), [])

    def test_batch_success_waits_for_wave_count_after_success_animation(self):
        settings=Settings(dungeon_category="calyx_golden",rounds=2,challenge_count=2,stamina_limit=20,use_support=False)
        team=Scene([token("队伍",.1,.05),token("开始挑战",.8,.9)])
        early=Scene([token("挑战成功",.5,.3)])
        ready=Scene([token("挑战成功",.5,.3),token("上轮挑战波次：2",.62,.85),token("退出关卡",.8,.9)])
        ctx=FakeContext([calyx_scene(cost=20,rounds=2),team,early,ready,Scene([])],settings)
        self.assertEqual(DailyWorkflow(ctx).battle().status,"ok")
        self.assertEqual((ctx.report.battle_completed,ctx.report.stamina_spent),(2,20))
        self.assertEqual(ctx.clicks.count("开始挑战"),1)

    def test_echo_uses_its_taller_row_and_planar_binds_the_visible_category(self):
        echo = Scene([token("毁灭的开端", .5, .40), token("支援舱段", .5, .43), token("进入", .82, .49)])
        rows = guide_rows(echo, "echo_of_war")
        self.assertEqual(rows[0][0], Dungeon("echo_of_war", "毁灭的开端", "支援舱段"))
        planar = Scene([token("位面饰品", .22, .45), token("百年冻土", .5, .5), token("进入", .82, .5)])
        self.assertEqual(guide_rows(planar, "planar")[0][0], Dungeon("planar", "百年冻土", "位面饰品"))
        planar.tokens.pop(0)
        self.assertEqual(guide_rows(planar, "planar"), [])

    def test_weekly_allowance_is_read_separately_and_never_inferred_from_stamina(self):
        from autohsr.dungeon_workflow import weekly_rewards
        scene = Scene([token("本周可领取奖励次数：", .52, .30), token("0/3", .48, .345), token("300/300", .88, .06)])
        self.assertEqual(weekly_rewards(scene), 0)
        scene.tokens.pop(1)
        self.assertIsNone(weekly_rewards(scene))

    def test_local_catalogue_merges_and_roundtrips_without_overwriting_bundle(self):
        with tempfile.TemporaryDirectory() as folder:
            bundled, local = Path(folder)/"bundled.json", Path(folder)/"local.json"
            save_catalogue(bundled, [Dungeon("calyx_golden", "回忆之蕾", "城郊雪原")])
            original = bundled.read_bytes()
            save_catalogue(local, [Dungeon("calyx_golden", "回忆之蕾", "绘世学院")])
            self.assertEqual(len(load_catalogue(bundled, local)), 2)
            self.assertEqual(bundled.read_bytes(), original)

    def test_scan_cli_is_independent_of_invalid_daily_fields_and_does_not_save(self):
        from autohsr.__main__ import main
        from contextlib import redirect_stdout, redirect_stderr
        import io
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder)/"config.json"
            Settings().save(config)
            original = config.read_bytes()
            with patch("autohsr.app.Runner") as runner, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                runner.return_value.run.return_value = {"status": "success"}
                self.assertEqual(main(["--scan-dungeons", "--config", str(config), "--stamina", "999"]), 0)
                self.assertEqual(runner.call_args.kwargs["operation"], "dungeon_catalogue")
            self.assertEqual(config.read_bytes(), original)

    def test_scan_defaults_to_all_categories_even_when_saved_plan_selects_one(self):
        from autohsr.__main__ import main
        from contextlib import redirect_stdout, redirect_stderr
        import io
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)/"config.json"
            Settings(dungeon_category="cavern",challenge_count=1).save(config)
            with patch("autohsr.app.Runner") as runner, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                runner.return_value.run.return_value={"status":"success"}
                self.assertEqual(main(["--scan-dungeons","--config",str(config)]),0)
                self.assertEqual(runner.call_args.args[0].dungeon_category,"auto")
                self.assertEqual(main(["--scan-dungeons","--category","planar","--config",str(config)]),0)
                self.assertEqual(runner.call_args.args[0].dungeon_category,"planar")

    def test_wheel_notches_are_separate_frames_and_zero_is_a_noop(self):
        from autohsr.windows import GameWindow
        from unittest.mock import Mock
        window = Mock()
        with patch("autohsr.windows.time.sleep") as sleep:
            GameWindow.scroll(window, -360)
            self.assertEqual(window.send.call_count, 3)
            self.assertEqual(sleep.call_count, 3)
            window.send.reset_mock()
            GameWindow.scroll(window, 0)
            window.send.assert_not_called()

    def test_all_bundled_missions_have_bound_rows_in_real_client_samples(self):
        root = Path(__file__).parent / "fixtures" / "dungeons"
        data = json.loads((root / "guide_rows.json").read_text(encoding="utf-8"))
        observed = set()
        for sample in data["samples"]:
            with self.subTest(source=sample["source"]):
                scene = Scene([Token(t["text"],t["score"],tuple(t["box"])) for t in sample["tokens"]])
                actual = [m for m,b in guide_rows(scene, sample["category"])]
                self.assertEqual(actual, [Dungeon(**m) for m in sample["expected"]])
                observed.update(actual)
        bundled = load_catalogue(Path(__file__).parents[2] / "assets" / "dungeons.json")
        self.assertEqual(len(bundled), 104)
        self.assertFalse(set(bundled) - observed, set(bundled) - observed)

    def test_real_cavern_refill_switch_translucent_border_is_recognized_off(self):
        import cv2
        import numpy as np
        root = Path(__file__).parent / "fixtures" / "dungeons"
        patch = cv2.imdecode(np.frombuffer((root/"cavern_refill_off.png").read_bytes(),np.uint8),cv2.IMREAD_COLOR)
        image = np.zeros((2160,3840,3),dtype=np.uint8)
        image[round(.735*2160):round(.78*2160),round(.94*3840):round(.99*3840)] = patch
        scene = Scene([token("侵蚀隧洞",.1,.05),token("挑战",.9,.92),
                       Token("快捷补充开拓力",.99,(.850520833333,.742592592593,.939583333333,.772222222222))],image)
        workflow = DailyWorkflow(FakeContext([scene],Settings(dungeon_category="cavern")))
        self.assertEqual(workflow._quick_refill_state(scene)[0],"off")

    def test_planar_prepare_has_direct_start_and_does_not_confuse_immersion_with_stamina(self):
        scene=Scene([token("位面饰品提取",.1,.05),token("下载角色",.35,.69),token("开始挑战",.85,.91),
                     token("40",.77,.91),token("183/300",.81,.06),token("0/12",.895,.06),token("挑战次数1",.85,.805)])
        workflow=DailyWorkflow(FakeContext([scene],Settings(dungeon_category="planar",rounds=1)))
        self.assertTrue(workflow._team_page(scene))
        self.assertEqual(workflow._available(scene),183)
        self.assertEqual(workflow._limit_batch(scene,40)[1],40)

    def test_real_planar_native_badge_and_friend_slot_are_both_read_and_action_button_is_not_proof(self):
        import cv2
        import numpy as np
        from autohsr.vision import Vision
        root=Path(__file__).parent/"fixtures"/"dungeons"
        data=json.loads((root/"planar_support.json").read_text(encoding="utf-8"))
        width,height=data['size'];image=np.zeros((height,width,3),dtype=np.uint8)
        for crop in data['crops']:
            x1,y1,x2,y2=crop['box']
            pixels=cv2.imdecode(np.frombuffer((root/crop['file']).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
            image[round(y1*height):round(y2*height),round(x1*width):round(x2*width)]=pixels
        scene=Scene([token("位面饰品提取",.1,.05),token("支援",.365,.828)],image)
        self.assertFalse(DailyWorkflow._support_marker(scene))
        vision=Vision()
        vision.refine_planar_support(scene)
        self.assertTrue(DailyWorkflow._support_marker(scene))
        self.assertEqual(vision.planar_friend_slot(scene,token("好友",.265,.203)),4)
        self.assertIsNone(vision.planar_friend_slot(scene,token("好友",.265,.332)))


if __name__ == "__main__":
    unittest.main()
