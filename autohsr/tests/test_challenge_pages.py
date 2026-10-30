"""Synthetic source-relation mechanisms, not real challenge page calibration."""
from copy import deepcopy
from dataclasses import FrozenInstanceError
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr import challenge_pages as pages
from autohsr.models import Scene, Token


def token(text, box, score=.99):
    return Token(text, score, tuple(v / size for v, size in zip(box, (1920, 1080, 1920, 1080))))


def paste(image, name, x, y):
    bitmap = pages._references()[name][0]
    image[y:y + bitmap.shape[0], x:x + bitmap.shape[1]] = bitmap
    return (x, y, x + bitmap.shape[1], y + bitmap.shape[0])


def lobby_scene(levels=(1, 2), *, stars=None, total=None, selected=None):
    """Artificial collage with original local glyphs and invented page text."""
    image = np.full((1080, 1920, 3), 12, np.uint8)
    paste(image, 'title', 100, 60)
    values = {level: 1 for level in levels} if stars is None else stars
    total = sum(values.values()) if total is None else total
    words = [token('忘却之庭', (151, 61, 202, 77)), token('混沌回忆', (152, 82, 202, 104)),
             token(f'{total}/36', (1400, 90, 1500, 120))]
    shape = cv2.cvtColor(pages._references()['star'][0], cv2.COLOR_BGR2GRAY) > 127
    for index, level in enumerate(levels):
        x = 650 + index * 180
        words.append(token(f'{level:02}', (x, 500, x + 38, 526)))
        for star in range(values.get(level, 0)):
            corner = image[560:577, x + 10 + star * 26:x + 27 + star * 26]
            corner[shape] = [112, 200, 255]
    if selected is not None:
        words.append(token(f'第{selected:02}层', (820, 160, 940, 190)))
    return Scene(words, image, captured_at=time.monotonic())


def setup_scene(level=1):
    """Artificial team header group; deliberately no selected role feedback."""
    image = np.full((1080, 1920, 3), 12, np.uint8)
    paste(image, 'team1', 650, 570)
    paste(image, 'team2', 650, 790)
    paste(image, 'reset', 950, 590)
    paste(image, 'switch', 1040, 590)
    box = paste(image, 'caption', 1650, 980)
    words = [token('「混沌回忆」', box)]
    if level is not None:
        words.append(token(f'第{level:02}层', (820, 160, 940, 190)))
    return Scene(words, image, captured_at=time.monotonic())


