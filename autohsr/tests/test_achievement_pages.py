from unittest import TestCase

import cv2
import numpy as np

from autohsr.achievement_pages import (
    AchievementListObservation, achievement_bulk_claim_visible, achievement_bulk_receipt_visible,
    achievement_overview, observe_achievement_list, observe_achievement_screen,
)
from autohsr.models import Scene, Token


def label(text, x, y, score=.99):
    return Token(text, score, (x - .014, y - .009, x + .014, y + .009))


def overview():
    return [label('成就', .068, .062), label('达成成就', .373, .878),
            label('众秘探奇', .225, .624), label('我，开拓者', .355, .632),
            label('通往群星的轨道', .487, .642), label('战意奔涌', .618, .634),
            label('流光遗痕', .748, .625)]


def category_view(category='与你同行的回忆', *, x=.08, search_x=.89):
    return [Token('成就', .99, (.052, .046, .083, .078)),
            Token(category, .99, (x, .113, x + .12, .149)),
            Token('成就进度 675/677', .99, (x, .150, x + .10, .179)),
            label('搜索', search_x, .920)]


def gold_controls(*buttons):
    frame = np.full((720, 1280, 3), 100, dtype=np.uint8)
    for button in buttons:
        x, y = button.center
        frame[round((y-.020)*720):round((y+.020)*720),
              round((x-.040)*1280):round((x+.040)*1280)] = (79, 196, 250)
    return frame


def receipt_rows(*titles):
    frame = gold_controls()
    for title in titles:
        y = title.center[1]
        frame[round((y - .022) * 720):round((y + .045) * 720), round(.08 * 1280):round(.92 * 1280)] = 232
    return frame


def scrolled_receipt_rows(titles, checks, *, mark='check', offset=0):
    frame = gold_controls()
    for index, title in enumerate(titles):
        y = round(title.center[1] * 720) + 24
        frame[y-47:y+47, 100:1180] = 224
        if index in checks:
            x = 1116 + offset
            cv2.ellipse(frame, (x, y), (18, 17), 0, 0, 320, (111, 111, 111), 2, cv2.LINE_AA)
            if mark == 'check':
                points = np.array([(x-8, y-1), (x-2, y+7), (x+12, y-11)], dtype=np.int32)
                cv2.polylines(frame, [points], False, (111, 111, 111), 4, cv2.LINE_AA)
    return frame


class AchievementOverviewTests(TestCase):
    def test_category_carousel_accepts_partial_scroll_and_small_vertical_animation(self):
        self.assertTrue(achievement_overview(Scene(overview())))
        frame = overview()[:5]
        frame[2] = label('众秘探奇', .159, .601)
        self.assertTrue(achievement_overview(Scene(frame)))

    def test_similar_titles_or_incomplete_footer_do_not_confirm_the_overview(self):
        correct = overview()
        for tokens in (correct[:1], correct[:2], correct[1:], correct[:1] + correct[2:],
                       correct[:4], [*correct, label('取消', .53, .68)],
                       [*correct, label('开拓等级 70', .70, .22)],
                       [*correct, label('战意奔涌', .55, .634, score=.73)],
                       correct[:2] + [label('众秘探奇', .35, .601), label('我，开拓者', .35, .631),
                                      label('通往群星的轨道', .35, .655)]):
            with self.subTest(tokens=tokens):
                self.assertFalse(achievement_overview(Scene(tokens)))

    def test_bulk_claim_requires_overview_and_gold_at_the_full_label(self):
        button = label('一键领取奖励', .824, .897)
        image = gold_controls(button)
        self.assertTrue(achievement_bulk_claim_visible(Scene([*overview(), button], image)))
        self.assertTrue(achievement_bulk_claim_visible(Scene([*overview(), label('键领取奖励', .824, .897)], image)))
        for tokens, pixels in (([*category_view(), button], image),
                               ([*overview(), button], None),
                               ([*overview(), label('一键领取', .824, .897)], image),
                               ([*overview(), button, label('获得物品', .50, .15, score=.71)], image)):
            with self.subTest(tokens=tokens):
                self.assertFalse(achievement_bulk_claim_visible(Scene(tokens, pixels)))

    def test_duplicate_bulk_variants_keep_button_unknown_at_collection_floor(self):
        button = label('一键领取奖励', .824, .897)
        image = gold_controls(button)
        for duplicate in (label('键领取奖励', .840, .897, score=.74),
                          label('一键领取奖励', .854, .897),
                          label('一键领取奖励', .696, .897, score=.70)):
            scene = Scene([*overview(), button, duplicate], image)
            self.assertTrue(achievement_overview(scene))
            self.assertFalse(achievement_bulk_claim_visible(scene))


