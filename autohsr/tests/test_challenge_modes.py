"""Original-crop composites for the two modes, plus a real redacted wrong page."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr import challenge_pages as pages
from autohsr.config import Settings
from autohsr.models import AutomationError, InputInterrupted, Scene, Token
from autohsr.tests import test_challenge_prepare as preparation
from autohsr.tests.test_challenge_pages import lobby_scene as chaos_lobby, paste, token


def blank_page():
    return Scene([], np.full((1080, 1920, 3), 12, np.uint8), captured_at=time.monotonic())


def fiction_lobby(*, shared_strip=False):
    scene = blank_page()
    paste(scene.image, 'fiction_title', 55, 60)
    scene.tokens.append(token('虚构叙事', (78, 61, 161, 82)))
    shape = cv2.cvtColor(pages._references()['fiction_star'][0], cv2.COLOR_BGR2GRAY) > 127
    labels = [(1, 625, 445), (2, 810, 510), (4, 1010, 565)]
    if shared_strip:
        labels[0] = (1, 740, 530)
    for level, x, y in labels:
        scene.tokens.append(token(f'{level:02}', (x, y, x + 34, y + 29)))
        for offset in {1: (), 2: (12, 36), 4: (12, 36, 60)}[level]:
            patch = scene.image[y + 54:y + 67, x + offset:x + offset + 13]
            patch[shape] = (95, 198, 255)
    return scene


def fiction_setup(level=2):
    scene = blank_page()
    paste(scene.image, 'team1', 650, 572)
    paste(scene.image, 'team2', 650, 790)
    paste(scene.image, 'reset', 1240, 490)
    # The full page need not have the lobby title.
    box = paste(scene.image, 'fiction_caption', 1680, 975)
    scene.tokens.append(token('进入故事', box))
    if level is not None:
        scene.tokens.append(token(f'第{level:02}层', (810, 150, 935, 180)))
    return scene


def layer_parts(words, *, x=810, y=150, score=.99):
    parts = []
    for word in words:
        right = x + 18 * len(word)
        parts.append(token(word, (x, y, right, y + 30), score=score))
        x = right + 4
    return parts


def apocalypse_lobby():
    scene = blank_page()
    paste(scene.image, 'apocalyptic_title', 67, 42)
    scene.tokens.extend([token('末日幻影', (119, 59, 216, 85)),
                         token('01', (630, 340, 662, 365)),
                         token('02', (950, 440, 982, 465))])
    return scene


def apocalypse_setup():
    scene = blank_page()
    paste(scene.image, 'reset', 1320, 127)
    scene.tokens.extend([token('节点一', (990, 270, 1070, 297)),
                         token('节点二', (995, 537, 1075, 564)),
                         token('前往挑战', (1680, 973, 1820, 1006))])
    return scene


class ChallengeModePageTests(unittest.TestCase):
    def test_fiction_lobby_binds_distinct_level_star_strips_without_a_selected_level(self):
        scene = fiction_lobby()
        observation = pages.observe(scene)
        self.assertEqual((observation.kind, observation.mode, observation.level), ('lobby', 'pure_fiction', None))
        rows = observation.basis['levels']
        self.assertEqual([(row['level'], row['stars'], row['available']) for row in rows],
                         [(1, None, None), (2, 2, None), (4, 3, None)])
        self.assertEqual([token.text for intent, token in observation.targets if intent == 'select_level'], ['02', '04'])
        self.assertEqual(pages.target(scene, 'select_level', level=2).text, '02')
        self.assertIsNone(pages.target(scene, 'select_level', level=1))
        self.assertIsNone(pages.target(scene, 'start', level=2))

    def test_fiction_foreign_dialog_duplicate_and_shared_strips_cannot_supply_targets(self):
        for word in ('开启故事', '选择最高解锁关卡', '未解锁', '末日幻影'):
            with self.subTest(word=word):
                scene = fiction_lobby()
                scene.tokens.append(token(word, (740, 220, 1010, 270), score=.80))
                self.assertIsNone(pages.target(scene, 'select_level', level=2))
        scene = fiction_lobby()
        scene.tokens.append(token('02', (1250, 410, 1300, 450), score=.80))
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        shared = pages.observe(fiction_lobby(shared_strip=True))
        self.assertEqual([token.text for _, token in shared.targets], ['04'])
        scene = fiction_lobby()
        scene.tokens[1] = token('01', (765, 430, 870, 525))
        self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_fiction_split_or_unread_overlay_and_split_foreign_mode_veto_the_lobby(self):
        scene = fiction_lobby()
        scene.tokens.extend([token('选择最高解锁', (740, 220, 900, 255), score=.80),
                             token('关卡', (905, 220, 956, 255), score=.80)])
        self.assertIsNone(pages.target(scene, 'select_level', level=2))
        scene = fiction_lobby()
        paste(scene.image, 'fiction_modal', 890, 610)
        self.assertIsNone(pages.target(scene, 'select_level', level=2))
        scene = fiction_lobby()
        paste(scene.image, 'apocalyptic_title', 275, 42)
        scene.tokens.extend([token('末日', (326, 59, 371, 85), score=.80),
                             token('幻影', (374, 59, 423, 85), score=.80)])
        self.assertIsNone(pages.target(scene, 'select_level', level=2))

    def test_fiction_requires_original_title_and_complete_ocr_for_lobby(self):
        scene = fiction_lobby()
        scene.tokens[0] = token('叙事', (122, 61, 160, 82))
        self.assertIsNone(pages.target(scene, 'select_level', level=2))
        scene.tokens.append(token('虚构', (78, 61, 117, 82)))
        self.assertIsNotNone(pages.target(scene, 'select_level', level=2))
        scene.image[60:83, 55:161] = 12
        self.assertIsNone(pages.target(scene, 'select_level', level=2))

    def test_fiction_setup_keeps_layer_and_character_evidence_independent(self):
        scene = fiction_setup(None)
        scene.tokens.append(token('02', (810, 150, 935, 180)))
        observed = pages.observe(scene)
        self.assertEqual((observed.kind, observed.mode, observed.level, observed.half),
                         ('team_setup', 'pure_fiction', None, None))
        self.assertEqual(observed.targets, ())
        verified = pages.observe(fiction_setup(4))
        self.assertEqual(verified.level, 4)
        self.assertEqual(verified.basis['team_feedback'], 'unknown')
        self.assertEqual(verified.basis['role_availability'], 'unknown')
        self.assertEqual(verified.basis['slot_feedback'], 'unknown')
        self.assertFalse(verified.basis['execution_supported'])
        self.assertEqual(pages.observe(fiction_setup(5)).kind, 'unknown')
        duplicate = fiction_setup()
        duplicate.tokens.append(token('第03层', (1100, 150, 1250, 180), score=.80))
        self.assertEqual(pages.observe(duplicate).kind, 'unknown')
        list_caption = fiction_setup(None)
        list_caption.tokens.append(token('第02层', (35, 150, 155, 180)))
        self.assertIsNone(pages.observe(list_caption).level)

    def test_fiction_setup_reads_a_single_contiguous_split_header(self):
        for words in (('第', '02', '层'), ('第0', '2层'), ('第', '0', '2', '层')):
            with self.subTest(words=words):
                scene = fiction_setup(None)
                fragments = layer_parts(words)
                scene.tokens.extend(reversed(fragments))
                result = pages.observe(scene)
                self.assertEqual((result.kind, result.level), ('team_setup', 2))
                self.assertEqual(result.basis['level_box'],
                                 [fragments[0].box[0], fragments[0].box[1],
                                  fragments[-1].box[2], fragments[-1].box[3]])

    def test_fiction_setup_reads_fullwidth_and_mixed_width_decimal_headers(self):
        for words in (('第０４层',), ('第０', '4层'), ('第', '0', '４', '层')):
            with self.subTest(words=words):
                scene = fiction_setup(None)
                scene.tokens.extend(layer_parts(words))
                result = pages.observe(scene)
                self.assertEqual((result.kind, result.level), ('team_setup', 4))

    def test_fiction_setup_does_not_pair_partial_or_weak_headers(self):
        variants = [
            layer_parts(('第', '02', '层'), x=1835),
            layer_parts(('第', '02')) + layer_parts(('层',), x=876, y=189),
            layer_parts(('第', '02')) + layer_parts(('层',), x=1000),
            layer_parts(('第', '02')) + layer_parts(('层',), x=872, score=.81),
        ]
        for fragments in variants:
            with self.subTest(fragments=fragments):
                scene = fiction_setup(None)
                scene.tokens.extend(fragments)
                result = pages.observe(scene)
                self.assertEqual((result.kind, result.level), ('team_setup', None))
                self.assertNotIn('level_box', result.basis)

    def test_fiction_setup_requires_a_unique_header_even_with_matching_digits(self):
        for digits, x, score in (('03', 948, .81), ('05', 948, .99), ('02', 948, .99), ('02', 810, .99),
                                 ('０４', 948, .81), ('０２', 948, .99)):
            with self.subTest(digits=digits, x=x, score=score):
                scene = fiction_setup()
                scene.tokens.extend(layer_parts(('第', digits, '层'), x=x, score=score))
                result = pages.observe(scene)
                self.assertEqual(result.kind, 'unknown')
                self.assertEqual(result.targets, ())

    def test_fiction_caption_without_two_headers_is_not_team_setup(self):
        scene = fiction_setup()
        scene.image[790:842, 650:678] = 12
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = fiction_setup()
        scene.image[975:1007, 1680:1788] //= 2
        self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_apocalyptic_detail_is_read_only_and_requires_local_change_team_evidence(self):
        scene = apocalypse_lobby()
        lobby = pages.observe(scene)
        self.assertEqual((lobby.kind, lobby.mode, lobby.level, lobby.targets), ('lobby', 'apocalyptic_shadow', None, ()))
        scene.tokens.append(token('前往挑战', (1690, 815, 1820, 843)))
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene.tokens[-1] = token('更换编队', (1190, 815, 1320, 843))
        self.assertEqual(pages.observe(scene).kind, 'lobby')
        scene.tokens[-1] = token('更换编队', (1690, 815, 1820, 843))
        detail = pages.observe(scene)
        self.assertEqual((detail.kind, detail.mode, detail.level, detail.targets),
                         ('level_detail', 'apocalyptic_shadow', None, ()))
        self.assertIsNone(pages.target(scene, 'select_level', level=2))
        scene.tokens[-1] = token('更换编队', (1690, 815, 1820, 843), score=.80)
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene.tokens[-1] = token('前往挑战', (1690, 815, 1820, 843), score=.80)
        self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_apocalyptic_detail_rejects_local_conflicting_action_captions(self):
        variants = [
            [token('前往挑战', (1775, 815, 1879, 843), score=.81)],
            [token('前往', (1775, 815, 1824, 843), score=.82),
             token('挑战', (1827, 815, 1879, 843), score=.78)],
        ]
        for captions in variants:
            with self.subTest(captions=captions):
                scene = apocalypse_lobby()
                scene.tokens.append(token('更换编队', (1650, 814, 1750, 841)))
                scene.tokens.extend(captions)
                result = pages.observe(scene)
                self.assertEqual((result.kind, result.targets), ('unknown', ()))
        scene = apocalypse_lobby()
        scene.tokens.extend([token('更换编队', (1650, 814, 1750, 841)),
                             token('前往挑战', (1200, 815, 1310, 842), score=.81)])
        self.assertEqual(pages.observe(scene).kind, 'level_detail')

    def test_apocalyptic_two_nodes_are_not_a_selected_node_or_current_level(self):
        scene = apocalypse_setup()
        observed = pages.observe(scene)
        self.assertEqual((observed.kind, observed.mode, observed.level, observed.half, observed.targets),
                         ('node_setup', 'apocalyptic_shadow', None, None, ()))
        self.assertEqual([row['node'] for row in observed.basis['nodes']], [1, 2])
        self.assertIsNone(observed.basis['selected_node'])
        self.assertEqual(observed.basis['slot_feedback'], 'unknown')
        self.assertIsNone(pages.target(scene, 'start', level=2))
        scene.tokens.pop(1)
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = apocalypse_setup()
        scene.image[127:153, 1320:1344] = 12
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = apocalypse_setup()
        scene.tokens.append(token('节点二', (1150, 546, 1230, 571), score=.80))
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = apocalypse_setup()
        scene.tokens.append(token('前往节点二', (1340, 946, 1450, 981), score=.80))
        self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_unavailable_fiction_asset_cannot_break_legacy_moc_or_allow_selection(self):
        scene = fiction_lobby()
        with tempfile.TemporaryDirectory() as folder:
            references = Path(folder) / 'references'
            shutil.copytree(pages.ASSET_ROOT, references, ignore=shutil.ignore_patterns('start_story.png'))
            with patch.object(pages, 'ASSET_ROOT', references):
                pages._references.cache_clear()
                try:
                    self.assertIsNone(pages.target(scene, 'select_level', level=2))
                    self.assertIsNotNone(pages.target(chaos_lobby(), 'select_level', level=2))
                finally:
                    pages._references.cache_clear()

    def test_public_redacted_planar_roster_is_a_real_wrong_page(self):
        fixture = Path(__file__).parent / 'fixtures/du_runtime/planar_preset_enabled'
        data = json.loads(fixture.with_suffix('.json').read_text(encoding='utf-8'))
        raw = fixture.with_suffix('.png').read_bytes()
        self.assertTrue(data['masked_identifiers'])
        self.assertEqual(hashlib.sha256(raw).hexdigest(), data['sha256'])
        scene = Scene([Token(**row) for row in data['tokens']],
                      cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR), captured_at=time.monotonic())
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        self.assertIsNone(pages.target(scene, 'select_level', level=2))


class FictionPreparationTests(unittest.TestCase):
    def context(self, folder, scenes):
        c = preparation.context(folder, scenes)
        c.settings = Settings(challenge_plan=dict(preparation.PLAN, mode='pure_fiction', levels=[2, 4]))
        return c

    def test_explicit_fiction_plan_selects_once_and_saves_same_level_feedback(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.context(folder, [fiction_lobby(), fiction_lobby(), fiction_setup(), fiction_setup()])
            with patch('autohsr.challenge_roster.observe_candidates', return_value={'availability': 'unknown'}) as scan:
                self.assertEqual(preparation.ChallengePreparationTests().execute(c).status, 'ok')
            c.window.click.assert_called_once()
            self.assertAlmostEqual(c.window.click.call_args.args[0], (810 + 17) / 1920)
            c.window.key.assert_not_called()
            data = c.report.challenge
            self.assertEqual(data['plan']['levels'], [2, 4])
            self.assertEqual(data['selected_level'], 2)
            self.assertTrue(data['preparation_page_verified'])
            self.assertFalse(data['team_verified'])
            self.assertFalse(data['battle_started'])
            self.assertFalse(data['completion_verified'])
            action, = data['actions']
            self.assertEqual((action['intent'], action['status']), ('select_level', 'verified'))
            one, two = action['after']
            self.assertLess(one['captured_at'], two['captured_at'])
            self.assertTrue(all(row['level'] == 2 and row['mode'] == 'pure_fiction' for row in (one, two)))
            self.assertEqual(scan.call_count, 2)
            self.assertTrue(all(call.kwargs == {'mode': 'pure_fiction'} for call in scan.call_args_list))

    def test_unproven_setup_does_not_verify_previous_click_or_repeat_it(self):
        with tempfile.TemporaryDirectory() as folder:
            c = self.context(folder, [fiction_lobby(), fiction_lobby(), fiction_setup(None)])

            def expire_wait(_scene):
                c.sleep = lambda _seconds: setattr(c.clock, 'value', c.clock.value + 31)

            preparation.track_captures(c, {2: expire_wait})
            with self.assertRaisesRegex(AutomationError, '同层备战页面'):
                preparation.ChallengePreparationTests().execute(c)
            self.assertEqual(c.report.challenge['actions'][0]['status'], 'unknown')
            self.assertFalse(c.report.challenge['preparation_page_verified'])
            c.window.click.assert_called_once()
            c.window.key.assert_not_called()

    def test_existing_fiction_setup_requires_same_account_and_input_epoch(self):
        for change in (None, 'account', 'epoch'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as folder:
                c = self.context(folder, [fiction_setup(), fiction_setup()])

                def change_binding(scene):
                    if change == 'account':
                        scene.tokens[-1] = token('UID:200000000', (15, 1035, 200, 1060))
                    elif change == 'epoch':
                        c.runner.input_epoch += 1

                preparation.track_captures(c, {1: change_binding})
                execute = preparation.ChallengePreparationTests().execute
                with patch('autohsr.challenge_roster.observe_candidates', return_value={'availability': 'unknown'}):
                    if change:
                        with self.assertRaises(InputInterrupted if change == 'epoch' else AutomationError):
                            execute(c)
                        self.assertFalse(c.report.challenge['preparation_page_verified'])
                    else:
                        self.assertEqual(execute(c).status, 'ok')
                        self.assertEqual(c.report.challenge['entry'], 'existing_team_setup')
                self.assertEqual(c.report.challenge['actions'], [])
                c.window.click.assert_not_called()
                c.window.key.assert_not_called()
