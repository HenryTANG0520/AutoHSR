"""Preferred support uses real image references and native feedback, no game IO."""
from contextlib import redirect_stdout,redirect_stderr
from dataclasses import replace
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr.config import Settings,SettingsError,RESOURCE_ROOT
from autohsr.models import AutomationError,Scene,Token
from autohsr.support_portraits import identify,references
from autohsr.support_profiles import catalogue,preferences
from autohsr.workflows import DailyWorkflow
from autohsr.tests import test_core as core


def config(prefs,**changes):
    return replace(Settings(support_preferences=prefs,support_scroll_pages=1),**changes)


def pref(character='',friend=''):return dict(character=character,friend=friend)


def picker(rows,*,marker=None,badges=False,scale=1.):
    page=core.support_picker([(name,y,friend) for name,y,role,friend in rows],marker)
    if page.image is None:page.image=np.full((1080,1920,3),80,np.uint8)
    for name,y,role,friend in rows:
        image=cv2.imdecode(np.frombuffer((RESOURCE_ROOT/'assets/upstream/March7thAssistant/support'/(role+'.png')).read_bytes(),np.uint8),1)
        x,top=48,round((y-.018)*1080);h,w=image.shape[:2]
        page.image[top:top+h,x:x+w]=image
        if badges:
            page.image[top:top+round(h*.26),x+w-round(w*.26):x+w]=(0,180,255)
            page.image[top+round(h*.22):top+round(h*.65),x:x+round(w*.26)]=(245,245,245)
    if scale!=1:page.image=cv2.resize(page.image,None,fx=scale,fy=scale)
    return page


def planar_picker(rows,marker=False):
    data=picker(rows,marker='green' if marker else None)
    data.tokens.extend([core.token('支援列表',.1,.05),core.token('刷新列表',.1,.9),
                        core.token('下载角色',.4,.68),core.token('开始挑战',.88,.92)])
    return data


def planar_team(marker=False):
    data=Scene([core.token('位面饰品提取',.1,.05),core.token('下载角色',.4,.68),
                core.token('支援',.35,.86),core.token('开始挑战',.88,.92)],np.full((1080,1920,3),80,np.uint8))
    if marker:
        data.tokens.append(Token('支援',.99,(.375,.78,.395,.80)))
        data.image[842:864,720:760]=(65,150,75)
    return data


class PreferenceTests(unittest.TestCase):
    def test_order_alias_and_literal_friend_are_preserved(self):
        self.assertEqual(preferences([pref('青雀','A!'),pref('FuXuan','')])[0].character,'Qingque')
        self.assertEqual(preferences([pref(friend='A!')])[0].friend,'A!')

    def test_settings_snapshot_and_explicit_save_only(self):
        value=config([pref('Cyrene','甲')]);snapshot=replace(value)
        value.support_preferences[0]['friend']='乙'
        self.assertEqual(snapshot.support_preferences[0]['friend'],'甲')
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'config.json';snapshot.save(path)
            self.assertEqual(Settings.load(path),snapshot)

    def test_invalid_preferences_and_search_options_reject_before_runtime(self):
        for value in (None,{},[pref()],[pref('unknown')],[dict(pref('Cyrene'),extra=1)],
                      [pref(friend=1)],[pref('Cyrene'),pref('Cyrene')],[pref(friend='x'*41)]):
            with self.subTest(value=value),self.assertRaises((SettingsError,ValueError)):
                config(value).validate('daily')
        for changes in (dict(support_scroll_pages=0),dict(support_scroll_pages=21),dict(support_scroll_pages=True),
                        dict(support_fallback='first'),dict(support_fallback='skip',support_preferences=[])):
            with self.subTest(changes=changes),self.assertRaises(SettingsError):replace(config([pref('Cyrene')]),**changes).validate()

    def test_all_pinned_portrait_bytes_and_dimensions_match_manifest(self):
        self.assertEqual(len(catalogue()),105)
        self.assertEqual(len(references()),105)
        root=RESOURCE_ROOT/'assets/upstream/March7thAssistant/support'
        for role,data in catalogue().items():
            self.assertEqual(hashlib.sha256((root/data['file']).read_bytes()).hexdigest(),data['sha256'],role)