class AchievementListTests(TestCase):
    def test_category_header_and_search_identify_list_during_scroll(self):
        for frame, rows in ((category_view(), [label('领取', .924, .286)]),
                            (category_view(x=.124, search_x=.84),
                             [label('领取', .876, y) for y in (.274, .454, .638, .822)]),
                            (category_view('众秘探奇'), [label('领取', .91, .575)])):
            with self.subTest(frame=frame, rows=rows):
                scene = Scene(frame + rows, gold_controls(*rows))
                self.assertEqual(observe_achievement_list(scene), AchievementListObservation(frame[1].text, True))
                self.assertFalse(achievement_overview(scene))

    def test_completed_progress_and_unverified_controls_leave_claim_unknown(self):
        view = [*category_view(), label('0/1', .915, .432), label('34/40', .915, .577),
                label('已完成', .915, .706), label('2023-05-01', .915, .742)]
        for button, image in ((label('领取', .924, .286), None),
                              (label('领取', .924, .286), gold_controls()),
                              (label('领取', .924, .286, score=.72), gold_controls(label('领取', .924, .286))),
                              (label('领取', .78, .286), gold_controls(label('领取', .78, .286))),
                              (label('领取', .924, .907), gold_controls(label('领取', .924, .907)))):
            with self.subTest(button=button, image=image is not None):
                self.assertEqual(observe_achievement_list(Scene([*view, button], image)),
                                 AchievementListObservation('与你同行的回忆', False))

    def test_overview_unrelated_rewards_and_modal_do_not_confirm_list(self):
        view = category_view()
        button = label('领取', .875, .371)
        for frame in (overview(), [view[0], view[1], view[3]],
                      [view[0], view[1], label('675/677', .14, .17), view[3]],
                      [view[0], view[1], view[2], label('搜索', .40, .920)],
                      [view[0], view[1], Token('成就进度 1/2', .99, (.166, .15, .266, .179)), view[3]],
                      [*view, label('取消', .54, .66, score=.70)],
                      [*view, label('获得物品', .50, .151, score=.70)],
                      [label('获得物品', .50, .216), label('星琼', .40, .59), label('点击空白处关闭', .50, .79)]):
            with self.subTest(frame=frame):
                self.assertIsNone(observe_achievement_list(Scene([*frame, button], gold_controls(button))))

    def test_weak_same_row_state_does_not_poison_independent_available_rows(self):
        view = category_view()
        button = label('领取', .910, .572)
        other = label('领取', .905, .356)
        for text in ('领取', '已完成', '已领取', '0/1'):
            conflict = label(text, .914, .573, score=.74)
            with self.subTest(text=text):
                self.assertEqual(observe_achievement_list(Scene([*view, button, conflict], gold_controls(button))),
                                 AchievementListObservation(view[1].text, False))
                self.assertEqual(observe_achievement_list(Scene([*view, button, conflict, other],
                                                                   gold_controls(button, other))),
                                 AchievementListObservation(view[1].text, True))

    def test_same_slot_weak_headings_and_inconsistent_progress_do_not_verify_category(self):
        view = category_view()
        button = label('领取', .910, .572)
        for duplicate in (Token('众秘探奇', .74, (.09, .113, .18, .149)),
                          label('成就', .089, .068, score=.74),
                          label('搜索', .85, .911, score=.74),
                          Token('成就进度 671/677', .74, (.09, .151, .18, .18))):
            with self.subTest(duplicate=duplicate):
                self.assertIsNone(observe_achievement_list(Scene([*view, duplicate, button], gold_controls(button))))
        for progress in ('675/67', '0/0'):
            with self.subTest(progress=progress):
                damaged = [*view[:2], Token(f'成就进度 {progress}', .99, view[2].box), view[3], button]
                self.assertIsNone(observe_achievement_list(Scene(damaged, gold_controls(button))))


