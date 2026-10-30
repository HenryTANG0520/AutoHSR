"""Synthetic UI compositions using the five original upstream control crops.

The OCR tokens are explicit synthetic observations; these scenes validate the
contracts and their counterexamples, not a real full-form calibration.
"""
from copy import deepcopy
import time
import unittest

import cv2
import numpy as np

from autohsr.models import Scene, Token
from autohsr.redemption_pages import (FIELD_KEY, _template, field_region, phone, phone_more_target,
                                     read_form, read_result, redemption_entry)


def token(text, box, score=.99):
    return Token(text, score, tuple(v / (1920 if i % 2 == 0 else 1080) for i, v in enumerate(box)))


def stamp(image, name, x, y, *, dim=1):
    source = _template(name)
    if source is None:
        raise AssertionError('Missing or changed original redemption crop: ' + name)
    source = source.copy()
    h, w = source.shape[:2]
    color = source[:, :, :3].astype(float)
    if source.shape[2] == 4:
        alpha = source[:, :, 3:4].astype(float) / 255
        color = color * alpha + image[y:y + h, x:x + w].astype(float) * (1 - alpha)
    image[y:y + h, x:x + w] = np.clip(color * dim, 0, 255).astype(np.uint8)
    return (x, y, x + w, y + h)


def base_scene():
    return Scene([], np.full((1080, 1920, 3), 70, np.uint8), captured_at=time.monotonic() - .1)


def phone_scene():
    scene = base_scene()
    scene.tokens = [token('开拓等级', (1340, 110, 1450, 145)), token('指南', (1340, 470, 1410, 505)),
                    token('委托', (1560, 470, 1630, 505)), token('无名勋礼', (1340, 600, 1480, 635))]
    stamp(scene.image, 'more', 1790, 104)
    return scene


def more_scene():
    scene = phone_scene()
    scene.tokens += [token('漫游签证', (1510, 215, 1660, 250)), token('兑换码', (1510, 305, 1630, 340))]
    return scene


def form_scene(code=None, *, echo=True, empty=None, disabled=False):
    scene = base_scene()
    stamp(scene.image, 'title', 900, 300)
    scene.tokens = [token('兑换码', (907, 307, 1000, 342)), token('取消', (710, 608, 765, 634)),
                    token('确认', (1152, 608, 1197, 631))]
    # A closed current input field. Geometry is recovered from its actual
    # connected background, not from these fixture coordinates at runtime.
    scene.image[430:500, 560:1360] = 246
    stamp(scene.image, 'paste' if code is None else 'clear', 1310, 452)
    stamp(scene.image, 'confirm', 1110, 605, dim=.45 if disabled else 1)
    empty = code is None if empty is None else empty
    if empty:
        scene.tokens.append(token('请输入兑换码', (600, 450, 840, 480)))
        cv2.putText(scene.image, 'placeholder', (600, 477), cv2.FONT_HERSHEY_SIMPLEX, .7, (80, 80, 80), 1)
    elif code is not None:
        scene.tokens.append(token(code, (600, 450, 1000, 480)))
        cv2.putText(scene.image, 'synthetic-code', (600, 477), cv2.FONT_HERSHEY_SIMPLEX, .7, (18, 18, 18), 1)
    if code is not None and echo:
        roi = field_region(scene)
        if roi is None:
            raise AssertionError('Synthetic form did not satisfy actual page geometry')
        scene.field_reads[FIELD_KEY] = (Token(code, .99, roi), Token(code, .99, roi))
    return scene


def result_scene(status='redeemed', *, inline=False):
    labels = dict(redeemed='兑换成功', expired='兑换码已过期', invalid='无效的兑换码', already_used='兑换码已被使用')
    if inline:
        scene = form_scene('AbC2026中文')
        scene.tokens.append(token(labels[status], (760, 535, 1130, 570)))
        return scene
    scene = base_scene()
    stamp(scene.image, 'confirm', 940, 605)
    scene.tokens = [token('确认', (982, 608, 1028, 631))]
    if status == 'redeemed':
        scene.tokens += [token('兑换成功', (900, 320, 1040, 360)),
                         token('奖励已通过游戏内邮件发放，请注意查收', (690, 425, 1240, 465))]
    else:
        scene.tokens += [token('提示', (920, 320, 1000, 360)),
                         token(labels[status], (790, 425, 1130, 465))]
    return scene


