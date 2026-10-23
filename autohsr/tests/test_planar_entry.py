"""Planar entry must be bounded and cannot become general DU navigation."""
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock

from autohsr.config import Settings
from autohsr.models import AutomationError, Scene, RunReport
from autohsr.planar_entry import field_ready,incomplete_team
from autohsr.workflows import DailyWorkflow
from autohsr.tests.test_core import FakeContext, token


def field():
    return Scene([token("差分宇宙",.06,.025),token("状态效果",.95,.225),token("等级90可可利亚",.5,.05)])


class PlanarEntryTests(unittest.TestCase):
    def test_current_battle_pause_glyph_can_confirm_planar_entry(self):
        scene=Scene([])
        ctx=FakeContext([scene],Settings(dungeon_category='planar'))
        ctx.planar_approach=Mock()
        ctx.template_matches={'du_battle_pause':[(.97,.045,.99)]}
        DailyWorkflow(ctx)._enter_planar_battle()
        ctx.planar_approach.assert_not_called()
        self.assertEqual(ctx.clicks,[])

    def test_empty_party_confirmation_is_cancelled_without_attacking(self):
        popup=Scene([token('提示',.5,.38),token('当前编队中仍有角色位空缺，是否继续出战？',.5,.49),
                     token('取消',.4,.62),token('确认',.62,.62)])
        setup=Scene([token('位面饰品提取',.12,.05),token('开始挑战',.87,.91),token('下载角色',.35,.69)])
        self.assertTrue(incomplete_team(popup))
        ctx=FakeContext([popup,setup],Settings(dungeon_category='planar'))
        ctx.planar_approach=Mock()
        with self.assertRaisesRegex(AutomationError,'队伍有空位'):
            DailyWorkflow(ctx)._enter_planar_battle()
        self.assertEqual(ctx.clicks,['取消'])
        ctx.planar_approach.assert_not_called()

    def test_unrelated_du_plane_or_missing_boss_header_never_allows_approach(self):
        self.assertTrue(field_ready(field()))
        for label in ("第一位面","位面地图","开始挑战","挑战成功"):
            scene=field();scene.tokens.append(token(label,.5,.5))
            self.assertFalse(field_ready(scene))
        scene=field();scene.tokens.pop()
        self.assertFalse(field_ready(scene))

    def test_context_requires_current_planar_start_pending_cost_and_field(self):
        import time
        from autohsr.app import Context
        runner=SimpleNamespace(settings=Settings(dungeon_category="planar"),report=RunReport(operation="daily",stamina_pending=40),
                               input_epoch=0,checkpoint=Mock(),_stop=threading.Event(),_pause=threading.Event())
        window=Mock();context=Context(runner,window,Mock())
        context.evidence=Mock();context.sleep=Mock()
        for pending,category in ((0,"planar"),(40,"cavern")):
            runner.report.stamina_pending=pending;runner.settings.dungeon_category=category
            scene=field();scene.captured_at=time.monotonic();context.last_scene=scene
            with self.assertRaises(AutomationError):
                context.planar_approach(scene)
            window.key_hold.assert_not_called()
        runner.report.stamina_pending=40;runner.settings.dungeon_category="planar"
        scene=field();scene.captured_at=time.monotonic();context.last_scene=scene
        context.planar_approach(scene)
        self.assertEqual(window.key_hold.call_args.args[:2],("w",600))
        self.assertEqual(runner.report.stamina_pending,40)
        self.assertIsNone(context.last_scene)

    def test_held_key_aborts_before_blocking_pause_checkpoint(self):
        import time
        from autohsr.app import Context
        from autohsr.models import InputInterrupted
        runner=SimpleNamespace(settings=Settings(dungeon_category="planar"),report=RunReport(operation="daily",stamina_pending=40),
                               input_epoch=0,checkpoint=Mock(),_stop=threading.Event(),_pause=threading.Event())
        window=Mock();context=Context(runner,window,Mock())
        context.evidence=Mock();context.sleep=Mock()
        scene=field();scene.captured_at=time.monotonic();context.last_scene=scene
        def during_hold(*args,checkpoint,**kwargs):
            runner._pause.set()
            runner.checkpoint.reset_mock()
            checkpoint()
        window.key_hold.side_effect=during_hold
        with self.assertRaises(InputInterrupted):
            context.planar_approach(scene)
        runner.checkpoint.assert_not_called()

    def test_field_retries_are_limited_and_do_not_replay_start(self):
        scene=field();ctx=FakeContext([scene],Settings(dungeon_category="planar"))
        ctx.planar_approach=Mock()
        ctx.template_matches={"planar_attack_mouse":[(.89,.845,.99)]}
        with self.assertRaisesRegex(AutomationError,"四次"):
            DailyWorkflow(ctx)._enter_planar_battle()
        self.assertEqual(ctx.planar_approach.call_count,4)
        self.assertEqual(len(ctx.clicks),4)
        self.assertNotIn("开始挑战",ctx.clicks)


if __name__ == "__main__":
    unittest.main()
