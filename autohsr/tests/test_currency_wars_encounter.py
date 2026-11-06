"""Synthetic encounter fields and fake-window checks for the formal read-only entry."""
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.currency_wars import CurrencyWarsWorkflow, observe
from autohsr.currency_wars_encounter import (
    encounter_node_visible, encounter_overlay_present, read_encounter, read_encounter_targets, supplement_encounter_fields,
)
from autohsr.currency_wars_standard_flow import next_action
from autohsr.models import AutomationError, FocusLost, Scene, Token
from autohsr.tests import test_currency_wars as check_tests


def token(text, x, y, *, score=.99, half_width=.025):
    return Token(text, score, (x - half_width, y - .009, x + half_width, y + .009))


def encounter(*, selected=None, tiers=(1, 3), badge_counts=None):
    """Geometric test patterns, independent of the public recording pixels."""
    image = np.full((540, 960, 3), (58, 42, 32), np.uint8)
    h, w = image.shape[:2]
    names = '一二三四'
    fields = [token('遭遇节点', .5, .092), token('选择', .564, .799),
              token('剩余次数：1', .386, .801, half_width=.048)]
    for index, (center, tier, badges) in enumerate(zip((.346, .653), tiers, badge_counts or tiers)):
        fields.extend([token('遭遇其' + names[tier - 1], center, .372), token('难度', center, .414),
                       token('奖励预览', center, .534)])
        for mark in range(badges):
            x = center + (mark - (badges - 1) / 2) * .032
            points = np.array([(round(w * (x - .011)), round(h * .436)), (round(w * x), round(h * .460)),
                               (round(w * (x + .011)), round(h * .436))])
            mark_color = (73, 37, 228) if tier == 4 else (225, 102, 53) if index == 0 else (238, 73, 156)
            cv2.polylines(image, [points], False, mark_color, 6)
        edges = (.254, .442) if index == 0 else (.551, .748)
        color = (237, 240, 244) if selected == index + 1 else (177, 75, 133) if index else (55, 61, 76)
        for edge in edges:
            cv2.line(image, (round(edge*w), round(.405*h)), (round(edge*w), round(.672*h)), color, 3)
    fields += [token('金币', .348, .594), token('3', .310, .620, half_width=.006),
               token('随机4费角色', .670, .594), token('2', .622, .620, half_width=.006)]
    body = (236, 232, 228) if selected else (42, 32, 25)
    cv2.rectangle(image, (round(.465*w), round(.775*h)), (round(.663*w), round(.825*h)), body, -1)
    if selected:
        fields.append(token('查看详情', .501, .238))
    return Scene(fields, image=image)


def with_missing_fields(*, selected=None, badge_counts=None):
    frame = encounter(selected=selected, badge_counts=badge_counts)
    frame.tokens = [t for t in frame.tokens if t.text not in ('3', '2')
                    and not (t.center[0] < .5 and t.text in ('难度', '奖励预览'))]
    frame.tokens.append(token('返回备战界面', .93, .073, half_width=.040))
    return frame


def experience_frame():
    frame = with_missing_fields(selected=2)
    frame.tokens = [token('经验', .640, .594, half_width=.013) if t.text == '随机4费角色' else t
                    for t in frame.tokens]
    return frame


def supplement(frame, *, quantities=('12', '2')):
    reader = Mock(confidence=.65)
    replies = [text for text in ('难度', '奖励预览', *quantities) for _ in range(2)]
    reader._read_field.side_effect = [None if text is None else Token(text, .96, (0, 0, 1, 1))
                                      for text in replies]
    return supplement_encounter_fields(frame, reader)