class RedemptionPagesTests(unittest.TestCase):
    def test_phone_more_requires_phone_and_unique_original_graphic(self):
        scene = phone_scene()
        self.assertTrue(phone(scene))
        self.assertIsNotNone(phone_more_target(scene))
        duplicate = deepcopy(scene); stamp(duplicate.image, 'more', 1690, 104)
        self.assertIsNone(phone_more_target(duplicate))
        no_phone = deepcopy(scene); no_phone.tokens = []
        self.assertIsNone(phone_more_target(no_phone))

    def test_more_menu_entry_requires_neighbor_and_current_phone_menu(self):
        self.assertEqual(redemption_entry(more_scene()).text, '兑换码')
        for label in ('漫游签证', '指南', '委托'):
            scene = more_scene(); scene.tokens = [t for t in scene.tokens if t.text != label]
            if label != '漫游签证':
                scene.tokens = [t for t in scene.tokens if t.text != '无名勋礼']
            with self.subTest(label=label):
                self.assertIsNone(redemption_entry(scene))
        self.assertIsNone(redemption_entry(form_scene()))

    def test_geometry_is_current_field_and_empty_requires_placeholder(self):
        scene = form_scene()
        form = read_form(scene)
        self.assertIsNotNone(form)
        self.assertEqual(form.field_roi, field_region(scene))
        self.assertTrue(form.empty)
        self.assertIsNone(form.current_code)
        self.assertIsNone(form.confirm_target)
        unknown = form_scene('AbC', echo=False)
        form = read_form(unknown)
        self.assertFalse(form.empty)
        self.assertIsNone(form.current_code)
        self.assertIsNone(form.confirm_target)

    def test_exact_independent_field_echo_preserves_case_and_chinese(self):
        for code in ('AbCd1234', 'aBcD1234', '星穹铁道2026', '中AbC文2'):
            scene = form_scene(code)
            form = read_form(scene)
            with self.subTest(code=code):
                self.assertEqual(form.current_code, code)
                self.assertFalse(form.empty)
                self.assertIsNotNone(form.confirm_target)
                self.assertEqual(form.basis['page'], 'redemption_form')
                self.assertNotIn(code, str(form.basis))

    def test_whole_page_code_clear_or_one_field_read_never_proves_full_echo(self):
        scene = form_scene('AbC2026', echo=False)
        self.assertIsNone(read_form(scene).current_code)
        roi = field_region(scene)
        scene.field_reads[FIELD_KEY] = (Token('AbC2026', .99, roi), None)
        self.assertIsNone(read_form(scene).current_code)
        scene.field_reads[FIELD_KEY] = (Token('AbC2026', .99, roi),)
        self.assertIsNone(read_form(scene).current_code)

    def test_disagreement_wrong_roi_low_confidence_and_truncated_text_are_unknown(self):
        for case in ('case_mismatch', 'partial', 'wrong_roi', 'low_score', 'ellipsis'):
            scene = form_scene('AbC2026')
            roi = field_region(scene)
            if case == 'case_mismatch':
                scene.field_reads[FIELD_KEY] = (Token('AbC2026', .99, roi), Token('ABC2026', .99, roi))
            elif case == 'partial':
                scene.field_reads[FIELD_KEY] = (Token('AbC', .99, roi), Token('AbC', .99, roi))
            elif case == 'wrong_roi':
                scene.field_reads[FIELD_KEY] = (Token('AbC2026', .99, (0, 0, 1, 1)),) * 2
            elif case == 'low_score':
                scene.field_reads[FIELD_KEY] = (Token('AbC2026', .60, roi),) * 2
            else:
                scene.tokens.append(token('…', (1200, 450, 1220, 480)))
            with self.subTest(case=case):
                form = read_form(scene)
                self.assertIsNone(form.current_code)
                self.assertIsNone(form.confirm_target)

    def test_control_characters_and_injection_strings_are_not_field_codes(self):
        for code in ('AbC\n123', 'AbC\t123', '$(fake)', 'A;B', ' A123', 'A123 ', 'A' * 65):
            scene = form_scene('AbC2026', echo=False)
            roi = field_region(scene)
            scene.field_reads[FIELD_KEY] = (Token(code, .99, roi), Token(code, .99, roi))
            with self.subTest(code=code):
                self.assertIsNone(read_form(scene).current_code)

    def test_nonfinite_or_malformed_field_boxes_do_not_become_code_evidence(self):
        for box in ((float('nan'), .1, .8, .5), (.1, .2, .3), ('bad', .1, .8, .5)):
            scene = form_scene('AbC2026', echo=False)
            scene.field_reads[FIELD_KEY] = (Token('AbC2026', .99, box),) * 2
            with self.subTest(box=box):
                self.assertIsNone(read_form(scene).current_code)

    def test_missing_shell_anchor_duplicate_field_or_both_icons_does_not_guess(self):
        for case in ('title', 'cancel', 'confirm', 'no_graphic', 'both_icons', 'open_background'):
            scene = form_scene()
            if case in ('title', 'cancel', 'confirm'):
                label = dict(title='兑换码', cancel='取消', confirm='确认')[case]
                scene.tokens = [t for t in scene.tokens if t.text != label]
            elif case == 'no_graphic':
                scene.image[300:348, 900:1007] = 70
            elif case == 'both_icons':
                stamp(scene.image, 'clear', 1230, 452)
            else:
                scene.image[370:605, 96:1820] = 246
                stamp(scene.image, 'paste', 1310, 452)
            with self.subTest(case=case):
                self.assertIsNone(field_region(scene))
                self.assertIsNone(read_form(scene))

    def test_disabled_or_occluded_confirm_is_not_a_submit_target(self):
        scene = form_scene('AbC2026', disabled=True)
        self.assertEqual(read_form(scene).current_code, 'AbC2026')
        self.assertIsNone(read_form(scene).confirm_target)
        scene = form_scene('AbC2026')
        scene.image[605:634, 1110:1155] = 70
        self.assertIsNone(read_form(scene).confirm_target)

    def test_payment_overlay_stale_animation_and_no_image_override_visible_form(self):
        for case in ('payment', 'stale', 'no_image', 'low_title'):
            scene = form_scene('AbC2026')
            if case == 'payment':
                scene.tokens.append(token('确认购买并支付', (820, 380, 1110, 420)))
            elif case == 'stale':
                scene.captured_at -= 20
            elif case == 'no_image':
                scene.image = None
            else:
                scene.tokens = [Token(t.text, .2, t.box) if t.text == '兑换码' else t for t in scene.tokens]
            with self.subTest(case=case):
                self.assertIsNone(read_form(scene))
                self.assertEqual(read_result(scene).status, 'unknown')

    def test_four_exact_standalone_results_require_independent_modal_composition(self):
        for status in ('redeemed', 'expired', 'invalid', 'already_used'):
            result = read_result(result_scene(status))
            with self.subTest(status=status):
                self.assertEqual(result.status, status)
                self.assertIsNotNone(result.close_target)
                self.assertIsNone(result.key)

    def test_inline_errors_only_allow_esc_never_the_form_submit_button(self):
        for status in ('expired', 'invalid', 'already_used'):
            result = read_result(result_scene(status, inline=True))
            with self.subTest(status=status):
                self.assertEqual(result.status, status)
                self.assertEqual(result.key, 'esc')
                self.assertIsNone(result.close_target)

    def test_static_success_generic_confirm_partial_or_conflicting_result_is_unknown(self):
        for case in ('no_mail', 'only_word', 'question', 'partial', 'conflict', 'no_title'):
            scene = result_scene()
            if case == 'no_mail':
                scene.tokens = [t for t in scene.tokens if not t.text.startswith('奖励')]
            elif case == 'only_word':
                scene.tokens = [t for t in scene.tokens if t.text == '兑换成功']
            elif case in ('question', 'partial'):
                scene.tokens = [Token('兑换成功?' if case == 'question' else '兑换成', t.score, t.box)
                                if t.text == '兑换成功' else t for t in scene.tokens]
            elif case == 'conflict':
                scene.tokens.append(token('兑换码已过期', (850, 510, 1140, 550)))
            else:
                scene = result_scene('invalid'); scene.tokens = [t for t in scene.tokens if t.text != '提示']
            with self.subTest(case=case):
                self.assertEqual(read_result(scene).status, 'unknown')

    def test_plain_form_and_phone_have_no_terminal_result(self):
        self.assertEqual(read_result(form_scene('AbC2026')).status, 'unknown')
        self.assertEqual(read_result(phone_scene()).status, 'unknown')


if __name__ == '__main__':
    unittest.main()
