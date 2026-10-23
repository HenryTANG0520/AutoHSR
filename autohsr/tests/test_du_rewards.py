import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import numpy as np
import cv2
from autohsr.config import Settings
from autohsr.models import Scene,Token,AutomationError
from autohsr.du_rewards import red_dots,home_targets,page_kind,guard_click,collect


def t(text,x,y):
    return Token(text,.99,(x-.02,y-.01,x+.02,y+.01))


def badge(image,x,y,white=True):
    h,w=image.shape[:2]
    scale=h/720
    center=(round(x*w),round(y*h))
    cv2.circle(image,center,round(10*scale),(35,35,230),-1)
    if white:
        cv2.line(image,(center[0],center[1]-round(5*scale)),
                 (center[0],center[1]+round(2*scale)),(255,255,255),round(2*scale))


class DuRewardTests(unittest.TestCase):
    def test_offscreen_gallery_notification_pans_toward_hidden_category(self):
        from autohsr.du_rewards import gallery_pan_plan, gallery_targets, collect_gallery,guard_pan
        from autohsr.tests.test_du_team import fixture
        page=fixture('gallery_offscreen_notification')
        self.assertEqual(page_kind(page),'gallery_home')
        self.assertEqual(gallery_targets(page),[])
        plan=gallery_pan_plan(page)
        self.assertEqual(plan,((.80,.65),(.35,.65)))
        guard_pan(page,*plan)
        cleared=Scene(page.tokens,np.zeros_like(page.image))
        self.assertIsNone(gallery_pan_plan(cleared))
        with self.assertRaises(AutomationError):
            guard_pan(Scene([]),*plan)
        with self.assertRaises(AutomationError):
            guard_pan(page,(.8,.65),(.35,.20))
        left=Scene(page.tokens,np.zeros_like(page.image));badge(left.image,.025,.26)
        self.assertEqual(gallery_pan_plan(left),tuple(reversed(plan)))
        # A translated category label is the evidence that the viewport moved.
        moved=Scene([Token(v.text,v.score,(v.box[0]-.10,v.box[1],v.box[2]-.10,v.box[3]))
                     if v.text=='方程' else v for v in page.tokens],cleared.image)
        ctx=Mock()
        def wait(predicate,**kwargs):
            self.assertFalse(predicate(page))
            self.assertTrue(predicate(moved))
            return moved
        ctx.wait.side_effect=wait
        self.assertIs(collect_gallery(SimpleNamespace(ctx=ctx),page,{'claims':[]}),moved)
        self.assertEqual(ctx.drag.call_args.kwargs['du_intent'],'du_reward_gallery_pan')
        ctx.click.assert_not_called()

    def test_all_surveyed_gallery_tabs_and_icon_only_claimed_rows(self):
        from autohsr.tests.test_du_team import fixture
        from autohsr.du_rewards import gallery_milestone_rows
        for name in ('blessing','curio','equation','weighted','event'):
            with self.subTest(category=name):
                self.assertEqual(page_kind(fixture('gallery_'+name+'_category')),'gallery_category')
        for name in ('blessing','curio','equation','miracle','event'):
            with self.subTest(milestones=name):
                page=fixture('gallery_'+name+'_milestones')
                self.assertEqual(page_kind(page),'gallery_milestones')
                self.assertEqual(len(gallery_milestone_rows(page)),5)
        after=fixture('gallery_event_after_claim')
        self.assertEqual(page_kind(after),'gallery_milestones')
        self.assertEqual([v.text for _,v in gallery_milestone_rows(after)].count('已领取'),4)
        for name in ('blessing','curio','equation'):
            self.assertEqual([v.text for _,v in gallery_milestone_rows(fixture('gallery_'+name+'_milestones'))],['已领取']*5)
        # Row labels alone cannot authorize a claim on a different page.
        blank=Scene(after.tokens,np.zeros_like(after.image))
        self.assertIsNone(page_kind(blank))

    def test_rewards_revisit_fitting_after_another_category_unlocks_new_tier(self):
        import json
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime/fit_65_red_after_steady'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        fit_home=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                       cv2.imread(str(root.with_suffix('.png'))))
        self.assertEqual([t.text for t in home_targets(fit_home)],['拟合等级'])
        blank=np.zeros_like(fit_home.image)
        steady_home=Scene(fit_home.tokens,blank.copy());badge(steady_home.image,.976,.579)
        both_home=Scene(fit_home.tokens,fit_home.image.copy());badge(both_home.image,.976,.579)
        cleared=Scene(fit_home.tokens,blank)
        fit=Scene([t('差分宇宙',.1,.05),t('675/800',.5,.51),
                   t('64',.42,.835),t('65',.50,.835),t('66',.58,.835)])
        steady=Scene([t('稳态数组',.1,.05),t('测试',.4,.1),t('难题',.58,.1)])
        pages=iter([fit,steady_home,steady,fit_home,fit,cleared])
        def wait(predicate,**kwargs):
            page=next(pages);self.assertTrue(predicate(page),kwargs.get('description'));return page
        ctx=Mock();ctx.wait.side_effect=wait
        flow=SimpleNamespace(ctx=ctx,settings=Settings(differential_universe_rewards=True),
                             report={},_persist_ledger=Mock())
        def claimed(workflow,page,report,*args):
            report['claims'].append({'source':args[0] if args else '稳态数组','result':'reward_overlay'})
            return page
        with patch('autohsr.du_rewards.collect_fit',side_effect=claimed), \
             patch('autohsr.du_rewards.collect_steady',side_effect=claimed):
            self.assertIs(collect(flow,both_home),cleared)
        report=flow.report['reward_collection']
        self.assertEqual(report['visits'],['拟合等级','稳态数组','拟合等级'])
        self.assertEqual(len(report['claims']),3)
        self.assertEqual(report['status'],'complete')

    def test_reward_revisit_without_new_receipt_stops_and_clears_old_complete_status(self):
        image=np.zeros((720,1280,3),np.uint8);badge(image,.974,.43)
        hub=Scene([t('差分宇宙',.1,.05),t('乐园漫记',.1,.11),
                   t('开始游戏',.82,.90),t('拟合等级',.94,.45)],image)
        fit=Scene([t('差分宇宙',.1,.05),t('675/800',.5,.51),
                   t('64',.42,.835),t('65',.50,.835),t('66',.58,.835)])
        ctx=Mock();ctx.wait.side_effect=[fit,hub]
        report={'claims':[],'visits':[],'status':'complete','home_evidence':'old home'}
        flow=SimpleNamespace(ctx=ctx,settings=Settings(differential_universe_rewards=True),
                             report={'reward_collection':report},_persist_ledger=Mock())
        with patch('autohsr.du_rewards.collect_fit',return_value=fit):
            with self.assertRaisesRegex(AutomationError,'没有新的奖励到账进展'):
                collect(flow,hub)
        self.assertEqual(report['status'],'failed')
        self.assertNotIn('home_evidence',report)
        self.assertIn('failure_reason',report)
        self.assertEqual(ctx.click.call_count,1)
        self.assertGreaterEqual(flow._persist_ledger.call_count,3)

    def test_native_gallery_pages_bind_marked_entries_and_earned_claim(self):
        import json
        from pathlib import Path
        from autohsr.du_rewards import gallery_targets,gallery_progress_target
        root=Path(__file__).parent/'fixtures/du_runtime'
        pages=[]
        for name in ('gallery_home','gallery_category','gallery_milestones'):
            data=json.loads((root/f'{name}.json').read_text(encoding='utf8'))
            page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                       cv2.imread(str(root/f'{name}.png')))
            self.assertEqual(page_kind(page),name)
            pages.append(page)
        category=gallery_targets(pages[0])
        self.assertEqual([v.text for v in category],['惊世奇迹'])
        guard_click(pages[0],category[0],'du_reward_gallery_category')
        progress=gallery_progress_target(pages[1])
        self.assertIsNotNone(progress)
        guard_click(pages[1],progress,'du_reward_gallery_progress')
        claim=pages[2].find('领取',(.68,.27,.79,.79),exact=True)
        self.assertIsNotNone(claim)
        guard_click(pages[2],claim,'du_reward_gallery_claim')

    def test_gallery_follows_marked_category_progress_then_verified_claim(self):
        from autohsr.du_rewards import gallery_targets,gallery_progress_target,collect_gallery
        image=np.zeros((720,1280,3),np.uint8);badge(image,.403,.604)
        root=Scene([t('可能性画廊',.08,.05),t('奖励领取进度76%',.77,.06),
                    t('收集进度58%',.90,.06),t('惊世奇迹',.35,.62)],image)
        self.assertEqual(page_kind(root),'gallery_home')
        target=gallery_targets(root)[0]
        guard_click(root,target,'du_reward_gallery_category')
        marked=np.zeros_like(image);badge(marked,.239,.891)
        category=Scene([t('惊世奇迹',.08,.05),t('惊世奇迹一览[42/200]',.20,.135),
                        t('奖励进度2/5',.16,.915)],marked)
        self.assertEqual(page_kind(category),'gallery_category')
        progress=gallery_progress_target(category)
        self.assertIsNotNone(progress)
        guard_click(category,progress,'du_reward_gallery_progress')
        claim=t('领取',.74,.326)
        milestones=Scene([t('并奇迹返现',.27,.235),t('累计解锁数量达到',.28,.30),
                          t('累计解锁数量达到',.28,.40),claim,t('进行中',.74,.425)])
        self.assertEqual(page_kind(milestones),'gallery_milestones')
        guard_click(milestones,claim,'du_reward_gallery_claim')
        with self.assertRaises(AutomationError):
            guard_click(milestones,milestones.tokens[-1],'du_reward_gallery_claim')
        overlay=Scene([t('获得物品',.5,.15),t('点击空白处关闭',.5,.8)])
        claimed=Scene([token for token in milestones.tokens if token is not claim]+[t('已领取',.74,.326)])
        unmarked=Scene(category.tokens,np.zeros_like(image))
        cleared=Scene(root.tokens,np.zeros_like(image))
        pages=iter([category,milestones,overlay,claimed,unmarked,cleared])
        def wait(predicate,**kwargs):
            page=next(pages)
            self.assertTrue(predicate(page),kwargs.get('description'))
            return page
        ctx=Mock();ctx.wait.side_effect=wait
        flow=SimpleNamespace(ctx=ctx)
        report={'claims':[]}
        self.assertIs(collect_gallery(flow,root,report),cleared)
        self.assertEqual(len(report['claims']),1)
        self.assertEqual(ctx.key.call_count,2)
        self.assertEqual([c.kwargs['du_intent'] for c in ctx.click.call_args_list],
                         ['du_reward_gallery_category','du_reward_gallery_progress',
                          'du_reward_gallery_claim','du_reward_dismiss'])
        self.assertIsNone(gallery_progress_target(unmarked))
        with self.assertRaises(AutomationError):
            guard_click(unmarked,progress,'du_reward_gallery_progress')

    def test_optional_gallery_collection_resumes_visible_reward_modal(self):
        claim=t('领取',.74,.326)
        modal=Scene([t('并奇迹返现',.27,.235),t('累计解锁数量达到',.28,.30),
                     t('累计解锁数量达到',.28,.40),t('进行中',.74,.425),claim])
        overlay=Scene([t('获得物品',.5,.15),t('点击空白处关闭',.5,.8)])
        claimed=Scene(modal.tokens[:-1]+[t('已领取',.74,.326)])
        category=Scene([t('惊世奇迹',.08,.05),t('惊世奇迹一览[42/200]',.20,.135),
                        t('奖励进度3/5',.16,.915)])
        gallery=Scene([t('可能性画廊',.08,.05),t('奖励领取进度77%',.77,.06),
                       t('收集进度58%',.90,.06)])
        hub=Scene([t('差分宇宙',.1,.05),t('乐园漫记',.1,.11),t('开始游戏',.82,.90)])
        pages=iter([overlay,claimed,category,gallery,hub])
        def wait(predicate,**kwargs):
            page=next(pages);self.assertTrue(predicate(page));return page
        ctx=Mock();ctx.wait.side_effect=wait
        flow=SimpleNamespace(ctx=ctx,settings=Settings(differential_universe_rewards=True),
                             report={},_persist_ledger=Mock())
        self.assertIs(collect(flow,modal),hub)
        self.assertEqual(flow.report['reward_collection']['status'],'complete')
        self.assertEqual([c.kwargs['du_intent'] for c in ctx.click.call_args_list],
                         ['du_reward_gallery_claim','du_reward_dismiss'])

    def test_all_moon_items_obtained_is_terminal_reward_page(self):
        from autohsr.du_rewards import collect_moon,moon_balance,moon_unlock_target
        page=Scene([t('月下奇谭·卷四',.29,.17),t('道具一览',.2,.61),
                    t('所有道具均已获得',.74,.71),t('0',.91,.06)])
        self.assertEqual(page_kind(page),'moon_rewards')
        self.assertEqual(moon_balance(page),0)
        self.assertIsNone(moon_unlock_target(page))
        flow=SimpleNamespace(ctx=Mock())
        self.assertIs(collect_moon(flow,page,{}),page)
        flow.ctx.click.assert_not_called()

    def test_unknown_home_notification_is_not_reported_as_all_claimed(self):
        image=np.zeros((720,1280,3),np.uint8);badge(image,.14,.32)
        page=Scene([t('差分宇宙',.1,.05),t('乐园漫记',.1,.11),t('开始游戏',.82,.90)],image)
        flow=SimpleNamespace(settings=Settings(differential_universe_rewards=True),ctx=Mock(),report={},_persist_ledger=Mock())
        with self.assertRaisesRegex(AutomationError,'未报告全部领完'):
            collect(flow,page)
        self.assertEqual(flow.report['reward_collection']['status'],'unhandled_notification')
        flow.ctx.click.assert_not_called()

    def test_native_zero_balance_fallback_never_grants_an_unlock(self):
        import json
        from pathlib import Path
        from autohsr.vision import Vision
        from autohsr.du_rewards import moon_balance,moon_unlock_target
        root=Path(__file__).parent/'fixtures/du_runtime'
        meta=json.loads((root/'moon_balance_zero.json').read_text())
        w,h=meta['source_size']; image=np.zeros((h,w,3),np.uint8)
        x1,y1,x2,y2=meta['crop_normalized']
        image[round(y1*h):round(y2*h),round(x1*w):round(x2*w)]=cv2.imdecode(np.fromfile(root/'moon_balance_zero.png',np.uint8),1)
        page=Scene([t('月下奇谭',.27,.17),t('道具一览',.20,.61),
                    t('使用卡带获取下一道具',.74,.68),t('解锁',.78,.77),t('×100',.70,.77)],image)
        vision=Vision.__new__(Vision); vision._read_field=Mock(return_value=None)
        vision.refine_du_reward_balance(page)
        self.assertEqual(moon_balance(page),0)
        self.assertIsNone(moon_unlock_target(page))
        # Missing pixels must leave balance unknown, not fabricate a zero.
        blank=Scene(page.tokens[:-1],np.zeros_like(image))
        vision.refine_du_reward_balance(blank)
        self.assertIsNone(moon_balance(blank))

    def test_unearned_red_avatar_art_is_not_a_reward_badge(self):
        from pathlib import Path
        path=Path(__file__).parent/'fixtures/du_runtime/rewards_fit_unearned_avatar.png'
        image=cv2.imdecode(np.fromfile(path,np.uint8),1)
        self.assertEqual(red_dots(Scene([],image)),[])

    def test_masked_client_frames_recognize_home_fit_and_three_badges(self):
        import json
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime'
        for row in json.loads((root/'reward_pages.json').read_text('utf-8')):
            with self.subTest(file=row['file']):
                page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in row['tokens']],
                           cv2.imdecode(np.fromfile(root/row['file'],np.uint8),1))
                self.assertEqual(page_kind(page),row['kind'])
                self.assertEqual(len(red_dots(page)),row['dots'])
                if row['kind']=='home':
                    self.assertEqual([v.text for v in home_targets(page)],['拟合等级','月下奇谭','稳态数组'])

    def test_optional_rewards_default_off_and_do_not_touch_ui(self):
        self.assertFalse(Settings().differential_universe_rewards)
        with self.assertRaises(ValueError):
            Settings(differential_universe_rewards=1).validate('differential_universe')
        flow=SimpleNamespace(settings=Settings(),ctx=Mock(),report={})
        page=Scene([])
        self.assertIs(collect(flow,page),page)
        flow.ctx.click.assert_not_called()

    def test_home_requires_a_badge_bound_to_the_entry(self):
        image=np.zeros((720,1280,3),np.uint8)
        page=Scene([t('差分宇宙',.1,.05),t('乐园漫记',.1,.11),t('开始游戏',.82,.90),
                    t('拟合等级',.94,.45),t('月下奇谭',.86,.32)],image)
        self.assertEqual(home_targets(page),[])
        badge(image,.974,.43)
        badge(image,.5,.5) # unrelated red marker
        badge(image,.89,.30,False) # plain red art, no white notification mark
        targets=home_targets(page)
        self.assertEqual([v.text for v in targets],['拟合等级'])
        guard_click(page,targets[0],'du_reward_open')
        with self.assertRaises(AutomationError):
            guard_click(page,page.tokens[-1],'du_reward_open')

    def test_fit_dots_are_only_clickable_on_correlated_reward_screen(self):
        image=np.zeros((720,1280,3),np.uint8)
        badge(image,.345,.741)
        page=Scene([t('差分宇宙',.1,.05),t('425/800',.5,.51),
                    t('42',.33,.835),t('43',.42,.835),t('44',.5,.835)],image)
        self.assertEqual(page_kind(page),'fit_rewards')
        dot=red_dots(page)[0]
        guard_click(page,dot,'du_reward_dot')
        with self.assertRaises(AutomationError):
            guard_click(Scene([],image),dot,'du_reward_dot')
        page.tokens[1]=t('425/800',.7,.1)
        self.assertIsNone(page_kind(page))
