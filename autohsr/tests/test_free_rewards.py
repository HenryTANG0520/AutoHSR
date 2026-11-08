import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
import cv2
import numpy as np
from autohsr.models import Scene,Token,AutomationError
from autohsr.config import Settings
from autohsr.policy import guard_click
from autohsr.free_rewards import (mail_entry,mailbox,mail_claimed,claim_enabled,battlepass_claim_target,battlepass_page,
    battlepass_modal,battlepass_tab,task_category,battlepass_progress,battlepass_settled)
from autohsr.tests.test_du_team import fixture
from autohsr.vision import Vision
from autohsr.workflows import DailyWorkflow


def with_battlepass_category_badge(scene, category):
    """Move the historical badge to the requested row in a synthetic replay."""
    original = fixture('bp_tasks_claimable').image
    image = scene.image.copy()
    image[25:55, 970:1000] = original[25:55, 970:1000]
    top = 369 if category == '本周任务' else 631
    image[top:top+28, 344:371] = original[369:397, 344:371]
    return replace(scene, image=image)


class FreeRewardTests(unittest.TestCase):
    def test_badged_icon_only_mail_requires_both_phone_and_matching_glyph(self):
        scene=fixture('phone_mail_icon');target=mail_entry(scene)
        self.assertIsNotNone(target);guard_click(scene,target)
        with self.assertRaises(AutomationError):guard_click(scene,target.center)
        with self.assertRaises(AutomationError):guard_click(scene,Token('phone_mail_body',.99,(.95,.30,.98,.32)))
        scene.image=np.zeros_like(scene.image)
        self.assertIsNone(mail_entry(scene))
        with self.assertRaises(AutomationError):guard_click(scene,target)
        self.assertIsNone(mail_entry(Scene([],fixture('phone_mail_icon').image)))

    def test_mailbox_alias_and_gold_global_claim_are_observed(self):
        scene=fixture('mail_claimable')
        self.assertTrue(mailbox(scene))
        target=scene.find('全部领取',exact=True)
        self.assertIs(claim_enabled(scene,target),True)
        scene.image=np.zeros_like(scene.image)
        self.assertIsNone(claim_enabled(scene,target))

    def test_transparent_disabled_mail_arrow_is_required_instead_of_darkness(self):
        before,after=fixture('mail_claimable'),fixture('mail_claimed')
        self.assertFalse(mail_claimed(before));self.assertTrue(mail_claimed(after))
        after.image=np.zeros_like(after.image)
        self.assertFalse(mail_claimed(after))

    def test_static_paid_buttons_do_not_hide_existing_free_rewards(self):
        for name,kind,eligible in [('bp_rewards_claimable','rewards',True),
                ('bp_rewards_settled','rewards',False),('bp_tasks_claimable','tasks',True),
                ('bp_tasks_settled','tasks',False),('bp_period_settled','tasks',False)]:
            with self.subTest(name=name):
                scene=fixture(name)
                self.assertEqual(battlepass_page(scene),kind)
                self.assertFalse(battlepass_modal(scene))
                self.assertEqual(battlepass_settled(scene,kind),not eligible)
                target=scene.find('一键领取',exact=True)
                if eligible:
                    self.assertIs(claim_enabled(scene,target),True);guard_click(scene,target)
                for text in ('购买等级','解锁无名客的荣勋'):
                    target=scene.find(text,exact=True)
                    if target:
                        with self.assertRaises(AutomationError):guard_click(scene,target)

    def test_task_categories_and_level_progress_change_without_item_popup(self):
        before,after=fixture('bp_tasks_claimable'),fixture('bp_tasks_settled')
        self.assertTrue(task_category(before,'本周任务'))
        self.assertTrue(task_category(after,'本周任务'))
        self.assertFalse(task_category(after,'本期任务'))
        self.assertTrue(task_category(fixture('bp_period_settled'),'本期任务'))
        self.assertEqual(battlepass_progress(before),(32,500,800))
        self.assertEqual(battlepass_progress(after),(33,400,800))

    def test_battlepass_locally_rereads_the_real_4k_weekly_footer(self):
        page = fixture('bp_tasks_claimable')
        original = page.find('一键领取', exact=True)
        alias = Token('-键领取', .87587, (3302/3840, 1806/2160, 3464/3840, 1862/2160))
        page.tokens = [alias if token == original else token for token in page.tokens]
        page.image = cv2.resize(page.image, (3840, 2160))
        path = Path(__file__).parent/'fixtures/du_runtime/bp_weekly_bulk_footer_46.png'
        page.image[1755:1939, 3000:3717] = cv2.imdecode(np.fromfile(path, np.uint8), cv2.IMREAD_COLOR)
        vision = Vision(.65)
        self.assertEqual(battlepass_claim_target(page, vision, .65), alias)
        self.assertIsNone(battlepass_claim_target(page, vision, .90))
        self.assertIsNone(battlepass_claim_target(page, None, .65))
        self.assertIsNone(battlepass_claim_target(replace(page, tokens=[*page.tokens, original]), vision, .65))
        modal = Token('选择奖励', .99, (.4, .4, .6, .5))
        self.assertIsNone(battlepass_claim_target(replace(page, tokens=[*page.tokens, modal]), vision, .65))
        page.image[1755:1939, 3000:3717] = 100
        self.assertIsNone(battlepass_claim_target(page, vision, .65))

    def test_unreadable_bulk_alias_remains_counterevidence_for_settlement(self):
        settled = fixture('bp_tasks_settled')
        settled.tokens.append(Token('键领取', .71, (.86, .83, .90, .86)))
        self.assertFalse(battlepass_settled(settled, 'tasks'))

    def test_combined_task_badge_can_be_attributed_only_to_the_other_category(self):
        cases = (('bp_tasks_settled', '本周任务', '本期任务'),
                 ('bp_period_settled', '本期任务', '本周任务'))
        for name, current, other in cases:
            settled = fixture(name)
            mixed = with_battlepass_category_badge(settled, other)
            for width in (1920, 1280, 960):
                with self.subTest(current=current, width=width):
                    image = cv2.resize(mixed.image, (width, round(width*9/16)), interpolation=cv2.INTER_AREA)
                    scene = replace(mixed, image=image)
                    self.assertFalse(battlepass_settled(scene, 'tasks'))
                    self.assertTrue(battlepass_settled(scene, 'tasks', category=current))
                    self.assertFalse(battlepass_settled(scene, 'tasks', category=other))
            self.assertFalse(battlepass_settled(with_battlepass_category_badge(mixed, current),
                                               'tasks', category=current))

    def test_other_badge_does_not_hide_current_claim_or_unknown_badge(self):
        scene = with_battlepass_category_badge(fixture('bp_tasks_settled'), '本期任务')
        row_claim = Token('领取', .99, (.87, .48, .90, .51))
        with_claim = replace(scene, tokens=[*scene.tokens, row_claim])
        self.assertFalse(battlepass_settled(with_claim, 'tasks', category='本周任务'))
        scene.image[900:945, 1588:1794] = (30, 175, 245)
        self.assertFalse(battlepass_settled(scene, 'tasks', category='本周任务'))
        scene = with_battlepass_category_badge(fixture('bp_tasks_settled'), '本期任务')
        scene.image[631:659, 344:371] = (0, 0, 255)
        self.assertFalse(battlepass_settled(scene, 'tasks', category='本周任务'))
        scene.image[631:659, 344:371] = fixture('bp_tasks_settled').image[631:659, 344:371]
        self.assertFalse(battlepass_settled(scene, 'tasks', category='本周任务'))

    def test_ordinary_battlepass_cannot_confirm_weekly_claim_from_period_tab(self):
        weekly = fixture('bp_tasks_claimable')
        period = fixture('bp_period_settled')
        self.assertGreater(battlepass_progress(period)[:2], battlepass_progress(weekly)[:2])
        flow = DailyWorkflow(Mock(settings=Settings()))
        flow._snapshot = Mock(return_value=weekly)
        flow._click = Mock(return_value=period)

        def wait(predicate, *, description):
            if description == '确认勋礼页面已加载':
                self.assertTrue(predicate(weekly))
                return weekly
            self.assertEqual(description, '核实勋礼任务经验到账')
            self.assertFalse(predicate(period))
            raise AutomationError('原分类未核实')

        flow._wait = wait
        with self.assertRaisesRegex(AutomationError, '原分类未核实'):
            flow.battlepass()
        flow._click.assert_called_once_with(weekly, weekly.find('一键领取', exact=True))

    def test_top_tabs_require_current_page_and_glyph_and_ignore_badges(self):
        self.assertIsNotNone(battlepass_tab(fixture('bp_rewards_claimable'),'tasks'))
        self.assertIsNotNone(battlepass_tab(fixture('bp_tasks_claimable'),'rewards'))
        self.assertIsNone(battlepass_tab(fixture('phone_mail_icon'),'tasks'))
        scene=fixture('bp_rewards_claimable');scene.image=np.zeros_like(scene.image)
        self.assertIsNone(battlepass_tab(scene,'tasks'))

    def test_missing_claim_during_transition_or_real_modal_is_not_complete(self):
        scene=fixture('bp_rewards_claimable')
        scene.tokens=[t for t in scene.tokens if t.text!='一键领取']
        self.assertFalse(battlepass_settled(scene,'rewards'))  # tab red dot survives
        scene=fixture('bp_rewards_settled')
        scene.tokens.append(Token('选择奖励',.99,(.4,.4,.6,.5)))
        self.assertTrue(battlepass_modal(scene));self.assertFalse(battlepass_settled(scene,'rewards'))
        self.assertFalse(battlepass_settled(fixture('phone_mail_icon'),None))