class ChallengePageTests(unittest.TestCase):
    def test_original_reference_manifest_and_bytes_are_required(self):
        data = json.loads((pages.ASSET_ROOT / 'sources.json').read_text(encoding='utf-8'))
        self.assertEqual(len(data['images']), 14)
        self.assertEqual(set(pages._references()), set(pages._FILES))
        import hashlib
        for row in data['images']:
            raw = (pages.ASSET_ROOT / row['file']).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), row['sha256'])
            self.assertEqual(len(raw), row['bytes'])

    def test_lobby_group_binds_each_positive_star_strip_to_its_label(self):
        scene = lobby_scene((1, 2, 3), stars={1: 1, 2: 2, 3: 3})
        value = pages.observe(scene)
        self.assertEqual((value.kind, value.mode, value.level, value.half, value.stars),
                         ('lobby', 'memory_of_chaos', None, None, None))
        self.assertEqual([(r['level'], r['stars']) for r in value.basis['levels']], [(1, 1), (2, 2), (3, 3)])
        self.assertEqual(pages.target(scene, 'select_level', level=2).text, '02')
        self.assertFalse(value.basis['full_real_page_calibrated'])
        self.assertTrue(all(row['available'] is None for row in value.basis['levels']))

    def test_current_level_is_separate_from_first_list_item(self):
        value = pages.observe(lobby_scene(selected=2))
        self.assertEqual((value.level, value.stars), (2, 1))
        self.assertEqual(pages.observe(lobby_scene(selected=12)).kind, 'unknown')
        scene = lobby_scene(selected=1)
        scene.tokens.append(token('第02层', (1050, 150, 1200, 180)))
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        self.assertIsNone(pages.target(scene, 'select_level', level=1))

    def test_missing_star_reference_does_not_become_zero_or_target(self):
        scene = lobby_scene(stars={1: 0, 2: 1})
        observation = pages.observe(scene)
        self.assertEqual(observation.kind, 'lobby')
        self.assertIsNone(observation.basis['levels'][0]['stars'])
        self.assertIsNone(pages.target(scene, 'select_level', level=1))
        self.assertIsNotNone(pages.target(scene, 'select_level', level=2))

    def test_title_numbers_or_gold_alone_do_not_authorize_a_level(self):
        scene = lobby_scene()
        for remove in ('title', 'counter', 'levels', 'stars'):
            value = deepcopy(scene)
            if remove == 'title':
                value.image[50:120, 80:220] = 12
            elif remove == 'counter':
                value.tokens = [t for t in value.tokens if '/36' not in t.text]
            elif remove == 'levels':
                value.tokens = [t for t in value.tokens if t.text != '02']
            else:
                value.image[540:600] = 12
            self.assertIsNone(pages.target(value, 'select_level', level=1), remove)

    def test_counter_conflict_duplicate_level_or_row_overlap_is_not_adopted(self):
        self.assertEqual(pages.observe(lobby_scene(total=0)).kind, 'unknown')
        scene = lobby_scene()
        scene.tokens.append(token('01', (1200, 500, 1240, 526)))
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = lobby_scene()
        scene.tokens = [token('02', (700, 500, 740, 526)) if t.text == '02' else t for t in scene.tokens]
        self.assertIsNone(pages.target(scene, 'select_level', level=1))

    def test_dialog_lock_other_mode_and_loading_override_visible_lobby(self):
        for label in ('未解锁', '确认退出', '充值', '虚构叙事', '末日幻影', '挑战成功', '加载中'):
            scene = lobby_scene()
            scene.tokens.append(token(label, (700, 300, 1000, 350)))
            self.assertEqual(pages.observe(scene).kind, 'unknown', label)

    def test_collected_blockers_win_before_the_stricter_positive_threshold(self):
        for label in ('未解锁', '确认退出', '是否退出', '充值', '加载中'):
            for build in (lobby_scene, setup_scene):
                scene = build()
                scene.tokens.append(token(label, (700, 300, 1000, 350), score=.84))
                self.assertEqual(pages.observe(scene, confidence=.65).kind, 'unknown', label)
                self.assertIsNone(pages.target(scene, 'select_level', confidence=.65, level=1), label)
        # Text below the declared collection threshold is not upgraded to
        # observed text, nor can it complete a missing positive page anchor.
        scene = lobby_scene()
        scene.tokens = [Token(t.text, .64, t.box) if '/36' in t.text else t for t in scene.tokens]
        scene.tokens.append(token('未解锁', (700, 300, 1000, 350), score=.64))
        self.assertEqual(pages.observe(scene, confidence=.65).kind, 'unknown')
        self.assertIsNone(pages.target(scene, 'select_level', confidence=.65, level=1))

    def test_dimmed_title_stars_or_conflicting_ocr_do_not_supply_targets(self):
        scene = lobby_scene()
        scene.image[60:107, 100:204] //= 2
        self.assertIsNone(pages.target(scene, 'select_level', level=1))
        scene = lobby_scene()
        scene.image[540:600] //= 2
        self.assertIsNone(pages.target(scene, 'select_level', level=1))
        scene = lobby_scene()
        scene.tokens.append(token('混沌回忆', (155, 65, 201, 105)))
        self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_setup_group_requires_independent_current_level_and_mode(self):
        result = pages.observe(setup_scene(4))
        self.assertEqual((result.kind, result.mode, result.level), ('team_setup', 'memory_of_chaos', 4))
        self.assertEqual(result.targets, ())
        self.assertEqual(result.basis['team_feedback'], 'unknown')
        self.assertIsNone(result.half)
        self.assertIsNone(pages.target(setup_scene(), 'select_level', level=1))
        self.assertEqual(pages.observe(setup_scene(None)).kind, 'unknown')
        scene = setup_scene()
        scene.tokens[0] = token('回忆', (1650, 980, 1770, 1005))
        self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_real_parent_title_and_original_quoted_caption_are_required(self):
        self.assertEqual(pages.observe(lobby_scene()).kind, 'lobby')
        self.assertEqual(pages.observe(setup_scene()).kind, 'team_setup')
        scene = lobby_scene()
        scene.tokens = [t for t in scene.tokens if t.text != '忘却之庭']
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = setup_scene()
        scene.tokens[0] = Token('混沌回忆', .99, scene.tokens[0].box)
        self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_real_title_lines_and_caption_can_have_exact_ordered_ocr_splits(self):
        scene = lobby_scene()
        scene.tokens = [t for t in scene.tokens if t.text not in ('忘却之庭', '混沌回忆')]
        scene.tokens += [token('回忆', (180, 82, 202, 104)), token('忘却', (151, 61, 175, 77)),
                         token('混沌', (152, 82, 176, 104)), token('之庭', (178, 61, 202, 77))]
        self.assertEqual(pages.observe(scene).kind, 'lobby')
        scene = lobby_scene()
        scene.tokens = [t for t in scene.tokens if t.text not in ('忘却之庭', '混沌回忆')]
        scene.tokens.append(token('忘却之庭\n混沌回忆', (151, 61, 202, 104)))
        self.assertEqual(pages.observe(scene).kind, 'lobby')
        for splits in (
                [('「混沌', (1650, 980, 1705, 1005)), ('回忆」', (1710, 980, 1769, 1005))],
                [('「', (1650, 980, 1660, 1005)), ('混沌回忆', (1664, 980, 1755, 1005)),
                 ('」', (1760, 980, 1769, 1005))],
                [('「混沌', (1650, 980, 1705, 990)), ('回忆」', (1710, 994, 1769, 1005))]):
            scene = setup_scene()
            scene.tokens = scene.tokens[1:] + [token(text, box) for text, box in splits]
            self.assertEqual(pages.observe(scene).kind, 'team_setup')

    def test_foreign_extra_text_reversed_title_or_modal_never_matches_by_substring(self):
        for text in ('活动忘却之庭', '忘却之庭活动', '混沌回忆活动'):
            scene = lobby_scene()
            index = 1 if text.startswith('混沌') else 0
            scene.tokens[index] = Token(text, .99, scene.tokens[index].box)
            self.assertIsNone(pages.target(scene, 'select_level', level=1), text)
        scene = lobby_scene()
        scene.tokens.append(token('说明', (155, 62, 200, 76)))
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = lobby_scene()
        scene.tokens[0] = Token('混沌回忆', .99, scene.tokens[0].box)
        scene.tokens[1] = Token('忘却之庭', .99, scene.tokens[1].box)
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        for text in ('进入「混沌回忆」', '「混沌回忆」活动', '「回忆混沌」'):
            scene = setup_scene()
            scene.tokens[0] = Token(text, .99, scene.tokens[0].box)
            self.assertEqual(pages.observe(scene).kind, 'unknown', text)
        for build in (lobby_scene, setup_scene):
            scene = build()
            scene.tokens.append(token('是否退出', (700, 300, 1000, 350)))
            self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_duplicate_or_conflicting_complete_level_headers_block_all_navigation(self):
        for second in (1, 2):
            scene = lobby_scene(selected=1)
            scene.tokens.append(token(f'第{second:02}层', (1050, 150, 1200, 180)))
            self.assertEqual(pages.observe(scene).kind, 'unknown')
            self.assertIsNone(pages.target(scene, 'select_level', level=1))
            scene = setup_scene(1)
            scene.tokens.append(token(f'第{second:02}层', (1050, 150, 1200, 180)))
            self.assertEqual(pages.observe(scene).kind, 'unknown')
        # Absence differs from ambiguity: ordinary list navigation remains.
        self.assertIsNone(pages.observe(lobby_scene()).level)
        self.assertIsNotNone(pages.target(lobby_scene(), 'select_level', level=1))

    def test_team_digits_do_not_prove_selected_roles_half_or_four_person_team(self):
        scene = setup_scene()
        scene.image[780:850, 640:700] = 12
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        result = pages.observe(setup_scene())
        self.assertFalse(result.basis['execution_supported'])
        self.assertFalse(hasattr(result, 'team1'))
        self.assertFalse(hasattr(result, 'cards'))
        with self.assertRaises(FrozenInstanceError):
            result.level = 2

    def test_no_battle_result_character_reset_or_start_action_is_exposed(self):
        for intent in ('reset', 'switch', 'start', 'select_character', 'claim', 'back', 'attack', 'technique'):
            self.assertIsNone(pages.target(lobby_scene(), intent, level=1))
        scene = lobby_scene()
        scene.tokens = [token('混沌回忆', (155, 65, 201, 105)), token('战斗胜利', (800, 400, 1100, 500))]
        self.assertEqual(pages.observe(scene).kind, 'unknown')

    def test_stale_future_low_confidence_malformed_and_wrong_aspect_are_unknown(self):
        scene = lobby_scene()
        for stamp in (time.monotonic() - 9, time.monotonic() + 1, float('nan')):
            scene.captured_at = stamp
            self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = lobby_scene()
        scene.tokens = [Token(t.text, .2, t.box) for t in scene.tokens]
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        scene = lobby_scene()
        scene.image = np.zeros((1080, 2560, 3), np.uint8)
        self.assertEqual(pages.observe(scene).kind, 'unknown')
        self.assertIsNone(pages.target(lobby_scene(), 'select_level', level=True))

    def test_manifest_and_replaced_asset_cannot_redefine_the_pinned_reference(self):
        original = pages.ASSET_ROOT
        with tempfile.TemporaryDirectory() as folder:
            import shutil
            for item in original.iterdir():
                if item.is_dir():
                    shutil.copytree(item, Path(folder) / item.name)
                else:
                    shutil.copyfile(item, Path(folder) / item.name)
            manifest = json.loads((Path(folder) / 'sources.json').read_text(encoding='utf-8'))
            row = next(row for row in manifest['images'] if row['file'] == pages._FILES['title'])
            row['sha256'] = '0' * 64
            (Path(folder) / 'sources.json').write_text(json.dumps(manifest), encoding='utf-8')
            pages._references.cache_clear()
            try:
                with patch.object(pages, 'ASSET_ROOT', Path(folder)):
                    self.assertEqual(pages._references(), {})
            finally:
                pages._references.cache_clear()


if __name__ == '__main__':
    unittest.main()