class PortraitTests(unittest.TestCase):
    def row(self,page,index=0):return DailyWorkflow._support_friend_rows(page)[index]

    def test_roles_are_local_to_complete_card_and_discriminate_forms(self):
        page=picker([('甲',.203,'Cyrene',True),('乙',.331,'SilverWolfLV999',True)])
        self.assertEqual(identify(page,self.row(page),{'Cyrene'}).character,'Cyrene')
        self.assertIsNone(identify(page,self.row(page),{'SilverWolfLV999'}))
        self.assertIsNone(identify(page,self.row(page,1),{'SilverWolf'}))
        self.assertEqual(identify(page,self.row(page,1),{'SilverWolfLV999'}).character,'SilverWolfLV999')

    def test_corner_and_star_badges_retry_without_lowering_threshold(self):
        page=picker([('甲',.203,'Cyrene',True)],badges=True)
        found=identify(page,self.row(page),{'Cyrene'})
        self.assertIsNotNone(found)
        self.assertEqual(found.mask_mode,'card_badges')
        self.assertGreaterEqual(found.score,.90)

    def test_supported_capture_scales_use_normalized_card_binding(self):
        for scale in (.5,1.,2.):
            with self.subTest(scale=scale):
                page=picker([('甲',.203,'FuXuan',True)],scale=scale)
                found=identify(page,self.row(page),{'FuXuan'})
                self.assertIsNotNone(found)
                self.assertEqual(found.character,'FuXuan')

    def test_unknown_constant_and_ambiguous_reference_never_confirm_role(self):
        page=picker([('甲',.203,'Cyrene',True)])
        blank=Scene(page.tokens,np.zeros_like(page.image))
        self.assertIsNone(identify(blank,self.row(page),{'Cyrene'}))
        bank=references()
        with patch('autohsr.support_portraits.references',return_value={'Cyrene':bank['Cyrene'],'other':bank['Cyrene']}):
            self.assertIsNone(identify(page,self.row(page),{'Cyrene'}))


