"""Synthetic encounter fields and fake-window checks for the formal read-only entry."""
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from autohsr.__main__ import main
from autohsr.app import Runner
from autohsr.config import Settings
from autohsr.currency_wars import CurrencyWarsWorkflow, observe
from autohsr.currency_wars_encounter import read_encounter
from autohsr.currency_wars_standard_flow import next_action
from autohsr.models import AutomationError, Scene, Token
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
            cv2.polylines(image, [points], False, (225, 102, 53) if index == 0 else (238, 73, 156), 6)
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


class EncounterTests(unittest.TestCase):
    def cli_report(self, frame):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            window, vision, _, daily, launch, budget = check_tests.CoordinatorTests.fixture(self, root)
            window.capture.return_value = (frame.image, None)
            vision.read.side_effect = lambda image, geometry: Scene(frame.tokens, image, geometry)
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

    def test_right_selection_requires_both_borders_button_and_detail(self):
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
        self.assertEqual((left.selection_state, left.confirm_state, left.selected_slot), ('unknown', 'enabled', None))

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
