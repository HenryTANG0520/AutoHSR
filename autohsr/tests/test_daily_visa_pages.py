"""Replay sanitized visa layout fields and the independently selected tab."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import unittest

import cv2
import numpy as np

from autohsr.daily_visa_pages import visa_character_tab, visa_overview, visa_support_section
from autohsr.models import Scene, Token


FIXTURES = Path(__file__).parent / 'fixtures' / 'daily_visa'
SOURCE = json.loads((FIXTURES / 'sources.json').read_text(encoding='utf8'))
ATTACHMENTS = {row['id']: row for row in SOURCE['frames']}


def replay(name):
    row = ATTACHMENTS[name]
    raw = (FIXTURES / row['crop_file']).read_bytes()
    if hashlib.sha256(raw).hexdigest() != row['crop_png_sha256']:
        raise AssertionError('Unexpected tab fixture bytes')
    crop = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    width, height = SOURCE['image_size_px']
    image = np.zeros((height, width, 3), dtype=np.uint8)
    left, top, right, bottom = row['crop_xyxy_px']
    image[top:bottom, left:right] = crop
    tokens = [Token(field['text'], field['score'], tuple(
        value / dimension for value, dimension in zip(field['xyxy_px'], (width, height) * 2)
    )) for field in row['tokens']]
    return Scene(tokens, image)


class VisaOverviewTests(unittest.TestCase):
    def setUp(self):
        self.collection = replay('collection')
        self.characters = replay('characters')
        self.battle_record = replay('battle-record')

    def test_static_source_overview_and_independent_subpages(self):
        self.assertTrue(visa_overview(self.collection))
        for scene in (self.characters, self.battle_record):
            with self.subTest(scene=scene.tokens):
                self.assertFalse(visa_overview(scene))
                # Neither stale OCR nor stale pixels can turn the wrong page
                # into an overview while the other observation remains current.
                self.assertFalse(visa_overview(replace(scene, tokens=self.collection.tokens)))
                self.assertFalse(visa_overview(replace(scene, image=self.collection.image)))
        stale_sections = [token for token in self.characters.tokens if token.text in ('支援角色', '星海同行')]
        self.assertFalse(visa_overview(replace(self.collection, tokens=self.collection.tokens + stale_sections)))

    def test_support_section_matches_only_the_selected_character_showcase(self):
        self.assertTrue(visa_support_section(self.characters))
        for other in (self.collection, self.battle_record):
            self.assertFalse(visa_support_section(other))
            self.assertFalse(visa_support_section(replace(other, tokens=self.characters.tokens)))
            self.assertFalse(visa_support_section(replace(other, image=self.characters.image)))

    def test_character_tab_is_the_genuine_unselected_middle_control_on_collection(self):
        scene = self.collection
        expected = next(token for token in scene.tokens if token.text == '角色展示')
        for width, height in ((1368, 807), (1920, 1080), (1280, 720), (960, 540)):
            with self.subTest(size=(width, height)):
                scaled = replace(scene, image=cv2.resize(scene.image, (width, height)))
                self.assertEqual(visa_character_tab(scaled, client_version='4.6.0'), expected)
        for other, version in ((scene, '4.7.0'), (self.characters, '4.6.0'), (self.battle_record, '4.6.0')):
            self.assertIsNone(visa_character_tab(other, client_version=version))

    def test_character_tab_needs_visible_bright_strokes_against_the_dark_pill(self):
        source = self.collection
        boxes = ((652, 94, 717, 115), (702, 94, 717, 115))
        for left, top, right, bottom in boxes:
            image = source.image.copy()
            image[top:bottom, left:right] = 51
            obscured = replace(source, image=image)
            self.assertTrue(visa_overview(obscured))
            self.assertIsNone(visa_character_tab(obscured, client_version='4.6.0'))
        dimmed = source.image.copy()
        dimmed[94:115, 652:717] = np.rint(dimmed[94:115, 652:717] * .65).astype(np.uint8)
        self.assertIsNone(visa_character_tab(replace(source, image=dimmed), client_version='4.6.0'))
        conflict = Token('角色展示', .71, (.29, .46, .34, .50))
        self.assertIsNone(visa_character_tab(replace(source, tokens=[*source.tokens, conflict]),
                                            client_version='4.6.0'))

    def test_layout_at_resized_fixture_and_without_the_top_capture_border(self):
        for classify, scene in ((visa_overview, self.collection), (visa_support_section, self.characters)):
            with self.subTest(classify=classify.__name__):
                image = cv2.resize(scene.image, (1920, 1080))
                self.assertTrue(classify(replace(scene, image=image)))
                tokens = []
                for token in scene.tokens:
                    x1, y1, x2, y2 = token.box
                    box = (x1, (y1 * 807 - 37) / 770, x2, (y2 * 807 - 37) / 770)
                    tokens.append(replace(token, box=box))
                self.assertTrue(classify(Scene(tokens, scene.image[37:])))

    def test_support_section_requires_both_exact_unique_heading_boxes(self):
        tokens = self.characters.tokens
        support = next(token for token in tokens if token.text == '支援角色')
        companion = next(token for token in tokens if token.text == '星海同行')
        for heading, other in ((support, companion), (companion, support)):
            with self.subTest(heading=heading.text):
                remaining = [token for token in tokens if token is not heading]
                self.assertFalse(visa_support_section(replace(self.characters, tokens=remaining)))
                for substitute in (replace(heading, score=.849), replace(heading, text=heading.text[:-1]),
                                   replace(heading, box=other.box)):
                    self.assertFalse(visa_support_section(replace(self.characters, tokens=[*remaining, substitute])))
                conflict = replace(heading, score=.66, box=(.90, .74, .97, .79))
                self.assertFalse(visa_support_section(replace(self.characters, tokens=[*tokens, conflict])))

    def test_support_section_rejects_overlapping_or_partly_active_tabs(self):
        double_active = self.characters.image.copy()
        double_active[83:124, 754:890] = self.collection.image[83:124, 754:890]
        half_active = self.characters.image.copy()
        half_active[90:115, 620:649] = 37
        for image in (double_active, half_active, np.rint(self.characters.image * .90).astype(np.uint8)):
            self.assertFalse(visa_support_section(replace(self.characters, image=image)))

    def test_title_or_gift_without_complete_landmarks_cannot_confirm_the_page(self):
        tokens = self.collection.tokens
        title = next(token for token in tokens if token.text == '漫游签证')
        subtitle = next(token for token in tokens if token.text == '收集展示' and token.center[0] < .15)
        gift = Token('支援奖励', .99, (.91, .29, .95, .33))
        cases = ([title], [title, gift], [token for token in tokens if token is not subtitle],
                 [token for token in tokens if token.text != '规则说明'])
        for incomplete in cases:
            self.assertFalse(visa_overview(replace(self.collection, tokens=incomplete)))
        # The genuine collection fixture has no gift or reward evidence.
        self.assertTrue(visa_overview(self.collection))
        self.assertFalse(visa_overview(self.characters))

    def test_declines_weak_clipped_and_conflicting_ocr_fields(self):
        tokens = self.collection.tokens
        subtitle = next(token for token in tokens if token.text == '收集展示' and token.center[0] < .15)
        rival = replace(subtitle, text='角色展示', score=.67)
        weak_rule = Token('规则说明', .67, (.45, .35, .55, .38))
        clipped = replace(subtitle, box=(.0, .095, .15, .139))
        tab = next(token for token in tokens if token.text == '角色展示')
        off_row = replace(tab, box=(.47, .136, .52, .166))
        cases = (
            [*tokens, rival],
            [*tokens, weak_rule],
            [replace(token, score=.849) if token is subtitle else token for token in tokens],
            [clipped if token is subtitle else token for token in tokens],
            [off_row if token is tab else token for token in tokens],
        )
        for conflict in cases:
            self.assertFalse(visa_overview(replace(self.collection, tokens=conflict)))
        self.assertFalse(visa_overview(self.collection, 1.0))
        self.assertFalse(visa_overview(self.collection, float('nan')))

    def test_declines_both_active_tabs_one_sided_pill_dimmed_and_unreadable_images(self):
        image = self.collection.image
        two_active = image.copy()
        two_active[83:124, 618:751] = self.characters.image[83:124, 618:751]
        half_active = image.copy()
        half_active[90:115, 760:790] = 37
        dimmed = np.rint(image * .90).astype(np.uint8)
        bright_glyphs = self.characters.image.copy()
        bright_glyphs[92:116, 788:854] = 255
        for altered in (two_active, half_active, dimmed, bright_glyphs, np.zeros_like(image), image[:, :, 0], None):
            self.assertFalse(visa_overview(replace(self.collection, image=altered)))

    def test_declines_payment_reward_help_and_helper_overlays(self):
        def label(text, x=.49, y=.40, score=.92):
            return Token(text, score, (x, y, x + .04, y + .024))

        overlays = (
            [label('确认支付 100')],
            [label('确认', x=.40), label('付款', x=.445)],
            [label('支援奖励')],
            [label('支援奖励领取记录')],
            [label('恭喜获得物品')],
            [label('获得', x=.40), label('物品', x=.445)],
            [label('获得', x=.40, score=.73), label('物品', x=.445, score=.73)],
            [label('点击空白处关闭')],
            [label('兑换码', x=.86, y=.18, score=.68)],
            [label('规则说明', score=.67)],
            [label('AutoHSR'), label('运行日志', y=.44), label('保存设置', y=.50)],
        )
        for overlay in overlays:
            with self.subTest(overlay=[token.text for token in overlay]):
                self.assertFalse(visa_overview(replace(self.collection, tokens=self.collection.tokens + overlay)))
                self.assertFalse(visa_support_section(replace(
                    self.characters, tokens=self.characters.tokens + overlay)))


if __name__ == '__main__':
    unittest.main()
