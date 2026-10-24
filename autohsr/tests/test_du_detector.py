"""ONNX coordinate and class decoding regressions, without sending game input."""
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from autohsr.du_detector import decode,detect
from autohsr.models import Scene


class DuDetectorTests(unittest.TestCase):
    def test_night_exit_training_replay_retains_bearing_through_avatar_occlusion(self):
        from autohsr.tests.test_du_team import fixture
        from tools.evaluate_du_detector import overlap
        import json
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('night_exit_reference','night_exit_occluded','night_exit_return_view'):
            with self.subTest(name=name):
                expected=json.loads((root/(name+'.json')).read_text('utf8'))['box']
                found=detect(fixture(name))
                self.assertEqual(len(found),1)
                self.assertEqual(found[0].text,'Target')
                self.assertGreaterEqual(overlap(found[0].box,expected),.5)

    def test_clipped_enemy_boxes_do_not_supply_bearings_or_reappear_in_exit_navigation(self):
        from autohsr.du_detector import detect_enemies
        from autohsr.du_navigation import navigation_targets
        from autohsr.models import Token
        valid=Token('Enemy',.9,(.3,.2,.7,.85))
        gate=Token('Target',.9,(.45,.2,.55,.5))
        for box in ((.533,0,1,.445),(.533,.02,.99,.445),(0,.2,.4,.7),(.3,.2,1,.7),(.3,.2,.7,1)):
            clipped=Token('Enemy',.93,box)
            with patch('autohsr.du_detector._detect',return_value=[clipped,valid]):
                self.assertEqual(detect_enemies(Scene([])),[valid])
            with patch('autohsr.du_detector.detect',return_value=[clipped,gate]), \
                 patch('autohsr.du_detector.detect_enemies',return_value=[]), \
                 patch('autohsr.du_navigation.random_gate',return_value=None):
                self.assertEqual(navigation_targets(Scene([])),[gate])
        with patch('autohsr.du_detector.detect',return_value=[valid,gate]):
            self.assertEqual(navigation_targets(Scene([]),enemies=False),[gate])

    def test_recovery_model_supplies_side_enemy_bearings_and_rejects_corner_avatar(self):
        import cv2,json
        from autohsr.du_detector import detect_recovery_enemies
        from tools.evaluate_du_detector import overlap
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('enemy_pair_front','enemy_yellow_side','enemy_corner_negative'):
            with self.subTest(name=name):
                expected=json.loads((root/f'{name}.json').read_text('utf8'))['boxes']
                found=detect_recovery_enemies(Scene([],cv2.imread(str(root/f'{name}.png'))))
                self.assertEqual(len(found),len(expected))
                for box in expected:
                    self.assertTrue(any(overlap(t.box,box['xyxy'])>=.5 for t in found))

    def test_close_winged_training_replay_supplies_a_bearing_after_device_occlusion(self):
        import cv2,json
        from autohsr.du_detector import detect_recovery_enemies
        from tools.evaluate_du_detector import overlap
        root=Path(__file__).parent/'fixtures/du_runtime'
        for i in range(3):
            name=f'enemy_close_winged_{i}'
            expected=json.loads((root/f'{name}.json').read_text('utf8'))['boxes'][0]['xyxy']
            found=detect_recovery_enemies(Scene([],cv2.imread(str(root/f'{name}.png'))))
            self.assertEqual(len(found),1)
            self.assertGreaterEqual(overlap(found[0].box,expected),.5)

    def test_two_card_room_and_edge_on_green_card_keep_their_bearings(self):
        import cv2,json
        from autohsr.du_detector import detect_cards
        from tools.evaluate_du_detector import overlap
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('two_cards_at_entry','card_green_edge_on','card_green_edge_on_pitched'):
            with self.subTest(name=name):
                expected=json.loads((root/(name+'.json')).read_text('utf8'))['boxes']
                found=detect_cards(Scene([],cv2.imread(str(root/(name+'.png')))))
                self.assertEqual(len(found),len(expected))
                for box in expected:
                    self.assertTrue(any(overlap(t.box,box['xyxy'])>=.5 for t in found))

    def test_console_occluded_door_supplies_bearing_without_claiming_open_face(self):
        import cv2
        from autohsr.du_navigation import random_gate,navigation_targets
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('encounter_synthesis_field','encounter_door_occluded_near'):
            with self.subTest(name=name):
                page=Scene([],cv2.imread(str(root/(name+'.png'))))
                found=detect(page)
                self.assertEqual(len(found),1)
                self.assertEqual(found[0].text,'Target')
                self.assertIsNone(random_gate(page,fast=True))
                self.assertTrue(navigation_targets(page,enemies=False))

    def test_pink_brush_and_cafe_signs_are_neither_gates_nor_cards(self):
        import cv2
        from autohsr.du_detector import detect_cards
        from autohsr.du_navigation import random_gate
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('pink_brush_false_gate','brush_and_cafe_sign'):
            with self.subTest(name=name):
                page=Scene([],cv2.imread(str(root/(name+'.png'))))
                self.assertEqual(detect(page),[])
                self.assertEqual(detect_cards(page),[])
                self.assertIsNone(random_gate(page,fast=True))

    def test_true_world_card_survives_beside_distracting_advertisement(self):
        import cv2
        from autohsr.du_detector import detect_cards
        page=Scene([],cv2.imread(str(Path(__file__).parent/'fixtures/du_runtime/card_with_advertisement.png')))
        found=detect_cards(page)
        self.assertEqual(len(found),1)
        self.assertGreater(found[0].center[0],.7)

    def test_blue_maintenance_card_is_a_bearing_and_banners_are_not(self):
        import cv2
        from autohsr.du_detector import detect_cards
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name,center in (('card_blue_forge_distant',.38),('card_blue_forge_close',.23),
                            ('card_blue_banner_negative',None),('card_boss_console_negative',None)):
            with self.subTest(name=name):
                found=detect_cards(Scene([],cv2.imread(str(root/(name+'.png')))))
                self.assertEqual(len(found),0 if center is None else 1)
                if center is not None:
                    self.assertLess(abs(found[0].center[0]-center),.05)

    def test_winged_elite_bearing_when_it_occludes_the_sleeping_door(self):
        import cv2,json
        from autohsr.du_detector import detect_enemies
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('enemy_winged_front','enemy_winged_center','enemy_winged_side','enemy_winged_hud'):
            with self.subTest(name=name):
                expected=json.loads((root/f'{name}.json').read_text('utf8'))['boxes'][0]['xyxy']
                found=detect_enemies(Scene([],cv2.imread(str(root/f'{name}.png'))))
                self.assertEqual(len(found),1)
                self.assertLess(abs(found[0].center[0]-(expected[0]+expected[2])/2),.06)

    def test_awake_exit_prevents_background_enemy_bearing_after_clear(self):
        import cv2
        from autohsr.du_navigation import navigation_targets
        page=Scene([],cv2.imread(str(Path(__file__).parent/'fixtures/du_runtime/gate_awake_ornament.png')))
        with patch('autohsr.du_detector.detect_enemies',side_effect=AssertionError('cleared room does not seek enemies')):
            targets=navigation_targets(page)
        self.assertTrue(targets)
        self.assertTrue(all(t.text=='Target' for t in targets))

    def test_dew_enemy_bearing_after_entry_door_disappears(self):
        import cv2,json
        from autohsr.du_detector import detect_enemies
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('enemy_dew_clear','enemy_dew_center','enemy_dew_front'):
            expected=json.loads((root/f'{name}.json').read_text(encoding='utf8'))['boxes'][0]['xyxy']
            found=detect_enemies(Scene([],cv2.imread(str(root/f'{name}.png'))))
            self.assertEqual(len(found),1)
            self.assertLess(abs(found[0].center[0]-(expected[0]+expected[2])/2),.06)

    def test_celestial_bearing_after_spawn_effects_clear(self):
        import cv2,json
        from autohsr.du_detector import detect_enemies
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('enemy_celestial_clear','enemy_celestial_center'):
            expected=json.loads((root/f'{name}.json').read_text(encoding='utf8'))['boxes'][0]['xyxy']
            found=detect_enemies(Scene([],cv2.imread(str(root/f'{name}.png'))))
            self.assertEqual(len(found),1)
            self.assertLess(abs(found[0].center[0]-(expected[0]+expected[2])/2),.06)

    def test_arbiter_bearing_with_progress_banner_occlusion(self):
        import cv2,json
        from autohsr.du_detector import detect_enemies
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('boss_arbiter_clear','boss_arbiter_center','boss_arbiter_occluded'):
            with self.subTest(name=name):
                expected=json.loads((root/f'{name}.json').read_text(encoding='utf8'))['boxes'][0]['xyxy']
                found=detect_enemies(Scene([],cv2.imread(str(root/f'{name}.png'))))
                self.assertEqual(len(found),1)
                self.assertLess(abs(found[0].center[0]-(expected[0]+expected[2])/2),.07)

    def test_distant_rest_door_uses_face_corroboration_without_global_threshold_drop(self):
        import cv2
        from autohsr.du_navigation import navigation_targets
        from autohsr.models import Token
        root=Path(__file__).parent/'fixtures/du_runtime'
        page=Scene([],cv2.imread(str(root/'gate_rest_distant.png')))
        found=navigation_targets(page,enemies=False)
        self.assertEqual(len(found),1)
        self.assertEqual(found[0].text,'Target')
        self.assertLess(abs(found[0].center[0]-.48),.03)
        low=Token('Target',.4,(.45,.20,.51,.36))
        for unrelated in (Token('差分宇宙随意门外观',.95,(.7,.2,.8,.3)),
                          Token('差分宇宙随意门外观',.95,(.40,.19,.55,.40))):
            with patch('autohsr.du_detector.detect',side_effect=[[],[low]]), \
                 patch('autohsr.du_navigation.random_gate',return_value=unrelated):
                self.assertEqual(navigation_targets(page,enemies=False),[])

    def test_avatar_in_front_of_wall_is_not_an_enemy_bearing(self):
        import cv2
        from autohsr.du_detector import detect_enemies
        root=Path(__file__).parent/'fixtures/du_runtime'
        self.assertEqual(detect_enemies(Scene([],cv2.imread(str(root/'enemy_avatar_negative.png')))),[])

    def test_large_close_enemy_is_not_removed_for_overlapping_avatar_centre(self):
        from autohsr.du_detector import detect_enemies
        from autohsr.models import Token
        enemy=Token('Enemy',.9,(.30,.20,.70,.85))
        with patch('autohsr.du_detector._detect',return_value=[enemy]):
            self.assertEqual(detect_enemies(Scene([])),[enemy])

    def test_griffin_bearing_survives_avatar_occlusion(self):
        import cv2,json
        from autohsr.du_detector import detect_enemies
        from tools.evaluate_du_detector import overlap
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('boss_griffin_clear','boss_griffin_center','boss_griffin_occluded'):
            with self.subTest(name=name):
                expected=json.loads((root/f'{name}.json').read_text(encoding='utf8'))['boxes'][0]['xyxy']
                found=detect_enemies(Scene([],cv2.imread(str(root/f'{name}.png'))))
                self.assertEqual(len(found),1)
                self.assertEqual(found[0].text,'Enemy')
                self.assertGreater(overlap(found[0].box,expected),.5)

    def test_ipc_boss_is_detected_through_player_and_hud_occlusion(self):
        import cv2,json
        from autohsr.du_detector import detect_enemies
        from tools.evaluate_du_detector import overlap
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name in ('boss_ipc_front','boss_ipc_clear','boss_ipc_occluded'):
            with self.subTest(name=name):
                expected=json.loads((root/f'{name}.json').read_text(encoding='utf8'))['boxes'][0]['xyxy']
                found=detect_enemies(Scene([],cv2.imread(str(root/f'{name}.png'))))
                self.assertEqual(len(found),1)
                self.assertEqual(found[0].text,'Enemy')
                self.assertGreater(overlap(found[0].box,expected),.5)

    def test_world_card_model_finds_front_back_and_gold_but_rejects_wall_posters(self):
        import cv2
        from autohsr.du_detector import detect_cards
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name,centers in (('event_card_front.png',[.39]),('event_card_back.png',[.55]),
                             ('card_cyan_frame.png',[.296]),('cards_reward_gold.png',[.378,.579]),
                             ('cards_poster_negative.png',[])):
            with self.subTest(file=name):
                found=detect_cards(Scene([],cv2.imread(str(root/name))))
                self.assertIsNotNone(found)
                self.assertEqual(len(found),len(centers))
                for center in centers:
                    self.assertTrue(any(t.text=='Card' and abs(t.center[0]-center)<.05 for t in found))

    def test_learned_card_absence_does_not_fall_back_to_artwork_heuristics(self):
        from autohsr.du_navigation import event_targets
        from autohsr.models import AutomationError
        with patch('autohsr.du_detector.detect_cards',return_value=[]), \
             patch('autohsr.du_navigation.event_cards',side_effect=AssertionError('false artwork fallback')):
            self.assertEqual(event_targets(Scene([],np.zeros((540,960,3),np.uint8))),[])
        with patch('autohsr.du_detector.detect_cards',return_value=None):
            with self.assertRaisesRegex(AutomationError,'缺少场景卡牌模型'):
                event_targets(Scene([],np.zeros((540,960,3),np.uint8)))

    def test_gold_background_does_not_merge_away_three_star_rarity(self):
        import cv2
        from autohsr.du_strategy import rarity
        path=Path(__file__).parent/'fixtures/du_runtime/gold_blessing_stars.png'
        page=Scene([],cv2.imread(str(path)))
        self.assertEqual([rarity(page,x) for x in (.25,.5,.75)],[3,3,3])

    def test_packaged_detector_finds_full_and_clipped_doors_but_not_posters(self):
        import cv2
        root=Path(__file__).parent/'fixtures/du_runtime'
        for number,center in ((220,.46),(230,.89),(223,None)):
            with self.subTest(frame=number), patch.dict('os.environ',{},clear=True):
                result=detect(Scene([],cv2.imread(str(root/f'detector_{number}.png'))))
                self.assertIsNotNone(result)
                if center is None:
                    self.assertEqual(result,[])
                else:
                    self.assertEqual(result[0].text,'Target')
                    self.assertLess(abs(result[0].center[0]-center),.06)

    def test_event_card_front_back_and_fast_interaction_hint(self):
        import cv2
        from autohsr.du_navigation import event_cards,interaction_hint
        root=Path(__file__).parent/'fixtures/du_runtime'
        for name,x in (('event_card_front.png',.39),('event_card_back.png',.55)):
            result=event_cards(Scene([],cv2.imread(str(root/name))))
            self.assertTrue(result,name)
            self.assertLess(abs(result[0].center[0]-x),.07)
        self.assertTrue(interaction_hint(cv2.imread(str(root/'interaction_hint.png'))))
        self.assertFalse(interaction_hint(cv2.imread(str(root/'detector_230.png'))))

    def test_letterbox_is_removed_and_overlapping_boxes_are_suppressed(self):
        predictions=np.array([[[320,320,160,80,.9],
                               [322,320,160,80,.8],
                               [100,320,40,40,.4]]],dtype=np.float32).transpose(0,2,1)
        result=decode(predictions,1280,720,640,.5,(0,140),names=('Target',))
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].text,'Target')
        np.testing.assert_allclose(result[0].box,(.375,280/720,.625,440/720))

    def test_class_channels_and_edge_clipping(self):
        predictions=np.array([[[0,320,160,80,.1,.95,.1],
                               [500,320,40,40,.1,.1,.9]]],dtype=np.float32)
        result=decode(predictions,1280,720,640,.5,(0,140))
        self.assertEqual([t.text for t in result],['GateLocked','Enemy'])
        self.assertEqual(result[0].box[0],0)

    def test_missing_model_is_distinct_from_no_detection(self):
        with patch('autohsr.du_detector.model_path',return_value=Path('missing-du-model.onnx')):
            self.assertIsNone(detect(Scene([],np.zeros((540,960,3),np.uint8))))

    def test_native_header_crop_recovers_missed_full_frame_text(self):
        import cv2
        from autohsr.vision import Vision
        from autohsr.differential_universe import classify_page
        from autohsr.models import Token
        from autohsr.policy import guard_differential_universe_field_input
        crop=cv2.imread(str(Path(__file__).parent/'fixtures/du_runtime/field_header_ocr.png'))
        value=Vision()._read_field(crop,r'.*(?:[1-9]|1[0-3])/13[)）]?第[一二三四五六1-6]位面[-—]?(?:战斗|精英|首领|异常).*')
        self.assertIsNotNone(value)
        scene=Scene([Token(value.text,value.score,(.015,.012,.17,.04))])
        self.assertEqual(classify_page(scene),'field_combat')
        guard_differential_universe_field_input(scene,action='test')


if __name__=='__main__':
    unittest.main()
