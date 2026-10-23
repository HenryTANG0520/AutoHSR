"""Runtime regressions from the October 20 client, without game inputs."""
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from autohsr.app import Context
from autohsr.config import Settings
from autohsr.differential_universe import DifferentialUniverseWorkflow, classify_page
from autohsr.models import AutomationError, InputInterrupted, RunReport, Scene, Token, normalize
from autohsr.policy import guard_differential_universe_click


def t(text,x=.1,y=.05):
    return Token(text,.99,(x-.02,y-.01,x+.02,y+.01))


class DuRuntimeTests(unittest.TestCase):
    @staticmethod
    def optional_device_fixture(name='optional_device_blocks_gate'):
        import cv2,json
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime'/name
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        return Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                     cv2.imread(str(root.with_suffix('.png'))))

    def test_native_optional_machine_only_authorizes_avoidance_with_live_prompt(self):
        from autohsr.du_navigation import optional_device_prompt
        from autohsr.policy import guard_differential_universe_field_interact
        page=self.optional_device_fixture()
        target=optional_device_prompt(page)
        self.assertEqual(target.text,'游玩「超级排排乐」')
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(page,target)
        for text in ('游玩「另一款游戏」','游玩『新的小游戏』','游玩“新的小游戏”'):
            changed=Scene([Token(text,v.score,v.box) if v==target else v for v in page.tokens],page.image)
            self.assertEqual(optional_device_prompt(changed).text,text)
            with self.assertRaises(AutomationError):
                guard_differential_universe_field_interact(changed,optional_device_prompt(changed))
        for text in ('启动「未知装置」','购买「超级排排乐」','超级排排乐','游玩「」','游玩「超级排排乐」消耗20'):
            changed=Scene([Token(text,v.score,v.box) if v==target else v for v in page.tokens],page.image)
            self.assertIsNone(optional_device_prompt(changed))
        ambiguous=Scene([*page.tokens,Token('游玩「另一款游戏」',.99,(.60,.60,.80,.63))],page.image)
        self.assertIsNone(optional_device_prompt(ambiguous))
        wrong_place=Scene([Token(target.text,target.score,(.20,.20,.45,.25)) if v==target else v
                           for v in page.tokens],page.image)
        self.assertIsNone(optional_device_prompt(wrong_place))
        wrong_room=Scene([Token('(6/13) 第二位面-战斗',v.score,v.box) if '位面-' in v.text else v
                          for v in page.tokens],page.image)
        self.assertIsNone(optional_device_prompt(wrong_room))
        page.image[round(.45*1080):round(.65*1080),round(.52*1920):round(.60*1920)]=0
        self.assertIsNone(optional_device_prompt(page))

    def test_optional_machine_detour_is_bounded_and_never_plays_the_game(self):
        page=self.optional_device_fixture()
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_move.return_value=page
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='field_wealth')
        with self.assertRaisesRegex(AutomationError,'已绕行一次'):
            flow._field_anomaly_visual(page,field_kind='field_wealth')
        self.assertEqual([(c.args[1],c.args[2]) for c in ctx.differential_universe_move.call_args_list],
                         [('s',500),('a',1100),('w',1100)])
        ctx.differential_universe_interact.assert_not_called()
        ctx.differential_universe_enter_random_gate.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()

    def test_optional_device_detour_stops_on_field_change_before_another_move(self):
        page=self.optional_device_fixture()
        next_page=Scene([t('区域待选择')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_move.return_value=next_page
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='station_choice')
        self.assertEqual(flow._field_anomaly_visual(page,field_kind='field_wealth'),(next_page,'station_choice'))
        ctx.differential_universe_move.assert_called_once_with(page,'s',500)
        ctx.differential_universe_interact.assert_not_called()

    def test_native_chaos_box_is_an_optional_obstacle_not_a_combat_reward(self):
        from autohsr.du_navigation import optional_device_prompt
        from autohsr.policy import guard_differential_universe_field_interact
        page=self.optional_device_fixture('chaos_box_blocks_combat')
        self.assertEqual(classify_page(page),'field_combat')
        target=optional_device_prompt(page)
        self.assertEqual(target.text,'混沌药箱')
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(page,target)
        ctx=Mock(settings=Settings(),report=RunReport())
        self.assertIsNone(DifferentialUniverseWorkflow(ctx,1)._combat_chest(page))
        ctx.differential_universe_interact.assert_not_called()

    def test_combat_reuses_bounded_optional_device_detour_without_f_or_attack(self):
        page=self.optional_device_fixture('chaos_box_blocks_combat')
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_move.return_value=page
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='field_combat')
        with self.assertRaisesRegex(AutomationError,'已绕行一次'):
            flow._field_visual(page)
        self.assertEqual([(c.args[1],c.args[2]) for c in ctx.differential_universe_move.call_args_list],
                         [('s',500),('a',1100),('w',1100)])
        ctx.differential_universe_interact.assert_not_called()
        ctx.differential_universe_attack.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()

    def test_unknown_combat_f_caption_is_rechecked_before_any_forward_input(self):
        page=self.optional_device_fixture('chaos_box_blocks_combat')
        page.tokens=[Token('未知装置',v.score,v.box) if v.text=='混沌药箱' else v for v in page.tokens]
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        with patch('autohsr.du_navigation.verified_attack_reticle',return_value=None):
            with self.assertRaisesRegex(AutomationError,'停止重复前进'):
                flow._field_visual(page)
        self.assertEqual(flow._snapshot.call_count,2)
        ctx.differential_universe_move.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_attack.assert_not_called()

    def test_combat_device_detour_stops_as_soon_as_battle_begins(self):
        page=self.optional_device_fixture('chaos_box_blocks_combat')
        battle=Scene([t('战斗开始')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_move.return_value=battle
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='battle')
        self.assertEqual(flow._field_visual(page),(battle,'battle'))
        ctx.differential_universe_move.assert_called_once_with(page,'s',500)
        ctx.differential_universe_interact.assert_not_called()

    def test_native_field_fade_is_not_a_reason_to_turn_and_night_is_ready(self):
        from autohsr.du_navigation import field_frame_ready
        fade=self.optional_device_fixture('rest_entry_fade')
        night=self.optional_device_fixture('rest_entry_ready')
        self.assertFalse(field_frame_ready(fade))
        self.assertTrue(field_frame_ready(night))
        self.assertTrue(field_frame_ready(self.optional_device_fixture('chaos_box_blocks_combat')))

    def test_entry_waits_for_two_ready_observations_without_moving_or_looking(self):
        fade=self.optional_device_fixture('rest_entry_fade')
        ready=self.optional_device_fixture('rest_entry_ready')
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(side_effect=[(ready,'field_rest'),(ready,'field_rest')])
        self.assertEqual(flow._settled_field_entry(fade,'field_rest'),(ready,'field_rest'))
        self.assertEqual(flow._snapshot.call_count,2)
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_move.assert_not_called()
        ctx.differential_universe_look.assert_not_called()

    def test_entry_fade_timeout_has_no_camera_or_movement_input(self):
        fade=self.optional_device_fixture('rest_entry_fade')
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(fade,'field_rest'))
        with self.assertRaisesRegex(AutomationError,'仍在淡入'):
            flow._settled_field_entry(fade,'field_rest')
        self.assertEqual(flow._snapshot.call_count,8)
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_move.assert_not_called()
        ctx.differential_universe_look.assert_not_called()

    def test_entry_wait_returns_an_actual_overlay_change(self):
        fade=self.optional_device_fixture('rest_entry_fade')
        reward=Scene([t('选择祝福')])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(reward,'blessing_choice'))
        self.assertEqual(flow._settled_field_entry(fade,'field_rest'),(reward,'blessing_choice'))
        ctx.differential_universe_motion.assert_not_called()

    def test_continuous_camera_search_stops_on_a_learned_gate_bearing(self):
        from autohsr.du_navigation import FieldMotionWatch
        page=self.optional_device_fixture('rest_entry_ready')
        vision=Mock()
        watch=FieldMotionWatch(page,vision,profile='seek')
        target=Token('Target',.9,(.4,.2,.5,.5))
        with patch('autohsr.du_navigation.random_gate',return_value=None), \
             patch('autohsr.du_navigation.navigation_targets',return_value=[target]):
            self.assertEqual(watch(page.image),'gate_landmark')
        vision.read.assert_not_called()

    def test_exit_camera_search_does_not_block_on_enemy_bar_ocr(self):
        from autohsr.du_navigation import FieldMotionWatch
        page=self.optional_device_fixture('rest_entry_ready')
        vision=Mock()
        watch=FieldMotionWatch(page,vision,profile='seek_gate')
        with patch('autohsr.du_navigation.random_gate',return_value=None), \
             patch('autohsr.du_navigation.navigation_targets',return_value=[]):
            self.assertIsNone(watch(page.image))
        vision.read.assert_not_called()

    def test_recruitment_header_with_blank_cards_waits_for_observed_titles(self):
        import json
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime'
        def read(name):
            meta=json.loads((root/(name+'.json')).read_text('utf8'))
            return Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in meta['tokens']])
        loading=read('snow_owl_recruitment_loading');loaded=read('snow_owl_recruitment')
        self.assertEqual(classify_page(loading),'area_choice')
        self.assertIsNone(DifferentialUniverseWorkflow._area_choice_target(loading))
        ctx=Mock(settings=Settings(),report=RunReport())
        def wait(predicate,**kwargs):
            self.assertFalse(predicate(loading))
            self.assertTrue(predicate(loaded))
            self.assertFalse(predicate(Scene([t('商店'),t('精英',.75,.52)])))
            self.assertEqual(kwargs['timeout'],15)
            return loaded
        ctx.wait.side_effect=wait
        flow=DifferentialUniverseWorkflow(ctx,1)
        page,target=flow._loaded_area_choice(loading)
        self.assertIs(page,loaded)
        self.assertEqual(target.text,'精英')
        ctx.click.assert_not_called()
        ctx.wait.side_effect=AutomationError('load timeout')
        with self.assertRaisesRegex(AutomationError,'load timeout'):
            flow._loaded_area_choice(loading)
        ctx.click.assert_not_called()

    def test_native_snow_owl_recruitment_chooses_elite_and_scopes_confirmation(self):
        import json,cv2
        from pathlib import Path
        from autohsr.policy import du_recruitment_candidates
        root=Path(__file__).parent/'fixtures/du_runtime/snow_owl_recruitment'
        meta=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in meta['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        self.assertEqual(classify_page(page),'area_choice')
        self.assertEqual([t.text for t in du_recruitment_candidates(page)],['奖励','事件','精英'])
        target=DifferentialUniverseWorkflow._area_choice_target(page)
        self.assertEqual(target.text,'精英')
        guard_differential_universe_click(page,target,intent='area_select')
        confirm=page.find('确认',exact=True)
        guard_differential_universe_click(page,confirm,intent='area_recruit_confirm')
        for missing in ('人才管理阶段','招聘阶段，请选择一个区域','事件'):
            changed=Scene([t for t in page.tokens if t.text!=missing])
            self.assertEqual(du_recruitment_candidates(changed),[])
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(changed,target,intent='area_select')
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(changed,confirm,intent='area_recruit_confirm')
        for fake in (t('精英',.8,.65),t('购买',.76,.516)):
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(page,fake,intent='area_select')

    def test_visible_cards_at_entry_skip_blind_forward_probe(self):
        import numpy as np
        page=Scene([t('(8/13) 第二位面-异常')],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_anomaly'))
        flow._field_anomaly_visual=Mock(return_value=(page,'field_anomaly'))
        cards=[Token('Card',.94,(.32,.25,.4,.44)),Token('Card',.93,(.61,.25,.69,.44))]
        with patch('autohsr.du_navigation.event_targets',return_value=cards):
            self.assertEqual(flow._field_anomaly(page,fresh_entry=True),(page,'field_anomaly'))
        ctx.differential_universe_motion.assert_not_called()
        flow._field_anomaly_visual.assert_called_once_with(page,field_kind='field_anomaly')

    def test_combat_chest_is_collected_before_rearming_straight_approach(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import guard_differential_universe_field_interact
        from autohsr.du_navigation import FieldMotionWatch
        root=Path(__file__).parent/'fixtures/du_runtime/combat_chest_blocks_approach'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        target=DifferentialUniverseWorkflow._field_interaction_target(page)
        self.assertEqual(target.text,'丰厚战利品')
        guard_differential_universe_field_interact(page,target)
        self.assertEqual(FieldMotionWatch(page,Mock(),profile='engage')(page.image),'interaction_hint')
        cleared=Scene([t for t in page.tokens if t is not target],page.image)
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_interact.return_value=cleared
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='field_combat')
        flow._snapshot=Mock(return_value=(cleared,'field_combat'))
        self.assertEqual(flow._field_visual(page,forward_ready=True),(cleared,'field_combat'))
        self.assertTrue(flow._fresh_field_entry)
        ctx.differential_universe_interact.assert_called_once_with(page,target)
        ctx.differential_universe_attack.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()
        flow._combat_chest_attempts=3
        with self.assertRaisesRegex(AutomationError,'三次宝箱交互'):
            flow._field_combat(page)
        self.assertEqual(ctx.differential_universe_interact.call_count,1)

    def test_native_precious_chest_prompt_requires_observed_f_in_wealth_room(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import guard_differential_universe_field_interact
        root=Path(__file__).parent/'fixtures/du_runtime/wealth_precious_chest_prompt'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        target=DifferentialUniverseWorkflow._field_interaction_target(page)
        self.assertEqual(target.text,'贵重战利品')
        self.assertEqual(classify_page(page),'field_wealth')
        guard_differential_universe_field_interact(page,target)
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(Scene(page.tokens),target)

    def test_native_encounter_room_waits_for_visible_gate_before_leaving_without_console(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import guard_differential_universe_field_input,guard_differential_universe_portal
        from autohsr.du_navigation import random_gate
        root=Path(__file__).parent/'fixtures/du_runtime/encounter_synthesis_field'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        self.assertEqual(classify_page(page),'field_anomaly')
        guard_differential_universe_field_input(page,action='forward')
        # The console occludes both eyes. This frame must not grant readiness;
        # the existing stationary scan waits for positive face evidence.
        self.assertIsNone(random_gate(page,fast=True))
        revealed=Scene(page.tokens,page.image)
        prompt=t('随意门',.55,.55)
        reached=Scene(page.tokens+[prompt],page.image)
        guard_differential_universe_portal(reached,prompt)
        done=Scene([t('选择下一站')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_look.return_value=revealed
        ctx.differential_universe_motion.return_value=reached
        ctx.differential_universe_enter_random_gate.return_value=done
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(side_effect=lambda p,*a:'station_choice' if p is done else 'field_anomaly')
        gate=Token('Target',.95,(.45,.15,.55,.45))
        awake=Token('差分宇宙随意门外观',.95,gate.box)
        with patch('autohsr.du_navigation.navigation_targets',return_value=[gate]), \
             patch('autohsr.du_navigation.random_gate',side_effect=lambda p,**kw: None if p is page else awake):
            self.assertEqual(flow._field_anomaly_visual(page),(done,'station_choice'))
        ctx.differential_universe_look.assert_called_once()
        ctx.differential_universe_interact.assert_not_called()
        for bad in (Scene([t('奇物合成')]),Scene([t('第一位面-奇物合成')]),
                    Scene([t('奇遇-奇物合成',.3,.5),t('第一位面')])):
            with self.assertRaises(AutomationError):
                guard_differential_universe_field_input(bad,action='forward')

    def test_native_explosion_beacon_cannot_be_confirmed_and_switches_to_safe_route(self):
        import json,cv2
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime/station_explosion_beacon'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        self.assertEqual(flow._station_hazard(page),'enemy_death_party_explosion')
        confirm=page.find('确定',(.48,.78,.98,.99),exact=True)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,confirm,intent='station_confirm')
        battle=page.find('战斗',(.20,.54,.73,.82),exact=True)
        safe=Scene([t for t in page.tokens if not t.within((.08,.14,.92,.33))]
                   +[t('获得宇宙碎片',.3,.24)])
        page.image=cv2.imread(str(root.with_suffix('.png')))
        safe.image=page.image
        flow._snapshot=Mock(side_effect=[(page,'station_choice'),(page,'station_choice'),
                                        (safe,'station_choice'),(safe,'station_choice')])
        flow._click=Mock(return_value=(safe,'station_choice'))
        self.assertEqual(flow._safer_station_preview(page,battle),(safe,'station_choice'))
        self.assertEqual(flow._click.call_args.args[1].text,'财富')
        self.assertEqual(flow._click.call_count,1)
        guard_differential_universe_click(safe,confirm,intent='station_confirm')

    def test_station_hazard_has_bounded_alternatives_and_ignores_unrelated_text(self):
        battle=t('战斗',.36,.70)
        hazard=t('跟你爆了：敌人被消灭时自爆，对我方全体造成伤害',.60,.20)
        page=Scene([t('选择下一站'),battle,hazard])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock()
        with self.assertRaisesRegex(AutomationError,'危险信标'):
            flow._safer_station_preview(page,battle)
        flow._click.assert_not_called()
        harmless=Scene([t('选择下一站'),battle,t(hazard.text,.6,.8)])
        self.assertIsNone(flow._station_hazard(harmless))
        self.assertEqual(flow._safer_station_preview(harmless,battle),(harmless,'station_choice'))

    def test_card_confidence_precedes_center_bias_in_uncleared_room(self):
        import numpy as np
        page=Scene([t('(5/13) 第二位面-事件')],np.zeros((540,960,3),np.uint8))
        done=Scene([t('事件')])
        cards=[Token('Card',.81,(.45,.17,.52,.31)),Token('Card',.96,(.72,.12,.82,.44))]
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_look.return_value=done
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='event')
        with patch('autohsr.du_navigation.event_targets',return_value=cards), \
             patch('autohsr.du_navigation.random_gate',return_value=None):
            self.assertEqual(flow._field_anomaly_visual(page,field_kind='field_event'),(done,'event'))
        self.assertGreater(ctx.differential_universe_look.call_args.args[1],0)
        ctx.differential_universe_motion.assert_not_called()
        self.assertEqual(flow.report['navigation_observations'][-1]['card_candidates'],2)

    def test_three_card_room_waits_for_awake_door_after_each_event(self):
        import numpy as np
        image=np.zeros((540,960,3),np.uint8)
        field=Scene([t('(5/13) 第二位面-事件')],image)
        reached=Scene(field.tokens+[t('调查',.6,.6)],image)
        event=Scene([t('事件')])
        portal=Scene(field.tokens+[t('随意门',.5,.55)],image)
        done=Scene([t('选择下一站')])
        sleeping=Token('差分宇宙睡眼门',.95,(.45,.1,.55,.5))
        awake=Token('差分宇宙随意门外观',.95,(.45,.1,.55,.5))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_motion.return_value=reached
        ctx.differential_universe_interact.return_value=event
        ctx.differential_universe_enter_random_gate.return_value=done
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._field_interaction_target=Mock(side_effect=lambda p: reached.tokens[-1] if p is reached else None)
        flow._observe=Mock(side_effect=lambda p,*a: 'event' if p is event else 'station_choice' if p is done else 'field_event')
        with patch('autohsr.du_navigation.random_gate',return_value=sleeping), \
             patch('autohsr.du_navigation.event_targets') as targets:
            for remaining in (3,2,1):
                targets.return_value=[Token('Card',.95-i*.01,(.45+i*.1,.2,.55+i*.1,.6)) for i in range(remaining)]
                self.assertEqual(flow._field_anomaly_visual(field,field_kind='field_event'),(event,'event'))
                ctx.differential_universe_enter_random_gate.assert_not_called()
        self.assertEqual(ctx.differential_universe_interact.call_count,3)
        ctx.differential_universe_motion.return_value=portal
        with patch('autohsr.du_navigation.random_gate',return_value=awake), \
             patch('autohsr.du_navigation.navigation_targets',return_value=[Token('Target',.95,(.45,.1,.55,.5))]), \
             patch('autohsr.du_navigation.event_targets',return_value=[]):
            self.assertEqual(flow._field_anomaly_visual(field,field_kind='field_event'),(done,'station_choice'))
        ctx.differential_universe_enter_random_gate.assert_called_once()
        self.assertEqual([v['gate_state'] for v in flow.report['navigation_observations']],
                         ['sleeping','sleeping','sleeping','awake'])

    def test_awake_exit_outranks_native_background_poster_card(self):
        import cv2
        from pathlib import Path
        from autohsr.du_navigation import event_targets,random_gate
        image=cv2.imread(str(Path(__file__).parent/'fixtures/du_runtime/awake_gate_with_poster.png'))
        page=Scene([t('(6/13) 第二位面-奖励')],image)
        self.assertFalse(event_targets(page))
        self.assertEqual(random_gate(page,fast=True).text,'差分宇宙随意门外观')
        done=Scene([t('选择下一站')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_look.return_value=done
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='station_choice')
        # Even if another detector proposes a poster again, a verified awake
        # door must retain priority over that candidate.
        with patch('autohsr.du_navigation.event_targets',return_value=[Token('Card',.9,(.47,.32,.52,.42))]):
            self.assertEqual(flow._field_anomaly_visual(page,field_kind='field_reward'),(done,'station_choice'))
        self.assertGreater(ctx.differential_universe_look.call_args.args[1],0)
        ctx.differential_universe_motion.assert_not_called()

    def test_known_exit_retains_priority_when_face_is_temporarily_occluded(self):
        import numpy as np
        page=Scene([t('(6/13) 第二位面-奖励')],np.zeros((540,960,3),np.uint8))
        done=Scene([t('选择下一站')])
        awake=Token('差分宇宙随意门外观',.95,(.55,.2,.65,.4))
        gate=Token('Target',.90,(.45,.2,.55,.5))
        poster=Token('Card',.90,(.25,.3,.35,.5))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_motion.side_effect=[page,done]
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(side_effect=['field_reward','station_choice'])
        with patch('autohsr.du_navigation.random_gate',side_effect=[awake,None]), \
             patch('autohsr.du_navigation.navigation_targets',return_value=[gate]), \
             patch('autohsr.du_navigation.event_targets',return_value=[poster]) as cards:
            self.assertEqual(flow._field_anomaly_visual(page,field_kind='field_reward'),(done,'station_choice'))
        cards.assert_not_called()
        ctx.differential_universe_look.assert_not_called()
        self.assertEqual(ctx.differential_universe_motion.call_count,2)

    def test_card_room_can_inspect_near_gate_back_with_one_bounded_side_route(self):
        import numpy as np
        page=Scene([t('(6/13) 第二位面-奖励')],np.zeros((540,960,3),np.uint8))
        done=Scene([t('选择下一站')])
        back=Token('差分宇宙随意门背面',.94,(.4,.1,.6,.6))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_move.side_effect=[page,done]
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(side_effect=['field_reward','station_choice'])
        with patch('autohsr.du_navigation.random_gate',return_value=back), \
             patch('autohsr.du_navigation.event_targets',return_value=[]):
            self.assertEqual(flow._field_anomaly_visual(page,field_kind='field_reward'),(done,'station_choice'))
        self.assertEqual([call.args[1:] for call in ctx.differential_universe_move.call_args_list],
                         [('a',750),('w',850)])
        ctx.differential_universe_enter_random_gate.assert_not_called()
        ctx.differential_universe_interact.assert_not_called()

    def test_gate_back_recovery_cannot_repeat_side_steps_without_progress(self):
        import numpy as np
        page=Scene([t('(6/13) 第二位面-奖励')],np.zeros((540,960,3),np.uint8))
        back=Token('差分宇宙随意门背面',.94,(.4,.1,.6,.6))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_move.return_value=page
        ctx.differential_universe_look.return_value=page
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='field_reward')
        with patch('autohsr.du_navigation.random_gate',return_value=back), \
             patch('autohsr.du_navigation.event_targets',return_value=[]):
            with self.assertRaisesRegex(AutomationError,'视觉导航达到上限'):
                flow._field_anomaly_visual(page,field_kind='field_reward')
        self.assertEqual([call.args[1:] for call in ctx.differential_universe_move.call_args_list],
                         [('a',750),('w',850)])
        ctx.differential_universe_enter_random_gate.assert_not_called()

    def test_native_forge_plus_three_selects_matching_card_and_confirms_once(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import du_miracle_target_labels
        root=Path(__file__).parent/'fixtures/du_runtime/forge_plus_three'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        self.assertEqual(classify_page(page),'miracle_target')
        self.assertEqual(du_miracle_target_labels(page),('铸造',))
        card=page.find('铸造',(.03,.24,.64,.78),exact=True)
        confirm=page.find('确定',exact=True)
        guard_differential_universe_click(page,card,intent='miracle_target')
        guard_differential_universe_click(page,confirm,intent='miracle_target_confirm')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,t('战斗',*card.center),intent='miracle_target')
        for old,new in (('指定1个','指定2个'),('+3','+3.0'),('+3','-3'),
                        ('指定1个','支付60星琼指定1个'),('+3','+3并消耗60星琼')):
            altered=Scene([Token(v.text.replace(old,new),v.score,v.box) for v in page.tokens])
            self.assertEqual(du_miracle_target_labels(altered),())
        done=Scene([t('点击空白处关闭')])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(side_effect=[(page,'miracle_target'),(done,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(done,'tutorial_overlay'))
        self.assertEqual(flow._apply_miracle_target(page),(done,'tutorial_overlay'))
        self.assertEqual([call.args[1] for call in flow._click.call_args_list],[card,confirm])

    def test_native_free_single_beacon_accepts_written_one_and_any_region(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import du_miracle_target_labels
        root=Path(__file__).parent/'fixtures/du_runtime/any_region_beacon'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        self.assertEqual(classify_page(page),'miracle_target')
        self.assertEqual(du_miracle_target_labels(page)[0],'战斗')
        card=page.find('战斗',(.03,.24,.64,.78),exact=True)
        guard_differential_universe_click(page,card,intent='miracle_target')
        guard_differential_universe_click(page,page.find('确定',exact=True),intent='miracle_target_confirm')
        for old,new in (('指定一个','指定两个'),('附加','花费60星琼附加'),('信标','奇物')):
            altered=Scene([Token(v.text.replace(old,new),v.score,v.box) for v in page.tokens])
            self.assertEqual(du_miracle_target_labels(altered),())
        body_only=Scene([Token(v.text,v.score,(.1,.5,.6,.55)) if '指定一个' in v.text else v
                         for v in page.tokens])
        self.assertEqual(du_miracle_target_labels(body_only),())

    def test_just_reached_gate_f_prompt_precedes_search_deadline(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import guard_differential_universe_portal
        root=Path(__file__).parent/'fixtures/du_runtime/late_gate_interaction'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        portal=page.find('随意门',(.25,.30,.78,.75),exact=True)
        guard_differential_universe_portal(page,portal)
        done=Scene([t('选择下一站')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_enter_random_gate.return_value=done
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._check_deadline=Mock(side_effect=AutomationError('search expired'))
        flow._observe=Mock(return_value='station_choice')
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        self.assertEqual(flow._field_anomaly_visual(page),(done,'station_choice'))
        ctx.differential_universe_enter_random_gate.assert_called_once_with(page,portal)
        flow._check_deadline.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_look.assert_not_called()

    def test_expired_search_without_live_interaction_still_stops_before_input(self):
        import numpy as np
        page=Scene([t('(10/13) 第三位面-异常')],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._check_deadline=Mock(side_effect=AutomationError('search expired'))
        with self.assertRaisesRegex(AutomationError,'search expired'):
            flow._field_anomaly_visual(page)
        ctx.differential_universe_enter_random_gate.assert_not_called()
        ctx.differential_universe_interact.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_look.assert_not_called()

    @staticmethod
    def _random_two_page(name):
        import cv2,json
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime'/('random_two_'+name)
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        return Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                     cv2.imread(str(root.with_suffix('.png'))))

    def test_native_two_card_conversion_requires_exact_free_instruction(self):
        from autohsr.policy import du_miracle_target_labels,du_miracle_randomize_two
        for name in ('target','remaining'):
            page=self._random_two_page(name)
            self.assertTrue(du_miracle_randomize_two(page))
            self.assertEqual(classify_page(page),'miracle_target')
            labels=du_miracle_target_labels(page)
            self.assertEqual(labels[0],'冒险')
            target=page.find(labels,(.03,.24,.64,.78),exact=True)
            guard_differential_universe_click(page,target,intent='miracle_target')
            guard_differential_universe_click(page,page.find('确定',exact=True),intent='miracle_target_confirm')
            for old,new in (('指定2个','指定3个'),('同等级','+1等级'),
                            ('指定2个','支付60星琼指定2个')):
                altered=Scene([Token(v.text.replace(old,new),v.score,v.box) for v in page.tokens])
                self.assertEqual(du_miracle_target_labels(altered),())
            relocated=Scene([Token(v.text,v.score,(.1,.4,.6,.45)) if '指定2个' in v.text else v
                             for v in page.tokens])
            self.assertEqual(du_miracle_target_labels(relocated),())

    def test_two_card_conversion_checks_loss_and_gain_before_next_confirmation(self):
        first=self._random_two_page('target');second=self._random_two_page('remaining')
        loss=self._random_two_page('loss');gain=self._random_two_page('gain')
        done=Scene([t('(3/13) 第一位面-奖励')])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(side_effect=[(first,'miracle_target'),(loss,'tutorial_overlay'),
                                     (second,'miracle_target'),(loss,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(loss,'tutorial_overlay'))
        flow._close_tutorial=Mock(side_effect=[(gain,'tutorial_overlay'),(second,'miracle_target'),
                                              (gain,'tutorial_overlay'),(done,'field_reward')])
        self.assertEqual(flow._apply_miracle_target(first),(done,'field_reward'))
        self.assertEqual(flow._click.call_count,4)
        self.assertEqual(flow._close_tutorial.call_count,4)
        self.assertEqual([v.kwargs['intent'] for v in flow._click.call_args_list],
                         ['miracle_target','miracle_target_confirm']*2)

    def test_two_card_conversion_can_resume_with_only_one_target_remaining(self):
        page=self._random_two_page('remaining');loss=self._random_two_page('loss')
        gain=self._random_two_page('gain');done=Scene([t('(3/13) 第一位面-奖励')])
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(side_effect=[(page,'miracle_target'),(loss,'tutorial_overlay')])
        flow._snapshot=Mock(return_value=(loss,'tutorial_overlay'))
        flow._close_tutorial=Mock(side_effect=[(gain,'tutorial_overlay'),(done,'field_reward')])
        self.assertEqual(flow._apply_miracle_target(page),(done,'field_reward'))
        self.assertEqual(flow._click.call_count,2)

    def test_two_card_conversion_does_not_repeat_without_both_one_card_receipts(self):
        page=self._random_two_page('target');loss=self._random_two_page('loss')
        gain=self._random_two_page('gain')
        wrong=Scene([Token(v.text.replace('失去数量：1','失去数量：2'),v.score,v.box) for v in loss.tokens])
        for receipt in (gain,wrong):
            flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
            flow._click=Mock(side_effect=[(page,'miracle_target'),(receipt,'tutorial_overlay')])
            flow._snapshot=Mock(return_value=(receipt,'tutorial_overlay'))
            flow._close_tutorial=Mock()
            with self.assertRaisesRegex(AutomationError,'逐张失去和获得各1张'):
                flow._apply_miracle_target(page)
            self.assertEqual(flow._click.call_count,2)
            flow._close_tutorial.assert_not_called()

    def test_two_card_conversion_stops_on_unchanged_selector_or_third_target(self):
        page=self._random_two_page('target');loss=self._random_two_page('loss')
        gain=self._random_two_page('gain')
        flow=DifferentialUniverseWorkflow(Mock(settings=Settings(),report=RunReport()),1)
        flow._click=Mock(return_value=(page,'miracle_target'))
        flow._snapshot=Mock(return_value=(page,'miracle_target'))
        with self.assertRaisesRegex(AutomationError,'确认后未前进'):
            flow._apply_miracle_target(page)
        self.assertEqual(flow._click.call_count,2)
        flow._click=Mock(side_effect=[(page,'miracle_target'),(loss,'tutorial_overlay')]*2)
        flow._snapshot=Mock(return_value=(loss,'tutorial_overlay'))
        flow._close_tutorial=Mock(side_effect=[(gain,'tutorial_overlay'),(page,'miracle_target')]*2)
        with self.assertRaisesRegex(AutomationError,'已确认两张'):
            flow._apply_miracle_target(page)
        self.assertEqual(flow._click.call_count,4)

    def test_reward_chest_uses_its_live_named_f_prompt_before_moving(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import guard_differential_universe_field_interact
        root=Path(__file__).parent/'fixtures/du_runtime/reward_chest_interaction'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        target=DifferentialUniverseWorkflow._field_interaction_target(page)
        self.assertIsNotNone(target)
        self.assertEqual(target.text,'丰厚战利品')
        guard_differential_universe_field_interact(page,target)
        reward=Scene([t('获得物品')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_interact.return_value=reward
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='tutorial_overlay')
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        self.assertEqual(flow._field_anomaly_visual(page,field_kind='field_reward'),(reward,'tutorial_overlay'))
        ctx.differential_universe_interact.assert_called_once_with(page,target)
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_move.assert_not_called()
        page.image[round(.45*720):round(.66*720),round(.52*1280):round(.62*1280)]=0
        self.assertIsNone(DifferentialUniverseWorkflow._field_interaction_target(page))
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(page,target)

    def test_unknown_f_caption_is_reobserved_without_stall_or_sidestep(self):
        import cv2,json
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime/reward_chest_interaction'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'].replace('丰厚战利品','未知机关'),v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_reward'))
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        with self.assertRaisesRegex(AutomationError,'F提示已出现'):
            flow._field_anomaly_visual(page,field_kind='field_reward')
        self.assertEqual(flow._snapshot.call_count,2)
        ctx.differential_universe_interact.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_move.assert_not_called()
        ctx.differential_universe_look.assert_not_called()

    def test_range_lock_recovers_a_real_ring_near_the_party_sidebar(self):
        import cv2
        from pathlib import Path
        from autohsr.du_navigation import verified_attack_reticle
        from autohsr.policy import guard_differential_universe_click
        image=cv2.imread(str(Path(__file__).parent/'fixtures/du_runtime/attack_ring_26.png'))
        page=Scene([t('(5/13) 第二位面-战斗'),t('等级89 幻造生物',.5,.055)],image)
        ring=verified_attack_reticle(page)
        self.assertIsNotNone(ring)
        self.assertGreater(ring.center[0],.90)
        guard_differential_universe_click(page,ring,intent='field_ring_attack')
        battle=Scene([t('战斗设置')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_attack.return_value=battle
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._choose_attack_character=Mock(return_value=(page,'field_combat'))
        flow._observe=Mock(return_value='battle')
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        self.assertEqual(flow._field_visual(page,range_seen=True),(battle,'battle'))
        ctx.differential_universe_attack.assert_called_once_with(page,ring,'field_ring_attack')
        ctx.differential_universe_look.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()

    def test_each_new_equation_overlay_restarts_its_own_close_budget(self):
        import cv2,json
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime'
        pages=[]
        for number in (24,27):
            data=json.loads((root/f'equation_queue_{number}.json').read_text('utf8'))
            pages.append(Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                               cv2.imread(str(root/f'equation_queue_{number}.png'))))
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(return_value=(pages[1],'tutorial_overlay'))
        self.assertEqual(flow._close_tutorial(pages[0]),(pages[1],'tutorial_overlay'))
        flow._click.assert_called_once()
        ctx.sleep.assert_not_called()
        blessing=Scene([t('获得祝福',.5,.08),t('点击空白处关闭',.5,.91)])
        flow._click=Mock(return_value=(pages[0],'tutorial_overlay'))
        self.assertEqual(flow._close_tutorial(blessing),(pages[0],'tutorial_overlay'))
        flow._click.assert_called_once()

    def test_plane_in_curio_description_is_not_a_field_hud(self):
        import cv2,json
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime/curio_plane_description'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        self.assertEqual(classify_page(page),'curio_choice')
        target=page.find('喜乐熏香',exact=True)
        self.assertIsNotNone(target)
        guard_differential_universe_click(page,target,intent='choice')
        guard_differential_universe_click(page,page.find('确认',exact=True),intent='choice_confirm')
        field=Scene([t('(4/13) 第一位面-首领'),*page.tokens],page.image)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(field,target,intent='choice')

    def test_edge_on_card_uses_qualified_world_caption_without_authorizing_f(self):
        import cv2,json
        from pathlib import Path
        from autohsr.du_navigation import event_targets
        from autohsr.policy import guard_differential_universe_field_interact
        root=Path(__file__).parent/'fixtures/du_runtime/card_edge_world_title'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        caption=next(t for t in page.tokens if '幻月之下' in t.text)
        targets=event_targets(page)
        self.assertEqual(len(targets),1)
        self.assertEqual(targets[0].text,'Card')
        self.assertAlmostEqual(targets[0].center[0],caption.center[0])
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(page,caption)
        with patch('autohsr.du_detector.detect_cards',return_value=[]):
            for other in (Scene([caption],page.image),
                          Scene([t('(11/13) 第三位面-事件'),t('维护市容（区域）',.15,.25)],page.image),
                          Scene([t('(11/13) 第三位面-事件'),t('普通广告文字',.5,.25)],page.image)):
                self.assertEqual(event_targets(other),[])

    def test_guide_tab_without_red_dot_and_with_occluded_lower_edge(self):
        import cv2
        from pathlib import Path
        from autohsr.vision import Vision
        root=Path(__file__).parent/'fixtures/du_runtime'
        image=cv2.imread(str(root/'guide_universe_tab_clear.png'))
        vision=object.__new__(Vision)
        template=Path(__file__).resolve().parents[2]/'assets/templates/du_guide_tab.png'
        page=Scene([t('星际和平指南')],image)
        match=vision.template(page,template,(.28,.15,.35,.24),threshold=.85)
        self.assertIsNotNone(match)
        self.assertLess(abs(match[0]-.31),.02)
        guard_differential_universe_click(page,Token('差分宇宙指南页签',match[2],
            (match[0]-.018,match[1]-.018,match[0]+.018,match[1]+.018)),intent='du_guide_tab')
        image[round(.15*1080):round(.24*1080),round(.28*1920):round(.35*1920)]=0
        self.assertIsNone(vision.template(page,template,(.28,.15,.35,.24),threshold=.85))

    def test_forge_menu_returns_to_required_card_flow_and_remembers_device(self):
        import cv2,json
        from pathlib import Path
        from autohsr.models import Stopped
        root=Path(__file__).parent/'fixtures/du_runtime/forge_console_menu'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        menu=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        self.assertEqual(classify_page(menu),'forge_console')
        for area in ('铸造','奇遇-奇物合成','奖励'):
            with self.subTest(area=area):
                field=Scene([t('(7/13) 第二位面-'+area)],menu.image)
                ctx=Mock(settings=Settings(),report=RunReport())
                ctx.checkpoint.side_effect=[None,Stopped('test end')]
                ctx.differential_universe_close_forge.return_value=field
                def wait(predicate,**kwargs):
                    self.assertTrue(predicate(field))
                    self.assertFalse(predicate(Scene([t('合成')])))
                    return field
                ctx.wait.side_effect=wait
                ctx.differential_universe_move.return_value=field
                flow=DifferentialUniverseWorkflow(ctx,1)
                flow._observe=Mock(return_value=classify_page(field))
                with self.assertRaises(Stopped):
                    flow._progress_run(menu,'forge_console')
                self.assertTrue(flow._forge_console_used)
                ctx.differential_universe_close_forge.assert_called_once_with(menu)
                ctx.differential_universe_enter_random_gate.assert_not_called()
                ctx.click.assert_not_called()

    def test_processed_device_prompt_and_bearing_do_not_reopen_console(self):
        import numpy as np
        from autohsr.models import Stopped
        field=Scene([t('(7/13) 第二位面-铸造')],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_look.side_effect=Stopped('search other card')
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._forge_console_used=True
        flow._field_interaction_target=Mock(return_value=t('造物调试台',.65,.57))
        with patch('autohsr.du_navigation.event_targets',return_value=[Token('Device',.86,(.45,.25,.55,.4))]), \
             patch('autohsr.du_navigation.navigation_targets',return_value=[]), \
             patch('autohsr.du_navigation.random_gate',return_value=None):
            with self.assertRaises(Stopped):
                flow._field_anomaly_visual(field,field_kind='field_forge')
        ctx.differential_universe_interact.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()

    def test_forge_device_name_requires_live_f_icon_in_prompt_row(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import guard_differential_universe_field_interact
        root=Path(__file__).parent/'fixtures/du_runtime/forge_interaction'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        target=DifferentialUniverseWorkflow._field_interaction_target(page)
        self.assertIsNotNone(target)
        self.assertTrue(target.within((.60,.45,.85,.70)))
        guard_differential_universe_field_interact(page,target)
        title=page.find('造物调试台',(.20,.07,.80,.40),exact=True)
        self.assertIsNotNone(title)
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(page,title)
        page.image[round(.45*540):round(.66*540),round(.52*960):round(.62*960)]=0
        self.assertIsNone(DifferentialUniverseWorkflow._field_interaction_target(page))
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(page,target)

    def test_forge_station_processes_live_card_interaction_before_sleeping_gate(self):
        import numpy as np
        from autohsr.models import Stopped
        from autohsr.policy import guard_differential_universe_field_interact
        field=Scene([t('(7/13) 第二位面-铸造'),t('事件',.65,.57)],np.zeros((540,960,3),np.uint8))
        event=Scene([t('差分宇宙'),t('事件'),t('维护市容',.15,.90)])
        guard_differential_universe_field_interact(field,field.tokens[-1])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.checkpoint.side_effect=[None,None,Stopped('test end')]
        ctx.differential_universe_interact.return_value=event
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._observe=Mock(return_value='event')
        with self.assertRaises(Stopped):
            flow._progress_run(field,'field_forge')
        ctx.differential_universe_interact.assert_called_once_with(field,field.tokens[-1])
        ctx.differential_universe_enter_random_gate.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()

    def test_reviewed_forge_card_title_precedes_device_and_unrelated_model_box(self):
        from autohsr.du_navigation import event_targets
        page=Scene([t('(7/13) 第二位面-铸造'),t('维护市容（区域）',.33,.17),
                    t('造物调试台',.65,.33)])
        with patch('autohsr.du_detector.detect_cards',return_value=[Token('Card',.9,(.7,.2,.74,.4))]):
            target=event_targets(page)[0]
        self.assertAlmostEqual(target.center[0],.33)
        from autohsr.policy import guard_differential_universe_field_interact
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_interact(page,page.tokens[1])

    def test_near_clipped_gate_back_is_recognized_for_side_route(self):
        import cv2
        from pathlib import Path
        from autohsr.du_navigation import random_gate
        path=Path(__file__).parent/'fixtures/du_runtime/gate_back_near_clipped.png'
        result=random_gate(Scene([],cv2.imread(str(path))),fast=True)
        self.assertIsNotNone(result)
        self.assertEqual(result.text,'差分宇宙随意门背面')

    def test_partial_awake_gate_requires_learned_box_pupil_and_trim(self):
        import cv2
        from pathlib import Path
        from autohsr.du_navigation import random_gate
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('gate_awake_partial_hud','gate_awake_partial_side'):
            page=Scene([],cv2.imread(str(root/(name+'.png'))))
            result=random_gate(page,fast=True)
            self.assertIsNotNone(result)
            self.assertEqual(result.text,'差分宇宙随意门外观')
            with patch('autohsr.du_detector.detect',return_value=[]):
                self.assertIsNone(random_gate(page,fast=True))
        self.assertIsNone(random_gate(Scene([],cv2.imread(str(root/'gate_banner_negative.png'))),fast=True))

    def test_awake_gate_can_approach_briefly_after_aligned_box_disappears(self):
        import numpy as np
        field=Scene([t('(6/13) 第二位面-异常')],np.zeros((540,960,3),np.uint8))
        aligned=Scene(field.tokens,field.image.copy())
        done=Scene([t('选择下一站'),t('战斗')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_look.return_value=aligned
        ctx.differential_universe_motion.return_value=done
        flow=DifferentialUniverseWorkflow(ctx,1)
        with patch('autohsr.du_navigation.event_targets',return_value=[]), \
             patch('autohsr.du_navigation.navigation_targets',side_effect=[
                 [Token('Target',.9,(.30,.15,.50,.65))],[]]), \
             patch('autohsr.du_navigation.random_gate',side_effect=[
                 Token('差分宇宙随意门外观',.93,(.30,.15,.50,.65)),None]):
            self.assertEqual(flow._field_anomaly_visual(field)[1],'station_choice')
        ctx.differential_universe_look.assert_called_once()
        ctx.differential_universe_motion.assert_called_once_with(aligned,'w',600,profile='occluded_card')

    def test_native_single_card_beacon_uses_source_region_not_removed_region(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import du_miracle_target_labels
        root=Path(__file__).parent/'fixtures/du_runtime/station_beacon_target'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        self.assertEqual(du_miracle_target_labels(page),('战斗',))
        self.assertEqual(classify_page(page),'miracle_target')
        card=page.find('战斗',(.03,.24,.64,.78),exact=True)
        guard_differential_universe_click(page,card,intent='miracle_target')
        guard_differential_universe_click(page,page.find('确定',exact=True),intent='miracle_target_confirm')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,t('精英',.15,.38),intent='miracle_target')
        for old,new in (('指定1个','指定2个'),('附加1个','附加2个'),('信标','奇物'),
                        ('指定1个','支付60星琼指定1个')):
            altered=Scene([Token(v.text.replace(old,new),v.score,v.box) for v in page.tokens])
            self.assertEqual(du_miracle_target_labels(altered),())

    def test_printed_balloon_with_enemy_bar_does_not_stop_fresh_forward_approach(self):
        import cv2
        from pathlib import Path
        from autohsr.du_navigation import verified_attack_reticle,FieldMotionWatch
        for number in (21,22,23,24):
            image=cv2.imread(str(Path(__file__).parent/f'fixtures/du_runtime/attack_ring_{number}.png'))
            page=Scene([t('(2/13) 第一位面-战斗'),t('等级87 游荡的怪物',.5,.055)],image)
            self.assertIsNone(verified_attack_reticle(page),number)
            vision=Mock();vision.read.return_value=Scene([t('等级87 游荡的怪物')])
            self.assertIsNone(FieldMotionWatch(page,vision,profile='engage')(image),number)
        battle=Scene([t('战斗设置')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_motion.return_value=battle
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        flow._observe=Mock(return_value='battle')
        self.assertEqual(flow._field_combat(page,fresh_entry=True),(battle,'battle'))
        ctx.differential_universe_motion.assert_called_once_with(page,'w',3000,profile='engage')

    def test_hollow_attack_ring_is_accepted_only_with_live_enemy_bar(self):
        import cv2
        from pathlib import Path
        from autohsr.du_navigation import verified_attack_reticle
        root=Path(__file__).parent/'fixtures/du_runtime'
        for number in (18,19,20):
            image=cv2.imread(str(root/f'attack_ring_{number}.png'))
            for width in (960,1280,1920):
                scaled=cv2.resize(image,(width,round(width*9/16)))
                page=Scene([t('(7/13) 第二位面-精英'),t('等级90 深寒徘徊者',.5,.055)],scaled)
                self.assertIsNotNone(verified_attack_reticle(page))
                self.assertIsNone(verified_attack_reticle(Scene(page.tokens[:1],scaled)))

    def test_native_combat_to_event_transformation_selects_only_combat_card(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import du_miracle_target_labels
        root=Path(__file__).parent/'fixtures/du_runtime/station_transform'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        self.assertEqual(du_miracle_target_labels(page),('战斗',))
        self.assertEqual(classify_page(page),'miracle_target')
        card=page.find('战斗',(.03,.24,.64,.78),exact=True)
        guard_differential_universe_click(page,card,intent='miracle_target')
        guard_differential_universe_click(page,page.find('确定',exact=True),intent='miracle_target_confirm')
        for label in ('事件','商店'):
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(page,t(label,.15,.38),intent='miracle_target')
        for old,new in (('指定1个','指定2个'),('【战斗】','【未知】'),('+1等级','-1等级')):
            altered=Scene([Token(v.text.replace(old,new),v.score,v.box) for v in page.tokens])
            self.assertEqual(du_miracle_target_labels(altered),())

    def test_reverse_station_transformation_uses_either_source_region(self):
        from autohsr.policy import du_miracle_target_labels
        page=Scene([t('选择站点卡'),t('抽牌区'),
                    t('指定1个【事件】或【异常】区域，使其变为+1等级的【战斗】区域',.5,.15),
                    t('事件',.15,.38),t('异常',.27,.38),t('战斗',.39,.38),t('确定',.85,.87)])
        self.assertEqual(classify_page(page),'miracle_target')
        self.assertEqual(du_miracle_target_labels(page),('事件','异常'))
        for source in page.tokens[3:5]:
            guard_differential_universe_click(page,source,intent='miracle_target')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,page.tokens[5],intent='miracle_target')

    def test_native_beacon_close_ocr_variant_requires_heading_and_bottom_prompt(self):
        import cv2,json
        from pathlib import Path
        from autohsr.policy import du_tutorial_close_prompt
        root=Path(__file__).parent/'fixtures/du_runtime/beacon_close_variant'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root.with_suffix('.png'))))
        prompt=du_tutorial_close_prompt(page)
        self.assertIsNotNone(prompt)
        self.assertEqual(normalize(prompt.text),'点击空日处关闭')
        self.assertEqual(classify_page(page),'tutorial_overlay')
        guard_differential_universe_click(page,prompt,intent='du_tutorial_close')
        for bad in (Scene([prompt]),Scene([t('信标已部署',.5,.14),t(prompt.text,.5,.50)]),
                    Scene([t('其他页面',.5,.14),prompt])):
            self.assertIsNone(du_tutorial_close_prompt(bad))
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(bad,prompt,intent='du_tutorial_close')

    def test_tutorial_close_rechecks_animation_before_retrying_current_prompt(self):
        original=Scene([t('信标已部署',.5,.14),t('点击空白处关闭',.5,.93)])
        settled=Scene([t('信标已部署',.5,.14),t('点击空日处关闭',.5,.93)])
        field=Scene([t('(2/13) 第一位面-事件')])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(side_effect=[(original,'tutorial_overlay'),(field,'field_anomaly')])
        flow._snapshot=Mock(return_value=(settled,'tutorial_overlay'))
        self.assertEqual(flow._close_tutorial(original),(field,'field_anomaly'))
        self.assertEqual(flow._click.call_args_list[1].args,(settled,settled.tokens[1]))
        self.assertEqual(flow._click.call_args_list[1].kwargs['intent'],'du_tutorial_close')

    def test_persistent_tutorial_overlay_has_a_bounded_retry(self):
        page=Scene([t('信标已部署',.5,.14),t('点击空日处关闭',.5,.93)])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(return_value=(page,'tutorial_overlay'))
        flow._snapshot=Mock(return_value=(page,'tutorial_overlay'))
        with self.assertRaisesRegex(AutomationError,'三次实时关闭提示'):
            flow._close_tutorial(page)
        self.assertEqual(flow._click.call_count,3)

    def test_new_reward_layer_is_progress_and_does_not_exhaust_previous_close_limit(self):
        strengthening=Scene([t('祝福强化',.5,.14),t('点击空白处关闭',.5,.93)])
        items=Scene([t('获得物品',.5,.14),t('宇宙碎片',.5,.50),t('点击空白处关闭',.5,.93)])
        field=Scene([t('(5/13) 第二位面-奖励')])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(side_effect=[(strengthening,'tutorial_overlay'),(items,'tutorial_overlay'),
                                     (field,'field_reward')])
        flow._snapshot=Mock(return_value=(strengthening,'tutorial_overlay'))
        self.assertEqual(flow._close_tutorial(strengthening),(items,'tutorial_overlay'))
        self.assertEqual(flow._close_tutorial(items),(field,'field_reward'))
        self.assertEqual(flow._click.call_count,3)
        mask=Scene([t('敷衍面具',.5,.14),t('区域会随机变化',.5,.50),t('点击空白处关闭',.5,.93)])
        lost=Scene([t('失去站点卡',.5,.14),t('点击空白处关闭',.5,.93)])
        gained=Scene([t('获得站点卡',.5,.14),t('点击空白处关闭',.5,.93)])
        upgraded=Scene([t('站点卡升级',.5,.14),t('点击空白处关闭',.5,.93)])
        for previous,current in ((mask,lost),(lost,gained),(gained,upgraded)):
            flow._click=Mock(return_value=(current,'tutorial_overlay'))
            self.assertEqual(flow._close_tutorial(previous),(current,'tutorial_overlay'))
            flow._click.assert_called_once()

    def test_card_interaction_recovers_missing_hint_before_retrying_fresh_prompt(self):
        import numpy as np
        header=t('(6/13) 第二位面-异常')
        image=np.zeros((540,960,3),np.uint8)
        initial=Scene([header,t('事件',.60,.55)],image)
        stopped=Scene([header],image)
        fresh=Scene([header,t('事件',.61,.54)],image)
        event=Scene([t('差分宇宙'),t('事件')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_interact.side_effect=[stopped,event]
        ctx.differential_universe_move.return_value=fresh
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(stopped,'field_anomaly'))
        flow._observe=Mock(side_effect=lambda page,label:'event' if page is event else 'field_anomaly')
        with patch('autohsr.du_navigation.event_targets',return_value=[]):
            self.assertEqual(flow._field_anomaly_visual(initial),(event,'event'))
        self.assertEqual([c.args[0] for c in ctx.differential_universe_interact.call_args_list],[initial,fresh])
        ctx.differential_universe_move.assert_called_once_with(stopped,'s',650)
        ctx.wait.assert_not_called()

    def test_unresponsive_live_card_prompts_are_bounded_to_three_inputs(self):
        import numpy as np
        page=Scene([t('(6/13) 第二位面-异常'),t('事件',.60,.55)],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_interact.return_value=page
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_anomaly'))
        flow._observe=Mock(return_value='field_anomaly')
        with self.assertRaisesRegex(AutomationError,'三次实时交互提示'):
            flow._field_anomaly_visual(page)
        self.assertEqual(ctx.differential_universe_interact.call_count,3)
        ctx.differential_universe_move.assert_not_called()

    def test_street_card_chooses_verified_fragment_reward_without_negative_curio(self):
        from autohsr.policy import du_event_free_choice
        choice=t('米叽里咕噜无语水果糖',.80,.525)
        body=t('获得300宇宙碎片，获得1个和宇宙碎片',.80,.565)
        page=Scene([t('事件'),t('商店街一番战',.15,.90),choice,body,t('相关的奇物',.75,.595),
                    t('米辣到怀疑人生的软糖',.80,.36),t('获得1个3星方程，获得1个随机负面奇物',.80,.40)])
        self.assertTrue(du_event_free_choice(page,choice))
        self.assertFalse(du_event_free_choice(page,page.tokens[-2]))
        guard_differential_universe_click(page,choice,intent='event_leave')
        ctx=Mock(settings=Settings(),report=RunReport())
        self.assertEqual(DifferentialUniverseWorkflow(ctx,1)._event_target(page),(choice,'event_leave'))
        for changed in ('花费300宇宙碎片，获得1个和宇宙碎片','获得300宇宙碎片，失去1个和宇宙碎片',
                        '获得300宇宙碎片，获得1个随机负面奇物'):
            page.tokens[3]=t(changed,.80,.565)
            self.assertFalse(du_event_free_choice(page,choice))
        page.tokens[3]=body
        page.tokens[1]=t('其他事件',.15,.90)
        self.assertFalse(du_event_free_choice(page,choice))

    def test_native_world_card_title_does_not_override_reward_room_header(self):
        import cv2,json
        from pathlib import Path
        from autohsr.du_navigation import event_targets
        root=Path(__file__).parent/'fixtures/du_runtime'
        for index in (130,131):
            data=json.loads((root/f'world_card_title_{index}.json').read_text('utf8'))
            page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                       cv2.imread(str(root/f'world_card_title_{index}.png')))
            self.assertEqual(classify_page(page),'field_reward')
            if index==131:
                with patch('autohsr.du_detector.detect_cards',return_value=[]):
                    targets=event_targets(page)
                self.assertEqual(len(targets),1)
                label=page.find('商店街一番战',(.20,.07,.80,.55),exact=True)
                self.assertAlmostEqual(targets[0].center[0],label.center[0])
                self.assertGreater(targets[0].center[1],label.center[1])
                with self.assertRaises(AutomationError):
                    from autohsr.policy import guard_differential_universe_field_interact
                    guard_differential_universe_field_interact(page,targets[0])
                with patch('autohsr.du_detector.detect_cards',return_value=[]):
                    self.assertEqual(event_targets(Scene([label],page.image)),[])
        page=Scene([t('(3/13) 第一位面-奖励'),t('商店街一番战',.5,.2),t('战斗',.6,.5)])
        self.assertEqual(classify_page(page),'field_reward')

    def test_fresh_card_station_approaches_before_searching_despite_unknown_art(self):
        import numpy as np
        for station,fresh in ((label,value) for label in ('奖励','铸造','商店','财富','冒险','异常','事件') for value in (False,True)):
            field_kind={'奖励':'field_reward','铸造':'field_forge','商店':'field_shop','财富':'field_wealth',
                        '冒险':'field_adventure','异常':'field_anomaly','事件':'field_event'}[station]
            page=Scene([t(f'(3/13) 第一位面-{station}')],np.zeros((540,960,3),np.uint8))
            near=Scene(page.tokens+[t('事件',.55,.53)],page.image)
            ctx=Mock(settings=Settings(),report=RunReport())
            flow=DifferentialUniverseWorkflow(ctx,1)
            flow._snapshot=Mock(return_value=(page,field_kind))
            flow._wait_known=Mock(side_effect=lambda page,kind,label:(page,kind))
            flow._field_anomaly_visual=Mock(return_value=(near,field_kind))
            ctx.differential_universe_motion.return_value=near
            flow._field_anomaly(page,fresh_entry=fresh)
            if fresh:
                ctx.differential_universe_motion.assert_called_once_with(page,'w',4000,profile='forward')
                flow._field_anomaly_visual.assert_called_once_with(near,field_kind=field_kind)
            else:
                ctx.differential_universe_motion.assert_not_called()
            ctx.differential_universe_look.assert_not_called()

    def test_lost_motion_ring_attacks_in_place_without_camera_search(self):
        import numpy as np
        page=Scene([t('(9/13) 第二位面-首领')],np.zeros((540,960,3),np.uint8))
        battle=Scene([t('战斗设置')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx._du_motion_result={'reason':'attack_reticle','attack_target':{'box':[.16,.35,.20,.42],'score':.9}}
        ctx.differential_universe_attack.return_value=battle
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        flow._field_attack_target=Mock(return_value=None)
        flow._choose_attack_character=Mock(return_value=(page,'field_combat'))
        flow._observe=Mock(return_value='battle')
        with patch('autohsr.du_navigation.navigation_targets',return_value=[]), \
             patch('autohsr.du_navigation.random_gate',return_value=None), \
             patch('autohsr.du_navigation.verified_attack_reticle',return_value=None):
            self.assertEqual(flow._field_visual(page,range_seen=True),(battle,'battle'))
        ctx.differential_universe_look.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_attack.assert_called_once()
        self.assertEqual(ctx.differential_universe_attack.call_args.args[-1],'field_forward_attack')

    def test_fresh_forward_approach_attacks_without_requiring_another_ring(self):
        import numpy as np
        page=Scene([t('(7/13) 第二位面-战斗')],np.zeros((540,960,3),np.uint8))
        done=Scene([t('选择祝福')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx._du_motion_result={'reason':'duration'}
        ctx.differential_universe_motion.return_value=page
        ctx.differential_universe_attack.return_value=done
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        flow._field_attack_target=Mock(return_value=None)
        flow._choose_attack_character=Mock(return_value=(page,'field_combat'))
        flow._observe=Mock(side_effect=lambda current,label:'blessing_choice' if current is done else 'field_combat')
        with patch('autohsr.du_navigation.navigation_targets',return_value=[]), \
             patch('autohsr.du_navigation.random_gate',return_value=None), \
             patch('autohsr.du_navigation.verified_attack_reticle',return_value=None):
            self.assertEqual(flow._field_combat(page,fresh_entry=True),(done,'blessing_choice'))
        ctx.differential_universe_motion.assert_called_once_with(page,'w',3000,profile='engage')
        ctx.differential_universe_look.assert_not_called()
        ctx.differential_universe_attack.assert_called_once()
        guard_differential_universe_click(page,*ctx.differential_universe_attack.call_args.args[1:2],intent='field_forward_attack')
        for other in (Scene([t('(7/13) 第二位面-事件')]),Scene([t('选择祝福')])):
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(other,ctx.differential_universe_attack.call_args.args[1],intent='field_forward_attack')

    def test_forward_attack_stops_after_two_misses_without_turning_or_walking(self):
        import numpy as np
        page=Scene([t('(7/13) 第二位面-战斗')],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_attack.return_value=page
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        flow._field_attack_target=Mock(return_value=None)
        flow._choose_attack_character=Mock(return_value=(page,'field_combat'))
        flow._observe=Mock(return_value='field_combat')
        with patch('autohsr.du_navigation.navigation_targets',return_value=[]), \
             patch('autohsr.du_navigation.random_gate',return_value=None), \
             patch('autohsr.du_navigation.verified_attack_reticle',return_value=None):
            with self.assertRaisesRegex(AutomationError,'两次接战未进入战斗'):
                flow._field_visual(page,forward_ready=True)
        self.assertEqual(ctx.differential_universe_attack.call_count,2)
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_look.assert_not_called()

    def test_stalled_fresh_probe_does_not_authorize_forward_attack(self):
        import numpy as np
        page=Scene([t('(7/13) 第二位面-战斗')],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx._du_motion_result={'reason':'background_stalled'}
        ctx.differential_universe_motion.return_value=page
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        flow._observe=Mock(return_value='field_combat')
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        flow._field_visual=Mock(return_value=(page,'field_combat'))
        with patch('autohsr.du_navigation.verified_attack_reticle',return_value=None):
            flow._field_combat(page,fresh_entry=True)
        flow._field_visual.assert_called_once_with(page,range_seen=False,forward_ready=False)

    def test_companion_ring_without_enemy_bar_preserves_fresh_forward_heading(self):
        import cv2,json
        from pathlib import Path
        from autohsr.du_navigation import attack_reticle,verified_attack_reticle,FieldMotionWatch
        root=Path(__file__).parent/'fixtures/du_runtime'
        data=json.loads((root/'companion_ring_candidate.json').read_text(encoding='utf8'))
        page=Scene([Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']],
                   cv2.imread(str(root/'companion_ring_candidate.png')))
        self.assertIsNone(attack_reticle(page))
        self.assertIsNone(verified_attack_reticle(page))
        vision=Mock();vision.read.return_value=Scene([])
        watch=FieldMotionWatch(page,vision,profile='engage')
        self.assertIsNone(watch(page.image))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx._du_motion_result={'reason':'duration'}
        ctx.differential_universe_motion.return_value=page
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        flow._wait_known=Mock(side_effect=lambda page,kind,label:(page,kind))
        flow._field_visual=Mock(return_value=(page,'field_combat'))
        flow._field_combat(page,fresh_entry=True)
        ctx.differential_universe_motion.assert_called_once_with(page,'w',3000,profile='engage')
        flow._field_visual.assert_called_once_with(page,range_seen=False,forward_ready=True)
        # A real ring and independent enemy bar still release held movement.
        real=Scene([t('(7/13) 第二位面-战斗'),t('等级90 惊梦剧团',.5,.05)],
                   cv2.imread(str(root/'attack_ring_mouse_animation.png')))
        self.assertIsNotNone(verified_attack_reticle(real))
        vision.read.return_value=Scene([t('等级90 惊梦剧团')])
        self.assertEqual(FieldMotionWatch(real,vision,profile='engage')(real.image),'attack_reticle')

    def test_short_blessing_name_ocr_variation_requires_matching_all_title_pixels(self):
        import cv2,numpy as np
        from pathlib import Path
        from autohsr.du_strategy import same_blessing_titles
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('blessing_title_variant','blessing_title_glow'):
            before=Scene([],cv2.imread(str(root/f'{name}_0.png')))
            after=Scene([],cv2.imread(str(root/f'{name}_1.png')))
            self.assertTrue(same_blessing_titles(before,after))
            changed=after.image.copy()
            changed[round(.42*540):round(.50*540),round(.405*960):round(.595*960)]=0
            self.assertFalse(same_blessing_titles(before,Scene([],changed)))
            changed=after.image.copy()
            changed[243:267,389:571]=after.image[243:267,634:816]
            self.assertFalse(same_blessing_titles(before,Scene([],changed)))
        self.assertFalse(same_blessing_titles(before,Scene([])))
        self.assertFalse(same_blessing_titles(Scene([],np.zeros_like(before.image)),
                                            Scene([],np.zeros_like(before.image))))

    def test_live_ring_with_enemy_bar_authorizes_attack_without_mouse_icon(self):
        import json,cv2
        from pathlib import Path
        from autohsr.du_navigation import attack_reticle
        root=Path(__file__).parent/'fixtures/du_runtime'
        data=json.loads((root/'attack_ring_mouse_animation.json').read_text(encoding='utf8'))
        page=Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in data['tokens']],
                   cv2.imread(str(root/'attack_ring_mouse_animation.png')))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.template.return_value=None
        flow=DifferentialUniverseWorkflow(ctx,1)
        ring,intent=flow._field_attack_target(page)
        self.assertEqual(ring,attack_reticle(page))
        self.assertEqual(intent,'field_ring_attack')
        guard_differential_universe_click(page,ring,intent=intent)
        ctx.template.assert_not_called()
        runner=SimpleNamespace(settings=Settings(),report=RunReport(operation='differential_universe'))
        context=Context(runner,Mock(),Mock())
        context.template=Mock(return_value=None)
        context._du_field_input=Mock(return_value=page)
        self.assertIs(context.differential_universe_attack(page,ring,intent),page)
        context.template.assert_not_called()
        for text in ('等级','第一位面'):
            other=Scene([t for t in page.tokens if text not in t.text],page.image)
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(other,ring,intent=intent)

    def test_fresh_entry_keeps_heading_even_when_only_a_side_enemy_is_detected(self):
        import numpy as np
        page=Scene([t('(3/13) 第一位面-战斗')],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx._du_motion_result={'reason':'attack_reticle'}
        ctx.differential_universe_motion.return_value=page
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        flow._observe=Mock(return_value='field_combat')
        flow._field_visual=Mock(return_value=(page,'field_combat'))
        with patch('autohsr.du_navigation.navigation_targets',return_value=[Token('Enemy',.8,(.60,.35,.66,.46))]), \
             patch('autohsr.du_navigation.attack_reticle',return_value=None):
            flow._field_combat(page,fresh_entry=True)
        ctx.differential_universe_motion.assert_called_once_with(page,'w',3000,profile='engage')
        flow._field_visual.assert_called_once_with(page,range_seen=True,forward_ready=True)
        ctx.differential_universe_look.assert_not_called()

    def test_battle_clear_is_retained_until_next_station_then_reset(self):
        battle=Scene([t('战斗设置')])
        field=Scene([t('(4/13) 第一位面-首领')])
        route=Scene([t('选择下一站'),t('战斗')])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._battle=Mock(return_value=(field,'field_combat'))
        flow._station_target=Mock(return_value=(route.tokens[-1],'station_select'))
        flow._click=Mock(return_value=(field,'field_combat'))
        def field_combat(page,*,fresh_entry):
            if flow._field_combat.call_count==1:
                self.assertTrue(flow._field_cleared)
                return route,'station_choice'
            self.assertFalse(flow._field_cleared)
            self.assertTrue(fresh_entry)
            raise AutomationError('new station state verified')
        flow._field_combat=Mock(side_effect=field_combat)
        with self.assertRaisesRegex(AutomationError,'new station state verified'):
            flow._progress_run(battle,'battle')

    def test_awake_door_remains_cleared_when_camera_temporarily_hides_its_eyes(self):
        import numpy as np
        page=Scene([t('(4/13) 第一位面-首领')],np.zeros((540,960,3),np.uint8))
        route=Scene([t('选择下一站'),t('战斗')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_motion.side_effect=[page,route]
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._field_attack_target=Mock(side_effect=AssertionError('cleared room'))
        face=Token('差分宇宙随意门外观',.95,(.4,.2,.6,.4))
        gate=Token('Target',.9,(.45,.2,.55,.5))
        with patch('autohsr.du_navigation.random_gate',side_effect=[face,None,None]), \
             patch('autohsr.du_navigation.navigation_targets',return_value=[gate]) as targets:
            self.assertEqual(flow._field_visual(page)[1],'station_choice')
        self.assertEqual([c.kwargs['enemies'] for c in targets.call_args_list],[False,False])

    def test_interrupted_gate_approach_repositions_before_retrying_live_prompt(self):
        import numpy as np
        field=t('(4/13) 第一位面-首领')
        initial=Scene([field,t('随意门',.6,.55)],np.zeros((540,960,3),np.uint8))
        stopped=Scene([field],initial.image)
        arrived=Scene([field,t('随意门',.6,.55)],initial.image)
        route=Scene([t('选择下一站'),t('战斗')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_enter_random_gate.side_effect=[stopped,route]
        ctx.differential_universe_motion.return_value=arrived
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._field_attack_target=Mock(return_value=None)
        flow._snapshot=Mock(return_value=(stopped,'field_combat'))
        gate=Token('Target',.9,(.45,.20,.55,.50))
        with patch('autohsr.du_navigation.navigation_targets',return_value=[gate]), \
             patch('autohsr.du_navigation.attack_reticle',return_value=None), \
             patch('autohsr.du_navigation.random_gate',return_value=None):
            self.assertEqual(flow._field_visual(initial)[1],'station_choice')
        self.assertEqual([call.args[0] for call in ctx.differential_universe_enter_random_gate.call_args_list],
                         [initial,arrived])
        ctx.differential_universe_motion.assert_called_once_with(stopped,'w',4000,profile='target')

    def test_gate_retry_stops_after_two_freshly_verified_prompts(self):
        page=Scene([t('(4/13) 第一位面-首领'),t('随意门',.6,.55)])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._field_attack_target=Mock(return_value=None)
        flow._enter_gate=Mock(return_value=(page,'field_combat'))
        with patch('autohsr.du_navigation.navigation_targets',return_value=[]), \
             patch('autohsr.du_navigation.attack_reticle',return_value=None):
            with self.assertRaisesRegex(AutomationError,'两次已核实随意门'):
                flow._field_visual(page)
        self.assertEqual(flow._enter_gate.call_count,2)
        ctx.differential_universe_motion.assert_not_called()

    def test_monthly_login_supply_interrupts_battle_and_requires_owned_reward(self):
        claim=t('点击领取今日补给',.5,.862)
        before=Scene([t('列车补给',.5,.071),t('剩余：10天',.5,.120),claim])
        revealed=Scene(before.tokens+[t('90',.5,.55),t('星琼',.5,.59)])
        battle=Scene([t('战斗设置')])
        self.assertEqual(classify_page(before),'login_supply')
        self.assertEqual(classify_page(revealed),'login_supply')
        guard_differential_universe_click(before,claim,intent='du_supply_claim')
        guard_differential_universe_click(revealed,claim,intent='du_supply_close')
        for page,intent in ((before,'du_supply_close'),(revealed,'du_supply_claim'),
                            (Scene(before.tokens+[t('购买')]),'du_supply_claim'),
                            (Scene([t('列车补给',.5,.071),t('剩余：0天',.5,.120),claim]),'du_supply_claim'),
                            (Scene(before.tokens+[t('300',.5,.55)]),'du_supply_claim')):
            with self.subTest(intent=intent,text=page.text),self.assertRaises(AutomationError):
                guard_differential_universe_click(page,claim,intent=intent)
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._click=Mock(side_effect=[(before,'login_supply'),(revealed,'login_supply')])
        def wait(predicate,**kwargs):
            page=revealed if flow._click.call_count==1 else battle
            self.assertTrue(predicate(page))
            return page
        ctx.wait.side_effect=wait
        self.assertEqual(flow._settle_supply(before)[1],'login_supply')
        self.assertEqual(flow._settle_supply(revealed)[1],'battle')
        self.assertEqual([c.kwargs['intent'] for c in flow._click.call_args_list],
                         ['du_supply_claim','du_supply_close'])
        with self.assertRaises(AutomationError):
            flow._settle_supply(revealed)

    def test_split_enemy_bar_allows_attack_only_with_live_range_ring(self):
        page=Scene([t('(11/13) 第三位面-精英'),t('等级93',.45,.05),t('「药王秘传」',.55,.05)])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._daily._icon=Mock(side_effect=lambda page,name,roi,**kw:(.89,.84) if name=='du_attack_mouse' else None)
        ctx.template.return_value=None
        ring=Token('差分宇宙已锁定敌方目标',.9,(.49,.35,.53,.40))
        with patch('autohsr.du_navigation.attack_reticle',return_value=ring):
            self.assertEqual(flow._field_attack_target(page)[1],'field_ring_attack')
        with patch('autohsr.du_navigation.attack_reticle',return_value=None):
            self.assertIsNone(flow._field_attack_target(page))

    def test_aligned_enemy_occlusion_bridge_does_not_require_persistent_name_bar(self):
        import numpy as np
        page=Scene([t('(9/13) 第二位面-首领')],np.zeros((540,960,3),np.uint8))
        near=Scene([t('战斗设置')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_look.return_value=page
        ctx.differential_universe_motion.return_value=near
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._field_attack_target=Mock(return_value=None)
        flow._observe=Mock(side_effect=lambda page,label:'battle' if page is near else 'field_combat')
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        enemy=Token('Enemy',.95,(.60,.26,.68,.45))
        with patch('autohsr.du_navigation.navigation_targets',side_effect=[[enemy],[]]), \
             patch('autohsr.du_navigation.attack_reticle',return_value=None):
            self.assertEqual(flow._field_visual(page),(near,'battle'))
        ctx.differential_universe_look.assert_called_once()
        ctx.differential_universe_motion.assert_called_once_with(page,'w',600,profile='engage')
        ctx.differential_universe_attack.assert_not_called()

    def test_fresh_forward_approach_keeps_heading_when_front_door_can_drop_out(self):
        import numpy as np
        page=Scene([t('(9/13) 第二位面-首领')],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx._du_motion_result={'reason':'attack_reticle'}
        ctx.differential_universe_motion.return_value=page
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        flow._observe=Mock(return_value='field_combat')
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        flow._field_visual=Mock(return_value=(page,'field_combat'))
        front=Token('Target',.65,(.46,.2,.54,.4))
        with patch('autohsr.du_navigation.navigation_targets',return_value=[front]), \
             patch('autohsr.du_navigation.attack_reticle',return_value=None):
            flow._field_combat(page,fresh_entry=True)
        ctx.differential_universe_motion.assert_called_once_with(page,'w',3000,profile='engage')
        flow._field_visual.assert_called_once_with(page,range_seen=True,forward_ready=True)
        ctx.differential_universe_look.assert_not_called()

    def test_warp_compound_eye_curio_is_distinct_from_warp_navigation(self):
        curio=t('跃迁复眼',.25,.48)
        page=Scene([t('差分宇宙'),t('选择奇物',.1,.08),t('请选择奇物',.5,.135),curio])
        guard_differential_universe_click(page,curio,intent='choice')
        for other in (Scene([curio]),Scene([t('跃迁'),curio]),
                      Scene([t('差分宇宙'),t('选择祝福'),t('请选择奇物',.5,.135),curio])):
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(other,curio,intent='choice')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,curio,intent='navigation')

    def test_only_fresh_confirmed_station_can_probe_unknown_enemy_forward(self):
        import numpy as np
        page=Scene([t('(6/13) 第二位面-精英')],
                   np.zeros((540,960,3),np.uint8))
        for fresh in (False,True):
            with self.subTest(fresh=fresh):
                ctx=Mock(settings=Settings(),report=RunReport())
                ctx.differential_universe_motion.return_value=page
                flow=DifferentialUniverseWorkflow(ctx,1)
                flow._field_attack_target=Mock(return_value=(t('差分宇宙基础攻击',.88,.85),'field_attack'))
                flow._field_visual=Mock(return_value=(page,'field_combat'))
                flow._snapshot=Mock(return_value=(page,'field_combat'))
                flow._observe=Mock(return_value='field_combat')
                flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
                with patch('autohsr.du_navigation.navigation_targets',return_value=[]), \
                     patch('autohsr.du_navigation.attack_reticle',return_value=None):
                    flow._field_combat(page,fresh_entry=fresh)
                if fresh:
                    ctx.differential_universe_motion.assert_called_once_with(page,'w',3000,profile='engage')
                else:
                    ctx.differential_universe_motion.assert_not_called()
                ctx.differential_universe_look.assert_not_called()

    def test_lost_range_ring_after_party_switch_never_resumes_forward_motion(self):
        import numpy as np
        page=Scene([t('(9/13) 第二位面-首领'),t('等级90 金人司阍',.5,.05)],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._field_attack_target=Mock(return_value=(t('差分宇宙基础攻击',.88,.85),'field_attack'))
        flow._choose_attack_character=Mock(return_value=(page,'field_combat'))
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        flow._observe=Mock(return_value='field_combat')
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        ctx.differential_universe_look.return_value=page
        ctx.differential_universe_attack.return_value=page
        ring=Token('差分宇宙已锁定敌方目标',.8,(.03,.65,.06,.71))
        enemy=Token('Enemy',.9,(.44,.42,.56,.70))
        with patch('autohsr.du_navigation.navigation_targets',return_value=[enemy]), \
             patch('autohsr.du_navigation.verified_attack_reticle',side_effect=[ring]+[None]*7):
            with self.assertRaisesRegex(AutomationError,'两次接战未进入战斗'):
                flow._field_visual(page)
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_move.assert_not_called()
        self.assertEqual(ctx.differential_universe_attack.call_count,2)
        ctx.differential_universe_look.assert_not_called()

    def test_centered_pink_gate_keeps_heading_even_with_sideways_enemy(self):
        import numpy as np
        from autohsr.models import Stopped
        page=Scene([t('(7/13) 第二位面-战斗')],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_motion.side_effect=Stopped('forward verified')
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._field_attack_target=Mock(return_value=None)
        gate=Token('Target',.9,(.46,.25,.54,.55))
        enemy=Token('Enemy',.9,(.70,.3,.82,.6))
        with patch('autohsr.du_navigation.navigation_targets',return_value=[enemy,gate]), \
             patch('autohsr.du_navigation.random_gate',return_value=None), \
             patch('autohsr.du_navigation.verified_attack_reticle',return_value=None), \
             patch('autohsr.du_detector.forward_barrier',return_value=None):
            with self.assertRaisesRegex(Stopped,'forward verified'):
                flow._field_visual(page)
        ctx.differential_universe_motion.assert_called_once_with(page,'w',3000,profile='engage')
        ctx.differential_universe_look.assert_not_called()

    def test_blessing_discard_modal_requires_exact_prompt_and_selected_name(self):
        from autohsr.policy import du_blessing_discard_prompt
        cancel=t('取消',.40,.62);confirm=t('确认',.62,.62)
        page=Scene([t('确认丢弃祝福「传质次星」？',.50,.485),cancel,confirm],
                   captured_at=time.monotonic())
        self.assertEqual(du_blessing_discard_prompt(page),'传质次星')
        self.assertEqual(classify_page(page),'blessing_discard_prompt')
        guard_differential_universe_click(page,confirm,intent='blessing_discard_prompt_confirm')
        runner=SimpleNamespace(settings=Settings(),report=RunReport(operation='differential_universe'),
                               input_epoch=0,checkpoint=Mock())
        ctx=Context(runner,Mock(),Mock());ctx.last_scene=page
        for decision in ({},{'discard':True,'selected':'厚垣'},
                         {'discard':False,'selected':'传质次星'}):
            runner.report.differential_universe={'reward_decisions':[decision]}
            with self.assertRaisesRegex(AutomationError,'不一致'):
                ctx.click(page,confirm,du_intent='blessing_discard_prompt_confirm')
        ctx.window.click.assert_not_called()
        for text in ('确认丢弃奇物「传质次星」？','确认丢弃祝福「传质次星」并花费100宇宙碎片？'):
            page.tokens[0]=t(text,.50,.485)
            self.assertIsNone(du_blessing_discard_prompt(page))
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(page,confirm,intent='blessing_discard_prompt_confirm')

    def test_one_star_blessing_discard_page_and_star_guard(self):
        import cv2,json,numpy as np
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime'
        data=json.loads((root/'blessing_discard.json').read_text(encoding='utf8'))
        page=Scene([Token(t['text'],t['score'],tuple(t['box'])) for t in data['tokens']],
                   cv2.imread(str(root/'blessing_discard.png')))
        self.assertEqual(classify_page(page),'blessing_discard')
        card=t('祝福候选卡片',.25,.32)
        guard_differential_universe_click(page,card,intent='blessing_discard_select')
        button=page.find('丢弃',(.56,.78,.99,.98),exact=True)
        guard_differential_universe_click(page,button,intent='blessing_discard_confirm')
        page.image=np.zeros_like(page.image)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,button,intent='blessing_discard_confirm')

    def test_discard_preserves_expanded_equations_and_needed_paths(self):
        from autohsr.du_strategy import blessing_discard_score
        option=t('传质次星',.25,.47)
        excess=Scene([option,t('7>>6/4',.25,.95)])
        needed=Scene([option,t('2>>1/4',.25,.95)])
        expanded=Scene([option,t('4>>3/4',.25,.95)])
        self.assertGreater(blessing_discard_score(excess,option,preview=True)[0],
                           blessing_discard_score(needed,option,preview=True)[0])
        self.assertGreater(blessing_discard_score(needed,option,preview=True)[0],
                           blessing_discard_score(expanded,option,preview=True)[0])
        self.assertEqual(blessing_discard_score(expanded,option,preview=True)[1]['equations_disabled'],1)

    def test_flea_market_only_allows_bounded_one_star_blessing_trade(self):
        from autohsr.policy import du_flea_market_choice
        title=t('跳蚤市场',.13,.9)
        option=t('米讲述多彩的旅途。',.81,.29)
        page=Scene([t('事件'),title,option,t('提交祝福。',.81,.33)])
        self.assertTrue(du_flea_market_choice(page,option))
        guard_differential_universe_click(page,option,intent='event_flea_select')
        page.tokens[2]=option=t('雪原的赏金猎人。',.81,.29)
        page.tokens[3]=t('失去1个1星祝福，获得3个2-3星祝福。',.81,.33)
        self.assertTrue(du_flea_market_choice(page,option))
        confirm=t('确定',.9,.40);page.tokens.append(confirm)
        guard_differential_universe_click(page,confirm,intent='event_flea_confirm')
        for description in ('失去2个1星祝福，获得3个2-3星祝福。','失去1个3星祝福，获得3个2-3星祝福。',
                            '失去50宇宙碎片，获得3个1-3星奇物。','失去1个1星祝福，获得3个2-3星祝福，花费100宇宙碎片。'):
            page.tokens[3]=t(description,.81,.33)
            self.assertFalse(du_flea_market_choice(page,option))
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(page,confirm,intent='event_flea_confirm')

    def test_centered_enemy_survives_only_two_short_avatar_occlusion_steps(self):
        import numpy as np
        page=Scene([t('(4/13) 第一位面-首领')],np.zeros((540,960,3),np.uint8))
        enemy=Token('Enemy',.95,(.43,.25,.57,.50))
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_motion.side_effect=[page,page,page,RuntimeError('stationary search')]
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._field_attack_target=Mock(return_value=(t('差分宇宙基础攻击',.88,.85),'field_attack'))
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        with patch('autohsr.du_navigation.navigation_targets',side_effect=[[enemy],[],[],[],[],[]]), \
             patch('autohsr.du_navigation.attack_reticle',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'stationary search'):
                flow._field_visual(page)
        moves=ctx.differential_universe_motion.call_args_list
        self.assertEqual([c.args[2] for c in moves[:3]],[3000,600,600])
        self.assertTrue(all(c.kwargs['profile']=='engage' for c in moves[:3]))
        self.assertEqual(moves[-1].args[1:],('scan_right',8000))
        self.assertEqual(moves[-1].kwargs,{'profile':'seek'})
        ctx.differential_universe_attack.assert_not_called()
        ctx.differential_universe_move.assert_not_called()

    def test_large_enemy_does_not_trigger_close_door_backoff(self):
        import numpy as np
        page=Scene([t('(4/13) 第一位面-首领')],np.zeros((540,960,3),np.uint8))
        enemy=Token('Enemy',.95,(.3,.1,.7,.85))
        battle=Scene([t('战斗设置')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_motion.return_value=battle
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._field_attack_target=Mock(return_value=None)
        with patch('autohsr.du_navigation.navigation_targets',return_value=[enemy]), \
             patch('autohsr.du_navigation.random_gate',return_value=None), \
             patch('autohsr.du_detector.forward_barrier',return_value=None):
            self.assertEqual(flow._field_visual(page)[1],'battle')
        ctx.differential_universe_move.assert_not_called()

    def test_noncombat_worlds_only_navigate_to_exit_and_never_attack_or_purchase(self):
        from autohsr.policy import guard_differential_universe_field_input,guard_differential_universe_portal
        import numpy as np
        for label,kind in (('商店','field_shop'),('财富','field_wealth'),('休整','field_rest'),
                           ('空白','field_blank'),('铸造','field_forge'),('冒险','field_adventure')):
            with self.subTest(label=label):
                page=Scene([t('(7/13) 第二位面-'+label),t('随意门',.60,.55)],np.zeros((540,960,3),np.uint8))
                self.assertEqual(classify_page(page),kind)
                guard_differential_universe_field_input(page,action='move_w')
                guard_differential_universe_portal(page,page.tokens[-1])
                for target in (t('购买',.6,.5),t('差分宇宙基础攻击',.88,.85)):
                    with self.assertRaises(AutomationError):
                        guard_differential_universe_click(page,target,intent='field_attack' if target.text.endswith('攻击') else 'navigation')
                ctx=Mock(settings=Settings(),report=RunReport())
                ctx.differential_universe_enter_random_gate.return_value=Scene([t('选择下一站'),t('选择一张站点卡')])
                flow=DifferentialUniverseWorkflow(ctx,1)
                with patch('autohsr.du_navigation.navigation_targets',return_value=[]) as detect:
                    self.assertEqual(flow._field_visual(page,field_kind=kind)[1],'station_choice')
                detect.assert_called_once_with(page,enemies=False)
                ctx.differential_universe_attack.assert_not_called()

    def test_free_color_reward_accepts_pure_gain_and_rejects_spending_or_negative_curios(self):
        from autohsr.policy import du_event_free_choice
        option=t('米淡金色。',.81,.29)
        page=Scene([t('事件'),t('一抹色彩',.13,.9),option,t('获得300宇宙碎片。',.81,.33)])
        self.assertTrue(du_event_free_choice(page,option))
        guard_differential_universe_click(page,option,intent='event_leave')
        for description,allowed in [('获得3个随机1-2星祝福。',True),('获得3个随机1-2星奇物。',True),
                                    ('放弃战斗，直接获得2个随机2-3星祝福',True),
                                    ('有概率获得3星祝福。',True),('有概率获得3星奇物。',True),
                                    ('获得1个3星奇物。',True),('获得1个3星祝福。',True),
                                    ('有概率获得3星奇物，花费100宇宙碎片',False),
                                    ('花费300宇宙碎片。',False),('获得3个负面奇物。',False),
                                    ('获得300宇宙碎片并消耗1个奇物',False)]:
            page.tokens[-1]=t(description,.81,.33)
            self.assertEqual(du_event_free_choice(page,option),allowed)

    def test_reward_world_cards_include_gold_frame_and_exclude_sleeping_gate(self):
        import cv2,numpy as np
        from pathlib import Path
        from autohsr.du_navigation import event_cards
        path=Path(__file__).parent/'fixtures/du_runtime/cards_reward_gold.png'
        cards=event_cards(Scene([],cv2.imdecode(np.fromfile(path,np.uint8),1)))
        for x,y in ((.378,.283),(.579,.267)):
            self.assertTrue(any(abs(t.center[0]-x)<.035 and abs(t.center[1]-y)<.035 for t in cards))
        self.assertFalse(any(abs(t.center[0]-.48)<.025 for t in cards))

    def test_reward_field_uses_card_interaction_and_never_authorizes_an_attack(self):
        from autohsr.policy import guard_differential_universe_field_input,guard_differential_universe_field_interact
        for label,kind in (('奖励','field_reward'),('事件','field_event')):
            with self.subTest(label=label):
                page=Scene([t('(7/13) 第二位面-'+label),t('事件',.60,.55)])
                self.assertEqual(classify_page(page),kind)
                guard_differential_universe_field_input(page,action='move_w')
                guard_differential_universe_field_interact(page,page.tokens[-1])
                with self.assertRaises(AutomationError):
                    guard_differential_universe_click(page,t('差分宇宙基础攻击',.88,.85),intent='field_attack')

    def test_bright_cyan_abnormal_card_does_not_require_dark_frame_rails(self):
        import cv2,numpy as np
        from pathlib import Path
        from autohsr.du_navigation import event_cards
        path=Path(__file__).parent/'fixtures/du_runtime/card_cyan_frame.png'
        cards=event_cards(Scene([],cv2.imdecode(np.fromfile(path,np.uint8),1)))
        self.assertTrue(any(abs(t.center[0]-.296)<.035 and abs(t.center[1]-.351)<.035 for t in cards))

    def test_sleeping_gate_face_is_never_mistaken_for_the_back(self):
        import cv2,json,numpy as np
        from pathlib import Path
        from autohsr.du_navigation import random_gate
        root=Path(__file__).parent/'fixtures/du_runtime'
        for row in json.loads((root/'sleep_gate_states.json').read_text()):
            with self.subTest(file=row['file']):
                page=Scene([],cv2.imdecode(np.fromfile(root/row['file'],np.uint8),1))
                gate=random_gate(page,fast=True)
                self.assertIsNotNone(gate)
                self.assertEqual(gate.text,'差分宇宙睡眼门')

    def test_anomaly_requires_awake_eyes_before_approaching_exit(self):
        import numpy as np
        page=Scene([t('(3/13) 第一位面-异常')],np.zeros((540,960,3),np.uint8))
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._field_visual=Mock(side_effect=AssertionError('unconfirmed exit'))
        ctx.differential_universe_look.return_value=page
        gate=Token('差分宇宙随意门背面',.94,(.4,.3,.6,.6))
        with patch('autohsr.du_navigation.event_targets',return_value=[]), \
             patch('autohsr.du_navigation.navigation_targets',return_value=[gate]), \
             patch('autohsr.du_navigation.random_gate',return_value=gate):
            with self.assertRaisesRegex(AutomationError,'异常区域原地搜索达到上限'):
                flow._field_anomaly_visual(page)
        flow._field_visual.assert_not_called()
        ctx.differential_universe_motion.assert_not_called()
        ctx.differential_universe_interact.assert_not_called()

    def test_cooking_event_accepts_verified_free_fight_and_rejects_changed_cost(self):
        from autohsr.policy import du_event_free_choice
        option=t('米一起上吧，我赶时间。',.81,.25)
        page=Scene([t('事件'),t('厨王争霸',.13,.90),option,
                    t('和攻擂者们战斗，胜利后获得2个1星奇',.81,.29),t('物和100宇宙碎片',.81,.32)])
        self.assertTrue(du_event_free_choice(page,option))
        guard_differential_universe_click(page,option,intent='event_leave')
        confirm=t('确定',.92,.37);page.tokens.append(confirm)
        guard_differential_universe_click(page,confirm,intent='event_confirm')
        page.tokens.pop()
        page.tokens[-1]=t('物，花费100宇宙碎片',.81,.32)
        self.assertFalse(du_event_free_choice(page,option))
        option=t('输了可别哭鼻子。',.81,.44)
        page=Scene([t('事件'),t('归来的岁阳',.13,.90),option,
                    t('与浮烟进行战斗，胜利后获得2个2星祝',.81,.48),t('福和200宇宙碎片',.81,.51)])
        self.assertTrue(du_event_free_choice(page,option))
        page.tokens[-1]=t('福，消耗200宇宙碎片',.81,.51)
        self.assertFalse(du_event_free_choice(page,option))

    def test_partial_card_frame_is_recovered_without_targeting_pink_door(self):
        import cv2,numpy as np
        from pathlib import Path
        from autohsr.du_navigation import event_cards
        path=Path(__file__).parent/'fixtures/du_runtime/card_avatar_occlusion.png'
        cards=event_cards(Scene([],cv2.imdecode(np.fromfile(path,np.uint8),1)))
        self.assertTrue(any(abs(t.center[0]-.46)<.035 for t in cards))
        self.assertFalse(any(abs(t.center[0]-.33)<.035 for t in cards))

    def test_just_aligned_card_survives_two_bounded_avatar_occlusion_steps(self):
        import numpy as np
        field=Scene([t('(3/13) 第一位面-异常')],np.zeros((540,960,3),np.uint8))
        card=Token('Card',.9,(.62,.30,.68,.45))
        event=Scene([t('事件')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_look.return_value=field
        ctx.differential_universe_motion.side_effect=[field,event]
        flow=DifferentialUniverseWorkflow(ctx,1)
        with patch('autohsr.du_navigation.event_targets',side_effect=[[card],[],[]]):
            self.assertEqual(flow._field_anomaly_visual(field)[1],'event')
        self.assertEqual(ctx.differential_universe_look.call_count,1)
        self.assertEqual(ctx.differential_universe_motion.call_count,2)
        for call in ctx.differential_universe_motion.call_args_list:
            self.assertEqual(call.args[1:],('w',600))
            self.assertEqual(call.kwargs['profile'],'occluded_card')
        ctx.differential_universe_move.assert_not_called()

    def test_distant_anomaly_card_frame_at_seventy_pixels_is_a_target(self):
        import cv2,numpy as np
        from pathlib import Path
        from autohsr.du_navigation import event_cards
        path=Path(__file__).parent/'fixtures/du_runtime/card_distant.png'
        cards=event_cards(Scene([],cv2.imdecode(np.fromfile(path,np.uint8),1)))
        self.assertTrue(any(abs(t.center[0]-.365)<.03 and abs(t.center[1]-.35)<.03 for t in cards))

    def test_native_title_retry_recovers_missing_two_character_blessing(self):
        import cv2,json,numpy as np
        from pathlib import Path
        from autohsr.vision import Vision
        root=Path(__file__).parent/'fixtures/du_runtime'
        meta=json.loads((root/'blessing_missing_title.json').read_text())
        w,h=meta['size']; image=np.zeros((h,w,3),np.uint8);a,b,c,d=meta['roi']
        image[round(b*h):round(d*h),round(a*w):round(c*w)]=cv2.imdecode(np.fromfile(root/'blessing_missing_title.png',np.uint8),1)
        page=Scene([t('选择祝福'),t('双极喷流',.50,.47),t('黑色太阳',.75,.47)],image)
        vision=Vision(); vision.refine_du_blessing_names(page)
        self.assertEqual(DifferentialUniverseWorkflow._choice_identity(page,'blessing_choice'),('悬丝','双极喷流','黑色太阳'))
        count=len(page.tokens);vision.refine_du_blessing_names(page)
        self.assertEqual(len(page.tokens),count)

    def test_current_analysis_report_requires_success_and_complete_progress(self):
        page=Scene([t(s) for s in ('分析报告','探索成功','差分宇宙构筑内容','周期演算（13/13）','返回主界面')])
        self.assertEqual(classify_page(page),'victory')
        page.tokens[3]=t('周期演算（12/13）')
        self.assertNotEqual(classify_page(page),'victory')
        page.tokens[1]=t('探索中断')
        self.assertEqual(classify_page(page),'defeat')

    def test_party_number_keys_reach_native_backend_and_release(self):
        from autohsr.windows import GameWindow
        window=SimpleNamespace(send=Mock())
        with patch('autohsr.windows.user32.MapVirtualKeyW',side_effect=lambda key,mode:key) as mapped, \
             patch('autohsr.windows.user32.SendInput',return_value=1) as released, \
             patch('autohsr.windows.time.sleep'):
            for key in ('1','2','3','4'):
                GameWindow.key(window,key)
            self.assertEqual([call.args[0] for call in mapped.call_args_list],[0x31,0x32,0x33,0x34])
            self.assertEqual(window.send.call_count,4)
            self.assertEqual(released.call_count,4)
            with self.assertRaises(ValueError):
                GameWindow.key(window,'5')

    def test_rest_field_can_use_gate_without_considering_an_attack(self):
        from autohsr.policy import guard_differential_universe_field_input,guard_differential_universe_portal
        page=Scene([t('(12/13) 第三位面-休整'),t('随意门',.6,.55)])
        self.assertEqual(classify_page(page),'field_rest')
        guard_differential_universe_field_input(page,action='move_w')
        guard_differential_universe_portal(page,page.tokens[1])
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        flow=DifferentialUniverseWorkflow(context,1)
        flow._field_attack_target=Mock(side_effect=AssertionError('rest does not attack'))
        context.differential_universe_enter_random_gate.return_value=Scene([t('选择下一站')])
        flow._observe=Mock(return_value='station_choice')
        flow._wait_known=Mock(side_effect=lambda p,k,label,**kw:(p,k))
        with patch('autohsr.du_navigation.navigation_targets',return_value=[]):
            self.assertEqual(flow._field_visual(page,field_kind='field_rest')[1],'station_choice')
        context.differential_universe_enter_random_gate.assert_called_once_with(page,page.tokens[1])
        context.differential_universe_attack.assert_not_called()

    def test_free_elite_card_level_effect_uses_its_named_target(self):
        page=Scene([t('选择站点卡'),t('指定1个【精英】区域，使其等级+1',.3,.145),
                    t('抽牌区'),t('精英',.23,.56),t('确定',.85,.89)])
        for detail in ('混沌：战斗胜利后额外获得1个奇物',
                       '强敌：区域内的敌人获得强化，战斗胜利后选择祝福时，升级所有祝福',
                       '战斗胜利后选择奇物或选择方程'):
            current=Scene(page.tokens+[t(detail,.5,.65)])
            self.assertEqual(classify_page(current),'miracle_target')
        guard_differential_universe_click(page,page.tokens[3],intent='miracle_target')
        guard_differential_universe_click(page,page.tokens[4],intent='miracle_target_confirm')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,t('战斗',.23,.56),intent='miracle_target')
        from autohsr.policy import du_miracle_target_labels
        for name in ('战斗','精英','首领','财富','异常','事件','冒险','铸造','商店','休整','奖励','空白'):
            current=Scene([t('选择站点卡'),t('抽牌区'),t(f'指定1个【{name}】区域，使其等级+1',.3,.145),
                           t(name,.23,.56),t('确定',.85,.89)])
            self.assertEqual(du_miracle_target_labels(current),(name,))
            self.assertEqual(classify_page(current),'miracle_target')
            guard_differential_universe_click(current,current.tokens[3],intent='miracle_target')
            current.tokens[2]=t(f'指定1个【{name}】区域，使其等级+20',.3,.145)
            self.assertEqual(du_miracle_target_labels(current),(name,))

    def test_three_blessing_titles_allow_one_character_ocr_fragment(self):
        page=Scene([t('共晓的时期',.25,.47),t('悬丝',.50,.47),t('节',.75,.47),
                    t('我方目标消耗战技点时速度提高',.75,.57)])
        self.assertEqual(DifferentialUniverseWorkflow._choice_identity(page,'blessing_choice'),
                         ('共晓的时期','悬丝','节'))

    def test_blessing_waits_for_animation_fragments_to_become_stable_titles(self):
        partial=Scene([t('受追',.25,.47),t('可使寸',.75,.47)])
        settled=Scene([t('受迫性跃迁',.25,.47),t('端感棒',.50,.47),t('可使寸寸折',.75,.47)])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._inactive=Mock(return_value=0)
        flow._snapshot=Mock(side_effect=[(settled,'blessing_choice'),(settled,'blessing_choice')])
        self.assertIs(flow._settle_blessing_titles(partial),settled)
        self.assertEqual(flow._snapshot.call_count,2)
        ctx.click.assert_not_called()

    def test_awake_gate_keeps_live_bearing_when_avatar_hides_one_eye(self):
        import numpy as np
        field=Scene([t('(6/13) 第二位面-异常')],np.zeros((540,960,3),np.uint8))
        aligned=Scene(field.tokens,field.image.copy())
        done=Scene([t('选择下一站'),t('战斗')])
        ctx=Mock(settings=Settings(),report=RunReport())
        ctx.differential_universe_look.return_value=aligned
        ctx.differential_universe_motion.return_value=done
        flow=DifferentialUniverseWorkflow(ctx,1)
        with patch('autohsr.du_navigation.event_targets',return_value=[]), \
             patch('autohsr.du_navigation.navigation_targets',side_effect=[
                 [Token('Target',.9,(.30,.15,.50,.65))],
                 [Token('Target',.9,(.40,.15,.60,.65))]]), \
             patch('autohsr.du_navigation.random_gate',side_effect=[
                 Token('差分宇宙随意门外观',.95,(.30,.3,.50,.5)),None]):
            self.assertEqual(flow._field_anomaly_visual(field)[1],'station_choice')
        ctx.differential_universe_look.assert_called_once()
        ctx.differential_universe_motion.assert_called_once()

    def test_visual_numpy_heading_is_accepted_without_native_input(self):
        import numpy as np
        from autohsr.windows import GameWindow,Geometry
        window=SimpleNamespace(send=Mock())
        with patch('autohsr.windows.time.sleep'):
            GameWindow.look(window,np.float64(.06),0,100,Geometry(0,0,1920,1080))
        self.assertGreater(window.send.call_count,0)
        with self.assertRaises(AutomationError):
            GameWindow.look(window,float('nan'),0,100,Geometry(0,0,1920,1080))
        with self.assertRaises(AutomationError):
            GameWindow.look(window,True,0,100,Geometry(0,0,1920,1080))

    def test_stall_ignores_avatar_motion_but_accepts_world_translation(self):
        import numpy as np
        import cv2
        from autohsr.du_navigation import BackgroundProgress
        rng=np.random.default_rng(42)
        image=rng.integers(0,255,(540,960,3),dtype=np.uint8)
        idle=image.copy();idle[230:500,390:610]=255
        watch=BackgroundProgress()
        self.assertIsNone(watch.update(image,0))
        self.assertIsNone(watch.update(idle,1.9))
        self.assertEqual(watch.update(idle,2.1),'background_stalled')
        watch=BackgroundProgress()
        watch.update(image,0)
        moved=cv2.warpAffine(image,np.float32([[1,0,8],[0,1,5]]),(960,540))
        self.assertIsNone(watch.update(moved,2.1))
        watch=BackgroundProgress()
        blank=np.zeros_like(image)
        watch.update(blank,0)
        self.assertIsNone(watch.update(blank,2.1))

    def test_equation_preview_rewards_completion_and_ignores_completed_paths(self):
        from autohsr.du_strategy import preview_progress,blessing_score
        page=Scene([t('2>>3/4',.2,.94),t('3→4/4',.4,.94),t('9>>10/4',.6,.94)])
        self.assertEqual(preview_progress(page),(1,1.5))
        page=Scene([t('9/4',.2,.94),t('2/6',.4,.94)])
        self.assertEqual(preview_progress(page),(0,0))
        page=Scene([t('祝福',.25,.45),t('欢愉',.25,.76),t('发牌员行动提前',.25,.60)])
        score,reason=blessing_score(page,page.tokens[0])
        self.assertTrue(reason['dealer'])
        self.assertTrue(reason['elation'])

    def test_forge_upgrade_only_selects_the_explicit_free_target(self):
        page=Scene([t('选择站点卡'),t('指定1个【铸造】区域，使其等级+2',.3,.145),
                    t('抽牌区'),t('铸造',.1,.4),t('确定',.85,.89)])
        self.assertEqual(classify_page(page),'miracle_target')
        guard_differential_universe_click(page,page.tokens[3],intent='miracle_target')
        guard_differential_universe_click(page,page.tokens[4],intent='miracle_target_confirm')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,t('购买',.1,.4),intent='miracle_target')

    def test_imperial_legacy_free_touch_requires_the_observed_reward_description(self):
        page=Scene([t('事件'),t('帝国遗产',.14,.9),t('触摸帝国的遗产。',.8,.33),
                    t('有极低的概率得到遗产的回应：获得300',.8,.37),
                    t('宇宙碎片；获得3个随机祝福',.8,.4),
                    t('接受帝国的遗产。',.8,.55),t('花费300宇宙碎片',.8,.59)])
        guard_differential_universe_click(page,page.tokens[2],intent='event_leave')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,page.tokens[5],intent='event_leave')
        page.tokens[3]=t('花费300宇宙碎片',.8,.37)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,page.tokens[2],intent='event_leave')

    def test_attack_ring_samples_reject_open_gate_and_character_emoji(self):
        import cv2,json
        from pathlib import Path
        from autohsr.du_navigation import attack_reticle
        root=Path(__file__).parent/'fixtures/du_runtime'
        for row in json.loads((root/'attack_rings.json').read_text(encoding='utf-8')):
            with self.subTest(file=row['file']):
                result=attack_reticle(Scene([],cv2.imread(str(root/row['file']))))
                self.assertEqual(result is not None,row['present'])

    def test_sleeping_gate_guides_approach_but_only_ring_authorizes_attack(self):
        import numpy as np
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        context._du_motion_result={}
        flow=DifferentialUniverseWorkflow(context,1)
        far=Scene([t('(7/13) 第二位面-战斗'),t('等级90 惊梦剧团',.5,.05)],np.zeros((540,960,3),np.uint8))
        near=Scene(far.tokens,far.image)
        battle=Scene([t('战斗设置')])
        # The packaged detector deliberately has one pink-door class. The
        # enemy's range ring may be off centre; do not turn and lose its lock.
        goal=Token('Target',.95,(.46,.3,.54,.7))
        ring=Token('差分宇宙已锁定敌方目标',.8,(.60,.36,.64,.42))
        attack=(t('差分宇宙基础攻击',.88,.85),'field_attack')
        flow._field_attack_target=Mock(return_value=attack)
        context.differential_universe_motion.return_value=near
        context.differential_universe_attack.return_value=battle
        flow._observe=Mock(side_effect=lambda page,label:'battle' if page is battle else 'field_combat')
        flow._wait_known=Mock(side_effect=lambda page,kind,label,**kw:(page,kind))
        with patch('autohsr.du_navigation.navigation_targets',return_value=[goal]), \
             patch('autohsr.du_navigation.attack_reticle',side_effect=lambda page:ring if page is near else None):
            self.assertEqual(flow._field_visual(far),(battle,'battle'))
        context.differential_universe_motion.assert_called_once_with(far,'w',3000,profile='engage')
        context.differential_universe_look.assert_not_called()
        context.differential_universe_attack.assert_called_once_with(near,*attack)

    def test_clipped_boss_name_still_exposes_basic_attack_candidate(self):
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        flow._daily._icon=Mock(return_value=(.89,.84))
        page=Scene([t('(9/13) 第二位面-首领'),t('等级52 金人司阍（错...',.5,.05)])
        self.assertEqual(flow._field_attack_target(page)[1],'field_attack')
        page.tokens[1]=t('等级52',.5,.05)
        flow._daily._icon.return_value=None
        ctx.template.return_value=None
        self.assertIsNone(flow._field_attack_target(page))

    def test_aurumaton_bearing_takes_priority_over_door_without_authorizing_attack(self):
        import cv2,json,numpy as np
        from pathlib import Path
        from autohsr.du_navigation import aurumaton_landmark,navigation_targets,attack_reticle
        root=Path(__file__).parent/'fixtures/du_runtime'
        for row in json.loads((root/'boss_aurumaton.json').read_text()):
            image=cv2.imdecode(np.fromfile(root/row['file'],np.uint8),1)
            page=Scene([t('(9/13) 第二位面-首领')],image)
            bosses=aurumaton_landmark(page)
            self.assertEqual(len(bosses),1)
            self.assertAlmostEqual(bosses[0].center[0],row['expected_x'],delta=.02)
            self.assertTrue(any(t.text=='Enemy' for t in navigation_targets(page)))
            self.assertIsNone(attack_reticle(page))
            self.assertEqual(aurumaton_landmark(Scene([],image)),[])
        negative=cv2.imdecode(np.fromfile(root/'gate_city_negative.png',np.uint8),1)
        self.assertEqual(aurumaton_landmark(Scene([t('(9/13) 第二位面-首领')],negative)),[])

    def test_enemy_name_without_world_target_never_authorizes_blind_travel(self):
        import numpy as np
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        flow=DifferentialUniverseWorkflow(context,1)
        page=Scene([t('(7/13) 第二位面-战斗')],np.zeros((540,960,3),np.uint8))
        flow._field_attack_target=Mock(return_value=(t('差分宇宙基础攻击',.88,.85),'field_attack'))
        context.differential_universe_look.return_value=page
        context.differential_universe_motion.return_value=page
        flow._observe=Mock(return_value='field_combat')
        flow._snapshot=Mock(return_value=(page,'field_combat'))
        flow._wait_known=Mock(side_effect=lambda p,k,label,**kw:(p,k))
        flow._find=Mock(return_value=None)
        with patch('autohsr.du_navigation.navigation_targets',return_value=[]), \
             patch('autohsr.du_navigation.attack_reticle',return_value=None):
            with self.assertRaisesRegex(AutomationError,'原地镜头搜索达到上限'):
                flow._field_visual(page)
        self.assertEqual(len(context.differential_universe_motion.call_args_list),2)
        self.assertTrue(all(c.args[1:] == ('scan_right',8000) and c.kwargs=={'profile':'seek'}
                            for c in context.differential_universe_motion.call_args_list))
        context.differential_universe_attack.assert_not_called()

    def test_home_links_and_mode_names_do_not_become_shop_pages(self):
        page=Scene([t(s) for s in ('差分宇宙','乐园漫记','黑塔的商店','开始游戏')])
        self.assertEqual(classify_page(page),'home')
        self.assertEqual(classify_page(Scene([t('1>2',.6,.55),t('事件',.46,.66),t('商店',.62,.66)])),'unknown')
        page=Scene([t(s) for s in ('差分宇宙','模式选择','常规','周期','进行中')])
        self.assertEqual(classify_page(page),'mode_select')

    def test_curio_victory_description_is_not_a_victory_page(self):
        page=Scene([t('差分宇宙'),t('选择奇物',.1,.075),
                    t('换境桂冠',.75,.48),t('而会视为本次战斗胜利并使所有角色恢复生命',.75,.62)])
        self.assertEqual(classify_page(page),'curio_choice')
        page=Scene([t('差分宇宙'),t('选择惊世奇迹',.5,.13),t('强化面具效果',.25,.55),t('确认',.6,.9)])
        self.assertEqual(classify_page(page),'miracle_choice')

    def test_guide_entry_is_bound_to_du_details_and_not_currency_wars(self):
        page=Scene([t('星际和平指南'),t('旷宇纷争'),t('乐园漫记',.75,.38),t('拟合等级',.5,.58)])
        enter=t('前往参与',.78,.815)
        guard_differential_universe_click(page,enter,intent='du_guide_enter')
        page.tokens=[v for v in page.tokens if v.text!='乐园漫记']
        page.tokens.append(t('货币战争',.75,.38))
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,enter,intent='du_guide_enter')

    def test_refill_prompt_overrides_guide_navigation(self):
        page=Scene([t('星际和平指南'),t('补充开拓力',.5,.5)])
        self.assertEqual(classify_page(page),'blocked')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,t('差分宇宙',.22,.44),intent='du_guide_select')

    def test_active_mode_is_not_repeatedly_started(self):
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        flow=DifferentialUniverseWorkflow(context,1)
        page=Scene([t('继续进度',.3,.7)])
        flow._open_differential_universe=Mock(return_value=(page,'mode_select'))
        flow._click=Mock()
        with self.assertRaisesRegex(AutomationError,'进行中'):
            flow._prepare_and_start(page,'mode_select')
        flow._click.assert_not_called()

    def test_timeouts_exclude_pause_and_focus_wait_time(self):
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        context.runner.inactive_duration=20
        flow=DifferentialUniverseWorkflow(context,1)
        with patch('autohsr.differential_universe.time.monotonic',return_value=100):
            flow._check_deadline(0,0,90,'寻找目标')
            context.runner.inactive_duration=0
            with self.assertRaisesRegex(AutomationError,'90秒'):
                flow._check_deadline(0,0,90,'寻找目标')

    def test_attack_transition_waits_without_replaying_input_and_has_a_deadline(self):
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        flow=DifferentialUniverseWorkflow(context,1)
        unknown=Scene([t('弱点')])
        reward=Scene([t('差分宇宙'),t('选择祝福')])
        flow._snapshot=Mock(side_effect=[(unknown,'unknown'),(reward,'blessing_choice')])
        with patch('autohsr.differential_universe.time.monotonic',return_value=0):
            self.assertEqual(flow._wait_known(unknown,'unknown','attack'),(reward,'blessing_choice'))
        context.click.assert_not_called()
        context.differential_universe_attack.assert_not_called()
        with patch('autohsr.differential_universe.time.monotonic',side_effect=[0,31]):
            with self.assertRaisesRegex(AutomationError,'画面过渡等待超过30秒'):
                flow._wait_known(unknown,'unknown','attack')

    def test_bonus_blessing_is_a_new_choice_and_body_text_is_not_the_anchor(self):
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        flow=DifferentialUniverseWorkflow(context,1)
        before=Scene([t('新星爆发',.25,.47),t('无存在者',.5,.47),t('死神骑车来',.75,.47),
                      t('次。',.16,.67),t('确认',.88,.89)])
        bonus=Scene([t('晶体谐振的灯塔',.25,.47),t('活的隐喻',.5,.47),t('昭质既设',.75,.47)])
        self.assertEqual(flow._choice_target(before,'blessing_choice').text,'新星爆发')
        flow._click=Mock(return_value=(before,'blessing_choice'))
        flow._snapshot=Mock(return_value=(bonus,'blessing_choice'))
        self.assertEqual(flow._confirm_choice(before,'blessing_choice'),(bonus,'blessing_choice'))
        self.assertEqual(flow._click.call_count,1)

    def test_bonus_equation_and_elation_path_are_recognized(self):
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        flow=DifferentialUniverseWorkflow(context,1)
        before=Scene([t('还魂医师',.25,.47),t('星星盗贼',.5,.47),t('概念献祭典仪',.75,.47),
                      t('欢愉·巡猎',.5,.75),t('确认',.88,.89)])
        bonus=Scene([t('物理魔法少女',.25,.47),t('肥皂车骑士',.5,.47),t('杀务净',.75,.47)])
        self.assertEqual(flow._choice_target(before,'equation_choice').text,'星星盗贼')
        flow._click=Mock(return_value=(bonus,'equation_choice'))
        flow._snapshot=Mock(return_value=(bonus,'equation_choice'))
        self.assertEqual(flow._confirm_choice(before,'equation_choice'),(bonus,'equation_choice'))
        miracle=Scene([t('万随面具·破',.245,.514),t('强化面具效果，当【超霸王玩偶',.241,.552),
                       t('螃蟹侠',.5,.514),t('模拟做人',.75,.514)])
        self.assertEqual(flow._choice_target(miracle,'miracle_choice').text,'万随面具·破')

    def test_periodic_resume_never_starts_extra_regular_runs(self):
        from autohsr.app import Runner
        with self.assertRaisesRegex(ValueError,'当前 1 局'):
            Runner(Settings(),operation='differential_universe',du_runs=3,
                   du_resume_active=True,du_periodic_rank=5)

    def test_movement_releases_before_a_blocking_pause(self):
        runner=SimpleNamespace(settings=Settings(),report=RunReport(operation='differential_universe'),
                               input_epoch=0,_stop=threading.Event(),_pause=threading.Event(),checkpoint=Mock())
        window=Mock();ctx=Context(runner,window,Mock())
        page=Scene([t('第一位面-战斗')],captured_at=time.monotonic())
        check=ctx._du_held_checkpoint(page)
        check()
        runner._pause.set()
        with self.assertRaises(InputInterrupted):
            check()
        runner.checkpoint.assert_not_called()

    def test_basic_attack_never_moves_cursor_and_releases_on_interruption(self):
        from autohsr.windows import GameWindow
        for interrupted in (False,True):
            window=Mock();check=Mock()
            if interrupted:
                check.side_effect=[None,InputInterrupted('pause')]
            with patch('autohsr.windows.user32.SendInput',return_value=1) as release, \
                 patch('autohsr.windows.time.sleep'):
                if interrupted:
                    with self.assertRaises(InputInterrupted):
                        GameWindow.field_attack(window,None,checkpoint=check)
                else:
                    GameWindow.field_attack(window,None,checkpoint=check)
                window.move.assert_not_called()
                self.assertEqual(window.send.call_args.args[0][0].mi.dwFlags,0x0002)
                self.assertEqual(release.call_args.args[1]._obj.mi.dwFlags,0x0004)

    def test_station_card_counter_does_not_authorize_search_attacks(self):
        page=Scene([t('第一位面-战斗'),t('0/1',.078,.308)])
        attack=t('差分宇宙基础攻击',.875,.875)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,attack,intent='field_search_attack')

    def test_station_combat_cards_are_selected_in_any_column(self):
        for x in (.36,.50,.64):
            page=Scene([t('差分宇宙'),t('选择下一站'),t('选择一张站点卡'),
                        t('战斗',x,.70),t('异常',.5,.7),t('铸造',.64,.7)])
            self.assertEqual(classify_page(page),'station_choice')
            target=DifferentialUniverseWorkflow._station_choice_target(page)
            self.assertEqual(target.text,'战斗')
            guard_differential_universe_click(page,target,intent='station_select')
        page=Scene([t('差分宇宙'),t('选择下一站'),t('选择一张站点卡'),
                    t('精英',.36,.7),t('财富',.5,.7),t('空白',.64,.7)])
        self.assertEqual(classify_page(page),'station_choice')
        self.assertEqual(DifferentialUniverseWorkflow._station_choice_target(page).text,'精英')
        guard_differential_universe_click(page,page.tokens[3],intent='station_select')

    def test_station_with_only_shop_and_forge_can_enter_without_purchasing(self):
        for labels,expected in ((('商店','商店','铸造'),'铸造'),(('商店','商店','商店'),'商店')):
            page=Scene([t('差分宇宙'),t('选择下一站'),t('选择一张站点卡')]+
                       [t(name,x,.70) for name,x in zip(labels,(.36,.50,.64))]+[t('确定',.85,.88)])
            self.assertEqual(classify_page(page),'station_choice')
            target=DifferentialUniverseWorkflow._station_choice_target(page)
            self.assertEqual(target.text,expected)
            guard_differential_universe_click(page,target,intent='station_select')
            guard_differential_universe_click(page,page.tokens[-1],intent='station_confirm')
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(page,t('购买',.5,.7),intent='station_select')

    def test_combat_station_icon_overrides_occluded_label_and_visible_elite(self):
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        context.template.return_value=(.50,.54,.99)
        flow=DifferentialUniverseWorkflow(context,1)
        page=Scene([t('选择下一站'),t('选择一张站点卡',.5,.25),t('精英',.36,.7),t('斗',.5,.7)])
        target,intent=flow._station_target(page)
        self.assertEqual(intent,'station_icon_select')
        guard_differential_universe_click(page,target,intent=intent)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(Scene([]),target,intent=intent)
        context.template.return_value=None
        target,intent=flow._station_target(page)
        self.assertEqual((target.text,intent),('精英','station_select'))

    def test_miracle_deck_page_is_not_a_shop_because_it_contains_shop_cards(self):
        page=Scene([t('差分宇宙'),t('选择站点卡'),t('指定1个区域，使其变为空白',.3,.145),
                    t('抽牌区'),t('商店',.57,.56),t('事件',.23,.56)])
        self.assertEqual(classify_page(page),'miracle_target')
        guard_differential_universe_click(page,page.tokens[-1],intent='miracle_target')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,page.tokens[-2],intent='miracle_target')

    def test_free_shop_card_upgrade_is_a_miracle_target_not_a_purchase(self):
        from autohsr.policy import du_miracle_target_labels
        page=Scene([t('差分宇宙'),t('选择站点卡'),t('抽牌区'),
                    t('指定1个【商店】区域，使其等级+2',.3,.145),t('商店',.23,.56),
                    t('在这个区域中可以消耗宇宙碎片购买祝福奇物和方程',.8,.7),
                    t('确定',.87,.9)])
        self.assertEqual(du_miracle_target_labels(page),('商店',))
        self.assertEqual(classify_page(page),'miracle_target')
        guard_differential_universe_click(page,page.tokens[4],intent='miracle_target')
        guard_differential_universe_click(page,page.tokens[-1],intent='miracle_target_confirm')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(Scene([t('商店')]),page.tokens[4],intent='miracle_target')

    def test_miracle_prefers_combat_or_random_upgrade_over_shop_only_target(self):
        page=Scene([t('选择你的奇迹'),t('寻常奇迹',.25,.45),t('寻常奇迹',.5,.45),t('寻常奇迹',.75,.45),
                    t('指定1个【商店】区域，使其等级+2',.25,.60),
                    t('使随机2个区域等级+1',.5,.60),t('指定1个区域，为其附加1个随机信标',.75,.60)])
        ctx=Mock(settings=Settings(),report=RunReport())
        flow=DifferentialUniverseWorkflow(ctx,1)
        self.assertEqual(flow._choice_target(page,'miracle_choice').center[0],.5)
        page.tokens[-1]=t('指定1个【战斗】区域，使其等级+1',.75,.60)
        self.assertEqual(flow._choice_target(page,'miracle_choice').center[0],.75)

    def test_camera_uses_relative_motion_without_absolute_cursor_warp(self):
        from autohsr.windows import GameWindow, Geometry
        window=Mock();geometry=Geometry(0,0,1920,1080)
        with patch('autohsr.windows.user32.SendInput',return_value=1),patch('autohsr.windows.time.sleep'):
            GameWindow.look(window,.12,0,300,geometry)
        window.move.assert_not_called()
        moves=[call.args[0][0].mi for call in window.send.call_args_list if call.args[0][0].mi.dwFlags==1]
        self.assertEqual(sum(m.dx for m in moves),round(1920*.12))
        self.assertEqual(sum(m.dy for m in moves),0)
        self.assertTrue(all(call.args[0][0].mi.dwFlags==1 for call in window.send.call_args_list))

    def test_truncated_field_label_requires_both_progress_and_hud(self):
        from autohsr.policy import guard_differential_universe_field_input
        page=Scene([t('(1/13) 第 位面-战'),t('Lv1/20')])
        self.assertEqual(classify_page(page),'field_combat')
        guard_differential_universe_field_input(page,action='move_w')
        page.tokens[0]=t('第 位面-战')
        self.assertEqual(classify_page(page),'unknown')
        with self.assertRaises(AutomationError):
            guard_differential_universe_field_input(page,action='move_w')

    def test_gate_landmark_at_different_distances_and_neon_negative(self):
        import json
        from pathlib import Path
        import cv2
        from autohsr.du_navigation import random_gate
        root=Path(__file__).parent/'fixtures/du_runtime'
        for sample in json.loads((root/'gate_samples.json').read_text()):
            with self.subTest(file=sample['file']):
                result=random_gate(Scene([],cv2.imread(str(root/sample['file']))))
                if sample['present']:
                    self.assertIsNotNone(result)
                    self.assertAlmostEqual(result.center[0],sample['x'],delta=.015)
                    self.assertEqual(result.text.endswith('背面'),sample.get('back',False))
                else:
                    self.assertIsNone(result)

    def test_forward_motion_detects_enemy_before_using_gate(self):
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        flow=DifferentialUniverseWorkflow(context,1)
        field=Scene([t('(5/13) 第二位面-战斗')])
        enemy_page=Scene(field.tokens+[t('等级86敌人',.5,.04)])
        reward=Scene([t('差分宇宙'),t('选择祝福')])
        enemy=Token('差分宇宙已锁定敌方目标',.99,(.48,.4,.52,.5))
        flow._find=Mock(return_value=None)
        flow._field_attack_target=Mock(side_effect=lambda page:
            (enemy,'field_target_attack') if page is enemy_page else None)
        flow._observe=Mock(side_effect=lambda page,label:
            'blessing_choice' if page is reward else 'field_combat')
        context.differential_universe_motion.return_value=enemy_page
        context.differential_universe_attack.return_value=reward
        with patch('autohsr.differential_universe.time.monotonic',return_value=0):
            self.assertEqual(flow._field_combat(field),(reward,'blessing_choice'))
        context.differential_universe_motion.assert_called_once_with(field,'w',3000,profile='forward')
        context.differential_universe_move.assert_not_called()
        context.differential_universe_look.assert_not_called()
        context.differential_universe_enter_random_gate.assert_not_called()
        context.differential_universe_attack.assert_called_once_with(enemy_page,enemy,'field_target_attack')

    def test_continuous_input_is_held_during_observation_and_released_on_detection(self):
        from autohsr.windows import GameWindow
        held=threading.Event()
        window=Mock()
        window.send.side_effect=lambda *_:held.set()
        def observe():
            self.assertTrue(held.is_set())
            return 'enemy_label'
        def release(*_):
            held.clear()
            return 1
        with patch('autohsr.windows.user32.SendInput',side_effect=release):
            result=GameWindow.field_motion(window,'w',1000,None,checkpoint=lambda:None,observe=observe)
        self.assertFalse(held.is_set())
        self.assertEqual(result['reason'],'enemy_label')
        self.assertEqual(result['frames'],1)
        self.assertEqual(window.send.call_args.args[0][0].ki.dwFlags,0x8)

    def test_continuous_key_deadline_and_pause_release_even_during_slow_ocr(self):
        from autohsr.windows import GameWindow
        for pause in (False,True):
            with self.subTest(pause=pause):
                held=threading.Event();paused=threading.Event();released=threading.Event()
                window=Mock()
                window.send.side_effect=lambda *_:held.set()
                def release(*_):
                    held.clear();released.set();return 1
                def check():
                    if paused.is_set():
                        raise InputInterrupted('pause')
                def observe():
                    self.assertTrue(held.is_set())
                    if pause:
                        paused.set()
                    self.assertTrue(released.wait(.8),'OCR must not block key release')
                with patch('autohsr.windows.user32.SendInput',side_effect=release):
                    if pause:
                        with self.assertRaises(InputInterrupted):
                            GameWindow.field_motion(window,'w',2000,None,checkpoint=check,observe=observe)
                    else:
                        GameWindow.field_motion(window,'w',140,None,checkpoint=check,observe=observe)
                self.assertFalse(held.is_set())

    def test_continuous_input_releases_if_observer_raises(self):
        from autohsr.windows import GameWindow
        window=Mock()
        with patch('autohsr.windows.user32.SendInput',return_value=1) as release:
            with self.assertRaisesRegex(RuntimeError,'vision'):
                GameWindow.field_motion(window,'w',1000,None,checkpoint=lambda:None,
                                        observe=Mock(side_effect=RuntimeError('vision')))
        self.assertEqual(release.call_args.args[1]._obj.ki.dwFlags,0xA)

    def test_continuous_scan_uses_relative_motion_without_key_or_button(self):
        from autohsr.windows import GameWindow,Geometry
        window=Mock()
        result=GameWindow.field_motion(window,'scan_right',120,Geometry(0,0,1920,1080),
                                       checkpoint=lambda:None,observe=lambda:None)
        self.assertGreater(result['frames'],0)
        self.assertTrue(window.send.called)
        for call in window.send.call_args_list:
            item=call.args[0][0]
            self.assertEqual(item.type,0)
            self.assertEqual(item.mi.dwFlags,1)
        window.move.assert_not_called()

    def test_card_upgrade_miracle_only_selects_combat_cards(self):
        page=Scene([t('选择站点卡'),t('指定1个【战斗】区域，使其等级+2',.3,.145),t('抽牌区'),
                    t('战斗',.23,.56),t('事件',.42,.56),t('确定',.85,.89)])
        self.assertEqual(classify_page(page),'miracle_target')
        guard_differential_universe_click(page,page.tokens[3],intent='miracle_target')
        guard_differential_universe_click(page,page.tokens[-1],intent='miracle_target_confirm')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,page.tokens[4],intent='miracle_target')
        page.tokens[1]=t('指定1个【财富】区域，使其等级+2',.3,.145)
        self.assertEqual(classify_page(page),'miracle_target')
        guard_differential_universe_click(page,t('财富',.23,.56),intent='miracle_target')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,page.tokens[3],intent='miracle_target')

    def test_motion_observer_ignores_camera_background_but_stops_on_page_change(self):
        import json
        from pathlib import Path
        import cv2
        import numpy as np
        from autohsr.du_navigation import FieldMotionWatch
        root=Path(__file__).parent/'fixtures/du_runtime'
        samples=json.loads((root/'field_headers.json').read_text())
        def frame(sample):
            header=cv2.imread(str(root/sample['file']))
            image=np.zeros((2160,3840,3),np.uint8)
            image[round(.008*2160):round(.040*2160),round(.012*3840):round(.19*3840)]=header
            return image
        watch=FieldMotionWatch(Scene([],frame(samples[0])),Mock(),profile='enemy',watch_gate=False)
        for sample in samples:
            with self.subTest(file=sample['file']):
                self.assertEqual(watch(frame(sample)),'field_hud_changed' if sample['stop'] else None)
        # The regional OCR prompt can end a hold before the door disappears.
        vision=Mock();vision.read.return_value=Scene([t('随意门')])
        watch=FieldMotionWatch(Scene([],frame(samples[0])),vision,profile='gate')
        with patch('autohsr.du_navigation.random_gate',return_value=None):
            self.assertEqual(watch(frame(samples[0])),'gate_prompt')

    def test_forced_curio_discard_is_bound_to_current_run_page(self):
        page=Scene([t('丢弃奇物'),t('你需舍弃1次奇物'),t('绝对自灭药膏',.25,.47),t('丢弃',.88,.89)])
        self.assertEqual(classify_page(page),'curio_discard')
        guard_differential_universe_click(page,page.tokens[2],intent='curio_discard_select')
        guard_differential_universe_click(page,page.tokens[3],intent='curio_discard_confirm')
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(Scene([]),page.tokens[3],intent='curio_discard_confirm')

    def test_team_drawer_and_interrupted_result_are_never_start_or_success(self):
        page=Scene([t(s) for s in ('下载角色','角色列表','预设编队','差分宇宙','乐园漫记','难度X','进入星阶模式')])
        self.assertEqual(classify_page(page),'team_selection')
        page=Scene([t(s) for s in ('差分宇宙','分析报告','探索中断','返回主界面')])
        self.assertEqual(classify_page(page),'defeat')

    def test_anomaly_world_event_prompt_is_f_interaction_and_never_a_choice(self):
        from autohsr.policy import guard_differential_universe_field_interact
        page=Scene([t('(3/13) 第一位面-异常'),t('事件',.55,.53),t('219',.19,.46)])
        self.assertEqual(classify_page(page),'field_anomaly')
        target=DifferentialUniverseWorkflow._field_interaction_target(page)
        self.assertEqual(target.text,'事件')
        guard_differential_universe_field_interact(page,target)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,page.tokens[-1],intent='choice')

    def test_brief_emergency_key_tap_is_not_lost_between_frames(self):
        from autohsr.windows import GameWindow
        for state in (1,0x8000,0x8001):
            with patch('autohsr.windows.user32.GetAsyncKeyState',return_value=state):
                self.assertTrue(GameWindow.emergency_pressed())
        with patch('autohsr.windows.user32.GetAsyncKeyState',return_value=0):
            self.assertFalse(GameWindow.emergency_pressed())

    def test_new_run_clears_old_stop_history_but_rejects_held_stop(self):
        from autohsr.app import Runner
        from autohsr.models import Stopped
        runner=Runner(Settings(),lambda event:None)
        with patch('autohsr.windows.user32.GetAsyncKeyState',return_value=1):
            runner._arm_hotkeys()
        self.assertFalse(runner._stop.is_set())
        with patch('autohsr.windows.user32.GetAsyncKeyState',return_value=0x8001):
            with self.assertRaises(Stopped):
                runner._arm_hotkeys()

    def test_anomaly_goes_straight_without_lateral_motion_or_orbit(self):
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        flow=DifferentialUniverseWorkflow(context,1)
        field=Scene([t('(3/13) 第一位面-异常')])
        prompt=Scene(field.tokens+[t('事件',.55,.53)])
        dialog=Scene([t('事件')])
        flow._observe=Mock(side_effect=lambda page,label: 'event' if page is dialog else 'field_anomaly')
        context.differential_universe_motion.return_value=prompt
        context.differential_universe_interact.return_value=dialog
        with patch('autohsr.differential_universe.time.monotonic',return_value=0):
            self.assertEqual(flow._field_anomaly(field),(dialog,'event'))
        context.differential_universe_motion.assert_called_once_with(field,'w',4000,profile='forward')
        context.differential_universe_move.assert_not_called()
        context.differential_universe_look.assert_not_called()
        context.differential_universe_interact.assert_called_once_with(prompt,prompt.tokens[-1])

    def test_event_next_arrow_and_free_leave_are_bound_to_dialog_page(self):
        page=Scene([t('差分宇宙'),t('事件'),t('模拟宇宙',.73,.48),t('商店与合成的介绍',.82,.54)])
        self.assertEqual(classify_page(page),'event')
        arrow=t('事件对话继续',.82,.67)
        guard_differential_universe_click(page,arrow,intent='event_advance')
        leave=t('离开机器',.82,.75)
        guard_differential_universe_click(page,leave,intent='event_leave')
        for bad,intent in ((t('存入5宇宙碎片',.82,.75),'event_leave'),
                           (t('离开并消耗100碎片',.82,.75),'event_leave'),
                           (t('事件对话继续',.25,.67),'event_advance')):
            with self.assertRaises(AutomationError):
                guard_differential_universe_click(page,bad,intent=intent)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(Scene([t('第一位面-异常')]),arrow,intent='event_advance')

    def test_event_loads_text_before_advancing_and_skips_spending_options(self):
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        context.template.side_effect=lambda page,*a,**kw: ((.82,.67,.95)
            if page.has('模拟宇宙',(.68,.15,.99,.85),exact=True) else None)
        flow=DifferentialUniverseWorkflow(context,1)
        loading=Scene([t('差分宇宙'),t('事件')])
        ready=Scene(loading.tokens+[t('模拟宇宙',.73,.48)])
        reward=Scene([t('选择祝福')])
        context.wait.return_value=ready
        flow._click=Mock()
        flow._observe=Mock(side_effect=lambda page,label:'blessing_choice' if page is reward else 'event')
        context.differential_universe_dialogue.return_value=reward
        self.assertEqual(flow._event(loading),(reward,'blessing_choice'))
        context.differential_universe_dialogue.assert_called_once()
        flow._click.assert_not_called()
        context.template.side_effect=None
        context.template.return_value=None
        options=Scene(ready.tokens+[t('存入5宇宙碎片',.82,.6),t('离开机器',.82,.75)])
        target,intent=flow._event_target(options)
        self.assertEqual((target.text,intent),('离开机器','event_leave'))
        selection=Scene(ready.tokens+[t('选择',.82,.68)])
        target,intent=flow._event_target(selection)
        self.assertEqual(intent,'event_open_selection')
        guard_differential_universe_click(selection,target,intent=intent)
        options=Scene(ready.tokens+[t('投资你的信任',.82,.4),t('花费100宇宙碎片',.82,.45),t('不拿。',.76,.54)])
        target,intent=flow._event_target(options)
        self.assertEqual((normalize(target.text),intent),('不拿','event_leave'))
        guard_differential_universe_click(options,target,intent=intent)
        options.tokens[-1]=t('米不拿。',.76,.54)
        target,intent=flow._event_target(options)
        self.assertEqual(target.text,'米不拿。')
        guard_differential_universe_click(options,target,intent=intent)

    def test_dialogue_burst_rechecks_arrow_before_each_click_and_stops_at_choices(self):
        from autohsr.windows import GameWindow
        window=Mock();observe=Mock(side_effect=[(.82,.67),(.82,.67),None])
        result=GameWindow.dialogue_burst(window,None,checkpoint=lambda:None,observe=observe)
        self.assertEqual(result['clicks'],2)
        self.assertEqual(result['reason'],'arrow_hidden')
        self.assertEqual(window.click_held.call_count,2)
        with patch('autohsr.windows.time.monotonic',side_effect=[0,0,5,5]):
            window.reset_mock()
            result=GameWindow.dialogue_burst(window,None,checkpoint=lambda:None,observe=lambda:(.82,.67))
            window.click_held.assert_not_called()
            self.assertEqual(result['clicks'],0)
        with self.assertRaises(InputInterrupted):
            GameWindow.dialogue_burst(window,None,checkpoint=Mock(side_effect=InputInterrupted('pause')),observe=observe)

    def test_event_keeps_advancing_visible_arrow_when_ocr_text_is_unchanged(self):
        page=Scene([t('事件'),t('离开这里。',.82,.6)])
        done=Scene([t('选择祝福')])
        context=Mock(settings=Settings(),report=RunReport())
        context.template.return_value=(.82,.67,.95)
        context.differential_universe_dialogue.side_effect=[page,done]
        flow=DifferentialUniverseWorkflow(context,1)
        flow._observe=Mock(side_effect=['event','blessing_choice'])
        self.assertEqual(flow._event(page),(done,'blessing_choice'))
        self.assertEqual(context.differential_universe_dialogue.call_count,2)
        context.wait.assert_not_called()

    def test_event_confirm_is_bound_to_selected_free_card(self):
        context=Mock(settings=Settings(),report=Mock(differential_universe={}))
        flow=DifferentialUniverseWorkflow(context,1)
        page=Scene([t('事件'),t('米不拿。',.75,.54),t('确定',.89,.625)])
        target,intent=flow._event_target(page)
        self.assertEqual((target.text,intent),('确定','event_confirm'))
        guard_differential_universe_click(page,target,intent=intent)
        with self.assertRaises(AutomationError):
            guard_differential_universe_click(page,t('确定',.89,.43),intent='event_confirm')

    def test_visible_event_arrow_outranks_leave_text_in_dialogue_history(self):
        import cv2,json
        from pathlib import Path
        root=Path(__file__).parent/'fixtures/du_runtime/event_arrow_with_leave_history'
        data=json.loads(root.with_suffix('.json').read_text('utf8'))
        tokens=[Token(v['text'],v['score'],tuple(v['box'])) for v in data['tokens']]
        image=cv2.imread(str(root.with_suffix('.png')))
        context=Mock(settings=Settings(),report=RunReport())
        context.template.return_value=None
        flow=DifferentialUniverseWorkflow(context,1)
        for labels in (tokens,[t for t in tokens if t.text!='模拟宇宙']):
            page=Scene(labels,image)
            target,intent=flow._event_target(page)
            self.assertEqual(intent,'event_advance')
            self.assertAlmostEqual(target.center[0],.822,places=2)
            guard_differential_universe_click(page,target,intent=intent)
        # Once the arrow disappears, current options may be selected normally.
        options=Scene([t('事件'),t('离开这里。',.82,.6)])
        target,intent=flow._event_target(options)
        self.assertEqual((target.text,intent),('离开这里。','event_leave'))

    def test_event_next_arrow_survives_hover_cursor_and_rejects_missing_arrow(self):
        import json
        from pathlib import Path
        import cv2
        import numpy as np
        from autohsr.du_navigation import event_next
        root=Path(__file__).parent/'fixtures/du_runtime'
        for sample in json.loads((root/'event_next.json').read_text()):
            with self.subTest(file=sample['file']):
                image=np.zeros((1080,1920,3),np.uint8)
                image[710:745,1560:1595]=cv2.imread(str(root/sample['file']))
                match=event_next(Scene([],image))
                self.assertIsNotNone(match)
                self.assertAlmostEqual(match[0],1577.5/1920,places=3)
        self.assertIsNone(event_next(Scene([],np.zeros((1080,1920,3),np.uint8))))

    def test_du_battle_controls_match_live_samples_and_read_auto_color(self):
        import json
        from pathlib import Path
        import cv2
        import numpy as np
        from autohsr.du_navigation import auto_state
        from autohsr.vision import Vision
        root=Path(__file__).parent/'fixtures/du_runtime'
        template=Path(__file__).resolve().parents[2]/'assets/templates/du_battle_pause.png'
        vision=Vision.__new__(Vision)
        for sample in json.loads((root/'battle_controls.json').read_text()):
            with self.subTest(file=sample['file']):
                image=np.zeros((1080,1920,3),np.uint8)
                image[:108,1632:1920]=cv2.imread(str(root/sample['file']))
                self.assertIsNotNone(vision.template(Scene([],image),template,(.95,0,1,.1),.88))
                self.assertEqual(auto_state(Scene([],image))[0],'on')
                # An unlit white glyph must be read as off, never as gold.
                white=cv2.cvtColor(cv2.cvtColor(image,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
                self.assertEqual(auto_state(Scene([],white))[0],'off')
        self.assertEqual(auto_state(Scene([],np.zeros((1080,1920,3),np.uint8))),(None,None))

    def test_masked_mouse_hint_matches_real_bright_and_dark_backgrounds(self):
        from pathlib import Path
        import json
        import cv2
        import numpy as np
        from autohsr.vision import Vision
        fixtures=Path(__file__).parent/'fixtures'/'du_runtime'
        samples=json.loads((fixtures/'attack_mouse.json').read_text())['samples']
        vision=Vision.__new__(Vision)
        template=Path(__file__).resolve().parents[2]/'assets/templates/du_attack_mouse.png'
        for sample in samples:
            with self.subTest(file=sample['file']):
                w,h=sample['size'];pixels=np.zeros((h,w,3),np.uint8)
                x1,y1,x2,y2=sample['rect']
                pixels[y1:y2,x1:x2]=cv2.imdecode(np.frombuffer((fixtures/sample['file']).read_bytes(),np.uint8),1)
                match=vision.template(Scene([],pixels),template,(.878,.825,.901,.867),threshold=.88)
                self.assertIsNotNone(match)
                self.assertAlmostEqual(match[0],.88984,places=4)
        self.assertIsNone(vision.template(Scene([],np.zeros((1080,1920,3),np.uint8)),template,(.878,.825,.901,.867),.88))


if __name__=='__main__':
    unittest.main()
