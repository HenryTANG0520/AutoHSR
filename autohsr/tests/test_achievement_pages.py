from unittest import TestCase

from autohsr.achievement_pages import achievement_overview
from autohsr.models import Scene, Token


def label(text, x, y, score=.99):
    return Token(text, score, (x - .014, y - .009, x + .014, y + .009))


def overview():
    return [label('成就', .068, .062), label('达成成就', .373, .878),
            label('众秘探奇', .225, .624), label('我，开拓者', .355, .632),
            label('通往群星的轨道', .487, .642), label('战意奔涌', .618, .634),
            label('流光遗痕', .748, .625)]


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
