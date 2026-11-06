"""Regular played overview and occupied two-node preparation contracts."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import time
import unittest

import numpy as np

from autohsr.challenge_apocalyptic_prepare import observe
from autohsr.models import Scene
from autohsr.tests.test_challenge_apocalyptic_prepare import APOCALYPTIC_PLAN, UID, frame, text
from autohsr.tests.test_challenge_integration import prepare_with_fake_window
from autohsr.vision import Vision


def overview(*, highlights=(4,)):
    tokens = [
        text('末日幻影', (.052, .048, .107, .076)),
        text('支配遗忘', (.452, .506, .557, .545)),
        text('常规模式', (.488, .675, .541, .703)),
        text('更换编队', (.882, .672, .929, .697)),
        text('节点一', (.367, .747, .406, .779)),
        text('2552', (.450, .762, .496, .798)),
        text('节点二', (.569, .748, .606, .778)),
        text('1278', (.653, .762, .699, .798)),
        text('重新挑战>', (.447, .814, .494, .840)),
        text('重新挑战>', (.650, .815, .699, .840)),
        text('01快速通关', (.210, .882, .283, .913)),
        text('02快速通关', (.359, .882, .431, .914)),
        text('037320', (.505, .882, .575, .915)),
        text('043830', (.655, .881, .724, .915)),
    ]
    image = np.full((1080, 1920, 3), 32, np.uint8)
    for number in highlights:
        x = 390 + 284 * (number - 1)
        image[996:999, x:x + 260] = (174, 220, 246)
    return Scene([*tokens, UID], image, captured_at=time.monotonic())


def setup_with_role_detail():
    scene = frame('node_setup', level='04')
    scene.tokens.append(text('角色详情', (.601, .899, .655, .929)))
    return scene


class RegularPlayedOverviewTests(unittest.TestCase):
    def test_explicit_normal_mode_selected_line_and_split_card_are_all_bound(self):
        scene = overview()
        scene.tokens[-2:-1] = [text('０４', (.655, .881, .679, .915)),
                               text('3830', (.679, .884, .724, .912))]
        page = observe(scene)
        self.assertEqual((page.kind, page.level, page.basis['visible_selected_level']), ('played_overview', 4, 4))
        self.assertEqual(page.basis['visible_node_points'], [2552, 1278])
        self.assertTrue(page.basis['button']['caption_verified'])
        self.assertEqual(page.basis['button']['activation'], 'unknown')
        self.assertEqual(page.targets, ())

    def test_missing_short_or_competing_gold_line_cannot_prove_selection(self):
        for scene in (overview(highlights=()), overview(highlights=(3, 4)), overview(highlights=(3,))):
            self.assertEqual(observe(scene).kind, 'unknown')
        short = overview(highlights=())
        short.image[996:999, 1330:1410] = (174, 220, 246)
        self.assertEqual(observe(short).kind, 'unknown')
        for rows in (slice(994, 1001), slice(986, 995)):
            thick = overview(highlights=())
            thick.image[rows, 1252:1514] = (174, 220, 246)
            self.assertEqual(observe(thick).kind, 'unknown')

    def test_shifted_buttons_wrong_mode_or_inconsistent_points_stay_unknown(self):
        for index, token in (
            (2, text('星启模式', (.488, .675, .541, .703))),
            (3, text('更换编队', (.860, .815, .929, .843))),
            (3, text('更换编队', (.860, .660, .929, .674))),
            (5, text('2553', (.450, .762, .496, .798))),
            (6, text('节点二', (.569, .736, .606, .761))),
            (7, text('1278', (.653, .786, .699, .808))),
            (8, text('重新挑战', (.311, .870, .379, .900), .78)),
        ):
            with self.subTest(token=token):
                scene = overview()
                scene.tokens[index] = token
                self.assertEqual(observe(scene).kind, 'unknown')
        scene = overview()
        scene.tokens.append(text('节点三', (.732, .752, .766, .782), .75))
        self.assertEqual(observe(scene).kind, 'unknown')

    def test_conflicts_partly_outside_the_field_stay_unknown(self):
        for token in (text('1279', (.675, .766, .726, .801), .78),
                      text('043831', (.630, .882, .694, .916), .78),
                      text('尚未挑战', (.699, .886, .752, .913), .77),
                      text('节点二', (.393, .752, .429, .778), .77)):
            with self.subTest(token=token):
                scene = overview()
                scene.tokens.append(token)
                self.assertEqual(observe(scene).kind, 'unknown')

    def test_overlaid_prompts_and_competing_page_titles_veto_background_anchors(self):
        for make_scene in (overview, setup_with_role_detail):
            for token in (text('快速通关', (.450, .160, .550, .190), .74),
                          text('提示', (.478, .373, .524, .402), .74)):
                with self.subTest(scene=make_scene.__name__, token=token):
                    scene = make_scene()
                    scene.tokens.append(token)
                    self.assertEqual(observe(scene).kind, 'unknown')
        scene = overview()
        scene.tokens.append(text('编队', (.053, .057, .082, .090), .74))
        self.assertEqual(observe(scene).kind, 'unknown')

    def test_role_details_are_scoped_to_the_setup_footer_and_clear_warning_vetoes(self):
        scene = setup_with_role_detail()
        page = observe(scene)
        self.assertEqual((page.kind, page.level), ('node_setup', 4))
        self.assertIn('role_detail', page.basis['anchors'])
        self.assertEqual(page.basis['team_feedback'], 'unknown')
        self.assertEqual(page.targets, ())
        scene.tokens[-1] = replace(scene.tokens[-1], box=(.650, .819, .706, .847))
        self.assertEqual(observe(scene).kind, 'unknown')
        scene = setup_with_role_detail()
        scene.tokens.append(text('清空当前挑战队伍', (.376, .425, .628, .462), .74))
        self.assertEqual(observe(scene).kind, 'unknown')

    def test_formal_cli_saves_page_observation_and_same_level_setup_independently(self):
        plan = dict(APOCALYPTIC_PLAN, levels=[4, 4])
        for scene, kind, code_expected in ((overview(), 'played_overview', 1),
                                          (setup_with_role_detail(), 'node_setup', 0)):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as folder:
                code, report, window = prepare_with_fake_window(Path(folder), [scene, scene], plan=plan)
                data = report['challenge']
                page = data['page_observation']
                self.assertEqual((code, page['kind'], page['level']), (code_expected, kind, 4))
                self.assertEqual(data['preparation_page_verified'], code_expected == 0)
                self.assertEqual(data['actions'], [])
                self.assertIsNone(data['selected_level'])
                if kind == 'played_overview':
                    self.assertTrue(page['matches_plan_level'])
                    self.assertEqual(page['visible_selected_level'], 4)
                journal = Path(report['run_dir']) / 'challenge-preparation.json'
                self.assertEqual(json.loads(journal.read_bytes()), data)
                for method in (window.focus, window.click, window.key, window.send, window.drag):
                    method.assert_not_called()

    def test_formal_cli_retains_mode_counterevidence_below_the_collection_threshold(self):
        first, second = overview(), overview()
        second.tokens.append(text('星启模式', (.705, .624, .759, .651), .74))
        self.assertEqual(observe(second, .80).kind, 'unknown')
        batches = iter((first.tokens, second.tokens))

        def engine(_image, *, use_cls):
            raw = []
            for token in next(batches):
                left, top, right, bottom = token.box
                corners = ((left, top), (right, top), (right, bottom), (left, bottom))
                box = [(x * 1920, y * 1080) for x, y in corners]
                raw.append((box, token.text, token.score))
            return raw, None

        vision = Vision.__new__(Vision)
        vision.confidence, vision.engine = .80, engine
        with tempfile.TemporaryDirectory() as folder:
            code, report, window = prepare_with_fake_window(Path(folder), [first, second],
                plan=dict(APOCALYPTIC_PLAN, levels=[4, 4]), vision=vision, confidence=.80)
        self.assertEqual(code, 1)
        self.assertEqual(len(report['challenge']['observations']), 1)
        self.assertNotIn('page_observation', report['challenge'])
        for method in (window.focus, window.click, window.key, window.send, window.drag):
            method.assert_not_called()
