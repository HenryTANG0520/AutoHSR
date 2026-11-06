"""Phone entry evidence from the tracked redacted layout and targeted contrasts."""
from dataclasses import replace
import time
import unittest

from autohsr.models import Token
from autohsr.team_calibration_pages import phone_team_target
from autohsr.tests.test_du_team import fixture


def _phone():
    scene = fixture('phone_mail_icon')
    return replace(scene, captured_at=time.monotonic())


def _change(scene, label, **fields):
    tokens = [replace(token, **fields) if token.text == label else token for token in scene.tokens]
    return replace(scene, tokens=tokens)


def _shift(token, dx, dy):
    left, top, right, bottom = token.box
    return replace(token, box=(left + dx, top + dy, right + dx, bottom + dy))


class PhoneTeamTargetTests(unittest.TestCase):
    def test_real_phone_grid_returns_original_token(self):
        scene = _phone()
        original = next(token for token in scene.tokens if token.text == '编队')
        self.assertIs(phone_team_target(scene), original)

    def test_small_shared_layout_shift_and_separate_level_number_are_supported(self):
        scene = _phone()
        labels = ('开拓等级70', '指南', '编队', '背包', '任务')
        shifted = [
            _shift(token, .004, -.004) if token.text in labels else token
            for token in scene.tokens
        ]
        moved = _change(replace(scene, tokens=shifted), '开拓等级70',
                        text='开拓等级', box=(.674, .227, .719, .252))
        moved.tokens.append(Token('70', .99, (.722, .227, .740, .252)))
        original = next(token for token in moved.tokens if token.text == '编队')
        self.assertIs(phone_team_target(moved), original)

    def test_target_uses_the_stronger_of_the_configured_and_fixed_thresholds(self):
        scene = _phone()
        self.assertIsNone(phone_team_target(_change(scene, '编队', score=.849), .4))
        self.assertIsNotNone(phone_team_target(_change(scene, '编队', score=.85), .4))
        self.assertIsNone(phone_team_target(_change(scene, '编队', score=.949), .95))
        self.assertIsNotNone(phone_team_target(_change(scene, '编队', score=.95), .95))

    def test_second_candidate_at_collection_floor_blocks_even_outside_target_slot(self):
        scene = _phone()
        for box in ((.688, .846, .710, .869), (.22, .07, .244, .094)):
            with self.subTest(box=box):
                duplicate = Token('编队', .65, box)
                self.assertIsNone(phone_team_target(replace(scene, tokens=[*scene.tokens, duplicate]), .95))
        noise = Token('编队', .649, (.22, .07, .244, .094))
        self.assertIsNotNone(phone_team_target(replace(scene, tokens=[*scene.tokens, noise]), .95))

    def test_partial_or_extra_text_does_not_establish_the_caption(self):
        scene = _phone()
        for text in ('编', '队', '编队!', '编队预设', '前往编队'):
            with self.subTest(text=text):
                self.assertIsNone(phone_team_target(_change(scene, '编队', text=text)))
        fragment = Token('队', .65, (.705, .848, .713, .869))
        self.assertIsNone(phone_team_target(replace(scene, tokens=[*scene.tokens, fragment])))

    def test_clipped_or_too_narrow_box_cannot_use_a_center_match(self):
        scene = _phone()
        for box in ((.670, .845, .715, .869), (.690, .845, .697, .869)):
            with self.subTest(box=box):
                self.assertIsNone(phone_team_target(_change(scene, '编队', box=box)))

    def test_each_anchor_must_be_present_and_strong(self):
        scene = _phone()
        for label in ('开拓等级70', '指南', '背包', '任务'):
            with self.subTest(label=label):
                missing = replace(scene, tokens=[token for token in scene.tokens if token.text != label])
                self.assertIsNone(phone_team_target(missing))
                self.assertIsNone(phone_team_target(_change(scene, label, score=.84)))

    def test_same_grid_cells_still_require_correct_column_row_and_spacing(self):
        scene = _phone()
        for shifts in (
            {'指南': (-.006, 0), '编队': (.009, 0)},
            {'背包': (0, -.011), '任务': (0, .010)},
            {'编队': (.009, 0), '背包': (-.008, 0)},
        ):
            with self.subTest(shifts=shifts):
                changed = [
                    _shift(token, *shifts[token.text]) if token.text in shifts else token
                    for token in scene.tokens
                ]
                self.assertIsNone(phone_team_target(replace(scene, tokens=changed)))

    def test_wrong_page_and_weak_popup_win_over_the_visible_background(self):
        scene = _phone()
        for text in ('预设编队', '角色列表', '生存索引', '提示', '取消', '确认切换', '是否确认修改编队'):
            with self.subTest(text=text):
                popup = Token(text, .65, (.4, .4, .54, .44))
                self.assertIsNone(phone_team_target(replace(scene, tokens=[*scene.tokens, popup]), .95))

    def test_stale_or_incomplete_scene_is_rejected(self):
        scene = _phone()
        self.assertIsNone(phone_team_target(replace(scene, captured_at=time.monotonic() - 9)))
        self.assertIsNone(phone_team_target(replace(scene, image=None)))


if __name__ == '__main__':
    unittest.main()