class SelectionTests(unittest.TestCase):
    def run_support(self,pages,settings):
        ctx=core.FakeContext(pages,settings);flow=DailyWorkflow(ctx)
        return ctx,flow

    def test_role_and_friend_select_same_card_in_preference_order(self):
        rows=[('甲',.203,'Cyrene',True),('乙',.331,'Qingque',True)]
        before=picker(rows);selected=picker(rows,marker='green');team=core.support_team('green')
        ctx,flow=self.run_support([core.support_team(),before,selected,team],config([pref('Qingque','乙'),pref('Cyrene','甲')]))
        self.assertIs(flow._support(ctx.snapshot()),team)
        self.assertEqual(ctx.clicks,['支援','好友','确认'])
        self.assertAlmostEqual(ctx.click_targets[1].center[1],.331)
        self.assertEqual(ctx.report.support_selections[-1]['selected']['character'],'Qingque')
        self.assertEqual(ctx.report.support_selections[-1]['state'],'borrowed')

    def test_friend_name_is_exact_not_a_substring_or_punctuation_fold(self):
        rows=[('甲!',.203,'Cyrene',True),('甲',.331,'Qingque',True)]
        team=core.support_team('green')
        ctx,flow=self.run_support([core.support_team(),picker(rows),picker(rows,marker='green'),team],config([pref(friend='甲')]))
        flow._support(ctx.snapshot())
        self.assertAlmostEqual(ctx.click_targets[1].center[1],.331)

    def test_small_card_ocr_position_jitter_keeps_current_identity(self):
        rows=[('甲',.203,'Cyrene',True)];selected=[('甲',.205,'Cyrene',True)]
        ctx,flow=self.run_support([core.support_team(),picker(rows),picker(selected,marker='green'),core.support_team('green')],
            config([pref('Cyrene','甲')]))
        flow._support(ctx.snapshot())
        self.assertEqual(ctx.report.support_selections[-1]['state'],'borrowed')

    def test_nonfriend_never_becomes_preferred_role_candidate(self):
        rows=[('陌生',.203,'Cyrene',False),('好友',.331,'Qingque',True)]
        ctx,flow=self.run_support([core.support_team(),picker(rows)],config([pref('Cyrene')]))
        with self.assertRaises(AutomationError):flow._support(ctx.snapshot())
        self.assertEqual(ctx.clicks,['支援'])
        self.assertEqual(ctx.report.support_selections[-1]['state'],'unverified')

    def test_explicit_full_toast_must_clear_before_next_preference(self):
        rows=[('甲',.203,'Cyrene',True),('乙',.331,'Qingque',True)]
        full=picker(rows);full.tokens.append(core.token('队伍角色已满',.5,.3))
        ctx,flow=self.run_support([core.support_team(),picker(rows),full,picker(rows),picker(rows,marker='green'),core.support_team('green')],
            config([pref(friend='甲'),pref(friend='乙')]))
        flow._support(ctx.snapshot())
        self.assertEqual(ctx.clicks,['支援','好友','好友','确认'])
        self.assertEqual(ctx.report.support_selections[-1]['selected']['friend'],'乙')
        self.assertEqual(ctx.report.support_selections[-1]['attempts'],2)

    def test_unknown_selection_feedback_does_not_try_next_or_confirm(self):
        rows=[('甲',.203,'Cyrene',True),('乙',.331,'Qingque',True)]
        ctx,flow=self.run_support([core.support_team(),picker(rows),picker(rows)],config([pref(friend='甲'),pref(friend='乙')]))
        with self.assertRaises(AutomationError):flow._support(ctx.snapshot())
        self.assertEqual(ctx.clicks,['支援','好友'])
        self.assertNotIn('确认',ctx.clicks)

    def test_only_explicit_skip_returns_without_borrowed_marker(self):
        rows=[('甲',.203,'Cyrene',True)];team=core.support_team()
        ctx,flow=self.run_support([team,picker(rows),team],config([pref('Qingque')],support_fallback='skip'))
        self.assertIs(flow._support(ctx.snapshot()),team)
        self.assertTrue(flow._support_skipped)
        self.assertEqual(ctx.keys,['esc'])
        self.assertEqual(ctx.clicks,['支援'])
        self.assertEqual(ctx.report.support_selections[-1]['state'],'skipped')

    def test_visible_friend_fallback_is_explicit_and_verified(self):
        rows=[('甲',.203,'Cyrene',True)];team=core.support_team('green')
        ctx,flow=self.run_support([core.support_team(),picker(rows),picker(rows),picker(rows,marker='green'),team],
            config([pref('Qingque')],support_fallback='friend'))
        flow._support(ctx.snapshot())
        self.assertTrue(ctx.report.support_selections[-1]['fallback_used'])
        self.assertEqual(ctx.scrolls,[60000])
        self.assertEqual(ctx.clicks,['支援','好友','确认'])

    def test_bounded_scroll_can_find_preferred_friend_on_next_page(self):
        first=[('甲',.203,'Cyrene',True)];second=[('乙',.203,'Qingque',True)]
        ctx,flow=self.run_support([core.support_team(),picker(first),picker(second),picker(second,marker='green'),core.support_team('green')],
            config([pref(friend='乙')],support_scroll_pages=2))
        flow._support(ctx.snapshot())
        self.assertEqual(ctx.scrolls,[-720])
        self.assertEqual(ctx.report.support_selections[-1]['pages_seen'],2)

    def test_changed_card_or_selected_avatar_stops_before_confirmation(self):
        initial=[('甲',.203,'Cyrene',True)];changed=[('甲',.203,'Qingque',True)]
        ctx,flow=self.run_support([core.support_team(),picker(initial),picker(changed,marker='green')],config([pref('Cyrene','甲')]))
        with self.assertRaisesRegex(AutomationError,'头像'):flow._support(ctx.snapshot())
        self.assertNotIn('确认',ctx.clicks)

    def test_missing_or_conflicting_marker_is_not_success(self):
        rows=[('甲',.203,'Cyrene',True)]
        conflict=picker(rows,marker='green');conflict.tokens.append(core.token('队伍角色已满',.5,.3))
        ctx,flow=self.run_support([core.support_team(),picker(rows),conflict],config([pref(friend='甲')]))
        with self.assertRaisesRegex(AutomationError,'冲突'):flow._support(ctx.snapshot())
        self.assertNotIn('确认',ctx.clicks)

    def test_unknown_empty_list_does_not_trigger_skip_fallback(self):
        ctx,flow=self.run_support([core.support_team(),core.support_picker([])],config([pref('Cyrene')],support_fallback='skip'))
        with self.assertRaisesRegex(AutomationError,'完整好友卡片'):flow._support(ctx.snapshot())
        self.assertEqual(ctx.keys,[])

    def test_failed_card_is_not_retried_through_another_preference(self):
        rows=[('甲',.203,'Cyrene',True)]
        full=picker(rows);full.tokens.append(core.token('队伍角色已满',.5,.3))
        ctx,flow=self.run_support([core.support_team(),picker(rows),full,picker(rows)],
            config([pref('Cyrene'),pref(friend='甲')]))
        with self.assertRaises(AutomationError):flow._support(ctx.snapshot())
        self.assertEqual(ctx.clicks,['支援','好友'])

    def test_planar_preferences_use_same_card_binding_and_verified_return(self):
        rows=[('甲',.203,'Cyrene',True)]
        last=planar_team(True)
        ctx,flow=self.run_support([planar_team(),planar_picker(rows),planar_picker(rows,True),last],
            config([pref('Cyrene','甲')],dungeon_category='planar'))
        self.assertIs(flow._support(ctx.snapshot()),last)
        self.assertEqual(ctx.clicks,['支援','好友'])
        self.assertEqual(ctx.keys,['esc'])
        self.assertEqual(ctx.report.support_selections[-1]['state'],'borrowed')

    def test_legacy_planar_also_waits_for_full_toast_to_clear(self):
        rows=[('甲',.203,'Cyrene',True),('乙',.331,'Qingque',True)]
        full=planar_picker(rows);full.tokens.append(core.token('队伍角色已满',.5,.3))
        last=planar_team(True)
        ctx,flow=self.run_support([planar_team(),planar_picker(rows),full,full,planar_picker(rows),planar_picker(rows,True),last],
            config([],dungeon_category='planar'))
        self.assertIs(flow._support(ctx.snapshot()),last)
        self.assertEqual(ctx.clicks,['支援','好友','好友'])
        self.assertEqual(ctx.keys,['esc'])

    def test_legacy_planar_conflicting_feedback_never_skips_to_next_card(self):
        rows=[('甲',.203,'Cyrene',True),('乙',.331,'Qingque',True)]
        full=planar_picker(rows,True);full.tokens.append(core.token('队伍角色已满',.5,.3))
        ctx,flow=self.run_support([planar_team(),planar_picker(rows),full],config([],dungeon_category='planar'))
        with self.assertRaisesRegex(AutomationError,'冲突'):flow._support(ctx.snapshot())
        self.assertEqual(ctx.clicks,['支援','好友'])
        self.assertEqual(ctx.keys,[])