class AchievementReceiptTests(TestCase):
    def test_bulk_receipt_has_independent_title_category_and_footer(self):
        header = [label('成就奖励', .50, .114), label('与你同行的回忆', .127, .193)]
        footer = [label('总计获得', .467, .838), label('确认', .502, .926)]
        rows = [label('东山再起', .176, .258), label('超大杯', .166, .408), label('星辰的鼓动即是爱', .203, .558)]
        for row_count in (1, 2, 3):
            with self.subTest(row_count=row_count):
                visible = rows[:row_count]
                self.assertTrue(achievement_bulk_receipt_visible(Scene([*header, *visible, *footer], receipt_rows(*visible))))
        other = label('众秘探奇', .129, .490)
        self.assertTrue(achievement_bulk_receipt_visible(Scene([*header, *rows, other, *footer], receipt_rows(*rows))))

    def test_title_animation_partial_receipt_and_generic_feedback_do_not_verify(self):
        title = label('成就奖励', .50, .114)
        category = label('与你同行的回忆', .127, .193)
        total = label('总计获得', .467, .838)
        confirm = label('确认', .502, .926)
        row = label('东山再起', .176, .258)
        for frame in ([label('成就奖励', .50, .418)], [title, category], [title, category, total],
                      [title, total, confirm], [title, category, total, label('确认', .50, .68)],
                      [label('获得物品', .50, .162), label('星琼', .50, .58), label('点击空白处关闭', .50, .73)],
                      [title, category, total, confirm, row, label('获得物品', .50, .15, score=.69)]):
            with self.subTest(frame=frame):
                self.assertFalse(achievement_bulk_receipt_visible(Scene(frame, receipt_rows(row))))

    def test_receipt_requires_visible_detail_and_unique_controls(self):
        row = label('东山再起', .176, .258)
        anchors = [label('成就奖励', .50, .114), label('与你同行的回忆', .127, .193),
                   label('总计获得', .467, .838), label('确认', .502, .926)]
        image = receipt_rows(row)
        for tokens, pixels in ((anchors, image), ([*anchors, row], gold_controls()),
                               ([*anchors, row, label('成就奖励', .515, .113, score=.73)], image),
                               ([*anchors, row, label('众秘探奇', .136, .192, score=.73)], image),
                               ([*anchors, row, label('确认', .561, .929, score=.71)], image),
                               ([*anchors, row, label('取消', .561, .929, score=.71)], image)):
            with self.subTest(tokens=tokens):
                self.assertFalse(achievement_bulk_receipt_visible(Scene(tokens, pixels)))

    def test_scrolled_receipt_needs_two_separate_same_row_checkmarks(self):
        anchors = [label('成就奖励', .50, .114), label('总计获得', .467, .838), label('确认', .502, .926)]
        rows = [label('东山再起', .176, .206), label('超大杯', .166, .356)]
        clean = scrolled_receipt_rows(rows, (0, 1))
        scene = Scene([*anchors, *rows], clean)
        self.assertEqual(observe_achievement_screen(scene, .85), ('achievement_receipt', None, None))
        for rejected in (Scene([*anchors, *rows], scrolled_receipt_rows(rows, (0,))),
                         Scene([*anchors, *rows], scrolled_receipt_rows(rows, (0, 1), mark='ring')),
                         Scene([*anchors, *rows], scrolled_receipt_rows(rows, (0, 1), offset=30)),
                         Scene([*anchors, rows[0], label('另一行文字', .177, .224)], clean)):
            self.assertIsNone(observe_achievement_screen(rejected, .85))

    def test_scrolled_receipt_still_requires_unique_anchors_and_clean_page(self):
        title = label('成就奖励', .50, .114)
        total = label('总计获得', .467, .838)
        confirm = label('确认', .502, .926)
        rows = [label('东山再起', .176, .206), label('超大杯', .166, .356)]
        clean = scrolled_receipt_rows(rows, (0, 1))
        for tokens in ((title, confirm), (title, total),
                       (title, total, confirm, label('确认', .546, .926, score=.74)),
                       (title, total, confirm, label('与你同行的回忆', .132, .178, score=.74)),
                       (title, total, confirm, label('获得物品', .50, .15, score=.74)),
                       (title, total, confirm, label('点击空白处关闭', .50, .74, score=.74))):
            with self.subTest(tokens=tokens):
                self.assertIsNone(observe_achievement_screen(Scene([*tokens, *rows], clean), .85))
