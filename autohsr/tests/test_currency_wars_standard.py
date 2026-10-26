"""A8 wealth rank selection: distinguish selection, visibility and start."""
import unittest
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import Mock

import cv2
import numpy as np

from autohsr.config import Settings
from autohsr.currency_wars_navigation import next_action
from autohsr.currency_wars_standard import difficulty_page, rank_target, selected_rank, visible_ranks, supplement_rank
from autohsr.models import AutomationError, Scene, Token


def rank_page(current=50, values=(50, 49, 48)):
    tokens = [Token(text, .99, box) for text, box in (
        ('货币战争', (.05, .04, .10, .07)), ('标准博弈', (.06, .80, .1, .83)),
        ('A8财富造物主', (.04, .28, .13, .31)),
        ('当前职级难度效果*效果叠加生效中', (.39, .28, .57, .31)),
        ('开始对局', (.85, .88, .91, .91))) ]
    image = np.zeros((1080, 1920, 3), dtype=np.uint8)
    for i, value in enumerate(values):
        y = .39 + .18*i
        box = (.12, y-.04, .18, y+.04)
        tokens.append(Token(str(value), .99, box))
        if value == current:
            image[round((y-.08)*1080):round((y+.08)*1080)] = (230, 130, 80)
        cv2.putText(image, str(value), (round(.12*1920), round((y+.033)*1080)),
                    cv2.FONT_HERSHEY_SIMPLEX, 2.8, (255, 255, 255) if value == current else (80, 60, 30), 9)
    return Scene(tokens, image)


class StandardRankTests(unittest.TestCase):
    def test_reads_highlight_not_first_visible_value_and_stops_at_target(self):
        state = rank_page(49)
        self.assertEqual(selected_rank(state), 49)
        self.assertEqual(rank_target(state)[0], 48)
        state = rank_page(40, (41, 40, 39))
        self.assertEqual(selected_rank(state), 40)
        self.assertIsNone(rank_target(state))

    def test_below_target_moves_up_without_overshooting(self):
        state = rank_page(39, (40, 39, 38))
        self.assertEqual(rank_target(state)[0], 40)

    def test_no_current_image_or_no_highlight_is_not_selected(self):
        state = rank_page()
        for image in (None, np.zeros_like(state.image)):
            state.image = image
            with self.assertRaises(AutomationError):
                selected_rank(state)

    def test_white_numeral_and_unique_background_both_required(self):
        state = rank_page()
        state.image[round(.35*1080):round(.43*1080), round(.12*1920):round(.18*1920)] = (230, 130, 80)
        with self.assertRaises(AutomationError):
            selected_rank(state)
        state = rank_page()
        extra = rank_page(49)
        state.image[round(.49*1080):round(.65*1080)] = extra.image[round(.49*1080):round(.65*1080)]
        with self.assertRaises(AutomationError):
            selected_rank(state)

    def test_unknown_misaligned_duplicate_and_low_confidence_numbers_stop(self):
        for values in ((50, 48, 47), (50, 50, 49), ()):
            with self.assertRaises(AutomationError):
                visible_ranks(rank_page(values=values))
        state = rank_page()
        state.tokens[-2] = replace(state.tokens[-2], score=.2)
        with self.assertRaises(AutomationError):
            visible_ranks(state)

    def test_standard_page_anchors_required_and_overclock_rejected(self):
        state = rank_page()
        self.assertTrue(difficulty_page(state))
        for index in range(5):
            modified = Scene(state.tokens[:index]+state.tokens[index+1:], state.image)
            self.assertFalse(difficulty_page(modified))
        state.tokens[1] = replace(state.tokens[1], text='超频博弈')
        self.assertFalse(difficulty_page(state))

    def test_navigation_scope_cannot_click_start_or_use_unselected_rank_as_target(self):
        c = SimpleNamespace(settings=Settings(), runner=SimpleNamespace(currency_configure=True))
        state = rank_page(50)
        action = next_action(state, c)
        self.assertEqual(action.intent, 'select_rank_48')
        self.assertEqual(action.target.text, '48')
        self.assertNotEqual(action.target.text, '开始对局')
        c.runner.currency_configure = False
        with self.assertRaises(AutomationError):
            next_action(state, c)

    def test_missing_selected_digit_uses_two_agreeing_local_ocr_variants(self):
        state = rank_page(47, (47, 46, 45))
        state.tokens = [t for t in state.tokens if t.text != '47']
        reader = Mock()
        reader.read_number.return_value = Token('47', .99, (0, 0, 1, 1))
        result = supplement_rank(state, reader)
        self.assertEqual(reader.read_number.call_count, 2)
        self.assertTrue(any(t.text == '47' for t in result.tokens))
        self.assertFalse(any(t.text == '47' for t in state.tokens))
        for fields in ([Token('47', .99, (0, 0, 1, 1)), Token('48', .99, (0, 0, 1, 1))],
                       [None, Token('47', .99, (0, 0, 1, 1))],
                       [Token('47', .5, (0, 0, 1, 1))]*2):
            reader.read_number.side_effect = fields
            self.assertIs(supplement_rank(state, reader), state)

    def test_existing_number_or_foreign_page_never_triggers_local_ocr(self):
        reader = Mock()
        self.assertIsNotNone(supplement_rank(rank_page(), reader))
        state = rank_page()
        state.tokens[1] = replace(state.tokens[1], text='超频博弈')
        self.assertIs(supplement_rank(state, reader), state)
        reader.read_number.assert_not_called()


if __name__ == '__main__':
    unittest.main()