class EntryTests(unittest.TestCase):
    def test_planar_explicit_skip_retains_native_payment_and_completion(self):
        from autohsr.tests import test_power_plan_entry as native
        class World(native.World):
            def scene(self,settings):
                if self.mode=='picker':return planar_picker([('甲',.203,'Cyrene',True)])
                data=super().scene(settings)
                if self.mode=='team':data.tokens.append(core.token('支援',.88,.87))
                return data
        value=config([pref(friend='乙')],support_fallback='skip',dungeon_category='planar',
                     assignments=False,daily=False,daily_synthesis=False,overlay_logs=False,
                     stamina_limit=40,challenge_count=1,rounds=1)
        with tempfile.TemporaryDirectory() as folder,native.runtime(Path(folder),value,World()) as (window,_):
            original=window.click;support_calls=[]
            def click(x,y,geometry):
                target=next(t for t in window.scene.tokens if abs(t.center[0]-x)<1e-6 and abs(t.center[1]-y)<1e-6)
                if target.text=='支援':support_calls.append(target.text);window.world.mode='picker'
                else:original(x,y,geometry)
            def key(name):
                self.assertEqual((name,window.world.mode),('esc','picker'))
                window.world.mode='team'
            window.click=click;window.key=key;window.move=lambda *args:None
            runner=native.Runner(value);window.owner=runner;report=runner.run()
        self.assertEqual(report.status,'success',report.error)
        self.assertEqual(support_calls,['支援'])
        self.assertEqual((report.stamina_spent,report.battle_completed),(40,1))
        self.assertEqual(report.support_selections[-1]['state'],'skipped')

    def test_parent_retains_daily_support_proof_after_weekly_failure(self):
        from autohsr.tests import test_plan_runner as plans
        fixture=plans.PlanTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
        record=dict(state='borrowed',selected=dict(friend='甲',character='Cyrene'))
        fixture.daily['support_selections']=[record]
        original=fixture.factory
        def factory(settings,emit,**options):
            if options['operation']=='differential_universe':raise AutomationError('fixture weekly failure')
            return original(settings,emit,**options)
        runner=fixture.runner();runner.factory=factory;report=runner.run()
        self.assertEqual(report.status,'partial')
        self.assertTrue(report.daily_verified)
        self.assertEqual(report.support_selections,[record])
        saved=json.loads((Path(report.run_dir)/'report.json').read_text('utf8'))
        self.assertEqual(saved['support_selections'],[record])

    def test_cli_preferences_enable_support_only_in_transient_daily_snapshot(self):
        from autohsr.__main__ import main
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);path=root/'config.json';Settings(use_support=False).save(path)
            before=path.read_bytes();prefs=root/'support.json';prefs.write_text(json.dumps([pref('Cyrene','甲')]),encoding='utf-8-sig')
            for mode,factory_name in (('--run','autohsr.app.Runner'),('--plan','autohsr.plan_runner.PlanRunner')):
                with self.subTest(mode=mode),patch(factory_name) as factory,redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                    factory.return_value.run.return_value={'status':'success'}
                    self.assertEqual(main([mode,'--config',str(path),'--support-preferences-file',str(prefs),
                        '--support-scroll-pages','3','--support-fallback','friend']),0)
                    used=factory.call_args.args[0]
                    self.assertTrue(used.use_support)
                    self.assertEqual(used.support_preferences,[pref('Cyrene','甲')])
                    self.assertEqual((used.support_scroll_pages,used.support_fallback),(3,'friend'))
                self.assertEqual(path.read_bytes(),before)

    def test_cli_wrong_scope_or_invalid_profile_does_not_construct_runner(self):
        from autohsr.__main__ import main
        cases=(['--check','--support-scroll-pages','2'],['--support-fallback','skip'],
               ['--run','--reward-only','--support-scroll-pages','3'],
               ['--plan','--resume-weekly-currency','--support-fallback','friend'])
        for args in cases:
            with self.subTest(args=args),patch('autohsr.app.Runner') as factory,redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):main(args)
                factory.assert_not_called()

    def test_formal_runner_uses_native_context_and_returns_verified_support_record(self):
        from autohsr.tests import test_power_plan_entry as native
        class World(native.World):
            borrowed=False
            def scene(self,settings):
                if self.mode in ('picker','selected'):
                    return picker([('甲',.203,'Cyrene',True)],marker='green' if self.mode=='selected' else None)
                data=super().scene(settings)
                if self.mode=='team':
                    data.tokens.append(core.token('支援',.88,.87))
                    if self.borrowed:data=core.support_marker(data)
                return data
        value=config([pref('Cyrene','甲')],assignments=False,daily=False,daily_synthesis=False,
                     overlay_logs=False,stamina_limit=10,challenge_count=1,rounds=1)
        with tempfile.TemporaryDirectory() as folder,native.runtime(Path(folder),value,World()) as (window,_):
            original=window.click;support_calls=[]
            def click(x,y,geometry):
                target=next(t for t in window.scene.tokens if abs(t.center[0]-x)<1e-6 and abs(t.center[1]-y)<1e-6)
                if target.text in ('支援','好友','确认'):
                    support_calls.append(target.text)
                    if target.text=='支援':window.world.mode='picker'
                    elif target.text=='好友':window.world.mode='selected'
                    else:window.world.mode='team';window.world.borrowed=True
                else:original(x,y,geometry)
            window.click=click
            runner=native.Runner(value);window.owner=runner;report=runner.run()
        self.assertEqual(report.status,'success',report.error)
        self.assertEqual(support_calls,['支援','好友','确认'])
        self.assertEqual((report.stamina_spent,report.battle_completed),(10,1))
        self.assertEqual(report.support_selections[-1]['state'],'borrowed')
        self.assertTrue(all(c.runner is runner for c in window.contexts))


if __name__=='__main__':unittest.main()