class EncounterTests(unittest.TestCase):
    def cli_report(self, frame):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            window, vision, _, daily, launch, budget = check_tests.CoordinatorTests.fixture(self, root)
            window.capture.return_value = (frame.image, None)
            vision.read.side_effect = lambda image, geometry: Scene(frame.tokens, image, geometry, field_reads=frame.field_reads)
            config = root / 'config.json'
            Settings(auto_launch=True, overlay_logs=False).save(config)
            original = config.read_bytes()
            with (patch.object(Runner, '_arm_hotkeys'), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO())):
                self.assertEqual(main(['--config', str(config), '--currency-wars-check']), 1)
            self.assertEqual(config.read_bytes(), original)
            saved, = (root / 'runs').glob('*/report.json')
            report = json.loads(saved.read_text(encoding='utf-8'))['currency_wars']
            for method in (window.click, window.key, window.move, window.drag, window.scroll, launch, budget, daily):
                method.assert_not_called()
            self.assertFalse(report['completion_verified'])
            return report

    def test_two_columns_keep_rank_cost_quantity_and_refresh_separate(self):
        result = read_encounter(encounter())
        self.assertTrue(result.layout_verified)
        first, second = result.cards
        self.assertEqual((first.slot, first.name, first.difficulty), (1, '遭遇其一', 1))
        self.assertEqual(first.reward_preview, dict(kind='gold', quantity=3, character_cost=None))
        self.assertEqual((second.slot, second.name, second.difficulty), (2, '遭遇其三', 3))
        self.assertEqual(second.reward_preview, dict(kind='random_character', quantity=2, character_cost=4))
        self.assertEqual(result.refresh_remaining, 1)
        self.assertEqual((result.selection_state, result.confirm_state, result.selected_slot), ('unselected', 'disabled', None))

    def test_rank_and_badge_count_follow_the_column_and_can_vary(self):
        result = read_encounter(encounter(tiers=(4, 2)))
        self.assertEqual([card.difficulty for card in result.cards], [4, 2])
        self.assertEqual(result.selection_state, 'unselected')
        disagreement = read_encounter(encounter(tiers=(4, 2), badge_counts=(3, 2)))
        self.assertEqual([card.difficulty for card in disagreement.cards], [None, 2])
        self.assertEqual(disagreement.selection_state, 'unknown')

    def test_title_card_footer_and_body_must_all_be_current(self):
        source = encounter()
        for missing in (('遭遇其一',), ('选择',), ('难度', '奖励预览')):
            with self.subTest(missing=missing):
                readout = read_encounter(Scene([t for t in source.tokens if t.text not in missing], image=source.image))
                self.assertFalse(readout.layout_verified)
                self.assertFalse(readout.cards)
                self.assertEqual(readout.confirm_state, 'unknown')
        for header in (token('遗遇节点', .5, .092), token('遭遇节点', .5, .092, score=.62)):
            result = read_encounter(Scene([header, *source.tokens[1:]], image=source.image))
            self.assertFalse(result.layout_verified)
        wrong_column = Scene([token('遭遇其三', .38, .372) if t.text == '遭遇其三' else t
                              for t in source.tokens], image=source.image)
        self.assertFalse(read_encounter(wrong_column).layout_verified)
        wide_label = Scene([token('遭遇其一', .346, .372, half_width=.11) if t.text == '遭遇其一' else t
                            for t in source.tokens], image=source.image)
        self.assertFalse(read_encounter(wide_label).layout_verified)

    def test_selection_requires_both_borders_button_and_detail(self):
        selected = encounter(selected=2)
        result = read_encounter(selected)
        self.assertEqual((result.selection_state, result.confirm_state, result.selected_slot), ('selected', 'enabled', 2))
        for detail in (None, '查看评情'):
            frame = encounter(selected=2)
            frame.tokens = [t for t in frame.tokens if t.text != '查看详情']
            if detail:
                frame.tokens.append(token(detail, .501, .238))
            self.assertEqual(read_encounter(frame).selection_state, 'unknown')
        selected.image[round(.42*540):round(.658*540), round(.722*960):round(.771*960)] = (58, 42, 32)
        self.assertEqual(read_encounter(selected).selection_state, 'unknown')
        left = read_encounter(encounter(selected=1))
        self.assertEqual((left.selection_state, left.confirm_state, left.selected_slot), ('selected', 'enabled', 1))

    def test_rank_four_uses_red_marks_and_previews_basic_equipment_separately(self):
        frame = encounter(tiers=(1, 4))
        frame.tokens = [token('随机简易装备', .67, .594) if t.text == '随机4费角色' else t for t in frame.tokens]
        result = read_encounter(frame)
        self.assertEqual([card.difficulty for card in result.cards], [1, 4])
        self.assertEqual(result.cards[1].reward_preview, dict(kind='random_basic_equipment', quantity=2, character_cost=None))
        self.assertEqual(result.refresh_remaining, 1)
        rgb = frame.image[round(.423*540):round(.476*540), round(.566*960):round(.735*960)]
        rgb[rgb[:, :, 2] > 150] = (226, 77, 152)
        self.assertIsNone(read_encounter(frame).cards[1].difficulty)

    def test_targets_use_exact_current_card_title_and_shared_choice_tokens(self):
        frame = encounter(selected=1, tiers=(1, 4))
        frame.tokens.append(token('返回备战界面', .91, .060))
        targets = read_encounter_targets(frame)
        self.assertEqual(targets.observation.selected_slot, 1)
        self.assertIs(targets.cards[0], next(t for t in frame.tokens if t.text == '遭遇其一'))
        self.assertIs(targets.cards[1], next(t for t in frame.tokens if t.text == '遭遇其四'))
        self.assertIs(targets.choose, next(t for t in frame.tokens if t.text == '选择'))
        frame.tokens.append(token('选择', .595, .801))
        self.assertIsNone(read_encounter_targets(frame))

    def test_still_white_refresh_button_cannot_preserve_old_selection(self):
        for tier in (2, 4):
            frame = encounter(selected=1, tiers=(1, tier))
            self.assertEqual(read_encounter_targets(frame).observation.selected_slot, 1)
            # Cards change while the shared button remains lit. The current pair
            # has no selected outline and must lose the earlier target.
            refreshed = encounter(tiers=(1, 2 if tier == 4 else 3))
            refreshed.image[round(.775*540):round(.825*540), round(.465*960):round(.663*960)] = 233
            refreshed.tokens = [token('剩余次数：0', .385, .80) if t.text == '剩余次数：1' else t
                                for t in refreshed.tokens]
            result = read_encounter(refreshed)
            self.assertEqual((result.selected_slot, result.confirm_state, result.refresh_remaining), (None, 'enabled', 0))
            self.assertIsNone(read_encounter_targets(refreshed))
            self.assertTrue(encounter_overlay_present(refreshed))

    def test_preparation_bleed_and_no_ocr_card_silhouette_block_reuse(self):
        frame = encounter(selected=1)
        for bleed in (token('1-7', .246, .075), token('出战', .951, .699)):
            with self.subTest(bleed=bleed.text):
                mixed = Scene([*frame.tokens, bleed], image=frame.image)
                self.assertFalse(read_encounter(mixed).layout_verified)
                self.assertIsNone(read_encounter_targets(mixed))
                self.assertTrue(encounter_overlay_present(mixed))
        image = np.full((540, 960, 3), (157, 92, 58), np.uint8)
        image[round(.414*540):round(.665*540), round(.251*960):round(.440*960)] = (83, 67, 58)
        prep = [token('备战阶段', .234, .054), token('1-7', .246, .075), token('出战', .951, .699)]
        self.assertTrue(encounter_overlay_present(Scene(prep, image=image)))
        self.assertTrue(encounter_overlay_present(Scene([*prep, token('备战阶段', .501, .464)])))
        self.assertFalse(encounter_overlay_present(Scene([*prep, token('难度选择', .14, .135)])))

    def test_route_label_requires_unique_current_chip_and_exact_text(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures' / 'currency_wars_pages.json').read_text(encoding='utf-8'))
        stage = [Token(**row) for row in fixture['pages']['preparation']['tokens']]
        stage = [t for t in stage if not (t.within((.10, .036, .29, .135)) and '-' in t.text)]
        stage.extend((token('1-7', .244, .081), token('战斗', .366, .088, half_width=.007)))
        image = np.full((540, 960, 3), (150, 80, 61), np.uint8)

        def current_badge(x):
            image[round(.079*540):round(.094*540), round((x-.009)*960):round((x+.009)*960)] = (86, 206, 250)
            image[round(.031*540):round(.042*540), round((x-.006)*960):round((x+.006)*960)] = (86, 206, 250)

        current_badge(.608)
        scene = Scene(stage, image=image)
        self.assertIsNone(encounter_node_visible(scene))  # Nearby future node text alone is insufficient.
        scene.tokens.append(token('战斗', .608, .102, half_width=.007))
        self.assertIsNone(encounter_node_visible(scene))  # A different row at the same X is still unrelated.
        scene.tokens.pop()
        exact = token('遭遇', .608, .088, half_width=.007)
        scene.tokens.append(exact)
        self.assertIs(encounter_node_visible(scene), True)
        scene.tokens[-1] = token('战斗', .608, .088, half_width=.007)
        self.assertIs(encounter_node_visible(scene), False)
        scene.tokens.append(exact)
        self.assertIsNone(encounter_node_visible(scene))
        scene.tokens.pop(-2)
        current_badge(.375)
        self.assertIsNone(encounter_node_visible(scene))

    def test_ambiguous_pixels_never_report_dark_button_as_unselected(self):
        frame = encounter()
        frame.image[round(.787*540):round(.815*540), round(.487*960):round(.528*960)] = 235
        self.assertEqual(read_encounter(frame).confirm_state, 'unknown')
        for image in (None, np.zeros((540, 960, 3), np.uint8)):
            frame.image = image
            result = read_encounter(frame)
            self.assertTrue(result.layout_verified)
            self.assertEqual((result.confirm_state, result.selection_state), ('unknown', 'unknown'))
            self.assertEqual([card.difficulty for card in result.cards], [None, None])

    def test_ambiguous_reward_quantity_and_offrow_refresh_remain_unknown(self):
        frame = encounter()
        frame.tokens = [t for t in frame.tokens if t.text not in ('剩余次数：1', '随机4费角色')]
        frame.tokens.extend([token('随机4费角色×5', .67, .594), token('剩余次数', .366, .801),
                             token('0', .40, .766, half_width=.006)])
        result = read_encounter(frame)
        self.assertIsNone(result.refresh_remaining)
        self.assertEqual(result.cards[1].reward_preview, dict(kind='random_character', quantity=None, character_cost=4))
        frame.tokens.append(token('0', .40, .802, half_width=.006))
        self.assertEqual(read_encounter(frame).refresh_remaining, 0)

    def test_difficulty_labels_remain_with_their_own_title_and_badge_row(self):
        for marker in (None, token('难度', .669, .483), token('难度', .669, .414, score=.62),
                       token('难度', .704, .411)):
            with self.subTest(marker=marker):
                frame = encounter(selected=2)
                frame.tokens = [t for t in frame.tokens if not (t.text == '难度' and t.center[0] > .5)]
                if marker is not None:
                    frame.tokens.append(marker)
                result = read_encounter(frame)
                self.assertTrue(result.layout_verified)
                self.assertEqual([card.difficulty for card in result.cards], [1, None])
                self.assertEqual(result.selected_slot, 2)

    def test_reward_count_cannot_be_borrowed_from_a_shifted_or_adjacent_counter(self):
        for y in (.620, .646):
            with self.subTest(y=y):
                frame = encounter(selected=2)
                frame.tokens = [t for t in frame.tokens if t.text != '2']
                frame.tokens.extend([token('剩余次数', .596, y, half_width=.016),
                                     token('2', .622, y, half_width=.006)])
                result = read_encounter(frame)
                self.assertEqual(result.refresh_remaining, 1)
                self.assertEqual(result.cards[0].reward_preview['quantity'], 3)
                self.assertEqual(result.cards[1].reward_preview,
                                 dict(kind='random_character', quantity=None, character_cost=4))

    def test_reward_name_must_follow_its_own_heading_and_survive_clipping(self):
        for heading_y, label_y in ((.560, .577), (.534, .641)):
            with self.subTest(heading=heading_y, label=label_y):
                frame = encounter()
                frame.tokens = [t for t in frame.tokens if t.text != '随机4费角色'
                                and not (t.text == '奖励预览' and t.center[0] > .5)]
                frame.tokens.extend([token('奖励预览', .653, heading_y), token('随机4费角色×2', .670, label_y)])
                result = read_encounter(frame)
                self.assertTrue(result.layout_verified)
                self.assertIsNone(result.cards[1].reward_preview)
                self.assertEqual(result.cards[0].reward_preview['quantity'], 3)

    def test_occlusion_keeps_only_evidenced_fields_in_readonly_report(self):
        frame = encounter(selected=2)
        frame.image[round(.423*540):round(.476*540), round(.566*960):round(.735*960)] = 0
        frame.image[round(.42*540):round(.66*540), round(.722*960):round(.771*960)] = 0
        frame.tokens = [t for t in frame.tokens if t.text != '2']
        report = self.cli_report(frame)
        self.assertEqual(report['page_kind'], 'encounter_selection')
        details = report['encounter']
        self.assertEqual((details['selected_slot'], details['selection_state']), (None, 'unknown'))
        self.assertEqual([card['difficulty'] for card in details['cards']], [1, None])
        self.assertEqual([card['reward_preview']['quantity'] for card in details['cards']], [3, None])
        self.assertEqual(details['refresh_remaining'], 1)

    def test_same_card_and_reward_labels_keep_zero_and_multi_digit_values_separate(self):
        frame = encounter(tiers=(1, 1))
        frame.tokens = [t for t in frame.tokens if t.text not in ('3', '2', '随机4费角色', '剩余次数：1')]
        frame.tokens.extend([token('金币', .670, .594), token('12', .310, .620, half_width=.007),
                             token('103', .622, .620, half_width=.010), token('剩余次数：0', .386, .801)])
        result = read_encounter(frame)
        self.assertEqual([card.name for card in result.cards], ['遭遇其一', '遭遇其一'])
        self.assertEqual([card.difficulty for card in result.cards], [1, 1])
        self.assertEqual([card.reward_preview['quantity'] for card in result.cards], [12, 103])
        self.assertEqual(result.refresh_remaining, 0)
        frame.tokens = [t for t in frame.tokens if t.text not in ('103', '剩余次数：0')]
        frame.tokens.extend([token('0', .622, .620, half_width=.006), token('剩余次数：12', .386, .801)])
        result = read_encounter(frame)
        self.assertEqual([card.reward_preview['quantity'] for card in result.cards], [12, None])
        self.assertEqual(result.refresh_remaining, 12)

    def test_local_fields_fill_current_missing_columns_and_stay_readonly(self):
        raw = with_missing_fields()
        self.assertFalse(read_encounter(raw).layout_verified)
        frame = supplement(raw, quantities=('103', '2'))
        self.assertIs(frame.tokens, raw.tokens)
        self.assertFalse(raw.field_reads)
        self.assertEqual(len(frame.field_reads), 4)
        targets = read_encounter_targets(frame)
        self.assertEqual(targets.observation.selection_state, 'unselected')
        self.assertEqual([card.difficulty for card in targets.observation.cards], [1, 3])
        self.assertEqual([card.reward_preview['quantity'] for card in targets.observation.cards], [103, 2])
        report = self.cli_report(frame)
        self.assertEqual(report['page_kind'], 'encounter_selection')
        self.assertEqual(report['decision'], 'stop_without_input')
        self.assertFalse(report['strategy_decision']['executable'])
        self.assertEqual(report['encounter']['cards'][0]['reward_preview']['quantity'], 103)

    def test_local_title_only_completes_the_original_ordinal_and_position(self):
        raw = with_missing_fields(selected=1)
        partial = token('遇其一', .346, .372)
        raw.tokens = [partial if t.text == '遭遇其一' else t for t in raw.tokens]
        reader = Mock(confidence=.65)
        for candidate in ('遭遇其二', '遭遇其一'):
            replies = (candidate, '难度', '奖励预览', '12', '2')
            reader._read_field.side_effect = [Token(t, .96, (0, 0, 1, 1)) for t in replies for _ in range(2)]
            frame = supplement_encounter_fields(raw, reader)
            self.assertIn(partial, frame.tokens)
            targets = read_encounter_targets(frame)
            if candidate == '遭遇其一':
                self.assertEqual(targets.cards[0], Token(candidate, .96, partial.box))
                self.assertEqual(targets.observation.selected_slot, 1)
            else:
                self.assertIsNone(targets)
        raw.tokens.append(token('遭遇其二', .346, .371))
        reader.reset_mock()
        self.assertIs(supplement_encounter_fields(raw, reader), raw)
        reader._read_field.assert_not_called()

    def test_local_fields_need_a_complete_current_panel_and_stable_controls(self):
        raw = with_missing_fields(selected=1)
        old_fields = supplement(raw).field_reads
        for problem in ('header', 'card', 'partial_pair', 'edge', 'white', 'preparation', 'shop'):
            with self.subTest(problem=problem):
                frame = with_missing_fields(selected=1)
                if problem == 'header':
                    frame.tokens[0] = token('遗遇节点', .5, .092)
                elif problem == 'card':
                    frame.tokens = [t for t in frame.tokens if t.text != '遭遇其三']
                elif problem == 'partial_pair':
                    frame.tokens = [Token(t.text[1:], t.score, t.box) if t.text.startswith('遭遇其') else t
                                    for t in frame.tokens]
                elif problem == 'edge':
                    left = frame.image[round(.42 * 540):round(.658 * 540), :round(.46 * 960)]
                    left[:] = (58, 42, 32)
                elif problem == 'white':
                    frame = with_missing_fields()
                    frame.image[round(.775 * 540):round(.825 * 540), round(.465 * 960):round(.663 * 960)] = 233
                elif problem == 'preparation':
                    frame.tokens += [token('1-7', .246, .074), token('出战', .95, .70)]
                else:
                    frame.tokens.append(token('补给阶段', .5, .07))
                reader = Mock(confidence=.65)
                self.assertIs(supplement_encounter_fields(frame, reader), frame)
                reader._read_field.assert_not_called()
                frame.field_reads = old_fields
                self.assertIsNone(read_encounter_targets(frame))

    def test_local_reads_reject_wrong_columns_disagreement_and_weak_values(self):
        for problem in ('column', 'different', 'decorated', 'weak'):
            with self.subTest(problem=problem):
                frame = supplement(with_missing_fields())
                left = 'currency_encounter.1.quantity'
                first, second = frame.field_reads[left]
                if problem == 'column':
                    frame.field_reads[left] = frame.field_reads['currency_encounter.2.quantity']
                elif problem == 'different':
                    frame.field_reads[left] = first, Token('13', second.score, second.box)
                elif problem == 'decorated':
                    frame.field_reads[left] = first, Token('1:2', second.score, second.box)
                else:
                    frame.field_reads[left] = first, Token(second.text, .84, second.box)
                result = read_encounter(frame)
                self.assertEqual([c.reward_preview['quantity'] for c in result.cards], [None, 2])

    def test_raw_quantity_conflicts_and_difficulty_pixels_survive_refinement(self):
        frame = supplement(with_missing_fields(badge_counts=(2, 3)))
        frame.tokens.append(token('7', .309, .617, half_width=.006))
        cards = read_encounter(frame).cards
        self.assertIsNone(cards[0].difficulty)
        self.assertEqual(cards[0].reward_preview['quantity'], 7)
        frame.tokens.append(token('8', .312, .623, half_width=.006))
        self.assertIsNone(read_encounter(frame).cards[0].reward_preview['quantity'])
        self.assertIsNone(read_encounter_targets(frame))

    def test_right_experience_preview_uses_its_own_amount_only_in_readonly_check(self):
        frame = supplement(experience_frame(), quantities=('3', '8'))
        observed = read_encounter(frame, include_experience=True)
        self.assertEqual(observed.selected_slot, 2)
        self.assertEqual(observed.cards[0].reward_preview, dict(kind='gold', quantity=3, character_cost=None))
        self.assertEqual(observed.cards[1].reward_preview, dict(kind='experience', quantity=8, character_cost=None))
        self.assertIsNone(read_encounter(frame).cards[1].reward_preview)
        self.assertIsNone(read_encounter_targets(frame).observation.cards[1].reward_preview)
        report = self.cli_report(frame)
        self.assertEqual(report['encounter']['cards'][1]['reward_preview'], observed.cards[1].reward_preview)
        self.assertEqual(report['decision'], 'stop_without_input')
        self.assertFalse(report['strategy_decision']['executable'])

    def test_experience_requires_current_exact_right_label_and_stable_panel(self):
        for problem in ('wrong_label', 'weak_label', 'left_label', 'white_transition', 'prep_bleed'):
            with self.subTest(problem=problem):
                frame = supplement(experience_frame(), quantities=('3', '8'))
                if problem == 'wrong_label':
                    replacement = token('经韵', .640, .594, half_width=.013)
                elif problem == 'weak_label':
                    replacement = token('经验', .640, .594, score=.84, half_width=.013)
                elif problem == 'left_label':
                    replacement = token('经验', .345, .594, half_width=.013)
                else:
                    replacement = next(t for t in frame.tokens if t.text == '经验')
                frame.tokens = [replacement if t.text == '经验' else t for t in frame.tokens]
                if problem == 'white_transition':
                    frame.tokens = [t for t in frame.tokens if t.text != '查看详情']
                if problem == 'prep_bleed':
                    frame.tokens.append(token('出战', .951, .699))
                cards = read_encounter(frame, include_experience=True).cards
                self.assertTrue(all(not c.reward_preview or c.reward_preview['kind'] != 'experience' for c in cards))

    def test_right_experience_quantity_remains_unknown_with_conflicts_or_other_column(self):
        frame = supplement(experience_frame(), quantities=('3', '8'))
        key = 'currency_encounter.2.experience_quantity'
        original = frame.field_reads[key]
        frame.field_reads[key] = frame.field_reads['currency_encounter.1.quantity']
        self.assertIsNone(read_encounter(frame, include_experience=True).cards[1].reward_preview['quantity'])
        frame.field_reads[key] = original
        frame.tokens.extend([token('8', .619, .619, half_width=.004), token('9', .622, .621, half_width=.004)])
        self.assertIsNone(read_encounter(frame, include_experience=True).cards[1].reward_preview['quantity'])
        frame.tokens.append(token('随机简易装备', .670, .594))
        self.assertIsNone(read_encounter(frame, include_experience=True).cards[1].reward_preview)

    def test_focus_loss_after_local_ocr_discards_the_completed_frame(self):
        frame = supplement(with_missing_fields(selected=1))
        with tempfile.TemporaryDirectory() as folder:
            window, vision, *_ = check_tests.CoordinatorTests.fixture(self, Path(folder))
            stale_geometry, fresh_geometry = object(), object()
            fresh = Scene([], image=np.zeros((90, 160, 3), dtype=np.uint8))
            window.capture.side_effect = [(frame.image, stale_geometry), (fresh.image, fresh_geometry)]
            vision.read.side_effect = [frame, fresh]

            def guard(geometry=None):
                if geometry is stale_geometry:
                    raise FocusLost('focus changed during local OCR')

            window.guard.side_effect = guard
            report = Runner(Settings(overlay_logs=False), operation='currency_wars').run()
            self.assertEqual(report.currency_wars['page_kind'], 'unknown')
            self.assertNotIn('encounter', report.currency_wars)
            self.assertEqual(vision.read.call_count, 2)
            window.click.assert_not_called()
            window.key.assert_not_called()

    def test_partially_visible_settlement_cannot_confirm_encounter_through_readonly_cli(self):
        frame = encounter(selected=2)
        frame.tokens.extend([token('挑战结束', .50, .201), token('挑战进度', .50, .349), token('前往结算', .51, .84)])
        self.assertEqual(observe(frame, .65).page_kind, 'unknown')
        report = self.cli_report(frame)
        self.assertEqual(report['page_kind'], 'unknown')
        self.assertFalse(report['page_verified'])
        self.assertNotIn('encounter', report)
        self.assertEqual(report['decision'], 'stop_without_input')

    def test_only_readonly_report_recognizes_encounter(self):
        frame = encounter(selected=2)
        self.assertEqual(observe(frame, .65).page_kind, 'unknown')
        with self.assertRaises(AutomationError):
            next_action(frame)
        report = self.cli_report(frame)
        self.assertEqual(report['page_kind'], 'encounter_selection')
        self.assertTrue(report['page_verified'])
        self.assertEqual(report['encounter']['selected_slot'], 2)
        self.assertEqual(report['decision'], 'stop_without_input')
        self.assertEqual(report['strategy_snapshot']['page'], 'unknown')
        self.assertFalse(report['strategy_decision']['executable'])

    def test_known_pages_retain_their_kind_with_a_stray_encounter_label(self):
        path = Path(__file__).parent / 'fixtures' / 'currency_wars_pages.json'
        pages = json.loads(path.read_text(encoding='utf-8'))['pages']
        for kind in ('preparation', 'investment_selection', 'supply_selection', 'environment', 'boss_intro'):
            with self.subTest(kind=kind):
                fields = [Token(**entry) for entry in pages[kind]['tokens']]
                fields.extend([token('遭遇节点', .5, .092), token('选择', .564, .799)])
                frame = Scene(fields, captured_at=time.monotonic())
                self.assertEqual(observe(frame, .65).page_kind, kind)
                context = check_tests.WorkflowSafetyTests.context(self, frame)
                CurrencyWarsWorkflow(context).inspect()
                self.assertEqual(context.report.currency_wars['page_kind'], kind)
                self.assertNotIn('encounter', context.report.currency_wars)

    def test_ambiguous_candidate_is_reported_without_cards_or_known_fields(self):
        frame = encounter(selected=2)
        frame.tokens[0] = token('遗遇节点', .5, .092)
        frame.captured_at = time.monotonic()
        context = check_tests.WorkflowSafetyTests.context(self, frame)
        result = CurrencyWarsWorkflow(context).inspect()
        report = context.report.currency_wars
        self.assertIn('布局待核实', result.detail)
        self.assertEqual(report['page_kind'], 'unknown')
        self.assertEqual(report['encounter'], dict(layout_verified=False, cards=(), selected_slot=None,
                                                  selection_state='unknown', confirm_state='unknown', refresh_remaining=None))
