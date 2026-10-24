import unittest
from unittest.mock import Mock
import numpy as np
from autohsr.models import Scene,Token,AutomationError
from autohsr.policy import guard_click
from autohsr.free_rewards import (mail_entry,mailbox,mail_claimed,claim_enabled,battlepass_page,
    battlepass_modal,battlepass_tab,task_category,battlepass_progress,battlepass_settled)
from autohsr.tests.test_du_team import fixture


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
